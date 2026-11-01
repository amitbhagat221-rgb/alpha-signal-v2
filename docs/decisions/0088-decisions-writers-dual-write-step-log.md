# ADR 0088 — Decisions and the step log: the producers write v3 themselves; the legacy tables drop on 2026-11-15

**Status:** accepted 2026-11-01 (plan 0030 stage 1 part 3, Tier B under ADR 0086) · **Supersedes:** nothing; refines ADR 0084

## Decision

1. The four Decisions producers (`scoring/screener.py`, `portfolio_construction.py`, `tools/compute_pick_outcomes.py`,
   `tools/portfolio_outcomes.py`) write `runs` / `picks` / `book_weights` / `outcomes` through `datamodel/decisions.py`,
   in the same transaction as their legacy write. `datamodel/sync.py` no longer mirrors those four tables: the daily
   `datamodel_reconcile` and `python -m datamodel.gate decisions` compare the two sides, so a writer that misses v3
   fails parity the same morning. The gate is the proof, not the mirror.
2. The step log moves by code, not by view: `steplog.log` writes the legacy `pipeline_log` row and one `step_runs`
   attempt (RUNNING opens it, the terminal status closes it in place, `attrs.log_id` = the legacy row's id). The sync's
   pipeline_log mirror stays as a watermark catch-up only (a process on older code), and every reader builds its SQL on
   `steplog.source()`, switched by `config.DATA_MODEL["steps"]` ("old" until the first morning run under the writer
   reads the same under both).
3. The test suite seeds Decisions rows through the writers (`tests/v3seed.py`) and reads them under the production
   flag; the `_legacy_reads` fixture is retired.
4. The drop commit for `daily_picks`, `pick_outcomes`, `portfolio_weights`, `portfolio_outcomes` is due on
   **2026-11-15** (14 days after the writers went live on the 2026-11-02 run), after the Parquet export
   (`datamodel/retire.py`); `pipeline_log` drops 14 days after the `steps` flag flips. Both are Tier B.

## Why

- A mirror that rebuilds v3 from the legacy table every morning can never show a writer fault; dual writing with the
  reconcile as the gate can. Python's JSON keeps every float exactly, so parity now holds bit for bit (measured on the
  2026-11-01 rows: 5,413 / 5,162 / 45 / 3 rows, `--exact` PASS), where the SQL mirror differed at 15 digits.
- pipeline_log keeps two rows per attempt and orders by `id`; step_runs keeps one. A view cannot give readers both
  shapes, but a FROM clause under a flag gives them one shape with a rollback.
- The legacy id on the attempt lets the old mirror and the old parity check keep working unchanged through the
  transition, including for processes still on the previous code the morning the change lands.

## Consequences

- `datamodel/sync.py`'s `sync_decisions` keeps only the replay docs, the contributions and today's run provenance.
- The declaration check (`pipeline._check_declared`) treats a view and its tables as the declared legacy name
  (`compat.aliases`); `runs` / `step_runs` are runner tables.
- At the drop: `tables.TABLES` rows and the freshness of the four tables move to `runs` (date column `as_of_date`),
  `checks/ranges.py`'s `pipeline_log.status` rule and `tools/regression_fixtures.py`'s heartbeat fixture move to
  `step_runs`; `tools/duckdb_refresh.py` already copies the view under the legacy name.
