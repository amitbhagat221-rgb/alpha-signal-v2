"""
Alpha Signal v2 — Small-Cap Trend Regime (multibagger gate)

Classifies the broad small-cap regime from NIFTY SMALLCAP 250 (nse_index_history)
via an EMA trend rule. Report C / IIMB Management Review found a simple EMA rule
on the Nifty Small-Cap index times broad small-cap strength; we use the trend to
CONDITION the multibagger screen's pillar weights, because the survivorship cohort
(ADR 0039) shows quality captures 2–4yr multibaggers in small-cap DOWNTRENDS and
UNDERperforms them in junk-rally UPTRENDS.

Regime (close vs EMA200, EMA50/EMA200 cross, EMA50 63d slope):
  UPTREND   — close > EMA200 AND EMA50 > EMA200   (risk-on / junk-rally prone)
  DOWNTREND — close < EMA200 AND EMA50 < EMA200   (bear / quality-favorable)
  NEUTRAL   — mixed (chop / transition)

This is an ENTRY-time proxy for the (unobservable) forward holding-period regime —
the IIMB finding is that small-cap trends persist enough for the entry trend to
carry information. The cohort validates WHICH weights win per regime; this module
only labels the CURRENT regime for the live screen.

Data note: nse_index_history small-cap depth starts 2023-06, so this classifier
can label the live/recent regime but NOT the pre-2023 cohort anchors. The cohort
characterises each historical window by its own realised small-cap strength
(universe-median forward multiple) instead — see tools/multibagger_cohort.py.

Reads: nse_index_history (NIFTY SMALLCAP 250). Pure read; no per-stock state.

Usage:
    python -m scoring.regime_smallcap            # print current regime
    python -m scoring.regime_smallcap --as-of 2025-02-25
"""

import argparse

import pandas as pd

from db import read_sql

SMALLCAP_INDEX = "NIFTY SMALLCAP 250"
EMA_FAST = 50
EMA_SLOW = 200
SLOPE_WINDOW = 63          # ~1 quarter of trading days
MIN_BARS = EMA_SLOW        # need a full slow-EMA window for a trustworthy label

UPTREND, DOWNTREND, NEUTRAL = "UPTREND", "DOWNTREND", "NEUTRAL"


def _load_series(as_of=None):
    """Daily close series for the small-cap index, up to and including `as_of`."""
    sql = (f"SELECT trade_date, close FROM nse_index_history "
           f"WHERE index_symbol = ?")
    params = [SMALLCAP_INDEX]
    if as_of:
        sql += " AND trade_date <= ?"
        params.append(as_of)
    sql += " ORDER BY trade_date"
    df = read_sql(sql, params=params)
    if df.empty:
        return pd.Series(dtype="float64")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.set_index("trade_date")["close"].astype("float64")


def classify(as_of=None, series=None):
    """Return the current small-cap trend regime as a dict.

    Pass `series` (a close-indexed pd.Series) to classify a preloaded path without
    re-reading the DB; otherwise reads nse_index_history up to `as_of` (latest).

    Keys: regime, as_of, close, ema_fast, ema_slow, close_vs_slow_pct,
          cross_pct (ema_fast/ema_slow−1), slope_pct (ema_fast 63d slope),
          n_bars, insufficient (True if < MIN_BARS — regime falls back to NEUTRAL).
    """
    c = series if series is not None else _load_series(as_of)
    out = {"regime": NEUTRAL, "as_of": None, "close": None,
           "ema_fast": None, "ema_slow": None, "close_vs_slow_pct": None,
           "cross_pct": None, "slope_pct": None, "n_bars": int(len(c)),
           "insufficient": True}
    if c.empty:
        return out

    ema_f = c.ewm(span=EMA_FAST, adjust=False).mean()
    ema_s = c.ewm(span=EMA_SLOW, adjust=False).mean()
    close, ef, es = float(c.iloc[-1]), float(ema_f.iloc[-1]), float(ema_s.iloc[-1])

    out.update({
        "as_of": c.index[-1].date().isoformat(),
        "close": close, "ema_fast": ef, "ema_slow": es,
        "close_vs_slow_pct": 100.0 * (close / es - 1.0) if es else None,
        "cross_pct": 100.0 * (ef / es - 1.0) if es else None,
    })
    if len(ema_f) > SLOPE_WINDOW:
        prev = float(ema_f.iloc[-1 - SLOPE_WINDOW])
        out["slope_pct"] = 100.0 * (ef / prev - 1.0) if prev else None

    # Below MIN_BARS the slow EMA hasn't seen a full window — don't trust a trend
    # label; stay NEUTRAL (the screen falls back to balanced weights).
    if len(c) < MIN_BARS:
        return out
    out["insufficient"] = False

    if close > es and ef > es:
        out["regime"] = UPTREND
    elif close < es and ef < es:
        out["regime"] = DOWNTREND
    else:
        out["regime"] = NEUTRAL
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", default=None, help="ISO date; classify as of this date")
    args = p.parse_args()
    r = classify(as_of=args.as_of)
    if r["close"] is None:
        print(f"No {SMALLCAP_INDEX} data available.")
        return
    print(f"Small-Cap Regime ({SMALLCAP_INDEX}) — as of {r['as_of']} ({r['n_bars']} bars)")
    print(f"  close {r['close']:.0f} | EMA{EMA_FAST} {r['ema_fast']:.0f} | EMA{EMA_SLOW} {r['ema_slow']:.0f}")
    print(f"  close vs EMA{EMA_SLOW}: {r['close_vs_slow_pct']:+.1f}%  | "
          f"EMA{EMA_FAST}/EMA{EMA_SLOW} cross: {r['cross_pct']:+.1f}%  | "
          f"EMA{EMA_FAST} {SLOPE_WINDOW}d slope: "
          f"{(f'{r['slope_pct']:+.1f}%' if r['slope_pct'] is not None else 'n/a')}")
    flag = "  [INSUFFICIENT HISTORY → NEUTRAL fallback]" if r["insufficient"] else ""
    print(f"  REGIME: {r['regime']}{flag}")


if __name__ == "__main__":
    main()
