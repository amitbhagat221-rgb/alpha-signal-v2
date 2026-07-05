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
import re
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


def _title_hash(title):
    """Normalize (lowercase, strip whitespace/punctuation) and hash a headline.

    Same regulatory story arrives via Google News + RBI + PIB + Wayback with
    near-identical headlines — this hash lets the classifier recognize a repeat
    and reuse the prior verdict instead of paying for Haiku/Sonnet again
    (audit Eff-F2)."""
    normalized = re.sub(r"[^a-z0-9]+", " ", str(title).lower()).strip()
    return hashlib.md5(normalized.encode()).hexdigest()


def _dedup_lookup(title_hash, run_cache):
    """Return (status, source_event_id) for a prior classification of this
    title_hash, or (None, None) if this is the first time we've seen it.

    Checks the in-run cache first (catches duplicates arriving in the same
    run, before either has a DB-persisted terminal status), then falls back
    to regulatory_events for duplicates resolved in a prior run."""
    if title_hash in run_cache:
        return run_cache[title_hash]
    row = read_sql(
        "SELECT event_id, classifier_status FROM regulatory_events "
        "WHERE title_hash = ? AND classifier_status IN ('haiku_rejected', 'classified') "
        "ORDER BY classifier_processed_at ASC LIMIT 1",
        params=[title_hash],
    )
    if row.empty:
        return None, None
    return row.iloc[0]["classifier_status"], row.iloc[0]["event_id"]


def _copy_signals(source_event_id, dest_event_id):
    """Copy regulatory_signals rows from a prior classification to a
    duplicate-title event, so downstream sector-signal coverage isn't lost
    just because the API call was skipped. Returns rows copied."""
    sig = read_sql(
        "SELECT sector, is_regulatory, stage, direction, magnitude, time_horizon, "
        "confidence, ai_reasoning FROM regulatory_signals WHERE event_id = ?",
        params=[source_event_id],
    )
    if sig.empty:
        return 0
    sig = sig.copy()
    sig["event_id"] = dest_event_id
    insert_df(sig, "regulatory_signals")
    return len(sig)


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
        "title_hash": _title_hash(article["title"]),
        "classifier_status": initial_status,
        "classifier_processed_at": datetime.now().isoformat(timespec="seconds"),
    }])
    insert_df(event, "regulatory_events")


def _save_event_dedup(article, title_hash, status, source_event_id):
    """Save a news_articles row that duplicates a prior title_hash verdict —
    no Haiku/Sonnet call. Copies sector signals from the source event if it
    was fully classified. Returns signal rows copied."""
    event_id = _event_id(article["article_id"])
    ministry = None
    n_signals = 0
    if status == "classified":
        src = read_sql("SELECT ministry FROM regulatory_events WHERE event_id = ?",
                        params=[source_event_id])
        if not src.empty:
            ministry = src.iloc[0]["ministry"]
        n_signals = _copy_signals(source_event_id, event_id)
    event = pd.DataFrame([{
        "event_id": event_id,
        "title": article["title"][:500],
        "summary": str(article.get("summary", ""))[:2000],
        "source": f"news_{article['source']}",
        "source_url": None,
        "published_at": article["published_at"],
        "ministry": ministry,
        "title_hash": title_hash,
        "classifier_status": status,
        "classifier_processed_at": datetime.now().isoformat(timespec="seconds"),
    }])
    insert_df(event, "regulatory_events")
    return n_signals


def _update_event_status(event_id, status, title_hash=None):
    """UPDATE regulatory_events.classifier_status — called after every Haiku/Sonnet call.
    This is the single source of truth for whether an event has been seen by the classifier."""
    with get_db() as conn:
        if title_hash is not None:
            conn.execute(
                "UPDATE regulatory_events SET classifier_status = ?, classifier_processed_at = ?, "
                "title_hash = ? WHERE event_id = ?",
                (status, datetime.now().isoformat(timespec="seconds"), title_hash, event_id),
            )
        else:
            conn.execute(
                "UPDATE regulatory_events SET classifier_status = ?, classifier_processed_at = ? WHERE event_id = ?",
                (status, datetime.now().isoformat(timespec="seconds"), event_id),
            )


