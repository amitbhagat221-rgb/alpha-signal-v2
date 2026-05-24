"""
Alpha Signal v2 — Configuration

Every tunable value lives here. No magic numbers in source/signal/scoring code.
Import what you need:
    from config import SIGNAL_WEIGHTS, API, DB_PATH
"""

from pathlib import Path

# ── Paths ──

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "alpha_signal.db"
SCHEMA_PATH = PROJECT_ROOT / "schema.sql"
LOG_PATH = PROJECT_ROOT / "output" / "pipeline.log"
V1_ROOT = Path.home() / "alpha-signal"

# ── Universe ──

TIERS = ("LARGE", "MID", "SMALL")

TIER_SIZES = {
    "LARGE": 100,    # top 100 by market cap
    "MID": 150,      # 101-250
    "SMALL": 2200,   # 251+
}

# Minimum ADTV (₹ Cr) to be investable per tier
ADTV_MIN = {
    "LARGE": 10.0,
    "MID": 5.0,
    "SMALL": 1.0,
}

# ── Signal Weights per Tier (from C13b validation) ──
# t >= 2.5 → 1.0x (primary)
# t = 1.5-2.5 → 0.5x (secondary)
# t = 0.5-1.5 → 0.2x (tertiary)
# t < 0.5 → 0x (excluded)

SIGNAL_WEIGHTS = {
    "LARGE": {
        "consensus":      0.40,   # t=3.52 primary
        "earnings_yield": 0.20,   # t=1.57 secondary
        "accruals":       0.15,   # t=0.20 tertiary
        "piotroski":      0.10,   # t=0.51 tertiary
        "momentum":       0.05,   # t=0.00 tertiary
        "book_to_price":  0.10,   # t=0.79 tertiary
    },
    "MID": {
        "accruals":       0.30,   # t=3.20 primary
        "piotroski":      0.20,   # t=2.23 secondary
        "consensus":      0.15,   # t=2.20 secondary
        "book_to_price":  0.20,   # t=2.33 secondary
        "earnings_yield": 0.10,   # t=1.01 tertiary
        "promoter":       0.05,   # t=0.83 tertiary
    },
    "SMALL": {
        "promoter":       0.25,   # t=3.20 primary
        "earnings_yield": 0.20,   # t=3.13 primary
        "piotroski":      0.15,   # t=2.81 primary
        "book_to_price":  0.15,   # t=2.54 primary
        "smart_money":    0.10,   # t=2.49 secondary
        "accruals":       0.10,   # t=2.10 secondary
        "momentum":       0.05,   # t=1.76 secondary
    },
}

# ── VIX Regime ──

VIX_REGIMES = {
    #              vix_low  vix_high  large  mid   small
    "CALM":       (0.0,     13.0,     0.30,  0.35, 0.35),
    "NORMAL":     (13.0,    25.0,     0.40,  0.30, 0.30),
    "CAUTION":    (25.0,    35.0,     0.55,  0.25, 0.20),
    "CRISIS":     (35.0,    999.0,    0.70,  0.20, 0.10),
}

# Days in new regime before switching (hysteresis)
VIX_HYSTERESIS_DAYS = 3

# ── Quality Gate (Small Caps Only) ──

QUALITY_GATE = {
    # Tier 1: Hard exclusions
    "min_piotroski_exclude": 1,      # F <= 1 → excluded
    "min_altman_z_exclude": 0.5,     # Z < 0.5 → excluded

    # Tier 2: Penalties (capped at total of -0.60)
    "penalty_cap": -0.60,
    "penalty_loss_majority": -0.25,   # loss 2/3 years
    "penalty_neg_fcf_3yr": -0.20,     # negative 3yr cumulative FCF
    "penalty_pledge_high": -0.25,     # pledge > 50%
    "penalty_low_piotroski": -0.15,   # F = 2-3
    "penalty_altman_grey": -0.15,     # Z = 0.5-1.1
    "penalty_beneish_flag": -0.20,    # M > -1.78

    # Tier 2 thresholds
    "pledge_high_pct": 50.0,
    "piotroski_low_range": (2, 3),
    "altman_grey_range": (0.5, 1.1),
    "beneish_manipulator": -1.78,

    # Tier 3: Quality composite weights
    "composite_weights": {
        "piotroski":    0.25,
        "cfo_ebitda":   0.20,
        "beneish":      0.20,
        "altman_z":     0.15,
        "pledge":       0.10,
        "fcf_years":    0.10,
    },
}

