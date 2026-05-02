"""
Alpha Signal v2 — NSE Bulk/Block Deals Fetcher

Fetches today's bulk and block deals from NSE archives.
No historical archive available — must accumulate daily.

URLs:
  Bulk:  https://archives.nseindia.com/content/equities/bulk.csv
  Block: https://archives.nseindia.com/content/equities/block.csv

Also migrates any v1 raw files not yet in DB.

Reads: NSE archives
Writes: bulk_deals

Usage:
    python -m sources.nse_bulk                      # fetch today
    python -m sources.nse_bulk --migrate-v1         # import v1 raw files
    python -m sources.nse_bulk --dry-run
"""

import argparse
import glob
import os
import re
from datetime import date

import pandas as pd
import requests

from config import API
from db import insert_df, read_sql

BULK_URL = "https://archives.nseindia.com/content/equities/bulk.csv"
BLOCK_URL = "https://archives.nseindia.com/content/equities/block.csv"
HEADERS = {"User-Agent": API["user_agent"]}

_SID_MAP = None


def _get_sid_map():
    global _SID_MAP
    if _SID_MAP is None:
        stocks = read_sql("SELECT sid, ticker FROM stocks")
        _SID_MAP = stocks.set_index("ticker")["sid"].to_dict()
    return _SID_MAP


def _parse_deals(csv_text, deal_type, deal_date=None):
    """Parse NSE bulk/block CSV into DataFrame matching bulk_deals schema."""
    if not csv_text or len(csv_text) < 50:
        return pd.DataFrame()

    try:
        df = pd.read_csv(pd.io.common.StringIO(csv_text))
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return df

    # Normalize column names (NSE has leading spaces sometimes)
    df.columns = df.columns.str.strip()

    sid_map = _get_sid_map()

    # Try to identify columns
    sym_col = next((c for c in df.columns if "symbol" in c.lower()), None)
    client_col = next((c for c in df.columns if "client" in c.lower() or "name" in c.lower()), None)
    bs_col = next((c for c in df.columns if "buy" in c.lower() and "sell" in c.lower()), None)
    qty_col = next((c for c in df.columns if "quant" in c.lower()), None)
    price_col = next((c for c in df.columns if "price" in c.lower()), None)
    date_col = next((c for c in df.columns if "date" in c.lower()), None)

    rows = []
    for _, r in df.iterrows():
        symbol = str(r.get(sym_col, "")).strip() if sym_col else ""
        sid = sid_map.get(symbol)
        if not sid:
            continue

        d = str(r.get(date_col, deal_date or date.today().isoformat())).strip()
        # Try to parse various date formats
        if d and len(d) >= 8:
            try:
                if "-" in d and len(d) == 10:
                    pass  # already YYYY-MM-DD
                elif "-" in d:
                    from datetime import datetime
                    d = datetime.strptime(d.strip()[:11], "%d-%b-%Y").strftime("%Y-%m-%d")
                elif "/" in d:
                    from datetime import datetime
                    d = datetime.strptime(d.strip()[:10], "%d/%m/%Y").strftime("%Y-%m-%d")
            except (ValueError, IndexError):
                d = deal_date or date.today().isoformat()

        rows.append({
            "sid": sid,
            "symbol": symbol,
            "client_name": str(r.get(client_col, ""))[:200] if client_col else None,
            "deal_type": deal_type,
            "buy_sell": str(r.get(bs_col, ""))[:10] if bs_col else None,
            "quantity": _safe_float(r.get(qty_col)) if qty_col else None,
            "price": _safe_float(r.get(price_col)) if price_col else None,
            "deal_date": d,
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _safe_float(val):
    try:
        return float(val) if val not in (None, "", "-") else None
    except (ValueError, TypeError):
        return None


def fetch_today(dry_run=False):
    """Fetch today's bulk and block deals from NSE."""
    print(f"NSE Bulk/Block Deals: fetching today ({date.today()})")

    if dry_run:
        print("  Dry run — not fetching.")
        return 0

    total = 0

    for url, deal_type in [(BULK_URL, "bulk"), (BLOCK_URL, "block")]:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                df = _parse_deals(resp.text, deal_type)
                if not df.empty:
                    n = insert_df(df, "bulk_deals")
                    print(f"  {deal_type}: {len(df)} deals fetched, {n} new")
                    total += n
                else:
                    print(f"  {deal_type}: no deals today")
            else:
                print(f"  {deal_type}: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  {deal_type}: error — {e}")

    return total


def migrate_v1(dry_run=False):
    """Import v1 raw bulk deal files not yet in DB."""
    raw_dir = os.path.expanduser("~/alpha-signal/data/smart_money/raw")
    files = sorted(glob.glob(os.path.join(raw_dir, "bulk_*.csv")))

    print(f"V1 migration: {len(files)} raw bulk deal files found")

    if dry_run:
        for f in files:
            print(f"  {os.path.basename(f)}")
        return 0

    total = 0
    for filepath in files:
        filename = os.path.basename(filepath)
        # Extract date from filename: bulk_YYYYMMDD.csv
        match = re.search(r"(\d{8})", filename)
        if not match:
            continue
        ds = match.group(1)
        deal_date = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"

        try:
            with open(filepath) as f:
                csv_text = f.read()
            df = _parse_deals(csv_text, "bulk", deal_date=deal_date)
            if not df.empty:
                n = insert_df(df, "bulk_deals")
                total += n
                if n > 0:
                    print(f"  {filename}: {n} new deals")
        except Exception as e:
            print(f"  {filename}: error — {e}")

    print(f"Migrated {total} new bulk deals from v1")
    return total


def compute(dry_run=False):
    """Pipeline entry point."""
    return fetch_today(dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--migrate-v1", action="store_true", help="Import v1 raw files")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.migrate_v1:
        migrate_v1(dry_run=args.dry_run)
    else:
        fetch_today(dry_run=args.dry_run)
