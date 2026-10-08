"""
The news editor (plan 0021) on a fresh schema-built DB: the daily edition reads raw
headlines once, files them under the fixed themes and writes three items; a theme
note is rewritten only when due and only under the page's writing rules (word caps,
short sentences, no numbers, whitelisted sectors); the weekly edition names sectors
from the whitelist; every kind undoes.
"""
import datetime as dt
import json

import pytest

import config
import db

TODAY = dt.date.today()


def day(n):
    return (TODAY - dt.timedelta(days=n)).isoformat()


TITLES = ["Oil climbs as supply tightens", "Crude rally lifts fuel costs", "Refiners brace for costlier crude",
          "Infosys wins a large deal", "Airlines flag fuel bill pressure", "Central bank holds rates steady",
          "Rupee slips against the dollar", "Chip plant gets state approval", "Startups test humanoid robots",
          "Robot makers raise fresh funding", "Monsoon ends on a wet note", "Cement prices firm up"]


@pytest.fixture
def ne(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "e.db")
    db.init_db()
    with db.get_db() as c:
        c.executemany("INSERT INTO news_articles (article_id, title, summary, source, published_at) "
                      "VALUES (?, ?, 'A short summary.', 'test', ?)",
                      [(f"a{i + 1}", t, day(1) + f"T05:{i:02d}:00") for i, t in enumerate(TITLES)])
        c.executemany("INSERT INTO stocks (sid, ticker, name, sector) VALUES (?, ?, ?, ?)",
                      [("ONGC", "ONGC", "ONGC", "Energy"), ("INDG", "INDIGO", "IndiGo", "Industrials"),
                       ("HDBK", "HDFCBANK", "HDFC Bank", "Financials"), ("INFY", "INFY", "Infosys", "Information Technology"),
                       ("TITN", "TITAN", "Titan", "Consumer Discretionary"), ("SUNP", "SUNPHARMA", "Sun Pharma", "Health Care")])
        c.execute("INSERT INTO news_article_stocks (article_id, sid) VALUES ('a1', 'ONGC')")
    from sources import news_editor
    return news_editor


def _ref(p, n):
    """ref of article a<n> in a daily payload (newest first)."""
    return p["_article_ids"].index(f"a{n}") + 1


def _today_result(p):
    oil = [_ref(p, n) for n in (1, 2, 3, 5)]
    return {"items": [{"headline": "Oil keeps climbing", "what": "Crude rose again as supply stayed tight.",
                       "so_what": "Fuel users face higher costs.", "theme": "oil_energy", "refs": oil[:2]},
                      {"headline": "Rates stay on hold", "what": "The central bank left rates unchanged.",
                       "so_what": "Borrowers get no relief yet.", "theme": "rates_dollar", "refs": [_ref(p, 6)]},
                      {"headline": "Robots draw fresh money", "what": "Robot makers raised new funding.",
                       "so_what": "An early sign for factory automation.", "theme": None, "refs": [_ref(p, 10)]}],
            "themes": {"oil_energy": oil, "rates_dollar": [_ref(p, 6), _ref(p, 7)], "ai_chips": [_ref(p, 8)]}}


NOTE = {"stands_now": "Crude is rising as supply stays tight.",
        "what_changed": "Refiners and airlines now warn about costs.",
        "why_it_matters": "India imports most of its oil. A costlier barrel lifts inflation.",
        "gains": ["Energy"], "loses": ["Industrials"],
        "portfolio_line": "Oil producers earn more. Heavy fuel users such as airlines earn less.",
        "what_to_watch": "The next producer meeting on output.",
        "next_if": ["If supply stays tight, then fuel users feel more pain.",
                    "If output rises, then the pressure on costs eases."],
        "story_so_far": "Crude began to rise when supply tightened. Fuel users then started to warn about costs."}


def _edition(ne):
    p = ne.today_payload(day(2), day(0))
    return p, ne.ingest_today(ne.validate_today(_today_result(p), p), p)


