# 0033 — Trust Pipeline + Unified Health Score (UHS)

**Status:** Accepted
**Date:** 2026-05-30
**Plan:** [0007 — trust pipeline + UHS](../plans/0007-trust-pipeline-uhs.md)

## Context
Two silent bugs lived for 20+ days each because every existing data quality check compared values to other internal values — a closed self-validating loop. The BAJAJHLDNG mc_slug bug (21% of moneycontrol slug mappings wrong → 1,115 contaminated `broker_recommendations` rows) and the `forecast_history.price` contamination (Tickertape returned current close labelled as historic PT → contaminated `pt_revision_yoy` factor ≈14% LARGE weight before drop, ADR 0020) both passed every freshness, range, schema, and null check. Both surfaced only by user spot-check.

Beyond silent bugs: the cockpit + email surfaced 11+ disparate quality vocabularies (pipeline SUCCESS/FAILED, freshness FRESH/STALE/OUTDATED, MF data_quality TRUSTED/WOUND_UP/SEGREGATED/INTERVAL/BONUS/ANOMALOUS, dossier integrity PASS/WARN/FAIL, eligibility 0/1, weight_coverage 0-1, eligible_coverage 0-1, fundamental_coverage 0-1, price_rows ≥60, factor verdict KEEP/WEAK/DROP, health email CRITICAL/WARN/INFO). The human reader had no single answer to "is this pick / factor / table trustworthy right now?"

User goal: blindly trust the data before deploying own capital. Plan 0007 estimated the **honest achievable ceiling at our scale (single VM, single user, no paid feed) at ~95/100**. True 100 requires Bloomberg/Refinitiv (~$20K/yr); we don't pay it. This ADR documents what we shipped and the honest limits.

## Decision
Ship two co-equal architecture elements together:

1. **Trust Pipeline — 7 gates per datum.** Every datum-of-record passes seven independent verifications before it can influence a deployable pick:
   - Gate 1 — Identity ([validators/identity_check.py](../../validators/identity_check.py)): the source returned data for the entity we asked for. Per-source rules: moneycontrol slug-segment match, yfinance exact ticker, tickertape `tt_sid==sid`, screener.in H1 contains expected name, ETMoney slug-segment match.
   - Gate 2 — Plausibility ([validators/plausibility.py](../../validators/plausibility.py)): value within domain prior. `PLAUSIBILITY_RANGES` per `(datum_class, segment)`. Hard range → quarantine; extreme range → live + WARN.
   - Gate 3 — Temporal continuity ([validators/temporal_continuity.py](../../validators/temporal_continuity.py)): no silent step-change. `CONTINUITY_THRESHOLDS` per class (stock close 1.4×, analyst PT 1.5×, NAV 3.0×, fundamentals annual 5×). `corporate_actions` escape hatch.
   - Gate 4 — Cross-source ([validators/cross_source.py](../../validators/cross_source.py)): for any datum with ≥2 sources, sources must agree. Per-class tolerance + elevated_tolerance thresholds. PT_EQUALS_PRICE special case for `forecast_history`.
   - Gate 5 — Unit / contract ([validators/unit_contract.py](../../validators/unit_contract.py) + `lineage.UNIT_CONTRACTS`): producer's unit declaration must match consumer's expectation. Heuristic auditor inside `db.upsert_df` catches pct_100/ratio_1 flips.
   - Gate 6 — Lineage completeness ([scoring/confidence.py](../../scoring/confidence.py)): every input traced to a source row. Coverage <80% in `signal_lineage` for a weighted factor caps `dim_provenance` at 10/20.
   - Gate 7 — External anchor ([tools/anchor_audit.py](../../tools/anchor_audit.py)): NSE bhavcopy is the canonical anchor for close/volume/delivery_pct; non-NSE sources must agree within 0.5%/5%/1pp. Manual BSE + AMC factsheet seeds for top-50 LARGE close and top-50 MF return.

   Any FAIL routes the row to `<source_table>_quarantine` (11 mirror tables auto-created from source DDL); consumer SQL `LEFT JOIN`s only `*_trusted` rows. Each verdict persists per `(sid, source_table, source_key, datum_class)` in `trust_verdicts` — the auditable receipt feeding UHS dimensions.

