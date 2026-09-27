"""
Alpha Signal v2 — NSE Insider Trading (PIT) Fetcher

Fetches SEBI PIT Reg 7 insider-trade disclosures from NSE in two steps:

  1. LIST  https://www.nseindia.com/api/corporates-pit-gg?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
           one row per FILING (broadcast time, symbol, XBRL/XML links) — no trade fields.
  2. XML   https://nsearchives.nseindia.com/corporate/xbrl/IT_…_WebXMLFile_….xml
           one XBRL instance per filing; each `DisclosureN` context is one trade
           (person, category, Buy/Sell/Pledge…, shares, value, trade dates).

The old one-step endpoint (/api/corporates-pit, trade fields inline) has returned an
empty `data` list since ~2026-05-02; NSE's own filings page moved to -gg (2026-09).
Only universe symbols are fetched, and a filing already stored (insider_trades.filing_id)
is never fetched again, so the daily run costs ~one XML per new universe filing.

Reads: NSE PIT list API + filing XBRL (nse_archives), stocks, insider_trades.filing_id
Writes: insider_trades

Usage:
    python -m sources.nse_insider                                  # last 10 days (daily)
    python -m sources.nse_insider --from 2026-05-01 --to 2026-09-27  # backfill a window
    python -m sources.nse_insider --days 30 --dry-run              # list + parse, no write
"""

import argparse
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timedelta

import pandas as pd

from db import insert_df, read_sql
from hosts import HOSTS
from sources import _http

NSE_PIT_LIST_URL = "https://www.nseindia.com/api/corporates-pit-gg"
# NSE's JSON headers (hosts.HOSTS["nse"]) + the insider-filings page as referer.
SESSION_HEADERS = {**HOSTS["nse"]["headers"],
                   "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading"}

NSE_HOME = "https://www.nseindia.com/"
DAILY_DAYS = 10          # disclosures are indexed days after the trade; re-list 10 days
LIST_CHUNK_DAYS = 31     # one list call per month (~600 filings) — no truncation seen

# XBRL element local-name → field
_XBRL = {
    "NameOfThePerson": "person",
    "CategoryOfPerson": "person_category",
    "SecuritiesAcquiredOrDisposedTransactionType": "tx_type",
    "SecuritiesAcquiredOrDisposedNumberOfSecurity": "shares",
    "SecuritiesAcquiredOrDisposedValueOfSecurity": "value",
    "DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate": "trade_date",
}


def _direction(tx):
    """Map an XBRL transaction type onto the vocabulary insider_trades already holds
    (Buy / Sell / Pledge / Pledge Revoke / Pledge Invoke), else keep it verbatim."""
    t = (tx or "").strip()
    low = t.lower()
    if "revok" in low or "release" in low:
        return "Pledge Revoke"
    if "invo" in low:
        return "Pledge Invoke"
    if "pledge" in low or "creation" in low:
        return "Pledge"
    if low in ("buy", "acquisition", "purchase") or low.startswith("buy"):
        return "Buy"
    if low in ("sell", "disposal", "sale") or low.startswith("sell"):
        return "Sell"
    return t


def _safe_float(val):
    if val is None or val == "" or val == "-":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def list_filings(start, end, session):
    """Filings broadcast in [start, end] (dates), one list call per month."""
    out, d = [], start
    while d <= end:
        chunk_end = min(d + timedelta(days=LIST_CHUNK_DAYS - 1), end)
        params = {"index": "equities", "from_date": d.strftime("%d-%m-%Y"),
                  "to_date": chunk_end.strftime("%d-%m-%Y")}
        resp = _http.polite_get(NSE_PIT_LIST_URL, session=session, params=params, timeout=60)
        rows = (resp.json().get("data") or []) if resp is not None else []
        print(f"  list {d} → {chunk_end}: {len(rows)} filings", flush=True)
        out.extend(rows)
        d = chunk_end + timedelta(days=1)
    return out


def parse_xbrl(xml_text):
    """[{person, person_category, tx_type, shares, value, trade_date}] — one per
    Disclosure context. Matches elements by local name, whatever the namespace prefix."""
    root = ET.fromstring(xml_text)
    by_ctx = defaultdict(dict)
    for el in root.iter():
        name = el.tag.rsplit("}", 1)[-1]
        field = _XBRL.get(name)
        ctx = el.get("contextRef")
        if field and ctx:
            by_ctx[ctx][field] = (el.text or "").strip()
    return [v for v in by_ctx.values() if v.get("tx_type") or v.get("person")]


