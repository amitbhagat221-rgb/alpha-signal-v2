"""
Alpha Signal v2 — Free Cash Flow Yield

Reads:  fundamentals_screener (annual rows), stocks
Writes: fcf_yield_scores

  Capex_t   = max(Δ(Net Block + CWIP), 0) + Depreciation_t
  FCF_t     = OCF_t − Capex_t
  Yield     = median(FCF_t over last 3 yrs) / market_cap_cr

The Δ(Net Block + CWIP) term captures growth capex; Depreciation captures
maintenance capex. Adding both is conservative (overstates capex slightly,
biasing the yield down) but defensible in the absence of a clean capex
line-item breakdown in the Data Sheet.

Financials excluded — capex semantics differ for banks/NBFCs.

Usage:
    python -m signals.fcf_yield
    python -m signals.fcf_yield --dry-run
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])

REQUIRED_ITEMS = [
    "Cash from Operating Activity",
    "Net Block",
    "Capital Work in Progress",
    "Depreciation",
]

SMOOTH_YEARS = 3
# stocks.market_cap_cr is misnamed — values are stored in raw rupees, not
# crores (RELI shows 1.83e13 = ₹18.3L cr, matches reality). Convert to
# crores so it lines up with fundamentals_screener line items, which are in
# ₹cr.
RUPEES_PER_CRORE = 1e7
MIN_MARKET_CAP_CR = SCREEN["min_market_cap_cr"]  # 200


def _load_data():
    placeholders = ",".join("?" for _ in FINANCIAL_SECTORS)
    stocks = read_sql(
        f"SELECT sid, sector, market_cap_cr FROM stocks "
        f"WHERE sector NOT IN ({placeholders}) "
        f"AND market_cap_cr >= ?",
        params=list(FINANCIAL_SECTORS) + [MIN_MARKET_CAP_CR * RUPEES_PER_CRORE],
    )
    stocks = stocks.copy()
    stocks["market_cap_cr"] = stocks["market_cap_cr"] / RUPEES_PER_CRORE

    fund = read_sql(
        "SELECT sid, period_end, line_item, value "
        "FROM fundamentals_screener "
        "WHERE period_type = 'annual' AND line_item IN "
        f"({','.join('?' for _ in REQUIRED_ITEMS)})",
        params=REQUIRED_ITEMS,
    )
    fund = fund[fund["sid"].isin(set(stocks["sid"]))].copy()
    return stocks, fund


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "fcf", "market_cap_cr", "fcf_yield"])

    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index().sort_values(["sid", "period_end"])

    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)

    # PP&E_t = Net Block + CWIP (the productive-asset base before depreciation hit).
    wide["ppe"] = wide["Net Block"] + wide["Capital Work in Progress"]

    # Capex needs the prior-year PP&E. Shift within each sid; drop years with no prior.
    wide["ppe_prev"] = wide.groupby("sid")["ppe"].shift(1)
    wide = wide.dropna(subset=["ppe_prev"])

    delta_ppe = (wide["ppe"] - wide["ppe_prev"]).clip(lower=0.0)
    wide["capex"] = delta_ppe + wide["Depreciation"]
    wide["fcf_yr"] = wide["Cash from Operating Activity"] - wide["capex"]

    # Last SMOOTH_YEARS years per stock; require all slots filled.
    last_n = wide.groupby("sid", as_index=False).tail(SMOOTH_YEARS)
    agg = last_n.groupby("sid", as_index=False).agg(
        period_end=("period_end", "max"),
        fcf=("fcf_yr", "median"),
        years_used=("fcf_yr", "count"),
    )
    agg = agg[agg["years_used"] >= SMOOTH_YEARS]

    agg = agg.merge(stocks[["sid", "market_cap_cr"]], on="sid", how="left")
    agg = agg[agg["market_cap_cr"].notna() & (agg["market_cap_cr"] > 0)]
    # market_cap is in ₹cr; FCF is in ₹cr; yield is dimensionless.
    agg["fcf_yield"] = agg["fcf"] / agg["market_cap_cr"]
    return agg[["sid", "period_end", "fcf", "market_cap_cr", "fcf_yield"]].reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)

    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "fcf", "market_cap_cr", "fcf_yield"]]

    n = len(df)
    if n:
        y = df["fcf_yield"]
        print(f"FCF Yield: {n} stocks scored | "
              f"median={y.median():.3f} | "
              f"p25={y.quantile(0.25):.3f} | p75={y.quantile(0.75):.3f}")
    else:
        print("FCF Yield: 0 stocks scored — fundamentals_screener thin.")

    if dry_run:
        print("Dry run — not saving.")
        return n

    rows = upsert_df(df, "fcf_yield_scores")
    print(f"Saved {rows} rows to fcf_yield_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
