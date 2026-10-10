"""
Fire drills (ADR 0060): every check in the health catalog is broken on purpose
here and must catch it. A check with no drill does not ship — the last test fails.

A check that cannot fail is worse than no check: it reads as "verified" on the
Health page while verifying nothing. Offline: temp DBs built from schema.sql and
synthetic gathered state, never the live DB.
"""
import json
import sqlite3
from datetime import date, timedelta

import pandas as pd
import pytest

import checks
import db
import factors
from checks import CRITICAL, FAIL, PASS, WARN, ranges, report
from config import PICKABLE_TIERS

TODAY = date.today().isoformat()


def _day(n):
    return (date.today() - timedelta(days=n)).isoformat()


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "drill.db"
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA_PATH.read_text())
    c.commit()
    monkeypatch.setattr(db, "DB_PATH", path)
    yield c
    c.close()


def _fires(code, conn):
    conn.commit()
    (v,) = checks.run(only=code)
    return v


def _stocks(conn, n=40, tier="LARGE", sector="Energy"):
    sids = [f"S{i:03d}" for i in range(n)]
    conn.executemany("INSERT INTO stocks (sid, ticker, name, sector, cap_tier) VALUES (?, ?, ?, ?, ?)",
                     [(s, s, s, sector, tier) for s in sids])
    return sids


# ───────────────────────────── data checks ─────────────────────────────

DATA_DRILLS = {}


def drill(code):
    def register(fn):
        DATA_DRILLS[code] = fn
        return fn
    return register


@drill("RANGE")
def _range(conn):
    """Every registered column: a legal value passes its rule, an illegal one fails it."""
    for (table, column), spec in ranges.COLUMNS.items():
        if "in" in spec:
            good, bad = spec["in"][0], "__not_a_legal_value__"
        else:
            lo, hi = ranges.bounds(table, column)
            good, bad = (lo if hi is None else (lo + hi) / 2), lo - 1
        sql = f"SELECT ({ranges.bad_sql(table, column)}) FROM (SELECT ? AS [{column}])"
        assert conn.execute(sql, (bad,)).fetchone()[0] == 1, (table, column, bad)
        assert conn.execute(sql, (good,)).fetchone()[0] == 0, (table, column, good)
        assert not ranges.in_range(table, column, bad) and ranges.in_range(table, column, good)
    # and end to end through the runner
    conn.execute("INSERT INTO stock_prices (sid, date, close) VALUES ('A', ?, -5)", (TODAY,))
    assert _fires("RANGE:stock_prices.close", conn)["status"] == FAIL


@drill("COVERAGE_GAP")
def _coverage(conn):
    """A universe of stocks and an empty table: every coverage gate must fire."""
    _stocks(conn)
    conn.commit()
    gates = [c for c in checks.coverage_checks()]
    assert gates
    for c in gates:
        v = _fires(c["code"], conn)
        assert (v["status"], v["severity"]) == (FAIL, CRITICAL), c["code"]


def _freeze(conn, days, tier=None, broken=None, mode="null"):
    """`days` frozen days of healthy inputs for every tier; on the newest day the
    `broken` screener column of `tier` is nulled (or made constant)."""
    for t, weights in factors.SIGNAL_WEIGHTS.items():
        cols = sorted({factors.SCREENER_COLS[k] for k in weights})
        for d in range(days):
            for i in range(40):
                inputs = {c: float((i * 7 + d) % 11) for c in cols}
                if d == 0 and broken and t == tier:
                    inputs[broken] = None if mode == "null" else 1.0
                conn.execute("INSERT INTO pit_replay_snapshots (snapshot_date, sid, cap_tier, inputs_json, frozen_at) "
                             "VALUES (?, ?, ?, ?, 'x')", (_day(d), f"{t}{i:03d}", t, json.dumps(inputs)))
    conn.execute("INSERT INTO daily_picks (sid, pick_date, cap_tier, final_score) VALUES ('S000', ?, 'LARGE', 0.5)", (TODAY,))


