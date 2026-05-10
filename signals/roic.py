"""
Alpha Signal v2 — ROIC (Return on Invested Capital)

Reads: fundamentals_screener (annual rows), stocks
Writes: roic_scores

  NOPAT            = (PBT + Interest) × (1 − Tax / PBT)
  Invested Capital = Equity Share Capital + Reserves + Borrowings
  ROIC             = NOPAT / Invested Capital

Uses the latest annual period_end per stock that has all required line items
non-null and PBT > 0 (negative PBT makes the tax-rate calc meaningless).

Financial Services sector excluded — leverage and "invested capital" semantics
differ for banks; routed through the financial sub-model per CLAUDE.md.

Usage:
    python -m signals.roic            # compute and save
    python -m signals.roic --dry-run  # compute, don't save
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])

REQUIRED_ITEMS = [
    "Profit before tax",
    "Tax",
    "Interest",
    "Equity Share Capital",
    "Reserves",
    "Borrowings",
]

# Robustness:
#   - Median ROIC across last N years suppresses one-off PBT spikes
#     (debt write-backs, asset sales).
#   - IC floor drops shell-sized stocks where the ratio is mathematically
#     valid but financially meaningless.
SMOOTH_YEARS = 3
MIN_INVESTED_CAPITAL_CR = 50.0


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
        return pd.DataFrame(columns=["sid", "period_end", "nopat", "invested_capital", "roic"])

    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()

    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)

    pbt = wide["Profit before tax"]
    interest = wide["Interest"]
    tax = wide["Tax"]
    # Tax adjustment only meaningful when PBT > 0; loss years use raw EBIT.
    tax_rate = np.where(pbt > 0, (tax / pbt.replace(0, np.nan)).clip(0.0, 1.0), 0.0)
    wide["nopat"] = (pbt + interest) * (1 - tax_rate)
    wide["invested_capital"] = (
        wide["Equity Share Capital"] + wide["Reserves"] + wide["Borrowings"]
    )
    wide = wide[wide["invested_capital"] >= MIN_INVESTED_CAPITAL_CR].copy()
    wide["roic_yr"] = wide["nopat"] / wide["invested_capital"]

    # Last SMOOTH_YEARS calendar years per stock (regardless of PBT sign).
    # Loss years pull the median down; one-off PBT spikes are middle-ranked,
    # not extreme. Require all SMOOTH_YEARS slots filled — short-history
    # stocks are filtered out rather than scored on a fragile sample.
    wide = wide.sort_values(["sid", "period_end"])
    last_n = wide.groupby("sid", as_index=False).tail(SMOOTH_YEARS)

    agg = last_n.groupby("sid", as_index=False).agg(
        period_end=("period_end", "max"),
        nopat=("nopat", "median"),
        invested_capital=("invested_capital", "median"),
        roic=("roic_yr", "median"),
        years_used=("roic_yr", "count"),
    )
    agg = agg[(agg["years_used"] >= SMOOTH_YEARS) & (agg["roic"] > 0)]
    return agg[["sid", "period_end", "nopat", "invested_capital", "roic"]].reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)

    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "nopat", "invested_capital", "roic"]]

    n = len(df)
    if n:
        roic = df["roic"]
        print(f"ROIC: {n} stocks scored | "
              f"median={roic.median():.3f} | "
              f"p25={roic.quantile(0.25):.3f} | p75={roic.quantile(0.75):.3f}")
    else:
        print("ROIC: 0 stocks scored — fundamentals_screener has no qualifying annual rows yet.")

    if dry_run:
        print("Dry run — not saving.")
        return n

    rows = upsert_df(df, "roic_scores")
    print(f"Saved {rows} rows to roic_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
