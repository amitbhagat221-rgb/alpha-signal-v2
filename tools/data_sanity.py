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
        "sql": """
            SELECT
                SUM(CASE WHEN ABS(fh.value - sp.close) < 0.5 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT fh2.sid || '@' || fh2.date || ': fh.value=' || fh2.value || ' / sp.close=' || sp2.close
                 FROM forecast_history fh2 JOIN stock_prices sp2 ON fh2.sid=sp2.sid AND fh2.date=sp2.date
                 WHERE fh2.metric='price' AND ABS(fh2.value - sp2.close) < 0.5 LIMIT 1) AS sample
            FROM forecast_history fh
            JOIN stock_prices sp ON fh.sid = sp.sid AND fh.date = sp.date
            WHERE fh.metric = 'price'
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
]


# ─────────────────────── Driver ───────────────────────


def run(only_code=None):
    """Run all checks, return list of violations (each a result dict)."""
    violations = []
    with get_db() as conn:
        for check in CHECKS:
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
