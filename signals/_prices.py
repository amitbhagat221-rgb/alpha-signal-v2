"""
Alpha Signal v2 — the price frame the price-based signals share.

One loader for the live screener (load once, pass `prices=` to every inline
signal) and the split/bonus adjustment the PIT backtest applies
(pit.py uses the same apply_adjustments), so the live path ranks
on the same adj_close the validated backtest did.

Reads: stock_prices (close > 0), corporate_adjustments
"""

import numpy as np
import pandas as pd

from db import read_sql


def apply_adjustments(prices, adjustments, as_of):
    """Add `adj_close` to `prices` using PIT-strict corporate adjustment.

    Only events with ex_date <= as_of are visible. For each (sid, date),
    adj_close = close × Π factor[e] for e where e.sid == sid AND date < e.ex_date <= as_of.

    Vectorized per-sid via reverse cumprod + searchsorted — O(N log M) per sid.
    """
    snap_str = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)
    visible = adjustments[adjustments["ex_date"] <= snap_str]
    out = prices.copy()

    if visible.empty:
        out["adj_close"] = out["close"]
        return out

    out["adj_close"] = out["close"].astype(float)
    events_by_sid = dict(tuple(visible.groupby("sid")))

    closes = out["close"].astype(float).values
    adj_factors = np.ones(len(out), dtype=float)

    for sid, idxs in out.groupby("sid").indices.items():
        if sid not in events_by_sid:
            continue
        g = events_by_sid[sid].sort_values("ex_date")
        ex_dates = g["ex_date"].values
        factors = g["factor"].values.astype(float)

        n = len(factors)
        rev_cum = np.empty(n + 1)
        rev_cum[n] = 1.0
        for i in range(n - 1, -1, -1):
            rev_cum[i] = factors[i] * rev_cum[i + 1]

        sid_dates = out["date"].values[idxs]
        # side='right' → first event with ex_date > date; product of factors[idx:] applies
        idx_arr = np.searchsorted(ex_dates, sid_dates, side="right")
        adj_factors[idxs] = rev_cum[idx_arr]

    out["adj_close"] = (closes * adj_factors).round(4)
    return out


def load_prices(as_of=None):
    """[sid, date, close, delivery_pct, adj_close] for every sid, ordered by sid, date —
    close > 0, ≤ as_of when given (default: all history, adjusted as of today). Same
    rows the PIT backtest loads (pit.load_raw)."""
    date_clause = f"AND date <= '{as_of}'" if as_of else ""
    prices = read_sql(
        f"SELECT sid, date, close, delivery_pct FROM stock_prices WHERE close > 0 {date_clause} "
        "ORDER BY sid, date"
    )
    adjustments = read_sql("SELECT sid, ex_date, factor FROM corporate_adjustments ORDER BY sid, ex_date")
    return apply_adjustments(prices, adjustments, as_of or pd.Timestamp.today().date())
