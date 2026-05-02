"""
Alpha Signal v2 — NSE Insider Trading (PIT) Fetcher

Fetches insider trade disclosures from NSE's PIT API.
2+ years of history available. Rich data: promoter buys/sells, pledges,
KMP trades, employee transactions.

API: https://www.nseindia.com/api/corporates-pit?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY

Reads: NSE PIT API
Writes: insider_trades

Usage:
    python -m sources.nse_insider                   # fetch last 30 days
    python -m sources.nse_insider --months 24       # backfill 2 years
    python -m sources.nse_insider --dry-run
"""

import argparse
import hashlib
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from config import API
from db import get_db, insert_df, read_sql

NSE_PIT_URL = "https://www.nseindia.com/api/corporates-pit"
HEADERS = {
    "User-Agent": API["user_agent"],
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading",
}

# Map NSE symbols to SIDs
_SID_MAP = None


def _get_sid_map():
    global _SID_MAP
    if _SID_MAP is None:
        stocks = read_sql("SELECT sid, ticker FROM stocks")
        _SID_MAP = stocks.set_index("ticker")["sid"].to_dict()
    return _SID_MAP


def _fetch_chunk(from_date, to_date, session):
    """Fetch one date range from NSE PIT API."""
    params = {
        "index": "equities",
        "from_date": from_date.strftime("%d-%m-%Y"),
        "to_date": to_date.strftime("%d-%m-%Y"),
    }

    try:
        resp = session.get(NSE_PIT_URL, params=params, headers=HEADERS, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", [])
        elif resp.status_code == 403:
            # Need to refresh session cookie
            session.get("https://www.nseindia.com/", headers=HEADERS, timeout=10)
            time.sleep(2)
            resp = session.get(NSE_PIT_URL, params=params, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("data", [])
        print(f"    HTTP {resp.status_code}", end="", flush=True)
        return []
    except Exception as e:
        print(f"    Error: {e}", end="", flush=True)
        return []


def _parse_records(records):
    """Parse NSE PIT API response into DataFrame matching insider_trades schema."""
    sid_map = _get_sid_map()
    rows = []

    for rec in records:
        symbol = rec.get("symbol", "").strip()
        sid = sid_map.get(symbol)
        if not sid:
            continue  # skip stocks not in our universe

        # Determine transaction type and values
        # NSE PIT API: buyQuantity/sellquantity are always 0
        # Real data is in secAcq (shares) and secVal (value in rupees)
        tx_type = rec.get("tdpTransactionType", "")
        sec_acq = _safe_float(rec.get("secAcq"))
        sec_val = _safe_float(rec.get("secVal"))

        shares = sec_acq or 0
        value = sec_val / 100000 if sec_val else None  # convert rupees → lakhs

        if tx_type in ("Buy", "Acquisition"):
            direction = "Buy"
        elif tx_type in ("Sell", "Disposal"):
            direction = "Sell"
        else:
            direction = tx_type  # Pledge, Pledge Revoke, Pledge Invoke, etc.

        # Parse trade date. NSE PIT occasionally returns placeholder records where
        # every field is "-"; reject anything that doesn't parse as DD-Mon-YYYY.
        raw_dt = (rec.get("acqfromDt") or "").strip()
        try:
            trade_date = datetime.strptime(raw_dt[:11].strip(), "%d-%b-%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue

        person_cat = rec.get("personCategory", "")
        person = rec.get("acqName", "")

        rows.append({
            "sid": sid,
            "symbol": symbol,
            "company_name": rec.get("company", "")[:100],
            "person": person[:200],
            "person_category": person_cat,
            "transaction_type": direction,
            "shares": shares,
            "value_lakhs": value,
            "trade_date": trade_date,
            "source": "nse_pit",
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _safe_float(val):
    if val is None or val == "" or val == "-":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def fetch_insider(months=1, dry_run=False):
    """Fetch insider trades from NSE PIT API."""
    end = date.today()
    start = end - timedelta(days=months * 30)

    # Fetch in 3-month chunks (API handles ~13K records per year)
    chunk_days = 90
    chunks = []
    d = start
    while d < end:
        chunk_end = min(d + timedelta(days=chunk_days), end)
        chunks.append((d, chunk_end))
        d = chunk_end + timedelta(days=1)

    print(f"NSE Insider Trades: {start} → {end} ({len(chunks)} chunks)")

    if dry_run:
        for i, (s, e) in enumerate(chunks):
            print(f"  Chunk {i+1}: {s} → {e}")
        return 0

    session = requests.Session()
    # Get initial cookies
    session.get("https://www.nseindia.com/", headers=HEADERS, timeout=10)
    time.sleep(2)

    total_saved = 0
    total_fetched = 0

    for i, (chunk_start, chunk_end) in enumerate(chunks):
        print(f"  [{i+1}/{len(chunks)}] {chunk_start} → {chunk_end}...", end=" ", flush=True)

        records = _fetch_chunk(chunk_start, chunk_end, session)
        total_fetched += len(records)

        if records:
            df = _parse_records(records)
            if not df.empty:
                n = insert_df(df, "insider_trades")
                total_saved += n
                print(f"{len(records)} fetched, {n} new")
            else:
                print(f"{len(records)} fetched, 0 matched universe")
        else:
            print("0 records")

        time.sleep(3)  # be gentle on NSE

    print(f"\nTotal: {total_fetched} fetched, {total_saved} new rows saved")
    return total_saved


def compute(dry_run=False):
    """Pipeline entry point — fetch last 30 days."""
    return fetch_insider(months=1, dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=1, help="How many months to fetch (default: 1)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    fetch_insider(months=args.months, dry_run=args.dry_run)
