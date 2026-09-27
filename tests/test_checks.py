"""
Plan 0015 Phase 4 — checks/: one range per column, derived criticality, the
post-step check, dataset kinds. Offline: registries + temp DBs, never the live DB.
"""
import sqlite3
from datetime import date, timedelta

import pytest

import checks
import db
import graph
import tables
from checks import ranges
from config import PIPELINE_STEPS, TIERS


@pytest.fixture(scope="module")
def schema_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(db.SCHEMA_PATH.read_text())
    yield conn
    conn.close()


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    path = tmp_path / "checks.db"
    conn = sqlite3.connect(path)
    conn.executescript(db.SCHEMA_PATH.read_text())
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


# ── one range per column ──

def test_every_registered_column_exists_and_has_one_rule(schema_conn):
    from factors import VALIDATION_RANGES
    for (table, column), spec in ranges.COLUMNS.items():
        cols = {r[1] for r in schema_conn.execute(f"PRAGMA table_info([{table}])")}
        assert column in cols, (table, column)
        assert len({"factor", "range", "min", "in"} & set(spec)) == 1, (table, column)
        if "factor" in spec:        # reused, never copied
            assert spec["factor"] in VALIDATION_RANGES, spec
        if "typical" in spec:
            lo, hi = ranges.bounds(table, column)
            assert lo <= spec["typical"][0] <= spec["typical"][1] <= hi, (table, column)


def test_enums_follow_config():
    assert ranges.COLUMNS[("stocks", "cap_tier")]["in"] == list(TIERS)
    assert "MICRO" not in ranges.COLUMNS[("daily_picks", "cap_tier")]["in"]


def test_factor_columns_reuse_the_backtest_range():
    from factors import VALIDATION_RANGES
    lo, hi, _ = VALIDATION_RANGES["m_score"]
    assert ranges.bounds("forensic_scores", "m_score") == (lo, hi)


def test_health_profiles_carry_no_ranges():
    import health
    for tbl, profile in health.TABLE_PROFILES.items():
        assert "validity_checks" not in profile, tbl


def test_consumers_read_the_registry(monkeypatch):
    from validators import per_stock_integrity as psi
    from validators.plausibility import verify_plausibility
    # plausibility's column classes resolve through the registry
    v = verify_plausibility("bank_gnpa_pct", 40)
    assert v.status == "OUT_OF_RANGE_HARD" and v.hard_range == ranges.bounds("banking_metrics", "gross_npa_pct")
    # the integrity check follows a registry change
    monkeypatch.setitem(ranges.COLUMNS, ("forensic_scores", "m_score"), {"range": (-1, 1)})
    assert psi.m_score_realistic({"m_score": 2.0})[0] == "FAIL"
    assert psi.m_score_realistic({"m_score": 0.5})[0] == "PASS"


def test_in_range_tolerates_float_roundoff():
    assert ranges.in_range("daily_picks", "final_score", 1.0000000000000002)
    assert not ranges.in_range("daily_picks", "final_score", 1.01)
    assert ranges.in_range("daily_picks", "final_score", None)
    assert not ranges.in_range("daily_picks", "cap_tier", "MICRO")


def test_range_verdict_end_to_end(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.execute("INSERT INTO stocks (sid, ticker, name, cap_tier) VALUES ('A', 'A', 'A', 'LARGE')")
    conn.executemany("INSERT INTO stock_prices (sid, date, close) VALUES ('A', ?, ?)",
                     [("2026-01-01", 10.0), ("2026-01-02", -1.0)])
    conn.commit()
    conn.close()
    (v,) = checks.run(only="RANGE:stock_prices.close")
    assert (v["status"], v["n_bad"], v["n_total"], v["sample"]) == ("FAIL", 1, 2, -1.0)
    assert v["severity"] == checks.CRITICAL        # stock_prices is on the email's path
    from tools import data_sanity
    (legacy,) = data_sanity.run(only_code="RANGE:stock_prices.close")
    assert legacy["n_violations"] == 1 and legacy["pct_violations"] == 50.0


# ── criticality is derived ──

def test_critical_steps_are_the_email_critical_path():
    crit = checks.critical_steps()
    assert {s["name"] for s in PIPELINE_STEPS if s.get("critical")} <= crit
    assert graph.ancestors(PIPELINE_STEPS, graph.EMAIL, needed_only=True) <= crit
    assert graph.EMAIL in crit


def test_critical_tables_are_critical_step_outputs():
    ct = checks.critical_tables()
    assert {"daily_picks", "daily_snapshots", "stock_prices", "_file_dossiers"} <= ct
    assert not any(t.startswith("file:") for t in ct)


def test_empty_table_policy_is_table_metadata():
    assert checks.empty_table_severity("analyst_consensus_quarantine") == checks.OK
    assert checks.empty_table_severity("paper_trades") == checks.INFO
    assert checks.empty_table_severity("daily_picks") == checks.CRITICAL


# ── post-step (invariant 4) ──

def test_post_step_fails_only_on_an_outdated_declared_output(temp_db):
    old = (date.today() - timedelta(days=30)).isoformat()
    today = date.today().isoformat()
    conn = sqlite3.connect(temp_db)
    conn.execute("INSERT INTO stock_prices (sid, date, close) VALUES ('A', ?, 1.0)", (old,))
    conn.execute("INSERT INTO daily_picks (sid, pick_date, cap_tier, final_score) VALUES ('A', ?, 'LARGE', 0.5)", (today,))
    conn.commit()
    conn.close()
    stale = {"name": "fetch_bhavcopy", "writes": ["stock_prices", "file:x"]}
    fresh = {"name": "screener", "writes": ["daily_picks"]}
    fails = checks.post_step(stale)
    assert len(fails) == 1 and fails[0].startswith("stock_prices is OUTDATED")
    assert checks.post_step(fresh) == []


# ── dataset kinds (H3) ──

def test_every_table_gets_exactly_one_kind():
    kinds = tables.dataset_kinds()
    registered = {t for t, e in tables.TABLES.items() if e["kind"] != "file"}
    assert set(kinds) == registered
    assert set(kinds.values()) <= set(tables.DATASET_KINDS)
    assert set(tables.DATASET_KIND_OVERRIDES) <= registered


def test_kind_inference_examples():
    k = tables.dataset_kinds()
    assert k["stock_prices"] == "series" and k["analyst_consensus"] == "state"
    assert k["bulk_deals"] == "event" and k["daily_picks"] == "feature"
    assert k["pipeline_log"] == "log" and k["analyst_consensus_snapshots"] == "series"
