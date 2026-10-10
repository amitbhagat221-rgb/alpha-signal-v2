"""
Alpha Signal v2 — Feeds: every external data stream, declared once (plan 0018).

hosts.py says HOW POLITELY we call a host; tables.py says WHAT a table is;
factors.py says what a factor is. This file says WHERE OUR DATA COMES FROM and
what happens when a source breaks — the data-supply map, in one place.

A feed is one data stream (not one host, not one table): nse_bhavcopy is a feed,
Tickertape fundamentals is a feed. Each entry:

    family      what kind of data it delivers (FAMILIES; lines up with plan 0017 concepts)
    status      wanted → candidate → probation → production → degraded → retired
    what        one line, plain English
    modules     sources/ modules that implement it
    schedule    "step:<PIPELINE_STEPS name>" | "cron:<run.sh job>" | "manual"
    writes      the tables it delivers (its primary outputs, not side columns)
    hosts       hosts.HOSTS keys it calls
    cadence     trading_day | daily | weekly | fortnightly | monthly | quarterly | manual
    routes      ordered sources: kind ∈ primary | fallback (independent, full) |
                gap-fill (partial) | manual (a human drops a file)
    serve_stale_days   how long consumers may run on the last good data
    canary      key into sources/canaries.CANARIES (a 1-item live probe), or None
    canary_waiver      why there is no canary (required when canary is None)
    derived_from       for in-house derivations (no host): the upstream feed(s)
    pit, tos, fallback_plan, notes, probe, ref   — free text / evidence

DERIVED, never hand-typed (plan 0018 D1):
    tier(feed)      T1 critical / T2 important / T3 probation — from the graph
    SYMPTOM_CLASSES / INCIDENTS  — the known-issue playbook the DQ agent follows

tests/test_feeds.py holds the registry to the code: every sources/ module, every
source step and every RAW table maps to a feed; every production feed is scheduled;
every T1 feed has a fallback or a serve-stale limit and a live canary.
Plain dicts (ADR 0004).
"""

FAMILIES = {
    # key: (label, what it delivers, plan-0017 concept that decides write + PIT rule)
    "reference":    ("Reference",          "who exists: universe, identifiers, crosswalks", "reference"),
    "prices":       ("Prices & market",    "bars, delivery, F&O, market structure, indices", "bars / series"),
    "fundamentals": ("Fundamentals",       "financial statements, results, sector KPIs", "fundamentals"),
    "ownership":    ("Ownership",          "shareholding, insider trades, bulk/block deals", "fundamentals / events"),
    "estimates":    ("Estimates",          "analyst consensus, forecasts, broker calls", "estimates"),
    "events":       ("Events & documents", "announcements, corporate actions, ratings, transcripts", "events / documents"),
    "macro":        ("Macro & flows",      "macro series, FII/DII flows, real-economy nowcasts", "series"),
    "news":         ("News",               "articles, regulatory items and their LLM enrichment", "documents"),
    "funds":        ("Funds",              "mutual-fund NAV, holdings, metadata", "series / fundamentals"),
}

STATUSES = ("wanted", "candidate", "probation", "production", "degraded", "retired")
LIVE = ("probation", "production", "degraded")          # feeds that run on a schedule
DISCOVERY = ("wanted", "candidate")
ROUTE_KINDS = ("primary", "fallback", "gap-fill", "manual")
CADENCES = ("trading_day", "daily", "weekly", "fortnightly", "monthly", "quarterly", "manual")
TIERS = ("T1", "T2", "T3")
TIER_LABEL = {"T1": "Critical", "T2": "Important", "T3": "Probation"}
CANARY_EVERY = {"T1": "daily", "T2": "weekly"}           # plan 0018 D4 (T3 → on demand)

REF = "RELIANCE"   # canary item: large, liquid, covered by every source


def _r(id, kind, host, how):
    return {"id": id, "kind": kind, "host": host, "how": how}