def _reuse_classification_existing(event_id, title_hash, status, source_event_id):
    """Same as _save_event_dedup but for a regulatory_events row that already
    exists (classify_events path — the event was harvested directly, not via
    news_articles) — UPDATE instead of INSERT. Returns signal rows copied."""
    ministry = None
    n_signals = 0
    if status == "classified":
        src = read_sql("SELECT ministry FROM regulatory_events WHERE event_id = ?",
                        params=[source_event_id])
        if not src.empty:
            ministry = src.iloc[0]["ministry"]
        n_signals = _copy_signals(source_event_id, event_id)
    with get_db() as conn:
        conn.execute(
            "UPDATE regulatory_events SET classifier_status = ?, classifier_processed_at = ?, "
            "title_hash = ?, ministry = COALESCE(?, ministry) WHERE event_id = ?",
            (status, datetime.now().isoformat(timespec="seconds"), title_hash, ministry, event_id),
        )
    return n_signals


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
    total_dedup_skipped = 0
    dedup_cache = {}   # title_hash -> (status, source_event_id), same-run duplicates

    for batch_start in range(0, total, batch_size):
        batch = unclassified.iloc[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size

        print(f"\n--- Batch {batch_num}/{total_batches} ({len(batch)} articles) ---")

        # Title-hash dedup: same regulatory story often arrives as multiple
        # separate news_articles rows. Skip the API entirely for a repeat
        # headline and reuse the prior verdict (audit Eff-F2).
        dedup_rows, fresh_rows = [], []
        for _, art in batch.iterrows():
            title_hash = _title_hash(art["title"])
            status, source_event_id = _dedup_lookup(title_hash, dedup_cache)
            if status is not None:
                dedup_rows.append((art, title_hash, status, source_event_id))
            else:
                fresh_rows.append(art)
        fresh_batch = pd.DataFrame(fresh_rows) if fresh_rows else batch.iloc[0:0]

        if dedup_rows:
            print(f"  Dedup: {len(dedup_rows)}/{len(batch)} match a prior headline — reusing verdict, no API call")
            for art, title_hash, status, source_event_id in dedup_rows:
                n_sig = _save_event_dedup(art, title_hash, status, source_event_id)
                total_signals += n_sig
                if status == "classified":
                    total_regulatory += 1
                dedup_cache[title_hash] = (status, _event_id(art["article_id"]))
            total_dedup_skipped += len(dedup_rows)

        # Stage 1: Haiku pre-filter (fresh headlines only)
        print(f"  Stage 1 (Haiku): filtering {len(fresh_batch)} fresh headlines...", end=" ", flush=True)
        regulatory_ids = _prefilter_batch(client, fresh_batch) if len(fresh_batch) else []
        print(f"{len(regulatory_ids)}/{len(fresh_batch)} regulatory")

        # Save non-regulatory as processed (so we don't re-check them)
        for _, art in fresh_batch.iterrows():
            _save_event(art, art["article_id"] in regulatory_ids)
            dedup_cache[_title_hash(art["title"])] = (
                "pending" if art["article_id"] in regulatory_ids else "haiku_rejected",
                _event_id(art["article_id"]),
            )

        # Stage 2: Sonnet deep classification for regulatory articles
        reg_articles = fresh_batch[fresh_batch["article_id"].isin(regulatory_ids)] if len(fresh_batch) else fresh_batch
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
                    dedup_cache[_title_hash(art["title"])] = ("classified", event_id)
                else:
                    # Sonnet failed (API error or bad JSON) — mark accordingly so we can retry
                    _update_event_status(event_id, "haiku_passed_sonnet_failed")

                time.sleep(0.3)  # rate limit for Sonnet

        total_regulatory += len(regulatory_ids)

    print(f"\n=== Summary ===")
    print(f"  Processed: {total} articles")
    print(f"  Regulatory: {total_regulatory} ({total_regulatory/total*100:.0f}%)")
    print(f"  Sector signals: {total_signals}")
    print(f"  Dedup-skipped (repeat headline, no API call): {total_dedup_skipped}")

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
    total_dedup_skipped = 0
    dedup_cache = {}   # title_hash -> (status, source_event_id), same-run duplicates

    for batch_start in range(0, total, batch_size):
        batch = unclassified.iloc[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size

        print(f"\n--- Batch {batch_num}/{total_batches} ({len(batch)} events) ---")

        # Title-hash dedup: the same regulatory story often lands as separate
        # events from Google News + RBI + PIB + Wayback. Skip the API for a
        # repeat headline and reuse the prior verdict (audit Eff-F2).
        dedup_rows, fresh_rows = [], []
        for _, evt in batch.iterrows():
            title_hash = _title_hash(evt["title"])
            status, source_event_id = _dedup_lookup(title_hash, dedup_cache)
            if status is not None and source_event_id != evt["event_id"]:
                dedup_rows.append((evt, title_hash, status, source_event_id))
            else:
                fresh_rows.append(evt)
        fresh_batch = pd.DataFrame(fresh_rows) if fresh_rows else batch.iloc[0:0]

        if dedup_rows:
            print(f"  Dedup: {len(dedup_rows)}/{len(batch)} match a prior headline — reusing verdict, no API call")
            for evt, title_hash, status, source_event_id in dedup_rows:
                n_sig = _reuse_classification_existing(evt["event_id"], title_hash, status, source_event_id)
                total_signals += n_sig
                if status == "classified":
                    total_regulatory += 1
                dedup_cache[title_hash] = (status, evt["event_id"])
            total_dedup_skipped += len(dedup_rows)

        # Stage 1: Haiku pre-filter — update classifier_status after EVERY call
        print(f"  Stage 1 (Haiku): filtering {len(fresh_batch)} fresh headlines...", end=" ", flush=True)
        regulatory_ids = []
        for _, evt in fresh_batch.iterrows():
            prompt = PREFILTER_PROMPT.format(
                title=str(evt["title"])[:200],
                summary=str(evt.get("summary", ""))[:300],
            )
            title_hash = _title_hash(evt["title"])
            try:
                resp = client.messages.create(
                    model=HAIKU_MODEL, max_tokens=5,
                    messages=[{"role": "user", "content": prompt}],
                )
                if "YES" in resp.content[0].text.strip().upper():
                    regulatory_ids.append(evt["event_id"])
                    # Don't update status yet — Sonnet will do it
                    dedup_cache[title_hash] = ("pending", evt["event_id"])
                else:
                    # Haiku rejected — mark + done with this event
                    _update_event_status(evt["event_id"], "haiku_rejected", title_hash=title_hash)
                    dedup_cache[title_hash] = ("haiku_rejected", evt["event_id"])
            except Exception as e:
                print(f"\n  Haiku error: {e}")
                # Don't change status on API error → leaves as pending → safe to retry
            time.sleep(0.1)

        print(f"{len(regulatory_ids)}/{len(fresh_batch)} regulatory")

        # Stage 2: Sonnet deep classify
        reg_events = fresh_batch[fresh_batch["event_id"].isin(regulatory_ids)] if len(fresh_batch) else fresh_batch
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

                    # Mark fully classified + update ministry + title_hash in one statement
                    evt_title_hash = _title_hash(evt["title"])
                    with get_db() as conn:
                        conn.execute(
                            "UPDATE regulatory_events SET classifier_status = ?, classifier_processed_at = ?, "
                            "title_hash = ?, ministry = COALESCE(?, ministry) WHERE event_id = ?",
                            ("classified", datetime.now().isoformat(timespec="seconds"), evt_title_hash,
                             str(ministry) if ministry else None, event_id),
                        )
                    dedup_cache[evt_title_hash] = ("classified", event_id)
                else:
                    # Sonnet failed (API error or bad JSON) — mark so we can retry
                    _update_event_status(event_id, "haiku_passed_sonnet_failed", title_hash=_title_hash(evt["title"]))

                time.sleep(0.3)

        total_regulatory += len(regulatory_ids)

    print(f"\n=== Summary ===")
    print(f"  Processed: {total} events")
    print(f"  Regulatory: {total_regulatory} ({total_regulatory/max(total,1)*100:.0f}%)")
    print(f"  Sector signals: {total_signals}")
    print(f"  Dedup-skipped (repeat headline, no API call): {total_dedup_skipped}")

    return total_regulatory


# Daily cap on cron runs — at ~5-10s per event (Haiku + maybe Sonnet), 500
# events ≈ 45-90 min upper bound. Without this, the 7,500-event backlog from
# a missed week of cron blocks the production pipeline for hours every day
# (witnessed 2026-05-25: classify_regulatory ran 1.5+hr, never reached
# fetch_broker_recos / screener / dossier / email downstream). Manual
# backfills bypass via `python -m sources.regulatory_classifier --events
# --limit N`.
DAILY_CLASSIFIER_CAP = 500


# ─────────────────────────────────────────────────────────────────────────────
# Message Batches API — async two-phase classifier (audit Eff-F2, migrated 2026-07-05)
#
# The sync per-item loop above (classify / classify_events) ran Haiku-then-Sonnet
# in-process and consumed ~54% of the daily pipeline wall-clock (~3,467s). It is
# KEPT as an explicit fallback: compute(sync=True) / `--sync`, an SDK without the
# Batch API, and any Batch-submit error all route back to it (bounded to the cap).
#
# The default path decouples classification from the pipeline. Each daily run:
#   (a) INGEST — poll every in-flight batch; for any that has 'ended', write
#       verdicts/signals with the *exact* same schema/INSERT semantics as the sync
#       path, then mark the batch 'ingested'. Haiku passers are submitted as a
#       Sonnet batch the moment their Haiku batch is ingested.
#   (b) SUBMIT — materialize new news_articles as pending events, then submit
#       today's pending events (post title-hash dedup, capped) as a Haiku batch.
# Net: ~1-2 day latency (fine — output feeds narrative only), near-zero pipeline
# wall-clock, and 50% token cost (Batch API pricing).
#
# classifier_status state machine (regulatory_events.classifier_status):
#   pending                    → needs Haiku (harvested/ingested, not yet submitted)
#   haiku_submitted            → in an in-flight Haiku batch
#   haiku_rejected             → terminal: Haiku said NO
#   sonnet_submitted           → in an in-flight Sonnet batch
#   classified                 → terminal: signals saved
#   haiku_passed_sonnet_failed → Haiku passed but Sonnet errored/bad-JSON → Sonnet retry
# Batch bookkeeping lives in regulatory_batches (see schema.sql).

_BATCHES_DDL = """
CREATE TABLE IF NOT EXISTS regulatory_batches (
    batch_id        TEXT PRIMARY KEY,
    stage           TEXT NOT NULL,
    submitted_at    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'submitted',
    n_items         INTEGER,
    ingested_at     TEXT
)
"""


def _ensure_batches_table():
    """Idempotent runtime guarantee — the daily pipeline does not re-run init_db,
    so create the batch-bookkeeping table here (mirrors sources/mf_holdings_scrape
    self-ensuring its columns). Canonical DDL also lives in schema.sql."""
    with get_db() as conn:
        conn.execute(_BATCHES_DDL)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reg_batches_status ON regulatory_batches(status)"
        )


def _batch_api_available(client):
    return hasattr(client, "messages") and hasattr(client.messages, "batches")


def _custom_id_ok(event_id):
    """Anthropic custom_id must match ^[a-zA-Z0-9_-]{1,64}$. Our event_ids
    (news_<int>, gnews_/rbi_/pib_/wb_<hash>) already satisfy this — an event that
    somehow doesn't is skipped so one bad id can't reject the whole batch."""
    return bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", str(event_id)))


def _haiku_request(event_id, title, summary):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    prompt = PREFILTER_PROMPT.format(
        title=str(title)[:200], summary=str(summary or "")[:300]
    )
    return Request(
        custom_id=event_id,
        params=MessageCreateParamsNonStreaming(
            model=HAIKU_MODEL, max_tokens=5,
            messages=[{"role": "user", "content": prompt}],
        ),
    )


def _sonnet_request(event_id, title, summary, source, published_at):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    prompt = CLASSIFY_PROMPT.format(
        title=str(title)[:300], summary=str(summary or "")[:1000],
        source=source, published_at=published_at,
    )
    return Request(
        custom_id=event_id,
        params=MessageCreateParamsNonStreaming(
            model=SONNET_MODEL, max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        ),
    )


def _result_text(message):
    for block in message.content:
        if block.type == "text":
            return block.text.strip()
    return ""


def _parse_classification(text):
    """Same markdown-tolerant JSON parse the sync Sonnet path uses."""
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _save_signals_for_event(event_id, classification):
    """Write regulatory_signals for a batch-classified event — identical row
    shape and INSERT OR IGNORE semantics to the sync _save_signals path."""
    sectors = classification.get("sectors_affected", [])
    if not sectors:
        return 0
    rows = [{
        "event_id": event_id,
        "sector": s.get("sector", "Unknown"),
        "is_regulatory": 1,
        "stage": classification.get("stage"),
        "direction": s.get("direction", 0),
        "magnitude": s.get("magnitude"),
        "time_horizon": s.get("time_horizon"),
        "confidence": s.get("confidence"),
        "ai_reasoning": s.get("reasoning"),
    } for s in sectors]
    insert_df(pd.DataFrame(rows), "regulatory_signals")
    return len(rows)


def _mark_classified(event_id, ministry):
    with get_db() as conn:
        conn.execute(
            "UPDATE regulatory_events SET classifier_status='classified', "
            "classifier_processed_at=?, ministry=COALESCE(?, ministry) WHERE event_id=?",
            (datetime.now().isoformat(timespec="seconds"),
             str(ministry) if ministry else None, event_id),
        )


def _bulk_mark(id_hash_pairs, status):
    """Mark a set of events with `status` and stamp their title_hash (so dedup
    can recognise repeat headlines once the verdict lands)."""
    now = datetime.now().isoformat(timespec="seconds")
    with get_db() as conn:
        conn.executemany(
            "UPDATE regulatory_events SET classifier_status=?, classifier_processed_at=?, "
            "title_hash=? WHERE event_id=?",
            [(status, now, th, eid) for eid, th in id_hash_pairs],
        )


def _record_batch(batch_id, stage, n_items):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO regulatory_batches "
            "(batch_id, stage, submitted_at, status, n_items, ingested_at) "
            "VALUES (?, ?, ?, 'submitted', ?, NULL)",
            (batch_id, stage, datetime.now().isoformat(timespec="seconds"), n_items),
        )


