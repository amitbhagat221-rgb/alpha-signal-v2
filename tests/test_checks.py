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


def test_post_step_exempts_best_effort_tables(temp_db):
    old = (date.today() - timedelta(days=400)).isoformat()
    conn = sqlite3.connect(temp_db)
    conn.execute("INSERT INTO insider_trades (sid, trade_date) VALUES ('A', ?)", (old,))
    conn.commit()
    conn.close()
    assert "insider_trades" in db.BEST_EFFORT_STALE
    assert checks.post_step({"name": "fetch_insider", "writes": ["insider_trades"]}) == []


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


def test_quarantine_mirrors_are_registered():
    # every quarantine mirror is registered as such, so "empty = clean" needs no name rule
    for t in tables.TABLES:
        if t.endswith("_quarantine"):
            assert tables.TABLES[t]["kind"] == "QUARANTINE", t


# ── every check answers one of the five questions, in plain words (ADR 0059) ──

def test_every_data_check_declares_its_meaning():
    for c in checks.all_checks():
        assert c["theme"] in checks.THEMES, c["code"]
        for field in ("message", "why", "fix"):
            assert isinstance(c.get(field), str) and len(c[field]) > 15, (c["code"], field)


def test_every_system_check_declares_its_meaning():
    from checks import report
    for code, c in report.SYSTEM_CHECKS.items():
        assert c["theme"] in checks.THEMES, code
        assert all(c[k] for k in ("when", "why", "fix", "severity")), code


def test_every_emitted_code_is_registered():
    """A verdict code the report cannot explain would crash the issue list."""
    import re
    from pathlib import Path
    from checks import report
    root = Path(checks.__file__).parent
    emitted = set()
    for f in ("feeds.py", "report.py"):
        emitted |= set(re.findall(r'code="([A-Z_]+)"', (root / f).read_text()))
    known = set(report.SYSTEM_CHECKS) | set(report.FAMILY)
    assert emitted and emitted <= known, emitted - known
    assert set(report.FAMILY.values()) <= set(report.SYSTEM_CHECKS)


def _state(**parts):
    """A gathered state with nothing wrong, overridable per gatherer."""
    base = {
        "pipeline": {"last_run_date": "2026-01-02", "last_run_status": "SUCCESS", "n_steps": 3,
                     "failed_steps_today": [], "failed_streaks": []},
        "tables": {"fresh": 5, "stale": [], "outdated": [], "empty": []},
        "watchdog": {"last_run": "2026-01-02T15:00:00", "age_hours": 1.0, "healed": 0, "failed": 0, "skipped": 0},
        "feeds": {"rows": [], "verdicts": []},
        "data": {"verdicts": []},
        "integrity": {"n_picks": 100, "rows": []},
        "gates": {"gates": []},
        "dossiers": {"latest_file": "d.json", "n_thesis": 0, "n_failed_validation": 0, "failed_samples": []},
        "endpoints": {"rows": []},
        "factors": {"decay": []},
    }
    return {**base, **parts}


def test_a_clean_state_has_no_issues_and_a_green_scorecard():
    from checks import report
    actionable, tolerated = report.issues(_state())
    assert actionable == [] and tolerated == []
    card = report.scorecard(actionable, _state())
    assert [r["theme"] for r in card] == list(checks.THEMES)
    assert {r["status"] for r in card} == {"OK"}


