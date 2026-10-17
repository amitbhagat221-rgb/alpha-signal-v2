"""Industry explainer (plan 0016 P5): the validator's no-numbers rule, the SVG geometry,
the cheat-sheet medians and the Sectors › Industry Detail pane that renders them."""

import json

import pytest

from cockpit import explainer as exv
from tools import sector_explainer as se


# ── validator ─────────────────────────────────────────────────────────────────

def test_prose_digits_allows_years_and_calendar_tokens():
    assert se.prose_digits("From 2020 to 2022 margins touched the high twenties; FY25 and Q1 were weak") == []
    assert se.prose_digits("China+1 sourcing since 2019") == []


def test_prose_digits_catches_raw_numbers():
    assert se.prose_digits("margins fell 500 bps to 18%") == ["500", "18%"]
    assert se.prose_digits("₹535,000 cr market") == ["₹535,000"]


def _minimal_explainer():
    return {
        "one_liner": "Makers of things.", "doors": [
            {"name": "A", "sub": "s", "examples": ["AAA"], "profit_kept": "low", "blurb": "b"},
            {"name": "B", "sub": "s", "examples": [], "profit_kept": "high", "blurb": "b"}],
        "door_analogy": "x", "door_so_what": "x",
        "kitchen": {"stations": [{"name": "stage", "what": "w", "who": "w"} for i in range(5)],
                    "bands": [{"label": "l", "kind": "india"}] * 5, "rival": None, "note": "n", "so_what": "s"},
        "end_markets": [{"name": "m", "buys": "b", "moves_with": "m"}] * 6, "end_markets_so_what": "s",
        "pnl": {"walk": {"input_label": "Raw", "opex_label": "Opex",
                         "a": {"name": "A", "input": 70, "opex": 18, "dep_int": 7},
                         "b": {"name": "B", "input": 52, "opex": 23, "dep_int": 9}},
                "lines": [{"line": "l", "matters": "yes", "why": "w"}] * 6, "analogy": "a", "so_what": "s"},
        "clock": {"is_cyclical": "yes", "phases": [{"name": n, "years": "2020", "what": "w"} for n in ("Boom", "Peak", "Bust", "Bottom")],
                  "position": "early_up", "position_label": "early up", "position_detail": "d",
                  "timeline": [{"when": "2019", "what": "w", "tone": "neutral"}] * 5,
                  "hands": [{"name": "h", "reading": "flat", "tone": "flat", "meaning": "m"}] * 4, "so_what": "s"},
        "dials": [{"name": "d", "channel": "c", "rise_does": "r", "direction": "up", "weight": 2, "indicator_id": "brent_crude"}] * 7,
        "dials_so_what": "s",
        "bottlenecks": [{"name": "b", "why": "w", "severity": "structural"}] * 5, "bottlenecks_so_what": "s",
        "rulebook": [{"body": "b", "what": "w", "why": "w", "status": "live"}] * 6,
        "regulatory_keywords": ["a", "b", "c", "d", "e", "f"],
        "forces": {"a_name": "A", "b_name": "B",
                   "scores": {k: [3, 1] for k in ("rivalry", "supplier", "buyer", "entrants", "substitutes")},
                   "why": {k: "w" for k in ("rivalry", "supplier", "buyer", "entrants", "substitutes")}, "so_what": "s"},
        "cheat_sheet": [{"metric": "m", "tells": "t", "good": "above 45%", "metric_key": "gross_margin_pct"}] * 8,
        "lead_indicators": [{"name": "l", "lead_quarters": 1, "channel": "c"}] * 6,
        "rule": {"text": "t", "signs": [{"name": "s", "ok": True, "note": "n"}] * 3},
        "call": {"headline": "h", "points": ["p"], "would_change": ["w"]},
        "tell_a_friend": " ".join(["word"] * 130),
        "glossary": [{"term": "t", "def": "d 1.2"}] * 12,
    }


