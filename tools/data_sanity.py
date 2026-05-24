"""
Alpha Signal v2 — Data Sanity Audit

Catches the class of bug freshness/error checks miss: producers ran cleanly,
wrote rows, but the rows are semantically wrong.

Examples shipped today:
  - analyst_consensus.price_target == stock_prices.close (PT feed misread)
  - pt_revision_yoy actually measures price returns, not consensus revisions
  - target_horizon dropped from dossier (caught by SCHEMA check)

Pattern: each check returns either None (pass) or a dict with severity,
n_violations, sample, and a one-line message. The health report aggregates
violations into CRITICAL / WARN issues alongside freshness/pipeline.

Adding a check: append a dict to CHECKS below. Two forms supported —
  1. SQL form: provide `sql` returning a single row with `n_bad` (plus optional
     `n_total`, `sample`). The framework computes pct + chooses severity.
  2. Function form: provide `fn` that returns either None or a result dict.

Usage:
    python -m tools.data_sanity                # run all, print report
    python -m tools.data_sanity --json         # machine-readable
    python -m tools.data_sanity --check CODE   # one check by code
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import get_db, read_sql


# ─────────────────────── Severity rules ───────────────────────

CRITICAL = "CRITICAL"
WARN = "WARN"
INFO = "INFO"


def _severity_for(pct, critical_pct=10, warn_pct=1):
    """Default severity classifier — % of rows violating the invariant."""
    if pct >= critical_pct:
        return CRITICAL
    if pct >= warn_pct:
        return WARN
    return INFO


# ─────────────────────── Check helpers ───────────────────────


def _run_sql_check(check, conn):
    """SQL-form check. Returns result dict or None."""
    df = read_sql(check["sql"])
    if df.empty:
        return None
    row = df.iloc[0].to_dict()
    n_bad = int(row.get("n_bad", 0) or 0)
    if n_bad == 0:
        return None
    n_total = int(row.get("n_total") or 0)
    pct = (100.0 * n_bad / n_total) if n_total > 0 else None
    sample = row.get("sample")

    severity = check.get("severity")
    if severity is None and pct is not None:
        severity = _severity_for(pct,
                                 critical_pct=check.get("critical_pct", 10),
                                 warn_pct=check.get("warn_pct", 1))
    elif severity is None:
        severity = WARN

    return {
        "code": check["code"],
        "severity": severity,
        "table": check.get("table"),
        "column": check.get("column"),
        "message": check["message"],
        "n_violations": n_bad,
        "n_total": n_total,
        "pct_violations": round(pct, 1) if pct is not None else None,
        "sample": sample,
    }


def _generic_coverage_checks():
    """Auto-generated coverage checks for every per-sid table in COVERAGE_THRESHOLDS.

    Avoids the maintenance burden of hand-writing a sanity-check row each time
    a new per-stock signal table ships. If db.COVERAGE_THRESHOLDS lists the
    table, this generator emits a CRITICAL/WARN at the same thresholds.
    """
    from db import COVERAGE_THRESHOLDS
    out = []
    for tbl, (gap_pct, severe_pct) in COVERAGE_THRESHOLDS.items():
        # critical_pct/warn_pct are PERCENT OF UNIVERSE MISSING — invert from
        # the COVERAGE_THRESHOLDS form which is "percent of universe present".
        out.append({
            "code": f"COVERAGE_GAP_AUTO_{tbl.upper()}",
            "table": tbl,
            "column": "sid",
            "message": f"{tbl} per-stock coverage below {gap_pct:.0f}% (severe < {severe_pct:.0f}%)",
            "critical_pct": 100 - severe_pct,
            "warn_pct": 100 - gap_pct,
            "sql": f"""
                SELECT
                    (SELECT COUNT(*) FROM stocks WHERE sid NOT IN (SELECT DISTINCT sid FROM {tbl})) AS n_bad,
                    (SELECT COUNT(*) FROM stocks) AS n_total,
                    (SELECT sid || ' (' || ticker || ', ' || cap_tier || ')' FROM stocks
                     WHERE sid NOT IN (SELECT DISTINCT sid FROM {tbl}) LIMIT 1) AS sample
            """,
        })
    return out


def _run_fn_check(check):
    """Function-form check. fn must return None or a result dict."""
    result = check["fn"]()
    if result is None:
        return None
    # Stamp the standard fields
    result.setdefault("code", check["code"])
    result.setdefault("severity", check.get("severity", WARN))
    result.setdefault("table", check.get("table"))
    result.setdefault("column", check.get("column"))
    result.setdefault("message", check["message"])
    return result


# ─────────────────────── Check definitions ───────────────────────

CHECKS = [
    # ═══════════════════════════════════════════════════════════════════
    # Data-feed integrity — wrong source, mislabeled column
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "PT_EQUALS_PRICE",
        "table": "analyst_consensus",
        "column": "price_target",
        "message": "analyst PT equals current close (feed misread — see HANDOFF 2026-05-22)",
        "critical_pct": 25,
        "warn_pct": 5,
        "sql": """
            WITH latest_px AS (
                SELECT sid, close FROM stock_prices
                WHERE (sid, date) IN (SELECT sid, MAX(date) FROM stock_prices GROUP BY sid)
            )
            SELECT
                SUM(CASE WHEN ABS(ac.price_target - lp.close) < 1.0 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT ac2.sid || ': PT=' || ROUND(ac2.price_target,1) || ' / close=' || ROUND(lp2.close,1)
                 FROM analyst_consensus ac2 JOIN latest_px lp2 ON ac2.sid = lp2.sid
                 WHERE ABS(ac2.price_target - lp2.close) < 1.0 AND ac2.has_analyst_data=1 LIMIT 1) AS sample
            FROM analyst_consensus ac
            JOIN latest_px lp ON ac.sid = lp.sid
            WHERE ac.has_analyst_data = 1 AND ac.price_target IS NOT NULL
        """,
    },
    {
        "code": "FORECAST_HISTORY_IS_PRICE_HISTORY",
        "table": "forecast_history",
        "column": "value (metric=price)",
        "message": "forecast_history.value (metric=price) matches stock_prices.close — not a real PT history",
        "critical_pct": 50,
        "warn_pct": 10,
        # Strengthened 2026-05-23: original check JOINed on (sid, date) — same date
        # — and the contamination pattern bypasses it (fh.date=2025-12-27,
        # sp.date=2026-05-23, but values match because the latest fh.value is
        # being overwritten with today's lastPrice). Now compares each stock's
        # LATEST fh.value vs LATEST sp.close regardless of date. If real PTs,
        # latest fh.value should be +12-25% above latest sp.close (sell-side
        # optimism). If matches within ₹1, the value is contaminated.
        "sql": """
            WITH latest_fh AS (
                SELECT sid, value, MAX(date) AS fh_date
                FROM forecast_history WHERE metric='price' GROUP BY sid
            ),
            latest_sp AS (
                SELECT sid, close, MAX(date) AS sp_date
                FROM stock_prices GROUP BY sid
            )
            SELECT
                SUM(CASE WHEN ABS(lf.value - ls.close) < 1.0 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT lf2.sid || ': fh.value=' || lf2.value || ' (' || lf2.fh_date || ') / sp.close=' || ls2.close || ' (' || ls2.sp_date || ')'
                 FROM latest_fh lf2 JOIN latest_sp ls2 ON lf2.sid=ls2.sid
                 WHERE ABS(lf2.value - ls2.close) < 1.0 LIMIT 1) AS sample
            FROM latest_fh lf JOIN latest_sp ls ON lf.sid = ls.sid
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Schema correctness — PT data shape
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "FORECAST_HISTORY_NON_YEAREND_PRICE",
        "table": "forecast_history",
        "column": "date (metric=price)",
        "message": "forecast_history.price has non-year-end entries (Tickertape stores PT only at year-end)",
        "critical_pct": 5,
        "warn_pct": 1,
        "sql": """
            SELECT
                SUM(CASE WHEN substr(date, 6, 2) NOT IN ('12') AND date >= '2022-01-01' THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT sid || '@' || date FROM forecast_history
                 WHERE metric='price' AND substr(date,6,2) NOT IN ('12') AND date >= '2022-01-01' LIMIT 1) AS sample
            FROM forecast_history WHERE metric='price'
        """,
    },
    {
        "code": "ACS_SNAPSHOTS_MISSING_RECENT_MONTH",
        "table": "analyst_consensus_snapshots",
        "column": "snapshot_date",
        "message": "Current month has no analyst_consensus_snapshots rows — monthly cron may not have fired",
        "severity": WARN,
        "sql": """
            SELECT
                CASE WHEN (SELECT COUNT(*) FROM analyst_consensus_snapshots
                           WHERE snapshot_date >= strftime('%Y-%m-01', 'now', '-1 month')) < 100
                     THEN 1 ELSE 0 END AS n_bad,
                1 AS n_total
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Bounds violations — value outside legal range
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "PIOTROSKI_OUT_OF_RANGE",
        "table": "daily_snapshots",
        "column": "piotroski_f",
        "message": "piotroski_f outside [0, 9]",
        "critical_pct": 5,
        "sql": """SELECT
                    SUM(CASE WHEN piotroski_f < 0 OR piotroski_f > 9 THEN 1 ELSE 0 END) AS n_bad,
                    COUNT(*) AS n_total,
                    MAX(piotroski_f) AS sample
                  FROM daily_snapshots WHERE piotroski_f IS NOT NULL""",
    },
    {
        "code": "FINAL_SCORE_OUT_OF_RANGE",
        "table": "daily_picks",
        "column": "final_score",
        "message": "final_score outside [0, 1]",
        "critical_pct": 1,
        "sql": """SELECT
                    SUM(CASE WHEN final_score < 0 OR final_score > 1 THEN 1 ELSE 0 END) AS n_bad,
                    COUNT(*) AS n_total,
                    MAX(final_score) AS sample
                  FROM daily_picks WHERE final_score IS NOT NULL""",
    },
    {
        "code": "BUY_PCT_OUT_OF_RANGE",
        "table": "analyst_consensus",
        "column": "buy_pct",
        "message": "buy_pct outside [0, 100]",
        "critical_pct": 1,
        "sql": """SELECT
                    SUM(CASE WHEN buy_pct < 0 OR buy_pct > 100 THEN 1 ELSE 0 END) AS n_bad,
                    COUNT(*) AS n_total
                  FROM analyst_consensus WHERE buy_pct IS NOT NULL""",
    },
    {
        "code": "PT_UPSIDE_OUT_OF_RANGE",
        "table": "consensus_signals",
        "column": "pt_upside",
        # consensus_signals.pt_upside is in PERCENT units (signals/consensus.py
        # stores `(pt/close - 1) * 100`). PIT table uses ratio units (no ×100).
        # Bounds here are for the percent form.
        "message": "pt_upside outside [-100%, +500%]",
        "critical_pct": 1,
        "sql": """SELECT
                    SUM(CASE WHEN pt_upside < -100 OR pt_upside > 500 THEN 1 ELSE 0 END) AS n_bad,
                    COUNT(*) AS n_total,
                    MAX(pt_upside) AS sample
                  FROM consensus_signals WHERE pt_upside IS NOT NULL""",
    },
    {
        "code": "M_SCORE_OUT_OF_RANGE",
        "table": "forensic_scores",
        "column": "m_score",
        "message": "m_score outside [-20, 20]",
        "critical_pct": 5,
        "sql": """SELECT
                    SUM(CASE WHEN m_score < -20 OR m_score > 20 THEN 1 ELSE 0 END) AS n_bad,
                    COUNT(*) AS n_total
                  FROM forensic_scores WHERE m_score IS NOT NULL""",
    },
    {
        "code": "Z_SCORE_OUT_OF_RANGE",
        "table": "forensic_scores",
        "column": "z_score",
        "message": "z_score outside [-50, 200]",
        "critical_pct": 5,
        "sql": """SELECT
                    SUM(CASE WHEN z_score < -50 OR z_score > 200 THEN 1 ELSE 0 END) AS n_bad,
                    COUNT(*) AS n_total
                  FROM forensic_scores WHERE z_score IS NOT NULL""",
    },
    {
        "code": "PROMOTER_PCT_OUT_OF_RANGE",
        "table": "shareholding",
        "column": "promoter_pct",
        "message": "promoter_pct outside [0, 100]",
        "critical_pct": 1,
        "sql": """SELECT SUM(CASE WHEN promoter_pct < 0 OR promoter_pct > 100 THEN 1 ELSE 0 END) AS n_bad,
                         COUNT(*) AS n_total
                  FROM shareholding WHERE promoter_pct IS NOT NULL""",
    },
    {
        "code": "PLEDGE_PCT_OUT_OF_RANGE",
        "table": "shareholding",
        "column": "pledge_pct",
        "message": "pledge_pct outside [0, 100]",
        "critical_pct": 1,
        "sql": """SELECT SUM(CASE WHEN pledge_pct < 0 OR pledge_pct > 100 THEN 1 ELSE 0 END) AS n_bad,
                         COUNT(*) AS n_total
                  FROM shareholding WHERE pledge_pct IS NOT NULL""",
    },
    {
        "code": "MOM_OUT_OF_RANGE",
        "table": "daily_snapshots",
        "column": "mom_6m / mom_12m",
        "message": "risk-adjusted momentum outside [-100, 100]",
        "critical_pct": 2,
        "sql": """SELECT
                    SUM(CASE WHEN mom_6m < -100 OR mom_6m > 100 OR mom_12m < -100 OR mom_12m > 100 THEN 1 ELSE 0 END) AS n_bad,
                    COUNT(*) AS n_total
                  FROM daily_snapshots WHERE mom_6m IS NOT NULL OR mom_12m IS NOT NULL""",
    },
    {
        "code": "CLOSE_PRICE_BAD",
        "table": "stock_prices",
        "column": "close",
        "message": "stock_prices.close ≤ 0 (impossible)",
        "critical_pct": 0.1,
        "sql": """SELECT SUM(CASE WHEN close <= 0 THEN 1 ELSE 0 END) AS n_bad, COUNT(*) AS n_total
                  FROM stock_prices""",
    },

    # ═══════════════════════════════════════════════════════════════════
    # Distribution sanity — column should have spread / non-degenerate
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "PT_UPSIDE_DEGENERATE",
        "table": "consensus_signals",
        "column": "pt_upside",
        # 1% absolute threshold (consensus_signals uses % units, so 1% = real-world 0.01)
        "message": "pt_upside is near-zero for >80% of universe (PT data dead)",
        "critical_pct": 80,
        "warn_pct": 50,
        "sql": """
            WITH latest AS (
                SELECT * FROM consensus_signals
                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM consensus_signals)
            )
            SELECT
                SUM(CASE WHEN ABS(pt_upside) < 1.0 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total
            FROM latest WHERE pt_upside IS NOT NULL
        """,
    },
    {
        "code": "FINAL_SCORE_NO_SPREAD",
        "table": "daily_picks",
        "column": "final_score",
        "message": "final_score std < 0.05 — ranker has degenerated",
        "severity": CRITICAL,
        "sql": """
            SELECT
                CASE WHEN (SELECT 1 FROM (
                    SELECT AVG((final_score - mean) * (final_score - mean)) AS var FROM (
                        SELECT final_score, (SELECT AVG(final_score) FROM daily_picks WHERE pick_date=(SELECT MAX(pick_date) FROM daily_picks)) AS mean
                        FROM daily_picks WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
                    )
                ) WHERE var < 0.0025) THEN 1 ELSE 0 END AS n_bad,
                1 AS n_total
        """,
    },
    {
        "code": "PIOTROSKI_NO_SPREAD",
        "table": "daily_snapshots",
        "column": "piotroski_f",
        "message": "piotroski_f distribution collapsed (≥80% on single integer)",
        "severity": CRITICAL,
        "sql": """
            WITH latest AS (
                SELECT piotroski_f FROM daily_snapshots
                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots)
                  AND piotroski_f IS NOT NULL
            ),
            modes AS (
                SELECT piotroski_f, COUNT(*) AS n FROM latest GROUP BY piotroski_f ORDER BY n DESC LIMIT 1
            )
            SELECT
                CASE WHEN (SELECT 100.0 * (SELECT n FROM modes) / (SELECT COUNT(*) FROM latest)) >= 80 THEN 1 ELSE 0 END AS n_bad,
                1 AS n_total
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Coverage / cardinality — table should have rows / dates as expected
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "DAILY_PICKS_COVERAGE_LOW",
        "table": "daily_picks",
        "column": "—",
        "message": "Latest daily_picks has <100 rows per tier — screener output thin",
        "severity": CRITICAL,
        "sql": """
            SELECT SUM(CASE WHEN c < 100 THEN 1 ELSE 0 END) AS n_bad, 3 AS n_total
            FROM (
                SELECT cap_tier, COUNT(*) AS c
                FROM daily_picks WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
                GROUP BY cap_tier
            )
        """,
    },
    {
        "code": "DAILY_PICKS_BAD_TIER",
        "table": "daily_picks",
        "column": "cap_tier",
        "message": "cap_tier outside {LARGE, MID, SMALL}",
        "critical_pct": 1,
        "sql": """SELECT SUM(CASE WHEN cap_tier NOT IN ('LARGE','MID','SMALL') THEN 1 ELSE 0 END) AS n_bad,
                         COUNT(*) AS n_total
                  FROM daily_picks WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)""",
    },
    {
        "code": "DAILY_PICKS_ORPHAN_SID",
        "table": "daily_picks",
        "column": "sid",
        "message": "daily_picks references a sid not in stocks table",
        "critical_pct": 0.1,
        "sql": """SELECT
                    SUM(CASE WHEN s.sid IS NULL THEN 1 ELSE 0 END) AS n_bad,
                    COUNT(*) AS n_total,
                    (SELECT dp2.sid FROM daily_picks dp2 LEFT JOIN stocks s2 ON dp2.sid=s2.sid
                     WHERE s2.sid IS NULL AND dp2.pick_date=(SELECT MAX(pick_date) FROM daily_picks) LIMIT 1) AS sample
                  FROM daily_picks dp LEFT JOIN stocks s ON dp.sid = s.sid
                  WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)""",
    },
    {
        "code": "DAILY_PICKS_RANK_DUPLICATE",
        "table": "daily_picks",
        "column": "rank",
        "message": "Duplicate (pick_date, cap_tier, rank) — rank not unique within tier",
        "critical_pct": 0.05,
        "warn_pct": 0.01,
        "sql": """
            SELECT
                COALESCE((SELECT SUM(n-1) FROM (
                    SELECT cap_tier, rank, COUNT(*) AS n
                    FROM daily_picks WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
                    GROUP BY cap_tier, rank HAVING COUNT(*) > 1
                )), 0) AS n_bad,
                (SELECT COUNT(*) FROM daily_picks WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)) AS n_total,
                (SELECT cap_tier || ' rank ' || rank || ' shared by ' || COUNT(*) || ' stocks'
                 FROM daily_picks WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
                 GROUP BY cap_tier, rank HAVING COUNT(*) > 1 ORDER BY COUNT(*) DESC LIMIT 1) AS sample
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Null / completeness — critical columns shouldn't be all-null
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "DAILY_SNAPSHOTS_ALL_NULL_PIOTROSKI",
        "table": "daily_snapshots",
        "column": "piotroski_f",
        "message": "piotroski_f null rate elevated for today's snapshots",
        "critical_pct": 80,
        "warn_pct": 50,
        "sql": """
            WITH latest AS (
                SELECT piotroski_f FROM daily_snapshots
                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots)
            )
            SELECT SUM(CASE WHEN piotroski_f IS NULL THEN 1 ELSE 0 END) AS n_bad,
                   COUNT(*) AS n_total
            FROM latest
        """,
    },
    {
        "code": "PIOTROSKI_F_SUM_MISMATCH",
        "table": "piotroski_scores",
        "column": "f_score",
        "message": "f_score doesn't equal sum of 9 component flags",
        "critical_pct": 5,
        "sql": """
            SELECT
                SUM(CASE WHEN f_score != (
                    COALESCE(roa_positive,0)+COALESCE(cfo_positive,0)+COALESCE(roa_improving,0)+
                    COALESCE(accruals_quality,0)+COALESCE(leverage_down,0)+COALESCE(liquidity_up,0)+
                    COALESCE(no_dilution,0)+COALESCE(gross_margin_up,0)+COALESCE(asset_turnover_up,0)
                ) THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total
            FROM piotroski_scores
            WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM piotroski_scores)
              AND f_score IS NOT NULL
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Cross-table consistency
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "ANALYST_CONSENSUS_NEGATIVE_EPS_GROWTH_BUT_BUY",
        "table": "analyst_consensus",
        "column": "—",
        "message": "Sanity: many stocks with negative EPS growth flagged 100% buy (possible logic flip)",
        "severity": INFO,
        "sql": """
            SELECT
                SUM(CASE WHEN eps_growth_pct < -20 AND buy_pct = 100 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total
            FROM analyst_consensus WHERE has_analyst_data = 1
        """,
    },
    {
        "code": "DAILY_SNAPSHOTS_DATE_DRIFT",
        "table": "daily_snapshots",
        "column": "snapshot_date",
        "message": "daily_snapshots latest date doesn't match daily_picks latest date",
        "severity": WARN,
        "sql": """
            SELECT
                CASE WHEN (SELECT MAX(snapshot_date) FROM daily_snapshots) != (SELECT MAX(pick_date) FROM daily_picks)
                     THEN 1 ELSE 0 END AS n_bad,
                1 AS n_total,
                (SELECT MAX(snapshot_date) FROM daily_snapshots) || ' vs ' || (SELECT MAX(pick_date) FROM daily_picks) AS sample
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # LLM dossier — schema + validation
    # ═══════════════════════════════════════════════════════════════════
    # (Existing dossier validation already runs at write-time and the health
    # report already reports DOSSIER_HALLUCINATION. We don't double-count it.)

    # ═══════════════════════════════════════════════════════════════════
    # Output-quality — pick is only as good as the data behind it
    # ═══════════════════════════════════════════════════════════════════
    # 2026-05-23: ANO ranked #1 SMALL with zero price rows and only 2 of 7
    # signals (one a default 50.0). Freshness watchdog said FRESH because
    # stock_prices.MAX(date) was current — the per-stock coverage hole was
    # invisible. The checks below catch that class of bug at the output layer.
    {
        "code": "DAILY_PICK_NO_PRICES",
        "table": "daily_picks",
        "column": "sid",
        "message": "Top-ranked stock has zero rows in stock_prices",
        "severity": CRITICAL,
        "sql": """
            WITH latest AS (
                SELECT sid, cap_tier, rank FROM daily_picks
                WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
                  AND rank <= 20
            )
            SELECT
                SUM(CASE WHEN sp.cnt IS NULL OR sp.cnt = 0 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT l.cap_tier || ' rank ' || l.rank || ': ' || l.sid
                 FROM latest l LEFT JOIN (
                    SELECT sid, COUNT(*) AS cnt FROM stock_prices WHERE close > 0 GROUP BY sid
                 ) sp2 ON l.sid = sp2.sid
                 WHERE sp2.cnt IS NULL OR sp2.cnt = 0 LIMIT 1) AS sample
            FROM latest l
            LEFT JOIN (
                SELECT sid, COUNT(*) AS cnt FROM stock_prices WHERE close > 0 GROUP BY sid
            ) sp ON l.sid = sp.sid
        """,
    },
    {
        "code": "DAILY_PICK_THIN_SIGNAL_COVERAGE",
        "table": "daily_picks",
        "column": "—",
        "message": "Top picks scored on <4 of 8 signals (rank inflated by missing-data normalization)",
        "critical_pct": 25,
        "warn_pct": 10,
        "sql": """
            WITH latest_picks AS (
                SELECT sid, cap_tier, rank FROM daily_picks
                WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
                  AND rank <= 50
            ),
            signal_counts AS (
                SELECT
                    lp.sid, lp.cap_tier, lp.rank,
                    (CASE WHEN ps.f_score IS NOT NULL THEN 1 ELSE 0 END +
                     CASE WHEN ac.accruals_signal IS NOT NULL THEN 1 ELSE 0 END +
                     CASE WHEN cs.consensus_signal IS NOT NULL THEN 1 ELSE 0 END +
                     CASE WHEN pr.promoter_signal IS NOT NULL THEN 1 ELSE 0 END +
                     CASE WHEN sm.smart_money_score IS NOT NULL THEN 1 ELSE 0 END +
                     CASE WHEN sp.cnt > 100 THEN 1 ELSE 0 END +    /* momentum + earnings_yield + b/p */
                     CASE WHEN sp.cnt > 100 THEN 1 ELSE 0 END +
                     CASE WHEN sp.cnt > 100 AND abs.total_equity IS NOT NULL THEN 1 ELSE 0 END) AS n_signals
                FROM latest_picks lp
                LEFT JOIN (SELECT sid, f_score FROM piotroski_scores WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM piotroski_scores)) ps ON lp.sid = ps.sid
                LEFT JOIN (SELECT sid, accruals_signal FROM accruals_scores WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM accruals_scores)) ac ON lp.sid = ac.sid
                LEFT JOIN (SELECT sid, consensus_signal FROM consensus_signals WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM consensus_signals)) cs ON lp.sid = cs.sid
                LEFT JOIN (SELECT sid, promoter_signal FROM promoter_signals WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM promoter_signals)) pr ON lp.sid = pr.sid
                LEFT JOIN (SELECT sid, smart_money_score FROM smart_money_scores WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM smart_money_scores)) sm ON lp.sid = sm.sid
                LEFT JOIN (SELECT sid, COUNT(*) AS cnt FROM stock_prices WHERE close > 0 GROUP BY sid) sp ON lp.sid = sp.sid
                LEFT JOIN (SELECT sid, MAX(total_equity) AS total_equity FROM annual_balance_sheet GROUP BY sid) abs ON lp.sid = abs.sid
            )
            SELECT
                SUM(CASE WHEN n_signals < 4 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT cap_tier || ' rank ' || rank || ': ' || sid || ' (' || n_signals || '/8 signals)'
                 FROM signal_counts WHERE n_signals < 4 ORDER BY rank LIMIT 1) AS sample
            FROM signal_counts
        """,
    },
    {
        "code": "SCORE_TABLE_DEFAULT_PROLIFERATION",
        "table": "smart_money_scores",
        "column": "smart_money_score",
        "message": "smart_money_score = 50.0 for >30% of universe (default-value leak from missing inputs)",
        "critical_pct": 30,
        "warn_pct": 15,
        # The 2026-05-23 bug: _minmax_by_tier seeded all stocks at 50.0, so
        # stocks with no bulk-deals AND no delivery data came out at exactly
        # 50.0 instead of NaN. Hardcoded threshold of exactly 50.0 catches the
        # default-substitution pattern; legitimate near-50 scores from real
        # min-max output won't land on the exact value.
        "sql": """
            WITH latest AS (
                SELECT smart_money_score FROM smart_money_scores
                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM smart_money_scores)
            )
            SELECT
                SUM(CASE WHEN smart_money_score = 50.0 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total
            FROM latest
        """,
    },
    {
        "code": "UNIVERSE_PRICE_COVERAGE_LOW",
        "table": "stock_prices",
        "column": "sid",
        "message": "Universe stocks missing from stock_prices entirely (harvester not covering all series)",
        "critical_pct": 20,
        "warn_pct": 5,
        # Mirrors db.COVERAGE_THRESHOLDS but lives in data_sanity so it shows
        # up in the daily health email alongside other invariant violations.
        "sql": """
            SELECT
                (SELECT COUNT(*) FROM stocks WHERE sid NOT IN (SELECT DISTINCT sid FROM stock_prices)) AS n_bad,
                (SELECT COUNT(*) FROM stocks) AS n_total,
                (SELECT sid || ' (' || ticker || ', ' || cap_tier || ')' FROM stocks
                 WHERE sid NOT IN (SELECT DISTINCT sid FROM stock_prices) LIMIT 1) AS sample
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Sector taxonomy — regulatory_signals.sector must align with stocks.sector
    # ═══════════════════════════════════════════════════════════════════
    # 2026-05-23: Gillette dossier showed Consumer Staples regulatory items
    # because that part matched. But 1,638 regulatory_signals rows ("Financial
    # Services" + "IT") never joined any stock — the AI classifier and the
    # stocks universe were using different sector taxonomies and no one knew.
    {
        "code": "REGULATORY_SECTOR_TAXONOMY_MISMATCH",
        "table": "regulatory_signals",
        "column": "sector",
        "message": "regulatory_signals.sector values don't exist in stocks.sector (taxonomy drift)",
        "critical_pct": 20,
        "warn_pct": 5,
        "sql": """
            SELECT
                (SELECT COUNT(*) FROM regulatory_signals
                 WHERE sector NOT IN (SELECT DISTINCT sector FROM stocks)) AS n_bad,
                (SELECT COUNT(*) FROM regulatory_signals) AS n_total,
                (SELECT sector || ' (' || COUNT(*) || ' rows orphaned)' FROM regulatory_signals
                 WHERE sector NOT IN (SELECT DISTINCT sector FROM stocks)
                 GROUP BY sector ORDER BY COUNT(*) DESC LIMIT 1) AS sample
        """,
    },
    # 2026-05-23: regulatory_events stopped flowing 2026-04-10 but stayed
    # "FRESH" because its threshold was monthly (50d). Gillette dossier showed
    # 43-day-old items as "most recent." Watchdog override now 14d.
    {
        "code": "REGULATORY_FEED_DARK",
        "table": "regulatory_events",
        "column": "published_at",
        "message": "No classified regulatory events in last 7 days — harvester or classifier silent",
        "severity": WARN,
        "sql": """
            SELECT
                CASE WHEN (SELECT COUNT(*) FROM regulatory_events
                           WHERE classifier_status = 'classified'
                             AND julianday('now') - julianday(published_at) <= 7) = 0
                     THEN 1 ELSE 0 END AS n_bad,
                1 AS n_total,
                (SELECT MAX(published_at) FROM regulatory_events WHERE classifier_status='classified') AS sample
        """,
    },
    # 2026-05-24 audit: 273 stocks have |eps_growth_pct| > 200% — arithmetic
    # artifacts from near-zero base EPS (turnarounds). consensus.py clips
    # internally before computing the signal, so screener rank is safe, but
    # the raw value is fed verbatim to the dossier LLM prompt. VSKI ranked
    # #1 SMALL today with eps_growth=2941%. Clip happens in output/dossier.py;
    # this check fires when extreme values reach the top-100 of any tier
    # (where they would be eligible for dossier generation if we extended it).
    {
        "code": "EXTREME_GROWTH_PCT_IN_TOP_PICKS",
        "table": "analyst_consensus",
        "column": "eps_growth_pct",
        "message": "Top-100 picks have |eps_growth_pct| or |revenue_growth_pct| > 300% (likely div-by-near-zero artifacts)",
        "critical_pct": 20,
        "warn_pct": 5,
        "sql": """
            WITH top_picks AS (
                SELECT sid FROM daily_picks
                WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
                  AND rank <= 100
            )
            SELECT
                SUM(CASE WHEN ABS(ac.eps_growth_pct) > 300 OR ABS(ac.revenue_growth_pct) > 300
                         THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT sid || ' (eps=' || ROUND(eps_growth_pct, 0) || '%)' FROM analyst_consensus
                 WHERE sid IN (SELECT sid FROM top_picks)
                   AND (ABS(eps_growth_pct) > 300 OR ABS(revenue_growth_pct) > 300)
                 ORDER BY ABS(eps_growth_pct) DESC LIMIT 1) AS sample
            FROM analyst_consensus ac
            WHERE ac.sid IN (SELECT sid FROM top_picks)
        """,
    },
    # 2026-05-24 fixed at consumer: signals/consensus.py now requires
    # (total_analysts IS NOT NULL OR price_target IS NOT NULL) in its SELECT —
    # Tickertape-only forecast rows (forward_eps without analyst attribution)
    # are model projections, not analyst consensus, and never fire consensus_signal.
    # This check now verifies the gate is holding: zero consensus_signals rows
    # should have a source analyst_consensus row missing both attribution fields.
    {
        "code": "CONSENSUS_SIGNAL_WITHOUT_ANALYST_ATTRIBUTION",
        "table": "consensus_signals",
        "column": "consensus_signal",
        "message": "consensus_signal fired for a stock whose analyst_consensus row has NULL total_analysts AND NULL price_target",
        "critical_pct": 1,   # ANY leak is a bug — gate failure
        "warn_pct": 0,
        "sql": """
            SELECT
                SUM(CASE WHEN ac.total_analysts IS NULL AND ac.price_target IS NULL
                         THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT cs2.sid FROM consensus_signals cs2
                 JOIN analyst_consensus ac2 ON ac2.sid = cs2.sid
                 WHERE cs2.consensus_signal IS NOT NULL
                   AND ac2.total_analysts IS NULL
                   AND ac2.price_target IS NULL LIMIT 1) AS sample
            FROM consensus_signals cs
            JOIN analyst_consensus ac ON ac.sid = cs.sid
            WHERE cs.consensus_signal IS NOT NULL
              AND cs.snapshot_date = (SELECT MAX(snapshot_date) FROM consensus_signals)
        """,
    },
    # Companion observation check: how much of the universe lacks analyst
    # attribution entirely. INFO severity — this is yfinance coverage gap,
    # not a leak. Watch for sudden jumps which indicate yfinance breakage.
    {
        "code": "ANALYST_ATTRIBUTION_COVERAGE",
        "table": "analyst_consensus",
        "column": "total_analysts",
        "message": "Stocks with NO analyst attribution (total_analysts AND price_target both NULL) — yfinance coverage gap, not a leak",
        "severity": INFO,
        "sql": """
            SELECT
                SUM(CASE WHEN total_analysts IS NULL AND price_target IS NULL THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT sid FROM analyst_consensus
                 WHERE total_analysts IS NULL AND price_target IS NULL LIMIT 1) AS sample
            FROM analyst_consensus
        """,
    },
]


