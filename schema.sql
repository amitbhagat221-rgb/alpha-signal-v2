-- Alpha Signal v2 — Database Schema
-- 25 tables in 5 groups
-- Run once via: db.py init_db()

-- ═══════════════════════════════════════════════════
-- GROUP 1: UNIVERSE & REFERENCE
-- ═══════════════════════════════════════════════════

-- THE single source of truth for all stocks.
-- Replaces: nifty500_list.csv + stock_metadata.csv + universe.csv + slug_map.csv
CREATE TABLE IF NOT EXISTS stocks (
    sid             TEXT PRIMARY KEY,
    ticker          TEXT NOT NULL,
    name            TEXT NOT NULL,
    sector          TEXT,
    industry        TEXT,
    cap_tier        TEXT CHECK(cap_tier IN ('LARGE', 'MID', 'SMALL')),
    market_cap_cr   REAL,
    adtv_6m_cr      REAL,
    in_nifty500     INTEGER DEFAULT 0,
    slug            TEXT,
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
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_stocks_tier ON stocks(cap_tier);
CREATE INDEX IF NOT EXISTS idx_stocks_sector ON stocks(sector);
CREATE INDEX IF NOT EXISTS idx_stocks_ticker ON stocks(ticker);


-- Daily OHLCV + delivery data. Replaces 501 individual CSV files.
-- Also replaces the old delivery_data table — single source for price + delivery.
CREATE TABLE IF NOT EXISTS stock_prices (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    date            TEXT NOT NULL,
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL NOT NULL,
    prev_close      REAL,
    volume          INTEGER CHECK(volume >= 0),
    traded_value    REAL,
    num_trades      INTEGER CHECK(num_trades >= 0),
    delivered_qty   INTEGER CHECK(delivered_qty >= 0),
    delivery_pct    REAL CHECK(delivery_pct BETWEEN 0 AND 100),
    source          TEXT DEFAULT 'bhavcopy',
    PRIMARY KEY (sid, date)
);

CREATE INDEX IF NOT EXISTS idx_prices_date ON stock_prices(date);


-- India VIX daily history
CREATE TABLE IF NOT EXISTS vix_history (
    date            TEXT PRIMARY KEY,
    vix             REAL NOT NULL CHECK(vix > 0)
);


-- Current regime state (singleton row — always id=1)
CREATE TABLE IF NOT EXISTS regime_state (
    id              INTEGER PRIMARY KEY DEFAULT 1 CHECK(id = 1),
    regime          TEXT CHECK(regime IN ('CALM', 'NORMAL', 'CAUTION', 'CRISIS')),
    vix_latest      REAL,
    vix_20d_avg     REAL,
    alloc_large     REAL,
    alloc_mid       REAL,
    alloc_small     REAL,
    updated_at      TEXT DEFAULT (datetime('now'))
);


-- ═══════════════════════════════════════════════════
-- GROUP 2: RAW DATA (harvested from external sources)
-- ═══════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS quarterly_income (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    period          TEXT NOT NULL,
    end_date        TEXT,
    reporting       TEXT DEFAULT 'consolidated',
    revenue         REAL,
    operating_profit REAL,
    net_income      REAL,
    eps             REAL,
    interest        REAL,
    pbt             REAL,
    total_other_income REAL,
    ebitda          REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, period, reporting)
);

CREATE TABLE IF NOT EXISTS annual_balance_sheet (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    period          TEXT NOT NULL,
    end_date        TEXT,
    total_assets    REAL,
    total_equity    REAL,
    total_debt      REAL,
    current_assets  REAL,
    current_liabilities REAL,
    cash_and_equivalents REAL,
    receivables     REAL,
    retained_earnings REAL,
    net_ppe         REAL,
    total_liabilities REAL,
    shares_outstanding REAL,
    long_term_debt  REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, period)
);

CREATE TABLE IF NOT EXISTS annual_cash_flow (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    period          TEXT NOT NULL,
    end_date        TEXT,
    operating_cash_flow REAL,
    capex           REAL,
    free_cash_flow  REAL,
    investing_cash_flow REAL,
    financing_cash_flow REAL,
    working_capital_change REAL,
    depreciation    REAL,
    net_change_in_cash REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, period)
);

