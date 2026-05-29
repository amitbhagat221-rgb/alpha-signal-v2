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
    cap_tier        TEXT CHECK(cap_tier IN ('LARGE', 'MID', 'SMALL', 'MICRO')),
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
    price_target    REAL,                              -- mean PT (kept for backward compat)
    -- Extended yfinance fields (added 2026-05-23 — Tier 1 PT plan):
    price_target_median REAL,                          -- more robust to outliers
    price_target_high   REAL,                          -- range top
    price_target_low    REAL,                          -- range bottom
    recommendation_key  TEXT,                          -- strong_buy/buy/hold/sell/strong_sell/none
    recommendation_mean REAL,                          -- 1=strong buy, 5=strong sell
    n_strong_buy   INTEGER,                            -- latest-period rating mix
    n_buy          INTEGER,
    n_hold         INTEGER,
    n_sell         INTEGER,
    n_strong_sell  INTEGER,
    pt_source      TEXT,                               -- 'yfinance' (only viable source as of 2026-05-23)
    -- PT freshness v2 (added 2026-05-23):
    next_earnings_date       TEXT,                     -- yyyy-mm-dd; freshness proxy (analysts revise post-earnings)
    rating_mix_history       TEXT,                     -- JSON: 4-period rating mix [[sb,b,h,s,ss], ...]
    price_target_prev        REAL,                     -- previous fetch's price_target (for change detection)
    price_target_changed_at  TEXT,                     -- datetime when we detected PT moved >0.5%
    forward_eps     REAL,
    eps_growth_pct  REAL,
    forward_revenue REAL,
    revenue_growth_pct REAL,
    has_analyst_data INTEGER DEFAULT 1,
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS forecast_history (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    metric          TEXT NOT NULL,                     -- 'price'/'eps'/'revenue'
    date            TEXT NOT NULL,                     -- publication / year-end date
    value           REAL,
    change          REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, metric, date)
);

-- Monthly snapshots of analyst consensus aggregate. Drives pt_revision_*
-- signals over proper windows. PTs are episodic — daily snapshots would be
-- phantom precision (same value most days). Snapshot once per month at the
-- 1st business day. Distinct from analyst_consensus (current-only, PK=sid)
-- and from forecast_history (year-end snapshots from Tickertape, even sparser).
CREATE TABLE IF NOT EXISTS analyst_consensus_snapshots (
    sid                 TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date       TEXT NOT NULL,                 -- 1st business day of month
    source              TEXT NOT NULL,                 -- 'yfinance' / 'tickertape' / 'moneycontrol'
    target_mean         REAL,
    target_median       REAL,
    target_high         REAL,                          -- highest analyst PT (dispersion proxy)
    target_low          REAL,
    n_analysts          INTEGER,
    recommendation_key  TEXT,                          -- strong_buy / buy / hold / sell / strong_sell / none
    recommendation_mean REAL,                          -- 1=strong buy, 5=strong sell
    fetched_at          TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, snapshot_date, source)
);
CREATE INDEX IF NOT EXISTS idx_acs_sid ON analyst_consensus_snapshots(sid);
CREATE INDEX IF NOT EXISTS idx_acs_date ON analyst_consensus_snapshots(snapshot_date);

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
    -- Pick-eligibility gate columns (persisted from 2026-05-24 so /audit
    -- can answer "why is this stock in/out of picks" without re-running scorer):
    weight_coverage      REAL,    -- fraction of tier signal weight backed by non-NULL signal OUTPUT
    price_rows           INTEGER, -- total non-zero close rows in stock_prices
    fundamental_coverage REAL,    -- min(quarterly_income rows / 8, 1.0) — INPUT-side coverage
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
    status          TEXT CHECK(status IN ('RUNNING', 'SUCCESS', 'FAILED', 'SKIPPED', 'COVERAGE_GAP', 'COVERAGE_SEVERE')),
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

