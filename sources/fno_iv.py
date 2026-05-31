"""
Alpha Signal v2 — F&O implied-volatility surface rollup — Plan 0002 §3.2.2 (IV half).

Derives an EOD implied-volatility surface for every F&O underlying by inverting
Black-76 on the **settlement prices already stored in fno_bhav** — no external IV
feed, no live option-chain dependency, and fully historical/backfillable (the
whole reason the IV half was thought "forward-only" until 2026-05-31; see ADR
0035 + memory iv_greeks_derivable_from_bhav).

Per (underlying, trade_date) it writes one fno_iv_history row:
  atm_iv             ATM IV on the expiry closest to ~30d (the VIX-comparable level)
  iv_skew_25d        iv(25Δ put) − iv(25Δ call) on that expiry  (+ve = downside fear)
  iv_term_structure  atm_iv(nearest ≥5d) − atm_iv(next expiry)  (+ve = backwardation/stress)

Validated 2026-05-31: NIFTY atm_iv tracks India VIX to ~0.1–2 vol points and sits
just below it (correct — VIX integrates the full smile + constant-30d), and CE/PE
IV match exactly at the ATM strike (put-call parity holds → inversion is sound).

Method notes:
  • Implied forward F from put-call parity at the ATM strike — removes the need to
    assume a dividend yield; only a small e^{rT} discount factor uses r (≈repo).
  • OTM convention: IV per strike from the call for K≥F, the put for K<F (OTM legs
    are the liquid, reliable ones). Far-OTM stale strikes are excluded upstream
    (fno_bhav keeps oi>0 ∨ vol>0) and by a settle>0 + min-time-value filter here.
  • Skew interpolates IV against Black-76 forward delta to ±0.25Δ on each wing.

Reads:  fno_bhav (settle, strike, option_type, expiry_date, underlying_price)
Writes: fno_iv_history (INSERT OR REPLACE)

Usage:
    python -m sources.fno_iv --backfill   # rollup every fno_bhav date not yet done
    python -m sources.fno_iv --date 2026-05-29
"""

from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

from db import get_db, read_sql

R = 0.065                 # India ~repo; enters only via the e^{-rT} discount factor
TARGET_DAYS = 30          # atm_iv basis expiry (VIX-comparable, stable across rolls)
MIN_DAYS_NEAR = 5         # skip <5d expiries — gamma/time-value explode, IV unstable
MIN_STRIKES_PER_WING = 2  # need ≥2 OTM strikes per wing to interpolate 25Δ
SQRT = np.sqrt


def _black76(F, K, T, sig, cp):
    """Black-76 price of an option on a forward F (cp = 'C' | 'P')."""
    if sig <= 0 or T <= 0:
        intrinsic = max(F - K, 0.0) if cp == "C" else max(K - F, 0.0)
        return np.exp(-R * T) * intrinsic
    d1 = (np.log(F / K) + 0.5 * sig * sig * T) / (sig * SQRT(T))
    d2 = d1 - sig * SQRT(T)
    df = np.exp(-R * T)
    if cp == "C":
        return df * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def _invert_iv(px, F, K, T, cp):
    """Implied vol from a Black-76 price. NaN if no root in (1e-4, 6.0)."""
    if px is None or px <= 0 or T <= 0 or F <= 0 or K <= 0:
        return np.nan
    # Reject prices below intrinsic (arbitrage / stale settle) — no valid IV.
    intrinsic = np.exp(-R * T) * (max(F - K, 0.0) if cp == "C" else max(K - F, 0.0))
    if px < intrinsic - 1e-6:
        return np.nan
    try:
        return brentq(lambda s: _black76(F, K, T, s, cp) - px, 1e-4, 6.0, maxiter=100)
    except Exception:
        return np.nan


def _forward_delta(F, K, T, sig, cp):
    """Black-76 forward delta (call ∈ (0,1), put ∈ (-1,0))."""
    if sig <= 0 or T <= 0:
        return np.nan
    d1 = (np.log(F / K) + 0.5 * sig * sig * T) / (sig * SQRT(T))
    return norm.cdf(d1) if cp == "C" else norm.cdf(d1) - 1.0


def _implied_forward(ce, pe, T):
    """Forward from put-call parity at the strike with the smallest |C−P| (ATM).

    F = K + e^{rT}(C − P). Returns (F, k_atm) or (None, None) if <3 common strikes.
    """
    common = ce.index.intersection(pe.index)
    if len(common) < 3:
        return None, None
    diff = (ce[common] - pe[common]).abs()
    k_atm = float(diff.idxmin())
    F = k_atm + np.exp(R * T) * float(ce[k_atm] - pe[k_atm])
    return (F if F > 0 else None), k_atm


