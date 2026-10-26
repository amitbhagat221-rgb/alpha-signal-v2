"""
Alpha Signal v2 — Configuration

Every tunable value lives here. No magic numbers in source/signal/scoring code.
Import what you need:
    from config import TIERS, PIPELINE_STEPS, DB_PATH
(External hosts — rate limits, headers, LLM model ids — live in hosts.py; factor
weights live on each factor in factors.py.)
"""

import os
from pathlib import Path

# ── Paths ──

PROJECT_ROOT = Path(__file__).resolve().parent
# ALPHA_DB points every reader/writer at another DB file (a copy for tests, gates and
# migrations — plan 0017 stage 0). Unset = the live DB.
DB_PATH = Path(os.environ.get("ALPHA_DB") or PROJECT_ROOT / "data" / "alpha_signal.db")
SCHEMA_PATH = PROJECT_ROOT / "schema.sql"
# Parquet archives (Kite minute bars, ADR 0072) live beside the DB, so ALPHA_DB in a worktree
# moves them too and a worktree never grows a second, empty archive of its own.
INTRADAY_DIR = Path(os.environ.get("ALPHA_INTRADAY") or DB_PATH.parent / "intraday")
LOG_PATH = PROJECT_ROOT / "output" / "pipeline.log"

# ── LLM work (plan 0016, ADR 0056) ──
# executor "queue": the LLM steps (alpha_mcp/steps.py) queue their items in llm_tasks and run the
# local worker (ops/llm_worker_local.sh — claude -p on the Claude subscription) on them, waiting at
# most deadline_min per step (the dossier deadline is how long the email waits, D4). "api": the old
# Anthropic API paths (paid credits, empty since 2026-08-24) — kept as a fallback (D3).
LLM_WORK = {
    "executor": "queue",
    "deadline_min": {"dossier": 20, "compute_sector_dossiers": 20, "news_brief": 10,
                     "classify_news": 30, "classify_regulatory": 45, "news_desk": 20},
}

# The news editor (plan 0021). The page's map of the world: (id, title, what belongs under it).
# Change the list here; a theme removed is retired, its note and history stay.
NEWS_THEMES = [
    ("rates_dollar", "Interest rates, the dollar and the rupee",
     "Central bank decisions in India and abroad, inflation, bond yields, the rupee, foreign money moving in or out"),
    ("oil_energy", "Oil, energy and the Middle East",
     "Crude oil and gas prices, producer decisions, Middle East conflict and shipping, India's fuel and import bill"),
    ("us_china_trade", "US-China rivalry, tariffs and supply chains",
     "Tariffs and sanctions, trade deals, export controls, wars and alliances that move trade, factories shifting between countries"),
    ("ai_chips", "AI and the chip build-out",
     "Artificial intelligence, data centres, semiconductors, what AI does to software and IT services, technology regulation"),
    ("india_policy", "India policy, capex and reforms",
     "Government spending and budgets, taxes, regulation and reforms, infrastructure, defence and manufacturing incentives"),
    ("energy_transition", "Energy transition and critical minerals",
     "Solar, wind, nuclear, batteries and electric vehicles, power demand and the grid, lithium, copper and rare earths"),
    ("consumer_credit", "Consumer and credit health in India",
     "Household spending and demand, loans and defaults, bank and lender health, jobs and wages, rural and urban demand"),
]
NEWS_EDITOR = {
    "today_days": 2,             # the daily edition reads unread headlines this many days back
    "today_max_headlines": 400,  # per daily task
    "today_max_chars": 38000,    # headline text one task carries: the worker cannot read a tool result above ~50 KB
    "theme_refresh_days": 7,     # a theme note is rewritten at most this often
    "theme_min_headlines": 3,    # a theme gets its first note once this many headlines are filed
    "theme_max_headlines": 60,   # newest headlines a note rewrite reads
    "week_refresh_days": 7,
    "week_max_headlines": 250,   # unfiled headlines the weekly edition reads
    "max_sentence_words": 20,    # average sentence length the validator accepts
}

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

# ── The pick gate (scoring/screener._pick_eligible; thresholds + rationale: ADR 0021) ──
# A ranked stock is published only if enough of its ELIGIBLE factor weight produced a
# value, enough of the tier's total weight did (backstop), it has ~3 months of prices
# and 4 of 8 quarters of fundamentals. `complete_from`: at or above this share of
# eligible weight the pick's data is described as complete (views.pick_data).
# What a wired factor with no value for a stock contributes to its score: the middle of the
# tier. Not dropped and re-spread over the other factors (ADR 0064).
MISSING_FACTOR_SCORE = 0.5

PICK_GATE = {"min_eligible_coverage": 0.60, "min_weight_coverage": 0.50,
             "min_price_rows": 60, "min_fundamental_coverage": 0.50, "complete_from": 0.99}

# ── Signal weights ──
# Hand-set, never derived (CLAUDE.md "Backtest hygiene", docs/reference/signal-weights.md)
# — but they live ON the factor: each wired factors.FACTORS entry carries
# `weights: {tier: w}` (ADR 0052 D4, amends ADR 0017). factors.SIGNAL_WEIGHTS is the
# derived {tier: {weight_key: w}} view every consumer imports.


# ── VIX Regime ──
# India-VIX band → allocation across the PICKABLE tiers (keyed by tier name; each
# regime's alloc sums to 1). scoring/regime.py reads REGIMES.
REGIMES = {
    "CALM":    {"vix": (0.0, 13.0),   "alloc": {"LARGE": 0.30, "MID": 0.35, "SMALL": 0.35}},
    "NORMAL":  {"vix": (13.0, 25.0),  "alloc": {"LARGE": 0.40, "MID": 0.30, "SMALL": 0.30}},
    "CAUTION": {"vix": (25.0, 35.0),  "alloc": {"LARGE": 0.55, "MID": 0.25, "SMALL": 0.20}},
    "CRISIS":  {"vix": (35.0, 999.0), "alloc": {"LARGE": 0.70, "MID": 0.20, "SMALL": 0.10}},
}
# Days in new regime before switching (hysteresis)
VIX_HYSTERESIS_DAYS = 3

# ── Forensic Thresholds ──

