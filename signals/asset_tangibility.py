"""
Alpha Signal v2 — Asset Tangibility (Net Block / Total Assets)

Reads:  fundamentals_screener (annual rows), stocks
Writes: asset_tangibility_scores

  Ratio = Net Block_t / Total_t, latest annual period

Higher = capex-heavy / asset-rich business model (utilities, cement, steel).
Lower = asset-light (IT services, FMCG). Useful as a structural style tag,
and as a risk-attribution input — asset-heavy names behave differently in
rate cycles.

This is descriptive more than predictive; whether it's predictive on the
return cross-section depends on the regime. We'll learn from the backtest.

Usage:
    python -m signals.asset_tangibility
"""

import numpy as np
import pandas as pd

from signals import _annual

REQUIRED_ITEMS = ["Net Block", "Total"]
MIN_ASSETS_CR = 50.0


def _load_data():
    return _annual.load(REQUIRED_ITEMS)


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


def compute(dry_run=False):
    return _annual.save(_compute(*_load_data()), "asset_tangibility_scores", "Asset tangibility", "asset_tangibility",
                        dry_run, fmt=".3f")


if __name__ == "__main__":
    _annual.cli(compute)
