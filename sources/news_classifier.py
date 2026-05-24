"""
Alpha Signal v2 — News Classifier (Phase 2)

Per-article LLM enrichment using Claude Haiku. For each unclassified row in
`news_articles`, populates a `news_enriched` row with:
  • topics + primary_topic  — from the TOPIC_TAXONOMY below
  • one_liner               — max 20 words, what happened
  • why_it_matters          — max 40 words, the implication
  • key_numbers             — JSON array of {label, value}, max 3
  • what_to_watch           — max 30 words, next thing to look for
  • confidence              — "high" | "medium" | "low"
  • sentiment               — "bullish" | "bearish" | "neutral"

Cost: ~$0.001 per article. 500-article backfill = ~$0.50.

Spec source: sources/news_app_build_spec.md — "the LLM layer, quality is
everything". Includes the spec's hallucination guardrails (number-check
against source text).

Usage:
    python -m sources.news_classifier                # classify all pending
    python -m sources.news_classifier --limit 50     # quick test
    python -m sources.news_classifier --dry-run      # show count + cost
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, get_db

HAIKU_MODEL = "claude-haiku-4-5-20251001"

# ─────────────────────── Topic taxonomy ───────────────────────
# Top-level "sections" (Inshorts-style top-tabs). Each is broad on purpose
# so the feed groups cleanly. Keywords are deterministic fallbacks used if
# the LLM output is ambiguous; the LLM picks topics from this same set.
# Order here = order of tabs in the UI.
TOPIC_TAXONOMY = {
    "macro":           {"label": "Macro",              "default_weight": 1.0, "color": "#9b59b6",
        "keywords": ["rbi", "sebi", "repo", "inflation", "gdp", "budget", "fiscal", "monetary", "policy"]},
    "global_economy":  {"label": "Global Economy",     "default_weight": 0.9, "color": "#5dade2",
        "keywords": ["us", "china", "eu", "fed", "ecb", "oil", "trade war", "tariff", "sanctions", "geopolit"]},
    "india_markets":   {"label": "India Markets",      "default_weight": 1.0, "color": "#2ecc71",
        "keywords": ["nifty", "sensex", "bse", "nse", "fii", "dii", "stock market", "equity"]},
    "finance":         {"label": "Finance & Banking",  "default_weight": 0.9, "color": "#f1c40f",
        "keywords": ["nbfc", "bank", "loan", "credit", "npa", "lending", "deposit", "insurance", "asset management"]},
    "earnings":        {"label": "Earnings & Companies","default_weight": 0.9, "color": "#e67e22",
        "keywords": ["earnings", "q1 results", "q2 results", "q3 results", "q4 results", "profit", "revenue", "company"]},
    "deals":           {"label": "Deals, IPOs & M&A",  "default_weight": 0.8, "color": "#e91e63",
        "keywords": ["ipo", "acquisition", "merger", "stake", "buyout", "drhp", "fund-rais", "private equity"]},
    "ai_tech":         {"label": "AI & Tech",          "default_weight": 0.9, "color": "#3498db",
        "keywords": ["ai", "artificial intelligence", "openai", "anthropic", "llm", "gpu", "nvidia", "semiconductor", "software", "startup", "cybersecurity"]},
    "politics":        {"label": "Politics & Policy",  "default_weight": 0.7, "color": "#c0392b",
        "keywords": ["election", "minister", "parliament", "cabinet", "supreme court", "ruling", "verdict", "law", "bill", "vote"]},
    "energy":          {"label": "Energy & Commodities","default_weight": 0.7, "color": "#ff8c00",
        "keywords": ["oil", "gas", "opec", "crude", "coal", "renewable", "solar", "ethanol", "lpg", "gold", "silver", "metal"]},
    "consumer":        {"label": "Consumer & Retail",  "default_weight": 0.6, "color": "#16a085",
        "keywords": ["fmcg", "retail", "auto", "ev", "smartphone", "real estate", "housing", "luxury"]},
    "industrial":      {"label": "Industrial & Infra", "default_weight": 0.6, "color": "#7f8c8d",
        "keywords": ["infrastructure", "highway", "railway", "defence", "defense", "pli", "manufacturing", "cement", "steel", "shipping", "aviation"]},
    "pharma_health":   {"label": "Pharma & Health",    "default_weight": 0.6, "color": "#1abc9c",
        "keywords": ["pharma", "drug", "health", "hospital", "vaccine", "medical", "biotech"]},
    "other":           {"label": "Other",              "default_weight": 0.3, "color": "#95a5a6",
        "keywords": []},
}

TOPIC_IDS = list(TOPIC_TAXONOMY.keys())


# ─────────────────────── Prompt ───────────────────────
CLASSIFY_PROMPT = """You are an Indian financial-news analyst. Given the article below, output JSON ONLY (no markdown fences, no prose) with these exact fields:

- topics: array of 1-3 topic_ids from this list: {topic_ids}. Most-relevant first.
- one_liner: max 20 words. Plain what-happened. No clickbait.
- why_it_matters: max 40 words. The actual implication for Indian markets/investors. If pure trivia or non-investment story, write "Not market-relevant".
- key_numbers: array of at most 3 {{"label": "X", "value": "Y"}}. Numbers ONLY if central to the story. Empty array if none.
- what_to_watch: max 30 words. Next concrete thing to look for. Empty string if nothing forming.
- confidence: "high" | "medium" | "low". Your confidence in source accuracy + the implication's correctness.
- sentiment: "bullish" | "bearish" | "neutral". From the perspective of Indian equities. Only "bullish"/"bearish" if a directional read is genuinely warranted; default "neutral".