def _reset(conn):
    conn.execute("DELETE FROM pit_replay_snapshots")
    conn.execute("DELETE FROM daily_picks")


@drill("FACTOR_INPUT")
def _factor_input(conn):
    tier = next(iter(factors.SIGNAL_WEIGHTS))
    heavy = max(factors.SIGNAL_WEIGHTS[tier], key=lambda k: abs(factors.SIGNAL_WEIGHTS[tier][k]))
    light = min(factors.SIGNAL_WEIGHTS[tier], key=lambda k: abs(factors.SIGNAL_WEIGHTS[tier][k]))
    pairs = sum(len(w) for w in factors.SIGNAL_WEIGHTS.values())
    # a heavy factor with no value for any stock: act today
    _freeze(conn, 8, tier, broken=factors.SCREENER_COLS[heavy])
    v = _fires("FACTOR_INPUT", conn)
    assert (v["status"], v["severity"], v["n_bad"], v["n_total"]) == (FAIL, CRITICAL, 1, pairs) and heavy in v["sample"]
    # a constant column is caught too, and a light weight only warns
    _reset(conn)
    _freeze(conn, 8, tier, broken=factors.SCREENER_COLS[light], mode="flat")
    v = _fires("FACTOR_INPUT", conn)
    expected = CRITICAL if abs(factors.SIGNAL_WEIGHTS[tier][light]) >= checks.model.HEAVY_WEIGHT else WARN
    assert (v["status"], v["severity"]) == (FAIL, expected) and "same value" in v["sample"]
    # healthy inputs pass, and every wired (tier, factor) was judged
    _reset(conn)
    _freeze(conn, 8)
    v = _fires("FACTOR_INPUT", conn)
    assert (v["status"], v["n_total"]) == (PASS, pairs)
    # a whole tier missing from the freeze is not a pass
    conn.execute("DELETE FROM pit_replay_snapshots WHERE cap_tier = ? AND snapshot_date = ?", (tier, TODAY))
    v = _fires("FACTOR_INPUT", conn)
    assert v["status"] == FAIL and tier in v["sample"]


def test_factor_input_notices_a_missing_freeze(conn):
    """Picks for today but no frozen inputs for today: the check says so instead of passing."""
    _freeze(conn, 8)
    conn.execute("DELETE FROM pit_replay_snapshots WHERE snapshot_date = ?", (TODAY,))
    v = _fires("FACTOR_INPUT", conn)
    assert v["status"] == FAIL and "did not run" in v["sample"]


@drill("PICKS_RESHUFFLED")
def _reshuffled(conn):
    sids = [f"S{i:03d}" for i in range(60)]
    tier = PICKABLE_TIERS[0]
    for i, sid in enumerate(sids):
        conn.execute("INSERT INTO daily_picks (sid, pick_date, cap_tier, final_score) VALUES (?, ?, ?, ?)",
                     (sid, _day(1), tier, i / 60))
        conn.execute("INSERT INTO daily_picks (sid, pick_date, cap_tier, final_score) VALUES (?, ?, ?, ?)",
                     (sid, TODAY, tier, 1 - i / 60))             # the ranking turned upside down
    v = _fires("PICKS_RESHUFFLED", conn)
    assert (v["status"], v["severity"]) == (FAIL, WARN) and tier in v["sample"]
    conn.execute("UPDATE daily_picks SET final_score = 1 - final_score WHERE pick_date = ?", (TODAY,))
    assert _fires("PICKS_RESHUFFLED", conn)["status"] == PASS


