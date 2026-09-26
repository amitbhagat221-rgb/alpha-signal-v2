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

import numpy as np
import pandas as pd

from db import read_sql


def ttm_eps(qi):
    """{sid: sum of the last 4 quarters' EPS}, consolidated preferred per sid;
    sids with <4 quarters are absent. `qi` = [sid, end_date, reporting, eps]."""
    has_consol = set(qi[qi["reporting"] == "consolidated"]["sid"])
    qi = qi[
        ((qi["sid"].isin(has_consol)) & (qi["reporting"] == "consolidated"))
        | (~qi["sid"].isin(has_consol))
    ]
    out = {}
    for sid, group in qi.groupby("sid"):
        g = group.sort_values("end_date")
        if len(g) >= 4:
            eps_sum = g.tail(4)["eps"].sum()
            if pd.notna(eps_sum):
                out[sid] = eps_sum
    return out


def earnings_yield(qi, close):
    """E/P = TTM EPS / close. `close` = [sid, close_price]; NaN where the close is
    missing or ≤ 0. Returns DataFrame[sid, earnings_yield] for sids with a TTM EPS.
    Shared by the live screener and tools/reconstruct_pit:pit_earnings_yield."""
    eps = ttm_eps(qi)
    if not eps:
        return pd.DataFrame(columns=["sid", "earnings_yield"])
    merged = pd.DataFrame({"sid": list(eps), "ttm_eps": list(eps.values())}).merge(
        close, on="sid", how="left")
    merged["earnings_yield"] = np.where(
        (merged["close_price"].notna()) & (merged["close_price"] > 0),
        (merged["ttm_eps"] / merged["close_price"]).round(6),
        np.nan,
    )
    return merged[["sid", "earnings_yield"]]


def compute_earnings_yield():
    """
    Compute earnings yield (E/P) for all stocks.
    Returns DataFrame: sid, earnings_yield (NaN where not computable)
    """
    qi = read_sql(
        "SELECT sid, period, end_date, reporting, eps "
        "FROM quarterly_income ORDER BY sid, end_date"
    )
    # Latest close price per stock
    close = read_sql(
        "SELECT sid, close AS close_price FROM stock_prices "
        "WHERE (sid, date) IN ("
        "  SELECT sid, MAX(date) FROM stock_prices GROUP BY sid"
        ")"
    )
    ey = earnings_yield(qi, close)
    all_sids = read_sql("SELECT sid FROM stocks")[["sid"]]
    return all_sids.merge(ey, on="sid", how="left")


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
