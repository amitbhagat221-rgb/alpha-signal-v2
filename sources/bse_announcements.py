"""
Alpha Signal v2 — BSE corporate-announcement EVENT-STREAM harvester.

Harvests the full BSE corporate-announcements feed — exchange-verified, timestamped,
survivorship-complete (delisted names included), depth back to 2018 — into the
`bse_announcements` table. ONE new data category (event-driven) that seeds several
factor families at once: PEAD announce-dates, transcript look-ahead fix, credit-
rating-change, promoter-pledge events, auditor/KMP resignations, governance signals
(critical_news materiality + disclosure latency).

ENDPOINT (unofficial — the public bseindia.com site's own backend; see
docs/reference/data-playbook.md "BSE announcement event stream"):
    GET https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w
      params: pageno, strCat=-1, subcategory=-1, strPrevDate=YYYYMMDD,
              strToDate=YYYYMMDD, strSearch=P, strscrip='', strType=C
      headers: browser UA + Referer/Origin bseindia.com, warmed session cookie
      response: {"Table":[...rows...], "Table1":[{"ROWCNT": <total>}]}  (50 rows/page)

DESIGN: date-iterating, no-scrip ("all announcements" mode) → universe-complete and
survivorship-free by construction. Metadata only (no PDF download — transcripts.py
handles selective PDF fetch). Idempotent: INSERT OR IGNORE on news_id, lock-retry on
the write. Universe-join (scrip_cd → sid) is DEFERRED to a static scrip-master map.

Rate-limited per CLAUDE.md: warmed session, browser headers, ~1.5-3s between pages,
single-threaded. Same IP-block hygiene as transcripts_pull.

Usage:
    python -m sources.bse_announcements --days 7              # recent 7 days (daily refresh)
    python -m sources.bse_announcements --from 2026-01-01 --to 2026-06-08
    python -m sources.bse_announcements --backfill            # full 2018-01-01 → today (newest first)
    python -m sources.bse_announcements --smoke               # one recent day, no write
"""

import argparse
import random
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import get_db

API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
WARM_URL = "https://www.bseindia.com/corporates/ann.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
    "Accept": "application/json, text/plain, */*",
}
DELAY_BETWEEN_PAGES = (1.5, 3.0)
PAGE_SIZE = 50
BACKFILL_START = "2018-01-01"

# BSE row field → our column
COLS = ["news_id", "scrip_cd", "sid", "company_name", "headline", "news_sub",
        "category", "subcategory", "announcement_type", "critical_news",
        "dt_tm", "submission_dt", "dissem_dt", "time_diff", "quarter_id",
        "attachment", "pdf_flag", "has_investor_ppt", "has_audio_video",
        "nsurl", "fetched_at"]


def make_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(WARM_URL, timeout=20)  # warm the cookie jar (BSE bot-gate)
    except Exception:
        pass
    return s


def _row_to_record(x, fetched_at):
    def _flag(v):
        return 1 if v not in (None, "", "0", 0, "N", "False", False) else 0
    return {
        "news_id":           str(x.get("NEWSID") or x.get("BSENewsid") or "").strip() or None,
        "scrip_cd":          x.get("SCRIP_CD"),
        "sid":               None,  # filled by the deferred scrip-master map
        "company_name":      (x.get("SLONGNAME") or "").strip() or None,
        "headline":          (x.get("HEADLINE") or "").strip() or None,
        "news_sub":          (x.get("NEWSSUB") or "").strip() or None,
        "category":          (x.get("CATEGORYNAME") or "").strip() or None,
        "subcategory":       (x.get("SUBCATNAME") or "").strip() or None,
        "announcement_type": (x.get("ANNOUNCEMENT_TYPE") or "").strip() or None,
        "critical_news":     _flag(x.get("CRITICALNEWS")),
        "dt_tm":             x.get("DT_TM") or x.get("NEWS_DT"),
        "submission_dt":     x.get("News_submission_dt"),
        "dissem_dt":         x.get("DissemDT"),
        "time_diff":         x.get("TimeDiff"),
        "quarter_id":        x.get("QUARTER_ID"),
        "attachment":        (x.get("ATTACHMENTNAME") or "").strip() or None,
        "pdf_flag":          _flag(x.get("PDFFLAG")),
        "has_investor_ppt":  _flag(x.get("Investor_Presentation")),
        "has_audio_video":   _flag(x.get("AUDIO_VIDEO_FILE")),
        "nsurl":             (x.get("NSURL") or "").strip() or None,
        "fetched_at":        fetched_at,
    }


