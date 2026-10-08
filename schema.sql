-- Alpha Signal v2 — Database Schema
--
-- GENERATED from the live DB's schema (sqlite3 -readonly data/alpha_signal.db .schema),
-- sqlite_* internals excluded, CREATE statements made IF NOT EXISTS. One block per
-- table (tables alphabetical, indexes after their table).
--
-- This file is the canonical DDL: db.init_db() executes it and then applies
-- db._COLUMN_MIGRATIONS (columns added to existing DBs after this snapshot) and
-- db._ensure_quarantine_tables(). When you add a table or column, add it HERE too
-- (and to _COLUMN_MIGRATIONS for a column on an existing table) — a DB rebuilt from
-- this file must match the live one table-for-table, column-for-column.
-- 134 tables. Snapshot 2026-09-26.

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
, price_target_median REAL, price_target_high REAL, price_target_low REAL, recommendation_key TEXT, recommendation_mean REAL, n_strong_buy INTEGER, n_buy INTEGER, n_hold INTEGER, n_sell INTEGER, n_strong_sell INTEGER, pt_source TEXT, next_earnings_date TEXT, rating_mix_history TEXT, price_target_prev REAL, price_target_changed_at TEXT);

CREATE TABLE IF NOT EXISTS analyst_consensus_quarantine (
    sid             TEXT,
    total_analysts  INTEGER,
    buy_pct         REAL,
    price_target    REAL,
    forward_eps     REAL,
    eps_growth_pct  REAL,
    forward_revenue REAL,
    revenue_growth_pct REAL,
    has_analyst_data INTEGER DEFAULT 1,
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now'))
, price_target_median REAL, price_target_high REAL, price_target_low REAL, recommendation_key TEXT, recommendation_mean REAL, n_strong_buy INTEGER, n_buy INTEGER, n_hold INTEGER, n_sell INTEGER, n_strong_sell INTEGER, pt_source TEXT, next_earnings_date TEXT, rating_mix_history TEXT, price_target_prev REAL, price_target_changed_at TEXT, _q_failed_gate TEXT, _q_reason TEXT, _q_quarantined_at TEXT DEFAULT (datetime('now')));

CREATE TABLE IF NOT EXISTS analyst_consensus_snapshots (
            sid                 TEXT NOT NULL REFERENCES stocks(sid),
            snapshot_date       TEXT NOT NULL,          -- 1st business day of the month
            source              TEXT NOT NULL,          -- 'yfinance' / 'tickertape' / 'moneycontrol'
            target_mean         REAL,
            target_median       REAL,
            target_high         REAL,
            target_low          REAL,
            n_analysts          INTEGER,
            recommendation_key  TEXT,
            recommendation_mean REAL,
            fetched_at          TEXT,
            PRIMARY KEY (sid, snapshot_date, source)
        );
CREATE INDEX IF NOT EXISTS idx_acs_date ON analyst_consensus_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_acs_sid ON analyst_consensus_snapshots(sid);

CREATE TABLE IF NOT EXISTS analyst_consensus_snapshots_quarantine (
            sid                 TEXT NOT NULL,
            snapshot_date       TEXT NOT NULL,          -- 1st business day of the month
            source              TEXT NOT NULL,          -- 'yfinance' / 'tickertape' / 'moneycontrol'
            target_mean         REAL,
            target_median       REAL,
            target_high         REAL,
            target_low          REAL,
            n_analysts          INTEGER,
            recommendation_key  TEXT,
            recommendation_mean REAL,
            fetched_at          TEXT
        , _q_failed_gate TEXT, _q_reason TEXT, _q_quarantined_at TEXT DEFAULT (datetime('now')));

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

CREATE TABLE IF NOT EXISTS annual_balance_sheet_quarantine (
    sid             TEXT NOT NULL,
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
    fetched_at      TEXT DEFAULT (datetime('now'))
, _q_failed_gate TEXT, _q_reason TEXT, _q_quarantined_at TEXT DEFAULT (datetime('now')));

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
    dividends_paid  REAL,
    net_change_in_cash REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, period)
);

CREATE TABLE IF NOT EXISTS annual_cash_flow_quarantine (
    sid             TEXT NOT NULL,
    period          TEXT NOT NULL,
    end_date        TEXT,
    operating_cash_flow REAL,
    capex           REAL,
    free_cash_flow  REAL,
    investing_cash_flow REAL,
    financing_cash_flow REAL,
    working_capital_change REAL,
    dividends_paid  REAL,
    net_change_in_cash REAL,
    fetched_at      TEXT DEFAULT (datetime('now'))
, _q_failed_gate TEXT, _q_reason TEXT, _q_quarantined_at TEXT DEFAULT (datetime('now')));

CREATE TABLE IF NOT EXISTS asset_tangibility_scores (sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT, asset_tangibility REAL, PRIMARY KEY (sid, snapshot_date));
CREATE INDEX IF NOT EXISTS idx_asstan_date ON asset_tangibility_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS banking_metrics (
    sid                      TEXT NOT NULL,
    period_end               TEXT NOT NULL,
    period_type              TEXT NOT NULL,
    interest_earned          REAL,
    interest_expended        REAL,
    net_interest_income      REAL,
    other_income             REAL,
    provisions               REAL,
    pre_provision_op_profit  REAL,
    net_profit               REAL,
    gross_npa_pct            REAL,
    net_npa_pct              REAL,
    pcr_pct                  REAL,
    slippage_pct             REAL,
    credit_cost_pct          REAL,
    advances                 REAL,
    deposits                 REAL,
    borrowings               REAL,
    book_value_per_share     REAL,
    casa_pct                 REAL,
    car_pct                  REAL,
    crar_pct                 REAL,
    nim_pct                  REAL,
    roa_pct                  REAL,
    cost_of_funds_pct        REAL,
    adj_book_per_share       REAL,
    source                   TEXT NOT NULL DEFAULT 'screener_in',
    fetched_at               TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, period_end, period_type)
);
CREATE INDEX IF NOT EXISTS idx_banking_metrics_period ON banking_metrics(period_end);
CREATE INDEX IF NOT EXISTS idx_banking_metrics_sid    ON banking_metrics(sid);

CREATE TABLE IF NOT EXISTS banking_metrics_quarantine (
    sid                      TEXT NOT NULL,
    period_end               TEXT NOT NULL,
    period_type              TEXT NOT NULL,
    interest_earned          REAL,
    interest_expended        REAL,
    net_interest_income      REAL,
    other_income             REAL,
    provisions               REAL,
    pre_provision_op_profit  REAL,
    net_profit               REAL,
    gross_npa_pct            REAL,
    net_npa_pct              REAL,
    pcr_pct                  REAL,
    slippage_pct             REAL,
    credit_cost_pct          REAL,
    advances                 REAL,
    deposits                 REAL,
    borrowings               REAL,
    book_value_per_share     REAL,
    casa_pct                 REAL,
    car_pct                  REAL,
    crar_pct                 REAL,
    nim_pct                  REAL,
    roa_pct                  REAL,
    cost_of_funds_pct        REAL,
    adj_book_per_share       REAL,
    source                   TEXT NOT NULL DEFAULT 'screener_in',
    fetched_at               TEXT DEFAULT (datetime('now'))
, _q_failed_gate TEXT, _q_reason TEXT, _q_quarantined_at TEXT DEFAULT (datetime('now')));

CREATE TABLE IF NOT EXISTS broker_recommendations (
    sid              TEXT NOT NULL REFERENCES stocks(sid),
    broker           TEXT NOT NULL,
    reco_date        TEXT NOT NULL,          -- ISO date the broker published
    reco_type        TEXT,                   -- BUY / HOLD / SELL / ACCUMULATE / REDUCE / NEUTRAL
    reco_price       REAL,                   -- price when call was made
    target_price     REAL NOT NULL,          -- the analyst target
    report_url       TEXT,                   -- PDF link if any
    fetched_at       TEXT,
    reco_date_imputed INTEGER,
    PRIMARY KEY (sid, broker, reco_date, target_price)
);
CREATE INDEX IF NOT EXISTS idx_brec_date ON broker_recommendations(reco_date);
CREATE INDEX IF NOT EXISTS idx_brec_sid ON broker_recommendations(sid);

CREATE TABLE IF NOT EXISTS broker_recommendations_quarantine (
    sid              TEXT NOT NULL,
    broker           TEXT NOT NULL,
    reco_date        TEXT NOT NULL,          -- ISO date the broker published
    reco_type        TEXT,                   -- BUY / HOLD / SELL / ACCUMULATE / REDUCE / NEUTRAL
    reco_price       REAL,                   -- price when call was made
    target_price     REAL NOT NULL,          -- the analyst target
    report_url       TEXT,                   -- PDF link if any
    fetched_at       TEXT,
    reco_date_imputed INTEGER
, _q_failed_gate TEXT, _q_reason TEXT, _q_quarantined_at TEXT DEFAULT (datetime('now')));

CREATE TABLE IF NOT EXISTS bse_announcements (
    news_id           TEXT PRIMARY KEY,   -- BSE NEWSID (stable unique announcement id)
    scrip_cd          INTEGER NOT NULL,   -- BSE scrip code (→ universe via deferred scrip-master map)
    sid               TEXT,               -- our universe SID, NULL until mapping built
    company_name      TEXT,               -- SLONGNAME (also enables name-match fallback)
    headline          TEXT,               -- HEADLINE
    news_sub          TEXT,               -- NEWSSUB (subject)
    category          TEXT,               -- CATEGORYNAME  (Result / Board Meeting / Company Update / ...)
    subcategory       TEXT,               -- SUBCATNAME    (Credit Rating / Pledge / Resignation / Buyback / ...)
    announcement_type TEXT,               -- ANNOUNCEMENT_TYPE
    critical_news     INTEGER,            -- CRITICALNEWS (BSE materiality flag)
    dt_tm             TEXT,               -- DT_TM  (announcement timestamp — look-ahead-safe event time)
    submission_dt     TEXT,               -- News_submission_dt
    dissem_dt         TEXT,               -- DissemDT (public dissemination time)
    time_diff         TEXT,               -- TimeDiff (submission→dissemination latency = governance signal)
    quarter_id        TEXT,               -- QUARTER_ID (links result filings to fiscal quarter)
    attachment        TEXT,               -- ATTACHMENTNAME (PDF GUID → corpfiling/AttachLive|AttachHis)
    pdf_flag          INTEGER,            -- PDFFLAG
    has_investor_ppt  INTEGER,            -- Investor_Presentation present
    has_audio_video   INTEGER,            -- AUDIO_VIDEO_FILE present
    nsurl             TEXT,               -- NSURL (BSE detail page slug)
    fetched_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bse_ann_cat   ON bse_announcements(category, subcategory);
CREATE INDEX IF NOT EXISTS idx_bse_ann_scrip ON bse_announcements(scrip_cd, dt_tm);
CREATE INDEX IF NOT EXISTS idx_bse_ann_sid   ON bse_announcements(sid, dt_tm);

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

CREATE TABLE IF NOT EXISTS capex_to_dep_scores (sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT, capex_to_dep REAL, PRIMARY KEY (sid, snapshot_date));
CREATE INDEX IF NOT EXISTS idx_capdep_date ON capex_to_dep_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS cash_conversion_cycle_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    period_end      TEXT,
    dso             REAL,
    dio             REAL,
    dpo             REAL,
    ccc             REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_ccc_date ON cash_conversion_cycle_scores(snapshot_date);

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

CREATE TABLE IF NOT EXISTS consensus_signals_quarantine (
    sid             TEXT NOT NULL,
    snapshot_date   TEXT NOT NULL,
    pt_upside       REAL,
    pt_revision_1yr REAL,
    eps_growth      REAL,
    revenue_growth  REAL,
    consensus_signal REAL
, _q_failed_gate TEXT, _q_reason TEXT, _q_quarantined_at TEXT DEFAULT (datetime('now')));

CREATE TABLE IF NOT EXISTS corporate_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sid TEXT REFERENCES stocks(sid),
    symbol TEXT NOT NULL,
    series TEXT,
    ind TEXT,             -- action type: SPLIT, BONUS, DIVIDEND, RIGHTS, etc.
    face_value REAL,
    subject TEXT,         -- raw description (e.g. "Stock Split From Rs.10/- to Rs.5/-")
    ex_date TEXT NOT NULL,
    fetched_at TEXT DEFAULT (datetime('now')),
    UNIQUE(symbol, ex_date, subject)
);
CREATE INDEX IF NOT EXISTS idx_ca_exdate ON corporate_actions(ex_date);
CREATE INDEX IF NOT EXISTS idx_ca_ind ON corporate_actions(ind);
CREATE INDEX IF NOT EXISTS idx_ca_sid ON corporate_actions(sid);