FORENSIC = {
    "beneish_grey": -2.22,     # above → possible manipulator
    "beneish_red": -1.78,      # above → likely manipulator
    "altman_distress": 1.10,   # below → distress zone
    "altman_grey": 2.60,       # below → grey zone
    # Flags still computed and shown (forensic_scores, cockpit) as REVIEW prompts, but no longer cut
    # the score: on 2019-26 history no MID/SMALL Beneish or Altman flag underperformed clean stocks
    # at 6 months (plan 0025 task 2.3, tools/lh_forensic.py; ADR 0073), and the cut sank fast growers
    # (NETWEB). True restores the −0.10/−0.20 cut.
    "score_penalty": False,
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

# Option paper book (plan 0022): the ops cockpit's one-tap Kite login (HTTPS, nginx → :3001).
# Register OPS_HTTPS + "/kite/callback" as the Kite Connect app's redirect URL.
OPS_HTTPS = "https://alpha.rendezvous-app.duckdns.org"
KITE_LOGIN_PAGE = OPS_HTTPS + "/kite/login"

# Option premium, live on Kite (plan 0029; options_live.py). These are the DEFAULTS: a row in
# option_live_settings (written from the ops cockpit /options or `python -m options_live set`)
# overrides a key without a deploy. Times are IST. Real orders only in mode approve / auto.
OPTIONS_LIVE = {
    "mode": "shadow",                      # off | shadow | approve | auto
    "lots_cap": {"NIFTY": 1, "SENSEX": 1},
    "lots_hard_max": 40,                   # no setting can raise a cap above this
    "margin_buffer_rs": 50_000,            # kept free after sizing (expiry-day add-on, MTM)
    "weekly_loss_limit_rs": 200_000,       # D4: realised loss this week (Mon-Sun) above it pauses entries
    "kill": False,                         # Stop: no new entries (buy-backs and Close-all still run)
    "adopt_manual_nifty": False,           # True: the Tuesday buy-back also closes Amit's own NIFTY legs of that expiry
    "tag": "as0029",                       # Kite order tag on every order this job places (≤ 20 chars)
    "chain_band": 0.08,                    # live chain fetched within ±8% of spot
    "entry_earliest": "15:00",             # an entry never starts before this...
    "entry_cutoff": "15:29",               # ...stops re-pricing here and cancels what is left
    "approve_by": "15:25",                 # approve mode: a ticket not approved by now expires unplaced
    "buyback_start": "15:05",
    "buyback_final": "15:14",              # the buy-back's final aggressive limit
    "buyback_end": "15:15",                # leftovers cancelled; NIFTY then expires normally, SENSEX skipped
    "closeall_minutes": 5,                 # Close-all: re-price this long, the last minute aggressive
    "reprice_every_s": 20,
    "approval_poll_s": 10,
    "min_sell_frac": 0.5,                  # a SELL is never re-priced below this share of its first mid
    "max_buy_mult": 3.0,                   # a BUY is never re-priced above this multiple of its first ask...
    "final_buy_pct": 0.25,                 # ...except the final limit: ask × (1 + pct) + ticks
    "final_buy_ticks": 4,
    "margin_freed_frac": 0.5,              # rotation gate: margin freed ≥ this share of the NIFTY entry margin
    "freeze_qty": {"NIFTY": 1800, "SENSEX": 1000},   # units per order; fallback when the instruments carry none
    "shadow_min_lots": 1,                  # shadow records at least this many lots even when margin is short
    # VIX guard (Amit 2026-10-25), India VIX at entry: insurance, not a tested rule (option-risk-filters study)
    "vix_halt": 30.0,                      # VIX ≥ this: no entry
    "vix_halve": 27.0,                     # VIX above this (and below vix_halt): half the lots (at least 1)
    "vix_max_age_days": 3,                 # no live quote: the stored close may be this old, else no entry
}

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

# ── Multibagger thesis (plan 0026, ADR 0075): the pond's safety gates, one place for live and backtest ──
MB_THESIS = {
    "mcap_max_cr": 5_000,          # live: the one market cap, no deflation; the backtest deflates it per anchor
    "adtv_min_cr": 0.5,            # ADTV = 126-session median of close x volume, Rs crore
    "adtv_window": 126,
    "adtv_rank_min": 250,          # ADTV rank must be BELOW the 250 most liquid (LARGE / MID stand-in)
    "pledge_max_pct": 50.0,        # live only (no pledge history); NaN passes
    "annual_lag_days": 150,        # an annual statement is knowable at period_end + 150 days
    "red_flag_days": 365,
    # The red-flag gate (signals.multibagger.red_flag_events, live; tools.mb_thesis.red_flags, backtest): kind ->
    # signals.announcements.kind_sql spec on BSE's taxonomy — BSE history and NSE live rows mapped through
    # NSE_BSE_EQUIVALENT (ADR 0082). A clause = {column: [SQL LIKE, % = wildcard, case-blind]}; any clause matches,
    # `exclude` (on the one-line title) vetoes. NSE's own watch `category` is NOT used: its insolvency text rule
    # catches "acquisition through CIRP", and "Change in Auditors" is mostly a rotation (not a flag).
    "red_flags": {
        "auditor_resignation": {"match": [{"subcategory": ["Resignation of Statutory Auditors"]}]},
        "cirp": {"match": [{"subcategory": ["%CIRP%"]}]},
        # Amit 2026-10-19 "add fraud/default as red flags". BSE files a Reg 30 fraud under 'General' (no
        # subcategory of its own); NSE under "Frauds/Default by employees" / "Fraud/Default/Arrest" (-> General).
        # Excluded: the company as a victim of impersonation / cyber fraud, a bank reporting a borrower's fraud,
        # clarifications of news, "account not classified as fraud", insurance recoveries.
        "fraud": {"match": [{"subcategory": ["General"], "title": ["%fraud%", "%arrest of%", "%arrested%"]}],
                  "exclude": ["%clarif%", "%news item%", "%news article%", "%media report%", "%not classified%",
                              "%no fraud%", "%cyber%", "%phishing%", "%fishing%", "%in the name of%", "%caution%",
                              "%alert%", "%fake%", "%imperson%", "%scam%", "%misuse%", "%borrowal fraud%",
                              "%fraud of bank%", "%to rbi%", "%to the rbi%", "%declaration of fraud to%",
                              "%insurance claim%", "%inadvertent%", "%preventive%", "%no connection%",
                              "%fraud control%", "%fraud management%", "%anti-fraud%", "%cardiac%"]},
        # A loan / debt default: BSE's event disclosures (filed when a default passes 30 days), and the same
        # disclosure filed under 'General' on either exchange. Excluded: the QUARTERLY C2 statement (filed every
        # quarter, often nil), cures ("made good", regularised), "no default" / repayment-on-time intimations.
        "default": {"match": [{"subcategory": ["Disclosures by listed entities of defaults on payment%"]},
                              {"subcategory": ["General"],
                               "title": ["%default in payment%", "%default in the payment of principal%",
                                         "%default in the payment of interest%", "%default in repayment%",
                                         "%default on payment%", "%defaults on payment%", "%defaults in payment%",
                                         "%defaults of payment%", "%default in servicing%", "%intimation of default%",
                                         "%disclosure of default%", "%about default%"]}],
                    "exclude": ["%quarterly disclosure%", "%quarter ended%", "%for the quarter%", "%for quarter%",
                                "%clarif%", "%no default%", "%not default%", "%not in default%",
                                "%nil default%", "% nil %", "%(nil)%", "%made good%", "%regularis%", "%regulariz%",
                                "%cured%", "%intimation of repayment%", "%timely payment%", "%timely repayment%",
                                "%payment made%"]},
    },
    # the same filing on both exchanges (an NSE event within signals.announcements.DEDUPE_DAYS of BSE's) is one event
    "top_n": 100,                  # stage 2: the top 100 by thesis_rank
    # Research overlay (plan 0026 4b, Amit 2026-10-16: "bake in the qualitative finding into rankings"): the thesis
    # score minus points per red flag (integrity areas weigh double) plus points for the 5x case; a reject is out.
    # Judgement, not backtested: checked forward by the research30 comparison at 24 months (research 0011).
    "research_overlay": {
        "integrity_areas": ("governance", "related_party", "audit", "accounting", "promoter", "legal_regulatory",
                            "disclosure", "pledge", "dilution"),
        # per flag; sized so the cap rarely binds (non-reject raw penalty 2026-10-16: median 0.07, max 0.14) and one
        # plausible 5x case (+0.04) offsets about 2.5 medium integrity flags. Thesis scores in the top 100 span ~0.2.
        "flag_points": {"medium": {"integrity": 0.015, "business": 0.008}, "low": {"integrity": 0.005, "business": 0.003}},
        "max_penalty": 0.15,
        "case_points": {"strong": 0.08, "plausible": 0.04, "weak": 0.0},
        "top_n": 30,
    },
    # Input-integrity checks in the live run (plan 0026 4b; the deep research found 7 of the 2026-10-15 top 100 on
    # broken inputs, incl. #1 and #2): signals/multibagger.data_checks
    "data_checks": {
        # the share-count check lives in the shared market cap: signals._fundamentals.FILED_SHARES_TOL (plan 0027)
        "demerger_days": 450,          # a demerger this recent: annual before it -> gate out; else blank the quarter part
        "revenue_tol": 1.25,           # latest quarter's results-table revenue vs Screener sales -> blank the quarter part
    },
    "max_book": 30,                # candidates + held (stage 3), output/mb_book.py
    "max_held": 10,                # stage 5
    # Capacity (research 0008 problem 3): a position may be at most this share of a name's 20-session median
    # traded value; book_inr is the desk's assumed money (CEO decision D3), split over max_book / max_held names.
    "max_adv_share": 0.05,
    "adv_window": 20,
    "book_inr": 3_000_000,         # Rs 30 lakh
    # Forward paper books (tools/mb_paper.py, research 0008 section 6): pond, top30 and amit10 from day one.
    "paper_top_n": 30,
    "kill": {
        "months_to_judge": 24,     # the score and human kills wait this long
        "score_pts": -5.0,         # top30 minus pond, cumulative return points
        "human_pts": -10.0,        # amit10 minus top30
        "hit_up": 0.50,            # a name counts as a hit when up at least this much
        "risk_excess": -0.35,      # rolling 12-month top30 return minus the benchmark's -> halt new buying
        "d6_pts": 3.0,               # D6: five-part top 30 vs price-only 30 after 24 months; within ±3 price-only wins
        "risk_crash_pond_up": 0.50,  # ... unless the pond rose more than this in that window (momentum crash, research 0008 round 2)
        "capacity_share": 0.10,    # any held / top30 name above this share of its 20-day ADTV -> stop adding
        "warn_fraction": 0.5,      # warn at this fraction of a threshold
    },
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

# Steps and run.sh jobs whose failure never pages (health severity is capped at WARN,
# however many days it has failed): {step_name: why, in plain words}. Declared here, next to the
# steps, so no check hard-codes a name. A step on this list must not feed the morning picks.
NON_PAGING_STEPS = {
    "datamodel_sync": "plan 0017 v3 shadow job (run.sh morning, after the email): mirrors the legacy tables into the v3 tables; no pick reads them yet",
    "datamodel_reconcile": "plan 0017 v3 shadow job (run.sh morning, after the email): old-vs-new parity record; no pick reads it",
    "fetch_prices_fallback": "gap-fill for the few stocks NSE files lack (REITs, InvITs, BSE-only); the main price feed is fetch_bhavcopy, a gap shows as stale prices on those names only",
}

# Steps and run.sh jobs that will never run again: {step_name: {since, ref, why, feed?}}. Their old
# failures are history, not an alert: Health drops them from PIPELINE_STEP and the ops Flow page shows
# them as "retired (since, ref)". A row logged under one AFTER `since` means something still schedules
# it (RETIRED_STEP_RAN, WARN). `feed`, when set, is the feeds.FEEDS entry retired with it.
RETIRED_STEPS = {
    "cron_bse_announcements": {"since": "2026-10-19", "ref": "ADR 0082", "feed": "bse_announcements",
                               "why": "BSE's WAF 403s this server since 2026-10-13; run.sh forward no longer runs it (NSE is the live source)"},
}

PIPELINE_STEPS = [
    # ── Data Sources ──
    {"name": "fetch_macro_market", "module": "sources.macro_yfinance", "function": "compute", "critical": False,
     "table": "macro_history",     "source": "yfinance (20 tickers)",  "data_freq": "daily",  "frequency": "daily",
     "reads": ["macro_history", "macro_indicator_meta"],
     "writes": ["macro_history", "macro_indicator_meta", "vix_history"],
     "lagged_reads": ["macro_history@fetch_macro_gov"]},

    {"name": "fetch_macro_gov",    "module": "sources.macro_gov",     "function": "compute", "critical": False,
     "table": "macro_history",     "source": "MoSPI (IIP, CPI) + OEA (core) + FRED", "data_freq": "monthly", "frequency": "weekly",
     "reads": ["macro_history", "stocks"],
     "writes": ["macro_history", "macro_indicator_meta", "macro_indicators"],
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
    # Split/bonus/dividend factors composed PIT-strict by pit.py/_prices. Hand-run only
    # until 2026-09-27 (froze 2026-04-30: LIC 1:1 bonus, Trent 1:2 … unadjusted). ~6 s.
    {"name": "compute_corporate_adjustments", "module": "tools.compute_corporate_adjustments", "function": "compute",
     "critical": False, "table": "corporate_adjustments", "source": "corporate_actions + stock_prices",
     "data_freq": "daily", "frequency": "daily",
     "reads": ["corporate_actions", "corporate_adjustments", "stock_prices"],
     "writes": ["corporate_adjustments"]},

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
     "table": "stocks", "source": "stock_prices + fundamentals_screener + annual_balance_sheet + corporate_adjustments + shareholding_categories",
     "data_freq": "monthly", "frequency": "monthly",
     "reads": ["annual_balance_sheet", "corporate_adjustments", "fundamentals_screener", "quarterly_income", "shareholding_categories", "stock_prices", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "fetch_news",         "module": "sources.rss",          "function": "compute", "critical": False,
     "table": "news_articles",     "source": "RSS feeds (10 feeds)", "data_freq": "daily", "frequency": "daily",
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
    # so new schemes get classified; metric-based ANOMALOUS flags get picked up on the next daily
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
    # compute_mf_metrics (returns, risk, score) and scrape_mf_holdings (which reads its scores) are listed
    # after fetch_nse_indices: the metrics need the same session's NIFTY 50 as the NAVs.

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
    # Monthly cron entry handles full refresh (run.sh tickertape).

    # Tickertape HTML scrape — one page hit per stock, writes both analyst_consensus
    # and forecast_history. Single pipeline entry: PIPELINE_STEPS maps one step to
    # one table, so forecast_history's freshness is tracked via its tables.TABLES
    # entry instead of a second step. A second "fetch_forecast" step here used to
    # call the SAME function again — pipeline.py's runner has no (module, function)
    # dedup (only the watchdog's heal loop does), so it ran compute() twice every
    # month: ~1.9h wasted + doubled Tickertape scrape load (audit Eff-F1).
    # fetch_analyst + fetch_shareholding (monthly Tickertape scrapes, ~1.9h + ~1.7h) moved to
    # the END of this list on 2026-09-27 with their writes declared lagged (ADR 0053): on the
    # 1st they sat on the email's critical path (email 07:47 UTC on 2026-09-01).

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
     "reads": ["annual_balance_sheet", "annual_cash_flow", "forensic_scores", "fundamentals_screener", "quarterly_income", "stocks"],
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

    # Cash Conversion Cycle — third Track 3 factor. DSO + DIO − DPO, 3-yr median.
    # Same gating — not in scoring weights yet.

    # Operating Margin Trend — 5y OLS slope of EBIT/Sales (pp/year). Same gating.
    {"name": "signal_operating_margin_trend", "module": "signals.operating_margin_trend", "function": "compute", "critical": False,
     "table": "operating_margin_trend_scores", "source": "fundamentals_screener — Sales + PBT + Interest",
     "data_freq": "annual",        "frequency": "weekly",
     "reads": ["fundamentals_screener", "operating_margin_trend_scores", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Working Capital Intensity — (Recv + Inv − Pay) / Sales, 3y median. Same gating.

    # Interest Coverage — (PBT + Interest) / Interest, 3y median. Same gating.

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

    # Sector-narrative-derived cluster (plan 0003) — 4 factors inspired by
    # IIM Ahmedabad sector-narrative pages. None in scoring weights yet;
    # promotion gated on backtest |t| ≥ 1.5 in any tier.





    {"name": "signal_accruals",    "module": "signals.accruals",    "function": "compute",  "critical": False,
     "table": "accruals_scores",   "source": "quarterly_income + annual_balance_sheet + annual_cash_flow",
     "data_freq": "quarterly",     "frequency": "weekly",
     "reads": ["accruals_scores", "annual_balance_sheet", "annual_cash_flow", "fundamentals_screener", "quarterly_income", "stocks"],
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
     "table": "macro_sector_signals", "source": "macro_history × macro_sector_map (pit.pit_macro_sector)", "data_freq": "daily", "frequency": "daily",
     "reads": ["macro_history", "macro_sector_map", "macro_sector_signals", "stocks"],
     "lagged_reads": ["macro_sector_signals@signal_regulatory", "stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

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
     "reads": ["analyst_consensus", "annual_balance_sheet", "annual_cash_flow", "bse_announcements", "bulk_deals", "forecast_history", "nse_announcements", "quarterly_income", "shareholding", "stock_prices", "stocks", "universe_eligibility"],
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
     "reads": ["analyst_consensus", "annual_balance_sheet", "annual_cash_flow", "bse_announcements", "bulk_deals", "consensus_signals", "corporate_adjustments", "daily_picks", "fno_iv_history", "forecast_history", "fundamentals_screener", "macro_history", "macro_sector_map", "macro_sector_signals_pit", "nlp_scores", "nse_announcements", "quarterly_income", "shareholding", "shareholding_categories", "stock_prices", "stocks", "universe_eligibility"],
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

    # Mutual funds: returns + risk + score + rolling returns + category aggregates from every NAV
    # (fetch_mf_nav_daily) and the NIFTY 50 benchmark (fetch_nse_indices, the same session), so both are
    # blocking reads. Daily since 2026-10-20 (was monthly: the score froze while NAVs moved). Full
    # recompute ~3 min / ~2.7 GB for ~5,700 scored schemes, so no incremental path. mf_metrics and
    # mf_category_stats keep the first computed day of each month plus the latest day
    # (signals.mf_metrics.prune_month), so a daily run does not add a row set per day.
    {"name": "compute_mf_metrics", "module": "signals.mf_metrics",           "function": "compute", "critical": False,
     "table": "mf_metrics",        "source": "mf_nav_history + NIFTY 50 (nse_index_history)", "data_freq": "daily", "frequency": "daily",
     "reads": ["mf_calendar_returns", "mf_category_stats", "mf_metrics", "mf_nav_history", "mf_rolling_returns", "mf_scheme_master", "nse_index_history", "stocks"],
     "writes": ["mf_calendar_returns", "mf_category_stats", "mf_metrics", "mf_rolling_returns"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},
    # Daily rotation (2026-10-10; was monthly top-100 only, which left every other fund frozen
    # and new launches never fetched). Primary: Groww fund pages keyed by AMFI code
    # (sources.mf_holdings_groww); fallback: ETMoney for funds Groww has no page for. Each
    # re-checks funds not seen for 14 days, stalest first, within its host's budget_min.
    # Listed after compute_mf_metrics: it reads today's scores (blocking), and compute_mf_metrics reads the
    # mf_scheme_master this step writes lagged, so a lagged mf_metrics read here would be a cycle.
    {"name": "scrape_mf_holdings", "module": "sources.mf_holdings_scrape",   "function": "compute", "critical": False,
     "table": "mf_holdings",       "source": "ETMoney portfolio-details (public)", "data_freq": "monthly", "frequency": "daily",
     "reads": ["mf_holdings", "mf_metrics", "mf_nav_history", "mf_scheme_master", "stocks"],
     "writes": ["mf_holdings", "mf_sector_allocation", "mf_scheme_master"],
     "lagged_writes": ["mf_scheme_master"],   # only its own etm_* columns; earlier MF steps never read them
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

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
    {"name": "compute_sector_dossiers", "module": "alpha_mcp.steps", "function": "compute_sector_dossiers", "critical": False,
     "table": "sector_dossiers",   "source": "sector_briefs + sector_force_breakdown + sector_metadata (llm_tasks queue)",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["daily_picks", "daily_snapshots", "sector_briefs", "sector_force_breakdown", "sector_metadata", "stock_prices", "stocks"],
     "lagged_reads": ["daily_snapshots@snapshot", "stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # ── Output ──
    {"name": "snapshot",           "module": "output.snapshot",     "function": "compute",  "critical": False,
     "table": "daily_snapshots",   "source": "pit.features_at(today) — the ranked values",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["annual_balance_sheet", "annual_cash_flow", "bulk_deals", "corporate_adjustments", "daily_snapshots", "forecast_history", "fundamentals_screener", "news_article_stocks", "news_articles", "quarterly_income", "shareholding", "stock_prices", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "diff_engine",        "module": "output.diff_engine",  "function": "compute",  "critical": False,
     "table": "daily_changes",     "source": "daily_picks + daily_snapshots (diff)",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["daily_changes", "daily_picks", "daily_snapshots", "stocks", "vix_history"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    {"name": "dossier",            "module": "alpha_mcp.steps",      "function": "dossier",  "critical": False,
     "table": None,                "source": "daily_picks + all signals (llm_tasks queue → local claude -p)",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["accruals_scores", "consensus_signals", "daily_picks", "daily_snapshots", "forensic_scores", "piotroski_scores", "promoter_signals", "sentiment_scores", "smart_money_scores", "stock_prices", "stocks"],
     "writes": ["file:dossiers"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # PIT replay freeze — captures today's pipeline inputs+outputs as a
    # frozen anchor. Daily cadence means every day becomes a regression-test
    # case going forward. It runs BEFORE the email (the email reads it): the
    # pre-send model checks judge the factor inputs frozen here (ADR 0060).
    # Non-critical: without it the email still goes, with a warning banner.
    # See [tools/pit_replay.py] and Plan 0005 Phase E.
    {"name": "pit_replay_freeze",  "module": "tools.pit_replay",    "function": "freeze",   "critical": False,
     "table": "pit_replay_snapshots", "source": "scoring.screener._load_signals + score_universe (frozen)",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["daily_picks"]},

    {"name": "email",              "module": "output.email_sender", "function": "compute",  "critical": False,
     "table": None,                "source": "daily_picks + dossiers (Gmail SMTP)",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["daily_changes", "daily_picks", "daily_snapshots", "file:dossiers", "pit_replay_snapshots", "regime_state", "stock_prices", "stocks"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # Plan 0015 Phase 0: the PIT panel (daily_snapshots_pit) was hand-rebuilt only
    # and froze at 2026-07-01 while the monthly backtest cron re-scored it. Weekly,
    # after the email: re-run recent monthly + Friday anchors (fwd returns mature)
    # and catch up missed ones. ~13 dates × ~40s.
    {"name": "refresh_pit_panel",  "module": "tools.reconstruct_pit", "function": "refresh", "critical": False,
     "table": "daily_snapshots_pit", "source": "all PIT producers over recent anchors",
     "data_freq": "weekly",        "frequency": "weekly",
     "reads": ["accruals_scores", "analyst_consensus_snapshots", "annual_balance_sheet", "annual_cash_flow", "banking_metrics", "bse_announcements", "bulk_deals", "consensus_signals", "corporate_actions", "corporate_adjustments", "daily_picks", "daily_snapshots", "daily_snapshots_pit", "fno_iv_history", "fno_pcr_history", "forecast_history", "forensic_scores", "fundamentals_screener", "insider_trades", "macro_history", "macro_sector_map", "macro_sector_signals_pit", "news_article_stocks", "news_articles", "nlp_scores", "nse_announcements", "piotroski_scores", "pit_reconstruction_log", "promoter_signals", "quarterly_income", "regulatory_events", "regulatory_signals", "sector_briefs", "shareholding", "short_selling_data", "smart_money_scores", "stock_prices", "stocks", "universe_eligibility"],
     "writes": ["daily_snapshots_pit", "macro_sector_signals_pit", "pit_reconstruction_log"],
     "lagged_writes": ["macro_sector_signals_pit"],
     "lagged_reads": ["stocks@classify_micro_tier", "stocks@fetch_broker_recos"]},

    # MICRO tier reclassifier — keeps the SMALL/MICRO boundary fresh as ADTV,
    # quality scores, and fundamental depth change. Idempotent. Demotes any
    # MICRO that re-qualifies for SMALL. See tools/classify_micro_tier.py.
    {"name": "classify_micro_tier","module": "tools.classify_micro_tier", "function": "reclassify", "critical": False,
     "table": "stocks",            "source": "pit.tier_inputs: stock_prices + statements + corporate_adjustments",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["annual_balance_sheet", "corporate_adjustments", "fundamentals_screener", "quarterly_income", "shareholding_categories", "stock_prices", "stocks"],
     "lagged_reads": ["stocks@fetch_broker_recos"]},

    # Multibagger valuation football fields (plan 0026): every field rebuilt on the latest close for the
    # candidate / held names plus the newest thesis run's top 100 (~100-130 names, ~15 s). Was hand-run
    # only and froze at 2026-10-15 while prices moved on. Display only (no pick reads it), so it sits
    # after the email; after refresh_pit_panel so a Sunday sees the refreshed band history.
    {"name": "compute_valuation_ranges", "module": "output.valuation", "function": "compute", "critical": False,
     "table": "valuation_ranges",  "source": "stock_prices + daily_snapshots_pit + quarterly_income + fundamentals_screener + analyst_consensus",
     "data_freq": "daily",         "frequency": "daily",
     "reads": ["analyst_consensus", "corporate_adjustments", "daily_snapshots_pit", "fundamentals_screener", "multibagger_book", "multibagger_scores", "quarterly_income", "stock_prices", "stocks", "valuation_ranges"],
     "lagged_reads": ["stocks@fetch_broker_recos"]},

    # ── Background / non-blocking section ──
    # Heavy enrichment + scrapes that don't gate today's picks. Moved AFTER
    # email so a slow run never blocks production. 2026-05-25 incident:
    # classify_regulatory was second-from-top and ran 1.5+hr daily, blocking
    # fetch_broker_recos + signals + screener + dossier + email entirely.
    # Each runs with its own internal cap so the daily cron has bounded
    # runtime even when there's a large backlog.

    # News Phase 2 enrichment — Claude Haiku (~$0.001/article, ~$1/day).
    {"name": "classify_news",       "module": "alpha_mcp.steps", "function": "classify_news", "critical": False,
     "table": "news_enriched",     "source": "news_articles (Claude Haiku enrich)", "data_freq": "daily", "frequency": "daily",
     "reads": ["news_articles", "news_enriched"]},

    # Daily news brief — Claude Sonnet (~$0.05/day). After classify_news.
    {"name": "news_brief",          "module": "alpha_mcp.steps",   "function": "news_brief", "critical": False,
     "table": "news_briefs",       "source": "news_enriched (Claude Sonnet synthesis)", "data_freq": "daily", "frequency": "daily",
     "reads": ["news_articles", "news_enriched"]},

    # The news editor (plan 0021): daily edition from raw headlines, theme notes and the
    # weekly edition when due. Does not need classify_news.
    {"name": "news_desk",           "module": "alpha_mcp.steps",   "function": "news_desk", "critical": False,
     "table": "news_today",        "source": "news_articles (llm_tasks: news_today, news_theme, news_week)", "data_freq": "daily", "frequency": "daily",
     "reads": ["news_articles", "news_article_stocks", "news_themes", "news_theme_articles", "news_week"]},

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
    {"name": "classify_regulatory","module": "alpha_mcp.steps", "function": "classify_regulatory", "critical": False,
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

    # ── Monthly Tickertape scrapes: after the email (review F1, 2026-09-27) ──
    # Their writes are LAGGED: on the 1st every reader (signals, screener, snapshot,
    # fetch_yf_analyst) sees the previous run's analyst_consensus / shareholding, and the
    # ~3.6h of scraping runs after the email. Shareholding is quarterly and Tickertape PT
    # fields are monthly, so a one-day lag on the 1st changes nothing material.
    # Tickertape HTML scrape — one page hit per stock, writes both analyst_consensus
    # and forecast_history (forecast_history's freshness comes from its tables.TABLES entry;
    # a second "fetch_forecast" step calling the same compute() doubled the scrape — Eff-F1).
    {"name": "fetch_analyst",      "module": "sources.tickertape_analyst", "function": "compute", "critical": False,
     "table": "analyst_consensus", "source": "Tickertape __NEXT_DATA__", "data_freq": "monthly", "frequency": "monthly",
     "reads": ["stocks"],
     "lagged_writes": ["analyst_consensus"]},

    # Tickertape shareholding pattern — Bharat_sm_data API (different path from analyst scrape).
    {"name": "fetch_shareholding", "module": "sources.tickertape_shareholding", "function": "compute", "critical": False,
     "table": "shareholding",      "source": "Tickertape API",        "data_freq": "quarterly", "frequency": "monthly",
     "reads": ["stocks"],
     "lagged_writes": ["shareholding"]},
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
        # of the run.sh morning cron (non-fatal — a failed rebuild just leaves
        # the previous file in place and logs a warning, invisible to health checks
        # until now). No PIPELINE_STEPS entry, so the watchdog can't auto-heal it —
        # this registration only makes a stale/failed rebuild visible (audit Data-F10).
        "virtual_table": "_file_duckdb_replica",
        "glob":          "data/alpha_signal.duckdb",
        "freshness_field": None,       # binary file — mtime-anchored, not JSON-parsed
        "optional":      "cockpit falls back to SQLite reads when the replica is missing",
        "source":        "tools/duckdb_refresh.py (run.sh morning cron tail, non-fatal)",
        "data_freq":     "daily",
        "frequency":     "daily",
        "producer":      "tools.duckdb_refresh",
    },
    {
        # backup_db.sh touches this only after a successful Drive upload (review F13:
        # nothing noticed a failed or skipped nightly backup). No step can heal it.
        "virtual_table": "_file_db_backup",
        "glob":          "output/backup_last_ok",
        "freshness_field": None,       # mtime-anchored
        "source":        "backup_db.sh (05:00 UTC cron) → gdrive:alpha-signal-v2-backups",
        "data_freq":     "daily",
        "frequency":     "daily",
        "producer":      "backup_db.sh",
    },
    {
        # ADR 0073 SMALL paper sleeve: both books' holdings + the SMALL long-hold ranking the cockpit shows
        # (stock page, Stocks screener, /book → Paper sleeve). Monthly, 2nd 06:40 UTC (`run.sh paper_sleeve`).
        "virtual_table": "_file_paper_sleeve",
        "glob":          "output/paper_sleeve/latest.json",
        "freshness_field": "long_hold",
        "source":        "tools/paper_sleeve.py (run.sh paper_sleeve, monthly)",
        "data_freq":     "monthly",
        "frequency":     "monthly",
        "producer":      "tools.paper_sleeve",
    },
    {
        # Plan 0026 1d.8: the multibagger desk's three forward paper books and their kill rules (Held tab panel).
        # Monthly, 2nd 06:50 UTC (`run.sh mb_paper`). Absent until Amit runs `run.sh mb_paper start`.
        "virtual_table": "_file_mb_paper",
        "glob":          "output/mb_paper/latest.json",
        "freshness_field": "asof",
        "optional":      "paper books are started by hand; the Held tab shows an empty state until then",
        "source":        "tools/mb_paper.py (run.sh mb_paper, monthly)",
        "data_freq":     "monthly",
        "frequency":     "monthly",
        "producer":      "tools.mb_paper",
    },
]


# ── NSE corporate announcements -> multibagger event-watch categories (plan 0026 task 4.0) ──
# NSE `desc` (lower-cased, exact) -> watch category. The BSE route will use the same category names:
# results, order_win, acquisition, funding, credit_rating, management_change, auditor_resignation,
# insolvency, shareholding_sast, pledge, clarification, other.
NSE_ANNOUNCEMENT_CATEGORIES = {
    "bagging/receiving of orders/contracts": "order_win",
    "acquisition": "acquisition",
    "scheme of arrangement": "acquisition",
    "sale or disposal": "acquisition",
    "other restructuring": "acquisition",
    "open offer": "acquisition",
    "demerger": "acquisition",
    "preferential issue": "funding",
    "raising of funds": "funding",
    "allotment of securities": "funding",
    "issue of securities": "funding",
    "rights issue": "funding",
    "monitoring agency report": "funding",
    "statement of deviation(s) or variation(s) under reg. 32": "funding",
    "credit rating": "credit_rating",
    "credit rating- revision": "credit_rating",
    "credit rating- new": "credit_rating",
    "credit rating- others": "credit_rating",
    "resignation of director/kmp/smp": "management_change",
    "resignation": "management_change",
    "appointment": "management_change",
    "reappointment": "management_change",
    "cessation": "management_change",
    "change in management": "management_change",
    "change in director(s)": "management_change",
    "change in company secretary/compliance officer": "management_change",
    "change in auditors": "auditor_resignation",
    "resignation of statutory auditor": "auditor_resignation",
    "resignation of statutory auditors": "auditor_resignation",
    "corporate insolvency resolution process": "insolvency",
    "disclosure under sebi takeover regulations": "shareholding_sast",
    "financial result updates": "results",
    "clarification - financial results": "clarification",
    "clarification": "clarification",
    "reply to clarification sought": "clarification",
    "spurt in volume": "clarification",
    "price movement": "clarification",
    "news verification": "clarification",
    "rumour verification - regulation 30(11)": "clarification",
}
# Descs that are explicitly "other" (listed so the coverage test knows they were looked at).
NSE_ANNOUNCEMENT_OTHER_DESCS = (
    "certificate under sebi (depositories and participants) regulations, 2018", "trading plan under pit",
    "public announcement - buyback of shares", "copy of newspaper publication", "shareholders meeting",
    "record date", "dividend", "esop/esos/esps", "allotment of esop/esps", "trading window",
    "structural digital database", "corrigendum", "action(s) taken or orders passed",
    "action(s) initiated or orders passed", "committee meeting updates", "meeting updates",
    "monthly business updates", "amendment to aoa/moa", "book closure", "disclosure of material issue",
    "revocation of suspension of securities", "integrated filing- governance", "name change",
    "rescission/termination(s)", "options to purchase securities", "related party transactions",
    "frauds/default by employees", "revised record date", "loss of share certificates", "product launch",
    "capacity addition", "pendency of litigation(s)/dispute(s) or the outcome impacting the company",
    "granting/withdrawal/surrender/cancellation/suspension of key licenses/ regulatory approvals",
    "effect(s) on listed entity due to changed regulatory  framework applicable")
# Generic descs hide the event in the subject text: re-classify those by keyword (first hit wins).
NSE_ANNOUNCEMENT_GENERIC_DESCS = (
    "updates", "general updates", "outcome of board meeting", "others", "press release",
    "investor presentation", "analysts/institutional investor meet/con. call updates")
NSE_ANNOUNCEMENT_TEXT_RULES = [
    (r"financial results?|unaudited|audited .*results|quarter ended|half year ended|year ended", "results"),
    (r"(receiv|secur|bagg|won|award|bags).{0,60}(order|contract|letter of (award|intent|acceptance))", "order_win"),
    (r"preferential (issue|allot)|qualified institutions placement|\bqip\b|warrants?\b|fund ?raising|raising of funds|rights issue|allotment of (equity|shares|securities|non)", "funding"),
    (r"credit rating|rating (action|assigned|reaffirm|revised)|\bcrisil\b|\bicra\b|care ratings|acuite|india ratings", "credit_rating"),
    (r"auditor", "auditor_resignation"),
    (r"resign|cessation|appointment of|change in (key|senior|management|director)|\bceo\b|\bcfo\b|managing director", "management_change"),
    (r"insolvency|\bcirp\b|\bnclt\b|liquidation", "insolvency"),
    (r"acqui(re|sition)|merger|amalgamation|demerger|slump sale|wholly owned subsidiary|joint venture|stake in", "acquisition"),
    (r"pledge|invocation|encumbrance", "pledge"),
    (r"substantial acquisition|takeover regulations|\bsast\b", "shareholding_sast"),
    (r"clarification|clarifies", "clarification"),
]
# NSE row -> its BSE-equivalent (category, subcategory), so one reader (signals.announcements) serves BSE history
# (bse_announcements, 2018-01 -> 2026-10-12; route dropped, ADR 0082) and NSE live (nse_announcements) in BSE's
# taxonomy. First match wins; within a rule every listed field must match (any of its SQL LIKE patterns,
# case-blind), `not_subject` vetoes. Only what clearly corresponds is mapped; an unmatched row keeps a NULL
# subcategory. Left unmapped on purpose (2026-10-19 data): "Resignation of Director/KMP/SMP" (a pointer filed beside
# the detailed "Resignation" row — mapping both double-counts), "Change in Auditors" (NSE files rotations there;
# BSE's rare "Change in Auditors" weighs 3 in governance_resignation), "Appointment", "Change in Company
# Secretary/Compliance Officer", "Allotment of Securities", "Disclosure under SEBI Takeover Regulations" (one NSE
# desc, several BSE subcategories), "Financial Result Updates", "Shareholders meeting", "Action(s) taken or orders
# passed", "Pendency of Litigation(s)...", "Delay/default in the payment of fines/penalties/dues etc. to authority".
_RESIGN = ["Resignation"]
NSE_BSE_EQUIVALENT = [
    # auditor resignations first, on any desc (a generic desc can carry one: "General Updates", "Cessation")
    {"desc": ["Resignation of Statutory Auditor%"], "bse": ("Company Update", "Resignation of Statutory Auditors")},
    {"subject": ["%resignation of statutory auditor%", "%resignation of the statutory auditor%",
                 "%resignation of joint statutory auditor%"],
     "bse": ("Company Update", "Resignation of Statutory Auditors")},
    # the NSE financial-results submission is BSE's category 'Result'
    {"desc": ["Outcome of Board Meeting"], "subject": ["%submitted to the exchange, the financial result%"],
     "bse": ("Result", "Financial Results")},
    {"desc": ["Outcome of Board Meeting"], "bse": ("Board Meeting", "Outcome of Board Meeting")},
    {"desc": ["Integrated Filing- Financial"], "bse": ("Integrated Filing", "Integrated Filing (Financial)")},
    # a detailed resignation: the role named in the subject picks BSE's subcategory (governance_resignation weights)
    {"desc": _RESIGN, "subject": ["%chief financial officer%", "%(CFO)%", "% CFO %"],
     "bse": ("Company Update", "Resignation of Chief Financial Officer (CFO)")},
    {"desc": _RESIGN, "subject": ["%chairman and managing director%", "%chairman & managing director%"],
     "bse": ("Company Update", "Resignation of Chairman and Managing Director")},
    {"desc": _RESIGN, "subject": ["%managing director%"], "not_subject": ["%whole%time director%"],
     "bse": ("Company Update", "Resignation of Managing Director")},
    {"desc": _RESIGN, "subject": ["%chief executive officer%", "%(CEO)%", "% CEO %"],
     "bse": ("Company Update", "Resignation of Chief Executive Officer (CEO)")},
    {"desc": _RESIGN, "subject": ["%chairman%", "%chairperson%"], "not_subject": ["%vice chair%", "%vice-chair%"],
     "bse": ("Company Update", "Resignation of Chairman")},
    {"desc": _RESIGN, "subject": ["%company secretary%", "%compliance officer%"],
     "bse": ("Company Update", "Resignation of Company Secretary / Compliance Officer")},
    {"desc": _RESIGN, "subject": ["%director%"], "bse": ("Company Update", "Resignation of Director")},
    {"desc": ["Cessation"], "bse": ("Company Update", "Cessation")},
    {"desc": ["Retirement"], "bse": ("Company Update", "Retirement")},
    {"desc": ["Demise"], "bse": ("Company Update", "Demise")},
    {"desc": ["Change in Management"], "bse": ("Company Update", "Change in Management")},
    {"desc": ["Change in Director(s)"], "bse": ("Company Update", "Change in Directorate")},
    {"desc": ["Corporate Insolvency Resolution Process%"],
     "bse": ("Company Update", "Updates - Corporate Insolvency Resolution Process  (CIRP)")},
    {"desc": ["Credit Rating%"], "bse": ("Company Update", "Credit Rating")},
    {"desc": ["Bagging/Receiving of orders/contracts"], "bse": ("Company Update", "Award of Order / Receipt of Order")},
    {"desc": ["Memorandum of Understanding/Agreements"],
     "bse": ("Company Update", "Memorandum of Understanding /Agreements")},
    {"desc": ["Acquisition"], "bse": ("Company Update", "Acquisition")},
    {"desc": ["Scheme of Arrangement"], "bse": ("Company Update", "Scheme of Arrangement")},
    {"desc": ["Amalgamation/Merger", "Demerger"], "bse": ("Corp. Action", "Amalgamation / Merger / Demerger")},
    {"desc": ["Open offer"], "bse": ("Company Update", "Open Offer")},
    {"desc": ["Delisting"], "bse": ("Company Update", "Delisting")},
    {"desc": ["Preferential issue"], "bse": ("Company Update", "Preferential Issue")},
    {"desc": ["Qualified Institutional Placement"], "bse": ("Company Update", "Qualified Institutional Placement")},
    {"desc": ["Raising of funds"], "bse": ("Company Update", "Raising of Funds")},
    {"desc": ["Monitoring Agency Report"], "bse": ("Company Update", "Monitoring Agency Report")},
    {"desc": ["Clarification", "Spurt in Volume", "Price movement", "News Verification",
              "Rumour Verification%", "Reply to clarification sought"], "bse": ("Company Update", "Clarification")},
    {"desc": ["Press Release"], "bse": ("Company Update", "Press Release / Media Release")},
    {"desc": ["Investor Presentation"], "bse": ("Company Update", "Investor Presentation")},
    {"desc": ["Analysts/Institutional Investor Meet/Con. Call Updates"], "bse": ("Company Update", "Analyst / Investor Meet")},
    {"desc": ["Copy of Newspaper Publication"], "bse": ("Company Update", "Newspaper Publication")},
    # NSE's catch-alls and its Reg 30 fraud / default descs: BSE files all of these under 'General'
    {"desc": ["General Updates", "Updates", "Fraud/Default/Arrest", "Frauds/Default by employees"],
     "bse": ("Company Update", "General")},
]
# ── Multibagger desk: per-name event watch (plan 0026 phase 4; signals/mb_watch.py) ──
WATCH_CATEGORIES = ("results", "order_win", "acquisition", "funding", "credit_rating", "management_change",
                    "auditor_resignation", "insolvency", "shareholding_sast", "pledge", "clarification", "other")
WATCH_SEVERITY = {"low": 0, "medium": 1, "high": 2}

# BSE `subcategory` (as filed) → (watch category, severity). Covers all 190 subcategories in
# bse_announcements (2026-10-15), so the top 150 by count are all mapped; an unseen or NULL one falls to
# ANNOUNCEMENT_DEFAULT. A second announcement source (NSE) plugs in by adding its own map here
# (NSE_ANNOUNCEMENT_CATEGORIES) and a loader to signals.mb_watch._ANN_LOADERS; categories and severities are shared.
_BSE_GROUPS = (
    ("results", "medium", ("Financial Results", "Integrated Filing (Financial)")),
    ("results", "low", ("Earnings Call Transcript", "Monthly Business Updates",
                        "Half Yearly Report (SEBI Circular No. CIR/IMD/DF-1/67/2017)",
                        "Limited Review Report", "Auditors Report", "Analyst / Investor Meet")),
    ("order_win", "medium", ("Award of Order / Receipt of Order",)),
    ("order_win", "low", ("Memorandum of Understanding /Agreements", "Agreement")),
    ("acquisition", "high", ("Open Offer", "Public Announcement-Open Offer", "Amalgamation / Merger / Demerger",
                             "Change in Management Control", "Delisting", "Public Announcement-Delisting",
                             "Voluntary Delisting")),
    ("acquisition", "medium", ("Acquisition", "Joint Venture", "Scheme of Arrangement", "Open Offer - Updates",
                               "Diversification / Disinvestment", "Restructuring")),
    ("acquisition", "low", ("Sale of shares", "Court Convened Meeting", "Post Offer Public Announcement",
                            "Public Announcement")),
    ("funding", "high", ("Preferential Issue", "Qualified Institutional Placement", "Raising of Funds")),
    ("funding", "medium", ("Allotment of Warrants", "Issue of Securities", "Bonds / Right issue", "FCCBs",
                           "Institutional Placement Programme", "Offer for Sale", "Capital Reduction")),
    ("funding", "low", ("Allotment of Equity Shares", "Allotment of ESOP / ESPS",
                        "Funds raising by issuance of Debt Securities by Large Entities",
                        "Debt Securities", "Conversion of Securities", "Monitoring Agency Report",
                        "Reg. 32 (1), (3) - Statement of Deviation & Variation", "Increase of Authorised Capital",
                        "Annulment / Re-issue of forfeited shares")),
    ("credit_rating", "medium", ("Credit Rating",)),
    ("management_change", "high", ("Resignation of Chief Financial Officer (CFO)", "Resignation of Managing Director",
                                   "Resignation of Chief Executive Officer (CEO)", "Resignation of Chairman",
                                   "Resignation of Chairman and Managing Director")),
    ("management_change", "medium", ("Change in Management", "Appointment of Chief Financial Officer (CFO)",
                                     "Appointment of Managing Director", "Appointment of Chief Executive Officer (CEO)",
                                     "Appointment of Chairman", "Appointment of Chairman and Managing Director",
                                     "Appointment of Managing Director & CEO", "Demise")),
    ("management_change", "low", ("Change in Directorate", "Resignation of Director",
                                  "Resignation of Company Secretary / Compliance Officer",
                                  "Appointment of Company Secretary / Compliance Officer", "Appointment of Director",
                                  "Cessation", "Retirement")),
    ("auditor_resignation", "high", ("Resignation of Statutory Auditors",)),
    ("auditor_resignation", "medium", ("Change in Auditors",)),
    ("auditor_resignation", "low", ("Appointment of Statutory Auditor/s",)),
    ("insolvency", "high", ("Updates - Corporate Insolvency Resolution Process  (CIRP)",
                            "Outcome of meeting of Committee of Creditors",
                            "Liquidation - Corporate Insolvency Resolution Process  (CIRP)", "Winding-up",
                            "Admission of application by Tribunal", "Approval of Resolution plan by Tribunal",
                            "Rejection of Resolution pan by Tribunal",
                            "Appointment of Interim Resolution Professional (IRP)",
                            "Initiation of Corporate Insolvency Resolution Process (CIRP) by Financial Creditors",
                            "Initiation of Corporate Insolvency Resolution Process (CIRP) by Corporate Applicant",
                            "Corporate Debt Restructuring")),
    ("insolvency", "medium", ("Intimation of meeting of Committee of Creditors", "Invitation of Resolution Plan",
                              "Resolution Plans received by Resolution Professional",
                              "Filing of Resolution plan with Tribunal", "List of Creditors",
                              "Replacement of Interim Resolution Professional (IRP)",
                              "Disclosures by listed entities of defaults on payment of interest/ repayment of principal amount for unlisted debt securities i.e. NCDs and NCRPS.")),
    ("insolvency", "low", ("Quarterly Disclosures by listed entities of defaults on payment of interest/ repayment of principal amount on loans from banks / financial institutions and unlisted debt securities.",
                           "Disclosures by listed entities of defaults on payment of interest/ repayment of principal amount for loans including revolving facilities like cash credit from banks / financial institutions.",
                           "Disclosure of divergence in the asset classification and provisioning by banks")),
    ("shareholding_sast", "medium", ("Disclosures under Reg. 29(1) of SEBI (SAST) Regulations, 2011",)),
    ("shareholding_sast", "low", ("Shareholding", "Disclosures under Reg. 29(2) of SEBI (SAST) Regulations, 2011",
                                  "Disclosures under Reg. 10(6) of SEBI (SAST) Regulations, 2011",
                                  "Disclosures under Reg. 10(7) of SEBI (SAST) Regulations, 2011",
                                  "Disclosures under Reg. 10(5) in respect of acquisition under Reg. 10(1)(a) of SEBI (SAST) Reg. 2011",
                                  "Disclosures under Reg. 10(5) in respect of acquisition under Reg. 10(4)(f) of SEBI (SAST) Reg. 2011",
                                  "Disclosures under Reg. 10(5) in respect of acquisition under Reg. 10(4)(e) of SEBI (SAST) Reg. 2011",
                                  "Disclosures under Reg. 18(6) of SEBI (SAST) Regulations, 2011",
                                  "Disclosures under Reg. 7(1) of SEBI (SAST) Regulations, 1997",
                                  "Disclosures under Reg. 7(1A) of SEBI (SAST) Regulations, 1997",
                                  "Disclosures under Reg. 7(3) of SEBI (SAST) Regulations, 1997",
                                  "Disclosures under Reg.13(6) of SEBI (Prohibition of Insider Trading) Regulations, 1992",
                                  "Disclosures under Reg.13(4A) of SEBI (Prohibition of Insider Trading) Regulations, 1992",
                                  "Disclosures under Reg.13(4) of SEBI (Prohibition of Insider Trading) Regulations, 1992",
                                  "Disclosures under Reg.13(4), 13(4A) of SEBI (Prohibition of Insider Trading) Regulations, 1992",
                                  "Disclosure under Clause 35A of the Listing Agreement", "Disclosure of IDR Holding",
                                  "Trading Plan under SEBI (PIT) Regulations, 2015")),
    ("pledge", "medium", ("Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011",
                          "Disclosure under Reg. 31(4) of SEBI (SAST) Regulation, 2011")),
    ("clarification", "medium", ("Clarification",)),
    ("other", "medium", ("Strikes /Lockouts / Disturbances", "Strike", "Buy back", "Public Announcement-Buyback",
                         "Sub-division / Stock Split", "Bonus", "Consolidation of Shares",
                         "Reg. 51 (1), (2) - Price Sensitive information / disclosure of event / Information")),
    ("other", "low", ("General", "Board Meeting", "Newspaper Publication", "AGM", "Closure of Trading Window",
                      "Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate",
                      "Certificate under Reg. 74 (5) of SEBI (DP) Regulations, 2018",
                      "Outcome of Board Meeting", "Reg. 13(3) - Statement of Investor Complaints",
                      "Press Release / Media Release",
                      "Reg. 40 (10) - PCS Certificate for Transfer / Transmission / Transposition",
                      "Reg. 7(3) – Compliance Certificate (RTA & Compliance Officer)",
                      "Reg. 34 (1) Annual Report", "Postal Ballot", "Investor Presentation",
                      "Reg.24(A)-Annual Secretarial Compliance", "Book Closure", "EGM", "Outcome without intimation",
                      "Dividend", "Record Date",
                      "Format of the Initial Disclosure to be made by an entity identified as a Large Corporate : Annexure A",
                      "Meeting Updates", "Board Meeting Rescheduled",
                      "Business Responsibility and Sustainability Reporting (BRSR)", "Book Closure / AGM",
                      "Code of Conduct under SEBI (PIT) Regulations, 2015", "Dividend Updates",
                      "Amendments to Memorandum & Articles of Association",
                      "Format of the Annual Disclosure to be made by an entity identified as a LC : Annexure B2",
                      "Format of the Annual Disclosure to be made by an entity identified as a LC : Annexure B1",
                      "Change in Registered Office Address", "Revision of outcome", "Dividend/AGM",
                      "57 (5) : intimation after the end of quarter", "New Listing",
                      "Certificate under Reg. 54 (5) of SEBI (DP) Regulations, 1996", "Board Meeting Cancelled",
                      "Press Release / Media Release (Revised)", "Date of payment of Dividend", "Change of Name",
                      "Interest Rates Updates", "Change in Corporate Office Address", "Reg. 54 - Asset Cover details",
                      "Intimation of Repayment of Commercial Paper (CP)",
                      "Format of the Annual Disclosure to be made by an entity identified as a Large Corporate",
                      "Reg. 57 (1) - Certificate of interest payment/Principal in case of NCD",
                      "57 (4) : Prior intimation to the beginning  of the quarter", "Committee Meeting",
                      "Post Buyback Public Announcement", "Certificate from CEO/CFO",
                      "Reg. 50 (1) - Prior intimation about Board meeting under Regulation 50(1))",
                      "Closure of Buy Back", "Daily Buy Back of equity shares",
                      "Regulation 61(4) - PCS Certificate for Transfer / Transmission / Transposition",
                      "Board Meeting Adjourned", "Reg. 52 (5) - Certificate from Debenture Trustee",
                      "Integrated Filing (Governance)", "Board Meeting Postponed",
                      "Reg. 57 (2) - Undertaking that documents & intimation submitted to Debenture trustee",
                      "Half Yearly Communication - Debt Instruments", "Asset Liability Management (ALM) statement",
                      "Reg. 50 (2) - Intimation to the Exchange about meeting under 50(2)", "Board Meeting Deferred",
                      "Cancellation of Dividend", "Mutual Fund Scheme Summary Document",
                      "Reg. 52 - Declaration for Audit Report/s with Unmodified Opinion(s)")),
)
BSE_ANNOUNCEMENT_CATEGORIES = {sub: (cat, sev) for cat, sev, subs in _BSE_GROUPS for sub in subs}
ANNOUNCEMENT_DEFAULT = ("other", "low")

# Government / PSU / LIC / state-body holders: upper-case substrings of shareholding_holders.holder_name.
GOVT_HOLDER_PATTERNS = (
    "PRESIDENT OF INDIA", "GOVERNOR OF", "GOVERNMENT OF", "GOVT OF", "LIFE INSURANCE CORPORATION",
    "GENERAL INSURANCE CORPORATION", "NEW INDIA ASSURANCE", "UNITED INDIA INSURANCE", "ORIENTAL INSURANCE",
    "INDUSTRIAL DEVELOPMENT CORPORATION", "STATE INDUSTRIAL", "SPECIFIED UNDERTAKING OF THE UNIT TRUST",
    "SMALL INDUSTRIES DEVELOPMENT BANK", "IFCI", "NABARD", "RAILWAY",
)
# shareholding_holders filing sections that are government by definition.
GOVT_HOLDER_CATEGORIES = ("CentralGovernmentOrStateGovernments",)
# Headline keywords (upper-case, matched as substrings) for orders from government buyers.
GOVT_BUYER_KEYWORDS = (
    "MINISTRY", "GOVERNMENT OF", "GOVT", "RAILWAY", "INDIAN NAVY", "INDIAN ARMY", "INDIAN AIR FORCE", "COAST GUARD",
    "DRDO", "NHAI", "NATIONAL HIGHWAYS", "BSNL", "MTNL", "ONGC", "NTPC", "NHPC", "SJVN", "POWER GRID", "POWERGRID",
    "BHEL", "HINDUSTAN AERONAUTICS", "BHARAT ELECTRONICS", "COAL INDIA", "INDIAN OIL", "IOCL", "BPCL", "HPCL", "GAIL",
    "NMDC", "JAL JEEVAN", "SMART CITY", "METRO RAIL", "DISCOM", "MUNICIPAL", "PUBLIC SECTOR", "PSU",
)
WATCH_HOLDER_MIN_PCT = 1.0        # a named holder at or above this % of equity is a timeline event
WATCH_PROMOTER_MOVE_PTS = 1.0     # promoter / pledge / MF / FII holding change (percentage points) that is an event
WATCH_DEAL_VALUE_CR = {"medium": 1.0, "high": 10.0}   # bulk / block / insider trade value (Rs crore) -> severity
WATCH_NEWS_DAYS = 365             # news and sector-regulatory events in a timeline with no `since`

# 15 investors widely known for Indian small caps before 2018 -> upper-case substrings matched against
# shareholding_holders.holder_name. Copied verbatim from tools/mb_thesis_v2.py SI_NAMES (frozen 2026-10-15;
# that tool is a pre-registration and is not edited). Only filings after 2016 are read.
SUPERINVESTORS = {
    "Ashish Kacholia": ["ASHISH KACHOLIA", "ASHISH RAMESHCHANDRA KACHOLIA", "BENGAL FINANCE & INVESTMENT"],
    "Vijay Kedia": ["VIJAY KISHANLAL KEDIA", "VIJAY KEDIA", "KEDIA SECURITIES"],
    "Dolly Khanna": ["DOLLY KHANNA", "RAJIV KHANNA"],
    "Mukul Agrawal": ["MUKUL MAHAVIR AGRAWAL", "MUKUL AGRAWAL", "PARAM CAPITAL"],
    "Porinju Veliyath": ["PORINJU", "EQUITY INTELLIGENCE INDIA"],
    "Rakesh / Rekha Jhunjhunwala": ["RAKESH RADHEYSHYAM JHUNJHUNWALA", "REKHA RAKESH JHUNJHUNWALA",
                                    "RAKESH JHUNJHUNWALA", "REKHA JHUNJHUNWALA", "RARE INVESTMENTS"],
    "Radhakishan Damani": ["RADHAKISHAN SHIVKISHAN DAMANI", "RADHAKISHAN DAMANI", "DERIVE TRADING",
                           "BRIGHT STAR INVESTMENTS"],
    "Ramesh Damani": ["RAMESH SHRICHAND DAMANI", "RAMESH DAMANI"],
    "Anil Kumar Goel": ["ANIL KUMAR GOEL", "SEEMA GOEL"],
    "Ashish Dhawan": ["ASHISH DHAWAN"],
    "Nemish Shah": ["NEMISH S SHAH", "NEMISH SHAH", "ENAM SECURITIES"],
    "Akash Bhanshali": ["AKASH BHANSHALI", "AKASH PRAKASH BHANSHALI"],
    "Satpal Khattar": ["SATPAL KHATTAR", "KHATTAR HOLDINGS"],
    "Sunil Singhania": ["ABAKKUS", "SUNIL SINGHANIA"],
    "Madhusudan Kela": ["MADHUSUDAN KELA", "MADHURI MADHUSUDAN KELA", "SINGULARITY"],
}

# Plan 0026 / ADR 0076: name exits by process, not price (the reviewer's name kill, research 0008).
# "exit": leave at the next liquid session; "review": decide within a week (our event study: 44-57 % false alarms).
MB_EXITS = {
    "auditor_days": 90,          # a statutory-auditor resignation filed within this many days -> exit
    "gsm_types": ("GSM",),       # on the latest surveillance list -> exit (ESM is not in surveillance_flags yet)
    "results_grace_days": 60,    # no results for the quarter after the latest one by its end + this -> exit
    "pledge_review_pct": 50.0,   # promoter pledge above this -> review
    "promoter_drop_pts": 5.0,    # promoter stake down more than this over the last two quarters -> review
    "demerger_days": 365,        # demerged within this many days -> review: the thesis score reads pre-demerger
                                 # fundamentals against the post-demerger price (BHIL #1 on 2026-10-15)
    "revenue_mismatch": 1.25,    # latest quarter's revenue in quarterly_income vs Screener Sales off by more than this
                                 # factor -> review: a one-off gain counted as revenue (THEM 2.1x on 2026-10-15)
    "shares_mismatch": 1.3,      # market cap from the latest filed total shares off by more than this factor from the
                                 # thesis market cap -> review: stale share count (IIAB #2 was 22x too small, 2026-10-15)
}
