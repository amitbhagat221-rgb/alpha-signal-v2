"""
Alpha Signal v2 — Configuration

Every tunable value lives here. No magic numbers in source/signal/scoring code.
Import what you need:
    from config import TIERS, PIPELINE_STEPS, DB_PATH
(External hosts — rate limits, headers, LLM model ids — live in hosts.py; factor
weights live on each factor in factors.py.)
"""

from pathlib import Path

# ── Paths ──

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "alpha_signal.db"
SCHEMA_PATH = PROJECT_ROOT / "schema.sql"
LOG_PATH = PROJECT_ROOT / "output" / "pipeline.log"

# ── Universe ──
# The segments (ADR 0052 "Segment" invariant): ranking happens only inside a tier,
# and a tier with pickable=False never reaches daily_picks. Everything tier-keyed
# (picks per tier, transaction costs, outcome benchmarks, regime allocations, the
# segment rule, EXCLUDED_FROM_PICKS, factors.TIERS) is derived from — or keyed by —
# this one dict, so adding a tier = one entry here (+ its weight content in
# factors.FACTORS). schema.sql's stocks.cap_tier CHECK is the one other place.
#   rank_max   segment rule (scoring/segment.py): market-cap rank ≤ rank_max, after
#              the previous tier (None = the rest). SEBI/AMFI cut-offs: 100 / 250.
#   carve_from a tier assigned by its own classifier out of another tier's members
#              (MICRO ← SMALL: tools/classify_micro_tier.py — ADR 0026; it runs
#              AFTER the segment node).
#   pickable   False → classified and scored, never recommended.
#   picks      names per tier in the published 5/5/5 book (PORTFOLIO["picks_per_tier"]).
#   cost_bps   one-way transaction cost (TRANSACTION_COSTS_BPS).
#   benchmark  nse_index_history index the pick outcomes are measured against.
TIERS = {
    "LARGE": {"rank_max": 100, "pickable": True, "picks": 5, "cost_bps": 30,
              "benchmark": "NIFTY 50"},
    "MID":   {"rank_max": 250, "pickable": True, "picks": 5, "cost_bps": 50,
              "benchmark": "NIFTY MIDCAP 150"},
    "SMALL": {"rank_max": None, "pickable": True, "picks": 5, "cost_bps": 150,
              "benchmark": "NIFTY SMALLCAP 250"},
    # Too illiquid + data-thin to trust, and trivially manipulatable by any
    # operator with size — CLASSIFIED but never recommended (ADR 0026).
    "MICRO": {"carve_from": "SMALL", "pickable": False},
}
PICKABLE_TIERS = tuple(t for t, spec in TIERS.items() if spec["pickable"])
# Tiers excluded from daily_picks / dossier / morning_brief / action_queue.
EXCLUDED_FROM_PICKS = tuple(t for t, spec in TIERS.items() if not spec["pickable"])
# Segment-node hysteresis (scoring/segment.py): a stock already in a tier keeps it
# until its market-cap rank leaves the boundary by more than this fraction of the
# boundary rank (±10 at 100, ±25 at 250). Measured, see scoring/segment.py.
TIER_HYSTERESIS = 0.10

# ── Signal weights ──
# Hand-set, never derived (CLAUDE.md "Backtest hygiene", docs/reference/signal-weights.md)
# — but they live ON the factor: each wired factors.FACTORS entry carries
# `weights: {tier: w}` (ADR 0052 D4, amends ADR 0017). factors.SIGNAL_WEIGHTS is the
# derived {tier: {weight_key: w}} view every consumer imports; the two dry-run
# variant schemes (SIGNAL_WEIGHTS_RETURN / _SHARPE) also live in factors.py.
# config.SIGNAL_WEIGHTS* (resolved by __getattr__) are LEGACY read-only aliases kept for
# cockpit/api.py and cockpit_ops/api.py — delete once they import factors.
_FACTORS_ALIASES = ("SIGNAL_WEIGHTS", "SIGNAL_WEIGHTS_RETURN", "SIGNAL_WEIGHTS_SHARPE")


def __getattr__(name):
    """PEP 562: resolve the legacy aliases lazily (factors imports config)."""
    if name in _FACTORS_ALIASES:
        import factors
        return getattr(factors, name)
    raise AttributeError(f"module 'config' has no attribute {name!r}")


# ── VIX Regime ──
# India-VIX band → allocation across the PICKABLE tiers (keyed by tier name; each
# regime's alloc sums to 1). scoring/regime.py reads REGIMES.
REGIMES = {
    "CALM":    {"vix": (0.0, 13.0),   "alloc": {"LARGE": 0.30, "MID": 0.35, "SMALL": 0.35}},
    "NORMAL":  {"vix": (13.0, 25.0),  "alloc": {"LARGE": 0.40, "MID": 0.30, "SMALL": 0.30}},
    "CAUTION": {"vix": (25.0, 35.0),  "alloc": {"LARGE": 0.55, "MID": 0.25, "SMALL": 0.20}},
    "CRISIS":  {"vix": (35.0, 999.0), "alloc": {"LARGE": 0.70, "MID": 0.20, "SMALL": 0.10}},
}
# LEGACY positional view (vix_low, vix_high, *alloc in PICKABLE_TIERS order) — kept
# only for output/diff_engine.py and cockpit_ops/api.py, which unpack 5-tuples.
# Delete once they read REGIMES.
VIX_REGIMES = {name: (*r["vix"], *(r["alloc"][t] for t in PICKABLE_TIERS))
               for name, r in REGIMES.items()}

# Days in new regime before switching (hysteresis)
VIX_HYSTERESIS_DAYS = 3

# ── Forensic Thresholds ──

FORENSIC = {
    "beneish_grey": -2.22,     # above → possible manipulator
    "beneish_red": -1.78,      # above → likely manipulator
    "altman_distress": 1.10,   # below → distress zone
    "altman_grey": 2.60,       # below → grey zone
}

# ── Revenue-plausibility hard exclusion (tier-agnostic) ──
# Catches what Beneish/Altman structurally cannot: a steady-state, internally-
# consistent revenue fabrication (Rajesh Exports / REXP, SEBI 2026-06-03 — ₹15.15
# lakh cr fabricated, ~99.8% of consolidated revenue). The accrual/distress models
# are YoY-change detectors and were defeated by 5yr of stable fake ratios + a
# fabricated cash side. The tell they ALL miss is the LEVEL: revenue churning many
# times the asset base at ~zero profit, which no legitimate business produces.
# Two-part AND so legitimate high-turnover names (distribution/staffing/agri-
# commodity, ~5-6x at 1-3% margin) are NOT caught — only impossible-turnover-at-
# zero-margin. On 2026-06-04 data this flags exactly 1 of 1,526 non-financials: REXP.
# A hard exclusion (drops from daily_picks), NOT a weighted factor → no t-stat gate.
REVENUE_PLAUSIBILITY = {
    "min_assets_cr": 100.0,        # below this, the ratio is rounding noise — skip
    "turnover_max": 8.0,           # TTM revenue / total_assets above this is suspect
    "abs_net_margin_max": 0.005,   # …AND |net margin| < 0.5% → revenue at ~no profit
}

# ── Portfolio Construction ──

