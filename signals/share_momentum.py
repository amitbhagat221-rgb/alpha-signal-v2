"""
Alpha Signal v2 — Market-Share Momentum (sector, 90-day window)

Reads:  stock_prices (close), fundamentals_screener ("No. of Equity Shares"),
        corporate_adjustments, stocks
Computed point in time only (pit.py); the live step that wrote its *_scores table had no reader and was removed (plan 0020, 2026-10).

  market_cap[t]      = close[t] × shares_outstanding[t]
  sector_total[t]    = sum(market_cap[t]) within sector
  share[t]           = market_cap[t] / sector_total[t]

  share_momentum     = share[t] / share[t-90 trading days] − 1

The headline factor in plan-0003. Stocks gaining share within their sector
tend to outperform; stocks losing share tend to lag. Independent of price
momentum (different denominator) and sector-relative by construction.

Shares outstanding is annual; we carry-forward the latest known share count
and apply corporate_adjustments for splits/bonuses between report and today.

Excludes financials (different reporting + share dynamics) and stocks below
₹200 cr market cap (numerical instability in tiny denominators).

"""

from config import SCREEN

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])
WINDOW_DAYS = 90
MIN_MARKET_CAP_CR = SCREEN["min_market_cap_cr"]


def sector_share_change(df):
    """df = [sid, sector, close_t, close_p, shares_outstanding] → adds market_cap_t,
    sector_share_t and share_momentum = sector_share_t / sector_share_p − 1, dropping
    rows whose past share is missing or zero (newly listed). Both market caps use the
    same latest share count. Shared with pit.py:pit_share_momentum."""
    df = df.copy()
    # Market cap in ₹cr (close in ₹, shares in lakhs/cr per Screener — but Screener
    # returns "No. of Equity Shares" already in cr units; multiply by close in ₹
    # then convert close-rupees × cr-shares = ₹cr directly, no further scaling).
    df["market_cap_t"] = df["close_t"] * df["shares_outstanding"]
    df["market_cap_p"] = df["close_p"] * df["shares_outstanding"]

    # Share within sector at each timestamp
    sector_total_t = df.groupby("sector")["market_cap_t"].sum().to_dict()
    sector_total_p = df.groupby("sector")["market_cap_p"].sum().to_dict()
    df["sector_share_t"] = df["market_cap_t"] / df["sector"].map(sector_total_t)
    df["sector_share_p"] = df["market_cap_p"] / df["sector"].map(sector_total_p)

    df = df[(df["sector_share_p"] > 0) & df["sector_share_p"].notna()].copy()
    df["share_momentum"] = df["sector_share_t"] / df["sector_share_p"] - 1
    return df
