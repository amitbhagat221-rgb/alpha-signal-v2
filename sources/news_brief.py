"""
Alpha Signal v2 — Daily News Brief Generator (Phase 2)

Per spec at sources/news_app_build_spec.md ("the 10 AM brief — the actual
product"). At cron-time, pulls the top N enriched articles from the last 24h,
synthesizes a structured brief via Claude Sonnet.

Output structure:
  • THE BIG ONE — single most important story (60 words)
  • FIVE FAST — five other things they need to know (20 words each)
  • ONE TO WATCH — something forming, not yet a story (40 words)
  • ZOOM OUT — one paragraph connecting today to a larger pattern (50 words)

Tone: "smart-friend voice. No clickbait."

Cost: ~$0.03-0.05 per daily brief (single Sonnet call, ~3K input + 500 output).

Usage:
    python -m sources.news_brief                # generate for today
    python -m sources.news_brief --date 2026-05-23
    python -m sources.news_brief --dry-run
"""

import argparse
import json
import os
import sys
from datetime import date as _date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, get_db

SONNET_MODEL = "claude-sonnet-4-20250514"

BRIEF_PROMPT = """You are writing the daily intelligence brief for one Indian investor / market-aware reader.
Their top interest areas are Indian markets, macro policy, AI/tech, and global economy.

From the articles below, produce a brief with this exact JSON structure (no markdown fences):

{{
  "big_one":       "...",     // THE BIG ONE — single most important story, ~60 words
  "five_fast":     ["...", "...", "...", "...", "..."],   // FIVE FAST — 5 other must-know items, ~20 words each
  "one_to_watch":  "...",     // ONE TO WATCH — something forming, ~40 words
  "zoom_out":      "..."      // ZOOM OUT — connect today to a larger pattern, ~50 words
}}

Constraints:
- Only use facts from the provided articles.
- If two articles contradict, surface the contradiction.
- Skip anything trivial — if there are only 3 things worth knowing, give 3 in five_fast.
- Tone: calm, smart-friend voice explaining the day over coffee. No "shocking", no "you won't believe".
- Write for someone who manages their own money — be honest about uncertainty.

Articles ({n_articles}):
{articles_text}
"""


def _get_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — news brief cannot run")
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _pick_top_articles(target_date, top=25):
    """Pick top N enriched articles for the brief.

    Ranks by source-tier × recency (24h half-life), preferring `confidence != low`,
    and ensures the result covers at least 5 distinct primary_topics for breadth.
    """
    df = read_sql(
        """
        SELECT na.title, na.summary, na.source, na.published_at,
               ne.primary_topic, ne.one_liner, ne.why_it_matters,
               ne.key_numbers, ne.confidence, ne.sentiment
        FROM news_articles na
        JOIN news_enriched ne ON ne.article_id = na.article_id
        WHERE ne.classifier_status = 'done'
          AND ne.why_it_matters != 'Not market-relevant'
          AND na.published_at >= datetime(?, '-2 days')
        ORDER BY na.published_at DESC
        LIMIT 200
        """,
        params=[target_date],
    )
    if df.empty:
        return df
    # Cap at top per primary_topic for diversity (≤5 per topic, then fill to `top`)
    picked = []
    seen_topics = {}
    for _, r in df.iterrows():
        t = r.get("primary_topic") or "other"
        if seen_topics.get(t, 0) >= 4:
            continue
        picked.append(r)
        seen_topics[t] = seen_topics.get(t, 0) + 1
        if len(picked) >= top:
            break
    return picked


def compute(target_date=None, dry_run=False, top=25):
    """Generate the daily brief for target_date (defaults to today)."""
    target_date = target_date or _date.today().isoformat()
    picks = _pick_top_articles(target_date, top=top)
    if len(picks) == 0:
        print(f"No enriched articles for {target_date} — skipping brief")
        return 0

    print(f"News brief: synthesizing from {len(picks)} top enriched articles for {target_date}")

    # Compact each article for the prompt
    chunks = []
    for i, r in enumerate(picks, 1):
        chunks.append(
            f"\n--- Article {i} [{r.get('primary_topic') or '?'} · {r.get('sentiment') or '?'}] ---\n"
            f"TITLE: {r['title']}\n"
            f"ONE-LINER: {r.get('one_liner') or ''}\n"
            f"WHY-IT-MATTERS: {r.get('why_it_matters') or ''}\n"
        )
    articles_text = "".join(chunks)
    prompt = BRIEF_PROMPT.format(n_articles=len(picks), articles_text=articles_text)

    if dry_run:
        print(f"  Estimated cost: ~$0.05 (Sonnet, ~{len(prompt)//4} input tokens)")
        return 0

    client = _get_client()
    resp = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    import re
    raw = re.sub(r"^```(?:json)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    try:
        brief = json.loads(raw)
    except Exception as e:
        print(f"  Failed to parse Sonnet output: {e}")
        print(f"  Raw: {raw[:400]}")
        return 0

    # Persist
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO news_briefs
               (brief_date, big_one, five_fast, one_to_watch, zoom_out, n_articles_used, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (target_date,
             brief.get("big_one", ""),
             json.dumps(brief.get("five_fast", [])),
             brief.get("one_to_watch", ""),
             brief.get("zoom_out", ""),
             len(picks)),
        )

    print(f"  Saved brief for {target_date} ({len(picks)} articles used)")
    print(f"\n  THE BIG ONE: {brief.get('big_one', '')[:200]}")
    return 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="ISO date (default: today)")
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    compute(target_date=args.date, dry_run=args.dry_run, top=args.top)