PORTFOLIO = {
    "max_stocks_per_sector": 5,
    "max_stock_weight_pct": 5.0,
    "max_daily_picks": 15,
    "picks_per_tier": {t: TIERS[t]["picks"] for t in PICKABLE_TIERS},
    # ── Track 3.3c — HRP position sizing (portfolio_construction.py) ──
    # The sized book draws picks_per_tier names per tier (the same 5/5/5 = 15-name
    # holdable book the paper portfolio uses), then HRP-allocates risk under these
    # caps. ADVISORY only until tools/validate_rank_skill.py clears. See ADR 0044.
    "hrp": {
        "cov_lookback_days": 500,   # trading days of daily returns for the covariance
        "cov_min_obs": 220,         # drop a name with thinner history than this
        "ledoit_wolf": True,        # shrink the sample covariance toward structure
        "ret_clip": (-0.5, 0.5),    # daily log-return winsorization — split-defense
                                    # (stock_prices.close is raw/unadjusted; mirrors
                                    # the signals/sector_momentum.py RET_CLIP rationale)
        "tilt_lambda": 0.6,         # alpha-score tilt strength (0 = pure risk parity)
        "min_adtv_inr": 1.0e7,      # liquidity floor: drop names whose 20d median
                                    # traded_value < ₹1cr/day (un-sizable for a retail book)
        # Weight caps for the CONCENTRATED ~15-name book. NOTE these intentionally
        # differ from the top-level max_stock_weight_pct=5.0, which is infeasible here
        # (15 names × 5% = 75% < 100%). 1/15≈6.7%, so the per-stock cap must exceed that.
        "max_stock_weight": 0.12,   # per-name ceiling
        "max_sector_weight": 0.35,  # per-sector ceiling (concentration guard)
        # Banded/hysteresis rebalancing (ADR 0046). The daily-reset book measured
        # 18.5%/day one-way turnover (2026-07-04 audit, Port-F1) — cost-fatal vs the
        # measured edge. Hysteresis: enter at top-5, exit only below top-8 within the
        # tier; carry the previous book unchanged unless a weight drifts >2pp from
        # target. "mode": "daily" preserves the old rebuild-from-scratch behavior.
        # DEFAULT flipped to banded 2026-07-05 — regime change in the stored
        # portfolio_weights evidence stream (books before/after are not comparable).
        "rebalance": {
            "mode": "banded",   # "banded" (default) | "daily" (legacy full rebuild)
            "rank_exit": 8,     # sell a held name only when its within-tier rank > this
            "drift_pp": 2.0,    # re-run HRP only if a weight drifts > this many pp from target
            # Iteration 2 (ADR 0046) — the 8/2pp band alone measured 12.0%/day at
            # net Sharpe -0.84 (cost-fatal): rank instability drove ~2 sells/day and
            # every trigger re-ran full HRP (~7.4pp jitter in unchanged names). The
            # tools/rebalance_sim.py --matrix winner (best net Sharpe, tiebreak lower
            # turnover) is d3/partial/trigger-only: 6.2%/day, net Sharpe +0.11 — the
            # first cost-POSITIVE cell. Debounce is the turnover lever; partial-resize
            # is the net-Sharpe lever (removes HRP jitter); a weekly full-resize
            # calendar HURTS (re-injects jitter) so it stays off.
            "debounce_days": 3,           # sell only after N consecutive days below rank_exit
            "resize": "partial",          # on a name change: "partial" (survivors keep drifted
                                          # weights, vacated mass funds buys) | "full" (re-run HRP)
            "full_resize_weekday": None,  # 0=Mon: full HRP re-run on the first pick_date of each
                                          # trade-week; None = trigger-only full re-sizes (winner)
        },
    },
}

# ── Transaction Costs (bps) ──

TRANSACTION_COSTS_BPS = {t: spec["cost_bps"] for t, spec in TIERS.items() if "cost_bps" in spec}

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

# ── Hosts (API politeness + LLM model ids) live in hosts.HOSTS (plan 0015 Phase 2) ──

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
    # Staleness floor on every "latest snapshot per sid" subquery in the screener
    # (audit Port-F6): a signal whose producer froze months ago (e.g. piotroski
    # for Financials, frozen 2026-05-09) was still feeding ranks forever via
    # MAX(snapshot_date) — there's no natural expiry. 45d covers the weekly
    # cadence (Task 2.3, audit Eff-F4) with 6× headroom; older rows are treated
    # as missing and weight_coverage renormalizes over the signals still present.
    "max_signal_age_days": 45,
}

# ── Pipeline ──