def _atm_iv_for_expiry(g, trade_date):
    """ATM IV + implied forward for one (underlying, expiry) option slice.

    Returns (atm_iv, forward, n_strikes) — atm_iv is the mean of the CE & PE IV at
    the strike nearest the implied forward (they coincide under parity; the mean
    is just noise reduction). NaN atm_iv if it can't be inverted.
    """
    T = (date.fromisoformat(g["expiry_date"].iloc[0]) - date.fromisoformat(trade_date)).days / 365.0
    if T <= 0:
        return np.nan, None, 0
    ce = g[g["option_type"] == "CE"].set_index("strike")["settle"]
    pe = g[g["option_type"] == "PE"].set_index("strike")["settle"]
    ce = ce[ce > 0]
    pe = pe[pe > 0]
    F, _ = _implied_forward(ce, pe, T)
    common = ce.index.intersection(pe.index)
    if F is None or len(common) < 3:
        return np.nan, F, len(common)
    k_near = min(common, key=lambda k: abs(k - F))
    ivc = _invert_iv(ce[k_near], F, k_near, T, "C")
    ivp = _invert_iv(pe[k_near], F, k_near, T, "P")
    atm = np.nanmean([ivc, ivp])
    return (float(atm) if np.isfinite(atm) else np.nan), F, len(common)


def _skew_25d(g, trade_date, F):
    """iv(25Δ put) − iv(25Δ call) on one expiry, via OTM IVs interpolated over
    forward delta. NaN if either wing lacks ≥2 OTM strikes bracketing 0.25Δ."""
    T = (date.fromisoformat(g["expiry_date"].iloc[0]) - date.fromisoformat(trade_date)).days / 365.0
    if T <= 0 or F is None or F <= 0:
        return np.nan

    call_pts, put_pts = [], []  # (delta, iv)
    for _, r in g.iterrows():
        K = float(r["strike"])
        if K <= 0:
            continue
        # OTM convention: call for K≥F, put for K<F
        if K >= F:
            iv = _invert_iv(r["settle"], F, K, T, "C") if r["option_type"] == "CE" else np.nan
            if np.isfinite(iv):
                call_pts.append((_forward_delta(F, K, T, iv, "C"), iv))
        else:
            iv = _invert_iv(r["settle"], F, K, T, "P") if r["option_type"] == "PE" else np.nan
            if np.isfinite(iv):
                put_pts.append((_forward_delta(F, K, T, iv, "P"), iv))

    iv_call_25 = _interp_at(call_pts, 0.25)
    iv_put_25 = _interp_at(put_pts, -0.25)
    if not (np.isfinite(iv_call_25) and np.isfinite(iv_put_25)):
        return np.nan
    return float(iv_put_25 - iv_call_25)


def _interp_at(points, target_delta):
    """Interpolate iv at a target forward delta from (delta, iv) points."""
    pts = [(d, v) for d, v in points if np.isfinite(d) and np.isfinite(v)]
    if len(pts) < MIN_STRIKES_PER_WING:
        return np.nan
    pts.sort(key=lambda x: x[0])
    deltas = np.array([d for d, _ in pts])
    ivs = np.array([v for _, v in pts])
    if not (deltas.min() <= target_delta <= deltas.max()):
        return np.nan  # don't extrapolate beyond the observed wing
    return float(np.interp(target_delta, deltas, ivs))


