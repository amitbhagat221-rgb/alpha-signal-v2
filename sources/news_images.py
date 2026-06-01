"""
Alpha Signal v2 — News image library (Pexels).

Downloads a small, curated pool of finance/markets-themed stock photos — a few
per news topic — resizes them to a thumbnail size, and stores them locally
under cockpit/static/news_img/<topic>/. The cockpit rotates through this pool
per card (by topic + a stable per-article hash), so cards get a relevant photo
behind the topic-tint + glyph/key-number, with NO per-request external fetch.

License: Pexels photos are free to use (no attribution required). We only keep
a local downsized copy.

Setup (one-time):
  1. Get a free API key at https://www.pexels.com/api/
  2. Add to ~/alpha-signal/run_pipeline.sh:  export PEXELS_API_KEY="..."
  3. Run:  python -m sources.news_images
  4. Restart the cockpit so it picks up the new pool.

Re-run anytime to refresh the pool (it overwrites in place).

Usage:
    python -m sources.news_images                 # ~8 per topic (~100 total)
    python -m sources.news_images --per-topic 6
    python -m sources.news_images --topic energy  # one topic only
"""

import argparse
import io
import os
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUT_DIR = PROJECT_ROOT / "cockpit" / "static" / "news_img"
PEXELS_URL = "https://api.pexels.com/v1/search"
THUMB_WIDTH = 600          # downsized thumbnail width
JPEG_QUALITY = 80
DELAY_SEC = 1.0            # be polite to the API

# topic_id → Pexels search query (tuned to look like the topic). Keep ids in
# sync with sources/news_classifier.py TOPIC_TAXONOMY / cockpit _NEWS_TOPICS.
TOPIC_QUERIES = {
    "macro":          "economy inflation interest rates",
    "global_economy": "global economy world trade shipping",
    "india_markets":  "mumbai india stock exchange skyline",
    "finance":        "bank finance money rupee",
    "earnings":       "corporate office business meeting",
    "deals":          "business handshake merger deal",
    "ai_tech":        "technology data center servers",
    "politics":       "government parliament building india",
    "energy":         "oil refinery power energy",
    "consumer":       "retail shopping store consumer",
    "industrial":     "factory manufacturing infrastructure",
    "pharma_health":  "pharmaceutical laboratory medicine",
    "other":          "business newspaper finance",
    "generic":        "stock market trading finance",   # fallback pool
}


def _client_key():
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        raise RuntimeError(
            "PEXELS_API_KEY not set. Get a free key at https://www.pexels.com/api/ "
            "and add `export PEXELS_API_KEY=...` to ~/alpha-signal/run_pipeline.sh"
        )
    return key


def _fetch_topic(key, topic, query, per_topic):
    """Download + resize `per_topic` photos for one topic into its folder."""
    from PIL import Image

    dest = OUT_DIR / topic
    dest.mkdir(parents=True, exist_ok=True)
    # over-fetch a little so we can skip any that fail to decode
    resp = requests.get(
        PEXELS_URL,
        headers={"Authorization": key},
        params={"query": query, "per_page": per_topic + 4,
                "orientation": "landscape", "size": "medium"},
        timeout=20,
    )
    resp.raise_for_status()
    photos = resp.json().get("photos", [])
    saved = 0
    for p in photos:
        if saved >= per_topic:
            break
        src = (p.get("src") or {})
        url = src.get("landscape") or src.get("large") or src.get("medium")
        if not url:
            continue
        try:
            img_bytes = requests.get(url, timeout=20).content
            im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            if im.width > THUMB_WIDTH:
                h = int(im.height * THUMB_WIDTH / im.width)
                im = im.resize((THUMB_WIDTH, h), Image.LANCZOS)
            im.save(dest / f"{saved:02d}.jpg", "JPEG", quality=JPEG_QUALITY, optimize=True)
            saved += 1
        except Exception as e:
            print(f"    skip ({type(e).__name__})")
            continue
        time.sleep(0.2)
    return saved


def run(per_topic=8, only_topic=None):
    key = _client_key()
    topics = {only_topic: TOPIC_QUERIES[only_topic]} if only_topic else TOPIC_QUERIES
    total = 0
    for topic, query in topics.items():
        n = _fetch_topic(key, topic, query, per_topic)
        total += n
        print(f"  {topic:15} {n} images  ({query})")
        time.sleep(DELAY_SEC)
    print(f"✓ {total} images saved under {OUT_DIR.relative_to(PROJECT_ROOT)}")
    if total == 0:
        raise RuntimeError("0 images downloaded — check PEXELS_API_KEY / network")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-topic", type=int, default=8)
    ap.add_argument("--topic", help="single topic id (default: all)")
    args = ap.parse_args()
    run(per_topic=args.per_topic, only_topic=args.topic)


if __name__ == "__main__":
    main()