def test_issue_shape_order_and_tolerated_split():
    from checks import report
    st = _state(
        tables={"fresh": 4, "stale": [("news_articles", 3.0, 2.0, "sources/rss.py")], "outdated": [],
                "empty": ["paper_trades"]},
        integrity={"n_picks": 100, "rows": [{"sid": "ABC", "integrity_status": "FAIL", "integrity_reasons": "pt mismatch"}]},
        watchdog={"last_run": None, "age_hours": None, "healed": 0, "failed": 0, "skipped": 0},
    )
    actionable, tolerated = report.issues(st)
    assert [i["code"] for i in actionable] == ["WATCHDOG", "PICK_INTEGRITY", "TABLE_STALE"]
    assert [i["code"] for i in tolerated] == ["TABLE_EMPTY"]          # a feature not live yet
    for i in actionable + tolerated:
        assert set(i) >= {"severity", "theme", "code", "id", "target", "message", "detail", "why", "fix", "days"}
        assert i["theme"] in checks.THEMES and i["why"] and i["fix"]
    card = {r["theme"]: r for r in report.scorecard(actionable, st)}
    assert (card["ran"]["status"], card["arrived"]["status"], card["model"]["status"]) == ("BROKEN", "WATCH", "OK")


def test_a_crashed_gatherer_is_an_issue_not_silence():
    from checks import report
    actionable, _ = report.issues(_state(feeds={"error": "KeyError: 'x'"}))
    assert [(i["code"], i["target"]) for i in actionable] == [("HEALTH_CHECK_CRASHED", "feeds")]


def test_fold_one_fact_one_verdict():
    """A failing step absorbs its own stale table and the watchdog heal that failed with it."""
    from checks import report
    step = next(s for s in PIPELINE_STEPS if not s.get("critical")
                and s["name"] not in checks.critical_steps() and graph.writes(s)
                and not graph.writes(s)[0].startswith("file:"))
    table = graph.writes(step)[0]
    st = _state(
        pipeline={"last_run_date": "2026-01-02", "last_run_status": "FAILED", "n_steps": 3, "failed_streaks": [],
                  "failed_steps_today": [{"step": step["name"], "error": "boom", "at": "t"},
                                         {"step": f"watchdog_{table}_heal", "error": "boom", "at": "t"}]},
        tables={"fresh": 4, "stale": [], "outdated": [(table, 9.0, 3.0, "x")], "empty": []},
    )
    actionable, _ = report.issues(st)
    assert [i["id"] for i in actionable] == [f"PIPELINE_STEP:{step['name']}"]
    assert table in actionable[0]["detail"] and "watchdog could not heal" in actionable[0]["detail"]
    # an unrelated stale table still stands on its own
    st["tables"]["stale"] = [("some_other_table", 3.0, 2.0, "y")]
    assert len(report.issues(st)[0]) == 2


def test_streak_replaces_the_single_failure():
    from checks import report
    st = _state(pipeline={"last_run_date": "2026-01-02", "last_run_status": "FAILED", "n_steps": 3,
                          "failed_steps_today": [{"step": "fetch_x", "error": "e", "at": "t"}],
                          "failed_streaks": [{"step": "fetch_x", "days": 3, "sample_error": "e"}]})
    (i,) = report.issues(st)[0]
    assert (i["code"], i["severity"]) == ("PIPELINE_STEP", checks.CRITICAL) and "3 days in a row" in i["message"]


def test_a_check_that_looks_at_nothing_is_reported(temp_db):
    from checks import report
    data = checks.run(only="RANGE:stock_prices.close")           # empty table → PASS on 0 rows
    assert data[0]["status"] == "PASS" and data[0]["n_total"] == 0
    actionable, _ = report.issues(_state(data={"verdicts": data}))
    assert [i["code"] for i in actionable] == ["CHECK_VACUOUS"]


def test_catalog_lists_every_check_once():
    from checks import report
    data = [{"code": c["code"], "check_id": c["code"], "target": "t", "status": "PASS", "severity": "OK",
             "detail": "", "message": c["message"], "rule": checks.rule(c), "n_total": 5,
             **{k: c.get(k) for k in checks._CARRIED}} for c in checks.all_checks()]
    rows = report.catalog(_state(data={"verdicts": data}))
    codes = [r["code"] for r in rows]
    assert len(codes) == len(set(codes))
    assert set(report.SYSTEM_CHECKS) <= set(codes) and {"RANGE", "COVERAGE_GAP", "FACTOR_INPUT"} <= set(codes)
    assert len(codes) <= 30, "few, high-quality checks: a new one must replace or earn its place (ADR 0060)"
    assert next(r for r in rows if r["code"] == "RANGE")["n_checks"] == len(ranges.COLUMNS)


