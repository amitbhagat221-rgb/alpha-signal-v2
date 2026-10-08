"""
Alpha Signal v2 — Revenue Volatility (5-year CV)

Reads:  fundamentals_screener (annual Sales rows), stocks
Computed point in time only (pit.py); the live step that wrote its *_scores table had no reader and was removed (plan 0020, 2026-10).

  yoy_growth[t]  = sales[t] / sales[t-1] − 1
  revenue_cv_5y  = stdev(yoy_growth over last 5 yrs) / |mean(yoy_growth)|

Lower CV = more predictable revenue trajectory. Used as a quality factor:
the low-volatility anomaly is well-documented; top-line stability is also
a leading indicator of bottom-line stability (different from existing
earnings_persistence which measures EPS CV).

Stocks with mean YoY growth near zero have unstable CV; we require
|mean growth| ≥ 2% to qualify. Also require ≥ 5 growth observations
(i.e. ≥ 6 years of Sales history).

"""

import numpy as np
import pandas as pd


MIN_YEARS = 6                  # need 6 years to get 5 YoY growth values
MIN_ABS_MEAN_GROWTH = 0.02     # filter near-zero mean growers (unstable CV)


def _compute(stocks, fund):
    """Per-sid 5y revenue CV off annual Sales rows. `stocks` is the universe (unused
    beyond the caller's scoping; kept for the shared (stocks, fund) signature)."""
    if fund.empty:
        return pd.DataFrame(columns=["sid", "revenue_cv_5y", "years_used"])

    fund = fund.sort_values(["sid", "period_end"])
    rows = []
    for sid, g in fund.groupby("sid"):
        sales = g["value"].dropna().tolist()
        if len(sales) < MIN_YEARS:
            continue
        # Use the latest MIN_YEARS observations; require positive prior period
        # for each YoY ratio.
        sales_window = sales[-MIN_YEARS:]
        growth = []
        for i in range(1, len(sales_window)):
            prev = sales_window[i - 1]
            # A non-positive base makes the growth ratio meaningless (the backtest's rule;
            # live used to skip only prev == 0).
            if prev is None or prev <= 0:
                continue
            growth.append(sales_window[i] / prev - 1)
        if len(growth) < MIN_YEARS - 1:
            continue
        m = float(np.mean(growth))
        if abs(m) < MIN_ABS_MEAN_GROWTH:
            continue
        s = float(np.std(growth, ddof=1))
        cv = s / abs(m)
        rows.append({
            "sid": sid,
            "revenue_cv_5y": round(cv, 4),
            "mean_growth": round(m, 4),
            "years_used": len(growth) + 1,
        })

    return pd.DataFrame(rows, columns=["sid", "revenue_cv_5y", "mean_growth", "years_used"])
