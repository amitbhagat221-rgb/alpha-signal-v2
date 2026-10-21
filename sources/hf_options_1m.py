"""
Alpha Signal v2 — one-off ingest of free 1-minute index-option bars (Amit 2026-10-21).

Source: the public Hugging Face dataset `thetrademarkk/india-index-options-1m`
(mirror `codepyx23/india-index-options-1m`), licence CC BY-NC 4.0 — research use only, never
redistributed or used commercially. One Parquet file per expiry with every strike's 1-minute
OHLC for the ~6-9 sessions before it, plus a 1-minute spot file per index. NIFTY and SENSEX only.

Source facts that shape it (probe 2026-10-20, smoke 2026-10-21):
  • timestamps are tz-aware IST; option bars 09:15-15:30, the index has a 09:07 pre-open bar
  • 2021-2023 files store every row twice → exact duplicates dropped
  • 2025+ files carry zero-volume snapshot bars stamped after 15:30 (15:40, 15:44) → dropped;
    a handful of traded bars stamped 09:14 or 15:31-15:41 → dropped and counted (> 1 % = rejected);
    all-zero placeholder bars (2024-05-18 Saturday session) → dropped. A Diwali muhurat day
    (first bar ≥ 17:00) keeps its evening session (17:00-20:00 that day only)
  • `volume` is in units: ÷ the lot size = contracts (option_book.lot_size; checked per day
    against fno_bhav's contract count, which overrides the table when it clearly says another lot)
  • `open_interest` is broken from 2025 (65 % zeros, the rest ~1 % of true) → not kept; OI is fno_bhav's
  • NSE's official option close is the 15:00-15:30 VWAP: each file is checked against fno_bhav
    (match = |VWAP − close| ≤ max(2 %, ₹0.10)); a file under 90 % is kept but marked suspect.
    SENSEX expiry days are left out of the check (fno_bhav's SENSEX expiry-day rows are broken).

Downloads are untrusted: each goes to a staging file, its size and sha256 must equal the HF
listing's LFS hash, and it is read with pyarrow only after its schema and row count pass.

Layout under config.INTRADAY_DIR / "options_1m" (INTRADAY_DIR follows ALPHA_DB / ALPHA_INTRADAY):
    {SYMBOL}/{EXPIRY}.parquet    ts (IST), trading_day, symbol, expiry, strike, option_type,
                                 open, high, low, close (₹), volume_contracts
    index/{SYMBOL}.parquet       ts (IST), trading_day, symbol, open, high, low, close
Manifest: `intraday_files` dataset 'options_1m', kind 'expiry' (key SYMBOL/EXPIRY) | 'index' (key SYMBOL);
the note holds the source sha256 (re-runs skip a file whose hash is unchanged) and the check result.

Usage:
    python -m sources.hf_options_1m --smoke NIFTY/2022-06-23,NIFTY/2025-07-03,SENSEX/2025-06-10
    python -m sources.hf_options_1m --backfill [--symbols NIFTY,SENSEX]
    python -m sources.hf_options_1m --status
Read: pd.read_parquet(config.INTRADAY_DIR / "options_1m" / "NIFTY" / "2025-07-03.parquet")  (or load())
"""

from __future__ import annotations

import argparse
import hashlib
import os
from datetime import date, time as dtime

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import runlog
from config import INTRADAY_DIR
from db import get_db, read_sql
from option_book import LOT_SIZES, lot_size
from sources import _http

