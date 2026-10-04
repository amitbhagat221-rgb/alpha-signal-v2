"""
Alpha Signal v2 — NSE Bhavcopy Fetcher

Fetches daily OHLCV + delivery % from NSE archives.
URL: https://archives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv

Guardrails:
  - Rejects if < 1,000 rows (holiday or bad file)
  - Rejects negative/zero close prices
  - Rejects delivery_pct outside 0-100
  - Skips weekends and known holidays
  - Validates column presence before insert
  - Maps symbols to SIDs (skips unknown symbols)

Reads: NSE archives
Writes: stock_prices

Usage:
    python -m sources.nse                     # fetch today
    python -m sources.nse --date 2026-04-07   # fetch specific date
    python -m sources.nse --backfill 30       # backfill last 30 days
    python -m sources.nse --dry-run
"""

import argparse
from datetime import date, datetime, timedelta
from io import StringIO

import numpy as np
import pandas as pd

from db import insert_df, read_sql
from sources import _http

BHAVCOPY_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv"

# Validation thresholds
MIN_ROWS = 1000           # typical trading day has 1500+ EQ rows
MAX_CLOSE = 500_000       # no stock > ₹5L (Berkshire-like check)
MIN_CLOSE = 0.01          # penny stock floor

# Equity-adjacent series we accept. NSE bhavcopy mixes equity with bonds,
# ETFs, and government securities; we want main-board + SME + trade-for-trade
# + REIT/InvIT, but not GS/GB/MF/E1. Without SM/BE/ST we lose ~175 stocks
# from our 2,448-stock universe (SME-listed pharma, etc — e.g. ANO/ANONDITA).
TRADEABLE_SERIES = {"EQ", "SM", "BE", "ST", "IV", "RR", "BZ"}

def _is_trading_day(d):
    """Skip weekends. Holidays will return 404 from NSE."""
    return d.weekday() < 5


# The rows of the day's file for symbols that are NOT in `stocks` — delisted and
# merged names, and listed ones outside our universe — parked by _fetch_date for
# fetch_bhavcopy to store in stock_prices_unlisted. The file is the same download:
# until 2026-10-03 these rows were dropped, which made every backtest date a
# survivors-only cross-section (plan 0020; ~670 of ~1,750 tradeable symbols in 2020).
_UNLISTED = {}


