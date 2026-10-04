# Data model redesign: tables grow with concepts, not things

## Mission
Design, then plan, a new data model for alpha-signal-v2, working as a senior data engineer would.
The governing principle: **the number of tables grows with the number of concepts, never with the number of things.**
A new factor, data source, event type, macro series, fundamental metric, market, model, tier or fund metric must be a new ROW (usually a catalog entry), never a new table or column.
Today the schema grows with things: 32 `*_scores` tables (one per factor), 11 quarantine copies, and one table per event source and per macro feed. At scale that means thousands of tables.

This session produces a census, a verified design, measurements, **ADR 0054** and **plan 0016**. Then it STOPS for Amit's approval. It changes no production table.

## Winning criteria
1. **Tables per new thing = 0** for all 9 kinds of thing above. Prove it with a worked example for each.
2. **Fixed, small schema.** About 20 tables in the main DB plus about 5 in `mf.db`, each justified by a distinct concept. Every current table maps to a target, or to "delete" with a reason.
3. **One write rule per concept**, enforced by `db.write(dataset, df)` plus a test that bans raw INSERT/REPLACE outside db.py (with a shrinking allowlist).
4. **Point-in-time correct by construction.** Every fact records when it became knowable (`available_at` / `fetched_at`). "What did I know on date D" is a filter, not a rebuild.
5. **Every pick explainable by one query** (run, model, per-factor contributions).
6. **No performance regressions.** Measure screener, `pit.load_raw`, backtest panel reads and the heaviest cockpit routes on a prototype before committing to the design.
7. **A migration anyone can follow:** staged, run side by side with the old tables, gated, and reversible at every stage.

## Starting hypothesis (validate or revise it; don't treat it as a spec)

### Design rules
- **Long, narrow tables for open-ended numbers:** features, fundamentals, series.
- **JSON payloads for varied attributes:** event details, with the hot fields exposed through views.
- **Wide, typed tables only for hot facts whose shape won't change:** daily bars, picks.
- **The catalog is generated from the code registries** (`factors.FACTORS`, `tables.TABLES`, `hosts.HOSTS`), and the code stays the owner. Integer ids stay stable across renames.
- **Types, ranges and units are enforced by `checks/`**, declared per catalog row. `views.py` is the only layer that turns long tables into wide ones; surfaces never read raw long tables.
- **No hard-coded tier lists in the schema.** No CHECK constraints listing tiers; tiers are data in `config.TIERS`.
- **Decisions are appended per run.** If the primary key excludes `run_id`, then say explicitly that reruns replace the previous run's rows. The earlier proposal contradicted itself here, so resolve it deliberately.
- **Versioned snapshots** need `fetched_at` AND `last_seen_at`. Otherwise, when a new version is only written on change, tables that rarely change look stale to the freshness checks.
- **Storage:** SQLite holds hot and recent data; history is Parquet read through DuckDB, which is already in use here. The design must not depend on SQLite, so a later move to Postgres is a port, not a redesign.

### Main database: concepts and their tables
| Concept | Table(s) | Absorbs today |
|---|---|---|
| Reference | `securities`, `security_tiers` (valid_from/valid_to), `security_links`, `calendar`, `catalog` | `stocks`, `scrip_master`, `sector_metadata`, `macro_sector_map`, `historical_universe`, `macro_indicator_meta` |
| Bars | `bars_daily`, `derivative_bars` | `stock_prices`, `fno_bhav` |
| Series | `series` (series_id, date, value, available_at) | `macro_history`, `macro_indicators`, `vix_history`, `nse_index_history`, `fii_dii_*`, `fno_iv_history`, `fno_pcr_history` |
| Events | `events` (type, sid, event_time, available_at, source, payload JSON) | `bse_announcements`, `corporate_actions`, `insider_trades`, `bulk_deals`, `news_articles`, `regulatory_events`, `earnings_calendar`, `event_calendar`, `surveillance_flags`, `policy_events`, `short_selling_data`, `broker_recommendations` |
| Documents | `documents` (long text, compressed or stored as files) | `transcripts`, news and filing text, LLM dossiers and briefs |
| Fundamentals and estimates | `fundamentals`, `estimates` (versioned) | `quarterly_income`, `annual_*`, `fundamentals_screener`, `banking_metrics`, `forecast_history`, `analyst_consensus(_snapshots)` |
| Ownership | `ownership` | `shareholding` (promoter and institutional only) |
| Features | `feature_values` (feature_id, date, entity_id [stock or sector], value, run_id) | 32 `*_scores`, the signal tables, sector PIT tables, the research panels (history to Parquet) |
| Decisions | `runs`, `picks`, `pick_contributions`, `book_weights`, `outcomes` | `daily_picks`, `portfolio_weights`, the outcome tables |
| Research | `factor_tests` | `pit_ic_by_tier_*`, `factor_horizon_gate` |
| Ops | `step_runs`, `check_results`, `row_issues`, `llm_usage` | `pipeline_log`, the log tables, `trust_verdicts`, the quarantine tables |