def _mark_batch_ingested(batch_id):
    with get_db() as conn:
        conn.execute(
            "UPDATE regulatory_batches SET status='ingested', ingested_at=? WHERE batch_id=?",
            (datetime.now().isoformat(timespec="seconds"), batch_id),
        )


def _open_batches():
    return read_sql(
        "SELECT batch_id, stage, n_items FROM regulatory_batches "
        "WHERE status='submitted' ORDER BY submitted_at ASC"
    )


# ── SUBMIT helpers ──

def _ingest_news_to_events(cap):
    """Materialize new news_articles as pending regulatory_events (async submit
    operates on regulatory_events only). Applies the title-hash dedup so a repeat
    headline reuses a prior verdict with no API call (audit Eff-F2). KEEP."""
    unclassified = _get_unclassified().head(cap)
    if unclassified.empty:
        return 0, 0
    n_fresh = n_dedup = 0
    for _, art in unclassified.iterrows():
        th = _title_hash(art["title"])
        status, src = _dedup_lookup(th, {})
        if status is not None:
            _save_event_dedup(art, th, status, src)
            n_dedup += 1
        else:
            _save_event(art, is_regulatory=True)  # writes classifier_status='pending'
            n_fresh += 1
    if n_fresh or n_dedup:
        print(f"  [submit] news→events: {n_fresh} new pending, {n_dedup} dedup-reused")
    return n_fresh, n_dedup