def test_daily_edition_reads_raw_headlines_once_and_files_them(ne):
    p, undo = _edition(ne)
    assert p["n_headlines"] == 12 and p["headlines"]["untrusted_text"].count("\n") == 11 and [t["id"] for t in p["themes"]] == [t[0] for t in config.NEWS_THEMES]
    ed = ne.today()
    assert ed["day"] == day(0) and len(ed["items"]) == 3 and ed["items"][0]["article_ids"] == ["a1", "a2"]
    assert db.scalar("SELECT COUNT(*) FROM news_theme_articles") == 12           # every headline read once
    assert db.scalar("SELECT COUNT(*) FROM news_theme_articles WHERE theme_id = 'oil_energy'") == 4
    assert ne.today_payload(day(2), day(0)) is None
    oil = next(t for t in ne.themes() if t["theme_id"] == "oil_energy")
    assert oil["n7"] == 4 and oil["heat"] == "Heating" and not oil["stands_now"]

    ne.undo_today(json.loads(json.dumps(undo)))
    assert db.scalar("SELECT COUNT(*) FROM news_theme_articles") == 0 and ne.today() == {}


def test_daily_validator_rejects_bad_editions(ne):
    p = ne.today_payload(day(2), day(0))
    good = _today_result(p)
    item = good["items"][0]
    for bad in ({**good, "items": good["items"][:2]},                                         # two items
                {**good, "items": [{**item, "what": "Brent rose to $101 a barrel."}] + good["items"][1:]},   # a number
                {**good, "items": [{**item, "theme": "gold"}] + good["items"][1:]},           # not a theme
                {**good, "items": [{**item, "refs": []}] + good["items"][1:]},                # nothing behind it
                {**good, "themes": {"gold": [1]}},
                {**good, "themes": {"oil_energy": [99]}}):
        with pytest.raises(ValueError):
            ne.validate_today(bad, p)


def test_theme_note_follows_the_writing_rules_is_weekly_and_undoes(ne):
    _edition(ne)
    (key, p, _), = ne.export_theme()                    # only oil has the 3 headlines a first note needs
    assert key == f"oil_energy@{day(0)}" and len(p["new_headlines"]) == 4 and "Energy" in p["sectors"]
    for field, bad in (("stands_now", "Crude is up 12% this month."),
                       ("stands_now", " ".join(["word"] * 31) + "."),
                       ("why_it_matters", " ".join(["word"] * 45) + "."),
                       ("gains", ["Oil & Gas"]),
                       ("next_if", ["If supply stays tight, then fuel users feel pain."])):
        with pytest.raises(ValueError):
            ne.validate_theme({**NOTE, field: bad}, p)
    with pytest.raises(ValueError):
        ne.validate_theme({**NOTE, "gains": [], "loses": []}, p)

    undo = ne.ingest_theme(ne.validate_theme(NOTE, p), p)
    oil = next(t for t in ne.themes() if t["theme_id"] == "oil_energy")
    assert oil["stands_now"] == NOTE["stands_now"] and oil["gains"] == ["Energy"] and oil["moved"]
    assert db.scalar("SELECT n_articles FROM news_theme_history") == 4

    with db.get_db() as c:                              # a new oil headline the next day: the note is not due yet
        c.execute("INSERT INTO news_articles (article_id, title, summary, source, published_at) "
                  "VALUES ('b1', 'Oil eases a little', '', 'test', ?)", (day(0) + "T06:00:00",))
        c.execute("INSERT INTO news_theme_articles (article_id, theme_id, assigned_on) VALUES ('b1', 'oil_energy', ?)", (day(0),))
    assert ne.export_theme() == []
    assert len(ne.export_theme(force=True)) == 1
    later = (TODAY + dt.timedelta(days=8)).isoformat()
    assert [k for k, _, _ in ne.export_theme(until=later)] == [f"oil_energy@{later}"]

    ne.undo_theme(json.loads(json.dumps(undo, default=str)))
    assert db.scalar("SELECT stands_now FROM news_themes WHERE theme_id = 'oil_energy'") is None
    assert db.scalar("SELECT COUNT(*) FROM news_theme_history") == 0


WEEK = {"radar": [{"title": "Humanoid robots leave the lab", "what": "Startups are testing robots and raising money.",
                   "why_early": "Factory automation suppliers could benefit later.", "refs": []}],
        "favour": [{"sector": "Energy", "reason": "Costlier crude lifts producer earnings."},
                   {"sector": "Financials", "reason": "Steady rates support lending margins."},
                   {"sector": "Information Technology", "reason": "Chip policy support is building."}],
        "careful": [{"sector": "Industrials", "reason": "Fuel bills squeeze heavy fuel users."},
                    {"sector": "Consumer Discretionary", "reason": "Costlier fuel leaves less to spend."},
                    {"sector": "Health Care", "reason": "A weaker rupee lifts input costs."}]}