def test_validator_accepts_minimal_and_rejects_digits_and_bad_shapes():
    ex = _minimal_explainer()
    assert se.validate_explainer(ex, ["AAA"]) == []
    bad = _minimal_explainer()
    bad["one_liner"] = "Worth ₹535,000 cr"
    bad["clock"]["position"] = "sideways"
    bad["doors"][0]["examples"] = ["NOPE"]
    bad["dials"][0] = dict(bad["dials"][0], indicator_id="not_a_series")
    errs = se.validate_explainer(bad, ["AAA"])
    assert any("digits in prose at one_liner" in e for e in errs)
    assert any("clock.position" in e for e in errs)
    assert any("doors[0].examples" in e for e in errs)
    assert any("indicator_id unknown" in e for e in errs)


def test_validator_checks_the_walk_sums_to_under_100():
    ex = _minimal_explainer()
    ex["pnl"]["walk"]["a"] = {"name": "A", "input": 80, "opex": 30, "dep_int": 5}
    assert any("pnl.walk.a" in e for e in se.validate_explainer(ex))


# ── geometry ──────────────────────────────────────────────────────────────────

def test_waterfall_bars_walk_from_100_to_profit():
    w = exv.waterfall({"name": "A", "input": 70, "opex": 18, "dep_int": 7}, "Raw", "Opex")
    assert [b["label"] for b in w["bars"]] == ["Sales", "Input", "Gross", "Opex", "EBITDA", "Dep+int", "Profit"]
    assert w["gross"] == 30 and w["ebitda"] == 12 and w["profit"] == 5
    assert all(b["h"] >= 0 for b in w["bars"])
    assert w["bars"][0]["h"] == pytest.approx(170)


def test_clock_hand_points_inside_the_ring():
    for pos in ("bottom", "early_up", "boom", "peak", "early_down", "bust"):
        h = exv.clock(pos)
        assert ((h["x2"] - 150) ** 2 + (h["y2"] - 150) ** 2) ** 0.5 < 120


def test_radar_has_five_points_per_series_and_labels():
    r = exv.radar({k: [3, 1] for k in ("rivalry", "supplier", "buyer", "entrants", "substitutes")})
    assert len(r["a_pts"]) == 5 and len(r["b_pts"]) == 5 and len(r["labels"]) == 5
    assert r["a_pts"][0] == (170.0, 40.0)          # rivalry 3 → top of the pentagon


def test_lead_dots_sort_by_lead_time():
    d = exv.lead_dots([{"name": "x", "lead_quarters": 2}, {"name": "y", "lead_quarters": 0}])
    assert [p["name"] for p in d["dots"]] == ["y", "x"]
    assert d["dots"][0]["x"] < d["dots"][1]["x"]


def test_per_stock_metrics_from_screener_lines():
    latest = {"Sales": 1000, "Raw Material Cost": 600, "Operating Profit": 150, "Net profit": 80,
              "Inventories": 250, "Receivables": 100, "Gross Block": 1200, "Depreciation": 50, "Net Block": 800,
              "Capital Work in Progress": 120, "Profit before tax": 100, "Interest": 20,
              "Equity Share Capital": 100, "Reserves": 500, "Borrowings": 400}
    prior = {"Sales": 900, "Gross Block": 1050}
    m = exv._per_stock_metrics(latest, prior)
    assert m["gross_margin_pct"] == pytest.approx(40)
    assert m["inventory_days"] == pytest.approx(91.25)
    assert m["capex_to_dep"] == pytest.approx(3)
    assert m["roce_pct"] == pytest.approx(12)
    assert m["sales_growth_pct"] == pytest.approx(100 / 9)


def test_filter_regulatory_matches_keywords_as_words():
    ev = [{"title": "India extends anti-dumping duty on phthalic anhydride", "ai_reasoning": ""},
          {"title": "Iron ore output doubles", "ai_reasoning": "mining"}]
    out = exv.filter_regulatory(ev, ["anti-dumping", "chemical"])
    assert [e["title"][:5] for e in out] == ["India"]
    assert exv.filter_regulatory(ev, []) == []


