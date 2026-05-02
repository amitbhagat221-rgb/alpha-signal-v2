# Alpha Signal v1 → v2 Migration Plan

> Slow, methodical, one step at a time. Every step user-validated before moving on.
>
> Created: 2026-04-09 | Owner: Amit Bhagat
> Last updated: 2026-04-09

---

## Table of Contents

1. [Migration Philosophy](#1-migration-philosophy)
2. [Architecture: v1 vs v2](#2-architecture-v1-vs-v2)
3. [Notebook vs Pure .py Decision Map](#3-notebook-vs-pure-py-decision-map)
4. [Phase-by-Phase Migration Plan](#4-phase-by-phase-migration-plan)
5. [Data Source Audit Checklist](#5-data-source-audit-checklist)
6. [Notebook → .py Conversion Workflow](#6-notebook-to-py-conversion-workflow)
7. [Parallel Run and Cutover Plan](#7-parallel-run-and-cutover-plan)
8. [Risk Register](#8-risk-register)
9. [Appendix: v1 → v2 File Map](#appendix-v1-to-v2-file-map)

---

## 1. Migration Philosophy

### Core Principles

1. **Audit before migrate.** Never migrate bad data. Every v1 data source gets inspected in a notebook before it touches v2's database.
2. **One layer at a time.** Build order follows the dependency graph: database → data sources → signals → scoring → output. Each layer tested before the next starts.
3. **User understands every piece.** Data-heavy steps go through Jupyter notebooks so the user can see the data, validate it, and build intuition before committing to production code.
4. **v1 stays live until v2 is proven.** 2-3 day parallel run before switching.
5. **Simplicity over abstraction.** Plain functions, Python config, no frameworks. You can always add complexity later; you can almost never remove it.
6. **No magic numbers.** Every threshold, weight, and delay lives in `config.py` with a comment explaining why.

### What "Done" Looks Like

- `~/alpha-signal-v2/data/alpha_signal.db` contains all 25 tables, populated and validated
- `pipeline.py` runs the full daily pipeline end-to-end
- v1's `run_pipeline.sh` cron is disabled
- v1's `scripts/` moved to `scripts/legacy/` for reference
- The user can explain what every table, source, and signal does

---

## 2. Architecture: v1 vs v2

### What Changed and Why

| Aspect | v1 (fragile) | v2 (simple + robust) | Why |
|--------|-------------|---------------------|-----|
| Data storage | ~80 CSV files, 400MB | 1 SQLite database, ~50-100MB | Queryable, schema-enforced, no duplication |
| Orchestration | `run_pipeline.sh` (bash, silent failures) | `pipeline.py` (~100 lines Python) | Logs to SQLite, retries, email alerts, you understand every line |
| Config | Weights hardcoded in 6+ scripts, values differ between screener & integrator | `config.py` (single file, all weights/thresholds) | One source of truth, autocomplete, importable |
| Code pattern | 38 numbered scripts, copy-pasted loaders | Plain functions in `sources/`, `signals/`, `scoring/` | No base classes, no plugin system, no YAML |
| Visibility | Check log file manually, hope for the best | `pipeline_log` table — `SELECT * FROM pipeline_log WHERE run_date = date('now')` | Your database IS your dashboard |
| Monitoring | None | Email on failure, pipeline_log table | Good enough for solo use |

### v2 Directory Structure

```
~/alpha-signal-v2/
├── config.py              # ALL config — weights, thresholds, paths, delays
├── db.py                  # Database helpers (get_db, insert_df, upsert_df, read_table)
├── schema.sql             # 25 tables, 5 groups
├── validate.py            # Shared validation functions
├── pipeline.py            # THE orchestrator (~100 lines)
│
├── sources/               # Each file = one data source, one fetch function
│   ├── tickertape.py      # fetch_income, fetch_bs, fetch_cf, fetch_consensus
│   ├── nse.py             # fetch_bhavcopy, fetch_bulk_deals, fetch_earnings_cal
│   ├── rss.py             # fetch_news
│   └── vix.py             # fetch_vix
│
├── signals/               # Each file = one signal, one compute function
│   ├── piotroski.py
│   ├── accruals.py
│   ├── consensus.py
│   ├── promoter.py
│   ├── forensic.py
│   ├── smart_money.py
│   ├── sentiment.py
│   └── macro.py
│
├── scoring/
│   ├── screener.py        # Within-tier percentile ranking + weighted combine
│   ├── quality_gate.py    # Small-cap filter
│   └── regime.py          # VIX regime + allocation
│
├── output/
│   ├── dossier.py         # AI stock reports
│   └── email.py           # Daily email
│
├── data/
│   └── alpha_signal.db    # THE database. One file. Back it up daily.
│
├── notebooks/             # Exploration + validation (Jupytext paired .py files)
├── tests/
└── requirements.txt       # Pinned dependencies
```

### Why No Prefect

Prefect is designed for teams running hundreds of flows across multiple machines. We're running ~15 steps once a day on one VM. A ~100-line `pipeline.py` gives us:
- Sequential step execution with dependency awareness
- Retry on failure (configurable per step)
- Full logging to `pipeline_log` SQLite table
- Email alert on crash
- Zero framework dependency, zero version churn risk, zero RAM overhead

If we ever need Prefect's features, we can add it later. The functions in `sources/` and `signals/` don't change — only the orchestrator does.

### Why No Base Classes

Our sources are too heterogeneous for a common interface. Tickertape needs SID-based API calls. NSE bhavcopy needs date-based CSV downloads. yfinance is a library call. Forcing them into `class TickertapeFundamentals(BaseSource)` adds ceremony without value for 12 sources.

Instead: plain functions with clear signatures. If you need shared behavior (rate limiting, retry), put it in a utility function.

### Why Python Config, Not YAML

YAML adds indirection and a parsing dependency. Python config is directly importable, has autocomplete, supports computed values, and needs zero extra libraries:

```python
# config.py
SIGNAL_WEIGHTS = {
    "LARGE": {"consensus": 0.40, "earnings_yield": 0.20, ...},
    "MID":   {"cf_accruals": 0.30, "book_to_price": 0.20, ...},
    "SMALL": {"promoter_qoq": 0.25, "earnings_yield": 0.20, ...},
}
```

---

## 3. Notebook vs Pure .py Decision Map

### The Rule

**Use a notebook when you need to SEE the data to understand or validate it.** Use pure .py for infrastructure, orchestration, and code where the logic matters more than the data shape.

### Notebooks (data exploration, audit, validation)

| Task | Why Notebook | Resulting .py |
|------|-------------|---------------|
| Audit universe.csv — inspect tiers, sectors, gaps | Need to see distribution, spot missing sectors | `sources/tickertape.py` (universe portion) |
| Audit quarterly_income.csv — column mapping, nulls | 21,571 rows with varying schemas | `sources/tickertape.py` |
| Audit annual_balancesheet.csv — field coverage | Need to see which fields are populated | `sources/tickertape.py` |
| Audit annual_cashflow.csv — FCF validation | Verify operating_cash_flow - capex = free_cash_flow | `sources/tickertape.py` |
| Audit shareholding.csv — promoter trends | Need to see QoQ patterns | `sources/tickertape.py` |
| Audit consensus.csv — coverage gaps | Only ~1,000 of 2,500 stocks have analyst data | `sources/tickertape.py` |
| Audit insider_archive.csv — dedup analysis | 111,420 rows with known duplicates | `sources/nse.py` |
| Audit price_data/ vs bhavcopy comparison | Compare yfinance vs NSE close prices | `sources/nse.py` |
| Validate Piotroski — cross-check v1 vs v2 | See score distributions, flag discrepancies | `signals/piotroski.py` |
| Validate accruals — CF vs BS accrual ratios | Need to see ratio distributions | `signals/accruals.py` |
| Validate forensic — Beneish/Altman coverage | v1 only covers 399 stocks, v2 should cover more | `signals/forensic.py` |
| Validate scoring — v1 vs v2 top-15 comparison | Need to see rank correlation | `scoring/screener.py` |
| Parallel run validation | Daily comparison notebook | One-off analysis |

### Pure .py from the Start

| File | Why No Notebook |
|------|----------------|
| `db.py` | Already built. Connection management, SQL helpers. |
| `schema.sql` | Already built. DDL statements. |
| `config.py` | Constants and weights. No data to explore. |
| `validate.py` | Validation functions. Pure logic. |
| `pipeline.py` | Orchestration. Wiring, not data. |
| `output/email.py` | SMTP infrastructure. |
| `output/dossier.py` | Claude API call. Template + API. |
| `scoring/regime.py` | VIX computation. Simple math. |
| `tests/*` | Test infrastructure. |

### The Workflow in Practice

```
Session starts
    │
    ├─ Is this a data-heavy step?
    │   │
    │   YES → Create notebook in notebooks/
    │   │     Write cells one at a time
    │   │     User runs each cell, validates output
    │   │     Once validated → jupytext convert to .py
    │   │     Then make .py production-grade (logging, error handling, CLI)
    │   │     → File lands in sources/ or signals/ or scoring/
    │   │
    │   NO → Write .py directly
    │         (infrastructure, config, orchestration, tests)
    │
    └─ Test and verify before moving on
```

---

## 4. Phase-by-Phase Migration Plan

### Phase 0: Foundation (DONE)

**Status: Complete**

What was built:
- `schema.sql` — 25 tables across 5 groups (fixed: dropped delivery_data, fixed analyst_consensus PK, added indexes on all signal tables, added CHECK constraints, added NOT NULL where needed)
- `db.py` — `get_db()`, `read_table()`, `insert_df()` (append-only), `upsert_df()` (update on conflict), `init_db()`

What was validated:
- `python db.py` creates the database and all 25 tables
- `table_counts()` shows all tables exist (empty)

---

### Phase 1: Data Source Audit (Notebooks)

**Goal:** Understand every v1 data source before writing any migration code.

#### Session 1.1: Universe Audit

**Notebook:** `notebooks/01_audit_universe.ipynb`

**What to examine:**
- `~/alpha-signal/data/harvester/universe.csv` (2,500 rows)
- `~/alpha-signal/data/nifty500_list.csv` (501 rows)
- `~/alpha-signal/data/harvester/slug_map.csv` (2,501 rows)
- `~/alpha-signal/data/stock_metadata.csv`

**Key questions:**
1. How many stocks per cap_tier? (expect: ~100 LARGE, ~150 MID, ~2250 SMALL)
2. How many sectors? Which sectors have <5 stocks?
3. Are there duplicate sids? Any missing sids?
4. Column mapping: universe.csv columns → `stocks` table columns
5. Decision: carry over yfinance metadata (PE, PB, ROE) or leave for Tickertape?

**Acceptance criteria:**
- [ ] User can state stocks per tier
- [ ] Column mapping documented
- [ ] Source decision for metadata columns

**Resulting .py:** `sources/tickertape.py` (universe loader portion)

---

#### Session 1.2: Fundamental Data Audit

**Notebook:** `notebooks/02_audit_fundamentals.ipynb`

**What to examine:**
- `quarterly_income.csv` (21,571 rows)
- `annual_balancesheet.csv` (19,196 rows)
- `annual_cashflow.csv` (19,155 rows)
- `shareholding.csv` (14,135 rows)

**Key questions:**
1. Column mapping: CSV columns → schema.sql columns (there are mismatches)
2. How many stocks have complete data?
3. NULL rates for critical fields (revenue, net_income, total_assets)
4. What does the `period` column format look like?
5. Does `operating_cash_flow - capex` always equal `free_cash_flow`?
6. Are there sids in these CSVs NOT in universe.csv?

**Acceptance criteria:**
- [ ] Column mapping documented for all 4 tables
- [ ] Data quality report: % null per critical field
- [ ] Schema.sql adjustments identified (if CSV has useful columns schema lacks)

**Resulting .py:** `sources/tickertape.py` (fundamentals portion)

---

#### Session 1.3: Price Data Audit

**Notebook:** `notebooks/03_audit_prices.ipynb`

**What to examine:**
- `~/alpha-signal/data/price_data/*.csv` (1,989 files) — yfinance OHLCV
- `~/alpha-signal/data/smart_money/delivery_30d.csv` — bhavcopy delivery data
- Live NSE bhavcopy fetch for today (compare against yfinance)

**Key questions:**
1. Pick 10 large caps: yfinance close vs bhavcopy close for overlapping dates. Discrepancy?
2. What does the bhavcopy CSV look like? Column names, data types?
3. How many trading days missing in last 3 years?
4. Bhavcopy delivery % distribution — median, NULL rate?

**Acceptance criteria:**
- [ ] User understands price discrepancy between yfinance and bhavcopy
- [ ] Bhavcopy column mapping documented
- [ ] Decision confirmed: bhavcopy primary, yfinance for VIX only
- [ ] Backfill strategy documented

**Resulting .py:** `sources/nse.py` (bhavcopy portion)

---

#### Session 1.4: Analyst Data Audit

**Notebook:** `notebooks/04_audit_analyst.ipynb`

**What to examine:**
- `consensus.csv` (2,439 rows)
- `forecast_history.csv` (29,014 rows)

**Key questions:**
1. How many stocks have analyst data? By tier?
2. Distribution of `total_analysts`?
3. Column mapping to schema
4. How is forecast_history time series structured?

**Acceptance criteria:**
- [ ] Coverage report by tier
- [ ] Column mapping documented
- [ ] Decision: migrate historical consensus or only latest?

**Resulting .py:** `sources/tickertape.py` (analyst portion)

---

#### Session 1.5: News, Insider, Smart Money, Macro Audit

**Notebook:** `notebooks/05_audit_remaining.ipynb`

**What to examine:**
- `news_archive.csv` (2,972 rows)
- `insider_archive.csv` (111,420 rows)
- `smart_money_score.csv` (2,517 rows)
- `bulk_30d.csv` (125 rows), `delivery_30d.csv` (2,470 rows)
- `earnings_calendar.csv` (130 rows)
- `macro_pulse.csv` (22 rows), `macro_sector_signals.csv` (27 rows)
- `india_vix.csv` (736 rows), `regime_state.json`

**Key questions:**
1. Insider: quantify duplicates, define dedup key
2. News: entity matching coverage (501 vs 2,500 stocks)
3. VIX column mapping
4. Regime JSON → regime_state table mapping

**Acceptance criteria:**
- [ ] Insider dedup strategy documented
- [ ] All column mappings documented
- [ ] Coverage gaps quantified

**Resulting .py:** `sources/nse.py`, `sources/rss.py`, `sources/vix.py`

---

#### Session 1.6: Computed Signals Audit

**Notebook:** `notebooks/06_audit_signals.ipynb`

**What to examine:**
- `piotroski.csv` (1,978 rows), `accruals.csv` (2,500 rows)
- `consensus.csv` (2,438 rows), `promoter.csv` (2,438 rows)
- `forensic_scores.csv` (399 rows)
- `smart_money_score.csv` (2,517 rows)
- `quality_gate.csv` (2,250 rows)

**Key questions:**
1. Piotroski: only 1,978 rows — why not 2,500?
2. Forensic: only 399 rows — v2 with Tickertape data should cover more
3. For ALL signals: single snapshot or historical?

**Critical finding:** v1 signals are point-in-time snapshots. v2 has `snapshot_date` in every signal table for historical tracking. We do NOT migrate v1 signal CSVs — we recompute in v2.

**Acceptance criteria:**
- [ ] Coverage gaps quantified per signal
- [ ] Decision confirmed: recompute signals, don't migrate
- [ ] User has read core logic of each v1 signal script

---

### Phase 2: Core Infrastructure

**Goal:** Build `config.py`, `validate.py`, `pipeline.py`. All pure .py, no notebooks.

#### Session 2.1: Config + Validation

**Files to create:**
- `config.py` — all weights, thresholds, paths, delays, API settings
- `validate.py` — shared validation functions (row count checks, null checks, range checks)
- `requirements.txt` — pinned dependencies

**Acceptance criteria:**
- [ ] `from config import SIGNAL_WEIGHTS, API_DELAY, DB_PATH` works
- [ ] `validate.validate_prices(df)` catches bad data
- [ ] `pip install -r requirements.txt` installs everything needed

---

#### Session 2.2: Pipeline Orchestrator

**File to create:** `pipeline.py`

**What it does:**
- Defines STEPS as a list of (name, module, function) tuples
- Runs each step in order
- Logs start/end/duration/rows to `pipeline_log` table
- Retries failed steps (configurable, default 1 retry)
- Emails on critical failure
- Supports `--step fetch_prices` to run a single step
- Supports `--dry-run` to show what would run

**Acceptance criteria:**
- [ ] `python pipeline.py` runs end-to-end
- [ ] `python pipeline.py --step fetch_vix` runs one step
- [ ] `SELECT * FROM pipeline_log` shows step history
- [ ] Failed step triggers email alert

---

### Phase 3: Data Migration — Universe and Prices

#### Session 3.1: Universe Migration

**Type:** Notebook → .py

**Notebook:** `notebooks/07_migrate_universe.ipynb`

**Steps:**
1. Load universe.csv, map columns to `stocks` table
2. Merge nifty500_list.csv → set `in_nifty500 = 1`
3. Merge slug_map.csv → populate `slug`
4. Insert into `stocks` using `upsert_df()`
5. Validate: tier distribution, required fields non-null

**Acceptance criteria:**
- [ ] `stocks` table: 2,500 rows, ~100 LARGE / ~150 MID / ~2250 SMALL
- [ ] All sids unique, no nulls in sid/ticker/name

**Resulting .py:** universe loading function in `sources/tickertape.py`

---

#### Session 3.2: Bhavcopy Source + Backfill

**Type:** Notebook → .py

**Notebook:** `notebooks/08_bhavcopy_exploration.ipynb`

**Steps:**
1. Fetch today's bhavcopy from NSE archives
2. Inspect columns, filter SERIES = 'EQ'
3. Map SYMBOL to sid via `stocks` table
4. Compare bhavcopy close vs yfinance for 10 large caps
5. Insert into `stock_prices`, verify

**Backfill plan:**
- 750 trading days (3 years), 2s delay between requests
- Resume: check `MAX(date)` in stock_prices, start from next day
- Expected: ~2M rows when complete, ~25 min at 2s/request

**Acceptance criteria:**
- [ ] Today's bhavcopy: ~1,800-2,200 rows
- [ ] Close prices match yfinance within 0.5%
- [ ] `delivery_pct` populated

**Resulting .py:** `sources/nse.py` (bhavcopy functions)

---

#### Session 3.3: VIX + Regime Migration

**Type:** Notebook (brief) → .py

**Notebook:** `notebooks/09_migrate_vix_regime.ipynb`

**Acceptance criteria:**
- [ ] `vix_history`: 736 rows
- [ ] `regime_state`: 1 row with current regime

**Resulting .py:** `sources/vix.py` + `scoring/regime.py`

---

### Phase 4: Data Migration — Raw Data Tables

#### Session 4.1: Fundamentals Migration

**Type:** Notebook → .py

**Notebook:** `notebooks/10_migrate_fundamentals.ipynb`

**Tables:** quarterly_income (~21,571), annual_balance_sheet (~19,196), annual_cash_flow (~19,155), shareholding (~14,135)

**Acceptance criteria:**
- [ ] Row counts within 1% of v1 (some may fail FK check)
- [ ] No orphaned sids
- [ ] Critical fields non-null

**Resulting .py:** `sources/tickertape.py` (fundamentals functions)

---

#### Session 4.2: Analyst Data Migration

**Type:** Notebook → .py

**Notebook:** `notebooks/11_migrate_analyst.ipynb`

**Tables:** analyst_consensus (~2,439), forecast_history (~29,014)

**Acceptance criteria:**
- [ ] Row counts match v1
- [ ] All sids have matching `stocks` row
- [ ] Coverage report by tier

**Resulting .py:** `sources/tickertape.py` (analyst functions)

---

#### Session 4.3: News Migration

**Type:** Notebook → .py

**Notebook:** `notebooks/12_migrate_news.ipynb`

**Tables:** news_articles, news_article_stocks

**Key decision:** Expand entity matching from 501 to 2,500 stocks.

**Resulting .py:** `sources/rss.py`

---

#### Session 4.4: Insider Trades Migration

**Type:** Notebook → .py

**Notebook:** `notebooks/13_migrate_insider.ipynb`

**Key work:** Dedup 111,420 rows using UNIQUE constraint.

**Resulting .py:** `sources/nse.py` (insider functions)

---

#### Session 4.5: Remaining Raw Data

**Type:** Notebook → .py

**Notebook:** `notebooks/14_migrate_remaining.ipynb`

**Tables:** bulk_deals, earnings_calendar, macro_indicators

**Note:** No separate `delivery_data` table — delivery data lives in `stock_prices` (from bhavcopy).

**Resulting .py:** `sources/nse.py` (bulk deals, events), `sources/vix.py` (macro)

---

### Phase 5: Computed Signals

**Critical decision:** We do NOT migrate v1 signal CSVs. We recompute all signals from raw data. This validates both the data migration AND the signal logic.

#### Session 5.1: Sentiment Signal

**Type:** Pure .py

**v1:** `07_sentiment_scorer.py` → **v2:** `signals/sentiment.py`

---

#### Session 5.2: Insider Signal

**Type:** Pure .py

**v1:** `09_insider_tracker.py` + `04_ai_classify_insider.py` → **v2:** `signals/insider_signal.py`

---

#### Session 5.3: Piotroski F-Score

**Type:** Notebook (formula validation) → .py

**Notebook:** `notebooks/15_validate_piotroski.ipynb`

**v1:** `27_piotroski.py` → **v2:** `signals/piotroski.py`

Compare v2 F-Scores against v1 for overlapping 1,978 stocks. Expect 95% within 1 point.

---

#### Session 5.4: Accruals Quality

**Type:** Notebook → .py

**v1:** `28_accruals.py` → **v2:** `signals/accruals.py`

---

#### Session 5.5: Consensus Signal

**Type:** Notebook → .py

**v1:** `29_consensus_signal.py` → **v2:** `signals/consensus.py`

---

#### Session 5.6: Promoter Signal

**Type:** Notebook → .py

**v1:** `30_promoter_signal.py` → **v2:** `signals/promoter.py`

---

#### Session 5.7: Forensic Guard

**Type:** Notebook (critical) → .py

**Notebook:** `notebooks/16_validate_forensic.ipynb`

**v1:** `17_forensic_guard.py` → **v2:** `signals/forensic.py`

Critical: v1 covers only 399 stocks (yfinance limitation). v2 with Tickertape fundamentals should cover many more.

---

#### Session 5.8: Smart Money

**Type:** Notebook → .py

**v1:** `16_smart_money.py` → **v2:** `signals/smart_money.py`

Reads from `bulk_deals` and `stock_prices.delivery_pct` (no separate delivery_data table).

---

#### Session 5.9: Macro Sector Signal

**Type:** Pure .py

**v1:** `14_macro_pulse.py` → **v2:** `signals/macro.py`

---

### Phase 6: Scoring Engine

#### Session 6.1: Screener

**Type:** Notebook (scoring validation) → .py

**Notebook:** `notebooks/17_validate_scoring.ipynb`

**v1:** `03_screener.py` + `08_integrate_sentiment.py` → **v2:** `scoring/screener.py` + `scoring/quality_gate.py`

**What the notebook validates:**
1. Load all signals from SQLite
2. Apply tier-specific weights from `config.py`
3. Rank within tier
4. Apply quality gate to small caps
5. Compare top 15 to v1's picks
6. Show rank correlation

**Acceptance criteria:**
- [ ] Top 15 have >60% overlap with v1
- [ ] Rankings are within-tier only
- [ ] Quality gate excludes ~15% of small caps
- [ ] Signal weights come from `config.SIGNAL_WEIGHTS` (single source of truth)

---

#### Session 6.2: Regime Module

**Type:** Pure .py

**v1:** `33_regime_module.py` → **v2:** `scoring/regime.py`

---

### Phase 7: Output Layer

All pure .py — no notebooks needed.

#### Session 7.1: Snapshots

**v2:** `output/snapshot.py` → writes to `daily_picks` and `daily_snapshots`

#### Session 7.2: AI Dossier

**v2:** `output/dossier.py` → Claude API

#### Session 7.3: Email

**v2:** `output/email.py` → Gmail SMTP

---

### Phase 8: Tests

All pure .py.

**Files:**
- `tests/test_smoke.py` — DB exists, tables populated, critical tables non-empty
- `tests/test_signals.py` — each signal produces values in expected ranges
- `tests/test_scoring.py` — weights sum to 1.0, ranks are within-tier

**Acceptance criteria:**
- [ ] `pytest tests/ -v` all green
- [ ] Tests run in < 30 seconds

---

### Phase 9: Parallel Run and Cutover

See [Section 7](#7-parallel-run-and-cutover-plan) for detailed plan.

---

## 5. Data Source Audit Checklist

### Universe and Reference (4 tables)

| Table | v1 Source | v1 File | Rows | Audit | Migrate | Validate |
|-------|-----------|---------|------|-------|---------|----------|
| `stocks` | universe.csv + nifty500 + slug_map + metadata | `data/harvester/universe.csv` | 2,500 | [ ] 1.1 | [ ] 3.1 | [ ] |
| `stock_prices` | yfinance → **NSE bhavcopy** | `data/price_data/*.csv` | ~500K | [ ] 1.3 | [ ] 3.2 | [ ] |
| `vix_history` | yfinance ^INDIAVIX | `data/reference/india_vix.csv` | 736 | [ ] 1.5 | [ ] 3.3 | [ ] |
| `regime_state` | VIX computation | `data/reference/regime_state.json` | 1 | [ ] 1.5 | [ ] 3.3 | [ ] |

### Raw Data (11 tables)

| Table | v1 Source | Rows | Audit | Migrate | Validate |
|-------|-----------|------|-------|---------|----------|
| `quarterly_income` | Tickertape SID API | 21,571 | [ ] 1.2 | [ ] 4.1 | [ ] |
| `annual_balance_sheet` | Tickertape SID API | 19,196 | [ ] 1.2 | [ ] 4.1 | [ ] |
| `annual_cash_flow` | Tickertape SID API | 19,155 | [ ] 1.2 | [ ] 4.1 | [ ] |
| `shareholding` | Tickertape SID API | 14,135 | [ ] 1.2 | [ ] 4.1 | [ ] |
| `analyst_consensus` | Tickertape __NEXT_DATA__ | 2,439 | [ ] 1.4 | [ ] 4.2 | [ ] |
| `forecast_history` | Tickertape __NEXT_DATA__ | 29,014 | [ ] 1.4 | [ ] 4.2 | [ ] |
| `news_articles` + `news_article_stocks` | RSS feeds | 2,972 | [ ] 1.5 | [ ] 4.3 | [ ] |
| `insider_trades` | BSE/NSE/Trendlyne | 111,420 (pre-dedup) | [ ] 1.5 | [ ] 4.4 | [ ] |
| `bulk_deals` | NSE archives | 125 | [ ] 1.5 | [ ] 4.5 | [ ] |
| `earnings_calendar` | NSE events API | 130 | [ ] 1.5 | [ ] 4.5 | [ ] |
| `macro_indicators` | RBI, PIB, GST | 22 | [ ] 1.5 | [ ] 4.5 | [ ] |

### Computed Signals (9 tables) — NOT migrated, recomputed

| Table | v1 Script | v1 Rows | Recompute |
|-------|-----------|---------|-----------|
| `sentiment_scores` | `07_sentiment_scorer.py` | ~500 | 5.1 |
| `insider_signals` | `09_insider_tracker.py` | ~476 | 5.2 |
| `piotroski_scores` | `27_piotroski.py` | 1,978 | 5.3 |
| `accruals_scores` | `28_accruals.py` | 2,500 | 5.4 |
| `consensus_signals` | `29_consensus_signal.py` | 2,438 | 5.5 |
| `promoter_signals` | `30_promoter_signal.py` | 2,438 | 5.6 |
| `forensic_scores` | `17_forensic_guard.py` | 399 | 5.7 |
| `smart_money_scores` | `16_smart_money.py` | 2,517 | 5.8 |
| `macro_sector_signals` | `14_macro_pulse.py` | 27 | 5.9 |

### Output + Pipeline (3 tables) — NEW in v2

| Table | Notes |
|-------|-------|
| `daily_picks` | Recomputed in Phase 6 |
| `daily_snapshots` | Recomputed in Phase 7 |
| `pipeline_log` | Populated by pipeline.py |

---

## 6. Notebook to .py Conversion Workflow

### Setup

```bash
pip install jupytext
```

**Configuration:** Add to `~/alpha-signal-v2/pyproject.toml`:
```toml
[tool.jupytext]
formats = "ipynb,py:percent"
```

This pairs every `.ipynb` with a `.py` file using `# %%` cell markers.

### The Three-Stage Process

#### Stage 1: Exploration Notebook

**Location:** `notebooks/XX_topic.ipynb`

- Cells created one at a time by Claude
- User runs each cell, inspects output
- Heavy use of `display()`, value counts, sample rows
- No error handling, no logging — pure exploration
- Markdown cells explain what each step does

#### Stage 2: Jupytext Convert

Once validated:
```bash
jupytext --to py:percent notebooks/XX_topic.ipynb
```

Creates `notebooks/XX_topic.py` with cells as `# %%` blocks.

**Important:** Always do Kernel → Restart & Run All before converting. Out-of-order execution is the #1 source of "worked in notebook but not in script."

#### Stage 3: Production-Grade .py

Claude takes the validated logic and creates the production module. What gets added:

| Addition | Why |
|----------|-----|
| `logging` calls (replace `print`) | Structured logging |
| `try/except` with specific exceptions | Graceful failure |
| Type hints | Self-documenting |
| CLI arguments (`argparse`) | `--dry-run`, `--limit`, `--since` |
| Input validation | Check DataFrame shape, required columns |
| Idempotency | Safe to re-run (`INSERT OR IGNORE` / `INSERT OR REPLACE`) |
| Rate limiting | 2s delay for Tickertape/NSE |
| Resume capability | Check max(date), start from next day |

**The notebook stays in `notebooks/` as a record. Production code goes to `sources/`, `signals/`, or `scoring/`.**

---

## 7. Parallel Run and Cutover Plan

### Pre-Parallel Checklist

ALL must be true:

- [ ] All 25 tables populated in v2
- [ ] `python pipeline.py` runs without error
- [ ] All signals produce non-empty output
- [ ] Email sends from v2
- [ ] `pytest tests/` all green

### Parallel Run (2-3 trading days)

**Setup:**
- v1 continues on existing cron (9:00 AM IST)
- v2 runs on separate cron (9:30 AM IST — 30 min offset)
- Both write their own outputs independently

**Daily comparison:** `notebooks/99_parallel_validation.ipynb`

| Check | Acceptable | Fail |
|-------|-----------|------|
| Top 15 overlap | 8+ of 15 match | <6 match |
| Rank correlation (Spearman, top 50) | > 0.7 | < 0.5 |
| Price accuracy (bhavcopy vs yfinance) | Within 0.5% | > 1% |
| Signal coverage (non-null counts) | v2 >= v1 | v2 < v1 by >10% |
| Regime match | Same regime | Different regime |
| Pipeline duration | < 15 min | > 30 min |
| Errors | 0 failed steps | Any critical failure |

### Decision Matrix

| Outcome | Action |
|---------|--------|
| All checks pass 2 consecutive days | Proceed to cutover |
| Minor discrepancies explainable by data source improvements | Accept |
| Major discrepancy (different regime, widespread mismatch) | Stop. Debug. Do NOT cut over. |
| v2 fails during parallel run | Fix and restart 2-day counter |

### Cutover Steps

1. Run v2 manually one final time, verify output
2. Disable v1 cron (comment out, don't delete)
3. Enable v2 cron at 9:00 AM IST
4. Move v1 scripts to `~/alpha-signal/scripts/legacy/`
5. Monitor for 1 week
6. After 1 week stable: archive v1 data (keep, never delete)

### Rollback

If v2 fails in first week:
1. Re-enable v1 cron
2. v1 picks up immediately (reads its own CSVs)
3. Fix v2 at leisure, retry parallel run

---

## 8. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | NSE bhavcopy URL changes/blocked | Medium | High | Keep yfinance as dormant fallback. Monitor daily. |
| R2 | Tickertape API changes | Medium | High | Check response structure on every fetch. Alert on schema change. |
| R3 | Column mapping errors during migration | Medium | Medium | Notebook validation catches this. Every migration has sample inspection. |
| R4 | Signal score discrepancy v1 vs v2 | High | Low | Many discrepancies are improvements (better data). Parallel run distinguishes bugs from improvements. |
| R5 | Bhavcopy backfill takes long | Medium | Low | Resume capability. 2s rate limit is conservative. |
| R6 | v1 cron stopped during migration | Low | High | v1 is never touched. All work in `~/alpha-signal-v2/`. |
| R7 | Database corruption | Low | High | Daily backup of `alpha_signal.db` (one file). v1 CSVs are ground truth for raw data. |
| R8 | Oracle Cloud IP blocked by NSE | Already happening | Low | Use `archives.nseindia.com` (not blocked). |
| R9 | SQLite concurrent write contention | Low | Low | WAL mode + busy_timeout=5000. Pipeline is sequential anyway. |
| R10 | Entity matching regression (news) | Medium | Medium | Expanding 501→2,500 stocks increases matches. Validate in notebook. |

---

## Appendix: v1 to v2 File Map

### Scripts → Sources (data fetching)

| v1 Script | v2 Function | Target Table |
|-----------|-------------|-------------|
| `01_fetch_universe.py` | `sources/tickertape.py::load_universe()` | `stocks` |
| `02_fetch_price_data.py` | **RETIRED** (replaced by bhavcopy) | — |
| `06_fetch_news.py` | `sources/rss.py::fetch_news()` | `news_articles` |
| `09_insider_tracker.py` (fetch) | `sources/nse.py::fetch_insider()` | `insider_trades` |
| `14_macro_pulse.py` (fetch) | `sources/vix.py::fetch_macro()` | `macro_indicators` |
| `16_smart_money.py` (fetch) | `sources/nse.py::fetch_bulk_deals()` | `bulk_deals` |
| `18_earnings_calendar.py` | `sources/nse.py::fetch_earnings()` | `earnings_calendar` |
| `22_data_harvester.py` | `sources/tickertape.py::fetch_fundamentals()` | income, bs, cf, shareholding |
| `25_analyst_harvester.py` | `sources/tickertape.py::fetch_consensus()` | `analyst_consensus` |
| `33_regime_module.py` (fetch) | `sources/vix.py::fetch_vix()` | `vix_history` |

### Scripts → Signals (computation)

| v1 Script | v2 Function | Target Table |
|-----------|-------------|-------------|
| `07_sentiment_scorer.py` | `signals/sentiment.py::compute()` | `sentiment_scores` |
| `09_insider_tracker.py` (classify) | `signals/insider_signal.py::compute()` | `insider_signals` |
| `27_piotroski.py` | `signals/piotroski.py::compute()` | `piotroski_scores` |
| `28_accruals.py` | `signals/accruals.py::compute()` | `accruals_scores` |
| `29_consensus_signal.py` | `signals/consensus.py::compute()` | `consensus_signals` |
| `30_promoter_signal.py` | `signals/promoter.py::compute()` | `promoter_signals` |
| `17_forensic_guard.py` | `signals/forensic.py::compute()` | `forensic_scores` |
| `16_smart_money.py` (score) | `signals/smart_money.py::compute()` | `smart_money_scores` |
| `14_macro_pulse.py` (signal) | `signals/macro.py::compute()` | `macro_sector_signals` |

### Scripts → Scoring / Output

| v1 Script | v2 Function | Target Table |
|-----------|-------------|-------------|
| `03_screener.py` + `08_integrate_sentiment.py` | `scoring/screener.py::score()` | `daily_picks` |
| `33_quality_gate.py` | `scoring/quality_gate.py::apply_gate()` | — (filter) |
| `33_regime_module.py` (regime) | `scoring/regime.py::compute_regime()` | `regime_state` |
| `26_snapshot_archiver.py` | `output/snapshot.py::archive()` | `daily_snapshots` |
| `11_ai_dossier.py` | `output/dossier.py::generate()` | — (email) |
| `04_send_email.py` | `output/email.py::send()` | — (email) |

### Retired / Deleted

| v1 Script | Why |
|-----------|-----|
| `02_fetch_price_data.py` (yfinance) | Replaced by NSE bhavcopy |
| `12_google_trends.py` | Dead signal |
| `run_pipeline.sh` | Replaced by `pipeline.py` |