def _rollup_iv_one(sym_df, trade_date):
    """One underlying's options on a date → IV surface rollup dict (or None)."""
    expiries = sorted(sym_df["expiry_date"].unique())
    # near = nearest expiry with ≥ MIN_DAYS_NEAR; far = the one after it
    dated = [(e, (date.fromisoformat(e) - date.fromisoformat(trade_date)).days) for e in expiries]
    near = next((e for e, d in dated if d >= MIN_DAYS_NEAR), None)
    if near is None:
        return None
    far = next((e for e, d in dated if d > (date.fromisoformat(near) - date.fromisoformat(trade_date)).days
                and e != near), None)
    # target = expiry closest to TARGET_DAYS (among ≥ MIN_DAYS_NEAR) — atm_iv basis
    elig = [(e, d) for e, d in dated if d >= MIN_DAYS_NEAR]
    if not elig:
        return None
    target = min(elig, key=lambda x: abs(x[1] - TARGET_DAYS))[0]
    days_target = (date.fromisoformat(target) - date.fromisoformat(trade_date)).days

    g_target = sym_df[sym_df["expiry_date"] == target]
    atm_iv, F, n_strikes = _atm_iv_for_expiry(g_target, trade_date)
    if not np.isfinite(atm_iv):
        return None
    skew = _skew_25d(g_target, trade_date, F)

    # Term structure: near vs far ATM IV (positive = inverted curve = stress)
    term = np.nan
    iv_near, _, _ = _atm_iv_for_expiry(sym_df[sym_df["expiry_date"] == near], trade_date)
    if far is not None:
        iv_far, _, _ = _atm_iv_for_expiry(sym_df[sym_df["expiry_date"] == far], trade_date)
        if np.isfinite(iv_near) and np.isfinite(iv_far):
            term = float(iv_near - iv_far)

    return {
        "target_expiry": target,
        "days_to_target": int(days_target),
        "forward": round(float(F), 2) if F else None,
        "atm_iv": round(float(atm_iv), 4),
        "iv_skew_25d": round(float(skew), 4) if np.isfinite(skew) else None,
        "iv_term_structure": round(float(term), 4) if np.isfinite(term) else None,
        "n_strikes": int(n_strikes),
    }


def compute_iv_for_date(trade_date):
    """Invert the IV surface for every underlying on `trade_date` → fno_iv_history.
    INSERT OR REPLACE. Returns rows written."""
    df = read_sql(
        "SELECT sid, symbol, expiry_date, strike, option_type, underlying_price, settle "
        "FROM fno_bhav WHERE trade_date = ? AND instrument_type IN ('STO','IDO') AND settle > 0",
        params=(trade_date,),
    )
    if df.empty:
        return 0
    rows = []
    for symbol, sym_df in df.groupby("symbol"):
        roll = _rollup_iv_one(sym_df, trade_date)
        if roll is None:
            continue
        sid_vals = sym_df["sid"].dropna().unique()
        rows.append({
            "sid": sid_vals[0] if len(sid_vals) else None,
            "symbol": symbol,
            "trade_date": trade_date,
            **roll,
        })
    if not rows:
        return 0
    cols = ["sid", "symbol", "trade_date", "target_expiry", "days_to_target",
            "forward", "atm_iv", "iv_skew_25d", "iv_term_structure", "n_strikes"]
    out = pd.DataFrame(rows)[cols]
    placeholders = ", ".join(["?"] * len(cols))
    sql = f"INSERT OR REPLACE INTO fno_iv_history ({', '.join(cols)}) VALUES ({placeholders})"
    with get_db() as conn:
        conn.executemany(sql, out.where(pd.notnull(out), None).values.tolist())
    return len(out)


def compute_iv(all_missing=True):
    """DAILY pipeline producer (`compute_fno_iv`). Inverts the IV surface for every
    fno_bhav trade_date not yet in fno_iv_history (self-heals across a backfill)."""
    bhav_dates = set(read_sql("SELECT DISTINCT trade_date FROM fno_bhav")["trade_date"])
    done = set(read_sql("SELECT DISTINCT trade_date FROM fno_iv_history")["trade_date"]) if \
        read_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='fno_iv_history'").shape[0] else set()
    todo = sorted(bhav_dates - done) if all_missing else sorted(bhav_dates)
    total = 0
    for d in todo:
        n = compute_iv_for_date(d)
        total += n
        if n:
            print(f"  fno_iv {d}: ✅ {n} underlyings")
    return total


def compute(all_missing=True):
    """Pipeline entry point (`compute_fno_iv`)."""
    return compute_iv(all_missing=all_missing)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="rollup all missing dates")
    ap.add_argument("--date", help="single trade_date YYYY-MM-DD")
    ap.add_argument("--all", action="store_true", help="recompute every date (not just missing)")
    args = ap.parse_args()

    # Ensure the table exists (schema.sql is the source of truth; mirror its DDL).
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fno_iv_history (
                sid TEXT, symbol TEXT NOT NULL, trade_date TEXT NOT NULL,
                target_expiry TEXT, days_to_target INTEGER, forward REAL,
                atm_iv REAL, iv_skew_25d REAL, iv_term_structure REAL,
                n_strikes INTEGER, computed_at TEXT DEFAULT (datetime('now')),
                UNIQUE(symbol, trade_date))""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fno_iv_sid_date ON fno_iv_history(sid, trade_date)")

    if args.date:
        n = compute_iv_for_date(args.date)
        print(f"fno_iv {args.date}: {n} underlyings")
    else:
        n = compute_iv(all_missing=not args.all)
        print(f"fno_iv: {n} total rows written")


if __name__ == "__main__":
    main()
