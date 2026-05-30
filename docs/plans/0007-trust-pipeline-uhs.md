# Plan 0007 — Data Quality Trust Pipeline + Unified Health Score

**Status**: proposed · 2026-05-29 · supersedes Next 3 per user direction
**Goal**: every datum-of-record that influences a deployable pick passes 7 independent gates before reaching a snapshot table; one Unified Health Score (UHS, 0-100) replaces the 11+ disparate quality vocabularies the user sees today.
**Baseline today**: ~80-90 checks across 11 subsystems; Plan 0005 reached ~93/100 by user's own measure. Two bugs (BAJAJHLDNG mc_slug + `forecast_history.price`) lived silently 20+ days each because no single layer caught them.
**Honest ceiling**: ~95/100 at our scale. True 100 requires a paid ground-truth feed (Bloomberg/Refinitiv ~$20K/yr); we don't pay it. This plan gets us as close as a single VM + single user can.
**Total estimated effort**: ~10 sessions across 8 phases. Plus recurring 30-min/week (Phase 6 anchors) + 30-min/month (AMC factsheets).

---

## Why this plan

Today the cockpit shows the user 11+ different vocabularies for "is this thing trustworthy?":
pipeline SUCCESS/FAILED, freshness FRESH/STALE/OUTDATED, MF `data_quality` TRUSTED/WOUND_UP/SEGREGATED/INTERVAL/BONUS/ANOMALOUS, dossier integrity PASS/WARN/FAIL, eligibility 0/1, `weight_coverage` 0-1, `eligible_coverage` 0-1, `fundamental_coverage` 0-1, `price_rows ≥60`, factor verdict KEEP/WEAK/DROP, health email CRITICAL/WARN/INFO, sanity-check OK/FAIL. They're at different abstraction levels, use different scales, and the human reader can't see a single answer to *"is this pick / factor / table trustworthy right now?"*

Two silent bugs lived for 20+ days each:
- **BAJAJHLDNG mc_slug** — 21% of moneycontrol slug mappings were wrong → 1,115 contaminated `broker_recommendations` rows. Passed every freshness, range, schema, null check.
- **`forecast_history.price` contamination** — Tickertape returned current close labeled as PT → contaminated `pt_revision_yoy` factor (≈14% LARGE weight before drop, ADR 0020). Passed every existing check.

Both surfaced only by user spot-check. The current quality stack is a closed loop: every check compares data to internal rules; there's no independent ground-truth anchor. This plan adds the missing axes — source-level identity, plausibility priors, temporal continuity, cross-source reconciliation, unit contracts, lineage completeness, and external anchor — and rolls them into one universal score.

User goal stated 2026-05-29: **"make data quality 100% so we can blindly trust the data"** before deploying own capital. We can't reach 100; we can reach ~95 and document the gap honestly.

---

## The Unified Health Score (UHS) — single scale, single colour

One number per entity. Five dimensions per number. Same five for any entity — datum, factor, pick, table, or whole system.

| Range | Colour | Label | Decision binding |
|---|---|---|---|
| ≥80 | 🟢 green | TRUSTED | deployable; appears in `action_queue` + morning_brief |
| 60-79 | 🟡 amber | REVIEW | shown but flagged "manual review before sizing capital" |
| <60 | 🔴 red | AVOID | excluded from `action_queue`, morning_brief, dossier |

**Five universal dimensions, 0-20 each, summing to 100:**

| # | Dimension | What it asks | Source gate |
|---|---|---|---|
| 1 | Provenance | Do we know the source, and did it return data for the entity we asked for? | Gate 1 + Gate 6 |
| 2 | Freshness | Is the value recent enough relative to expected refresh cadence? | existing `data_health()` + Gate 4 |
| 3 | Plausibility | Is the value within the domain prior for this entity's class? | Gate 2 |
| 4 | Consistency | Does it agree with peers (cross-row), prior values (temporal), cross-sources? | Gates 3 + 4 + 5 |
| 5 | Coverage | Is the entity complete relative to its expected inputs? | existing `eligibility/registry.py` + Gate 6 |

