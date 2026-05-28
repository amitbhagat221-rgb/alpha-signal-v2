"""
Alpha Signal v2 — Daily MF NAV ingest from AMFI NAVAll.txt.

Single HTTP, <2s runtime, all ~14,000 schemes in one shot. The same
NAVAll.txt file that feeds the scheme master (sources/mf_amfi_master.py)
also carries today's NAV per scheme. Reuses `parse_navall()` from that
module to avoid duplicating parser logic.

Idempotent: PK on `mf_nav_history (scheme_code, nav_date)` means re-runs
the same day insert 0 rows. Holidays/weekends: AMFI still publishes the
file but with the prior business day's NAV — `INSERT OR IGNORE` handles
the repeat gracefully.

Wired into `PIPELINE_STEPS` as `fetch_mf_nav_daily` (frequency: daily).

Usage:
    python -m sources.mf_nav_daily               # daily refresh
    python -m sources.mf_nav_daily --dry-run     # parse + report only
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import get_db, read_sql
from sources.mf_amfi_master import fetch_navall_text, parse_navall


def compute(dry_run: bool = False) -> int:
    """Pull today's NAVs from NAVAll.txt; insert into mf_nav_history."""
    print(f"Fetching NAVAll.txt for today's NAVs…")
    text = fetch_navall_text()
    rows = parse_navall(text)
    print(f"Parsed {len(rows)} scheme rows from AMFI")

    # Keep only rows that have BOTH a numeric NAV AND a parseable date.
    # Some closed-ended / wound-down schemes show their last known NAV with
    # an old date — those are not "today's NAV", skip them at the daily-fetch
    # layer (mf_amfi_master keeps the master entry).
    nav_rows = [
        {"scheme_code": r["scheme_code"], "nav_date": r["nav_date"], "nav": r["nav"]}
        for r in rows
        if r["nav"] is not None and r["nav_date"] is not None
    ]
    print(f"  {len(nav_rows)} have non-null NAV + date")

    if not nav_rows:
        raise RuntimeError("Parsed 0 usable NAV rows — file format may have changed")

    nav_dates = pd.Series([r["nav_date"] for r in nav_rows]).value_counts().head(3)
    print(f"  NAV date distribution (top 3): {dict(nav_dates)}")

    if dry_run:
        print("--dry-run: not saving.")
        return len(nav_rows)

    # INSERT OR IGNORE — re-runs and holiday re-fetches are no-ops on the PK.
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.executemany(
            "INSERT OR IGNORE INTO mf_nav_history (scheme_code, nav_date, nav, fetched_at) "
            "VALUES (?, ?, ?, ?)",
            [(r["scheme_code"], r["nav_date"], r["nav"], now) for r in nav_rows],
        )
        n_new = cursor.rowcount

    print(f"\nInserted {n_new} new NAV rows ({len(nav_rows) - n_new} already-present skipped)")

    # Print a couple of post-state stats
    summary = read_sql("""
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT scheme_code) AS distinct_schemes,
            MIN(nav_date) AS oldest,
            MAX(nav_date) AS latest
        FROM mf_nav_history
    """).iloc[0]
    print(f"mf_nav_history: {summary['total_rows']:,} rows · "
          f"{summary['distinct_schemes']:,} schemes · "
          f"{summary['oldest']} → {summary['latest']}")

    return n_new


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    compute(dry_run=args.dry_run)
