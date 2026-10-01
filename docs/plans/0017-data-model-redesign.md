# Plan 0017 — Data model: tables grow with concepts, not things

**Status:** approved 2026-10-01 (Amit: "agree with all", D1–D8 as recommended). The write side was built on 2026-09-30 as a shadow sync (`datamodel/`, master 13439f9) that fills every v3 table from the legacy tables, with daily parity; see Implementation notes.
**Decision:** [ADR 0054](../decisions/0054-tables-grow-with-concepts.md). **Census:** [data-census-2026-09-27](../studies/data-census-2026-09-27.md).
**Builds on:** [ADR 0052](../decisions/0052-seven-building-blocks.md) and [plan 0015](0015-first-principles-architecture.md): `tables.TABLES`, `factors.FACTORS`, `hosts.HOSTS`, `pit.features_at`, `graph.py`, `checks/`, `views.py` and `run.sh`.
**Sequencing with [plan 0016](0016-alpha-signal-mcp.md)** (agreed with Amit 2026-09-28):
1. **This plan's stage 0 (the remaining items).** Both plans' gates need `ALPHA_DB`, and the live-DB pre-push fixture fires on every push.
2. **Plan 0016 phases 1–3.** They restore the LLM outputs, dead since 2026-08-24 (5 standing CRITICALs), and add `llm_tasks`.
3. **This plan's stages 1–2.** Catalog, `db.write`, tier-history capture; then runs and explainable picks. The MCP gains `explain_pick`.
4. **Plan 0016 phases 4–5.** HTTPS, routine, phone; these wait on 0016's D1/D2.
5. **This plan's stages 3–8.**

**Numbering:** the prompt asked for "plan 0016", but that number was taken the same day by [0016-alpha-signal-mcp](0016-alpha-signal-mcp.md).

**Method:**
- **Phase A, census:** 4 read-only auditors, with the lead re-verifying every load-bearing claim.
- **Phase B, design** (§2–§5): target DDL, table mapping, write rules, catalog.
- **Phase C, stress tests** (§8).
- **Phase D, prototype** (§6): built on a `VACUUM INTO` snapshot copy. Unchanged code ran against compatibility views from a git worktree whose `data/` pointed at the copy. Cockpits ran on 3100/3101 only.

## 1. Winning criteria → where each is met

| # | Criterion | Met by | Proof |
|---|---|---|---|
| 1 | 0 tables per new thing | catalog rows plus 10 generic concept tables | §7: 9 worked examples |
| 2 | Small fixed schema | 24 main (23 here + `llm_tasks` from plan 0016) + 5 `mf.db` (was 134) | §2, census summary |
| 3 | One write rule per concept | `db.write(dataset, df)` dispatch, plus the no-raw-SQL test | §4 |
| 4 | PIT by construction | `available_at` on every fact; versioned facts | §4, §8 |
| 5 | One-query explanation | `runs` ⋈ `picks` ⋈ `pick_contributions` | §5 `views.explain` |
| 6 | No perf regression | Parquet history plus native reads; measured | §6 |
| 7 | Followable migration | 9 stages, each with a gate and a rollback | §9 |

## 2. Target schema (24 tables in the main DB)

Portable types only: TEXT, INTEGER, REAL, BLOB. JSON is read with `->>`. There are no CHECK constraints listing tiers. `WITHOUT ROWID` is a SQLite storage hint, dropped in a Postgres port.