FEEDS = {
    # ═══════════════════════════════ Reference ═══════════════════════════════
    "universe_liveness": {
        "family": "reference", "status": "production",
        "what": "Which stocks in our universe are still trading",
        "modules": ["sources.universe"], "schedule": ["step:universe_liveness"],
        "writes": ["stocks"], "hosts": [], "cadence": "trading_day",
        "derived_from": ["nse_bhavcopy"], "routes": [],
        "canary": None, "canary_waiver": "derived in-house from stock_prices",
        "serve_stale_days": 5,
    },
    "scrip_master": {
        "family": "reference", "status": "production",
        "what": "Matches BSE codes to NSE symbols so filings link to the right stock",
        "modules": ["sources.scrip_master"], "schedule": ["cron:forward"],
        "writes": ["scrip_master"], "hosts": ["upstox", "github_raw"], "cadence": "daily",
        "routes": [_r("upstox_instruments", "primary", "upstox", "complete.json.gz instrument master"),
                   {**_r("bse_listofscrips", "fallback", "github_raw", "ListOfScrips.csv mirror"),
                    "dead": "2026-09-28: GitHub mirror 404 (canary)"}],
        "canary": "scrip_master", "serve_stale_days": 30,
        "pit": "static map; delisted scrips kept", "tos": "public files",
    },

    # ═══════════════════════════════ Prices & market ═══════════════════════════════
    "nse_bhavcopy": {
        "family": "prices", "status": "production",
        "what": "Daily prices, volume and delivery % for every NSE stock — the main price source",
        "modules": ["sources.nse"], "schedule": ["step:fetch_bhavcopy"],
        "writes": ["stock_prices", "stock_prices_unlisted", "symbol_changes"], "hosts": ["nse_archives"], "cadence": "trading_day",
        "routes": [_r("nse_sec_bhavdata", "primary", "nse_archives", "archives sec_bhavdata_full_{DDMMYYYY}.csv"),
                   _r("yfinance_gapfill", "gap-fill", "yahoo", "fetch_prices_fallback: only sids NSE lacks"),
                   _r("nse_legacy_archive", "gap-fill", "nse_archives", "history before 2020: historical/EQUITIES cm{DD}{MMM}{YYYY}bhav.csv.zip (no delivery)")],
        "serve_stale_days": 1, "canary": "nse_bhavcopy",
        "pit": "file date (published ~18:30 IST, T+0)", "tos": "public exchange archive",
        "fallback_plan": "HF tejhq adjusted parquet or BSE bhavcopy as a FULL fallback (research 0005 ✅ probed)",
    },
    "yfinance_prices": {
        "family": "prices", "status": "production",
        "what": "Prices for the stocks NSE files miss (REITs, InvITs, BSE-only, new listings)",
        "modules": ["sources.yfinance_prices"], "schedule": ["step:fetch_prices_fallback"],
        "writes": ["stock_prices"], "hosts": ["yahoo"], "cadence": "trading_day",
        "routes": [_r("yfinance_history", "primary", "yahoo", "yf.download .NS then .BO")],
        "serve_stale_days": 3, "canary": "yfinance_prices",
        "pit": "bar date", "tos": "unofficial public API",
    },
    "fno_bhav": {
        "family": "prices", "status": "production",
        "what": "Daily futures & options prices and open interest",
        "modules": ["sources.fno_pull"], "schedule": ["step:fetch_fno_bhav", "step:compute_fno_pcr"],
        "writes": ["fno_bhav", "fno_pcr_history"], "hosts": ["nse", "nse_archives"], "cadence": "trading_day",
        "routes": [_r("nselib_fno_bhav", "primary", "nse", "nselib.derivatives.fno_bhav_copy (UDiFF)"),
                   _r("nse_legacy_fo", "gap-fill", "nse_archives", "history before 2024-07-15: historical/DERIVATIVES "
                      "fo{DD}{MMM}{YYYY}bhav.csv.zip — index options + futures only, index level from nse_index_history")],
        "serve_stale_days": 2, "canary": "fno_bhav",
        "pit": "trade date", "tos": "public exchange data",
        "fallback_plan": "nsearchives UDiFF / legacy fo{DD}{MMM}{YYYY}bhav.csv.zip direct (research 0005 ✅)",
    },
    "fno_iv": {
        "family": "prices", "status": "production",
        "what": "Option implied volatility, calculated from the stored option prices",
        "modules": ["sources.fno_iv"], "schedule": ["step:compute_fno_iv"],
        "writes": ["fno_iv_history"], "hosts": [], "cadence": "trading_day",
        "derived_from": ["fno_bhav"], "routes": [],
        "canary": None, "canary_waiver": "derived in-house from fno_bhav", "serve_stale_days": 2,
    },
    "nse_indices": {
        "family": "prices", "status": "production",
        "what": "Daily levels of NSE indices (Nifty 50, Midcap 150, Smallcap 250…)",
        "modules": ["sources.nselib_pull"], "schedule": ["step:fetch_nse_indices"],
        "writes": ["nse_index_history"], "hosts": ["nse"], "cadence": "trading_day",
        "routes": [_r("nselib_index_data", "primary", "nse", "nselib cm.index_data")],
        "serve_stale_days": 3, "canary": "nse_indices",
        "pit": "trade date", "tos": "public exchange data",
    },
    "nse_market_daily": {
        "family": "prices", "status": "production",
        "what": "Daily FII/DII flows, short selling and surveillance lists (NSE keeps no history — a missed day is lost)",
        "modules": ["sources.nselib_pull"], "schedule": ["cron:forward"],
        "writes": ["short_selling_data", "fii_dii_cash_flow", "fii_dii_positioning", "surveillance_flags"],
        "hosts": ["nse"], "cadence": "trading_day",
        "routes": [_r("nse_api_daily", "primary", "nse", "fiidiiTradeReact, reportASM/GSM, nselib short-selling")],
        "serve_stale_days": 3, "canary": "nse_market_daily",
        "pit": "trade date; NO historical archive — a missed day is lost", "tos": "public exchange data",
    },

    # ═══════════════════════════════ Fundamentals ═══════════════════════════════
    "tickertape_fundamentals": {
        "family": "fundamentals", "status": "production",
        "what": "Company financial statements: quarterly results, balance sheet, cash flow",
        "modules": ["sources.tickertape"], "schedule": ["cron:tickertape"],
        "writes": ["quarterly_income", "annual_balance_sheet", "annual_cash_flow"],
        "hosts": ["tickertape"], "cadence": "monthly",
        "routes": [_r("bharat_sm_data", "primary", "tickertape", "Bharat_sm_data Tickertape client (internal JSON)")],
        "serve_stale_days": 45, "canary": "tickertape_fundamentals",
        "pit": "period end + filing lag (factors.FACTORS filing_lag)", "tos": "unofficial public API",
        "fallback_plan": "Screener exports (already harvested) → NSE results XBRL (research 0005 ✅). "
                         "Bharat_sm_data last released 2025-07: the top single-source risk",
    },
    "screener_fundamentals": {
        "family": "fundamentals", "status": "production",
        "what": "Company financials from Screener.in (our paid account)",
        "modules": ["sources.screener_pull", "sources.screener_schedules"],
        "schedule": ["cron:screener_universe", "cron:screener_cookie", "cron:screener_schedules"],
        "writes": ["fundamentals_screener", "shareholding"], "hosts": ["screener"], "cadence": "fortnightly",
        "routes": [_r("screener_export", "primary", "screener", "session cookie → per-stock Excel export")],
        "serve_stale_days": 45, "canary": "screener",
        "pit": "period end; no filing timestamp (lag rule)", "tos": "our paid Premium account",
        "notes": "Session has a fixed ~30-day life; cron:screener_cookie re-logs in 3x/day. "
                 "screener_schedules ('+' rows: Intangible Assets …) runs quarterly in two resumable night windows "
                 "(scheduled 2026-09-28; had been manual-only, Intangible Assets 4.5 months stale)",
    },
    "banking_metrics": {
        "family": "fundamentals", "status": "production",
        "what": "Bank and NBFC ratios (bad loans, margins, capital) from Screener",
        "modules": ["sources.banking_metrics"], "schedule": ["step:fetch_banking_metrics"],
        "writes": ["banking_metrics"], "hosts": ["screener"], "cadence": "monthly",
        "routes": [_r("screener_pages", "primary", "screener", "company page ratio tables")],
        "serve_stale_days": 60, "canary": "screener",
        "pit": "quarter end + lag", "tos": "our paid Premium account",
    },

    # ═══════════════════════════════ Ownership ═══════════════════════════════
    "tickertape_shareholding": {
        "family": "ownership", "status": "production",
        "what": "Who owns each company each quarter (promoters, FIIs, funds, public, pledges)",
        "modules": ["sources.tickertape_shareholding"], "schedule": ["step:fetch_shareholding"],
        "writes": ["shareholding"], "hosts": ["tickertape"], "cadence": "monthly",
        "routes": [_r("bharat_sm_data_shp", "primary", "tickertape", "get_share_holding_pattern(slug)")],
        "serve_stale_days": 60, "canary": "tickertape_shareholding",
        "pit": "quarter end + ~21d filing lag", "tos": "unofficial public API",
        "fallback_plan": "BSE Corp_Shareholding_ng XBRL — also adds retail COUNTS (research 0005 ✅)",
    },
    "nse_insider": {
        "family": "ownership", "status": "production",
        "what": "Insider buying and selling disclosed to NSE",
        "modules": ["sources.nse_insider"], "schedule": ["step:fetch_insider"],
        "writes": ["insider_trades"], "hosts": ["nse", "nse_archives"], "cadence": "daily",
        "routes": [_r("nse_pit_gg", "primary", "nse", "api/corporates-pit-gg + XBRL")],
        "serve_stale_days": 7, "canary": "nse_insider",
        "pit": "broadcast time", "tos": "public exchange data",
    },
    "nse_bulk_deals": {
        "family": "ownership", "status": "production",
        "what": "Large bulk and block deals (NSE keeps no history — collected daily)",
        "modules": ["sources.nse_bulk"], "schedule": ["step:fetch_bulk_deals"],
        "writes": ["bulk_deals"], "hosts": ["nse_archives"], "cadence": "trading_day",
        "routes": [_r("nse_bulk_csv", "primary", "nse_archives", "content/equities/bulk.csv + block.csv"),
                   _r("nselib_bulk_range", "fallback", "nse", "nselib cm.bulk_deal_data date range")],
        "serve_stale_days": 3, "canary": "nse_bulk_deals",
        "pit": "deal date", "tos": "public exchange archive",
    },

    # ═══════════════════════════════ Estimates ═══════════════════════════════
    "tickertape_analyst": {
        "family": "estimates", "status": "production",
        "what": "Analyst ratings and earnings forecasts from Tickertape",
        "modules": ["sources.tickertape_analyst"], "schedule": ["step:fetch_analyst"],
        "writes": ["forecast_history", "analyst_consensus"], "hosts": ["tickertape"], "cadence": "monthly",
        "routes": [_r("tickertape_next_data", "primary", "tickertape", "tickertape.in/{slug} __NEXT_DATA__")],
        "serve_stale_days": 45, "canary": "tickertape_analyst",
        "pit": "snapshot date; the 'price' metric is NOT ingested (ADR 0045)", "tos": "public page",
        "fallback_plan": "Yahoo earnings_estimate (partial) — else serve stale",
    },
    "yfinance_analyst": {
        "family": "estimates", "status": "production",
        "what": "Analyst price targets from Yahoo (weekly, plus a monthly snapshot)",
        "modules": ["sources.yfinance_analyst"], "schedule": ["step:fetch_yf_analyst", "cron:pt_snapshot"],
        "writes": ["analyst_consensus", "analyst_consensus_snapshots"], "hosts": ["yahoo"], "cadence": "weekly",
        "routes": [_r("yfinance_targets", "primary", "yahoo", "Ticker.analyst_price_targets")],
        "serve_stale_days": 14, "canary": "yfinance_analyst",
        "pit": "snapshot table is the only honest PT history (monthly)", "tos": "unofficial public API",
    },
    "moneycontrol_recos": {
        "family": "estimates", "status": "production",
        "what": "Individual broker buy/sell calls from Moneycontrol",
        "modules": ["sources.moneycontrol_recos"], "schedule": ["step:fetch_broker_recos"],
        "writes": ["broker_recommendations"], "hosts": ["moneycontrol"], "cadence": "weekly",
        "routes": [_r("mc_stock_page", "primary", "moneycontrol", "stock page broker-reco block")],
        "serve_stale_days": 30, "canary": "moneycontrol_recos",
        "pit": "reco_date; undated calls carry reco_date_imputed=1 (fetch date, not an event time)", "tos": "public page",
        "notes": "Decided 2026-09-28: keep (dispersion + cross-source PT check), not a factor input; "
                 "71% of stored dates were imputed — now flagged",
    },

    # ═══════════════════════════════ Events & documents ═══════════════════════════════
    "bse_announcements": {
        "family": "events", "status": "production",
        "what": "Every company announcement filed on BSE (results, resignations, ratings…)",
        "modules": ["sources.bse_announcements"], "schedule": ["cron:forward"],
        "writes": ["bse_announcements"], "hosts": ["bse_api", "bse"], "cadence": "daily",
        "routes": [_r("bse_ann_api", "primary", "bse_api", "AnnSubCategoryGetData/w (curl_cffi chrome TLS)")],
        "serve_stale_days": 3, "canary": "bse_announcements",
        "pit": "dt_tm dissemination time", "tos": "public exchange data",
        "fallback_plan": "NSE corporate-announcements API",
    },
    "corporate_actions": {
        "family": "events", "status": "production",
        "what": "Splits, bonuses, dividends and buybacks, with their dates",
        "modules": ["sources.nselib_pull"], "schedule": ["step:fetch_corp_actions"],
        "writes": ["corporate_actions"], "hosts": ["nse"], "cadence": "trading_day",
        "routes": [_r("nselib_corp_actions", "primary", "nse", "nselib cm.corporate_actions_for_equity")],
        "serve_stale_days": 3, "canary": "corporate_actions",
        "pit": "ex-date", "tos": "public exchange data",
        "fallback_plan": "HF tejhq actions/ parquet; BSE corporate actions",
    },
    "earnings_calendar": {
        "family": "events", "status": "production",
        "what": "Upcoming results and board-meeting dates",
        "modules": ["sources.nselib_pull"], "schedule": ["step:fetch_earnings_calendar"],
        "writes": ["earnings_calendar"], "hosts": ["nse"], "cadence": "trading_day",
        "routes": [_r("nselib_event_calendar", "primary", "nse", "nselib cm.event_calendar_for_equity")],
        "serve_stale_days": 7, "canary": "earnings_calendar",
        "pit": "announced date", "tos": "public exchange data",
    },
    "transcripts": {
        "family": "events", "status": "production",
        "what": "Earnings-call transcripts",
        "modules": ["sources.transcripts_pull"], "schedule": ["cron:transcripts"],
        "writes": ["transcripts"], "hosts": ["screener", "bse"], "cadence": "weekly",
        "routes": [_r("screener_concalls", "primary", "screener", "concall section → BSE AttachLive/AttachHis PDF")],
        "canary": "screener", "serve_stale_days": 14,
        "pit": "bse_filing_date (look-ahead safe; filled by --backfill-filing-dates)", "tos": "public filings",
        "notes": "Scheduled weekly 2026-09-28 (was orphaned since 2026-06-07); one-off catch-up for Jun→Sep run the same day",
    },

    # ═══════════════════════════════ Macro & flows ═══════════════════════════════
    "macro_market": {
        "family": "macro", "status": "production",
        "what": "Market indicators: sector indices, commodities, rupee, US yields, India VIX",
        "modules": ["sources.macro_yfinance"], "schedule": ["step:fetch_macro_market"],
        "writes": ["macro_history", "vix_history"], "hosts": ["yahoo"], "cadence": "trading_day",
        "routes": [_r("yfinance_macro", "primary", "yahoo", "yf.download ^NSEI, ^INDIAVIX, futures, FX")],
        "serve_stale_days": 2, "canary": "macro_market",
        "pit": "bar date", "tos": "unofficial public API",
        "fallback_plan": "nse_index_history (nselib) for the index legs",
    },
    "macro_official": {
        "family": "macro", "status": "production",
        "what": "Official economy data: industrial output, inflation, core industries",
        "modules": ["sources.macro_gov", "sources.macro_official"], "schedule": ["step:fetch_macro_gov"],
        "writes": ["macro_history", "macro_indicators", "macro_indicator_meta"],
        "hosts": ["mospi", "oea"], "cadence": "weekly",
        "routes": [_r("mospi_api", "primary", "mospi", "api.mospi.gov.in IIP/CPI"),
                   _r("oea_excel", "primary", "oea", "eaindustry.nic.in core-sector Excel")],
        "serve_stale_days": 60, "canary": "macro_official",
        "pit": "release date (~6-8 weeks after the month)", "tos": "government open data",
    },

    # ═══════════════════════════════ News ═══════════════════════════════
    "rss_news": {
        "family": "news", "status": "production",
        "what": "Financial news headlines, matched to our stocks",
        "modules": ["sources.rss"], "schedule": ["step:fetch_news"],
        "writes": ["news_articles"], "hosts": ["economictimes", "livemint", "google_news"], "cadence": "daily",
        "routes": [_r("et_feeds", "primary", "economictimes", "Economic Times RSS (several sections)"),
                   _r("livemint_feeds", "fallback", "livemint", "Livemint RSS"),
                   _r("gnews_theme_searches", "primary", "google_news", "Google News searches for the trade, chips and energy-transition themes (plan 0021)")],
        "serve_stale_days": 1, "canary": "rss_news",
        "pit": "published_at", "tos": "public RSS",
    },
    "regulatory_news": {
        "family": "news", "status": "production",
        "what": "Regulation and policy news (RBI, government, Google News)",
        "modules": ["sources.regulatory_harvester"], "schedule": ["step:fetch_regulatory"],
        "writes": ["regulatory_events"], "hosts": ["google_news", "rbi", "pib", "wayback"], "cadence": "daily",
        "routes": [_r("google_news_rss", "primary", "google_news", "news.google.com/rss/search"),
                   _r("rbi_circulars", "fallback", "rbi", "NotificationUser.aspx?Id=")],
        "serve_stale_days": 3, "canary": "regulatory_news",
        "pit": "published date", "tos": "public RSS / government sites",
    },
    "llm_enrichment": {
        "family": "news", "status": "degraded",
        "what": "AI summaries and tagging of news and regulation",
        "modules": ["sources.news_classifier", "sources.news_brief", "sources.news_editor", "sources.regulatory_classifier"],
        "schedule": ["step:classify_news", "step:news_brief", "step:news_desk", "step:classify_regulatory"],
        "writes": ["news_enriched", "news_briefs", "news_themes", "news_theme_articles", "news_theme_history", "news_today", "news_week",
                   "regulatory_signals"], "hosts": ["anthropic"],
        "cadence": "daily", "routes": [_r("llm_tasks_worker", "primary", "anthropic", "llm_tasks queue → local claude -p on the subscription (alpha_mcp/steps.py)"),
                                       _r("anthropic_api", "fallback", "anthropic", "Messages API (Haiku/Sonnet) — config.LLM_WORK executor 'api'")],
        "derived_from": ["rss_news", "regulatory_news"],
        "canary": None, "canary_waiver": "subscription-bound worker (plan 0016); step failures already page and every result is validated by alpha-work.submit",
        "serve_stale_days": 3, "notes": "API credits empty since 2026-08-24; since 2026-10-02 the steps run through the llm_tasks queue (ADR 0056)",
    },
    "news_images": {
        "family": "news", "status": "production",
        "what": "Stock photos for the news cards in the cockpit",
        "modules": ["sources.news_images"], "schedule": ["manual"],
        "writes": [], "hosts": ["pexels_api", "pexels_images"], "cadence": "manual",
        "routes": [_r("pexels", "primary", "pexels_api", "Pexels search API")],
        "canary": None, "canary_waiver": "cosmetic, built once by hand",
    },

    # ═══════════════════════════════ Funds ═══════════════════════════════
    "amfi_nav": {
        "family": "funds", "status": "production",
        "what": "Daily NAV and scheme list for ~14,000 mutual funds (AMFI)",
        "modules": ["sources.mf_amfi_master", "sources.mf_nav_daily", "sources.mf_nav_backfill"],
        "schedule": ["step:fetch_mf_master", "step:fetch_mf_nav_daily"],
        "writes": ["mf_scheme_master", "mf_nav_history"], "hosts": ["amfi", "mfapi"], "cadence": "daily",
        "routes": [_r("amfi_navall", "primary", "amfi", "spages/NAVAll.txt"),
                   _r("amfi_nav_history", "fallback", "amfi", "portal NAV history report (gap repair --from/--to)"),
                   _r("mfapi", "fallback", "mfapi", "api.mfapi.in per-scheme history (mf_nav_backfill)")],
        "serve_stale_days": 3, "canary": "amfi_nav",
        "pit": "NAV date", "tos": "public AMFI files / community API",
    },
    "mf_quality": {
        "family": "funds", "status": "production",
        "what": "Flags mutual-fund schemes that should be left out (segregated, closed…)",
        "modules": ["sources.mf_data_quality"], "schedule": ["step:classify_mf_quality"],
        "writes": ["mf_scheme_master"], "hosts": [], "cadence": "weekly",
        "derived_from": ["amfi_nav"], "routes": [],
        "canary": None, "canary_waiver": "derived in-house", "serve_stale_days": 14,
    },
    "mf_holdings": {
        "family": "funds", "status": "production",
        "what": "Monthly mutual-fund portfolios: what each fund holds",
        "modules": ["sources.mf_holdings_scrape", "sources.mf_holdings"], "schedule": ["step:scrape_mf_holdings"],
        "writes": ["mf_holdings", "mf_sector_allocation"], "hosts": ["etmoney"], "cadence": "monthly",
        "routes": [_r("etmoney_pages", "primary", "etmoney", "portfolio-details sitemap → scheme pages"),
                   _r("csv_drop", "manual", None, "sources.mf_holdings --csv (AMC disclosure files)")],
        "serve_stale_days": 45, "canary": "mf_holdings",
        "pit": "portfolio as-of date", "tos": "public pages",
    },
    "mf_metadata": {
        "family": "funds", "status": "candidate",
        "what": "MF AUM / expense ratio / manager (CSV ingest path; no free automated source found)",
        "modules": ["sources.mf_metadata_enrichment"], "schedule": ["manual"],
        "writes": ["mf_scheme_master"], "hosts": [], "cadence": "manual", "routes": [],
        "canary": None, "canary_waiver": "manual CSV path",
    },

    # ═══════════════ Discovery: research 0005 candidates (T3 until probation) ═══════════════
    "kite_intraday": {
        "family": "prices", "status": "candidate",
        "what": "Zerodha Kite intraday bars for 3 microstructure factors",
        "modules": ["sources.kite_pull"], "schedule": [], "writes": [], "hosts": ["kite"],
        "cadence": "trading_day", "routes": [_r("kite_connect", "primary", "kite", "Kite Connect historical API")],
        "canary": None, "canary_waiver": "needs a paid account (plan 0018 D6)",
        "probe": ("NEEDS ACCOUNT", "2026-09-28", "Kite ~₹500/mo incl. history (unconfirmed); Fyers free 1-min from 2017"),
        "ref": "research 0005 B2",
    },
    "bse_shp_xbrl": {
        "family": "ownership", "status": "probation",
        "what": "Named holders above 1% of every stock (promoters, fund schemes, FPIs, individuals), from the exchange filing",
        "modules": ["sources.bse_shp"], "schedule": ["cron:transcripts"],
        "writes": ["shareholding_holders", "shareholding_categories"], "hosts": ["bse_api", "bse"], "cadence": "weekly",
        "routes": [_r("bse_shp_xbrl", "primary", "bse_api", "Corp_Shareholding_ng/w index (no Origin header) → XBRL .xml / inline .html")],
        "serve_stale_days": 120, "canary": "bse_shp_xbrl",
        "pit": "filed_at = BSE broadcast time; a revision is a later filed_at", "tos": "public exchange data",
        "fallback_plan": "NSE corporate-share-holdings-master (per symbol, Sep-2021 →) — also the only route for the 249 NSE-only stocks",
        "need": "named holders for the investor-approaches page (cloning panel); category totals + retail (≤₹2L) holder counts back to 2016 for the ownership-flow factors",
        "notes": "Promoted 2026-10-04 on a 3-stock canary + smoke test. Weekly run fetches stocks missing the latest quarter "
                 "(budgeted, resumable). Names are as filed: resolve spellings before following one investor across stocks",
        "probe": ("WORKS", "2026-09-28", "BSE index to 2001, XBRL from 2016; GRAVITA Jun-2016 retail 8,323 / 8,841"),
        "ref": "research 0005 A2",
    },
    "nse_results_xbrl": {
        "family": "fundamentals", "status": "candidate",
        "what": "Quarterly results on filing day (first-reported, timestamped XBRL)",
        "need": "fix the up-to-a-month Tickertape lag; fallback for tickertape_fundamentals",
        "probe": ("WORKS", "2026-09-28", "corporates-financial-results XBRL ≤Dec-2024; 2025+ at integrated-filing-results"),
        "ref": "research 0005 A3",
    },
    "yahoo_earnings_history": {
        "family": "estimates", "status": "probation",
        "what": "Earnings surprises (estimate vs actual per result) and weekly EPS-estimate trends",
        "modules": ["sources.yahoo_estimates"], "schedule": ["cron:estimates"],
        "writes": ["analyst_estimates"], "hosts": ["yahoo"], "cadence": "weekly",
        "routes": [_r("yf_earnings_dates", "primary", "yahoo", "get_earnings_dates (history) + earningsTrend (snapshots)")],
        "serve_stale_days": 14, "canary": "yahoo_estimates",
        "pit": "snapshots: fetch time (honest); history: report time, label pit_unverified", "tos": "unofficial public API",
        "need": "the SUE numerator PEAD lacked; estimate-revision factors",
        "notes": "Backfill 2026-09-28: history for LARGE/MID/SMALL, trend for covered stocks",
        "probe": ("WORKS", "2026-09-28", "RELIANCE 78 q to 2007, GRAVITA 15 q to 2015"), "ref": "research 0005 A4",
    },
    "nse_credit_ratings": {
        "family": "events", "status": "probation",
        "what": "Credit-rating changes (upgrades, downgrades, new, withdrawn) filed on NSE",
        "modules": ["sources.nse_events"], "schedule": ["cron:forward"],
        "writes": ["market_events"], "hosts": ["nse"], "cadence": "daily",
        "routes": [_r("nse_reg30_ratings", "primary", "nse", "api/corporate-credit-rating (with the earlier rating)")],
        "serve_stale_days": 7, "canary": "nse_credit_ratings",
        "pit": "available_at = NSE broadcast time", "tos": "public exchange data",
        "need": "credit-rating direction factor (checklist 1e)",
        "notes": "Backfilled 2025-01 → 2026-09 (6,897 events). Direction from the two ratings, not the label. "
                 "Covers ~100 listed issuers (debt-heavy banks/NBFCs dominate); downgrades rare in this window (26)",
        "probe": ("WORKS", "2026-09-28", "≥Jan-2025, 82% carry CreditRatingEarlier"), "ref": "research 0005 B1",
    },
    "cra_rating_letters": {
        "family": "events", "status": "candidate",
        "what": "Rating-agency letters/PDFs (CARE, CRISIL, ICRA) → action + 3-year history annexure",
        "need": "2018-2025 backfill of rating direction",
        "probe": ("WORKS", "2026-09-28", "5/6 BSE letters text-extractable (AttachHis); CARE p1 'Downgraded from' verified"),
        "ref": "research 0005 B1",
    },
    "nse_legacy_bhavcopy": {
        "family": "prices", "status": "candidate",
        "what": "Legacy NSE CM bhavcopy archive incl. delisted names (1994+), for a survivorship-free panel",
        "need": "plan 0014 D3 (floor corrected from ~2023)",
        "notes": "2026-10-04: prices 2015-01 → 2019-12 are being loaded by `python -m sources.nse --legacy` "
                 "(run.sh backfill; source='legacy_bhavcopy', universe rows → stock_prices, the rest → "
                 "stock_prices_unlisted). Still a candidate for the ISIN-keyed, pre-2015 survivorship panel",
        "probe": ("WORKS", "2026-09-28", "2015: ~715 of 1,510 symbols not in today's universe; PREVCLOSE is UNADJUSTED"),
        "ref": "research 0005 A1",
    },
    "hf_tejhq_bars": {
        "family": "prices", "status": "candidate",
        "what": "HuggingFace tejhq/indian-markets: adjusted NSE prices 2010+, delisted kept",
        "need": "zero-NSE-request survivorship panel; full fallback for nse_bhavcopy",
        "probe": ("WORKS", "2026-09-28", "BPCL 2024 bonus correctly adjusted; 669/2,182 symbols outside universe"),
        "ref": "research 0005 A1b",
    },
    "nse_mto_delivery": {
        "family": "prices", "status": "candidate",
        "what": "Pre-2020 security-wise delivery files (extends delivery_anomaly_z history)",
        "probe": ("WORKS", "2026-09-28", "MTO_05012015.DAT parsed"), "ref": "research 0005 A1c",
    },
    "nse_legacy_fo": {
        "family": "prices", "status": "candidate",
        "what": "Legacy F&O bhavcopy (pre-2025) → IV history backfill",
        "notes": "2026-10-09: index options + futures 2019-01 → 2024-07-12 loaded into fno_bhav by "
                 "`python -m sources.fno_pull --legacy` (run.sh backfill) for the option-premium study. "
                 "Still a candidate for STOCK options (~30M rows; disk)",
        "probe": ("WORKS", "2026-09-28", "2015 file: 29k contracts with SETTLE_PR, OPEN_INT"), "ref": "research 0005 B3",
    },
    "nse_holidays": {
        "family": "reference", "status": "probation",
        "what": "Exchange trading-holiday list (F&O and equities), for the option paper book's entry days",
        "modules": ["sources.nse_holidays"], "schedule": ["cron:morning"], "writes": ["market_holidays"],
        "hosts": ["nse"], "cadence": "daily",
        "routes": [_r("nse_holiday_master", "primary", "nse", "nselib trading_holiday_calendar → /api/holiday-master?type=trading")],
        "canary_waiver": "one small list a day; option_book raises when it has no F&O rows",
        "pit": "published ahead for the year", "tos": "public exchange data",
    },
    "kite_option_quotes": {
        "family": "prices", "status": "probation",
        "what": "Live NIFTY/SENSEX option quotes + Kite margin at 15:20 IST on paper-book entry days (plan 0022)",
        "modules": ["sources.kite_quotes"], "schedule": ["cron:kite_quotes"], "writes": ["option_live_quotes"],
        "hosts": ["kite"], "cadence": "weekly",
        "routes": [_r("kite_quote", "primary", "kite", "kc.quote depth + basket_order_margins (account ML5851, read-only)")],
        "canary_waiver": "needs Amit's daily Kite login; a missing login fails the job loudly (NoKiteSession)",
        "pit": "snapshot time", "tos": "Kite Connect subscription",
    },
    "bse_fo_bhav": {
        "family": "prices", "status": "probation",
        "what": "BSE index options + futures (SENSEX, BANKEX) EOD, into fno_bhav beside NSE's",
        "modules": ["sources.bse_fo"], "schedule": ["cron:morning"], "writes": ["fno_bhav"], "hosts": ["bse"],
        "canary_waiver": "SENSEX only feeds the option paper book (plan 0022); option_book raises when an entry day's chain is missing",
        "cadence": "trading_day",
        "routes": [_r("bse_fo_udiff", "primary", "bse", "download/BhavCopy/Derivative/BhavCopy_BSE_FO_0_0_0_{YYYYMMDD}_F_0000.CSV (from ~2024-01-05)")],
        "need": "SENSEX weekly expiry (BSE's side of one-weekly-per-exchange) for the option-premium study",
        "notes": "2026-10-09: history 2024-01-05 → 2026-10-08 loaded (679 days); daily in run.sh morning since 2026-10-10. Missing day = HTTP 200 + HTML page. "
                 "Older BSE file (to 2024-07-05) has no settle price or index level, not read",
        "probe": ("WORKS", "2026-10-09", "UDiFF 2026-10-08 (696 SENSEX options) + 2024-01-11 (171); legacy 2023-08-04 zip served"),
    },
    "nse_slb": {
        "family": "prices", "status": "candidate",
        "what": "Securities lending & borrowing: lending fees + open positions (short-interest proxy)",
        "probe": ("WORKS", "2026-09-28", "2021 + 2026 files; thin market (36→180 rows/day)"), "ref": "research 0005 C",
    },
    "nse_cmvolt": {
        "family": "prices", "status": "candidate",
        "what": "NSCCL daily exchange volatility per symbol",
        "probe": ("WORKS", "2026-09-28", "4,952 symbols/day"), "ref": "research 0005",
    },
    "index_membership": {
        "family": "reference", "status": "production",
        "what": "History of stocks added to or removed from NSE indices (1996 → 2020)",
        "modules": ["sources.nse_events"], "schedule": ["manual"],
        "writes": ["market_events"], "hosts": ["nse_archives"], "cadence": "manual",
        "routes": [_r("index_incl_excl_xls", "primary", "nse_archives", "content/indices/IndexInclExcl.xls")],
        "canary": None, "canary_waiver": "a static historical file, loaded once",
        "pit": "effective date (announcement ~4 weeks earlier)", "tos": "public exchange archive",
        "notes": "Loaded 9,121 events. NSE stopped updating this file in 2020 — later changes need the index press releases",
        "probe": ("WORKS", "2026-09-28", "all sheets parsed"), "ref": "research 0005 B4",
    },
    "nse_ipo_master": {
        "family": "events", "status": "probation",
        "what": "IPO listings with issue dates and price, plus anchor lock-in expiry dates",
        "modules": ["sources.nse_events"], "schedule": ["cron:forward"],
        "writes": ["market_events"], "hosts": ["nse"], "cadence": "daily",
        "routes": [_r("nse_past_issues", "primary", "nse", "api/public-past-issues")],
        "serve_stale_days": 7, "canary": None, "canary_waiver": "one call inside the forward job; it raises on 0 rows",
        "pit": "listing date; lock-in dates by the SEBI anchor rule (approximate)", "tos": "public exchange data",
        "notes": "Backfilled 1,457 issues (2003 → 2026, EQ + SME + others)",
        "probe": ("WORKS", "2026-09-28", "1,458 issues back to 2012 incl. SME"), "ref": "research 0005 B5",
    },
    "vahan_registrations": {
        "family": "macro", "status": "candidate",
        "what": "VAHAN vehicle registrations by maker × month (auto OEM nowcast)",
        "need": "plan 0003 market-share momentum (autos)",
        "probe": ("WORKS", "2026-09-28", "python-requests reset; curl_cffi chrome → 200, no captcha"), "ref": "research 0005 B6",
    },
    "india_energy_csvs": {
        "family": "macro", "status": "candidate",
        "what": "Robbie Andrew GitHub CSVs: daily power, company-level coal/aluminium output",
        "probe": ("WORKS", "2026-09-28", "63 files, pushed daily"), "ref": "research 0005 B7",
    },
    "fbil_gsec_curve": {
        "family": "macro", "status": "candidate",
        "what": "FBIL daily G-sec par yield curve (replaces the gsec10 ETF proxy)",
        "probe": ("WORKS", "2026-09-28", "fetchfiltered publication list returned"), "ref": "research 0005 B8",
    },
    "rbi_sector_credit": {
        "family": "macro", "status": "candidate",
        "what": "RBI sectoral deployment of bank credit (RBIH DBIE mirror)",
        "probe": ("WORKS", "2026-09-28", "DBIE search finds the table"), "ref": "research 0005 B8",
    },
    "ppac_fuel": {
        "family": "macro", "status": "candidate",
        "what": "PPAC petroleum product consumption by month",
        "probe": ("WORKS", "2026-09-28", "hidden AJAX JSON"), "ref": "research 0005 B8",
    },
    "free_intraday": {
        "family": "prices", "status": "wanted",
        "what": "Free 1-minute history (Fyers from 2017, Upstox from 2022, ICICI Breeze 3y)",
        "need": "backtest intraday microstructure factors without paying for Kite",
        "probe": ("NEEDS ACCOUNT", "2026-09-28", "not probed — plan 0018 D6"), "ref": "research 0005 B2",
    },
    "gst_collections": {
        "family": "macro", "status": "wanted",
        "what": "Monthly GST collections / e-way bills",
        "need": "macro nowcast; macro_indicators leaves it blank",
        "probe": ("BLOCKED", "2026-09-28", "gst.gov.in JS anti-bot — do not bypass; look for a mirror"),
        "ref": "research 0005 C",
    },

    # ═══════════════════════════════ Retired / dead ends ═══════════════════════════════
    "data_gov_in": {
        "family": "macro", "status": "retired",
        "what": "data.gov.in macro API", "probe": ("DEAD", "2026-09-27", "gateway 502s; datasets stopped 2023-24"),
        "ref": "commit 11c6631 → macro_official",
    },
    "tickertape_pt_history": {
        "family": "estimates", "status": "retired",
        "what": "Tickertape forecastsHistory.price as PT history",
        "probe": ("DEAD", "2026-07-05", "it is the realized year-ahead close (look-ahead)"), "ref": "ADR 0045",
    },
    "ishares_holdings": {
        "family": "ownership", "status": "retired",
        "what": "iShares INDA holdings JSON (passive-FPI proxy)",
        "probe": ("DEAD", "2026-09-28", "endpoint returns an HTML page"), "ref": "research 0005",
    },
}