**Roll-up rule (uniform):**
```
UHS(datum)   = sum of 5 dimensions, each 0-20
UHS(factor)  = weight_coverage-weighted mean of UHS(input data)
UHS(pick)    = signal_weight-weighted mean of UHS(factor) for the SID
UHS(table)   = median UHS of its rows
UHS(system)  = geometric mean of UHS for tier-1 critical tables
```

Geometric mean for system → a single broken critical table drags the whole score sharply down. No hiding behind averages.

**Single source of truth**: new table `health_score` (PK: `entity_kind, entity_id, snapshot_date`). Every cockpit surface, email row, and dossier badge reads from it — nothing computes UHS inline.

**Vocabulary cuts** (subsumed by UHS, retired in Phase 7):
- All numeric vocabularies (`weight_coverage`, `eligible_coverage`, `fundamental_coverage`, `integrity_status`) → UHS dimensions
- MF `data_quality` enum → UHS plausibility-dim discount + reason
- Factor verdict (KEEP/WEAK/DROP) → factor UHS coverage-dim
- Daily-email severity → UHS thresholds (<60 / 60-79 / ≥80)

11 vocabularies → 1. Dimensions stay rich (5); user sees one number unless drilling down.

---

## The Trust Pipeline (the 7 gates)

Each datum-of-record (a fetched row about to be written) passes through gates in order. Any FAIL → row routed to `<table>_quarantine`; consumer SQL only sees trusted rows. Each verdict persisted per `(sid, source_table, source_key, datum_class)` in new `trust_verdicts` table — the auditable receipt feeding UHS dimensions.

| # | Gate | Runs where | UHS dim it feeds | Catches |
|---|---|---|---|---|
| 1 | Identity | source fetcher pre-write | Provenance | BAJAJHLDNG class |
| 2 | Plausibility | source fetcher pre-write | Plausibility | Franklin NAV 1,628→4,383; CCAVENUE +33,522% |
| 3 | Temporal continuity | source fetcher pre-write | Consistency | Silent step-changes; wound-up reprice |
| 4 | Cross-source reconciliation | sanity batch nightly | Consistency | `forecast_history.price` class |
| 5 | Unit / type contract | producer→consumer boundary | Consistency | pt_upside percent-vs-fraction |
| 6 | Lineage completeness | per-signal compute | Provenance + Coverage | "data with no traced provenance" |
| 7 | External anchor | weekly anchor refresh | Consistency + Plausibility | The closed-loop self-validation problem |

---

## Phases

### Phase 1 — UHS schema + score writer (1 session)
Foundation. Everything later writes here.

**Deliverables**
- New table `health_score` (PK: `entity_kind, entity_id, snapshot_date`). Columns: `dim_provenance`, `dim_freshness`, `dim_plausibility`, `dim_consistency`, `dim_coverage`, `score_total`, `label`, `reasons_json`, `computed_at`.
- New table `trust_verdicts` (PK: `sid, source_table, source_key, datum_class, snapshot_date`). One INTEGER per gate (0=FAIL, 1=PASS, 2=PENDING_REVIEW), `reasons_json`, `verdict_overall`.
- New module `scoring/health_score.py`: `compute_uhs(entity_kind, entity_id, dim_dict)`, `rollup_factor_uhs(factor_id)`, `rollup_pick_uhs(sid, date)`, `rollup_table_uhs(table)`, `rollup_system_uhs()`.
- Reuse `_persisted_cache` decorator for cockpit reads.
- Update `cockpit/api.py:get_health_overview` to read from `health_score` first, falling back to legacy until Phase 7.

**Ship boundary**: `health_score` populated for the 10 wired factors and yesterday's `daily_picks`. `/explorer/<sid>` shows a single UHS badge + 5-dim breakdown. No legacy scores removed yet.

### Phase 2 — Identity Gate (Gate 1, 1 session)
BAJAJHLDNG fix at runtime, not nightly audit.

**Deliverables**
- New `validators/identity_check.py`: `verify_identity(sid, response_payload, source) → (status, expected_co, returned_co, reasoning)`. Per-source rules: moneycontrol slug-segment match; yfinance exact ticker; tickertape `tt_sid == sid`; screener.in `<h1>` company-name; ETMoney slug-segment.
- Wire into `sources/moneycontrol_recos.py`, `sources/tickertape_*.py`, `sources/yfinance_*.py`, `sources/banking_metrics.py`, `sources/mf_holdings_scrape.py`. `INSERT OR REPLACE` becomes: if WRONG_ENTITY → quarantine + verdict; never write to live table.
- New quarantine tables: `<table>_quarantine` mirroring schema of each source-fetching table.
- Existing `_mc_slug_name_mismatch_check` becomes the offline auditor of the live gate (catches gate-regression).