@drill("DAILY_PICKS_COVERAGE_LOW")
def _thin(conn):
    for tier in PICKABLE_TIERS:                           # 40 stocks a tier
        conn.executemany("INSERT INTO stocks (sid, ticker, name, sector, cap_tier) VALUES (?, ?, ?, 'Energy', ?)",
                         [(f"{tier}{i}", f"{tier}{i}", "x", tier) for i in range(40)])
    rank = lambda tier, n: conn.executemany(
        "INSERT INTO daily_picks (sid, pick_date, cap_tier, final_score) VALUES (?, ?, ?, 0.5)",
        [(f"{tier}{i}", TODAY, tier) for i in range(n)])
    rank(PICKABLE_TIERS[0], 5)                            # 5 of 40 in one tier, nothing in the others
    v = _fires("DAILY_PICKS_COVERAGE_LOW", conn)
    assert (v["status"], v["severity"], v["n_bad"]) == (FAIL, CRITICAL, len(PICKABLE_TIERS))
    conn.execute("DELETE FROM daily_picks")
    for tier in PICKABLE_TIERS:
        rank(tier, 37)                                    # 37 of 40 ranked is not thin (a flat 100 was the old bar)
    assert _fires("DAILY_PICKS_COVERAGE_LOW", conn)["status"] == PASS


def _targets(conn, targets):
    for sid, pt in targets.items():
        conn.execute("INSERT INTO stock_prices (sid, date, close) VALUES (?, ?, 100)", (sid, TODAY))
        conn.execute("INSERT INTO analyst_consensus (sid, price_target, has_analyst_data, fetched_at) VALUES (?, ?, 1, ?)",
                     (sid, pt, TODAY))


def _price_days(conn, days):
    """days: {date: {sid: (close, volume)}}"""
    _stocks(conn, n=0)
    for d, rows in days.items():
        conn.executemany("INSERT INTO stock_prices (sid, date, close, volume, source) VALUES (?, ?, ?, ?, 'bhavcopy')",
                         [(sid, d, c, v) for sid, (c, v) in rows.items()])


@drill("PRICE_DAY_COPIED")
def _holiday_file_stored_as_a_trading_day(conn):
    conn.executemany("INSERT INTO stocks (sid, ticker, name, sector, cap_tier) VALUES (?, ?, ?, 'Energy', 'LARGE')",
                     [(s, s, s) for s in "ABCD"])
    session = {s: (100.0 + i, 5000 + i) for i, s in enumerate("ABCD")}
    _price_days(conn, {"2026-09-30": {s: (c - 1, v + 7) for s, (c, v) in session.items()},
                       "2026-10-01": session, "2026-10-02": session})          # the holiday repeats 10-01
    v = _fires("PRICE_DAY_COPIED", conn)
    assert (v["status"], v["n_bad"], v["n_total"], v["severity"]) == (FAIL, 4, 4, CRITICAL)


@drill("PRICE_JUMP_UNEXPLAINED")
def _a_split_nobody_recorded(conn):
    conn.executemany("INSERT INTO stocks (sid, ticker, name, sector, cap_tier) VALUES (?, ?, ?, 'Energy', 'SMALL')",
                     [(s, s, s) for s in ("SPLIT", "KNOWN", "CALM")])
    _price_days(conn, {"2026-09-30": {"SPLIT": (500.0, 10), "KNOWN": (500.0, 10), "CALM": (50.0, 10)},
                       "2026-10-01": {"SPLIT": (100.0, 50), "KNOWN": (100.0, 50), "CALM": (51.0, 12)}})
    conn.execute("INSERT INTO corporate_adjustments (sid, ex_date, factor, n_events, inds) VALUES ('KNOWN', '2026-10-01', 0.2, 1, 'SPLIT')")
    v = _fires("PRICE_JUMP_UNEXPLAINED", conn)
    assert (v["status"], v["n_bad"], v["n_total"]) == (FAIL, 1, 3) and "SPLIT" in v["sample"]


@drill("ANALYST_TARGET_IMPLAUSIBLE")
def _implausible_targets(conn):
    _targets(conn, {"HUGE": 900.0, "TINY": 10.0, "SANE": 120.0, "ON_PRICE": 100.0})
    v = _fires("ANALYST_TARGET_IMPLAUSIBLE", conn)
    assert (v["status"], v["n_bad"], v["n_total"]) == (FAIL, 2, 4)


