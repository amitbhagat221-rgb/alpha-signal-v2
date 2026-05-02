# 0001 — SQLite over CSV files

**Status:** Accepted
**Date:** 2026-04-09
**Decided by:** Amit (with Claude Code)

## Context

v1 stored everything as CSV files: `~/alpha-signal/data/` had 80+ CSVs across multiple subdirectories. The "universe" was defined in three different files (`nifty500_list.csv` 501 stocks, `stock_metadata.csv` 501 stocks, `universe.csv` 2,500 stocks). Different scripts read different ones. Insider archive had 96.5% duplicate rows because there was no UNIQUE constraint, just `concat + drop_duplicates` in pandas (which the script forgot to do).

We needed a single source of truth, with constraints enforced by the storage layer rather than hoped for in code.

## Decision

One SQLite database file at `data/alpha_signal.db`. 33 tables across 6 logical groups. WAL journaling for concurrent reads. Schema versioned via `schema.sql` (CREATE TABLE IF NOT EXISTS).

All scripts use the helpers in `db.py` (`get_db()`, `read_table()`, `upsert_df()`, etc.) — no script opens `sqlite3.connect()` directly.

## Alternatives considered

- **Continue with CSVs.** Status quo. Rejected: every problem we hit in v1 was a "CSV said one thing, script assumed another" problem.
- **Postgres.** More features, but requires running a server, has auth, is overkill for a single-user single-VM project. SQLite is a file. Backup = `cp`.
- **DuckDB.** Faster for analytics, OLAP-shaped. But weaker concurrency story and less mature for the write-heavy ingest patterns we need. SQLite is boring and that's good.
- **Parquet + pandas.** Great for read-heavy analytics, awful for incremental writes. We do a lot of "append today's data" — Parquet rewrites the whole file.

## Consequences

**Easier:**
- One backup target (`alpha_signal.db`)
- UNIQUE/PRIMARY KEY constraints enforce dedup at insert time
- Foreign keys catch "wrong sid" bugs at insert time
- SQL is the right query language for this data shape
- WAL allows pipeline tasks to read while one writes

**Harder:**
- Migrations need to be intentional (we use `schema.sql` with IF NOT EXISTS, plus ad-hoc ALTER scripts)
- Notebooks need to use `db.read_table()` instead of `pd.read_csv()` — small workflow cost

**Will bite us if:**
- DB file gets corrupted (mitigation: daily backup; SQLite is very crash-resistant in WAL mode)
- We ever need multi-machine writes (we don't)
- Schema changes get sloppy (mitigation: every schema change goes in `schema.sql` AND has a migration script in `notebooks/` that's runnable on existing DBs)

## References

- Schema: [../reference/schema.md](../reference/schema.md)
- DB helpers: `db.py`
- Original data source audit: [../_archive/2026-04-09-data-source-strategy.md](../_archive/2026-04-09-data-source-strategy.md)
