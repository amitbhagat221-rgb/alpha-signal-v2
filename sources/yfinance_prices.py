"""
Alpha Signal v2 — yfinance Price Fallback (BSE / non-EQ series)

Fills the gap left by sources/nse.py (which only fetches NSE 'EQ' / SM / BE etc).
Targets SIDs missing from `stock_prices`: mostly InvITs, REITs, BSE-only listings,
recent IPOs not yet on NSE. As of 2026-05-24, 339 of 2,448 universe SIDs are
absent from stock_prices entirely; ~70% are reachable via yfinance with `.BO`.

Strategy:
  1. Identify SIDs missing from stock_prices in the last 30 days.
  2. One batched yf.download of every `<ticker>.NS` (rare hits — would have been
     caught by the NSE harvester, but try anyway in case the ticker is new).
  3. One batched yf.download of `<ticker>.BO` (BSE) for the .NS misses.
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
from datetime import date, timedelta

import pandas as pd


from db import read_sql, insert_df

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


def _download(symbols, period):
    """One batched yf.download → {symbol: history} for symbols that returned
    prices. Replaces a Ticker().history() call per symbol + a 1.5s sleep each;
    same fields (auto_adjust=False → raw OHLC). threads=False keeps yfinance's
    per-symbol requests sequential. Rows with no Close (a symbol absent on a date
    another symbol traded) are dropped — per-ticker history() never had them."""
    import yfinance as yf
    if not symbols:
        return {}
    data = yf.download(symbols, period=period, auto_adjust=False, group_by="ticker",
                       progress=False, threads=False)
    out = {}
    for sym in symbols:
        if isinstance(data.columns, pd.MultiIndex):
            if sym not in data.columns.get_level_values(0):
                continue
            h = data[sym]
        else:
            h = data
        h = h.dropna(subset=["Close"])
        if not h.empty:
            out[sym] = h
    return out


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

    period = f"{max(7, days)}d"
    tickers = missing["ticker"].tolist()
    got = {".NS": _download([t + ".NS" for t in tickers], period)}
    got[".BO"] = _download([t + ".BO" for t in tickers if t + ".NS" not in got[".NS"]], period)

    rows = []
    sids_with_data = 0
    by_suffix = {".NS": 0, ".BO": 0}
    for sid, ticker, _ in missing.itertuples(index=False):
        for suffix in (".NS", ".BO"):
            hist = got[suffix].get(ticker + suffix)
            if hist is not None:
                rows.extend(_normalize(sid, suffix, hist))
                sids_with_data += 1
                by_suffix[suffix] += 1
                break
    rows_written = insert_df(pd.DataFrame(rows), "stock_prices") if rows else 0

    print(f"Done. {sids_with_data}/{total} SIDs filled ({by_suffix.get('.NS',0)} via .NS, {by_suffix.get('.BO',0)} via .BO), {rows_written} price rows written.")
    return rows_written


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, help="Limit to first N missing SIDs (smoke test)")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Window to check / fetch")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    compute(limit=args.limit, days=args.days, dry_run=args.dry_run)
