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

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql
from signals import _annual

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])

REQUIRED_ITEMS = [
    "Cash from Operating Activity",
    "Net Block",
    "Capital Work in Progress",
    "Depreciation",
]

SMOOTH_YEARS = 3
MIN_MARKET_CAP_CR = SCREEN["min_market_cap_cr"]  # 200


def _load_data():
    placeholders = ",".join("?" for _ in FINANCIAL_SECTORS)
    stocks = read_sql(
        f"SELECT sid, sector, market_cap_cr FROM stocks "
        f"WHERE sector NOT IN ({placeholders}) "
        f"AND market_cap_cr >= ?",
        params=list(FINANCIAL_SECTORS) + [MIN_MARKET_CAP_CR],
    )
    stocks = stocks.copy()

    fund = read_sql(
        "SELECT sid, period_end, line_item, value "
        "FROM fundamentals_screener "
        "WHERE period_type = 'annual' AND line_item IN "
        f"({','.join('?' for _ in REQUIRED_ITEMS)})",
        params=REQUIRED_ITEMS,
    )
    fund = fund[fund["sid"].isin(set(stocks["sid"]))].copy()
    return stocks, fund


def fcf_median(fund):
    """Per-sid median FCF (₹cr) over the last SMOOTH_YEARS years, all slots filled —
    the numerator the live yield and pit.py:pit_fcf_yield share
    (they differ only in the market-cap denominator's source).
    Returns DataFrame[sid, period_end, fcf, years_used]."""
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "fcf", "years_used"])

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
    return agg[agg["years_used"] >= SMOOTH_YEARS]


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "fcf", "market_cap_cr", "fcf_yield"])
    agg = fcf_median(fund)
    agg = agg.merge(stocks[["sid", "market_cap_cr"]], on="sid", how="left")
    agg = agg[agg["market_cap_cr"].notna() & (agg["market_cap_cr"] > 0)]
    # market_cap is in ₹cr; FCF is in ₹cr; yield is dimensionless.
    agg["fcf_yield"] = agg["fcf"] / agg["market_cap_cr"]
    return agg[["sid", "period_end", "fcf", "market_cap_cr", "fcf_yield"]].reset_index(drop=True)


def compute(dry_run=False):
    return _annual.save(_compute(*_load_data()), "fcf_yield_scores", "FCF Yield", "fcf_yield",
                        dry_run, fmt=".3f")


if __name__ == "__main__":
    _annual.cli(compute)
