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

TIERS = ("LARGE", "MID", "SMALL", "MICRO")

TIER_SIZES = {
    "LARGE": 100,    # top 100 by market cap
    "MID": 150,      # 101-250
    "SMALL": 2200,   # 251+, minus MICRO carveout
    # MICRO: composite spec, see tools/classify_micro_tier.py — not size-ranked
}

# Minimum ADTV (₹ Cr) to be investable per tier. MICRO are below this
# threshold by definition (the manipulation pre-requisite) and excluded from picks.
ADTV_MIN = {
    "LARGE": 10.0,
    "MID": 5.0,
    "SMALL": 1.0,
    "MICRO": 0.0,   # advisory only — MICRO are excluded by tier, not by ADTV
}

# Tiers excluded from daily_picks / dossier / morning_brief / action_queue.
# MICRO stocks are CLASSIFIED but never recommended — they're too illiquid +
# data-thin to trust, and trivially manipulatable by any operator with size.
# See tools/classify_micro_tier.py for the composite criteria.
EXCLUDED_FROM_PICKS = ("MICRO",)

# ── Signal Weights per Tier (from C13b validation) ──
# t >= 2.5 → 1.0x (primary)
# t = 1.5-2.5 → 0.5x (secondary)
# t = 0.5-1.5 → 0.2x (tertiary)
# t < 0.5 → 0x (excluded)

SIGNAL_WEIGHTS = {
    # 2026-05-31 promotion wave: idle-but-validated factors brought into production
    # after an orthogonality sweep (each new factor max |ρ|≤0.27 vs wired). pt_upside
    # is CAPPED well below its t=7-9 implied share — the |t| is still pending an
    # artifact re-verification (analyst-PT PIT history; open question, recheck 2026-08),
    # so it gets a strong-but-not-dominant weight. eps_growth held back (ρ=0.63 with
    # consensus → redundant). Each tier renormalised to Σ=1.
    "LARGE": {
        # 2026-06-02 horizon-gate review (ADR 0038, tools/promotion_gate.py): both
        # lenses — v1 C13b AND the net-of-cost gate — agree LARGE's value/quality
        # block is weak (small-cap-grade factors carrying LARGE weight; matches the
        # walk-forward "LARGE ~zero OOS skill"). momentum (t=0.00) DROPPED — it broke
        # the config's own t<0.5→0× rule AND the gate REJECTs it. accruals + piotroski
        # equalised to 0.09 as explicit DIVERSIFICATION ballast (not validated alpha —
        # both gate-REJECT) kept only to avoid over-concentrating consensus.
        # earnings_yield trimmed (over-weighted for a 0.5×-secondary; gate REJECT in
        # LARGE — strong in SMALL, weak here). Freed weight → the only doubly-validated
        # pair (consensus + book_to_price). MID left untouched (its flags are
        # gate↔history CONFLICTS, not acted on).
        "consensus":      0.35,   # t=3.52 primary; gate LIBRARY 2.29 — the LARGE anchor
        "pt_upside":      0.25,   # t=7.15 primary (capped — artifact re-verify 2026-08)
        "earnings_yield": 0.12,   # t=1.57 secondary; gate REJECT in LARGE — trimmed
        "book_to_price":  0.10,   # t=0.79; gate LIBRARY (sign-unstable) — best of the rest
        "accruals":       0.09,   # t=0.20; gate REJECT — diversifier, not alpha
        "piotroski":      0.09,   # t=0.51; gate REJECT — diversifier, not alpha
    },
    "MID": {
        # iv_skew_25d added 2026-05-31 (ADR 0035): MID t=+3.16 KEEP, 48 wk, orthogonal.
        # pt_upside added in the same promotion wave (MID t=8.40, capped).
        "pt_upside":      0.25,   # t=8.40 primary (capped — artifact re-verify 2026-08)
        "accruals":       0.19,   # t=3.20 primary
        "iv_skew_25d":    0.14,   # t=3.16 primary (MID, F&O stocks)
        "piotroski":      0.12,   # t=2.23 secondary
        "book_to_price":  0.12,   # t=2.33 secondary
        "consensus":      0.09,   # t=2.20 secondary
        "earnings_yield": 0.05,   # t=1.01 tertiary
        "promoter":       0.04,   # t=0.83 tertiary
    },
    "SMALL": {
        # promotion wave: pt_upside (t=9.14, capped), pledge_quality (t=5.90),
        # delivery_anomaly_z (t=4.76, n=103) — all orthogonal (max |ρ|≤0.08 vs wired).
        # 2026-06-02 horizon-gate review (ADR 0038): SMALL is the healthiest tier
        # (walk-forward VALIDATED) — most factors PROMOTE in both lenses. One trim:
        # pledge_quality 0.13→0.10 — the gate demotes it to LIBRARY (1.96) and flags
        # it single-horizon-fragile (works only @20d) + sign-unstable; kept (not gutted)
        # for its orthogonal promoter-pledge-stress info. Freed weight → book_to_price,
        # the gate's single strongest factor in the whole model (net_t 13.58 @252d).
        # smart_money carries 0.06 but is NOT backtested (no PIT/gate entry) — flagged
        # to validate or reclassify as a diversifier. accruals = gate↔history conflict,
        # held.
        "pt_upside":          0.16,   # t=9.14 primary (capped — artifact re-verify 2026-08)
        "promoter":           0.15,   # t=3.20 primary; gate LIBRARY 1.83
        "earnings_yield":     0.12,   # t=3.13 primary; gate PROMOTE 7.75 @252d
        "book_to_price":      0.12,   # t=2.54 secondary; gate PROMOTE 13.58 @252d (strongest)
        "delivery_anomaly_z": 0.11,   # t=4.76 primary (n=103, orthogonal); gate PROMOTE 2.12
        "pledge_quality":     0.10,   # t=5.90; gate LIBRARY 1.96 fragile — trimmed, kept orthogonal
        "piotroski":          0.09,   # t=2.81 secondary; gate PROMOTE 4.87
        "smart_money":        0.06,   # smart_money_score: backtested 2026-06-02 → SMALL t=1.06 (n=6, DROP/thin). Prior "t=2.49" was avg_delivery borrowed via a mis-alias. Diversifier — re-judge as anchors accrue.
        "accruals":           0.06,   # t=2.10 secondary; gate REJECT — conflict, held
        "momentum":           0.03,   # t=1.76 tertiary; gate REJECT — token
    },
}