# ─────────────────────── Driver ───────────────────────


def run(only_code=None):
    """Run all checks, return list of violations (each a result dict)."""
    # Auto-generated coverage checks (one per table in COVERAGE_THRESHOLDS).
    # Lives outside CHECKS so future per-sid tables can be covered just by
    # adding to db.COVERAGE_THRESHOLDS.
    all_checks = CHECKS + _generic_coverage_checks()
    violations = []
    with get_db() as conn:
        for check in all_checks:
            if only_code and check["code"] != only_code:
                continue
            try:
                if "sql" in check:
                    result = _run_sql_check(check, conn)
                else:
                    result = _run_fn_check(check)
            except Exception as e:
                result = {
                    "code": check["code"],
                    "severity": WARN,
                    "table": check.get("table"),
                    "column": check.get("column"),
                    "message": f"Check itself raised: {type(e).__name__}: {e}",
                    "n_violations": None,
                    "n_total": None,
                    "pct_violations": None,
                    "sample": None,
                }
            if result is not None:
                violations.append(result)
    return violations


def format_terminal(violations):
    if not violations:
        return "✓ All sanity checks passed."
    by_sev = {CRITICAL: [], WARN: [], INFO: []}
    for v in violations:
        by_sev.get(v["severity"], by_sev[WARN]).append(v)

    lines = []
    summary = " · ".join(
        f"{len(by_sev[s])} {s}" for s in (CRITICAL, WARN, INFO) if by_sev[s]
    )
    lines.append(f"Data sanity audit — {summary or 'all clean'}")
    lines.append("=" * 80)
    for sev in (CRITICAL, WARN, INFO):
        for v in by_sev[sev]:
            marker = "❌" if sev == CRITICAL else ("⚠" if sev == WARN else "·")
            pct_str = f" ({v['pct_violations']:.1f}%)" if v.get("pct_violations") is not None else ""
            n_str = f"{v['n_violations']}/{v['n_total']}" if v.get("n_total") else f"{v['n_violations'] or 0}"
            lines.append(f"  {marker} [{sev}] {v['code']}")
            lines.append(f"      {v['message']}")
            lines.append(f"      table: {v.get('table')} · column: {v.get('column')} · {n_str}{pct_str}")
            if v.get("sample"):
                lines.append(f"      sample: {v['sample']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check", help="Run a single check by code")
    args = parser.parse_args()

    violations = run(only_code=args.check)
    if args.json:
        print(json.dumps(violations, indent=2, default=str))
    else:
        print(format_terminal(violations))

    # Exit non-zero on any CRITICAL — lets cron / CI signal
    return 1 if any(v["severity"] == CRITICAL for v in violations) else 0


if __name__ == "__main__":
    sys.exit(main())
