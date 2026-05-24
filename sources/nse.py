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
import time
from datetime import date, datetime, timedelta
from io import StringIO

import pandas as pd
import requests

from config import API
from db import read_sql, insert_df

BHAVCOPY_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv"
HEADERS = {"User-Agent": API["user_agent"]}

# Validation thresholds
MIN_ROWS = 1000           # typical trading day has 1500+ EQ rows
MAX_CLOSE = 500_000       # no stock > ₹5L (Berkshire-like check)
MIN_CLOSE = 0.01          # penny stock floor

# Equity-adjacent series we accept. NSE bhavcopy mixes equity with bonds,
# ETFs, and government securities; we want main-board + SME + trade-for-trade
# + REIT/InvIT, but not GS/GB/MF/E1. Without SM/BE/ST we lose ~175 stocks
# from our 2,448-stock universe (SME-listed pharma, etc — e.g. ANO/ANONDITA).
TRADEABLE_SERIES = {"EQ", "SM", "BE", "ST", "IV", "RR", "BZ"}

_SID_MAP = None


def _get_sid_map():
    global _SID_MAP
    if _SID_MAP is None:
        stocks = read_sql("SELECT sid, ticker FROM stocks")
        _SID_MAP = stocks.set_index("ticker")["sid"].to_dict()
    return _SID_MAP


def _is_trading_day(d):
    """Skip weekends. Holidays will return 404 from NSE."""
    return d.weekday() < 5


def _fetch_date(target_date):
    """Fetch and parse bhavcopy for a single date. Returns (df, errors)."""
    date_str = target_date.strftime("%d%m%Y")
    url = BHAVCOPY_URL.format(date=date_str)

    resp = requests.get(url, headers=HEADERS, timeout=30)

    if resp.status_code == 404:
        return None, [f"404 — likely holiday ({target_date})"]
    if resp.status_code != 200:
        return None, [f"HTTP {resp.status_code}"]

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

    # Filter to tradeable equity-adjacent series (EQ + SM + BE + ST + IV + RR + BZ).
    if "SERIES" in df.columns:
        df["SERIES"] = df["SERIES"].str.strip()
        df = df[df["SERIES"].isin(TRADEABLE_SERIES)].copy()

    # ── GUARDRAIL 2: Minimum rows ──
    if len(df) < MIN_ROWS:
        return None, [f"Only {len(df)} EQ rows (expected {MIN_ROWS}+) — possible partial file"]

    # Map to our schema
    sid_map = _get_sid_map()

    # Build clean output
    col_map = {
        "SYMBOL": "symbol",
        "OPEN_PRICE": "open",
        "HIGH_PRICE": "high",
        "LOW_PRICE": "low",
        "CLOSE_PRICE": "close",
        "PREVCLOSE": "prev_close",
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

    # Drop unmapped symbols
    unmapped = df["sid"].isna().sum()
    df = df.dropna(subset=["sid"])

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

    return df[out_cols], errors


def fetch_bhavcopy(target_date=None, dry_run=False):
    """Fetch bhavcopy for a single date."""
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
        return 0

    for e in errors:
        print(f"\n    ⚠ {e}", end="", flush=True)

    n = insert_df(df, "stock_prices")
    print(f"{len(df)} rows ({n} new)")
    return n


def backfill(days=30, dry_run=False):
    """Backfill last N days of bhavcopy."""
    print(f"NSE Bhavcopy: backfilling {days} days")
    total = 0
    for i in range(days, 0, -1):
        d = date.today() - timedelta(days=i)
        n = fetch_bhavcopy(d, dry_run=dry_run)
        total += n
        if not dry_run:
            time.sleep(2)  # 2s delay between requests
    print(f"\nTotal: {total} new rows")
    return total


def compute(dry_run=False):
    """Pipeline entry point — backfill last 7 trading days.

    Cron runs in the early morning before NSE publishes the day's bhavcopy,
    so fetching only `date.today()` returns 0 rows on every run. Backfilling
    a 7-day window (with INSERT OR IGNORE) picks up today's file once it
    goes live AND self-heals from cron downtime or skipped weekends without
    re-inserting what we already have.
    """
    return backfill(days=7, dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Fetch specific date (YYYY-MM-DD)")
    parser.add_argument("--backfill", type=int, help="Backfill last N days")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.backfill:
        backfill(days=args.backfill, dry_run=args.dry_run)
    elif args.date:
        print("NSE Bhavcopy:")
        fetch_bhavcopy(args.date, dry_run=args.dry_run)
    else:
        compute(dry_run=args.dry_run)
