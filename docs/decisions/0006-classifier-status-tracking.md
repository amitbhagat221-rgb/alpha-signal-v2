# 0006 — Classifier status tracking on the events table
**2026-04-11 · Accepted**

**Decision.** `regulatory_events` carries `classifier_status` + `classifier_processed_at` columns. Six terminal states: `pending`, `haiku_rejected`, `haiku_rejected_inferred`, `haiku_passed_sonnet_failed`, `classified`, `unknown`. Unclassified-event query is `WHERE classifier_status IN ('pending', 'haiku_passed_sonnet_failed')` — not a left-join against `regulatory_signals`.

**Why.** The classifier has two stages (Haiku pre-filter → Sonnet deep classify). Only events that pass both get a `regulatory_signals` row. The old "no signals row = unclassified" definition meant:
- Haiku-rejected events looked unclassified, so reruns re-Haiku-ed them (wasted tokens)
- Sonnet failures were indistinguishable from rejections
- When the 2026-04-10 run hit budget cap, no way to know what had processed

**Verifier required.** `python -m sources.verify_classifier_trace` mocks all four code paths and asserts state. Run after any classifier change.

**Trade-offs.** One-shot ALTER TABLE + backfill. Every classifier call must update the column — no "forget to update" code paths.

**References.** `sources/regulatory_classifier.py` · `sources/verify_classifier_trace.py`