def _submit_sonnet(client, event_ids):
    """Build + submit a Sonnet batch for Haiku passers. Marks them
    'sonnet_submitted'; on submit error routes them to 'haiku_passed_sonnet_failed'
    so the next run retries the Sonnet stage. Returns count submitted."""
    event_ids = [e for e in event_ids if _custom_id_ok(e)]
    if not event_ids:
        return 0
    placeholders = ",".join("?" * len(event_ids))
    rows = read_sql(
        f"SELECT event_id, title, summary, source, published_at "
        f"FROM regulatory_events WHERE event_id IN ({placeholders})",
        params=list(event_ids),
    )
    reqs, ids = [], []
    for _, ev in rows.iterrows():
        reqs.append(_sonnet_request(
            ev["event_id"], ev["title"], ev["summary"], ev["source"], ev["published_at"]))
        ids.append(ev["event_id"])
    if not reqs:
        return 0
    try:
        batch = client.messages.batches.create(requests=reqs)
    except Exception as e:
        print(f"  [submit] WARN Sonnet batch submit failed ({e}) — passers set to retry")
        for eid in ids:
            _update_event_status(eid, "haiku_passed_sonnet_failed")
        return 0
    for eid in ids:
        _update_event_status(eid, "sonnet_submitted")
    _record_batch(batch.id, "sonnet", len(reqs))
    print(f"  [submit] Sonnet batch {batch.id}: {len(reqs)} events")
    return len(reqs)


