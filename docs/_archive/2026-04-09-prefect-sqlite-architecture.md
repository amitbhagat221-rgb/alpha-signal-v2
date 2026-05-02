# Alpha Signal — Prefect + SQLite Architecture

> Replacing: CSV files + bash cron orchestration
> With: SQLite database + Prefect orchestrated flows with UI
>
> Created: 2026-04-09 | Owner: Amit Bhagat

---

## Why This Matters

| Before (CSV + cron) | After (SQLite + Prefect) |
|---------------------|--------------------------|
| 80+ CSV files scattered across `data/` | 1 database file, queryable with SQL |
| `run_pipeline.sh` — no error handling, no visibility | Prefect UI — see every run, every task, every failure |
| "Did today's pipeline work?" → check log file manually | Prefect dashboard shows green/red per task at a glance |
| "When was this data last refreshed?" → `ls -la` | `SELECT MAX(updated_at) FROM stocks` |
| "Which stocks have no sentiment?" → write pandas code | `SELECT * FROM stocks WHERE sid NOT IN (SELECT DISTINCT symbol FROM sentiment_scores)` |
| Duplicate rows in insider_archive (11MB) | `UNIQUE` constraints prevent duplication at the DB level |
| Schema drift between scripts | Table schemas are enforced — wrong column = error |

---

## Part 1: SQLite Database Design

### Database file
```
data/alpha_signal.db     (~50-100 MB estimated, replaces ~400 MB of CSVs)
```

### Table Map (26 tables, 5 groups)

```
alpha_signal.db
│
├── UNIVERSE & REFERENCE ──────────────────────────────────
│   ├── stocks                    ← THE single source of truth (replaces universe.csv + nifty500 + metadata)
│   ├── stock_prices              ← daily OHLCV (replaces data/price_data/*.csv)
│   ├── vix_history               ← India VIX daily (replaces india_vix.csv)
│   └── regime_state              ← current VIX regime + allocation weights
│
├── RAW DATA (harvested from external sources) ────────────
│   ├── quarterly_income          ← Tickertape income statements
│   ├── annual_balance_sheet      ← Tickertape balance sheets
│   ├── annual_cash_flow          ← Tickertape cash flow
│   ├── shareholding              ← Tickertape promoter/FII/MF holdings
│   ├── analyst_consensus         ← Tickertape analyst snapshot
│   ├── forecast_history          ← Tickertape PT/EPS time series
│   ├── news_articles             ← RSS feed articles
│   ├── insider_trades            ← raw BSE/NSE/Trendlyne insider trades
│   ├── bulk_deals                ← NSE bulk/block deals
│   ├── delivery_data             ← NSE bhavcopy delivery %
│   ├── earnings_calendar         ← NSE upcoming results dates
│   └── macro_indicators          ← RBI, PIB, GST, IIP data
│
├── COMPUTED SIGNALS ──────────────────────────────────────
│   ├── sentiment_scores          ← VADER per-stock sentiment
│   ├── insider_signals           ← classified insider signals
│   ├── smart_money_scores        ← bulk deal + delivery signals
│   ├── forensic_scores           ← Beneish M-Score + Altman Z
│   ├── piotroski_scores          ← 9-factor F-Score
│   ├── accruals_scores           ← cash vs accrual quality
│   ├── consensus_signals         ← analyst revision momentum
│   ├── promoter_signals          ← promoter buying momentum
│   └── macro_sector_signals      ← sector-level macro impact
│
├── OUTPUT ────────────────────────────────────────────────
│   ├── daily_picks               ← final ranked stocks (replaces enriched_*.csv)
│   └── daily_snapshots           ← point-in-time signal archive
│
└── PIPELINE METADATA ─────────────────────────────────────
    └── pipeline_runs             ← every Prefect run: status, duration, errors
```

---

### Full Schema Definitions

#### UNIVERSE & REFERENCE