@drill("ANALYST_TARGET_IS_PRICE")
def _targets_are_prices(conn):
    _targets(conn, {"A": 100.2, "B": 99.9, "C": 100.9, "D": 130.0})          # C is a real +0.9%
    v = _fires("ANALYST_TARGET_IS_PRICE", conn)
    assert (v["status"], v["n_bad"], v["n_total"], v["severity"]) == (FAIL, 2, 4, CRITICAL)


def test_one_rule_for_an_implausible_target():
    """The Yahoo sweep, the broker aggregate and the health check share validators.plausibility."""
    from validators.plausibility import PT_CLOSE_RATIO, pt_implausible, pt_implausible_sql
    lo, hi = PT_CLOSE_RATIO
    assert pt_implausible(100 * hi + 1, 100) and pt_implausible(100 * lo - 1, 100)
    assert not pt_implausible(150, 100) and not pt_implausible(None, 100) and not pt_implausible(150, 0)
    assert str(hi) in pt_implausible_sql("a", "b") and str(lo) in pt_implausible_sql("a", "b")


@drill("CONSENSUS_SIGNAL_WITHOUT_ANALYST_ATTRIBUTION")
def _consensus(conn):
    conn.execute("INSERT INTO consensus_signals (sid, snapshot_date, consensus_signal) VALUES ('A', ?, 0.7)", (TODAY,))
    conn.execute("INSERT INTO analyst_consensus (sid, fetched_at) VALUES ('A', ?)", (TODAY,))      # nobody covers it
    assert _fires("CONSENSUS_SIGNAL_WITHOUT_ANALYST_ATTRIBUTION", conn)["status"] == FAIL


@drill("REGULATORY_SECTOR_TAXONOMY_MISMATCH")
def _taxonomy(conn):
    _stocks(conn, n=3, sector="Energy")
    conn.execute("INSERT INTO regulatory_signals (event_id, sector, is_regulatory) VALUES ('e1', 'Not A Sector', 1)")
    assert _fires("REGULATORY_SECTOR_TAXONOMY_MISMATCH", conn)["status"] == FAIL


@pytest.mark.parametrize("code", sorted(DATA_DRILLS))
def test_data_check_fires(code, conn):
    DATA_DRILLS[code](conn)


# ───────────────────────────── system checks ─────────────────────────────
# Each drill is the smallest gathered state in which the check must fire.

def _clean(**parts):
    base = {
        "as_of": TODAY,
        "pipeline": {"last_run_date": TODAY, "last_run_status": "SUCCESS", "n_steps": 3,
                     "failed_steps_today": [], "failed_streaks": []},
        "tables": {"fresh": 5, "stale": [], "outdated": [], "empty": []},
        "watchdog": {"last_run": TODAY + "T15:00:00", "age_hours": 1.0, "healed": 0, "failed": 0, "skipped": 0},
        "feeds": {"rows": [], "verdicts": []},
        "data": {"verdicts": []},
        "integrity": {"n_picks": 100, "rows": []},
        "gates": {"gates": []},
        "dossiers": {"latest_file": "d.json", "n_thesis": 0, "n_failed_validation": 0, "failed_samples": []},
        "endpoints": {"rows": []},
        "factors": {"decay": []},
    }
    return {**base, **parts}


def _feed(**facts):
    """checks.feeds verdicts for one live T1 feed carrying `facts`."""
    from checks.feeds import feed_verdicts
    row = {"feed": "f", "tier": "T1", "status": "production", "canary": "k", "canary_gates": [],
           "canary_last": {"status": "PASS", "symptom": None, "checked_at": pd.Timestamp.now().isoformat()},
           "canary_prev": None, "schedule": ["step:x"], "resilience": "fallback", "serve_stale_days": 1,
           "fallback_plan": None, "notes": None, **facts}
    return {"rows": [row], "verdicts": feed_verdicts([row])}