```sql
-- ── Reference ─────────────────────────────────────────────────────────────
CREATE TABLE catalog (            -- generated from code registries (§5); ids append-only
  catalog_id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
  unit TEXT, lo REAL, hi REAL, cadence TEXT, lag_days INTEGER,
  spec TEXT,                      -- JSON: the registry entry (weights, eligibility, enum codes, db file…)
  first_seen TEXT NOT NULL, retired_at TEXT, renamed_from TEXT,
  UNIQUE (kind, name));           -- kind: feature|series|event_type|doc_type|metric|dataset|host|model|check|fund_metric
CREATE TABLE entities (           -- anything a value can be about
  entity_id INTEGER PRIMARY KEY, kind TEXT NOT NULL,   -- security|sector|industry|index|market|portfolio
  key TEXT NOT NULL, market TEXT NOT NULL DEFAULT 'IN', name TEXT,
  listed_on TEXT, delisted_on TEXT, attrs TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE (kind, market, key));
CREATE TABLE classifications (    -- SCD2: tier, sector, industry, index membership, micro…
  entity_id INTEGER NOT NULL, scheme TEXT NOT NULL, value TEXT NOT NULL,
  valid_from TEXT NOT NULL, valid_to TEXT, source TEXT, run_id INTEGER,
  PRIMARY KEY (entity_id, scheme, valid_from)) WITHOUT ROWID;
CREATE TABLE identifiers (        -- NSE symbol, BSE scrip, ISIN, Upstox key, yfinance, Screener/MC slug
  entity_id INTEGER NOT NULL, namespace TEXT NOT NULL, value TEXT NOT NULL,
  valid_from TEXT NOT NULL, valid_to TEXT, attrs TEXT,
  PRIMARY KEY (namespace, value, valid_from)) WITHOUT ROWID;
-- ── Bars ──────────────────────────────────────────────────────────────────
CREATE TABLE bars_daily (         -- stocks AND indices; raw (unadjusted)
  entity_id INTEGER NOT NULL, date TEXT NOT NULL, source TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL, delivery_qty REAL, delivery_pct REAL,
  trades REAL, turnover REAL, fetched_at TEXT NOT NULL,
  PRIMARY KEY (entity_id, date, source)) WITHOUT ROWID;   -- source in PK: a 2nd source can coexist (gate 7 fix)
CREATE TABLE derivative_bars (
  underlying_id INTEGER, symbol TEXT NOT NULL, instrument TEXT NOT NULL, expiry TEXT NOT NULL,
  strike REAL NOT NULL, option_type TEXT NOT NULL, date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, settle REAL, contracts REAL, value REAL, oi REAL, oi_change REAL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (symbol, instrument, expiry, strike, option_type, date)) WITHOUT ROWID;
-- ── Series ────────────────────────────────────────────────────────────────
CREATE TABLE series_values (      -- macro, VIX, FII/DII flows, index-level IV…; revisions append
  series_id INTEGER NOT NULL, date TEXT NOT NULL, value REAL,
  available_at TEXT NOT NULL, fetched_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  PRIMARY KEY (series_id, date, fetched_at)) WITHOUT ROWID;
-- ── Events ────────────────────────────────────────────────────────────────
CREATE TABLE events (
  event_id INTEGER PRIMARY KEY, type_id INTEGER NOT NULL, subtype TEXT,
  entity_id INTEGER, event_time TEXT NOT NULL, available_at TEXT NOT NULL,
  source TEXT NOT NULL, source_key TEXT NOT NULL, payload BLOB,   -- JSON (jsonb in SQLite)
  fetched_at TEXT NOT NULL,
  UNIQUE (type_id, source, source_key));
CREATE INDEX ix_events_entity ON events (entity_id, type_id, event_time);
CREATE INDEX ix_events_type   ON events (type_id, subtype, event_time);
CREATE TABLE event_links (        -- an event about several entities (news → stocks, regulation → sectors)
  event_id INTEGER NOT NULL, entity_id INTEGER NOT NULL, role TEXT NOT NULL, weight REAL,
  PRIMARY KEY (event_id, entity_id, role)) WITHOUT ROWID;
-- ── Documents ─────────────────────────────────────────────────────────────
CREATE TABLE documents (          -- source texts AND model-authored outputs
  doc_id INTEGER PRIMARY KEY, type_id INTEGER NOT NULL,
  entity_id INTEGER, event_id INTEGER, parent_doc_id INTEGER,
  doc_date TEXT NOT NULL, available_at TEXT NOT NULL, source TEXT NOT NULL, source_key TEXT NOT NULL,
  run_id INTEGER, model TEXT, title TEXT,
  fields TEXT,                    -- JSON: validated structured fields — the ONLY place numbers live
  body BLOB, body_path TEXT,      -- zlib text, or a file for very large bodies
  content_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'valid',   -- valid|invalid|superseded
  created_at TEXT NOT NULL,
  UNIQUE (type_id, source, source_key, content_hash));
-- ── Company facts ─────────────────────────────────────────────────────────
CREATE TABLE fundamentals (       -- statements, ratios, bank metrics, shareholding pattern
  entity_id INTEGER NOT NULL, metric_id INTEGER NOT NULL,
  period_end TEXT NOT NULL, period_type TEXT NOT NULL, basis TEXT NOT NULL, source TEXT NOT NULL,
  value REAL, available_at TEXT NOT NULL, fetched_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  PRIMARY KEY (entity_id, metric_id, period_end, period_type, basis, source, fetched_at)) WITHOUT ROWID;
CREATE TABLE estimates (          -- forward-looking opinions: EPS/revenue estimates, PTs, recos
  entity_id INTEGER NOT NULL, metric_id INTEGER NOT NULL, target_period TEXT NOT NULL, source TEXT NOT NULL,
  value REAL, label TEXT, available_at TEXT NOT NULL, fetched_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  PRIMARY KEY (entity_id, metric_id, target_period, source, fetched_at)) WITHOUT ROWID;
-- ── Features ──────────────────────────────────────────────────────────────
CREATE TABLE feature_values (     -- numeric only; enums are integer codes declared in catalog.spec
  feature_id INTEGER NOT NULL, date TEXT NOT NULL, entity_id INTEGER NOT NULL,
  value REAL, run_id INTEGER NOT NULL,
  PRIMARY KEY (feature_id, date, entity_id)) WITHOUT ROWID;
CREATE INDEX ix_fv_entity ON feature_values (entity_id, date);   -- stock page
-- ── Decisions ─────────────────────────────────────────────────────────────
CREATE TABLE runs (
  run_id INTEGER PRIMARY KEY, kind TEXT NOT NULL,     -- morning|forward|watchdog|replay|reconstruct|backtest|manual
  as_of_date TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
  official INTEGER NOT NULL DEFAULT 0,                -- the run whose picks were emailed for as_of_date
  git_sha TEXT, dirty INTEGER, config_hash TEXT, model_id INTEGER, attrs TEXT);   -- attrs: regime, host, argv
CREATE TABLE picks (              -- every ranked stock, not only the emailed ones
  run_id INTEGER NOT NULL, entity_id INTEGER NOT NULL, tier TEXT NOT NULL,
  rank INTEGER, score REAL, selected INTEGER NOT NULL, gate TEXT, uhs REAL, attrs TEXT,
  PRIMARY KEY (run_id, entity_id)) WITHOUT ROWID;
CREATE TABLE pick_contributions (
  run_id INTEGER NOT NULL, entity_id INTEGER NOT NULL, feature_id INTEGER NOT NULL,
  raw REAL, pctile REAL, weight REAL, contribution REAL,
  PRIMARY KEY (run_id, entity_id, feature_id)) WITHOUT ROWID;
CREATE TABLE book_weights (run_id INTEGER NOT NULL, entity_id INTEGER NOT NULL, weight REAL, attrs TEXT,
  PRIMARY KEY (run_id, entity_id)) WITHOUT ROWID;
CREATE TABLE outcomes (           -- entity = a security (pick outcome) or the book (portfolio outcome)
  run_id INTEGER NOT NULL, entity_id INTEGER NOT NULL, horizon_days INTEGER NOT NULL,
  start_date TEXT, end_date TEXT, ret REAL, bench_ret REAL, excess REAL, computed_at TEXT NOT NULL,
  PRIMARY KEY (run_id, entity_id, horizon_days)) WITHOUT ROWID;
-- ── Research ──────────────────────────────────────────────────────────────
CREATE TABLE factor_tests (
  test_id INTEGER PRIMARY KEY, feature_id INTEGER NOT NULL, tier TEXT, horizon_days INTEGER,
  method TEXT NOT NULL, source TEXT NOT NULL, period_start TEXT, period_end TEXT,
  n INTEGER, ic REAL, t_stat REAL, icir REAL, verdict TEXT, run_id INTEGER, computed_at TEXT NOT NULL, attrs TEXT,
  UNIQUE (feature_id, tier, horizon_days, method, source, period_end));
-- ── Ops ───────────────────────────────────────────────────────────────────
CREATE TABLE step_runs (
  run_id INTEGER NOT NULL, step TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, rows INTEGER, error TEXT, attrs TEXT,
  PRIMARY KEY (run_id, step, attempt));
CREATE TABLE check_results (      -- freshness, coverage, UHS dims, trust-gate pass counts, endpoint audits
  check_id INTEGER NOT NULL, subject TEXT NOT NULL, entity_id INTEGER NOT NULL DEFAULT 0, date TEXT NOT NULL,
  status TEXT NOT NULL, score REAL, detail TEXT, run_id INTEGER, checked_at TEXT NOT NULL,
  PRIMARY KEY (check_id, subject, entity_id, date));
CREATE TABLE row_issues (         -- quarantine, trust-gate failures, pull errors
  issue_id INTEGER PRIMARY KEY, dataset TEXT NOT NULL, row_key TEXT NOT NULL, rule TEXT NOT NULL,
  severity TEXT NOT NULL, payload TEXT, run_id INTEGER, detected_at TEXT NOT NULL,
  resolved_at TEXT, resolution TEXT,
  UNIQUE (dataset, row_key, rule, detected_at));
CREATE TABLE llm_usage (…as today…, mode TEXT, run_id INTEGER);   -- mode: api|session|routine
CREATE TABLE llm_tasks (…as plan 0016 §5…);   -- model work queue; created by plan 0016 phase 2, owned there
```

