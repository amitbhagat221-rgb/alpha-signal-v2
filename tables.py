"""
Alpha Signal v2 — Table registry

ONE entry per table in the DB (plus file-output virtual tables that need a
freshness override). Everything the health / freshness / lineage / quarantine /
DuckDB code needs to know about a table lives here; db.py re-exports the derived
views below under their historical names.

Fields (only `kind`, `domain`, `date_col` are always present):
    kind         RAW (fetched) / COMPUTED (derived) / STATE (config, single-row) /
                 LOG (append-only audit) / QUARANTINE (Trust Pipeline mirror) / file
    domain       cockpit Data Inventory section — must be one of db.DOMAIN_ORDER
    freq         freshness cadence (daily/weekly/monthly/quarterly/annual) for tables
                 NOT fed by a PIPELINE_STEPS step with this `table` (the step's
                 `frequency` wins). A table fed only by a standalone cron MUST set
                 it, or it gets no freshness benchmark.
    data_freq    how often the underlying data changes (display only)
    source       upstream description (display only; the step's wins)
    date_col     the column freshness / date span is anchored on — the first
                 db.DATE_COLS candidate present on the table; None = no anchor
    stale_days   per-table freshness threshold, overriding the freq default
                 (db.STALENESS_THRESHOLDS) — for upstreams with a known lag
    coverage     (gap_below_pct, severe_below_pct) per-stock coverage gate: a table
                 that should have a row per universe stock flips to COVERAGE_GAP /
                 COVERAGE_SEVERE when too many sids are missing. Logged by the
                 watchdog, never auto-healed — usually structural (source doesn't
                 cover SME, harvester drops a series), not fixed by the next cron.
    best_effort  upstream can legitimately carry no fresh data — staleness is a
                 WARN, never a heal-streak CRITICAL, and the watchdog skips heals
    quarantine   gets a <table>_quarantine mirror (Trust Pipeline, Plan 0007)
    may_be_empty an EMPTY table is expected (a feature not live yet): the health
                 report shows INFO instead of the 0-row CRITICAL (checks.empty_table_severity;
                 an empty QUARANTINE mirror is always OK — nothing was quarantined)
    mirror       copied into the DuckDB read replica (tools/duckdb_refresh)
    contract     write gate (plan 0018): checked in db.insert_df / upsert_df on every
                 batch of ≥ 20 rows BEFORE it is written, on the columns the batch
                 carries — max_null {col: share}, not_all_zero [cols]. A violation
                 raises db.ContractViolation and nothing is written. Thresholds were
                 validated against every live batch since 2025-06 (they flag only the
                 2026-05-03 price=0 bulk_deals backfill).
    depth / description   Data Inventory text

Adding a table: add it to schema.sql AND here (tests/test_tables.py checks both
directions against a DB built from schema.sql).
"""

