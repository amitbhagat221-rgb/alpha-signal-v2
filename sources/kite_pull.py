"""
Alpha Signal v2 — Zerodha Kite Connect ingest — Plan 0002 §3.1c.

Intraday bars + daily microstructure aggregates from Kite Connect. Feeds the
true-intraday §3.2.3 microstructure factors that have NO daily substitute:
`volume_clock_concentration`, `tick_imbalance_5d`, `intraday_momentum_persistence`.
(The other 6 §3.2.3 factors are daily-derivable from stock_prices — see
signals/microstructure.py — so this is only needed for those 3.)

Now: the Kite login helpers (`kite()`, NoKiteSession) used by every Kite module. The minute
bars are fetched by sources/kite_bars.py into Parquet (ADR 0072); the SQLite bar tables and
aggregates below were never run and are superseded.

⚠ STATUS (original scaffold): PENDING LIVE CREDENTIALS. Written 2026-05-31 but NOT yet
verified against a live key, and deliberately NOT wired into config.PIPELINE_STEPS
— a daily pipeline must not depend on an unverified producer (CLAUDE.md: silent
failures are the enemy). Verify with `--check-auth` first, then `--instruments`,
then a small `--backfill-bars --universe fno --days 5` smoke before any full run.

Kite reality that shapes this module:
  • Kite Connect is a SEPARATE ₹500/mo dev-app subscription on top of the trading
    login. Create the app at developers.kite.trade → api_key + api_secret.
  • Zerodha flushes EVERY API session each morning at a time between ~06:00 and ~07:30 IST
    (docs: "6 AM"; Zerodha staff: "around 7:30"; their advice: take the day's token at or after
    08:30 IST). A login at 06:19 IST died before 08:35 on 2026-11-03 and the 09:16 close did
    not run. So: the day's login is done by hand after 08:30, the token is cached in a dated
    file (IST date), and kite() PROVES a cached token with a profile() call before handing it
    out — a rejected token is deleted and reported as no session (ADR 0093). A session is
    also killed by a Kite web/app logout and by a new generate_session on the same api_key.
  • Historical minute bars for listed NSE stocks go back to 2015 (probed 2026-10-11:
    RELIANCE / COFORGE / IFBIND full sessions every year 2015–2026, nothing 2013–14).
    The 60-day limit is per REQUEST, not total depth — loop in chunks. Expired F&O
    contracts and delisted stocks have no intraday history (survivors only).
  • Historical API rate limit ≈ 3 req/s; one call fetches a full date-range for
    one instrument+interval, so the whole F&O universe is ~220 calls (~1-2 min).

Credentials (env, from ~/.config/alpha-signal/secrets.env via run.sh — NEVER in code):
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
from datetime import date, datetime, timedelta

import pandas as pd

from db import get_db, read_sql
from sources import _http

TOKEN_CACHE = os.path.expanduser("~/.kite_access_token.json")  # {date, access_token}
# Every Kite call (login, instruments, historical bars) goes through the host door
# as _http.pace("kite"): CLAUDE.md 2s floor (Kite itself allows ~3 req/s).
LOGIN_URL = "https://kite.zerodha.com/api/login"
TWOFA_URL = "https://kite.zerodha.com/api/twofa"


# ─────────────────────────── Auth (the reusable hard part) ───────────────────────────

SECRETS = os.path.expanduser("~/.config/alpha-signal/secrets.env")
from config import KITE_LOGIN_PAGE as LOGIN_PAGE   # ops cockpit one-tap login (plan 0022)


def _secret_from_file(name):
    """`export NAME="value"` from the secrets file — for processes that did not start
    through run.sh (the cockpit services), so the file stays the one copy."""
    import re
    try:
        with open(SECRETS) as f:
            for line in f:
                m = re.match(rf'\s*export\s+{name}="?([^"\n]*)"?\s*$', line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


def _env(name):
    v = os.environ.get(name) or _secret_from_file(name)
    if not v:
        raise RuntimeError(
            f"{name} not set. Add Kite creds to ~/.config/alpha-signal/secrets.env "
            f"(KITE_API_KEY/API_SECRET/USER_ID/PASSWORD/TOTP_SECRET) — never in code.")
    return v


IST = __import__("zoneinfo").ZoneInfo("Asia/Kolkata")
SAFE_LOGIN_IST = "08:30"                           # Zerodha's own advice: take the day's token at or after this


def _ist_now():
    return datetime.now(IST)


def login_info():
    """{"date": IST date, "at": UTC iso of the login, "early": logged in before 08:30 IST that day} for today's
    cached token, else None. Never touches Kite."""
    try:
        import json
        with open(TOKEN_CACHE) as f:
            d = json.load(f)
        if d.get("date") != _ist_now().date().isoformat() or not d.get("access_token"):
            return None
        at = d.get("at")
        early = None
        if at:
            t = datetime.fromisoformat(at).astimezone(IST)
            h, m = map(int, SAFE_LOGIN_IST.split(":"))
            early = (t.hour, t.minute) < (h, m)
        return {"date": d["date"], "at": at, "early": early}
    except Exception:
        return None


def _cached_token():
    """Return today's (IST) cached access_token, or None if absent/stale."""
    try:
        import json
        with open(TOKEN_CACHE) as f:
            d = json.load(f)
        if d.get("date") == _ist_now().date().isoformat() and d.get("access_token"):
            return d["access_token"]
    except Exception:
        pass
    return None


