"""
Alpha Signal v2 — Free Cash Flow Margin

Reads:  fundamentals_screener (annual rows), stocks
Writes: fcf_margin_scores

  Capex_t = max(Δ(Net Block + CWIP), 0) + Depreciation_t
  FCF_t   = OCF_t − Capex_t
  Margin  = median(FCF_t / Sales_t over last 3 yrs)

Sister of `fcf_yield`: where FCF Yield is price-relative, FCF Margin is
fundamental-only — captures the cash-generation efficiency of revenue.
Useful for cross-sector quality screens since it doesn't require a valuation
input.

Financials excluded.

Usage:
    python -m signals.fcf_margin
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])
REQUIRED_ITEMS = [
    "Sales",
    "Cash from Operating Activity",
    "Net Block",
    "Capital Work in Progress",
    "Depreciation",
]
SMOOTH_YEARS = 3
MIN_SALES_CR = 50.0


def _load_data():
    placeholders = ",".join("?" for _ in FINANCIAL_SECTORS)
    stocks = read_sql(
        f"SELECT sid, sector FROM stocks WHERE sector NOT IN ({placeholders})",
        params=list(FINANCIAL_SECTORS),
    )
    sids = set(stocks["sid"])
    fund = read_sql(
        "SELECT sid, period_end, line_item, value "
        "FROM fundamentals_screener WHERE period_type = 'annual' "
        f"AND line_item IN ({','.join('?' for _ in REQUIRED_ITEMS)})",
        params=REQUIRED_ITEMS,
    )
    fund = fund[fund["sid"].isin(sids)].copy()
    return stocks, fund


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "fcf_margin"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index().sort_values(["sid", "period_end"])
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Sales"] >= MIN_SALES_CR].copy()
    wide["ppe"] = wide["Net Block"] + wide["Capital Work in Progress"]
    wide["ppe_prev"] = wide.groupby("sid")["ppe"].shift(1)
    wide = wide.dropna(subset=["ppe_prev"])
    delta_ppe = (wide["ppe"] - wide["ppe_prev"]).clip(lower=0.0)
    wide["capex"] = delta_ppe + wide["Depreciation"]
    wide["fcf_margin_yr"] = (wide["Cash from Operating Activity"] - wide["capex"]) / wide["Sales"]

    last_n = wide.groupby("sid", as_index=False).tail(SMOOTH_YEARS)
    agg = last_n.groupby("sid", as_index=False).agg(
        period_end=("period_end", "max"),
        fcf_margin=("fcf_margin_yr", "median"),
        years_used=("fcf_margin_yr", "count"),
    )
    agg = agg[agg["years_used"] >= SMOOTH_YEARS]
    return agg[["sid", "period_end", "fcf_margin"]].reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)
    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "fcf_margin"]]
    n = len(df)
    if n:
        v = df["fcf_margin"]
        print(f"FCF Margin: {n} stocks | median={v.median():.3f} | p25={v.quantile(0.25):.3f} | p75={v.quantile(0.75):.3f}")
    else:
        print("FCF Margin: 0 stocks scored.")
    if dry_run:
        print("Dry run — not saving.")
        return n
    rows = upsert_df(df, "fcf_margin_scores")
    print(f"Saved {rows} rows to fcf_margin_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