TABLES = {
    # ── Universe & Prices ──
    # F&O EOD grid + its rollup advance only on trading days, fetched the next
    # morning. MAX(trade_date) sits at Friday's session across a weekend (≈3d),
    # and a holiday adjacent to the weekend stretches it to ≈5-6d. 6 tolerates
    # that cluster yet still flags a genuinely stalled fetcher inside a week.
    "fno_bhav": {
        "contract": {"max_null": {"settle": 0.05}, "not_all_zero": ["settle", "underlying_price"]},
        "kind": "RAW", "domain": "Universe & Prices", "date_col": "trade_date", "stale_days": 6,
    },
    "fno_iv_history": {
        "kind": "COMPUTED", "domain": "Universe & Prices", "date_col": "trade_date", "stale_days": 6,
    },
    "fno_pcr_history": {
        "kind": "COMPUTED", "domain": "Universe & Prices", "date_col": "trade_date", "stale_days": 6,
    },
    # 2026-06-01: index history is trading-days only; a Fri close read on Mon
    # is ~3d old, plus nselib's T+1 posting lag → 6 tolerates a long weekend.
    # (Was untracked entirely until fetch_nse_indices became a pipeline step.)
    "nse_index_history": {
        "kind": "RAW", "domain": "Universe & Prices", "date_col": "trade_date", "stale_days": 6,
    },
    "regime_state": {
        "kind": "STATE", "domain": "Universe & Prices", "date_col": "updated_at",
        "depth": "Single row (current state)",
        "description": "Current VIX regime (CALM/NORMAL/CAUTION/CRISIS) and the corresponding tier allocation weights (alloc_large, alloc_mid, alloc_small).",
    },
    # scrip_master rebuilds the full scrip→sid map every run (updated_at=now for every
    # row) so its anchor advances daily regardless; 5 tolerates a skipped run. Fed by
    # run.sh forward (14:00 UTC, wired 2026-06-13).
    "scrip_master": {
        "kind": "RAW", "domain": "Universe & Prices", "freq": "daily", "data_freq": "daily",
        "source": "Upstox instrument master (run.sh forward)", "date_col": "updated_at",
        "stale_days": 5,
    },
    # Per-stock coverage gate (`coverage`): pre-2026-05-23 the entire 22%
    # gap on stock_prices was invisible because MAX(date) stayed FRESH for the 78%
    # that did exist.
    "symbol_changes": {
        "kind": "RAW", "domain": "Universe & Prices", "date_col": "change_date",
        "description": "NSE's list of symbol changes (old symbol, new symbol, date). Links a renamed stock's earlier price rows, stored under the old symbol, to its sid.",
    },
    "stock_prices_unlisted": {
        "kind": "RAW", "domain": "Universe & Prices", "date_col": "date",
        "description": "Daily OHLCV + delivery for every NSE symbol that is NOT in `stocks` (delisted, merged, or outside our universe), from the same bhavcopy file as stock_prices. Keyed by exchange symbol. The survivorship-free half of the price history.",
    },
    "daily_snapshots_pit_unlisted": {
        "kind": "COMPUTED", "domain": "Backtest (PIT)", "date_col": "snapshot_date",
        "description": "Price-only factors + 20-day label for every NSE symbol outside `stocks` (delisted, merged, never in the universe) at each panel anchor, keyed by symbol; tier estimated from traded value. Built by tools/unlisted_panel.py; the full-market evidence for the backtest.",
    },
    "stock_prices": {
        "contract": {"max_null": {"close": 0.02}, "not_all_zero": ["close", "volume"]},
        "kind": "RAW", "domain": "Universe & Prices", "date_col": "date", "coverage": (95.0, 80.0),
        "mirror": True,
        "depth": "3+ years (922 daily files)",
        "description": "Daily OHLCV bhavcopy per stock — open, high, low, close, volume, traded value, delivery quantity, delivery %. Foundational price table for momentum, RSI, returns, 52-week highs.",
    },
    "stocks": {
        "kind": "RAW", "domain": "Universe & Prices", "date_col": "updated_at",
        "depth": "Snapshot only",
        "description": "Universe of investable stocks (2,448 NSE-listed, ETFs excluded). Tickers, company names, sectors, market cap tiers (LARGE/MID/SMALL), and yfinance fundamentals (P/E, ROE, D/E). Single source of truth — every other table joins on `sid`.",
    },
    "universe_eligibility": {
        "kind": "COMPUTED", "domain": "Universe & Prices", "date_col": "snapshot_date",
    },
    # Mirrored from macro_history.india_vix by sources.macro_yfinance._sync_vix_history.
    "vix_history": {
        "kind": "RAW", "domain": "Universe & Prices", "freq": "daily", "data_freq": "daily",
        "source": "yfinance (^INDIAVIX)", "date_col": "date",
        "depth": "3 years daily",
        "description": "India VIX daily values from yfinance. Used by the regime classifier to determine CALM/NORMAL/CAUTION/CRISIS state and adjust LARGE/MID/SMALL portfolio allocation.",
    },

    # ── Fundamentals ──
    # Sell-side doesn't cover every SMALL → coverage gate at 60/30.
    "analyst_consensus": {
        "kind": "RAW", "domain": "Fundamentals", "date_col": "fetched_at", "coverage": (60.0, 30.0),
        "quarantine": True,
        "depth": "Latest snapshot per stock",
        "description": "Latest analyst consensus snapshot from Tickertape — price target, total analysts, buy %, forward EPS/revenue, EPS/revenue growth %. One row per stock.",
    },
    # Standalone-cron-fed (NOT in PIPELINE_STEPS). Registered 2026-06-03 after the
    # monthly snapshot cron silently no-op'd for ~a month (cd-less `python -m` →
    # ModuleNotFoundError). Written 1st business day of each month, so age oscillates
    # 0→~33d across a normal month; 40 sits above that ceiling yet flags a MISSED
    # month by ~day 40 (≈1 week into the next month) — the gap that hid the June 1
    # cron crash. See the CLAUDE.md cadence rule.
    "analyst_consensus_snapshots": {
        "kind": "RAW", "domain": "Fundamentals", "freq": "monthly", "data_freq": "monthly",
        "source": "yfinance --snapshot (standalone monthly cron, 1st biz day)",
        "date_col": "snapshot_date", "stale_days": 40, "quarantine": True,
    },
    # ── Filing-cycle-bound tables (data only moves when companies file) ──
    # Producer runs daily, but `latest_date` is the most recent end_date, which only
    # advances after a fresh filing wave. stale_days is set so the alarm fires only
    # when the EXPECTED next wave has been missed (= a real harvester problem), not on
    # the natural lag inside a wave. 2026-05-25: bumped from monthly(50) defaults
    # after they flagged STALE 55d when the data is healthy. Annual filings: ~12mo max
    # gap, 220 catches a missed cycle in ~7mo.
    "annual_balance_sheet": {
        "contract": {"max_null": {"total_assets": 0.5}},
        "kind": "RAW", "domain": "Fundamentals", "freq": "monthly", "data_freq": "annual",
        "source": "Tickertape API", "date_col": "end_date", "stale_days": 220,
        "coverage": (85.0, 70.0), "quarantine": True,
        "depth": "10 years per stock",
        "description": "Annual balance sheet from Tickertape — total assets, equity, debt, current assets/liabilities, shares outstanding, retained earnings, net PPE. Powers D/E, ROE, ROA, current ratio, book value, Altman Z, Piotroski leverage.",
    },
    "annual_cash_flow": {
        "contract": {"max_null": {"operating_cash_flow": 0.6}},
        "kind": "RAW", "domain": "Fundamentals", "freq": "monthly", "data_freq": "annual",
        "source": "Tickertape API", "date_col": "end_date", "stale_days": 220, "quarantine": True,
        "depth": "10 years per stock",
        "description": "Annual cash flow statement from Tickertape — operating CF, capex, free cash flow, financing CF, dividends paid. Powers FCF yield, Piotroski CFO/accruals quality, capex ratio.",
    },
    "banking_metrics": {
        "kind": "RAW", "domain": "Fundamentals", "date_col": "fetched_at", "quarantine": True,
    },
    "broker_recommendations": {
        "kind": "RAW", "domain": "Fundamentals", "date_col": "fetched_at", "quarantine": True,
    },
    # Tickertape stores PT only at FY year-end → annual cadence (220).
    "forecast_history": {
        "contract": {"max_null": {"value": 0.5}},
        "kind": "RAW", "domain": "Fundamentals", "freq": "monthly", "data_freq": "monthly",
        "source": "Tickertape API", "date_col": "date", "stale_days": 220, "quarantine": True,
        "depth": "Time series of revisions",
        "description": "Time series of analyst forecast revisions — price target, EPS, revenue forecasts over time. Used to compute pt_revision_1yr signal and the forecast revision chart.",
    },
    # Manual Screener.in Premium pull, roughly fortnightly. 21d gives one missed cycle
    # before alarm. Auth broken 2026-07-01 — the alarm firing daily until Amit repairs
    # it is intended (audit Data-F2). Screener.in doesn't cover all SME-board
    # smallcaps: verified 2026-05-25 100% LARGE + 100% MID; 14.8% of SMALL is
    # structurally absent — coverage gap lowered 90→85, severe at 70 still catches a
    # real regression.
    "fundamentals_screener": {
        "contract": {"max_null": {"value": 0.6}},
        "kind": "RAW", "domain": "Fundamentals", "freq": "weekly", "data_freq": "biweekly",
        "source": "Screener.in Premium (cron `screener_pull --universe`, 1st + 15th 06:00 UTC)", "date_col": "fetched_at",
        "stale_days": 21, "coverage": (85.0, 70.0),
    },
    # Quarterly filings; ~90d max gap, 120 tolerates a delayed wave.
    "quarterly_income": {
        "contract": {"max_null": {"revenue": 0.5}},
        "kind": "RAW", "domain": "Fundamentals", "freq": "monthly", "data_freq": "quarterly",
        "source": "Tickertape API", "date_col": "end_date", "stale_days": 120,
        "coverage": (85.0, 70.0), "quarantine": True,
        "depth": "10 quarters per stock",
        "description": "Quarterly income statement from Tickertape — revenue, operating expenses, EBITDA (revenue − operating expenses), operating profit, PBT, net income, EPS. Powers TTM ratios, YoY growth, Piotroski profitability factors, accruals, forensic Beneish.",
    },
    "shareholding": {
        "contract": {"max_null": {"promoter_pct": 0.5}},
        "kind": "RAW", "domain": "Fundamentals", "date_col": "end_date",
        "depth": "~6 quarters per stock (window varies by fetch date)",
        "description": "Quarterly shareholding pattern from Tickertape — promoter %, FII %, MF %, DII %, public %, pledge %, insurance %. Each stock has ~6 trailing quarters at the time it was last fetched, so the calendar span across the table looks much wider than the per-stock depth. Powers promoter signal (QoQ change).",
    },
    "shareholding_holders": {
        "contract": {"max_null": {"shares": 0.0, "pct": 0.2}, "not_all_zero": ["shares"]},
        # The newest end_date is the last quarter end until the next quarter's filings land
        # (~21 days after it ends) and the Sunday run picks them up: up to ~125 days old.
        "kind": "RAW", "domain": "Fundamentals", "date_col": "end_date", "freq": "quarterly",
        "source": "BSE shareholding-pattern XBRL (run.sh transcripts, Sunday)", "stale_days": 130,
        "depth": "XBRL filings from Jun-2016; latest quarter first, history backfilled on demand",
        "description": "Named holders above 1% per stock per quarter, as filed on BSE: promoters, mutual-fund schemes, FPIs, individuals. `filed_at` is the broadcast time (point-in-time); a revised filing adds rows with a later `filed_at`. Stocks with a BSE code only (2,199 of 2,448). Holder names are as filed — the same investor can appear under several spellings.",
    },
    "shareholding_categories": {
        "contract": {"max_null": {"promoter_pct": 0.0, "foreign_inst_pct": 0.0, "n_shareholders": 0.05},
                     "not_all_zero": ["total_shares"]},
        "kind": "RAW", "domain": "Fundamentals", "date_col": "end_date", "freq": "quarterly",
        "source": "BSE shareholding-pattern XBRL (run.sh transcripts, Sunday; --reparse from the archive)",
        "stale_days": 130,
        "depth": "XBRL filings from Jun-2016, as deep as shareholding_holders",
        "description": "Category totals per stock per filing, as filed on BSE: promoter, foreign and domestic institutions, mutual funds, insurance, small (≤ Rs 2 lakh) and large individuals, plus the number of shareholders and of small shareholders. `filed_at` is the broadcast time (point-in-time); a revision adds a row with a later `filed_at`. The deep history behind the ownership-flow factors; `shareholding` (Tickertape) holds only about two years.",
    },

    # ── Trades & Corporate ──
    # BSE corporate-announcement event stream (--days 7 keep-current), refreshed by
    # run.sh forward (14:00 UTC, wired 2026-06-13). No business-date column
    # among the DATE_COLS candidates (dt_tm isn't one) → freshness anchors on
    # fetched_at, which advances on any day the refresh inserts a NEW filing. The
    # whole-BSE firehose files most calendar days, but a weekend + adjacent holiday
    # can go quiet; 5 tolerates that, still flags a stalled cron within a few days.
    "bse_announcements": {
        "contract": {"max_null": {"headline": 0.3, "dt_tm": 0.05}},
        "kind": "RAW", "domain": "Trades & Corporate", "freq": "daily", "data_freq": "daily",
        "source": "BSE AnnSubCategoryGetData --days 7 (run.sh forward)",
        "date_col": "fetched_at", "stale_days": 5,
    },
    "bulk_deals": {
        "contract": {"max_null": {"price": 0.05, "quantity": 0.05}, "not_all_zero": ["price", "quantity"]},
        "kind": "RAW", "domain": "Trades & Corporate", "date_col": "deal_date",
        "depth": "Growing daily (no historical archive)",
        "description": "Daily bulk/block deals from NSE archives. NO HISTORICAL ARCHIVE — only today's file is fetchable, so this accumulates one day at a time.",
    },
    # Producer runs daily but the freshness anchor is fetched_at (ex_date isn't a
    # DATE_COLS candidate), which only advances on a day with a NEW ex-date row. NSE
    # announces something most trading days, but holiday clusters (Diwali, year-end)
    # can go several quiet days. 10d tolerates that yet flags a stalled fetcher.
    "corporate_actions": {
        "kind": "RAW", "domain": "Trades & Corporate", "date_col": "fetched_at", "stale_days": 10,
    },
    "corporate_adjustments": {
        "kind": "COMPUTED", "domain": "Trades & Corporate", "date_col": "fetched_at",
    },
    # FORWARD-dated board-meeting calendar; a daily nselib pull keeps near-future
    # events present so MAX(date) sits ahead of today during health. Was a one-off
    # v1-CSV import with no producer (→ 6d stale, cockpit upcoming-events widget
    # empty); wired daily 2026-06-04. 10 flags a genuinely stalled fetcher once the
    # forward buffer drains, without month-edge noise.
    "earnings_calendar": {
        "kind": "RAW", "domain": "Trades & Corporate", "date_col": "date", "stale_days": 10,
        "depth": "Forward-looking events",
        "description": "Upcoming corporate event dates from NSE — earnings, dividends, board meetings. Sparse coverage (~50 stocks at any time).",
    },
    "event_calendar": {"kind": "COMPUTED", "domain": "Trades & Corporate", "date_col": None},
    # The forward-only NSE tables below are fed by run.sh forward (14:00 UTC
    # cron), not PIPELINE_STEPS — any table whose only producer is a standalone cron
    # MUST carry `freq` here or it gets no freshness benchmark.
    # FII/DII cash + surveillance snapshots are trading-day rows published EOD; a
    # Friday read on Monday is ~3d, +T+1 publish lag. 5 tolerates that, flags a stall.
    "fii_dii_cash_flow": {
        "kind": "RAW", "domain": "Trades & Corporate", "freq": "daily", "data_freq": "daily",
        "source": "NSE FII/DII cash flow (run.sh forward)", "date_col": "fetched_at",
        "stale_days": 5,
    },
    # Reports yesterday's settled OI (inherent +1d) and is pulled days_back=3; over a
    # weekend the freshest row is ~3-4d old. 6 tolerates a long weekend + the
    # settlement lag, still flags a stalled run.sh forward.
    "fii_dii_positioning": {
        "kind": "RAW", "domain": "Trades & Corporate", "freq": "daily", "data_freq": "daily",
        "source": "NSE FII/DII F&O OI (run.sh forward)", "date_col": "trade_date",
        "stale_days": 6,
    },
    # NSE PIT insider disclosures lag the trade by WEEKS (by-trade_date is structurally
    # sparse near today): stale_days 14→30 (2026-05-25), 30→45 (2026-06-04) as the real
    # lag was measured. best_effort: NSE's corporates-pit endpoint STOPPED serving
    # recent PIT disclosures ~2026-05 (verified 2026-06-22: returns 200 + data for Apr
    # [392 rows] but ~0 for May-onward — a recent-data cliff, not a 403/block). The
    # producer runs clean but lands nothing → table frozen at trade_date 2026-05-02.
    # insider_score is NOT wired into SIGNAL_WEIGHTS (zero pick impact). Revisit when
    # a working PIT endpoint is found (NSE site archaeology).
    "insider_trades": {
        "kind": "RAW", "domain": "Trades & Corporate", "date_col": "trade_date", "stale_days": 45,
        "best_effort": True,
        "depth": "2+ years history (NSE PIT)",
        "description": "Promoter/KMP/director trades from NSE PIT API — person, transaction type, shares (`secAcq`), value (`secVal`). 1,043 stocks covered.",
    },
    # NSE posts T+1 with occasional multi-day gaps (low-activity days). Wired into
    # the daily-forward cron (run.sh forward) 2026-06-03. 7 tolerates weekend + posting lag + a quiet gap;
    # provisional — tighten after observing the first cron runs.
    "short_selling_data": {
        "kind": "RAW", "domain": "Trades & Corporate", "freq": "daily", "data_freq": "daily",
        "source": "NSE short selling (run.sh forward, wired 2026-06-03)",
        "date_col": "fetched_at", "stale_days": 7,
    },
    "surveillance_flags": {
        "kind": "RAW", "domain": "Trades & Corporate", "freq": "daily", "data_freq": "daily",
        "source": "NSE ASM/GSM/F&O-ban (run.sh forward)", "date_col": "fetched_at",
        "stale_days": 5,
    },

    # ── News & Sentiment ──
    "news_article_stocks": {
        "kind": "COMPUTED", "domain": "News & Sentiment", "freq": "daily", "data_freq": "daily",
        "source": "Entity matching on news_articles", "date_col": None,
        "depth": "Grows with news_articles",
        "description": "Entity matching: which news articles mention which stocks. Created by string matching company names + tickers against titles and summaries.",
    },
    "news_articles": {
        "contract": {"max_null": {"title": 0.01}},
        "kind": "RAW", "domain": "News & Sentiment", "date_col": "published_at",
        "depth": "Growing daily from RSS",
        "description": "RSS news articles from Economic Times and Livemint section feeds plus three Google News theme searches. Title, summary, URL, publication date.",
    },
    "news_briefs": {"kind": "COMPUTED", "domain": "News & Sentiment", "date_col": "brief_date"},
    "news_enriched": {"kind": "COMPUTED", "domain": "News & Sentiment", "date_col": "classified_at"},
    "news_themes": {
        "kind": "COMPUTED", "domain": "News & Sentiment", "date_col": "updated_at",
        "description": "The standing themes of the News page: one row per theme in config.NEWS_THEMES with its current note. Rewritten about weekly by the news_theme task.",
    },
    "news_theme_articles": {
        "kind": "COMPUTED", "domain": "News & Sentiment", "date_col": "assigned_on",
        "description": "Which theme each headline was filed under by the daily edition (NULL = read, fits no theme).",
    },
    "news_theme_history": {
        "kind": "COMPUTED", "domain": "News & Sentiment", "date_col": "as_of",
        "description": "One row per theme-note rewrite: the timeline shown on the theme page.",
    },
    "news_today": {
        "kind": "COMPUTED", "domain": "News & Sentiment", "date_col": "day",
        "description": "The daily edition of the News page: the three things that matter today, written in one pass over the day's raw headlines.",
    },
    "news_week": {
        "kind": "COMPUTED", "domain": "News & Sentiment", "date_col": "as_of",
        "description": "The weekly edition of the News page: what is new and fits no theme yet, and three sectors to favour / be careful with.",
    },
    "transcripts": {"kind": "RAW", "domain": "News & Sentiment", "date_col": "fetched_at"},

    # ── Macro ──
    "macro_history": {
        "contract": {"max_null": {"value": 0.1}, "not_all_zero": ["value"]},
        "kind": "RAW", "domain": "Macro", "date_col": "date",
        "depth": "3+ years (50 indicators)",
        "description": "Time series of 50 macro indicators (Nifty sectors, commodities, FX, rates, IIP, CPI, Core Sector, GST). Sources: yfinance + data.gov.in + FRED. Daily and monthly frequencies.",
    },
    "macro_indicator_meta": {
        "kind": "RAW", "domain": "Macro", "freq": "monthly", "data_freq": "static",
        "source": "config (indicator registry)", "date_col": None,
        "depth": "Registry (50 entries)",
        "description": "Registry of all 50 macro indicators with source, frequency, sector mapping, and units. Used by the macro signal generator to resolve indicator → sector.",
    },
    # v1-migration leftover, no v2 producer. Marked annual to silence the freshness alarm.
    "macro_indicators": {
        "kind": "COMPUTED", "domain": "Macro", "freq": "weekly", "data_freq": "monthly",
        "source": "sources/macro_official.py (MoSPI IIP + OEA core YoY → v1 thresholds)",
        "date_col": "snapshot_date",
        "depth": "One label snapshot per weekly macro run (2026-09-27 →); a 2026-04-09 v1 snapshot before",
        "description": "Per-indicator STRONG/IMPROVING/STABLE/DETERIORATING labels (+ macro_overall) from the latest official IIP and core-sector YoY. signals/macro.py reads the latest snapshot into sector scores. Indicators older than 150 days get no label.",
    },
    "macro_sector_map": {
        "kind": "RAW", "domain": "Macro", "freq": "monthly", "data_freq": "static",
        "source": "config (sector mapping)", "date_col": None,
        "depth": "Configuration (30 rules)",
        "description": "Mapping table: macro indicator → affected sector → direction (+1/-1) → weight. Translates indicator changes into sector scores.",
    },
    "macro_sector_signals": {
        "kind": "COMPUTED", "domain": "Macro", "date_col": "snapshot_date",
        "depth": "Latest snapshot per sector",
        "description": "Sector-level macro and regulatory scores (one row per sector). Combines macro indicator changes + AI-classified regulatory events.",
    },
    "sector_analyst_breadth_pit": {"kind": "COMPUTED", "domain": "Macro", "date_col": "snapshot_date"},
    "sector_force_breakdown": {"kind": "COMPUTED", "domain": "Macro", "date_col": "snapshot_date"},
    "sector_metadata": {"kind": "STATE", "domain": "Macro", "date_col": None},
    "sector_narrative_runs": {"kind": "LOG", "domain": "Macro", "date_col": None},
    "sector_policy_pit": {"kind": "COMPUTED", "domain": "Macro", "date_col": "snapshot_date"},
    "sector_sentiment_breadth_pit": {"kind": "COMPUTED", "domain": "Macro", "date_col": "snapshot_date"},

    # ── Regulatory ──
    "policy_events": {"kind": "RAW", "domain": "Regulatory", "date_col": None},
    # Anthropic Batch-API bookkeeping: written only by the API fallback (config.LLM_WORK["executor"]
    # == "api"). The default queue executor never touches it (plan 0016), so it is not tracked.
    "regulatory_batches": {"kind": "STATE", "domain": "Regulatory", "date_col": "submitted_at",
                           "best_effort": True},
    # 2026-05-23: regulatory_events was scored as "monthly" (50d) and silently went
    # stale for 43d before being noticed (Gillette dossier showing 2023 articles).
    # News/PIB are weekly cadence at worst; if the harvester stops, we want a yellow
    # flag in <2 weeks, not 50 days.
    "regulatory_events": {
        "kind": "RAW", "domain": "Regulatory", "date_col": "published_at", "stale_days": 14,
        "depth": "3 years harvested",
        "description": "Regulatory events harvested from Google News + RBI circulars + Wayback Machine + PIB. 16,523 events spanning 2023-2026. Each event has a `classifier_status` column tracking whether the AI classifier has processed it (see CLAUDE.md rule #17).",
    },
    "regulatory_signals": {
        "kind": "COMPUTED", "domain": "Regulatory", "date_col": "classified_at", "stale_days": 14,
        "depth": "Partial — ~16% of regulatory_events classified (API budget locked)",
        "description": "AI-classified sector impacts from `regulatory_events`. Stage 1 Haiku pre-filter + Stage 2 Sonnet deep classify. Each event can produce 1-N sector signals (direction, magnitude, time_horizon, confidence, reasoning). Currently 5,687 signals from 2,702 of 16,523 events; the rest is paused on Anthropic budget cap.",
    },

    # ── Computed Signals ──
    "accruals_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
        "depth": "Latest snapshot per stock",
        "description": "Cash flow accruals + balance sheet accruals + earnings persistence per stock. Measures whether reported earnings are backed by cash. Powers the accruals signal.",
    },
    "asset_tangibility_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "capex_to_dep_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "cash_conversion_cycle_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "consensus_signals": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
        "quarantine": True, "mirror": True,
        "depth": "Latest snapshot per stock",
        "description": "Computed consensus signal per stock — combines pt_upside, pt_revision_1yr, eps_growth, revenue_growth from analyst_consensus + forecast_history.",
    },
    "debt_structure_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "dio_change_yoy_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "dso_change_yoy_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "fcf_margin_scores": {"kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date"},
    "fcf_yield_scores": {"kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date"},
    "financial_signal_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "forensic_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
        "depth": "Latest snapshot per stock",
        "description": "Beneish M-Score (earnings manipulation detector, 6-factor) + Altman Z'' (bankruptcy predictor, emerging market variant) per stock. Used as a forensic penalty in the screener.",
    },
    "goodwill_to_assets_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "gross_profitability_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "insider_signals": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
        "depth": "25 months reconstructed",
        "description": "Computed monthly insider buying/selling signal per stock derived from `insider_trades`. 25 months of history reconstructed for backtesting + the current month.",
    },
    "interest_coverage_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "inventory_turnover_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "management_scores": {"kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date"},
    "playbook_members": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date", "freq": "daily",
        "source": "sleeves.py rules (run.sh morning → tools/playbook_backtest --record)",
        "depth": "From 2026-10-04 (forward record)",
        "description": "Which stocks each investor-playbook sleeve held each day (breakouts, insiders, quality, deep_value) and the red-flag set. Append-only forward record for judging the sleeves without hindsight.",
    },
    "managerial_ability_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    # Weekly (Sunday) fundamental screen. snapshot_date only advances on the weekly run,
    # so mid-week it's up to ~6d old; 10 tolerates a normal week + a holiday-shifted
    # Sunday, flags a genuinely missed weekly run.
    "multibagger_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
        "stale_days": 10,
    },
    "nlp_scores": {"kind": "COMPUTED", "domain": "Computed Signals", "date_col": None},
    "nwc_to_revenue_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "operating_margin_trend_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "piotroski_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
        "coverage": (85.0, 70.0),
        "depth": "Latest snapshot per stock",
        "description": "9-factor Piotroski F-Score per stock — profitability (3), leverage (3), efficiency (3). Range 0-9. Computed from quarterly_income + annual_balance_sheet + annual_cash_flow.",
    },
    "promoter_signals": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
        "coverage": (90.0, 70.0),
        "depth": "Latest snapshot per stock",
        "description": "Computed promoter signal per stock — QoQ change in promoter holding, trend direction, pledge quality. From `shareholding`.",
    },
    "revenue_cv_scores": {"kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date"},
    "roic_scores": {"kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date"},
    "roiic_scores": {"kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date"},
    "sales_growth_relative_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "sentiment_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
        "depth": "7-day rolling per stock",
        "description": "VADER sentiment scores from news articles, aggregated to per-stock 7-day windows.",
    },
    "sga_to_revenue_change_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "share_momentum_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "sloan_accruals_full_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },
    "smart_money_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
        "coverage": (95.0, 80.0),
        "depth": "Latest snapshot per stock",
        "description": "Composite institutional accumulation signal — bulk deal activity (60%) + delivery percentage (40%). Range 0-100.",
    },
    "working_capital_intensity_scores": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": "snapshot_date",
    },

    # ── Output ──
    "daily_changes": {
        "kind": "COMPUTED", "domain": "Output", "date_col": "change_date",
        "depth": "Growing daily",
        "description": "Output of the diff engine — what changed today vs yesterday. ENTRY/EXIT/UPGRADE/DOWNGRADE/SIGNAL_FIRED/REGIME_CHANGE events.",
    },
    "daily_picks": {
        "kind": "COMPUTED", "domain": "Output", "date_col": "pick_date", "mirror": True,
        "depth": "Latest pick_date snapshot",
        "description": "Daily output of the screener — every stock with its final_score, rank within tier, base_score, and forensic_adj. The ranked universe.",
    },
    "daily_snapshots": {
        "kind": "COMPUTED", "domain": "Output", "date_col": "snapshot_date",
        "depth": "Growing daily (PIT archive)",
        "description": "Point-in-time archive of all signal values per stock. One row per stock per pick_date. Used for diff engine + signal time series + backtesting.",
    },
    # Paper trading is not live yet: empty is expected (INFO, not a 0-row CRITICAL).
    "paper_nav_history": {"kind": "COMPUTED", "domain": "Output", "date_col": None, "may_be_empty": True},
    "paper_positions": {"kind": "STATE", "domain": "Output", "date_col": None, "may_be_empty": True},
    "paper_trades": {"kind": "COMPUTED", "domain": "Output", "date_col": "trade_date", "may_be_empty": True},
    # ── Forward-return-window-bound tables ──
    # Producer runs daily, but MAX(pick_date) only advances once a pick has a COMPLETED
    # forward return — governed by the SHORTEST window, 20 trading days ≈ 28 calendar
    # (the 5d window was dropped 2026-06-01). 35 tolerates that lag + a holiday
    # cluster, yet still flags a genuinely stalled producer in ~5wk.
    "pick_outcomes": {
        "kind": "COMPUTED", "domain": "Output", "date_col": "pick_date", "stale_days": 35,
        "mirror": True,
    },
    # Track 3.3c — same 20d shortest window as pick_outcomes; mirror its 35.
    "portfolio_outcomes": {
        "kind": "COMPUTED", "domain": "Output", "date_col": "asof_date", "stale_days": 35,
        "depth": "Per (asof_date, window) — grows as books mature",
        "description": "Realized-return head-to-head: each HRP book's close-to-close return at 20/63/126 trading-day windows under HRP weights vs equal-weight on the same names (the weighting edge) vs a tier-blended NIFTY benchmark. Evidence builds toward the gate for sizing by risk (HRP must beat the current portfolio by 1.5% risk-adjusted over 18-24 months). Advisory only.",
    },
    "portfolio_weights": {
        "kind": "COMPUTED", "domain": "Output", "date_col": "asof_date",
        "depth": "Snapshot per build date (asof_date)",
        "description": "Sized book — HRP risk-parity weights × alpha tilt over the top picks_per_tier names, under per-stock / per-sector / ₹-ADTV liquidity caps. Carries marginal_risk_contrib (percent of portfolio variance per name). ADVISORY only (no capital deployed until rank-skill validates). Built daily after the screener and backfilled across the pick history.",
    },
    "sector_briefs": {"kind": "COMPUTED", "domain": "Output", "date_col": "snapshot_date"},
    "sector_dossiers": {"kind": "COMPUTED", "domain": "Output", "date_col": "snapshot_date"},

    # ── Backtest (PIT) ──
    "daily_snapshots_pit": {
        "kind": "COMPUTED", "domain": "Backtest (PIT)", "date_col": "snapshot_date", "mirror": True,
        "depth": "Monthly anchors from 2019-12 + Friday anchors; refreshed weekly by refresh_pit_panel",
        "description": "Point-in-time factor panel rebuilt by tools/reconstruct_pit.py with filing-lag discipline (75d annual / 60d quarterly / 21d shareholding): what each factor would have said on each past date, plus the forward-return label. Continues the frozen archive (daily_snapshots_pit_v1) after 2026-02 and adds the forensic m_score and z_score.",
    },
    "daily_snapshots_pit_v1": {
        "kind": "RAW", "domain": "Backtest (PIT)", "date_col": "snapshot_date", "mirror": True,
        "depth": "35 monthly dates (Apr 2023 → Feb 2026)",
        "description": "Frozen archive of the first point-in-time panel: 1,978 stocks × 35 monthly dates × 13 factors + the 20-day forward return. Read-only history that the early factor tests were run on; the live panel is daily_snapshots_pit.",
    },
    "factor_horizon_gate": {"kind": "COMPUTED", "domain": "Backtest (PIT)", "date_col": None},
    "historical_universe": {"kind": "COMPUTED", "domain": "Backtest (PIT)", "date_col": "snapshot_date"},
    "macro_sector_signals_pit": {
        "kind": "COMPUTED", "domain": "Backtest (PIT)", "date_col": "snapshot_date",
    },
    "pit_ic_by_tier_v1": {
        "kind": "RAW", "domain": "Backtest (PIT)", "date_col": None, "mirror": True,
        "depth": "30 rows (10 signals × 3 tiers)",
        "description": "Rank-IC, t-stat and verdict per factor × cap tier from the first 36-period validation. Read-only history; current evidence is in the factor-evidence tables.",
    },
    "pit_ic_by_tier_v2": {"kind": "COMPUTED", "domain": "Backtest (PIT)", "date_col": None},
    "pit_reconstruction_log": {"kind": "LOG", "domain": "Backtest (PIT)", "date_col": "finished_at"},
    "pit_replay_snapshots": {
        "kind": "COMPUTED", "domain": "Backtest (PIT)", "date_col": "snapshot_date",
    },

    # ── Pipeline ──
    "analyst_consensus_quarantine": {
        "kind": "QUARANTINE", "domain": "Pipeline", "date_col": "fetched_at",
    },
    "analyst_consensus_snapshots_quarantine": {
        "kind": "QUARANTINE", "domain": "Pipeline", "date_col": "snapshot_date",
    },
    "annual_balance_sheet_quarantine": {
        "kind": "QUARANTINE", "domain": "Pipeline", "date_col": "end_date",
    },
    "annual_cash_flow_quarantine": {"kind": "QUARANTINE", "domain": "Pipeline", "date_col": "end_date"},
    "banking_metrics_quarantine": {"kind": "QUARANTINE", "domain": "Pipeline", "date_col": "fetched_at"},
    "broker_recommendations_quarantine": {
        "kind": "QUARANTINE", "domain": "Pipeline", "date_col": "fetched_at",
    },
    "consensus_signals_quarantine": {
        "kind": "QUARANTINE", "domain": "Pipeline", "date_col": "snapshot_date",
    },
    "external_anchors": {"kind": "RAW", "domain": "Pipeline", "date_col": "fetched_at",
                         "description": "History only: NSE-close anchors of a retired gate. The step that wrote it, "
                                        "anchor_audit, never produced a verdict and was retired; tools/reconcile.py "
                                        "does the cross-source price check daily."},
    "forecast_history_quarantine": {"kind": "QUARANTINE", "domain": "Pipeline", "date_col": "date"},
    "health_score": {"kind": "COMPUTED", "domain": "Pipeline", "date_col": "snapshot_date",
                     "description": "History only: the retired data-trust score per factor / table / "
                                    "system / pick, 2026-05 → 2026-10-02. Nothing writes it; daily_picks.uhs_* columns hold "
                                    "the per-pick values of the same period."},
    "llm_usage": {"kind": "LOG", "domain": "Pipeline", "date_col": None},
    "llm_tasks": {
        "kind": "LOG", "domain": "Pipeline", "date_col": "created_at",
        "depth": "The LLM work queue",
        "description": "One row per unit of LLM work (a regulatory headline, a news article; later a dossier or brief). Queued by `python -m alpha_mcp.tasks enqueue <kind>`, leased by a worker over the alpha-work MCP (`claim`), and written only by `submit`, which validates the result server-side and ingests it through the producer's own save path. status: queued / claimed / done / invalid / failed. undo_json lets `rollback(kind, since)` restore what an ingest changed.",
    },
    "mcp_calls": {
        "kind": "LOG", "domain": "Pipeline", "date_col": "ts",
        "depth": "Audit log of MCP tool calls",
        "description": "One row per alpha-research / alpha-ops / alpha-work MCP tool call: profile, role (ALPHA_MCP_ROLE), tool, a hash of the arguments, rows returned, latency in ms and any error. Written by a connection that may insert into this table and nothing else.",
    },
    "mf_holdings_quarantine": {"kind": "QUARANTINE", "domain": "Pipeline", "date_col": "as_of_date"},
    "mf_sector_allocation_quarantine": {
        "kind": "QUARANTINE", "domain": "Pipeline", "date_col": "as_of_date",
    },
    "feed_checks": {
        "kind": "LOG", "domain": "Pipeline", "date_col": "run_date", "freq": "daily",
        "depth": "Per-feed canary / gate verdicts (append-only)",
        "description": "One row per feed check: canary (1-item live probe before the morning run), gate or reconcile. Status PASS/WARN/FAIL/ERROR, symptom class A-H, HTTP status, rows, bytes, shape fingerprint vs the accepted baseline, and a JSON detail with the gate results and any drift diff. Read by the ops Data Supply page and the health report's feed verdicts.",
    },
    "run_events": {
        "kind": "LOG", "domain": "Pipeline", "date_col": "ts", "freq": "daily",
        "depth": "Structured run log, 90-day retention",
        "description": "One row per event of a step / cron / manual source run, keyed by run_id: run_start, request (failed or retried HTTP call with host, redacted URL, status, latency and a redacted response snippet), item_error, exception (exact file:line, symptom class, frames), summary, run_end (per-host request/status counters, retries, rows written per table, output tail), run_exit (shell exit code). Queried by the ops Data Supply page, `python -m runlog`, and agents over MCP.",
    },
    "market_events": {
        "contract": {"max_null": {"event_time": 0.0, "available_at": 0.0}},
        "kind": "RAW", "domain": "Trades & Corporate", "date_col": "fetched_at", "freq": "daily",
        "depth": "Credit ratings from 2025-01, IPO listings from 2012, index changes 1996-2020",
        "description": "One row per market event, all event streams in one table: type = credit_rating (NSE Reg-30 feed with the earlier rating, direction derived), ipo_listing (NSE past issues + anchor lock-in dates by rule), index_change (NSE inclusion/exclusion log). event_time = when it happened; available_at = when the market could know it (PIT); payload = the source row as JSON.",
    },
    "analyst_estimates": {
        "contract": {"max_null": {"value": 0.05}},
        "kind": "RAW", "domain": "Fundamentals", "date_col": "last_seen_at", "freq": "weekly",
        "depth": "Yahoo EPS estimate vs actual per report back to ~2007 (L/M), EPS trend snapshots from 2026-09",
        "description": "Versioned analyst estimates: eps_estimate / eps_actual / eps_surprise_pct per earnings report (target_period = report date), and weekly EPS-trend snapshots (current and 7/30/60/90 days ago, revisions up/down, low/high, analyst count; target_period = Yahoo period label). available_at: the fetch time for snapshots; the report time for historical rows, labelled pit_unverified until the estimate's freeze-at-report is verified.",
    },
    "pipeline_log": {
        "kind": "LOG", "domain": "Pipeline", "date_col": "run_date",
        "depth": "Per-step run history (append-only)",
        "description": "Append-only audit trail of every pipeline step run — start/end timestamps, status (RUNNING/SUCCESS/FAILED), rows affected, duration, error message. Each step writes a RUNNING row on start and a SUCCESS/FAILED row on completion.",
    },
    "quarterly_income_quarantine": {"kind": "QUARANTINE", "domain": "Pipeline", "date_col": "end_date"},
    "screener_pull_errors": {"kind": "LOG", "domain": "Pipeline", "date_col": None},
    # signal_lineage / trust_verdicts / mf_sector_allocation: registered 2026-09-26
    # (were un-benchmarked). All three are written as a side effect of pipeline steps
    # whose `table` is another table, so they carry their own freq here.
    "signal_lineage": {
        "kind": "COMPUTED", "domain": "Pipeline", "freq": "daily", "data_freq": "daily",
        "source": "db.emit_lineage from signal modules", "date_col": "snapshot_date",
    },
    "sqlite_sequence": {
        "kind": "STATE", "domain": "Pipeline", "date_col": None,
        "depth": "Internal",
        "description": "Internal SQLite table tracking AUTOINCREMENT counters. Not user-facing.",
    },
    "trust_verdicts": {
        "kind": "COMPUTED", "domain": "Pipeline", "freq": "daily", "data_freq": "daily",
        "source": "the write-time gates (validators._verdicts.GATES: identity, plausibility) called by "
                  "yfinance_analyst, banking_metrics, moneycontrol_recos, mf_holdings; the gate_3..7 columns are history",
        "date_col": "snapshot_date",
    },
    # Rows mature on a 20d forward window (pick_outcomes join), so MAX(date) is
    # structurally ~1 month old even when the producer is healthy. 45d tolerates that
    # lag and only alarms on true death (audit Data-F5).
    "uhs_calibration_log": {
        "kind": "COMPUTED", "domain": "Pipeline", "date_col": "pick_date", "stale_days": 45,
        "description": "History only: the retired trust score against forward return; it never reached the 6 months it needed.",
    },

    # ── Other ──
    "mf_calendar_returns": {
        "kind": "COMPUTED", "domain": "Other", "date_col": None,
        "depth": "Per-scheme per-calendar-year",
        "description": "Yearly returns table for the bar chart on the detail page. PK (scheme_code, year).",
    },
    "mf_category_stats": {
        "kind": "COMPUTED", "domain": "Other", "date_col": "as_of_date",
        "depth": "One row per (category_norm, as_of_date)",
        "description": "Category aggregates — median 1Y/3Y/5Y returns, median Sharpe, top/bottom decile cuts. Powers the heatmap on /mutual-funds and peer-rank comparisons.",
    },
    "mf_holdings": {"kind": "RAW", "domain": "Other", "date_col": "as_of_date", "quarantine": True},
    "mf_metrics": {
        "kind": "COMPUTED", "domain": "Other", "date_col": "as_of_date",
        "depth": "One row per (scheme_code, as_of_date); recomputed monthly",
        "description": "Per-scheme returns + risk snapshot. 1Y/3Y/5Y/10Y CAGR, Sharpe, Sortino, max drawdown, peer rank, plus composite_score (0-100 within category) with 4-way breakdown (3Y CAGR / Sharpe 3Y / max DD / rolling consistency).",
    },
    "mf_nav_history": {
        "kind": "RAW", "domain": "Other", "date_col": "fetched_at",
        "depth": "~13y daily NAV per scheme (mfapi.in backfill) + ongoing daily (AMFI)",
        "description": "Per-scheme NAV time series. PK (scheme_code, nav_date). Bootstrap fills via mfapi.in; daily incremental via AMFI NAVAll.txt.",
    },
    "mf_rolling_returns": {
        "kind": "COMPUTED", "domain": "Other", "date_col": "anchor_date",
        "depth": "Monthly anchors (~60 per scheme), 3Y + 5Y rolling CAGR each",
        "description": "Rolling 3Y and 5Y CAGR sampled on the first business day of each month, plus a flag for whether the rolling window beat category median. Drives the rolling-returns charts + the consistency component of composite_score.",
    },
    "mf_scheme_master": {
        "kind": "RAW", "domain": "Other", "date_col": "fetched_at",
        "depth": "~14,364 active Indian MF schemes (refreshed weekly from AMFI NAVAll.txt)",
        "description": "Authoritative MF universe from AMFI. One row per scheme: code, ISINs, name, AMC, raw + normalised category, plan_type (Direct/Regular), option_type (Growth/IDCW), last_seen, active flag.",
    },
    "mf_schemes": {
        "kind": "RAW", "domain": "Other", "date_col": "fetched_at",
        "depth": "Subset of mf_scheme_master with full backfilled history",
        "description": "Compat table from v0 — tracks scheme metadata (inception_date, has_full_history) for schemes we've backfilled via mfapi.in. Functionally a join key with mf_scheme_master.",
    },
    "mf_sector_allocation": {
        "kind": "RAW", "domain": "Other", "freq": "monthly", "data_freq": "monthly",
        "source": "Scraped with mf_holdings (fetch_mf_holdings step)", "date_col": "as_of_date",
        "quarantine": True,
    },

    # ── File outputs (virtual tables from config.FILE_OUTPUTS) ──
    # DuckDB replica rebuilds nightly via the run.sh morning cron tail (non-fatal on
    # failure). 2d catches a failed/stale rebuild quickly without false-alarming on
    # same-day timing drift (audit Data-F10).
    "_file_duckdb_replica": {"kind": "file", "domain": "Output", "date_col": None, "stale_days": 2},
    "_file_db_backup": {"kind": "file", "domain": "Output", "date_col": None, "stale_days": 2},
    # ── Data model v3 (ADR 0054 / plan 0017) — shadow tables filled by datamodel/sync.py from the
    # legacy tables and reconciled daily (datamodel/reconcile.py → check_results). Timeless for the
    # freshness scan except bars_daily (a stalled sync shows there); parity is the health signal.
    "bars_daily": {
        "kind": "COMPUTED", "domain": "Universe & Prices", "date_col": "date", "freq": "daily", "stale_days": 6,
        "best_effort": True,
        "description": "Daily OHLCV for securities and indices (v3; mirror of stock_prices + nse_index_history, source in the PK).",
    },
    "catalog": {
        "kind": "COMPUTED", "domain": "Universe & Prices", "date_col": None,
        "description": 'Every name the system knows (features, metrics, series, event/doc types, datasets, checks) with an append-only integer id; generated from the code registries and the legacy columns the sync maps.',
    },
    "entities": {
        "kind": "COMPUTED", "domain": "Universe & Prices", "date_col": None,
        "description": 'Anything a value can be about: securities (incl. dead names), sectors, industries, indices, the market, the book.',
    },
    "classifications": {
        "kind": "COMPUTED", "domain": "Universe & Prices", "date_col": None,
        "description": 'SCD2 history of tier / sector / industry / Nifty-500 membership (valid_from, valid_to). Seeded 2026-09-30 from stocks + daily_picks history.',
    },
    "identifiers": {
        "kind": "COMPUTED", "domain": "Universe & Prices", "date_col": None,
        "description": 'External ids per entity over time: NSE symbol, Tickertape slug, Moneycontrol slug, BSE scrip, ISIN.',
    },
    "derivative_bars": {
        "kind": "COMPUTED", "domain": "Universe & Prices", "date_col": None,
        "description": "F&O EOD grid (mirror of fno_bhav; strike 0 / option_type '' for futures).",
    },
    "series_values": {
        "kind": "COMPUTED", "domain": "Macro", "date_col": None,
        "description": 'Entity-less observations (macro, FII/DII flows), versioned: a revision appends a row (fetched_at + last_seen_at).',
    },
    "events": {
        "kind": "COMPUTED", "domain": "Trades & Corporate", "date_col": None,
        "description": 'Point-in-time occurrences (BSE announcements, corporate actions, insider trades, bulk deals, short selling, surveillance, earnings dates, regulatory/policy events, news, broker recos, market events) with event_time, available_at and a JSON payload.',
    },
    "event_links": {
        "kind": "COMPUTED", "domain": "Trades & Corporate", "date_col": None,
        "description": 'An event about several entities (news → stocks).',
    },
    "documents": {
        "kind": "COMPUTED", "domain": "News & Sentiment", "date_col": None,
        "description": 'Source texts and model outputs (transcripts, news classifications, regulatory labels, briefs, sector dossiers, free-text feature attributes); numbers only in `fields`.',
    },
    "fundamentals": {
        "kind": "COMPUTED", "domain": "Fundamentals", "date_col": None,
        "description": 'Reported company facts (statements, Screener line items, bank metrics, shareholding pattern), versioned; available_at = period_end + filing lag.',
    },
    "estimates": {
        "kind": "COMPUTED", "domain": "Fundamentals", "date_col": None,
        "description": 'Forward-looking opinions (PTs, EPS/revenue estimates, recos), versioned; the monthly snapshot is a view.',
    },
    "feature_values": {
        "kind": "COMPUTED", "domain": "Computed Signals", "date_col": None,
        "description": 'Every derived number: feature × date × entity, slice-replaced per (feature, date); enums are catalog-declared codes.',
    },
    "runs": {
        "kind": "COMPUTED", "domain": "Output", "date_col": None,
        "description": 'One row per run (morning, watchdog, reconstruct, …) with git sha and attrs; decisions hang off run_id.',
    },
    "picks": {
        "kind": "COMPUTED", "domain": "Output", "date_col": None,
        "description": 'Every ranked stock per run: tier, rank, score, selected, gate.',
    },
    "pick_contributions": {
        "kind": "COMPUTED", "domain": "Output", "date_col": None,
        "description": 'Per pick × factor: raw input, within-tier percentile, weight, contribution (Σ = base score). Rebuilt from pit_replay inputs and kept only when the rebuilt score matches daily_picks.',
    },
    "book_weights": {
        "kind": "COMPUTED", "domain": "Output", "date_col": None,
        "description": 'HRP book weights per run.',
    },
    "outcomes": {
        "kind": "COMPUTED", "domain": "Output", "date_col": None,
        "description": 'Forward returns per run × entity (a security, or the book) × horizon.',
    },
    "factor_tests": {
        "kind": "COMPUTED", "domain": "Backtest (PIT)", "date_col": None,
        "description": 'Evidence about features: IC by tier, horizon gate.',
    },
    "step_runs": {
        "kind": "COMPUTED", "domain": "Pipeline", "date_col": None,
        "description": 'One row per step attempt within a run (pipeline, watchdog heals, endpoint audits, PIT reconstructions, LLM batches).',
    },
    "check_results": {
        "kind": "COMPUTED", "domain": "Pipeline", "date_col": None,
        "description": 'Check outcomes per subject and date: feed checks, health-check history, data-model parity.',
    },
    "row_issues": {
        "kind": "COMPUTED", "domain": "Pipeline", "date_col": None,
        "description": 'Rows rejected or flagged (quarantine, trust-gate failures, pull errors), with the row as JSON and a resolution slot.',
    },
}



