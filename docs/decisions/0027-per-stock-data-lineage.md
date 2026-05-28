# ADR 0027 — Per-stock data lineage (three-layer registry + emitter)

**Status**: accepted · 2026-05-25
**Plan**: 0005 Phase F (93 → 95)
**Supersedes**: nothing
**Related**: ADR 0017 (factor library two-tier), ADR 0020 (PT data model v2), the MC slug contamination drive-by (2026-05-25)

## Context

Today's mc_slug contamination drive-by exposed a class of bug we couldn't catch:
21% of `stocks.mc_slug` values pointed at the wrong company's MoneyControl
URL. 1,115 of 3,300 `broker_recommendations` rows and 496 `analyst_consensus`
rows held wrong total_analysts/buy_pct/price_target. The data looked correct
at every freshness check; only a per-stock semantic comparison (slug-company
segment vs `stocks.name`) caught it. Any new contamination of this class
would lie hidden until someone manually noticed a sentinel value.

Plan 0005 Phase F (line 152) calls for "instrument every signal module to
record source-row → factor-input mapping". The naive read (long-format table
of every (sid, factor, source row) emitted on every pipeline run) explodes:
2,448 sids × 63 factors × ~3 source rows ≈ 460K rows/day. Storage discipline
and a clear scope decision are required.

## Decision

Three-layer architecture:

1. **`lineage.FACTOR_LINEAGE` — static factor registry**.
   Declarative dict keyed by canonical factor name (`db.BACKTEST_SIGNALS.signal`),
   covering **all 63 factors** regardless of production status (model_active,
   candidate, library, computed, composite). Each entry declares its read
   spec: source tables, columns, key fields, selection semantics, filter,
   sector exclusions. Sub-factors of the same producer (e.g. `pt_upside` and
   `eps_growth_yoy` both belong to `signals/consensus.py`) get their own
   entries with explicit source-table mappings.

2. **`lineage.TABLE_COLUMN_SOURCES` — column-level provenance**.
   Only mixed-source tables need entries. `analyst_consensus` is the canonical
   case (yfinance, Tickertape, MoneyControl all co-write different columns).
   `stocks.mc_slug` carries an entry as the fragile autosuggest bridge that
   caused the BAJA bug — explicit naming so any lineage UI surfaces it.

3. **`signal_lineage` DB table — dynamic per-sid emission**.
   Per (sid, factor, snapshot_date, source_table, source_key, contribution).
   Populated by `db.emit_lineage()` from each signal module's
   `_compute_scores`. **Gated by `lineage.lineage_active_sids()`** which
   returns the top-300 SIDs from latest `daily_picks` by default (overridable
   via `LINEAGE_SIDS` env var). Off-universe SIDs get static lineage only.

Drift gating: `tools/data_sanity.LINEAGE_REGISTRY_DRIFT` is **CRITICAL** if
any `BACKTEST_SIGNALS` factor lacks a `FACTOR_LINEAGE` entry. Adding a new
factor without lineage is mechanically blocked at the daily health report.

Cockpit: `/api/lineage/{sid}` + a "Data Lineage" panel on stock_detail.html
(Alpine-driven, lazy-loaded on expand). Top-300 SIDs see row-level
provenance; others see the declared static spec.

## Scope decisions

- **Top-300 SIDs, not universe.** The actionable use case is auditing today's
  picks and the action queue. The non-actionable 2,148 SIDs would 7x the
  table size for marginal benefit; their static lineage is enough to answer
  "which sources feed this factor". Override with `LINEAGE_SIDS` env var.
- **Long-format table, not JSON column on `*_signals`.** Queryable, indexable,
  joinable. JSON-on-signal would couple lifetimes 1:1 with signal values
  (a win) but make `WHERE source_table=X` lookups O(N) (a loss).
- **No PIT backfill (this session).** Lineage for the 147 historical PIT
  dates would double table size. The static layer is reconstructible at
  any time; row-level is current-day only for v1.
- **Column-level provenance is first-class.** The BAJA bug lived in column-
  level mixed-source ambiguity — `analyst_consensus.price_target` came from
  MC for some sids and yfinance for others. The lineage UI surfaces this
  per-column so the failure mode is visible.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Registry drifts from code as signals evolve | `LINEAGE_REGISTRY_DRIFT` sanity check; CRITICAL on missing entries |
| Storage explosion | Top-300 gate via `lineage_active_sids()`; per-factor DELETE-before-INSERT keeps idempotent re-runs clean |
| PIT replay divergence | `tools/reconstruct_pit.py` re-implements signal math inline — it does NOT call into `signals.*.compute`. Emitting lineage from PIT replay would diverge from production emission until reconstruct is refactored. Not solved in v1; flagged in plan 0005. |
| Untracked sub-signals | `inherits_from` field lets sub-factors share a parent's read spec while declaring their own `sub_contribution` tag |

## Coverage in this session (wave 1)

- **Static layer**: all 63 BACKTEST_SIGNALS factors have entries
  (`model_active`=6, `candidate`=9, `library`=41, `computed`=2, `composite`=5).
  0 missing, 0 orphan.
- **Dynamic emission**: 2 pilot signals — `signals/consensus.py` emits 460
  rows (3 factors × top-300 ∩ analyst-coverage); `signals/piotroski.py` emits
  ~2,900 rows (1 factor × 11 source rows/sid × ~260 scored top-300 SIDs).
- **Cockpit**: `/api/lineage/{sid}` returns dynamic + static; stock_detail
  Data Lineage panel renders both shapes.
- **Drift gate**: `LINEAGE_REGISTRY_DRIFT` returns 0/63 (clean) currently.

## Deferred to next session

- Roll the dynamic emission pattern across the remaining ~31 factors (every
  signal module that currently writes a `*_signals` table).
- PIT-time lineage capture (after refactoring `reconstruct_pit.py` to call
  into module `_compute_scores` rather than inline math).
- Lineage-based assertions in `validators/per_stock_integrity.py`:
  e.g. "no consensus row sourced from `analyst_consensus.price_target`
  where the originating `mc_slug` points to a different company-name than
  `stocks.name`".
- 90-day retention sweep on `signal_lineage` (table will grow ~3K rows/day
  for the 2 pilot signals; ~30-40K rows/day at full coverage).
