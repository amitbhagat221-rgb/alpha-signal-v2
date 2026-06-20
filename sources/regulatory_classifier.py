"""
Alpha Signal v2 — Regulatory News Classifier

Two-stage AI classification:
  Stage 1 (Haiku): Quick filter — is this article about regulation/policy? (~80% filtered out)
  Stage 2 (Sonnet): Deep classify — which sectors, direction, magnitude, stage

Reads: news_articles
Writes: regulatory_events + regulatory_signals

Usage:
    python -m sources.regulatory_classifier                # classify all unclassified
    python -m sources.regulatory_classifier --limit 50     # classify 50 articles
    python -m sources.regulatory_classifier --dry-run      # show stats without calling API
"""

import argparse
import hashlib
import json
import os
import time
from datetime import datetime

import pandas as pd

from db import read_sql, get_db, insert_df, upsert_df

# Cost-efficient: Haiku for pre-filter, Sonnet for deep classification
HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"

PREFILTER_PROMPT = """Classify this Indian financial news headline+summary.
Is this about government regulation, policy, court orders, RBI/SEBI decisions,
import/export duties, budget proposals, or any regulatory change?

Title: {title}
Summary: {summary}

Respond with ONLY one word: YES or NO"""

CLASSIFY_PROMPT = """You are an expert Indian regulatory analyst. Classify this news article
for its impact on Indian equity sectors.

Title: {title}
Summary: {summary}
Source: {source}
Date: {published_at}

Respond in JSON (no markdown, just raw JSON):
{{
  "is_regulatory": true,
  "stage": "discussion|draft|notification|implementation|enforcement",
  "ministry": "which ministry/regulator (RBI/SEBI/MoF/etc) or null",
  "sectors_affected": [
    {{
      "sector": "exact BSE sector name",
      "direction": 1 or -1,
      "magnitude": "minor|moderate|major",
      "time_horizon": "immediate|3mo|6mo|12mo",
      "confidence": "high|medium|low",
      "reasoning": "one line why"
    }}
  ]
}}

Valid sectors (use these EXACT strings — taxonomy aligned to stocks.sector):
Communication Services, Consumer Discretionary, Consumer Staples, Energy,
Financials, Health Care, Industrials, Information Technology, Materials,
Real Estate, Utilities

Rules:
- Only sectors genuinely affected. Don't force-fit sectors.
- "major" = >10% sector impact potential. "moderate" = 5-10%. "minor" = <5%.
- Be specific about WHY. Generic "positive for economy" is useless.
- Use EXACTLY the sector strings above. Do NOT use "Financial Services" (use "Financials"),
  do NOT use "IT" (use "Information Technology"). Mismatches orphan the row from stocks join."""