# ── Forensic Thresholds ──

FORENSIC = {
    "beneish_grey": -2.22,     # above → possible manipulator
    "beneish_red": -1.78,      # above → likely manipulator
    "altman_distress": 1.10,   # below → distress zone
    "altman_grey": 2.60,       # below → grey zone
}

# ── Portfolio Construction ──

PORTFOLIO = {
    "max_stocks_per_sector": 5,
    "max_stock_weight_pct": 5.0,
    "max_daily_picks": 15,
    "picks_per_tier": {
        "LARGE": 5,
        "MID": 5,
        "SMALL": 5,
    },
}

# ── Transaction Costs (bps) ──

TRANSACTION_COSTS_BPS = {
    "LARGE": 30,
    "MID": 50,
    "SMALL": 150,
}

# ── Rebalance Frequencies ──

REBALANCE_FREQ = {
    "LARGE": "monthly",
    "MID": "quarterly",
    "SMALL": "semi-annual",
}

# ── Backtester ──

BACKTEST = {
    "forward_horizons": [5, 10, 20, 40, 60],
    "min_stocks_per_date": 50,
    "filing_lag_quarterly_days": 60,
    "filing_lag_annual_days": 75,
    "momentum_skip_days": 22,
    "momentum_6m_days": 154,
    "momentum_12m_days": 252,
}

# ── API / Network ──

API = {
    "tickertape_delay": 2.0,
    "nse_delay": 2.0,
    "slug_delay": 0.3,
    "default_timeout": 15,
    "nse_timeout": 30,
    "max_retries": 2,
    "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
}

# ── Screener Filters ──

SCREEN = {
    "min_market_cap_cr": 200,
    "min_avg_volume_20d": 10_000,
    "financial_sectors": ["Financials"],
    "cyclical_sectors": ["Metals & Mining", "Oil & Gas", "Chemicals", "Cement"],
    # InvIT / REIT / business-trust name patterns. These instruments don't
    # share equity ranking semantics (distribution-yield vehicles with
    # quarterly NAV mechanics, low float). Excluded from main screener since
    # 2026-05-24. Match is on stocks.name containing any of these substrings
    # (case-insensitive); audit pass with `python -m scoring.screener
    # --dry-run` after editing to confirm intent.
    "trust_exclusion_patterns": [
        "InvIT", "REIT",
        "Infrastructure Trust", "Infra Trust",
        "Highways Trust", "Realty Trust",
        "Business Parks", "Office Parks",
        "Yield Plus Trust", "Select Trust",
    ],
}

# ── Pipeline ──

PIPELINE = {
    "retry_count": 1,
    "email_on_failure": True,
}

# ── Pipeline Steps ──
# Single source of truth for the entire pipeline.
# pipeline.py reads this. data_health() reads this.
# Change "frequency" here to change how often a step runs.
#
# Fields:
#   name:       step name (used in --step flag and pipeline_log)
#   module:     Python module path
#   function:   function to call (must return int or None)
#   critical:   if True, pipeline stops on failure
#   table:      target DB table (for data health tracking)
#   source:     where the data comes from
#   data_freq:  how often the underlying data changes (daily/quarterly/annual)
#   frequency:  how often this step runs (daily/weekly/monthly)

