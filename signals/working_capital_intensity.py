"""
Alpha Signal v2 — Working Capital Intensity

Reads:  fundamentals_screener (annual rows), stocks
Writes: working_capital_intensity_scores

  WCI = (Receivables + Inventory − Trade Payables) / Sales
  Reported as the 3-year median per stock.

Sibling of cash_conversion_cycle but expressed as a fraction of revenue
rather than in days. Lower (and especially negative) values mean less
capital is tied up per ₹ of sales — a structural quality marker.

Financial Services excluded.

Usage:
    python -m signals.working_capital_intensity
    python -m signals.working_capital_intensity --dry-run
"""

import numpy as np
import pandas as pd

from signals import _annual

REQUIRED_ITEMS = ["Sales", "Receivables", "Inventory", "Trade Payables"]
SMOOTH_YEARS = 3
MIN_SALES_CR = 50.0


def _load_data():
    return _annual.load(REQUIRED_ITEMS)


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "wc_intensity"])

    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Sales"] >= MIN_SALES_CR].copy()

    wide["wci_yr"] = (
        wide["Receivables"] + wide["Inventory"] - wide["Trade Payables"]
    ) / wide["Sales"]

    wide = wide.sort_values(["sid", "period_end"])
    last_n = wide.groupby("sid", as_index=False).tail(SMOOTH_YEARS)
    agg = last_n.groupby("sid", as_index=False).agg(
        period_end=("period_end", "max"),
        wc_intensity=("wci_yr", "median"),
        years_used=("wci_yr", "count"),
    )
    agg = agg[agg["years_used"] >= SMOOTH_YEARS]
    return agg[["sid", "period_end", "wc_intensity"]].reset_index(drop=True)


def compute(dry_run=False):
    return _annual.save(_compute(*_load_data()), "working_capital_intensity_scores", "WC intensity", "wc_intensity",
                        dry_run, fmt=".3f")


if __name__ == "__main__":
    _annual.cli(compute)