SYSTEM_DRILLS = {
    "PIPELINE_STEP": _clean(pipeline={"last_run_date": TODAY, "last_run_status": "FAILED", "n_steps": 3,
                                      "failed_steps_today": [{"step": "fetch_x", "error": "boom", "at": "t"}],
                                      "failed_streaks": []}),
    "WATCHDOG": _clean(watchdog={"last_run": _day(3) + "T15:00:00", "age_hours": 72.0, "healed": 0, "failed": 0, "skipped": 0}),
    "HEALTH_CHECK_CRASHED": _clean(feeds={"error": "KeyError: 'x'"}),
    "TABLE_STALE": _clean(tables={"fresh": 4, "stale": [("news_articles", 3.0, 2.0, "x")], "outdated": [], "empty": []}),
    "TABLE_EMPTY": _clean(tables={"fresh": 4, "stale": [], "outdated": [], "empty": ["daily_picks"]}),
    "FEED_PROBE": _clean(feeds=_feed(canary_last={"status": "FAIL", "symptom": "D",
                                                  "checked_at": pd.Timestamp.now().isoformat()})),
    "FEED_VOLUME": _clean(feeds=_feed(volume={"fetch_x": {"stable": True, "ratio": 0.1, "last": 10, "median": 100.0}})),
    "FEED_RECONCILE_FAIL": _clean(feeds=_feed(reconcile={"status": "FAIL", "detail": json.dumps(
        {"agree_share": 0.5, "compared": 20, "against": "a second source", "tolerance": 0.05, "worst": []})})),
    "CHECK_VACUOUS": _clean(data={"verdicts": [checks.verdict("X", "t.c", checks.OK, PASS, code="X", n_total=0,
                                                              theme="correct", why="w", fix="f", message="m", rule="r")]}),
    "PICK_INTEGRITY": _clean(integrity={"n_picks": 100, "rows": [{"sid": "A", "integrity_status": "FAIL", "integrity_reasons": "r"}]}),
    "TRUST_GATE_DORMANT": _clean(gates={"gates": [{"name": "Plausibility", "last": "2026-05-31", "dormant": True}]}),
    "DOSSIER_HALLUCINATION": _clean(dossiers={"latest_file": "d.json", "n_thesis": 15, "n_failed_validation": 2,
                                              "failed_samples": [{"ticker": "A", "n_violations": 1, "sample": "thesis: '16.5%'"}]}),
    "COCKPIT_ENDPOINT": _clean(endpoints={"rows": [{"endpoint": "quarterly", "status": "FAILED", "error": "[CRITICAL] gaps"}]}),
    "FACTOR_DECAY": _clean(factors={"decay": [{"weight_key": "k", "tier": "LARGE", "decayed": True,
                                               "ic_all": 0.03, "ic_recent": -0.01}]}),
}


@pytest.mark.parametrize("code", sorted(SYSTEM_DRILLS))
def test_system_check_fires(code):
    fired = {i["code"] for group in report.issues(SYSTEM_DRILLS[code]) for i in group}
    assert fired == {code}, f"{code}: the drill fired {fired or 'nothing'}"
    assert all(group == [] for group in report.issues(_clean())), "the clean state must be silent"


# ───────────────────────────── re-graded paths (2026-10-10) ─────────────────────────────
# The severity of each lower grade is decided in the check; these prove the lower path
# still fires, and that the full-severity path next to it still pages.

def _fired(state):
    return [i for group in report.issues(state) for i in group]


def test_a_shadow_job_failing_for_days_is_a_warning_not_a_page():
    from config import NON_PAGING_STEPS
    step = next(iter(NON_PAGING_STEPS))
    pipe = {"last_run_date": TODAY, "last_run_status": "FAILED", "n_steps": 3,
            "failed_steps_today": [{"step": step, "error": "boom", "at": "t"}],
            "failed_streaks": [{"step": step, "days": 9, "sample_error": "boom"}]}
    (i,) = _fired(_clean(pipeline=pipe))
    assert (i["code"], i["target"], i["severity"]) == ("PIPELINE_STEP", step, WARN)
    pipe["failed_streaks"][0]["step"] = pipe["failed_steps_today"][0]["step"] = "fetch_x"
    (i,) = _fired(_clean(pipeline=pipe))
    assert i["severity"] == CRITICAL                              # any other step on a streak still pages


