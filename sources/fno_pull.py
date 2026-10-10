"""
Alpha Signal v2 — NSE F&O (derivatives) EOD ingest. Track 3.1b.

One source, two tables, one daily rhythm:

  - `fno_bhav`         raw per-contract EOD grid (the backfillable store)
  - `fno_pcr_history`  computed per-(underlying, date) PCR + max-pain rollup

The whole pipeline rides on a single nselib call:

    nselib.derivatives.fno_bhav_copy(trade_date)  ->  ~35K rows for ONE day

That one frame is the entire F&O market for that session — every strike × CE/PE
× expiry across ~211 stock + 5 index underlyings — so there is NO per-symbol
loop (the plan's original `option_chain_equities`-per-stock assumption is moot).
It is also historically backfillable from NSE archives (verified ≥6 months),
which is why the OI/PCR/max-pain §3.2.2 factors are NOT gated on the usual
90-day accumulation clock.

What this module does NOT do: IV / Greeks. Those need the live option-chain API
(forward-only, no archive) and a weekday verification — deferred to a later
session as `fno_iv_snapshot`. See HANDOFF + docs/plans/0002 §3.1b / §3.2.2.

Conventions (CLAUDE.md): 2s floor between NSE calls · idempotent INSERT OR
IGNORE · producers RAISE on a real stall (all calls erroring) rather than
writing nothing silently.

Usage:
    python -m sources.fno_pull --backfill --months 6     # one-time deep load
    python -m sources.fno_pull --date 29-05-2026          # single day (debug)
    python -m sources.fno_pull --daily                    # pipeline daily step
    python -m sources.fno_pull --pcr                       # (re)compute rollup
    python -m sources.fno_pull --legacy --start 2019-01-01 --end 2024-07-12 --budget-min 50
"""

import argparse
from datetime import date, timedelta

import pandas as pd

from db import get_db, insert_df, read_sql
from sources import _http

# Each nselib call is paced by the host door (_http.pace("nse"), 2s floor).

# Instrument-type taxonomy in the UDiFF bhavcopy (FinInstrmTp):
#   STO = stock option · IDO = index option · STF = stock future · IDF = index future
OPTION_TYPES = ("STO", "IDO")
FUTURE_TYPES = ("STF", "IDF")
FNO_TYPES = OPTION_TYPES + FUTURE_TYPES


def _iso(val):
    """Coerce an NSE date cell to ISO. UDiFF already ships ISO, but be defensive."""
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        return pd.to_datetime(s).date().isoformat()
    except Exception:
        return None


