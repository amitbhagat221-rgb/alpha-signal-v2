"""
Alpha Signal v2 — CapEx / Depreciation ratio

Reads:  fundamentals_screener (annual rows), stocks
Computed point in time only (pit.py); the live step that wrote its *_scores table had no reader and was removed (plan 0020, 2026-10).

  Capex_t   = max(Δ(Net Block + CWIP), 0) + Depreciation_t
  Ratio_t   = Capex_t / Depreciation_t
  Score     = median(Ratio_t over last 3 yrs)

>1 means the company is investing more than it's wearing out — growing.
<1 means it's harvesting — running the assets down. ~1 is steady-state.

Useful as a capital-allocation cycle signal. Filter: Depreciation ≥ ₹1 cr
to drop asset-light services (where the ratio is meaningless).

Capped to ±20 to keep distressed names from dominating the rank.

"""

import numpy as np
import pandas as pd


REQUIRED_ITEMS = ["Net Block", "Capital Work in Progress", "Depreciation"]
SMOOTH_YEARS = 3
MIN_DEPRECIATION_CR = 1.0
RATIO_CAP = 20.0


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "capex_to_dep"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index().sort_values(["sid", "period_end"])
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Depreciation"] >= MIN_DEPRECIATION_CR].copy()
    wide["ppe"] = wide["Net Block"] + wide["Capital Work in Progress"]
    wide["ppe_prev"] = wide.groupby("sid")["ppe"].shift(1)
    wide = wide.dropna(subset=["ppe_prev"])
    delta_ppe = (wide["ppe"] - wide["ppe_prev"]).clip(lower=0.0)
    wide["capex"] = delta_ppe + wide["Depreciation"]
    wide["ratio_yr"] = (wide["capex"] / wide["Depreciation"]).clip(-RATIO_CAP, RATIO_CAP)

    last_n = wide.groupby("sid", as_index=False).tail(SMOOTH_YEARS)
    agg = last_n.groupby("sid", as_index=False).agg(
        period_end=("period_end", "max"),
        capex_to_dep=("ratio_yr", "median"),
        years_used=("ratio_yr", "count"),
    )
    agg = agg[agg["years_used"] >= SMOOTH_YEARS]
    return agg[["sid", "period_end", "capex_to_dep"]].reset_index(drop=True)