PIPELINE = {
    "retry_count": 1,
    "email_on_failure": True,
    # Plan 0015 Phase 1b: run steps in the order graph.py derives from their
    # declared reads/writes (the email's critical path first; every read keeps
    # the data version it saw under the hand order — tests/test_graph.py).
    # False = the PIPELINE_STEPS list order (instant revert).
    "derived_order": True,
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
     "table": "macro_history",     "source": "yfinance (20 tickers)",  "data_freq": "daily",  "frequency": "daily",
     "reads": ["macro_history", "macro_indicator_meta"],
     "writes": ["macro_history", "macro_indicator_meta", "vix_history"],
     "lagged_reads": ["macro_history@fetch_macro_gov"]},

    {"name": "fetch_macro_gov",    "module": "sources.macro_gov",     "function": "compute", "critical": False,
     "table": "macro_history",     "source": "data.gov.in + FRED",    "data_freq": "monthly", "frequency": "weekly",
     "reads": ["stocks"],
     "writes": ["macro_history", "macro_indicator_meta"],
     "lagged_writes": ["macro_indicator_meta"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos", "stocks@segment_tiers", "stocks@universe_liveness"]},

    {"name": "fetch_insider",      "module": "sources.nse_insider",   "function": "compute", "critical": False,
     "table": "insider_trades",    "source": "NSE PIT API",          "data_freq": "daily",  "frequency": "daily",
     "reads": ["stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos", "stocks@segment_tiers", "stocks@universe_liveness"]},

    {"name": "fetch_bulk_deals",   "module": "sources.nse_bulk",     "function": "compute", "critical": False,
     "table": "bulk_deals",        "source": "NSE archives CSV",     "data_freq": "daily",  "frequency": "daily",
     "reads": ["stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos", "stocks@segment_tiers", "stocks@universe_liveness"]},

    {"name": "fetch_bhavcopy",     "module": "sources.nse",          "function": "compute", "critical": True,
     "table": "stock_prices",      "source": "NSE Archives bhavcopy", "data_freq": "daily", "frequency": "daily",
     "reads": ["stock_prices"],
     "lagged_reads": ["stock_prices@fetch_prices_fallback"]},

    # Plan 0005 Phase C: yfinance fallback for SIDs not in NSE bhavcopy
    # (InvITs, REITs, BSE-only listings, recent IPOs). Tries .NS first then
    # .BO. Empirically 90% hit rate on the 339 missing SIDs as of 2026-05-24.
    {"name": "fetch_prices_fallback", "module": "sources.yfinance_prices", "function": "compute", "critical": False,
     "table": "stock_prices",      "source": "yfinance .BO / .NS (gap-fill)", "data_freq": "daily", "frequency": "daily",
     "reads": ["stock_prices", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos", "stocks@segment_tiers", "stocks@universe_liveness"]},

    # Corporate actions (splits/bonuses/special dividends) over a short trailing
    # window. Feeds Gate 3 temporal-continuity's escape hatch so real ex-date
    # price step-changes (LIC 1:2 split, LEM 11.5×, …) classify as CONTINUOUS
    # instead of generating noise verdicts. Idempotent INSERT OR IGNORE; the
    # monthly `--source corp --months 24` deep backfill is the gap-repair path.
    {"name": "fetch_corp_actions", "module": "sources.nselib_pull", "function": "compute_corp_actions", "critical": False,
     "table": "corporate_actions", "source": "NSE corporate-actions (nselib)", "data_freq": "daily", "frequency": "daily",
     "reads": ["fii_dii_positioning", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos", "stocks@segment_tiers", "stocks@universe_liveness"]},

    # Board-meeting / forthcoming-events calendar (one nselib call, −3d→+30d
    # window). Forward-dated, so a daily run keeps it fresh and feeds the
    # cockpit's "upcoming earnings" widget. Was a one-off v1-CSV import (notebook)
    # with no producer → went stale; wired daily 2026-06-04. Idempotent.
    {"name": "fetch_earnings_calendar", "module": "sources.nselib_pull", "function": "compute_earnings_calendar", "critical": False,
     "table": "earnings_calendar", "source": "NSE event-calendar (nselib)", "data_freq": "daily", "frequency": "daily",
     "reads": ["fii_dii_positioning", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos", "stocks@segment_tiers", "stocks@universe_liveness"]},

    # Track 3.1b — NSE F&O EOD grid. One nselib.fno_bhav_copy call = the whole
    # market (~16K info-carrying rows/day). Runs in the morning pipeline against
    # the prior session's archive, exactly like fetch_bhavcopy. compute() walks a
    # short trailing window so a missed day self-heals. compute_pcr() must run
    # AFTER (it aggregates the rows just written) — keep this ordering.
    {"name": "fetch_fno_bhav",     "module": "sources.fno_pull",     "function": "compute", "critical": False,
     "table": "fno_bhav",          "source": "NSE F&O bhavcopy (nselib UDiFF)", "data_freq": "daily", "frequency": "daily",
     "reads": ["fno_bhav"]},

    {"name": "compute_fno_pcr",    "module": "sources.fno_pull",     "function": "compute_pcr", "critical": False,
     "table": "fno_pcr_history",   "source": "fno_bhav (nearest-expiry rollup)", "data_freq": "daily", "frequency": "daily",
     "reads": ["fno_bhav", "fno_pcr_history"]},

    {"name": "compute_fno_iv",     "module": "sources.fno_iv",       "function": "compute", "critical": False,
     "table": "fno_iv_history",    "source": "fno_bhav (Black-76 IV surface inversion)", "data_freq": "daily", "frequency": "daily",
     "reads": ["fno_bhav", "fno_iv_history"]},

    {"name": "universe_liveness",  "module": "sources.universe",     "function": "compute", "critical": False,
     "table": "stocks",            "source": "stock_prices (recent activity)", "data_freq": "daily", "frequency": "daily",
     "reads": ["stock_prices", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos", "stocks@segment_tiers"]},

    # Plan 0015 D3: LARGE (top 100) / MID (101-250) / SMALL by fresh market cap on the
    # 1st, with ±10% hysteresis (scoring/segment.py). Before this nothing re-tiered:
    # cap_tier was a one-time April 2026 load. MICRO carve-out stays in classify_micro_tier.
    {"name": "segment_tiers", "module": "scoring.segment", "function": "compute", "critical": False,
     "table": "stocks", "source": "stock_prices + fundamentals_screener + annual_balance_sheet + corporate_adjustments",
     "data_freq": "monthly", "frequency": "monthly",
     "reads": ["annual_balance_sheet", "corporate_adjustments", "fundamentals_screener", "stock_prices", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "fetch_news",         "module": "sources.rss",          "function": "compute", "critical": False,
     "table": "news_articles",     "source": "RSS feeds (8 sources)", "data_freq": "daily", "frequency": "daily",
     "reads": ["news_articles"]},

    # Regulatory harvester is daily (cheap incremental, ~5 min).
    {"name": "fetch_regulatory",   "module": "sources.regulatory_harvester", "function": "harvest_incremental", "critical": False,
     "table": "regulatory_events", "source": "Google News last 30d", "data_freq": "daily", "frequency": "daily",
     "reads": ["regulatory_events", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # ── Mutual Fund universe (research-only, plan prfect-lets-add-a-zazzy-eich, 2026-05-26) ──
    # Weekly: refresh scheme master from AMFI NAVAll.txt (~14k schemes, single HTTP).
    {"name": "fetch_mf_master",    "module": "sources.mf_amfi_master",       "function": "compute", "critical": False,
     "table": "mf_scheme_master",  "source": "AMFI NAVAll.txt",       "data_freq": "weekly", "frequency": "weekly",
     "reads": ["mf_scheme_master", "stocks"],
     "lagged_reads": ["mf_scheme_master@classify_mf_quality", "stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    # Weekly: classify data quality — flag wound-up / segregated / interval / bonus / anomalous schemes
    # so they don't pollute the universe browser, scorer, or category stats. Runs AFTER master refresh
    # so new schemes get classified; metric-based ANOMALOUS flags get picked up on the next monthly
    # metrics recompute (the classifier reads from mf_metrics if present).
    {"name": "classify_mf_quality","module": "sources.mf_data_quality",      "function": "compute", "critical": False,
     "table": "mf_scheme_master",  "source": "name patterns + NAV jumps", "data_freq": "weekly", "frequency": "weekly",
     "reads": ["mf_metrics", "mf_nav_history", "mf_scheme_master"],
     "lagged_reads": ["mf_metrics@compute_mf_metrics", "mf_nav_history@fetch_mf_nav_daily"]},
    # Daily: refresh today's NAVs for all schemes from same source (single HTTP, idempotent).
    {"name": "fetch_mf_nav_daily", "module": "sources.mf_nav_daily",         "function": "compute", "critical": False,
     "table": "mf_nav_history",    "source": "AMFI NAVAll.txt",       "data_freq": "daily",  "frequency": "daily",
     "reads": ["mf_nav_history", "mf_scheme_master", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    # Monthly: recompute returns + risk + scorer + rolling-returns + category aggregates.
    {"name": "compute_mf_metrics", "module": "signals.mf_metrics",           "function": "compute", "critical": False,
     "table": "mf_metrics",        "source": "mf_nav_history + Nifty50 benchmark", "data_freq": "monthly", "frequency": "monthly",
     "reads": ["mf_calendar_returns", "mf_category_stats", "mf_metrics", "mf_nav_history", "mf_rolling_returns", "mf_scheme_master", "stock_prices", "stocks"],
     "writes": ["mf_calendar_returns", "mf_category_stats", "mf_metrics", "mf_rolling_returns"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    # Monthly: refresh top-N MF holdings via ETMoney scrape (AMFI's holdings data has 45d lag,
    # monthly refresh is sufficient). Rate-limited at 2.5s/req with 30s pause every 100 reqs.
    {"name": "scrape_mf_holdings", "module": "sources.mf_holdings_scrape",   "function": "compute", "critical": False,
     "table": "mf_holdings",       "source": "ETMoney portfolio-details (public)", "data_freq": "monthly", "frequency": "monthly",
     "reads": ["mf_holdings", "mf_metrics", "mf_scheme_master", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # ── Sector signal history (monthly PIT accumulators, 2026-06) ──
    # Start the clock on at-entry sector signals so they're backtestable in ~12mo.
    # Each upserts a monthly snapshot from an already-accruing source. Cheap,
    # non-blocking; the sector-signal lab validated sector momentum (t+3) — these
    # accrue the orthogonal candidates (analyst revisions, news, policy).
    {"name": "sector_analyst_breadth",  "module": "signals.sector_breadth", "function": "compute_analyst", "critical": False,
     "table": "sector_analyst_breadth_pit",  "source": "analyst_consensus_snapshots (MoM PT revision)", "data_freq": "monthly", "frequency": "monthly",
     "reads": ["analyst_consensus_snapshots", "sector_analyst_breadth_pit", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    {"name": "sector_sentiment_breadth","module": "signals.sector_breadth", "function": "compute_sentiment", "critical": False,
     "table": "sector_sentiment_breadth_pit","source": "sentiment_scores (30d news breadth)", "data_freq": "monthly", "frequency": "monthly",
     "reads": ["sector_sentiment_breadth_pit", "sentiment_scores", "stocks"],
     "lagged_reads": ["sentiment_scores@signal_sentiment", "stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    {"name": "sector_policy",           "module": "signals.sector_policy",  "function": "compute", "critical": False,
     "table": "sector_policy_pit",            "source": "policy_events (curated store)", "data_freq": "monthly", "frequency": "monthly",
     "reads": ["policy_events", "sector_policy_pit"]},

    # NOTE: classify_regulatory, classify_news, news_brief, and fetch_broker_recos
    # all moved to END of pipeline — they were blocking production. See block
    # at the bottom: "Background / non-blocking section".

    # {"name": "fetch_fundamentals", "module": "sources.tickertape", "function": "compute", "critical": False,
    #  "table": "quarterly_income",  "source": "Tickertape API",     "data_freq": "quarterly", "frequency": "monthly"},
    # NOTE: Tickertape fetcher takes ~4 hours for full universe (2,448 × 3 calls × 2s).
    # Run manually: python -m sources.tickertape --limit 10 (test) then full run overnight.
    # Monthly cron entry handles full refresh (run_tickertape_monthly.sh).

    # Tickertape HTML scrape — one page hit per stock, writes both analyst_consensus
    # and forecast_history. Single pipeline entry: PIPELINE_STEPS maps one step to
    # one table, so forecast_history's freshness is tracked via its tables.TABLES
    # entry instead of a second step. A second "fetch_forecast" step here used to
    # call the SAME function again — pipeline.py's runner has no (module, function)
    # dedup (only the watchdog's heal loop does), so it ran compute() twice every
    # month: ~1.9h wasted + doubled Tickertape scrape load (audit Eff-F1).
    {"name": "fetch_analyst",      "module": "sources.tickertape_analyst", "function": "compute", "critical": False,
     "table": "analyst_consensus", "source": "Tickertape __NEXT_DATA__", "data_freq": "monthly", "frequency": "monthly",
     "reads": ["stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Tickertape shareholding pattern — Bharat_sm_data API (different path from analyst scrape).
    {"name": "fetch_shareholding", "module": "sources.tickertape_shareholding", "function": "compute", "critical": False,
     "table": "shareholding",      "source": "Tickertape API",        "data_freq": "quarterly", "frequency": "monthly",
     "reads": ["stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # ── Signals ──
    {"name": "signal_sentiment",   "module": "signals.sentiment",   "function": "compute",  "critical": False,
     "table": "sentiment_scores",  "source": "news_articles",       "data_freq": "daily",   "frequency": "daily",
     "reads": ["news_article_stocks", "news_articles", "sentiment_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "signal_insider",     "module": "signals.insider_signal", "function": "compute", "critical": False,
     "table": "insider_signals",   "source": "insider_trades (NSE PIT)", "data_freq": "daily", "frequency": "daily",
     "reads": ["insider_trades", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "signal_forensic",    "module": "signals.forensic",    "function": "compute",  "critical": False,
     "table": "forensic_scores",   "source": "quarterly_income + annual_balance_sheet + annual_cash_flow",
     "data_freq": "quarterly",     "frequency": "weekly",
     "reads": ["annual_balance_sheet", "annual_cash_flow", "forensic_scores", "quarterly_income", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "signal_piotroski",   "module": "signals.piotroski",   "function": "compute",  "critical": False,
     "table": "piotroski_scores",  "source": "quarterly_income + annual_balance_sheet + annual_cash_flow",
     "data_freq": "quarterly",     "frequency": "weekly",
     "reads": ["annual_balance_sheet", "annual_cash_flow", "daily_picks", "piotroski_scores", "quarterly_income", "stocks"],
     "writes": ["piotroski_scores", "signal_lineage"],
     "lagged_reads": ["daily_picks@screener", "stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # ROIC — first Track 3 factor. Reads fundamentals_screener (sourced
    # weekly via sources.screener_pull — separate cadence, not in daily
    # pipeline). Not yet in scoring weights — needs t-stat validation.
    {"name": "signal_roic",        "module": "signals.roic",        "function": "compute",  "critical": False,
     "table": "roic_scores",       "source": "fundamentals_screener (Screener Premium)",
     "data_freq": "annual",        "frequency": "weekly",
     "reads": ["fundamentals_screener", "roic_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # FCF Yield — second Track 3 factor. Same data source, same gating —
    # not in scoring weights yet.
    {"name": "signal_fcf_yield",   "module": "signals.fcf_yield",   "function": "compute",  "critical": False,
     "table": "fcf_yield_scores",  "source": "fundamentals_screener (Screener Premium) + stocks.market_cap_cr",
     "data_freq": "annual",        "frequency": "weekly",
     "reads": ["fcf_yield_scores", "fundamentals_screener", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Cash Conversion Cycle — third Track 3 factor. DSO + DIO − DPO, 3-yr median.
    # Same gating — not in scoring weights yet.
    {"name": "signal_cash_conversion_cycle", "module": "signals.cash_conversion_cycle", "function": "compute", "critical": False,
     "table": "cash_conversion_cycle_scores", "source": "fundamentals_screener — Sales + Receivables + Inventory + Trade Payables",
     "data_freq": "annual",        "frequency": "weekly",
     "reads": ["cash_conversion_cycle_scores", "fundamentals_screener", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Operating Margin Trend — 5y OLS slope of EBIT/Sales (pp/year). Same gating.
    {"name": "signal_operating_margin_trend", "module": "signals.operating_margin_trend", "function": "compute", "critical": False,
     "table": "operating_margin_trend_scores", "source": "fundamentals_screener — Sales + PBT + Interest",
     "data_freq": "annual",        "frequency": "weekly",
     "reads": ["fundamentals_screener", "operating_margin_trend_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Working Capital Intensity — (Recv + Inv − Pay) / Sales, 3y median. Same gating.
    {"name": "signal_working_capital_intensity", "module": "signals.working_capital_intensity", "function": "compute", "critical": False,
     "table": "working_capital_intensity_scores", "source": "fundamentals_screener — Sales + Receivables + Inventory + Trade Payables",
     "data_freq": "annual",        "frequency": "weekly",
     "reads": ["fundamentals_screener", "stocks", "working_capital_intensity_scores"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Interest Coverage — (PBT + Interest) / Interest, 3y median. Same gating.
    {"name": "signal_interest_coverage", "module": "signals.interest_coverage", "function": "compute", "critical": False,
     "table": "interest_coverage_scores", "source": "fundamentals_screener — PBT + Interest",
     "data_freq": "annual",        "frequency": "weekly",
     "reads": ["fundamentals_screener", "interest_coverage_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # ROIIC — marginal NOPAT/IC over trailing 5y. Sister of ROIC; measures
    # how productive newly-deployed capital has been.
    {"name": "signal_roiic", "module": "signals.roiic", "function": "compute", "critical": False,
     "table": "roiic_scores", "source": "fundamentals_screener — PBT + Tax + Interest + Equity Share Capital + Reserves + Borrowings",
     "data_freq": "annual",        "frequency": "weekly",
     "reads": ["fundamentals_screener", "roiic_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Gross Profitability (Novy-Marx anchor) — multibagger funnel quality anchor.
    {"name": "signal_gross_profitability", "module": "signals.gross_profitability", "function": "compute", "critical": False,
     "table": "gross_profitability_scores", "source": "fundamentals_screener — Sales + Raw Material Cost + Change in Inventory + Power and Fuel + Other Mfr. Exp + Total",
     "data_freq": "annual",        "frequency": "weekly",
     "reads": ["fundamentals_screener", "gross_profitability_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # ── Forensic / capital-allocation batch (plan 0002 §3.2.1) ──
    {"name": "signal_dso_change_yoy", "module": "signals.dso_change_yoy", "function": "compute", "critical": False,
     "table": "dso_change_yoy_scores", "source": "fundamentals_screener — Sales + Receivables",
     "data_freq": "annual", "frequency": "weekly",
     "reads": ["dso_change_yoy_scores", "fundamentals_screener", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    {"name": "signal_dio_change_yoy", "module": "signals.dio_change_yoy", "function": "compute", "critical": False,
     "table": "dio_change_yoy_scores", "source": "fundamentals_screener — Sales + Inventory",
     "data_freq": "annual", "frequency": "weekly",
     "reads": ["dio_change_yoy_scores", "fundamentals_screener", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    {"name": "signal_nwc_to_revenue", "module": "signals.nwc_to_revenue", "function": "compute", "critical": False,
     "table": "nwc_to_revenue_scores", "source": "fundamentals_screener — Sales + Receivables + Inventory + Trade Payables",
     "data_freq": "annual", "frequency": "weekly",
     "reads": ["fundamentals_screener", "nwc_to_revenue_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    {"name": "signal_sloan_accruals_full", "module": "signals.sloan_accruals_full", "function": "compute", "critical": False,
     "table": "sloan_accruals_full_scores", "source": "fundamentals_screener — Receivables + Inventory + Trade Payables + Depreciation + Total",
     "data_freq": "annual", "frequency": "weekly",
     "reads": ["fundamentals_screener", "sloan_accruals_full_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    {"name": "signal_sga_to_revenue_change", "module": "signals.sga_to_revenue_change", "function": "compute", "critical": False,
     "table": "sga_to_revenue_change_scores", "source": "fundamentals_screener — Sales + Selling and admin",
     "data_freq": "annual", "frequency": "weekly",
     "reads": ["fundamentals_screener", "sga_to_revenue_change_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    {"name": "signal_fcf_margin", "module": "signals.fcf_margin", "function": "compute", "critical": False,
     "table": "fcf_margin_scores", "source": "fundamentals_screener — Sales + OCF + Net Block + CWIP + Depreciation",
     "data_freq": "annual", "frequency": "weekly",
     "reads": ["fcf_margin_scores", "fundamentals_screener", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    {"name": "signal_capex_to_dep", "module": "signals.capex_to_dep", "function": "compute", "critical": False,
     "table": "capex_to_dep_scores", "source": "fundamentals_screener — Net Block + CWIP + Depreciation",
     "data_freq": "annual", "frequency": "weekly",
     "reads": ["capex_to_dep_scores", "fundamentals_screener", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    {"name": "signal_goodwill_to_assets", "module": "signals.goodwill_to_assets", "function": "compute", "critical": False,
     "table": "goodwill_to_assets_scores", "source": "fundamentals_screener — Intangible Assets + Total",
     "data_freq": "annual", "frequency": "weekly",
     "reads": ["fundamentals_screener", "goodwill_to_assets_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    {"name": "signal_debt_structure", "module": "signals.debt_structure", "function": "compute", "critical": False,
     "table": "debt_structure_scores", "source": "fundamentals_screener — Long term Borrowings + Borrowings",
     "data_freq": "annual", "frequency": "weekly",
     "reads": ["debt_structure_scores", "fundamentals_screener", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    {"name": "signal_asset_tangibility", "module": "signals.asset_tangibility", "function": "compute", "critical": False,
     "table": "asset_tangibility_scores", "source": "fundamentals_screener — Net Block + Total",
     "data_freq": "annual", "frequency": "weekly",
     "reads": ["asset_tangibility_scores", "fundamentals_screener", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Sector-narrative-derived cluster (plan 0003) — 4 factors inspired by
    # IIM Ahmedabad sector-narrative pages. None in scoring weights yet;
    # promotion gated on backtest |t| ≥ 1.5 in any tier.

    {"name": "signal_revenue_cv",  "module": "signals.revenue_cv",  "function": "compute",  "critical": False,
     "table": "revenue_cv_scores", "source": "fundamentals_screener — Sales (annual, 6 yrs)",
     "data_freq": "annual",        "frequency": "weekly",
     "reads": ["fundamentals_screener", "revenue_cv_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "signal_inventory_turnover", "module": "signals.inventory_turnover", "function": "compute", "critical": False,
     "table": "inventory_turnover_scores", "source": "fundamentals_screener — Sales + Inventory",
     "data_freq": "annual",                "frequency": "weekly",
     "reads": ["fundamentals_screener", "inventory_turnover_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "signal_sales_growth_relative", "module": "signals.sales_growth_relative", "function": "compute", "critical": False,
     "table": "sales_growth_relative_scores", "source": "fundamentals_screener — Sales + sector peers",
     "data_freq": "annual",                   "frequency": "weekly",
     "reads": ["fundamentals_screener", "sales_growth_relative_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "signal_share_momentum", "module": "signals.share_momentum", "function": "compute", "critical": False,
     "table": "share_momentum_scores", "source": "stock_prices + fundamentals_screener — No. of Equity Shares",
     "data_freq": "daily",             "frequency": "daily",
     "reads": ["fundamentals_screener", "share_momentum_scores", "stock_prices", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "signal_accruals",    "module": "signals.accruals",    "function": "compute",  "critical": False,
     "table": "accruals_scores",   "source": "quarterly_income + annual_balance_sheet + annual_cash_flow",
     "data_freq": "quarterly",     "frequency": "weekly",
     "reads": ["accruals_scores", "annual_balance_sheet", "annual_cash_flow", "quarterly_income", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "signal_consensus",   "module": "signals.consensus",   "function": "compute",  "critical": False,
     "table": "consensus_signals", "source": "analyst_consensus + forecast_history + stock_prices",
     "data_freq": "monthly",       "frequency": "daily",
     "reads": ["analyst_consensus", "consensus_signals", "daily_picks", "stock_prices", "stocks"],
     "writes": ["consensus_signals", "signal_lineage"],
     "lagged_reads": ["daily_picks@screener", "stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "signal_promoter",    "module": "signals.promoter",    "function": "compute",  "critical": False,
     "table": "promoter_signals",  "source": "shareholding",        "data_freq": "quarterly", "frequency": "weekly",
     "reads": ["promoter_signals", "shareholding", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "signal_smart_money", "module": "signals.smart_money", "function": "compute",  "critical": False,
     "table": "smart_money_scores","source": "bulk_deals + stock_prices", "data_freq": "daily", "frequency": "daily",
     "reads": ["bulk_deals", "smart_money_scores", "stock_prices", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Multibagger screen (plan 0008) — SEPARATE 3-stage funnel, kept OUT of
    # daily_picks. Runs LAST in the signal block (reads roic/roiic/gross_prof/
    # margin/piotroski/smart_money/promoter/forensic scores just written above
    # + shareholding + annual fundamentals_screener) and picks regime-conditioned
    # pillar weights off the small-cap EMA regime. Weekly (Sunday): a 2–4yr
    # fundamental screen doesn't move day-to-day, and validation (ADR 0039) shows
    # the ranking edge is weak → this is a refreshing watchlist, not a daily signal.
    {"name": "signal_multibagger", "module": "signals.multibagger", "function": "compute", "critical": False,
     "table": "multibagger_scores", "source": "roic/roiic/gross_profitability/piotroski/forensic/promoter/smart_money scores + shareholding + fundamentals_screener + small-cap EMA regime",
     "data_freq": "weekly",         "frequency": "weekly",
     "reads": ["forensic_scores", "fundamentals_screener", "gross_profitability_scores", "multibagger_scores", "nse_index_history", "operating_margin_trend_scores", "piotroski_scores", "promoter_signals", "roic_scores", "roiic_scores", "shareholding", "smart_money_scores", "stocks"],
     "lagged_reads": ["nse_index_history@fetch_nse_indices", "stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "signal_macro",       "module": "signals.macro",       "function": "compute",  "critical": False,
     "table": "macro_sector_signals", "source": "macro_indicators", "data_freq": "monthly", "frequency": "daily",
     "reads": ["macro_indicators", "macro_sector_signals"],
     "lagged_reads": ["macro_sector_signals@signal_regulatory"]},

    {"name": "signal_regulatory", "module": "signals.regulatory",  "function": "compute",  "critical": False,
     "table": "macro_sector_signals", "source": "regulatory_events + regulatory_signals (AI classified)",
     "data_freq": "daily",           "frequency": "daily",
     "reads": ["macro_sector_signals", "regulatory_events", "regulatory_signals"]},

    # ── Scoring ──
    # Plan 0005 Phase A: refresh eligibility BEFORE screener so eligible_coverage
    # uses today's snapshot, not yesterday's.
    {"name": "refresh_eligibility", "module": "tools.refresh_eligibility", "function": "refresh",
     "critical": False,
     "table": "universe_eligibility", "source": "eligibility/registry.py — 8 signals × universe",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["analyst_consensus", "annual_balance_sheet", "annual_cash_flow", "bse_announcements", "bulk_deals", "quarterly_income", "shareholding", "stock_prices", "stocks", "universe_eligibility"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "regime_update",      "module": "scoring.regime",      "function": "compute",  "critical": False,
     "table": "regime_state",      "source": "vix_history",         "data_freq": "daily",   "frequency": "daily",
     "reads": ["vix_history"]},

    # Financial sub-model (Track 2.2b, ADR 0030) — daily snapshot of per-
    # stock score for 158 Banks + NBFCs. Reads latest quarterly + annual
    # from banking_metrics; renormalizes 40% AQ + 30% P + 15% C (NULL
    # until 2.2c) + 15% F over present components. Currently print-only:
    # the screener doesn't route Financials through it yet (Phase 2.2d
    # decision pending t-stat ≥ 2.0 backtest validation).
    {"name": "compute_financial_signal", "module": "signals.financial_signal", "function": "compute", "critical": False,
     "table": "financial_signal_scores", "source": "banking_metrics", "data_freq": "daily", "frequency": "daily",
     "reads": ["banking_metrics", "financial_signal_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "screener",           "module": "scoring.screener",    "function": "compute",  "critical": True,
     "table": "daily_picks",       "source": "all signals",         "data_freq": "daily",   "frequency": "daily",
     "reads": ["analyst_consensus", "annual_balance_sheet", "annual_cash_flow", "bse_announcements", "bulk_deals", "consensus_signals", "corporate_adjustments", "daily_picks", "fno_iv_history", "forecast_history", "forensic_scores", "health_score", "macro_history", "macro_sector_signals_pit", "piotroski_scores", "quarterly_income", "shareholding", "signal_lineage", "stock_prices", "stocks", "trust_verdicts", "universe_eligibility"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Track 3.3c — HRP position sizing. Turns the within-tier ranked daily_picks
    # into a sized book (portfolio_weights). Runs right AFTER the screener (needs
    # today's picks) and after price ingest (covariance + ADTV from stock_prices).
    # NON-critical: ADVISORY only (no capital until rank-skill validates), and a
    # thin-day build failure must never block dossier/email. See ADR 0044.
    {"name": "portfolio_construction", "module": "portfolio_construction", "function": "run", "critical": False,
     "table": "portfolio_weights", "source": "daily_picks + stock_prices (HRP sizing)",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["daily_picks", "portfolio_weights", "stock_prices", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Benchmark + smart-beta index history (NIFTY 50 / Midcap 150 / Smallcap
    # 250 …). Was manual-only → went 32d stale (2026-06-01) → pick_outcomes
    # excess returns silently NULL'd, and nse_index_history wasn't even
    # freshness-tracked (not a pipeline-output table). Now a daily step:
    # short rolling window, idempotent INSERT OR IGNORE. Must run BEFORE
    # compute_pick_outcomes so the benchmark is current when excess is computed.
    {"name": "fetch_nse_indices",  "module": "sources.nselib_pull", "function": "compute_nse_indices", "critical": False,
     "table": "nse_index_history", "source": "NSE index history (nselib)",
     "data_freq": "daily",         "frequency": "daily",
     "reads": []},

    # Live equity curve — realized forward returns on every daily_picks row.
    # Runs after screener (today's picks land first) but needs ≥20 trading days
    # of forward data to write a row, so it's writing prior mature rows daily.
    # Idempotent upsert by (sid, pick_date, window_days).
    {"name": "compute_pick_outcomes", "module": "tools.compute_pick_outcomes", "function": "compute", "critical": False,
     "table": "pick_outcomes",     "source": "daily_picks + stock_prices + nse_index_history",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["daily_picks", "nse_index_history", "pick_outcomes", "stock_prices"]},

    # Track 3.3c — HRP book realized-return head-to-head (HRP vs equal-weight vs
    # NIFTY) per asof_date × window. Runs AFTER compute_pick_outcomes (reuses its
    # price logic; both need today's prices). Non-critical, ADVISORY: the §3.3c
    # gate evidence accumulates here. Idempotent upsert by (asof_date, window_days).
    {"name": "portfolio_outcomes", "module": "tools.portfolio_outcomes", "function": "compute", "critical": False,
     "table": "portfolio_outcomes", "source": "portfolio_weights + stock_prices + nse_index_history",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["nse_index_history", "portfolio_outcomes", "portfolio_weights", "stock_prices"]},

    # Plan 0007 Phase 1 — daily Unified Health Score (UHS) writer. Computes
    # factor + table + system UHS for today's snapshot. include_picks=True so
    # the daily_picks UHS rollup is also persisted alongside factors. Reads from
    # universe_eligibility (eligibility/registry), data_health (db.py), and
    # FACTOR_LINEAGE (lineage.py). Non-critical (UHS is observation, not gate).
    {"name": "compute_health_score", "module": "scoring.health_score", "function": "compute", "critical": False,
     "table": "health_score",      "source": "universe_eligibility + data_health + FACTOR_LINEAGE",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["analyst_consensus", "annual_balance_sheet", "annual_cash_flow", "bse_announcements", "consensus_signals", "daily_picks", "daily_snapshots", "fno_iv_history", "health_score", "piotroski_scores", "quarterly_income", "stock_prices", "stocks", "trust_verdicts", "universe_eligibility"],
     "lagged_writes": ["health_score"],
     "lagged_reads": ["daily_snapshots@snapshot", "stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Plan 0007 Phase 6 — External Anchor (Gate 7). Promotes yesterday's NSE
    # bhavcopy rows to external_anchors then audits non-NSE sources (yfinance)
    # for drift. Writes gate_7_anchor verdicts feeding UHS Consistency dim.
    # Non-critical: anchor data is the foundation of the closed-loop fix,
    # but a failure to audit doesn't compromise the primary pick pipeline.
    {"name": "anchor_audit", "module": "tools.anchor_audit", "function": "compute", "critical": False,
     "table": "external_anchors",  "source": "stock_prices (bhavcopy + yfinance)",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["stock_prices"]},

    # Plan 0007 Phase 8 — UHS calibration log. Joins every pick_outcomes row
    # to its daily_picks.uhs_score so that once 6+ months of forward returns
    # accumulate (~late Nov 2026) the uniform 20/20/20/20/20 dim weighting can
    # be regression-validated against realised return. Until then: observation
    # only. Non-critical.
    {"name": "update_uhs_calibration", "module": "scoring.confidence", "function": "update_calibration_log",
     "critical": False, "table": "uhs_calibration_log",
     "source": "pick_outcomes + daily_picks.uhs_score",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["daily_picks", "pick_outcomes"]},

    # Sector briefs — plan 0006 Phase A. One sector_briefs row per sector per
    # date with macro + model + regulatory rollup and a bucket classifier
    # (BOOMING / LIKELY / HEADWIND / QUIET). Drives the /sectors digest UX
    # in Phase C. Non-critical: a failure here doesn't block dossiers or
    # email. Idempotent (INSERT OR REPLACE on sector + date).
    {"name": "compute_sector_briefs", "module": "signals.sector_briefs", "function": "compute", "critical": False,
     "table": "sector_briefs",     "source": "macro_sector_signals + daily_picks + regulatory_signals",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["daily_picks", "macro_sector_signals", "regulatory_events", "regulatory_signals", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Sector momentum — plan 0006 Phase E. Per-sector S/M/L relative strength vs
    # NIFTY 50 (constituent cap-weighted), classified strong/neutral/weak by
    # tercile. UPDATEs sector_briefs.horizon_* in place, so it runs AFTER
    # compute_sector_briefs. Powers the horizon badges on the /sectors digest.
    {"name": "compute_sector_momentum", "module": "signals.sector_momentum", "function": "compute", "critical": False,
     "table": "sector_briefs",     "source": "stock_prices + stocks + macro_history (nifty50)",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["macro_history", "sector_briefs", "stock_prices", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Sector force breakdown — plan 0006 Phase B. Sits on top of sector_briefs.
    # Per (sector, date) emits up to 4 rows, one per force {macro, regulation,
    # tech, market}. Market is reserved for v2 (no sector-level FII/DII data).
    # Powers the "BY FORCE" 2×2 grid in the Phase C /sectors digest UX.
    {"name": "compute_sector_forces", "module": "signals.sector_forces", "function": "compute", "critical": False,
     "table": "sector_force_breakdown", "source": "sector_briefs + regulatory_signals + sector_metadata",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["regulatory_events", "regulatory_signals", "sector_briefs", "sector_metadata", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Sector dossiers — plan 0006 Phase D. LLM-narrated per-sector thesis on top
    # of briefs + forces + sector_metadata. ~11 Claude calls/night (~₹3-5).
    # Non-critical: a failure must not block the stock dossier or email. Same
    # no-raw-numbers hygiene contract as output.dossier; invalid → valid=0.
    {"name": "compute_sector_dossiers", "module": "output.sector_dossier", "function": "compute", "critical": False,
     "table": "sector_dossiers",   "source": "sector_briefs + sector_force_breakdown + sector_metadata (Claude API)",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["daily_picks", "daily_snapshots", "sector_briefs", "sector_force_breakdown", "sector_metadata", "stock_prices", "stocks"],
     "lagged_reads": ["daily_snapshots@snapshot", "stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # ── Output ──
    {"name": "snapshot",           "module": "output.snapshot",     "function": "compute",  "critical": False,
     "table": "daily_snapshots",   "source": "all signals + stock_prices",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["accruals_scores", "annual_balance_sheet", "consensus_signals", "daily_picks", "daily_snapshots", "piotroski_scores", "promoter_signals", "quarterly_income", "sentiment_scores", "smart_money_scores", "stock_prices", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "diff_engine",        "module": "output.diff_engine",  "function": "compute",  "critical": False,
     "table": "daily_changes",     "source": "daily_picks + daily_snapshots (diff)",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["daily_changes", "daily_picks", "daily_snapshots", "stocks", "vix_history"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "dossier",            "module": "output.dossier",      "function": "compute",  "critical": False,
     "table": None,                "source": "daily_picks + all signals (Claude API)",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["accruals_scores", "consensus_signals", "daily_picks", "daily_snapshots", "forensic_scores", "piotroski_scores", "promoter_signals", "sentiment_scores", "smart_money_scores", "stock_prices", "stocks"],
     "writes": ["file:dossiers"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "email",              "module": "output.email_sender", "function": "compute",  "critical": False,
     "table": None,                "source": "daily_picks + dossiers (Gmail SMTP)",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["daily_changes", "daily_picks", "daily_snapshots", "file:dossiers", "regime_state", "stock_prices", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # PIT replay freeze — captures today's pipeline inputs+outputs as a
    # frozen anchor. Daily cadence means every day becomes a regression-test
    # case going forward. Non-critical: a freeze failure shouldn't gate email.
    # See [tools/pit_replay.py] and Plan 0005 Phase E.
    {"name": "pit_replay_freeze",  "module": "tools.pit_replay",    "function": "freeze",   "critical": False,
     "table": "pit_replay_snapshots", "source": "scoring.screener._load_signals + score_universe (frozen)",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["daily_picks"]},

    # Plan 0015 Phase 0: the PIT panel (daily_snapshots_pit) was hand-rebuilt only
    # and froze at 2026-07-01 while the monthly backtest cron re-scored it. Weekly,
    # after the email: re-run recent monthly + Friday anchors (fwd returns mature)
    # and catch up missed ones. ~13 dates × ~40s.
    {"name": "refresh_pit_panel",  "module": "tools.reconstruct_pit", "function": "refresh", "critical": False,
     "table": "daily_snapshots_pit", "source": "all PIT producers over recent anchors",
     "data_freq": "weekly",        "frequency": "weekly",
     "reads": ["accruals_scores", "analyst_consensus_snapshots", "annual_balance_sheet", "annual_cash_flow", "banking_metrics", "bse_announcements", "bulk_deals", "consensus_signals", "corporate_actions", "corporate_adjustments", "daily_picks", "daily_snapshots", "daily_snapshots_pit", "fno_iv_history", "fno_pcr_history", "forecast_history", "forensic_scores", "fundamentals_screener", "insider_trades", "macro_history", "macro_sector_map", "macro_sector_signals_pit", "news_article_stocks", "news_articles", "nlp_scores", "piotroski_scores", "pit_reconstruction_log", "promoter_signals", "quarterly_income", "regulatory_events", "regulatory_signals", "sector_briefs", "shareholding", "short_selling_data", "smart_money_scores", "stock_prices", "stocks", "universe_eligibility"],
     "writes": ["daily_snapshots_pit", "macro_sector_signals_pit", "pit_reconstruction_log"],
     "lagged_writes": ["macro_sector_signals_pit"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # MICRO tier reclassifier — keeps the SMALL/MICRO boundary fresh as ADTV,
    # quality scores, and fundamental depth change. Idempotent. Demotes any
    # MICRO that re-qualifies for SMALL. See tools/classify_micro_tier.py.
    {"name": "classify_micro_tier","module": "tools.classify_micro_tier", "function": "reclassify", "critical": False,
     "table": "stocks",            "source": "stocks + stock_prices + piotroski_scores + quarterly_income",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["piotroski_scores", "quarterly_income", "stock_prices", "stocks"],
     "lagged_reads": ["stocks@fetch_broker_recos"]},

    # ── Background / non-blocking section ──
    # Heavy enrichment + scrapes that don't gate today's picks. Moved AFTER
    # email so a slow run never blocks production. 2026-05-25 incident:
    # classify_regulatory was second-from-top and ran 1.5+hr daily, blocking
    # fetch_broker_recos + signals + screener + dossier + email entirely.
    # Each runs with its own internal cap so the daily cron has bounded
    # runtime even when there's a large backlog.

    # News Phase 2 enrichment — Claude Haiku (~$0.001/article, ~$1/day).
    {"name": "classify_news",       "module": "sources.news_classifier", "function": "compute", "critical": False,
     "table": "news_enriched",     "source": "news_articles (Claude Haiku enrich)", "data_freq": "daily", "frequency": "daily",
     "reads": ["news_articles", "news_enriched"]},

    # Daily news brief — Claude Sonnet (~$0.05/day). After classify_news.
    {"name": "news_brief",          "module": "sources.news_brief",   "function": "compute", "critical": False,
     "table": "news_briefs",       "source": "news_enriched (Claude Sonnet synthesis)", "data_freq": "daily", "frequency": "daily",
     "reads": ["news_articles", "news_enriched"]},

    # Regulatory classifier — async two-phase via the Anthropic Message Batches
    # API (audit Eff-F2, migrated 2026-07-05). Each run INGESTs any completed
    # batch (writing verdicts/signals exactly as the old sync path did) then
    # SUBMITs the day's pending events (post title-hash dedup, capped at
    # DAILY_CLASSIFIER_CAP=500/run) as a new Haiku batch; Haiku passers are
    # submitted as a Sonnet batch on ingest. This took ~54% of the pipeline
    # wall-clock (~3,467s of the old per-item loop) off the critical path — the
    # step now just polls + submits (seconds) — at 50% token cost (batch pricing).
    # ~1-2 day classification latency is fine: output feeds narrative only. The
    # sync per-item path is kept as a fallback (`--sync`, or auto on batch error).
    {"name": "classify_regulatory","module": "sources.regulatory_classifier", "function": "compute", "critical": False,
     "table": "regulatory_signals","source": "regulatory_events (Message Batches, capped 500/run)", "data_freq": "daily", "frequency": "daily",
     "reads": ["news_articles", "regulatory_batches", "regulatory_events", "regulatory_signals", "stocks"],
     "writes": ["regulatory_batches", "regulatory_events", "regulatory_signals"],
     "lagged_writes": ["regulatory_events", "regulatory_signals"],
     "lagged_reads": ["stocks@fetch_broker_recos"]},

    # Yahoo Finance analyst consensus aggregate. Replaces the Tickertape PT field
    # (which was contaminated with lastPrice — see HANDOFF 2026-05-22). Refreshes
    # the live `analyst_consensus` row per stock. The monthly snapshot to
    # `analyst_consensus_snapshots` runs from its own cron entry (1st business
    # day of month) — keeping daily history would be phantom precision since
    # PTs are episodic. Background section: the weekly run is ~1.5h at the
    # 2s floor and must not delay screener/email (2026-09-27); signal_consensus
    # picks up the refreshed rows on the next run.
    {"name": "fetch_yf_analyst",   "module": "sources.yfinance_analyst",   "function": "compute", "critical": False,
     "table": "analyst_consensus", "source": "Yahoo Finance (yfinance)",  "data_freq": "monthly", "frequency": "weekly",
     "reads": ["analyst_consensus", "broker_recommendations", "stock_prices", "stocks"],
     "lagged_writes": ["analyst_consensus"],
     "lagged_reads": ["broker_recommendations@fetch_broker_recos", "stocks@fetch_broker_recos"]},

    # Moneycontrol broker recos — DAILY with a 90-min stalest-first budget
    # (stocks.mc_checked_at); DELAY=12s → ~300 stocks/day, full cycle ~8-9 days.
    # The old weekly full sweep ran ~18h and held the harvest lock all Sunday.
    # Discovery one-time: --discover-only (mc_slug already populated).
    {"name": "fetch_broker_recos", "module": "sources.moneycontrol_recos", "function": "compute", "critical": False,
     "table": "broker_recommendations", "source": "Moneycontrol HTML (12s/req)",   "data_freq": "weekly", "frequency": "daily",
     "reads": ["broker_recommendations", "stocks"],
     "writes": ["broker_recommendations", "stocks"]},

    # Banking metrics — Screener.in HTML scrape, 158 Banks + NBFCs (ADR 0030,
    # Phase 2.2a-ii). Underlying data is quarterly so MONTHLY cron suffices.
    # ~3 s/stock × 158 = ~8 min. Function signature differs from pipeline's
    # standard `compute()` — banking_metrics.main() takes argparse args; the
    # runner needs `--universe`. Wrapped via `compute()` helper.
    {"name": "fetch_banking_metrics", "module": "sources.banking_metrics", "function": "compute_universe", "critical": False,
     "table": "banking_metrics",    "source": "Screener.in stock pages (158 banks+NBFCs)", "data_freq": "quarterly", "frequency": "monthly",
     "reads": ["broker_recommendations", "fundamentals_screener", "stocks"],
     "lagged_writes": ["banking_metrics"]},
]

# Tables fed by standalone crons / migrations (not a PIPELINE_STEPS `table`)
# carry their freshness cadence in tables.TABLES (`freq`) — the old
# RAW_TABLES list lives there now (tables.RAW_TABLES is derived from it).


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
    {
        # Columnar SQLite→DuckDB replica (db.py read_sql_fast). Rebuilt at the tail
        # of run_pipeline.sh's daily cron (non-fatal — a failed rebuild just leaves
        # the previous file in place and logs a warning, invisible to health checks
        # until now). No PIPELINE_STEPS entry, so the watchdog can't auto-heal it —
        # this registration only makes a stale/failed rebuild visible (audit Data-F10).
        "virtual_table": "_file_duckdb_replica",
        "glob":          "data/alpha_signal.duckdb",
        "freshness_field": None,       # binary file — mtime-anchored, not JSON-parsed
        "source":        "tools/duckdb_refresh.py (run_pipeline.sh cron tail, non-fatal)",
        "data_freq":     "daily",
        "frequency":     "daily",
        "producer":      "tools.duckdb_refresh",
    },
]