def test_recovered_step_is_not_a_failure(temp_db):
    """The report reads a step's FINAL state: failed then succeeded on a re-run = fine."""
    from checks import system
    today = date.today().isoformat()
    conn = sqlite3.connect(temp_db)
    rows = [("healed", "FAILED", "boom"), ("healed", "SUCCESS", None), ("broken", "FAILED", "boom")]
    conn.executemany("INSERT INTO pipeline_log (run_date, step_name, status, started_at, finished_at, error_message) "
                     f"VALUES ('{today}', ?, ?, '{today}T03:00:00', '{today}T03:01:00', ?)", rows)
    conn.commit()
    conn.close()
    p = system.pipeline_facts(1)
    assert [f["step"] for f in p["failed_steps_today"]] == ["broken"]
    assert (p["n_steps"], p["last_run_status"]) == (2, "FAILED")


def test_pick_gate_has_one_definition():
    """The screener's thresholds and the words a pick's data is described in come
    from config.PICK_GATE (ADR 0061)."""
    import views
    from config import PICK_GATE
    from scoring import screener
    assert screener.MIN_ELIGIBLE_COVERAGE == PICK_GATE["min_eligible_coverage"]
    assert screener.MIN_PRICE_ROWS == PICK_GATE["min_price_rows"]
    assert "uhs" not in views.PICK_GATE_SQL and "integrity_status" in views.PICK_GATE_SQL
    full = views.pick_data({"eligible_coverage": 1.0, "price_rows": 400, "fundamental_coverage": 1.0})
    part = views.pick_data({"eligible_coverage": 0.72, "price_rows": 90, "fundamental_coverage": 0.5})
    assert (full["score"], full["word"], full["quarters"]) == (100, "Complete", 8)
    assert (part["score"], part["word"], part["colour"], part["quarters"]) == (72, "Partial", "amber", 4)
    assert views.pick_data({"eligible_coverage": None}) is None


# ── one registry of areas; a new area cannot be half-wired ──

def test_every_area_is_a_facts_and_verdicts_pair():
    from checks import report, system
    for key, (facts, build) in system.AREAS.items():
        assert callable(facts) and callable(build), key
        assert build(_state()[key]) == [], f"{key}: the clean state must produce no verdict"
    assert set(_state()) == set(system.AREAS), "the test state and the registry list the same areas"
    codes = {v["code"] for v in report.verdicts(_state())}
    assert codes == set()


def test_decay_needs_more_than_noise(monkeypatch):
    """A recent mean below the long-run mean only counts when it is 2+ standard errors below."""
    import factors
    from tools import factor_decay as fd
    tier, key = next((t, k) for t, w in factors.SIGNAL_WEIGHTS.items() for k, x in w.items() if x > 0)
    monkeypatch.setattr(factors, "SIGNAL_WEIGHTS", {tier: {key: factors.SIGNAL_WEIGHTS[tier][key]}})
    noisy = [0.05] * 40 + [0.30, -0.32, 0.25, -0.28, 0.31, -0.30, 0.27, -0.29, 0.26, -0.31, 0.28, -0.30]   # mean ≈ -0.01, huge spread
    gone = [0.05] * 40 + [-0.02, -0.03, -0.01, -0.02, -0.03, -0.02, -0.01, -0.02, -0.03, -0.02, -0.01, -0.02]  # tight and negative
    for series, expected in ((noisy, False), (gone, True)):
        monkeypatch.setattr(fd, "_factor_ic_series", lambda col, t, s=series: [(f"d{i}", x, 50) for i, x in enumerate(s)])
        (row,) = fd.analyze()
        assert row["decayed"] is expected, (series[-3:], row)