# RAW tables that are deliberately NOT fed by any feed (legacy / manual research artifacts).
NON_FEED_TABLES = {
    "daily_snapshots_pit_v1": "v1 archive, frozen",
    "pit_ic_by_tier_v1": "v1 archive, frozen",
    "policy_events": "hand-curated seed (28 rows), superseded by regulatory_events",
    "macro_sector_map": "hand-maintained sector map",
    "mf_schemes": "v1 MF table, superseded by mf_scheme_master",
    "external_anchors": "anchor_audit tool output (plan 0017 D4: retire)",
}


# ═══════════════════════════════ Known issues (plan 0018 §5) ═══════════════════════════════
SYMPTOM_CLASSES = {
    # code: (name, signature, first response)
    "A": ("Blocked", "403 / connection reset / 200 HTML challenge where data was expected",
          "Referer + cookie warm, then TLS impersonation (hosts `impersonate`). Never bypass captcha or auth."),
    "B": ("Moved", "404, or 200-but-empty, or a row-count cliff",
          "Check wrapper changelogs (nselib, NseIndiaApi, jugaad), exchange circulars and daily-reports manifests; probe candidates."),
    "C": ("Auth expired", "login page / 401 / session cookie rejected",
          "Run the declared re-login path; alert if it fails."),
    "D": ("Shape drift", "canary fingerprint differs from the accepted baseline",
          "Diff saved raw responses, fix the parser, add the failing response as a fixture, replay, then --accept."),
    "E": ("Partial / zero", "row count or coverage below its band",
          "Check holiday calendar; try the next route; heal via the watchdog."),
    "F": ("Semantic drift", "plausible values that mean something else (units, dates, fields)",
          "Cross-source reconciliation (Gate 3); pull the field; PIT audit."),
    "G": ("Quota / billing", "429 / 400 credit balance / budget exhausted",
          "Back off within the host budget; switch executor; never raise politeness."),
    "H": ("Orphan", "feed not scheduled, or its cron is a no-op",
          "Schedule it (step or run.sh case); tests/test_feeds.py blocks new orphans."),
}

