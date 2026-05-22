"""
Alpha Signal v2 — Sector-Relative Sales Growth

Reads:  fundamentals_screener (annual Sales), stocks
Writes: sales_growth_relative_scores

  sales_growth_yoy[t]   = sales[t] / sales[t-1] − 1                (3-yr median)
  sector_median_growth  = median(sales_growth_yoy) within sector
  relative_growth       = sales_growth_yoy − sector_median_growth

Stocks growing FASTER than their sector are taking share or expanding the
addressable market — both alpha. Stocks growing SLOWER are losing the
structural battle even if absolute growth looks fine.

Existing `revenue_growth_yoy` factor is absolute. A 15% Pharma stock looks
fast in isolation but is *underperforming* the 22% sector. This factor fixes
the comparison.

Smoothing: 3-yr median per the Track 3 convention.

Usage:
    python -m signals.sales_growth_relative
    python -m signals.sales_growth_relative --dry-run
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])
SMOOTH_YEARS = 3


def _load_data():
    placeholders = ",".join("?" for _ in FINANCIAL_SECTORS)
    stocks = read_sql(
        f"SELECT sid, sector FROM stocks WHERE sector NOT IN ({placeholders})",
        params=list(FINANCIAL_SECTORS),
    )
    sids = set(stocks["sid"])

    fund = read_sql(
        "SELECT sid, period_end, value "
        "FROM fundamentals_screener "
        "WHERE period_type = 'annual' AND line_item = 'Sales'"
    )
    fund = fund[fund["sid"].isin(sids)].copy()
    return stocks, fund


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "sales_growth", "sector_median", "relative_growth"])

    fund = fund.sort_values(["sid", "period_end"])
    fund["prev_sales"] = fund.groupby("sid")["value"].shift(1)
    fund = fund.dropna(subset=["prev_sales"])
    fund = fund[fund["prev_sales"] > 0]
    fund["growth_yr"] = fund["value"] / fund["prev_sales"] - 1

    # 3-year median growth per stock
    last_n = fund.groupby("sid", as_index=False).tail(SMOOTH_YEARS)
    agg = last_n.groupby("sid", as_index=False).agg(
        period_end=("period_end", "max"),
        sales_growth=("growth_yr", "median"),
        years_used=("growth_yr", "count"),
    )
    agg = agg[agg["years_used"] >= SMOOTH_YEARS]

    # Sector medians
    agg = agg.merge(stocks[["sid", "sector"]], on="sid", how="left")
    sector_median = agg.groupby("sector")["sales_growth"].median().to_dict()
    agg["sector_median"] = agg["sector"].map(sector_median)
    agg["relative_growth"] = agg["sales_growth"] - agg["sector_median"]

    return agg[["sid", "period_end", "sales_growth", "sector_median", "relative_growth"]].reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)

    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "sales_growth", "sector_median", "relative_growth"]]

    n = len(df)
    if n:
        rg = df["relative_growth"]
        print(f"Sales growth (sector-relative): {n} stocks scored | "
              f"absolute median={df['sales_growth'].median():.2%} | "
              f"relative p25={rg.quantile(0.25):.2%} · p75={rg.quantile(0.75):.2%}")
    else:
        print("Sales growth (sector-relative): 0 stocks scored.")

    if dry_run:
        print("Dry run — not saving.")
        return n

    rows = upsert_df(df, "sales_growth_relative_scores")
    print(f"Saved {rows} rows to sales_growth_relative_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