def test_non_paging_steps_name_real_steps():
    import feeds
    from config import NON_PAGING_STEPS, PIPELINE_STEPS
    known = {s["name"] for s in PIPELINE_STEPS} | {step for logs in feeds._run_sh_logs().values() for step, _ in logs}
    run_sh = (db.PROJECT_ROOT / "run.sh").read_text()
    for name, why in NON_PAGING_STEPS.items():
        assert why and (name in known or f"logged {name} " in run_sh), f"{name} is not a step or a run.sh job"


def test_an_empty_table_of_a_feed_not_on_the_picks_path_is_graded_down(monkeypatch):
    import feeds
    monkeypatch.setitem(feeds.FEEDS, "_t_probation", {"status": "probation", "writes": ["_t_prob_tbl"]})
    monkeypatch.setitem(feeds.FEEDS, "_t_candidate", {"status": "candidate", "writes": ["_t_cand_tbl"]})
    assert checks.empty_table_severity("_t_prob_tbl") == WARN
    assert checks.empty_table_severity("_t_cand_tbl") == checks.INFO
    monkeypatch.setitem(feeds.FEEDS, "_t_prod", {"status": "production", "writes": ["_t_prob_tbl"]})
    assert checks.empty_table_severity("_t_prob_tbl") == CRITICAL   # one production writer = on the path
    assert checks.empty_table_severity("_file_duckdb_replica") == WARN   # optional file: readers fall back
    assert checks.empty_table_severity("_file_dossiers") == CRITICAL
    (i,) = _fired(_clean(tables={"fresh": 4, "stale": [], "outdated": [], "empty": ["_file_duckdb_replica"]}))
    assert (i["code"], i["severity"]) == ("TABLE_EMPTY", WARN)


def test_a_volume_spike_is_info_only_while_a_backfill_is_declared(tmp_path, monkeypatch):
    import time
    from checks import feeds as cf
    spike = {"fetch_x": {"stable": True, "ratio": 20.0, "last": 4000, "median": 200.0}}
    marker = tmp_path / "backfill_active"
    monkeypatch.setattr(cf, "BACKFILL_MARKER", marker)
    assert not cf.backfill_active()                                       # no marker
    (i,) = _fired(_clean(feeds=_feed(volume=spike)))
    assert (i["code"], i["severity"]) == ("FEED_VOLUME", WARN)
    marker.write_text(str(int(time.time()) - 3600))
    assert cf.backfill_active()
    (i,) = _fired(_clean(feeds=_feed(volume=spike)))
    assert (i["code"], i["severity"]) == ("FEED_VOLUME", checks.INFO)
    marker.write_text(str(int(time.time()) - 30 * 3600))                  # window long over: back to WARN
    assert not cf.backfill_active()
    (i,) = _fired(_clean(feeds=_feed(volume=spike)))
    assert i["severity"] == WARN
    monkeypatch.setitem(spike["fetch_x"], "ratio", 0.1)                   # a drop is never excused by a backfill
    marker.write_text(str(int(time.time())))
    (i,) = _fired(_clean(feeds=_feed(volume=spike)))
    assert i["severity"] == CRITICAL


def test_yfinance_fallback_drops_no_trade_bars():
    from sources import yfinance_prices as yp
    idx = pd.to_datetime(["2026-10-07", "2026-10-08", "2026-10-09"])
    h = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": [0, float("nan"), 120]}, index=idx)
    rows = yp._normalize("S", ".BO", h)
    assert [r["date"] for r in rows] == ["2026-10-09"] and rows[0]["volume"] == 120
    assert yp._normalize("S", ".BO", h.iloc[:2]) == []


# ───────────────────────────── no check without a drill ─────────────────────────────

def test_every_check_has_a_drill():
    catalog = set(report.SYSTEM_CHECKS) | {c.get("family") or c["code"] for c in checks.all_checks()}
    drilled = set(SYSTEM_DRILLS) | set(DATA_DRILLS)
    assert catalog - drilled == set(), f"checks with no proof they can fire: {sorted(catalog - drilled)}"
    assert drilled - catalog == set(), f"drills for checks that no longer exist: {sorted(drilled - catalog)}"


