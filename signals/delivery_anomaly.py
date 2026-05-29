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
CLIP = (-5.0, 5.0)  # match reconstruct_pit.py


def compute_delivery_anomaly_z() -> pd.DataFrame:
    """For each sid: latest delivery_pct minus 90d baseline mean, ÷ baseline std."""
    prices = read_sql(
        "SELECT sid, date, delivery_pct FROM stock_prices "
        "WHERE delivery_pct IS NOT NULL AND date >= date('now','-180 days')"
    )
    if prices.empty:
        return pd.DataFrame(columns=["sid", "delivery_anomaly_z"])

    prices = prices.sort_values(["sid", "date"])
    rows = []
    for sid, g in prices.groupby("sid"):
        g = g.tail(WINDOW_DAYS)
        deliv = g["delivery_pct"].dropna()
        if len(deliv) < MIN_HISTORY:
            continue
        latest = deliv.iloc[-1]
        baseline = deliv.iloc[:-1]
        std = baseline.std()
        if not std or std <= 0:
            continue
        z = (latest - baseline.mean()) / std
        z = max(CLIP[0], min(CLIP[1], float(z)))
        rows.append({"sid": sid, "delivery_anomaly_z": round(z, 3)})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = compute_delivery_anomaly_z()
    print(f"Computed delivery_anomaly_z for {len(df):,} stocks")
    if not df.empty:
        print(df["delivery_anomaly_z"].describe())
