"""
Alpha Signal v2 — Earnings Yield Signal

  earnings_yield = TTM EPS / current_price
                 = sum(last 4 quarters EPS) / latest close

Handles negative EPS correctly (ranks them as poor value, unlike P/E).

Reads: quarterly_income, stock_prices
Returns: DataFrame with sid, earnings_yield

No separate DB table — stored in daily_snapshots during scoring phase.

Usage:
    python -m signals.earnings_yield            # compute and print stats
    python -m signals.earnings_yield --dry-run  # same
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from db import read_sql


def compute_earnings_yield():
    """
    Compute earnings yield (E/P) for all stocks.
    Returns DataFrame: sid, earnings_yield
    """
    # TTM EPS: sum of last 4 quarters
    qi = read_sql(
        "SELECT sid, period, end_date, reporting, eps "
        "FROM quarterly_income ORDER BY sid, end_date"
    )

    # Prefer consolidated
    has_consol = set(qi[qi["reporting"] == "consolidated"]["sid"])
    qi = qi[
        ((qi["sid"].isin(has_consol)) & (qi["reporting"] == "consolidated"))
        | (~qi["sid"].isin(has_consol))
    ]

    ttm_eps = {}
    for sid, group in qi.groupby("sid"):
        g = group.sort_values("end_date")
        if len(g) >= 4:
            eps_sum = g.tail(4)["eps"].sum()
            if pd.notna(eps_sum):
                ttm_eps[sid] = eps_sum

    # Latest close price per stock
    prices = read_sql(
        "SELECT sid, close FROM stock_prices "
        "WHERE (sid, date) IN ("
        "  SELECT sid, MAX(date) FROM stock_prices GROUP BY sid"
        ")"
    )
    price_map = prices.set_index("sid")["close"].to_dict()

    # Compute E/P
    rows = []
    for sid, eps in ttm_eps.items():
        price = price_map.get(sid)
        if price and price > 0:
            ey = round(eps / price, 6)
            rows.append({"sid": sid, "earnings_yield": ey})
        else:
            rows.append({"sid": sid, "earnings_yield": None})

    # Add stocks with no EPS data
    all_sids = set(read_sql("SELECT sid FROM stocks")["sid"])
    computed_sids = {r["sid"] for r in rows}
    for sid in all_sids - computed_sids:
        rows.append({"sid": sid, "earnings_yield": None})

    return pd.DataFrame(rows)


def compute(dry_run=False):
    """Main entry point for pipeline compatibility."""
    df = compute_earnings_yield()

    has_ey = df["earnings_yield"].notna().sum()
    ey_vals = df["earnings_yield"].dropna()

    print(f"Earnings Yield: {len(df)} stocks, {has_ey} computed")
    if has_ey > 0:
        print(f"  Mean E/P: {ey_vals.mean():.4f} ({1/ey_vals[ey_vals>0].mean():.1f}x implied P/E)")
        print(f"  Median E/P: {ey_vals.median():.4f}")
        print(f"  Negative EPS: {(ey_vals < 0).sum()} stocks")
    print("  (No separate DB table — stored in daily_snapshots during scoring)")

    return len(df)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
