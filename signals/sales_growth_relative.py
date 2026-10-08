"""
Alpha Signal v2 — Sector-Relative Sales Growth

Reads:  fundamentals_screener (annual Sales), stocks
Computed point in time only (pit.py); the live step that wrote its *_scores table had no reader and was removed (plan 0020, 2026-10).

  sales_growth_yoy[t]   = sales[t] / sales[t-1] − 1                (3-yr median)
  sector_median_growth  = median(sales_growth_yoy) within sector
  relative_growth       = sales_growth_yoy − sector_median_growth

Stocks growing FASTER than their sector are taking share or expanding the
addressable market — both alpha. Stocks growing SLOWER are losing the
structural battle even if absolute growth looks fine.

Existing `revenue_growth_yoy` factor is absolute. A 15% Pharma stock looks
fast in isolation but is *underperforming* the 22% sector. This factor fixes
the comparison.

Smoothing: 3-yr median per the Track 3 convention.

"""

import pandas as pd


SMOOTH_YEARS = 3


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "sales_growth", "sector_median", "relative_growth"])

    fund = fund.sort_values(["sid", "period_end"])
    fund["prev_sales"] = fund.groupby("sid")["value"].shift(1)
    fund = fund.dropna(subset=["prev_sales"])
    fund = fund[fund["prev_sales"] > 0]
    fund["growth_yr"] = fund["value"] / fund["prev_sales"] - 1

    # 3-year median growth per stock
    last_n = fund.groupby("sid", as_index=False).tail(SMOOTH_YEARS)
    agg = last_n.groupby("sid", as_index=False).agg(
        period_end=("period_end", "max"),
        sales_growth=("growth_yr", "median"),
        years_used=("growth_yr", "count"),
    )
    agg = agg[agg["years_used"] >= SMOOTH_YEARS]

    # Sector medians
    agg = agg.merge(stocks[["sid", "sector"]], on="sid", how="left")
    sector_median = agg.groupby("sector")["sales_growth"].median().to_dict()
    agg["sector_median"] = agg["sector"].map(sector_median)
    agg["relative_growth"] = agg["sales_growth"] - agg["sector_median"]

    return agg[["sid", "period_end", "sales_growth", "sector_median", "relative_growth"]].reset_index(drop=True)