def _rows_for_filing(filing, disclosures, sid, today_iso):
    rows = []
    for x in disclosures:
        trade_date = (x.get("trade_date") or "")[:10]
        try:
            datetime.strptime(trade_date, "%Y-%m-%d")
        except ValueError:
            continue
        if trade_date > today_iso:          # future-dated = filing glitch; corrupts MAX(trade_date)
            continue
        value = _safe_float(x.get("value"))
        rows.append({
            "sid": sid,
            "symbol": filing["symbol"].strip(),
            "company_name": (filing.get("companyName") or "")[:100],
            "person": (x.get("person") or "")[:200],
            "person_category": x.get("person_category") or "",
            "transaction_type": _direction(x.get("tx_type")),
            "shares": _safe_float(x.get("shares")) or 0,
            "value_lakhs": value / 100000 if value else None,   # rupees → lakhs
            "trade_date": trade_date,
            "source": "nse_pit",
            "filing_id": filing["xmlFileName"].rsplit("/", 1)[-1],
        })
    return rows


def fetch_insider(start, end, dry_run=False):
    """List filings broadcast in [start, end], fetch the XBRL of each new universe
    filing, write insider_trades. Returns rows written (parsed, when dry_run)."""
    print(f"NSE Insider Trades: filings broadcast {start} → {end}")
    session = _http.warm_session(NSE_HOME, headers=SESSION_HEADERS)
    filings = list_filings(start, end, session)
    # NSE files hundreds of PIT disclosures a week — an empty list over a week-plus
    # window means the endpoint changed again, not a quiet market (the old API sat
    # empty for 5 months while the step logged SUCCESS).
    if not filings and (end - start).days >= 6:
        raise RuntimeError(f"NSE PIT list returned 0 filings for {start} → {end} — endpoint "
                           "likely changed; insider_trades is not being refreshed")

    sids = _http.sid_map()
    seen = set(read_sql("SELECT DISTINCT filing_id FROM insider_trades "
                        "WHERE filing_id IS NOT NULL")["filing_id"])
    todo = [f for f in filings
            if f.get("xmlFileName") and sids.get((f.get("symbol") or "").strip())
            and f["xmlFileName"].rsplit("/", 1)[-1] not in seen]
    print(f"  {len(filings)} filings · {len(todo)} new universe filings to fetch")

    today_iso = date.today().isoformat()
    rows, n_err, written = [], 0, 0
    for i, f in enumerate(todo, 1):
        try:
            resp = _http.polite_get(f["xmlFileName"], timeout=30)
            if resp is None:
                n_err += 1
                continue
            rows += _rows_for_filing(f, parse_xbrl(resp.content), sids[f["symbol"].strip()], today_iso)
        except Exception as e:                       # one bad filing must not sink the run
            n_err += 1
            print(f"    [{f.get('symbol')}] {type(e).__name__}: {str(e)[:80]}", flush=True)
        if len(rows) >= 500 or i == len(todo):
            if rows and not dry_run:
                written += insert_df(pd.DataFrame(rows), "insider_trades")
            elif dry_run:
                written += len(rows)
            rows = []
        if i % 100 == 0:
            print(f"  [{i}/{len(todo)}] written={written} errors={n_err}", flush=True)

    print(f"\nTotal: {len(todo)} filings fetched, {n_err} errors, {written} rows "
          f"{'parsed (dry run)' if dry_run else 'new'}")
    if todo and n_err > len(todo) / 2:
        raise RuntimeError(f"NSE PIT XBRL: {n_err}/{len(todo)} filings failed to fetch/parse")
    return written


def compute(dry_run=False):
    """Pipeline entry point — filings broadcast in the last DAILY_DAYS days. Trades are
    disclosed days-to-weeks after they happen; filtering by BROADCAST date (not trade
    date, as the old API did) means every filing is seen once, the day it appears."""
    end = date.today()
    return fetch_insider(end - timedelta(days=DAILY_DAYS), end, dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=DAILY_DAYS, help="broadcast window (default 10)")
    parser.add_argument("--from", dest="frm", help="backfill start YYYY-MM-DD")
    parser.add_argument("--to", dest="to", help="backfill end YYYY-MM-DD (default today)")
    parser.add_argument("--dry-run", action="store_true", help="list + parse, no write")
    args = parser.parse_args()
    end = date.fromisoformat(args.to) if args.to else date.today()
    start = date.fromisoformat(args.frm) if args.frm else end - timedelta(days=args.days)
    fetch_insider(start, end, dry_run=args.dry_run)