# ── Two optimized weight schemes from PIT IC backtest (2026-05-28) ──
# Source: tools/optimize_weights.py reads pit_ic_by_tier_v2 and normalises by tier.
# Each scheme is "aggressive" — no caps, no diversification floor. pt_upside +
# eps_growth dominate because their t-stats earn it (t=7-9 and t=5 respectively).
# Choose by passing --variant {return,sharpe} to scoring/screener.

# MaxReturn: w_i ∝ |t_stat_i| × sign(IC_i). Favours absolute IC magnitude.
# Refresh: python -m tools.optimize_weights --filter-wired
# 2026-05-29: pledge_quality + delivery_anomaly_z now wired (Next-3 #3), so SMALL
# includes both; MID stays at 2 factors until interest_coverage/ccc/etc are wired.
SIGNAL_WEIGHTS_RETURN = {
    "LARGE": {
        "pt_upside":         0.4679,  # t=7.15
        "eps_growth":        0.3475,  # t=5.31
        "consensus":         0.1846,  # t=2.82
    },
    "MID": {
        "pt_upside":         0.7241,  # t=8.40
        "accruals":         -0.2759,  # t=-3.20 (inverse)
    },
    "SMALL": {
        "pt_upside":         0.2364,  # t=9.14
        "pledge_quality":    0.1526,  # t=5.90
        "delivery_anomaly_z":0.1232,  # t=4.76
        "smart_money":       0.1131,  # t=4.37 (avg_delivery_pct_30d)
        "eps_growth":        0.0836,  # t=3.23
        "earnings_yield":    0.0809,  # t=3.13
        "consensus":         0.0776,  # t=3.00
        "promoter":          0.0678,  # t=2.62
        "piotroski":         0.0649,  # t=2.51
    },
}

