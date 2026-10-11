"""
Alpha Signal v2 — Kite minute-bar archive (ADR 0072; Kite dataset ① of 2026-10-11).

Every universe stock's 1-minute bars since 2015 into Parquet — four columns: sid, ts,
close, volume — with one manifest row per file in `intraday_files`. The factors read a
daily summary built from these files, never Kite directly.

Kite facts that shape it (probed 2026-10-11):
  • minute history goes back to 2015 for listed stocks; one request covers at most 60 days,
    so a stock is ~72 requests, newest first, stopping where the stock had not yet listed
  • prices AND volumes are split/bonus-adjusted as of the fetch day (KOTAKBANK's raw close
    of 2133.3 on 2026-01-12 is 426.7 on Kite after its 1:5 split). Ratios inside a day do not
    care; price levels are on the basis of `fetched_on` in the manifest
  • listed stocks only: nothing built on this sees delisted names (survivors-only)
  • it needs that day's Kite login, done by hand: no login = nothing to do, not a failure

Layout under config.INTRADAY_DIR / "bars_1m":
    _staging/sid=<SID>.parquet     the backfill: one file per stock, all of its history
    month=YYYY-MM/part-0.parquet   after compaction (all stocks, sorted by sid, ts) — later

Usage:
    python -m sources.kite_bars --smoke RELI,COFO,IFBI    # 3 stocks by sid, end to end
    python -m sources.kite_bars --backfill [--until 23:50] [--budget-min N]
    python -m sources.kite_bars --status
    python -m sources.kite_bars --has-session             # exit 0 when today's login works
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import runlog
from config import INTRADAY_DIR
from db import get_db, read_sql
from sources import _http
from sources.kite_pull import NoKiteSession, kite

LABEL = "kite_bars"
DATASET = "bars_1m"
ROOT = INTRADAY_DIR / DATASET
STAGING = ROOT / "_staging"
IST = ZoneInfo("Asia/Kolkata")
START = date(2015, 1, 1)        # Kite's minute depth (nothing in 2013-14 for any of the probe stocks)
CHUNK_DAYS = 60                 # Kite's limit per minute request
EMPTY_STOP = 2                  # this many empty chunks in a row = the stock had not listed yet
RETRIES = 3                     # per chunk, each retry is another paced call (no sleeps)
SESSION_OPEN, SESSION_CLOSE = dtime(9, 0), dtime(20, 0)   # IST; muhurat sessions run in the evening
MAX_BARS_PER_DAY = 400          # 375 in a normal session

SCHEMA = pa.schema([("sid", pa.string()), ("ts", pa.timestamp("s", tz="UTC")),
                    ("close", pa.int32()),          # paise
                    ("volume", pa.int64())])


# ─────────────────────────── contract ───────────────────────────

def validate(df):
    """The write contract (ADR 0072): reject the stock's file rather than store a bad bar."""
    if df.empty:
        return
    local = df["ts"].dt.tz_convert(IST)
    tod = local.dt.time
    problems = []
    if df["ts"].duplicated().any():
        problems.append(f"{int(df['ts'].duplicated().sum())} duplicate minutes")
    if ((tod < SESSION_OPEN) | (tod >= SESSION_CLOSE)).any():
        problems.append(f"{int(((tod < SESSION_OPEN) | (tod >= SESSION_CLOSE)).sum())} bars outside 09:00-20:00 IST")
    if (df["close"] <= 0).any():
        problems.append(f"{int((df['close'] <= 0).sum())} non-positive closes")
    if (df["volume"] < 0).any():
        problems.append(f"{int((df['volume'] < 0).sum())} negative volumes")
    per_day = local.dt.date.value_counts()
    if (per_day > MAX_BARS_PER_DAY).any():
        problems.append(f"{int((per_day > MAX_BARS_PER_DAY).sum())} days over {MAX_BARS_PER_DAY} bars")
    if problems:
        raise ValueError("contract: " + "; ".join(problems))


