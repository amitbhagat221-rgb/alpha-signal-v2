"""
Alpha Signal v2 — Asset Tangibility (Net Block / Total Assets)

Reads:  fundamentals_screener (annual rows), stocks
Computed point in time only (pit.py); the live step that wrote its *_scores table had no reader and was removed (plan 0020, 2026-10).

  Ratio = Net Block_t / Total_t, latest annual period

Higher = capex-heavy / asset-rich business model (utilities, cement, steel).
Lower = asset-light (IT services, FMCG). Useful as a structural style tag,
and as a risk-attribution input — asset-heavy names behave differently in
rate cycles.

This is descriptive more than predictive; whether it's predictive on the
return cross-section depends on the regime. We'll learn from the backtest.

"""

import numpy as np
import pandas as pd


REQUIRED_ITEMS = ["Net Block", "Total"]
MIN_ASSETS_CR = 50.0


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
