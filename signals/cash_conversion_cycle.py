"""
Alpha Signal v2 — Cash Conversion Cycle

Reads:  fundamentals_screener (annual rows), stocks
Writes: cash_conversion_cycle_scores

  DSO = Receivables    / (Sales / 365)
  DIO = Inventory      / (Sales / 365)
  DPO = Trade Payables / (Sales / 365)
  CCC = DSO + DIO − DPO

Sales is used as the denominator for all three legs. Screener doesn't expose
a clean COGS line — "Raw Material Cost" misses labour and overheads, and
isn't populated for service businesses at all. The bias (Sales > COGS)
inflates DIO/DPO by the same factor across all stocks, so within-tier
ranking is preserved.

Lower (or more negative) CCC = tighter working-capital cycle, generally
higher quality.

Smoothing: 3-year median per stock — suppresses one-off year-end working
capital tactics (channel stuffing, supplier-financing programs).

Financial Services excluded — banks/NBFCs have deposits, not Trade Payables,
and the cycle metaphor doesn't apply. Routed through the financial sub-model
per CLAUDE.md.

Usage:
    python -m signals.cash_conversion_cycle
    python -m signals.cash_conversion_cycle --dry-run
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
    "Receivables",
    "Inventory",
    "Trade Payables",
]

SMOOTH_YEARS = 3
# Filter out shell-sized stocks where the cycle is mathematically defined
# but financially meaningless (₹1 cr annual sales etc.).
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
        return pd.DataFrame(columns=["sid", "period_end", "dso", "dio", "dpo", "ccc"])

    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()

    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Sales"] >= MIN_SALES_CR].copy()

    daily_sales = wide["Sales"] / 365.0
    wide["dso_yr"] = wide["Receivables"]    / daily_sales
    wide["dio_yr"] = wide["Inventory"]      / daily_sales
    wide["dpo_yr"] = wide["Trade Payables"] / daily_sales
    wide["ccc_yr"] = wide["dso_yr"] + wide["dio_yr"] - wide["dpo_yr"]

    wide = wide.sort_values(["sid", "period_end"])
    last_n = wide.groupby("sid", as_index=False).tail(SMOOTH_YEARS)

    agg = last_n.groupby("sid", as_index=False).agg(
        period_end=("period_end", "max"),
        dso=("dso_yr", "median"),
        dio=("dio_yr", "median"),
        dpo=("dpo_yr", "median"),
        ccc=("ccc_yr", "median"),
        years_used=("ccc_yr", "count"),
    )
    agg = agg[agg["years_used"] >= SMOOTH_YEARS]
    return agg[["sid", "period_end", "dso", "dio", "dpo", "ccc"]].reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)

    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "dso", "dio", "dpo", "ccc"]]

    n = len(df)
    if n:
        c = df["ccc"]
        print(f"CCC: {n} stocks scored | "
              f"median={c.median():.1f}d | "
              f"p25={c.quantile(0.25):.1f}d | p75={c.quantile(0.75):.1f}d | "
              f"negative={(c < 0).sum()}")
    else:
        print("CCC: 0 stocks scored — fundamentals_screener has no qualifying annual rows yet.")

    if dry_run:
        print("Dry run — not saving.")
        return n

    rows = upsert_df(df, "cash_conversion_cycle_scores")
    print(f"Saved {rows} rows to cash_conversion_cycle_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