**Ship boundary**: deliberate poison test — fetch BAJAJHLDNG → response carrying BAJAJ FINANCE name → quarantine write + verdict row. UHS provenance dim drops to 0 for that row. `tests/test_identity_gate.py` runs in pre-push.

### Phase 3 — Plausibility + Temporal Continuity + Regression Fixtures (Gates 2+3, 1 session)
Two gates share infrastructure; regression framework lands here so every later phase has fixtures.

**Deliverables**
- New `validators/plausibility.py` with `PLAUSIBILITY_RANGES` dict keyed by `(datum_class, segment)`:
  - `("pt_upside_pct", "LARGE")` → hard `[-50, +100]`, extreme `[-30, +50]`
  - `("pt_upside_pct", "SMALL")` → hard `[-90, +200]`, extreme `[-60, +150]`
  - `("nav_dod_change_pct", "equity_fund")` → hard `[-15, +15]`
  - `("bank_gnpa_pct", "*")` → hard `[0, 20]`
  - `("promoter_pct", "*")` → hard `[0, 100]`
- New `validators/temporal_continuity.py`: per-class thresholds — stock close 1.4× (auto cross-check `corporate_actions`); analyst PT 1.5×; NAV 3.0× (wind-up pattern); fundamentals annual 5×.
- Pattern reuses `sources/mf_data_quality.py:_classify_by_metrics` + `_classify_by_nav_jumps`, generalised from MF to stocks.
- New `tools/regression_fixtures.py`. One JSON fixture per documented historic bug:
  - `bug_2026_05_22_halc_hallucination`
  - `bug_2026_05_23_franklin_nav_repricing`
  - `bug_2026_05_23_forecast_history_contamination`
  - `bug_2026_05_25_bajajhldng_slug`
  - `bug_2026_05_28_ccavenue_pt_upside_outlier`
  - `bug_2026_05_29_financial_signal_tier_direction_flip`
  - `bug_2026_05_29_watchdog_check_constraint_crash`
  - `bug_2026_05_29_dossier_mm_regex_false_positive`
- Extend `tools/pit_replay.py:replay_all` to also run `regression_fixtures.verify_all`. Pre-push hook blocks fixture-breaking commits.

**Ship boundary**: all 8 fixtures green. Franklin NAV row → `mf_nav_history_quarantine`. CCAVENUE pt_upside → `consensus_signals_quarantine`. UHS plausibility + consistency dims drop on quarantined rows.

### Phase 4 — Cross-Source + Unit Contract Gates (Gates 4+5, 1 session)
`forecast_history.price` fix.

**Deliverables**
- New `validators/cross_source.py`: for any datum with ≥2 sources (close, PT, EPS), nightly compute Kendall-τ agreement, flag DIVERGENT_SILENT. Uses `db.read_sql_fast` (DuckDB replica).
- Extend `CROSS_SOURCE_PT_MISMATCH` at `tools/data_sanity.py:818` — generalise from "fires at >30%, ≥10 brokers" to per-(sid, datum_class, date) agreement score feeding UHS consistency dim.
- New `validators/unit_contract.py` + extend `lineage.py` with `UNIT_CONTRACTS` dict keyed by `(table, column)`, values like `pct_100`, `ratio_1`, `inr_crore`, `inr_raw`.
- Producer-side: `FACTOR_LINEAGE` entries gain `unit` field; `db.upsert_df` asserts writer's frame matches declared unit.
- Consumer-side: tiny `db.read_typed(table, col, expected_unit)` helper used by `scoring/screener.py` — asserts column unit matches consumer expectation, fails loudly at boundary.

**Ship boundary**: replay a `forecast_history` row containing today's close — cross-source diff vs `broker_recommendations` + `analyst_consensus` triggers DIVERGENT_SILENT, quarantined. Inject pt_upside row in `ratio_1` format into `pct_100` column — unit gate FAILS at producer with explicit unit mismatch.

