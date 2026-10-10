"""
Alpha Signal v2 — the market reading behind dynamic option setups (plan 0023).

One function used by the backtest (tools/option_dynamic_study.py) and, if a policy
passes, by the live paper book: `readings(underlying)` → one row per trading day with
only what was known at that day's close.

    vrp        ATM IV (≈30-day, fno_iv_history) − 20-day realised vol of the index closes
    r5         5-session index return            r5_pct     its expanding percentile
    skew       25-delta put IV − call IV         skew_pct   expanding percentile (≥120 days)
    term       near ATM IV − next expiry ATM IV  (> 0 = inverted = stress)
    pcr        put/call open interest (front expiry)  pcr_pct  expanding percentile (≥120 days)
    usd5, oil5 |5-day % change| of USD/INR and Brent at the PREVIOUS day (yfinance prints
               after the Indian close), with expanding percentiles usd5_pct / oil5_pct

Expanding percentiles use only values strictly before the day (no look-ahead, no tuning).
"""

import numpy as np
import pandas as pd

from db import read_sql

MIN_HISTORY = {"r5": 250, "skew": 120, "pcr": 120, "usd5": 250, "oil5": 250}


def _series(sql, params):
    df = read_sql(sql, params=params)
    return df.set_index(df.columns[0])[df.columns[1]].astype(float).sort_index()


def index_closes(underlying):
    """Daily index closes: NIFTY from macro_history (2015 →), SENSEX from its option chain's underlying."""
    if underlying == "NIFTY":
        return _series("SELECT date, value FROM macro_history WHERE indicator_id = 'nifty50'", [])
    return _series("SELECT trade_date, MAX(underlying_price) FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' "
                   "GROUP BY trade_date", [underlying])


def expanding_pct(s, min_n):
    """Percentile of each value among the values strictly before it (NaN until min_n exist)."""
    vals, out = s.values, np.full(len(s), np.nan)
    for i in range(len(s)):
        past = vals[:i][~np.isnan(vals[:i])]
        if len(past) >= min_n and not np.isnan(vals[i]):
            out[i] = (past < vals[i]).mean()
    return pd.Series(out, index=s.index)


def readings(underlying):
    """One row per trading day of `underlying`'s option chain, PIT (see module docstring)."""
    close = index_closes(underlying)
    logret = np.log(close).diff()
    rv20 = logret.rolling(20).std() * np.sqrt(252)
    r5 = close / close.shift(5) - 1
    iv = read_sql("SELECT trade_date, atm_iv, iv_skew_25d, iv_term_structure FROM fno_iv_history WHERE symbol = ?",
                  params=[underlying]).set_index("trade_date").sort_index()
    pcr = _series("SELECT trade_date, pcr_oi FROM fno_pcr_history WHERE symbol = ?", [underlying])
    macro = {}
    for name, ind in (("usd5", "usdinr"), ("oil5", "brent_crude")):
        m = _series("SELECT date, value FROM macro_history WHERE indicator_id = ?", [ind])
        macro[name] = (m / m.shift(5) - 1).abs()

    days = read_sql("SELECT DISTINCT trade_date FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' ORDER BY 1",
                    params=[underlying])["trade_date"]
    df = pd.DataFrame(index=pd.Index(days, name="date"))
    df["vrp"] = iv["atm_iv"].reindex(df.index) - rv20.reindex(df.index)
    df["r5"] = r5.reindex(df.index)
    df["skew"] = iv["iv_skew_25d"].reindex(df.index)
    df["term"] = iv["iv_term_structure"].reindex(df.index)
    df["pcr"] = pcr.reindex(df.index)
    # percentiles over each input's own full history, then read on the chain's days
    df["r5_pct"] = expanding_pct(r5.dropna(), MIN_HISTORY["r5"]).reindex(df.index)
    df["skew_pct"] = expanding_pct(df["skew"], MIN_HISTORY["skew"])
    df["pcr_pct"] = expanding_pct(df["pcr"], MIN_HISTORY["pcr"])
    for name, s in macro.items():
        prev = s.reindex(df.index.union(s.index)).sort_index().ffill().shift(1)   # value of the previous day
        df[name] = prev.reindex(df.index)
        df[name + "_pct"] = expanding_pct(s.dropna(), MIN_HISTORY[name]).reindex(
            df.index.union(s.index)).sort_index().ffill().shift(1).reindex(df.index)
    return df
