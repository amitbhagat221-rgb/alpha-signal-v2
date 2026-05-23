"""
Alpha Signal v2 — Intangibles / Total Assets (Goodwill proxy)

Reads:  fundamentals_screener (annual rows), stocks
Writes: goodwill_to_assets_scores

  Ratio = Intangible Assets_t / Total_t, latest annual period

Screener doesn't separate goodwill from other intangibles, so this is an
"intangibles intensity" proxy. High ratio signals acquisition-driven growth
and higher impairment risk; the literature shows high-intangibles portfolios
underperform on average post-acquisition.

Stocks without an Intangible Assets line item are NaN (not 0) — absence may
mean the line wasn't reported, not that the firm has none.

Usage:
    python -m signals.goodwill_to_assets
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])
REQUIRED_ITEMS = ["Intangible Assets", "Total"]
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
        return pd.DataFrame(columns=["sid", "period_end", "goodwill_to_assets"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Total"] >= MIN_ASSETS_CR].copy()
    wide["goodwill_to_assets"] = wide["Intangible Assets"] / wide["Total"]
    wide = wide.sort_values(["sid", "period_end"])
    latest = wide.groupby("sid", as_index=False).tail(1)
    return latest[["sid", "period_end", "goodwill_to_assets"]].reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)
    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "goodwill_to_assets"]]
    n = len(df)
    if n:
        v = df["goodwill_to_assets"]
        print(f"Intangibles/Assets: {n} stocks | median={v.median():.3f} | p25={v.quantile(0.25):.3f} | p75={v.quantile(0.75):.3f}")
    else:
        print("Intangibles/Assets: 0 stocks scored.")
    if dry_run:
        print("Dry run — not saving.")
        return n
    rows = upsert_df(df, "goodwill_to_assets_scores")
    print(f"Saved {rows} rows to goodwill_to_assets_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
