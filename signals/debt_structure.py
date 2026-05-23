"""
Alpha Signal v2 — Debt Structure (LT debt share)

Reads:  fundamentals_screener (annual rows), stocks
Writes: debt_structure_scores

  Ratio = Long term Borrowings_t / Borrowings_t, latest annual period

1.0 = all debt is long-term (no near-term rollover risk).
0.0 = all debt is short-term (high refinancing risk, especially in tight
liquidity environments).

Filter: Total Borrowings ≥ ₹50 cr (debt-light stocks have meaningless ratios).
Stocks that don't separate LT vs ST in their filings → NaN.

Higher is safer; lower flags balance-sheet fragility.

Usage:
    python -m signals.debt_structure
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])
REQUIRED_ITEMS = ["Long term Borrowings", "Borrowings"]
MIN_BORROWINGS_CR = 50.0


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
        return pd.DataFrame(columns=["sid", "period_end", "debt_structure"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Borrowings"] >= MIN_BORROWINGS_CR].copy()
    wide["debt_structure"] = (
        wide["Long term Borrowings"] / wide["Borrowings"]
    ).clip(0.0, 1.0)
    wide = wide.sort_values(["sid", "period_end"])
    latest = wide.groupby("sid", as_index=False).tail(1)
    return latest[["sid", "period_end", "debt_structure"]].reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)
    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "debt_structure"]]
    n = len(df)
    if n:
        v = df["debt_structure"]
        print(f"Debt structure (LT/total): {n} stocks | median={v.median():.3f} | p25={v.quantile(0.25):.3f} | p75={v.quantile(0.75):.3f}")
    else:
        print("Debt structure: 0 stocks scored.")
    if dry_run:
        print("Dry run — not saving.")
        return n
    rows = upsert_df(df, "debt_structure_scores")
    print(f"Saved {rows} rows to debt_structure_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
