# ADR 0024 — Per-signal eligibility + per-stock integrity validator

**Status**: accepted · 2026-05-24
**Implements**: [plan 0005 Phase A + B](../plans/0005-data-confidence-to-95.md)

## Context

Two structural gaps remained after the Health Center work (ADR 0023):

1. **Missing data was indistinguishable from broken data.** When `consensus_signal` was NULL for a SMALL cap, the screener's `weight_coverage` dropped by the consensus weight, leaving us unable to tell:
   - the source legitimately has no data for this SID (yfinance has no analyst), vs.
   - the signal producer broke for this SID.

2. **Picks could contradict themselves across sources.** The 2026-05-22 HALC bug ("16.5% downside at ₹1038" while PT/close = -8.5%) lived in the gap between LLM narrative and structured fields. The dossier validator suppressed raw numbers in prose, but never cross-checked structured fields against each other.

## Decision

### Phase A — per-signal eligibility registry

`eligibility/registry.py` declares per-signal `eligible_universe_sql`. Each query returns the SIDs that SHOULD have a score for that signal. A SID being INELIGIBLE is a deliberate exclusion, not a defect.

- `tools/refresh_eligibility.py` writes one row per (sid, signal, snapshot_date) to `universe_eligibility` nightly (cron step inserted before screener).
- `scoring/screener.py` computes `eligible_coverage = covered / ELIGIBLE` alongside the legacy `weight_coverage = covered / TIER TOTAL`. A LARGE cap missing consensus that was never going to have it gets full credit on eligible_coverage.
- Cockpit Health Center "Universe coverage per signal" section shows eligible/ineligible per signal so a regression (eligible suddenly drops 20% overnight = source went dark) is obvious.

**Not changed in this commit**: the pick gate still uses raw `weight_coverage ≥ 0.50`. Switching the gate to `eligible_coverage` is a behavior change deferred to a follow-up once a few days of data confirm it's stable.

### Phase B — per-stock integrity validator

`validators/per_stock_integrity.py` runs cross-source consistency assertions on every SID in `daily_picks`. Each assertion is a pure function `(row_dict) → (PASS | WARN | FAIL, reason)`. Results stored in `daily_picks.integrity_status` + `integrity_reasons`.

Current assertions:
- `pt_upside_consistency` — `pt_upside_pct` ≈ `(price_target − close) / close` within 0.5pp (the HALC catcher)
- `consensus_requires_attribution` — non-NULL consensus implies `total_analysts > 0` OR `price_target IS NOT NULL`
- `forward_pe_consistency` — `forward_pe` ≈ `close / forward_eps` within 5%
- `f_score_range`, `m_score_realistic`, `base_score_realistic` — range checks
- `eps_growth_requires_eps`, `extreme_growth_clipped` — provenance / sanity

A FAIL bumps the SID out of `cockpit.api.get_top_picks` (which drives morning_brief + action_queue). The SID is retained in `daily_picks` with reasons for review.

### Already paid off

The validator's first run caught 14 real FAILs: `signals/consensus.py` had `total_analysts IS NOT NULL` (passes for `total_analysts = 0`) where it should have been `total_analysts > 0`. Gate tightened in same commit.

## Trade-offs

- **Two coverage metrics** (`weight_coverage` and `eligible_coverage`) is slightly more cognitive load than one, but the alternative is silently picking the wrong default. Keep both during a transition period; deprecate `weight_coverage` once a sustained period of `eligible_coverage` shows no regressions.
- **Integrity validator runs on every screener pass** (~1s for ~1800 picks). Acceptable. If it grows past 10s, batch the cross-source SELECT.
- **Eligibility SQL lives in Python**, not as a SQL view. Reason: per CLAUDE.md ("no frameworks, no base classes, no YAML"). The registry doubles as documentation of "what each signal needs from the source layer".

## Reversal cost

Low. Phase A: drop the `universe_eligibility` table, remove the registry, revert screener changes. Phase B: drop the integrity columns, remove validator import. The bug Phase B already caught (`consensus.py` gate tightening) stays regardless.

## Forward links

- Phase C (coverage gap closure) uses the eligibility registry to drive backfill priorities.
- Phase E (PIT replay) uses both: eligibility per historical date + integrity assertions as part of the replay contract.
