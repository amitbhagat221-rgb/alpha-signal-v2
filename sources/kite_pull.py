"""
Alpha Signal v2 — Zerodha Kite Connect ingest — Plan 0002 §3.1c.

Intraday bars + daily microstructure aggregates from Kite Connect. Feeds the
true-intraday §3.2.3 microstructure factors that have NO daily substitute:
`volume_clock_concentration`, `tick_imbalance_5d`, `intraday_momentum_persistence`.
(The other 6 §3.2.3 factors are daily-derivable from stock_prices — see
signals/microstructure.py — so this is only needed for those 3.)

⚠ STATUS: SCAFFOLD, PENDING LIVE CREDENTIALS. Written 2026-05-31 but NOT yet
verified against a live key, and deliberately NOT wired into config.PIPELINE_STEPS
— a daily pipeline must not depend on an unverified producer (CLAUDE.md: silent
failures are the enemy). Verify with `--check-auth` first, then `--instruments`,
then a small `--backfill-bars --universe fno --days 5` smoke before any full run.

Kite reality that shapes this module:
  • Kite Connect is a SEPARATE ₹500/mo dev-app subscription on top of the trading
    login. Create the app at developers.kite.trade → api_key + api_secret.
  • The access_token expires every morning (~06:00 IST). For unattended cron we
    auto-login with the account's TOTP 2FA secret (pyotp) and cache the token in
    a dated file so we log in at most once per day.
  • Historical INTRADAY (minute) is only ~60 trading days rolling — these factors
    are forward-accumulation, not backfillable deep. Set this up early to start
    the 90-day clock.
  • Historical API rate limit ≈ 3 req/s; one call fetches a full date-range for
    one instrument+interval, so the whole F&O universe is ~220 calls (~1-2 min).

Credentials (env, via v1 run_pipeline.sh exports — NEVER in code):
    KITE_API_KEY, KITE_API_SECRET            — from the Connect dev app
    KITE_USER_ID, KITE_PASSWORD, KITE_TOTP_SECRET  — for unattended login
  (Alternatively, paste a fresh token: `--request-token <tok>`.)

Reads:  stocks (ticker→sid map)
Writes: kite_intraday_bars, kite_tick_aggregates

Usage:
    python -m sources.kite_pull --check-auth
    python -m sources.kite_pull --instruments
    python -m sources.kite_pull --backfill-bars --universe fno --days 60
    python -m sources.kite_pull --aggregate
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import date, datetime, timedelta

import pandas as pd

from db import get_db, read_sql

TOKEN_CACHE = os.path.expanduser("~/.kite_access_token.json")  # {date, access_token}
HIST_RATE_SLEEP = 0.34   # ≈3 req/s historical-data limit
LOGIN_URL = "https://kite.zerodha.com/api/login"
TWOFA_URL = "https://kite.zerodha.com/api/twofa"


# ─────────────────────────── Auth (the reusable hard part) ───────────────────────────

def _env(name):
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(
            f"{name} not set. Add Kite creds to v1 run_pipeline.sh exports "
            f"(KITE_API_KEY/API_SECRET/USER_ID/PASSWORD/TOTP_SECRET) — never in code.")
    return v


def _cached_token():
    """Return today's cached access_token, or None if absent/stale."""
    try:
        import json
        with open(TOKEN_CACHE) as f:
            d = json.load(f)
        if d.get("date") == date.today().isoformat() and d.get("access_token"):
            return d["access_token"]
    except Exception:
        pass
    return None


def _cache_token(tok):
    import json
    with open(TOKEN_CACHE, "w") as f:
        json.dump({"date": date.today().isoformat(), "access_token": tok}, f)
    os.chmod(TOKEN_CACHE, 0o600)


