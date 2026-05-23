"""
Alpha Signal v2 — SG&A Intensity, YoY change

Reads:  fundamentals_screener (annual rows), stocks
Writes: sga_to_revenue_change_scores

  SGA_int_t = "Selling and admin"_t / Sales_t
  Δ         = SGA_int_t − SGA_int_{t-1}

Rising SGA intensity = operating discipline slipping, or sales falling faster
than overheads can be cut. Higher Δ = worse.

"Selling and admin" in Screener is the closest line to GAAP SG&A; it doesn't
include R&D or other overheads broken out separately, but it captures the
sales/marketing engine specifically.

Usage:
    python -m signals.sga_to_revenue_change
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])
REQUIRED_ITEMS = ["Sales", "Selling and admin"]
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
        return pd.DataFrame(columns=["sid", "period_end", "sga_to_revenue_change"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Sales"] >= MIN_SALES_CR].copy()
    wide["sga_int"] = wide["Selling and admin"] / wide["Sales"]
    wide = wide.sort_values(["sid", "period_end"])

    rows = []
    for sid, g in wide.groupby("sid"):
        if len(g) < 2:
            continue
        latest, prior = g.iloc[-1], g.iloc[-2]
        rows.append({
            "sid": sid,
            "period_end": latest["period_end"],
            "sga_to_revenue_change": float(latest["sga_int"] - prior["sga_int"]),
        })
    if not rows:
        return pd.DataFrame(columns=["sid", "period_end", "sga_to_revenue_change"])
    return pd.DataFrame(rows).reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)
    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "sga_to_revenue_change"]]
    n = len(df)
    if n:
        v = df["sga_to_revenue_change"]
        print(f"Δ SGA/Revenue: {n} stocks | median={v.median():.4f} | p25={v.quantile(0.25):.4f} | p75={v.quantile(0.75):.4f}")
    else:
        print("Δ SGA/Revenue: 0 stocks scored.")
    if dry_run:
        print("Dry run — not saving.")
        return n
    rows = upsert_df(df, "sga_to_revenue_change_scores")
    print(f"Saved {rows} rows to sga_to_revenue_change_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
