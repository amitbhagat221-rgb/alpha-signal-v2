"""
Alpha Signal v2 — Asset Tangibility (Net Block / Total Assets)

Reads:  fundamentals_screener (annual rows), stocks
Writes: asset_tangibility_scores

  Ratio = Net Block_t / Total_t, latest annual period

Higher = capex-heavy / asset-rich business model (utilities, cement, steel).
Lower = asset-light (IT services, FMCG). Useful as a structural style tag,
and as a risk-attribution input — asset-heavy names behave differently in
rate cycles.

This is descriptive more than predictive; whether it's predictive on the
return cross-section depends on the regime. We'll learn from the backtest.

Usage:
    python -m signals.asset_tangibility
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])
REQUIRED_ITEMS = ["Net Block", "Total"]
MIN_ASSETS_CR = 50.0


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
        return pd.DataFrame(columns=["sid", "period_end", "asset_tangibility"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Total"] >= MIN_ASSETS_CR].copy()
    wide["asset_tangibility"] = (wide["Net Block"] / wide["Total"]).clip(0.0, 1.0)
    wide = wide.sort_values(["sid", "period_end"])
    latest = wide.groupby("sid", as_index=False).tail(1)
    return latest[["sid", "period_end", "asset_tangibility"]].reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)
    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "asset_tangibility"]]
    n = len(df)
    if n:
        v = df["asset_tangibility"]
        print(f"Asset tangibility: {n} stocks | median={v.median():.3f} | p25={v.quantile(0.25):.3f} | p75={v.quantile(0.75):.3f}")
    else:
        print("Asset tangibility: 0 stocks scored.")
    if dry_run:
        print("Dry run — not saving.")
        return n
    rows = upsert_df(df, "asset_tangibility_scores")
    print(f"Saved {rows} rows to asset_tangibility_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
