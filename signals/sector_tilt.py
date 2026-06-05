"""
Alpha Signal v2 — Sector Tilt (validated daily sector-momentum + macro ensemble).

The per-stock factor that tilts the screener toward tailwind sectors. Validated
2026-06-04 (tools/sector_tilt_validation.py) as ADDITIVE to the stock momentum
already in the model — Fama-MacBeth slope +0.84%/σ, t+3.34 controlling for stock
momentum; double-sort orthogonal across all stock-momentum terciles. ADR 0041.

The signal, per GICS sector:

    sector_tilt(sector) = mean( z(trailing-6m basket momentum), z(macro_score) )

  • trailing-6m basket momentum = MEDIAN over the sector's constituents of each
    stock's trailing ≈6-month (126 trading-day) simple return. Median, not
    cap-weighted, so a few mega-caps don't define the sector basket (matches the
    validated construction).
  • macro_score = the latest per-sector macro_score from macro_sector_signals_pit
    (the orthogonal macro engine; corr +0.08 with sector momentum, ensemble t+3.0).
  • both z-scored ACROSS the ~11 sectors, then averaged (mean of whichever terms
    are available); the per-sector value is mapped onto every stock via stocks.sector.

Distinct from signals/sector_momentum.py (63d cap-weighted relative-strength vs
NIFTY 50) — that cousin backtested WEAK/DROP within-tier and sits in FACTOR_LIBRARY.
This is the richer 6m-absolute + macro ensemble that the validation cleared.

The core takes injectable price / macro / stocks frames so the live path and the
PIT path (tools/reconstruct_pit.py:pit_sector_tilt) run identical logic on different
as-of data — never a second copy.

Reads:  stock_prices, stocks, macro_sector_signals_pit (macro_score)

Usage:
    python -m signals.sector_tilt            # print per-sector ensemble + sample
    python -m signals.sector_tilt --date YYYY-MM-DD   # as-of a historical date
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from db import read_sql

# Trailing-momentum window in trading days (≈6 months — the validated lookback).
MOM_WINDOW = 126
# A sector needs at least this many constituents with a valid window return
# before we trust its basket median (matches MIN_STOCKS_PER_SECTOR in the
# validation tool). Every GICS sector clears this comfortably (min ≈33 stocks).
MIN_CONSTITUENTS = 5
# Per-constituent return winsorization before the median — bounds a single
# split/anomaly (stock_prices.close is raw/unadjusted). Same defense as the
# cousin's RET_CLIP; the median already resists outliers, this is belt-and-braces.
RET_CLIP = (-0.6, 3.0)
# Final z-ensemble clip — keeps the factor in VALIDATION_RANGES (-3, 3) and
# matches sector_momentum's per-stock clip.
Z_CLIP = 3.0


def _window_return(values: np.ndarray, w: int):
    """Position-based simple return over the last `w` rows of a close series.

    Mirrors signals/momentum.py and signals/sector_momentum.py: index from the
    end so missing trading days shorten the effective lookback rather than
    misaligning dates. None if too little history or a non-positive base price."""
    if values is None or len(values) < w + 1:
        return None
    p_now = values[-1]
    p_then = values[-w - 1]
    if p_then is None or p_then <= 0 or p_now is None or p_now <= 0:
        return None
    return float(p_now / p_then - 1.0)


def _z(s: pd.Series) -> pd.Series:
    """Cross-sectional z-score (population std, ddof=0). Flat → zeros."""
    s = s.astype(float)
    sd = s.std(ddof=0)
    return (s - s.mean()) / sd if sd else s * 0.0


def _basket_momentum(prices: pd.DataFrame, sector_of: dict) -> pd.Series:
    """Per-sector trailing-6m basket momentum = median constituent window return.

    Returns Series indexed by sector (sectors with <MIN_CONSTITUENTS valid
    returns are dropped)."""
    rets: dict[str, list] = {}
    for sid, g in prices.groupby("sid", sort=False):
        sector = sector_of.get(sid)
        if sector is None:
            continue
        r = _window_return(g["close"].to_numpy(), MOM_WINDOW)
        if r is not None:
            rets.setdefault(sector, []).append(float(np.clip(r, *RET_CLIP)))
    out = {sec: float(np.median(rl)) for sec, rl in rets.items()
           if len(rl) >= MIN_CONSTITUENTS}
    return pd.Series(out, dtype=float)


def compute_sector_tilt(
    prices: pd.DataFrame | None = None,
    macro_sector: pd.DataFrame | None = None,
    stocks: pd.DataFrame | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """Core: per-stock sector-tilt factor (the validated ensemble).

    Inputs are injectable so the PIT helper can pass as-of-frozen frames; when
    omitted they're loaded live (optionally bounded by as_of_date).

      prices       — [sid, date, close], ordered by sid,date (raw close OK).
      macro_sector — [sector, macro_score], latest per sector (as-of for PIT).
      stocks       — [sid, sector].

    Returns DataFrame[sid, sector_tilt].
    """
    date_clause = f"AND date <= '{as_of_date}'" if as_of_date else ""

    if prices is None:
        prices = read_sql(
            f"SELECT sid, date, close FROM stock_prices "
            f"WHERE close > 0 {date_clause} ORDER BY sid, date"
        )
    if stocks is None:
        stocks = read_sql("SELECT sid, sector FROM stocks WHERE sector IS NOT NULL")
    if macro_sector is None:
        # Latest macro_score per sector (≤ as_of_date when given — keeps live and
        # PIT identical; the PIT helper passes a pre-sliced frame instead).
        snap_clause = f"WHERE snapshot_date <= '{as_of_date}'" if as_of_date else ""
        macro_sector = read_sql(
            "SELECT sector, macro_score FROM macro_sector_signals_pit "
            "WHERE (sector, snapshot_date) IN ("
            "  SELECT sector, MAX(snapshot_date) FROM macro_sector_signals_pit "
            f"  {snap_clause} GROUP BY sector"
            ") AND macro_score IS NOT NULL"
        )

    empty = pd.DataFrame(columns=["sid", "sector_tilt"])
    if prices is None or prices.empty or stocks is None or stocks.empty:
        return empty

    sector_of = dict(zip(stocks["sid"], stocks["sector"]))

    # Term 1 — trailing-6m basket momentum, z-scored across sectors.
    mom = _basket_momentum(prices, sector_of)
    if mom.empty:
        return empty
    parts = [_z(mom.dropna())]

    # Term 2 — macro_score, z-scored across sectors (appended if available).
    if macro_sector is not None and not macro_sector.empty:
        mac = (macro_sector.dropna(subset=["macro_score"])
               .set_index("sector")["macro_score"].astype(float))
        if not mac.empty:
            parts.append(_z(mac))

    # Ensemble = per-sector mean of the available z-terms (skips NaN, matching the
    # validation's concat(...).mean(axis=1)). Then clip to ±3 for the range gate.
    sig_by_sector = pd.concat(parts, axis=1).mean(axis=1, skipna=True)
    sig_by_sector = sig_by_sector.clip(-Z_CLIP, Z_CLIP)

    out = stocks.copy()
    out["sector_tilt"] = out["sector"].map(sig_by_sector)
    out = out.dropna(subset=["sector_tilt"])[["sid", "sector_tilt"]]
    out["sector_tilt"] = out["sector_tilt"].round(4)
    return out.reset_index(drop=True)


def _per_sector_view(as_of_date: str | None = None) -> pd.Series:
    """Diagnostic: the per-sector ensemble value (before mapping to stocks)."""
    date_clause = f"AND date <= '{as_of_date}'" if as_of_date else ""
    prices = read_sql(
        f"SELECT sid, date, close FROM stock_prices WHERE close > 0 {date_clause} "
        f"ORDER BY sid, date"
    )
    stocks = read_sql("SELECT sid, sector FROM stocks WHERE sector IS NOT NULL")
    sector_of = dict(zip(stocks["sid"], stocks["sector"]))
    mom = _basket_momentum(prices, sector_of)
    parts = [_z(mom.dropna()).rename("z_mom6")]
    snap_clause = f"WHERE snapshot_date <= '{as_of_date}'" if as_of_date else ""
    mac = read_sql(
        "SELECT sector, macro_score FROM macro_sector_signals_pit "
        "WHERE (sector, snapshot_date) IN ("
        "  SELECT sector, MAX(snapshot_date) FROM macro_sector_signals_pit "
        f"  {snap_clause} GROUP BY sector) AND macro_score IS NOT NULL"
    )
    if not mac.empty:
        mser = mac.set_index("sector")["macro_score"].astype(float)
        parts.append(_z(mser).rename("z_macro"))
    view = pd.concat(parts, axis=1)
    view["sector_tilt"] = view.mean(axis=1, skipna=True).clip(-Z_CLIP, Z_CLIP)
    return view.sort_values("sector_tilt", ascending=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="as-of date YYYY-MM-DD (default: live latest)")
    args = parser.parse_args()
    view = _per_sector_view(as_of_date=args.date)
    print("Per-sector ensemble (z_mom6 + z_macro → sector_tilt):")
    print(view.round(3).to_string())
    df = compute_sector_tilt(as_of_date=args.date)
    print(f"\nMapped to {len(df)} stocks. Sample:")
    print(df.head(8).to_string(index=False))