def _fetch_page(session, frm, to, pageno):
    """Return (rows, total_count). frm/to are YYYYMMDD strings."""
    params = {"pageno": pageno, "strCat": "-1", "subcategory": "-1",
              "strPrevDate": frm, "strToDate": to, "strSearch": "P",
              "strscrip": "", "strType": "C"}
    r = session.get(API, params=params, timeout=30)
    j = r.json()
    if not isinstance(j, dict):
        return [], 0
    rows = j.get("Table") or []
    meta = j.get("Table1") or []
    total = meta[0].get("ROWCNT", 0) if meta and isinstance(meta[0], dict) else 0
    return rows, total


def _store(records, max_retries=6):
    """INSERT OR IGNORE with lock-retry (same hardening as transcripts_pull)."""
    records = [r for r in records if r.get("news_id")]
    if not records:
        return 0
    sql = (f"INSERT OR IGNORE INTO bse_announcements ({','.join(COLS)}) "
           f"VALUES ({','.join('?' * len(COLS))})")
    payload = [tuple(r.get(c) for c in COLS) for r in records]
    for attempt in range(max_retries):
        try:
            with get_db() as conn:
                before = conn.total_changes
                conn.executemany(sql, payload)
                return conn.total_changes - before
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or attempt == max_retries - 1:
                raise
            time.sleep(2.0 * (attempt + 1))
    return 0


def harvest_range(session, frm_iso, to_iso, dry_run=False):
    """Harvest one date range (inclusive). Returns (rows_seen, rows_new)."""
    frm = frm_iso.replace("-", "")
    to = to_iso.replace("-", "")
    fetched_at = datetime.now().isoformat(timespec="seconds")
    rows, total = _fetch_page(session, frm, to, 1)
    if not rows:
        return 0, 0
    n_pages = max(1, -(-total // PAGE_SIZE))  # ceil
    all_rows = list(rows)
    for pg in range(2, n_pages + 1):
        time.sleep(random.uniform(*DELAY_BETWEEN_PAGES))
        try:
            more, _ = _fetch_page(session, frm, to, pg)
        except Exception as e:
            print(f"    page {pg} err: {str(e)[:60]}", flush=True)
            continue
        if not more:
            break
        all_rows.extend(more)
    recs = [_row_to_record(x, fetched_at) for x in all_rows]
    if dry_run:
        return len(recs), 0
    new = _store(recs)
    return len(recs), new


def _day_iter(start_iso, end_iso):
    """Yield single ISO dates NEWEST first. The all-scrip/all-category 'firehose'
    endpoint only honours a SINGLE day per call (multi-day ranges return 0), so the
    harvest is day-by-day. Weekends/holidays return 0 rows in one cheap request."""
    start = datetime.fromisoformat(start_iso).date()
    cur = datetime.fromisoformat(end_iso).date()
    while cur >= start:
        yield cur.isoformat()
        cur -= timedelta(days=1)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--days", type=int, help="recent N days (daily refresh)")
    p.add_argument("--from", dest="frm", help="from date YYYY-MM-DD")
    p.add_argument("--to", dest="to", help="to date YYYY-MM-DD")
    p.add_argument("--backfill", action="store_true", help=f"full {BACKFILL_START} → today, newest first")
    p.add_argument("--smoke", action="store_true", help="one recent day, no write")
    args = p.parse_args()

    today = date.today().isoformat()
    session = make_session()

    if args.smoke:
        seen, _ = harvest_range(session, (date.today() - timedelta(days=1)).isoformat(), today, dry_run=True)
        print(f"smoke: {seen} announcements seen for the last day (no write).")
        return 0

    # Resolve the [from, to] window, then iterate single days (newest first).
    if args.backfill:
        frm, to = BACKFILL_START, today
        print(f"BSE announcements backfill — single-day walk {today} → {BACKFILL_START} (newest first)")
    elif args.frm and args.to:
        frm, to = args.frm, args.to
    else:
        n = args.days or 7
        frm = (date.today() - timedelta(days=n)).isoformat()
        to = today

    days = list(_day_iter(frm, to))
    tot_seen = tot_new = 0
    for i, d in enumerate(days, 1):
        try:
            seen, new = harvest_range(session, d, d)
        except Exception as e:
            print(f"  [{d}] ERROR {type(e).__name__}: {str(e)[:70]}", flush=True)
            time.sleep(random.uniform(*DELAY_BETWEEN_PAGES))
            continue
        tot_seen += seen; tot_new += new
        if seen or i % 30 == 0:   # skip silent weekend/holiday spam, but heartbeat every 30 days
            print(f"  [{i:4d}/{len(days)}] {d}: {seen:>4} seen, {new:>4} new (cum new={tot_new})", flush=True)
        time.sleep(random.uniform(*DELAY_BETWEEN_PAGES))
    print(f"\nDone. {frm}..{to}  seen={tot_seen} new_rows={tot_new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