2. **Unified Health Score (UHS) — 0-100 single scale, single colour code.** Replaces the 11+ disparate vocabularies. Five universal dimensions (Provenance / Freshness / Plausibility / Consistency / Coverage, 0-20 each, summing to 100). Same five for any entity — datum, factor, pick, table, system. Roll-up rule:
   ```
   UHS(datum)   = sum of 5 dims (normalised over non-NULL dims)
   UHS(factor)  = weight_coverage-weighted mean of input data UHS
   UHS(pick)    = signal_weight-weighted mean of factor UHS for the SID
   UHS(table)   = median UHS of rows
   UHS(system)  = geometric mean of UHS for tier-1 critical tables
   ```
   Geometric mean for system → a single broken critical table drags the whole score sharply down. No hiding behind averages.

   Bands: ≥80 🟢 TRUSTED · 60-79 🟡 REVIEW · <60 🔴 AVOID. PRELIMINARY label distinguishes "would be TRUSTED if all gates were live" from fully-evaluated TRUSTED. Single source of truth: new table `health_score` (PK: entity_kind, entity_id, snapshot_date). Cockpit + dossier email + ntfy push all read here; nothing computes UHS inline.

The Trust Pipeline produces the dimensions; UHS rolls them up. Both shipped together because neither alone is sufficient.

## Rationale (alternatives weighed)
- **One unified composite score (no separate dimensions)** — easiest to consume but loses the diagnostic information. A reader seeing "this pick is 65" can't tell whether it's data-stale or contradiction-flagged or coverage-thin. Keeping 5 dims surfaced inside one rollup gives both the single-number simplicity and the per-axis drill-down.
- **Block all writes at every gate failure (no quarantine — just refuse)** — cleaner semantics but loses forensic data. The quarantine pattern keeps the rejected row in a schema-correct sibling table so future investigation (or false-positive re-instatement) is trivial. Mirror tables are auto-created by introspection; minor storage cost.
- **Compute UHS only at consumer time (no persistence)** — eliminates the `health_score` table but means cockpit reads do full rollup math every page load. The persistence + 30-day backfill (4,361 rows on first run) makes both cockpit reads and historical drift trends cheap.
- **Skip Gate 7 entirely (closed-loop accepted)** — would honestly admit our scale limits. Rejected: NSE bhavcopy is already authoritative and we already fetch it; promoting it to anchor status was the lowest-cost way to introduce ANY external check, and the synthetic regression fixture proves Gate 7 fires on a +5% poison.
- **Defer vocabulary collapse to a separate plan** — currently the deprecated checks tagged in Phase 7 still appear in the code (just runtime-skipped). A future cleanup deletes them entirely. Trade-off accepted: deletion mid-rollout is risky; tag-and-skip lets us reverse if a gate regresses.

## Constraints / known limits

- **Fundamentals have no external anchor at our scale.** Gate 4 cross-source agreement (Tickertape vs Screener.in vs Moneycontrol) is the best free proxy. Revenue / NPA / EPS / earnings_yield depend entirely on internal cross-source corroboration. Bloomberg/Refinitiv (~$20K/yr) is the upgrade path; not in scope at this budget.
- **UHS dim weighting (20/20/20/20/20) is principled but unvalidated.** New `uhs_calibration_log` table (added in Phase 8) captures the forward-return-by-UHS-bucket relationship; once 6+ months of `pick_outcomes` accumulate the dim weights can be regression-fit. Until then 20/20/20/20/20 is a uniform-prior default.
- **Gate 7 (anchor) is partly manual.** BSE spot-check is a weekly 30-min process; AMC factsheets are monthly 30-min. If skipped >2 weeks, anchor coverage decays. Cockpit `/system` "Anchors" tile (added Phase 8) shows next-due-date.
- **PRELIMINARY label is the polite version of "we don't know."** A factor with Phase 1+3 dims but Phase 4 verdicts still warming up reads as PRELIMINARY ≥80 — the user sees a high score but the label disclaims the partial-evaluation state. Phase 8's 7-day burn-in is when most PRELIMINARY labels should flip to TRUSTED.
- **The honest ceiling is ~95/100, NOT 100/100.** The closed-loop self-validation problem is partially-fixed (price/volume/delivery_pct anchored; fundamentals + analyst PT only cross-source corroborated). True 100 needs an independent fundamental anchor.
- **Quarantine tables grow unboundedly.** 11 mirror tables receive rejected rows over time. Storage cost is small in absolute terms (most rows pass) but adds to backup size. A periodic compaction job is a future plan.
- **Gate 5 heuristic is conservative.** The `pct_100` vs `ratio_1` value-range heuristic in `db._check_frame_units` only fires when >95% of ≥20 non-null values look wrong. False negatives are possible for partial-fill columns; false positives have been weeded out in Phase 4 (two genuine registry mistakes were found and fixed).

## Consequences