def to_frame(sid, bars):
    """Kite candles → the archive's four columns (close in paise, ts in UTC)."""
    if not bars:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in
                             (("sid", "object"), ("ts", "datetime64[s, UTC]"), ("close", "int32"), ("volume", "int64"))})
    df = pd.DataFrame(bars)
    # Kite's 2015 history has placeholder bars before a session's first trade: close 0 AND
    # volume 0 (COFORGE 2015-05-18 09:15). No trade, no information: dropped here. A zero close
    # WITH volume is still a contract failure.
    df = df[~((df["close"] <= 0) & (df["volume"] == 0))]
    # 2015 also has a few bars stamped off the minute (11:54:38). Keyed by their minute, but
    # dropped when that minute already has a regular bar (one was an exact copy of it).
    ts = pd.to_datetime(df["date"]).dt.tz_convert("UTC")
    minute = ts.dt.floor("min")
    stray = (ts != minute) & minute.isin(set(minute[ts == minute]))
    df, minute = df[~stray], minute[~stray]
    out = pd.DataFrame({
        "sid": sid,
        "ts": minute.astype("datetime64[s, UTC]"),
        "close": (df["close"] * 100).round().astype("int32"),
        "volume": df["volume"].astype("int64"),
    })
    return out.sort_values("ts").reset_index(drop=True)


# ─────────────────────────── files + manifest ───────────────────────────

