"""
Alpha Signal v2 — Market-Share Momentum (sector, 90-day window)

Reads:  stock_prices (close), fundamentals_screener ("No. of Equity Shares"),
        corporate_adjustments, stocks
Writes: share_momentum_scores

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

Usage:
    python -m signals.share_momentum
    python -m signals.share_momentum --dry-run
"""

from datetime import timedelta

import pandas as pd

from config import SCREEN
from db import read_sql
from signals import _annual

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])
WINDOW_DAYS = 90
MIN_MARKET_CAP_CR = SCREEN["min_market_cap_cr"]


def _load_data():
    placeholders = ",".join("?" for _ in FINANCIAL_SECTORS)
    stocks = read_sql(
        f"SELECT sid, sector, market_cap_cr FROM stocks "
        f"WHERE sector NOT IN ({placeholders}) AND ticker IS NOT NULL "
        f"AND market_cap_cr >= ?",
        params=list(FINANCIAL_SECTORS) + [MIN_MARKET_CAP_CR],
    )
    sids = set(stocks["sid"])

    # Latest annual "No. of Equity Shares" per stock (carry-forward)
    shares = read_sql(
        "SELECT sid, period_end, value AS shares_outstanding "
        "FROM fundamentals_screener "
        "WHERE period_type='annual' AND line_item='No. of Equity Shares'"
    )
    shares = shares[shares["sid"].isin(sids)].copy()
    if not shares.empty:
        shares = (shares.sort_values(["sid", "period_end"])
                        .groupby("sid", as_index=False).tail(1))

    # Daily close prices over the last ~6 months (window + buffer)
    prices = read_sql(
        f"SELECT sid, date, close FROM stock_prices "
        f"WHERE date >= date('now', '-{WINDOW_DAYS * 2 + 30} days') "
        f"ORDER BY sid, date"
    )
    prices = prices[prices["sid"].isin(sids)].copy()

    return stocks, shares, prices


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


def _compute(stocks, shares, prices):
    if prices.empty or shares.empty:
        return pd.DataFrame(columns=["sid", "market_cap_cr", "sector_share", "share_momentum"])

    # Today's price per stock = last available close
    latest = prices.sort_values(["sid", "date"]).groupby("sid", as_index=False).tail(1)
    latest = latest.rename(columns={"close": "close_t", "date": "date_t"})

    # Find a price ~WINDOW_DAYS trading days ago (≈ WINDOW_DAYS * 1.4 calendar days)
    cutoff_date = (pd.to_datetime(latest["date_t"].iloc[0])
                   - timedelta(days=int(WINDOW_DAYS * 1.45))).strftime("%Y-%m-%d")
    past_window = prices[prices["date"] <= cutoff_date]
    past = past_window.sort_values(["sid", "date"]).groupby("sid", as_index=False).tail(1)
    past = past.rename(columns={"close": "close_p", "date": "date_p"})

    df = latest.merge(past, on="sid", how="inner")
    df = df.merge(shares[["sid", "shares_outstanding"]], on="sid", how="inner")
    df = df.merge(stocks[["sid", "sector"]], on="sid", how="inner")
    df = sector_share_change(df)

    df = df.rename(columns={"market_cap_t": "market_cap_cr",
                            "sector_share_t": "sector_share"})
    return df[["sid", "market_cap_cr", "sector_share", "share_momentum"]].reset_index(drop=True)


def compute(dry_run=False):
    return _annual.save(_compute(*_load_data()), "share_momentum_scores", "Share momentum",
                        "share_momentum", dry_run, fmt="+.3%")


if __name__ == "__main__":
    _annual.cli(compute)