```sql
-- THE single source of truth for all stocks
-- Replaces: nifty500_list.csv, stock_metadata.csv, universe.csv, slug_map.csv
CREATE TABLE stocks (
    sid             TEXT PRIMARY KEY,          -- Tickertape SID (e.g. "RELI")
    ticker          TEXT NOT NULL,             -- NSE symbol (e.g. "RELIANCE")
    name            TEXT NOT NULL,             -- Full company name
    sector          TEXT,                      -- GICS sector
    industry        TEXT,                      -- GICS industry
    cap_tier        TEXT CHECK(cap_tier IN ('LARGE','MID','SMALL')),
    market_cap_cr   REAL,                      -- market cap in ₹ crores
    adtv_6m_cr      REAL,                      -- avg daily traded value, 6 months
    in_nifty500     INTEGER DEFAULT 0,         -- 1 if in Nifty 500 index
    slug            TEXT,                      -- Tickertape URL slug
    -- yfinance metadata (refreshed weekly)
    pe_ratio        REAL,
    pb_ratio        REAL,
    roe             REAL,
    debt_to_equity  REAL,
    dividend_yield  REAL,
    revenue_growth  REAL,
    profit_margin   REAL,
    free_cashflow   REAL,
    beta            REAL,
    fifty_two_week_high REAL,
    fifty_two_week_low  REAL,
    avg_volume      REAL,
    -- Tracking
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_stocks_tier ON stocks(cap_tier);
CREATE INDEX idx_stocks_sector ON stocks(sector);
CREATE INDEX idx_stocks_ticker ON stocks(ticker);


-- Daily OHLCV prices (replaces data/price_data/*.csv — ~500 files)
CREATE TABLE stock_prices (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    date            TEXT NOT NULL,              -- YYYY-MM-DD
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL NOT NULL,
    volume          INTEGER,
    PRIMARY KEY (sid, date)
);

CREATE INDEX idx_prices_date ON stock_prices(date);


-- India VIX daily history
CREATE TABLE vix_history (
    date            TEXT PRIMARY KEY,          -- YYYY-MM-DD
    vix             REAL NOT NULL
);


-- Current regime state (single row, updated daily)
CREATE TABLE regime_state (
    id              INTEGER PRIMARY KEY DEFAULT 1 CHECK(id = 1),  -- singleton
    regime          TEXT CHECK(regime IN ('CALM','NORMAL','CAUTION','CRISIS')),
    vix_latest      REAL,
    vix_20d_avg     REAL,
    alloc_large     REAL,                      -- % allocation to large cap
    alloc_mid       REAL,
    alloc_small     REAL,
    updated_at      TEXT DEFAULT (datetime('now'))
);
```

#### RAW DATA

```sql
-- Quarterly income statements (Tickertape)
CREATE TABLE quarterly_income (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    period          TEXT NOT NULL,              -- "SEP 2023", "DEC 2023"
    end_date        TEXT,                       -- YYYY-MM-DD
    reporting       TEXT,                       -- "consolidated" or "standalone"
    revenue         REAL,
    operating_profit REAL,
    net_income      REAL,
    eps             REAL,
    ebitda          REAL,
    tax             REAL,
    interest        REAL,
    depreciation    REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, period, reporting)
);


-- Annual balance sheets
CREATE TABLE annual_balance_sheet (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    period          TEXT NOT NULL,              -- "FY 2024"
    end_date        TEXT,
    total_assets    REAL,
    total_equity    REAL,
    total_debt      REAL,
    current_assets  REAL,
    current_liabilities REAL,
    cash_and_equivalents REAL,
    inventory       REAL,
    receivables     REAL,
    goodwill        REAL,
    retained_earnings REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, period)
);


-- Annual cash flow
CREATE TABLE annual_cash_flow (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    period          TEXT NOT NULL,
    end_date        TEXT,
    operating_cash_flow REAL,
    capex           REAL,
    free_cash_flow  REAL,
    investing_cash_flow REAL,
    financing_cash_flow REAL,
    dividends_paid  REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, period)
);


-- Promoter/FII/MF shareholding (quarterly)
CREATE TABLE shareholding (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    end_date        TEXT NOT NULL,              -- quarter end YYYY-MM-DD
    promoter_pct    REAL,
    fii_pct         REAL,
    mf_pct          REAL,
    dii_pct         REAL,
    public_pct      REAL,
    pledge_pct      REAL,                      -- promoter pledge %
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, end_date)
);


-- Analyst consensus snapshot (Tickertape)
CREATE TABLE analyst_consensus (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    total_analysts  INTEGER,
    buy_pct         REAL,
    price_target    REAL,
    forward_eps     REAL,
    eps_growth_pct  REAL,
    forward_revenue REAL,
    revenue_growth_pct REAL,
    has_analyst_data INTEGER DEFAULT 1,
    fetched_at      TEXT NOT NULL,
    PRIMARY KEY (sid, fetched_at)
);


-- Analyst forecast history (time series)
CREATE TABLE forecast_history (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    metric          TEXT NOT NULL,              -- "price", "eps", "revenue"
    date            TEXT NOT NULL,
    value           REAL,
    change          REAL,
    fetched_at      TEXT NOT NULL,
    PRIMARY KEY (sid, metric, date)
);


-- News articles from RSS feeds
CREATE TABLE news_articles (
    article_id      TEXT PRIMARY KEY,          -- MD5 hash
    title           TEXT NOT NULL,
    summary         TEXT,
    url             TEXT,
    source          TEXT NOT NULL,              -- "moneycontrol", "et_markets" etc.
    published_at    TEXT,
    fetched_at      TEXT DEFAULT (datetime('now'))
);

-- Many-to-many: which stocks are mentioned in which article
CREATE TABLE news_article_stocks (
    article_id      TEXT NOT NULL REFERENCES news_articles(article_id),
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    match_location  TEXT,                      -- "title", "summary", "both"
    PRIMARY KEY (article_id, sid)
);


-- Raw insider trades (deduplicated by natural key)
CREATE TABLE insider_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sid             TEXT REFERENCES stocks(sid),
    symbol          TEXT,                      -- raw symbol from source
    company_name    TEXT,
    person          TEXT,
    person_category TEXT,                      -- PROMOTER, DIRECTOR, KMP, EMPLOYEE, OTHER
    transaction_type TEXT,                     -- BUY, SELL, PLEDGE_CREATE, PLEDGE_RELEASE
    shares          REAL,
    value_lakhs     REAL,
    trade_date      TEXT,
    source          TEXT,                      -- BSE, NSE, TRENDLYNE
    fetched_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(sid, person_category, transaction_type, trade_date, shares)
);

CREATE INDEX idx_insider_sid ON insider_trades(sid);
CREATE INDEX idx_insider_date ON insider_trades(trade_date);


-- NSE bulk/block deals
CREATE TABLE bulk_deals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sid             TEXT REFERENCES stocks(sid),
    symbol          TEXT NOT NULL,
    client_name     TEXT,
    deal_type       TEXT,                      -- "BULK" or "BLOCK"
    buy_sell        TEXT,                      -- "BUY" or "SELL"
    quantity        REAL,
    price           REAL,
    deal_date       TEXT NOT NULL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(symbol, client_name, deal_date, quantity)
);


-- NSE bhavcopy delivery data
CREATE TABLE delivery_data (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    date            TEXT NOT NULL,
    traded_qty      REAL,
    delivered_qty   REAL,
    delivery_pct    REAL,
    PRIMARY KEY (sid, date)
);


-- Earnings calendar
CREATE TABLE earnings_calendar (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,
    symbol          TEXT,
    sid             TEXT REFERENCES stocks(sid),
    company         TEXT,
    purpose         TEXT,
    bm_desc         TEXT,
    added_date      TEXT DEFAULT (date('now')),
    UNIQUE(symbol, date)
);


-- Macro indicators
CREATE TABLE macro_indicators (
    indicator       TEXT NOT NULL,              -- "gst", "iip", "credit_growth" etc.
    signal          TEXT,                       -- "IMPROVING", "STABLE", "DECLINING"
    value           REAL,
    detail          TEXT,
    snapshot_date   TEXT NOT NULL,
    PRIMARY KEY (indicator, snapshot_date)
);
```

