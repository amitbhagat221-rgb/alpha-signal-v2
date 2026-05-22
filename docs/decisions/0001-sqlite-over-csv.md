# 0001 — SQLite over CSV files
**2026-04-09 · Accepted**

**Decision.** One SQLite database at `data/alpha_signal.db`. 51 tables, WAL journaling, schema in `schema.sql`. All scripts go through `db.py` helpers — no direct `sqlite3.connect`.

**Why.** v1 had 80+ scattered CSVs, 3 conflicting "universe" files (501 vs 501 vs 2,500), and 96.5% duplicate rows in `insider_archive.csv` because dedup lived in pandas and the script forgot to call it. We needed constraints enforced by storage, not hoped for in code.

**Trade-offs.**
- Backup = `cp`; UNIQUE/FK catch dedup + wrong-sid bugs at insert time
- Notebooks must use `db.read_table()` instead of `pd.read_csv()` (small workflow cost)
- Schema changes go in `schema.sql` + ad-hoc migration in `notebooks/`

**Not chosen.** Postgres (server overhead). DuckDB (weaker concurrency). Parquet (rewrites whole file on append).

**References.** `db.py` · `schema.sql` · [reference/schema.md](../reference/schema.md)