-- ROIC (Return on Invested Capital) — first F-track factor sourced from fundamentals_screener.
-- NOPAT = (PBT + Interest) × (1 − Tax/PBT); Invested Capital = Equity + Reserves + Borrowings.
CREATE TABLE IF NOT EXISTS roic_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    period_end      TEXT,                         -- annual period used
    nopat           REAL,
    invested_capital REAL,
    roic            REAL,                         -- NOPAT / Invested Capital
    PRIMARY KEY (sid, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_roic_date ON roic_scores(snapshot_date);

-- FCF Yield — second F-track factor.
-- FCF = OCF − Capex; Capex ≈ Δ(Net Block + CWIP) + Depreciation (cf. roic.py
-- comment for derivation). Yield = 3-yr median FCF / current market cap.
CREATE TABLE IF NOT EXISTS fcf_yield_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    period_end      TEXT,
    fcf             REAL,                         -- 3-yr median FCF
    market_cap_cr   REAL,
    fcf_yield       REAL,                         -- FCF / Market Cap
    PRIMARY KEY (sid, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_fcfy_date ON fcf_yield_scores(snapshot_date);

-- Cash Conversion Cycle — third Track 3 factor.
-- DSO = Receivables / (Sales/365); DIO = Inventory / (Sales/365);
-- DPO = Trade Payables / (Sales/365); CCC = DSO + DIO − DPO.
-- Sales used as the denominator for all three legs (no clean COGS line in
-- Screener); the bias is consistent across stocks, so ranking is preserved.
-- 3-yr median per stock to suppress one-off year-end working-capital tactics.
CREATE TABLE IF NOT EXISTS cash_conversion_cycle_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    period_end      TEXT,
    dso             REAL,        -- days sales outstanding
    dio             REAL,        -- days inventory outstanding
    dpo             REAL,        -- days payables outstanding
    ccc             REAL,        -- DSO + DIO − DPO
    PRIMARY KEY (sid, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_ccc_date ON cash_conversion_cycle_scores(snapshot_date);

-- Operating Margin Trend — slope of last 5 years' (PBT+Interest)/Sales.
-- Positive slope = expanding profitability. Financials excluded.
CREATE TABLE IF NOT EXISTS operating_margin_trend_scores (
    sid              TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date    TEXT NOT NULL,
    period_end       TEXT,
    margin_latest    REAL,       -- most recent year's EBIT/Sales
    margin_5y_avg    REAL,       -- mean across the 5y window
    margin_slope     REAL,       -- pp/year slope from linear regression
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_omtrend_date ON operating_margin_trend_scores(snapshot_date);

-- Working Capital Intensity — 3y median (Receivables + Inventory − Trade Payables) / Sales.
-- Lower = less capital tied per ₹ of revenue. Same data lineage as CCC,
-- but expressed as a ratio rather than days — captures the magnitude of
-- working-capital drag in a scale-free way.
CREATE TABLE IF NOT EXISTS working_capital_intensity_scores (
    sid              TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date    TEXT NOT NULL,
    period_end       TEXT,
    wc_intensity     REAL,       -- (Recv+Inv-Pay)/Sales, 3y median
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_wci_date ON working_capital_intensity_scores(snapshot_date);

-- Interest Coverage — 3y median (PBT + Interest) / Interest.
-- Higher = safer balance sheet. Stocks with Interest ≈ 0 (no debt) are
-- excluded — coverage isn't meaningful, and they'd dominate the rank.
CREATE TABLE IF NOT EXISTS interest_coverage_scores (
    sid              TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date    TEXT NOT NULL,
    period_end       TEXT,
    interest_coverage REAL,      -- (PBT + Interest) / Interest, 3y median
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_icov_date ON interest_coverage_scores(snapshot_date);

-- ROIIC — Return on Incremental Invested Capital, 5-year endpoint.
-- (NOPAT_t − NOPAT_{t-5}) / (IC_t − IC_{t-5}). Drop ΔIC < ₹50 cr to avoid
-- denominator blow-ups and sign-inverted capital returners. Capped to ±5.
CREATE TABLE IF NOT EXISTS roiic_scores (
    sid              TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date    TEXT NOT NULL,
    period_end       TEXT,
    delta_nopat      REAL,        -- NOPAT_t − NOPAT_{t-5}, ₹cr
    delta_ic         REAL,        -- IC_t − IC_{t-5}, ₹cr (≥ 50 by filter)
    roiic            REAL,        -- ΔNOPAT / ΔIC, capped ±5
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_roiic_date ON roiic_scores(snapshot_date);

-- ─────────────────────────────────────────────────────────────
-- Forensic / capital-allocation batch (plan 0002 §3.2.1)
-- All single-column score tables, latest annual or 3y-median.
-- ─────────────────────────────────────────────────────────────

-- DSO YoY change (Receivables/(Sales/365) − prior year). Days.
CREATE TABLE IF NOT EXISTS dso_change_yoy_scores (
    sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT,
    dso_change_yoy REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_dsoyoy_date ON dso_change_yoy_scores(snapshot_date);

-- DIO YoY change (Inventory/(Sales/365) − prior year). Days.
CREATE TABLE IF NOT EXISTS dio_change_yoy_scores (
    sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT,
    dio_change_yoy REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_dioyoy_date ON dio_change_yoy_scores(snapshot_date);

-- NWC / Revenue, latest annual. Spot sibling of wc_intensity (3y median).
CREATE TABLE IF NOT EXISTS nwc_to_revenue_scores (
    sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT,
    nwc_to_revenue REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_nwc2rev_date ON nwc_to_revenue_scores(snapshot_date);

-- Sloan accruals (BS construction): (ΔNWC − Depreciation) / avg Total Assets.
CREATE TABLE IF NOT EXISTS sloan_accruals_full_scores (
    sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT,
    sloan_accruals_full REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_sloanfull_date ON sloan_accruals_full_scores(snapshot_date);

-- SGA / Revenue YoY change.
CREATE TABLE IF NOT EXISTS sga_to_revenue_change_scores (
    sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT,
    sga_to_revenue_change REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_sgachg_date ON sga_to_revenue_change_scores(snapshot_date);

-- FCF margin: 3y median FCF / Sales. (FCF formula = fcf_yield's.)
CREATE TABLE IF NOT EXISTS fcf_margin_scores (
    sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT,
    fcf_margin REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_fcfmargin_date ON fcf_margin_scores(snapshot_date);

-- CapEx / Depreciation ratio, 3y median. >1 = growing, <1 = harvesting.
CREATE TABLE IF NOT EXISTS capex_to_dep_scores (
    sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT,
    capex_to_dep REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_capdep_date ON capex_to_dep_scores(snapshot_date);

-- Intangibles / Total assets (proxy for goodwill_to_assets — Screener doesn't
-- separate goodwill from other intangibles).
CREATE TABLE IF NOT EXISTS goodwill_to_assets_scores (
    sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT,
    goodwill_to_assets REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_gw2assets_date ON goodwill_to_assets_scores(snapshot_date);

-- LT Borrowings / Total Borrowings. Higher = safer debt maturity profile.
CREATE TABLE IF NOT EXISTS debt_structure_scores (
    sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT,
    debt_structure REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_dbtstruct_date ON debt_structure_scores(snapshot_date);

-- Net Block / Total assets. Capital-intensity tag.
CREATE TABLE IF NOT EXISTS asset_tangibility_scores (
    sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT,
    asset_tangibility REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_asstan_date ON asset_tangibility_scores(snapshot_date);

-- ─────────────────────────────────────────────────────────────
-- Sector-narrative-derived factor cluster (plan 0007)
-- ─────────────────────────────────────────────────────────────

-- D: Revenue Volatility (5-year CV) — top-line stability proxy.
CREATE TABLE IF NOT EXISTS revenue_cv_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    revenue_cv_5y   REAL,        -- stdev / |mean| of last 5 YoY growth rates
    mean_growth     REAL,        -- mean of last 5 YoY growth rates
    years_used      INTEGER,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_rev_cv_date ON revenue_cv_scores(snapshot_date);

-- C: Inventory Turnover (sector-relative) — Sales / Inventory.
CREATE TABLE IF NOT EXISTS inventory_turnover_scores (
    sid                 TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date       TEXT NOT NULL,
    period_end          TEXT,
    inventory_turnover  REAL,    -- 3-yr median Sales / Inventory
    sector_p50          REAL,    -- median across sector peers
    relative_turnover   REAL,    -- inventory_turnover / sector_p50
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_inv_turn_date ON inventory_turnover_scores(snapshot_date);

-- B: Sector-Relative Sales Growth.
CREATE TABLE IF NOT EXISTS sales_growth_relative_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    period_end      TEXT,
    sales_growth    REAL,         -- 3-yr median YoY sales growth
    sector_median   REAL,         -- median across sector peers
    relative_growth REAL,         -- sales_growth − sector_median
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_sgr_date ON sales_growth_relative_scores(snapshot_date);

-- A: Market-Share Momentum — Δ market_cap_share within sector, 90-day window.
CREATE TABLE IF NOT EXISTS share_momentum_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    market_cap_cr   REAL,         -- current market cap (₹ × share count, in line-item units)
    sector_share    REAL,         -- share[t]
    share_momentum  REAL,         -- share[t] / share[t-90d] − 1
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_sharemom_date ON share_momentum_scores(snapshot_date);

-- ─────────────────────────────────────────────────────────────
-- Sector Intelligence (plan 0006) — per-sector structured narrative
-- ─────────────────────────────────────────────────────────────

-- Single row per sector. payload is a JSON blob with the IIM-style structure
-- (value chain, drivers, segments, regulators, cyclicality, india_specific,
-- trend_bullets) plus our top-players list (auto-derived from stocks).
-- 'source' is 'auto' (LLM-generated) or 'manual' (user override that wins).
CREATE TABLE IF NOT EXISTS sector_metadata (
    sector          TEXT NOT NULL,        -- GICS sector name (matches stocks.sector)
    industry        TEXT,                 -- IIM industry mapped to this sector
    source          TEXT NOT NULL DEFAULT 'auto' CHECK(source IN ('auto', 'manual')),
    generated_at    TEXT DEFAULT (datetime('now')),
    payload         TEXT NOT NULL,        -- JSON blob, see structure below
    notes           TEXT,                 -- optional free-text on generation run
    PRIMARY KEY (sector, source)
);

-- payload JSON shape:
-- {
--   "summary": "one-sentence sector pitch",
--   "industry_size_inr_cr": <number>,
--   "industry_cagr_pct": <number>,
--   "value_chain": [{"name": "...", "items": ["..."]}, ...],   -- 5 stages
--   "drivers": {
--     "revenue": [{"item": "...", "type": "structural|cyclical|policy"}, ...],
--     "cost":    [{"item": "...", "type": "..."}, ...],
--     "growth":  [{"item": "...", "type": "..."}, ...]
--   },
--   "segments": [{"name": "...", "kpis": [{"name": "...", "formula": "...", "direction": "higher_is_better"}]}, ...],
--   "regulators": [{"body": "...", "what": "..."}, ...],
--   "cyclicality": "...",
--   "india_specific": ["...", "..."],
--   "trend_bullets": {
--     "industry_size":     ["..."],
--     "structural_shifts": ["..."],
--     "regulatory":        ["..."],
--     "headwinds":         ["..."],
--     "india_specific":    ["..."]
--   },
--   "top_players_override": null    -- optional; if set, used instead of derived
-- }

CREATE INDEX IF NOT EXISTS idx_sector_meta_gen ON sector_metadata(generated_at);

-- Run log for the narrative-fetcher cron job
CREATE TABLE IF NOT EXISTS sector_narrative_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT DEFAULT (datetime('now')),
    finished_at     TEXT,
    status          TEXT,                 -- 'SUCCESS' | 'PARTIAL' | 'FAILED'
    sectors_done    INTEGER DEFAULT 0,
    sectors_failed  INTEGER DEFAULT 0,
    api_cost_usd    REAL,
    detail          TEXT
);


-- ──────────────────────────────────────────────────────────────────
-- Plan 0005 Phase A: per-signal eligibility
-- One row per (sid, signal, snapshot_date). `eligible=1` means the SID
-- meets the signal's eligibility SQL (eligibility/registry.py) — it
-- SHOULD have a score. `eligible=0` means the SID is correctly missing
-- (e.g. SMALL cap with no analyst coverage for `consensus`). This lets
-- scoring/screener.py compute `eligible_coverage` distinct from raw
-- `weight_coverage`, and lets cockpit Health Center distinguish
-- "broken" from "expected miss" per signal.
-- ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS universe_eligibility (
    sid             TEXT NOT NULL,
    signal          TEXT NOT NULL,
    snapshot_date   TEXT NOT NULL DEFAULT (date('now')),
    eligible        INTEGER NOT NULL CHECK(eligible IN (0,1)),
    refreshed_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (sid, signal, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_eligibility_signal_date ON universe_eligibility(signal, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_eligibility_date ON universe_eligibility(snapshot_date);


-- ──────────────────────────────────────────────────────────────────
-- Plan 0005 news Phase 2: per-article LLM enrichment
-- One row per news_articles.article_id. Populated by sources/news_classifier.py
-- (Claude Haiku — ~$0.001 per article). Fields lifted from the spec at
-- sources/news_app_build_spec.md. NULL = not yet classified.
-- ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS news_enriched (
    article_id       TEXT PRIMARY KEY REFERENCES news_articles(article_id),
    topics           TEXT,            -- JSON array of topic_ids (e.g. ["ai", "indian_markets"])
    primary_topic    TEXT,            -- single best-match topic, used for filter chips
    one_liner        TEXT,            -- max 20 words, what happened
    why_it_matters   TEXT,            -- max 40 words, the actual implication
    key_numbers      TEXT,            -- JSON array of {label, value} pairs, max 3
    what_to_watch    TEXT,            -- max 30 words, next thing to look for
    confidence       TEXT,            -- "high" | "medium" | "low"
    sentiment        TEXT,            -- "bullish" | "bearish" | "neutral" — market-relevance only
    classifier_status TEXT DEFAULT 'pending',  -- pending | done | failed | skipped
    classified_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_news_enriched_topic ON news_enriched(primary_topic);
CREATE INDEX IF NOT EXISTS idx_news_enriched_status ON news_enriched(classifier_status);

-- Daily news brief — one row per date. Synthesized by sources/news_brief.py
-- via Claude Sonnet from top-N enriched articles. Cron: 04:00 UTC after the
-- per-article classifier completes.
CREATE TABLE IF NOT EXISTS news_briefs (
    brief_date       TEXT PRIMARY KEY,
    big_one          TEXT NOT NULL,    -- THE BIG ONE — single most important story (60w)
    five_fast        TEXT NOT NULL,    -- FIVE FAST — JSON array of 5 items (20w each)
    one_to_watch     TEXT,             -- ONE TO WATCH — forming story (40w)
    zoom_out         TEXT,             -- ZOOM OUT — connect today to larger pattern (50w)
    n_articles_used  INTEGER,
    generated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Mutual Fund research universe (plan: prfect-lets-add-a-zazzy-eich, 2026-05-26) ──
-- Standalone research interface covering all ~4,048 active Indian MF schemes.
-- Universe + daily NAV from AMFI NAVAll.txt; full historical NAV from mfapi.in.
-- Metrics + scorer computed monthly. See cockpit page /mutual-funds.

-- AMFI scheme master — authoritative ~4,048 schemes (weekly refresh)
CREATE TABLE IF NOT EXISTS mf_scheme_master (
    scheme_code      TEXT PRIMARY KEY,
    isin_growth      TEXT,
    isin_div         TEXT,
    scheme_name      TEXT NOT NULL,
    amc              TEXT,                        -- fund house (e.g. "HDFC Mutual Fund")
    category_raw     TEXT,                        -- AMFI/SEBI category string as-fetched
    category_norm    TEXT,                        -- our normalised label (e.g. "Equity / Multi Cap")
    sub_category     TEXT,
    plan_type        TEXT CHECK (plan_type IN ('DIRECT','REGULAR','UNKNOWN')),
    option_type      TEXT CHECK (option_type IN ('GROWTH','IDCW','UNKNOWN')),
    inception_date   TEXT,                        -- when fetchable from mfapi.in
    aum_cr           REAL,                        -- ₹ crore (NULL in v1 — needs VRO/Groww in v2)
    expense_ratio    REAL,                        -- pct (NULL in v1)
    benchmark        TEXT,                        -- e.g. "Nifty 50 TRI"
    last_seen        TEXT,                        -- date this scheme last appeared in NAVAll.txt
    active           INTEGER DEFAULT 1,
    fetched_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_mf_master_amc      ON mf_scheme_master(amc);
CREATE INDEX IF NOT EXISTS idx_mf_master_cat      ON mf_scheme_master(category_norm);
CREATE INDEX IF NOT EXISTS idx_mf_master_plan     ON mf_scheme_master(plan_type, option_type);
CREATE INDEX IF NOT EXISTS idx_mf_master_active   ON mf_scheme_master(active);

-- Point-in-time returns + risk snapshot per scheme — recomputed monthly
CREATE TABLE IF NOT EXISTS mf_metrics (
    scheme_code             TEXT NOT NULL,
    as_of_date              TEXT NOT NULL,
    nav                     REAL,
    nav_date                TEXT,
    ret_1m                  REAL,
    ret_3m                  REAL,
    ret_6m                  REAL,
    ret_1y                  REAL,
    ret_3y_cagr             REAL,
    ret_5y_cagr             REAL,
    ret_10y_cagr            REAL,
    ret_since_inception_cagr REAL,
    std_1y                  REAL,
    std_3y                  REAL,
    sharpe_1y               REAL,
    sharpe_3y               REAL,
    sortino_1y              REAL,
    max_drawdown            REAL,                 -- negative %
    max_dd_start            TEXT,
    max_dd_end              TEXT,
    recovery_days           INTEGER,
    bench_spread_1y         REAL,                 -- ret_1y - benchmark_1y
    bench_spread_3y         REAL,
    peer_rank_1y            INTEGER,
    peer_rank_3y            INTEGER,
    peer_count              INTEGER,
    composite_score         REAL,                 -- 0-100 within category
    score_percentile        REAL,                 -- 0-100 percentile within category
    score_3y_cagr_pct       REAL,                 -- breakdown: each component's percentile
    score_sharpe_3y_pct     REAL,
    score_max_dd_pct        REAL,
    score_consistency_pct   REAL,
    PRIMARY KEY (scheme_code, as_of_date)
);
CREATE INDEX IF NOT EXISTS idx_mf_metrics_score ON mf_metrics(composite_score DESC);
CREATE INDEX IF NOT EXISTS idx_mf_metrics_asof ON mf_metrics(as_of_date);

-- Per-scheme calendar-year returns (for the bar chart on detail page)
CREATE TABLE IF NOT EXISTS mf_calendar_returns (
    scheme_code   TEXT NOT NULL,
    year          INTEGER NOT NULL,
    ret_pct       REAL,
    bench_ret_pct REAL,
    PRIMARY KEY (scheme_code, year)
);

-- Per-scheme rolling 3Y/5Y CAGR sampled monthly (rolling-return chart + consistency scorer)
CREATE TABLE IF NOT EXISTS mf_rolling_returns (
    scheme_code                 TEXT NOT NULL,
    anchor_date                 TEXT NOT NULL,    -- first business day of each month
    rolling_3y_cagr             REAL,
    rolling_5y_cagr             REAL,
    rolling_3y_beats_category   INTEGER,          -- 1 if rolling > category median for that anchor; 0 if <=; NULL if N/A
    rolling_5y_beats_category   INTEGER,
    PRIMARY KEY (scheme_code, anchor_date)
);
CREATE INDEX IF NOT EXISTS idx_mf_rolling_sid ON mf_rolling_returns(scheme_code);

-- Category aggregates for ranking + heatmap
CREATE TABLE IF NOT EXISTS mf_category_stats (
    category_norm     TEXT NOT NULL,
    as_of_date        TEXT NOT NULL,
    scheme_count      INTEGER,
    median_ret_1y     REAL,
    median_ret_3y     REAL,
    median_ret_5y     REAL,
    median_sharpe_1y  REAL,
    median_std_1y     REAL,
    top_decile_ret_1y REAL,
    bot_decile_ret_1y REAL,
    PRIMARY KEY (category_norm, as_of_date)
);

-- Per-scheme portfolio holdings (Phase 4c — schema ready, ingest deferred).
-- Top stocks + sector allocation per scheme from AMFI monthly disclosures.
-- AMFI publishes monthly portfolio disclosures (~45-day lag) at
-- amfiindia.com/research-information/other-data — page is JS-rendered, per-AMC
-- XLSX downloads. Full automated ingest needs per-AMC parsers (~50 AMCs).
-- Schema lands now so the UI tab can render "—" placeholders cleanly.
CREATE TABLE IF NOT EXISTS mf_holdings (
    scheme_code     TEXT NOT NULL,
    as_of_date      TEXT NOT NULL,   -- disclosure month-end
    holding_rank    INTEGER NOT NULL,
    instrument_type TEXT,             -- 'EQUITY' / 'DEBT' / 'CASH' / 'OTHER'
    sid             TEXT,             -- our stocks.sid if equity holding (NULLABLE — best-effort match)
    isin            TEXT,
    instrument_name TEXT NOT NULL,
    sector          TEXT,
    pct_of_aum      REAL,
    market_value_cr REAL,
    PRIMARY KEY (scheme_code, as_of_date, holding_rank)
);
CREATE INDEX IF NOT EXISTS idx_mf_holdings_scheme ON mf_holdings(scheme_code);
CREATE INDEX IF NOT EXISTS idx_mf_holdings_sid    ON mf_holdings(sid);

-- Per-scheme sector allocation rollup (derived from mf_holdings or AMC disclosure)
CREATE TABLE IF NOT EXISTS mf_sector_allocation (
    scheme_code  TEXT NOT NULL,
    as_of_date   TEXT NOT NULL,
    sector       TEXT NOT NULL,
    pct_of_aum   REAL NOT NULL,
    PRIMARY KEY (scheme_code, as_of_date, sector)
);

-- ── Paper portfolio — realized-return loop (plan 0005 Phase F+, 2026-05-25) ──
-- The bridge between "we publish daily picks" and "did this make money?".
-- Forward-tracking + historical backfill from existing daily_picks. Once these
-- prove out, the same plumbing wires into Kite Connect for live trading.
-- See docs/decisions/0028-paper-portfolio-realized-return-loop.md.

CREATE TABLE IF NOT EXISTS paper_positions (
    position_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    sid              TEXT NOT NULL,
    cap_tier         TEXT NOT NULL,
    sector           TEXT,
    entry_date       TEXT NOT NULL,      -- when the position was opened
    entry_price      REAL NOT NULL,
    entry_weight_pct REAL NOT NULL,      -- target weight at entry (% of NAV)
    qty              REAL NOT NULL,      -- shares (fractional allowed for paper)
    exit_date        TEXT,               -- NULL while open
    exit_price       REAL,
    rank_at_entry    INTEGER,
    score_at_entry   REAL,
    status           TEXT NOT NULL CHECK (status IN ('OPEN','CLOSED'))
);
CREATE INDEX IF NOT EXISTS idx_paper_positions_status ON paper_positions(status);
CREATE INDEX IF NOT EXISTS idx_paper_positions_sid ON paper_positions(sid);

CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date       TEXT NOT NULL,
    sid              TEXT NOT NULL,
    side             TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    qty              REAL NOT NULL,
    price            REAL NOT NULL,      -- executed at this price (next-day open in paper)
    gross_value      REAL NOT NULL,      -- qty * price
    cost_bps         REAL NOT NULL,      -- from config.TRANSACTION_COSTS_BPS by tier
    cost_amount      REAL NOT NULL,
    net_value        REAL NOT NULL,      -- gross +/- cost
    reason           TEXT NOT NULL,      -- INITIAL / NEW_PICK / EXIT_DROPPED / EXIT_SECTOR_CAP / EXIT_FORCED
    position_id      INTEGER REFERENCES paper_positions(position_id),
    rebalance_date   TEXT                -- the Friday whose picks drove this trade
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_date ON paper_trades(trade_date);
CREATE INDEX IF NOT EXISTS idx_paper_trades_sid ON paper_trades(sid);

CREATE TABLE IF NOT EXISTS paper_nav_history (
    nav_date              TEXT PRIMARY KEY,
    nav                   REAL NOT NULL,          -- mark-to-market portfolio value INR
    cash                  REAL NOT NULL,          -- uninvested cash
    n_positions           INTEGER NOT NULL,
    daily_return_pct      REAL,                   -- vs prior nav
    cumulative_return_pct REAL,                   -- vs initial 10L
    drawdown_pct          REAL,                   -- from running peak
    benchmark_nav         REAL,                   -- Nifty50 baseline starting at same capital
    benchmark_cumret      REAL,
    spread_vs_benchmark   REAL                    -- alpha proxy
);
CREATE INDEX IF NOT EXISTS idx_paper_nav_date ON paper_nav_history(nav_date);

-- ── Per-stock data lineage (plan 0005 Phase F, 2026-05-25) ──
-- For any (sid, factor, date), points at the exact source rows that contributed.
-- Emitted by each signal module's _compute_scores via db._emit_lineage().
-- Gated by lineage.lineage_active_sids() (default top-300 from daily_picks).
-- Static lineage (declarative) lives in lineage.FACTOR_LINEAGE.
-- See docs/decisions/0027-per-stock-data-lineage.md.
CREATE TABLE IF NOT EXISTS signal_lineage (
    sid              TEXT NOT NULL,
    snapshot_date    TEXT NOT NULL,
    factor           TEXT NOT NULL,         -- canonical factor name (matches db.BACKTEST_SIGNALS.signal)
    source_table     TEXT NOT NULL,
    source_key       TEXT NOT NULL,         -- JSON dict {col: value} identifying source row(s)
    source_cols      TEXT,                  -- JSON list of cols read from this source row
    column_sources   TEXT,                  -- JSON {col: feed} for mixed-source tables; NULL otherwise
    contribution     TEXT,                  -- role label (ltm_y0 / latest / pt_upside_anchor / ...)
    PRIMARY KEY (sid, snapshot_date, factor, source_table, source_key, contribution)
);
CREATE INDEX IF NOT EXISTS idx_lineage_sid_factor ON signal_lineage(sid, factor);
CREATE INDEX IF NOT EXISTS idx_lineage_snapshot ON signal_lineage(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_lineage_source_table ON signal_lineage(source_table);