INCIDENTS = [
    # (date, feed, class, symptom, cause, fix, ref)
    ("2026-09-28", "banking_metrics", "D", "every quarantine write failed: no column _book_value_cr (found by the run log's output tail)",
     "quarantine_row passed the in-flight helper column to the mirror table",
     "quarantine_row drops underscore helper keys; write_verdicts failures now a run-log WARN", "plan 0018 run log"),
    ("2026-09-28", "banking_metrics", "F", "BJAT dropped as identity_gate WRONG_ENTITY (found by the run log)",
     "Screener h1 '&amp;' vs stocks.name 'and' — the normaliser kept 'amp'",
     "html.unescape + '&'→'and' in validators/identity_check._normalise_company_name", "plan 0018 run log"),
    ("2026-09-28", "scrip_master", "B", "fallback route ListOfScrips.csv returns 404 (first canary run)",
     "third-party GitHub mirror removed", "OPEN — route marked dead; Upstox primary healthy; find a BSE-direct list",
     "plan 0018 P0"),
    ("2026-09-28", "nse_legacy_bhavcopy", "F", "PREVCLOSE/CLOSE(t-1) factor = 1.0 on a 1:1 bonus",
     "legacy PREVCLOSE is unadjusted", "adjust via corporate_actions or HF adj_close", "research 0005"),
    ("2026-09-28", "nse_results_xbrl", "B", "corporates-financial-results stops at Dec-2024",
     "results moved to Integrated Filing", "api/integrated-filing-results (iXBRL)", "research 0005"),
    ("2026-09-28", "cra_rating_letters", "B", "AttachLive PDF 404", "older filings archived",
     "fall back to xml-data/corpfiling/AttachHis/", "research 0005"),
    ("2026-09-28", "vahan_registrations", "A", "connection reset for python-requests",
     "TLS fingerprinting", "curl_cffi chrome session", "research 0005"),
    ("2026-09-28", "bse_shp_xbrl", "A", "1814-byte error shell", "an Origin header is rejected",
     "send Referer, never Origin", "research 0005"),
    ("2026-09-27", "macro_official", "B", "data.gov.in 502 / timeouts; series frozen 2023-24",
     "source abandoned", "MoSPI API + OEA Excel", "11c6631"),
    ("2026-09-26", "amfi_nav", "D", "NAV parse gap 08-19 → 09-25", "AMFI added Plan;Option columns",
     "parser fix + refill via AMFI history report", "checklist 2026-09-27"),
    ("2026-09-19", "bse_announcements", "A", "403 from api.bseindia.com", "Akamai TLS-fingerprint gate",
     "hosts bse_api impersonate=chrome", "0642a6a"),
    ("2026-09-27", "screener_fundamentals", "C", "exports fail, homepage shows login link only",
     "session has a fixed ~30-day life; no re-login attempted Jul→Sep", "keepalive re-logs in via creds", "0642a6a"),
    ("2026-08-24", "llm_enrichment", "G", "400 credit balance too low", "API credits exhausted",
     "session backlog clear; plan 0016 routines", "checklist (e)"),
    ("2026-06-07", "transcripts", "H", "no new transcripts", "module never scheduled",
     "weekly run.sh transcripts (reported in last 45 days) + Jun→Sep catch-up, 2026-09-28", "plan 0018"),
    ("2026-05-02", "nse_insider", "B", "corporates-pit returns 200 with ~0 rows", "endpoint silently deprecated",
     "corporates-pit-gg list + per-filing XBRL", "0642a6a"),
    ("2026-07-05", "tickertape_analyst", "F", "pt_upside t=7-9 in backtest",
     "forecastsHistory.price is the realized year-ahead close", "field pulled (ADR 0045)", "ADR 0045"),
    ("2026-09-27", "nse_bhavcopy", "E", "0 rows logged SUCCESS", "failed download returned 0 silently",
     "producers raise on 0 output", "ADR 0052"),
    ("2026-04-30", "corporate_actions", "H", "corporate_adjustments stale for 5 months",
     "no producer step", "daily compute_corporate_adjustments step", "e8eac9e"),
]


