"""
Alpha Signal v2 — F&O implied-volatility factors — Plan 0002 §3.2.2 (IV half).

Four per-stock factors on top of the precomputed `fno_iv_history` surface (built
by sources/fno_iv.py via Black-76 inversion of fno_bhav settlement prices — no
external IV feed; validated against India VIX, see ADR 0035):

  iv_skew_25d        iv(25Δ put) − iv(25Δ call)         — downside-fear pricing  (stored)
  iv_term_structure  atm_iv(near) − atm_iv(next month)  — vol-curve slope        (stored, sparse*)
  iv_realised_spread atm_iv − 21d realised vol          — variance risk premium  (derived)
  iv_percentile_1y   rank of atm_iv in its trailing ≤1y — cheap/rich vol regime  (derived)

*iv_term_structure has thin single-stock coverage (~20%): Indian stock options
concentrate liquidity in the near month, so the next-month ATM IV is often not
recoverable. It's really an index-level signal — kept here for completeness, but
expect a small, liquidity-biased cross-section. Skew + the two atm_iv-derived
factors are near-fully covered.

The core takes injectable iv_hist / prices frames so the live path and the
backtest PIT path (tools/reconstruct_pit.py:pit_fno_iv) run identical logic on
different as-of data. Stock-only (fno_iv_history index rows carry sid=NULL).
Sign/strength is decided by the backtest; no direction is assumed here.

Reads:  fno_iv_history, stock_prices
Returns: DataFrame[sid, iv_skew_25d, iv_term_structure, iv_realised_spread, iv_percentile_1y]

Usage:
    python -m signals.fno_iv_factors            # compute live + print stats
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from db import read_sql

RV_WINDOW = 21            # trading days for realised vol (≈1 month, matches atm_iv ~30d)
PERCENTILE_LOOKBACK = 252  # ≤1y trailing window for iv_percentile_1y
MIN_PERCENTILE_OBS = 20    # need this many atm_iv obs before a percentile is meaningful
SKEW_CLIP = (-0.5, 0.5)    # vol points; bound rare blow-ups
TERM_CLIP = (-0.5, 0.5)
SPREAD_CLIP = (-1.0, 1.0)


def _realised_vol(closes: np.ndarray, window: int = RV_WINDOW):
    """Annualised close-to-close realised vol over the last `window` returns."""
    c = closes[~np.isnan(closes)]
    if len(c) < window + 1:
        return np.nan
    rets = np.diff(np.log(c[-(window + 1):]))
    if len(rets) < 2:
        return np.nan
    sd = np.std(rets, ddof=1)
    return float(sd * np.sqrt(252)) if sd > 0 else np.nan


def compute_iv_factors(
    iv_hist: pd.DataFrame | None = None,
    prices: pd.DataFrame | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """Core: per-stock IV factors as of the latest available trade_date.

    `iv_hist` (fno_iv_history) and `prices` (stock_prices) are injectable — the PIT
    path passes as-of-frozen frames. When None they're loaded live (bounded by
    as_of_date). Only stock underlyings (sid IS NOT NULL) are scored.

    Returns DataFrame[sid, iv_skew_25d, iv_term_structure, iv_realised_spread,
    iv_percentile_1y].
    """
    cols = ["sid", "iv_skew_25d", "iv_term_structure", "iv_realised_spread", "iv_percentile_1y"]
    if iv_hist is None:
        date_clause = f"AND trade_date <= '{as_of_date}'" if as_of_date else ""
        iv_hist = read_sql(
            "SELECT sid, trade_date, atm_iv, iv_skew_25d, iv_term_structure "
            f"FROM fno_iv_history WHERE sid IS NOT NULL {date_clause} "
            "ORDER BY sid, trade_date"
        )
    if iv_hist is None or iv_hist.empty:
        return pd.DataFrame(columns=cols)

    iv = iv_hist[iv_hist["sid"].notna()].copy().sort_values(["sid", "trade_date"])

    # Realised vol per sid from the close series (only need a short tail).
    if prices is None:
        date_clause = f"AND date <= '{as_of_date}'" if as_of_date else ""
        prices = read_sql(
            f"SELECT sid, date, close FROM stock_prices WHERE close > 0 {date_clause} "
            "ORDER BY sid, date"
        )
    rv_of = {}
    if prices is not None and not prices.empty:
        for sid, g in prices.sort_values(["sid", "date"]).groupby("sid", sort=False):
            rv_of[sid] = _realised_vol(g["close"].to_numpy())

    rows = []
    for sid, g in iv.groupby("sid", sort=False):
        now = g.iloc[-1]
        atm_now = now["atm_iv"]

        # iv_percentile_1y: rank of latest atm_iv within trailing ≤1y series.
        hist = g["atm_iv"].dropna().to_numpy()[-PERCENTILE_LOOKBACK:]
        if len(hist) >= MIN_PERCENTILE_OBS and pd.notna(atm_now):
            pct = float((hist <= atm_now).sum() / len(hist))
        else:
            pct = np.nan

        # iv_realised_spread: atm_iv − realised vol (variance risk premium).
        rv = rv_of.get(sid, np.nan)
        spread = float(atm_now - rv) if (pd.notna(atm_now) and pd.notna(rv)) else np.nan

        rows.append({
            "sid": sid,
            "iv_skew_25d": _clip(now["iv_skew_25d"], *SKEW_CLIP),
            "iv_term_structure": _clip(now["iv_term_structure"], *TERM_CLIP),
            "iv_realised_spread": _clip(spread, *SPREAD_CLIP),
            "iv_percentile_1y": round(pct, 4) if pd.notna(pct) else np.nan,
        })

    out = pd.DataFrame(rows)
    for c in ("iv_skew_25d", "iv_term_structure", "iv_realised_spread"):
        out[c] = out[c].round(4)
    return out[cols].reset_index(drop=True)


def _clip(v, lo, hi):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    return float(min(max(v, lo), hi))


if __name__ == "__main__":
    out = compute_iv_factors()
    print(f"Computed F&O IV factors for {len(out):,} stocks")
    if not out.empty:
        for c in ("iv_skew_25d", "iv_term_structure", "iv_realised_spread", "iv_percentile_1y"):
            s = out[c].dropna()
            if len(s):
                print(f"  {c:20s} n={len(s):4d}  mean={s.mean():+.4f}  "
                      f"min={s.min():+.4f}  max={s.max():+.4f}")
            else:
                print(f"  {c:20s} n=   0  (no data yet)")
