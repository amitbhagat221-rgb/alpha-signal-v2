"""
Alpha Signal v2 — Earnings-call transcript harvester (Plan 0002 §3.1d, Path B)

Discovers earnings-call transcripts via the Screener.in *concall* section, resolves
each to the underlying BSE-hosted PDF, extracts the text, and stores it as a
content-addressed document in the `transcripts` table.

CHAIN (validated 2026-06-06):
    screener.in/company/<TICKER>/consolidated/   → "Documents → Concalls" block
      each <li> = a concall (period label "Apr 2026") + links: Transcript / PPT / REC / Notes
    Transcript link → https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=<guid>.pdf  (HTML wrapper)
      → real PDF at https://www.bseindia.com/xml-data/corpfiling/{AttachLive|AttachHis}/<guid>.pdf
      → pdfplumber extracts clean text

DESIGN: this is a DOCUMENT STORE, not a parsed schema. We store metadata + one
raw_text blob, content-addressed by sha256, append-only (INSERT OR IGNORE on
(sid, source_url)). Tone / forward-looking / uncertainty factors are derived
DOWNSTREAM in signals/nlp_scores.py — NOT here. (See schema.sql `transcripts`.)

Auth: reuses the Screener session from sources.screener_pull (cookie jar).
Rate-limited: ≥2s between stocks, ≥1.5s between BSE PDF downloads (CLAUDE.md).
Idempotent: skips (sid, source_url) pairs already stored.

Usage:
    python -m sources.transcripts_pull --smoke                  # 3 well-known stocks, recent 2 each
    python -m sources.transcripts_pull --sid INFY               # one stock, all transcripts
    python -m sources.transcripts_pull --sid INFY --max-docs 4  # one stock, recent 4
    python -m sources.transcripts_pull --tier LARGE --max-docs 8
    python -m sources.transcripts_pull --universe --max-docs 8  # full backfill (recent 8 each)
    python -m sources.transcripts_pull --sid INFY --dry-run     # parse + resolve, don't download/write
"""

import argparse
import hashlib
import io
import random
import re
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import get_db, read_sql
from sources.screener_pull import (
    COMPANY_CONSOLIDATED_URL,
    COMPANY_URL,
    check_auth,
    make_session,
)

# BSE serves filing PDFs only with a browser UA + a bseindia referer.
BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://www.bseindia.com/",
}
ATTACH_BASES = ("AttachLive", "AttachHis")  # recent filings live; older ones archived
DELAY_BETWEEN_STOCKS = (2.0, 3.5)
DELAY_BETWEEN_PDFS = (1.5, 3.0)
SMOKE_SIDS = ("INFY", "RELI", "TCS")

# doc_type label (lowercased) → we keep these. 'rec' (YouTube video) is skipped.
KEEP_LABELS = {"transcript": "transcript", "notes": "notes", "ppt": "ppt"}


# ─────────────────────────────── parsing ───────────────────────────────

def _parse_concalls(html: str) -> list[dict]:
    """Parse the Screener 'Concalls' block → list of {period_label, doc_date, doc_type, url}.

    One row per (concall, document-link). Only BSE AnnPdfOpen / direct-PDF links are
    kept (YouTube 'REC' links are dropped). doc_date = first-of-month from the label.
    """
    soup = BeautifulSoup(html, "html.parser")
    block = soup.find("div", class_=re.compile(r"\bconcalls\b"))
    if block is None:
        h = soup.find(lambda t: t.name in ("h2", "h3")
                      and "concall" in t.get_text(strip=True).lower())
        block = h.find_parent("div") if h else None
    if block is None:
        return []

    out = []
    for li in block.find_all("li"):
        date_div = li.find("div")
        period_label = date_div.get_text(strip=True) if date_div else None
        doc_date = _label_to_date(period_label)
        for a in li.find_all("a"):
            label = a.get_text(strip=True).lower()
            href = a.get("href") or ""
            doc_type = KEEP_LABELS.get(label)
            if not doc_type:
                continue  # skip REC / unknown
            if "bseindia.com" not in href and not href.lower().endswith(".pdf"):
                continue  # skip non-PDF hosts (e.g. tcs.com PPT, youtube)
            out.append({
                "period_label": period_label,
                "doc_date": doc_date,
                "doc_type": doc_type,
                "url": href,
            })
    return out


