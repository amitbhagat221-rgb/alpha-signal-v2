"""
Alpha Signal v2 — F&O Open-Interest factors — Plan 0002 §3.2.2 (OI half).

Four per-stock factors read off the pre-computed nearest-expiry options rollup
in `fno_pcr_history` (one row per underlying per trade_date, see ADR 0034):

  pcr_oi             put_oi / call_oi          — positioning skew (level)
  pcr_volume         put_vol / call_vol        — same-day flow skew (level)
  max_pain_distance  (spot − max_pain) / spot  — pull toward the writer-pain strike
  oi_buildup_signal  4-state regime score      — fresh longs vs shorts (derived)

The first three are stored columns — the factor is just "latest row ≤ as-of".
oi_buildup_signal is derived from the day-over-day change in total OI and the
underlying price, classified into the textbook four quadrants:

  price ↑ & OI ↑  → long buildup     → +1.0  (fresh longs, most bullish)
  price ↑ & OI ↓  → short covering   → +0.5  (shorts closing, mildly bullish)
  price ↓ & OI ↓  → long unwinding   → −0.5  (longs closing, mildly bearish)
  price ↓ & OI ↑  → short buildup    → −1.0  (fresh shorts, most bearish)

The buildup delta is taken ONLY against a prior row sharing the SAME expiry_date
— around the monthly expiry roll the "nearest expiry" jumps to the next series
and total OI drops discontinuously, so a naive 1-day Δ would be pure roll noise.
If no same-expiry prior row exists (e.g. the trading day right after a roll), the
buildup is NaN for that stock that day rather than a phantom signal.

Stock-only by construction: index underlyings (NIFTY/BANKNIFTY/…) carry sid=NULL
in fno_pcr_history (symbol-keyed), so the `sid IS NOT NULL` filter drops them.

The core takes an injectable `pcr_hist` frame so the live path and the backtest
PIT path (tools/reconstruct_pit.py:pit_fno_oi) run identical logic on different
as-of data — never a second copy. Sign/strength is decided by the backtest; no
direction is assumed here.

Reads:  fno_pcr_history
Returns: DataFrame[sid, pcr_oi, pcr_volume, max_pain_distance, oi_buildup_signal]

Usage:
    python -m signals.fno_oi_factors            # compute live + print stats
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from db import read_sql

# Clip bounds mirror tools/reconstruct_pit.py VALIDATION_RANGES so the live and
# PIT paths produce identically-bounded values.
PCR_CLIP = (0.0, 20.0)          # raw PCR can spike on thin call OI; cap the tail
MAXPAIN_CLIP = (-1.0, 1.0)      # fraction of spot
# Same-expiry prior row must be within this many calendar days, else the gap is
# treated as a roll/data hole and oi_buildup → NaN.
BUILDUP_MAX_GAP_DAYS = 10


def _buildup_score(d_price: float, d_oi: float) -> float:
    """Four-quadrant OI-buildup regime score (see module docstring)."""
    if d_price > 0:
        return 1.0 if d_oi > 0 else 0.5
    if d_price < 0:
        return -1.0 if d_oi > 0 else -0.5
    return 0.0  # flat price → no directional buildup reading


def compute_oi_factors(
    pcr_hist: pd.DataFrame | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """Core: per-stock F&O OI factors as of the latest available trade_date.

    `pcr_hist` is injectable (PIT path passes an as-of-frozen frame). When None
    it's loaded live, optionally bounded by `as_of_date`. Only stock underlyings
    (sid IS NOT NULL) are scored.

    Returns DataFrame[sid, pcr_oi, pcr_volume, max_pain_distance, oi_buildup_signal].
    """
    if pcr_hist is None:
        date_clause = f"AND trade_date <= '{as_of_date}'" if as_of_date else ""
        pcr_hist = read_sql(
            "SELECT sid, trade_date, expiry_date, underlying_price, "
            "total_call_oi, total_put_oi, pcr_oi, pcr_volume, max_pain_distance "
            f"FROM fno_pcr_history WHERE sid IS NOT NULL {date_clause} "
            "ORDER BY sid, trade_date"
        )

    if pcr_hist is None or pcr_hist.empty:
        return pd.DataFrame(
            columns=["sid", "pcr_oi", "pcr_volume", "max_pain_distance", "oi_buildup_signal"]
        )

    df = pcr_hist[pcr_hist["sid"].notna()].copy()
    df = df.sort_values(["sid", "trade_date"])
    df["_total_oi"] = df["total_call_oi"].fillna(0) + df["total_put_oi"].fillna(0)
    df["_td"] = pd.to_datetime(df["trade_date"])

    rows = []
    for sid, g in df.groupby("sid", sort=False):
        now = g.iloc[-1]
        rec = {
            "sid": sid,
            "pcr_oi": _clip(now["pcr_oi"], *PCR_CLIP),
            "pcr_volume": _clip(now["pcr_volume"], *PCR_CLIP),
            "max_pain_distance": _clip(now["max_pain_distance"], *MAXPAIN_CLIP),
            "oi_buildup_signal": np.nan,
        }

        # Most recent prior row sharing the current nearest expiry (roll-safe).
        same_exp = g.iloc[:-1]
        same_exp = same_exp[same_exp["expiry_date"] == now["expiry_date"]]
        if not same_exp.empty:
            prev = same_exp.iloc[-1]
            gap = (now["_td"] - prev["_td"]).days
            if (
                0 < gap <= BUILDUP_MAX_GAP_DAYS
                and pd.notna(now["underlying_price"])
                and pd.notna(prev["underlying_price"])
            ):
                d_price = now["underlying_price"] - prev["underlying_price"]
                d_oi = now["_total_oi"] - prev["_total_oi"]
                rec["oi_buildup_signal"] = _buildup_score(d_price, d_oi)

        rows.append(rec)

    out = pd.DataFrame(rows)
    for c in ("pcr_oi", "pcr_volume", "max_pain_distance"):
        out[c] = out[c].round(4)
    return out.reset_index(drop=True)


def _clip(v, lo, hi):
    """Round-trip a possibly-None value through clip bounds, preserving NaN."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    return float(min(max(v, lo), hi))


if __name__ == "__main__":
    out = compute_oi_factors()
    print(f"Computed F&O OI factors for {len(out):,} stocks")
    if not out.empty:
        for c in ("pcr_oi", "pcr_volume", "max_pain_distance", "oi_buildup_signal"):
            s = out[c].dropna()
            print(f"  {c:20s} n={len(s):4d}  "
                  f"mean={s.mean():+.3f}  min={s.min():+.3f}  max={s.max():+.3f}")
