# HANDOFF
Updated: 2026-05-29 | Branch: master (uncommitted, see /handoff diff) | HEAD: `0d8d8bd` feat(track-2.2+screener): Phase 2.2b-v2 split + pledge_quality/delivery_anomaly_z wired

## Left off
Two threads landed this session: (1) **DuckDB read-replica** added behind a one-line refresh step in [run_pipeline.sh](run_pipeline.sh) — `/model` cold went 5.6s → 1.6s, `/system` 33.9s → 13.1s after a separate `factor_type_conformance` query-rewrite + sampling in [health.py:534](health.py#L534); (2) **Plan 0006 Phases A+B+C shipped** — `sector_briefs` + `sector_force_breakdown` tables, classifier, and a new digest at `/sectors` Tab "Today" replacing the rejected 47-card heatmap.

## Pick up here
1. **Phase 2.2b-v2 — tier-aware financial_signal** — pending after parallel session's split (`financial_quality` SMALL, `financial_recovery` MID/LARGE) didn't clear |t|≥2.0. Decision tree in [docs/plans/0001-mother-plan.md §2.2](docs/plans/0001-mother-plan.md) — accumulate more PIT periods, OR re-think direction-flip framing.
2. **Plan 0006 Phase D — LLM sector dossiers** — schema and prompt in [docs/plans/0006-sector-dossiers.md §Phase D](docs/plans/0006-sector-dossiers.md). New `sector_dossiers` table; 11 LLM calls/night (~₹3-5 cost). Mirror `output/dossier.py` hygiene contract (no raw numbers in narrative).
3. **Wire 2 bench factors** — `pledge_quality` SMALL + `delivery_anomaly_z` SMALL — the parallel session committed config but verify they're in [scoring/screener.py:_load_signals()](scoring/screener.py); re-run `python -m tools.optimize_weights` to confirm WIRED_KEYS coverage moves.

## Watch out
- **DuckDB replica is a derived artifact**, rebuilt nightly by `tools.duckdb_refresh`. If you change `DUCKDB_MIRRORED_TABLES` in [db.py:218](db.py#L218), you must also `rm data/alpha_signal.duckdb && python -m tools.duckdb_refresh` or the next `read_sql_fast()` query against a newly-added table will error. Falls back gracefully if file is missing.
- **`read_sql_fast` dialect**: DuckDB rejects SQLite's `[col]` bracket-quoting. Always use double-quotes (`"col"`). Caller is responsible for only referencing tables in `DUCKDB_MIRRORED_TABLES`.
- **Ops cockpit had a latent circular-import bug** — `cockpit_ops/app.py` now imports `cockpit.api` first (see file header comment). Was masked because ops cockpit hadn't restarted since the 2026-05-26 back-import was added; my restart this session exposed it. Don't reorder.
- **`factor_type_conformance` now samples tables >500K rows** (sample size 200K). For rates that round to score=100 the original was already lossy; for rates that would actually demote a score, 200K detects them with high confidence. Sampled rows are flagged "(sampled)" in the issue message.
- **`/sectors` Market force shows "attribution pending"** by design. v2's `fii_dii_cash_flow` is index-level only (`category` ∈ {FII,DII,Client}, no sector column). Phase B writes nothing for market; cockpit shows the gap explicitly.

## Active plan
[docs/plans/0006-sector-dossiers.md](docs/plans/0006-sector-dossiers.md) (Phase D — LLM narration · Phase E — per-sector horizon scores)
