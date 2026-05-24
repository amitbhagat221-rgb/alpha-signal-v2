"""
Alpha Signal v2 — Regulatory Event Historical Harvester

Four data sources for 3-year regulatory event backfill:

1. Google News RSS:  ~5,000-10,000 articles via topic × date-window queries
2. RBI Circulars:    ~870 notifications via ID iteration (12500-13368)
3. Wayback Machine:  ~450 articles from archived ET Markets RSS snapshots
4. PIB Releases:     ~2,000+ press releases via PRID iteration

All stored in regulatory_events table. Then classified by regulatory_classifier.py.

Usage:
    python -m sources.regulatory_harvester --source google     # Google News RSS
    python -m sources.regulatory_harvester --source rbi        # RBI circulars
    python -m sources.regulatory_harvester --source wayback    # Wayback Machine
    python -m sources.regulatory_harvester --source pib        # PIB releases
    python -m sources.regulatory_harvester --all               # everything
    python -m sources.regulatory_harvester --dry-run           # show plan
"""

import argparse
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from html import unescape

import pandas as pd
import requests

from config import API
from db import get_db, insert_df, read_sql

USER_AGENT = API["user_agent"]
HEADERS = {"User-Agent": USER_AGENT}


# ═══════════════════════════════════════════════════
# 1. GOOGLE NEWS RSS
# ═══════════════════════════════════════════════════

GOOGLE_TOPICS = [
    # Monetary / banking
    "RBI+monetary+policy+India",
    "RBI+repo+rate+India",
    "India+banking+regulation+NBFC",
    "RBI+circular+notification",
    "India+credit+growth+lending",
    # Securities / markets
    "SEBI+circular+regulation",
    "SEBI+mutual+fund+India",
    "India+FPI+FII+regulation",
    "India+stock+market+regulation",
    # Trade / tariffs
    "India+import+duty+tariff",
    "India+export+ban+restriction",
    "India+customs+duty+change",
    "India+anti+dumping+duty",
    # Industrial policy
    "India+PLI+scheme+manufacturing",
    "India+defense+indigenization+policy",
    "India+mining+auction+policy",
    "India+auto+EV+policy+regulation",
    # Energy / environment
    "India+ethanol+blending+biofuel",
    "India+renewable+energy+solar+policy",
    "India+coal+mining+regulation",
    "India+oil+gas+regulation+policy",
    "India+power+electricity+tariff+regulation",
    # Agriculture
    "India+agriculture+MSP+policy",
    "India+fertilizer+subsidy+policy",
    "India+sugar+export+regulation",
    # Tax / fiscal
    "India+budget+tax+policy+stock",
    "GST+council+rate+change+India",
    "India+corporate+tax+change",
    # Sector-specific
    "India+pharma+drug+regulation+DPCO",
    "India+telecom+TRAI+regulation",
    "India+real+estate+RERA+regulation",
    "India+infrastructure+highway+policy",
    "India+steel+cement+duty+regulation",
    "India+chemical+regulation+policy",
    # Cross-cutting
    "India+cabinet+approval+economic",
    "India+Supreme+Court+ruling+economic",
    "India+insolvency+NCLT+IBC",
    "India+disinvestment+privatization",
    "India+semiconductor+electronics+policy",
]

# 6-month windows covering 3 years
GOOGLE_WINDOWS = [
    ("2023-04-01", "2023-09-30"),
    ("2023-10-01", "2024-03-31"),
    ("2024-04-01", "2024-09-30"),
    ("2024-10-01", "2025-03-31"),
    ("2025-04-01", "2025-09-30"),
    ("2025-10-01", "2026-04-10"),
]