**The 24 tables and why each is a separate concept:**

| # | Concept | Tables | Why this is its own concept |
|---|---|---|---|
| 1 | Reference | `catalog`, `entities`, `classifications`, `identifiers` | Names, things, time-varying labels and external keys each have a different key and change rule |
| 2 | Bars | `bars_daily`, `derivative_bars` | Hot, fixed-shape, largest append volume |
| 3 | Series | `series_values` | Entity-less observations that get revised |
| 4 | Events | `events`, `event_links` | Point-in-time occurrences; the only concept that is many-to-many with entities |
| 5 | Documents | `documents` | Text and model output: large bodies, validated fields |
| 6 | Company facts | `fundamentals`, `estimates` | Period-anchored and versioned. Split because estimates are opinions: separate PIT and plausibility rules (HALC, ADR 0045) |
| 7 | Features | `feature_values` | Derived numbers; the fastest-growing concept |
| 8 | Decisions | `runs`, `picks`, `pick_contributions`, `book_weights`, `outcomes` | Appended per run, and must never be overwritten |
| 9 | Research | `factor_tests` | Evidence about features |
| 10 | Ops | `step_runs`, `check_results`, `row_issues`, `llm_usage`, `llm_tasks` | Operational telemetry, plus the model work queue: leased items with a state machine, not telemetry, but the same owner and cadence (plan 0016 §5) |

**Deliberate changes from the starting hypothesis:**
- **`ownership` is merged into `fundamentals` (family `ownership`).** The shareholding pattern is a period-anchored, versioned, lagged company fact with exactly the same write and PIT rule. Holder-level ownership is `mf.fund_holdings` or insider events.
- **`securities` becomes `entities`.** Sectors, indices, the market and the book also need ids, because features and outcomes are computed about them.
- **`calendar` is dropped.** Sessions come from the index entity's bars; nothing needs a forward holiday table yet.

**`mf.db` (5 tables):**
- `funds (fund_id, scheme_code, name, amc, category, plan, option, isin, attrs, …)`
- `fund_nav (fund_id, date, nav, fetched_at)`
- `fund_holdings (fund_id, as_of, available_at, holding_type[security|sector|asset], holding_key, sid, weight, value, qty, fetched_at)`
- `fund_metrics (subject_kind[fund|category], subject, metric, window, as_of, value, run_id)`
- `row_issues`

## 3. Old → new mapping

Every one of the 134 tables has a target, or DELETE with evidence: see the census table.

**By concept:**

| Target | Absorbs (count) |
|---|---|
| Reference | stocks, scrip_master, historical_universe, macro_indicator_meta, macro_sector_map (5) |
| Bars | stock_prices, nse_index_history, fno_bhav (3) |
| Series | macro_history, fii_dii_cash_flow, fii_dii_positioning (3; vix_history is deleted as a copy) |
| Events | bse_announcements, corporate_actions, corporate_adjustments (derived), insider_trades, bulk_deals, short_selling_data, surveillance_flags, earnings_calendar, regulatory_events, policy_events, news_articles, news_article_stocks→links, broker_recommendations (13) |
| Documents | transcripts, news_enriched, regulatory_signals, news_briefs, sector_dossiers, sector_metadata (6) |
| Company facts | quarterly_income, annual_balance_sheet, annual_cash_flow, fundamentals_screener, banking_metrics, shareholding, analyst_consensus, analyst_consensus_snapshots, forecast_history (9) |
| Features | 32 `*_scores` + consensus/promoter/insider signals, daily_snapshots, daily_snapshots_pit(+v1), fno_iv/pcr_history, universe_eligibility, regime_state, macro_indicators, 5 sector feature tables, sector_briefs (49) |
| Decisions | daily_picks, portfolio_weights, pick_outcomes, portfolio_outcomes, pit_replay_snapshots, daily_changes→view (6) |
| Research | pit_ic_by_tier_v2, factor_horizon_gate (2) |
| Ops | pipeline_log, pit_reconstruction_log, sector_narrative_runs, regulatory_batches, screener_pull_errors, llm_usage, health_score, trust_verdicts, 9 quarantine mirrors (17) |
| mf.db | 9 `mf_*` + 2 MF quarantine mirrors (11) |
| DELETE | event_calendar, sector_policy_pit, paper_positions, paper_trades, paper_nav_history, pit_ic_by_tier_v1, uhs_calibration_log (→ view), external_anchors, vix_history (9) |
| Design question | signal_lineage (D3) |

**Column mapping rules.** Each stage's migration script emits the full per-column manifest and fails on any column it does not map.