# ═══════════════════════════════ Derived views ═══════════════════════════════

def schedule_kinds(feed):
    """[(kind, name)] from `schedule` — kind ∈ step | cron | manual."""
    out = []
    for s in FEEDS[feed].get("schedule") or []:
        kind, _, name = s.partition(":")
        out.append((kind, name or kind))
    return out


def steps_of(feed):
    return [n for k, n in schedule_kinds(feed) if k == "step"]


def crons_of(feed):
    return [n for k, n in schedule_kinds(feed) if k == "cron"]


def has_fallback(feed):
    """A LIVE independent full route (fallback/manual) beyond the primary one(s).
    A route marked `dead` is kept for the record but is not resilience."""
    return any(r["kind"] in ("fallback", "manual") and not r.get("dead")
               for r in FEEDS[feed].get("routes") or [])


def resilience(feed):
    """'fallback' | 'serve-stale' | 'none' — what happens when the primary dies."""
    if has_fallback(feed):
        return "fallback"
    return "serve-stale" if FEEDS[feed].get("serve_stale_days") else "none"


def _critical_tables():
    """(raw, any) — tables the picks/email path depends on: written or read by a
    critical step (checks.critical_steps = graph ancestors of the email), plus every
    table a wired factor (factors.FACTORS weights) reads. `raw` keeps RAW tables only
    (what an external feed must deliver); `any` keeps every kind (what an in-house
    derivation must deliver). Plan 0018 D1: derived, never hand-kept."""
    import checks
    import factors
    import graph
    from config import PIPELINE_STEPS
    from tables import TABLES
    crit = checks.critical_steps()
    touched = set()
    for s in PIPELINE_STEPS:
        if isinstance(s, str) or s["name"] not in crit:
            continue
        touched |= set(graph.writes(s)) | set(graph.reads(s))
    for f in factors.FACTORS.values():
        if f.get("weights"):
            touched |= set(f.get("source_tables") or [])
    return {t for t in touched if TABLES.get(t, {}).get("kind") == "RAW"}, touched