def _submit_haiku_phase(client, cap):
    """Submit up to `cap` pending events as a Haiku pre-filter batch, after a
    title-hash dedup pass that reuses prior verdicts for free. On submit error,
    fall back to the sync path for this run (bounded to the cap)."""
    pend = read_sql(
        "SELECT event_id, title, summary FROM regulatory_events "
        "WHERE classifier_status='pending' AND title IS NOT NULL AND length(title)>10 "
        "ORDER BY published_at DESC LIMIT ?",
        params=[cap],
    )
    if pend.empty:
        return 0
    reqs, submit_ids = [], []
    dedup_cache = {}
    n_dedup = 0
    for _, ev in pend.iterrows():
        eid = ev["event_id"]
        if not _custom_id_ok(eid):
            continue
        th = _title_hash(ev["title"])
        status, src = _dedup_lookup(th, dedup_cache)
        if status is not None and src != eid:
            _reuse_classification_existing(eid, th, status, src)
            dedup_cache[th] = (status, eid)
            n_dedup += 1
            continue
        reqs.append(_haiku_request(eid, ev["title"], ev["summary"]))
        submit_ids.append((eid, th))
    if n_dedup:
        print(f"  [submit] Haiku dedup: {n_dedup} reused a prior verdict, no API call")
    if not reqs:
        return 0
    try:
        batch = client.messages.batches.create(requests=reqs)
    except Exception as e:
        print(f"  [submit] WARN Haiku batch submit failed ({e}) — falling back to sync")
        return classify_events(limit=cap)
    _bulk_mark(submit_ids, "haiku_submitted")
    _record_batch(batch.id, "haiku", len(reqs))
    print(f"  [submit] Haiku batch {batch.id}: {len(reqs)} events")
    return len(reqs)