### Phase 5 — Lineage Completeness + Pick-Level UHS Rollup (Gate 6, 2 sessions)
Per-pick UHS is the single number the user sees before sizing capital.

**Deliverables**
- New `scoring/confidence.py`: for each `daily_picks` row, computes 5-dim UHS using `health_score` rows for each input factor.
- Gate 6 enforcement: any factor with <80% lineage coverage in `signal_lineage` has Provenance dim capped at 10/20. SMALL caps get a `consensus` waiver per existing eligibility registry.
- New columns on `daily_picks` (via `_COLUMN_MIGRATIONS`): `uhs_score INTEGER`, `uhs_breakdown_json TEXT`, `uhs_label TEXT`, `uhs_worst_dim TEXT`. Compute in `scoring/screener.py:compute` after `validate_picks`.
- Surfaces:
  - Daily dossier email — UHS badge (🟢/🟡/🔴 + score) next to each pick; worst-dim noted if <80
  - Cockpit `/explorer/<sid>` — new "Trust" panel: UHS score + 5-dim radar + gate verdicts table
  - Cockpit `/morning-brief` — picks sorted by UHS desc; <60 hidden by default with "show all" toggle
  - `output/dossier.py:_build_prompt` — UHS + worst_dim in LLM context; narrative must acknowledge weak dim
- Pick-gate extension (additive): existing gate (weight_coverage ≥0.50, price_rows ≥60, fundamental_coverage ≥0.50) PLUS `uhs_score ≥ 60`. <60 → "review only," never in `action_queue`.

**Ship boundary**: every recent `daily_picks` row has `uhs_score ∈ [0,100]`. `/explorer/RELI` shows Trust panel. A <60 SID does NOT appear in morning_brief. Daily email shows UHS ribbon per pick.

### Phase 6 — External Anchor (Gate 7, 1 session) — the closed-loop fix
Three free anchors at our scale.

**Deliverables**
- New table `external_anchors` (`datum_class, sid_or_segment, anchor_value, anchor_source, anchor_date`).
  - **Anchor A — NSE bhavcopy**: promote to ground truth for `close`, `volume`, `delivery_pct` for all 2,448 stocks. Other sources (yfinance) must agree within 0.5% or flag.
  - **Anchor B — BSE official site spot-check**: top-50 LARGE close prices, manually seeded weekly. 30-min/week. Cockpit `/system` shows next-due-date.
  - **Anchor C — AMC factsheets**: monthly, free, top-50 MF schemes. Manual parse → 1Y/3Y return cross-check against `mf_metrics.composite_score`. 30-min/month.
- New `tools/anchor_audit.py` — weekly cron; emits `ANCHOR_DRIFT` verdicts; new `EXTERNAL_ANCHOR_DRIFT` data_sanity check.
- Cockpit `/system` "Anchors" tile: SIDs anchored, drift count last 7d, next manual-anchor due.
- Honest scope statement in plan + cockpit + ADR: fundamentals (revenue, NPA, EPS) have NO external anchor at our scale. Gate 4 cross-source is the best free proxy. Phase explicitly delineates anchored vs cross-source-corroborated.

**Ship boundary**: ≥50 SIDs have weekly anchor rows. `EXTERNAL_ANCHOR_DRIFT` fires on deliberately-corrupted close (test: change a known close by 5% → diff >2% → WARN). Anchors tile shows green.

### Phase 7 — Streamlining: cut subsumed checks + collapse vocabularies (1 session)
**Cuts from `tools/data_sanity.py:CHECKS`** (38 → ~22):
- Remove (Gate 4 covers): `PT_EQUALS_PRICE`, `FORECAST_HISTORY_IS_PRICE_HISTORY`
- Remove (Gate 2 covers all): `PT_UPSIDE_OUT_OF_RANGE`, `BUY_PCT_OUT_OF_RANGE`, `PROMOTER_PCT_OUT_OF_RANGE`, `PLEDGE_PCT_OUT_OF_RANGE`, `M_SCORE_OUT_OF_RANGE`, `Z_SCORE_OUT_OF_RANGE`, `MOM_OUT_OF_RANGE`, `PIOTROSKI_OUT_OF_RANGE`, `FINAL_SCORE_OUT_OF_RANGE`, `CLOSE_PRICE_BAD`
- Remove (Gates 2+4 cover): `CROSS_SOURCE_PT_MISMATCH`, `EXTREME_GROWTH_PCT_IN_TOP_PICKS`
- **Retain**: `MC_SLUG_NAME_MISMATCH` (offline auditor of Gate 1), `LINEAGE_REGISTRY_DRIFT`, all DISTRIBUTION + COVERAGE + CARDINALITY checks (NOT per-row gates).