def _auto_request_token(api_key):
    """Headless login (user_id + password + TOTP) → request_token.

    Uses Kite's web login endpoints; brittle by nature (undocumented, can change).
    If this breaks, fall back to the manual flow: open
    https://kite.trade/connect/login?api_key=<key>&v=3 , log in, copy the
    request_token from the redirect URL, and pass it via --request-token.
    """
    import re
    import pyotp
    import requests

    s = requests.Session()
    r = s.post(LOGIN_URL, data={"user_id": _env("KITE_USER_ID"),
                                "password": _env("KITE_PASSWORD")})
    r.raise_for_status()
    request_id = r.json()["data"]["request_id"]
    totp = pyotp.TOTP(_env("KITE_TOTP_SECRET")).now()
    r2 = s.post(TWOFA_URL, data={"user_id": _env("KITE_USER_ID"),
                                 "request_id": request_id, "twofa_value": totp})
    r2.raise_for_status()
    # Hitting the connect login URL now 302-redirects to the app's registered
    # redirect_url with ?request_token=…. If that URL isn't a live server the
    # request errors — we parse the attempted URL for the token either way.
    try:
        resp = s.get(f"https://kite.trade/connect/login?api_key={api_key}&v=3",
                     allow_redirects=True)
        m = re.search(r"request_token=([\w]+)", resp.url)
    except requests.exceptions.RequestException as e:
        attempted = getattr(getattr(e, "request", None), "url", "") or ""
        m = re.search(r"request_token=([\w]+)", str(attempted))
    if m:
        return m.group(1)
    raise RuntimeError(
        "Could not auto-extract request_token — use the manual --request-token fallback "
        "(open https://kite.trade/connect/login?api_key=<key>&v=3, log in, copy the token).")


def kite(request_token=None):
    """Return an authenticated KiteConnect. Uses today's cached token if present;
    else exchanges a request_token (passed or auto-logged-in) for a new one."""
    from kiteconnect import KiteConnect
    api_key = _env("KITE_API_KEY")
    kc = KiteConnect(api_key=api_key)

    tok = _cached_token()
    if tok:
        kc.set_access_token(tok)
        return kc

    if request_token is None:
        request_token = _auto_request_token(api_key)
    data = kc.generate_session(request_token, api_secret=_env("KITE_API_SECRET"))
    _cache_token(data["access_token"])
    kc.set_access_token(data["access_token"])
    return kc


# ─────────────────────────── Instrument map ───────────────────────────

