# 0006 — Classifier status tracking on the events table

**Status:** Accepted
**Date:** 2026-04-11
**Decided by:** Amit (with Claude Code)

## Context

The regulatory classifier has two stages: Haiku pre-filter (cheap, asks YES/NO) and Sonnet deep classify (expensive, returns structured JSON). Only events that pass BOTH stages get a row written to `regulatory_signals`.

The original implementation defined "unclassified events" as "events with no row in `regulatory_signals`". This was a bug:

1. Haiku-rejected events never get a signals row (correctly — they're not regulatory). But under the old definition they looked "unclassified", so re-running the classifier would re-Haiku them, wasting tokens.
2. Sonnet errors / bad JSON also produced no signals row. They became indistinguishable from Haiku rejections.
3. When the 2026-04-10 run hit the API budget cap, there was no way to know which events had been processed and which hadn't.

We needed an audit trail of every classifier verdict, including rejections and failures.

## Decision

Add `classifier_status` and `classifier_processed_at` columns to `regulatory_events`. Six terminal states:

- `pending` — never seen by the classifier (default for new events)
- `haiku_rejected` — Haiku said NO (terminal, directly observed)
- `haiku_rejected_inferred` — backfilled via temporal inference for Run 4's gap
- `haiku_passed_sonnet_failed` — Haiku YES but Sonnet errored (retryable)
- `classified` — full pipeline complete, signals saved (terminal)
- `unknown` — oldest events the date-DESC sweep never reached

`classify_events()` updates this column after every Haiku and Sonnet call. The query for unclassified events now reads:

```sql
WHERE classifier_status IN ('pending', 'haiku_passed_sonnet_failed')
```

instead of a left-join against `regulatory_signals`.

## Alternatives considered

- **Separate `classifier_log` table.** More normalized, but every query now needs a join. The status is per-event, so it belongs on the event row.
- **JSON column with verdict history.** Overkill — we don't need history, we need current state.
- **Boolean `processed` flag.** Loses the distinction between rejected/failed/classified. No good.

## Consequences

**Easier:**
- Re-runs only process truly unprocessed events
- Sonnet failures are retryable (status = `haiku_passed_sonnet_failed` is the retry pool)
- "What did the classifier do last night?" is a SQL query against `classifier_processed_at`
- Future audits can verify claims like "we never re-Haiku a rejected event"

**Harder:**
- Schema migration on a populated `regulatory_events` table (~16K rows). Done with ALTER TABLE + a one-shot backfill script.
- One more invariant to maintain — every classifier call must set the status, no "forget to update" code paths.

**Verifier required:** `python -m sources.verify_classifier_trace` mocks Haiku/Sonnet responses and runs all four code paths (Haiku NO / full success / Sonnet fail / Haiku exception). Asserts `classifier_status` is correct in each case. Run after any classifier change.

## References

- Classifier: `sources/regulatory_classifier.py`
- Verifier: `sources/verify_classifier_trace.py`
- The bug discussion is in the project memory and CLAUDE.md.