#### COMPUTED SIGNALS

```sql
-- Per-stock sentiment scores (daily)
CREATE TABLE sentiment_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,              -- date scored
    sentiment_today REAL,
    articles_today  INTEGER DEFAULT 0,
    sentiment_7d    REAL,
    articles_7d     INTEGER DEFAULT 0,
    sentiment_30d   REAL,
    articles_30d    INTEGER DEFAULT 0,
    sentiment_momentum REAL,                   -- 7d - 30d
    latest_headline TEXT,
    PRIMARY KEY (sid, snapshot_date)
);


-- Insider signals (daily, derived from insider_trades)
CREATE TABLE insider_signals (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    signal_type     TEXT NOT NULL,              -- PROMOTER_BUYING, CLUSTER_BUYING, etc.
    strength        TEXT,                       -- VERY_HIGH, HIGH, MODERATE
    score_impact    REAL NOT NULL,
    description     TEXT,
    PRIMARY KEY (sid, snapshot_date, signal_type)
);


-- Smart money composite (daily)
CREATE TABLE smart_money_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    bulk_score      REAL,
    delivery_score  REAL,
    smart_money_score REAL,
    net_buy_qty     REAL,
    buy_deals       INTEGER,
    sell_deals      INTEGER,
    repeat_buyers   INTEGER,
    PRIMARY KEY (sid, snapshot_date)
);


-- Forensic guard (Beneish + Altman)
CREATE TABLE forensic_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    m_score         REAL,                      -- Beneish M-Score
    m_score_flag    TEXT,                      -- GREEN, GREY, RED
    z_score         REAL,                      -- Altman Z"-Score
    z_score_flag    TEXT,                      -- SAFE, GREY, DISTRESS
    penalty         REAL DEFAULT 0,
    PRIMARY KEY (sid, snapshot_date)
);


-- Piotroski F-Score
CREATE TABLE piotroski_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    f_score         INTEGER CHECK(f_score BETWEEN 0 AND 9),
    -- 9 individual components (1 or 0 each)
    roa_positive    INTEGER,
    cfo_positive    INTEGER,
    roa_improving   INTEGER,
    accruals_quality INTEGER,
    leverage_down   INTEGER,
    liquidity_up    INTEGER,
    no_dilution     INTEGER,
    gross_margin_up INTEGER,
    asset_turnover_up INTEGER,
    PRIMARY KEY (sid, snapshot_date)
);


-- Accruals quality
CREATE TABLE accruals_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    cf_accruals_ratio REAL,                    -- (CFO - Net Income) / Total Assets
    bs_accruals_ratio REAL,                    -- Balance sheet accruals
    earnings_persistence REAL,
    accruals_signal REAL,                      -- combined 0-1 signal
    PRIMARY KEY (sid, snapshot_date)
);


-- Consensus / analyst revision signal
CREATE TABLE consensus_signals (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    pt_upside       REAL,                      -- price target upside %
    pt_revision_1yr REAL,                      -- PT revision over 1 year
    eps_growth      REAL,
    revenue_growth  REAL,
    consensus_signal REAL,                     -- combined 0-1 signal
    PRIMARY KEY (sid, snapshot_date)
);


-- Promoter buying momentum
CREATE TABLE promoter_signals (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    promoter_qoq    REAL,                      -- quarter-over-quarter change
    promoter_trend  TEXT,                      -- BUYING, SELLING, STABLE
    pledge_quality  REAL,
    promoter_signal REAL,                      -- combined 0-1 signal
    PRIMARY KEY (sid, snapshot_date)
);


-- Macro → sector signals
CREATE TABLE macro_sector_signals (
    sector          TEXT NOT NULL,
    snapshot_date   TEXT NOT NULL,
    macro_score     REAL,
    macro_signal    TEXT,                       -- TAILWIND, NEUTRAL, HEADWIND
    macro_detail    TEXT,
    PRIMARY KEY (sector, snapshot_date)
);
```

