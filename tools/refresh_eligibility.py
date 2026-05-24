"""
Refresh universe_eligibility table for today's snapshot.

For each signal in eligibility/registry.py, runs the signal's `eligible_sql`,
then writes one row per (sid, signal, snapshot_date) marking the SID
ELIGIBLE (1) or INELIGIBLE (0). The previous day's rows are NOT deleted —
the table is an append-only history.

Usage:
    python -m tools.refresh_eligibility
    python -m tools.refresh_eligibility --signal consensus       # one signal
    python -m tools.refresh_eligibility --date 2026-05-24        # force date
    python -m tools.refresh_eligibility --dry-run                # don't write

Cron: run nightly after the daily pipeline (after fetch_* but before screener).

Plan 0005 Phase A. See docs/plans/0005-data-confidence-to-95.md.
"""

import argparse
import sys
from datetime import date as _date
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, get_db
from eligibility.registry import SIGNAL_ELIGIBILITY, UNIVERSE_SQL, all_signals


def refresh(only_signal=None, snapshot_date=None, dry_run=False, verbose=True):
    """Compute eligibility for each signal and upsert into universe_eligibility.

    Returns: list of dicts {signal, n_eligible, n_ineligible} per signal.
    """
    snapshot_date = snapshot_date or _date.today().isoformat()
    universe = set(read_sql(UNIVERSE_SQL)["sid"].dropna().astype(str))

    signals = [only_signal] if only_signal else all_signals()
    out = []

    for sig in signals:
        if sig not in SIGNAL_ELIGIBILITY:
            raise SystemExit(f"Unknown signal: {sig}. Known: {all_signals()}")

        spec = SIGNAL_ELIGIBILITY[sig]
        try:
            eligible_df = read_sql(spec["eligible_sql"])
            eligible_set = set(eligible_df["sid"].dropna().astype(str))
        except Exception as e:
            if verbose:
                print(f"  ✗ {sig}: eligible_sql failed — {type(e).__name__}: {e}")
            out.append({"signal": sig, "n_eligible": 0, "n_ineligible": 0, "error": str(e)})
            continue

        # Intersect with universe — a sid in eligible_set but not in universe
        # is data drift; ignore. A sid in universe but not eligible_set is INELIGIBLE.
        eligible_in_universe = eligible_set & universe
        ineligible_in_universe = universe - eligible_set

        if verbose:
            print(f"  {sig:18s} eligible={len(eligible_in_universe):>4d} "
                  f"ineligible={len(ineligible_in_universe):>4d} "
                  f"(of {len(universe)} universe)")

        if dry_run:
            out.append({
                "signal": sig,
                "n_eligible": len(eligible_in_universe),
                "n_ineligible": len(ineligible_in_universe),
            })
            continue

        rows = []
        for sid in eligible_in_universe:
            rows.append((sid, sig, snapshot_date, 1))
        for sid in ineligible_in_universe:
            rows.append((sid, sig, snapshot_date, 0))

        with get_db() as conn:
            # Idempotent upsert — replace prior write for same (sid, signal, date)
            conn.executemany(
                """INSERT INTO universe_eligibility (sid, signal, snapshot_date, eligible, refreshed_at)
                   VALUES (?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(sid, signal, snapshot_date) DO UPDATE SET
                       eligible = excluded.eligible,
                       refreshed_at = excluded.refreshed_at""",
                rows,
            )

        out.append({
            "signal": sig,
            "n_eligible": len(eligible_in_universe),
            "n_ineligible": len(ineligible_in_universe),
        })

    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--signal", help="Refresh just one signal (default: all)")
    p.add_argument("--date", help="Override snapshot_date (default: today)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    print(f"Refreshing universe_eligibility for snapshot={args.date or _date.today().isoformat()}")
    if args.dry_run:
        print("  (dry-run — no DB writes)")
    out = refresh(only_signal=args.signal, snapshot_date=args.date, dry_run=args.dry_run)
    n_total_rows = sum(r["n_eligible"] + r["n_ineligible"] for r in out if "error" not in r)
    print(f"Done. {len(out)} signal(s) refreshed, {n_total_rows} (sid,signal) rows written.")


if __name__ == "__main__":
    main()