def build_instrument_map(kc=None):
    """Map our universe (stocks.ticker) → Kite NSE equity instrument_token.
    Writes kite_instruments(sid, ticker, instrument_token, tradingsymbol). Returns n."""
    kc = kc or kite()
    instruments = pd.DataFrame(kc.instruments("NSE"))
    eq = instruments[instruments["instrument_type"] == "EQ"][["tradingsymbol", "instrument_token"]]
    uni = read_sql("SELECT sid, ticker FROM stocks WHERE ticker IS NOT NULL")
    merged = uni.merge(eq, left_on="ticker", right_on="tradingsymbol", how="inner")
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS kite_instruments (
            sid TEXT, ticker TEXT, instrument_token INTEGER, tradingsymbol TEXT,
            updated_at TEXT DEFAULT (datetime('now')), UNIQUE(sid))""")
        conn.executemany(
            "INSERT OR REPLACE INTO kite_instruments (sid, ticker, instrument_token, tradingsymbol) "
            "VALUES (?,?,?,?)",
            merged[["sid", "ticker", "instrument_token", "tradingsymbol"]].values.tolist())
    print(f"  kite_instruments: {len(merged)}/{len(uni)} universe SIDs mapped to NSE tokens")
    return len(merged)


def _universe_tokens(which="fno"):
    """Resolve the instrument set to pull. 'fno' = stocks in fno_bhav (liquid,
    pairs with the options factors); 'nifty500'; 'all' = full mapped universe."""
    base = read_sql("SELECT sid, ticker, instrument_token FROM kite_instruments")
    if which == "fno":
        fno = set(read_sql("SELECT DISTINCT sid FROM fno_bhav WHERE sid IS NOT NULL")["sid"])
        return base[base["sid"].isin(fno)]
    if which == "nifty500":
        n500 = set(read_sql("SELECT sid FROM stocks WHERE in_nifty500=1")["sid"])
        return base[base["sid"].isin(n500)]
    return base


# ─────────────────────────── Bars + aggregates ───────────────────────────

def backfill_bars(days=60, universe="fno", kc=None):
    """Pull `days` of minute bars for the chosen universe → kite_intraday_bars
    (INSERT OR IGNORE, append-only). Rate-limited. Returns rows written."""
    kc = kc or kite()
    toks = _universe_tokens(universe)
    if toks.empty:
        raise RuntimeError("No instrument tokens — run --instruments first")
    frm = (date.today() - timedelta(days=days)).isoformat() + " 09:00:00"
    to = date.today().isoformat() + " 16:00:00"
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS kite_intraday_bars (
            sid TEXT, instrument_token INTEGER, ts TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            UNIQUE(instrument_token, ts))""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kite_bars_sid_ts ON kite_intraday_bars(sid, ts)")
    total, n_ok, n_err = 0, 0, 0
    for _, row in toks.iterrows():
        try:
            bars = kc.historical_data(int(row["instrument_token"]), frm, to, "minute")
            recs = [(row["sid"], int(row["instrument_token"]), b["date"].isoformat(),
                     b["open"], b["high"], b["low"], b["close"], b["volume"]) for b in bars]
            with get_db() as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO kite_intraday_bars "
                    "(sid,instrument_token,ts,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?,?)", recs)
            total += len(recs); n_ok += 1
        except Exception as e:
            n_err += 1
            print(f"  {row['ticker']}: {e}")
        time.sleep(HIST_RATE_SLEEP)
    if n_ok == 0 and n_err:
        raise RuntimeError(f"kite backfill: all {n_err} calls failed — auth/endpoint issue")
    print(f"  kite_intraday_bars: {total} rows · {n_ok} ok · {n_err} err")
    return total


def compute_tick_aggregates():
    """Daily VWAP + intraday-derived microstructure aggregates from minute bars →
    kite_tick_aggregates. (The 3 true-intraday factors read from here.)"""
    bars = read_sql("SELECT sid, ts, open, high, low, close, volume FROM kite_intraday_bars")
    if bars.empty:
        return 0
    bars["d"] = bars["ts"].str[:10]
    bars["t"] = bars["ts"].str[11:16]
    rows = []
    for (sid, d), g in bars.groupby(["sid", "d"]):
        vol = g["volume"].sum()
        if vol <= 0:
            continue
        vwap = float((g["close"] * g["volume"]).sum() / vol)
        last30 = g[g["t"] >= "15:00"]["volume"].sum()
        rows.append({
            "sid": sid, "trade_date": d, "vwap": round(vwap, 2),
            "vol_last30min_frac": round(float(last30 / vol), 4),   # volume_clock_concentration
            "n_bars": len(g),
        })
    if not rows:
        return 0
    out = pd.DataFrame(rows)
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS kite_tick_aggregates (
            sid TEXT, trade_date TEXT, vwap REAL, vol_last30min_frac REAL, n_bars INTEGER,
            computed_at TEXT DEFAULT (datetime('now')), UNIQUE(sid, trade_date))""")
        conn.executemany(
            "INSERT OR REPLACE INTO kite_tick_aggregates (sid,trade_date,vwap,vol_last30min_frac,n_bars) "
            "VALUES (?,?,?,?,?)", out[["sid","trade_date","vwap","vol_last30min_frac","n_bars"]].values.tolist())
    print(f"  kite_tick_aggregates: {len(out)} stock-days")
    return len(out)


def compute():
    """Daily pipeline entry (NOT wired until verified): refresh today's bars +
    aggregates. Kept here so wiring is a one-line PIPELINE_STEPS add post-verify."""
    kc = kite()
    backfill_bars(days=5, universe="fno", kc=kc)  # short self-healing window
    return compute_tick_aggregates()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-auth", action="store_true", help="verify creds: print profile + a sample LTP")
    ap.add_argument("--request-token", help="manual request_token (skips headless TOTP login)")
    ap.add_argument("--instruments", action="store_true", help="build sid→NSE-token map")
    ap.add_argument("--backfill-bars", action="store_true")
    ap.add_argument("--universe", default="fno", choices=["fno", "nifty500", "all"])
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--aggregate", action="store_true", help="compute daily aggregates from bars")
    args = ap.parse_args()

    if args.check_auth:
        kc = kite(request_token=args.request_token)
        prof = kc.profile()
        print(f"  ✅ auth OK — {prof.get('user_name')} ({prof.get('user_id')})")
        ltp = kc.ltp(["NSE:RELIANCE"])
        print(f"  sample LTP NSE:RELIANCE = {ltp.get('NSE:RELIANCE', {}).get('last_price')}")
        return
    if args.instruments:
        build_instrument_map(); return
    if args.backfill_bars:
        backfill_bars(days=args.days, universe=args.universe); return
    if args.aggregate:
        compute_tick_aggregates(); return
    ap.print_help()


if __name__ == "__main__":
    main()