#### OUTPUT

```sql
-- Final daily picks (replaces enriched_*.csv + latest_picks.csv)
CREATE TABLE daily_picks (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    pick_date       TEXT NOT NULL,
    final_score     REAL,
    rank            INTEGER,
    -- Component scores (for explainability)
    base_score      REAL,
    sentiment_adj   REAL,
    insider_adj     REAL,
    forensic_adj    REAL,
    macro_adj       REAL,
    piotroski_adj   REAL,
    accruals_adj    REAL,
    consensus_adj   REAL,
    promoter_adj    REAL,
    smart_money_adj REAL,
    -- Context
    cap_tier        TEXT,
    sector          TEXT,
    PRIMARY KEY (sid, pick_date)
);

CREATE INDEX idx_picks_date ON daily_picks(pick_date);


-- Point-in-time signal snapshots (for backtesting)
CREATE TABLE daily_snapshots (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    cap_tier        TEXT,
    close_price     REAL,
    -- All signals at this point in time
    piotroski_f     INTEGER,
    cf_accruals     REAL,
    bs_accruals     REAL,
    earnings_yield  REAL,
    book_to_price   REAL,
    consensus_signal REAL,
    promoter_qoq    REAL,
    delivery_pct    REAL,
    mom_6m          REAL,
    mom_12m         REAL,
    smart_money     REAL,
    sentiment_7d    REAL,
    PRIMARY KEY (sid, snapshot_date)
);

CREATE INDEX idx_snapshots_date ON daily_snapshots(snapshot_date);
CREATE INDEX idx_snapshots_tier ON daily_snapshots(cap_tier);
```

#### PIPELINE METADATA

```sql
-- Pipeline execution log (populated by Prefect, queryable via SQL)
CREATE TABLE pipeline_runs (
    run_id          TEXT PRIMARY KEY,          -- Prefect flow run ID
    flow_name       TEXT NOT NULL,             -- "daily_pipeline", "weekend_refresh"
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT,                      -- COMPLETED, FAILED, CANCELLED
    duration_sec    REAL,
    tasks_total     INTEGER,
    tasks_succeeded INTEGER,
    tasks_failed    INTEGER,
    error_message   TEXT
);

CREATE TABLE pipeline_task_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES pipeline_runs(run_id),
    task_name       TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    status          TEXT,
    duration_sec    REAL,
    rows_written    INTEGER,
    error_message   TEXT
);
```

---

## Part 2: Prefect Flow Design

### Installation
```bash
source ~/alpha-signal/venv/bin/activate
pip install prefect --break-system-packages
prefect server start  # runs UI on http://localhost:4200
```