LABEL = "hf_options_1m"
DATASET = "options_1m"
ROOT = INTRADAY_DIR / DATASET
DOWNLOAD = ROOT / "_download"
REPOS = ("thetrademarkk/india-index-options-1m", "codepyx23/india-index-options-1m")   # primary, mirror
TREE_URL = "https://huggingface.co/api/datasets/{repo}/tree/main/{path}"
FILE_URL = "https://huggingface.co/datasets/{repo}/resolve/main/{path}"
SYMBOLS = ("NIFTY", "SENSEX")
IST = "Asia/Kolkata"
OPT_OPEN, IDX_OPEN, CLOSE = dtime(9, 15), dtime(9, 0), dtime(15, 30)
MUHURAT_OPEN, MUHURAT_CLOSE = dtime(17, 0), dtime(20, 0)   # Diwali evening session: a day whose first bar is ≥ 17:00
VWAP_FROM, VWAP_TO = 15 * 60, 15 * 60 + 29   # minute of day: bars stamped 15:00 … 15:29 cover 15:00-15:30
MATCH_PCT, MATCH_RS, SUSPECT_BELOW = 0.02, 0.10, 0.90
STUB_BELOW = 1_000      # traded bars: a real expiry file has ~100 k; below this it is an upstream stub (kept, labelled)
STRAY_MAX = 0.01                        # share of rows that may trade outside the session (dropped)
MAX_SRC_ROWS = 5_000_000                # largest real file ~1.2 M rows (duplicated years)
RETRIES = 3                             # whole-file download attempts per repo (each one paced by the door)

SRC_COLUMNS = {   # column → pyarrow type test; the source schema must carry exactly these kinds
    "options": {"timestamp": "ts", "open": "float", "high": "float", "low": "float", "close": "float",
                "volume": "int", "open_interest": "int", "trading_day": "str", "symbol": "str",
                "strike": "int", "option_type": "str", "expiry": "str"},
    "index": {"timestamp": "ts", "open": "float", "high": "float", "low": "float", "close": "float",
              "volume": "int", "trading_day": "str", "symbol": "str"},
}
OPT_SCHEMA = pa.schema([("ts", pa.timestamp("s", tz=IST)), ("trading_day", pa.date32()),
                        ("symbol", pa.string()), ("expiry", pa.date32()), ("strike", pa.int32()),
                        ("option_type", pa.string()), ("open", pa.float64()), ("high", pa.float64()),
                        ("low", pa.float64()), ("close", pa.float64()), ("volume_contracts", pa.float64())])
IDX_SCHEMA = pa.schema([("ts", pa.timestamp("s", tz=IST)), ("trading_day", pa.date32()), ("symbol", pa.string()),
                        ("open", pa.float64()), ("high", pa.float64()), ("low", pa.float64()), ("close", pa.float64())])


# ─────────────────────────── source schema (untrusted file) ───────────────────────────

def _kind_ok(t, want):
    if want == "ts":
        return pa.types.is_timestamp(t) and t.tz in ("+05:30", IST)
    if want == "float":
        return pa.types.is_floating(t)
    if want == "int":
        return pa.types.is_integer(t)
    return pa.types.is_string(t) or pa.types.is_large_string(t)


def check_schema(schema, kind):
    """Reject a file whose columns or types are not the documented ones (before reading its rows)."""
    want = SRC_COLUMNS[kind]
    have = {f.name: f.type for f in schema}
    problems = [f"missing {c}" for c in want if c not in have]
    problems += [f"{c} is {have[c]}, want {k}" for c, k in want.items() if c in have and not _kind_ok(have[c], k)]
    if problems:
        raise ValueError("schema: " + "; ".join(problems))


def read_source(path, kind):
    """pyarrow only — never anything that could execute. Schema and size first, then the rows."""
    pf = pq.ParquetFile(path)
    check_schema(pf.schema_arrow, kind)
    if pf.metadata.num_rows > MAX_SRC_ROWS:
        raise ValueError(f"schema: {pf.metadata.num_rows:,} rows > {MAX_SRC_ROWS:,}")
    return pf.read(columns=list(SRC_COLUMNS[kind])).to_pandas()


# ─────────────────────────── normalise + contract ───────────────────────────