Rules:
- Never speculate beyond what's in the article.
- If a number isn't in the source, do not include it in key_numbers.
- If the article is opinion/editorial, set confidence to "low".

Article:
TITLE: {title}
SOURCE: {source}
SUMMARY: {summary}
"""


def _get_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — news classifier cannot run")
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


# ─────────────────────── Hallucination guardrails ───────────────────────
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _verify_numbers_in_source(key_numbers, source_text):
    """Per spec: every number in key_numbers must appear verbatim in source.
    Returns the filtered list (drops invented numbers)."""
    if not key_numbers:
        return []
    src_lower = source_text.lower()
    kept = []
    for kn in key_numbers:
        v = str(kn.get("value", ""))
        nums = _NUMBER_RE.findall(v)
        if not nums:
            # Non-numeric value (e.g. "Q1") — keep
            kept.append(kn)
            continue
        # Strip commas + cast to compare digits-only
        digits_only = nums[0].replace(",", "")
        if digits_only in src_lower.replace(",", ""):
            kept.append(kn)
    return kept


# ─────────────────────── Driver ───────────────────────


def _classify_one(client, title, summary, source):
    """Single Haiku call. Returns dict matching news_enriched columns, or None on parse error."""
    prompt = CLASSIFY_PROMPT.format(
        topic_ids=", ".join(TOPIC_IDS),
        title=(title or "").replace("\n", " ")[:300],
        source=source or "",
        summary=(summary or "").replace("\n", " ")[:1500],
    )
    try:
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        # Strip markdown fences if model wraps anyway
        raw = re.sub(r"^```(?:json)?\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        data = json.loads(raw)
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {str(e)[:120]}"}

    # Normalize + validate
    topics = data.get("topics") or []
    topics = [t for t in topics if t in TOPIC_TAXONOMY][:3]
    if not topics:
        topics = ["other"]

    # Hallucination guard: filter invented numbers
    key_numbers = _verify_numbers_in_source(
        data.get("key_numbers") or [],
        f"{title} {summary}",
    )

    return {
        "topics":         json.dumps(topics),
        "primary_topic":  topics[0],
        "one_liner":      (data.get("one_liner") or "")[:250],
        "why_it_matters": (data.get("why_it_matters") or "")[:400],
        "key_numbers":    json.dumps(key_numbers),
        "what_to_watch":  (data.get("what_to_watch") or "")[:300],
        "confidence":     (data.get("confidence") or "medium") if data.get("confidence") in ("high","medium","low") else "medium",
        "sentiment":      (data.get("sentiment") or "neutral") if data.get("sentiment") in ("bullish","bearish","neutral") else "neutral",
        "classifier_status": "done",
    }


def compute(limit=None, dry_run=False, days=7):
    """Classify all unclassified articles from last N days."""
    pending = read_sql(
        """
        SELECT na.article_id, na.title, na.summary, na.source
        FROM news_articles na
        LEFT JOIN news_enriched ne ON ne.article_id = na.article_id
        WHERE na.published_at >= date('now', ?)
          AND (ne.article_id IS NULL OR ne.classifier_status = 'pending' OR ne.classifier_status = 'failed')
        ORDER BY na.published_at DESC
        """,
        params=[f"-{days} days"],
    )
    if limit:
        pending = pending.head(limit)
    total = len(pending)
    print(f"News classifier: {total} pending articles (last {days}d)")
    if total == 0:
        return 0
    if dry_run:
        est = total * 0.001
        print(f"  Est. cost: ${est:.2f} ({total} × Haiku @ ~$0.001/article)")
        return 0

    client = _get_client()
    n_done = n_failed = 0
    t0 = time.time()
    for i, (article_id, title, summary, source) in enumerate(pending.itertuples(index=False), 1):
        out = _classify_one(client, title, summary, source)
        if out is None or out.get("_error"):
            n_failed += 1
            err = out.get("_error", "unknown") if out else "no response"
            with get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO news_enriched "
                    "(article_id, classifier_status, classified_at) "
                    "VALUES (?, 'failed', datetime('now'))",
                    (article_id,),
                )
            if i % 25 == 0:
                print(f"  [{i}/{total}] {n_done} done · {n_failed} failed · {(time.time()-t0)/i:.1f}s/article")
            continue
        with get_db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO news_enriched
                   (article_id, topics, primary_topic, one_liner, why_it_matters,
                    key_numbers, what_to_watch, confidence, sentiment,
                    classifier_status, classified_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (article_id, out["topics"], out["primary_topic"], out["one_liner"],
                 out["why_it_matters"], out["key_numbers"], out["what_to_watch"],
                 out["confidence"], out["sentiment"], out["classifier_status"]),
            )
        n_done += 1
        if i % 25 == 0 or i == total:
            print(f"  [{i}/{total}] {n_done} done · {n_failed} failed · {(time.time()-t0)/i:.1f}s/article")

    elapsed = time.time() - t0
    print(f"Done in {elapsed:.0f}s. {n_done} classified, {n_failed} failed.")
    return n_done


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, help="Max articles to process")
    p.add_argument("--days", type=int, default=7, help="Lookback window")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    compute(limit=args.limit, dry_run=args.dry_run, days=args.days)