def _normalize_bhav(df, sid_map):
    """UDiFF frame -> fno_bhav schema. Keeps only F&O instrument rows carrying
    information (oi>0 OR volume>0); coalesces futures' NaN strike/option_type to
    0/'XX' so the UNIQUE composite is deterministic."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]
    df = df[df["FinInstrmTp"].isin(FNO_TYPES)]
    if df.empty:
        return pd.DataFrame()

    oi = pd.to_numeric(df["OpnIntrst"], errors="coerce").fillna(0)
    vol = pd.to_numeric(df["TtlTradgVol"], errors="coerce").fillna(0)
    df = df[(oi > 0) | (vol > 0)]
    if df.empty:
        return pd.DataFrame()

    out = pd.DataFrame({
        "symbol": df["TckrSymb"].astype(str).str.strip(),
        "instrument_type": df["FinInstrmTp"].astype(str).str.strip(),
        "expiry_date": df["XpryDt"].map(_iso),
        "strike": pd.to_numeric(df["StrkPric"], errors="coerce").fillna(0.0),
        "option_type": df["OptnTp"].astype(str).str.strip().replace(
            {"": "XX", "nan": "XX", "None": "XX"}).fillna("XX"),
        "trade_date": df["TradDt"].map(_iso),
        "close": pd.to_numeric(df["ClsPric"], errors="coerce"),
        "settle": pd.to_numeric(df["SttlmPric"], errors="coerce"),
        "underlying_price": pd.to_numeric(df["UndrlygPric"], errors="coerce"),
        "oi": pd.to_numeric(df["OpnIntrst"], errors="coerce").fillna(0).astype("int64"),
        "chg_oi": pd.to_numeric(df["ChngInOpnIntrst"], errors="coerce").fillna(0).astype("int64"),
        "volume": pd.to_numeric(df["TtlTradgVol"], errors="coerce").fillna(0).astype("int64"),
        "num_trades": pd.to_numeric(df["TtlNbOfTxsExctd"], errors="coerce").fillna(0).astype("int64"),
    })
    out["sid"] = out["symbol"].map(sid_map)
    out = out.dropna(subset=["expiry_date", "trade_date"])
    # Column order matches schema (sid first); insert_df is name-agnostic but keep tidy.
    cols = ["sid", "symbol", "instrument_type", "expiry_date", "strike", "option_type",
            "trade_date", "close", "settle", "underlying_price", "oi", "chg_oi",
            "volume", "num_trades"]
    return out[cols]


def pull_fno_bhav(trade_date, sid_map=None):
    """Fetch + persist ONE trading day's F&O grid. `trade_date` is a date or a
    'dd-mm-yyyy' string. Returns rows inserted, or -1 if the NSE call errored
    (vs 0 = a real holiday/empty session) so callers can tell a stall from a
    no-trade day."""
    from nselib import derivatives as dv
    if sid_map is None:
        sid_map = _http.sid_map()  # index underlyings (NIFTY…) → None, stored symbol-keyed
    d_str = trade_date.strftime("%d-%m-%Y") if hasattr(trade_date, "strftime") else str(trade_date)
    try:
        with _http.pace("nse"):
            raw = dv.fno_bhav_copy(trade_date=d_str)
    except Exception:
        # "No data" for non-trading days arrives as an exception too; the caller
        # distinguishes by counting how many calls erred vs. how many were tried.
        return -1
    out = _normalize_bhav(raw, sid_map)
    if out.empty:
        return 0
    return insert_df(out, "fno_bhav")


def _weekdays_back(days):
    """Calendar weekdays from today backwards (most-recent first). Holidays are
    handled downstream — the NSE call simply returns nothing for them."""
    today = date.today()
    out = []
    for delta in range(days):
        d = today - timedelta(days=delta)
        if d.weekday() < 5:  # Mon–Fri
            out.append(d)
    return out


def _existing_trade_dates():
    df = read_sql("SELECT DISTINCT trade_date FROM fno_bhav")
    return set(df["trade_date"].tolist())


def backfill_fno_bhav(months=6):
    """Deep one-time load: walk weekdays back `months`, skip already-loaded
    dates, fetch each. Idempotent. Raises if EVERY attempted NSE call erred
    (endpoint unreachable) — a flat table from a real stall must not pass
    silently (CLAUDE.md)."""
    sid_map = _http.sid_map()
    have = _existing_trade_dates()
    days = _weekdays_back(int(months * 31))
    total, n_ok, n_err, n_skip = 0, 0, 0, 0
    for d in days:
        if d.isoformat() in have:
            n_skip += 1
            continue
        n = pull_fno_bhav(d, sid_map)
        if n == -1:
            n_err += 1
        else:
            n_ok += 1
            total += n
            if n:
                print(f"  fno_bhav {d.isoformat()}: ✅ {n} new rows")
    attempted = n_ok + n_err
    if attempted and n_ok == 0:
        raise RuntimeError(
            f"fno_bhav backfill: all {n_err} NSE calls erred — endpoint unreachable")
    print(f"  backfill done: {total} rows · {n_ok} days loaded · {n_skip} skipped · {n_err} erred")
    return total


# ── Legacy archive (before the UDiFF files this table starts with, 2024-07) ──
# One zip per trading day. Same contracts, older column names, and no underlying
# price: index levels come from nse_index_history (except on expiry day, where an
# option's SETTLE_PR already IS the index settlement, as in UDiFF). CONTRACTS is in
# lots, the same unit as UDiFF TtlTradgVol. Index underlyings only: stock options
# would add ~30M rows the option-selling study (docs/studies/option-premium-
# feasibility-2026-10.md) does not need.
LEGACY_FO_URL = "https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{y}/{mmm}/fo{d:02d}{mmm}{y}bhav.csv.zip"
LEGACY_INDEX = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK",
                "FINNIFTY": "NIFTY FINANCIAL SERVICES", "MIDCPNIFTY": "NIFTY MIDCAP SELECT"}
_LEGACY_TYPES = {"OPTIDX": "IDO", "FUTIDX": "IDF"}


def parse_legacy_fo(content, index_close):
    """A legacy fo…bhav.csv.zip → fno_bhav rows for LEGACY_INDEX underlyings.

    `index_close` = {fno symbol: index close that day}; a symbol without one is
    dropped (no underlying price is better than a wrong one)."""
    import io
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(content))
    df = pd.read_csv(z.open(z.namelist()[0]))
    df.columns = df.columns.str.strip()
    df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
    df["INSTRUMENT"] = df["INSTRUMENT"].astype(str).str.strip()
    df = df[df["INSTRUMENT"].isin(_LEGACY_TYPES) & df["SYMBOL"].isin(index_close)]
    df = df[(df["OPEN_INT"] > 0) | (df["CONTRACTS"] > 0)]
    if df.empty:
        return pd.DataFrame()
    out = pd.DataFrame({
        "sid": None,
        "symbol": df["SYMBOL"],
        "instrument_type": df["INSTRUMENT"].map(_LEGACY_TYPES),
        "expiry_date": pd.to_datetime(df["EXPIRY_DT"].astype(str).str.strip(), format="%d-%b-%Y").dt.date.astype(str),
        "strike": pd.to_numeric(df["STRIKE_PR"], errors="coerce").fillna(0.0),
        "option_type": df["OPTION_TYP"].astype(str).str.strip().replace({"": "XX", "nan": "XX"}),
        "trade_date": pd.to_datetime(df["TIMESTAMP"].astype(str).str.strip().str.title(), format="%d-%b-%Y").dt.date.astype(str),
        "close": pd.to_numeric(df["CLOSE"], errors="coerce"),
        "settle": pd.to_numeric(df["SETTLE_PR"], errors="coerce"),
        "underlying_price": df["SYMBOL"].map(index_close),
        "oi": df["OPEN_INT"].astype("int64"),
        "chg_oi": df["CHG_IN_OI"].astype("int64"),
        "volume": df["CONTRACTS"].astype("int64"),
        "num_trades": None,                         # not in the legacy file
    })
    return out


def backfill_legacy(start, end, budget_min=None):
    """Load the legacy F&O archive for [start, end] (index underlyings only) into
    fno_bhav. Resumable: days that already hold index options are skipped; stops at
    `budget_min`. Loads the index levels it needs into nse_index_history first.
    Returns new rows."""
    import runlog
    from sources.nse import _is_trading_day
    from sources.nselib_pull import backfill_index_history

    backfill_index_history(list(LEGACY_INDEX.values()), start, end)   # skips months it holds
    closes = read_sql("SELECT index_symbol, trade_date, close FROM nse_index_history WHERE index_symbol IN (%s) "
                      "AND trade_date BETWEEN ? AND ?" % ",".join("?" * len(LEGACY_INDEX)),
                      params=list(LEGACY_INDEX.values()) + [start, end])
    by_day = {}
    sym = {v: k for k, v in LEGACY_INDEX.items()}
    for i, d, c in zip(closes.index_symbol, closes.trade_date, closes.close):
        by_day.setdefault(d, {})[sym[i]] = c

    have = set(read_sql("SELECT DISTINCT trade_date FROM fno_bhav WHERE instrument_type = 'IDO' "
                        "AND trade_date BETWEEN ? AND ?", params=[start, end])["trade_date"])
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    todo = [d for d in (s + timedelta(days=i) for i in range((e - s).days + 1))
            if _is_trading_day(d) and d.isoformat() not in have]
    print(f"NSE legacy F&O {start} → {end}: {len(todo)} weekdays not yet loaded ({len(have)} loaded)")
    out_of_time = _http.time_budget("nse_archives", budget_min) if budget_min else (lambda: False)
    total = n_days = n_bad = 0
    for d in todo:
        if out_of_time():
            print(f"  stopped at the {budget_min:.0f}-min budget — rerun to resume")
            break
        if d.isoformat() not in by_day:             # no index level = market holiday (or a gap to report)
            continue
        url = LEGACY_FO_URL.format(y=d.year, mmm=d.strftime("%b").upper(), d=d.day)
        try:
            resp = _http.polite_get(url, timeout=40)
            if resp is None:
                runlog.item_failed("nse_legacy_fo", d.isoformat(), "no file on a day with an index close")
                n_bad += 1
                continue
            df = parse_legacy_fo(resp.content, by_day[d.isoformat()])
        except Exception as ex:                    # noqa: BLE001 — one bad day must not stop the range
            n_bad += 1
            runlog.item_error("nse_legacy_fo", d.isoformat(), ex)
            continue
        if df.empty:
            n_bad += 1
            runlog.item_failed("nse_legacy_fo", d.isoformat(), "0 index contracts in the file")
            continue
        total += insert_df(df, "fno_bhav", lock_retries=5)
        runlog.item_ok()
        n_days += 1
        if n_days % 50 == 0:
            print(f"  {d}: {n_days} days loaded, {total} rows", flush=True)
    print(f"NSE legacy F&O: {n_days} days loaded, {total} new rows, {n_bad} bad days")
    if todo and n_days == 0 and n_bad:
        raise RuntimeError(f"legacy F&O: 0 of {len(todo)} days loaded ({n_bad} bad) — archive moved or blocked?")
    return total


def compute(lookback_days=5):
    """DAILY pipeline producer (PIPELINE_STEPS `fetch_fno_bhav`). Fetches a short
    trailing window of weekdays, idempotently. Self-heals a missed day. Runs in
    the morning pipeline — 'today' hasn't traded yet, so its call no-ops and the
    most recent real session is picked up.

    Raises if every call in the window erred (real NSE stall); a window that is
    fully already-loaded (n_new==0, no errors) is the normal steady state and
    returns 0 quietly."""
    sid_map = _http.sid_map()
    have = _existing_trade_dates()
    total, n_ok, n_err = 0, 0, 0
    for d in _weekdays_back(lookback_days):
        if d.isoformat() in have:
            continue
        n = pull_fno_bhav(d, sid_map)
        if n == -1:
            n_err += 1
        else:
            n_ok += 1
            total += n
            if n:
                print(f"  fno_bhav {d.isoformat()}: ✅ {n} new rows")
    if (n_ok + n_err) and n_ok == 0 and n_err == lookback_days:
        raise RuntimeError(
            f"fno_bhav daily: all {n_err} NSE calls erred over {lookback_days}d — endpoint unreachable")
    return total


# ───────────────────────── PCR / max-pain rollup ─────────────────────────

def _max_pain(strikes_calls_puts):
    """strikes_calls_puts: dict strike -> (call_oi, put_oi). Returns the strike
    minimising total option-writer payout at expiry (the classic max-pain point):

        pain(K) = Σ_c max(K - c, 0)·call_oi(c)  +  Σ_p max(p - K, 0)·put_oi(p)

    None if there are no strikes."""
    if not strikes_calls_puts:
        return None
    strikes = sorted(strikes_calls_puts)
    best_k, best_pain = None, None
    for k in strikes:
        pain = 0.0
        for s, (coi, poi) in strikes_calls_puts.items():
            if s < k:
                pain += (k - s) * coi          # ITM calls writers pay
            elif s > k:
                pain += (s - k) * poi          # ITM puts writers pay
        if best_pain is None or pain < best_pain:
            best_pain, best_k = pain, k
    return best_k


def _rollup_one(g):
    """One underlying's option rows on its nearest expiry -> rollup dict."""
    spot = pd.to_numeric(g["underlying_price"], errors="coerce").dropna()
    spot = float(spot.iloc[0]) if len(spot) else None

    calls = g[g["option_type"] == "CE"]
    puts = g[g["option_type"] == "PE"]
    call_oi, put_oi = int(calls["oi"].sum()), int(puts["oi"].sum())
    call_vol, put_vol = int(calls["volume"].sum()), int(puts["volume"].sum())

    grid = {}
    for _, r in g.iterrows():
        k = float(r["strike"])
        if k <= 0:
            continue
        c, p = grid.get(k, (0, 0))
        if r["option_type"] == "CE":
            c += int(r["oi"])
        elif r["option_type"] == "PE":
            p += int(r["oi"])
        grid[k] = (c, p)
    mp = _max_pain(grid)

    return {
        "underlying_price": spot,
        "total_call_oi": call_oi,
        "total_put_oi": put_oi,
        "pcr_oi": (put_oi / call_oi) if call_oi else None,
        "total_call_vol": call_vol,
        "total_put_vol": put_vol,
        "pcr_volume": (put_vol / call_vol) if call_vol else None,
        "max_pain": mp,
        "max_pain_distance": ((spot - mp) / spot) if (spot and mp) else None,
        "n_strikes": len(grid),
    }