**Vocabulary collapse**:
- `weight_coverage`, `eligible_coverage`, `fundamental_coverage`, `integrity_status` → all replaced by reading UHS dims from `health_score`. Columns kept on `daily_picks` for back-compat one cycle.
- MF `data_quality` enum → still computed (as input to Gate 2), but consumers read `health_score.label`.
- Daily email severity → REPLACED by UHS bands: <60 = "action required", 60-79 = "review", ≥80 = no mention.
- Cockpit `/system` tile colours: every chip uses the universal 🟢/🟡/🔴 scale.

**Ship boundary**: `data_sanity.CHECKS` shrinks 38 → ~22; all deletions have UHS equivalent. Daily email same-or-fewer issues vs prior 7-day baseline. Cockpit shows ONE colour vocabulary everywhere.

### Phase 8 — Confidence-aware orchestration + ADR + calibration scaffold (2 sessions)
**Deliverables**
- `scoring/screener.py` pick-gate extension: UHS ≥60 is now a first-class gate alongside ADR 0021's three.
- `output/dossier.py` prompt: LLM shown UHS + worst dim. Extends `_NARRATIVE_FIELDS` hygiene with a new banned pattern — cannot claim "strong fundamentals" if `dim_provenance < 12` or `dim_consistency < 12`.
- Daily email + ntfy push: per-pick UHS ribbon. Push fires only on system UHS dropping below 60 or any tier-1 table UHS <60.
- Cockpit `/system` adds Gate-7 dashboard: one tile per gate, yesterday's quarantine count, verdict distribution histogram.
- New table `uhs_calibration_log` — every `pick_outcomes` row joined to its `daily_picks.uhs_score`. Once 6+ months accumulate, regress forward-5d return on UHS to validate the 20/20/20/20/20 dim weighting. Park as future work.
- **New ADR 0033** — "Trust pipeline + Unified Health Score". Documents ceiling = 95/100 honestly. Lists BAJAJHLDNG and forecast_history as canonical cases. Documents explicit out-of-scope items.

**Ship boundary**: 7 consecutive days of daily emails carrying UHS ribbon. At least one pick down-graded by UHS. All 8 regression fixtures green pre-push. ADR 0033 merged. Cockpit shows UHS-only colour vocabulary.

---

## Sequencing rationale

Optimised for silent-bug elimination first, then visibility, then cleanup.

| Phase | Sessions | Why this slot |
|---|---:|---|
| 1. UHS schema | 1 | Foundation — every later phase writes here |
| 2. Identity Gate | 1 | Kills BAJAJHLDNG class immediately; atomic; cheapest |
| 3. Plausibility + Temporal + Fixtures | 1 | Franklin + CCAVENUE class; fixture framework unlocks later phases |
| 4. Cross-source + Unit | 1 | Kills forecast_history class + pt_upside unit-mismatch class |
| 5. Lineage + Pick UHS rollup | 2 | The user-facing payoff — confidence is now in front of every pick |
| 6. External Anchor | 1 | The closed-loop fix; required before deleting redundant checks |
| 7. Streamlining | 1 | Now safe to cut because UHS + gates cover what's deleted |
| 8. Orchestration + ADR | 2 | Polish + calibration scaffold |

**Total: 10 sessions.** Plus recurring 30-min/week (Phase 6 anchors) + 30-min/month (AMC factsheets).

**If forced to ship only 3 sessions**: Phase 1 (UHS) + Phase 2 (Identity) + Phase 5 first half (per-pick rollup using only freshness + coverage dims). Catches ~70% of silent-bug surface and puts UHS in front of the user.

---

## What's deferred / explicitly out of scope