def _cache_token(tok):
    import json
    with open(TOKEN_CACHE, "w") as f:
        json.dump({"date": _ist_now().date().isoformat(), "access_token": tok,
                   "at": datetime.now(__import__("datetime").timezone.utc).isoformat()}, f)
    os.chmod(TOKEN_CACHE, 0o600)


def _drop_token(why):
    try:
        os.remove(TOKEN_CACHE)
    except FileNotFoundError:
        pass
    print(f"kite: cached token dropped ({why})")


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
    with _http.pace("kite"):
        r = s.post(LOGIN_URL, data={"user_id": _env("KITE_USER_ID"),
                                    "password": _env("KITE_PASSWORD")})
    r.raise_for_status()
    request_id = r.json()["data"]["request_id"]
    with _http.pace("kite"):   # TOTP minted AFTER the gap wait, so it can't expire in it
        totp = pyotp.TOTP(_env("KITE_TOTP_SECRET")).now()
        r2 = s.post(TWOFA_URL, data={"user_id": _env("KITE_USER_ID"),
                                     "request_id": request_id, "twofa_value": totp})
    r2.raise_for_status()
    # Hitting the connect login URL now 302-redirects to the app's registered
    # redirect_url with ?request_token=…. If that URL isn't a live server the
    # request errors — we parse the attempted URL for the token either way.
    try:
        with _http.pace("kite"):
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


class NoKiteSession(RuntimeError):
    """No Kite login today: Zerodha flushes sessions 06:00–07:30 IST; the day's token is taken by hand after 08:30."""


WRITE_METHODS = ("place_order", "modify_order", "cancel_order", "exit_order", "convert_position", "place_gtt",
                 "modify_gtt", "delete_gtt", "place_mf_order", "cancel_mf_order", "place_mf_sip", "modify_mf_sip", "cancel_mf_sip")


class ClaudeMayNotTrade(RuntimeError):
    """A broker write from inside a Claude Code session (2026-11-03)."""


def _guard_writes(kc):
    """Inside a Claude Code session (CLAUDECODE is set in its shells, never in cron or the cockpit service) every broker
    write raises, however the code got here. Reads still work."""
    if os.environ.get("CLAUDECODE"):
        def refuse(*a, **kw):
            raise ClaudeMayNotTrade("broker writes are refused inside a Claude session: only Amit and the scheduled jobs trade")
        for name in WRITE_METHODS:
            setattr(kc, name, refuse)
    return kc


def kite(request_token=None, cached_only=False):
    """Return an authenticated KiteConnect. Uses today's cached token if present;
    else exchanges a request_token (passed or auto-logged-in) for a new one.
    `cached_only`: never log in — raise NoKiteSession when today's token is missing
    (scheduled jobs: trading logins are done by hand, plan 0022)."""
    from kiteconnect import KiteConnect
    api_key = _env("KITE_API_KEY")
    kc = KiteConnect(api_key=api_key)

    tok = _cached_token()
    if tok:
        kc.set_access_token(tok)
        from kiteconnect.exceptions import TokenException
        try:                                        # a cached token is a session only when Kite says so
            with _http.pace("kite"):
                kc.profile()
        except TokenException as e:
            _drop_token(f"Kite rejected it: {e}")
            raise NoKiteSession(f"Kite rejected today's token (flushed, or a Kite logout) — log in again after "
                                f"{SAFE_LOGIN_IST} IST at {LOGIN_PAGE}") from e
        return _guard_writes(kc)

    if request_token is None:
        if cached_only:
            raise NoKiteSession(f"no Kite login today — log in at {LOGIN_PAGE}")
        request_token = _auto_request_token(api_key)
    with _http.pace("kite"):
        data = kc.generate_session(request_token, api_secret=_env("KITE_API_SECRET"))
    _cache_token(data["access_token"])
    kc.set_access_token(data["access_token"])
    return _guard_writes(kc)


# ─────────────────────────── Instrument map ───────────────────────────

def build_instrument_map(kc=None):
    """Map our universe (stocks.ticker) → Kite NSE equity instrument_token.
    Writes kite_instruments(sid, ticker, instrument_token, tradingsymbol). Returns n."""
    kc = kc or kite()
    with _http.pace("kite"):
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
            with _http.pace("kite"):
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