def compute_pcr_for_date(trade_date):
    """Aggregate fno_bhav option rows for one date into fno_pcr_history, per
    underlying, on its NEAREST expiry. INSERT OR REPLACE. Returns rows written."""
    df = read_sql(
        "SELECT sid, symbol, instrument_type, expiry_date, strike, option_type, "
        "       underlying_price, oi, volume "
        "FROM fno_bhav WHERE trade_date = ? AND instrument_type IN ('STO','IDO')",
        params=(trade_date,),
    )
    if df.empty:
        return 0
    rows = []
    for symbol, sym_df in df.groupby("symbol"):
        nearest = sorted(sym_df["expiry_date"].unique())[0]
        g = sym_df[sym_df["expiry_date"] == nearest]
        roll = _rollup_one(g)
        sid_vals = g["sid"].dropna().unique()
        rows.append({
            "sid": sid_vals[0] if len(sid_vals) else None,
            "symbol": symbol,
            "trade_date": trade_date,
            "expiry_date": nearest,
            **roll,
        })
    out = pd.DataFrame(rows)
    cols = ["sid", "symbol", "trade_date", "expiry_date", "underlying_price",
            "total_call_oi", "total_put_oi", "pcr_oi", "total_call_vol",
            "total_put_vol", "pcr_volume", "max_pain", "max_pain_distance", "n_strikes"]
    out = out[cols]
    placeholders = ", ".join(["?"] * len(cols))
    sql = f"INSERT OR REPLACE INTO fno_pcr_history ({', '.join(cols)}) VALUES ({placeholders})"
    with get_db() as conn:
        conn.executemany(sql, out.where(pd.notnull(out), None).values.tolist())
    return len(out)