def _parse_google_rss(xml_text):
    """Parse Google News RSS XML into list of dicts."""
    items = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            source_el = item.find("source")
            source = source_el.text if source_el is not None else "google_news"
            description = item.findtext("description", "")

            # Clean HTML from description
            description = re.sub(r"<[^>]+>", "", unescape(description))

            # Parse date
            parsed_date = None
            if pub_date:
                try:
                    parsed_date = datetime.strptime(
                        pub_date, "%a, %d %b %Y %H:%M:%S %Z"
                    ).isoformat()
                except ValueError:
                    try:
                        parsed_date = datetime.strptime(
                            pub_date[:25], "%a, %d %b %Y %H:%M:%S"
                        ).isoformat()
                    except ValueError:
                        parsed_date = pub_date

            event_id = hashlib.md5(f"{title}_{pub_date}".encode()).hexdigest()[:16]

            items.append({
                "event_id": f"gnews_{event_id}",
                "title": title[:500],
                "summary": description[:2000],
                "source": f"gnews_{source}",
                "source_url": link,
                "published_at": parsed_date,
                "ministry": None,
            })
    except ET.ParseError as e:
        pass
    return items


def harvest_google_news(dry_run=False):
    """Fetch historical news from Google News RSS with date-windowed topic queries."""
    total_queries = len(GOOGLE_TOPICS) * len(GOOGLE_WINDOWS)
    print(f"Google News RSS: {len(GOOGLE_TOPICS)} topics × {len(GOOGLE_WINDOWS)} windows = {total_queries} queries")

    if dry_run:
        for topic in GOOGLE_TOPICS:
            print(f"  {topic}")
        return 0

    all_items = []
    seen_ids = set()
    query_num = 0

    for topic in GOOGLE_TOPICS:
        for start, end in GOOGLE_WINDOWS:
            query_num += 1
            q = f"{topic}+after:{start}+before:{end}"
            url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"

            try:
                resp = requests.get(url, headers=HEADERS, timeout=15)
                if resp.status_code == 200:
                    items = _parse_google_rss(resp.text)
                    new_items = [i for i in items if i["event_id"] not in seen_ids]
                    for i in new_items:
                        seen_ids.add(i["event_id"])
                    all_items.extend(new_items)

                    if query_num % 20 == 0 or len(new_items) > 0:
                        print(f"  [{query_num:3d}/{total_queries}] {topic[:40]:40s} {start[:7]}→{end[:7]} +{len(new_items)} (total: {len(all_items)})")
                elif resp.status_code == 429:
                    print(f"  Rate limited at query {query_num}. Sleeping 30s...")
                    time.sleep(30)
                else:
                    pass  # silently skip non-200

            except Exception as e:
                print(f"  Error: {e}")

            time.sleep(1.0)  # be gentle

    print(f"\nGoogle News: {len(all_items)} unique articles fetched")

    if all_items:
        df = pd.DataFrame(all_items)
        n = insert_df(df, "regulatory_events")
        print(f"Saved {n} new rows to regulatory_events")

    return len(all_items)


# ═══════════════════════════════════════════════════
# 2. RBI CIRCULARS
# ═══════════════════════════════════════════════════

