# ADR 0054 — Tables grow with concepts, not things

Status: **accepted** 2026-10-01 (Amit: "agree with all", D1–D8 as recommended) · Plan [0017](../plans/0017-data-model-redesign.md) · Census [data-census-2026-09-27](../studies/data-census-2026-09-27.md) · Extends [ADR 0052](0052-seven-building-blocks.md) (Dataset block) · Supersedes the per-table model in `schema.sql` (134 tables)

## Decision
1. **A new thing is a row, never a table or column.** That covers a new factor, source, event type, macro series, fundamental metric, market, model, tier or fund metric. The names live in the code registries and are mirrored into a generated `catalog` table (append-only integer ids, renames declared).
2. **The main DB holds 24 tables across 10 concepts:**

   | Concept | Tables |
   |---|---|
   | Reference | `catalog` · `entities` · `classifications` (valid_from/valid_to) · `identifiers` |
   | Bars | `bars_daily` · `derivative_bars` |
   | Series | `series_values` |
   | Events | `events` · `event_links` |
   | Documents | `documents` |
   | Company facts | `fundamentals` · `estimates` |
   | Features | `feature_values` |
   | Decisions | `runs` · `picks` · `pick_contributions` · `book_weights` · `outcomes` |
   | Research | `factor_tests` |
   | Ops | `step_runs` · `check_results` · `row_issues` · `llm_usage` · `llm_tasks` (the model work queue, [plan 0016](../plans/0016-alpha-signal-mcp.md)) |

   Mutual funds move to `mf.db` (5 tables: `funds` · `fund_nav` · `fund_holdings` · `fund_metrics` · `row_issues`), read by stock code only via `views.py` (ATTACH read-only).
3. **Each concept has one write rule, dispatched by `db.write(dataset, df)`:**
   - append-if-new for events, bars and documents
   - versioned (`fetched_at` + `last_seen_at`) for series, fundamentals and estimates
   - slice-replace per (feature, date) for features
   - append-per-run for decisions

   A test bans raw INSERT/REPLACE/UPDATE/DELETE outside `db.py` (allowlist may only shrink).
4. **Every fact carries `available_at`.** "What did I know on D" is the filter `available_at <= D`. Migrated history gets `available_at` from today's lag rules, and nothing is invented.
5. **Decisions are appended per run.** `picks` and `pick_contributions` are keyed by `run_id`, so reruns and a second run on the same day keep both. Features are not: they are keyed by (feature, date, entity), and a rerun replaces the slice, with `run_id` recording who wrote it. A pick's exact inputs survive in `pick_contributions`.
6. **Storage is split by age.** SQLite holds current and recent rows and takes every write; append-only history (features, events, bars, NAV) is compacted monthly to Parquet; `views.py` reads both through DuckDB (SQLite ATTACHed read-only). Nothing is SQLite-specific (no tier CHECK lists, JSON via `->>`), so Postgres would be a port.
7. **Only `views.py` turns long rows into wide frames.** Surfaces and `pit.load_raw` never read raw long tables. During migration, the old table names survive as compatibility views, and they are retired one reader at a time.

## Why
- **The schema grows with things.** There are 32 `*_scores` tables and 11 quarantine mirrors, and every new source or macro feed means a new table.
- **Copies drift.** The census found five pairs of drifting copies and two multi-producer `OR REPLACE` bugs that nulled another producer's columns.
- **Several "snapshot" tables can't answer "as of D":**
  - the hub's tier is overwritten
  - `forecast_history` is rewritten monthly
  - `analyst_consensus_snapshots` rows are backdated
  - the insider feed has no disclosure date
- **Picks can't be explained or reproduced**: no run id, git sha, or per-factor contributions (review F6/F7).
- **Measured on a snapshot, the new model is exact and not slower** (plan 0017 §6):
  - Compatibility views reproduced seven old tables row for row.
  - The backtest panel reads in 6.2 s from Parquet, against 16.2 s today; its history is 25 MB against 201 MB.
  - Event history is 374 MB against 2.09 GB.
  - With native indexed reads, the screener's inputs build at today's speed.

## Consequences
- **Long SQLite rows cost 2–6× the wide bytes.** Hot data therefore stays small, and history goes to Parquet. Compatibility views over big tables are slow (the panel took 76 s), so hot readers switch to native `views.py` reads in the same stage.
- **Named `views.py` read models** replace ad-hoc SQL in cockpit_ops (coverage, counts) and in tools that `SELECT *` the panel.
- **Enums become catalog-declared integer codes** (no more alphabetical ranking of TEXT labels, e.g. multibagger `promoter_trend`). `signal_lineage`, `external_anchors`, `uhs_calibration_log`, `paper_*` and `pit_ic_by_tier_v1` are retired, each with census evidence.

## Non-goals
Postgres now (one writer; the design keeps it a port) · streaming/Kafka (daily batch) · an ORM (ADR 0004) · concurrent writers (harvest lock + 30 s `busy_timeout`) · a separate warehouse (Parquet + DuckDB is it) · rewriting history to invent PIT timestamps it never had (old rows keep today's lag rules).
