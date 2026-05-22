"""
Alpha Signal v2 — Working Capital Intensity

Reads:  fundamentals_screener (annual rows), stocks
Writes: working_capital_intensity_scores

  WCI = (Receivables + Inventory − Trade Payables) / Sales
  Reported as the 3-year median per stock.

Sibling of cash_conversion_cycle but expressed as a fraction of revenue
rather than in days. Lower (and especially negative) values mean less
capital is tied up per ₹ of sales — a structural quality marker.

Financial Services excluded.

Usage:
    python -m signals.working_capital_intensity
    python -m signals.working_capital_intensity --dry-run
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])

REQUIRED_ITEMS = ["Sales", "Receivables", "Inventory", "Trade Payables"]
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
        "FROM fundamentals_screener "
        "WHERE period_type = 'annual' AND line_item IN "
        f"({','.join('?' for _ in REQUIRED_ITEMS)})",
        params=REQUIRED_ITEMS,
    )
    fund = fund[fund["sid"].isin(sids)].copy()
    return stocks, fund


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "wc_intensity"])

    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Sales"] >= MIN_SALES_CR].copy()

    wide["wci_yr"] = (
        wide["Receivables"] + wide["Inventory"] - wide["Trade Payables"]
    ) / wide["Sales"]

    wide = wide.sort_values(["sid", "period_end"])
    last_n = wide.groupby("sid", as_index=False).tail(SMOOTH_YEARS)
    agg = last_n.groupby("sid", as_index=False).agg(
        period_end=("period_end", "max"),
        wc_intensity=("wci_yr", "median"),
        years_used=("wci_yr", "count"),
    )
    agg = agg[agg["years_used"] >= SMOOTH_YEARS]
    return agg[["sid", "period_end", "wc_intensity"]].reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)

    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "wc_intensity"]]

    n = len(df)
    if n:
        w = df["wc_intensity"]
        print(f"WC intensity: {n} stocks scored | "
              f"median={w.median():.3f} | "
              f"p25={w.quantile(0.25):.3f} | p75={w.quantile(0.75):.3f} | "
              f"negative={(w < 0).sum()}")
    else:
        print("WC intensity: 0 stocks scored — thin fundamentals.")

    if dry_run:
        print("Dry run — not saving.")
        return n

    rows = upsert_df(df, "working_capital_intensity_scores")
    print(f"Saved {rows} rows to working_capital_intensity_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