CREATE TABLE IF NOT EXISTS shareholding (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    end_date        TEXT NOT NULL,
    promoter_pct    REAL CHECK(promoter_pct BETWEEN 0 AND 100),
    fii_pct         REAL CHECK(fii_pct BETWEEN 0 AND 100),
    mf_pct          REAL CHECK(mf_pct BETWEEN 0 AND 100),
    dii_pct         REAL CHECK(dii_pct BETWEEN 0 AND 100),
    public_pct      REAL CHECK(public_pct BETWEEN 0 AND 100),
    pledge_pct      REAL CHECK(pledge_pct BETWEEN 0 AND 100),
    insurance_pct   REAL CHECK(insurance_pct BETWEEN 0 AND 100),
    retail_hni_pct  REAL CHECK(retail_hni_pct BETWEEN 0 AND 100),
    other_pct       REAL CHECK(other_pct BETWEEN 0 AND 100),
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, end_date)
);

-- Analyst consensus: current snapshot per stock.
-- Use INSERT OR REPLACE to always keep latest.
-- Historical tracking happens via daily_snapshots table.
CREATE TABLE IF NOT EXISTS analyst_consensus (
    sid             TEXT PRIMARY KEY REFERENCES stocks(sid),
    total_analysts  INTEGER,
    buy_pct         REAL CHECK(buy_pct BETWEEN 0 AND 100),
    price_target    REAL,
    forward_eps     REAL,
    eps_growth_pct  REAL,
    forward_revenue REAL,
    revenue_growth_pct REAL,
    has_analyst_data INTEGER DEFAULT 1,
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS forecast_history (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    metric          TEXT NOT NULL,
    date            TEXT NOT NULL,
    value           REAL,
    change          REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, metric, date)
);

CREATE TABLE IF NOT EXISTS news_articles (
    article_id      TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    summary         TEXT,
    url             TEXT,
    source          TEXT NOT NULL,
    published_at    TEXT,
    fetched_at      TEXT DEFAULT (datetime('now'))
);

-- Many-to-many: articles ↔ stocks
CREATE TABLE IF NOT EXISTS news_article_stocks (
    article_id      TEXT NOT NULL REFERENCES news_articles(article_id),
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    match_location  TEXT,
    PRIMARY KEY (article_id, sid)
);

CREATE INDEX IF NOT EXISTS idx_news_stocks_sid ON news_article_stocks(sid);

CREATE TABLE IF NOT EXISTS insider_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    symbol          TEXT,
    company_name    TEXT,
    person          TEXT,
    person_category TEXT,
    transaction_type TEXT,
    shares          REAL,
    value_lakhs     REAL,
    trade_date      TEXT,
    source          TEXT,
    fetched_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(sid, person_category, transaction_type, trade_date, shares)
);

CREATE INDEX IF NOT EXISTS idx_insider_sid ON insider_trades(sid);
CREATE INDEX IF NOT EXISTS idx_insider_date ON insider_trades(trade_date);

CREATE TABLE IF NOT EXISTS bulk_deals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    symbol          TEXT NOT NULL,
    client_name     TEXT,
    deal_type       TEXT,
    buy_sell        TEXT,
    quantity        REAL,
    price           REAL,
    deal_date       TEXT NOT NULL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(symbol, client_name, deal_date, quantity)
);

CREATE TABLE IF NOT EXISTS earnings_calendar (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,
    symbol          TEXT,
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    company         TEXT,
    purpose         TEXT,
    bm_desc         TEXT,
    added_date      TEXT DEFAULT (date('now')),
    UNIQUE(symbol, date)
);

CREATE TABLE IF NOT EXISTS macro_indicators (
    indicator       TEXT NOT NULL,
    signal          TEXT,
    value           REAL,
    detail          TEXT,
    snapshot_date   TEXT NOT NULL,
    PRIMARY KEY (indicator, snapshot_date)
);


