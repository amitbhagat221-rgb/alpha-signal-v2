"""
Alpha Signal v2 — Net Working Capital to Revenue (latest annual)

Reads:  fundamentals_screener (annual rows), stocks
Writes: nwc_to_revenue_scores

  NWC = Receivables + Inventory − Trade Payables
  Ratio = NWC / Sales, latest annual period

Spot (not smoothed) sibling of `wc_intensity`. The 3y-median version captures
the steady-state cycle; this latest-year version catches recent shifts.
Higher = more cash tied up in operating cycle.

Usage:
    python -m signals.nwc_to_revenue
"""

import numpy as np
import pandas as pd

from signals import _annual

REQUIRED_ITEMS = ["Sales", "Receivables", "Inventory", "Trade Payables"]
MIN_SALES_CR = 50.0


def _load_data():
    return _annual.load(REQUIRED_ITEMS)


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "nwc_to_revenue"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Sales"] >= MIN_SALES_CR].copy()
    wide["nwc_to_revenue"] = (
        wide["Receivables"] + wide["Inventory"] - wide["Trade Payables"]
    ) / wide["Sales"]
    wide = wide.sort_values(["sid", "period_end"])
    latest = wide.groupby("sid", as_index=False).tail(1)
    return latest[["sid", "period_end", "nwc_to_revenue"]].reset_index(drop=True)


def compute(dry_run=False):
    return _annual.save(_compute(*_load_data()), "nwc_to_revenue_scores", "NWC/Revenue", "nwc_to_revenue",
                        dry_run, fmt=".3f")


if __name__ == "__main__":
    _annual.cli(compute)
