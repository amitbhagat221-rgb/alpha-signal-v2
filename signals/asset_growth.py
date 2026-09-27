"""
Alpha Signal v2 — Asset Growth YoY (investment factor, CMA)

`asset_growth_yoy` — YoY % change in total assets between the two most recent
annual balance sheets. The canonical investment factor (Cooper-Gulen-Schill
2008; the CMA leg of Fama-French 2015): firms that aggressively expand their
balance sheet subsequently underperform — empire-building, over-investment,
and issuance all load on this one line. Audit 2026-07-04 Factor-F3 LARGE-tier
rebuild candidate #3.

Expected sign: NEGATIVE IC (high asset growth → low forward return). The
backtest decides — record the observed sign, don't force it.

Reads:  annual_balance_sheet (total_assets), stocks (sector)
Returns: DataFrame[sid, asset_growth_yoy]   — in PERCENT (mirrors
         revenue_growth_yoy's unit convention)

PIT convention: identical to book_to_price/piotroski — the PIT path
(pit.py:pit_asset_growth_yoy) passes the knowable_annual
slice (end_date + 75d SEBI filing lag ≤ eval), then the two most recent rows
per sid are the endpoints (same latest-vs-prior convention as
dso_change_yoy). No extra staleness gate — same as book_to_price.

Financial sectors excluded — for banks/NBFCs total-asset growth is lending
growth, a different economic object; they route through the financial
sub-model per CLAUDE.md. Prior-year total assets ≥ ₹50 cr (denominator floor,
the fundamentals-batch ₹50 cr shell-guard convention).

Usage:
    python -m signals.asset_growth      # live compute + print stats
"""

from __future__ import annotations

import pandas as pd

from config import SCREEN
from db import read_sql

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])

MIN_PRIOR_ASSETS_CR = 50.0     # denominator floor — drop shell-sized bases
GROWTH_CLIP = (-100.0, 1000.0)  # percent; mirrors revenue_growth_yoy bounds


def compute_asset_growth_yoy(
    bs: pd.DataFrame | None = None,
    stocks: pd.DataFrame | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """YoY % change in total assets per sid, from the two latest annual rows.

    `bs` is injectable for PIT — a frame with [sid, end_date, total_assets],
    ALREADY sliced to what was knowable (the PIT caller applies the 75d annual
    filing lag via knowable_annual, exactly as for book_to_price/piotroski).
    The live path reads annual_balance_sheet directly (optionally ≤ as_of on
    end_date). Non-financial universe only; NULL when <2 usable annual rows.
    """
    cols = ["sid", "asset_growth_yoy"]
    if stocks is None:
        stocks = read_sql("SELECT sid, sector FROM stocks")
    if bs is None:
        dc = f"AND end_date <= '{as_of_date}'" if as_of_date else ""
        bs = read_sql(
            f"SELECT sid, end_date, total_assets FROM annual_balance_sheet "
            f"WHERE end_date IS NOT NULL {dc} ORDER BY sid, end_date"
        )
    if bs is None or len(bs) == 0:
        return pd.DataFrame(columns=cols)

    universe = set(stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)]["sid"])
    b = bs[["sid", "end_date", "total_assets"]].dropna(subset=["total_assets"])
    b = b[(b["total_assets"] > 0) & (b["sid"].isin(universe))]
    b = b.sort_values(["sid", "end_date"])

    rows = []
    for sid, g in b.groupby("sid"):
        if len(g) < 2:
            continue
        latest, prior = g.iloc[-1], g.iloc[-2]
        if prior["total_assets"] < MIN_PRIOR_ASSETS_CR:
            continue
        growth = (latest["total_assets"] / prior["total_assets"] - 1.0) * 100.0
        growth = min(max(growth, GROWTH_CLIP[0]), GROWTH_CLIP[1])
        rows.append({"sid": sid, "asset_growth_yoy": round(float(growth), 3)})
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


if __name__ == "__main__":
    res = compute_asset_growth_yoy()
    s = res["asset_growth_yoy"].dropna()
    print(f"asset_growth_yoy — {len(s):,} non-financial stocks scored (2 annual BS rows, "
          f"prior-year assets ≥ ₹{MIN_PRIOR_ASSETS_CR:.0f} cr)")
    if len(s):
        print(f"  YoY asset growth %: median={s.median():+.1f}  "
              f"p25={s.quantile(0.25):+.1f}  p75={s.quantile(0.75):+.1f}")