### Mutual funds: a separate domain in a separate file, `mf.db`
- **Tables:** `funds`, `fund_nav`, `fund_holdings`, `fund_metrics` (long: fund or category × metric × window), and `row_issues`. These replace the 11 `mf_*` tables.
- **Boundary rules:**
  - Each database has one owner, and code never writes across the boundary.
  - Stock code may READ `mf.db` only through `views.py` (ATTACH read-only). There are no cross-file foreign keys, so a check verifies that `fund_holdings.sid` exists in `securities`.
  - Scheduling (`run.sh`), `step_runs` and `checks/` are shared. `tables.TABLES[...]` records which database each dataset lives in.
  - `mf.db` is backed up, rebuilt and monitored on its own.

## Facts verified 2026-09-27 (re-verify; they drift)
- **Tables:**
  - 134 in total.
  - 32 `*_scores`, 11 `*_quarantine` and 11 `mf_*`.
  - 52 foreign keys point at `stocks(sid)`.
- **Size:** 8.6 GB in total. Most of it is raw data, not features.

  | Table | Size |
  |---|---|
  | `bse_announcements` | 1.77 GB (check what makes it so big: probably full text) |
  | `transcripts` | 0.77 GB |
  | `fno_bhav` | 0.75 GB, plus ~0.8 GB of indexes |
  | `mf_nav_history` | 0.49 GB, plus ~0.75 GB of indexes |
  | `stock_prices` | 0.25 GB |
  | `daily_snapshots_pit` | 186 MB, 109 columns, ~494K rows |

- **Can't be collapsed as-is:** these carry TEXT columns that a numeric `feature_values` row can't hold, so decide where their text goes:
  - `insider_signals`
  - `forensic_scores`
  - `nlp_scores`
  - `multibagger_scores`
  - `management_scores`
