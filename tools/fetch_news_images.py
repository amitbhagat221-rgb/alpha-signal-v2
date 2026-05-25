"""
News image backfill — scrape og:image / twitter:image from article URLs.

Run when you want richer cards on /news. Page renders without it (gradient
placeholder), so this is opt-in. Idempotent — only fetches missing rows.

Usage:
    python -m tools.fetch_news_images                    # all missing
    python -m tools.fetch_news_images --limit 50         # smoke
    python -m tools.fetch_news_images --source livemint_markets
    python -m tools.fetch_news_images --dry-run --limit 10
"""

import argparse
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import get_db, read_sql

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_0) AppleWebKit/605.1.15 "
                  "(KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY_SEC = 1.0
TIMEOUT = 10
MAX_BYTES = 250_000  # parse only the head — img URLs live in <meta>


def _extract_image(html: str, base_url: str) -> str | None:
    """og:image > twitter:image > link rel=image_src. Returns absolute URL or None."""
    soup = BeautifulSoup(html, "html5lib")
    for prop in ("og:image", "og:image:secure_url", "og:image:url"):
        m = soup.find("meta", attrs={"property": prop})
        if m and m.get("content"):
            return _absolutize(m["content"].strip(), base_url)
    for name in ("twitter:image", "twitter:image:src"):
        m = soup.find("meta", attrs={"name": name})
        if m and m.get("content"):
            return _absolutize(m["content"].strip(), base_url)
    link = soup.find("link", attrs={"rel": "image_src"})
    if link and link.get("href"):
        return _absolutize(link["href"].strip(), base_url)
    return None


def _absolutize(url: str, base_url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        m = re.match(r"^(https?://[^/]+)", base_url)
        return (m.group(1) if m else "") + url
    return url


def fetch_one(url: str) -> str | None:
    try:
        with requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True) as r:
            if r.status_code != 200:
                return None
            chunks = []
            n = 0
            for chunk in r.iter_content(chunk_size=8192):
                chunks.append(chunk)
                n += len(chunk)
                if n >= MAX_BYTES:
                    break
            html = b"".join(chunks).decode(r.encoding or "utf-8", errors="replace")
            return _extract_image(html, url)
    except (requests.exceptions.RequestException, ValueError):
        return None


def compute(limit: int | None = None, source: str | None = None, dry_run: bool = False) -> int:
    """Backfill image_url for enriched articles that don't have one yet.
    Returns: count of rows updated."""
    sql = """
        SELECT na.article_id AS id, na.url, na.source
        FROM news_articles na
        JOIN news_enriched ne ON ne.article_id = na.article_id
        WHERE ne.image_url IS NULL
          AND na.url IS NOT NULL
          AND na.url != ''
    """
    params: list = []
    if source:
        sql += " AND na.source = ?"
        params.append(source)
    sql += " ORDER BY na.published_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"

    df = read_sql(sql, params=params)
    if df.empty:
        print("No articles needing image backfill.")
        return 0

    print(f"Fetching images for {len(df)} articles (delay {DELAY_SEC}s, timeout {TIMEOUT}s)...")
    found, missed = 0, 0
    for i, row in enumerate(df.itertuples(index=False), 1):
        img = fetch_one(row.url)
        if img:
            found += 1
            if not dry_run:
                with get_db() as conn:
                    conn.execute(
                        "UPDATE news_enriched SET image_url = ? WHERE article_id = ?",
                        (img, row.id),
                    )
        else:
            missed += 1
        if i % 25 == 0 or i == len(df):
            print(f"  [{i}/{len(df)}]  found={found}  missed={missed}")
        time.sleep(DELAY_SEC)

    print(f"Done. found={found}  missed={missed}  rate={found/len(df):.0%}")
    return found


def main():
    p = argparse.ArgumentParser(description="Backfill og:image into news_enriched.image_url")
    p.add_argument("--limit", type=int, help="Cap on rows (smoke test)")
    p.add_argument("--source", help="Only this source (e.g. livemint_markets)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    compute(limit=args.limit, source=args.source, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
