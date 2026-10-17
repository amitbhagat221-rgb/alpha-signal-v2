"""The /macro page (plan 0028): assembled from desk_snapshots for any as-of date; the written note carries no figures."""
import sqlite3
from pathlib import Path

import pytest

import db
from cockpit import macro
from output import desk_archive as A
from output import macro_desk

SCHEMA = Path(__file__).resolve().parents[1] / "schema.sql"
BRIEF = {"data_date": "2026-10-04", "brent": 96.3, "brent_3m": 24.9, "oil": "amber", "us10y": 4.78, "us_3m_bps": 25, "us": "amber",
         "usdinr": 94.49, "vix": 10.7, "fii20": -9159, "dii20": 69074, "flows": "green", "fii_long": 11.1, "fii_long_pct": 10,
         "rbi": "amber", "rbi_text": "On hold", "rbi_set": "2026-09-06", "regime": "Reflation", "regime_month": "2026-07", "nifty": 24100.5}
CHAPTER = ('<article class="chapter tr-in" data-view="in-4"><div class="asof-banner" hidden>old</div>'
           '<p>See <a class="ind h" href="/sectors?industry=Banks#per-sector">Banks</a> and <a href="#in-5">oil</a>.</p></article>')
NOTE = {"title": "The squeeze continues", "verdict": "Oil and US yields press from outside.",
        "winners": [["Defence", "policy priority", "gl-7"]], "losers": [["FMCG", "oil shocks hurt", "in-5"]],
        "coming": [["Mid-November", "CPI for October."]]}


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    c = sqlite3.connect(path)
    ddl = SCHEMA.read_text()
    start = ddl.index("CREATE TABLE IF NOT EXISTS desk_snapshots")
    c.executescript(ddl[start:ddl.index(";", ddl.index("CREATE INDEX IF NOT EXISTS idx_desk_snapshots_part")) + 1])
    A.save("brief", BRIEF, "2026-10-05", method="retrospective", conn=c)
    A.save("brief", {**BRIEF, "oil": "red", "rbi": "red", "data_date": "2026-10-16",
                     "movers": [{"id": "nifty_it", "label": "Nifty IT", "value": 1.0, "chg": 3.9, "z": 2.4, "unit": "%",
                                 "reads": ["IT Services & ITeS"]}]}, "2026-10-17", conn=c)
    A.save("brief_note", NOTE, "2026-10-17", method="manual", conn=c)
    A.save("chapter", {"title": "The RBI's three levers", "track": "India", "html": CHAPTER}, "2026-10-17", item="in-4", method="manual", conn=c)
    A.save("hotspots", {"rows": [["Iran war and Hormuz", "escalating"]]}, "2026-10-17", method="manual", conn=c)
    c.commit()
    c.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def test_page_today_has_the_note_the_change_and_cockpit_links_leave_the_frame(desk):
    m = macro.page()
    assert m["is_latest"] and m["brief"]["date"] == "2026-10-17" and m["note"]["date"] == "2026-10-17"
    oil = next(l for l in m["lights"] if l["key"] == "oil")
    assert oil["colour"] == "red" and oil["was"] == "amber" and oil["was_date"] == "2026-10-05"
    html = m["chapters"][0]["html"]
    assert 'target="_top" class="ind h" href="/sectors' in html and '<a href="#in-5">' in html   # only cockpit links
    assert "asof-banner" not in html                                                             # current version: no banner


def test_page_as_of_a_past_date_shows_that_brief_and_flags_later_versions(desk):
    m = macro.page("2026-10-10")
    assert not m["is_latest"] and m["brief"]["date"] == "2026-10-05" and m["note"] is None
    assert m["chapters"][0]["early"] and "earliest archived version of this chapter is 2026-10-17" in m["chapters"][0]["html"]
    assert m["hot"]["early"] and m["dates"] == ["2026-10-17", "2026-10-05"]
    assert macro.page("not-a-date")["brief"]["date"] == "2026-10-17"


def test_frame_renders_for_today_and_the_past(desk):
    from cockpit.app import templates
    for as_of in (None, "2026-10-05"):
        html = templates.get_template("macro_frame.html").render(m=macro.page(as_of))
        assert 'data-view="today"' in html and 'data-view="archive"' in html and 'id="asof"' in html
    assert "The squeeze continues" in templates.get_template("macro_frame.html").render(m=macro.page())


def test_note_validator_rejects_figures():
    assert macro_desk.validate_note(NOTE) is NOTE
    with pytest.raises(ValueError, match="figures"):
        macro_desk.validate_note({**NOTE, "verdict": "Brent rose 4% today."})
    with pytest.raises(ValueError, match="missing"):
        macro_desk.validate_note({**NOTE, "coming": []})


def test_latest_all_falls_back_to_the_earliest_version(desk):
    c = sqlite3.connect(desk)
    A.save("chapter", {"title": "t", "track": "India", "html": CHAPTER + " "}, "2026-11-17", item="in-4", conn=c)
    assert A.latest_all("chapter", conn=c)["in-4"]["snapshot_date"] == "2026-11-17"
    assert A.latest_all("chapter", as_of="2026-10-20", conn=c)["in-4"]["snapshot_date"] == "2026-10-17"
    early = A.latest_all("chapter", as_of="2026-10-01", conn=c)["in-4"]
    assert early["snapshot_date"] == "2026-10-17" and early["early"]
    assert [d for d, _ in A.history("brief", conn=c)] == ["2026-10-05", "2026-10-17"]