# ── Dataset kind (plan 0015 H3, ADR 0052 Dataset block) — DERIVED ──
# `kind` above is provenance (RAW / COMPUTED / …). The dataset kind is semantics,
# inferred from the table's PRIMARY KEY in schema.sql, never hand-kept:
#
#   event    append-only facts: a surrogate / event-id key (bulk deal, filing,
#            news article). Write rule: insert-or-ignore; never updated.
#   series   entity × date [× source] observations fetched from outside.
#   state    entity → current value (no date in the key): stocks, analyst_consensus.
#   feature  derived per entity × date (COMPUTED with a date in the key).
#   log      runner / audit trails and quarantine mirrors (append).
#
# Vintage rule for series (documented, NOT yet enforced — plan 0015 Phase 3
# finding "invariant 1 is approximate"): an exact as-of read needs first-seen
# timestamps. A series row is insert-only and carries `fetched_at` (when WE first
# saw it); a restatement or backfill is a NEW row (new fetched_at), never an
# in-place UPDATE. asof(series, t) = for each key, the row with the latest
# fetched_at <= t among rows whose business date + availability lag <= t.
# Today statement tables are upserted in place, so a replay applies
# `end_date + lag` to today's (restated) values; the rule removes that gap.
DATASET_KINDS = ("event", "series", "state", "feature", "log")