- **Dead:** the 3 `paper_*` tables have no code references.
- **Not dead:** the `_v1` tables still have 5–6 code readers.
- **Locking:** `busy_timeout` is 5 s, and the logs show 20 "database is locked" errors.
- **Existing building blocks to extend, not replace** (ADR 0052, plan 0015, the 2026-09-26 cleanup):
  - `tables.TABLES` (already has `kind`), `factors.FACTORS`, `hosts.HOSTS`
  - `pit.features_at`, `graph.py` (run order derived from each step's reads/writes), `checks/`, `views.py`, `run.sh`
- **Context:** docs/studies/architecture-review-2026-09-27.md (31/60). F6/F7 (pick provenance) are solved by the Decisions concept.

## Prerequisites (confirm they're done; otherwise schedule them first)
- **F1:** the monthly Tickertape fetches no longer block the 1st-of-month email.
- **F4:** a test gate that can actually fail: pre-push hook with `pipefail`, pytest installed, the suite run before any deploy.

Every migration stage relies on comparison checks, and those are worthless if no gate runs them.

## Process

**Phase A — Census (read-only).** For every table, record:
- concept, grain, primary key, writers (file:line), readers (file:line, including views, templates and tools)
- rows, MB (use `dbstat` on a `.backup` copy), growth per month, cadence
- its time columns, and whether it is point-in-time safe
- the target concept, or "delete"

Save it as `docs/studies/data-census-<date>.md`. Anything that fits no concept is a design question: record it; don't force it into a table.

**Phase B — Design.** Produce:
- the target DDL
- the old → new mapping for every table and column
- the write rule per concept, and `db.write` dispatch
- the catalog, and how it's generated from the code registries
- the `views.py` read models that hide the reshaping
- how `pit.load_raw` and `features_at` read the new model
- the `mf.db` boundary

For each of the 9 kinds of thing, write the ≤10-line change a developer makes to add one.

**Phase C — Stress test the design** against the hard cases before calling it simpler:
- analyst PTs are episodic, and `forecast_history` price is contaminated (ADR 0045)
- HALC-style numbers-in-narrative checks
- restated fundamentals and versions
- corporate adjustments and split-adjusted prices
- Financials eligibility (ADR 0048)
- MICRO exclusion and re-tiering with history
- quarantine and row issues
- LLM outputs as documents
- `reconstruct_pit.py`'s rule of writing only the columns it produced (what replaces it)
- a second market
- 10× factors and 5× universe
- two runs per day
- backup, restore and the DuckDB replica
- MF holdings feeding a future stock signal

**Phase D — Measure on a `.backup` copy (never the live file).** Prototype `feature_values` (backfill the panel), `events` (backfill 3 event tables) and one versioned snapshot. Report:
- size in SQLite vs Parquet
- screener input build time
- `pit.load_raw` / `features_at` time and peak memory
- backtest panel read time
- the heaviest cockpit routes on test ports

Compare each against today's numbers. If long-format SQLite is too big or slow, take the history-in-Parquet path.

**Phase E — Write it down.**
- ADR 0054: decision in the first 10 lines, ≤60 lines total. It records the principle, the concepts, the MF boundary, the storage split, and what it supersedes.
- Plan 0016: stages as checklists, each with its gate, rollback, effort and the tables it retires.
- Update docs/reference/architecture.md "Where the truth lives".

**Phase F — STOP.** Present to Amit and wait for approval:
- the census summary
- the design, and the tables-per-new-thing proof
- the measurements
- table count before and after, main DB and `mf.db`
- the staged plan
- the top risks

Don't create, alter or drop any production table before he approves.

## Proposed migration order (for plan 0016; re-rank with evidence)
0. **Prerequisites F1 and F4, plus quick wins:** merge the 11 quarantine tables into `row_issues`; drop the 3 `paper_*` tables after verification; raise `busy_timeout` to 30 s.
1. **Decisions + `runs`.** Explainable picks. Add `run_id`/`model_id` and `pick_contributions`. `daily_picks` can stay as a compatibility view.
2. **`db.write` + `catalog`,** plus the no-raw-SQL test. Everything after this writes through it.
3. **`mf.db` as the pilot of the side-by-side pattern.** It's low-risk because no ranking dependency crosses the boundary.
4. **Features.** The fastest-growing concept: one table per factor today.
5. **Events + documents.** One table per source today, and the biggest size win.
6. **Series.**
7. **Fundamentals/estimates (versioned) + ownership.** This fixes the point-in-time accuracy gap from today on; older rows stay as accurate as today's lag rules.
8. **Reference split + `security_tiers` history.** 52 foreign keys to `stocks`, so the riskiest: do it last, with a `stocks` compatibility view.

## Gate for every stage (a stage that can't pass stays unmerged)
- **Parity while writing both.** New and old tables are written together, and a comparison check runs in production and must match for N days before any old table is dropped. N is set in the plan.
- **Readers switch through compatibility views, one at a time.**
- **Standard checks.** Tests pass, `pipeline.py --dry-run` works, and every module imports.
- **Backtest data.** `reconstruct_one_date` on 3 monthly dates gives identical values.
- **Live picks.** Today's screener ranks per tier are identical.
- **Cockpit.** All routes return 200, and the HTML matches after normalisation (test ports 3100/3101, `COCKPIT_CACHE_DIR` in the scratchpad).
- **Email and health.** Email HTML is byte-identical, and health/check output is identical.
- **Recovery.** Backup and restore of the new tables are tested, and the DuckDB replica is updated.
- **Runtime.** Critical-path time to the email is no worse.
- **Written rollback.** Every stage has one, and old tables are dropped only in a separate, later commit.

## Non-goals (state why in the ADR)
Moving to Postgres now, streaming or Kafka, an ORM, multiple concurrent writers, a separate warehouse, and rewriting historic data to invent point-in-time timestamps it never had.

## Safety (learned the hard way)
- **Production.** It runs from /home/ubuntu/alpha-signal-v2 via `run.sh` (03:30 UTC morning run). Never edit, merge, deploy, restart services, or ALTER/DROP/VACUUM production tables without Amit's explicit OK. Never do it during the pipeline window.
- **The database.** It is live (8.6 GB). Read it with `file:data/alpha_signal.db?mode=ro`. Do all heavy scans and prototypes on a `.backup` copy in the scratchpad. Take a verified backup before any approved stage is deployed.
- **No network.** Use the LD_PRELOAD `connect()` shim when importing fetchers; see memory `offline_network_isolation`.
- **Worktrees.** Work in git worktrees, and check `git merge-base --is-ancestor <master> HEAD`.
- **Other sessions.** Check first (`git status`, ListAgents), and never stage their uncommitted files.
- **"Unused" ≠ dead.** Check crontab, `run.sh`, dynamic step imports, templates and JS, `.claude/`, commands in docs, and whether it is the only writer of a live table.
- **Agent claims.** They were wrong ~10% of the time; verify every claim in code or SQL. Run ≤4 subagents, each with an explicit file-ownership list.
- **Standing rules.** CLAUDE.md applies: no `git add .`/`-A`, no `--amend`, never `pkill -f "uvicorn cockpit.app"`. Add a checklist bullet before starting.

## Done means
Amit can read one page and see the concepts, the table count before and after, the proof that no new thing ever needs a new table, and the measured cost. He can approve plan 0016 stage by stage, knowing each stage's gate and rollback.