### Flow Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  DAILY PIPELINE (runs 3:30 AM IST via Prefect scheduler)       │
│                                                                │
│  ┌──────────────────────────────────────────┐                  │
│  │  STAGE 1: HARVEST (parallel where safe)   │                  │
│  │                                           │                  │
│  │  ┌─────────────┐  ┌─────────────┐        │                  │
│  │  │ fetch_news   │  │track_insiders│        │                  │
│  │  └──────┬──────┘  └──────┬──────┘        │                  │
│  │         │                │               │                  │
│  │  ┌──────┴──────┐  ┌─────┴──────────┐    │                  │
│  │  │score_sentiment│ │fetch_earnings  │    │                  │
│  │  └──────┬──────┘  └────────────────┘    │                  │
│  │         │                               │                  │
│  │  ┌──────┴──────┐  ┌─────────────┐       │                  │
│  │  │classify_news │  │fetch_macro  │       │                  │
│  │  └─────────────┘  └─────────────┘       │                  │
│  │                                           │                  │
│  │  ┌─────────────┐  ┌─────────────┐        │                  │
│  │  │fetch_smart   │  │refresh_vix  │        │                  │
│  │  │  _money      │  │  _regime    │        │                  │
│  │  └─────────────┘  └─────────────┘        │                  │
│  └──────────────────────────────────────────┘                  │
│                         │                                      │
│                         ▼                                      │
│  ┌──────────────────────────────────────────┐                  │
│  │  STAGE 2: COMPUTE SIGNALS (after harvest) │                  │
│  │                                           │                  │
│  │  ┌───────────┐ ┌──────────┐ ┌──────────┐ │                  │
│  │  │compute    │ │compute   │ │compute   │ │                  │
│  │  │_forensic  │ │_piotroski│ │_accruals │ │                  │
│  │  └───────────┘ └──────────┘ └──────────┘ │                  │
│  │  ┌───────────┐ ┌──────────┐              │                  │
│  │  │compute    │ │compute   │              │                  │
│  │  │_consensus │ │_promoter │              │                  │
│  │  └───────────┘ └──────────┘              │                  │
│  └──────────────────────────────────────────┘                  │
│                         │                                      │
│                         ▼                                      │
│  ┌──────────────────────────────────────────┐                  │
│  │  STAGE 3: SCORE & OUTPUT (sequential)     │                  │
│  │                                           │                  │
│  │  run_screener                             │                  │
│  │       ↓                                   │                  │
│  │  integrate_signals                        │                  │
│  │       ↓                                   │                  │
│  │  archive_snapshot                         │                  │
│  │       ↓                                   │                  │
│  │  generate_dossier (AI)                    │                  │
│  │       ↓                                   │                  │
│  │  send_email                               │                  │
│  └──────────────────────────────────────────┘                  │
│                         │                                      │
│                         ▼                                      │
│  ┌──────────────────────────────────────────┐                  │
│  │  STAGE 4: HOUSEKEEPING                    │                  │
│  │  log_pipeline_run → git_backup            │                  │
│  └──────────────────────────────────────────┘                  │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  WEEKEND REFRESH (runs Saturday 5 AM)                          │
│                                                                │
│  refresh_universe_index                                        │
│       ↓                                                        │
│  refresh_stock_metadata (yfinance for all 2,500)               │
│       ↓                                                        │
│  refresh_price_history (3 years OHLCV)                         │
│       ↓                                                        │
│  refresh_tier_assignment                                       │
│       ↓                                                        │
│  run_data_hygiene                                              │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  MONTHLY DEEP HARVEST (manual trigger or 1st Saturday)         │
│                                                                │
│  harvest_financials (income, BS, CF — Tickertape)              │
│       ↓                                                        │
│  harvest_shareholding                                          │
│       ↓                                                        │
│  harvest_analyst_consensus                                     │
│       ↓                                                        │
│  harvest_forecast_history                                      │
│       ↓                                                        │
│  harvest_slug_map                                              │
└────────────────────────────────────────────────────────────────┘
```

### Prefect Code Structure

```python
# flows/daily_pipeline.py

from prefect import flow, task, get_run_logger
from prefect.tasks import task_input_hash
from datetime import timedelta
import sqlite3
import pandas as pd
from config.database import get_db, DB_PATH

# ── STAGE 1 TASKS ──

@task(retries=2, retry_delay_seconds=30, tags=["harvest", "network"])
def fetch_news():
    """Fetch RSS articles → news_articles + news_article_stocks tables."""
    logger = get_run_logger()
    # ... (adapted from 06_fetch_news.py, writes to DB instead of CSV)
    logger.info(f"Fetched {n_new} new articles, matched to {n_stocks} stocks")
    return n_new

@task(retries=1, tags=["compute"])
def score_sentiment():
    """VADER sentiment → sentiment_scores table."""
    logger = get_run_logger()
    # ... (adapted from 07_sentiment_scorer.py)
    logger.info(f"Scored sentiment for {n} stocks")
    return n

@task(retries=2, retry_delay_seconds=60, tags=["harvest", "network"])
def track_insiders():
    """BSE/NSE/Trendlyne → insider_trades + insider_signals tables."""
    logger = get_run_logger()
    # ... (adapted from 09_insider_tracker.py, UNIQUE constraint handles dedup)
    logger.info(f"Found {n_trades} trades, {n_signals} signals")
    return n_signals

@task(retries=1, tags=["harvest", "network"])
def fetch_earnings_calendar():
    """NSE event calendar → earnings_calendar table."""
    ...

@task(retries=1, tags=["harvest", "network"])
def classify_news():
    """Claude Haiku classification → updates news_articles with category."""
    ...

@task(retries=1, tags=["compute"])
def compute_forensic():
    """Beneish + Altman → forensic_scores table."""
    ...

@task(retries=1, tags=["harvest", "network"])
def fetch_macro():
    """RBI/PIB/GST → macro_indicators + macro_sector_signals tables."""
    ...

@task(retries=2, retry_delay_seconds=30, tags=["harvest", "network"])
def fetch_smart_money():
    """NSE bulk/block + bhavcopy → bulk_deals + delivery_data + smart_money_scores."""
    ...

@task(retries=1, tags=["harvest", "network"])
def refresh_vix_regime():
    """yfinance ^INDIAVIX → vix_history + regime_state tables."""
    ...


# ── STAGE 2 TASKS ──

@task(tags=["compute"])
def compute_piotroski():
    """quarterly_income + annual_balance_sheet + annual_cash_flow → piotroski_scores."""
    ...

@task(tags=["compute"])
def compute_accruals():
    """Same inputs → accruals_scores."""
    ...

@task(tags=["compute"])
def compute_consensus():
    """analyst_consensus + forecast_history → consensus_signals."""
    ...