PIPELINE_STEPS = [
    # ── Data Sources ──
    {"name": "fetch_macro_market", "module": "sources.macro_yfinance", "function": "compute", "critical": False,
     "table": "macro_history",     "source": "yfinance (20 tickers)",  "data_freq": "daily",  "frequency": "daily"},

    {"name": "fetch_macro_gov",    "module": "sources.macro_gov",     "function": "compute", "critical": False,
     "table": "macro_history",     "source": "data.gov.in + FRED",    "data_freq": "monthly", "frequency": "weekly"},

    {"name": "fetch_insider",      "module": "sources.nse_insider",   "function": "compute", "critical": False,
     "table": "insider_trades",    "source": "NSE PIT API",          "data_freq": "daily",  "frequency": "daily"},

    {"name": "fetch_bulk_deals",   "module": "sources.nse_bulk",     "function": "compute", "critical": False,
     "table": "bulk_deals",        "source": "NSE archives CSV",     "data_freq": "daily",  "frequency": "daily"},

    {"name": "fetch_bhavcopy",     "module": "sources.nse",          "function": "compute", "critical": True,
     "table": "stock_prices",      "source": "NSE Archives bhavcopy", "data_freq": "daily", "frequency": "daily"},

    {"name": "universe_liveness",  "module": "sources.universe",     "function": "compute", "critical": False,
     "table": "stocks",            "source": "stock_prices (recent activity)", "data_freq": "daily", "frequency": "daily"},

    {"name": "fetch_news",         "module": "sources.rss",          "function": "compute", "critical": False,
     "table": "news_articles",     "source": "RSS feeds (8 sources)", "data_freq": "daily", "frequency": "daily"},

    # Regulatory pipeline — harvester writes to regulatory_events, classifier
    # writes to regulatory_signals. Were missing from PIPELINE_STEPS pre-
    # 2026-05-24 → REGULATORY_FEED_DARK fired (43 days silent before the
    # staleness override caught it). Weekly harvest, daily classify (only
    # new unclassified rows).
    {"name": "fetch_regulatory",   "module": "sources.regulatory_harvester", "function": "harvest_all", "critical": False,
     "table": "regulatory_events", "source": "RBI + PIB + Google News + Wayback", "data_freq": "weekly", "frequency": "weekly"},

    {"name": "classify_regulatory","module": "sources.regulatory_classifier", "function": "compute", "critical": False,
     "table": "regulatory_signals","source": "regulatory_events (AI-classified)", "data_freq": "daily", "frequency": "daily"},

    # Moneycontrol broker recos — named-broker BUY/HOLD/SELL with target prices.
    # 2026-05-24: source confirmed alive (HINDALCO returned 6 real reports from
    # Motilal Oswal / Prabhudas Lilladher / Emkay Global). One-time backfill
    # needed first: `python -m sources.moneycontrol_recos --discover-only`
    # (writes stocks.mc_slug for ~2,448 stocks; otherwise harvester silently
    # skips no_slug stocks). Then this daily step keeps it fresh.
    {"name": "fetch_broker_recos", "module": "sources.moneycontrol_recos", "function": "compute", "critical": False,
     "table": "broker_recommendations", "source": "Moneycontrol HTML",   "data_freq": "weekly", "frequency": "weekly"},

    # {"name": "fetch_fundamentals", "module": "sources.tickertape", "function": "compute", "critical": False,
    #  "table": "quarterly_income",  "source": "Tickertape API",     "data_freq": "quarterly", "frequency": "monthly"},
    # NOTE: Tickertape fetcher takes ~4 hours for full universe (2,448 × 3 calls × 2s).
    # Run manually: python -m sources.tickertape --limit 10 (test) then full run overnight.
    # Monthly cron entry handles full refresh (run_tickertape_monthly.sh).

    # Tickertape HTML scrape — one page hit per stock, writes both analyst_consensus
    # and forecast_history. Two pipeline entries because each row in PIPELINE_STEPS
    # maps to one table; watchdog dedupes by (module, function) so it only runs once.
    {"name": "fetch_analyst",      "module": "sources.tickertape_analyst", "function": "compute", "critical": False,
     "table": "analyst_consensus", "source": "Tickertape __NEXT_DATA__", "data_freq": "monthly", "frequency": "monthly"},

    {"name": "fetch_forecast",     "module": "sources.tickertape_analyst", "function": "compute", "critical": False,
     "table": "forecast_history",  "source": "Tickertape __NEXT_DATA__", "data_freq": "monthly", "frequency": "monthly"},

    # Yahoo Finance analyst consensus aggregate. Replaces the Tickertape PT field
    # (which was contaminated with lastPrice — see HANDOFF 2026-05-22). Refreshes
    # the live `analyst_consensus` row per stock. The monthly snapshot to
    # `analyst_consensus_snapshots` runs from its own cron entry (1st business
    # day of month) — keeping daily history would be phantom precision since
    # PTs are episodic.
    {"name": "fetch_yf_analyst",   "module": "sources.yfinance_analyst",   "function": "compute", "critical": False,
     "table": "analyst_consensus", "source": "Yahoo Finance (yfinance)",  "data_freq": "monthly", "frequency": "daily"},

    # Tickertape shareholding pattern — Bharat_sm_data API (different path from analyst scrape).
    {"name": "fetch_shareholding", "module": "sources.tickertape_shareholding", "function": "compute", "critical": False,
     "table": "shareholding",      "source": "Tickertape API",        "data_freq": "quarterly", "frequency": "monthly"},

    # ── Signals ──
    {"name": "signal_sentiment",   "module": "signals.sentiment",   "function": "compute",  "critical": False,
     "table": "sentiment_scores",  "source": "news_articles",       "data_freq": "daily",   "frequency": "daily"},

    {"name": "signal_insider",     "module": "signals.insider_signal", "function": "compute", "critical": False,
     "table": "insider_signals",   "source": "insider_trades (NSE PIT)", "data_freq": "daily", "frequency": "daily"},

    {"name": "signal_forensic",    "module": "signals.forensic",    "function": "compute",  "critical": False,
     "table": "forensic_scores",   "source": "quarterly_income + annual_balance_sheet + annual_cash_flow",
     "data_freq": "quarterly",     "frequency": "daily"},

    {"name": "signal_piotroski",   "module": "signals.piotroski",   "function": "compute",  "critical": False,
     "table": "piotroski_scores",  "source": "quarterly_income + annual_balance_sheet + annual_cash_flow",
     "data_freq": "quarterly",     "frequency": "daily"},

    # ROIC — first Track 3 factor. Reads fundamentals_screener (sourced
    # weekly via sources.screener_pull — separate cadence, not in daily
    # pipeline). Not yet in scoring weights — needs t-stat validation.
    {"name": "signal_roic",        "module": "signals.roic",        "function": "compute",  "critical": False,
     "table": "roic_scores",       "source": "fundamentals_screener (Screener Premium)",
     "data_freq": "annual",        "frequency": "daily"},

    # FCF Yield — second Track 3 factor. Same data source, same gating —
    # not in scoring weights yet.
    {"name": "signal_fcf_yield",   "module": "signals.fcf_yield",   "function": "compute",  "critical": False,
     "table": "fcf_yield_scores",  "source": "fundamentals_screener (Screener Premium) + stocks.market_cap_cr",
     "data_freq": "annual",        "frequency": "daily"},

    # Cash Conversion Cycle — third Track 3 factor. DSO + DIO − DPO, 3-yr median.
    # Same gating — not in scoring weights yet.
    {"name": "signal_cash_conversion_cycle", "module": "signals.cash_conversion_cycle", "function": "compute", "critical": False,
     "table": "cash_conversion_cycle_scores", "source": "fundamentals_screener — Sales + Receivables + Inventory + Trade Payables",
     "data_freq": "annual",        "frequency": "daily"},

    # Operating Margin Trend — 5y OLS slope of EBIT/Sales (pp/year). Same gating.
    {"name": "signal_operating_margin_trend", "module": "signals.operating_margin_trend", "function": "compute", "critical": False,
     "table": "operating_margin_trend_scores", "source": "fundamentals_screener — Sales + PBT + Interest",
     "data_freq": "annual",        "frequency": "daily"},

    # Working Capital Intensity — (Recv + Inv − Pay) / Sales, 3y median. Same gating.
    {"name": "signal_working_capital_intensity", "module": "signals.working_capital_intensity", "function": "compute", "critical": False,
     "table": "working_capital_intensity_scores", "source": "fundamentals_screener — Sales + Receivables + Inventory + Trade Payables",
     "data_freq": "annual",        "frequency": "daily"},

    # Interest Coverage — (PBT + Interest) / Interest, 3y median. Same gating.
    {"name": "signal_interest_coverage", "module": "signals.interest_coverage", "function": "compute", "critical": False,
     "table": "interest_coverage_scores", "source": "fundamentals_screener — PBT + Interest",
     "data_freq": "annual",        "frequency": "daily"},

    # ROIIC — marginal NOPAT/IC over trailing 5y. Sister of ROIC; measures
    # how productive newly-deployed capital has been.
    {"name": "signal_roiic", "module": "signals.roiic", "function": "compute", "critical": False,
     "table": "roiic_scores", "source": "fundamentals_screener — PBT + Tax + Interest + Equity Share Capital + Reserves + Borrowings",
     "data_freq": "annual",        "frequency": "daily"},

    # ── Forensic / capital-allocation batch (plan 0002 §3.2.1) ──
    {"name": "signal_dso_change_yoy", "module": "signals.dso_change_yoy", "function": "compute", "critical": False,
     "table": "dso_change_yoy_scores", "source": "fundamentals_screener — Sales + Receivables",
     "data_freq": "annual", "frequency": "daily"},
    {"name": "signal_dio_change_yoy", "module": "signals.dio_change_yoy", "function": "compute", "critical": False,
     "table": "dio_change_yoy_scores", "source": "fundamentals_screener — Sales + Inventory",
     "data_freq": "annual", "frequency": "daily"},
    {"name": "signal_nwc_to_revenue", "module": "signals.nwc_to_revenue", "function": "compute", "critical": False,
     "table": "nwc_to_revenue_scores", "source": "fundamentals_screener — Sales + Receivables + Inventory + Trade Payables",
     "data_freq": "annual", "frequency": "daily"},
    {"name": "signal_sloan_accruals_full", "module": "signals.sloan_accruals_full", "function": "compute", "critical": False,
     "table": "sloan_accruals_full_scores", "source": "fundamentals_screener — Receivables + Inventory + Trade Payables + Depreciation + Total",
     "data_freq": "annual", "frequency": "daily"},
    {"name": "signal_sga_to_revenue_change", "module": "signals.sga_to_revenue_change", "function": "compute", "critical": False,
     "table": "sga_to_revenue_change_scores", "source": "fundamentals_screener — Sales + Selling and admin",
     "data_freq": "annual", "frequency": "daily"},
    {"name": "signal_fcf_margin", "module": "signals.fcf_margin", "function": "compute", "critical": False,
     "table": "fcf_margin_scores", "source": "fundamentals_screener — Sales + OCF + Net Block + CWIP + Depreciation",
     "data_freq": "annual", "frequency": "daily"},
    {"name": "signal_capex_to_dep", "module": "signals.capex_to_dep", "function": "compute", "critical": False,
     "table": "capex_to_dep_scores", "source": "fundamentals_screener — Net Block + CWIP + Depreciation",
     "data_freq": "annual", "frequency": "daily"},
    {"name": "signal_goodwill_to_assets", "module": "signals.goodwill_to_assets", "function": "compute", "critical": False,
     "table": "goodwill_to_assets_scores", "source": "fundamentals_screener — Intangible Assets + Total",
     "data_freq": "annual", "frequency": "daily"},
    {"name": "signal_debt_structure", "module": "signals.debt_structure", "function": "compute", "critical": False,
     "table": "debt_structure_scores", "source": "fundamentals_screener — Long term Borrowings + Borrowings",
     "data_freq": "annual", "frequency": "daily"},
    {"name": "signal_asset_tangibility", "module": "signals.asset_tangibility", "function": "compute", "critical": False,
     "table": "asset_tangibility_scores", "source": "fundamentals_screener — Net Block + Total",
     "data_freq": "annual", "frequency": "daily"},

    # Sector-narrative-derived cluster (plan 0003) — 4 factors inspired by
    # IIM Ahmedabad sector-narrative pages. None in scoring weights yet;
    # promotion gated on backtest |t| ≥ 1.5 in any tier.

    {"name": "signal_revenue_cv",  "module": "signals.revenue_cv",  "function": "compute",  "critical": False,
     "table": "revenue_cv_scores", "source": "fundamentals_screener — Sales (annual, 6 yrs)",
     "data_freq": "annual",        "frequency": "daily"},

    {"name": "signal_inventory_turnover", "module": "signals.inventory_turnover", "function": "compute", "critical": False,
     "table": "inventory_turnover_scores", "source": "fundamentals_screener — Sales + Inventory",
     "data_freq": "annual",                "frequency": "daily"},

    {"name": "signal_sales_growth_relative", "module": "signals.sales_growth_relative", "function": "compute", "critical": False,
     "table": "sales_growth_relative_scores", "source": "fundamentals_screener — Sales + sector peers",
     "data_freq": "annual",                   "frequency": "daily"},

    {"name": "signal_share_momentum", "module": "signals.share_momentum", "function": "compute", "critical": False,
     "table": "share_momentum_scores", "source": "stock_prices + fundamentals_screener — No. of Equity Shares",
     "data_freq": "daily",             "frequency": "daily"},

    {"name": "signal_accruals",    "module": "signals.accruals",    "function": "compute",  "critical": False,
     "table": "accruals_scores",   "source": "quarterly_income + annual_balance_sheet + annual_cash_flow",
     "data_freq": "quarterly",     "frequency": "daily"},

    {"name": "signal_consensus",   "module": "signals.consensus",   "function": "compute",  "critical": False,
     "table": "consensus_signals", "source": "analyst_consensus + forecast_history + stock_prices",
     "data_freq": "monthly",       "frequency": "daily"},

    {"name": "signal_promoter",    "module": "signals.promoter",    "function": "compute",  "critical": False,
     "table": "promoter_signals",  "source": "shareholding",        "data_freq": "quarterly", "frequency": "daily"},

    {"name": "signal_smart_money", "module": "signals.smart_money", "function": "compute",  "critical": False,
     "table": "smart_money_scores","source": "bulk_deals + stock_prices", "data_freq": "daily", "frequency": "daily"},

    {"name": "signal_macro",       "module": "signals.macro",       "function": "compute",  "critical": False,
     "table": "macro_sector_signals", "source": "macro_indicators", "data_freq": "monthly", "frequency": "daily"},

    {"name": "signal_regulatory", "module": "signals.regulatory",  "function": "compute",  "critical": False,
     "table": "macro_sector_signals", "source": "regulatory_events + regulatory_signals (AI classified)",
     "data_freq": "daily",           "frequency": "daily"},

    # ── Scoring ──
    {"name": "quality_gate",       "module": "scoring.quality_gate","function": "compute",  "critical": True,
     "table": None,                "source": "piotroski + forensic + shareholding",
     "data_freq": "quarterly",     "frequency": "daily"},

    {"name": "regime_update",      "module": "scoring.regime",      "function": "compute",  "critical": False,
     "table": "regime_state",      "source": "vix_history",         "data_freq": "daily",   "frequency": "daily"},

    {"name": "screener",           "module": "scoring.screener",    "function": "compute",  "critical": True,
     "table": "daily_picks",       "source": "all signals",         "data_freq": "daily",   "frequency": "daily"},

    # ── Output ──
    {"name": "snapshot",           "module": "output.snapshot",     "function": "compute",  "critical": False,
     "table": "daily_snapshots",   "source": "all signals + stock_prices",
     "data_freq": "daily",         "frequency": "daily"},

    {"name": "diff_engine",        "module": "output.diff_engine",  "function": "compute",  "critical": False,
     "table": "daily_changes",     "source": "daily_picks + daily_snapshots (diff)",
     "data_freq": "daily",         "frequency": "daily"},

    {"name": "dossier",            "module": "output.dossier",      "function": "compute",  "critical": False,
     "table": None,                "source": "daily_picks + all signals (Claude API)",
     "data_freq": "daily",         "frequency": "daily"},

    {"name": "email",              "module": "output.email_sender", "function": "compute",  "critical": False,
     "table": None,                "source": "daily_picks + dossiers (Gmail SMTP)",
     "data_freq": "daily",         "frequency": "daily"},
]