- **Bloomberg/Refinitiv anchor** — ~$20K/yr; documented as the 95→100 ceiling. Defer indefinitely.
- **Per-cell column-level lineage** — `lineage.TABLE_COLUMN_SOURCES` already covers worst tables. Per-cell adds storage without proportional bug-catch.
- **Intraday UHS recompute** — UHS computed at pipeline-write time + nightly rollup. Intraday unnecessary for daily-cadence picks.
- **UHS dim weight calibration** — the 20/20/20/20/20 split is principled but unvalidated. Calibrate against `pick_outcomes` once 6+ months accumulate (late 2026).
- **Live-trade gate** — block trades on UHS <80 once Kite Connect lives. Tiny extension to Phase 8.

---

## Critical files for implementation

**New**:
- `scoring/health_score.py`, `scoring/confidence.py`
- `validators/identity_check.py`, `plausibility.py`, `temporal_continuity.py`, `cross_source.py`, `unit_contract.py`
- `tools/regression_fixtures.py`, `tools/anchor_audit.py`

**New tables**: `health_score`, `trust_verdicts`, `external_anchors`, `uhs_calibration_log`, `<table>_quarantine` (one per source-fetching table)

**Extended**:
- `db.py:_COLUMN_MIGRATIONS` — new columns on `daily_picks`, new tables
- `lineage.py` — `UNIT_CONTRACTS` dict
- `tools/pit_replay.py` — regression fixtures wired in
- `tools/data_sanity.py` — cuts + `EXTERNAL_ANCHOR_DRIFT` check
- `scoring/screener.py` — UHS as 4th pick-gate
- `output/dossier.py` — UHS in prompt + hygiene extension

**Reused patterns**:
- `sources/mf_data_quality.py:_classify_by_metrics` (extend MF→stocks)
- `validators/per_stock_integrity.py` (gate-extension pattern)
- `_persisted_cache` decorator (UHS reads)

---

## Verification (end-to-end)

```bash
# Phase 1
sqlite3 data/alpha_signal.db "SELECT entity_kind, COUNT(*) FROM health_score GROUP BY 1"
curl -s localhost:3000/explorer/RELI | grep "UHS"

# Phase 2
python -m tests.test_identity_gate
sqlite3 data/alpha_signal.db "SELECT COUNT(*) FROM broker_recommendations_quarantine"

# Phase 3
python -m tools.regression_fixtures verify_all
python -m tools.pit_replay replay_all

# Phase 4
sqlite3 data/alpha_signal.db "SELECT COUNT(*) FROM trust_verdicts WHERE gate_4_cross = 0"
python -c "from validators.unit_contract import assert_unit; assert_unit('consensus_signals','pt_upside','pct_100')"

# Phase 5
sqlite3 data/alpha_signal.db "SELECT COUNT(*) FROM daily_picks WHERE uhs_score IS NULL AND pick_date >= date('now','-7 days')"
curl -s localhost:3000/explorer/RELI | grep "Trust panel"

# Phase 6
sqlite3 data/alpha_signal.db "SELECT COUNT(DISTINCT sid_or_segment) FROM external_anchors WHERE anchor_date >= date('now','-7 days')"

# Phase 7
wc -l tools/data_sanity.py

# Phase 8
ls docs/decisions/0033-trust-pipeline-uhs.md
```

---

## Risks & trade-offs

- **Phase 3 fixtures could be wrong** — fixtures encode expected verdicts from current understanding of each bug; the bug could have been subtler. Mitigation: fixtures are versioned, refined on review.
- **UHS dim weights (20/20/20/20/20) are principled but unvalidated**. Calibration log captures forward-return-by-UHS-bucket for retrospective validation; weights are tunable not embedded.
- **Gate 7 (anchor) is partly manual** — weekly + monthly human time. If skipped >2 weeks, anchor coverage decays. Mitigation: cockpit `/system` tile shows next-due-date and turns amber after 7d, red after 14d.
- **Quarantine tables grow** — every fetcher gets a sibling `*_quarantine`. Storage cost small (most rows pass) but adds to backup size. Defer compaction.
- **Phase 7 streamlining could break a forgotten consumer**. Mitigation: PIT replay must PASS after each cut; failure → restore.
- **Doesn't solve ground-truth-for-fundamentals problem**. Documented explicitly. Not solvable at our budget.
