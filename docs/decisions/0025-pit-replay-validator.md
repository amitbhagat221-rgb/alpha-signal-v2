# 0025 — PIT replay validator gates push and persists composite signals

**Status:** Accepted
**Date:** 2026-05-25
**Plan:** [0005 Data confidence 75 → 95](../plans/0005-data-confidence-to-95.md) Phase E

## Context
We had no way to prove that a code change in `scoring/`, `signals/`, `sources/`, or `eligibility/` didn't silently shift today's picks. The HALC incident (2026-05-22) — a model dossier showing "16.5% downside" while the structured field claimed +8.5% — was a slow drift across multiple producer changes that nobody caught at push time. Producer rewrites, schema migrations, signal weight tweaks, and config edits can all change the output without changing the test suite.

We also couldn't backtest "would today's code reproduce yesterday's picks given yesterday's inputs?" — necessary for verifying historical PIT integrity. The `daily_snapshots_pit` table stored RAW signal inputs (e.g. `cf_accruals`, `bs_accruals`, `m_score`) but not the COMPOSITE outputs the screener actually uses (`accruals_signal`, `forensic_penalty`). So even with PIT data, we could only validate score_universe code drift on 4 of 8 signals.

## Decision
1. **Freeze the full screener input + output per anchor date**, persisted in a new `pit_replay_snapshots` table. One row per (snapshot_date, sid) with JSON blobs for inputs (18 cols incl. cap_tier, all 8 signals, coverage gates) and outputs (rank, final_score, all *_adj contributions). Tagged with `frozen_at` + `frozen_by_commit`.
2. **Replay = pure function**: load frozen inputs → call current `scoring/screener.score_universe()` → diff vs frozen output. Per-tier verdict from three metrics (top-30 jaccard, max rank shift, max abs(score diff %)) combined to PASS/WARN/FAIL.
3. **Push is gated by a git pre-push hook** at `.git/hooks/pre-push` that only fires when `scoring/`/`signals/`/`sources/`/`eligibility/` files change. FAIL blocks push; WARN allows; bypass requires explicit `git push --no-verify`.
4. **Daily auto-freeze via PIPELINE_STEPS** (`pit_replay_freeze`, non-critical) so the anchor library grows continuously without manual intervention.
5. **`daily_snapshots_pit` stores composite signals too** — added 4 columns (`accruals_signal`, `promoter_signal`, `forensic_penalty`, `smart_money_score`). `pit_accruals`/`pit_promoter`/`pit_forensic` in `tools/reconstruct_pit.py` extended to keep composites from the existing `_compute_scores()` outputs; new `pit_smart_money` helper. Historical replays now cover the full 8 screener inputs, not just 4.

## Rationale (alternatives weighed)
- **Snapshot picks only (cheaper)** — would catch screener changes but not signal-module changes; the replay would need to compare picks against the live output, not a recomputed output. Rejected: misses the most common regression class.
- **Snapshot inputs only (skip outputs)** — would still need a reference for diff. The 2-blob (input+output) design lets a single snapshot serve as both: input drives replay, output is the ground truth.
- **Skip composites (4-of-8 coverage)** — was the initial Slice A scope. Rejected because the hook would only catch drift in score_universe + 4 signals; the other 4 would silently regress until the next day's auto-freeze. Backfilling composites is cheap (one 45s reconstruct_pit run per anchor cohort).
- **Embed full picks in test fixtures (git-tracked)** — fails on size (~1MB per anchor × 7 anchors); SQLite blob is the right home.

## Constraints / known limits
- **Composites for the oldest anchor (2024-09-02) are sparse for promoter_signal** (154/2448 stocks) because `signals.promoter` needs 5 quarterly shareholding rows and the archive thins out that far back. Real data-depth artifact, not a bug. Documented in checklist Next-3 #3.
- **Hook ignores config.py-only changes** — if SIGNAL_WEIGHTS shifts in config without touching signal/scoring code, drift surfaces only on next daily auto-freeze. Acceptable: config changes are rare and intentional, and the warning still appears in `replay-all`.
- **Frozen inputs become stale if input shape changes** (new signal column added). Re-freeze required. Operational chore, not automatic.

## Consequences
- Code drift in scoring/signals/sources/eligibility is caught in <10s at push time, not weeks later when picks look off.
- Adding a new signal now has a checklist: register in screener, add to reconstruct_pit (column + helper + DEFAULT_SIGNALS), re-freeze anchors. Documented in the HANDOFF "Watch out" section.
- Confidence: Plan 0005 climbs from 90 → 93 cleanly.

## Files
- [tools/pit_replay.py](../../tools/pit_replay.py)
- [tools/reconstruct_pit.py:431-485](../../tools/reconstruct_pit.py#L431-L485) (`pit_accruals`/`pit_promoter`/`pit_forensic`/`pit_smart_money`)
- [tools/reconstruct_pit.py:120-160](../../tools/reconstruct_pit.py#L120-L160) (PIT_COLUMNS — 4 composites added)
- [config.py PIPELINE_STEPS `pit_replay_freeze`](../../config.py)
- [.git/hooks/pre-push](../../.git/hooks/pre-push)
- [cockpit/api.py get_health_overview() "pit_replay" tile](../../cockpit/api.py)
