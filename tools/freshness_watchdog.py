"""
Alpha Signal v2 — Freshness Watchdog

Scans data_health() for STALE/OUTDATED tables, looks up each table's registered
producer from config.PIPELINE_STEPS, and retriggers the producer. Closes the
loop on silent fetcher failures (where the producer logs SUCCESS but inserts
0 rows) — if the table is still stale after running, the next cron tick tries
again and logs a watchdog FAILED row.

Run from cron once or twice daily (e.g. 17:00 UTC). Idempotent and safe to
re-run: every producer in PIPELINE_STEPS uses INSERT OR IGNORE / OR REPLACE.

Usage:
    python -m tools.freshness_watchdog              # full scan + heal
    python -m tools.freshness_watchdog --dry-run    # report only, don't fetch
    python -m tools.freshness_watchdog --tables stock_prices,insider_trades
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import data_health, get_db, read_sql
from config import PIPELINE_STEPS
from pipeline import run_step


def _producer_for(table_name, row_produced_by=None):
    """Return the (name, module, function, critical) tuple for a table's producer.

    Match priority:
      1. PIPELINE_STEPS row with matching `table`
      2. PIPELINE_STEPS row whose `name` matches `row_produced_by` (file outputs
         have `table: None`, so data_health() carries the step name in
         `produced_by` instead).
    """
    for s in PIPELINE_STEPS:
        if s.get("table") and s["table"] == table_name:
            return (s["name"], s["module"], s["function"], s["critical"])
    if row_produced_by:
        for s in PIPELINE_STEPS:
            if s["name"] == row_produced_by:
                return (s["name"], s["module"], s["function"], s["critical"])
    return None


def _log_watchdog(table, action, status, error=None):
    """Append a row to pipeline_log so watchdog runs show alongside cron runs."""
    now = datetime.now().isoformat(timespec="seconds")
    with get_db() as conn:
        conn.execute(
            """INSERT INTO pipeline_log
               (run_date, step_name, status, started_at, finished_at, error_message)
               VALUES (date('now'), ?, ?, ?, ?, ?)""",
            (f"watchdog_{table}_{action}", status, now, now, error),
        )


def _report_coverage(coverage_gap, dry_run=False):
    """Print and log per-sid coverage shortfalls. Does not auto-heal."""
    if coverage_gap.empty:
        return
    print(f"⚠ {len(coverage_gap)} tables with per-stock coverage gap:")
    for _, row in coverage_gap.iterrows():
        tbl = row["table"]
        pct = row.get("stock_coverage_pct")
        cov = row.get("stock_coverage", "—")
        status = row.get("coverage_status", "?")
        marker = "✗✗" if status == "COVERAGE_SEVERE" else "✗ "
        print(f"  {marker} {tbl:30s} {status:16s} {cov}")
        if not dry_run:
            _log_watchdog(
                tbl,
                "coverage",
                status,
                error=f"per-sid coverage {pct}% — structural gap, won't self-heal",
            )
    print()


def _log_recoveries(df, dry_run=False):
    """Emit a heal-SUCCESS marker for any table whose LAST watchdog heal FAILED
    but which is now FRESH — i.e. it recovered without the watchdog acting (late
    data landed via the normal pipeline, or a structural-lag STALENESS_OVERRIDE
    was corrected). The failure-streak detector in health_report keys off each
    step's *latest* status, so without this a self-recovered table shows a
    phantom "failed N consecutive days" CRITICAL until the old FAILED rows age
    out of the window. This closes that loop — symmetric with the heal-SUCCESS
    the scan already logs when it heals a table itself."""
    latest = read_sql(
        """
        WITH ranked AS (
            SELECT step_name, status,
                   ROW_NUMBER() OVER (PARTITION BY step_name ORDER BY id DESC) AS rn
            FROM pipeline_log
            WHERE step_name LIKE 'watchdog_%\\_heal' ESCAPE '\\'
              AND status IN ('SUCCESS', 'FAILED')
        )
        SELECT step_name FROM ranked WHERE rn = 1 AND status = 'FAILED'
        """
    )
    if latest.empty:
        return
    fresh = set(df[df["freshness"] == "FRESH"]["table"])
    for step in latest["step_name"]:
        tbl = step[len("watchdog_"):-len("_heal")]  # step_name = watchdog_<table>_heal
        if tbl in fresh:
            print(f"  ✓ {tbl:30s} recovered → logging heal SUCCESS (last heal had FAILED)")
            if not dry_run:
                _log_watchdog(tbl, "heal", "SUCCESS",
                              error="recovered — table FRESH without watchdog action")


def scan(dry_run=False, only_tables=None):
    df = data_health()

    # Close the loop on self-recovered tables before the stale scan: a table that
    # went FRESH on its own still carries a FAILED-latest heal log → phantom streak.
    _log_recoveries(df, dry_run=dry_run)

    stale = df[df["freshness"].isin(["STALE", "OUTDATED"])].copy()
    if only_tables:
        stale = stale[stale["table"].isin(only_tables)]

    # Coverage scan — separate concern from time-based staleness. A table can
    # be FRESH (MAX(date) is today) but have a structural per-sid gap. We log
    # these but don't auto-heal — re-running the producer won't fix a harvester
    # that systematically drops a series or a source that doesn't carry every
    # stock. Surfaces them so the human knows where the holes are.
    coverage_gap = df[df.get("coverage_status", "").isin(["COVERAGE_GAP", "COVERAGE_SEVERE"])].copy()
    if only_tables:
        coverage_gap = coverage_gap[coverage_gap["table"].isin(only_tables)]
    _report_coverage(coverage_gap, dry_run=dry_run)

    if stale.empty:
        print("✓ All registered tables are FRESH. Nothing to heal.")
        # Heartbeat so `health_report` sees a recent run even on a clean scan
        # (otherwise "last ran Nh ago" only updates when something fires).
        if not dry_run:
            _log_watchdog("heartbeat", "scan", "SUCCESS", error=None)
        return 0

    print(f"⚠ {len(stale)} stale/outdated tables:")
    healed, skipped, failed = 0, 0, 0
    # Dedupe by (module, function): a single producer (e.g. tickertape_analyst)
    # may write multiple tables. Running it twice would just waste 80 min.
    ran_producers = set()

    for _, row in stale.sort_values("age_days", ascending=False).iterrows():
        tbl = row["table"]
        age = int(row["age_days"]) if row["age_days"] else "?"
        freshness = row["freshness"]
        producer = _producer_for(tbl, row.get("produced_by"))

        if producer is None:
            print(f"  ✗ {tbl:30s} {freshness:8s} {age}d old — NO PRODUCER REGISTERED")
            _log_watchdog(tbl, "scan", "SKIPPED", error="no producer in PIPELINE_STEPS")
            skipped += 1
            continue

        name, module, func_name, critical = producer
        producer_key = (module, func_name)

        if producer_key in ran_producers:
            print(f"  ↻ {tbl:30s} {freshness:8s} {age}d old — already covered by {module}.{func_name} above")
            continue

        print(f"  → {tbl:30s} {freshness:8s} {age}d old — running {module}.{func_name}")
        ran_producers.add(producer_key)

        if dry_run:
            print("    (dry-run, skipped)")
            continue

        ok = run_step(name, module, func_name, critical)
        if ok:
            # Re-check this row to see if freshness improved.
            new_df = data_health()
            new_row = new_df[new_df["table"] == tbl]
            new_age = new_row.iloc[0]["age_days"] if not new_row.empty else None
            new_fresh = new_row.iloc[0]["freshness"] if not new_row.empty else "?"
            print(f"    after: {new_fresh} (age {new_age}d)")
            if new_fresh == "FRESH":
                healed += 1
                _log_watchdog(tbl, "heal", "SUCCESS")
            else:
                # Producer ran cleanly but data still stale → silent failure.
                failed += 1
                _log_watchdog(tbl, "heal", "FAILED",
                              error=f"producer ran but table still {new_fresh} ({new_age}d)")
                print(f"    ⚠ producer succeeded but table still {new_fresh} — silent fetcher failure")
        else:
            failed += 1
            _log_watchdog(tbl, "heal", "FAILED", error="producer raised")

    print()
    print(f"Summary: {healed} healed · {skipped} skipped (no producer) · {failed} failed")

    # Proactive endpoint coverage audit. Catches "table is fresh but the cockpit
    # endpoint that consumes it returns empty for X% of stocks" — a class the
    # freshness check can't see by design. Added 2026-05-23.
    print()
    print("─── Cockpit endpoint coverage audit ───")
    try:
        from tools.cockpit_endpoint_audit import audit as endpoint_audit
        endpoint_audit(sample_size=30)
    except Exception as e:
        print(f"  ⚠ endpoint audit failed: {type(e).__name__}: {e}")

    return failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, don't fetch")
    parser.add_argument("--tables", help="Comma-separated subset of tables to consider")
    args = parser.parse_args()

    only = [t.strip() for t in args.tables.split(",")] if args.tables else None
    rc = scan(dry_run=args.dry_run, only_tables=only)
    sys.exit(rc)


if __name__ == "__main__":
    main()