# MaxSharpe: w_i ∝ |ICIR_i| × sign(IC_i). Favours information ratio (mean/vol of IC).
SIGNAL_WEIGHTS_SHARPE = {
    "LARGE": {
        "eps_growth":        0.5239,  # ICIR=1.88
        "pt_upside":         0.3371,  # ICIR=1.21
        "consensus":         0.1390,  # ICIR=0.50
    },
    "MID": {
        "pt_upside":         0.6533,  # ICIR=1.42
        "accruals":         -0.3467,  # ICIR=-0.75 (inverse)
    },
    "SMALL": {
        "pt_upside":         0.2169,  # ICIR=1.54
        "pledge_quality":    0.1488,  # ICIR=1.06
        "eps_growth":        0.1435,  # ICIR=1.02
        "earnings_yield":    0.0983,  # ICIR=0.70
        "smart_money":       0.0914,  # ICIR=0.65
        "delivery_anomaly_z":0.0775,  # ICIR=0.55
        "piotroski":         0.0768,  # ICIR=0.55
        "consensus":         0.0745,  # ICIR=0.53
        "promoter":          0.0722,  # ICIR=0.51
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

    # Plan 0005 Phase C: yfinance fallback for SIDs not in NSE bhavcopy
    # (InvITs, REITs, BSE-only listings, recent IPOs). Tries .NS first then
    # .BO. Empirically 90% hit rate on the 339 missing SIDs as of 2026-05-24.
    {"name": "fetch_prices_fallback", "module": "sources.yfinance_prices", "function": "compute", "critical": False,
     "table": "stock_prices",      "source": "yfinance .BO / .NS (gap-fill)", "data_freq": "daily", "frequency": "daily"},

    # Corporate actions (splits/bonuses/special dividends) over a short trailing
    # window. Feeds Gate 3 temporal-continuity's escape hatch so real ex-date
    # price step-changes (LIC 1:2 split, LEM 11.5×, …) classify as CONTINUOUS
    # instead of generating noise verdicts. Idempotent INSERT OR IGNORE; the
    # monthly `--source corp --months 24` deep backfill is the gap-repair path.
    {"name": "fetch_corp_actions", "module": "sources.nselib_pull", "function": "compute_corp_actions", "critical": False,
     "table": "corporate_actions", "source": "NSE corporate-actions (nselib)", "data_freq": "daily", "frequency": "daily"},

    # Track 3.1b — NSE F&O EOD grid. One nselib.fno_bhav_copy call = the whole
    # market (~16K info-carrying rows/day). Runs in the morning pipeline against
    # the prior session's archive, exactly like fetch_bhavcopy. compute() walks a
    # short trailing window so a missed day self-heals. compute_pcr() must run
    # AFTER (it aggregates the rows just written) — keep this ordering.
    {"name": "fetch_fno_bhav",     "module": "sources.fno_pull",     "function": "compute", "critical": False,
     "table": "fno_bhav",          "source": "NSE F&O bhavcopy (nselib UDiFF)", "data_freq": "daily", "frequency": "daily"},

    {"name": "compute_fno_pcr",    "module": "sources.fno_pull",     "function": "compute_pcr", "critical": False,
     "table": "fno_pcr_history",   "source": "fno_bhav (nearest-expiry rollup)", "data_freq": "daily", "frequency": "daily"},

    {"name": "compute_fno_iv",     "module": "sources.fno_iv",       "function": "compute", "critical": False,
     "table": "fno_iv_history",    "source": "fno_bhav (Black-76 IV surface inversion)", "data_freq": "daily", "frequency": "daily"},

    {"name": "universe_liveness",  "module": "sources.universe",     "function": "compute", "critical": False,
     "table": "stocks",            "source": "stock_prices (recent activity)", "data_freq": "daily", "frequency": "daily"},

    {"name": "fetch_news",         "module": "sources.rss",          "function": "compute", "critical": False,
     "table": "news_articles",     "source": "RSS feeds (8 sources)", "data_freq": "daily", "frequency": "daily"},

    # Regulatory harvester is daily (cheap incremental, ~5 min).
    {"name": "fetch_regulatory",   "module": "sources.regulatory_harvester", "function": "harvest_incremental", "critical": False,
     "table": "regulatory_events", "source": "Google News last 30d", "data_freq": "daily", "frequency": "daily"},

    # ── Mutual Fund universe (research-only, plan prfect-lets-add-a-zazzy-eich, 2026-05-26) ──
    # Weekly: refresh scheme master from AMFI NAVAll.txt (~14k schemes, single HTTP).
    {"name": "fetch_mf_master",    "module": "sources.mf_amfi_master",       "function": "compute", "critical": False,
     "table": "mf_scheme_master",  "source": "AMFI NAVAll.txt",       "data_freq": "weekly", "frequency": "weekly"},
    # Weekly: classify data quality — flag wound-up / segregated / interval / bonus / anomalous schemes
    # so they don't pollute the universe browser, scorer, or category stats. Runs AFTER master refresh
    # so new schemes get classified; metric-based ANOMALOUS flags get picked up on the next monthly
    # metrics recompute (the classifier reads from mf_metrics if present).
    {"name": "classify_mf_quality","module": "sources.mf_data_quality",      "function": "compute", "critical": False,
     "table": "mf_scheme_master",  "source": "name patterns + NAV jumps", "data_freq": "weekly", "frequency": "weekly"},
    # Daily: refresh today's NAVs for all schemes from same source (single HTTP, idempotent).
    {"name": "fetch_mf_nav_daily", "module": "sources.mf_nav_daily",         "function": "compute", "critical": False,
     "table": "mf_nav_history",    "source": "AMFI NAVAll.txt",       "data_freq": "daily",  "frequency": "daily"},
    # Monthly: recompute returns + risk + scorer + rolling-returns + category aggregates.
    {"name": "compute_mf_metrics", "module": "signals.mf_metrics",           "function": "compute", "critical": False,
     "table": "mf_metrics",        "source": "mf_nav_history + Nifty50 benchmark", "data_freq": "monthly", "frequency": "monthly"},
    # Monthly: refresh top-N MF holdings via ETMoney scrape (AMFI's holdings data has 45d lag,
    # monthly refresh is sufficient). Rate-limited at 2.5s/req with 30s pause every 100 reqs.
    {"name": "scrape_mf_holdings", "module": "sources.mf_holdings_scrape",   "function": "compute", "critical": False,
     "table": "mf_holdings",       "source": "ETMoney portfolio-details (public)", "data_freq": "monthly", "frequency": "monthly"},

    # NOTE: classify_regulatory, classify_news, news_brief, and fetch_broker_recos
    # all moved to END of pipeline — they were blocking production. See block
    # at the bottom: "Background / non-blocking section".

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
    # Plan 0005 Phase A: refresh eligibility BEFORE screener so eligible_coverage
    # uses today's snapshot, not yesterday's.
    {"name": "refresh_eligibility", "module": "tools.refresh_eligibility", "function": "refresh",
     "critical": False,
     "table": "universe_eligibility", "source": "eligibility/registry.py — 8 signals × universe",
     "data_freq": "daily",         "frequency": "daily"},

    {"name": "quality_gate",       "module": "scoring.quality_gate","function": "compute",  "critical": True,
     "table": None,                "source": "piotroski + forensic + shareholding",
     "data_freq": "quarterly",     "frequency": "daily"},

    {"name": "regime_update",      "module": "scoring.regime",      "function": "compute",  "critical": False,
     "table": "regime_state",      "source": "vix_history",         "data_freq": "daily",   "frequency": "daily"},

    # Financial sub-model (Track 2.2b, ADR 0030) — daily snapshot of per-
    # stock score for 158 Banks + NBFCs. Reads latest quarterly + annual
    # from banking_metrics; renormalizes 40% AQ + 30% P + 15% C (NULL
    # until 2.2c) + 15% F over present components. Currently print-only:
    # the screener doesn't route Financials through it yet (Phase 2.2d
    # decision pending t-stat ≥ 2.0 backtest validation).
    {"name": "compute_financial_signal", "module": "signals.financial_signal", "function": "compute", "critical": False,
     "table": "financial_signal_scores", "source": "banking_metrics", "data_freq": "daily", "frequency": "daily"},

    {"name": "screener",           "module": "scoring.screener",    "function": "compute",  "critical": True,
     "table": "daily_picks",       "source": "all signals",         "data_freq": "daily",   "frequency": "daily"},

    # Benchmark + smart-beta index history (NIFTY 50 / Midcap 150 / Smallcap
    # 250 …). Was manual-only → went 32d stale (2026-06-01) → pick_outcomes
    # excess returns silently NULL'd, and nse_index_history wasn't even
    # freshness-tracked (not a pipeline-output table). Now a daily step:
    # short rolling window, idempotent INSERT OR IGNORE. Must run BEFORE
    # compute_pick_outcomes so the benchmark is current when excess is computed.
    {"name": "fetch_nse_indices",  "module": "sources.nselib_pull", "function": "compute_nse_indices", "critical": False,
     "table": "nse_index_history", "source": "NSE index history (nselib)",
     "data_freq": "daily",         "frequency": "daily"},

    # Live equity curve — realized forward returns on every daily_picks row.
    # Runs after screener (today's picks land first) but needs ≥20 trading days
    # of forward data to write a row, so it's writing prior mature rows daily.
    # Idempotent upsert by (sid, pick_date, window_days).
    {"name": "compute_pick_outcomes", "module": "tools.compute_pick_outcomes", "function": "compute", "critical": False,
     "table": "pick_outcomes",     "source": "daily_picks + stock_prices + nse_index_history",
     "data_freq": "daily",         "frequency": "daily"},

    # Plan 0007 Phase 1 — daily Unified Health Score (UHS) writer. Computes
    # factor + table + system UHS for today's snapshot. include_picks=True so
    # the daily_picks UHS rollup is also persisted alongside factors. Reads from
    # universe_eligibility (eligibility/registry), data_health (db.py), and
    # FACTOR_LINEAGE (lineage.py). Non-critical (UHS is observation, not gate).
    {"name": "compute_health_score", "module": "scoring.health_score", "function": "compute", "critical": False,
     "table": "health_score",      "source": "universe_eligibility + data_health + FACTOR_LINEAGE",
     "data_freq": "daily",         "frequency": "daily"},

    # Plan 0007 Phase 6 — External Anchor (Gate 7). Promotes yesterday's NSE
    # bhavcopy rows to external_anchors then audits non-NSE sources (yfinance)
    # for drift. Writes gate_7_anchor verdicts feeding UHS Consistency dim.
    # Non-critical: anchor data is the foundation of the closed-loop fix,
    # but a failure to audit doesn't compromise the primary pick pipeline.
    {"name": "anchor_audit", "module": "tools.anchor_audit", "function": "compute", "critical": False,
     "table": "external_anchors",  "source": "stock_prices (bhavcopy + yfinance)",
     "data_freq": "daily",         "frequency": "daily"},

    # Plan 0007 Phase 8 — UHS calibration log. Joins every pick_outcomes row
    # to its daily_picks.uhs_score so that once 6+ months of forward returns
    # accumulate (~late Nov 2026) the uniform 20/20/20/20/20 dim weighting can
    # be regression-validated against realised return. Until then: observation
    # only. Non-critical.
    {"name": "update_uhs_calibration", "module": "scoring.confidence", "function": "update_calibration_log",
     "critical": False, "table": "uhs_calibration_log",
     "source": "pick_outcomes + daily_picks.uhs_score",
     "data_freq": "daily",         "frequency": "daily"},

    # Sector briefs — plan 0006 Phase A. One sector_briefs row per sector per
    # date with macro + model + regulatory rollup and a bucket classifier
    # (BOOMING / LIKELY / HEADWIND / QUIET). Drives the /sectors digest UX
    # in Phase C. Non-critical: a failure here doesn't block dossiers or
    # email. Idempotent (INSERT OR REPLACE on sector + date).
    {"name": "compute_sector_briefs", "module": "signals.sector_briefs", "function": "compute", "critical": False,
     "table": "sector_briefs",     "source": "macro_sector_signals + daily_picks + regulatory_signals",
     "data_freq": "daily",         "frequency": "daily"},

    # Sector momentum — plan 0006 Phase E. Per-sector S/M/L relative strength vs
    # NIFTY 50 (constituent cap-weighted), classified strong/neutral/weak by
    # tercile. UPDATEs sector_briefs.horizon_* in place, so it runs AFTER
    # compute_sector_briefs. Powers the horizon badges on the /sectors digest.
    {"name": "compute_sector_momentum", "module": "signals.sector_momentum", "function": "compute", "critical": False,
     "table": "sector_briefs",     "source": "stock_prices + stocks + macro_history (nifty50)",
     "data_freq": "daily",         "frequency": "daily"},

    # Sector force breakdown — plan 0006 Phase B. Sits on top of sector_briefs.
    # Per (sector, date) emits up to 4 rows, one per force {macro, regulation,
    # tech, market}. Market is reserved for v2 (no sector-level FII/DII data).
    # Powers the "BY FORCE" 2×2 grid in the Phase C /sectors digest UX.
    {"name": "compute_sector_forces", "module": "signals.sector_forces", "function": "compute", "critical": False,
     "table": "sector_force_breakdown", "source": "sector_briefs + regulatory_signals + sector_metadata",
     "data_freq": "daily",         "frequency": "daily"},

    # Sector dossiers — plan 0006 Phase D. LLM-narrated per-sector thesis on top
    # of briefs + forces + sector_metadata. ~11 Claude calls/night (~₹3-5).
    # Non-critical: a failure must not block the stock dossier or email. Same
    # no-raw-numbers hygiene contract as output.dossier; invalid → valid=0.
    {"name": "compute_sector_dossiers", "module": "output.sector_dossier", "function": "compute", "critical": False,
     "table": "sector_dossiers",   "source": "sector_briefs + sector_force_breakdown + sector_metadata (Claude API)",
     "data_freq": "daily",         "frequency": "daily"},

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

    # PIT replay freeze — captures today's pipeline inputs+outputs as a
    # frozen anchor. Daily cadence means every day becomes a regression-test
    # case going forward. Non-critical: a freeze failure shouldn't gate email.
    # See [tools/pit_replay.py] and Plan 0005 Phase E.
    {"name": "pit_replay_freeze",  "module": "tools.pit_replay",    "function": "freeze",   "critical": False,
     "table": "pit_replay_snapshots", "source": "scoring.screener._load_signals + score_universe (frozen)",
     "data_freq": "daily",         "frequency": "daily"},

    # MICRO tier reclassifier — keeps the SMALL/MICRO boundary fresh as ADTV,
    # quality scores, and fundamental depth change. Idempotent. Demotes any
    # MICRO that re-qualifies for SMALL. See tools/classify_micro_tier.py.
    {"name": "classify_micro_tier","module": "tools.classify_micro_tier", "function": "reclassify", "critical": False,
     "table": "stocks",            "source": "stocks + stock_prices + piotroski_scores + quarterly_income",
     "data_freq": "daily",         "frequency": "daily"},

    # ── Background / non-blocking section ──
    # Heavy enrichment + scrapes that don't gate today's picks. Moved AFTER
    # email so a slow run never blocks production. 2026-05-25 incident:
    # classify_regulatory was second-from-top and ran 1.5+hr daily, blocking
    # fetch_broker_recos + signals + screener + dossier + email entirely.
    # Each runs with its own internal cap so the daily cron has bounded
    # runtime even when there's a large backlog.

    # News Phase 2 enrichment — Claude Haiku (~$0.001/article, ~$1/day).
    {"name": "classify_news",       "module": "sources.news_classifier", "function": "compute", "critical": False,
     "table": "news_enriched",     "source": "news_articles (Claude Haiku enrich)", "data_freq": "daily", "frequency": "daily"},

    # Daily news brief — Claude Sonnet (~$0.05/day). After classify_news.
    {"name": "news_brief",          "module": "sources.news_brief",   "function": "compute", "critical": False,
     "table": "news_briefs",       "source": "news_enriched (Claude Sonnet synthesis)", "data_freq": "daily", "frequency": "daily"},

    # Regulatory classifier — hard-capped at DAILY_CLASSIFIER_CAP (500/run) so
    # the 7.5K-event backlog drains over 15 days without ever blocking cron.
    {"name": "classify_regulatory","module": "sources.regulatory_classifier", "function": "compute", "critical": False,
     "table": "regulatory_signals","source": "regulatory_events (AI-classified, capped 500/run)", "data_freq": "daily", "frequency": "daily"},

    # Moneycontrol broker recos — WEEKLY (Sunday only per `frequency: weekly`).
    # DELAY=12s × 2336 sids ≈ 8 hours. Pipeline runner honors frequency since
    # 2026-05-25. Discovery one-time: --discover-only (mc_slug already
    # populated for 2336 stocks).
    {"name": "fetch_broker_recos", "module": "sources.moneycontrol_recos", "function": "compute", "critical": False,
     "table": "broker_recommendations", "source": "Moneycontrol HTML (12s/req)",   "data_freq": "weekly", "frequency": "weekly"},

    # Banking metrics — Screener.in HTML scrape, 158 Banks + NBFCs (ADR 0030,
    # Phase 2.2a-ii). Underlying data is quarterly so MONTHLY cron suffices.
    # ~3 s/stock × 158 = ~8 min. Function signature differs from pipeline's
    # standard `compute()` — banking_metrics.main() takes argparse args; the
    # runner needs `--universe`. Wrapped via `compute()` helper.
    {"name": "fetch_banking_metrics", "module": "sources.banking_metrics", "function": "compute_universe", "critical": False,
     "table": "banking_metrics",    "source": "Screener.in stock pages (158 banks+NBFCs)", "data_freq": "quarterly", "frequency": "monthly"},
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