def compute_pcr(all_missing=True):
    """DAILY pipeline producer (PIPELINE_STEPS `compute_fno_pcr`). Computes the
    PCR/max-pain rollup for every fno_bhav trade_date not yet in fno_pcr_history
    (self-healing across a backfill). Returns total rows written."""
    bhav_dates = set(read_sql("SELECT DISTINCT trade_date FROM fno_bhav")["trade_date"])
    done_dates = set(read_sql("SELECT DISTINCT trade_date FROM fno_pcr_history")["trade_date"])
    todo = sorted(bhav_dates - done_dates) if all_missing else sorted(bhav_dates)
    total = 0
    for d in todo:
        n = compute_pcr_for_date(d)
        total += n
        if n:
            print(f"  fno_pcr {d}: ✅ {n} underlyings")
    return total


# ───────────────────────── Driver ─────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="deep one-time load")
    ap.add_argument("--months", type=int, default=6, help="backfill depth")
    ap.add_argument("--date", type=str, help="single day dd-mm-yyyy (debug)")
    ap.add_argument("--daily", action="store_true", help="daily trailing-window fetch")
    ap.add_argument("--pcr", action="store_true", help="(re)compute PCR rollup for missing dates")
    ap.add_argument("--legacy", action="store_true", help="legacy archive, index underlyings, --start/--end")
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2024-07-12", help="last day before the UDiFF files (2024-07-15)")
    ap.add_argument("--budget-min", type=float, help="stop after this many minutes (resumable)")
    args = ap.parse_args()

    if args.legacy:
        backfill_legacy(args.start, args.end, args.budget_min)

    if args.date:
        n = pull_fno_bhav(args.date)
        print(f"  fno_bhav {args.date}: {n} rows")
    if args.backfill:
        print(f"\n=== F&O bhavcopy backfill ({args.months} months) ===")
        backfill_fno_bhav(months=args.months)
    if args.daily:
        print("\n=== F&O bhavcopy daily ===")
        n = compute()
        print(f"  → {n} new fno_bhav rows")
    if args.pcr or args.backfill or args.daily:
        print("\n=== F&O PCR / max-pain rollup ===")
        n = compute_pcr()
        print(f"  → {n} fno_pcr_history rows")


if __name__ == "__main__":
    main()
