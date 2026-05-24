"""
Alpha Signal v2 — yfinance Price Fallback (BSE / non-EQ series)

Fills the gap left by sources/nse.py (which only fetches NSE 'EQ' / SM / BE etc).
Targets SIDs missing from `stock_prices`: mostly InvITs, REITs, BSE-only listings,
recent IPOs not yet on NSE. As of 2026-05-24, 339 of 2,448 universe SIDs are
absent from stock_prices entirely; ~70% are reachable via yfinance with `.BO`.

Strategy:
  1. Identify SIDs missing from stock_prices in the last 30 days.
  2. For each, try `<ticker>.NS` first (rare — would have been caught by NSE
     harvester, but try anyway in case ticker was added recently).
  3. Fall back to `<ticker>.BO` (BSE).
  4. Insert with source='yfinance' so we know which rows came from where.

Runs nightly after fetch_bhavcopy in PIPELINE_STEPS. Plan 0005 Phase C.
See docs/plans/0005-data-confidence-to-95.md.

Usage:
    python -m sources.yfinance_prices              # full gap-fill
    python -m sources.yfinance_prices --limit 20   # smoke test
    python -m sources.yfinance_prices --days 30    # window size
    python -m sources.yfinance_prices --dry-run
"""

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, insert_df

DELAY = 1.5   # yfinance is generous but be polite
DEFAULT_DAYS = 30


def _missing_sids(days=DEFAULT_DAYS):
    """Return list of (sid, ticker) for SIDs absent from stock_prices in last N days."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    df = read_sql(
        """
        SELECT s.sid, s.ticker, s.cap_tier
        FROM stocks s
        WHERE s.ticker IS NOT NULL
          AND s.sid NOT IN (
            SELECT DISTINCT sid FROM stock_prices WHERE date >= ?
          )
        ORDER BY s.market_cap_cr DESC
        """,
        params=[cutoff],
    )
    return df


def _fetch_one(ticker, days):
    """Try `.NS` first, then `.BO`. Return (suffix, DataFrame) or (None, None)."""
    import yfinance as yf
    period = f"{max(7, days)}d"
    for suffix in (".NS", ".BO"):
        try:
            tk = yf.Ticker(ticker + suffix)
            h = tk.history(period=period, auto_adjust=False)
            if h is not None and not h.empty:
                return suffix, h
        except Exception:
            continue
    return None, None


def _normalize(sid, suffix, hist_df):
    """Convert yfinance history into stock_prices rows."""
    rows = []
    for ts, row in hist_df.iterrows():
        rows.append({
            "sid": sid,
            "date": ts.date().isoformat(),
            "open": float(row["Open"]) if pd.notna(row["Open"]) else None,
            "high": float(row["High"]) if pd.notna(row["High"]) else None,
            "low":  float(row["Low"]) if pd.notna(row["Low"]) else None,
            "close": float(row["Close"]),
            "volume": int(row["Volume"]) if pd.notna(row["Volume"]) else None,
            "source": f"yfinance{suffix}",
        })
    return rows


def compute(limit=None, days=DEFAULT_DAYS, dry_run=False):
    """Pipeline entry point — fill stock_prices for missing SIDs via yfinance."""
    missing = _missing_sids(days=days)
    if limit:
        missing = missing.head(limit)

    total = len(missing)
    print(f"yfinance price fallback: {total} SIDs missing from stock_prices in last {days}d")
    if total == 0:
        return 0
    if dry_run:
        sample = missing.head(10).to_dict("records")
        print(f"  Sample SIDs to fetch: {[r['ticker'] for r in sample]}")
        return 0

    rows_written = 0
    sids_with_data = 0
    sids_no_data = 0
    by_suffix = {".NS": 0, ".BO": 0}
    for i, (sid, ticker, _) in enumerate(missing.itertuples(index=False), 1):
        suffix, hist = _fetch_one(ticker, days)
        if hist is None:
            sids_no_data += 1
        else:
            rows = _normalize(sid, suffix, hist)
            if rows:
                df_out = pd.DataFrame(rows)
                n = insert_df(df_out, "stock_prices")
                rows_written += n
                sids_with_data += 1
                by_suffix[suffix] = by_suffix.get(suffix, 0) + 1
        if i % 25 == 0 or i == total:
            print(f"  [{i:>3d}/{total}] sids_with_data={sids_with_data} no_data={sids_no_data} rows={rows_written}")
        time.sleep(DELAY)

    print(f"Done. {sids_with_data}/{total} SIDs filled ({by_suffix.get('.NS',0)} via .NS, {by_suffix.get('.BO',0)} via .BO), {rows_written} price rows written.")
    return rows_written


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, help="Limit to first N missing SIDs (smoke test)")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Window to check / fetch")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    compute(limit=args.limit, days=args.days, dry_run=args.dry_run)
