"""
Alpha Signal v2 — Daily-derivable microstructure factors — Plan 0002 §3.2.3.

Six of the nine §3.2.3 microstructure factors are computable from the daily OHLCV
we already store in stock_prices — no Kite intraday feed needed (only the other 3:
volume_clock_concentration, tick_imbalance_5d, intraday_momentum_persistence
genuinely require minute/tick data → gated on 3.1c Kite, ON HOLD).

  intraday_range_compression  ATR(5) / ATR(20)                     — vol regime (clean)
  closing_strength_1m         mean (close−low)/(high−low), 21d      — where-in-range close (clean)
  opening_gap_freq_1m         frac of 21d with |open/prevclose−1|>1% — gappiness (clean)
  vwap_deviation_5d           (close − typical_price)/TP, 5d mean   — intraday-strength PROXY*
  bidask_spread_proxy         Corwin-Schultz spread from H/L, 20d   — illiquidity PROXY
  kyle_lambda                 Amihud: mean |ret| / turnover, 21d    — price-impact PROXY

*True VWAP needs intraday volume-weighting; stock_prices.traded_value is ~17% NULL
(all recent), so we use the OHLC typical price (H+L+C)/3 as the daily VWAP proxy
(100% coverage). Likewise prev_close is self-computed as lag(close), and Amihud's
turnover uses close×volume (traded_value is the same ₹ figure where present, but NULL
recently). Raw (unadjusted) prices + winsorisation — same split-defense stance as
signals/sector_momentum.py (cross-day legs see rare split noise, bounded by clips).

Injectable `prices` frame so the live path and the PIT path
(tools/reconstruct_pit.py:pit_microstructure) run identical logic. Sign decided
by the backtest. Unlike the F&O factors these have years of price history → they
backtest on the full ~149-date v2 panel (monthly cadence).

Reads:  stock_prices (open, high, low, close, volume)
Returns: DataFrame[sid, <6 factors>]

Usage:
    python -m signals.microstructure            # compute live + print stats
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from db import read_sql

LOOKBACK_DAYS = 35        # tail slice loaded per stock (covers the 21d windows + ATR20)
MIN_HISTORY = 22
ATR_SHORT, ATR_LONG = 5, 20
WIN_1M = 21
VWAP_WIN = 5
CS_WIN = 20               # Corwin-Schultz day-pairs
GAP_THRESHOLD = 0.01      # >1% overnight gap
_K_CS = 3 - 2 * np.sqrt(2)

# Bounds mirror tools/reconstruct_pit.py VALIDATION_RANGES.
CLIPS = {
    "intraday_range_compression": (0.0, 5.0),
    "closing_strength_1m":        (0.0, 1.0),
    "opening_gap_freq_1m":        (0.0, 1.0),
    "vwap_deviation_5d":          (-0.5, 0.5),
    "bidask_spread_proxy":        (0.0, 1.0),
    "kyle_lambda":                (0.0, 1.0),
}


def _atr(high, low, close_prev):
    """True range per day (needs prev close); returns array of TR."""
    hl = high - low
    hc = np.abs(high - close_prev)
    lc = np.abs(low - close_prev)
    return np.maximum.reduce([hl, hc, lc])


def _corwin_schultz(high, low):
    """Mean Corwin-Schultz 2-day spread estimate over the available pairs.

    Negative single-pair estimates are floored to 0 (CS convention). Returns a
    fraction (0.002 = 20 bps) or NaN if <2 days."""
    if len(high) < 2:
        return np.nan
    spreads = []
    for i in range(len(high) - 1):
        h1, l1, h2, l2 = high[i], low[i], high[i + 1], low[i + 1]
        if min(l1, l2) <= 0 or h1 <= 0 or h2 <= 0:
            continue
        beta = np.log(h1 / l1) ** 2 + np.log(h2 / l2) ** 2
        gamma = np.log(max(h1, h2) / min(l1, l2)) ** 2
        alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / _K_CS - np.sqrt(gamma / _K_CS)
        s = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
        spreads.append(max(s, 0.0))
    return float(np.mean(spreads)) if spreads else np.nan


def _one_stock(g: pd.DataFrame) -> dict | None:
    """Compute the 6 factors for one stock's recent daily OHLCV (sorted by date)."""
    g = g.tail(LOOKBACK_DAYS)
    if len(g) < MIN_HISTORY:
        return None
    o = g["open"].to_numpy(float)
    h = g["high"].to_numpy(float)
    l = g["low"].to_numpy(float)
    c = g["close"].to_numpy(float)
    v = g["volume"].to_numpy(float)
    cp = np.concatenate([[c[0]], c[:-1]])  # prev_close = lag(close), first row self

    rng = h - l
    valid_rng = rng > 0

    # intraday_range_compression = ATR(5)/ATR(20)
    tr = _atr(h, l, cp)
    atr_s = tr[-ATR_SHORT:].mean() if len(tr) >= ATR_SHORT else np.nan
    atr_l = tr[-ATR_LONG:].mean() if len(tr) >= ATR_LONG else np.nan
    range_comp = (atr_s / atr_l) if (atr_l and atr_l > 0) else np.nan

    # closing_strength_1m = mean (close-low)/(high-low) over last 21d (skip 0-range)
    cs_idx = np.where(valid_rng)[0][-WIN_1M:]
    closing_strength = float(((c[cs_idx] - l[cs_idx]) / rng[cs_idx]).mean()) if len(cs_idx) else np.nan

    # opening_gap_freq_1m = frac of last 21d with |open/prevclose - 1| > 1%
    w = slice(-WIN_1M, None)
    cpw = cp[w]
    gaps = np.abs(o[w] / np.where(cpw > 0, cpw, np.nan) - 1.0)
    opening_gap_freq = float(np.nanmean(gaps > GAP_THRESHOLD)) if np.isfinite(gaps).any() else np.nan

    # vwap_deviation_5d = mean (close - typical_price)/TP over 5d, TP=(H+L+C)/3
    tp = (h + l + c) / 3.0
    tpw, cw = tp[-VWAP_WIN:], c[-VWAP_WIN:]
    vwap_dev = float(np.mean((cw - tpw) / np.where(tpw > 0, tpw, np.nan))) if (tpw > 0).all() else np.nan

    # bidask_spread_proxy = Corwin-Schultz over last ~20 day-pairs
    spread = _corwin_schultz(h[-(CS_WIN + 1):], l[-(CS_WIN + 1):])

    # kyle_lambda = Amihud illiquidity: mean |ret| / turnover_cr over 21d
    ret = c[1:] / np.where(c[:-1] > 0, c[:-1], np.nan) - 1.0
    turnover_cr = (c[1:] * v[1:]) / 1e7  # ₹ crore
    amihud_terms = np.abs(ret) / np.where(turnover_cr > 0, turnover_cr, np.nan)
    kyle = float(np.nanmean(amihud_terms[-WIN_1M:])) if np.isfinite(amihud_terms[-WIN_1M:]).any() else np.nan

    out = {
        "intraday_range_compression": range_comp,
        "closing_strength_1m": closing_strength,
        "opening_gap_freq_1m": opening_gap_freq,
        "vwap_deviation_5d": vwap_dev,
        "bidask_spread_proxy": spread,
        "kyle_lambda": kyle,
    }
    return {k: _clip(x, *CLIPS[k]) for k, x in out.items()}


