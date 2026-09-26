"""
Alpha Signal v2 — Intangibles / Total Assets (Goodwill proxy)

Reads:  fundamentals_screener (annual rows), stocks
Writes: goodwill_to_assets_scores

  Ratio = Intangible Assets_t / Total_t, latest annual period

Screener doesn't separate goodwill from other intangibles, so this is an
"intangibles intensity" proxy. High ratio signals acquisition-driven growth
and higher impairment risk; the literature shows high-intangibles portfolios
underperform on average post-acquisition.

Stocks without an Intangible Assets line item are NaN (not 0) — absence may
mean the line wasn't reported, not that the firm has none.

Usage:
    python -m signals.goodwill_to_assets
"""

import numpy as np
import pandas as pd

from signals import _annual

REQUIRED_ITEMS = ["Intangible Assets", "Total"]
MIN_ASSETS_CR = 50.0


def _load_data():
    return _annual.load(REQUIRED_ITEMS)


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


def compute(dry_run=False):
    return _annual.save(_compute(*_load_data()), "goodwill_to_assets_scores", "Intangibles/Assets", "goodwill_to_assets",
                        dry_run, fmt=".3f")


if __name__ == "__main__":
    _annual.cli(compute)
