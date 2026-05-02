"""
Alpha Signal v2 — Momentum Signal

Risk-adjusted 6M and 12M momentum following Jegadeesh-Titman methodology.

  mom_6m  = ret_6m / vol_6m   (skip 22 days, 154-day lookback)
  mom_12m = ret_12m / vol_12m (skip 22 days, 252-day lookback)

Reads: stock_prices
Returns: DataFrame with sid, mom_6m, mom_12m

No separate DB table — values stored in daily_snapshots during scoring phase.

Usage:
    python -m signals.momentum            # compute and print stats
    python -m signals.momentum --dry-run  # same (no DB writes)
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import BACKTEST
from db import read_sql

SKIP_DAYS = BACKTEST["momentum_skip_days"]     # 22
WINDOW_6M = BACKTEST["momentum_6m_days"]       # 154
WINDOW_12M = BACKTEST["momentum_12m_days"]     # 252


def compute_momentum():
    """
    Compute risk-adjusted 6M and 12M momentum for all stocks.
    Returns DataFrame: sid, mom_6m, mom_12m
    """
    # Load enough price history (12M + skip + buffer)
    prices = read_sql(
        "SELECT sid, date, close FROM stock_prices "
        "WHERE close > 0 ORDER BY sid, date"
    )

    rows = []
    for sid, group in prices.groupby("sid"):
        g = group.sort_values("date")
        n = len(g)

        row = {"sid": sid}

        # Need at least WINDOW_12M + SKIP_DAYS prices for 12M
        closes = g["close"].values

        # 6M momentum
        if n >= WINDOW_6M + SKIP_DAYS:
            # Price at skip point (22 days ago)
            p_skip = closes[-SKIP_DAYS - 1]
            # Price at 6M ago
            p_6m = closes[-(WINDOW_6M + SKIP_DAYS)]

            if p_6m > 0 and p_skip > 0:
                ret_6m = p_skip / p_6m - 1
                # Volatility of daily returns in the 6M window (excluding skip)
                window = closes[-(WINDOW_6M + SKIP_DAYS):(-SKIP_DAYS)]
                daily_rets = np.diff(window) / window[:-1]
                vol_6m = daily_rets.std()
                if vol_6m > 0:
                    row["mom_6m"] = round(ret_6m / vol_6m, 4)

        # 12M momentum
        if n >= WINDOW_12M + SKIP_DAYS:
            p_12m = closes[-(WINDOW_12M + SKIP_DAYS)]

            if p_12m > 0 and p_skip > 0:
                ret_12m = p_skip / p_12m - 1
                window = closes[-(WINDOW_12M + SKIP_DAYS):(-SKIP_DAYS)]
                daily_rets = np.diff(window) / window[:-1]
                vol_12m = daily_rets.std()
                if vol_12m > 0:
                    row["mom_12m"] = round(ret_12m / vol_12m, 4)

        rows.append(row)

    return pd.DataFrame(rows)


def compute(dry_run=False):
    """Main entry point for pipeline compatibility."""
    df = compute_momentum()

    has_6m = df["mom_6m"].notna().sum()
    has_12m = df["mom_12m"].notna().sum()

    print(f"Momentum: {len(df)} stocks")
    print(f"  6M: {has_6m} stocks, mean={df['mom_6m'].dropna().mean():.3f}")
    print(f"  12M: {has_12m} stocks, mean={df['mom_12m'].dropna().mean():.3f}")
    print("  (No separate DB table — stored in daily_snapshots during scoring)")

    return len(df)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