CREATE TABLE IF NOT EXISTS corporate_adjustments (
                sid TEXT NOT NULL,
                ex_date TEXT NOT NULL,
                factor REAL NOT NULL,         -- combined multiplier for PRE-ex_date prices (< 1)
                n_events INTEGER NOT NULL,    -- number of events composed (1 typical, 2 same-day)
                inds TEXT NOT NULL,           -- comma-joined event types: SPLIT,BONUS,DIVIDEND
                subjects TEXT,                -- concatenated raw subjects (truncated)
                fetched_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (sid, ex_date)
            );

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
    sector          TEXT, weight_coverage REAL, price_rows INTEGER, fundamental_coverage REAL, eligible_coverage REAL, integrity_status TEXT, integrity_reasons TEXT, uhs_score INTEGER, uhs_breakdown_json TEXT, uhs_label TEXT, uhs_worst_dim TEXT,
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

CREATE TABLE IF NOT EXISTS daily_snapshots_pit (
    sid              TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date    TEXT NOT NULL,
    cap_tier         TEXT,
    close_price      REAL,
    piotroski_f      INTEGER,
    cf_accruals      REAL,
    bs_accruals      REAL,
    earnings_persistence REAL,
    earnings_yield   REAL,
    book_to_price    REAL,
    promoter_qoq     REAL,
    mom_6m           REAL,
    mom_12m          REAL,
    m_score          REAL,
    z_score          REAL,
    reconstructed_at TEXT DEFAULT (datetime('now')), promoter_trend_4q REAL, pledge_quality REAL, mom_composite REAL, macd_bullish INTEGER, position_52w REAL, avg_delivery_pct_30d REAL, delivery_anomaly_z REAL, fwd_return_20d REAL, roe REAL, roa REAL, debt_to_equity REAL, profit_margin REAL, revenue_growth_yoy REAL, eps_growth_yoy REAL, pt_revision_yoy REAL, eps_revision_yoy REAL, consensus_signal_combined REAL, value_composite REAL, quality_composite REAL, growth_composite REAL, pt_upside REAL, bulk_deal_signal REAL, short_selling_signal REAL, earnings_beat_rate REAL, news_volume_7d REAL, revenue_cv_5y REAL, relative_turnover REAL, relative_growth REAL, share_momentum REAL, ccc REAL, margin_slope REAL, wc_intensity REAL, interest_coverage REAL, roic REAL, fcf_yield REAL, roiic REAL, dso_change_yoy REAL, dio_change_yoy REAL, nwc_to_revenue REAL, sloan_accruals_full REAL, sga_to_revenue_change REAL, fcf_margin REAL, capex_to_dep REAL, goodwill_to_assets REAL, debt_structure REAL, asset_tangibility REAL, insider_score REAL, sentiment_7d REAL, accruals_signal REAL, promoter_signal REAL, forensic_penalty REAL, smart_money_score REAL, financial_signal REAL, financial_quality REAL, financial_recovery REAL, sector_momentum REAL, pcr_oi REAL, pcr_volume REAL, max_pain_distance REAL, oi_buildup_signal REAL, iv_skew_25d REAL, iv_term_structure REAL, iv_realised_spread REAL, iv_percentile_1y REAL, intraday_range_compression REAL, closing_strength_1m REAL, opening_gap_freq_1m REAL, vwap_deviation_5d REAL, bidask_spread_proxy REAL, kyle_lambda REAL, earnings_surprise_std REAL, pead_drift_60d REAL, corporate_action_density REAL, buyback_announcement_30d REAL, industry_id INTEGER, oil_beta REAL, metals_beta REAL, inr_beta REAL, gold_beta REAL, gross_profitability REAL, sector_tilt REAL, rate_beta REAL, credit_beta REAL, governance_resignation REAL, earnings_call_tone_qoq REAL, forward_looking_intensity REAL, uncertainty_word_density REAL, low_vol_252d REAL, st_reversal_21d REAL, asset_growth_yoy REAL, announcement_car REAL, residual_momentum_12_1 REAL, max_lottery_21d REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_pit_date ON daily_snapshots_pit(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_pit_tier ON daily_snapshots_pit(cap_tier);

CREATE TABLE IF NOT EXISTS daily_snapshots_pit_v1 (
    sid                  TEXT NOT NULL,
    snapshot_date        TEXT NOT NULL,
    ticker               TEXT,
    cap_tier             TEXT,
    sector               TEXT,
    price                REAL,
    fwd_return_20d       REAL,
    piotroski_f          INTEGER,
    cf_accruals          REAL,
    bs_accruals          REAL,
    eps_cv               REAL,
    earnings_beat_rate   REAL,
    book_to_price        REAL,
    earnings_yield       REAL,
    mom_6m               REAL,
    mom_12m              REAL,
    promoter_qoq         REAL,
    pledge_quality       REAL,
    avg_delivery_pct_30d REAL,
    imported_at          TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_pit_v1_date ON daily_snapshots_pit_v1(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_pit_v1_tier ON daily_snapshots_pit_v1(cap_tier);

CREATE TABLE IF NOT EXISTS debt_structure_scores (sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT, debt_structure REAL, PRIMARY KEY (sid, snapshot_date));
CREATE INDEX IF NOT EXISTS idx_dbtstruct_date ON debt_structure_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS dio_change_yoy_scores (sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT, dio_change_yoy REAL, PRIMARY KEY (sid, snapshot_date));
CREATE INDEX IF NOT EXISTS idx_dioyoy_date ON dio_change_yoy_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS dso_change_yoy_scores (sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT, dso_change_yoy REAL, PRIMARY KEY (sid, snapshot_date));
CREATE INDEX IF NOT EXISTS idx_dsoyoy_date ON dso_change_yoy_scores(snapshot_date);

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

CREATE TABLE IF NOT EXISTS event_calendar (
    sid TEXT, event_type TEXT, event_subtype TEXT, announce_date TEXT,
    record_date TEXT, source TEXT, loaded_at TEXT,
    PRIMARY KEY (sid, event_type, announce_date)
);

CREATE TABLE IF NOT EXISTS external_anchors (
    datum_class       TEXT NOT NULL,         -- close / volume / delivery_pct / mf_ret_1y / mf_ret_3y_cagr
    sid_or_segment    TEXT NOT NULL,         -- stocks.sid OR mf_scheme_master.scheme_code
    anchor_value      REAL,
    anchor_source     TEXT NOT NULL,         -- 'nse_bhavcopy' | 'bse_manual' | 'amc_factsheet'
    anchor_date       TEXT NOT NULL,
    notes             TEXT,
    fetched_at        TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (datum_class, sid_or_segment, anchor_source, anchor_date)
);
CREATE INDEX IF NOT EXISTS idx_external_anchors_class ON external_anchors(datum_class, anchor_date);
CREATE INDEX IF NOT EXISTS idx_external_anchors_date ON external_anchors(anchor_date);

CREATE TABLE IF NOT EXISTS factor_horizon_gate (
    signal TEXT NOT NULL, cap_tier TEXT NOT NULL, source TEXT, cadence TEXT,
    natural_horizon INTEGER, gross_ic REAL, gross_t REAL, sigma_fwd REAL,
    cost_ic REAL, net_ic REAL, net_t REAL, net_ir_annual REAL, n_periods INTEGER,
    sign_stable INTEGER, turnover_assumed REAL, is_live INTEGER, verdict TEXT,
    ir_curve_json TEXT, computed_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (signal, cap_tier)
);

CREATE TABLE IF NOT EXISTS fcf_margin_scores (sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT, fcf_margin REAL, PRIMARY KEY (sid, snapshot_date));
CREATE INDEX IF NOT EXISTS idx_fcfmargin_date ON fcf_margin_scores(snapshot_date);

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

CREATE TABLE IF NOT EXISTS fii_dii_cash_flow (
    flow_date TEXT NOT NULL,
    category TEXT NOT NULL,        -- 'FII' or 'DII'
    buy_value_cr REAL,
    sell_value_cr REAL,
    net_value_cr REAL,
    fetched_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (flow_date, category)
);
CREATE INDEX IF NOT EXISTS idx_fii_cash_date ON fii_dii_cash_flow(flow_date);

CREATE TABLE IF NOT EXISTS fii_dii_positioning (
    trade_date TEXT NOT NULL,
    client_type TEXT NOT NULL,
    future_index_long INTEGER,
    future_index_short INTEGER,
    future_stock_long INTEGER,
    future_stock_short INTEGER,
    option_index_call_long INTEGER,
    option_index_put_long INTEGER,
    option_index_call_short INTEGER,
    option_index_put_short INTEGER,
    option_stock_call_long INTEGER,
    option_stock_put_long INTEGER,
    option_stock_call_short INTEGER,
    option_stock_put_short INTEGER,
    total_long INTEGER,
    total_short INTEGER,
    fetched_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (trade_date, client_type)
);
CREATE INDEX IF NOT EXISTS idx_fii_pos_date ON fii_dii_positioning(trade_date);

CREATE TABLE IF NOT EXISTS financial_signal_scores (
    sid                 TEXT NOT NULL,
    snapshot_date       TEXT NOT NULL,
    industry            TEXT,
    cap_tier            TEXT,
    asset_quality_z     REAL,
    profitability_z     REAL,
    capital_z           REAL,
    funding_z           REAL,
    components_present  INTEGER,
    score_basis         TEXT,
    financial_signal    REAL,
    gross_npa_pct       REAL,
    net_npa_pct         REAL,
    nii_margin_pct      REAL,
    np_margin_pct       REAL,
    cost_of_funds_pct   REAL,
    computed_at         TEXT DEFAULT (datetime('now')), financial_quality REAL, financial_recovery REAL, quality_basis TEXT, recovery_basis TEXT, asset_quality_quality_z REAL, asset_quality_recovery_z REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_financial_signal_date ON financial_signal_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS fno_bhav (
    sid               TEXT,                         -- mapped from TckrSymb; NULL for indices
    symbol            TEXT NOT NULL,                -- TckrSymb (NSE underlying)
    instrument_type   TEXT NOT NULL,                -- STO/IDO (option) · STF/IDF (future)
    expiry_date       TEXT NOT NULL,                -- ISO
    strike            REAL NOT NULL DEFAULT 0,      -- 0 for futures
    option_type       TEXT NOT NULL DEFAULT 'XX',   -- CE/PE; XX for futures
    trade_date        TEXT NOT NULL,                -- ISO
    close             REAL,                         -- ClsPric
    settle            REAL,                         -- SttlmPric
    underlying_price  REAL,                         -- UndrlygPric (spot)
    oi                INTEGER,                      -- OpnIntrst
    chg_oi            INTEGER,                      -- ChngInOpnIntrst
    volume            INTEGER,                      -- TtlTradgVol
    num_trades        INTEGER,                      -- TtlNbOfTxsExctd
    fetched_at        TEXT DEFAULT (datetime('now')),
    UNIQUE(symbol, instrument_type, expiry_date, strike, option_type, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_fno_bhav_date ON fno_bhav(trade_date);
CREATE INDEX IF NOT EXISTS idx_fno_bhav_sid_date ON fno_bhav(sid, trade_date);

CREATE TABLE IF NOT EXISTS fno_iv_history (
        sid TEXT, symbol TEXT NOT NULL, trade_date TEXT NOT NULL,
        target_expiry TEXT, days_to_target INTEGER, forward REAL,
        atm_iv REAL, iv_skew_25d REAL, iv_term_structure REAL,
        n_strikes INTEGER, computed_at TEXT DEFAULT (datetime('now')),
        UNIQUE(symbol, trade_date));
CREATE INDEX IF NOT EXISTS idx_fno_iv_sid_date ON fno_iv_history(sid, trade_date);

CREATE TABLE IF NOT EXISTS fno_pcr_history (
    sid               TEXT,
    symbol            TEXT NOT NULL,
    trade_date        TEXT NOT NULL,
    expiry_date       TEXT,                         -- nearest expiry used
    underlying_price  REAL,
    total_call_oi     INTEGER,
    total_put_oi      INTEGER,
    pcr_oi            REAL,                          -- put_oi / call_oi
    total_call_vol    INTEGER,
    total_put_vol     INTEGER,
    pcr_volume        REAL,                          -- put_vol / call_vol
    max_pain          REAL,                          -- argmin writer-payout strike
    max_pain_distance REAL,                          -- (spot - max_pain) / spot
    n_strikes         INTEGER,
    computed_at       TEXT DEFAULT (datetime('now')),
    UNIQUE(symbol, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_fno_pcr_sid_date ON fno_pcr_history(sid, trade_date);

CREATE TABLE IF NOT EXISTS forecast_history (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    metric          TEXT NOT NULL,
    date            TEXT NOT NULL,
    value           REAL,
    change          REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, metric, date)
);

CREATE TABLE IF NOT EXISTS forecast_history_quarantine (
    sid             TEXT NOT NULL,
    metric          TEXT NOT NULL,
    date            TEXT NOT NULL,
    value           REAL,
    change          REAL,
    fetched_at      TEXT DEFAULT (datetime('now'))
, _q_failed_gate TEXT, _q_reason TEXT, _q_quarantined_at TEXT DEFAULT (datetime('now')));

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
CREATE INDEX IF NOT EXISTS idx_fund_screener_item ON fundamentals_screener(line_item);
CREATE INDEX IF NOT EXISTS idx_fund_screener_sid ON fundamentals_screener(sid);

CREATE TABLE IF NOT EXISTS goodwill_to_assets_scores (sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT, goodwill_to_assets REAL, PRIMARY KEY (sid, snapshot_date));
CREATE INDEX IF NOT EXISTS idx_gw2assets_date ON goodwill_to_assets_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS gross_profitability_scores (
    sid                  TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date        TEXT NOT NULL,
    period_end           TEXT,                    -- latest annual period used
    gross_profit         REAL,                    -- ₹ cr, 3y median
    total_assets         REAL,                    -- ₹ cr, 3y median
    gross_profitability  REAL,                    -- Gross Profit / Total Assets
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_gross_profitability_date ON gross_profitability_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS health_score (
    entity_kind       TEXT NOT NULL,         -- datum | factor | pick | table | system
    entity_id         TEXT NOT NULL,         -- factor name, sid|date, table name, 'SYSTEM', etc.
    snapshot_date     TEXT NOT NULL,
    dim_provenance    INTEGER,               -- 0..20; NULL = not evaluated this phase
    dim_freshness     INTEGER,
    dim_plausibility  INTEGER,
    dim_consistency   INTEGER,
    dim_coverage      INTEGER,
    score_total       INTEGER,               -- sum of non-NULL dims
    score_max         INTEGER,               -- 20 × count(non-NULL dims)
    score_pct         INTEGER,               -- round(100 × score_total / score_max)
    label             TEXT,                  -- UNKNOWN | AVOID | REVIEW | PRELIMINARY | TRUSTED
    reasons_json      TEXT,                  -- JSON dict {dim_name: explanation, …}
    computed_at       TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (entity_kind, entity_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_health_score_kind_date ON health_score(entity_kind, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_health_score_label ON health_score(label);

CREATE TABLE IF NOT EXISTS historical_universe (
    snapshot_date  TEXT NOT NULL,   -- actual bhavcopy trading day used
    requested_date TEXT,            -- the anchor date requested
    symbol         TEXT NOT NULL,
    sid            TEXT,            -- NULL = not in current stocks (delisted/untracked)
    series         TEXT,
    close          REAL,
    delivery_pct   REAL,
    PRIMARY KEY (snapshot_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_histuniv_sid ON historical_universe(sid);

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
    fetched_at      TEXT DEFAULT (datetime('now')), filing_id TEXT,
    UNIQUE(sid, person_category, transaction_type, trade_date, shares)
);
CREATE INDEX IF NOT EXISTS idx_insider_date ON insider_trades(trade_date);
CREATE INDEX IF NOT EXISTS idx_insider_sid ON insider_trades(sid);

CREATE TABLE IF NOT EXISTS interest_coverage_scores (
    sid TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date TEXT NOT NULL,
    period_end TEXT,
    interest_coverage REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_icov_date ON interest_coverage_scores(snapshot_date);

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

CREATE TABLE IF NOT EXISTS llm_usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    called_at     TEXT NOT NULL DEFAULT (datetime('now')),
    step          TEXT NOT NULL,
    model         TEXT NOT NULL,
    mode          TEXT NOT NULL DEFAULT 'sync',
    n_calls       INTEGER NOT NULL DEFAULT 1,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    est_cost_usd  REAL
);

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
CREATE INDEX IF NOT EXISTS idx_macro_history_category ON macro_history(category);
CREATE INDEX IF NOT EXISTS idx_macro_history_date ON macro_history(date);

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

CREATE TABLE IF NOT EXISTS macro_indicators (
    indicator       TEXT NOT NULL,
    signal          TEXT,
    value           REAL,
    detail          TEXT,
    snapshot_date   TEXT NOT NULL,
    PRIMARY KEY (indicator, snapshot_date)
);

CREATE TABLE IF NOT EXISTS macro_sector_map (
    indicator_id    TEXT NOT NULL REFERENCES macro_indicator_meta(indicator_id),
    sector          TEXT NOT NULL,
    direction       INTEGER NOT NULL,
    weight          REAL DEFAULT 1.0,
    rationale       TEXT,
    PRIMARY KEY (indicator_id, sector)
);

CREATE TABLE IF NOT EXISTS macro_sector_signals (
    sector          TEXT NOT NULL,
    snapshot_date   TEXT NOT NULL,
    macro_score     REAL,
    macro_signal    TEXT,
    macro_detail    TEXT,
    PRIMARY KEY (sector, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_macro_sector_date ON macro_sector_signals(snapshot_date);

CREATE TABLE IF NOT EXISTS macro_sector_signals_pit (
    sector TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    regulatory_score REAL,
    macro_score REAL,
    n_reg_events INTEGER,
    n_macro_indicators INTEGER,
    reconstructed_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sector, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_msp_date ON macro_sector_signals_pit(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_msp_sector ON macro_sector_signals_pit(sector);

CREATE TABLE IF NOT EXISTS management_scores (
    sid                   TEXT NOT NULL,
    snapshot_date         TEXT NOT NULL,
    cap_tier              TEXT,
    capital_allocation_z  REAL,                  -- pillar A  (z within tier)
    alignment_z           REAL,                  -- pillar B
    credibility_z         REAL,                  -- pillar C
    mgmt_quality_z        REAL,                  -- weighted composite z
    mgmt_quality_score    REAL,                  -- 0-100 percentile within cap_tier
    grade                 TEXT,                  -- A+/A/B/C/D from the percentile
    -- raw component values (transparency for the scorecard)
    roic                  REAL,
    roiic                 REAL,
    fcf_margin            REAL,
    promoter_trend        REAL,
    pledge_quality        REAL,
    promoter_signal       REAL,
    f_score               REAL,
    accruals_quality      REAL,
    forensic_penalty      REAL,
    n_pillars             INTEGER,               -- pillars present (1-3); composite renormalised
    computed_at           TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_mgmt_scores_score ON management_scores(snapshot_date, mgmt_quality_score DESC);

CREATE TABLE IF NOT EXISTS managerial_ability_scores (
    sid                TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date      TEXT NOT NULL,
    cap_tier           TEXT,
    sector             TEXT,
    period_end         TEXT,                    -- latest annual period used
    dea_efficiency     REAL,                    -- stage-1 θ (VRS, within sector), (0,1]
    ma_residual        REAL,                    -- stage-2 Tobit residual = managerial ability
    ma_score           REAL,                    -- 0-100 percentile of ma_residual within cap_tier
    grade              TEXT,                    -- A+/A/B/C/D from the percentile
    -- stage-1 inputs/output (₹ cr, 3y median — transparency)
    sales              REAL,
    cogs               REAL,
    employee_cost      REAL,
    net_block          REAL,
    intangibles        REAL,
    total_assets       REAL,
    n_peers            INTEGER,                 -- firms in the sector DEA frontier
    computed_at        TEXT DEFAULT (datetime('now')), frontier_group TEXT,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_managerial_ability_date ON managerial_ability_scores(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_managerial_ability_score ON managerial_ability_scores(snapshot_date, ma_score DESC);

CREATE TABLE IF NOT EXISTS mf_calendar_returns (
    scheme_code   TEXT NOT NULL,
    year          INTEGER NOT NULL,
    ret_pct       REAL,
    bench_ret_pct REAL,
    PRIMARY KEY (scheme_code, year)
);

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

CREATE TABLE IF NOT EXISTS mf_holdings (
    scheme_code     TEXT NOT NULL,
    as_of_date      TEXT NOT NULL,
    holding_rank    INTEGER NOT NULL,
    instrument_type TEXT,
    sid             TEXT,
    isin            TEXT,
    instrument_name TEXT NOT NULL,
    sector          TEXT,
    pct_of_aum      REAL,
    market_value_cr REAL,
    PRIMARY KEY (scheme_code, as_of_date, holding_rank)
);
CREATE INDEX IF NOT EXISTS idx_mf_holdings_scheme ON mf_holdings(scheme_code);
CREATE INDEX IF NOT EXISTS idx_mf_holdings_sid    ON mf_holdings(sid);

CREATE TABLE IF NOT EXISTS mf_holdings_quarantine (
    scheme_code     TEXT NOT NULL,
    as_of_date      TEXT NOT NULL,
    holding_rank    INTEGER NOT NULL,
    instrument_type TEXT,
    sid             TEXT,
    isin            TEXT,
    instrument_name TEXT NOT NULL,
    sector          TEXT,
    pct_of_aum      REAL,
    market_value_cr REAL
, _q_failed_gate TEXT, _q_reason TEXT, _q_quarantined_at TEXT DEFAULT (datetime('now')));

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
    max_drawdown            REAL,
    max_dd_start            TEXT,
    max_dd_end              TEXT,
    recovery_days           INTEGER,
    bench_spread_1y         REAL,
    bench_spread_3y         REAL,
    peer_rank_1y            INTEGER,
    peer_rank_3y            INTEGER,
    peer_count              INTEGER,
    composite_score         REAL,
    score_percentile        REAL,
    score_3y_cagr_pct       REAL,
    score_sharpe_3y_pct     REAL,
    score_max_dd_pct        REAL,
    score_consistency_pct   REAL,
    PRIMARY KEY (scheme_code, as_of_date)
);
CREATE INDEX IF NOT EXISTS idx_mf_metrics_asof ON mf_metrics(as_of_date);
CREATE INDEX IF NOT EXISTS idx_mf_metrics_score ON mf_metrics(composite_score DESC);

CREATE TABLE IF NOT EXISTS mf_nav_history (
    scheme_code TEXT NOT NULL,
    nav_date TEXT NOT NULL,
    nav REAL,
    fetched_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (scheme_code, nav_date)
);
CREATE INDEX IF NOT EXISTS idx_mfnav_date ON mf_nav_history(nav_date);
CREATE INDEX IF NOT EXISTS idx_mfnav_scheme ON mf_nav_history(scheme_code);

CREATE TABLE IF NOT EXISTS mf_rolling_returns (
    scheme_code                 TEXT NOT NULL,
    anchor_date                 TEXT NOT NULL,
    rolling_3y_cagr             REAL,
    rolling_5y_cagr             REAL,
    rolling_3y_beats_category   INTEGER,
    rolling_5y_beats_category   INTEGER,
    PRIMARY KEY (scheme_code, anchor_date)
);
CREATE INDEX IF NOT EXISTS idx_mf_rolling_sid ON mf_rolling_returns(scheme_code);

CREATE TABLE IF NOT EXISTS mf_scheme_master (
    scheme_code      TEXT PRIMARY KEY,
    isin_growth      TEXT,
    isin_div         TEXT,
    scheme_name      TEXT NOT NULL,
    amc              TEXT,
    category_raw     TEXT,
    category_norm    TEXT,
    sub_category     TEXT,
    plan_type        TEXT CHECK (plan_type IN ('DIRECT','REGULAR','UNKNOWN')),
    option_type      TEXT CHECK (option_type IN ('GROWTH','IDCW','UNKNOWN')),
    inception_date   TEXT,
    aum_cr           REAL,
    expense_ratio    REAL,
    benchmark        TEXT,
    last_seen        TEXT,
    active           INTEGER DEFAULT 1,
    fetched_at       TEXT
, data_quality TEXT DEFAULT 'TRUSTED', quality_reason TEXT, etm_slug TEXT, etm_id INTEGER);
CREATE INDEX IF NOT EXISTS idx_mf_master_active   ON mf_scheme_master(active);
CREATE INDEX IF NOT EXISTS idx_mf_master_amc      ON mf_scheme_master(amc);
CREATE INDEX IF NOT EXISTS idx_mf_master_cat      ON mf_scheme_master(category_norm);
CREATE INDEX IF NOT EXISTS idx_mf_master_plan     ON mf_scheme_master(plan_type, option_type);

CREATE TABLE IF NOT EXISTS mf_schemes (
    scheme_code TEXT PRIMARY KEY,
    scheme_name TEXT,
    fund_house TEXT,
    scheme_type TEXT,          -- 'EQUITY_LARGE', 'EQUITY_MID', 'EQUITY_FLEXI', etc.
    direct_or_regular TEXT,
    growth_or_dividend TEXT,
    is_top50 INTEGER DEFAULT 0,
    fetched_at TEXT DEFAULT (datetime('now'))
, category_norm TEXT, benchmark TEXT, inception_date TEXT, has_full_history INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS mf_sector_allocation (
    scheme_code  TEXT NOT NULL,
    as_of_date   TEXT NOT NULL,
    sector       TEXT NOT NULL,
    pct_of_aum   REAL NOT NULL,
    PRIMARY KEY (scheme_code, as_of_date, sector)
);

CREATE TABLE IF NOT EXISTS mf_sector_allocation_quarantine (
    scheme_code  TEXT NOT NULL,
    as_of_date   TEXT NOT NULL,
    sector       TEXT NOT NULL,
    pct_of_aum   REAL NOT NULL
, _q_failed_gate TEXT, _q_reason TEXT, _q_quarantined_at TEXT DEFAULT (datetime('now')));

CREATE TABLE IF NOT EXISTS multibagger_scores (
    sid                   TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date         TEXT NOT NULL,
    cap_tier              TEXT,
    mcap_cr               REAL,                  -- market cap in ₹ crore
    survived              INTEGER,               -- 1 = passed all gates + hurdles
    passed_gates          INTEGER,
    gate_fail             TEXT,                  -- which Stage-1 gates failed
    passed_hurdles        INTEGER,
    hurdle_fail           TEXT,                  -- which Stage-2 hurdles failed
    de_ratio              REAL,                  -- Borrowings / (EqCap + Reserves)
    pat_cagr_3y           REAL,
    earnings_acceleration REAL,                  -- annual growth-of-growth
    ep_yield              REAL,                  -- latest PAT / market cap
    peg                   REAL,
    gross_profitability   REAL,                  -- Novy-Marx anchor (reused)
    roic                  REAL,
    roiic                 REAL,
    margin_slope          REAL,
    f_score               INTEGER,               -- Piotroski
    promoter_pct          REAL,
    pledge_pct            REAL,
    smart_money_score     REAL,
    m_score_flag          TEXT,                  -- Beneish CLEAN / LIKELY_MANIPULATOR
    p_quality             REAL,                  -- Stage-3 pillar sub-scores
    p_growth              REAL,
    p_conviction          REAL,
    interaction           REAL,                  -- growth × cheapness
    multibagger_score     REAL,                  -- final composite (survivors only)
    rank_in_tier          REAL, smallcap_regime TEXT, regime_favorable INTEGER,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_multibagger_date ON multibagger_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS news_article_stocks (
    article_id      TEXT NOT NULL REFERENCES news_articles(article_id),
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    match_location  TEXT,
    PRIMARY KEY (article_id, sid)
);
CREATE INDEX IF NOT EXISTS idx_news_stocks_sid ON news_article_stocks(sid);

CREATE TABLE IF NOT EXISTS news_articles (
    article_id      TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    summary         TEXT,
    url             TEXT,
    source          TEXT NOT NULL,
    published_at    TEXT,
    fetched_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS news_briefs (
    brief_date       TEXT PRIMARY KEY,
    big_one          TEXT NOT NULL,    -- THE BIG ONE — single most important story (60w)
    five_fast        TEXT NOT NULL,    -- FIVE FAST — JSON array of 5 items (20w each)
    one_to_watch     TEXT,             -- ONE TO WATCH — forming story (40w)
    zoom_out         TEXT,             -- ZOOM OUT — connect today to larger pattern (50w)
    n_articles_used  INTEGER,
    generated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The news editor (plan 0021, sources/news_editor.py). Themes are a fixed list in
-- config.NEWS_THEMES; this state table holds each theme's note, rewritten in place.
CREATE TABLE IF NOT EXISTS news_themes (
    theme_id        TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    scope           TEXT NOT NULL,    -- what belongs under the theme
    status          TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'retired')),
    updated_at      TEXT,             -- as-of day of the note below
    stands_now      TEXT,             -- 30w
    what_changed    TEXT,             -- 40w
    why_it_matters  TEXT,             -- 50w
    gains           TEXT,             -- JSON array of sector names
    loses           TEXT,             -- JSON array of sector names
    portfolio_line  TEXT,             -- 35w: what kind of company gains / loses
    what_to_watch   TEXT,             -- 30w
    next_if         TEXT,             -- JSON array of 2 "If ..., then ..." branches
    story_so_far    TEXT              -- 200w
);

-- Headline → theme, written by the daily edition. theme_id NULL = read, fits no theme.
CREATE TABLE IF NOT EXISTS news_theme_articles (
    article_id      TEXT PRIMARY KEY REFERENCES news_articles(article_id),
    theme_id        TEXT REFERENCES news_themes(theme_id),
    assigned_on     TEXT NOT NULL,
    used_in_update  TEXT              -- as-of day of the note rewrite that read this headline
);
CREATE INDEX IF NOT EXISTS idx_news_theme_articles_theme ON news_theme_articles(theme_id);

-- One row per theme-note rewrite: the theme's timeline.
CREATE TABLE IF NOT EXISTS news_theme_history (
    theme_id        TEXT NOT NULL REFERENCES news_themes(theme_id),
    as_of           TEXT NOT NULL,
    stands_now      TEXT,
    what_changed    TEXT,
    n_articles      INTEGER,
    PRIMARY KEY (theme_id, as_of)
);

-- The daily edition: the three things that matter today.
CREATE TABLE IF NOT EXISTS news_today (
    day             TEXT PRIMARY KEY,
    items           TEXT NOT NULL,    -- JSON array of {headline, what, so_what, theme, article_ids}
    n_headlines     INTEGER,          -- headlines the edition read
    generated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The weekly edition: on the radar + sectors to favour / be careful with.
CREATE TABLE IF NOT EXISTS news_week (
    as_of           TEXT PRIMARY KEY,
    radar           TEXT NOT NULL,    -- JSON array of {title, what, why_early, article_ids}
    favour          TEXT NOT NULL,    -- JSON array of {sector, reason}
    careful         TEXT NOT NULL,    -- JSON array of {sector, reason}
    generated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

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
, image_url TEXT, keywords TEXT);
CREATE INDEX IF NOT EXISTS idx_news_enriched_status ON news_enriched(classifier_status);
CREATE INDEX IF NOT EXISTS idx_news_enriched_topic ON news_enriched(primary_topic);

CREATE TABLE IF NOT EXISTS nlp_scores (
    sid                       TEXT NOT NULL,
    doc_type                  TEXT NOT NULL,
    doc_date                  TEXT NOT NULL,
    word_count                INTEGER,
    lm_positive               INTEGER,
    lm_negative               INTEGER,
    net_tone                  REAL,   -- (pos - neg) / word_count * 100
    uncertainty_density       REAL,   -- LM-uncertainty hits / word_count * 100   (#37)
    forward_looking_intensity REAL,   -- forward-looking phrases per 1000 words    (#36)
    computed_at               TEXT DEFAULT (datetime('now')), available_date TEXT,
    PRIMARY KEY (sid, doc_type, doc_date)
);
CREATE INDEX IF NOT EXISTS idx_nlp_scores_sid ON nlp_scores(sid, doc_date);

CREATE TABLE IF NOT EXISTS nse_index_history (
    index_symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, traded_value REAL,
    fetched_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (index_symbol, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_nse_idx_date ON nse_index_history(trade_date);

CREATE TABLE IF NOT EXISTS nwc_to_revenue_scores (sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT, nwc_to_revenue REAL, PRIMARY KEY (sid, snapshot_date));
CREATE INDEX IF NOT EXISTS idx_nwc2rev_date ON nwc_to_revenue_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS operating_margin_trend_scores (
    sid TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date TEXT NOT NULL,
    period_end TEXT,
    margin_latest REAL,
    margin_5y_avg REAL,
    margin_slope REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_omtrend_date ON operating_margin_trend_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS paper_nav_history (
    nav_date              TEXT PRIMARY KEY,
    nav                   REAL NOT NULL,
    cash                  REAL NOT NULL,
    n_positions           INTEGER NOT NULL,
    daily_return_pct      REAL,
    cumulative_return_pct REAL,
    drawdown_pct          REAL,
    benchmark_nav         REAL,
    benchmark_cumret      REAL,
    spread_vs_benchmark   REAL
);
CREATE INDEX IF NOT EXISTS idx_paper_nav_date ON paper_nav_history(nav_date);

CREATE TABLE IF NOT EXISTS paper_positions (
    position_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    sid              TEXT NOT NULL,
    cap_tier         TEXT NOT NULL,
    sector           TEXT,
    entry_date       TEXT NOT NULL,
    entry_price      REAL NOT NULL,
    entry_weight_pct REAL NOT NULL,
    qty              REAL NOT NULL,
    exit_date        TEXT,
    exit_price       REAL,
    rank_at_entry    INTEGER,
    score_at_entry   REAL,
    status           TEXT NOT NULL CHECK (status IN ('OPEN','CLOSED'))
);
CREATE INDEX IF NOT EXISTS idx_paper_positions_sid ON paper_positions(sid);
CREATE INDEX IF NOT EXISTS idx_paper_positions_status ON paper_positions(status);

CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date       TEXT NOT NULL,
    sid              TEXT NOT NULL,
    side             TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    qty              REAL NOT NULL,
    price            REAL NOT NULL,
    gross_value      REAL NOT NULL,
    cost_bps         REAL NOT NULL,
    cost_amount      REAL NOT NULL,
    net_value        REAL NOT NULL,
    reason           TEXT NOT NULL,
    position_id      INTEGER REFERENCES paper_positions(position_id),
    rebalance_date   TEXT
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_date ON paper_trades(trade_date);
CREATE INDEX IF NOT EXISTS idx_paper_trades_sid ON paper_trades(sid);

CREATE TABLE IF NOT EXISTS pick_outcomes (
    sid             TEXT NOT NULL,
    pick_date       TEXT NOT NULL,
    window_days     INTEGER NOT NULL,
    cap_tier        TEXT,
    rank_at_pick    INTEGER,
    final_score     REAL,
    entry_price     REAL,
    exit_date       TEXT,
    exit_price      REAL,
    fwd_return_pct  REAL,
    bench_index     TEXT,
    bench_return_pct REAL,
    excess_return_pct REAL,
    computed_at     TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, pick_date, window_days)
);
CREATE INDEX IF NOT EXISTS idx_pick_outcomes_date ON pick_outcomes(pick_date);
CREATE INDEX IF NOT EXISTS idx_pick_outcomes_tier ON pick_outcomes(cap_tier, pick_date);

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

-- Plan 0018: one row per feed check (canary / gate / reconcile). Maps onto plan 0017's
-- check_results (+ row_issues for row-level rejects) when that table lands.
CREATE TABLE IF NOT EXISTS feed_checks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date     TEXT NOT NULL DEFAULT (date('now')),
    feed         TEXT NOT NULL,
    check_kind   TEXT NOT NULL CHECK(check_kind IN ('canary', 'gate', 'reconcile')),
    route        TEXT,
    status       TEXT NOT NULL CHECK(status IN ('PASS', 'WARN', 'FAIL', 'ERROR')),
    symptom      TEXT,
    http_status  INTEGER,
    n_rows       INTEGER,
    bytes        INTEGER,
    fingerprint  TEXT,
    baseline     TEXT,
    duration_sec REAL,
    detail       TEXT,
    checked_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_feed_checks_feed ON feed_checks(feed, id);

-- Plan 0018: structured run log — one row per event of an ingestor / step run (runlog.py).
-- Queryable by the ops page, `python -m runlog`, and an outside agent over MCP.
CREATE TABLE IF NOT EXISTS run_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    ts           TEXT NOT NULL,
    step         TEXT,
    feed         TEXT,
    event        TEXT NOT NULL,
    level        TEXT NOT NULL CHECK(level IN ('INFO', 'WARN', 'ERROR')),
    host         TEXT,
    url          TEXT,
    http_status  INTEGER,
    attempt      INTEGER,
    duration_ms  INTEGER,
    item         TEXT,
    rows         INTEGER,
    symptom      TEXT,
    error_type   TEXT,
    message      TEXT,
    location     TEXT,
    detail       TEXT
);
CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id);
CREATE INDEX IF NOT EXISTS idx_run_events_feed ON run_events(feed, id);
CREATE INDEX IF NOT EXISTS idx_run_events_level ON run_events(level, id);

-- Plan 0018 new sources, shaped like plan 0017's concept tables so its migration is a rename:
-- market_events ≈ 0017 `events` (one table for every event stream: credit ratings, IPO
-- listings, index changes …); analyst_estimates ≈ 0017 `estimates` (versioned: a changed
-- value is a new row, an unchanged one only bumps last_seen_at).
CREATE TABLE IF NOT EXISTS market_events (
    event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    type         TEXT NOT NULL,
    subtype      TEXT,
    sid          TEXT,
    event_time   TEXT NOT NULL,
    available_at TEXT NOT NULL,
    source       TEXT NOT NULL,
    source_key   TEXT NOT NULL,
    payload      TEXT,
    fetched_at   TEXT NOT NULL,
    UNIQUE (type, source, source_key)
);
CREATE INDEX IF NOT EXISTS idx_market_events_sid ON market_events(sid, type, event_time);
CREATE INDEX IF NOT EXISTS idx_market_events_type ON market_events(type, subtype, event_time);

CREATE TABLE IF NOT EXISTS analyst_estimates (
    sid           TEXT NOT NULL,
    metric        TEXT NOT NULL,
    target_period TEXT NOT NULL,
    source        TEXT NOT NULL,
    value         REAL,
    label         TEXT,
    available_at  TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    PRIMARY KEY (sid, metric, target_period, source, fetched_at)
);
CREATE INDEX IF NOT EXISTS idx_analyst_estimates_metric ON analyst_estimates(metric, target_period);

CREATE TABLE IF NOT EXISTS "pipeline_log" (
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

CREATE TABLE IF NOT EXISTS pit_ic_by_tier_v1 (
    signal           TEXT NOT NULL,
    cap_tier         TEXT NOT NULL,
    description      TEXT,
    n_periods        INTEGER,
    n_stocks_avg     INTEGER,
    mean_ic          REAL,
    std_ic           REAL,
    icir             REAL,
    t_stat           REAL,
    avg_ls_pct       REAL,
    verdict          TEXT,
    higher_better    INTEGER,
    imported_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (signal, cap_tier)
);

CREATE TABLE IF NOT EXISTS pit_ic_by_tier_v2 (
    signal TEXT NOT NULL,
    cap_tier TEXT NOT NULL,
    n_periods INTEGER,
    n_stocks_avg INTEGER,
    mean_ic REAL,
    std_ic REAL,
    icir REAL,
    t_stat REAL,
    verdict TEXT,
    source TEXT,                   -- 'v1_archive', 'v2_recompute', 'merged'
    computed_at TEXT DEFAULT (datetime('now')), t_stat_ci_lo REAL, t_stat_ci_hi REAL,
    PRIMARY KEY (signal, cap_tier, source)
);

CREATE TABLE IF NOT EXISTS pit_reconstruction_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_date        TEXT NOT NULL,
    signals_run      TEXT NOT NULL,
    rows_attempted   INTEGER,
    rows_written     INTEGER,
    validation_summary TEXT,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    duration_sec     REAL,
    status           TEXT CHECK(status IN ('RUNNING', 'SUCCESS', 'FAILED', 'SKIPPED')),
    error_message    TEXT
);
CREATE INDEX IF NOT EXISTS idx_pit_log_date ON pit_reconstruction_log(eval_date);

CREATE TABLE IF NOT EXISTS pit_replay_snapshots (
                snapshot_date    TEXT NOT NULL,
                sid              TEXT NOT NULL,
                rank             INTEGER,
                final_score      REAL,
                cap_tier         TEXT,
                output_json      TEXT,   -- full row's *_adj, base_score, penalty, etc
                inputs_json      TEXT,   -- frozen signal-table values
                frozen_at        TEXT NOT NULL,
                frozen_by_commit TEXT,
                PRIMARY KEY (snapshot_date, sid)
            );
CREATE INDEX IF NOT EXISTS idx_pit_replay_date ON pit_replay_snapshots(snapshot_date);

CREATE TABLE IF NOT EXISTS policy_events (
    event_date      TEXT NOT NULL,      -- announcement / effective date
    sector          TEXT NOT NULL,      -- GICS sector affected
    event_type      TEXT,               -- BUDGET / PLI / ORDER / REGULATION / TARIFF / THEME
    direction       INTEGER NOT NULL,   -- +1 tailwind / −1 headwind
    magnitude       REAL NOT NULL,      -- 0–3 curated importance
    title           TEXT NOT NULL,
    source          TEXT,
    PRIMARY KEY (event_date, sector, title)
);
CREATE INDEX IF NOT EXISTS idx_policy_sector ON policy_events(sector);

CREATE TABLE IF NOT EXISTS portfolio_outcomes (
    asof_date         TEXT NOT NULL,    -- portfolio_weights.asof_date (book date)
    window_days       INTEGER NOT NULL, -- forward TRADING-day horizon (20/63/126)
    hrp_return_pct    REAL,             -- Σ(weight × fwd_ret), HRP weights renorm over matured names
    eqw_return_pct    REAL,             -- mean fwd_ret over the same matured names (equal-weight)
    bench_return_pct  REAL,             -- tier-weight-blended NIFTY benchmark return
    hrp_vs_eqw_pct    REAL,             -- hrp_return_pct − eqw_return_pct (the weighting edge)
    hrp_excess_pct    REAL,             -- hrp_return_pct − bench_return_pct (vs passive)
    n_names           INTEGER,          -- book size at asof_date
    n_matured         INTEGER,          -- names with a realized return at this window
    computed_at       TEXT,
    PRIMARY KEY (asof_date, window_days)
);
CREATE INDEX IF NOT EXISTS idx_portfolio_outcomes_window ON portfolio_outcomes(window_days);

CREATE TABLE IF NOT EXISTS portfolio_weights (
    asof_date              TEXT NOT NULL,   -- daily_picks.pick_date the book was built from
    sid                    TEXT NOT NULL REFERENCES stocks(sid),
    weight                 REAL,            -- final position weight (0..max_stock_weight), Σ=1
    factor_score           REAL,            -- daily_picks.final_score (the alpha tilt input)
    marginal_risk_contrib  REAL,            -- w_i·(Σw)_i / σ_p — fraction of portfolio vol from this name
    cap_tier               TEXT,
    sector                 TEXT,
    name                   TEXT,
    rank                   INTEGER,         -- within-tier rank carried from daily_picks
    created_at             TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (asof_date, sid)
);
CREATE INDEX IF NOT EXISTS idx_portfolio_weights_date ON portfolio_weights(asof_date);

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

CREATE TABLE IF NOT EXISTS quarterly_income (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    period          TEXT NOT NULL,
    end_date        TEXT,
    reporting       TEXT DEFAULT 'consolidated',
    revenue         REAL,
    operating_profit REAL,
    net_income      REAL,
    eps             REAL,
    operating_expenses REAL,
    pbt             REAL,
    tax_and_minority REAL,
    ebitda          REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, period, reporting)
);

CREATE TABLE IF NOT EXISTS quarterly_income_quarantine (
    sid             TEXT NOT NULL,
    period          TEXT NOT NULL,
    end_date        TEXT,
    reporting       TEXT DEFAULT 'consolidated',
    revenue         REAL,
    operating_profit REAL,
    net_income      REAL,
    eps             REAL,
    operating_expenses REAL,
    pbt             REAL,
    tax_and_minority REAL,
    ebitda          REAL,
    fetched_at      TEXT DEFAULT (datetime('now'))
, _q_failed_gate TEXT, _q_reason TEXT, _q_quarantined_at TEXT DEFAULT (datetime('now')));

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

CREATE TABLE IF NOT EXISTS regulatory_batches (
    batch_id        TEXT PRIMARY KEY,
    stage           TEXT NOT NULL,
    submitted_at    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'submitted',
    n_items         INTEGER,
    ingested_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_reg_batches_status ON regulatory_batches(status);

CREATE TABLE IF NOT EXISTS regulatory_events (
    event_id        TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    summary         TEXT,
    full_text       TEXT,
    source          TEXT NOT NULL,
    source_url      TEXT,
    published_at    TEXT NOT NULL,
    ministry        TEXT,
    fetched_at      TEXT DEFAULT (datetime('now'))
, classifier_status TEXT DEFAULT 'pending', classifier_processed_at TEXT, title_hash TEXT);
CREATE INDEX IF NOT EXISTS idx_reg_events_classifier_status ON regulatory_events(classifier_status);
CREATE INDEX IF NOT EXISTS idx_reg_events_date ON regulatory_events(published_at);
CREATE INDEX IF NOT EXISTS idx_reg_events_source ON regulatory_events(source);

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
CREATE INDEX IF NOT EXISTS idx_reg_signals_date ON regulatory_signals(classified_at);
CREATE INDEX IF NOT EXISTS idx_reg_signals_sector ON regulatory_signals(sector);

CREATE TABLE IF NOT EXISTS revenue_cv_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    revenue_cv_5y   REAL,        -- stdev / |mean| of last 5 YoY growth rates
    mean_growth     REAL,        -- mean of last 5 YoY growth rates
    years_used      INTEGER,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_rev_cv_date ON revenue_cv_scores(snapshot_date);

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

CREATE TABLE IF NOT EXISTS roiic_scores (
            sid TEXT NOT NULL REFERENCES stocks(sid),
            snapshot_date TEXT NOT NULL,
            period_end TEXT,
            delta_nopat REAL,
            delta_ic REAL,
            roiic REAL,
            PRIMARY KEY (sid, snapshot_date)
        );
CREATE INDEX IF NOT EXISTS idx_roiic_date ON roiic_scores(snapshot_date);

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

CREATE TABLE IF NOT EXISTS screener_pull_errors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sid             TEXT,                         -- nullable if error was pre-lookup
    ticker          TEXT,
    error_type      TEXT NOT NULL,                -- 'auth' | 'http' | 'parse' | 'thin' | 'empty' | 'fetch'
    error_message   TEXT,
    http_status     INTEGER,
    attempted_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_screener_errors_date ON screener_pull_errors(attempted_at);
CREATE INDEX IF NOT EXISTS idx_screener_errors_sid ON screener_pull_errors(sid);

CREATE TABLE IF NOT EXISTS scrip_master (
                scrip_cd   INTEGER PRIMARY KEY,
                isin       TEXT,
                nse_symbol TEXT,
                sid        TEXT,
                name       TEXT,
                status     TEXT,
                source     TEXT,
                updated_at TEXT
            );
CREATE INDEX IF NOT EXISTS idx_scrip_master_isin ON scrip_master(isin);
CREATE INDEX IF NOT EXISTS idx_scrip_master_sid  ON scrip_master(sid);

CREATE TABLE IF NOT EXISTS sector_analyst_breadth_pit (
    sector          TEXT NOT NULL,
    snapshot_date   TEXT NOT NULL,      -- the later month's snapshot (1st-of-month)
    n_covered       INTEGER,            -- stocks with coverage in both months
    pct_pt_up       REAL,               -- share whose target_mean rose MoM
    pct_pt_down     REAL,
    mean_pt_chg_pct REAL,               -- mean MoM % change in target_mean
    mean_reco       REAL,               -- mean recommendation_mean (1=buy..5=sell)
    breadth         REAL,               -- pct_pt_up − pct_pt_down (the signal)
    PRIMARY KEY (sector, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_sabp_date ON sector_analyst_breadth_pit(snapshot_date);

CREATE TABLE IF NOT EXISTS sector_briefs (
    sector              TEXT NOT NULL,
    snapshot_date       TEXT NOT NULL,
    n_stocks            INTEGER NOT NULL,
    mcap_total_cr       REAL,
    macro_score         REAL,
    macro_signal        TEXT,
    macro_drivers       TEXT,
    breadth_pct         REAL,
    avg_score           REAL,
    n_picks_top30       INTEGER NOT NULL DEFAULT 0,
    top_picks           TEXT,
    n_regulatory_30d    INTEGER NOT NULL DEFAULT 0,
    regulatory_summary  TEXT,
    fii_net_30d         REAL,
    dii_net_30d         REAL,
    bucket              TEXT NOT NULL CHECK (bucket IN ('BOOMING','LIKELY','HEADWIND','QUIET')),
    computed_at         TEXT NOT NULL, horizon_short TEXT, horizon_medium TEXT, horizon_long TEXT,
    PRIMARY KEY (sector, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_sector_briefs_bucket ON sector_briefs(snapshot_date, bucket);
CREATE INDEX IF NOT EXISTS idx_sector_briefs_date ON sector_briefs(snapshot_date);

CREATE TABLE IF NOT EXISTS sector_dossiers (
    sector                   TEXT NOT NULL,
    snapshot_date            TEXT NOT NULL,
    thesis                   TEXT,
    bull_case                TEXT,   -- JSON list of strings
    bear_case                TEXT,   -- JSON list of strings
    what_to_watch            TEXT,   -- JSON list of {horizon: S|M|L, item: str}
    tech_innovation_drivers  TEXT,   -- JSON list of strings
    conviction               TEXT,   -- HIGH / MEDIUM / LOW (sector tilt)
    valid                    INTEGER NOT NULL DEFAULT 0,
    validation_json          TEXT,
    model                    TEXT,
    generated_at             TEXT NOT NULL,
    PRIMARY KEY (sector, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_sector_dossiers_date ON sector_dossiers(snapshot_date);

CREATE TABLE IF NOT EXISTS sector_force_breakdown (
    sector              TEXT NOT NULL,
    snapshot_date       TEXT NOT NULL,
    force               TEXT NOT NULL CHECK (force IN ('macro','regulation','market','tech')),
    direction           TEXT,
    magnitude           TEXT,
    summary             TEXT,
    detail              TEXT,
    computed_at         TEXT NOT NULL,
    PRIMARY KEY (sector, snapshot_date, force)
);
CREATE INDEX IF NOT EXISTS idx_sector_force_date_force ON sector_force_breakdown(snapshot_date, force);

CREATE TABLE IF NOT EXISTS sector_metadata (
    sector          TEXT NOT NULL,        -- GICS sector name (matches stocks.sector)
    industry        TEXT,                 -- IIM industry mapped to this sector
    source          TEXT NOT NULL DEFAULT 'auto' CHECK(source IN ('auto', 'manual')),
    generated_at    TEXT DEFAULT (datetime('now')),
    payload         TEXT NOT NULL,        -- JSON blob, see structure below
    notes           TEXT,                 -- optional free-text on generation run
    PRIMARY KEY (sector, source)
);
CREATE INDEX IF NOT EXISTS idx_sector_meta_gen ON sector_metadata(generated_at);

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

CREATE TABLE IF NOT EXISTS sector_policy_pit (
    sector          TEXT NOT NULL,
    snapshot_date   TEXT NOT NULL,      -- month-end
    policy_score    REAL,               -- decayed net tailwind (− = net headwind)
    n_events        INTEGER,
    PRIMARY KEY (sector, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_spp_date ON sector_policy_pit(snapshot_date);

CREATE TABLE IF NOT EXISTS sector_sentiment_breadth_pit (
    sector          TEXT NOT NULL,
    snapshot_date   TEXT NOT NULL,      -- last sentiment snapshot date in the month
    n_stocks        INTEGER,
    mean_sent_30d   REAL,
    pct_positive    REAL,               -- share with sentiment_30d > 0
    article_vol     INTEGER,            -- total articles_30d in sector
    sent_breadth    REAL,               -- pct_positive − pct_negative (the signal)
    PRIMARY KEY (sector, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_ssbp_date ON sector_sentiment_breadth_pit(snapshot_date);

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

CREATE TABLE IF NOT EXISTS sga_to_revenue_change_scores (sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT, sga_to_revenue_change REAL, PRIMARY KEY (sid, snapshot_date));
CREATE INDEX IF NOT EXISTS idx_sgachg_date ON sga_to_revenue_change_scores(snapshot_date);

CREATE TABLE IF NOT EXISTS share_momentum_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    market_cap_cr   REAL,         -- current market cap (₹ × share count, in line-item units)
    sector_share    REAL,         -- share[t]
    share_momentum  REAL,         -- share[t] / share[t-90d] − 1
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_sharemom_date ON share_momentum_scores(snapshot_date);

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
    n_shareholders  INTEGER,
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, end_date)
);

-- Named holders above 1% from the BSE shareholding-pattern XBRL (sources/bse_shp.py).
-- Append-only: a revised filing for a quarter is a new set of rows with a later
-- filed_at (BSE broadcast time = when the market could read it).
CREATE TABLE IF NOT EXISTS shareholding_holders (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    scrip_cd        INTEGER NOT NULL,          -- BSE scrip code the filing was read under
    end_date        TEXT NOT NULL,             -- quarter end the filing describes
    filed_at        TEXT NOT NULL,             -- BSE broadcast time of the filing
    holder_category TEXT NOT NULL,             -- filing section: MutualFundsOrUTI, IndividualsOrHUF, ...
    holder_seq      INTEGER NOT NULL,          -- row number within the section
    holder_name     TEXT NOT NULL,             -- as filed (spelling varies between companies)
    promoter_type   TEXT,                      -- 'Promoter' / 'Promoter Group'; NULL for public holders and pre-2019 filings
    shares          REAL,
    pct             REAL CHECK(pct BETWEEN 0 AND 100),   -- % of total shares, as filed
    source_url      TEXT,
    fetched_at      TEXT NOT NULL,
    PRIMARY KEY (sid, end_date, filed_at, holder_category, holder_seq)
);
CREATE INDEX IF NOT EXISTS idx_shp_holders_name ON shareholding_holders(holder_name, end_date);

-- Forward record of the investor-playbook sleeves (sleeves.py): which stocks each sleeve
-- held on each day, written after the morning run by tools/playbook_backtest --record.
-- Append-only; the only evidence on the sleeves that is free of hindsight and survivorship.
CREATE TABLE IF NOT EXISTS playbook_members (
    sid           TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date TEXT NOT NULL,
    sleeve        TEXT NOT NULL,             -- sleeves.SLEEVES key, or 'flagged' (the red-flag veto set)
    in_sleeve     INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (sid, snapshot_date, sleeve)
);
CREATE INDEX IF NOT EXISTS idx_playbook_members_date ON playbook_members(snapshot_date, sleeve);

CREATE TABLE IF NOT EXISTS short_selling_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sid TEXT REFERENCES stocks(sid),
    symbol TEXT NOT NULL,
    short_date TEXT NOT NULL,
    quantity REAL,
    fetched_at TEXT DEFAULT (datetime('now')),
    UNIQUE(symbol, short_date)
);
CREATE INDEX IF NOT EXISTS idx_short_date ON short_selling_data(short_date);
CREATE INDEX IF NOT EXISTS idx_short_sid ON short_selling_data(sid);

CREATE TABLE IF NOT EXISTS signal_lineage (
        sid              TEXT NOT NULL,
        snapshot_date    TEXT NOT NULL,
        factor           TEXT NOT NULL,
        source_table     TEXT NOT NULL,
        source_key       TEXT NOT NULL,
        source_cols      TEXT,
        column_sources   TEXT,
        contribution     TEXT,
        PRIMARY KEY (sid, snapshot_date, factor, source_table, source_key, contribution)
    );
CREATE INDEX IF NOT EXISTS idx_lineage_sid_factor ON signal_lineage(sid, factor);
CREATE INDEX IF NOT EXISTS idx_lineage_snapshot ON signal_lineage(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_lineage_source_table ON signal_lineage(source_table);

CREATE TABLE IF NOT EXISTS sloan_accruals_full_scores (sid TEXT NOT NULL REFERENCES stocks(sid), snapshot_date TEXT NOT NULL, period_end TEXT, sloan_accruals_full REAL, PRIMARY KEY (sid, snapshot_date));
CREATE INDEX IF NOT EXISTS idx_sloanfull_date ON sloan_accruals_full_scores(snapshot_date);

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

-- The same daily NSE file's rows for symbols that are NOT in `stocks`: delisted and
-- merged names, and listed ones outside our universe. Keyed by the exchange symbol
-- of the day (no sid exists). Lets a backtest date hold the stocks that traded THEN.
CREATE TABLE IF NOT EXISTS stock_prices_unlisted (
    symbol          TEXT NOT NULL,
    series          TEXT NOT NULL,
    date            TEXT NOT NULL,
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL NOT NULL,
    prev_close      REAL,
    volume          INTEGER,
    traded_value    REAL,
    num_trades      INTEGER,
    delivered_qty   INTEGER,
    delivery_pct    REAL,
    source          TEXT DEFAULT 'bhavcopy',
    PRIMARY KEY (symbol, date, series)
);
CREATE INDEX IF NOT EXISTS idx_prices_unlisted_date ON stock_prices_unlisted(date);

-- NSE's own list of symbol changes (content/equities/symbolchange.csv): a renamed
-- stock's earlier history sits under its old symbol.
CREATE TABLE IF NOT EXISTS symbol_changes (
    old_symbol      TEXT NOT NULL,
    new_symbol      TEXT NOT NULL,
    change_date     TEXT NOT NULL,
    name            TEXT,
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (old_symbol, new_symbol, change_date)
);

CREATE TABLE IF NOT EXISTS "stocks" (
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
    updated_at      TEXT DEFAULT (datetime('now')),
    mc_slug TEXT
, mc_checked_at TEXT);
CREATE INDEX IF NOT EXISTS idx_stocks_sector ON stocks(sector);
CREATE INDEX IF NOT EXISTS idx_stocks_ticker ON stocks(ticker);
CREATE INDEX IF NOT EXISTS idx_stocks_tier ON stocks(cap_tier);

CREATE TABLE IF NOT EXISTS surveillance_flags (
    sid TEXT NOT NULL,
    symbol TEXT NOT NULL,
    flag_type TEXT NOT NULL,       -- 'ASM_LT', 'ASM_ST', 'GSM', 'FNO_BAN'
    flag_date TEXT NOT NULL,
    stage TEXT,                    -- ASM stage (Stage I/II/III/IV) or null
    reason TEXT,
    fetched_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, flag_type, flag_date)
);
CREATE INDEX IF NOT EXISTS idx_surv_date ON surveillance_flags(flag_date);
CREATE INDEX IF NOT EXISTS idx_surv_type ON surveillance_flags(flag_type);

CREATE TABLE IF NOT EXISTS transcripts (
    sid           TEXT NOT NULL,
    doc_type      TEXT NOT NULL,                 -- 'transcript' | 'notes' | 'ppt'
    period_label  TEXT,                          -- raw concall label, e.g. 'Apr 2026'
    doc_date      TEXT,                          -- YYYY-MM-DD (concall month → first business day)
    announce_date TEXT,                          -- exact date parsed from PDF page 1, when found
    source_url    TEXT NOT NULL,                 -- Screener/BSE AnnPdfOpen wrapper URL (stable id)
    pdf_url       TEXT,                          -- resolved AttachLive/AttachHis PDF URL
    n_pages       INTEGER,
    char_count    INTEGER,                       -- length of raw_text (0 ⇒ extraction failed)
    raw_text      TEXT,                          -- full extracted transcript text
    sha256        TEXT,                          -- content hash of raw_text (dedup + integrity)
    fetched_at    TEXT NOT NULL, bse_filing_date TEXT,
    PRIMARY KEY (sid, source_url)
);
CREATE INDEX IF NOT EXISTS idx_transcripts_sid_date ON transcripts(sid, doc_date);

CREATE TABLE IF NOT EXISTS trust_verdicts (
    sid               TEXT NOT NULL,
    source_table      TEXT NOT NULL,
    source_key        TEXT NOT NULL,         -- JSON dict {col: value} identifying source row
    datum_class       TEXT NOT NULL,         -- e.g. 'pt_upside_pct', 'gnpa_pct', 'close'
    snapshot_date     TEXT NOT NULL,
    gate_1_identity      INTEGER,            -- Phase 2 populates
    gate_2_plausibility  INTEGER,            -- Phase 3
    gate_3_temporal      INTEGER,            -- Phase 3
    gate_4_cross_source  INTEGER,            -- Phase 4
    gate_5_unit          INTEGER,            -- Phase 4
    gate_6_lineage       INTEGER,            -- Phase 5
    gate_7_anchor        INTEGER,            -- Phase 6
    verdict_overall      TEXT,               -- TRUSTED | QUARANTINED | PENDING_REVIEW
    reasons_json         TEXT,
    computed_at          TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, source_table, source_key, datum_class, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_trust_verdicts_table_date ON trust_verdicts(source_table, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_trust_verdicts_verdict ON trust_verdicts(verdict_overall);

CREATE TABLE IF NOT EXISTS uhs_calibration_log (
    sid                TEXT NOT NULL,
    pick_date          TEXT NOT NULL,
    window_days        INTEGER NOT NULL,    -- 5, 20, 60 from pick_outcomes
    fwd_return_pct     REAL,                -- realised forward return
    uhs_score          INTEGER,             -- 0-100 score at pick_date
    uhs_label          TEXT,                -- TRUSTED/PRELIMINARY/REVIEW/AVOID
    uhs_worst_dim      TEXT,
    cap_tier           TEXT,
    written_at         TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, pick_date, window_days)
);
CREATE INDEX IF NOT EXISTS idx_uhs_cal_pick_date ON uhs_calibration_log(pick_date);
CREATE INDEX IF NOT EXISTS idx_uhs_cal_window_score ON uhs_calibration_log(window_days, uhs_score);

CREATE TABLE IF NOT EXISTS universe_eligibility (
    sid             TEXT NOT NULL,
    signal          TEXT NOT NULL,
    snapshot_date   TEXT NOT NULL DEFAULT (date('now')),
    eligible        INTEGER NOT NULL CHECK(eligible IN (0,1)),
    refreshed_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (sid, signal, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_eligibility_date ON universe_eligibility(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_eligibility_signal_date ON universe_eligibility(signal, snapshot_date);

CREATE TABLE IF NOT EXISTS vix_history (
    date            TEXT PRIMARY KEY,
    vix             REAL NOT NULL CHECK(vix > 0)
);

CREATE TABLE IF NOT EXISTS working_capital_intensity_scores (
    sid TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date TEXT NOT NULL,
    period_end TEXT,
    wc_intensity REAL,
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_wci_date ON working_capital_intensity_scores(snapshot_date);

-- ── LLM work queue + MCP audit (plan 0016) ──
-- One row per unit of LLM work. task_id = kind:item_key:input_hash (the same input is never
-- queued twice). Written only by alpha_mcp.tasks: enqueue (INSERT OR IGNORE), then status
-- changes via claim / submit / fail. payload keys starting with "_" never leave the server.
-- undo_json = what the kind's ingest changed, so rollback(kind, since) can restore it.
CREATE TABLE IF NOT EXISTS llm_tasks (
    task_id      TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    item_key     TEXT NOT NULL,
    input_hash   TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status       TEXT NOT NULL CHECK(status IN ('queued','claimed','done','invalid','failed','expired')),
    priority     INTEGER DEFAULT 5,
    deadline_at  TEXT,
    attempts     INTEGER DEFAULT 0,
    claimed_by   TEXT,
    lease_until  TEXT,
    result_json  TEXT,
    undo_json    TEXT,
    error        TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    done_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_tasks_claim ON llm_tasks(kind, status, priority);

-- Audit of every MCP tool call (alpha_mcp._core.audit): who (profile + role), what, how long.
CREATE TABLE IF NOT EXISTS mcp_calls (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    profile   TEXT NOT NULL,
    role      TEXT,
    tool      TEXT NOT NULL,
    args_hash TEXT,
    rows      INTEGER,
    ms        INTEGER,
    error     TEXT
);
CREATE INDEX IF NOT EXISTS idx_mcp_calls_ts ON mcp_calls(ts);

-- ═══════════════════════════════════════════════════════════════════════════
-- Data model v3 — ADR 0054 / plan 0017. Tables grow with concepts, not things.
-- Filled by datamodel/sync.py from the legacy tables (shadow week, 2026-09-30 →);
-- datamodel/reconcile.py records parity in check_results. Portable SQL: no tier
-- CHECK lists, JSON as TEXT read with ->>. mf.db has its own file: datamodel/mf_schema.sql.
-- ═══════════════════════════════════════════════════════════════════════════

-- ── Reference ──
CREATE TABLE IF NOT EXISTS catalog (
    catalog_id   INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,          -- feature|series|event_type|doc_type|metric|dataset|check|model
    name         TEXT NOT NULL,
    unit         TEXT,
    lo           REAL,
    hi           REAL,
    cadence      TEXT,
    lag_days     INTEGER,
    spec         TEXT,                   -- JSON: origin, enum codes, registry entry
    first_seen   TEXT NOT NULL,
    retired_at   TEXT,
    renamed_from TEXT,
    UNIQUE (kind, name)
);
CREATE TABLE IF NOT EXISTS entities (
    entity_id   INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,           -- security|sector|industry|index|market|portfolio
    key         TEXT NOT NULL,
    market      TEXT NOT NULL DEFAULT 'IN',
    name        TEXT,
    listed_on   TEXT,
    delisted_on TEXT,
    attrs       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (kind, market, key)
);
CREATE TABLE IF NOT EXISTS classifications (
    entity_id  INTEGER NOT NULL,
    scheme     TEXT NOT NULL,            -- tier|sector|industry|nifty500
    value      TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to   TEXT,                     -- NULL = current
    source     TEXT,
    run_id     INTEGER,
    PRIMARY KEY (entity_id, scheme, valid_from)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_cls_scheme ON classifications (scheme, valid_to);
CREATE TABLE IF NOT EXISTS identifiers (
    entity_id  INTEGER NOT NULL,
    namespace  TEXT NOT NULL,            -- nse_symbol|tickertape_slug|mc_slug|bse_scrip|isin|upstox
    value      TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to   TEXT,
    attrs      TEXT,
    PRIMARY KEY (namespace, value, valid_from)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_ident_entity ON identifiers (entity_id, namespace);

-- ── Bars ──
CREATE TABLE IF NOT EXISTS bars_daily (
    entity_id    INTEGER NOT NULL,
    date         TEXT NOT NULL,
    source       TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, prev_close REAL, volume REAL,
    delivery_qty REAL, delivery_pct REAL, trades REAL, turnover REAL,
    attrs        TEXT,                   -- source-specific extras (e.g. historical_universe series / requested_date)
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (entity_id, date, source)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_bars_date ON bars_daily (date);
CREATE TABLE IF NOT EXISTS derivative_bars (
    underlying_id INTEGER,
    symbol        TEXT NOT NULL,
    instrument    TEXT NOT NULL,
    expiry        TEXT NOT NULL,
    strike        REAL NOT NULL,         -- 0 for futures
    option_type   TEXT NOT NULL,         -- '' for futures
    date          TEXT NOT NULL,
    close REAL, settle REAL, underlying_price REAL, oi REAL, oi_change REAL, volume REAL, trades REAL,
    fetched_at    TEXT NOT NULL,
    PRIMARY KEY (symbol, instrument, expiry, strike, option_type, date)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_dbars_date ON derivative_bars (date);

-- ── Series (versioned: a revision appends) ──
CREATE TABLE IF NOT EXISTS series_values (
    series_id    INTEGER NOT NULL,
    date         TEXT NOT NULL,
    value        REAL,
    available_at TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (series_id, date, fetched_at)
) WITHOUT ROWID;

-- ── Events ──
CREATE TABLE IF NOT EXISTS events (
    event_id     INTEGER PRIMARY KEY,
    type_id      INTEGER NOT NULL,
    subtype      TEXT,
    entity_id    INTEGER,
    event_time   TEXT NOT NULL,
    available_at TEXT NOT NULL,
    source       TEXT NOT NULL,
    source_key   TEXT NOT NULL,
    payload      TEXT,
    fetched_at   TEXT NOT NULL,
    UNIQUE (type_id, source, source_key)
);
CREATE INDEX IF NOT EXISTS ix_events_entity ON events (entity_id, type_id, event_time);
CREATE INDEX IF NOT EXISTS ix_events_type   ON events (type_id, subtype, event_time);
CREATE TABLE IF NOT EXISTS event_links (
    event_id  INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    role      TEXT NOT NULL,
    weight    REAL,
    PRIMARY KEY (event_id, entity_id, role)
) WITHOUT ROWID;

-- ── Documents (source texts and model outputs; numbers only in `fields`) ──
CREATE TABLE IF NOT EXISTS documents (
    doc_id        INTEGER PRIMARY KEY,
    type_id       INTEGER NOT NULL,
    entity_id     INTEGER,
    event_id      INTEGER,
    parent_doc_id INTEGER,
    doc_date      TEXT NOT NULL,
    available_at  TEXT NOT NULL,
    source        TEXT NOT NULL,
    source_key    TEXT NOT NULL,
    run_id        INTEGER,
    model         TEXT,
    title         TEXT,
    fields        TEXT,
    body          BLOB,                  -- zlib-compressed text
    body_path     TEXT,
    content_hash  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'valid',   -- valid|invalid|superseded
    created_at    TEXT NOT NULL,
    UNIQUE (type_id, source, source_key, content_hash)
);
CREATE INDEX IF NOT EXISTS ix_docs_entity ON documents (entity_id, type_id, doc_date);

-- ── Company facts (versioned) ──
CREATE TABLE IF NOT EXISTS fundamentals (
    entity_id    INTEGER NOT NULL,
    metric_id    INTEGER NOT NULL,
    period_end   TEXT NOT NULL,
    period_type  TEXT NOT NULL,
    basis        TEXT NOT NULL,
    source       TEXT NOT NULL,
    value        REAL,
    available_at TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (entity_id, metric_id, period_end, period_type, basis, source, fetched_at)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS estimates (
    entity_id     INTEGER NOT NULL,
    metric_id     INTEGER NOT NULL,
    target_period TEXT NOT NULL,
    source        TEXT NOT NULL,
    value         REAL,
    label         TEXT,
    as_of         TEXT,                  -- the date the source says it is as of (monthly snapshot date)
    available_at  TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    PRIMARY KEY (entity_id, metric_id, target_period, source, fetched_at)
) WITHOUT ROWID;

-- ── Features (numeric; enums are catalog-declared codes) ──
CREATE TABLE IF NOT EXISTS feature_values (
    feature_id INTEGER NOT NULL,
    date       TEXT NOT NULL,
    entity_id  INTEGER NOT NULL,
    value      REAL,
    run_id     INTEGER NOT NULL,
    PRIMARY KEY (feature_id, date, entity_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_fv_entity ON feature_values (entity_id, date);

-- ── Decisions (appended per run) ──
CREATE TABLE IF NOT EXISTS runs (
    run_id      INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,           -- morning|forward|watchdog|reconstruct|endpoint_audit|llm|datamodel_sync
    as_of_date  TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    official    INTEGER NOT NULL DEFAULT 0,
    git_sha     TEXT,
    dirty       INTEGER,
    config_hash TEXT,
    model_id    INTEGER,
    attrs       TEXT
);
CREATE INDEX IF NOT EXISTS ix_runs_kind_date ON runs (kind, as_of_date);
CREATE TABLE IF NOT EXISTS picks (
    run_id    INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    tier      TEXT NOT NULL,
    rank      INTEGER,
    score     REAL,
    selected  INTEGER NOT NULL,
    gate      TEXT,
    uhs       REAL,
    attrs     TEXT,
    PRIMARY KEY (run_id, entity_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS pick_contributions (
    run_id       INTEGER NOT NULL,
    entity_id    INTEGER NOT NULL,
    feature_id   INTEGER NOT NULL,
    raw          REAL,
    pctile       REAL,
    weight       REAL,
    contribution REAL,                   -- share of base score; Σ over features = picks base score
    PRIMARY KEY (run_id, entity_id, feature_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS book_weights (
    run_id    INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    weight    REAL,
    attrs     TEXT,
    PRIMARY KEY (run_id, entity_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS outcomes (
    run_id       INTEGER NOT NULL,
    entity_id    INTEGER NOT NULL,
    horizon_days INTEGER NOT NULL,
    start_date   TEXT,
    end_date     TEXT,
    ret          REAL,
    bench_ret    REAL,
    excess       REAL,
    attrs        TEXT,
    computed_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, entity_id, horizon_days)
) WITHOUT ROWID;

-- ── Research ──
CREATE TABLE IF NOT EXISTS factor_tests (
    test_id      INTEGER PRIMARY KEY,
    feature_id   INTEGER NOT NULL,
    tier         TEXT NOT NULL,
    horizon_days INTEGER NOT NULL DEFAULT 0,
    method       TEXT NOT NULL,          -- ic_by_tier|horizon_gate
    source       TEXT NOT NULL,
    period_start TEXT,
    period_end   TEXT,
    n            INTEGER,
    ic           REAL,
    t_stat       REAL,
    icir         REAL,
    verdict      TEXT,
    run_id       INTEGER,
    computed_at  TEXT NOT NULL,
    attrs        TEXT,
    UNIQUE (feature_id, tier, horizon_days, method, source)
);

-- ── Ops ──
CREATE TABLE IF NOT EXISTS step_runs (
    run_id      INTEGER NOT NULL,
    step        TEXT NOT NULL,
    attempt     INTEGER NOT NULL DEFAULT 1,
    status      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    rows        INTEGER,
    error       TEXT,
    attrs       TEXT,
    PRIMARY KEY (run_id, step, attempt)
);
CREATE TABLE IF NOT EXISTS check_results (
    check_id   INTEGER NOT NULL,
    subject    TEXT NOT NULL,
    entity_id  INTEGER NOT NULL DEFAULT 0,
    date       TEXT NOT NULL,
    status     TEXT NOT NULL,
    score      REAL,
    detail     TEXT,
    run_id     INTEGER,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (check_id, subject, entity_id, date)
);
CREATE TABLE IF NOT EXISTS row_issues (
    issue_id    INTEGER PRIMARY KEY,
    dataset     TEXT NOT NULL,
    row_key     TEXT NOT NULL,
    rule        TEXT NOT NULL,
    severity    TEXT NOT NULL,           -- quarantine|review|error
    payload     TEXT,
    run_id      INTEGER,
    detected_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution  TEXT,
    UNIQUE (dataset, row_key, rule, detected_at)
);
