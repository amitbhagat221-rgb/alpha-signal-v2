"""views.py read-models + the PAGES nav (plan 0015 Phase 5). Offline: a temp SQLite DB."""
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import pytest

import config
import db
import views


@pytest.fixture
def tmpdb(tmp_path, monkeypatch):
    path = tmp_path / "v.db"
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE stocks (sid TEXT PRIMARY KEY, ticker TEXT, name TEXT, sector TEXT,
            cap_tier TEXT, pe_ratio REAL, pb_ratio REAL, roe REAL, market_cap_cr REAL);
        CREATE TABLE daily_picks (sid TEXT, pick_date TEXT, final_score REAL, rank INTEGER,
            cap_tier TEXT, sector TEXT, base_score REAL, forensic_adj REAL,
            integrity_status TEXT, uhs_score REAL, uhs_label TEXT, uhs_worst_dim TEXT,
            uhs_breakdown_json TEXT, PRIMARY KEY (sid, pick_date));
        CREATE TABLE daily_snapshots (sid TEXT, snapshot_date TEXT, cap_tier TEXT, close_price REAL,
            piotroski_f INTEGER, cf_accruals REAL, bs_accruals REAL, earnings_yield REAL,
            book_to_price REAL, consensus_signal REAL, promoter_qoq REAL, delivery_pct REAL,
            mom_6m REAL, mom_12m REAL, smart_money REAL, sentiment_7d REAL);
        CREATE TABLE stock_prices (sid TEXT, date TEXT, close REAL);
        CREATE TABLE pipeline_log (id INTEGER PRIMARY KEY, run_date TEXT, step_name TEXT,
            status TEXT, rows_affected INTEGER, duration_sec REAL, error_message TEXT,
            started_at TEXT, finished_at TEXT);
    """)
    c.commit()
    c.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def _exec(path, sql, rows):
    c = sqlite3.connect(path)
    c.executemany(sql, rows)
    c.commit()
    c.close()


def test_picks_one_gate(tmpdb):
    _exec(tmpdb, "INSERT INTO stocks (sid, ticker, cap_tier) VALUES (?,?,?)",
          [(s, s, "LARGE") for s in ("OK", "FAIL", "AVOID", "LEGACY", "WARN")])
    _exec(tmpdb, "INSERT INTO daily_picks (sid, pick_date, final_score, rank, cap_tier, "
                 "integrity_status, uhs_score) VALUES (?,?,?,?,?,?,?)", [
        ("OK", "2026-09-27", 0.9, 1, "LARGE", "PASS", 80),
        ("FAIL", "2026-09-27", 0.8, 2, "LARGE", "FAIL", 90),     # integrity FAIL → hidden
        ("AVOID", "2026-09-27", 0.7, 3, "LARGE", "PASS", 59),    # UHS AVOID band → hidden
        ("LEGACY", "2026-09-27", 0.6, 4, "LARGE", None, None),   # pre-UHS row → shown
        ("WARN", "2026-09-27", 0.5, 5, "LARGE", "WARN", 60),     # WARN is surfaced, not gated
        ("OK", "2026-09-26", 0.9, 1, "LARGE", "PASS", 80),
    ])
    assert views.picks()["sid"].tolist() == ["OK", "LEGACY", "WARN"]
    assert views.picks(gated=False)["sid"].tolist() == ["OK", "FAIL", "AVOID", "LEGACY", "WARN"]
    assert views.picks("2026-09-26")["sid"].tolist() == ["OK"]
    assert views.pick_dates(2) == ["2026-09-27", "2026-09-26"]
    assert views.pick_count() == 5
    assert "close_price" in views.published_picks().columns


def test_tiers_follow_config(monkeypatch):
    monkeypatch.setattr(config, "TIERS", ("LARGE", "MID", "SMALL", "MICRO"))
    monkeypatch.setattr(config, "EXCLUDED_FROM_PICKS", ("MICRO",))
    assert views.pickable_tiers() == ["LARGE", "MID", "SMALL"]
    assert views.unpickable_tiers() == ["MICRO"]
    # config.TIERS as a dict of specs (plan 0015): `pickable` decides, no hand list
    monkeypatch.setattr(config, "TIERS", {"LARGE": {}, "MID": {}, "SMALL": {},
                                          "NANO": {"pickable": False}, "MICRO": {"pickable": False}})
    monkeypatch.setattr(config, "EXCLUDED_FROM_PICKS", ())
    assert views.tiers() == ["LARGE", "MID", "SMALL", "NANO", "MICRO"]
    assert views.pickable_tiers() == ["LARGE", "MID", "SMALL"]


def test_price_metrics_are_trading_day_returns(tmpdb):
    days = pd.bdate_range("2025-01-01", periods=300)
    _exec(tmpdb, "INSERT INTO stock_prices VALUES (?,?,?)",
          [("X", d.strftime("%Y-%m-%d"), 100.0 + i) for i, d in enumerate(days)])
    m = views.price_metrics(["X"])["X"]
    last = 399.0
    for label, n in views.RETURN_WINDOWS:
        assert m[f"return_{label}"] == round((last / (last - n) - 1) * 100, 1)
    assert m["close_price"] == last and m["price_date"] == days[-1].strftime("%Y-%m-%d")
    assert views.latest_close(["X"]) == {"X": (last, days[-1].strftime("%Y-%m-%d"))}
    assert views.price_metrics(["NOPE"]) == {"NOPE": {}}


def test_pipeline_status_marks_aborted_and_prefers_completion(tmpdb):
    now = datetime.now()
    old = (now - timedelta(hours=2)).isoformat()
    fresh = now.isoformat()
    today = now.date().isoformat()
    _exec(tmpdb, "INSERT INTO pipeline_log (run_date, step_name, status, started_at) VALUES (?,?,?,?)", [
        (today, "a", "RUNNING", old), (today, "a", "SUCCESS", old),   # completion wins
        (today, "b", "RUNNING", old),                                  # crashed → ABORTED
        (today, "c", "RUNNING", fresh),                                # genuinely running
        ("2020-01-01", "d", "FAILED", "2020-01-01T03:00:00"),          # outside 7 days
    ])
    st = {r["step_name"]: r["status"] for r in views.pipeline_status(7)}
    assert st == {"a": "SUCCESS", "b": "ABORTED", "c": "RUNNING"}
    assert views.step_status()["d"]["status"] == "FAILED"          # all history for /flow


def test_signal_tables_are_the_display_list(monkeypatch):
    """One display list, in order; tables lacking (sid, snapshot_date) are skipped."""
    monkeypatch.setattr(views, "_columns",
                        lambda t: ("sid", "x") if t == "insider_signals" else ("sid", "snapshot_date", "x"))
    expected = [t for t in views._DISPLAY_SIGNAL_TABLES if t != "insider_signals"]
    assert views.signal_tables() == expected


@pytest.mark.parametrize("app_mod, pages_mod", [("cockpit.app", "cockpit.pages"),
                                                ("cockpit_ops.app", "cockpit_ops.pages")])
def test_pages_drive_the_nav(app_mod, pages_mod):
    import importlib
    from cockpit._shared import nav_model
    app = importlib.import_module(app_mod).app
    pages = importlib.import_module(pages_mod)
    routes = {r.path for r in app.routes if "GET" in (getattr(r, "methods", None) or ())}
    nav = nav_model(pages.PAGES, pages.OTHER_APP, pages.BRAND)
    ids = [p["id"] for p in pages.PAGES]
    assert len(ids) == len(set(ids))
    for p in pages.PAGES:
        assert p["path"] in routes, p["path"]
    rail = [p["id"] for _, items in nav["sections"] for p in items]
    mobile = [p["id"] for p in nav["tabs"]] + [p["id"] for p in nav["more"]]
    assert sorted(rail) == sorted(mobile) == sorted(ids)   # every page on both, once


def test_flow_edges_are_the_graph(monkeypatch):
    import graph
    from cockpit_ops import api
    monkeypatch.setattr(views, "step_status", lambda: {})
    api.get_flow_overview.cache_clear()
    ov = api.get_flow_overview()
    api.get_flow_overview.cache_clear()
    pairs = {(w, r) for w, r, _, _ in graph.edges(config.PIPELINE_STEPS)}
    assert {(e["from"], e["to"]) for e in ov["edges"]} == pairs
    names = [s["name"] for layer in ov["layers"] for s in layer["steps"]]
    assert sorted(names) == sorted(s["name"] for s in config.PIPELINE_STEPS)
