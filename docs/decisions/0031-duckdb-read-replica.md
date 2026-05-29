# 0031 — DuckDB as read-replica for analytical reads

**Status:** Accepted
**Date:** 2026-05-29

## Context

SQLite remains the right authoritative store for v2 — single file, no daemon, WAL concurrency, mature backup tooling, all 93 tables FK-tied to `stocks(sid)` with `PRAGMA foreign_keys=ON` enforced by [db.py:43](../../db.py#L43). It is not the bottleneck for cron writes (single-writer pipeline) or for indexed point lookups.

It IS the bottleneck for **wide column-scan queries** that the cockpit + backtests run constantly:
- `get_backtest_roster` iterates `BACKTEST_SIGNALS` (≈30 entries) and runs a `COUNT DISTINCT snapshot_date + MIN + MAX + AVG(CASE WHEN col IS NOT NULL)` per column per PIT table. Cold render: **5.6s** for the `/model` page.
- `compute_db_health` runs 9 per-table factor checks across 93 tables; `factor_type_conformance` alone was 5.4s on `daily_snapshots_pit` (68 columns × 360K rows × `typeof()`). Cold `/system`: **33.9s**.

The `.pkl` cache layer existed *because* of this. 140× cold-restart improvement (ADR-adjacent — see Stage 2 cockpit split in [HANDOFF 2026-05-28](../../HANDOFF.md)) was load-bearing. If SQLite reads were fast we wouldn't need it.

Benchmark on the live 2.0 GB DB ([tools/bench_duckdb_vs_sqlite.py](../../tools/bench_duckdb_vs_sqlite.py)) — same query, three execution paths:

| Query | SQLite | DuckDB ATTACH→SQLite | DuckDB native |
|---|---:|---:|---:|
| Q1 wide PIT scan (68 cols × 360K rows) | 132.8 ms | 165.8 ms | 4.9 ms (**27×**) |
| Q2 1.5M-row prices aggregation | 962.8 ms | 284.9 ms | 16.9 ms (**57×**) |
| Q3 picks×prices join | 202.4 ms | 300.1 ms | 17.9 ms (**11×**) |

Two unexpected findings worth recording:

1. **`ATTACH sqlite` is not the answer.** Q1 and Q3 are SLOWER through DuckDB-ATTACH-SQLite than direct SQLite, because DuckDB still pays the row-store boundary tax pulling rows out of SQLite before aggregating. Only Q2 wins (3.4×) because aggregation dominates crossing cost.
2. **Native DuckDB file is 87 MB vs 2 GB SQLite** — 23× compression from columnar storage on wide tables. The replica file *itself* makes a useful off-host backup artifact (~30 MB gzipped).

## Decision

Add DuckDB as a **read-replica**, not as a primary store. SQLite stays authoritative; DuckDB is a derived columnar mirror rebuilt nightly.

Specifics:

1. **Mirrored tables** — declared in [db.py:218 `DUCKDB_MIRRORED_TABLES`](../../db.py#L218). Pilot set covers the analytical-scan-heavy nightly-written tables only:
   - `daily_snapshots_pit`, `daily_snapshots_pit_v1`, `pit_ic_by_tier_v1`
   - `stock_prices`, `daily_picks`, `pick_outcomes`, `consensus_signals`
   - **Not mirrored**: small lookup tables (gain negligible), intraday-written tables (`news_articles`, 14:00 forward-cron tables — would be stale by lunch), append-only event tables that are point-lookup-heavy.

2. **Refresh cadence** — [tools/duckdb_refresh.py](../../tools/duckdb_refresh.py) runs once nightly from [run_pipeline.sh](../../run_pipeline.sh) after `pipeline.py` finishes. ≈6 seconds wall-clock to rebuild the full replica. Non-fatal failures: the previous file stays in place; cockpit serves slightly stale data instead of erroring.

3. **Read routing** — new [db.read_sql_fast()](../../db.py#L229) helper. Opens DuckDB read-only if the replica file exists; falls back to SQLite if missing. Caller is responsible for two things:
   - SQL must be DuckDB-dialect (double-quoted identifiers — DuckDB rejects SQLite's `[col]` syntax).
   - Caller only references tables in `DUCKDB_MIRRORED_TABLES`. Mixed queries that need both mirrored + non-mirrored data either split the query or stay on SQLite.

4. **Initial adoption** — one function patched per session, behind a measurable win. First was [cockpit_ops/api.py:get_backtest_roster](../../cockpit_ops/api.py) (5.6s → 1.6s, 3.5×). Expansion target list in [HANDOFF.md](../../HANDOFF.md). No big-bang migration.

5. **What stays on SQLite forever**:
   - All pipeline writes
   - All FK-constrained operations (DuckDB enforces FK on INSERT but NOT on parent DELETE — see point 6 of "Empirical constraint behaviour" in this ADR's session notes)
   - `sqlite3` CLI debugging, ops cockpit `/sql` page, every operator-runbook command in OPERATOR.md §7
   - Anything `INSERT OR IGNORE` / `INSERT OR REPLACE` (DuckDB syntax differs)

## Consequences

**Good:**
- ≈40 lines of new code, zero migration debt. Reversible in 5 minutes (`rm data/alpha_signal.duckdb`, revert 4 files).
- Cockpit cold-path improvements are real and measurable (`/model` 3.5×, more to come).
- The 87 MB DuckDB file makes off-host backup easier as a side benefit (compresses to ~30 MB vs 400 MB for gzipped SQLite).
- Read-replica pattern composes — adding a second function to `read_sql_fast` is a one-line change in that function, no infra work.

**Bad:**
- Two artifacts on disk to reason about (`alpha_signal.db` + `alpha_signal.duckdb`). Cockpit cache invalidation now has a second axis: if you change `DUCKDB_MIRRORED_TABLES` or the mirror set's schema, `rm data/alpha_signal.duckdb` before next run or `read_sql_fast` errors against a missing table.
- DuckDB dialect divergence is a footgun. The first caller patched mid-session caught the bracket-vs-double-quote difference at the keyboard; codebase would benefit from a small linter / test that asserts no `[col]` syntax in functions that route through `read_sql_fast`.
- DuckDB's constraint semantics differ in one specific way: parent-row DELETE that orphans children is BLOCKED on SQLite (with `foreign_keys=ON`), ALLOWED on DuckDB. In the read-replica shape this can't bite (all writes are bulk CTAS, never individual DELETEs), but it would matter if DuckDB ever became authoritative for writes. Recorded here so a future "let's just migrate" doesn't skip the constraint audit.

**Neutral / watch:**
- The intraday-write exclusion list is a per-table decision today; it should become a column on a metadata table if the mirrored set grows past ~15 tables. For now (7 mirrored), inline-in-source is fine.
- Future cockpit functions touching slow paths should be patched one-at-a-time and benched. The remaining big targets are `get_factor_health` (cached at 5min TTL but slow underneath), `get_pick_outcomes_summary` (76K-row aggregations), and any backtest tool that scans `daily_snapshots_pit`.

## References
- Benchmark code + results: [tools/bench_duckdb_vs_sqlite.py](../../tools/bench_duckdb_vs_sqlite.py)
- Refresh script: [tools/duckdb_refresh.py](../../tools/duckdb_refresh.py)
- Read helper: [db.read_sql_fast()](../../db.py#L229)
- First adoption: [cockpit_ops/api.py:get_backtest_roster](../../cockpit_ops/api.py)
- DuckDB 1.5.1 was the version benchmarked; `pip show duckdb` confirms what's installed.
- Empirical constraint behaviour (CHECK / PK / FK-on-INSERT / FK-on-DELETE) verified 2026-05-29 via in-process test (`python -c "import duckdb…"`); CHECK, PK, FK-on-INSERT all match SQLite; FK-on-parent-DELETE is the one divergence (DuckDB allows orphan creation).