def test_weekly_edition_needs_a_note_and_whitelisted_sectors(ne):
    _edition(ne)
    assert ne.export_week() == []                       # no theme has a note yet
    (_, tp, _), = ne.export_theme()
    ne.ingest_theme(ne.validate_theme(NOTE, tp), tp)
    (key, p, _), = ne.export_week()
    titles = [h["title"]["untrusted_text"] for h in p["unfiled_headlines"]]
    assert "Startups test humanoid robots" in titles and "Oil climbs as supply tightens" not in titles
    assert p["sector_flow"]["Energy"]["this_week"] == 1
    robots = [titles.index(t) + 1 for t in ("Startups test humanoid robots", "Robot makers raise fresh funding")]
    good = {**WEEK, "radar": [{**WEEK["radar"][0], "refs": robots}, {**WEEK["radar"][0], "refs": robots}]}
    for bad in ({**good, "radar": [{**WEEK["radar"][0], "refs": robots[:1]}] * 2},            # one headline behind it
                {**good, "favour": good["favour"][:2]},
                {**good, "careful": [{"sector": "Energy", "reason": "x y."}] + good["careful"][1:]},   # in both lists
                {**good, "favour": [{"sector": "Banks", "reason": "x y."}] + good["favour"][1:]}):
        with pytest.raises(ValueError):
            ne.validate_week(bad, p)
    undo = ne.ingest_week(ne.validate_week(good, p), p)
    w = ne.week()
    assert [x["sector"] for x in w["favour"]][0] == "Energy" and len(w["radar"][0]["article_ids"]) == 2
    assert ne.export_week() == []                       # next one is due in a week
    ne.undo_week(json.loads(json.dumps(undo)))
    assert ne.week() == {}


def test_themes_follow_config(ne, monkeypatch):
    ne.ensure_themes()
    monkeypatch.setattr(config, "NEWS_THEMES", config.NEWS_THEMES[:6])
    assert len(ne.themes()) == 6
    assert db.scalar("SELECT status FROM news_themes WHERE theme_id = ?", [config.NEWS_THEMES[-1][0]]) == "active"
    assert db.scalar("SELECT COUNT(*) FROM news_themes WHERE status = 'retired'") == 1


def test_kinds_are_registered_in_drain_order(ne):
    from alpha_mcp import tasks
    order = tasks.DRAIN_ORDER
    assert order.index("news_today") < order.index("news_theme") < order.index("news_week")
    assert "NO NUMBERS" in tasks.kinds_spec()["kinds"]["news_theme"]["instructions"]
    assert tasks.enqueue("news_today")["queued"] == 1
    (item,) = tasks.claim("news_today")
    assert "_article_ids" not in item["payload"] and item["payload"]["n_headlines"] == 12


def test_news_pages_render(ne, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from cockpit import api
    from cockpit.app import app
    import webauth
    monkeypatch.setattr(webauth, "AUTH_FILE", tmp_path / "auth.json")
    webauth.set_password("correct horse battery")
    client = TestClient(app, cookies={webauth.COOKIE: webauth.make_token()})

    def clear():
        for f in (api.get_news_today, api.get_news_themes, api.get_news_week, api.get_sector_radar):
            f.cache_clear()
    clear()
    page = client.get("/news")
    assert page.status_code == 200 and "No weekly outlook has been written yet" in page.text and "No note yet" in page.text
    assert client.get("/news/theme/nope").status_code == 404

    _edition(ne)
    (_, tp, _), = ne.export_theme()
    ne.ingest_theme(ne.validate_theme(NOTE, tp), tp)
    (_, p, _), = ne.export_week()
    titles = [h["title"]["untrusted_text"] for h in p["unfiled_headlines"]]
    robots = [titles.index(t) + 1 for t in ("Startups test humanoid robots", "Robot makers raise fresh funding")]
    week = {**WEEK, "radar": [{**WEEK["radar"][0], "refs": robots}, {**WEEK["radar"][0], "refs": robots}]}
    ne.ingest_week(ne.validate_week(week, p), p)
    clear()
    page = client.get("/news")
    assert page.status_code == 200
    for needle in ("Oil keeps climbing", "Humanoid robots leave the lab", "/sectors?sector=Energy",
                   "not a recommendation", "/news/theme/oil_energy", "/news/all"):
        assert needle in page.text, needle
    assert client.get("/news/all").status_code == 200
    deep = client.get("/news/theme/oil_energy")
    assert deep.status_code == 200 and "Timeline" in deep.text and "Crude began to rise" in deep.text
