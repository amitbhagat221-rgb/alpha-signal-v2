"""
Alpha Signal v2 — Net Working Capital to Revenue (latest annual)

Reads:  fundamentals_screener (annual rows), stocks
Writes: nwc_to_revenue_scores

  NWC = Receivables + Inventory − Trade Payables
  Ratio = NWC / Sales, latest annual period

Spot (not smoothed) sibling of `wc_intensity`. The 3y-median version captures
the steady-state cycle; this latest-year version catches recent shifts.
Higher = more cash tied up in operating cycle.

Usage:
    python -m signals.nwc_to_revenue
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])
REQUIRED_ITEMS = ["Sales", "Receivables", "Inventory", "Trade Payables"]
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
        return pd.DataFrame(columns=["sid", "period_end", "nwc_to_revenue"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Sales"] >= MIN_SALES_CR].copy()
    wide["nwc_to_revenue"] = (
        wide["Receivables"] + wide["Inventory"] - wide["Trade Payables"]
    ) / wide["Sales"]
    wide = wide.sort_values(["sid", "period_end"])
    latest = wide.groupby("sid", as_index=False).tail(1)
    return latest[["sid", "period_end", "nwc_to_revenue"]].reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)
    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "nwc_to_revenue"]]
    n = len(df)
    if n:
        v = df["nwc_to_revenue"]
        print(f"NWC/Revenue: {n} stocks | median={v.median():.3f} | p25={v.quantile(0.25):.3f} | p75={v.quantile(0.75):.3f}")
    else:
        print("NWC/Revenue: 0 stocks scored.")
    if dry_run:
        print("Dry run — not saving.")
        return n
    rows = upsert_df(df, "nwc_to_revenue_scores")
    print(f"Saved {rows} rows to nwc_to_revenue_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
