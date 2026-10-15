"""
Alpha Signal v2 — NSE corporate announcements (feed nse_announcements; plan 0026 task 4.0).

The fallback route for BSE's AnnSubCategoryGetData, which Akamai has 403'd since 2026-10-13. Its own
table (`nse_announcements`): NSE's ids and `desc` taxonomy are not BSE's, and the governance and
credit-rating factors read `bse_announcements`, so rows are never mixed.

ENDPOINT (unofficial — the nseindia.com site's own backend; NSE needs the cookie warm on the home page):
    GET https://www.nseindia.com/api/corporate-announcements
        params: index=equities, from_date=DD-MM-YYYY, to_date=DD-MM-YYYY [, symbol=<NSE symbol>]
        response: JSON list of {symbol, sm_isin, sm_name, desc, attchmntText, an_dt, exchdisstime,
                  attchmntFile, seq_id, ...}; ~500 rows per trading day, no paging.
    Verified 2026-10-15: 2 days -> 1,058 rows; 2018-01-01..03 -> 351 rows (depth back to at least 2018-01).

PIT: `an_dt` is the announcement time; `dissem_dt` (exchdisstime) the exchange dissemination time
(absent in old rows). The stock is found by ISIN (scrip_master) first, then NSE symbol (stocks.ticker).
`category` is the watch category from config.NSE_ANNOUNCEMENT_CATEGORIES (+ text rules for generic descs).
Append-only: INSERT OR IGNORE on seq_id.

Usage:
    python -m sources.nse_announcements --days 7                  # daily refresh (run.sh forward)
    python -m sources.nse_announcements --from 2026-10-13 --to 2026-10-15
    python -m sources.nse_announcements --smoke                   # 3 stocks, 2 days, print, no write
    python -m sources.nse_announcements --backfill                # 2018-01-01 -> today, newest first
"""

import argparse
import re
import sys
from datetime import date, datetime, timedelta

import pandas as pd

import config
import runlog
from db import insert_df, read_sql
from hosts import HOSTS
from sources import _http

API = "https://www.nseindia.com/api/corporate-announcements"
WARM_URL = "https://www.nseindia.com/"
HEADERS = {**HOSTS["nse"]["headers"],
           "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"}
BACKFILL_START = "2018-01-01"
SMOKE_SYMBOLS = ["RELIANCE", "INFY", "NETWEB"]
COLS = ["seq_id", "symbol", "isin", "sid", "desc_category", "category", "subject", "an_dt", "dissem_dt",
        "attachment_url", "fetched_at"]

_TEXT_RULES = [(re.compile(p, re.I), c) for p, c in config.NSE_ANNOUNCEMENT_TEXT_RULES]


def categorize(desc, text):
    """NSE `desc` (+ subject text for generic descs) -> watch category."""
    d = (desc or "").strip().lower()
    if d in config.NSE_ANNOUNCEMENT_CATEGORIES:
        return config.NSE_ANNOUNCEMENT_CATEGORIES[d]
    if d in config.NSE_ANNOUNCEMENT_GENERIC_DESCS:
        for rx, cat in _TEXT_RULES:
            if rx.search(text or ""):
                return cat
    return "other"


def _ts(s):
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime((s or "").strip(), fmt).isoformat(sep=" ")
        except ValueError:
            continue
    return None


def sid_maps():
    """(ISIN -> sid, NSE symbol -> sid). scrip_master carries the ISIN; stocks.ticker the symbol."""
    m = read_sql("SELECT isin, sid FROM scrip_master WHERE sid IS NOT NULL AND isin IS NOT NULL")
    return dict(zip(m["isin"], m["sid"])), _http.sid_map("ticker")


def to_records(rows, isin_map, tick_map, fetched_at):
    out = []
    for x in rows:
        seq = str(x.get("seq_id") or "").strip()
        an = _ts(x.get("an_dt"))
        if not seq or not an:
            continue
        isin = (x.get("sm_isin") or "").strip() or None
        sym = (x.get("symbol") or "").strip().upper() or None
        text = (x.get("attchmntText") or "").strip() or None
        desc = (x.get("desc") or "").strip() or None
        out.append({
            "seq_id": seq, "symbol": sym, "isin": isin,
            "sid": isin_map.get(isin) or tick_map.get(sym),
            "desc_category": desc, "category": categorize(desc, text), "subject": text,
            "an_dt": an, "dissem_dt": _ts(x.get("exchdisstime")),
            "attachment_url": (x.get("attchmntFile") or "").strip() or None,
            "fetched_at": fetched_at,
        })
    return out