def _clip(v, lo, hi):
    if v is None or not np.isfinite(v):
        return np.nan
    return float(min(max(v, lo), hi))


def compute_microstructure(
    prices: pd.DataFrame | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """Core: 6 daily microstructure factors per stock from OHLCV.

    `prices` is injectable (PIT path passes an as-of-frozen frame). When None it's
    loaded live, optionally bounded by as_of_date.

    Returns DataFrame[sid, intraday_range_compression, closing_strength_1m,
    opening_gap_freq_1m, vwap_deviation_5d, bidask_spread_proxy, kyle_lambda].
    """
    cols = ["sid", *CLIPS.keys()]
    if prices is None:
        date_clause = f"AND date <= '{as_of_date}'" if as_of_date else ""
        prices = read_sql(
            "SELECT sid, date, open, high, low, close, volume FROM stock_prices "
            f"WHERE close > 0 {date_clause} ORDER BY sid, date"
        )
    if prices is None or prices.empty:
        return pd.DataFrame(columns=cols)

    prices = prices.sort_values(["sid", "date"])
    rows = []
    for sid, g in prices.groupby("sid", sort=False):
        rec = _one_stock(g)
        if rec is not None:
            rows.append({"sid": sid, **rec})
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=cols)
    for k in CLIPS:
        out[k] = out[k].round(5)
    return out[cols].reset_index(drop=True)


if __name__ == "__main__":
    out = compute_microstructure()
    print(f"Computed microstructure factors for {len(out):,} stocks")
    for c in CLIPS:
        s = out[c].dropna() if c in out else pd.Series(dtype=float)
        if len(s):
            print(f"  {c:28s} n={len(s):4d}  mean={s.mean():+.5f}  "
                  f"min={s.min():+.5f}  max={s.max():+.5f}")