def _get_client():
    """Get Anthropic client."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Run: source ~/alpha-signal/run_pipeline.sh"
        )
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _event_id(article_id):
    """Generate event_id from article_id."""
    return f"news_{article_id}"


def _get_unclassified():
    """Get articles not yet in regulatory_events."""
    return read_sql("""
        SELECT a.article_id, a.title, a.summary, a.source, a.published_at
        FROM news_articles a
        WHERE a.article_id NOT IN (SELECT REPLACE(event_id, 'news_', '') FROM regulatory_events)
        ORDER BY a.published_at DESC
    """)


def _prefilter_batch(client, articles):
    """Stage 1: Quick Haiku filter — is this regulatory? Returns list of article_ids that pass."""
    regulatory_ids = []

    for _, art in articles.iterrows():
        prompt = PREFILTER_PROMPT.format(
            title=art["title"][:200],
            summary=str(art.get("summary", ""))[:300],
        )

        try:
            resp = client.messages.create(
                model=HAIKU_MODEL,
                max_tokens=5,
                messages=[{"role": "user", "content": prompt}],
            )
            answer = resp.content[0].text.strip().upper()
            if "YES" in answer:
                regulatory_ids.append(art["article_id"])
        except Exception as e:
            print(f"  Haiku error: {e}")

        time.sleep(0.1)  # rate limit

    return regulatory_ids


def _deep_classify(client, article):
    """Stage 2: Sonnet deep classification of one regulatory article."""
    prompt = CLASSIFY_PROMPT.format(
        title=article["title"][:300],
        summary=str(article.get("summary", ""))[:1000],
        source=article["source"],
        published_at=article["published_at"],
    )

    try:
        resp = client.messages.create(
            model=SONNET_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()

        # Parse JSON (handle markdown code blocks)
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)

    except json.JSONDecodeError:
        return None
    except Exception as e:
        print(f"  Sonnet error: {e}")
        return None


def _save_event(article, is_regulatory):
    """Save to regulatory_events table with classifier_status set.

    classifier_status:
      'haiku_rejected'  → Haiku said NO; no Sonnet call needed
      'pending'         → Haiku said YES; about to call Sonnet (status updated again on success/fail)
    """
    initial_status = "pending" if is_regulatory else "haiku_rejected"
    event = pd.DataFrame([{
        "event_id": _event_id(article["article_id"]),
        "title": article["title"][:500],
        "summary": str(article.get("summary", ""))[:2000],
        "source": f"news_{article['source']}",
        "source_url": None,
        "published_at": article["published_at"],
        "ministry": None,
        "classifier_status": initial_status,
        "classifier_processed_at": datetime.now().isoformat(timespec="seconds"),
    }])
    insert_df(event, "regulatory_events")


def _update_event_status(event_id, status):
    """UPDATE regulatory_events.classifier_status — called after every Haiku/Sonnet call.
    This is the single source of truth for whether an event has been seen by the classifier."""
    with get_db() as conn:
        conn.execute(
            "UPDATE regulatory_events SET classifier_status = ?, classifier_processed_at = ? WHERE event_id = ?",
            (status, datetime.now().isoformat(timespec="seconds"), event_id),
        )


def _save_signals(article, classification):
    """Save AI classification to regulatory_signals table."""
    event_id = _event_id(article["article_id"])
    sectors = classification.get("sectors_affected", [])

    if not sectors:
        return 0

    rows = []
    for s in sectors:
        rows.append({
            "event_id": event_id,
            "sector": s.get("sector", "Unknown"),
            "is_regulatory": 1,
            "stage": classification.get("stage"),
            "direction": s.get("direction", 0),
            "magnitude": s.get("magnitude"),
            "time_horizon": s.get("time_horizon"),
            "confidence": s.get("confidence"),
            "ai_reasoning": s.get("reasoning"),
        })

    df = pd.DataFrame(rows)
    insert_df(df, "regulatory_signals")
    return len(rows)


def classify(limit=None, dry_run=False):
    """Classify unclassified news articles."""
    unclassified = _get_unclassified()
    if limit:
        unclassified = unclassified.head(limit)

    total = len(unclassified)
    print(f"Regulatory Classifier: {total} articles to process")

    if total == 0:
        print("Nothing to classify.")
        return 0

    if dry_run:
        print(f"  Would process {total} articles")
        print(f"  Estimated Haiku cost: ~${total * 0.0003:.2f}")
        print(f"  Estimated Sonnet cost (assuming 20% regulatory): ~${total * 0.2 * 0.003:.2f}")
        print(f"  Total estimated: ~${total * 0.0003 + total * 0.2 * 0.003:.2f}")
        return 0

    client = _get_client()

    # Process in batches of 100
    batch_size = 100
    total_regulatory = 0
    total_signals = 0

    for batch_start in range(0, total, batch_size):
        batch = unclassified.iloc[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size

        print(f"\n--- Batch {batch_num}/{total_batches} ({len(batch)} articles) ---")

        # Stage 1: Haiku pre-filter
        print(f"  Stage 1 (Haiku): filtering...", end=" ", flush=True)
        regulatory_ids = _prefilter_batch(client, batch)
        print(f"{len(regulatory_ids)}/{len(batch)} regulatory")

        # Save non-regulatory as processed (so we don't re-check them)
        for _, art in batch.iterrows():
            _save_event(art, art["article_id"] in regulatory_ids)

        # Stage 2: Sonnet deep classification for regulatory articles
        reg_articles = batch[batch["article_id"].isin(regulatory_ids)]
        if len(reg_articles) > 0:
            print(f"  Stage 2 (Sonnet): classifying {len(reg_articles)} articles...")

            for _, art in reg_articles.iterrows():
                event_id = _event_id(art["article_id"])
                classification = _deep_classify(client, art)
                if classification:
                    n_signals = _save_signals(art, classification)
                    total_signals += n_signals

                    ministry = classification.get("ministry", "")
                    sectors = [s["sector"] for s in classification.get("sectors_affected", [])]
                    print(f"    {art['title'][:60]}... → {ministry} → {sectors}")

                    # Mark as fully classified + update ministry
                    with get_db() as conn:
                        conn.execute(
                            "UPDATE regulatory_events SET classifier_status = ?, classifier_processed_at = ?, ministry = COALESCE(?, ministry) WHERE event_id = ?",
                            ("classified", datetime.now().isoformat(timespec="seconds"),
                             str(ministry) if ministry else None, event_id),
                        )
                else:
                    # Sonnet failed (API error or bad JSON) — mark accordingly so we can retry
                    _update_event_status(event_id, "haiku_passed_sonnet_failed")

                time.sleep(0.3)  # rate limit for Sonnet

        total_regulatory += len(regulatory_ids)

    print(f"\n=== Summary ===")
    print(f"  Processed: {total} articles")
    print(f"  Regulatory: {total_regulatory} ({total_regulatory/total*100:.0f}%)")
    print(f"  Sector signals: {total_signals}")

    return total_regulatory


def classify_events(limit=None, dry_run=False):
    """Classify events that have classifier_status='pending' or 'haiku_passed_sonnet_failed'.

    NOTE: this used to query "events with no signals yet", which silently re-processed
    Haiku-rejected events on every run (no audit trail of rejections). Now driven by
    the explicit classifier_status column on regulatory_events. Events tagged
    'unknown' (legacy from before this column existed) are NOT re-processed automatically —
    use --include-unknown to backfill them."""
    unclassified = read_sql("""
        SELECT event_id, title, summary, source, published_at
        FROM regulatory_events
        WHERE classifier_status IN ('pending', 'haiku_passed_sonnet_failed')
        AND title IS NOT NULL AND length(title) > 10
        ORDER BY published_at DESC
    """)
    if limit:
        unclassified = unclassified.head(limit)

    total = len(unclassified)
    print(f"Regulatory Classifier (events): {total} events to process")

    if total == 0:
        print("Nothing to classify.")
        return 0

    if dry_run:
        print(f"  Would process {total} events")
        haiku_cost = total * 150 / 1_000_000 * 1.00 + total * 5 / 1_000_000 * 5.00
        reg_est = int(total * 0.20)
        sonnet_cost = reg_est * 400 / 1_000_000 * 3.00 + reg_est * 200 / 1_000_000 * 15.00
        print(f"  Haiku pre-filter: ~${haiku_cost:.2f}")
        print(f"  Sonnet classify (~{reg_est} regulatory): ~${sonnet_cost:.2f}")
        print(f"  Total: ~${haiku_cost + sonnet_cost:.2f}")
        return 0

    client = _get_client()
    batch_size = 100
    total_regulatory = 0
    total_signals = 0

    for batch_start in range(0, total, batch_size):
        batch = unclassified.iloc[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size

        print(f"\n--- Batch {batch_num}/{total_batches} ({len(batch)} events) ---")

        # Stage 1: Haiku pre-filter — update classifier_status after EVERY call
        print(f"  Stage 1 (Haiku): filtering...", end=" ", flush=True)
        regulatory_ids = []
        for _, evt in batch.iterrows():
            prompt = PREFILTER_PROMPT.format(
                title=str(evt["title"])[:200],
                summary=str(evt.get("summary", ""))[:300],
            )
            try:
                resp = client.messages.create(
                    model=HAIKU_MODEL, max_tokens=5,
                    messages=[{"role": "user", "content": prompt}],
                )
                if "YES" in resp.content[0].text.strip().upper():
                    regulatory_ids.append(evt["event_id"])
                    # Don't update status yet — Sonnet will do it
                else:
                    # Haiku rejected — mark + done with this event
                    _update_event_status(evt["event_id"], "haiku_rejected")
            except Exception as e:
                print(f"\n  Haiku error: {e}")
                # Don't change status on API error → leaves as pending → safe to retry
            time.sleep(0.1)

        print(f"{len(regulatory_ids)}/{len(batch)} regulatory")

        # Stage 2: Sonnet deep classify
        reg_events = batch[batch["event_id"].isin(regulatory_ids)]
        if len(reg_events) > 0:
            print(f"  Stage 2 (Sonnet): classifying {len(reg_events)} events...")

            for _, evt in reg_events.iterrows():
                event_id = evt["event_id"]
                classification = _deep_classify(client, evt)
                if classification:
                    sectors = classification.get("sectors_affected", [])
                    if sectors:
                        rows = []
                        for s in sectors:
                            rows.append({
                                "event_id": event_id,
                                "sector": s.get("sector", "Unknown"),
                                "is_regulatory": 1,
                                "stage": classification.get("stage"),
                                "direction": s.get("direction", 0),
                                "magnitude": s.get("magnitude"),
                                "time_horizon": s.get("time_horizon"),
                                "confidence": s.get("confidence"),
                                "ai_reasoning": s.get("reasoning"),
                            })
                        df = pd.DataFrame(rows)
                        insert_df(df, "regulatory_signals")
                        total_signals += len(rows)

                    ministry = classification.get("ministry")
                    sector_names = [s["sector"] for s in sectors]
                    print(f"    {str(evt['title'])[:60]}... → {ministry} → {sector_names}")

                    # Mark fully classified + update ministry in one statement
                    with get_db() as conn:
                        conn.execute(
                            "UPDATE regulatory_events SET classifier_status = ?, classifier_processed_at = ?, ministry = COALESCE(?, ministry) WHERE event_id = ?",
                            ("classified", datetime.now().isoformat(timespec="seconds"),
                             str(ministry) if ministry else None, event_id),
                        )
                else:
                    # Sonnet failed (API error or bad JSON) — mark so we can retry
                    _update_event_status(event_id, "haiku_passed_sonnet_failed")

                time.sleep(0.3)

        total_regulatory += len(regulatory_ids)

    print(f"\n=== Summary ===")
    print(f"  Processed: {total} events")
    print(f"  Regulatory: {total_regulatory} ({total_regulatory/max(total,1)*100:.0f}%)")
    print(f"  Sector signals: {total_signals}")

    return total_regulatory


# Daily cap on cron runs — at ~5-10s per event (Haiku + maybe Sonnet), 500
# events ≈ 45-90 min upper bound. Without this, the 7,500-event backlog from
# a missed week of cron blocks the production pipeline for hours every day
# (witnessed 2026-05-25: classify_regulatory ran 1.5+hr, never reached
# fetch_broker_recos / screener / dossier / email downstream). Manual
# backfills bypass via `python -m sources.regulatory_classifier --events
# --limit N`.
DAILY_CLASSIFIER_CAP = 500


def compute(dry_run=False):
    """Pipeline entry point — classifies both news_articles and regulatory_events.

    Hard-caps each side at DAILY_CLASSIFIER_CAP to keep the cron run bounded
    so downstream production steps (signals → screener → dossier → email) run
    every day. The backlog catches up over multiple days; new daily incoming
    (~50 events) fits comfortably under the cap.
    """
    n1 = classify(limit=DAILY_CLASSIFIER_CAP, dry_run=dry_run)
    n2 = classify_events(limit=DAILY_CLASSIFIER_CAP, dry_run=dry_run)
    return n1 + n2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Max articles to process")
    parser.add_argument("--events", action="store_true", help="Classify regulatory_events (not news_articles)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.events:
        classify_events(limit=args.limit, dry_run=args.dry_run)
    else:
        classify(limit=args.limit, dry_run=args.dry_run)