# Also track raw data tables (not pipeline steps — populated by migration / fetchers)
RAW_TABLES = [
    {"table": "stocks",               "source": "universe.csv (v1 migration)",     "data_freq": "weekly",    "frequency": "weekly"},
    {"table": "stock_prices",          "source": "NSE Bhavcopy archives",           "data_freq": "daily",     "frequency": "daily"},
    {"table": "quarterly_income",      "source": "Tickertape API",                  "data_freq": "quarterly", "frequency": "monthly"},
    {"table": "annual_balance_sheet",  "source": "Tickertape API",                  "data_freq": "annual",    "frequency": "monthly"},
    {"table": "annual_cash_flow",      "source": "Tickertape API",                  "data_freq": "annual",    "frequency": "monthly"},
    {"table": "shareholding",          "source": "Tickertape API",                  "data_freq": "quarterly", "frequency": "monthly"},
    {"table": "analyst_consensus",     "source": "Tickertape API",                  "data_freq": "monthly",   "frequency": "monthly"},
    {"table": "forecast_history",      "source": "Tickertape API",                  "data_freq": "monthly",   "frequency": "monthly"},
    {"table": "vix_history",           "source": "yfinance (^INDIAVIX)",            "data_freq": "daily",     "frequency": "daily"},
    {"table": "insider_trades",        "source": "NSE/BSE insider archives",        "data_freq": "daily",     "frequency": "daily"},
    {"table": "news_articles",         "source": "RSS feeds (8 sources)",           "data_freq": "daily",     "frequency": "daily"},
    {"table": "news_article_stocks",   "source": "Entity matching on news_articles","data_freq": "daily",     "frequency": "daily"},
    {"table": "bulk_deals",            "source": "NSE bulk/block deal archives",    "data_freq": "daily",     "frequency": "daily"},
    {"table": "earnings_calendar",     "source": "NSE events API",                  "data_freq": "daily",     "frequency": "daily"},
    # macro_indicators: v1-migration leftover, no v2 producer. Mark annual to silence freshness alarm.
    {"table": "macro_indicators",      "source": "v1 migration (leftover)",        "data_freq": "static",    "frequency": "annual"},
    {"table": "macro_history",          "source": "yfinance + data.gov.in + FRED",  "data_freq": "daily",     "frequency": "daily"},
    {"table": "macro_indicator_meta",   "source": "config (indicator registry)",    "data_freq": "static",    "frequency": "monthly"},
    {"table": "macro_sector_map",       "source": "config (sector mapping)",        "data_freq": "static",    "frequency": "monthly"},
    # regulatory_*: harvester paused 2026-04-10 (Anthropic budget). Score against monthly cadence until resumed.
    {"table": "regulatory_events",      "source": "Google News + RBI + PIB + Wayback", "data_freq": "daily",  "frequency": "monthly"},
    {"table": "regulatory_signals",     "source": "AI classification (Haiku+Sonnet)",  "data_freq": "daily",  "frequency": "monthly"},
    # vix_history is mirrored from macro_history.india_vix by sources.macro_yfinance._sync_vix_history.
    {"table": "vix_history",            "source": "yfinance ^INDIAVIX (mirrored from macro_history)", "data_freq": "daily", "frequency": "daily"},
]


# File-based outputs that aren't DB tables. Tracked by data_health() so the
# freshness watchdog can see them — without this, file-only producers (the
# 2026-05 HALC dossier bug) fail silently for weeks.
#
# Each entry maps a virtual_table name → glob pattern (newest file by mtime
# is the freshness anchor), a recency threshold in days, and the producer
# step the watchdog should retrigger.
FILE_OUTPUTS = [
    {
        "virtual_table": "_file_dossiers",
        "glob":          "output/dossiers_*.json",
        "freshness_field": "thesis",   # JSON must contain at least one record with this key
        "source":        "output/dossier.py (Claude API)",
        "data_freq":     "daily",
        "frequency":     "daily",
        "producer":      "dossier",    # PIPELINE_STEPS name to retrigger
    },
]