def _prep(raw, symbol, open_time):
    """Shared cleaning, each counted in `stats` (→ the manifest note):
      dup_rows      exact duplicate rows (2021-2023 files store every row twice)
      zero_rows     all-zero OHLC with no volume (placeholders, e.g. the 2024-05-18 Saturday session)
      late_rows     no-trade snapshots outside the session (2025+: LTP copies stamped 15:40-15:46)
      stray_rows    bars WITH volume outside the session (a 09:14 or 15:31-15:41 stamp; a few per file)
    A Diwali muhurat day (first bar >= 17:00) keeps its evening session instead. More than
    STRAY_MAX of a file's rows traded outside the session = a stamping bug -> the file is rejected."""
    if (raw["symbol"] != symbol).any():
        raise ValueError(f"contract: symbol {sorted(set(raw['symbol']) - {symbol})[:3]} in a {symbol} file")
    df = raw.drop(columns=[c for c in ("open_interest",) if c in raw])
    n0 = len(df)
    df = df.drop_duplicates()
    stats = {"dup_rows": n0 - len(df)}
    zero = (df[["open", "high", "low", "close"]] == 0).all(axis=1) & (df["volume"] == 0)
    stats["zero_rows"] = int(zero.sum())
    df = df[~zero]
    ts = df["timestamp"].dt.tz_convert(IST)
    tod = ts.dt.time
    muhurat = tod.groupby(ts.dt.date).transform("min") >= MUHURAT_OPEN    # 2021-11-04, 2022-10-24, …
    outside = pd.Series(np.where(muhurat, (tod < MUHURAT_OPEN) | (tod > MUHURAT_CLOSE),
                                 (tod < open_time) | (tod > CLOSE)), index=df.index)
    traded = df["volume"] != 0
    stats["late_rows"] = int((outside & ~traded).sum())
    stats["stray_rows"] = int((outside & traded).sum())
    stats["muhurat_days"] = int(ts[muhurat].dt.date.nunique())
    if stats["stray_rows"] > STRAY_MAX * max(len(df), 1):
        raise ValueError(f"contract: {stats['stray_rows']} traded bars outside "
                         f"{open_time:%H:%M}-15:30 IST (> {STRAY_MAX:.0%} of the file)")
    df, ts, muhurat = df[~outside], ts[~outside], muhurat[~outside]
    if (ts != ts.dt.floor("min")).any():
        raise ValueError(f"contract: {int((ts != ts.dt.floor('min')).sum())} bars off the minute")
    df = df.assign(ts=ts.dt.floor("s").astype(f"datetime64[s, {IST}]"), _muhurat=muhurat)
    td = pd.to_datetime(df["trading_day"], format="%Y-%m-%d", errors="coerce")
    if td.isna().any() or (td.dt.date != df["ts"].dt.date).any():
        raise ValueError("contract: trading_day differs from the bar's IST date")
    return df.assign(trading_day=td.dt.date), stats


def _ohlc_problems(df, open_time):
    tod = df["ts"].dt.time
    p = []
    regular = ~df["_muhurat"] & ((tod < open_time) | (tod > CLOSE))
    evening = df["_muhurat"] & ((tod < MUHURAT_OPEN) | (tod > MUHURAT_CLOSE))
    if (regular | evening).any():
        p.append(f"{int((regular | evening).sum())} bars outside {open_time:%H:%M}-15:30 IST "
                 "(muhurat days 17:00-20:00)")
    px = df[["open", "high", "low", "close"]]
    if px.isna().any().any() or (px <= 0).any().any():
        p.append("missing or non-positive prices")
    if ((df["high"] < px.max(axis=1) - 1e-9) | (df["low"] > px.min(axis=1) + 1e-9)).any():
        p.append("high/low outside open/close")
    return p


