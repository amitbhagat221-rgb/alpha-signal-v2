"""
Alpha Signal v2 — Momentum Signal

Risk-adjusted 6M and 12M momentum following Jegadeesh-Titman methodology.

  mom_6m  = ret_6m / vol_6m   (skip 22 days, 154-day lookback)
  mom_12m = ret_12m / vol_12m (skip 22 days, 252-day lookback)

Reads: stock_prices + corporate_adjustments (split/bonus-adjusted, like the PIT backtest)
Returns: DataFrame with sid, mom_6m, mom_12m

No separate DB table — values stored in daily_snapshots during scoring phase.

Usage:
    python -m signals.momentum            # compute and print stats
    python -m signals.momentum --dry-run  # same (no DB writes)
"""

import argparse

import numpy as np
import pandas as pd

from config import BACKTEST
from signals._prices import load_prices

SKIP_DAYS = BACKTEST["momentum_skip_days"]     # 22
WINDOW_6M = BACKTEST["momentum_6m_days"]       # 154
WINDOW_12M = BACKTEST["momentum_12m_days"]     # 252


def momentum(prices):
    """Risk-adjusted 6M and 12M momentum per sid from an as-of price frame.

    `prices` = [sid, date, close(, adj_close)]; adj_close (split/bonus-adjusted)
    is preferred when present, so a split inside the window isn't read as a crash.
    Shared by the live screener and tools/reconstruct_pit:pit_momentum.
    Returns DataFrame[sid, mom_6m, mom_12m] (NaN where history is too short).
    """
    rows = []
    price_col = "adj_close" if "adj_close" in prices.columns else "close"
    for sid, group in prices.groupby("sid"):
        g = group.sort_values("date")
        closes = g[price_col].values
        n = len(closes)

        row = {"sid": sid}

        # 6M momentum
        if n >= WINDOW_6M + SKIP_DAYS:
            # Price at skip point (22 days ago) and 6M ago
            p_skip = closes[-SKIP_DAYS - 1]
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
            p_skip = closes[-SKIP_DAYS - 1]
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


def compute_momentum(prices=None):
    """
    Compute risk-adjusted 6M and 12M momentum for all stocks, on split/bonus-
    adjusted closes (the backtest's basis). `prices` = a signals._prices frame
    (the screener loads it once); loaded when omitted.
    Returns DataFrame: sid, mom_6m, mom_12m
    """
    if prices is None:
        prices = load_prices()
    return momentum(prices)


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
