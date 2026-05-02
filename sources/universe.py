"""
Alpha Signal v2 — Universe Liveness Refresh

Bumps stocks.updated_at for tickers that have a stock_prices row in the last
N days. Stocks that haven't traded recently keep their old timestamp — those
are candidates for delisting review.

Why not refetch fundamentals here? PE/PB/ROE/etc come from Tickertape, which
takes ~4 hours for a full universe scan. Fundamentals are refreshed via the
manual `python -m sources.tickertape` run on a monthly cadence.

This step is the lightweight weekly checkpoint: which tickers are still alive?

Reads:  stock_prices
Writes: stocks (only the updated_at timestamp)

Usage:
    python -m sources.universe                  # bump for stocks with prices in last 7d
    python -m sources.universe --days 30        # widen the liveness window
    python -m sources.universe --dry-run
"""

import argparse

from db import get_db, read_sql

DEFAULT_LIVENESS_DAYS = 7


def compute(dry_run=False, days=DEFAULT_LIVENESS_DAYS):
    """Bump updated_at for stocks with recent prices."""
    cutoff_sql = f"date('now', '-{int(days)} days')"

    counts = read_sql(f"""
        SELECT
          (SELECT COUNT(*) FROM stocks) AS total_stocks,
          (SELECT COUNT(DISTINCT sid) FROM stock_prices
            WHERE date >= {cutoff_sql}) AS live_sids
    """).iloc[0]
    print(f"Universe liveness: {counts['live_sids']:,} of {counts['total_stocks']:,} stocks "
          f"traded in last {days}d")

    if dry_run:
        print("Dry run — not updating.")
        return int(counts["live_sids"])

    with get_db() as conn:
        cur = conn.execute(f"""
            UPDATE stocks
            SET updated_at = CURRENT_TIMESTAMP
            WHERE sid IN (
              SELECT DISTINCT sid FROM stock_prices WHERE date >= {cutoff_sql}
            )
        """)
        n = cur.rowcount

    dormant = int(counts["total_stocks"] - counts["live_sids"])
    if dormant:
        print(f"  {dormant} stocks dormant > {days}d — not refreshed (delisting candidates)")
    print(f"Bumped updated_at on {n} stocks")
    return n


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=DEFAULT_LIVENESS_DAYS,
                        help=f"liveness window in days (default {DEFAULT_LIVENESS_DAYS})")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run, days=args.days)
