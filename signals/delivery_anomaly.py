"""
Alpha Signal v2 — Delivery Anomaly Z-Score

Today's delivery % vs the trailing 90-day mean, normalised by 90-day std.
A large positive z means delivery-based buying is spiking vs the recent baseline.
Backtest: SMALL t = 4.76 (KEEP), runs at the smart-money cluster.

Reads: stock_prices.delivery_pct
Returns: DataFrame with sid, delivery_anomaly_z

No separate DB table — values are computed live by the screener and persisted
inside daily_snapshots via the scoring phase. Mirrors signals/momentum.py.

Usage:
    python -m signals.delivery_anomaly            # compute and print stats
"""

import pandas as pd

from db import read_sql


WINDOW_DAYS = 90
MIN_HISTORY = 30
# |z| beyond this is discarded (NaN), NOT clipped — that is what the validated
# backtest saw (reconstruct_pit VALIDATION_RANGES NaNs out-of-range values).
# Live used to clip to ±5, ranking the biggest spikes top on a region the
# backtest never tested. Live and PIT now share delivery_anomaly_z() below.
Z_LIMIT = 5.0


def delivery_anomaly_z(prices: pd.DataFrame, window: int = WINDOW_DAYS) -> pd.DataFrame:
    """Latest delivery_pct vs the prior rows of the trailing `window`, in std units.

    `prices` needs sid, date, delivery_pct (nulls allowed) and must already be
    as-of filtered by the caller. Used by the live screener and pit_delivery_anomaly_z.
    """
    if prices.empty or "delivery_pct" not in prices.columns:
        return pd.DataFrame(columns=["sid", "delivery_anomaly_z"])
    rows = []
    for sid, g in prices.sort_values(["sid", "date"]).groupby("sid"):
        deliv = g["delivery_pct"].tail(window).dropna()
        if len(deliv) < MIN_HISTORY:
            continue
        baseline = deliv.iloc[:-1]
        mean, std = baseline.mean(), baseline.std()
        if not std or std <= 0 or pd.isna(mean):
            continue
        z = (deliv.iloc[-1] - mean) / std
        if abs(z) <= Z_LIMIT:
            rows.append({"sid": sid, "delivery_anomaly_z": round(float(z), 3)})
    return pd.DataFrame(rows, columns=["sid", "delivery_anomaly_z"])


def compute_delivery_anomaly_z() -> pd.DataFrame:
    """Live: today's value per sid from the last ~180 calendar days of prices."""
    prices = read_sql(
        "SELECT sid, date, delivery_pct FROM stock_prices "
        "WHERE date >= date('now','-180 days')"
    )
    return delivery_anomaly_z(prices)


if __name__ == "__main__":
    df = compute_delivery_anomaly_z()
    print(f"Computed delivery_anomaly_z for {len(df):,} stocks")
    if not df.empty:
        print(df["delivery_anomaly_z"].describe())
