"""
Alpha Signal v2 — Macro Market Data (yfinance)

Fetches 3yr daily history for 20 market-based macro indicators:
- Nifty sectoral indices (12)
- Commodities (5: crude, gold, copper, aluminium, silver)
- FX (1: USD/INR)
- Rates (1: US 10Y yield)
- Volatility (1: India VIX)

Stores in macro_history table. Also populates macro_indicator_meta.

Usage:
    python -m sources.macro_yfinance                  # backfill 3yr
    python -m sources.macro_yfinance --days 30        # last 30 days only
    python -m sources.macro_yfinance --dry-run        # show what would be fetched
"""

import argparse
import time
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from db import get_db, upsert_df, insert_df, read_sql

# Ticker registry: indicator_id → (yf_ticker, name, category, unit)
TICKERS = {
    # Sectoral indices
    "nifty50":          ("^NSEI",       "Nifty 50",         "coincident", "index"),
    "bank_nifty":       ("^NSEBANK",    "Bank Nifty",       "coincident", "index"),
    "nifty_it":         ("^CNXIT",      "Nifty IT",         "coincident", "index"),
    "nifty_metal":      ("^CNXMETAL",   "Nifty Metal",      "coincident", "index"),
    "nifty_realty":     ("^CNXREALTY",   "Nifty Realty",     "coincident", "index"),
    "nifty_pharma":     ("^CNXPHARMA",  "Nifty Pharma",     "coincident", "index"),
    "nifty_auto":       ("^CNXAUTO",    "Nifty Auto",       "coincident", "index"),
    "nifty_fmcg":       ("^CNXFMCG",    "Nifty FMCG",       "coincident", "index"),
    "nifty_energy":     ("^CNXENERGY",  "Nifty Energy",     "coincident", "index"),
    "nifty_infra":      ("^CNXINFRA",   "Nifty Infra",      "coincident", "index"),
    "nifty_psubank":    ("^CNXPSUBANK", "Nifty PSU Bank",   "coincident", "index"),
    "nifty_media":      ("^CNXMEDIA",   "Nifty Media",      "coincident", "index"),
    # Volatility
    "india_vix":        ("^INDIAVIX",   "India VIX",        "leading",    "index"),
    # Commodities
    "brent_crude":      ("BZ=F",        "Brent Crude",      "leading",    "usd"),
    "gold":             ("GC=F",        "Gold",             "leading",    "usd"),
    "copper":           ("HG=F",        "Copper",           "leading",    "usd"),
    "aluminium":        ("ALI=F",       "Aluminium (LME)",  "leading",    "usd"),
    "silver":           ("SI=F",        "Silver",           "leading",    "usd"),
    # FX
    "usdinr":           ("USDINR=X",    "USD/INR",          "coincident", "inr"),
    # Rates
    "us_10y":           ("^TNX",        "US 10Y Yield",     "leading",    "percent"),
}


def _populate_meta():
    """Insert/update macro_indicator_meta for all yfinance tickers."""
    rows = []
    for ind_id, (ticker, name, category, unit) in TICKERS.items():
        rows.append({
            "indicator_id": ind_id,
            "name": name,
            "source": "yfinance",
            "source_ref": ticker,
            "category": category,
            "frequency": "daily",
            "unit": unit,
            "description": f"{name} — daily from yfinance ({ticker})",
        })
    df = pd.DataFrame(rows)
    with get_db() as conn:
        upsert_df(df, "macro_indicator_meta", conn=conn)
    return len(rows)


def _fetch_ticker(indicator_id, ticker, start_date, end_date):
    """Fetch daily close for one ticker. Returns DataFrame."""
    try:
        data = yf.download(ticker, start=start_date, end=end_date,
                           progress=False, auto_adjust=True)
        if data.empty:
            return pd.DataFrame()

        # Handle MultiIndex columns from yfinance
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        df = pd.DataFrame({
            "indicator_id": indicator_id,
            "date": data.index.strftime("%Y-%m-%d"),
            "value": data["Close"].values,
            "source": "yfinance",
            "category": TICKERS[indicator_id][2],
            "unit": TICKERS[indicator_id][3],
        })
        df = df.dropna(subset=["value"])
        return df
    except Exception as e:
        print(f"  Error fetching {ticker}: {e}")
        return pd.DataFrame()


def _compute_changes(df):
    """Compute YoY and MoM changes for a single indicator's time series."""
    if df.empty or len(df) < 2:
        return df

    df = df.sort_values("date").copy()
    vals = df["value"].values

    # MoM: vs 22 trading days ago (~1 month)
    mom = pd.Series(vals).pct_change(periods=min(22, len(vals) - 1)) * 100
    df["mom_change"] = mom.values

    # YoY: vs 252 trading days ago (~1 year)
    if len(vals) > 252:
        yoy = pd.Series(vals).pct_change(periods=252) * 100
        df["yoy_change"] = yoy.values

    return df


def backfill(days=None, dry_run=False):
    """Fetch macro market data and store in macro_history."""
    if days:
        start = (date.today() - timedelta(days=days)).isoformat()
    else:
        start = (date.today() - timedelta(days=3 * 365 + 30)).isoformat()
    end = date.today().isoformat()

    print(f"Macro yfinance backfill: {start} to {end}")
    print(f"Tickers: {len(TICKERS)}")

    if dry_run:
        for ind_id, (ticker, name, _, _) in TICKERS.items():
            print(f"  {ind_id:20s} {ticker:15s} {name}")
        print("\nDry run — not fetching.")
        return 0

    # Populate metadata
    _populate_meta()
    print("Metadata: populated")

    total_rows = 0
    for i, (ind_id, (ticker, name, _, _)) in enumerate(TICKERS.items(), 1):
        print(f"  [{i:2d}/{len(TICKERS)}] {ind_id:20s} {ticker:12s} ", end="", flush=True)

        df = _fetch_ticker(ind_id, ticker, start, end)
        if df.empty:
            print("— no data")
            continue

        df = _compute_changes(df)

        rows = upsert_df(df, "macro_history")
        total_rows += len(df)
        print(f"— {len(df)} rows")

        time.sleep(0.5)  # gentle on yfinance

    print(f"\nTotal: {total_rows} rows in macro_history")

    # Mirror india_vix into vix_history so regime.py + diff_engine read fresh data.
    # vix_history is the historical contract; macro_history is the firehose.
    vix_rows = _sync_vix_history()
    if vix_rows:
        print(f"Mirrored {vix_rows} rows into vix_history")

    return total_rows


def _sync_vix_history():
    """Copy india_vix rows from macro_history into vix_history (idempotent)."""
    df = read_sql(
        "SELECT date, value AS vix FROM macro_history "
        "WHERE indicator_id='india_vix' AND value IS NOT NULL "
        "ORDER BY date"
    )
    if df.empty:
        return 0
    return upsert_df(df, "vix_history")


def compute(dry_run=False):
    """Pipeline entry point — daily refresh (last 7 days)."""
    return backfill(days=7, dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, help="Fetch last N days (default: 3yr)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    backfill(days=args.days, dry_run=args.dry_run)