def fetch_range(session, frm, to, symbol=None):
    """Raw rows for [frm, to] (dates). A WAF block / non-JSON body raises, never reads as 'no rows'."""
    params = {"index": "equities", "from_date": frm.strftime("%d-%m-%Y"), "to_date": to.strftime("%d-%m-%Y")}
    if symbol:
        params["symbol"] = symbol
    r = _http.polite_request("GET", API, session=session, check=False, retries=1, timeout=60,
                             headers={"Referer": HEADERS["Referer"]}, params=params)
    if r.status_code != 200:
        raise RuntimeError(f"NSE corporate-announcements HTTP {r.status_code} ({frm}..{to})")
    try:
        j = r.json()
    except ValueError:
        raise RuntimeError(f"NSE corporate-announcements non-JSON body ({frm}..{to}): {r.text[:60]!r}")
    if isinstance(j, dict):
        j = j.get("data") or []
    if not isinstance(j, list):
        raise RuntimeError(f"NSE corporate-announcements unexpected shape {type(j).__name__}")
    return j


def _store(records):
    if not records:
        return 0
    return insert_df(pd.DataFrame([[r[c] for c in COLS] for r in records], columns=COLS),
                     "nse_announcements", lock_retries=5)


def _chunks(start, end, step):
    """[from, to] windows of `step` days, NEWEST first."""
    cur = end
    while cur >= start:
        lo = max(start, cur - timedelta(days=step - 1))
        yield lo, cur
        cur = lo - timedelta(days=1)


def harvest(frm, to, step=1, symbols=None, dry_run=False):
    """Pull [frm, to]; returns (seen, new, errors, windows)."""
    session = _http.warm_session(WARM_URL, headers=HEADERS)
    isin_map, tick_map = sid_maps()
    fetched_at = datetime.now().isoformat(timespec="seconds")
    seen = new = errs = n_win = 0
    jobs = [(w, s) for w in _chunks(frm, to, step) for s in (symbols or [None])]
    for (lo, hi), sym in jobs:
        n_win += 1
        try:
            raw = fetch_range(session, lo, hi, sym)
        except Exception as e:
            errs += 1
            print(f"  [{lo}..{hi}] ERROR {type(e).__name__}: {str(e)[:80]}", flush=True)
            runlog.item_error("nse announcements", f"{lo}..{hi}", e)
            continue
        recs = to_records(raw, isin_map, tick_map, fetched_at)
        seen += len(recs)
        n = 0 if dry_run else _store(recs)
        new += n
        if recs:
            print(f"  [{lo}..{hi}] {sym or 'all'}: {len(recs):>4} seen, {n:>4} new", flush=True)
        if dry_run and recs:
            print(f"      sample: {recs[0]['symbol']} | {recs[0]['desc_category']} -> {recs[0]['category']} | "
                  f"sid={recs[0]['sid']}")
    return seen, new, errs, n_win


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--days", type=int, help="recent N days (daily refresh)")
    p.add_argument("--from", dest="frm")
    p.add_argument("--to", dest="to")
    p.add_argument("--backfill", action="store_true", help=f"{BACKFILL_START} -> today, newest first")
    p.add_argument("--smoke", action="store_true", help="3 stocks, 2 days; with --write stores to ALPHA_DB")
    p.add_argument("--write", action="store_true", help="smoke: store rows (use a scratch ALPHA_DB)")
    p.add_argument("--chunk-days", type=int, default=1)
    a = p.parse_args(argv)

    today = date.today()
    symbols = None
    if a.smoke:
        frm, to, symbols = today - timedelta(days=2), today - timedelta(days=1), SMOKE_SYMBOLS
    elif a.backfill:
        frm, to = date.fromisoformat(BACKFILL_START), today
    elif a.frm and a.to:
        frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    else:
        frm, to = today - timedelta(days=a.days or 7), today

    seen, new, errs, n_win = harvest(frm, to, a.chunk_days, symbols, dry_run=a.smoke and not a.write)
    print(f"\nDone. {frm}..{to} seen={seen} new_rows={new} errors={errs}/{n_win}")
    if n_win and errs == n_win:
        raise RuntimeError(f"NSE announcements: all {errs} requests failed - endpoint blocked or moved")
    if seen == 0:
        raise RuntimeError(f"NSE announcements: 0 rows for {frm}..{to} - endpoint moved or blocked?")
    runlog.note("nse_announcements done", seen=seen, new=new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