def _submit_sonnet_stragglers(client, cap):
    """Sonnet-retry for events that passed Haiku but whose Sonnet stage failed
    (bad JSON, API error, or a prior batch that errored/expired)."""
    strag = read_sql(
        "SELECT event_id FROM regulatory_events "
        "WHERE classifier_status='haiku_passed_sonnet_failed' "
        "ORDER BY published_at DESC LIMIT ?",
        params=[cap],
    )
    if strag.empty:
        return 0
    return _submit_sonnet(client, list(strag["event_id"]))


# ── INGEST helpers ──

def _ingest_haiku(client, results):
    """YES → collect passer; NO → haiku_rejected; errored/expired/canceled →
    back to pending (retry next run). Submits a Sonnet batch for the passers."""
    passers, rejects, requeue = [], [], []
    for r in results:
        eid = r.custom_id
        if r.result.type == "succeeded":
            ans = _result_text(r.result.message).upper()
            (passers if "YES" in ans else rejects).append(eid)
        else:  # errored | expired | canceled — unprocessed, return to pending
            requeue.append(eid)
    for eid in rejects:
        _update_event_status(eid, "haiku_rejected")
    for eid in requeue:
        _update_event_status(eid, "pending")
    if passers:
        _submit_sonnet(client, passers)
    return {"verdicts": len(passers) + len(rejects), "requeued": len(requeue)}


def _ingest_sonnet(results):
    """succeeded+parsed → save signals + classified; bad JSON or errored →
    haiku_passed_sonnet_failed (Sonnet retry). Same INSERT semantics as sync."""
    n_class = n_sig = requeue = 0
    for r in results:
        eid = r.custom_id
        if r.result.type == "succeeded":
            cls = _parse_classification(_result_text(r.result.message))
            if cls:
                n_sig += _save_signals_for_event(eid, cls)
                _mark_classified(eid, cls.get("ministry"))
                n_class += 1
            else:
                _update_event_status(eid, "haiku_passed_sonnet_failed")
        else:  # errored | expired | canceled — retry Sonnet next run
            _update_event_status(eid, "haiku_passed_sonnet_failed")
            requeue += 1
    return {"classified": n_class, "signals": n_sig, "requeued": requeue}


