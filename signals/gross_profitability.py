"""
Alpha Signal v2 — Gross Profitability (Novy-Marx anchor)

Reads:  fundamentals_screener (annual rows), stocks
Writes: gross_profitability_scores

  COGS                 = Raw Material Cost + Change in Inventory
                         + Power and Fuel + Other Mfr. Exp
  Gross Profit         = Sales − COGS
  Gross Profitability  = Gross Profit / Total Assets

The single most robust standalone quality predictor in the cross-section
(Novy-Marx 2013): gross-profits-to-assets carries the largest information
ratio of the common quality measures and is *cleaner* than earnings because it
sits above SG&A, R&D and depreciation — the lines where managers bury growth
investment. Anchor quality factor of the multibagger funnel
(docs/reference/multibagger-research.md, finding #1).

COGS note: Screener.in's Indian feed has no single "COGS" line, so we sum the
direct-manufacturing cost lines. We REQUIRE `Raw Material Cost` to be present —
pure service/IT names (no raw material) are left unscored (NaN) rather than
handed a spurious Sales−0 gross profit; they lean on the other quality factors.

Financial Services excluded — "total assets" and gross-margin semantics differ
for banks; routed through the financial sub-model per CLAUDE.md.

Filters:
  - Sales ≥ ₹50 cr, Total assets ≥ ₹50 cr (drop shell-sized names)
  - Raw Material Cost present (else not a goods business → NaN)
  - 3-year median, ≥2 of 3 annual periods present

Usage:
    python -m signals.gross_profitability
    python -m signals.gross_profitability --dry-run
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])

# COGS = sum of direct-manufacturing cost lines. Raw Material Cost is the
# gating component (absent → not a goods business → unscored).
REQUIRED_ITEMS = ["Sales", "Raw Material Cost", "Total"]
OPTIONAL_COGS_ITEMS = ["Change in Inventory", "Power and Fuel", "Other Mfr. Exp"]
ALL_ITEMS = REQUIRED_ITEMS + OPTIONAL_COGS_ITEMS

SMOOTH_YEARS = 3
MIN_YEARS = 2          # ≥2 of last 3 annual periods (multibaggers skew young)
MIN_SALES_CR = 50.0
MIN_ASSETS_CR = 50.0
# Materials-meaningfulness floor: gross-profitability is a GOODS-business
# measure. Labor-intensive services (IT, staffing) report tiny material cost,
# so a materials-only COGS understates their true cost and inflates GP. Require
# materials ≥ 10% of sales — below that, the firm isn't a goods business and is
# left unscored (it leans on the other quality factors). Excludes ~130 names.
MATERIAL_MIN_FRAC = 0.10
GP_CAP = (-1.0, 2.0)   # GP/assets real-world band; cap tail names


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
        f"({','.join('?' for _ in ALL_ITEMS)})",
        params=ALL_ITEMS,
    )
    fund = fund[fund["sid"].isin(sids)].copy()
    return stocks, fund


def _compute(stocks, fund):
    cols = ["sid", "period_end", "gross_profit", "total_assets", "gross_profitability"]
    if fund.empty:
        return pd.DataFrame(columns=cols)

    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()

    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    for item in OPTIONAL_COGS_ITEMS:
        if item not in wide.columns:
            wide[item] = 0.0
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    if wide.empty:
        return pd.DataFrame(columns=cols)
    wide[OPTIONAL_COGS_ITEMS] = wide[OPTIONAL_COGS_ITEMS].fillna(0.0)

    cogs = (wide["Raw Material Cost"] + wide["Change in Inventory"]
            + wide["Power and Fuel"] + wide["Other Mfr. Exp"])
    wide["gross_profit"] = wide["Sales"] - cogs
    wide["total_assets"] = wide["Total"]
    wide = wide[(wide["Sales"] >= MIN_SALES_CR)
                & (wide["total_assets"] >= MIN_ASSETS_CR)
                & (wide["Raw Material Cost"] >= MATERIAL_MIN_FRAC * wide["Sales"])].copy()
    wide["gp_yr"] = (wide["gross_profit"] / wide["total_assets"]).clip(*GP_CAP)

    wide = wide.sort_values(["sid", "period_end"])
    last_n = wide.groupby("sid", as_index=False).tail(SMOOTH_YEARS)
    agg = last_n.groupby("sid", as_index=False).agg(
        period_end=("period_end", "max"),
        gross_profit=("gross_profit", "median"),
        total_assets=("total_assets", "median"),
        gross_profitability=("gp_yr", "median"),
        years_used=("gp_yr", "count"),
    )
    agg = agg[agg["years_used"] >= MIN_YEARS]
    return agg[cols].reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)

    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end",
             "gross_profit", "total_assets", "gross_profitability"]]

    n = len(df)
    if n:
        g = df["gross_profitability"]
        print(f"Gross Profitability: {n} stocks scored | "
              f"median={g.median():.3f} | "
              f"p25={g.quantile(0.25):.3f} | p75={g.quantile(0.75):.3f}")
    else:
        print("Gross Profitability: 0 stocks scored — "
              "fundamentals_screener thin or no qualifying goods businesses.")

    if dry_run:
        print("Dry run — not saving.")
        return n

    rows = upsert_df(df, "gross_profitability_scores")
    print(f"Saved {rows} rows to gross_profitability_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
