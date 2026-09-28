# ADR 0055 — Data supply is declared (feeds), probed (canaries) and logged (run log)

Status: **accepted** 2026-09-28 (Amit: "approved all", plan 0018 D1–D6) · Plan [0018](../plans/0018-data-supply-strategy.md) · Research [0005](../research/0005-source-gap-sweep.md) · Builds on [ADR 0052](0052-seven-building-blocks.md) (Host/Node/Check blocks) · Table shapes follow [ADR 0054](0054-tables-grow-with-concepts.md)

## Decision
1. **Every external data stream is a feed**: one entry in `feeds.py` covering family, status, routes, schedule, canary, PIT and ToS. The **tier** (T1 critical / T2 important / T3 probation) is **derived**:
   - T1 = the feed writes a RAW table that the picks/email critical path reads or writes, or that a wired factor reads.
   - A derivation is judged on its outputs.
   - Tiers are never hand-typed.
2. **Every live feed has a canary.** It is a 1-item live probe (`sources/canaries.py`) run by `tools/canary.py`:
   - 02:45 UTC, T1 daily and T2 Sundays, under the harvest lock.
   - Gates: transport, content, and a **shape fingerprint** vs the accepted baseline (fields removed = FAIL, added = WARN).
   - Every failure is tagged with a symptom class A–H. Verdicts go to `feed_checks` and `checks/feeds.py`, which page by tier.
3. **Every run is logged as structured events** (`runlog.py` → `run_events`):
   - It captures the exact failure point (`file:line`), redacted upstream responses, counters and the output tail.
   - It hooks at the shared choke points (host door, harvest loop, db writes, `pipeline.run_step`, `run.sh logged`), not per module.
   - A failure that is only `print`ed counts as a silent failure.
4. **New sources enter through a funnel**: wanted → candidate → probation → production.
   - Each stage is a status of the same registry entry.
   - Hard gates: ToS-clean and PIT-honest.

## Why
- In 2026 every feed outage was found late, by a person: BSE 403, the Screener session, the NSE insider endpoint, the AMFI columns, the transcripts orphan and the LLM credits.
- The first canary run found a dead fallback route (scrip_master). The first run-log use found two silent bugs:
  - a false identity-gate reject (`&amp;`)
  - every banking quarantine write failing
- Hand-kept criticality drifts; the graph already knows what the email needs.

## Consequences
- **Structure.**
  - `tests/test_feeds.py` fails on an unregistered source module, step or RAW table, an unscheduled production feed, or a T1 feed without a live fallback / serve-stale limit or a canary.
  - `tests/conftest.py` isolates the run log from the live DB.
- **New tables.**
  - `feed_checks` and `run_events` (LOG).
  - New sources use concept-shaped tables, so plan 0017's migration is a rename: `market_events` (≈ `events`) and `analyst_estimates` (≈ `estimates`, versioned).
- **Full harvests are gated too, not just probes** (added the same day):
  - Write contracts (`tables.TABLES` `contract`) block a garbage batch in `db.insert_df` / `upsert_df` before it is written.
  - A self-calibrated row-count band flags a stable step that writes < 0.6× its trailing-20 median.
  - Gate 3 (`tools/reconcile.py`) compares prices with Yahoo and fundamentals with Screener daily.
  - Replay tests run real upstream responses through the real parsers offline.
- **Deferred:**
  - fallback route runner (P3)
  - ecosystem watch + saved quarterly sweep (P4)
  - DQ agent with an L0/L1/L2 permission ceiling (P5, after plan 0016)
- **Not chosen:** a per-module FEED dict (one central file shows the supply map), YAML, a workflow engine, per-request success logging (volume; counters instead).