# Explicit overrides — only where the PK shape says something else.
DATASET_KIND_OVERRIDES = {
    # A broker call / surveillance flag / policy event / corporate event is a
    # one-off fact even though a date sits in its key.
    "broker_recommendations": "event",
    "surveillance_flags": "event",
    "policy_events": "event",
    "event_calendar": "event",
    # The archived v1 PIT panel is derived per sid × date (provenance says RAW
    # only because it was imported, not computed here).
    "daily_snapshots_pit_v1": "feature",
}

# Key columns that identify an event (not an entity) when no date is in the key.
_EVENT_KEYS = {"article_id", "news_id", "event_id", "source_url"}


def _is_date_key(col):
    return col == "date" or col.endswith("_date") or col in ("period", "period_end", "year")


def dataset_kind(table, pk, provenance, date_col=None, autoincrement=False):
    """The one dataset kind of a table from its PK columns and provenance."""
    if table in DATASET_KIND_OVERRIDES:
        return DATASET_KIND_OVERRIDES[table]
    if provenance in ("LOG", "QUARANTINE"):
        return "log"
    if provenance == "STATE":
        return "state"
    if autoincrement:                       # surrogate id: one row per fact
        return "event"
    keys = list(pk) or ([date_col] if date_col else [])
    if any(_is_date_key(c) for c in keys):
        return "feature" if provenance == "COMPUTED" else "series"
    if any(c in _EVENT_KEYS for c in keys):
        return "feature" if provenance == "COMPUTED" else "event"
    return "state"