# ── the pane ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """The app without its login wall, restored afterwards (other test modules
    assert the wall is there)."""
    from starlette.testclient import TestClient
    import cockpit.app as m
    saved = list(m.app.user_middleware)
    m.app.user_middleware = [mw for mw in saved if mw.cls.__name__ != "LoginRequired"]
    m.app.middleware_stack = None
    yield TestClient(m.app, raise_server_exceptions=True)
    m.app.user_middleware = saved
    m.app.middleware_stack = None


def test_industry_with_explainer_renders_the_twelve_cards(client):
    import db
    row = db.one("SELECT sector FROM sector_metadata WHERE source = 'auto' AND payload LIKE '%\"explainer\":%' LIMIT 1")
    if not row:
        pytest.skip("no industry has an explainer yet")
    html = client.get("/sectors", params={"industry": row["sector"]}).text
    for cid in ("ex-c1", "ex-c2", "ex-c4", "ex-c5", "ex-c9", "ex-c10", "ex-c11", "ex-c12", "ex-gl"):
        assert f'id="{cid}"' in html, cid
    assert "Understand" in html and "Picks &amp; signals" in html
    assert "More context" not in html            # nothing collapsed any more


def test_industry_without_explainer_still_renders(client, monkeypatch):
    from cockpit import api
    payload = {"summary": "A story.", "value_chain": [{"name": "a", "items": ["x"]}] * 5,
               "drivers": {"revenue": [{"item": "r"}], "cost": [], "growth": []},
               "cyclicality": "It cycles.", "regulators": [{"body": "RBI", "what": "w"}],
               "india_specific": ["one"], "trend_bullets": {"headwinds": ["h"]}, "segments": [],
               "_generated_at": "2026-05-11 00:00:00", "_industry": "Banks", "_source": "auto"}
    monkeypatch.setattr(api, "get_group_metadata", lambda name: payload)
    html = client.get("/sectors", params={"industry": "Banks"}).text
    assert "has not been written for this industry yet" in html
    assert "Cyclicality" in html and "More context" not in html
    assert 'id="ex-c1"' not in html


def test_sector_view_and_stock_partial_render(client):
    assert client.get("/sectors", params={"sector": "Materials"}).status_code == 200
    r = client.get("/partial/industry-card/Chemicals%20%26%20Specialty")
    assert r.status_code == 200 and "Listed players" in r.text


def test_story_refresh_keeps_the_explainer(tmp_path, monkeypatch):
    """tools/sector_narrative_fetcher.save_payload must not drop the explainer block."""
    import sqlite3
    from contextlib import contextmanager
    from tools import sector_narrative_fetcher as f
    dbp = tmp_path / "t.db"
    con = sqlite3.connect(dbp)
    con.execute("CREATE TABLE sector_metadata (sector TEXT, industry TEXT, source TEXT, generated_at TEXT, payload TEXT, notes TEXT, PRIMARY KEY (sector, source))")
    con.execute("INSERT INTO sector_metadata VALUES ('X', 'X', 'auto', '2026-01-01', ?, NULL)",
                [json.dumps({"summary": "old", "explainer": {"one_liner": "kept"}, "explainer_generated_at": "2026-10-16"})])
    con.commit(); con.close()

    @contextmanager
    def fake_db():
        c = sqlite3.connect(dbp)
        try:
            yield c
        finally:
            c.close()
    monkeypatch.setattr(f, "get_db", fake_db)
    f.save_payload("X", "X", {"summary": "new"})
    got = json.loads(sqlite3.connect(dbp).execute("SELECT payload FROM sector_metadata").fetchone()[0])
    assert got["summary"] == "new" and got["explainer"]["one_liner"] == "kept"
