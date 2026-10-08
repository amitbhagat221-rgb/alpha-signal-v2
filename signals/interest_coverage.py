"""
Alpha Signal v2 — Interest Coverage

Reads:  fundamentals_screener (annual rows), stocks
Computed point in time only (pit.py); the live step that wrote its *_scores table had no reader and was removed (plan 0020, 2026-10).

  EBIT_t            = PBT_t + Interest_t
  coverage_t        = EBIT_t / Interest_t
  interest_coverage = 3-year median

Higher = safer balance sheet. Stocks with near-zero Interest (debt-free
or near debt-free) are excluded — coverage is mathematically huge but
not informative, and they'd dominate the rank.

Loss years (negative EBIT) yield negative coverage and are kept — they
correctly signal distress.

Financial Services excluded — Interest is the COGS of banking, not a
financing cost.

"""

import numpy as np
import pandas as pd


REQUIRED_ITEMS = ["Profit before tax", "Interest"]
SMOOTH_YEARS = 3
# Floor on annual interest expense. Below ~₹1 cr the ratio explodes and
# stops carrying real information (RIL-style essentially-debt-free names).
MIN_INTEREST_CR = 1.0
# Cap absurd coverages from creeping past the floor (e.g. 0.001 cr interest
# on a ₹10K cr EBIT business). Real-world bands: <1 distressed, 1-3 weak,
# 3-10 normal, 10-30 strong, >30 exceptional.
COVERAGE_CAP = 200.0


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "interest_coverage"])

    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Interest"] >= MIN_INTEREST_CR].copy()

    wide["ebit"] = wide["Profit before tax"] + wide["Interest"]
    wide["cov_yr"] = (wide["ebit"] / wide["Interest"]).clip(-COVERAGE_CAP, COVERAGE_CAP)

    wide = wide.sort_values(["sid", "period_end"])
    last_n = wide.groupby("sid", as_index=False).tail(SMOOTH_YEARS)
    agg = last_n.groupby("sid", as_index=False).agg(
        period_end=("period_end", "max"),
        interest_coverage=("cov_yr", "median"),
        years_used=("cov_yr", "count"),
    )
    agg = agg[agg["years_used"] >= SMOOTH_YEARS]
    return agg[["sid", "period_end", "interest_coverage"]].reset_index(drop=True)