def _ingest_phase(client):
    """Poll every in-flight batch; ingest any that has 'ended'."""
    stats = {"batches": 0, "haiku": 0, "classified": 0, "signals": 0, "requeued": 0}
    open_b = _open_batches()
    for _, row in open_b.iterrows():
        bid, stage = row["batch_id"], row["stage"]
        try:
            b = client.messages.batches.retrieve(bid)
        except Exception as e:
            print(f"  [ingest] retrieve {bid} failed ({e}) — leaving for next run")
            continue
        if b.processing_status != "ended":
            print(f"  [ingest] {stage} batch {bid} still '{b.processing_status}' — next run")
            continue
        results = list(client.messages.batches.results(bid))
        if stage == "haiku":
            h = _ingest_haiku(client, results)
            stats["haiku"] += h["verdicts"]
            stats["requeued"] += h["requeued"]
        else:
            s = _ingest_sonnet(results)
            stats["classified"] += s["classified"]
            stats["signals"] += s["signals"]
            stats["requeued"] += s["requeued"]
        _mark_batch_ingested(bid)
        stats["batches"] += 1
    return stats


def _compute_batch(cap, dry_run, client):
    _ensure_batches_table()

    if dry_run:
        pend = read_sql(
            "SELECT COUNT(*) n FROM regulatory_events WHERE classifier_status='pending'"
        ).iloc[0]["n"]
        strag = read_sql(
            "SELECT COUNT(*) n FROM regulatory_events "
            "WHERE classifier_status='haiku_passed_sonnet_failed'"
        ).iloc[0]["n"]
        open_b = _open_batches()
        print(f"  [batch dry-run] {len(open_b)} in-flight batch(es); "
              f"{pend} pending; would submit up to {min(cap, pend)} to Haiku, "
              f"{min(cap, strag)} to Sonnet-retry")
        return 0

    ingested = _ingest_phase(client)          # Phase A
    _ingest_news_to_events(cap)               # Phase B0
    n_haiku = _submit_haiku_phase(client, cap)  # Phase B1
    n_sonnet_retry = _submit_sonnet_stragglers(client, cap)  # Phase B2

    print("\n=== Regulatory classifier (Message Batches) ===")
    print(f"  Ingested {ingested['batches']} batch(es): "
          f"haiku_verdicts={ingested['haiku']}, classified={ingested['classified']}, "
          f"signals={ingested['signals']}, requeued={ingested['requeued']}")
    print(f"  Submitted: haiku={n_haiku} events, sonnet_retry={n_sonnet_retry} events")
    return ingested["classified"]


def _compute_sync(cap, dry_run):
    """Explicit fallback — the original synchronous per-item Haiku→Sonnet path."""
    n1 = classify(limit=cap, dry_run=dry_run)
    n2 = classify_events(limit=cap, dry_run=dry_run)
    return n1 + n2


def compute(dry_run=False, sync=False, cap=None):
    """Pipeline entry point — async two-phase Message Batches classifier.

    Each run ingests any completed batch (writing verdicts/signals exactly as the
    sync path would) and submits the day's pending events as a new Haiku batch,
    keeping the DAILY_CLASSIFIER_CAP intake cap. `sync=True` (or `--sync`), an SDK
    without the Batch API, and any unexpected batch-path error all fall back to the
    original synchronous per-item path, bounded to the cap.
    """
    cap = DAILY_CLASSIFIER_CAP if cap is None else cap
    if sync:
        return _compute_sync(cap, dry_run)
    try:
        client = _get_client()
    except RuntimeError as e:
        print(e)
        return 0
    if not _batch_api_available(client):
        print("  Batch API unavailable in this SDK — using synchronous fallback")
        return _compute_sync(cap, dry_run)
    try:
        return _compute_batch(cap, dry_run, client)
    except Exception as e:
        print(f"  WARN batch path errored ({e}) — falling back to sync for this run")
        return _compute_sync(cap, dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Max items (sync manual backfill)")
    parser.add_argument("--cap", type=int, help="Override per-run intake cap (batch mode)")
    parser.add_argument("--events", action="store_true", help="Sync-classify regulatory_events directly (manual backfill)")
    parser.add_argument("--sync", action="store_true", help="Force the synchronous per-item path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.events:
        classify_events(limit=args.limit, dry_run=args.dry_run)
    elif args.sync:
        _compute_sync(args.limit or DAILY_CLASSIFIER_CAP, args.dry_run)
    else:
        compute(dry_run=args.dry_run, cap=args.cap)