def write_parquet(df, path):
    """Atomic: a crash leaves the old file or no file, never half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    table = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
    pq.write_table(table, tmp, compression="zstd", compression_level=9, use_dictionary=["sid"],
                   column_encoding={c: "DELTA_BINARY_PACKED" for c in ("ts", "close", "volume")})
    os.replace(tmp, path)
    return path.stat().st_size


def record(kind, key, df, path, nbytes, note=None):
    ts = df["ts"] if not df.empty else None
    with get_db() as conn:
        conn.execute(
            """INSERT INTO intraday_files (dataset, kind, key, path, n_rows, n_days, first_ts, last_ts,
                                           bytes, fetched_on, note, written_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?, datetime('now'))
               ON CONFLICT(dataset, kind, key) DO UPDATE SET
                   path=excluded.path, n_rows=excluded.n_rows, n_days=excluded.n_days,
                   first_ts=excluded.first_ts, last_ts=excluded.last_ts, bytes=excluded.bytes,
                   fetched_on=excluded.fetched_on, note=excluded.note, written_at=excluded.written_at""",
            (DATASET, kind, key, str(path) if path else None, len(df),
             int(ts.dt.tz_convert(IST).dt.date.nunique()) if ts is not None else 0,
             ts.min().isoformat() if ts is not None else None, ts.max().isoformat() if ts is not None else None,
             nbytes, date.today().isoformat(), note))


def done_sids():
    return set(read_sql("SELECT key FROM intraday_files WHERE dataset = ? AND kind = 'staging'",
                        params=[DATASET])["key"])


# ─────────────────────────── fetch ───────────────────────────

def instrument_tokens(kc):
    """sid → NSE equity token, matched on the universe ticker (series suffixes as a fallback)."""
    with _http.pace("kite"):
        inst = pd.DataFrame(kc.instruments("NSE"))
    eq = inst[inst["instrument_type"] == "EQ"]
    by_symbol = dict(zip(eq["tradingsymbol"], eq["instrument_token"]))
    uni = read_sql("SELECT sid, ticker, cap_tier, market_cap_cr FROM stocks WHERE ticker IS NOT NULL "
                   "ORDER BY market_cap_cr IS NULL, market_cap_cr DESC")
    out = []
    for r in uni.itertuples():
        tok = next((by_symbol[s] for s in (r.ticker, f"{r.ticker}-BE", f"{r.ticker}-BZ") if s in by_symbol), None)
        out.append((r.sid, r.ticker, r.cap_tier, int(tok) if tok is not None else None))
    return out


def _chunk(kc, token, lo, hi):
    for attempt in range(1, RETRIES + 1):
        try:
            with _http.pace("kite"):
                return kc.historical_data(token, f"{lo} 09:00:00", f"{hi} 23:59:59", "minute")
        except Exception as e:                      # noqa: BLE001 — classified below
            name = type(e).__name__
            if name == "TokenException":
                raise NoKiteSession(f"Kite session ended: {e}") from e
            if name == "InputException" or attempt == RETRIES:
                raise
            print(f"    retry {attempt}/{RETRIES - 1} {lo}..{hi}: {name}: {e}", flush=True)


def fetch_stock(kc, sid, token, end=None):
    """All of a stock's minute bars, newest chunk first, until it had not listed yet."""
    end = end or date.today()
    frames, empty, hi = [], 0, end
    while hi >= START:
        lo = max(START, hi - timedelta(days=CHUNK_DAYS - 1))
        bars = _chunk(kc, token, lo, hi)
        if bars:
            frames.append(to_frame(sid, bars))
            empty = 0
        else:
            empty += 1
            if empty >= EMPTY_STOP:
                break
        hi = lo - timedelta(days=1)
    if not frames:
        return to_frame(sid, [])
    df = pd.concat(frames, ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    return df


def harvest(sids=None, until=None, budget_min=None):
    """Backfill each stock not yet in the manifest, largest first. Returns (ok, errors, rows)."""
    kc = kite(cached_only=True)
    universe = instrument_tokens(kc)
    have = done_sids()
    todo = [u for u in universe if (sids is None or u[0] in sids) and (sids is not None or u[0] not in have)]
    deadline = None
    if until:
        h, m = map(int, until.split(":"))
        deadline = datetime.combine(date.today(), dtime(h, m))
    if budget_min:
        b = datetime.now() + timedelta(minutes=budget_min)
        deadline = min(deadline, b) if deadline else b
    print(f"{LABEL}: {len(todo)} stocks to fetch ({len(have)} already done of {len(universe)})"
          + (f", stopping new stocks at {deadline:%H:%M}" if deadline else ""), flush=True)
    if not todo:
        print(f"{LABEL}: nothing left to fetch", flush=True)
        return 0, 0, 0
    ok = err = rows = 0
    for i, (sid, ticker, tier, token) in enumerate(todo, 1):
        if deadline and datetime.now() >= deadline:
            print(f"{LABEL}: deadline reached after {i - 1} stocks", flush=True)
            break
        if token is None:
            err += 1
            runlog.item_failed(LABEL, sid, f"{ticker}: no NSE equity instrument on Kite", symptom="F")
            continue
        try:
            df = fetch_stock(kc, sid, token)
            validate(df)
        except NoKiteSession:
            print(f"{LABEL}: Kite session ended after {i - 1} stocks — resumes after the next login", flush=True)
            break
        except Exception as e:                      # noqa: BLE001 — one stock never stops the run
            err += 1
            runlog.item_error(LABEL, sid, e)
            print(f"  {sid} {ticker}: {type(e).__name__}: {e}", flush=True)
            continue
        if df.empty:
            record("staging", sid, df, None, 0, note="no minute bars on Kite (suspended or illiquid)")
        else:
            path = STAGING / f"sid={sid}.parquet"
            record("staging", sid, df, path, write_parquet(df, path))
            ok += 1
            rows += len(df)
            runlog.item_ok()
        if i % 10 == 0 or i == len(todo):
            print(f"  [{i}/{len(todo)}] {sid} {ticker} {tier}: {len(df):,} bars "
                  f"from {df['ts'].min():%Y-%m-%d}" if not df.empty else f"  [{i}/{len(todo)}] {sid}: none", flush=True)
    runlog.harvest_summary(LABEL, min(i, len(todo)), ok, err, rows)
    if ok == 0 and err > 0:
        raise RuntimeError(f"{LABEL}: {err} stocks failed and none was written")
    return ok, err, rows


def status():
    df = read_sql("SELECT COUNT(*) AS stocks, SUM(n_rows) AS bars, SUM(bytes) AS bytes, MIN(first_ts) AS first, "
                  "MAX(last_ts) AS last, SUM(path IS NULL) AS empty FROM intraday_files WHERE dataset = ? "
                  "AND kind = 'staging'", params=[DATASET])
    r = df.iloc[0]
    total = int(read_sql("SELECT COUNT(*) AS n FROM stocks WHERE ticker IS NOT NULL")["n"][0])
    print(f"{DATASET}: {int(r['stocks'] or 0)}/{total} stocks done ({int(r['empty'] or 0)} with no bars) · "
          f"{int(r['bars'] or 0):,} bars · {(r['bytes'] or 0) / 2**20:,.0f} MB · {r['first']} → {r['last']}")


def has_session():
    try:
        kc = kite(cached_only=True)
        with _http.pace("kite"):
            kc.profile()
        return True
    except Exception as e:                          # noqa: BLE001
        print(f"no Kite session: {type(e).__name__}: {e}")
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--smoke", help="comma-separated sids: fetch them end to end (rewrites their files)")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--until", help="HH:MM (VM time, UTC): start no new stock after this")
    ap.add_argument("--budget-min", type=int)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--has-session", action="store_true")
    a = ap.parse_args()
    if a.has_session:
        sys.exit(0 if has_session() else 1)
    if a.status:
        return status()
    if a.smoke:
        harvest(sids=set(a.smoke.split(",")))
        return status()
    if a.backfill:
        harvest(until=a.until, budget_min=a.budget_min)
        return status()
    ap.print_help()


if __name__ == "__main__":
    main()
