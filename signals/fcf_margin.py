"""
Alpha Signal v2 — Free Cash Flow Margin

Reads:  fundamentals_screener (annual rows), stocks
Computed point in time only (pit.py); the live step that wrote its *_scores table had no reader and was removed (plan 0020, 2026-10).

  Capex_t = max(Δ(Net Block + CWIP), 0) + Depreciation_t
  FCF_t   = OCF_t − Capex_t
  Margin  = median(FCF_t / Sales_t over last 3 yrs)

Sister of `fcf_yield`: where FCF Yield is price-relative, FCF Margin is
fundamental-only — captures the cash-generation efficiency of revenue.
Useful for cross-sector quality screens since it doesn't require a valuation
input.

Financials excluded.

"""

import numpy as np
import pandas as pd


REQUIRED_ITEMS = [
    "Sales",
    "Cash from Operating Activity",
    "Net Block",
    "Capital Work in Progress",
    "Depreciation",
]
SMOOTH_YEARS = 3
MIN_SALES_CR = 50.0


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "fcf_margin"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index().sort_values(["sid", "period_end"])
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Sales"] >= MIN_SALES_CR].copy()
    wide["ppe"] = wide["Net Block"] + wide["Capital Work in Progress"]
    wide["ppe_prev"] = wide.groupby("sid")["ppe"].shift(1)
    wide = wide.dropna(subset=["ppe_prev"])
    delta_ppe = (wide["ppe"] - wide["ppe_prev"]).clip(lower=0.0)
    wide["capex"] = delta_ppe + wide["Depreciation"]
    wide["fcf_margin_yr"] = (wide["Cash from Operating Activity"] - wide["capex"]) / wide["Sales"]

    last_n = wide.groupby("sid", as_index=False).tail(SMOOTH_YEARS)
    agg = last_n.groupby("sid", as_index=False).agg(
        period_end=("period_end", "max"),
        fcf_margin=("fcf_margin_yr", "median"),
        years_used=("fcf_margin_yr", "count"),
    )
    agg = agg[agg["years_used"] >= SMOOTH_YEARS]
    return agg[["sid", "period_end", "fcf_margin"]].reset_index(drop=True)