@task(tags=["compute"])
def compute_promoter():
    """shareholding → promoter_signals."""
    ...


# ── STAGE 3 TASKS ──

@task(tags=["compute"])
def run_screener():
    """stocks + stock_prices + sentiment → base screen."""
    ...

@task(tags=["compute"])
def integrate_signals():
    """All signals → daily_picks table."""
    ...

@task(tags=["compute"])
def archive_snapshot():
    """Current signals → daily_snapshots table."""
    ...

@task(retries=1, tags=["network", "ai"])
def generate_dossier():
    """Top picks → Claude Sonnet → dossier text."""
    ...

@task(retries=1, tags=["network"])
def send_email():
    """daily_picks + dossier → Gmail."""
    ...


# ── THE FLOW ──

@flow(name="daily_pipeline", log_prints=True)
def daily_pipeline():
    """Main daily pipeline — runs at 3:30 AM IST."""
    logger = get_run_logger()
    logger.info("Starting daily pipeline")

    # Stage 1: Harvest (parallel where independent)
    news_future = fetch_news.submit()
    insider_future = track_insiders.submit()
    earnings_future = fetch_earnings_calendar.submit()
    macro_future = fetch_macro.submit()
    smart_money_future = fetch_smart_money.submit()
    vix_future = refresh_vix_regime.submit()

    # Wait for news before sentiment/classification
    news_count = news_future.result()
    sentiment_future = score_sentiment.submit()
    classify_future = classify_news.submit()

    # Wait for all Stage 1
    insider_future.result()
    earnings_future.result()
    macro_future.result()
    smart_money_future.result()
    vix_future.result()
    sentiment_future.result()
    classify_future.result()

    # Stage 2: Compute signals (parallel)
    forensic_future = compute_forensic.submit()
    piotroski_future = compute_piotroski.submit()
    accruals_future = compute_accruals.submit()
    consensus_future = compute_consensus.submit()
    promoter_future = compute_promoter.submit()

    # Wait for all Stage 2
    forensic_future.result()
    piotroski_future.result()
    accruals_future.result()
    consensus_future.result()
    promoter_future.result()

    # Stage 3: Score & Output (sequential)
    run_screener()
    integrate_signals()
    archive_snapshot()
    generate_dossier()
    send_email()

    logger.info("Daily pipeline complete")


if __name__ == "__main__":
    daily_pipeline()
```

### Deployment & Scheduling

```python
# flows/deploy.py — register schedules with Prefect

from prefect import serve
from flows.daily_pipeline import daily_pipeline
from flows.weekend_refresh import weekend_refresh
from flows.monthly_harvest import monthly_harvest

if __name__ == "__main__":
    daily_deploy = daily_pipeline.to_deployment(
        name="daily-pipeline",
        cron="30 3 * * *",           # 3:30 AM daily (IST = UTC+5:30)
        tags=["production"],
    )

    weekend_deploy = weekend_refresh.to_deployment(
        name="weekend-refresh",
        cron="0 5 * * 6",            # Saturday 5 AM
        tags=["production"],
    )

    monthly_deploy = monthly_harvest.to_deployment(
        name="monthly-harvest",
        cron="0 4 1 * *",            # 1st of month, 4 AM
        tags=["production"],
    )

    serve(daily_deploy, weekend_deploy, monthly_deploy)
```

---

## Part 3: Database Helper Module

```python
# config/database.py — single module for all DB access

import sqlite3
import pandas as pd
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent.parent / "data" / "alpha_signal.db"

@contextmanager
def get_db():
    """Get a database connection with WAL mode and foreign keys."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")       # concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")         # enforce references
    conn.execute("PRAGMA busy_timeout=5000")       # wait 5s on locks
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def read_table(table_name, where=None, params=None):
    """Read a table (or filtered subset) into a DataFrame."""
    query = f"SELECT * FROM {table_name}"
    if where:
        query += f" WHERE {where}"
    with get_db() as conn:
        return pd.read_sql_query(query, conn, params=params)


def upsert_df(df, table_name, conn, if_exists="replace"):
    """Write a DataFrame to a table with upsert semantics."""
    df.to_sql(table_name, conn, if_exists=if_exists, index=False,
              method="multi", chunksize=500)


def get_universe(tier=None):
    """Load the stock universe, optionally filtered by tier."""
    where = f"cap_tier = '{tier}'" if tier else None
    return read_table("stocks", where)


def get_latest_signal(table_name, sid=None):
    """Get the most recent snapshot from a signal table."""
    where = "snapshot_date = (SELECT MAX(snapshot_date) FROM {})".format(table_name)
    if sid:
        where += f" AND sid = '{sid}'"
    return read_table(table_name, where)


def init_db():
    """Create all tables if they don't exist. Safe to run multiple times."""
    schema_sql = (Path(__file__).parent.parent / "config" / "schema.sql").read_text()
    with get_db() as conn:
        conn.executescript(schema_sql)
    print(f"Database initialized at {DB_PATH}")