- **Every pick now carries a 0-100 UHS score**, persisted on `daily_picks` and surfaced everywhere the user reads picks (dossier email footer per pick, cockpit `/morning-brief` filter, `/explorer/<sid>` Trust tab full breakdown).
- **The pick-eligibility gate gained a 4th condition**: in addition to ADR 0021's `weight_coverage ≥0.50`, `price_rows ≥60`, `fundamental_coverage ≥0.50`, a row must now also have `uhs_score >= 60 OR uhs_score IS NULL` (NULL fallback for legacy rows). UHS <60 picks stay in `daily_picks` for review but never appear in morning_brief or action_queue.
- **Five named bug classes are now caught at fetch time** rather than by user spot-check days later:
  - BAJAJHLDNG class (wrong-entity response) → Gate 1
  - Franklin NAV class (silent step-change) → Gates 2 + 3
  - CCAVENUE class (impossible plausibility) → Gate 2
  - `forecast_history.price` class (close masquerading as PT) → Gate 4
  - pt_upside %-vs-fraction class (unit mismatch) → Gate 5
- **9 historic bugs are permanent pre-push regression tests** in [tools/regression_fixtures.py](../../tools/regression_fixtures.py) — pre-push hook fails on any regression.
- **14 data_sanity checks deprecated** ([tools/data_sanity.py](../../tools/data_sanity.py)) and runtime-skipped (Phase 7); their detection logic now lives in the runtime gates. Entries stay in CHECKS as historical record. A future plan can delete them once burn-in confirms the gates haven't regressed.
- **Cockpit colour vocabulary collapses to one scheme** — 🟢 ≥80, 🟡 60-79, 🔴 <60 — used everywhere (badge, panels, system tiles, email).
- **PIT replay framework gained a parallel discipline**: pre-push runs both the existing PIT replay (catches code-induced pick drift) AND the regression fixtures (catches gate regression). Different bug classes; both required.

## Files

**New modules:**
- [validators/identity_check.py](../../validators/identity_check.py) — Gate 1
- [validators/plausibility.py](../../validators/plausibility.py) — Gate 2
- [validators/temporal_continuity.py](../../validators/temporal_continuity.py) — Gate 3
- [validators/cross_source.py](../../validators/cross_source.py) — Gate 4
- [validators/unit_contract.py](../../validators/unit_contract.py) — Gate 5
- [scoring/health_score.py](../../scoring/health_score.py) — UHS rollup
- [scoring/confidence.py](../../scoring/confidence.py) — Gate 6 + pick-level UHS
- [tools/anchor_audit.py](../../tools/anchor_audit.py) — Gate 7
- [tools/regression_fixtures.py](../../tools/regression_fixtures.py) — 9 historic bugs as pre-push tests
- [tests/test_identity_gate.py](../../tests/test_identity_gate.py) — 16 unit tests
- [scoring/health_score.py](../../scoring/health_score.py) — UHS schema + rollup writer

**New tables:** `health_score`, `trust_verdicts`, `external_anchors`, `uhs_calibration_log`, 11× `*_quarantine` mirrors.

**Producer wiring (5 fetchers):** moneycontrol_recos, banking_metrics, mf_holdings_scrape, yfinance_analyst (Gates 1+2). Tickertape deferred — no payload identifier to verify against.

**Surfaces:** dossier email footer per pick · cockpit `/explorer` Trust tab · cockpit `/morning-brief` UHS filter · `daily_picks.uhs_score` + `uhs_breakdown_json` + `uhs_label` + `uhs_worst_dim`.

**ADR cross-refs:** supersedes parts of [ADR 0019](0019-observability-sensor-surface-alert.md) (sensors-surface-alert pattern still applies for system-level signals; per-row gates absorb the data-quality slice). Extends [ADR 0021](0021-pick-eligibility-gate.md) (UHS ≥60 is the new 4th gate). Extends [ADR 0024](0024-per-signal-eligibility-and-per-stock-integrity.md) (`integrity_status` retained, generalised by UHS Consistency dim). Operates at per-factor level, complementing [ADR 0028](0028-two-variant-factor-model.md)'s per-tier weighting and [ADR 0032](0032-tier-direction-flip-split-signal.md)'s per-signal direction split.

## Trigger to revisit

- **After 7 consecutive days of UHS ribbon emails** (Phase 8 burn-in target). Expected: most PRELIMINARY labels flip to TRUSTED as verdict pools fill; at least 1-3 picks should be downgraded by UHS over the week — proving the gates do work, not theatre.
- **After 6 months of `pick_outcomes` accumulation** (~late Nov 2026). Regress forward-5d return on `daily_picks.uhs_score` to validate the 20/20/20/20/20 dim weighting. If a dim shows zero realised-return information, re-weight.
- **If a 10th silent bug ever appears** (passing all 7 gates and surfacing only by user spot-check), open Plan 0008 to design the 8th gate. The fact that no 10th has surfaced is itself signal.
- **If we can afford a paid feed**, Phase 6's Anchor C (AMC factsheets) extends naturally to Bloomberg/Refinitiv-anchored fundamentals; ceiling moves from ~95/100 toward 99/100.