-- ═══════════════════════════════════════════════════
-- GROUP 3: COMPUTED SIGNALS
-- All signal tables have snapshot_date indexes for
-- efficient "get latest signals" queries.
-- ═══════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS sentiment_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    sentiment_today REAL,
    articles_today  INTEGER DEFAULT 0,
    sentiment_7d    REAL,
    articles_7d     INTEGER DEFAULT 0,
    sentiment_30d   REAL,
    articles_30d    INTEGER DEFAULT 0,
    sentiment_momentum REAL,
    latest_headline TEXT,
    PRIMARY KEY (sid, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_sentiment_date ON sentiment_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS insider_signals (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    signal_type     TEXT NOT NULL,
    strength        TEXT,
    score_impact    REAL NOT NULL,
    description     TEXT,
    PRIMARY KEY (sid, snapshot_date, signal_type)
);

CREATE INDEX IF NOT EXISTS idx_insider_signals_date ON insider_signals(snapshot_date);

CREATE TABLE IF NOT EXISTS smart_money_scores (
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

CREATE INDEX IF NOT EXISTS idx_smart_money_date ON smart_money_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS forensic_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    m_score         REAL,
    m_score_flag    TEXT,
    z_score         REAL,
    z_score_flag    TEXT,
    penalty         REAL DEFAULT 0,
    PRIMARY KEY (sid, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_forensic_date ON forensic_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS piotroski_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    f_score         INTEGER CHECK(f_score BETWEEN 0 AND 9),
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

CREATE INDEX IF NOT EXISTS idx_piotroski_date ON piotroski_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS accruals_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    cf_accruals_ratio REAL,
    bs_accruals_ratio REAL,
    earnings_persistence REAL,
    accruals_signal REAL,
    PRIMARY KEY (sid, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_accruals_date ON accruals_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS consensus_signals (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    pt_upside       REAL,
    pt_revision_1yr REAL,
    eps_growth      REAL,
    revenue_growth  REAL,
    consensus_signal REAL,
    PRIMARY KEY (sid, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_consensus_date ON consensus_signals(snapshot_date);

CREATE TABLE IF NOT EXISTS promoter_signals (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    promoter_qoq    REAL,
    promoter_trend  TEXT,
    pledge_quality  REAL,
    promoter_signal REAL,
    PRIMARY KEY (sid, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_promoter_date ON promoter_signals(snapshot_date);

CREATE TABLE IF NOT EXISTS macro_sector_signals (
    sector          TEXT NOT NULL,
    snapshot_date   TEXT NOT NULL,
    macro_score     REAL,
    macro_signal    TEXT,
    macro_detail    TEXT,
    PRIMARY KEY (sector, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_macro_sector_date ON macro_sector_signals(snapshot_date);


-- ═══════════════════════════════════════════════════
-- GROUP 4: OUTPUT
-- ═══════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS daily_picks (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    pick_date       TEXT NOT NULL,
    final_score     REAL,
    rank            INTEGER,
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
    cap_tier        TEXT,
    sector          TEXT,
    PRIMARY KEY (sid, pick_date)
);

CREATE INDEX IF NOT EXISTS idx_picks_date ON daily_picks(pick_date);

CREATE TABLE IF NOT EXISTS daily_snapshots (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    cap_tier        TEXT,
    close_price     REAL,
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

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON daily_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_snapshots_tier ON daily_snapshots(cap_tier);


-- ═══════════════════════════════════════════════════
-- GROUP 5: PIPELINE METADATA
-- ═══════════════════════════════════════════════════

-- Replaces Prefect dashboard. Query this table for pipeline health.
-- Example: SELECT * FROM pipeline_log WHERE run_date = date('now') ORDER BY started_at
CREATE TABLE IF NOT EXISTS pipeline_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        TEXT NOT NULL DEFAULT (date('now')),
    step_name       TEXT NOT NULL,
    status          TEXT CHECK(status IN ('RUNNING', 'SUCCESS', 'FAILED', 'SKIPPED')),
    rows_affected   INTEGER,
    started_at      TEXT DEFAULT (datetime('now')),
    finished_at     TEXT,
    duration_sec    REAL,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_log_date ON pipeline_log(run_date);


-- ═══════════════════════════════════════════════════
-- GROUP 6: MACRO & REGULATORY INTELLIGENCE
-- ═══════════════════════════════════════════════════

-- Historical time series for all macro indicators (replaces flat macro_indicators for analysis)
CREATE TABLE IF NOT EXISTS macro_history (
    indicator_id    TEXT NOT NULL,
    date            TEXT NOT NULL,
    value           REAL,
    yoy_change      REAL,
    mom_change      REAL,
    source          TEXT,
    category        TEXT,
    unit            TEXT,
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (indicator_id, date)
);

CREATE INDEX IF NOT EXISTS idx_macro_history_date ON macro_history(date);
CREATE INDEX IF NOT EXISTS idx_macro_history_category ON macro_history(category);

-- Registry of all macro indicators with metadata
CREATE TABLE IF NOT EXISTS macro_indicator_meta (
    indicator_id    TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source          TEXT NOT NULL,
    source_ref      TEXT,
    category        TEXT,
    frequency       TEXT DEFAULT 'monthly',
    unit            TEXT,
    description     TEXT
);

-- Indicator → Sector mapping with direction and weight
CREATE TABLE IF NOT EXISTS macro_sector_map (
    indicator_id    TEXT NOT NULL REFERENCES macro_indicator_meta(indicator_id),
    sector          TEXT NOT NULL,
    direction       INTEGER NOT NULL,
    weight          REAL DEFAULT 1.0,
    rationale       TEXT,
    PRIMARY KEY (indicator_id, sector)
);

-- Raw regulatory events from PIB/RBI/SEBI/Gazette/News
CREATE TABLE IF NOT EXISTS regulatory_events (
    event_id            TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    summary             TEXT,
    full_text           TEXT,
    source              TEXT NOT NULL,
    source_url          TEXT,
    published_at        TEXT NOT NULL,
    ministry            TEXT,
    fetched_at          TEXT DEFAULT (datetime('now')),
    -- Classifier audit trail (added 2026-04-11 to fix the silent-state bug)
    -- Values:  'pending'                   = never seen by classifier
    --          'haiku_rejected'            = Haiku said NO (proven, observed directly)
    --          'haiku_rejected_inferred'   = backfilled from Option A temporal inference
    --                                        (~95% confidence: not directly observed but the
    --                                        count + date range from yesterday's run logs
    --                                        proves Haiku reached this date range)
    --          'haiku_passed_sonnet_failed'= Haiku YES but Sonnet errored / bad JSON
    --          'classified'                = full pipeline done, signals saved
    --          'unknown'                   = oldest events that the date-DESC sweep
    --                                        likely never reached (~1,546 events from before
    --                                        2023-09-13, recoverable only by explicit re-run)
    classifier_status       TEXT DEFAULT 'pending',
    classifier_processed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_reg_events_date ON regulatory_events(published_at);
CREATE INDEX IF NOT EXISTS idx_reg_events_source ON regulatory_events(source);
CREATE INDEX IF NOT EXISTS idx_reg_events_classifier_status ON regulatory_events(classifier_status);

-- AI-classified regulatory impact per sector
CREATE TABLE IF NOT EXISTS regulatory_signals (
    event_id        TEXT NOT NULL REFERENCES regulatory_events(event_id),
    sector          TEXT NOT NULL,
    is_regulatory   INTEGER NOT NULL,
    stage           TEXT,
    direction       INTEGER,
    magnitude       TEXT,
    time_horizon    TEXT,
    confidence      TEXT,
    ai_reasoning    TEXT,
    classified_at   TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (event_id, sector)
);

CREATE INDEX IF NOT EXISTS idx_reg_signals_sector ON regulatory_signals(sector);
CREATE INDEX IF NOT EXISTS idx_reg_signals_date ON regulatory_signals(classified_at);


-- ═══════════════════════════════════════════════════
-- GROUP 7: COCKPIT — CHANGE DETECTION
-- ═══════════════════════════════════════════════════

-- Daily change events produced by the diff engine.
-- Consumed by the cockpit Morning Brief and Action Queue.
CREATE TABLE IF NOT EXISTS daily_changes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    change_date     TEXT NOT NULL,
    change_type     TEXT NOT NULL,
    severity        TEXT NOT NULL,
    sid             TEXT,
    cap_tier        TEXT,
    headline        TEXT NOT NULL,
    detail          TEXT,
    color           TEXT
);

CREATE INDEX IF NOT EXISTS idx_changes_date ON daily_changes(change_date);
CREATE INDEX IF NOT EXISTS idx_changes_sid ON daily_changes(sid);


-- ═══════════════════════════════════════════════════
-- GROUP 8: F-TRACK FUNDAMENTALS (Screener Premium)
-- ═══════════════════════════════════════════════════

-- Long-format fundamentals from Screener.in Premium Excel exports.
-- One row per (sid × period_end × period_type × line_item).
-- Source: sources/screener_pull.py — see ADR/plan 0005 A1.
CREATE TABLE IF NOT EXISTS fundamentals_screener (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    period_end      TEXT NOT NULL,                -- ISO date (period close)
    period_type     TEXT NOT NULL,                -- 'quarterly' | 'annual'
    line_item       TEXT NOT NULL,                -- e.g. 'Revenue', 'COGS', 'Receivables'
    value           REAL,                         -- numeric value (NULL if Screener showed '—')
    filing_date     TEXT,                         -- when Screener says it was filed (often NULL)
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, period_end, period_type, line_item)
);

CREATE INDEX IF NOT EXISTS idx_fund_screener_sid ON fundamentals_screener(sid);
CREATE INDEX IF NOT EXISTS idx_fund_screener_item ON fundamentals_screener(line_item);

-- Per-stock pull errors. Append-only audit trail.
CREATE TABLE IF NOT EXISTS screener_pull_errors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sid             TEXT,                         -- nullable if error was pre-lookup
    ticker          TEXT,
    error_type      TEXT NOT NULL,                -- 'auth' | 'http' | 'parse' | 'thin' | 'empty' | 'fetch'
    error_message   TEXT,
    http_status     INTEGER,
    attempted_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_screener_errors_sid ON screener_pull_errors(sid);
CREATE INDEX IF NOT EXISTS idx_screener_errors_date ON screener_pull_errors(attempted_at);