def dataset_kinds(conn=None):
    """{table: dataset kind} for every table in TABLES (file outputs excluded),
    reading PKs from `conn` or, by default, from a DB built from schema.sql."""
    import sqlite3
    own = conn is None
    if own:
        from config import SCHEMA_PATH
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA_PATH.read_text())
    try:
        out = {}
        for t, e in TABLES.items():
            if e["kind"] == "file":
                continue
            info = conn.execute(f"PRAGMA table_info([{t}])").fetchall()
            pk = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5] > 0]
            ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()
            auto = bool(ddl and ddl[0] and "AUTOINCREMENT" in ddl[0].upper())
            out[t] = dataset_kind(t, pk, e["kind"], e.get("date_col"), auto)
        return out
    finally:
        if own:
            conn.close()


# ── Derived views (historical names, re-exported by db) ──

TABLE_META = {t: {k: e[k] for k in ("kind", "depth", "description") if k in e}
              for t, e in TABLES.items() if e["kind"] != "file"}
TABLE_DOMAIN = {t: e["domain"] for t, e in TABLES.items() if e["kind"] != "file"}
STALENESS_OVERRIDES = {t: e["stale_days"] for t, e in TABLES.items() if "stale_days" in e}
COVERAGE_THRESHOLDS = {t: e["coverage"] for t, e in TABLES.items() if "coverage" in e}
BEST_EFFORT_STALE = {t for t, e in TABLES.items() if e.get("best_effort")}
QUARANTINE_SOURCE_TABLES = [t for t, e in TABLES.items() if e.get("quarantine")]
DUCKDB_MIRRORED_TABLES = frozenset(t for t, e in TABLES.items() if e.get("mirror"))
RAW_TABLES = [
    {"table": t, "source": e.get("source", "—"), "data_freq": e.get("data_freq", "—"),
     "frequency": e["freq"]}
    for t, e in TABLES.items() if e.get("freq")
]