_TIERS = {}


def tiers(refresh=False):
    """{feed: 'T1'|'T2'|'T3'|None}. T3 = discovery/probation; None = retired.
    T1 when the feed delivers a table the picks/email path or a wired factor needs:
    external feeds are judged on RAW tables, in-house derivations (derived_from) on
    their outputs of any kind — a derivation is as critical as what it feeds."""
    if _TIERS and not refresh:
        return _TIERS
    crit_raw, crit_any = _critical_tables()
    out = {}
    for name, f in FEEDS.items():
        st = f["status"]
        if st == "retired":
            out[name] = None
        elif st in DISCOVERY or st == "probation":
            out[name] = "T3"
        else:
            crit = crit_any if f.get("derived_from") else crit_raw
            out[name] = "T1" if set(f.get("writes") or []) & crit else "T2"
    _TIERS.clear()
    _TIERS.update(out)
    return _TIERS


def tier(feed):
    return tiers()[feed]


def canary_every(feed):
    """'daily' | 'weekly' | None — from the tier (plan 0018 D4)."""
    t = tier(feed)
    return CANARY_EVERY.get(t) if FEEDS[feed].get("canary") else None


_RUN_SH_LOGS = {}


def _run_sh_logs():
    """{job: [(log_step, module|None)]} parsed from run.sh `logged cron_x … python -m mod`
    lines — so the registry never hand-copies the names run.sh logs under."""
    if _RUN_SH_LOGS:
        return _RUN_SH_LOGS
    import re
    from pathlib import Path
    text = (Path(__file__).resolve().parent / "run.sh").read_text()
    job = None
    for line in text.splitlines():
        m = re.match(r"^\s{4}([a-z_]+)\)", line)
        if m:
            job = m.group(1)
        for step, rest in re.findall(r"logged (cron_\w+) (.*)", line):
            mod = re.search(r"python -m ([\w.]+)", rest)
            _RUN_SH_LOGS.setdefault(job, []).append((step, mod.group(1) if mod else None))
    return _RUN_SH_LOGS


def log_steps(feed):
    """pipeline_log step names that record this feed's runs: its PIPELINE_STEPS, plus
    the run.sh `logged` names of its cron jobs (matched on module; a job logged once
    without a module, e.g. cron_tickertape, counts for every feed it serves)."""
    f = FEEDS[feed]
    mods = set(f.get("modules") or [])
    out = list(steps_of(feed))
    logs = _run_sh_logs()
    for job in crons_of(feed):
        entries = logs.get(job, [])
        hit = [s for s, m in entries if m in mods]
        out += hit or [s for s, m in entries if m is None] or [f"cron_{job}"]
    return out