| Target | Keys | Values | Time |
|---|---|---|---|
| **Features** | `sid`→entity_id, `snapshot_date`→date | each numeric column → feature `<column>` (a clash gets `<table>.<column>`) | `computed_at`→the run |
| Features: text labels | | enum code, `spec.codes = {"ACCUMULATING": 1, …}`, ordinal where order means something | |
| **Events** | the source natural key → `source_key`, using a *complete* key (adds `person` for insider trades, `buy_sell`/`deal_type` for bulk deals) | every other column → `payload.<column>`; the category → `subtype` | the occurrence column → `event_time`; the dissemination column → `available_at`, else `event_time` + the declared lag |
| **Facts** | `(sid, period/end_date, reporting)` → `(entity, period_end, period_type, basis)` | each numeric column → metric `<family>.<column>` | `fetched_at` → the version start; `available_at` = the filing date if known, else `period_end + lag_days` (60/75/21, today's pit.py rules) |
| **Decisions** | `daily_picks` rows → `picks` under a synthetic `runs` row per historical date (kind=`legacy`, git_sha NULL) | `*_score` inputs → `pick_contributions` where they exist | |
| | `pit_replay_snapshots.inputs_json` → the exact `raw` values for 131 dates | the 9 always-zero `*_adj` columns are dropped | |

**Text that doesn't fit a numeric table** (census C corrected the "5 TEXT tables" claim):
- Flags, grades and trends become enum codes.
- `insider_signals.description` is a template, regenerated in the view.
- `sentiment_scores.latest_headline` is a number stored as text, so it becomes a feature.
- `multibagger_scores.gate_fail` becomes one 0/1 feature per reason.
- No column in the signal tables needs `documents`.

## 4. One write rule per concept

`db.write(dataset, df, run_id=…)` looks up `tables.TABLES[dataset]`, which gains `concept` and `db`, and dispatches:

| Concept | Rule | Mechanics |
|---|---|---|
| reference | upsert by natural key, never delete | `classifications` is SCD2: close the open row (`valid_to = D`), insert the new value |
| bars | append-if-new | `INSERT … ON CONFLICT DO NOTHING`. A correction is `restate=True`: update the row and log a `row_issues` audit entry |
| series, fundamentals, estimates | **versioned** | Compare with the key's latest version. Equal: `UPDATE last_seen_at`. Different or new: INSERT with `fetched_at = now` |
| events, documents | append-if-new on (type, source, source_key[, hash]) | Derived events (`source='derived:<step>'`) slice-replace on (type, source) |
| features | **slice-replace** on (feature_id, date) | One transaction: DELETE the slice, INSERT the rows, `run_id` required. Fixes the "stale row survives a NaN rerun" hole (census C) |
| decisions | append per run | A `runs` row must exist, and rows are immutable. The one exception is `outcomes`, upserted as returns mature |
| ops | per table | `step_runs`/`check_results` upsert on PK; `row_issues` insert, with resolve = UPDATE `resolved_at`; `llm_usage` append; `llm_tasks` insert-if-new on `task_id` (kind:item:input_hash), then status transitions only through plan 0016's `claim`/`submit`/`fail` |

**How `db.write` enforces it:**
- **Unknown names are rejected.** A feature, metric, event type or series not in the catalog is written to `row_issues('unknown_name')` and not stored. That ends silent vocabulary drift, such as the `forecast_history.price` metric (ADR 0045).
- **Catalog ranges are checked.** `lo`/`hi` from the catalog are checked on write; out-of-range rows become `row_issues` (the old quarantine).

**The no-raw-SQL test** (`tests/test_write_discipline.py`):
- It AST-scans every non-test `.py` outside `db.py` for SQL strings that match `INSERT|REPLACE|UPDATE|DELETE`, and for `.to_sql(`.
- It fails on any hit not in `tests/write_allowlist.txt`, a list of `file:function` entries that may only shrink (the test also fails if a listed entry no longer offends).
- `tools/regression_fixtures.py` is on the list only until stage 0 moves it to a temp DB.

## 5. Catalog, registries, and read models

**The code stays the owner of every name.**

| Catalog kind | Comes from |
|---|---|
| feature | `factors.FACTORS` |
| dataset | `tables.TABLES` |
| host | `hosts.HOSTS` |
| model | `config.SCREEN` and the weights hash, per run |
| series, metric, event_type, doc_type | declared *in the dataset entry* that produces them, e.g. `tables.TABLES["macro_mospi"]["series"] = sources.macro_gov.SERIES` or `["metrics"] = sources.screener.LINE_ITEMS` |
| check | `checks/` |
| fund_metric | `mf/metrics.py` |

**How the catalog is maintained:**
- `catalog.sync()` runs at the start of `run.sh` and in tests. It inserts new names, never deletes (it sets `retired_at` instead), and applies declared `renamed_from`.
- Ids are append-only integers held in the DB.
- **Parquet stores names, not ids.** History is self-describing and survives an id remap, and a schema-built DB re-syncs by name.
- `tests/test_catalog.py`: every registry name is present after sync, no id is reused, and every `spec.codes` enum is declared once.

**Read models (`views.py`), the only layer that goes from long to wide:**

| Function | Returns |
|---|---|
| `features(names, start, end, entities=None, run='official')` | wide frame; DuckDB over Parquet + SQLite |
| `panel(names=None, dates=None)` | the backtest panel. It replaces `SELECT * FROM daily_snapshots_pit` in backtest_pit, promotion_gate and ic_decay (census D) |
| `coverage(dataset\|features)` | one grouped query. Replaces the per-column loop in cockpit_ops (measured 25.8 s → 2.6 s) |
| `facts_asof(metrics, D, basis='consolidated')` | for each key, the latest version with `fetched_at ≤ D` among rows with `available_at ≤ D`. Before capture starts it falls back to the latest version, which is today's behaviour, for parity |
| `estimates_asof(metrics, D)`, `pt_monthly(D)` | the monthly snapshot is a *view* (as-of the 1st business day), not rows |
| `events(type, start, end, available_by=D, subtypes=None)` | indexed; the hot payload fields are exploded |
| `bars(entities, start, end, adjusted=True, as_of=D)` | applies only price_adjustment events with ex_date ≤ D |
| `tier_asof(D)`, `universe_asof(D)` | from `classifications` |
| `picks(as_of, run='official', gated=True)` and `explain(run_id, entity)` | **explain is one query:** `runs ⋈ picks ⋈ pick_contributions ⋈ catalog`. The gate also fixes review F15 |

**MCP (plan 0016) is the fourth `views.py` consumer**, after the cockpit, the email and the dossier.
- Its research tools call `views.py` and cockpit functions, never table names, so they survive every stage unchanged.
- The exceptions are its `sql` and `schema` tools, which expose physical names. Old names live on as compatibility views until each drop commit, and the tool snapshot tests are in the standard gate (k).
- Stage 2 adds `explain_pick(sid, date|run)` → `views.explain`.

**`pit.load_raw` / `features_at`:**
- `RAW_SQL[k]` becomes `RAW_VIEWS[k] = lambda: views.<fn>(…)` returning the *same frame shape*, so producers don't change.
- `knowable_quarterly`/`annual`/`shareholding` become `available_at <= D` filters. Migrated rows carry `available_at = end_date + lag`, so results are identical by construction (stage gate: `reconstruct_one_date` on 3 dates).

**Storage split:**
- SQLite holds every write, plus current and recent rows. The hot window is 13 months for features, events, bars and NAV; facts, reference and decisions are all hot.
- `tools/compact.py` (monthly, 2nd of month) copies closed months to `data/history/<concept>/<yyyy>/<mm>.parquet`. It verifies row-count and checksum parity, rclone-backs the file up, then deletes those hot rows. Never the reverse order.
- `views.py` reads with one DuckDB connection: `ATTACH` the SQLite file `READ_ONLY` (the `sqlite_scanner` extension is installed locally) and UNION the Parquet glob. That was measured at 8.4 s for 13.1M rows.
- The `alpha_signal.duckdb` replica and `tools/duckdb_refresh` are retired.

## 6. Measurements (Phase D, snapshot 2026-09-27; 4 vCPU ARM, 23 GB RAM)

**Parity:**
- 7 old tables were rebuilt in the new model: daily_snapshots_pit, daily_snapshots_pit_v1, bse_announcements, insider_trades, bulk_deals, quarterly_income and forecast_history.
- Compatibility views with the old names returned **identical rows and values** for all 7: 3,298,838 rows, NaN-aware and exact.
- That was after fixing two prototype slips that the check caught:
  - NULL subcategory had been encoded as `''`.
  - 25,802 stock-dates with all-NULL features had vanished. The fix is an `in_universe` membership feature, because row existence is itself a fact.

**Size and speed:**

| Measure | Today | New, SQLite long / compatibility view | New, native read / Parquet history |
|---|---|---|---|
| Backtest panel full read (v2) | 16.2 s, 3.1 GB peak | 76 s through the SQL pivot view ✗ | **6.2 s**, 3.1 GB (DuckDB PIVOT over Parquet) |
| Panel, 10 features × all dates | n/a (loads all 109 cols) | — | **0.8 s**, 0.5 GB |
| Factor coverage (105 cols, cockpit_ops) | 25.8 s (per-column loop) | ~100 × 76 s ✗ (ops cockpit warm-up never finished) | **2.6 s** (one GROUP BY) |
| Screener input build (`load_raw` + `features_at`) | 54.4 s = 14.7 prices + 14.3 load_raw + 25.4 features_at; 1.30 GB | 58.0 s; load_raw 23.0 s ✗ (BSE via view 10.6 + 11.1 s) | BSE native: results 0.50 s (0.39 today), governance **0.13 s (3.86 today)** → load_raw ≈ today −3.6 s |
| `pit.load_raw()` all 28 frames | 29.9 s, 2.1 GB | — | — |
| Panel storage (pit + v1) | 201 MB | 411 MB (13.1M non-null values; ~25% of cells are filled) | **24.5 MB** |
| Events storage (3 tables) | 2,089 MB | 2,797 MB (jsonb repeats keys) | **374 MB** (JSON payload), 258 MB typed |
| quarterly_income / forecast_history | 4.2 / 2.8 MB | 24.7 / 3.4 MB | 1.0 MB |
| Cockpit, 21 main routes, warm OS cache | e.g. /model/variants 71.7 s, /explorer/RELI 2.8 s, /api/quarterly 0.01 s | 65.4 / 3.1 / 0.61 s. All others within noise. 20/21 byte-identical HTML after normalization | — |

**What the numbers decide:**
1. **History goes to Parquet.** Long SQLite is 2–6× the wide bytes and slower to pivot; Parquet is 8× smaller than today and 2.6× faster to read.
2. **Compatibility views are only a crutch for point reads.** Any hot scan must switch to a native `views.py` read *in the same stage*. The runtime gate catches the rest.
3. **Schema introspection breaks.** The one HTML diff (`/model` shows "not in PIT") was cockpit_ops/api.py:234 testing `sqlite_master WHERE type='table'`, which a view doesn't satisfy. Every stage greps for `sqlite_master`, `table_info` and `read_sql_fast` against migrated names, and `db.dataset_exists()` replaces them.

Reproduce with: `scratchpad/proto_build.py`, `proto_parity.py`, `bench_baseline.py`, `bench_parquet.py`, `bench_cockpit*.sh`. These are session files; the plan keeps the method, not the files.

## 7. Tables per new thing = 0 (worked examples)

| Thing | The whole change | New tables |
|---|---|---|
| **Factor** | `factors.FACTORS["gross_margin_trend"] = {compute: signals.gm_trend.compute, range: (-1, 1), cadence: "quarterly", eligibility: {...}}`; the producer returns `(sid, date, value)` and calls `db.write("features", df.assign(feature="gross_margin_trend"))`; `catalog.sync()` adds the row | 0 |
| **Data source** | `hosts.HOSTS["nsdl"] = {gap: 2, budget: …}` + `tables.TABLES["nsdl_fpi"] = {concept: "series", series: sources.nsdl.SERIES, cadence: "daily"}` + the fetcher module; `db.write("nsdl_fpi", df)` | 0 |
| **Event type** | `tables.TABLES["bse_announcements"]["event_types"]["bse:Credit Rating"] = {available_at: "dissem_dt", payload: ["agency", "rating"]}`; producer rows `(sid, event_time, available_at, source_key, payload)` | 0 |
| **Macro series** | `sources.macro_gov.SERIES["gst_collections"] = {unit: "₹cr", freq: "monthly", release_lag_days: 1, sector_weights: {…}}` (this also replaces the writer-less `macro_sector_map`) | 0 |
| **Fundamental metric** | `sources.screener.LINE_ITEMS["contingent_liabilities"] = {family: "balance", unit: "₹cr", lag_days: 75}` | 0 |
| **Market** | `entities(kind='security', market='US', key=…)` rows; `identifiers` namespace `us_ticker`; `config.TIERS` gains a `market` key; bars/events/facts unchanged; the index entity's bars give its sessions | 0 |
| **Model** | `config.MODELS["v2_ema"] = {weights: …}`: each run records `model_id`; two models on one day are two runs, compared with `views.picks(run=…)` | 0 |
| **Tier** | `config.TIERS["NANO"] = {rank_rule: …, pickable: False}`; segment writes `classifications(scheme='tier', value='NANO')` (no CHECK constraint to edit) | 0 |
| **Fund metric** | `mf/metrics.py: METRICS["sortino_3y"] = {window: "3y", fn: …}`; rows in `mf.fund_metrics` | 0 |

## 8. Stress tests (Phase C)

**Analyst PTs are episodic; `forecast_history.price` is contaminated (ADR 0045).**
- `estimates` versions only on change, so the daily refresh writes nothing new most days, and the CLAUDE.md "never a daily snapshot row" rule holds structurally.
- The monthly snapshot is `views.pt_monthly(D)`. Its as-of comes from `fetched_at`, which fixes the backdated 05-01 snapshot.
- `est.price` is not in the catalog, so `db.write` rejects it.
- The Moneycontrol aggregate becomes its own `source`, which ends the hidden second writer.

**HALC numbers in narrative.**
- Doc types declare `spec.narrative_no_numbers: true`.
- `db.write` runs `output/dossier.py`'s validator. A failing document is stored with `status='invalid'` plus a `row_issues` entry, and `views.dossier()` returns only `valid`. Numbers live only in `fields`.

**Restated fundamentals.**
- A restatement is a new version.
- `facts_asof(D)` returns what was on file at D once capture starts. Before capture it falls back to the latest version, today's behaviour, and nothing is invented.

**Corporate adjustments and split-adjusted prices.**
- Bars are stored raw. Adjustments are derived events (`price_adjustment`, slice-replaced by the producer).
- `views.bars(adjusted=True, as_of=D)` applies only adjustments with ex_date ≤ D, the same semantics as `pit.apply_pit_adjustments`.

**Financials eligibility (ADR 0048).**
- Eligibility stays in `eligibility/registry.py`, mirrored into `catalog.spec`.
- Ineligible (entity, feature) pairs have no rows, and `eligible_coverage` renormalizes as today. There is no schema impact.

**MICRO exclusion and re-tiering with history.**
- `segment.py` and `classify_micro_tier.py` write SCD2 `classifications(scheme='tier')` rows with a `run_id`.
- `pickable` stays in `config.TIERS`, and `tier_asof(D)` gives the backtest real historical tiers from the capture date on. Before that date it uses today's tier, which is the current behaviour, now flagged.
- Stage 1 starts capturing classifications immediately, as a mirror.

**Quarantine and row issues.**
- The 11 mirrors plus failing trust verdicts plus `screener_pull_errors` all become `row_issues`.
- Release = `resolved_at` + `db.write` of the corrected row (no release path exists today).
- Verdict/mirror drift (320 vs 0) becomes impossible, because there is one record.

**LLM outputs as documents.**
- Each carries its run, model and content hash; spend goes to `llm_usage.run_id`.
- A rerun with identical output dedups on hash, and a changed output supersedes.

**`reconstruct_pit.py`'s rule of writing only the columns it produced.**
- This becomes structural: a producer only has rows for its own features.
- Slice-replace keeps the good half of the rule (untouched features are safe) and closes the hole: a stock that now evaluates to NaN loses its stale value.

**A second market.** See §7. Tiers, calendars and identifiers are all rows. `market` is part of the `entities` key, so symbols can't collide.

**10× factors and 5× universe.**
- Measured storage is ~1.9 B per value in Parquet (24.5 MB / 13.1M values), so 50× the panel is about 1.2 GB.
- Pivot time scales with the features read: a research read takes 0.8 s per 10 features.
- Daily live features are not stored per stock per day: they are computed by `features_at`. Only `pick_contributions` is stored: ~18K rows/day today (1,770 ranked × 10 wired factors), ~0.9M/day at 5× universe × 10× wired factors.
- At that scale `pick_contributions` keeps a 3-month hot window and compacts to Parquet (~0.4 GB/yr at the measured 1.9 B/value).
- SQLite hot stays under ~2 GB.

**Two runs per day.**
- Both keep their picks (`run_id` is in the PK). `runs.official` marks the emailed run, and `views.picks` defaults to it.
- The second run replaces feature slices. The first run's exact inputs survive in `pick_contributions`.

**Backup, restore, and the DuckDB replica.**
- Backup = `VACUUM INTO` of `alpha_signal.db` and `mf.db`, plus an rclone copy of `data/history/`. The Parquet files are immutable, so the copy is incremental.
- The quarterly restore drill restores all three into scratch and runs `views.panel()` parity.
- The replica is retired (§5).

**MF holdings feeding a stock signal.**
- A stock-side producer calls `views.fund_holdings_asof(D)`. That ATTACHes `mf.db` read-only and filters on `available_at`, the disclosure date, which fixes today's scrape-date bug.
- It writes `feature_values` in the main DB.
- A check verifies `fund_holdings.sid ∈ entities`.

## 9. Migration stages

Every stage runs side by side and is reversible until its separate drop commit.

**The standard gate** (all items, plus the stage-specific ones):
- (a) Tests pass, `pipeline.py --dry-run` works, and every module imports.
- (b) **Parity while writing both:** a `check_results` parity check runs in production and matches for N consecutive trading days. N = 5 for stages feeding ranking (4, 6, 7, 8) and 3 otherwise.
- (c) Readers switch through compatibility views one at a time, and hot scans go native.
- (d) `reconstruct_one_date` on 3 monthly dates gives identical values.
- (e) Today's screener ranks per tier are identical.
- (f) All cockpit routes return 200 on 3100/3101, and the normalized HTML is identical.
- (g) Email HTML is byte-identical, and health output is identical.
- (h) Backup and restore of the new tables are tested.
- (i) Critical-path time to the email is ≤ today.
- (j) A grep for `sqlite_master` / `table_info` / `read_sql_fast` against migrated names comes back clean.
- (k) Once plan 0016 phase 1 exists: its offline MCP tool snapshot tests pass on the stage's DB copy (via `ALPHA_DB`).

**Standard rollback:** set `config.DATA_MODEL[<stage>] = "old"`. Readers go back to the old tables, which are still being written. The new tables stay, harmless. Old tables are dropped only in a later, separate commit, ≥14 days after the switch, after a verified backup.

| Stage | Scope | Specific gate | Rollback | Effort | Retires |
|---|---|---|---|---|---|
| **0. Prereqs + quick wins** | **Already shipped by other sessions on 2026-09-27:** F1 (421b972: monthly Tickertape scrapes off the email path), F4 (900904b: versioned `ops/hooks/pre-push` with pipefail, pytest in `.devlib`), plus F3, F10, F12, F13, F15. **Remaining:** (1) move `tools/regression_fixtures.py` onto a temp DB. The new hook still runs it against the live DB ([ops/hooks/pre-push:38](../../ops/hooks/pre-push)), deleting all of RELI's `trust_verdicts`/`external_anchors` on every push. (2) `ALPHA_DB` env override (F8), needed by every gate in this plan and by plan 0016's phase-1 gate. (3) `busy_timeout` 5 s → 30 s. (4) The 11 quarantine mirrors → `row_issues` (79 rows). (5) Drop the 3 `paper_*`, `event_calendar`, `pit_ic_by_tier_v1`, `sector_policy_pit`; `uhs_calibration_log` → view | A fixture run leaves the live DB byte-identical (checksum before/after); an `ALPHA_DB=copy` test run touches 0 live rows | revert commits; drops restorable from the pre-stage backup | 1 session | 21 retired, `row_issues` added (134 → 114): 11 mirrors, 3 paper_*, event_calendar, pit_ic_by_tier_v1, sector_policy_pit, uhs_calibration_log, screener_pull_errors, external_anchors (D4), signal_lineage (D3) |
| *(plan 0016 phases 1–3)* | *Not this plan: the MCP read surface, then `llm_tasks` + `TASK_KINDS`, then the dossier/news-brief kinds* | *plan 0016's own gates* | *plan 0016* | *3–5 sessions* | *`llm_tasks` added (→ 115)* |
| **1. Catalog + entities + `db.write`** | `catalog`, `entities`, `identifiers` and `classifications` created and synced every run. `classifications` starts **capturing tier/sector history now** (additive). `db.write` wraps `insert_df`/`upsert_df` with the same behaviour; the no-raw-SQL test lands with the current allowlist frozen | Every write goes through `db.write` (the allowlist only shrinks); the catalog matches the registries | flag off; the tables are additive | 2 sessions | 0 retired, 4 added (→ 119) |
| **2. Decisions + runs** | `runs` (git sha, config/weights hash, `official`), `step_runs` (from `pipeline_log`), `picks`, `pick_contributions`, `book_weights`, `outcomes`. `daily_picks`/`portfolio_weights`/`pipeline_log` become compatibility views. Backfill the 131 replay dates from `pit_replay_snapshots`. `views.explain` + gated `views.picks` | `explain(run, sid)` reproduces today's score to 1e-9 for every pick on 3 dates; email and health outputs identical | flag off | 2 sessions | 12 retired, 7 added (→ 114): pipeline_log, pit_reconstruction_log, sector_narrative_runs, regulatory_batches, daily_picks, portfolio_weights, pick_outcomes, portfolio_outcomes, pit_replay_snapshots, daily_changes, health_score, trust_verdicts (fails → row_issues, passes → check_results counts) |
| **3. `mf.db` pilot** | 5 tables in `data/mf.db`; MF producers write there; the cockpit MF pages read via ATTACH. First run of the side-by-side pattern end to end, with no ranking dependency (census B) | `/mutual-funds*` HTML identical; NAV row counts equal | point MF readers back | 1–2 sessions | 9 `mf_*` retired (→ 105); the MF mirrors already moved in stage 0 |
| **4. Company facts (versioned)** | Moved ahead of Features: every day without versioning is revision history lost for good. `fundamentals` (statements, Screener line items, bank metrics, shareholding) and `estimates`; `facts_asof`, `pt_monthly`; RAW_VIEWS for qi/bs/cf/sh/fh/acs/fund_screener/banking_metrics | `reconstruct_one_date` identical on 3 dates; `forecast_history.price` rejected | flag off | 2 sessions | 9 retired, 2 added (→ 98) |
| **5. Features + Parquet history** | `feature_values`; 49 feature tables mapped (enums coded); `views.features/panel/coverage`; backtest_pit, promotion_gate, ic_decay, walk_forward and cockpit_ops coverage switched native in this stage; `tools/compact.py`; the DuckDB replica retired | Panel read ≤ 16 s (measured 6.2); IC table from backtest_pit identical; the ops cockpit warm-up ≤ today | flag off; Parquet files are only an extra copy | 3 sessions | 49 feature tables + pit_ic_by_tier_v2 + factor_horizon_gate retired, `feature_values` + `factor_tests` added (→ 49); the `.duckdb` replica retired |
| **6. Events + documents** | `events`, `event_links`, `documents`; the BSE/insider/bulk/news/regulatory/corporate-action producers; the LLM outputs switch at one point per kind, plan 0016's `TASK_KINDS[kind].ingest` → `db.write("documents", …)` (the dossier file becomes a `documents` row); native `views.events` for `bse_results`/`bse_gov` (measured 0.50/0.13 s) | Event counts per type equal; load_raw ≤ today | flag off | 2–3 sessions | 19 retired, 3 added (→ 33); ~1.7 GB of hot SQLite (history → 0.37 GB Parquet) |
| **7. Series + bars** | `series_values` (macro, VIX, FII/DII; `SERIES` declarations replace `macro_sector_map`, which fixes the live-vs-PIT two-map split), `bars_daily` (+ index bars; source in the PK), `derivative_bars` | sector_tilt identical on 3 dates; bars row counts equal | flag off | 2 sessions | 8 retired, 3 added (→ 28): macro_history, fii_dii ×2, vix_history, macro_sector_map, stock_prices, nse_index_history, fno_bhav |
| **8. Reference switch-over** | Readers of `stocks` → `entities` + `tier_asof`; `stocks` becomes a compatibility view; the 52 FKs are re-pointed; MICRO rule on `classifications` | Every route/email/screener identical; FK integrity check | flag off; `stocks` is still written until the drop | 2 sessions | 4 retired (→ **24**): stocks, scrip_master, historical_universe, macro_indicator_meta |

**Final count:**
- Main DB: 134 → 24 tables (+ `sqlite_sequence`), counting plan 0016's `llm_tasks`.
- `mf.db`: 5 tables.
- History: Parquet under `data/history/`.
- Total effort: about **17–20 sessions**. Stages 0–2 alone deliver explainable picks and a gate that can fail, so each stage pays for itself.

## 10. Top risks

1. **Compatibility views hide slow scans.** Measured: the panel took 76 s through the view, BSE 10 s, and the ops warm-up never finished. Mitigation: hot scans go native in the same stage; gate (i) plus the ops-cockpit warm-up time.
2. **Dual writes lengthen the morning run and lock contention** (25 "database is locked" lines in the logs already, counted 2026-09-27). Mitigation: stage 0 raises `busy_timeout` to 30 s; gate (i) enforces the critical path; dual-write only for the ≤N-day parity window per stage.
3. **Schema introspection breaks silently** (measured: `/model` "not in PIT"). Mitigation: gate (j) plus `db.dataset_exists()`.
4. **Two stores (SQLite + Parquet).** A compaction bug could lose a month. Mitigation: copy → verify count and checksum → back up → only then delete hot rows; the restore drill covers Parquet.
5. **Prod runs from a shared working tree (F8).** A half-done migration edit would run in the 03:30 cron. Mitigation: stage 0's `ALPHA_DB`; migrations deploy from a tagged worktree only.
6. **Catalog id loss.** Parquet stores names, and `catalog.sync()` rebuilds by name. Mitigation: the ids are only a SQLite-hot optimization.
7. **Scope creep into behaviour changes.** Examples: the EPS lag fix (census finding) and historical tiers in the backtest. Mitigation: every stage is *parity-only*. Behaviour fixes are separate, evidence-gated changes listed in §11.

## 11. Decisions for Amit

| # | Decision | Recommendation |
|---|---|---|
| D1 | The 10 concepts / 24 + 5 tables (§2, incl. plan 0016's `llm_tasks`) | approve — **approved 2026-10-01** |
| D2 | `ownership` merged into `fundamentals` (family `ownership`) | approve (same write and PIT rule) — **approved 2026-10-01** |
| D3 | `signal_lineage`: retire (only 2 of ~105 factors emit it; UHS gate 6 becomes an input-coverage check) or keep as `documents(type=lineage)` | retire |
| D4 | Retire `external_anchors` + gate 7 (structurally dead); `bars_daily` keeps source in its PK so a real second-source check is possible later | approve — **approved 2026-10-01** |
| D5 | Features: a rerun replaces the (feature, date) slice; decisions append per run | approve — **approved 2026-10-01** |
| D6 | History to Parquet, monthly compaction, 13-month hot window; retire the DuckDB replica | approve — **approved 2026-10-01** |
| D7 | Behaviour fixes found by the census stay OUT of the migration and become separate evidence-gated items: forecast_history EPS filing lag (look-ahead in wired `consensus`), historical tiers in the backtest, insider disclosure date, the multibagger `promoter_trend` alphabetical ranking, the two macro sector maps | approve; add them to the checklist — **approved 2026-10-01** |
| D8 | Order with plan 0016 as in the header; stage 0 now; each later stage approved individually | **approved 2026-09-28** (order); stage-level approvals pending |

## Implementation notes
- **2026-09-28:** sequencing with plan 0016 agreed (header, D8).
  - Stage 0 shrank: F1 and F4 were shipped by other sessions on 2026-09-27 (421b972, 900904b), along with F3/F10/F12/F13/F15.
  - The versioned pre-push hook still runs `tools.regression_fixtures` against the live DB, so item (1) stays.
  - Plan 0016's `llm_tasks` is counted in the Ops concept (24 main tables).
  - Nothing implemented yet.
- **2026-09-30, scope change (Amit):** "implement all tables now, keep the older ones, reconcile for a week, then discard the old tables." This replaces the stage-by-stage producer migration for the *write* side.
  - A shadow sync (`datamodel/sync.py`, run at the end of `run.sh morning`) derives every new table from the old ones, idempotently and incrementally, applying each concept's write rule (versioned facts, SCD2 classifications, slice-replace features, per-run decisions).
  - Producers are unchanged, so ranking risk is nil. History starts accruing from the first sync.
  - `datamodel/reconcile.py` records old-vs-new parity daily in `check_results`.
  - The read-side switch (views/compat views, native hot readers) happens during the week, before any drop.
  - Stages 0–8 remain the plan for moving producers to write the new tables natively.
- **2026-09-30, open design item (from the parked agent-org design, future plan 0019):** a `hypotheses` concept (card in, verdict out; shared inbox for CIO/researchers/sector desk). Proposed fit, no new table: a hypothesis is a `documents` row (catalog doc_type `hypothesis`, `fields` = card + status + verdict, revisions supersede, `run_id` = the agent run); the verdict can be a child document (`parent_doc_id`). Timing: stage 1–2. Amit to decide.
- **2026-09-30, lossless-migration audit (Amit: "the old hard-earned data is migrated, right?").** The first mapping dropped or collapsed some legacy data. All of it is now carried, and `datamodel/reconcile.py` checks it:
  - `historical_universe`: 17,691 survivorship-free rows → `bars_daily` (source `historical_universe`, `attrs` = series/requested_date).
  - `scrip_master`: all 14,822 rows → `identifiers(bse_scrip)`; the 12,111 unmapped rows get `instrument` entities.
  - Every other `stocks` column (`market_cap_cr`, `adtv_6m_cr`, …) → `entities.attrs`.
  - `nlp_scores` is keyed by `doc_date` (32 rows collapsed on `available_date`).
  - `insider_signals` is split by `signal_type` (12 rows collapsed).
  - A panel `in_universe` membership feature is kept (rows whose values are all NULL).
  - Per-row TRUSTED `trust_verdicts` → `check_results` (not counts).
  - `pit_replay_snapshots` → `documents(pit_replay)`, keeping the exact frozen inputs and outputs.
  - Date-like text keeps its time part.
  - Parity uses **raw** row counts, so any key collapse FAILs.
- **Rule for the drop step (end of the reconciliation week):** no legacy table is dropped until:
  1. its parity has been PASS for 7 consecutive days,
  2. its readers are switched (compatibility view or native `views.py`), and
  3. it has been exported whole to `data/history/legacy/<table>.parquet` (checksummed, included in the backup).

  The export also covers what v3 deliberately doesn't model (write-time `computed_at` columns, `requested_date`) and the RETIRED tables (`signal_lineage`, `external_anchors`, `uhs_calibration_log`, `paper_*`, `event_calendar`, `sector_policy_pit`, `pit_ic_by_tier_v1`, `vix_history`), so nothing hard-won becomes unrecoverable. The export and drop run from a separate commit per batch.
- **2026-10-01: Amit approved D1–D8 ("agree with all").**
  - **Deployed:** `datamodel/` was fast-forwarded to master (5fea6a2…13439f9). On a 2026-09-30 snapshot: full sync 20 min (2.8 GB peak), daily incremental 3.9 min, reconcile ~5 min. Every legacy table PASS or RETIRED (113/0/14).
  - **Not done by the agent:** the one-time live backfill and the tier-history seed from the 2026-09-30 backup. Both write to the live DB, and the permission classifier blocked them; Amit runs them, or the next `run.sh morning` does the full sync automatically, since a first run with no prior sync is FULL.
  - **Tier history gap:** the 2026-10-01 03:30 re-tier ran before the tables existed. The pre-change tiers of ranked stocks are recovered from `daily_picks`; MICRO/unranked stocks need the 2026-09-30 backup (kept until ~10-07).