def normalise_options(raw, symbol, expiry, lots=None):
    """HF expiry file → archive frame + stats. `lots` {trading_day: lot} overrides lot_size()."""
    df, stats = _prep(raw, symbol, OPT_OPEN)
    exp = pd.to_datetime(df["expiry"], format="%Y-%m-%d", errors="coerce").dt.date
    problems = []
    if exp.isna().any() or (exp != date.fromisoformat(expiry)).any():
        problems.append(f"expiry column differs from the file's {expiry}")
    if not df["option_type"].isin(["CE", "PE"]).all():
        problems.append("option_type outside CE/PE")
    if (df["strike"] <= 0).any():
        problems.append("non-positive strike")
    if (df["volume"] < 0).any():
        problems.append("negative volume")
    if (df["trading_day"] > date.fromisoformat(expiry)).any():
        problems.append("bars after expiry")
    if df.duplicated(["ts", "strike", "option_type"]).any():
        problems.append(f"{int(df.duplicated(['ts', 'strike', 'option_type']).sum())} conflicting duplicate minutes")
    problems += _ohlc_problems(df, OPT_OPEN)
    if problems:
        raise ValueError("contract: " + "; ".join(problems))
    lots = lots or {}
    by_day = {d: lots.get(d) or lot_size(symbol, d.isoformat()) for d in df["trading_day"].unique()}
    lot = df["trading_day"].map(by_day).astype("int64")
    stats["offlot_bars"] = float((df["volume"] % lot != 0).mean()) if len(df) else 0.0
    stats["lots"] = sorted(set(lot))
    out = pd.DataFrame({
        "ts": df["ts"], "trading_day": df["trading_day"], "symbol": symbol,
        "expiry": date.fromisoformat(expiry), "strike": df["strike"].astype("int32"),
        "option_type": df["option_type"], "open": df["open"].astype(float), "high": df["high"].astype(float),
        "low": df["low"].astype(float), "close": df["close"].astype(float),
        "volume_contracts": df["volume"] / lot,
    })
    return out.sort_values(["strike", "option_type", "ts"]).reset_index(drop=True), stats


def normalise_index(raw, symbol):
    df, stats = _prep(raw, symbol, IDX_OPEN)
    problems = _ohlc_problems(df, IDX_OPEN)
    if df.duplicated("ts").any():
        problems.append(f"{int(df.duplicated('ts').sum())} conflicting duplicate minutes")
    if problems:
        raise ValueError("contract: " + "; ".join(problems))
    stats["nonzero_volume_bars"] = int((df["volume"] != 0).sum())   # always 0 in the source: not kept
    out = df[["ts", "trading_day", "symbol", "open", "high", "low", "close"]]
    return out.sort_values("ts").reset_index(drop=True), stats


# ─────────────────────────── check against fno_bhav ───────────────────────────

def bhav_rows(symbol, expiry):
    return read_sql("SELECT trade_date, strike, option_type, close, volume FROM fno_bhav WHERE symbol = ? "
                    "AND instrument_type = 'IDO' AND expiry_date = ?", params=[symbol, expiry])


def _iso_days(df):
    return df["trading_day"].map({d: d.isoformat() for d in df["trading_day"].unique()})


def _checked_days(bhav, symbol, expiry, df):
    """File days fno_bhav has the expiry for (minus SENSEX expiry days)."""
    days = set(bhav["trade_date"]) & set(_iso_days(df))
    if symbol == "SENSEX":
        days.discard(expiry)        # fno_bhav's SENSEX expiry-day rows are broken (being fixed elsewhere)
    return days


def infer_lots(df, bhav, symbol, expiry):
    """{day: lot} where fno_bhav's contract count clearly says another of the symbol's known lots."""
    known = {n for _, n in LOT_SIZES[symbol]}
    out = {}
    for d, ratio in _volume_ratios(df, bhav, symbol, expiry).items():
        if abs(ratio - 1) <= 0.03:
            continue
        current = lot_size(symbol, d)
        for n in known:
            if n != current and abs(ratio * current / n - 1) <= 0.03:
                out[date.fromisoformat(d)] = n
    return out


def _volume_ratios(df, bhav, symbol, expiry):
    """Per day: median over contracts of (minute contracts summed) / fno_bhav contracts."""
    days = _checked_days(bhav, symbol, expiry, df)
    if not days:
        return {}
    v = df.assign(day=_iso_days(df))
    v = v[v["day"].isin(days)].groupby(["day", "strike", "option_type"])["volume_contracts"].sum().reset_index()
    b = bhav[bhav["volume"] > 0].assign(strike=lambda x: x["strike"].round().astype("int64"))
    m = v.merge(b, left_on=["day", "strike", "option_type"], right_on=["trade_date", "strike", "option_type"])
    m = m[m["volume_contracts"] > 0]
    return (m["volume_contracts"] / m["volume"]).groupby(m["day"]).median().to_dict()


