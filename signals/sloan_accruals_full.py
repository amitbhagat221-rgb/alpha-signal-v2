"""
Alpha Signal v2 — Sloan Accruals (full balance-sheet formula)

Reads:  fundamentals_screener (annual rows), stocks
Writes: sloan_accruals_full_scores

  NWC_t   = Receivables_t + Inventory_t − Trade Payables_t
  ΔNWC    = NWC_t − NWC_{t-1}
  TA_avg  = (Total_t + Total_{t-1}) / 2
  Sloan   = (ΔNWC − Depreciation_t) / TA_avg

The original Sloan (1996) accruals measure. Captures earnings quality:
high accruals (positive Sloan) = lots of non-cash income that hasn't shown
up in operating cash flow yet → lower-quality earnings, tend to mean-revert.

Lower is better (negative Sloan = cash-rich earnings).

Note: this complements `cf_accruals` (already in production) which uses CF
statement directly. This uses the BS-construction formula — the gap between
the two is itself a forensic signal but we're not encoding that here.

Usage:
    python -m signals.sloan_accruals_full
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])
REQUIRED_ITEMS = ["Receivables", "Inventory", "Trade Payables", "Depreciation", "Total"]
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
        return pd.DataFrame(columns=["sid", "period_end", "sloan_accruals_full"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Total"] >= MIN_ASSETS_CR].copy()
    wide["nwc"] = wide["Receivables"] + wide["Inventory"] - wide["Trade Payables"]
    wide = wide.sort_values(["sid", "period_end"])

    rows = []
    for sid, g in wide.groupby("sid"):
        if len(g) < 2:
            continue
        latest, prior = g.iloc[-1], g.iloc[-2]
        ta_avg = (latest["Total"] + prior["Total"]) / 2.0
        if ta_avg <= 0:
            continue
        sloan = (latest["nwc"] - prior["nwc"] - latest["Depreciation"]) / ta_avg
        rows.append({
            "sid": sid,
            "period_end": latest["period_end"],
            "sloan_accruals_full": float(sloan),
        })
    if not rows:
        return pd.DataFrame(columns=["sid", "period_end", "sloan_accruals_full"])
    return pd.DataFrame(rows).reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)
    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "sloan_accruals_full"]]
    n = len(df)
    if n:
        v = df["sloan_accruals_full"]
        print(f"Sloan accruals (full): {n} stocks | median={v.median():.4f} | p25={v.quantile(0.25):.4f} | p75={v.quantile(0.75):.4f}")
    else:
        print("Sloan accruals (full): 0 stocks scored.")
    if dry_run:
        print("Dry run — not saving.")
        return n
    rows = upsert_df(df, "sloan_accruals_full_scores")
    print(f"Saved {rows} rows to sloan_accruals_full_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
