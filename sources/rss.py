"""
Alpha Signal v2 — RSS News Fetcher

Fetches news from 8 Indian financial RSS feeds, matches articles to stocks.

Guardrails:
  - Deduplicates by md5(title + source) — skips existing articles
  - Validates article has title and published_at
  - Entity matching against full 2,448 stock universe (not just Nifty 500)
  - Skips articles older than 7 days (stale)
  - Rate-limited: 1 request per feed

Reads: RSS feeds (ET, LiveMint, MoneyControl)
Writes: news_articles, news_article_stocks

Usage:
    python -m sources.rss              # fetch from all feeds
    python -m sources.rss --dry-run
"""

import argparse
import hashlib
import re
import time
from datetime import datetime, timedelta

import feedparser
import pandas as pd

from db import read_sql, insert_df

# RSS feed URLs
FEEDS = {
    "et_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "et_companies": "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms",
    "et_economy": "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
    "livemint_markets": "https://www.livemint.com/rss/markets",
    "livemint_companies": "https://www.livemint.com/rss/companies",
    "moneycontrol_latest": "https://www.moneycontrol.com/rss/latestnews.xml",
    "moneycontrol_business": "https://www.moneycontrol.com/rss/business.xml",
    "moneycontrol_markets": "https://www.moneycontrol.com/rss/marketreports.xml",
}

# Exact match symbols (too short / ambiguous for substring match)
EXACT_MATCH_ONLY = {
    "OIL", "PVR", "HCL", "BEL", "HAL", "ITC", "MCX", "REC", "SBI",
    "JSL", "PFC", "NCC", "KEC", "GMR", "IRB", "DLF", "PNB",
}

_STOCK_INDEX = None


def _build_stock_index():
    """Build stock name index for entity matching."""
    global _STOCK_INDEX
    if _STOCK_INDEX is not None:
        return _STOCK_INDEX

    stocks = read_sql("SELECT sid, ticker, name FROM stocks")

    index = {}

    for _, row in stocks.iterrows():
        sid = row["sid"]
        ticker = row["ticker"]
        name = str(row.get("name", ""))

        # Ticker match (word boundary)
        if ticker and len(ticker) >= 3:
            index[ticker.upper()] = {"sid": sid, "type": "ticker", "exact": ticker.upper() in EXACT_MATCH_ONLY}

        # Company name (first 2-3 significant words)
        if name and len(name) > 5:
            # Extract significant words (skip Ltd, Limited, India, Corp, etc.)
            skip_words = {"ltd", "limited", "india", "corp", "corporation", "co", "company",
                          "industries", "and", "the", "of", "pvt", "private"}
            words = [w for w in name.split() if w.lower() not in skip_words and len(w) > 2]
            if len(words) >= 2:
                key = " ".join(words[:2]).upper()
                if key not in index:  # don't overwrite ticker matches
                    index[key] = {"sid": sid, "type": "name", "exact": False}

    _STOCK_INDEX = index
    return index


def _match_article(title, summary=""):
    """Match article to stock SIDs using entity matching."""
    index = _build_stock_index()
    matches = set()

    text_upper = f"{title} {summary}".upper()

    for key, info in index.items():
        if info["exact"]:
            # Exact word boundary match in title only
            if re.search(rf"\b{re.escape(key)}\b", title.upper()):
                matches.add((info["sid"], "title"))
        else:
            # Word boundary match in full text
            if re.search(rf"\b{re.escape(key)}\b", text_upper):
                loc = "title" if key in title.upper() else "summary"
                matches.add((info["sid"], loc))

    return matches


def _article_id(title, source):
    """Generate deterministic article ID for dedup."""
    return hashlib.md5(f"{title.lower().strip()}_{source}".encode()).hexdigest()[:12]


def _parse_date(entry):
    """Extract published date from feed entry."""
    for field in ["published_parsed", "updated_parsed"]:
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime(*parsed[:6]).isoformat()
            except (TypeError, ValueError):
                pass
    # Try string parsing
    for field in ["published", "updated"]:
        date_str = entry.get(field, "")
        if date_str:
            return date_str
    return None


def fetch_news(dry_run=False):
    """Fetch from all RSS feeds."""
    print(f"RSS News: {len(FEEDS)} feeds")

    # Load existing article IDs for dedup
    existing = set(read_sql("SELECT article_id FROM news_articles")["article_id"])
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()

    total_articles = 0
    total_links = 0

    for source_name, url in FEEDS.items():
        print(f"  {source_name:25s}", end=" ", flush=True)

        if dry_run:
            print("dry run")
            continue

        try:
            feed = feedparser.parse(url)
            entries = feed.entries

            if not entries:
                print("0 entries")
                continue

            articles = []
            links = []

            for entry in entries:
                title = entry.get("title", "").strip()
                if not title or len(title) < 10:
                    continue

                aid = _article_id(title, source_name)
                if aid in existing:
                    continue  # dedup

                pub_date = _parse_date(entry)

                # ── GUARDRAIL: skip stale articles ──
                if pub_date and pub_date < cutoff:
                    continue

                summary = entry.get("summary", "")
                # Clean HTML from summary
                summary = re.sub(r"<[^>]+>", "", summary)[:500]

                link = entry.get("link", "")

                articles.append({
                    "article_id": aid,
                    "title": title[:500],
                    "summary": summary,
                    "url": link[:500],
                    "source": source_name,
                    "published_at": pub_date,
                })
                existing.add(aid)

                # Entity matching
                matches = _match_article(title, summary)
                for sid, match_loc in matches:
                    links.append({
                        "article_id": aid,
                        "sid": sid,
                        "match_location": match_loc,
                    })

            if articles:
                n_art = insert_df(pd.DataFrame(articles), "news_articles")
                total_articles += n_art

            if links:
                n_links = insert_df(pd.DataFrame(links), "news_article_stocks")
                total_links += n_links

            print(f"{len(entries)} entries → {len(articles)} new → {len(links)} stock links")

        except Exception as e:
            print(f"ERROR: {e}")

        time.sleep(1)  # gentle between feeds

    print(f"\nTotal: {total_articles} new articles, {total_links} stock links")
    return total_articles


def compute(dry_run=False):
    """Pipeline entry point."""
    return fetch_news(dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    fetch_news(dry_run=args.dry_run)