```

---

## Part 4: Migration Strategy

### Order of operations (don't break the running pipeline)

```
Week 1: Foundation
  ├─ Install Prefect, set up server
  ├─ Create config/schema.sql (all CREATE TABLE statements)
  ├─ Create config/database.py (helper module)
  ├─ Create scripts/migrate_csv_to_db.py (one-time CSV → SQLite migration)
  ├─ Run migration, verify row counts match
  └─ Prefect UI running, no flows yet

Week 2: First flow (news pipeline only)
  ├─ Adapt 06_fetch_news.py → tasks that write to DB
  ├─ Adapt 07_sentiment_scorer.py → reads/writes DB
  ├─ Test: run via Prefect, check UI, compare outputs to CSV version
  └─ Old CSV pipeline still runs daily (parallel operation)

Week 3: Remaining harvest tasks
  ├─ Adapt 09, 18, 14, 16, 33_regime, 17 → DB tasks
  ├─ All Stage 1 tasks working in Prefect
  └─ CSV pipeline still running as backup

Week 4: Signal + integration tasks
  ├─ Adapt 27, 28, 29, 30 → DB tasks
  ├─ Adapt 03, 08, 26, 11, 04 → DB tasks
  ├─ Full daily_pipeline flow working end-to-end
  ├─ Run BOTH pipelines for 3 days, compare outputs
  └─ Switch cron to Prefect, retire run_pipeline.sh

Week 5: Weekend + monthly flows
  ├─ Build weekend_refresh flow (universe + prices + metadata)
  ├─ Build monthly_harvest flow (financials + shareholding)
  ├─ Retire run_weekend_refresh.sh
  └─ Delete CSV files after confirming DB has all data
```

### One-time CSV → SQLite migration script
```python
# scripts/migrate_csv_to_db.py

"""
One-time migration: read all existing CSVs, insert into SQLite tables.
Run once, verify counts, then proceed with Prefect flows.
"""

from config.database import get_db, init_db, DB_PATH
import pandas as pd
from pathlib import Path

DATA = Path("data")