def vwap_check(df, bhav, symbol, expiry):
    """fno_bhav close (NSE: 15:00-15:30 VWAP) vs the file's bars → {n, match, vol_ratio, days}."""
    days = _checked_days(bhav, symbol, expiry, df)
    res = {"n": 0, "match": None, "vol_ratio": None, "days": len(days)}
    if not days:
        return res
    minute = df["ts"].dt.hour * 60 + df["ts"].dt.minute
    w = df[(minute >= VWAP_FROM) & (minute <= VWAP_TO) & (df["volume_contracts"] > 0)]
    w = w.assign(day=_iso_days(w))
    w = w[w["day"].isin(days)]
    tp = (w["high"] + w["low"] + w["close"]) / 3
    g = (w.assign(pv=tp * w["volume_contracts"]).groupby(["day", "strike", "option_type"])[["pv", "volume_contracts"]]
         .sum().reset_index())
    g["vwap"] = g["pv"] / g["volume_contracts"]
    b = bhav[bhav["close"] > 0].assign(strike=lambda x: x["strike"].round().astype("int64"))
    m = g.merge(b, left_on=["day", "strike", "option_type"], right_on=["trade_date", "strike", "option_type"])
    if m.empty:
        return res
    ok = (m["vwap"] - m["close"]).abs() <= np.maximum(MATCH_PCT * m["close"], MATCH_RS + 1e-9)
    ratios = _volume_ratios(df, bhav, symbol, expiry)
    res.update(n=len(m), match=float(ok.mean()), vol_ratio=float(np.median(list(ratios.values()))) if ratios else None)
    return res


# ─────────────────────────── files + manifest ───────────────────────────

def write_parquet(df, path, schema):
    """Atomic: a crash leaves the old file or no file, never half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    dict_cols = [c for c in ("symbol", "option_type") if c in schema.names]
    enc = {c: ("BYTE_STREAM_SPLIT" if pa.types.is_floating(schema.field(c).type) else "DELTA_BINARY_PACKED")
           for c in schema.names if c not in dict_cols}
    pq.write_table(table, tmp, compression="zstd", compression_level=9, use_dictionary=dict_cols,
                   column_encoding=enc)
    os.replace(tmp, path)
    return path.stat().st_size


def record(kind, key, df, path, nbytes, note):
    ts = df["ts"].dt.tz_convert("UTC")
    with get_db() as conn:
        conn.execute(
            """INSERT INTO intraday_files (dataset, kind, key, path, n_rows, n_days, first_ts, last_ts,
                                           bytes, fetched_on, note, written_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?, datetime('now'))
               ON CONFLICT(dataset, kind, key) DO UPDATE SET
                   path=excluded.path, n_rows=excluded.n_rows, n_days=excluded.n_days,
                   first_ts=excluded.first_ts, last_ts=excluded.last_ts, bytes=excluded.bytes,
                   fetched_on=excluded.fetched_on, note=excluded.note, written_at=excluded.written_at""",
            (DATASET, kind, key, str(path), len(df), int(df["trading_day"].nunique()),
             ts.min().isoformat(), ts.max().isoformat(), nbytes, date.today().isoformat(), note))


def parse_note(note):
    return dict(p.split("=", 1) for p in (note or "").split("; ") if "=" in p)


def manifest():
    m = read_sql("SELECT kind, key, path, n_rows, n_days, bytes, note FROM intraday_files WHERE dataset = ?",
                 params=[DATASET])
    return {(r.kind, r.key): r for r in m.itertuples()}


def load(symbol, expiry=None):
    """The archive's frame for one expiry (or the index spot file when expiry is None)."""
    path = ROOT / "index" / f"{symbol}.parquet" if expiry is None else ROOT / symbol / f"{expiry}.parquet"
    return pd.read_parquet(path)


# ─────────────────────────── fetch (through the door) ───────────────────────────

