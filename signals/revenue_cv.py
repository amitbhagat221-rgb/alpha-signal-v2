"""
Alpha Signal v2 — Revenue Volatility (5-year CV)

Reads:  fundamentals_screener (annual Sales rows), stocks
Writes: revenue_cv_scores

  yoy_growth[t]  = sales[t] / sales[t-1] − 1
  revenue_cv_5y  = stdev(yoy_growth over last 5 yrs) / |mean(yoy_growth)|

Lower CV = more predictable revenue trajectory. Used as a quality factor:
the low-volatility anomaly is well-documented; top-line stability is also
a leading indicator of bottom-line stability (different from existing
earnings_persistence which measures EPS CV).

Stocks with mean YoY growth near zero have unstable CV; we require
|mean growth| ≥ 2% to qualify. Also require ≥ 5 growth observations
(i.e. ≥ 6 years of Sales history).

Usage:
    python -m signals.revenue_cv
    python -m signals.revenue_cv --dry-run
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from db import read_sql, upsert_df

MIN_YEARS = 6                  # need 6 years to get 5 YoY growth values
MIN_ABS_MEAN_GROWTH = 0.02     # filter near-zero mean growers (unstable CV)


def _load_data():
    stocks = read_sql("SELECT sid, sector FROM stocks WHERE ticker IS NOT NULL")
    sids = set(stocks["sid"])

    fund = read_sql(
        "SELECT sid, period_end, value "
        "FROM fundamentals_screener "
        "WHERE period_type = 'annual' AND line_item = 'Sales'"
    )
    fund = fund[fund["sid"].isin(sids)].copy()
    return stocks, fund


def _compute(fund):
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
            if prev is None or prev == 0:
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

    return pd.DataFrame(rows)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(fund)

    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "revenue_cv_5y", "mean_growth", "years_used"]]

    n = len(df)
    if n:
        cv = df["revenue_cv_5y"]
        print(f"Revenue CV: {n} stocks scored | "
              f"median={cv.median():.2f} | "
              f"p25={cv.quantile(0.25):.2f} | p75={cv.quantile(0.75):.2f}")
    else:
        print("Revenue CV: 0 stocks scored — Sales history thin.")

    if dry_run:
        print("Dry run — not saving.")
        return n

    rows = upsert_df(df, "revenue_cv_scores")
    print(f"Saved {rows} rows to revenue_cv_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
