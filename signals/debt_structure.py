"""
Alpha Signal v2 — Debt Structure (LT debt share)

Reads:  fundamentals_screener (annual rows), stocks
Writes: debt_structure_scores

  Ratio = Long term Borrowings_t / Borrowings_t, latest annual period

1.0 = all debt is long-term (no near-term rollover risk).
0.0 = all debt is short-term (high refinancing risk, especially in tight
liquidity environments).

Filter: Total Borrowings ≥ ₹50 cr (debt-light stocks have meaningless ratios).
Stocks that don't separate LT vs ST in their filings → NaN.

Higher is safer; lower flags balance-sheet fragility.

Usage:
    python -m signals.debt_structure
"""

import numpy as np
import pandas as pd

from signals import _annual

REQUIRED_ITEMS = ["Long term Borrowings", "Borrowings"]
MIN_BORROWINGS_CR = 50.0


def _load_data():
    return _annual.load(REQUIRED_ITEMS)


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "debt_structure"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Borrowings"] >= MIN_BORROWINGS_CR].copy()
    wide["debt_structure"] = (
        wide["Long term Borrowings"] / wide["Borrowings"]
    ).clip(0.0, 1.0)
    wide = wide.sort_values(["sid", "period_end"])
    latest = wide.groupby("sid", as_index=False).tail(1)
    return latest[["sid", "period_end", "debt_structure"]].reset_index(drop=True)


def compute(dry_run=False):
    return _annual.save(_compute(*_load_data()), "debt_structure_scores", "Debt structure (LT/total)", "debt_structure",
                        dry_run, fmt=".3f")


if __name__ == "__main__":
    _annual.cli(compute)