def list_files(path, repo=REPOS[0]):
    """[{path, size, sha256}] under `path` of the dataset (follows the API's Link pagination)."""
    url, out = TREE_URL.format(repo=repo, path=path), []
    while url:
        resp = _http.polite_get(url, timeout=30)
        if resp is None:
            raise RuntimeError(f"{LABEL}: {url} not found")
        for e in resp.json():
            if e.get("type") == "file" and e["path"].endswith(".parquet"):
                lfs = e.get("lfs") or {}
                out.append({"path": e["path"], "size": int(lfs.get("size") or e["size"]), "sha256": lfs.get("oid")})
        url = resp.links.get("next", {}).get("url")
    if not out:
        raise RuntimeError(f"{LABEL}: no parquet files listed under {path}")
    return out


def download(entry, dest):
    """Stream `entry` to `dest` (staging), checking size + sha256 against the listing. Mirror on failure."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for repo in REPOS:
        for _attempt in range(RETRIES):
            h, n = hashlib.sha256(), 0
            try:
                resp = _http.polite_get(FILE_URL.format(repo=repo, path=entry["path"]), stream=True, timeout=60)
                if resp is None:
                    last = FileNotFoundError(f"{repo}/{entry['path']}: 404")
                    break
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(1 << 20):
                        n += len(chunk)
                        if n > entry["size"]:
                            raise ValueError(f"download larger than the listed {entry['size']:,} B")
                        h.update(chunk)
                        f.write(chunk)
            except (OSError, ValueError, *_http._REQ_ERRORS) as e:   # noqa: SLF001 — the door's error set
                last = e
                continue
            if n == entry["size"] and (entry["sha256"] is None or h.hexdigest() == entry["sha256"]):
                return repo, h.hexdigest()
            last = ValueError(f"{repo}/{entry['path']}: {n:,} B sha256 {h.hexdigest()[:12]} ≠ listing "
                              f"{entry['size']:,} B {str(entry['sha256'])[:12]}")
    dest.unlink(missing_ok=True)
    raise last


# ─────────────────────────── one file ───────────────────────────

def _done(have, kind, key, entry):
    r = have.get((kind, key))
    return (r is not None and r.path and os.path.exists(r.path)
            and parse_note(r.note).get("src_sha256") == entry["sha256"])


def ingest_expiry(entry, symbol, have, force=False):
    """Download → validate → normalise → check vs fno_bhav → write → manifest. None if already done."""
    expiry = os.path.basename(entry["path"]).removesuffix(".parquet")
    date.fromisoformat(expiry)
    key = f"{symbol}/{expiry}"
    if not force and _done(have, "expiry", key, entry):
        return None
    staged = DOWNLOAD / f"{symbol}_{expiry}.parquet"
    try:
        repo, sha = download(entry, staged)
        raw = read_source(staged, "options")
        df, stats = normalise_options(raw, symbol, expiry)
        bhav = bhav_rows(symbol, expiry)
        lots = infer_lots(df, bhav, symbol, expiry)
        if lots:
            df, stats = normalise_options(raw, symbol, expiry, lots=lots)
        chk = vwap_check(df, bhav, symbol, expiry)
    finally:
        staged.unlink(missing_ok=True)
    if df.empty:
        raise ValueError(f"{key}: 0 bars after cleaning")
    traded = int((df["volume_contracts"] > 0).sum())
    status = ("stub" if traded < STUB_BELOW else "unvalidated" if not chk["n"]
              else "suspect" if chk["match"] < SUSPECT_BELOW else "ok")
    note = "; ".join([
        f"status={status}", f"traded_bars={traded}",f"vwap_match={chk['match']:.3f}" if chk["n"] else "vwap_match=", f"vwap_n={chk['n']}",
        f"bhav_days={chk['days']}", f"vol_ratio={chk['vol_ratio']:.3f}" if chk["vol_ratio"] else "vol_ratio=",
        f"lot={'/'.join(map(str, stats['lots']))}", f"lot_from_bhav={len(lots)}d",
        f"offlot_bars={stats['offlot_bars']:.4f}", f"dup_rows={stats['dup_rows']}", f"late_rows={stats['late_rows']}",
        f"stray_rows={stats['stray_rows']}", f"zero_rows={stats['zero_rows']}", f"muhurat_days={stats['muhurat_days']}", f"repo={repo}", f"src_bytes={entry['size']}", f"src_sha256={sha}", "licence=CC BY-NC 4.0"])
    path = ROOT / symbol / f"{expiry}.parquet"
    record("expiry", key, df, path, write_parquet(df, path, OPT_SCHEMA), note)
    return {"key": key, "rows": len(df), "status": status, **chk}


def ingest_index(entry, symbol, have, force=False):
    if not force and _done(have, "index", symbol, entry):
        return None
    staged = DOWNLOAD / f"index_{symbol}.parquet"
    try:
        repo, sha = download(entry, staged)
        df, stats = normalise_index(read_source(staged, "index"), symbol)
    finally:
        staged.unlink(missing_ok=True)
    if df.empty:
        raise ValueError(f"index {symbol}: 0 bars after cleaning")
    note = "; ".join(["status=ok", f"dup_rows={stats['dup_rows']}", f"late_rows={stats['late_rows']}",
                      f"stray_rows={stats['stray_rows']}", f"zero_rows={stats['zero_rows']}", f"muhurat_days={stats['muhurat_days']}", f"nonzero_volume_bars={stats['nonzero_volume_bars']}", f"repo={repo}",
                      f"src_bytes={entry['size']}", f"src_sha256={sha}", "licence=CC BY-NC 4.0"])
    path = ROOT / "index" / f"{symbol}.parquet"
    record("index", symbol, df, path, write_parquet(df, path, IDX_SCHEMA), note)
    return {"key": f"index/{symbol}", "rows": len(df), "status": "ok"}


# ─────────────────────────── the run ───────────────────────────

def harvest(symbols=SYMBOLS, keys=None, force=False):
    """Every listed expiry (or only `keys` 'SYM/EXPIRY' / 'index/SYM') not yet in the manifest with
    the same source hash. Returns (written, skipped, errors). Raises when nothing could be written."""
    have = manifest()
    stem = lambda e: os.path.basename(e["path"]).removesuffix(".parquet")   # noqa: E731
    index_files = {stem(e): e for e in list_files("index")}
    jobs = []                                       # (key, kind, symbol, listing entry)
    for s in symbols:
        if s not in index_files:
            raise RuntimeError(f"{LABEL}: no index/{s}.parquet in the dataset")
        jobs.append((f"index/{s}", "index", s, index_files[s]))
        if keys is None or any(k.startswith(f"{s}/") for k in keys):
            jobs += [(f"{s}/{stem(e)}", "expiry", s, e) for e in list_files(f"options/{s}")]
    if keys is not None:
        jobs = [j for j in jobs if j[0] in keys]
        if len(jobs) != len(keys):
            raise RuntimeError(f"{LABEL}: not in the dataset: {sorted(set(keys) - {j[0] for j in jobs})}")
    print(f"{LABEL}: {len(jobs)} files listed → {ROOT}", flush=True)
    written = skipped = errors = 0
    results = []
    for i, (_key, kind, s, e) in enumerate(jobs, 1):
        try:
            r = (ingest_index if kind == "index" else ingest_expiry)(e, s, have, force=force)
        except Exception as ex:                     # noqa: BLE001 — one file never stops the run
            errors += 1
            runlog.item_error(LABEL, e["path"], ex)
            print(f"  {e['path']}: {type(ex).__name__}: {ex}", flush=True)
            continue
        if r is None:
            skipped += 1
            continue
        written += 1
        results.append(r)
        runlog.item_ok()
        if r["status"] == "suspect":                # kept, but on the record (run_events), not only printed
            runlog.note(f"{LABEL}: {r['key']} suspect — VWAP match {r['match']:.1%} of {r['n']} "
                        f"< {SUSPECT_BELOW:.0%}", level="WARN", key=r["key"], match=r["match"], n=r["n"])
        if r["status"] == "stub":
            runlog.note(f"{LABEL}: {r['key']} is an upstream stub ({r['rows']:,} bars, under {STUB_BELOW:,} traded)",
                        level="WARN", key=r["key"])
        if i % 20 == 0 or i == len(jobs) or keys is not None:
            m = f" vwap {r['match']:.1%} of {r['n']}" if r.get("n") else ""
            print(f"  [{i}/{len(jobs)}] {r['key']}: {r['rows']:,} bars {r['status']}{m}", flush=True)
    rows = sum(r["rows"] for r in results)
    runlog.harvest_summary(LABEL, len(jobs), written, errors, rows)
    print(f"{LABEL}: {written} written · {skipped} unchanged · {errors} errors · {rows:,} bars", flush=True)
    if written == 0 and (errors or not skipped):
        raise RuntimeError(f"{LABEL}: nothing written ({errors} errors of {len(jobs)} files)")
    return written, skipped, errors


def missing_expiries(symbol):
    """Expiries fno_bhav lists (index options, inside the source's span) that the source has no file for."""
    have = read_sql("SELECT key FROM intraday_files WHERE dataset = ? AND kind = 'expiry' AND key LIKE ?",
                    params=[DATASET, f"{symbol}/%"])["key"].str.split("/").str[1]
    if have.empty:
        return []
    bhav = read_sql("SELECT DISTINCT expiry_date FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' "
                    "AND expiry_date BETWEEN ? AND ? AND trade_date >= date(expiry_date, '-10 days')",
                    params=[symbol, have.min(), have.max()])["expiry_date"]
    return sorted(set(bhav) - set(have))


def status():
    m = read_sql("SELECT kind, key, n_rows, n_days, bytes, note FROM intraday_files WHERE dataset = ?",
                 params=[DATASET])
    if m.empty:
        print(f"{DATASET}: nothing in the manifest")
        return
    notes = m["note"].map(parse_note)
    m["status"] = notes.map(lambda n: n.get("status"))
    m["match"] = pd.to_numeric(notes.map(lambda n: n.get("vwap_match") or None), errors="coerce")
    m["n"] = pd.to_numeric(notes.map(lambda n: n.get("vwap_n") or 0), errors="coerce")
    m["symbol"] = np.where(m["kind"] == "index", "index/" + m["key"], m["key"].str.split("/").str[0])
    print(f"{DATASET} under {ROOT}")
    for sym, g in m.groupby("symbol"):
        line = f"  {sym:12s} {len(g):4d} files · {g['n_rows'].sum():>12,} bars · {g['bytes'].sum() / 2**20:7.1f} MB"
        if not sym.startswith("index/"):
            exp = g["key"].str.split("/").str[1]
            v = g["match"].dropna()
            line += (f" · {exp.min()} → {exp.max()} · checked {len(v)} (match median {v.median():.1%}, "
                     f"p10 {v.quantile(.1):.1%}, min {v.min():.1%}) · suspect {int((g['status'] == 'suspect').sum())}"
                     f" · unvalidated {int((g['status'] == 'unvalidated').sum())}"
                     f" · stub {int((g['status'] == 'stub').sum())}") if len(v) else ""
            miss = missing_expiries(sym)
            line += f"\n  {'':12s} missing vs fno_bhav: {len(miss)} {miss}"
        print(line)
    for r in m[m["status"] == "suspect"].itertuples():
        print(f"  SUSPECT {r.key}: VWAP match {r.match:.1%} of {int(r.n)}")
    for r in m[m["status"] == "stub"].itertuples():
        print(f"  STUB {r.key}: {r.n_rows:,} bars on {r.n_days} day(s)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--smoke", help="comma-separated SYM/EXPIRY or index/SYM keys, end to end (rewrites them)")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    ap.add_argument("--force", action="store_true", help="rewrite files whose source hash is unchanged")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    symbols = tuple(a.symbols.split(","))
    if a.status:
        return status()
    if a.smoke:
        keys = set(a.smoke.split(","))
        harvest(symbols=tuple(s for s in symbols if any(k == f"index/{s}" or k.startswith(f"{s}/") for k in keys)),
                keys=keys, force=True)
        return status()
    if a.backfill:
        harvest(symbols=symbols, force=a.force)
        return status()
    ap.print_help()


if __name__ == "__main__":
    main()