# ───────────────────────────── retired checks live on as tests ─────────────────────────────
# Rules that can only break when code changes are checked when code changes (ADR 0060).

def test_pick_gate_makes_a_priceless_or_thin_pick_impossible():
    """Retired DAILY_PICK_NO_PRICES / DAILY_PICK_THIN_SIGNAL_COVERAGE: the gate that
    writes daily_picks refuses these stocks, so the daily checks could never fire."""
    from scoring import screener
    df = pd.DataFrame({
        "sid": ["OK", "NO_PRICES", "THIN", "NO_FUNDAMENTALS"],
        "eligible_coverage": [1.0, 1.0, 0.3, 1.0], "weight_coverage": [1.0, 1.0, 0.3, 1.0],
        "price_rows": [500, 0, 500, 500], "fundamental_coverage": [1.0, 1.0, 1.0, 0.1],
    })
    assert screener._pick_eligible(df).tolist() == [True, False, False, False]


def test_rank_is_unique_within_a_tier_by_construction(conn):
    """Retired DAILY_PICKS_RANK_DUPLICATE: scoring ranks with method='first'."""
    from scoring import screener
    df = pd.DataFrame({"sid": list("abcd"), "cap_tier": [PICKABLE_TIERS[0]] * 4, "penalty": [0.0] * 4,
                       **{col: [1.0, 1.0, 1.0, 1.0] for col in set(factors.SCREENER_COLS.values())}})
    ranks = screener.score_universe(df)["rank"].tolist()
    assert sorted(ranks) == [1, 2, 3, 4]                         # four identical scores, four distinct ranks


def test_growth_is_clipped_before_the_dossier_prompt():
    """Retired EXTREME_GROWTH_PCT_IN_TOP_PICKS: the clip it watched over."""
    from output import dossier
    assert dossier._clip_growth(2941.0) == f"{dossier._GROWTH_DISPLAY_CAP:.0f}+"
    assert dossier._clip_growth(12.34) == 12.3 and dossier._clip_growth(None) is None


def test_best_effort_table_is_tolerated_not_alarmed():
    table = next(iter(db.BEST_EFFORT_STALE))
    actionable, tolerated = report.issues(_clean(tables={"fresh": 4, "stale": [], "outdated": [(table, 40.0, 3.0, "x")], "empty": []}))
    assert actionable == [] and [i["id"] for i in tolerated] == [f"TABLE_STALE:{table}"]


# ───────────────────────────── checked before the picks go out ─────────────────────────────

def test_picks_email_warns_before_sending(conn):
    """A dead factor input reaches the reader as a banner on the picks email, not 20 minutes later."""
    from output import email_sender
    tier = next(iter(factors.SIGNAL_WEIGHTS))
    heavy = max(factors.SIGNAL_WEIGHTS[tier], key=lambda k: abs(factors.SIGNAL_WEIGHTS[tier][k]))
    _freeze(conn, 8, tier, broken=factors.SCREENER_COLS[heavy])
    conn.commit()
    warnings = email_sender.model_warnings()
    assert any(w["severity"] == CRITICAL and heavy in w["detail"] for w in warnings)
    banner = email_sender._warning_banner(warnings)
    assert "Read before acting" in banner and heavy in banner
    assert email_sender._warning_banner([]) == ""


def test_pre_send_checks_that_cannot_run_are_a_warning(monkeypatch):
    from output import email_sender
    monkeypatch.setattr(checks, "run", lambda **kw: 1 / 0)
    (w,) = email_sender.model_warnings()
    assert w["severity"] == WARN and "could not run" in w["message"]


def test_the_freeze_runs_before_the_email():
    """The pre-send checks read the frozen inputs, so the derived order must put the freeze first."""
    import graph
    from config import PIPELINE_STEPS
    order = graph.order(PIPELINE_STEPS)
    assert order.index("screener") < order.index("pit_replay_freeze") < order.index("email")
