"""
Alpha Signal v2 — Inventory Turnover (sector-relative)

Reads:  fundamentals_screener (annual Sales + Inventory), stocks
Writes: inventory_turnover_scores

  inventory_turnover  = Sales / avg(Inventory)         (annual)
  sector_p50          = median(turnover) for stocks in same sector
  relative_turnover   = inventory_turnover / sector_p50

Higher turnover = more efficient working-capital management. Within-sector
relative because Pharma (~3-4x) and Retail (~10-15x) have very different
absolute scales.

Excluded:
  - Financial Services (no inventory)
  - Sectors with inherently zero/near-zero inventory: Information Technology,
    Communication Services, Utilities (banks, telcos, IT firms hold no goods)
  - Stocks with avg inventory < ₹1 cr (numerical instability)

Smoothing: 3-year median of yearly turnover, same convention as ROIC / FCFY.

Usage:
    python -m signals.inventory_turnover
    python -m signals.inventory_turnover --dry-run
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

# Sectors where inventory is structurally absent or meaningless
EXCLUDED_SECTORS = set(SCREEN["financial_sectors"]) | {
    "Information Technology",
    "Communication Services",
    "Utilities",
}

SMOOTH_YEARS = 3
MIN_AVG_INVENTORY_CR = 1.0


def _load_data():
    placeholders = ",".join("?" for _ in EXCLUDED_SECTORS)
    stocks = read_sql(
        f"SELECT sid, sector FROM stocks WHERE sector NOT IN ({placeholders})",
        params=list(EXCLUDED_SECTORS),
    )
    sids = set(stocks["sid"])

    fund = read_sql(
        "SELECT sid, period_end, line_item, value "
        "FROM fundamentals_screener "
        "WHERE period_type = 'annual' AND line_item IN ('Sales', 'Inventory')"
    )
    fund = fund[fund["sid"].isin(sids)].copy()
    return stocks, fund


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "inventory_turnover", "sector_p50", "relative_turnover"])

    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()

    for col in ("Sales", "Inventory"):
        if col not in wide.columns:
            wide[col] = np.nan
    wide = wide.dropna(subset=["Sales", "Inventory"])
    wide = wide[wide["Inventory"] >= MIN_AVG_INVENTORY_CR]
    wide = wide[wide["Sales"] > 0]

    wide["turnover_yr"] = wide["Sales"] / wide["Inventory"]

    # 3-year median turnover per stock
    wide = wide.sort_values(["sid", "period_end"])
    last_n = wide.groupby("sid", as_index=False).tail(SMOOTH_YEARS)
    agg = last_n.groupby("sid", as_index=False).agg(
        period_end=("period_end", "max"),
        inventory_turnover=("turnover_yr", "median"),
        years_used=("turnover_yr", "count"),
    )
    agg = agg[agg["years_used"] >= SMOOTH_YEARS]

    # Attach sector + compute sector medians
    agg = agg.merge(stocks[["sid", "sector"]], on="sid", how="left")
    sector_p50 = agg.groupby("sector")["inventory_turnover"].median().to_dict()
    agg["sector_p50"] = agg["sector"].map(sector_p50)
    agg["relative_turnover"] = agg["inventory_turnover"] / agg["sector_p50"]

    return agg[["sid", "period_end", "inventory_turnover", "sector_p50", "relative_turnover"]].reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)

    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "inventory_turnover", "sector_p50", "relative_turnover"]]

    n = len(df)
    if n:
        rt = df["relative_turnover"]
        print(f"Inventory turnover: {n} stocks scored | "
              f"absolute median={df['inventory_turnover'].median():.2f}× | "
              f"relative median={rt.median():.2f} | p25={rt.quantile(0.25):.2f} | p75={rt.quantile(0.75):.2f}")
    else:
        print("Inventory turnover: 0 stocks scored.")

    if dry_run:
        print("Dry run — not saving.")
        return n

    rows = upsert_df(df, "inventory_turnover_scores")
    print(f"Saved {rows} rows to inventory_turnover_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