def _label_to_date(label: str | None) -> str | None:
    """'Apr 2026' → '2026-04-01'. Returns None if unparseable."""
    if not label:
        return None
    for fmt in ("%b %Y", "%B %Y", "%b %y"):
        try:
            return datetime.strptime(label.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


_DATE_PATTERNS = [
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s+(\d{4})\b"), "%d %B %Y"),
    (re.compile(r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b"), "%B %d %Y"),
    (re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b"), "%d %m %Y"),
]


def _parse_announce_date(text: str) -> str | None:
    """Best-effort exact date from the first page (e.g. 'April 27, 2026'). None if not found."""
    head = (text or "")[:1500]
    for rx, fmt in _DATE_PATTERNS:
        m = rx.search(head)
        if not m:
            continue
        raw = " ".join(m.groups())
        for f in (fmt, fmt.replace("%B", "%b")):
            try:
                return datetime.strptime(raw, f).date().isoformat()
            except ValueError:
                continue
    return None


# ──────────────────── BSE filing-date join (look-ahead) ─────────────────
# The transcript PDF is a BSE corpfiling attachment whose GUID (Pname=<guid>.pdf)
# is the SAME key as bse_announcements.attachment. Matching on it gives the real
# filing dt_tm — the look-ahead-safe availability date — instead of the
# first-of-month doc_date proxy (which leads the true filing by ~2 weeks). This is
# the transcript analogue of the PEAD date-swap (signals/pead.py). Next-3 #1c.

def _guid_from_url(url: str | None) -> str | None:
    """Extract the BSE attachment GUID (`<guid>.pdf`) from a concall/PDF URL.

    `...AnnPdfOpen.aspx?Pname=<guid>.pdf` → '<guid>.pdf'; a direct
    `.../AttachLive/<guid>.pdf` → '<guid>.pdf'. None for non-BSE direct PDFs
    (e.g. 'qect_Q2_2020-21.pdf' on a company host — no bse_announcements row).
    """
    if not url:
        return None
    m = re.search(r"Pname=([^\"&]+)", url)
    if m:
        return m.group(1)
    if url.lower().endswith(".pdf") and "bseindia.com" in url:
        return url.rsplit("/", 1)[-1]
    return None


def _filing_dates_for_guids(guids) -> dict:
    """Map {guid → date(dt_tm)} from bse_announcements for the given attachment GUIDs.

    dt_tm == dissem_dt (public dissemination time) on BSE; the date part is the
    availability date. Returns the earliest dt_tm if a GUID appears twice.
    """
    guids = [g for g in dict.fromkeys(guids) if g]
    if not guids:
        return {}
    out = {}
    CHUNK = 800  # stay under SQLite's variable limit
    for i in range(0, len(guids), CHUNK):
        chunk = guids[i:i + CHUNK]
        ph = ",".join("?" * len(chunk))
        rows = read_sql(
            f"SELECT attachment, MIN(date(dt_tm)) AS d FROM bse_announcements "
            f"WHERE attachment IN ({ph}) AND dt_tm IS NOT NULL GROUP BY attachment",
            params=chunk)
        for r in rows.itertuples(index=False):
            if r.d:
                out[r.attachment] = r.d
    return out


def backfill_filing_dates(only_null: bool = True) -> int:
    """Backfill transcripts.bse_filing_date from the BSE GUID join. Idempotent.

    `only_null=True` touches rows where bse_filing_date IS NULL (cheap re-runs as
    the BSE stream deepens); False recomputes all. Returns rows updated.
    """
    where = "WHERE bse_filing_date IS NULL" if only_null else ""
    docs = read_sql(f"SELECT rowid AS rid, source_url, pdf_url FROM transcripts {where}")
    if docs.empty:
        print("backfill_filing_dates: nothing to do.")
        return 0
    docs["guid"] = docs["source_url"].map(_guid_from_url)
    docs.loc[docs["guid"].isna(), "guid"] = docs["pdf_url"].map(_guid_from_url)
    gmap = _filing_dates_for_guids(docs["guid"].dropna().tolist())
    updates = [(gmap[g], rid)
               for rid, g in zip(docs["rid"], docs["guid"])
               if g in gmap]
    if updates:
        with get_db() as conn:
            conn.executemany(
                "UPDATE transcripts SET bse_filing_date = ? WHERE rowid = ?", updates)
    n_total = len(docs)
    print(f"backfill_filing_dates: {len(updates)}/{n_total} rows filled "
          f"({len(updates)/n_total*100:.1f}% GUID-matched to bse_announcements)")
    return len(updates)


# ─────────────────────────── fetch + extract ───────────────────────────

def _resolve_and_download(session, ann_url: str) -> tuple[str | None, bytes | None]:
    """Resolve a Screener concall link to the real BSE PDF bytes.

    AnnPdfOpen.aspx?Pname=<guid>.pdf is an HTML wrapper; the file lives at
    corpfiling/{AttachLive|AttachHis}/<guid>.pdf. A direct .pdf URL is fetched as-is.
    Returns (pdf_url, pdf_bytes) or (None, None) on failure.
    """
    m = re.search(r"Pname=([^\"&]+)", ann_url)
    if m:
        guid = m.group(1)
        for base in ATTACH_BASES:
            pdf_url = f"https://www.bseindia.com/xml-data/corpfiling/{base}/{guid}"
            try:
                r = session.get(pdf_url, headers=BSE_HEADERS, timeout=40)
            except Exception:
                continue
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                return pdf_url, r.content
        return None, None
    # direct PDF link
    if ann_url.lower().endswith(".pdf"):
        try:
            r = session.get(ann_url, headers=BSE_HEADERS, timeout=40)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                return ann_url, r.content
        except Exception:
            return None, None
    return None, None


def _extract_pdf_text(pdf_bytes: bytes, max_pages: int = 80) -> tuple[str, int]:
    """Extract text via pdfplumber. Returns (text, n_pages). ('', 0) on failure."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            n_pages = len(pdf.pages)
            parts = [(p.extract_text() or "") for p in pdf.pages[:max_pages]]
        return "\n".join(parts).strip(), n_pages
    except Exception:
        return "", 0


def _fetch_company_html(session, ticker: str) -> str | None:
    """GET the consolidated company page, falling back to standalone."""
    for url in (COMPANY_CONSOLIDATED_URL.format(ticker=ticker),
                COMPANY_URL.format(ticker=ticker)):
        try:
            r = session.get(url, timeout=25)
        except Exception:
            continue
        if r.status_code == 200 and len(r.text) > 2000:
            return r.text
    return None


# ──────────────────────────────── store ────────────────────────────────

def _existing_urls(sid: str) -> set[str]:
    df = read_sql("SELECT source_url FROM transcripts WHERE sid = ?", params=[sid])
    return set(df["source_url"].tolist()) if not df.empty else set()


def _store_rows(rows: list[dict], max_retries: int = 6) -> int:
    """INSERT OR IGNORE content-addressed transcript rows. Returns rows actually written.

    Retries on transient `database is locked`. get_db() already sets
    busy_timeout=5000, but *write-write* contention (the nightly backup's VACUUM,
    the daily pipeline, a DuckDB refresh) raises SQLITE_BUSY immediately for
    deadlock-avoidance regardless of the timeout. A linear backoff covers that
    gap so a multi-hour harvest is never lost to a one-second lock.
    """
    if not rows:
        return 0
    cols = ["sid", "doc_type", "period_label", "doc_date", "announce_date",
            "bse_filing_date", "source_url", "pdf_url", "n_pages", "char_count",
            "raw_text", "sha256", "fetched_at"]
    payload = [tuple(r.get(c) for c in cols) for r in rows]
    sql = (f"INSERT OR IGNORE INTO transcripts ({','.join(cols)}) "
           f"VALUES ({','.join('?' * len(cols))})")
    for attempt in range(max_retries):
        try:
            with get_db() as conn:
                before = conn.total_changes
                conn.executemany(sql, payload)
                return conn.total_changes - before
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or attempt == max_retries - 1:
                raise
            time.sleep(2.0 * (attempt + 1))  # 2,4,6,8,10s
    return 0


# ──────────────────────────────── pull ─────────────────────────────────

def pull_one(session, sid: str, ticker: str, max_docs: int | None = None,
             doc_types=("transcript",), dry_run: bool = False) -> dict:
    """Harvest transcripts for one stock. Returns a small report dict."""
    html = _fetch_company_html(session, ticker)
    if html is None:
        return {"sid": sid, "ticker": ticker, "status": "no_page", "found": 0, "new": 0}

    links = [d for d in _parse_concalls(html) if d["doc_type"] in doc_types]
    # newest first (Screener lists newest first; keep that order), cap to max_docs
    if max_docs:
        links = links[:max_docs]
    if not links:
        return {"sid": sid, "ticker": ticker, "status": "no_concalls", "found": 0, "new": 0}

    have = _existing_urls(sid)
    todo = [d for d in links if d["url"] not in have]
    if dry_run:
        return {"sid": sid, "ticker": ticker, "status": "dry_run",
                "found": len(links), "new_candidates": len(todo),
                "sample": [(d["period_label"], d["doc_type"], d["url"][:70]) for d in todo[:3]]}

    rows, fetched_at = [], datetime.now().isoformat(timespec="seconds")
    for i, d in enumerate(todo):
        if i:
            time.sleep(random.uniform(*DELAY_BETWEEN_PDFS))
        pdf_url, pdf_bytes = _resolve_and_download(session, d["url"])
        if not pdf_bytes:
            continue
        text, n_pages = _extract_pdf_text(pdf_bytes)
        if not text:
            continue
        rows.append({
            "sid": sid,
            "doc_type": d["doc_type"],
            "period_label": d["period_label"],
            "doc_date": d["doc_date"],
            "announce_date": _parse_announce_date(text),
            "bse_filing_date": None,  # stamped below from the BSE GUID join
            "source_url": d["url"],
            "pdf_url": pdf_url,
            "n_pages": n_pages,
            "char_count": len(text),
            "raw_text": text,
            "sha256": hashlib.sha256(text.encode("utf-8", "replace")).hexdigest(),
            "fetched_at": fetched_at,
        })
    # Stamp the look-ahead-safe filing date (real BSE dt_tm via the PDF GUID). One
    # batched lookup per stock; leaves NULL if the filing isn't in the stream yet
    # (a later backfill_filing_dates() pass fills it; nlp_scores COALESCEs to
    # announce_date meanwhile). Next-3 #1c.
    if rows:
        gmap = _filing_dates_for_guids(
            [_guid_from_url(r["source_url"]) or _guid_from_url(r["pdf_url"]) for r in rows])
        for r in rows:
            g = _guid_from_url(r["source_url"]) or _guid_from_url(r["pdf_url"])
            r["bse_filing_date"] = gmap.get(g)
    written = _store_rows(rows)
    return {"sid": sid, "ticker": ticker, "status": "ok",
            "found": len(links), "candidates": len(todo),
            "downloaded": len(rows), "new": written}


def _targets(args) -> pd.DataFrame:
    if args.smoke:
        return read_sql(
            f"SELECT sid, ticker FROM stocks WHERE sid IN ({','.join('?' * len(SMOKE_SIDS))}) "
            "AND ticker IS NOT NULL", params=list(SMOKE_SIDS))
    if args.sid:
        return read_sql("SELECT sid, ticker FROM stocks WHERE sid = ?", params=[args.sid])
    if args.deepen:
        # Re-visit every stock we already hold a transcript for — these are proven
        # concall-doers — and (with no --max-docs) pull the FULL history Screener
        # exposes, not just the most-recent N. INSERT OR IGNORE makes this additive:
        # the 4 we already have are skipped, only the older quarters get fetched.
        # Market-cap ordered so large/mid caps (which back-populate the thin
        # 2022-2024 anchors) land first.
        return read_sql(
            "SELECT DISTINCT t.sid, s.ticker FROM transcripts t "
            "JOIN stocks s ON s.sid = t.sid "
            "WHERE s.ticker IS NOT NULL ORDER BY s.market_cap_cr DESC")
    if args.tier or args.universe:
        # Optional analyst-coverage gate: a stock with ≥N analysts almost always
        # holds a concall; one with none almost never does. For SMALL this skips
        # ~900 transcript-less names (no wasted fetches / IP-block risk).
        min_an = getattr(args, "min_analysts", 0) or 0
        join = ("JOIN analyst_consensus a ON s.sid = a.sid AND a.total_analysts >= ? "
                if min_an > 0 else "")
        where, params = "s.ticker IS NOT NULL", []
        if min_an > 0:
            params.append(min_an)          # JOIN '?' precedes WHERE '?' in SQL text
        if args.tier:
            where += " AND s.cap_tier = ?"
            params.append(args.tier)
        return read_sql(
            f"SELECT s.sid, s.ticker FROM stocks s {join}WHERE {where} "
            "ORDER BY s.market_cap_cr DESC", params=params)
    return pd.DataFrame()


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--smoke", action="store_true", help="3 well-known stocks, recent 2 docs each")
    p.add_argument("--sid", help="single stock SID")
    p.add_argument("--tier", choices=["LARGE", "MID", "SMALL", "MICRO"])
    p.add_argument("--universe", action="store_true")
    p.add_argument("--deepen", action="store_true",
                   help="re-visit every stock already in `transcripts`, uncapped — "
                        "pull the FULL concall history Screener exposes (back-populates "
                        "the thin 2022-2024 backtest anchors). Additive (INSERT OR IGNORE).")
    p.add_argument("--max-docs", type=int, default=None, help="recent N concalls per stock")
    p.add_argument("--doc-types", default="transcript",
                   help="comma list: transcript,notes,ppt (default: transcript)")
    p.add_argument("--min-analysts", type=int, default=0,
                   help="only stocks with >= N analysts (concall-likely; e.g. 1 for SMALL)")
    p.add_argument("--limit", type=int, default=None, help="cap number of stocks (debug)")
    p.add_argument("--dry-run", action="store_true", help="parse + resolve, no download/write")
    p.add_argument("--backfill-filing-dates", action="store_true",
                   help="match existing transcripts to bse_announcements by PDF GUID and "
                        "fill bse_filing_date (the look-ahead-safe filing date); no fetching")
    args = p.parse_args()

    # Maintenance mode: no Screener auth / fetching needed — pure DB join.
    if args.backfill_filing_dates:
        backfill_filing_dates(only_null=True)
        return 0

    if args.smoke and args.max_docs is None:
        args.max_docs = 2
    doc_types = tuple(t.strip() for t in args.doc_types.split(",") if t.strip())

    session = make_session()
    ok, detail = check_auth(session)
    if not ok:
        raise RuntimeError(f"Screener auth failed: {detail}. Run `python -m sources.screener_pull --login`.")

    tgt = _targets(args)
    if tgt.empty:
        print("No targets. Use --smoke / --sid / --tier / --universe.")
        return 1
    if args.limit:
        tgt = tgt.head(args.limit)

    print(f"transcripts_pull — {len(tgt)} stock(s), doc_types={doc_types}, "
          f"max_docs={args.max_docs}, dry_run={args.dry_run}")
    tot_new = tot_dl = tot_cand = 0
    for i, r in enumerate(tgt.itertuples(index=False)):
        if i:
            time.sleep(random.uniform(*DELAY_BETWEEN_STOCKS))
        try:
            rep = pull_one(session, r.sid, r.ticker, max_docs=args.max_docs,
                           doc_types=doc_types, dry_run=args.dry_run)
        except Exception as e:
            # One stock's failure (DB lock, network drop, malformed PDF) must never
            # kill a multi-hour harvest. Log and carry on — the run is idempotent,
            # so a later --deepen pass re-attempts whatever was left incomplete.
            rep = {"sid": r.sid, "ticker": r.ticker,
                   "status": f"ERROR:{type(e).__name__}", "found": 0, "new": 0}
            print(f"  [{r.sid:>6} {r.ticker:<14}] {rep}  ({e})", flush=True)
            continue
        tot_new += rep.get("new", 0)
        tot_dl += rep.get("downloaded", 0)
        tot_cand += rep.get("candidates", 0)
        print(f"  [{r.sid:>6} {r.ticker:<14}] {rep}", flush=True)

    if not args.dry_run:
        print(f"\nDone. candidates={tot_cand} downloaded={tot_dl} new_rows={tot_new}")
        # silent-failure guard: raise only if there WERE new docs to fetch but none
        # landed (auth/parser/BSE break). All-skipped re-runs (candidates==0) are fine.
        if tot_cand > 0 and tot_dl == 0 and len(tgt) > 3:
            raise RuntimeError("transcripts_pull: had new transcript candidates but "
                               "downloaded 0 — check auth / parser / BSE reachability.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
