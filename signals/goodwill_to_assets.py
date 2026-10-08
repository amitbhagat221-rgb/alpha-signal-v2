"""
Alpha Signal v2 — Intangibles / Total Assets (Goodwill proxy)

Reads:  fundamentals_screener (annual rows), stocks
Computed point in time only (pit.py); the live step that wrote its *_scores table had no reader and was removed (plan 0020, 2026-10).

  Ratio = Intangible Assets_t / Total_t, latest annual period

Screener doesn't separate goodwill from other intangibles, so this is an
"intangibles intensity" proxy. High ratio signals acquisition-driven growth
and higher impairment risk; the literature shows high-intangibles portfolios
underperform on average post-acquisition.

Stocks without an Intangible Assets line item are NaN (not 0) — absence may
mean the line wasn't reported, not that the firm has none.

"""

import numpy as np
import pandas as pd


REQUIRED_ITEMS = ["Intangible Assets", "Total"]
MIN_ASSETS_CR = 50.0


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "goodwill_to_assets"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Total"] >= MIN_ASSETS_CR].copy()
    wide["goodwill_to_assets"] = wide["Intangible Assets"] / wide["Total"]
    wide = wide.sort_values(["sid", "period_end"])
    latest = wide.groupby("sid", as_index=False).tail(1)
    return latest[["sid", "period_end", "goodwill_to_assets"]].reset_index(drop=True)
