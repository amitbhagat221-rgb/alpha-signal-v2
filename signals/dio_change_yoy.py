"""
Alpha Signal v2 — Days Inventory Outstanding, YoY change

Reads:  fundamentals_screener (annual rows), stocks
Writes: dio_change_yoy_scores

  DIO_t = Inventory_t / (Sales_t / 365)
  Δ DIO = DIO_t − DIO_{t-1}   (days)

Rising DIO = inventory accumulating faster than sales — slowing demand,
obsolescence, or aggressive production. Yellow flag in forensic screens.

Usage:
    python -m signals.dio_change_yoy
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])
REQUIRED_ITEMS = ["Sales", "Inventory"]
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
        return pd.DataFrame(columns=["sid", "period_end", "dio_change_yoy"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Sales"] >= MIN_SALES_CR].copy()
    wide["dio"] = wide["Inventory"] / (wide["Sales"] / 365.0)
    wide = wide.sort_values(["sid", "period_end"])
    rows = []
    for sid, g in wide.groupby("sid"):
        if len(g) < 2:
            continue
        latest, prior = g.iloc[-1], g.iloc[-2]
        rows.append({
            "sid": sid,
            "period_end": latest["period_end"],
            "dio_change_yoy": float(latest["dio"] - prior["dio"]),
        })
    if not rows:
        return pd.DataFrame(columns=["sid", "period_end", "dio_change_yoy"])
    return pd.DataFrame(rows).reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)
    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "dio_change_yoy"]]
    n = len(df)
    if n:
        v = df["dio_change_yoy"]
        print(f"DIO change YoY: {n} stocks | median={v.median():.1f}d | p25={v.quantile(0.25):.1f}d | p75={v.quantile(0.75):.1f}d")
    else:
        print("DIO change YoY: 0 stocks scored.")
    if dry_run:
        print("Dry run — not saving.")
        return n
    rows = upsert_df(df, "dio_change_yoy_scores")
    print(f"Saved {rows} rows to dio_change_yoy_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