def _parse_rbi_notification(html, notif_id):
    """Extract title, date, and body from RBI notification page."""
    # The actual title is inside the tablebg content, after the PDF link
    # Format: "( 194 kb ) Formalisation of Informal Micro Enterprises..."
    title = None
    content_match = re.search(r'class="tablebg"[^>]*>(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
    if content_match:
        text = re.sub(r"<[^>]+>", " ", content_match.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        # Strip the PDF size prefix like "( 194 kb )"
        text = re.sub(r"^\s*\(\s*\d+\s*kb\s*\)\s*", "", text, flags=re.IGNORECASE)
        # Title is text before the RBI reference number (RBI/2023-24/...)
        rbi_ref = re.search(r"RBI/\d{4}", text)
        if rbi_ref:
            title = text[:rbi_ref.start()].strip()
        elif len(text) > 20:
            title = text[:200]

    if not title or len(title) < 15:
        return None, None, None

    # Date — look for "Month DD, YYYY" pattern
    date_match = re.search(
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
        html,
    )
    pub_date = None
    if date_match:
        try:
            pub_date = datetime.strptime(
                date_match.group(0).replace(",", ""), "%B %d %Y"
            ).isoformat()
        except ValueError:
            pass

    # Body text
    body = re.sub(r"<script.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()

    return title[:500], pub_date, body[:3000]


def harvest_rbi(start_id=12500, end_id=13370, dry_run=False):
    """Fetch RBI circulars/notifications by iterating IDs."""
    total = end_id - start_id
    print(f"RBI Circulars: IDs {start_id}-{end_id} ({total} to check)")

    if dry_run:
        print(f"  Would fetch {total} notification pages")
        return 0

    items = []
    for notif_id in range(start_id, end_id):
        url = f"https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id={notif_id}&Mode=0"

        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200 and len(resp.text) > 2000:
                title, pub_date, body = _parse_rbi_notification(resp.text, notif_id)

                if title and len(title) > 10:
                    event_id = f"rbi_{notif_id}"
                    items.append({
                        "event_id": event_id,
                        "title": title[:500],
                        "summary": body[:2000],
                        "full_text": body,
                        "source": "rbi_circular",
                        "source_url": url,
                        "published_at": pub_date,
                        "ministry": "RBI",
                    })

        except Exception:
            pass

        if (notif_id - start_id) % 50 == 0 and notif_id > start_id:
            print(f"  [{notif_id - start_id}/{total}] {len(items)} circulars found", flush=True)

        time.sleep(2.0)  # 2s delay to be gentle on RBI servers

    print(f"\nRBI: {len(items)} circulars fetched")

    if items:
        df = pd.DataFrame(items)
        n = insert_df(df, "regulatory_events")
        print(f"Saved {n} new rows")

    return len(items)


# ═══════════════════════════════════════════════════
# 3. WAYBACK MACHINE
# ═══════════════════════════════════════════════════

WAYBACK_FEEDS = [
    "economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
    "www.livemint.com/rss/markets",
    "www.livemint.com/rss/companies",
    "feeds.feedburner.com/NDTV-LatestBusinessNews",
    "www.moneycontrol.com/rss/latestnews.xml",
]


def harvest_wayback(dry_run=False):
    """Fetch archived RSS snapshots from Wayback Machine."""
    print(f"Wayback Machine: checking {len(WAYBACK_FEEDS)} feeds")

    if dry_run:
        for feed in WAYBACK_FEEDS:
            print(f"  {feed}")
        return 0

    all_items = []
    seen_ids = set()

    for feed_url in WAYBACK_FEEDS:
        # Query CDX API for available snapshots
        cdx_url = (
            f"http://web.archive.org/cdx/search/cdx?"
            f"url={feed_url}&output=json&from=20230101&to=20260410&limit=50"
        )

        try:
            resp = requests.get(cdx_url, timeout=30)
            if resp.status_code != 200:
                continue

            rows = resp.json()
            if len(rows) < 2:  # first row is header
                continue

            snapshots = rows[1:]  # skip header
            print(f"  {feed_url}: {len(snapshots)} snapshots")

            for snap in snapshots[:20]:  # limit per feed
                timestamp = snap[1]
                archive_url = f"https://web.archive.org/web/{timestamp}/{feed_url}"

                try:
                    r = requests.get(archive_url, headers=HEADERS, timeout=15)
                    if r.status_code == 200:
                        items = _parse_rss_generic(r.text, f"wayback_{feed_url.split('/')[0]}")
                        new = [i for i in items if i["event_id"] not in seen_ids]
                        for i in new:
                            seen_ids.add(i["event_id"])
                        all_items.extend(new)
                except Exception:
                    pass

                time.sleep(1.0)

        except Exception as e:
            print(f"  CDX error for {feed_url}: {e}")

    print(f"\nWayback: {len(all_items)} unique articles")

    if all_items:
        df = pd.DataFrame(all_items)
        n = insert_df(df, "regulatory_events")
        print(f"Saved {n} new rows")

    return len(all_items)


def _parse_rss_generic(xml_text, source_prefix):
    """Parse generic RSS/Atom XML."""
    items = []
    try:
        root = ET.fromstring(xml_text)

        # Handle Atom feeds
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        # Try RSS format
        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            description = item.findtext("description", "")
            description = re.sub(r"<[^>]+>", "", unescape(description or ""))

            event_id = hashlib.md5(f"{title}_{pub_date}".encode()).hexdigest()[:16]
            items.append({
                "event_id": f"wb_{event_id}",
                "title": title[:500],
                "summary": description[:2000],
                "source": source_prefix,
                "source_url": link,
                "published_at": pub_date,
                "ministry": None,
            })

        # Try Atom format if no RSS items found
        if not items:
            for entry in root.findall(".//atom:entry", ns):
                title = entry.findtext("atom:title", "", ns)
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                pub_date = entry.findtext("atom:published", "", ns) or entry.findtext("atom:updated", "", ns)
                summary = entry.findtext("atom:summary", "", ns)
                summary = re.sub(r"<[^>]+>", "", unescape(summary or ""))

                event_id = hashlib.md5(f"{title}_{pub_date}".encode()).hexdigest()[:16]
                items.append({
                    "event_id": f"wb_{event_id}",
                    "title": title[:500],
                    "summary": summary[:2000],
                    "source": source_prefix,
                    "source_url": link,
                    "published_at": pub_date,
                    "ministry": None,
                })

    except ET.ParseError:
        pass
    return items


# ═══════════════════════════════════════════════════
# 4. PIB PRESS RELEASES
# ═══════════════════════════════════════════════════

# Key ministries for market-relevant policy
PIB_RELEVANT_KEYWORDS = [
    "finance", "commerce", "industry", "petroleum", "power", "coal",
    "steel", "chemical", "fertilizer", "agriculture", "telecom",
    "defence", "health", "pharma", "mining", "railway", "transport",
    "cabinet", "NITI", "disinvestment", "tax", "GST", "budget",
    "RBI", "SEBI", "insurance", "banking",
]


def _parse_pib_page(html, prid):
    """Extract title, date, and body from PIB press release."""
    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else ""
    title = re.sub(r"\s+", " ", title).strip()

    # Check if English (skip Hindi/Urdu etc)
    if not title or any(ord(c) > 127 for c in title[:20]):
        return None, None, None

    # Date
    date_match = re.search(
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
        html,
    )
    pub_date = None
    if date_match:
        try:
            pub_date = datetime.strptime(
                date_match.group(0).replace(",", ""), "%B %d %Y"
            ).isoformat()
        except ValueError:
            pass

    # Body text
    body = re.sub(r"<script.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()

    # Relevance filter — does it mention market-relevant keywords?
    body_lower = body.lower()
    is_relevant = any(kw in body_lower for kw in PIB_RELEVANT_KEYWORDS)
    if not is_relevant:
        return None, None, None

    # Try to extract ministry
    ministry_match = re.search(r"Ministry of ([^<\n]+)", html)
    ministry = ministry_match.group(1).strip()[:100] if ministry_match else None

    return title, pub_date, body[:3000], ministry


def harvest_pib(start_prid=2150000, end_prid=2260000, dry_run=False):
    """Fetch PIB press releases by iterating PRIDs."""
    total = end_prid - start_prid
    print(f"PIB Press Releases: PRIDs {start_prid}-{end_prid} ({total} to scan)")
    print(f"  Filtering for: English language + market-relevant keywords")

    if dry_run:
        print(f"  Would scan {total} PRID pages")
        return 0

    items = []
    skipped = 0

    for prid in range(start_prid, end_prid):
        url = f"https://pib.gov.in/PressReleasePage.aspx?PRID={prid}"

        try:
            resp = requests.get(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html",
            }, timeout=10)

            if resp.status_code == 200 and len(resp.text) > 3000:
                result = _parse_pib_page(resp.text, prid)
                if result and result[0]:
                    title, pub_date, body, ministry = result
                    items.append({
                        "event_id": f"pib_{prid}",
                        "title": title[:500],
                        "summary": body[:2000],
                        "full_text": body,
                        "source": "pib",
                        "source_url": url,
                        "published_at": pub_date,
                        "ministry": ministry,
                    })
                else:
                    skipped += 1
            elif resp.status_code == 403:
                time.sleep(5)  # back off on 403

        except Exception:
            pass

        if (prid - start_prid) % 500 == 0 and prid > start_prid:
            print(f"  [{prid - start_prid}/{total}] {len(items)} relevant releases, {skipped} skipped")

        time.sleep(0.3)

    print(f"\nPIB: {len(items)} relevant releases (of {total} scanned, {skipped} skipped)")

    if items:
        df = pd.DataFrame(items)
        n = insert_df(df, "regulatory_events")
        print(f"Saved {n} new rows")

    return len(items)


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

def harvest_incremental(days=30, dry_run=False):
    """Daily-cron-safe regulatory event fetch — last N days only.

    `harvest_all` is a 3-year backfill (180 Google queries + 870 RBI iterations
    + 110K PIB IDs) — wrong fit for daily cron, would always time out leaving
    stale RUNNING rows. This is the daily incremental: a single recent window
    on Google News for each topic. Completes in ~5 minutes.

    Plan 0005 Phase C — see docs/plans/0005-data-confidence-to-95.md.
    """
    from datetime import date as _date, timedelta as _td
    end = _date.today()
    start = end - _td(days=days)
    window_str_start = start.isoformat()
    window_str_end = end.isoformat()

    if dry_run:
        print(f"[dry-run] would query {len(GOOGLE_TOPICS)} topics × 1 window "
              f"({window_str_start} → {window_str_end})")
        return 0

    print(f"Regulatory incremental: last {days}d ({window_str_start} → {window_str_end})")
    print(f"  {len(GOOGLE_TOPICS)} topics × 1 window = {len(GOOGLE_TOPICS)} queries")

    all_items = []
    seen_ids = set()
    for i, topic in enumerate(GOOGLE_TOPICS, 1):
        q = f"{topic}+after:{window_str_start}+before:{window_str_end}"
        url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                items = _parse_google_rss(resp.text)
                new_items = [it for it in items if it["event_id"] not in seen_ids]
                for it in new_items:
                    seen_ids.add(it["event_id"])
                all_items.extend(new_items)
                if i % 10 == 0 or len(new_items) > 0:
                    print(f"  [{i:3d}/{len(GOOGLE_TOPICS)}] {topic[:40]:40s} +{len(new_items)} (total: {len(all_items)})")
            elif resp.status_code == 429:
                print(f"  Rate limited at query {i}. Sleeping 30s...")
                time.sleep(30)
        except Exception as e:
            print(f"  Error on {topic}: {e}")
        time.sleep(1.0)

    print(f"\nRegulatory incremental: {len(all_items)} articles fetched")
    if all_items:
        df = pd.DataFrame(all_items)
        n = insert_df(df, "regulatory_events")
        print(f"Saved {n} new rows to regulatory_events")
    return len(all_items)


def harvest_all(dry_run=False):
    """Run all harvesters."""
    total = 0
    print("=" * 60)
    print("REGULATORY EVENT HISTORICAL BACKFILL")
    print("=" * 60)

    print("\n[1/4] Google News RSS...")
    total += harvest_google_news(dry_run=dry_run)

    print("\n[2/4] RBI Circulars...")
    total += harvest_rbi(dry_run=dry_run)

    print("\n[3/4] Wayback Machine...")
    total += harvest_wayback(dry_run=dry_run)

    print("\n[4/4] PIB Press Releases...")
    total += harvest_pib(dry_run=dry_run)

    print(f"\n{'=' * 60}")
    print(f"TOTAL: {total} regulatory events harvested")
    print(f"{'=' * 60}")

    # Show DB state
    from db import read_sql
    events = read_sql("SELECT source, COUNT(*) as n FROM regulatory_events GROUP BY source ORDER BY n DESC")
    print("\nregulatory_events by source:")
    print(events.to_string(index=False))

    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["google", "rbi", "wayback", "pib"],
                        help="Run specific harvester")
    parser.add_argument("--all", action="store_true", help="Run all harvesters")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.source == "google":
        harvest_google_news(dry_run=args.dry_run)
    elif args.source == "rbi":
        harvest_rbi(dry_run=args.dry_run)
    elif args.source == "wayback":
        harvest_wayback(dry_run=args.dry_run)
    elif args.source == "pib":
        harvest_pib(dry_run=args.dry_run)
    elif args.all:
        harvest_all(dry_run=args.dry_run)
    else:
        print("Specify --source {google,rbi,wayback,pib} or --all")