def migrate():
    init_db()

    migrations = [
        # (csv_path, table_name, column_mapping or None)
        (DATA / "harvester/universe.csv",          "stocks",              None),
        (DATA / "harvester/quarterly_income.csv",  "quarterly_income",    None),
        (DATA / "harvester/annual_balancesheet.csv","annual_balance_sheet",None),
        (DATA / "harvester/annual_cashflow.csv",   "annual_cash_flow",    None),
        (DATA / "harvester/shareholding.csv",       "shareholding",       None),
        (DATA / "analyst/consensus.csv",            "analyst_consensus",  None),
        (DATA / "analyst/forecast_history.csv",     "forecast_history",   None),
        (DATA / "news/news_archive.csv",            "news_articles",      None),
        (DATA / "reference/india_vix.csv",          "vix_history",        None),
        (DATA / "signals/piotroski.csv",            "piotroski_scores",   None),
        (DATA / "signals/accruals.csv",             "accruals_scores",    None),
        (DATA / "signals/consensus.csv",            "consensus_signals",  None),
        (DATA / "signals/promoter.csv",             "promoter_signals",   None),
        (DATA / "smart_money/smart_money_score.csv","smart_money_scores", None),
        (DATA / "forensic/forensic_scores.csv",     "forensic_scores",    None),
        (DATA / "events/earnings_calendar.csv",     "earnings_calendar",  None),
        (DATA / "macro/macro_pulse.csv",            "macro_indicators",   None),
    ]

    with get_db() as conn:
        for csv_path, table, col_map in migrations:
            if not csv_path.exists():
                print(f"  SKIP (not found): {csv_path}")
                continue
            df = pd.read_csv(csv_path)
            if col_map:
                df = df.rename(columns=col_map)
            # Insert, ignoring columns that don't match the table schema
            try:
                df.to_sql(table, conn, if_exists="append", index=False)
                print(f"  ✅ {table}: {len(df)} rows from {csv_path.name}")
            except Exception as e:
                print(f"  ⚠️  {table}: {e}")

        # Migrate price data (many files → one table)
        price_dir = DATA / "price_data"
        if price_dir.exists():
            count = 0
            for f in price_dir.glob("*.csv"):
                sid = f.stem
                try:
                    df = pd.read_csv(f, parse_dates=True)
                    df["sid"] = sid
                    df.to_sql("stock_prices", conn, if_exists="append", index=False)
                    count += 1
                except Exception:
                    pass
            print(f"  ✅ stock_prices: {count} stock files migrated")

    print(f"\nDatabase: {DB_PATH} ({DB_PATH.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    migrate()
```

---

## Part 5: Prefect UI — What You'll See

Once running, open **http://your-vm-ip:4200** to see:

### Flow Runs Dashboard
```
┌─────────────────────────────────────────────────────────┐
│  Flow Runs                                     [Filter] │
│                                                         │
│  ✅ daily_pipeline  2026-04-09 03:30  4m 22s  COMPLETED │
│  ✅ daily_pipeline  2026-04-08 03:30  4m 18s  COMPLETED │
│  🔴 daily_pipeline  2026-04-07 03:30  2m 01s  FAILED    │
│     └─ fetch_smart_money: NSE timeout after 60s         │
│  ✅ weekend_refresh  2026-04-05 05:00  18m 44s COMPLETED│
│  ✅ daily_pipeline  2026-04-04 03:30  4m 35s  COMPLETED │
└─────────────────────────────────────────────────────────┘
```

### Task-Level Detail (click into a run)
```
┌─────────────────────────────────────────────────────────┐
│  daily_pipeline — 2026-04-09 03:30                       │
│                                                         │
│  STAGE 1: HARVEST                                       │
│  ✅ fetch_news           12s   (142 new articles)       │
│  ✅ track_insiders       8s    (23 trades, 8 signals)   │
│  ✅ fetch_earnings       3s    (12 upcoming)            │
│  ✅ fetch_macro          5s    (23 indicators)          │
│  ✅ fetch_smart_money    15s   (bulk + delivery)        │
│  ✅ refresh_vix_regime   4s    (VIX=14.2, NORMAL)       │
│  ✅ score_sentiment      6s    (389 stocks scored)      │
│  ✅ classify_news        22s   (18 articles classified)  │
│                                                         │
│  STAGE 2: COMPUTE                                       │
│  ✅ compute_forensic     8s                             │
│  ✅ compute_piotroski    5s                             │
│  ✅ compute_accruals     4s                             │
│  ✅ compute_consensus    3s                             │
│  ✅ compute_promoter     2s                             │
│                                                         │
│  STAGE 3: OUTPUT                                        │
│  ✅ run_screener         35s                            │
│  ✅ integrate_signals    12s   (15 picks)               │
│  ✅ archive_snapshot     4s    (2,500 rows)             │
│  ✅ generate_dossier     45s   (5 dossiers, ₹12 spent) │
│  ✅ send_email           3s                             │
└─────────────────────────────────────────────────────────┘
```

### What you can do in the UI:
- **See history** of every run with timing and status
- **Click into failures** to see the exact error traceback
- **Re-run failed tasks** without re-running the whole pipeline
- **Trigger manual runs** (e.g. monthly harvest on demand)
- **See task dependencies** as a visual DAG
- **Filter by tag** (e.g. show only "network" tasks to see all external API calls)
- **Set notifications** (Prefect Cloud supports Slack/email; self-hosted uses webhooks)

---

## Project Structure After Migration

```
~/alpha-signal/
├── config/
│   ├── settings.py              # existing (keep for now)
│   ├── pipeline_config.py       # NEW: all thresholds, constants
│   ├── database.py              # NEW: DB helper module
│   └── schema.sql               # NEW: all CREATE TABLE statements
│
├── flows/
│   ├── daily_pipeline.py        # NEW: main Prefect flow
│   ├── weekend_refresh.py       # NEW: weekly refresh flow
│   ├── monthly_harvest.py       # NEW: monthly deep harvest
│   └── deploy.py                # NEW: register all deployments
│
├── tasks/                       # NEW: one file per task group
│   ├── harvest_news.py          # adapted from 06 + 07 + 10
│   ├── harvest_insiders.py      # adapted from 09
│   ├── harvest_macro.py         # adapted from 14 + 33_regime
│   ├── harvest_smart_money.py   # adapted from 16
│   ├── harvest_fundamentals.py  # adapted from 22
│   ├── compute_signals.py       # adapted from 27, 28, 29, 30
│   ├── compute_forensic.py      # adapted from 17
│   ├── score_and_integrate.py   # adapted from 03 + 08
│   ├── output.py                # adapted from 11 + 04 + 26
│   └── maintenance.py           # cleanup, hygiene, git backup
│
├── scripts/                     # OLD: kept during migration, retired after
│   ├── (all existing .py files)
│   └── migrate_csv_to_db.py     # one-time migration
│
├── tests/
│   ├── test_smoke.py            # pre-pipeline checks
│   ├── test_contracts.py        # schema validation
│   └── test_signals.py          # regression checks
│
├── data/
│   ├── alpha_signal.db          # NEW: the single database
│   ├── backtest/                # keep: reconstructed signals + prices for backtesting
│   └── (old CSVs kept as backup during migration)
│
├── learning/                    # existing notebooks (update to read from DB)
├── Audit/                       # existing audit notebook
├── AUDIT_NOTES.md
├── SYSTEM_HARDENING_PLAN.md
├── PREFECT_SQLITE_ARCHITECTURE.md  # this file
└── CLAUDE.md
```

---

## Decision Points for You

Before we start building, confirm these:

1. **Prefect self-hosted vs Cloud?** Self-hosted is free, runs on your VM. Cloud gives you mobile notifications + team features but requires account. I recommend **self-hosted** to start.

2. **Migration approach?** The plan above runs both systems in parallel for a week before switching. This is safest but means maintaining both briefly. OK?

3. **Which flow to build first?** I recommend the news→sentiment pipeline (Branch A) because it's the simplest chain and gives you a working Prefect flow + DB writes to validate the pattern before tackling the complex ones.

4. **Do you want the old numbered scripts deleted after migration, or archived to a `scripts/legacy/` folder?**
