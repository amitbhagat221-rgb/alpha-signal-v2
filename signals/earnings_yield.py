"""
Alpha Signal v2 — Earnings Yield Signal

  earnings_yield = TTM EPS / current_price
                 = sum(last 4 quarters EPS) / latest close

Handles negative EPS correctly (ranks them as poor value, unlike P/E).

Reads: quarterly_income, stock_prices
Returns: DataFrame with sid, earnings_yield

No separate DB table — stored in daily_snapshots during scoring phase.

"""


import numpy as np
import pandas as pd



def ttm_eps(qi):
    """{sid: sum of the last 4 quarters' EPS}, consolidated preferred per sid;
    sids with <4 quarters are absent. `qi` = [sid, end_date, reporting, eps]."""
    from signals._fundamentals import prefer_consolidated, ttm
    out = {sid: ttm(g, "eps") for sid, g in prefer_consolidated(qi).groupby("sid")}
    return {sid: v for sid, v in out.items() if v is not None}


def earnings_yield(qi, close):
    """E/P = TTM EPS / close. `close` = [sid, close_price]; NaN where the close is
    missing or ≤ 0. Returns DataFrame[sid, earnings_yield] for sids with a TTM EPS.
    Shared by the live screener and pit.py:pit_earnings_yield."""
    eps = ttm_eps(qi)
    if not eps:
        return pd.DataFrame(columns=["sid", "earnings_yield"])
    merged = pd.DataFrame({"sid": list(eps), "ttm_eps": list(eps.values())}).merge(
        close, on="sid", how="left")
    merged["earnings_yield"] = np.where(
        (merged["close_price"].notna()) & (merged["close_price"] > 0),
        (merged["ttm_eps"] / merged["close_price"]).round(6),
        np.nan,
    )
    return merged[["sid", "earnings_yield"]]