def _file_date(df):
    """The trade date a bhavcopy file states for itself (DATE1, e.g. '01-Oct-2026'),
    or None when the column is absent or unreadable."""
    if "DATE1" not in df.columns or df.empty:
        return None
    try:
        return datetime.strptime(str(df["DATE1"].iloc[0]).strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


def _fetch_date(target_date):
    """Fetch and parse bhavcopy for a single date. Returns (df, errors)."""
    date_str = target_date.strftime("%d%m%Y")
    url = BHAVCOPY_URL.format(date=date_str)

    try:
        resp = _http.polite_get(url, timeout=30)
    except Exception as e:   # a bad day must SKIP, not fail this critical step
        return None, [f"{type(e).__name__}: {e}"]
    if resp is None:
        return None, [f"404 — likely holiday ({target_date})"]

    # Parse CSV
    try:
        df = pd.read_csv(StringIO(resp.text))
    except Exception as e:
        return None, [f"CSV parse error: {e}"]

    # Strip column names (NSE has leading spaces)
    df.columns = df.columns.str.strip()

    # ── GUARDRAIL 1: Column presence ──
    required = ["SYMBOL", "SERIES", "CLOSE_PRICE"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return None, [f"Missing columns: {missing}"]

    # ── GUARDRAIL 1b: the file must be FOR the day asked ──
    # On a market holiday NSE answers the holiday's URL with the previous session's
    # file. Stamping it with the requested date stored 44 copied "trading days"
    # (2020-2026): every price window counted them and the day's picks ranked on them.
    file_date = _file_date(df)
    if file_date is not None and file_date != target_date:
        return None, [f"404 — holiday: the file served for {target_date} is the {file_date} session"]

    # Filter to tradeable equity-adjacent series (EQ + SM + BE + ST + IV + RR + BZ).
    if "SERIES" in df.columns:
        df["SERIES"] = df["SERIES"].str.strip()
        df = df[df["SERIES"].isin(TRADEABLE_SERIES)].copy()

    # ── GUARDRAIL 2: Minimum rows ──
    if len(df) < MIN_ROWS:
        return None, [f"Only {len(df)} EQ rows (expected {MIN_ROWS}+) — possible partial file"]

    # Map to our schema
    sid_map = _http.sid_map()

    # Build clean output
    col_map = {
        "SYMBOL": "symbol",
        "OPEN_PRICE": "open",
        "HIGH_PRICE": "high",
        "LOW_PRICE": "low",
        "CLOSE_PRICE": "close",
        "PREV_CLOSE": "prev_close",
        "TTL_TRD_QNTY": "volume",
        "TTL_TRD_VAL": "traded_value",
        "NO_OF_TRADES": "num_trades",
        "DELIV_QTY": "delivered_qty",
        "DELIV_PER": "delivery_pct",
    }

    # Strip all column names for mapping
    rename = {}
    for old, new in col_map.items():
        # Try with and without space prefix
        if old in df.columns:
            rename[old] = new
        elif f" {old}" in df.columns:
            rename[f" {old}"] = new

    df = df.rename(columns=rename)

    # Add sid and date
    df["symbol"] = df["symbol"].str.strip() if "symbol" in df.columns else df.iloc[:, 0].str.strip()
    df["sid"] = df["symbol"].map(sid_map)
    df["date"] = target_date.isoformat()
    df["source"] = "bhavcopy"

    # Symbols outside our universe are kept, in their own table (see _UNLISTED below)

    # ── GUARDRAIL 3: Numeric conversion + validation ──
    for col in ["open", "high", "low", "close", "prev_close", "volume",
                "traded_value", "num_trades", "delivered_qty", "delivery_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    errors = []

    # ── GUARDRAIL 4: No negative/zero close prices ──
    bad_close = df[(df["close"] <= MIN_CLOSE) | (df["close"] > MAX_CLOSE)]
    if len(bad_close) > 0:
        errors.append(f"{len(bad_close)} rows with invalid close price (dropped)")
        df = df[(df["close"] > MIN_CLOSE) & (df["close"] <= MAX_CLOSE)]

    # ── GUARDRAIL 5: Delivery % in 0-100 ──
    if "delivery_pct" in df.columns:
        bad_deliv = df[(df["delivery_pct"] < 0) | (df["delivery_pct"] > 100)]
        if len(bad_deliv) > 0:
            errors.append(f"{len(bad_deliv)} rows with delivery_pct outside 0-100 (clipped)")
            df["delivery_pct"] = df["delivery_pct"].clip(lower=0, upper=100)

    # ── GUARDRAIL 6: Close vs prev_close sanity (no >50% gap unless penny stock) ──
    if "prev_close" in df.columns:
        df["_pct_change"] = ((df["close"] - df["prev_close"]) / df["prev_close"]).abs()
        extreme = df[(df["_pct_change"] > 0.5) & (df["close"] > 10)]
        if len(extreme) > 20:  # more than 20 extreme moves = likely bad data
            errors.append(f"WARNING: {len(extreme)} stocks with >50% day change")
        df = df.drop(columns=["_pct_change"])

    # ── GUARDRAIL 7: Volume sanity ──
    if "volume" in df.columns:
        neg_vol = df[df["volume"] < 0]
        if len(neg_vol) > 0:
            errors.append(f"{len(neg_vol)} rows with negative volume (dropped)")
            df = df[df["volume"] >= 0]

    # Select output columns
    out_cols = ["sid", "date", "open", "high", "low", "close", "prev_close",
                "volume", "traded_value", "num_trades", "delivered_qty",
                "delivery_pct", "source"]
    for col in out_cols:
        if col not in df.columns:
            df[col] = None

    listed = df["sid"].notna()
    _UNLISTED[target_date] = (df.loc[~listed, ["symbol", "SERIES", *out_cols[1:]]]
                              .rename(columns={"SERIES": "series"}))
    return df.loc[listed, out_cols], errors


def fetch_bhavcopy(target_date=None, dry_run=False, failures=None):
    """Fetch bhavcopy for a single date.

    `failures` (optional list): a day that could not be loaded for a reason OTHER
    than 404 (not published / holiday) is appended as "YYYY-MM-DD: reason".
    """
    if target_date is None:
        target_date = date.today()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    if not _is_trading_day(target_date):
        print(f"  {target_date}: weekend — skipped")
        return 0

    print(f"  {target_date}...", end=" ", flush=True)

    if dry_run:
        print("dry run")
        return 0

    df, errors = _fetch_date(target_date)

    if df is None:
        print(f"SKIP — {errors}")
        if failures is not None and not errors[0].startswith("404"):
            failures.append(f"{target_date}: {errors[0]}")
        return 0

    for e in errors:
        print(f"\n    ⚠ {e}", end="", flush=True)

    n = insert_df(df, "stock_prices")
    unlisted = _UNLISTED.pop(target_date, None)
    n_unlisted = insert_df(unlisted, "stock_prices_unlisted") if unlisted is not None and len(unlisted) else 0
    print(f"{len(df)} rows ({n} new), {n_unlisted} new rows outside the universe")
    return n


def backfill(days=30, dry_run=False):
    """Backfill last N days of bhavcopy."""
    print(f"NSE Bhavcopy: backfilling {days} days")
    total = 0
    for i in range(days, 0, -1):
        d = date.today() - timedelta(days=i)
        n = fetch_bhavcopy(d, dry_run=dry_run)
        total += n   # polite_get keeps ≥2s between archive requests
    print(f"\nTotal: {total} new rows")
    return total


def backfill_range(start, end, dry_run=False):
    """Backfill bhavcopy for an explicit [start, end] calendar range (YYYY-MM-DD).

    For deep historical fills below the daily-cron floor (e.g. extending PIT before
    stock_prices' 2022-07 start to test regime-sensitive factors like credit_beta over
    the 2020-22 credit-stress window). Reuses fetch_bhavcopy → identical mapping /
    validation / sid-map / source='bhavcopy', so the rows are consistent with the live
    table. Weekends skip free; holidays 404 and skip. 2s floor between fetches (CLAUDE
    data rule). NOTE: the sec_bhavdata_full archive only reaches ~2020-01; older dates
    404 (would need jugaad-data's legacy-format path)."""
    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    print(f"NSE Bhavcopy: backfilling range {s} → {e}")
    total = 0
    d = s
    while d <= e:
        if _is_trading_day(d):
            total += fetch_bhavcopy(d, dry_run=dry_run)   # polite_get paces ≥2s
        d += timedelta(days=1)
    print(f"\nTotal: {total} new rows ({s} → {e})")
    return total


SYMBOL_CHANGE_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"


def link_renames(dry_run=False):
    """Give a renamed stock its earlier history. NSE's symbol-change list is stored in
    symbol_changes; every stock_prices_unlisted row whose symbol later became (through
    any chain of renames) the ticker of a stock in our universe is copied into
    stock_prices under that sid (INSERT OR IGNORE). Without this a renamed stock starts
    its price history on the day of the rename: ADANIENSOL had none before 2023-08,
    VGL none before 2025-10 (127 stocks, 93k rows at the 2026-10-03 backfill).
    Returns the number of price rows added."""
    resp = _http.polite_get(SYMBOL_CHANGE_URL, timeout=30)
    if resp is None:
        raise RuntimeError("NSE symbol-change list not found (404)")
    sc = pd.read_csv(StringIO(resp.text), header=None, names=["name", "old_symbol", "new_symbol", "change_date"],
                     encoding="latin-1")
    for c in ("name", "old_symbol", "new_symbol"):
        sc[c] = sc[c].astype(str).str.strip()
    sc["change_date"] = pd.to_datetime(sc["change_date"].astype(str).str.strip(), format="%d-%b-%Y", errors="coerce")
    sc = sc.dropna(subset=["change_date"]).sort_values("change_date")
    if len(sc) < 500:                       # the list has held 1,000+ rows since 2025
        raise RuntimeError(f"NSE symbol-change list has only {len(sc)} rows — refusing to use a partial file")
    sc["change_date"] = sc["change_date"].dt.strftime("%Y-%m-%d")

    later = dict(zip(sc["old_symbol"], sc["new_symbol"]))        # in date order: the latest change wins

    def final(symbol):
        seen = set()
        while symbol in later and symbol not in seen:
            seen.add(symbol)
            symbol = later[symbol]
        return symbol

    sid_of = _http.sid_map()
    unlisted = read_sql("SELECT DISTINCT symbol FROM stock_prices_unlisted")["symbol"]
    moves = {s: sid_of[final(s)] for s in unlisted if final(s) != s and final(s) in sid_of}
    if dry_run:
        print(f"symbol changes: {len(sc)} listed, {len(moves)} unlisted symbols are earlier names of universe stocks")
        return 0
    insert_df(sc[["old_symbol", "new_symbol", "change_date", "name"]], "symbol_changes")
    added = 0
    for symbol, sid in moves.items():
        rows = read_sql("SELECT date, open, high, low, close, prev_close, volume, traded_value, num_trades, "
                        "delivered_qty, delivery_pct, source FROM stock_prices_unlisted WHERE symbol = ? "
                        f"AND series IN ({','.join('?' * len(TRADEABLE_SERIES))})", params=[symbol, *sorted(TRADEABLE_SERIES)])
        rows = rows.sort_values("date").drop_duplicates("date")
        rows.insert(0, "sid", sid)
        added += insert_df(rows, "stock_prices")
    print(f"symbol changes: {len(sc)} listed; {added} earlier-name price rows added for {len(moves)} universe stocks")
    return added


def _loaded_dates(since_iso):
    df = read_sql("SELECT DISTINCT date FROM stock_prices WHERE source = 'bhavcopy' AND date >= ?",
                  params=[since_iso])
    return set(df["date"])


def compute(dry_run=False):
    """Pipeline entry point — fill any of the last 7 days not yet loaded.

    Cron runs in the early morning before NSE publishes the day's bhavcopy,
    so fetching only `date.today()` returns 0 rows on every run. Walking a
    7-day window picks up the latest file once it goes live AND self-heals
    from cron downtime. Days whose bhavcopy rows are already in stock_prices
    are skipped (mirrors fno_pull.compute) — the old version re-downloaded all
    ~5 weekday files (~20 MB) every morning to INSERT-OR-IGNORE them away.
    Holidays aren't "loaded", so they're re-probed (one 404 each) until they
    age out of the window.
    """
    today = date.today()
    days = [today - timedelta(days=i) for i in range(7, 0, -1)]
    have = _loaded_dates(days[0].isoformat())
    todo = [d for d in days if _is_trading_day(d) and d.isoformat() not in have]
    print(f"NSE Bhavcopy: {len(todo)} of the last 7 days not yet loaded")
    failures = []
    n = sum(fetch_bhavcopy(d, dry_run=dry_run, failures=failures) for d in todo)
    if not dry_run:
        _assert_fresh(today, failures)
        try:
            link_renames()
        except Exception as e:                  # noqa: BLE001 — the day's prices are in; a rename waits a day, visibly
            import runlog
            runlog.item_error("nse_bhavcopy", "symbol_changes", e)
    return n


# Weekdays with no bhavcopy between the newest loaded day and today. Holidays make
# 1 normal (49× since 2022-08) and 2 rare (once); 3+ has never happened. This is a
# CRITICAL step: returning 0 here used to log SUCCESS and let the screener rank on
# stale prices (plan 0015 Phase 0).
STALE_WEEKDAYS = 3


def _assert_fresh(today, failures):
    """Raise if a day failed for a non-404 reason, or if prices are stale."""
    if failures:
        raise RuntimeError("bhavcopy download failed (not a 404/holiday): " + "; ".join(failures))
    newest = read_sql("SELECT MAX(date) AS d FROM stock_prices WHERE source = 'bhavcopy'")["d"].iloc[0]
    if newest is None:
        raise RuntimeError("stock_prices has no bhavcopy rows")
    missing = int(np.busday_count(newest, today.isoformat())) - 1
    if missing >= STALE_WEEKDAYS:
        raise RuntimeError(f"bhavcopy stale: newest loaded day {newest}, {missing} weekdays "
                           f"missing before {today} (threshold {STALE_WEEKDAYS})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Fetch specific date (YYYY-MM-DD)")
    parser.add_argument("--backfill", type=int, help="Backfill last N days")
    parser.add_argument("--start", help="Range backfill start (YYYY-MM-DD), with --end")
    parser.add_argument("--end", help="Range backfill end (YYYY-MM-DD), with --start")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.start and args.end:
        backfill_range(args.start, args.end, dry_run=args.dry_run)
    elif args.backfill:
        backfill(days=args.backfill, dry_run=args.dry_run)
    elif args.date:
        print("NSE Bhavcopy:")
        fetch_bhavcopy(args.date, dry_run=args.dry_run)
    else:
        compute(dry_run=args.dry_run)
