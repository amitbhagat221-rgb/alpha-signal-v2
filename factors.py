"""
Alpha Signal v2 — the factor registry. One entry per factor; every factor list
in the codebase is DERIVED from it (bottom of this file) — never hand-edit a copy.

Adding a factor = one FACTORS entry + its pit_* helper in pit.py (+ a
PIT_PRODUCERS row if it is a new --signal group). Everything else — PIT_COLUMNS,
VALIDATION_RANGES, the backtest column map, cadence, FACTOR_LIBRARY /
FACTOR_STATUS, the screener's column map, the weight-key alias map, the weights
view, pit_replay inputs, eligibility, lineage — follows from the entry.

WEIGHTS are hand-set ON the entry (`weights: {tier: w}`, ADR 0052 D4 — amends ADR
0017) and NEVER derived from evidence (CLAUDE.md "Backtest hygiene",
docs/reference/signal-weights.md). SIGNAL_WEIGHTS ({tier: {weight_key: w}}) is the
derived view. A factor is WIRED iff it carries a nonzero weight; its lifecycle
status is COMPUTED by status() from the weights + its "bench", never stored.
Weight rules (ADR 0049, 2026-07-05 honest re-derivation): clean |t|≥1.5 on the tier,
n≥20 anchors, sign matches the economic prior, one representative per orthogonal
family, benched-for-cause stays benched; weights ∝ shrunk conviction, single-factor
cap ~0.30, Σ|w| = 1.0 per tier (tests/test_factor_registry.py enforces the sum).

Entry fields (keyed by the registry signal id — the old BACKTEST_SIGNALS "signal").
[default] = inferred by _fill_defaults() when absent; write the field only when it differs.
  metadata         label, group, description, source_tables [its producer's
                   tables — factors.producer_tables()], source_columns,
                   filing_lag, pit_column_v1 [None], pit_column_v2 [the key],
                   [external_table], v1_verdict_summary, status (DATA readiness:
                   READY/DEGRADED/DROPPED/PROPOSED/SUPERSEDED/CONTROL) [READY],
                   status_reason [""]
  cadence          backtest cadence: monthly | weekly | sector_portfolio | portfolio [monthly]
  producer         tools/reconstruct_pit --signal group that writes pit_column_v2
  pit_range        (lo, hi) — values outside are DISCARDED (NaN), in PIT and live
  weights          {tier: w} production weight per rankable tier (config.TIERS pickable);
                   absent = not wired
  bench            non-wired home (ADR 0017; audit Factor-F2 — every factor must
                   be weighted or benched, factors.partition_check()):
                     LIBRARY    computed + PIT-reconstructable, below the |t|≥1.5
                                promotion bar (or parked pending sign/regime review)
                     PROPOSED   KEEP-grade or zero-backtest-row; a visible
                                promotion candidate. Wiring is a human decision.
                     BLOCKED    data or methodology blocker
                     SUPERSEDED replaced by another id; kept for lineage/back-compat
                     CONTROL    categorical/structural covariate, not alpha
  weight_key       the screener's name for this factor [the key, when `weights` is set]
  tiers            restrict weight_key → this id to these tiers (momentum 12m ↔ SMALL)
  screener_col     column in scoring.screener._load_signals() output [weight_key]
  replay_col       daily_snapshots_pit column the screener column is fed from
                   [the PIT column; None = display-only, no PIT twin]
  family           orthogonal family for tools/factor_marginal --within-group
  eligibility      {description, eligible_sql} — who SHOULD have a score (plan 0005)

Cadence taxonomy (2026-05-24, ADR 0022):
  monthly          slow-moving fundamentals/momentum/shareholding/analyst; C13b
                   framework; fwd_return_20d, no Newey-West. The default.
  weekly           behavioural / event / news / daily-published; Friday anchors,
                   Newey-West when the signal window overlaps the eval gap.
  sector_portfolio sector-level signals — a sector-tilt portfolio test, not IC.
  portfolio        the end-state composite — Track 2.4 portfolio backtest.
Data status taxonomy ("status", readiness — NOT lifecycle): READY (in a PIT table),
PARTIAL, MISSING (raw data exists, reconstruction not written), PROPOSED (v1
inventory, no v2 module), BLOCKED (raw data insufficient), plus DROPPED /
DEGRADED / SUPERSEDED / CONTROL markers. Everything — even DROP verdicts — stays
registered: regimes shift. IC / t / verdict live in pit_ic_by_tier_v2, never here.

Imports config (tiers) but never db — db.py re-exports the registry views. config
must not import this module at load time (its legacy weight aliases are lazy).
"""

import numpy as np

import config

# A quarterly-result print in bse_announcements. Most companies file it under category
# 'Result'; many large ones (Bank of Baroda, PNB, Canara, Coal India, LIC …) file it as the
# outcome of the board meeting. Counting only 'Result' left the earnings-window factor
# empty for them, and six large banks fell out of the 2026-10-04 picks on coverage.
RESULT_FILING_SQL = ("(category = 'Result' OR (subcategory = 'Outcome of Board Meeting' AND "
                     "(lower(headline) LIKE '%financial result%' OR lower(headline) LIKE '%unaudited%' "
                     "OR lower(headline) LIKE '%audited financial%')))")

FACTORS = {

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 1 — VALUE
    # ═══════════════════════════════════════════════════════════════════

    "earnings_yield": {
        "label": "Earnings Yield (TTM E/P)",
        "group": "Value",
        "description": "Trailing 12-month EPS / current price",
        "source_columns": ["qi.eps", "stock_prices.close"],
        "filing_lag": "60d quarterly + 0d price",
        "pit_column_v1": "earnings_yield",
        "v1_verdict_summary": "DROP / DROP / KEEP (t=3.13 SMALL)",
        "producer": "earnings_yield",
        "pit_range": (-10, 10),
        "weight_key": "earnings_yield",
        "family": "Value",
        "eligibility": {
            "description": "Stocks with ≥4 quarters of EPS in quarterly_income AND a close price",
            "eligible_sql": """
                SELECT DISTINCT qi.sid FROM quarterly_income qi
                WHERE qi.sid IN (SELECT DISTINCT sid FROM stock_prices)
                  AND qi.eps IS NOT NULL
                GROUP BY qi.sid HAVING COUNT(*) >= 4
            """,
        },
    },
    "book_to_price": {
        "label": "Book-to-Price",
        "group": "Value",
        "description": "Per-share book equity / price",
        "source_columns": ["bs.total_equity", "bs.shares_outstanding", "stock_prices.close"],
        "filing_lag": "75d annual + 0d price",
        "pit_column_v1": "book_to_price",
        "v1_verdict_summary": "DROP / WEAK / KEEP (t=2.54 SMALL)",
        "producer": "book_to_price",
        "pit_range": (-100, 1000),
        "weight_key": "book_to_price",
        "bench": "LIBRARY",  # un-wired: t: L 1.26 · M 1.18 · S 0.71, below the 1.5 bar — promotion review 2026-10-03 (docs/studies/promotion-review-2026-10.md), corrected panel
        "family": "Value",
        "eligibility": {
            "description": "Stocks with annual_balance_sheet.total_equity + shares_outstanding>0 + a close price",
            "eligible_sql": """
                SELECT DISTINCT abs.sid FROM annual_balance_sheet abs
                WHERE abs.total_equity IS NOT NULL
                  AND abs.shares_outstanding IS NOT NULL AND abs.shares_outstanding > 0
                  AND abs.sid IN (SELECT DISTINCT sid FROM stock_prices)
            """,
        },
    },
    "position_52w": {
        "label": "52-Week Range Position",
        "group": "Value",
        "description": "(close − 52w_low) / (52w_high − 52w_low) — proximity to lows is value-positive",
        "source_columns": ["stock_prices.close (rolling 252d high/low)"],
        "filing_lag": "0d",
        "v1_verdict_summary": "(used as 25% of value composite, not separately validated)",
        "producer": "position_52w",
        "pit_range": (0, 1),
        "bench": "LIBRARY",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 2 — QUALITY (profitability + leverage + efficiency)
    # ═══════════════════════════════════════════════════════════════════

    "piotroski_f_score": {
        "label": "Piotroski F-Score",
        "group": "Quality",
        "description": "9-factor profitability + leverage + efficiency score (0-9)",
        "source_columns": ["qi.{eps,net_income,revenue}", "bs.{total_assets,equity,debt,shares_outstanding}", "cf.operating_cash_flow"],
        "filing_lag": "75d annual + 60d quarterly",
        "pit_column_v1": "piotroski_f",
        "pit_column_v2": "piotroski_f",
        "v1_verdict_summary": "DROP / WEAK / KEEP (t=2.81 SMALL)",
        "producer": "piotroski",
        "pit_range": (0, 9),
        "weights": {"MID": 0.18, "SMALL": 0.14},  # t: M 3.63 · S 4.26 (26 anchors) — promotion review 2026-10-03 (docs/studies/promotion-review-2026-10.md), corrected panel
        "weight_key": "piotroski",
        "screener_col": "f_score",
        "family": "Quality",
        "eligibility": {
            "description": "Stocks with ≥2 annual periods (YoY F-score baseline), EX-Financials (F-score components are non-financial-firm constructs — mirrors lineage.py sector_exclusions)",
            "eligible_sql": """
                SELECT sid FROM annual_balance_sheet
                WHERE sid NOT IN (SELECT sid FROM stocks WHERE sector = 'Financials')
                GROUP BY sid HAVING COUNT(*) >= 2
            """,
        },
    },
    "cf_accruals_ratio": {
        "label": "CF Accruals (Sloan)",
        "group": "Quality",
        "description": "(Net income − operating CF) / total assets — earnings backed by cash",
        "source_columns": ["qi.net_income", "cf.operating_cash_flow", "bs.total_assets"],
        "filing_lag": "75d annual + 60d quarterly",
        "pit_column_v1": "cf_accruals",
        "pit_column_v2": "cf_accruals",
        "v1_verdict_summary": "DROP / KEEP / WEAK (t=3.20 MID)",
        "producer": "accruals",
        "pit_range": (-100, 100),
        # clean t=−2.65 on THIS column (low accruals = cash-backed earnings → negative weight).
        # Until 2026-10-03 the weight was +0.22 on `accruals_signal`, a four-part blend with no
        # evidence of its own (MID t=0.59 on 8 anchors); the blend stays in the panel, unweighted.
        "weights": {"MID": -0.12},  # t: M −1.92 on this column — promotion review 2026-10-03 (docs/studies/promotion-review-2026-10.md), corrected panel
        "weight_key": "accruals",
        "family": "Quality",
        "eligibility": {
            "description": "Stocks with annual_balance_sheet + annual_cash_flow, EX-Financials (banks have no operating accruals — mirrors lineage.py sector_exclusions / config.financial_sectors)",
            "eligible_sql": """
                SELECT DISTINCT abs.sid FROM annual_balance_sheet abs
                INNER JOIN annual_cash_flow acf ON acf.sid = abs.sid
                WHERE abs.sid NOT IN (SELECT sid FROM stocks WHERE sector = 'Financials')
            """,
        },
    },
    "bs_accruals_ratio": {
        "label": "BS Accruals",
        "group": "Quality",
        "description": "ΔWorking capital − capex − depreciation, scaled by assets",
        "source_columns": ["bs.{current_assets,liabilities,cash}", "screener.Depreciation"],
        "filing_lag": "75d annual",
        "pit_column_v1": "bs_accruals",
        "pit_column_v2": "bs_accruals",
        "v1_verdict_summary": "DROP / DROP / DROP",
        "status_reason": "Kept despite DROP — regimes change",
        "producer": "accruals",
        "pit_range": (-10, 10),
        "bench": "PROPOSED",  # TODO amit: classify
    },
    "earnings_persistence": {
        "label": "Earnings Persistence (EPS CV)",
        "group": "Quality",
        "description": "Coefficient of variation of trailing-8-quarter EPS — lower = more persistent",
        "source_columns": ["qi.eps"],
        "filing_lag": "60d quarterly",
        "pit_column_v1": "eps_cv",
        "v1_verdict_summary": "(diagnostic, sparse coverage)",
        "producer": "accruals",
        "pit_range": (0, 1000),
        "bench": "PROPOSED",
    },
    "earnings_beat_rate": {
        "label": "Earnings Beat Rate",
        "group": "Quality",
        "description": "Fraction of last-N quarters where actual EPS beat consensus (proxy: vs prev-quarter run-rate)",
        "source_columns": ["qi.eps"],
        "filing_lag": "60d quarterly",
        "pit_column_v1": "earnings_beat_rate",
        "v1_verdict_summary": "(diagnostic, used inside accruals composite)",
        "status_reason": "v2 reconstruction now writes column. Proxy: fraction of last 8 quarters with positive QoQ EPS growth (v1 used vs-consensus; we lack consensus per quarter). 2,161-2,221 stocks populated across all 7 snapshot dates.",
        "producer": "earnings_beat_rate",
        "pit_range": (0, 1),
        "bench": "LIBRARY",
    },
    "roe": {
        "label": "Return on Equity",
        "group": "Quality",
        "description": "Net income / total equity (TTM)",
        "source_columns": ["qi.net_income (TTM)", "bs.total_equity"],
        "filing_lag": "75d annual + 60d quarterly",
        "v1_verdict_summary": "(45% of quality composite — quality_recon: DROP all tiers)",
        "status_reason": "Negative-equity stocks → NaN (D/E meaningless there).",
        "producer": "quality_fundamentals",
        "pit_range": (-200, 1000),
        "bench": "PROPOSED",  # TODO amit: classify
    },
    "roa": {
        "label": "Return on Assets",
        "group": "Quality",
        "description": "Net income / total assets (TTM)",
        "source_columns": ["qi.net_income (TTM)", "bs.total_assets"],
        "filing_lag": "75d annual + 60d quarterly",
        "v1_verdict_summary": "(component of Track 2.2 financial sub-model; not in main C13b)",
        "producer": "quality_fundamentals",
        "pit_range": (-100, 200),
        "bench": "PROPOSED",  # TODO amit: classify
    },
    "debt_to_equity": {
        "label": "Debt-to-Equity",
        "group": "Quality",
        "description": "Total debt / total equity (lower better; financial sector excluded)",
        "source_columns": ["bs.total_debt", "bs.total_equity"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "(30% of quality composite)",
        "status_reason": "Financial sector NaN'd (D/E meaningless for banks).",
        "producer": "quality_fundamentals",
        "pit_range": (0, 50),
        "bench": "LIBRARY",
    },
    "profit_margin": {
        "label": "Profit Margin",
        "group": "Quality",
        "description": "Net income / revenue (TTM)",
        "source_columns": ["qi.net_income", "qi.revenue"],
        "filing_lag": "60d quarterly",
        "v1_verdict_summary": "(25% of quality composite)",
        "producer": "quality_fundamentals",
        "pit_range": (-100, 100),
        "bench": "LIBRARY",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 3 — GROWTH
    # ═══════════════════════════════════════════════════════════════════

    "revenue_growth_yoy": {
        "label": "Revenue YoY Growth",
        "group": "Growth",
        "description": "Trailing 4Q revenue / prior 4Q revenue − 1",
        "source_columns": ["qi.revenue (8 quarters)"],
        "filing_lag": "60d quarterly",
        "v1_verdict_summary": "growth_recon: DROP all tiers (n=16)",
        "status_reason": "Kept despite v1 DROP — regimes change.",
        "producer": "growth_fundamentals",
        "pit_range": (-100, 1000),
        "bench": "LIBRARY",
    },
    "eps_growth_yoy": {
        "label": "EPS YoY Growth",
        "group": "Growth",
        "description": "Trailing 4Q EPS / prior 4Q EPS − 1",
        "source_columns": ["qi.eps (8 quarters)"],
        "filing_lag": "60d quarterly",
        "v1_verdict_summary": "growth_recon: DROP all tiers",
        "status_reason": "Kept despite v1 DROP. Tiny base EPS produces high noise — clipped to ±1000% range.",
        "producer": "growth_fundamentals",
        "pit_range": (-1000, 1000),
        "weight_key": "eps_growth",
        "replay_col": None,  # display-only screener column, no PIT twin
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 4 — MOMENTUM
    # ═══════════════════════════════════════════════════════════════════

    "mom_6m_adj": {
        "label": "Risk-Adj 6M Momentum",
        "group": "Momentum",
        "description": "6-month return / 6-month daily-return std, with 22-day skip window",
        "source_columns": ["stock_prices.close"],
        "filing_lag": "0d",
        "pit_column_v1": "mom_6m",
        "pit_column_v2": "mom_6m",
        "v1_verdict_summary": "DROP / DROP / WEAK (t=1.32 SMALL)",
        "status_reason": "v2 uses PIT-strict corporate-action-adjusted close: corporate_adjustments table holds 3,036 (sid, ex_date) factors covering SPLIT+BONUS+DIVIDEND; tools.reconstruct_pit.apply_pit_adjustments composes only events with ex_date <= snapshot_date. Apples-to-apples 12-date diagnostic: raw close 0.745 → PIT-adj 0.862 mean Pearson vs v1 archive (+0.117 lift). v1 is forward-adjusted via yfinance (mildly leaky); v2 is non-leaky and canonical going forward.",
        "producer": "momentum",
        "pit_range": (-100, 100),
        "bench": "LIBRARY",  # dropped from SIGNAL_WEIGHTS 2026-07-05 (ADR 0049): clean t=1.34 — sub-bar noise
        "weight_key": "momentum",
        "screener_col": "mom_6m",
        "family": "Momentum",
        "eligibility": {
            "description": "Stocks with ≥126 trading days of price history (~6mo for mom_6m / mom_12m)",
            "eligible_sql": """
                SELECT sid FROM stock_prices
                GROUP BY sid HAVING COUNT(*) >= 126
            """,
        },
    },
    "mom_12m_adj": {
        "label": "Risk-Adj 12M Momentum",
        "group": "Momentum",
        "description": "12-month return / 12-month daily-return std, with 22-day skip",
        "source_columns": ["stock_prices.close"],
        "filing_lag": "0d",
        "pit_column_v1": "mom_12m",
        "pit_column_v2": "mom_12m",
        "v1_verdict_summary": "WEAK / DROP / WEAK (t=−1.64 LARGE, 1.76 SMALL)",
        "status_reason": "Same PIT-strict adjustment as mom_6m_adj. 12-date apples-to-apples Pearson lift +0.116; pooled v1↔v2 Pearson 0.71 / Spearman 0.87 (essentially identical to forward-adjusted-splits-only — leakage in v1 is small in practice; correctness benefit is architectural).",
        "producer": "momentum",
        "pit_range": (-100, 100),
        "bench": "LIBRARY",  # dropped from SIGNAL_WEIGHTS 2026-07-05 (ADR 0049): clean t=1.34 — sub-bar noise
        "weight_key": "momentum",
        "tiers": ("SMALL",),  # the screener scores momentum on 12m in SMALL
        "screener_col": "mom_12m",
    },
    "macd_signal": {
        "label": "MACD Bullish Crossover",
        "group": "Momentum",
        "description": "12/26 EMA crossover state — binary signal from price",
        "source_columns": ["stock_prices.close (252d)"],
        "filing_lag": "0d",
        "pit_column_v2": "macd_bullish",
        "v1_verdict_summary": "(technical — used in v1 screener but not in C13b validation)",
        "producer": "macd",
        "pit_range": (0, 1),
        "bench": "PROPOSED",  # TODO amit: classify
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 5 — OWNERSHIP / INSIDER
    # ═══════════════════════════════════════════════════════════════════

    "promoter_qoq": {
        "label": "Promoter QoQ Change",
        "group": "Ownership",
        "description": "Quarter-over-quarter change in promoter holding %",
        "source_columns": ["shareholding.promoter_pct"],
        "filing_lag": "21d",
        "pit_column_v1": "promoter_qoq",
        "v1_verdict_summary": "DROP / DROP / KEEP (t=3.20 SMALL)",
        "status_reason": "Diagnostic 2026-05-04: median |v1-v2 diff|=0.000 across 1,896 overlap stocks; when both >0.05 abs, **sign-match=97.4%**. The 0.55 raw correlation was scatter-dominated (most stocks have 0 change, agree trivially); for ranking purposes the signal is directionally sound. Backtest reproduces v1's t=3.20 SMALL exactly (validated 2026-05-03).",
        "producer": "promoter",
        "pit_range": (-100, 100),
        "weight_key": "promoter",
        "replay_col": "promoter_signal",
        "family": "Ownership",
        "eligibility": {
            "description": "Stocks with ≥2 quarterly shareholding snapshots (promoter QoQ delta needs prior quarter)",
            "eligible_sql": """
                SELECT sid FROM shareholding
                GROUP BY sid HAVING COUNT(*) >= 2
            """,
        },
    },
    "promoter_trend_4q": {
        "label": "Promoter 1-Year Trend",
        "group": "Ownership",
        "description": "Latest promoter % minus value 5 quarters ago",
        "source_columns": ["shareholding.promoter_pct (5 quarters)"],
        "filing_lag": "21d",
        "v1_verdict_summary": "(35% of promoter composite, not separately validated)",
        "producer": "promoter_trend",
        "pit_range": (-100, 100),
        "bench": "PROPOSED",  # TODO amit: classify
    },
    "pledge_quality": {
        "label": "Pledge Quality",
        "group": "Ownership",
        "description": "1 − (promoter pledge %) — higher better",
        "source_columns": ["shareholding.pledge_pct"],
        "filing_lag": "21d",
        "pit_column_v1": "pledge_quality",
        "v1_verdict_summary": "DROP all tiers",
        "status_reason": "Now in both v1 archive and v2 recompute. Kept despite DROP — regimes change.",
        "producer": "pledge",
        "pit_range": (0, 1),
        "weight_key": "pledge_quality",
        # un-wired (no bench: still weighted in the dry-run variant schemes): t: S 0.56, below the 1.5 bar — promotion review 2026-10-03 (docs/studies/promotion-review-2026-10.md), corrected panel
        "family": "Ownership",
        "eligibility": {
            "description": "Stocks with a shareholding pattern that states the promoter pledge",
            "eligible_sql": """
                SELECT DISTINCT sid FROM shareholding WHERE pledge_pct IS NOT NULL
            """,
        },
    },
    "insider_signal": {
        "label": "Insider Trading Signal",
        "group": "Ownership",
        "description": "Promoter/KMP buy-vs-sell over trailing 90 days",
        "source_columns": ["insider_trades.{person_category, transaction_type, value_lakhs, trade_date}"],
        "filing_lag": "0d (NSE PIT discloses on transaction)",
        "pit_column_v2": "insider_score",  # PIT helper added 2026-05-24
        "external_table": "insider_signals",
        "v1_verdict_summary": "(not in C13b; new in v2)",
        "status_reason": "Lives in insider_signals table — 29 monthly snapshots. Join on (sid, snapshot_date).",
        "cadence": "weekly",
        "producer": "insider_signal",
        "pit_range": (-1, 1),
        "bench": "LIBRARY",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 6 — FORENSIC
    # ═══════════════════════════════════════════════════════════════════

    "m_score": {
        "label": "Beneish M-Score",
        "group": "Forensic",
        "description": "Earnings manipulation detector (6-factor reduced model)",
        "source_columns": ["qi.revenue", "bs.{receivables,current_assets,total_assets}", "screener.Depreciation"],
        "filing_lag": "75d annual + 60d quarterly",
        "v1_verdict_summary": "(not in C13b; new in v2)",
        "status_reason": "Computed forward-only (n=7 months, 13,922 rows in daily_snapshots_pit). Backtest n grows monthly with cron. Signal is correct; only the C13b-grade t-stat needs n≥18.",
        "producer": "forensic",
        "pit_range": (-20, 20),
        "bench": "PROPOSED",  # TODO amit: classify
        "family": "Forensic",
    },
    "z_score": {
        "label": "Altman Z'' (emerging market)",
        "group": "Forensic",
        "description": "Bankruptcy predictor, 4-factor emerging-market variant",
        "source_columns": ["bs.{current_assets,liabilities,retained_earnings,total_assets}", "cf.operating_cash_flow"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "(not in C13b; new in v2)",
        "status_reason": "Computed forward-only (n=7 months, 15,504 rows). Backtest n grows monthly. Signal is correct; only C13b-grade t-stat needs n≥18.",
        "producer": "forensic",
        "pit_range": (-50, 100),
        "bench": "PROPOSED",  # TODO amit: classify
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 7 — SMART MONEY
    # ═══════════════════════════════════════════════════════════════════

    "avg_delivery_pct_30d": {
        "label": "30-Day Avg Delivery %",
        "group": "Smart Money",
        "description": "Mean delivery percentage over trailing 30 days",
        "source_columns": ["stock_prices.delivery_pct"],
        "filing_lag": "0d",
        "pit_column_v1": "avg_delivery_pct_30d",
        "v1_verdict_summary": "DROP / DROP / WEAK (t=2.49 SMALL)",
        "status_reason": "Now in both archives.",
        "cadence": "weekly",
        "producer": "delivery",
        "pit_range": (0, 100),
        "weights": {"SMALL": 0.12},  # t: S 3.67; delivery LEVEL, 0.06 correlated with the anomaly — promotion review 2026-10-03 (docs/studies/promotion-review-2026-10.md), corrected panel
        "family": "Delivery",
        "eligibility": {
            "description": "Stocks with at least 20 delivery readings in the last 60 days",
            "eligible_sql": """
                SELECT sid FROM stock_prices WHERE delivery_pct IS NOT NULL AND date >= date((SELECT MAX(date) FROM stock_prices), '-60 day') GROUP BY sid HAVING COUNT(*) >= 20
            """,
        },
    },
    "smart_money_score": {
        "label": "Smart Money Composite",
        "group": "Smart Money",
        "description": "Composite of bulk-deal net-buy depth + delivery-% strength (signals.smart_money). Wired into SMALL screener weight; registered 2026-06-02 to close the never-backtested gap (HANDOFF 2026-06-02).",
        "source_columns": ["bulk_deals.*", "stock_prices.delivery_pct"],
        "filing_lag": "0d",
        "v1_verdict_summary": "(was unbacktested — PIT-thin: bulk_deals ~1mo depth → only 6 reconstructed anchors)",
        "status_reason": "PIT helper pit_smart_money exists; thin history (n≈6) — verdict preliminary.",
        "producer": "smart_money",
        "pit_range": (0, 100),
        "weight_key": "smart_money",
        "family": "Microstructure",
        "eligibility": {
            "description": "Stocks with bulk_deals or delivery activity in last 90d (smart-money signal aggregates both)",
            "eligible_sql": """
                SELECT sid FROM (
                    SELECT DISTINCT sid FROM bulk_deals WHERE deal_date >= date('now', '-90 days')
                    UNION
                    SELECT DISTINCT sid FROM stock_prices WHERE date >= date('now', '-90 days')
                )
            """,
        },
    },
    "delivery_anomaly_z": {
        "label": "Delivery % Anomaly (z-score)",
        "group": "Smart Money",
        "description": "Today's delivery % vs 90-day mean, normalized",
        "source_columns": ["stock_prices.delivery_pct (rolling 90d)"],
        "filing_lag": "0d",
        "v1_verdict_summary": "(component of v1 smart_money_score)",
        "cadence": "weekly",
        "producer": "delivery",
        "pit_range": (-5, 5),
        "weights": {"SMALL": 0.24},  # t: S 5.52, survives the multiple-testing haircut — promotion review 2026-10-03 (docs/studies/promotion-review-2026-10.md), corrected panel
        "family": "Microstructure",
        "eligibility": {
            "description": "Stocks with at least 30 delivery readings in the last 150 days",
            "eligible_sql": """
                SELECT sid FROM stock_prices
                WHERE delivery_pct IS NOT NULL
                  AND date >= date((SELECT MAX(date) FROM stock_prices), '-150 day')
                GROUP BY sid HAVING COUNT(*) >= 30
            """,
        },
    },
    "sector_momentum": {
        "label": "Sector Momentum (relative strength vs NIFTY)",
        "group": "Momentum",
        "description": "Stock inherits its GICS sector's medium-horizon (≈3m) "
                       "constituent cap-weighted return minus NIFTY 50, z-scored "
                       "across sectors. Classic sector-momentum anomaly.",
        "source_columns": ["stock_prices.close", "stocks.{sector,market_cap_cr}",
                           "macro_history.nifty50"],
        "filing_lag": "0d",
        "v1_verdict_summary": "(new — Plan 0006 Phase E, no v1 counterpart)",
        "status_reason": "Shipped 2026-05-31 (Plan 0006 Phase E). Backtest on 29 "
                         "monthly PIT periods: SMALL t=1.88 WEAK (IC +0.016), "
                         "MID t=0.33 DROP, LARGE t=-0.60 DROP. Stays on bench — "
                         "below the 2.0 screener-promotion gate; not wired to "
                         "SIGNAL_WEIGHTS. Also powers the /sectors S/M/L horizon "
                         "badges. Re-test as PIT panel deepens.",
        "producer": "sector_momentum",
        "pit_range": (-3, 3),
        "bench": "PROPOSED",  # TODO amit: classify
    },
    "sector_tilt": {
        "label": "Sector Tilt (6m basket momentum + macro ensemble)",
        "group": "Momentum",
        "description": "Stock inherits its GICS sector's ensemble = mean of "
                       "z(trailing-6m median constituent return) and z(latest "
                       "macro_sector_signals_pit.macro_score), z-scored across "
                       "the 11 sectors. Validated additive to stock momentum "
                       "(Fama-MacBeth t+3.34 at 3m horizon, ADR 0041).",
        "source_columns": ["stock_prices.close", "stocks.sector",
                           "macro_sector_signals_pit.macro_score"],
        "filing_lag": "0d (prices) / monthly (macro leg)",
        "v1_verdict_summary": "(new — ADR 0041, no v1 counterpart)",
        "status_reason": "Shipped 2026-06-05 (ADR 0041). Distinct from the benched "
                         "sector_momentum cousin (63d cap-wtd RS): this is the 6m "
                         "absolute median basket + orthogonal macro engine. Backtest "
                         "on 34 monthly PIT anchors: SMALL t=+3.18 KEEP (IC +0.023, "
                         "ICIR 0.545, CI [1.14,5.88]) → WIRED SIGNAL_WEIGHTS[SMALL]=0.10. "
                         "LARGE t=+0.92 / MID t=+0.64 DROP — beats the cousin in every "
                         "tier but clears only SMALL; not wired LARGE/MID.",
        "producer": "sector_tilt",
        "pit_range": (-3, 3),
        "weights": {"SMALL": 0.14},  # t: S 3.59 (L 0.54 dropped) — promotion review 2026-10-03 (docs/studies/promotion-review-2026-10.md), corrected panel
        "family": "Macro",
        "eligibility": {
            "description": "Every stock with a sector (the factor is one value per sector)",
            "eligible_sql": """
                SELECT sid FROM stocks WHERE sector IS NOT NULL
            """,
        },
    },
    "pcr_oi": {
        "label": "Put-Call Ratio (Open Interest)",
        "group": "Options/F&O",
        "description": "Nearest-expiry total put OI / total call OI for the F&O "
                       "underlying. High = put-heavy positioning (bearish, or "
                       "contrarian-bullish on excess fear). Sign decided by backtest.",
        "source_columns": ["fno_pcr_history.pcr_oi"],
        "filing_lag": "0d (EOD F&O bhavcopy)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 OI half, no v1 counterpart)",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2). Backtest on 22 "
                         "weekly PIT periods (NW3): best |t|=0.36 LARGE — DROP all "
                         "tiers. On the bench (FACTOR_LIBRARY). Re-test as the 6mo "
                         "fno_pcr_history window deepens past one regime.",
        "cadence": "weekly",
        "producer": "fno_oi",
        "pit_range": (0, 20),
        "bench": "LIBRARY",  # best |t|=0.36 LARGE
    },
    "pcr_volume": {
        "label": "Put-Call Ratio (Volume)",
        "group": "Options/F&O",
        "description": "Nearest-expiry total put volume / total call volume — the "
                       "same-day flow analogue of PCR(OI). Sign decided by backtest.",
        "source_columns": ["fno_pcr_history.pcr_volume"],
        "filing_lag": "0d (EOD F&O bhavcopy)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 OI half, no v1 counterpart)",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2). Backtest on 22 "
                         "weekly PIT periods (NW3): SMALL t=-1.69 WEAK (high put-vol "
                         "→ mild underperformance, sensible sign; CI straddles 0), "
                         "LARGE/MID DROP. Below 2.0 gate — on the bench "
                         "(FACTOR_LIBRARY). Re-test as window deepens.",
        "cadence": "weekly",
        "producer": "fno_oi",
        "pit_range": (0, 20),
        "bench": "LIBRARY",  # SMALL t=-1.69 WEAK (sensible bearish sign)
    },
    "max_pain_distance": {
        "label": "Max-Pain Distance",
        "group": "Options/F&O",
        "description": "(spot − max_pain_strike) / spot, where max-pain is the "
                       "argmin total-writer-payout strike on the nearest expiry. "
                       "Tests the 'price drifts toward max-pain into expiry' lore.",
        "source_columns": ["fno_pcr_history.max_pain_distance"],
        "filing_lag": "0d (EOD F&O bhavcopy)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 OI half, no v1 counterpart)",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2). Backtest on 22 "
                         "weekly PIT periods (NW3): MID t=-1.68 WEAK (spot above "
                         "max-pain → drifts back, sensible mean-reversion sign; CI "
                         "straddles 0), LARGE/SMALL DROP. Below 2.0 gate — on the "
                         "bench (FACTOR_LIBRARY). Re-test as window deepens.",
        "cadence": "weekly",
        "producer": "fno_oi",
        "pit_range": (-1, 1),
        "bench": "LIBRARY",  # MID t=-1.68 WEAK (mean-reversion to max-pain)
    },
    "oi_buildup_signal": {
        "label": "OI Buildup Regime",
        "group": "Options/F&O",
        "description": "Four-state score from the same-expiry day-over-day change "
                       "in total OI vs underlying price: long buildup +1 / short "
                       "covering +0.5 / long unwinding −0.5 / short buildup −1. "
                       "Δ taken only within one expiry series (roll-safe).",
        "source_columns": ["fno_pcr_history.{total_call_oi,total_put_oi,underlying_price,expiry_date}"],
        "filing_lag": "0d (EOD F&O bhavcopy)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 OI half, no v1 counterpart)",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2). Backtest on 22 "
                         "weekly PIT periods (NW3): best |t|=0.45 MID — DROP all "
                         "tiers (4-state Δ is noisy at weekly cadence). On the bench "
                         "(FACTOR_LIBRARY). Re-test as window deepens.",
        "cadence": "weekly",
        "producer": "fno_oi",
        "pit_range": (-1, 1),
        "bench": "LIBRARY",  # best |t|=0.45 MID
    },
    "iv_skew_25d": {
        "label": "IV Skew (25Δ put − call)",
        "group": "Options/F&O",
        "description": "iv(25-delta put) − iv(25-delta call) on the ~30d expiry, from "
                       "Black-76 inversion of fno_bhav settle prices. Positive = "
                       "downside protection bid up (fear). Sign decided by backtest.",
        "source_columns": ["fno_iv_history.iv_skew_25d"],
        "filing_lag": "0d (EOD F&O bhavcopy)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 IV half, no v1 counterpart)",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2 IV half, ADR 0035). "
                         "WIRED into SIGNAL_WEIGHTS[MID]=0.18 on 2026-05-31. Backtest "
                         "on the EXTENDED 48 weekly periods (~11mo, multi-regime): MID "
                         "t=+3.16 KEEP (IC +0.060, CI [2.13,7.15] strictly >0; held "
                         "from the 25-period t=4.61), LARGE t=1.37 / SMALL t=0.17 DROP "
                         "→ MID-only. Orthogonal to size/adtv/existing factors "
                         "(|ρ|<0.15) — adds genuinely new info. F&O-stock coverage.",
        "cadence": "weekly",
        "producer": "fno_iv",
        "pit_range": (-0.5, 0.5),
        "weights": {"LARGE": 0.25, "MID": 0.24},  # t: L 1.86 · M 4.06 — promotion review 2026-10-03 (docs/studies/promotion-review-2026-10.md), corrected panel
        "family": "Options",
        "eligibility": {
            "description": "Stocks with a listed option chain: an implied-volatility row within a week of the newest one",
            "eligible_sql": """
                SELECT DISTINCT sid FROM fno_iv_history
                WHERE sid IS NOT NULL
                  AND trade_date >= date((SELECT MAX(trade_date) FROM fno_iv_history), '-7 day')
            """,
        },
    },
    "iv_term_structure": {
        "label": "IV Term Structure (near − far)",
        "group": "Options/F&O",
        "description": "ATM IV(nearest ≥5d expiry) − ATM IV(next month). Positive = "
                       "inverted/backwardated curve (near-term stress). NOTE: thin "
                       "single-stock coverage (~20%) — next-month stock options are "
                       "illiquid; really an index-level signal.",
        "source_columns": ["fno_iv_history.iv_term_structure"],
        "filing_lag": "0d (EOD F&O bhavcopy)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 IV half, no v1 counterpart)",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2 IV half, ADR 0035). "
                         "Backtest (NW3): MID t=-1.80 WEAK (17 periods). SMALL 'KEEP' "
                         "t=-4.94 is a 7-period/23-stock SMALL-SAMPLE ARTIFACT (CI "
                         "[-32.7,-3.1]) — NOT trusted, NOT promoted. ~20% stock "
                         "coverage (far-month liquidity gap; index-level signal at "
                         "heart). Bench (FACTOR_LIBRARY).",
        "cadence": "weekly",
        "producer": "fno_iv",
        "pit_range": (-0.5, 0.5),
        "bench": "LIBRARY",  # MID t=-1.80 WEAK; SMALL KEEP is a thin-sample artifact
    },
    "iv_realised_spread": {
        "label": "IV − Realised Vol Spread",
        "group": "Options/F&O",
        "description": "ATM IV − 21d annualised realised vol — the variance risk "
                       "premium. Positive = options pricing more vol than has been "
                       "realised (rich). Sign decided by backtest.",
        "source_columns": ["fno_iv_history.atm_iv", "stock_prices.close (21d)"],
        "filing_lag": "0d (EOD F&O bhavcopy + 0d price)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 IV half, no v1 counterpart)",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2 IV half, ADR 0035). "
                         "Backtest 25 weekly periods (NW3): MID t=-1.95 WEAK (CI "
                         "[-5.94,-0.31] excludes 0; rich variance premium → MID "
                         "underperformance, sensible sign), LARGE/SMALL DROP. ~99% "
                         "coverage. Bench (FACTOR_LIBRARY).",
        "cadence": "weekly",
        "producer": "fno_iv",
        "pit_range": (-1.0, 1.0),
        "bench": "LIBRARY",  # MID t=-1.95 WEAK (CI excludes 0)
    },
    "iv_percentile_1y": {
        "label": "IV Percentile (trailing ≤1y)",
        "group": "Options/F&O",
        "description": "Percentile rank of today's ATM IV within its own trailing "
                       "≤252-day history. High = vol is expensive vs its own recent "
                       "range (mean-reversion / regime). Sign decided by backtest.",
        "source_columns": ["fno_iv_history.atm_iv (trailing series)"],
        "filing_lag": "0d (EOD F&O bhavcopy)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 IV half, no v1 counterpart)",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2 IV half, ADR 0035). "
                         "Backtest 25 weekly periods (NW3): best LARGE t=1.18 — DROP "
                         "all tiers (IV percentile is a regime/timing read, not a "
                         "cross-sectional stock-picker). fno_bhav backfilled to ~1yr "
                         "so the trailing-1y window is full. Bench (FACTOR_LIBRARY).",
        "cadence": "weekly",
        "producer": "fno_iv",
        "pit_range": (0, 1),
        "bench": "LIBRARY",  # best |t|=1.18 LARGE — DROP (regime signal)
    },
    "intraday_range_compression": {
        "label": "Intraday Range Compression (ATR5/ATR20)",
        "group": "Microstructure",
        "description": "5-day ATR / 20-day ATR. <1 = recent daily ranges tighter "
                       "than the longer run (volatility compression). Daily OHLC.",
        "source_columns": ["stock_prices.{high,low,close}"],
        "filing_lag": "0d",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.3, daily-derivable, no Kite)",
        "status_reason": "Shipped 2026-05-31 (§3.2.3 daily half). Backtest 39 monthly periods: best |t|=0.92 LARGE — DROP all tiers. Bench (FACTOR_LIBRARY).",
        "producer": "microstructure",
        "pit_range": (0, 5),
        "bench": "LIBRARY",  # best |t|=0.92 LARGE — DROP
    },
    "closing_strength_1m": {
        "label": "Closing Strength (1mo)",
        "group": "Microstructure",
        "description": "Mean (close−low)/(high−low) over ~21d — where in the daily "
                       "range the close lands. High = persistent late-day buying.",
        "source_columns": ["stock_prices.{high,low,close}"],
        "filing_lag": "0d",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.3, daily-derivable, no Kite)",
        "status_reason": "Shipped 2026-05-31 (§3.2.3 daily half). Backtest 39 monthly periods: best |t|=0.98 SMALL — DROP all tiers. Bench (FACTOR_LIBRARY).",
        "producer": "microstructure",
        "pit_range": (0, 1),
        "bench": "LIBRARY",  # best |t|=0.98 SMALL — DROP
    },
    "opening_gap_freq_1m": {
        "label": "Opening Gap Frequency (1mo)",
        "group": "Microstructure",
        "description": "Fraction of last ~21d with a >1% overnight gap "
                       "(|open/prev_close − 1|). News/event sensitivity proxy.",
        "source_columns": ["stock_prices.{open,close}"],
        "filing_lag": "0d",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.3, daily-derivable, no Kite)",
        "status_reason": "Shipped 2026-05-31 (§3.2.3 daily half). Backtest 39 monthly periods: MID t=1.31 weak hint, DROP all tiers. Bench (FACTOR_LIBRARY).",
        "producer": "microstructure",
        "pit_range": (0, 1),
        "bench": "LIBRARY",  # MID t=1.31 — DROP
    },
    "vwap_deviation_5d": {
        "label": "VWAP Deviation (5d, OHLC proxy)",
        "group": "Microstructure",
        "description": "Mean 5d (close − typical_price)/typical_price, TP=(H+L+C)/3 "
                       "(daily VWAP proxy — traded_value is ~17% NULL). Late-day strength.",
        "source_columns": ["stock_prices.{high,low,close}"],
        "filing_lag": "0d",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.3, daily-derivable proxy, no Kite)",
        "status_reason": "Shipped 2026-05-31 (§3.2.3 daily half). Backtest 39 monthly periods: best |t|=0.96 SMALL — DROP (OHLC typical-price proxy; true VWAP needs intraday). Bench (FACTOR_LIBRARY).",
        "producer": "microstructure",
        "pit_range": (-0.5, 0.5),
        "bench": "LIBRARY",  # best |t|=0.96 SMALL — DROP
    },
    "bidask_spread_proxy": {
        "label": "Bid-Ask Spread (Corwin-Schultz)",
        "group": "Microstructure",
        "description": "Corwin-Schultz 2-day high/low spread estimator, ~20d mean. "
                       "Illiquidity proxy (higher = wider effective spread). Daily H/L.",
        "source_columns": ["stock_prices.{high,low}"],
        "filing_lag": "0d",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.3, daily-derivable proxy, no Kite)",
        "status_reason": "Shipped 2026-05-31 (§3.2.3 daily half). Backtest 39 monthly periods: MID t=1.30 weak hint, DROP all tiers. Bench (FACTOR_LIBRARY).",
        "producer": "microstructure",
        "pit_range": (0, 1),
        "bench": "LIBRARY",  # MID t=1.30 — DROP
    },
    "kyle_lambda": {
        "label": "Kyle Lambda (Amihud illiquidity)",
        "group": "Microstructure",
        "description": "Amihud: mean |daily return| / turnover(₹cr) over ~21d. "
                       "Price impact per unit volume; higher = more illiquid.",
        "source_columns": ["stock_prices.{close,volume}"],
        "filing_lag": "0d",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.3, daily-derivable proxy, no Kite)",
        "status_reason": "Shipped 2026-05-31 (§3.2.3 daily half). Backtest 39 monthly periods: LARGE t=+4.24 KEEP + MID t=+4.14 KEEP (both CI strictly >0), SMALL t=+1.65 WEAK — the Amihud illiquidity premium (illiquid -> higher fwd returns). Strong + economically grounded. PROMOTION CANDIDATE but trading-cost-coupled (you pay the spread youre compensated for) + likely colinear with size/adtv -> needs factor_correlation + cost-aware review before wiring.",
        "producer": "microstructure",
        "pit_range": (0, 1),
        "bench": "LIBRARY",  # LARGE t=+4.24 + MID t=+4.14 KEEP — Amihud illiquidity premium; promotion candidate (cost-coupled)
    },
    "earnings_surprise_std": {
        "label": "Earnings Surprise (SUE)",
        "group": "Event/PEAD",
        "description": "Standardised unexpected earnings — seasonal random walk: "
                       "(EPS_t − EPS_{t-4}) / stdev(trailing YoY EPS changes). The "
                       "classic PEAD signal; no analyst-consensus dependency.",
        "source_columns": ["quarterly_income.eps"],
        "filing_lag": "~45d announcement approx (period_end + 45d)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.5, time-series SUE)",
        "status_reason": "Shipped 2026-05-31 (§3.2.5). Backtest 13-16 monthly periods: all tiers DROP (best LARGE t=0.52). Time-series seasonal-RW SUE proxy too noisy without true earnings-announcement dates + analyst consensus (quarterly_income has neither) — PEAD did not replicate via this proxy. Bench (FACTOR_LIBRARY).",
        "producer": "pead",
        "pit_range": (-5, 5),
        "bench": "LIBRARY",  # DROP — SUE proxy too noisy w/o announce dates + consensus
    },
    "pead_drift_60d": {
        "label": "PEAD Drift (post-earnings, 60d)",
        "group": "Event/PEAD",
        "description": "Abnormal return (stock − NIFTY) since the most recent "
                       "earnings announcement (≈period_end+45d), if within a ~60-day "
                       "post-announcement window; else NULL. Drift-in-progress.",
        "source_columns": ["quarterly_income.end_date", "stock_prices.close", "macro_history.nifty50"],
        "filing_lag": "~45d announcement approx",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.5)",
        "status_reason": "Shipped 2026-05-31 (§3.2.5). Backtest 25 monthly periods: SMALL t=-1.54 WEAK (NEGATIVE — post-earnings drift reverses in small caps, opposite of classic PEAD; likely illiquid-reversal noise), LARGE/MID DROP. Active only post-earnings (~600-800/date). Bench.",
        "producer": "pead",
        "pit_range": (-1, 1),
        "bench": "LIBRARY",  # SMALL t=-1.54 WEAK (reversal sign)
    },
    "corporate_action_density": {
        "label": "Corporate Action Density (1y)",
        "group": "Event/PEAD",
        "description": "Count of corporate actions (dividends/splits/bonus/etc.) in "
                       "the trailing 1 year. Higher = more capital-action activity.",
        "source_columns": ["corporate_actions.ex_date"],
        "filing_lag": "0d (ex_date anchor)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.5)",
        "status_reason": "Shipped 2026-05-31 (§3.2.5). Backtest 20-21 monthly periods: LARGE t=-3.67 KEEP (CI [-5.99,-2.06]; more corp actions -> lower fwd returns), MID/SMALL DROP. NOT promoted — mechanism unclear (likely a maturity/value proxy), corporate_actions only 2yr deep (single regime); verify non-colinear with value factors before trusting. Bench (FACTOR_LIBRARY).",
        "producer": "pead",
        "pit_range": (0, 20),
        "bench": "LIBRARY",  # LARGE t=-3.67 KEEP but unclear mechanism (maturity/value proxy?) — NOT promoted
    },
    "buyback_announcement_30d": {
        "label": "Buyback Announcement (30d)",
        "group": "Event/PEAD",
        "description": "1 if a buyback corporate action appears in the last 30 days "
                       "(subject ~ 'buy back'), else 0. Sparse binary event flag.",
        "source_columns": ["corporate_actions.{ex_date,subject}"],
        "filing_lag": "0d (ex_date anchor)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.5)",
        "status_reason": "Shipped 2026-05-31 (§3.2.5). Backtest: DROP all tiers (LARGE/MID only n=2 periods, SMALL t=-0.65) — too sparse (~9 buybacks/date) for power. Bench.",
        "producer": "pead",
        "pit_range": (0, 1),
        "bench": "LIBRARY",  # DROP — too sparse
    },
    "announcement_car": {
        "label": "Announcement-Window CAR (PEAD proxy)",
        "group": "Event/PEAD",
        "description": "Market-adjusted cumulative abnormal return in the [-1,+1] trading-day "
                       "window around the latest BSE 'Result' announcement (buy at the last "
                       "pre-print close, measure to +1, minus NIFTY-50 over the same dates). "
                       "The market's own immediate reaction = a real-time earnings-surprise proxy "
                       "needing no analyst consensus (which we lack PIT); PEAD hypothesis: a big "
                       "positive CAR keeps drifting → expected IC POSITIVE. Staleness gate 90d "
                       "(one reporting quarter); NULL when no qualifying recent print.",
        "source_columns": ["bse_announcements.{sid,dt_tm,category=Result}", "stock_prices.close (adj)", "macro_history.nifty50"],
        "filing_lag": "0d (dt_tm event-time anchor; CAR window must close ≤ eval)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.5, PEAD-via-CAR; audit Factor-F3 sanctioned next candidate)",
        "status_reason": "Shipped + backtested 2026-07-05 (PEAD-via-CAR, the sanctioned next step after "
                         "the SUE/pead_drift PEAD failed — memory pead_needs_announce_dates). 78 monthly "
                         "anchors on the CLEAN post-ADR-0047 panel (fwd_return anchor-proximity guard). "
                         "SMALL t=+3.74 KEEP (IC +0.0258, ICIR 0.424, CI [1.99,5.74]); LARGE t=+2.23 WEAK "
                         "(IC +0.0308, ICIR 0.253, CI [0.22,4.36]); MID t=+1.20 DROP (IC +0.0141, "
                         "CI [-0.73,3.20]). ALL THREE POSITIVE — the hypothesised sign (a big announcement "
                         "reaction keeps drifting). This is the FIRST honest thing the LARGE tier has gotten "
                         "from the rebuild: LARGE +2.23 tops the current best wired LARGE factor (consensus "
                         "+1.62 on the clean panel). Multiple-testing: SMALL fails BY-FDR (p_BY 0.153, "
                         "Bonferroni bar |t|≥4.09 not cleared) but sits in the SAME p_BY band as the already-"
                         "WIRED sector_tilt SMALL (3.69) and consensus SMALL (3.74) — a genuine promotion "
                         "candidate, not robust-core. NOT wired (human weight review). Benched in FACTOR_LIBRARY. "
                         "NOTE: a live daily producer is NOT yet built — wiring requires one (see status).",
        "producer": "announcement_car",
        "pit_range": (-1, 1),
        "weights": {"LARGE": 0.35, "MID": 0.10, "SMALL": 0.22},  # t: L 2.65 · M 1.88 · S 5.51 — promotion review 2026-10-03 (docs/studies/promotion-review-2026-10.md), corrected panel
        "family": "Event",
        "eligibility": {
            "description": "Stocks with a BSE Result announcement in the trailing ~95d (the CAR staleness gate is 90d + window-close; names without a fresh print have no reading and must not be coverage-penalised for it)",
            "eligible_sql": """
                SELECT DISTINCT sid FROM bse_announcements
                WHERE """ + RESULT_FILING_SQL + """ AND sid IS NOT NULL AND dt_tm IS NOT NULL
                  AND date(dt_tm) >= date('now', '-95 day') AND date(dt_tm) <= date('now')
            """,
        },
    },
    "governance_resignation": {
        "label": "Governance Resignation Intensity (1y)",
        "group": "Event/Forensic",
        "description": "Weighted trailing-365d density of senior-officer + auditor "
                       "resignation/cessation events from the BSE announcement stream "
                       "(auditor 3.0 / CFO 2.5 / MD-CEO-Chairman 2.0 / director-CS-cessation 1.0). "
                       "Higher = more governance instability. Dual-use forensic red-flag.",
        "source_columns": ["bse_announcements.{sid,subcategory,dt_tm}"],
        "filing_lag": "0d (dt_tm event-time anchor)",
        "v1_verdict_summary": "(new — ADR 0042 BSE event stream)",
        "status_reason": "Shipped 2026-06-13 (ADR 0042). Backtest 46 monthly periods (2018+ BSE depth): "
                         "MID t=-3.82 KEEP (IC -0.051, ICIR -0.56, CI [-6.57,-1.71]) — NEGATIVE sign as "
                         "hypothesised (senior/auditor resignations -> lower fwd returns); LARGE t=-1.61 / "
                         "SMALL t=-1.65 WEAK (same negative direction, not significant). Clear mechanism "
                         "(governance instability), 8yr deep — stronger than corporate_action_density. "
                         "Candidate for deliberate weight review (negative-weight penalty in MID) pending "
                         "orthogonality vs piotroski/forensic/pledge_quality. Dual-use forensic red-flag. NOT yet wired.",
        "producer": "governance",
        "pit_range": (0, 12),
        "weight_key": "governance_resignation",
        "bench": "LIBRARY",  # un-wired: t: M −0.30 (S −2.33: a candidate there), below the 1.5 bar — promotion review 2026-10-03 (docs/studies/promotion-review-2026-10.md), corrected panel
        "family": "Governance",
        "eligibility": {
            "description": "Every stock: no resignation filing in the window is a real reading (0), not a gap",
            "eligible_sql": """
                SELECT sid FROM stocks
            """,
        },
    },
    "earnings_call_tone_qoq": {
        "label": "Earnings-Call Tone QoQ",
        "group": "NLP/Transcript",
        "description": "Δ net Loughran-McDonald tone (positive−negative word density) of the "
                       "latest earnings-call transcript vs the prior call. Tone momentum; "
                       "look-ahead-safe on the real BSE filing date (available_date, #1c).",
        "source_columns": ["nlp_scores.{net_tone,available_date,doc_date}"],
        "filing_lag": "0d (available_date = real BSE filing dt_tm)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.4)",
        "status_reason": "Shipped 2026-06-14 (§3.2.4). Backtest 46 monthly periods: DROP all tiers "
                         "(LARGE t=0.88 / MID -0.17 / SMALL 0.62) — tone-momentum didn't replicate. Bench (FACTOR_LIBRARY).",
        "producer": "nlp",
        "pit_range": (-20, 20),
        "bench": "LIBRARY",  # best |t|=0.88 LARGE — DROP all tiers (tone-momentum didn't replicate)
    },
    "forward_looking_intensity": {
        "label": "Forward-Looking Intensity",
        "group": "NLP/Transcript",
        "description": "Forward-looking phrases per 1,000 words in the latest earnings-call "
                       "transcript (guidance/outlook/expansion language). Look-ahead-safe (#1c).",
        "source_columns": ["nlp_scores.{forward_looking_intensity,available_date,doc_date}"],
        "filing_lag": "0d (available_date = real BSE filing dt_tm)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.4)",
        "status_reason": "Shipped 2026-06-14 (§3.2.4). Backtest 46 monthly periods: LARGE t=+1.67 / SMALL t=+1.94 "
                         "WEAK (positive — more guidance language → better fwd returns, sensible; CIs straddle 0), "
                         "MID t=0.99 DROP. Sub-2.5, not wired. Bench (FACTOR_LIBRARY); re-test as panel deepens.",
        "producer": "nlp",
        "pit_range": (0, 200),
        "weights": {"LARGE": 0.20},  # t: L 2.18 — promotion review 2026-10-03 (docs/studies/promotion-review-2026-10.md), corrected panel
        "family": "Transcript",
        "eligibility": {
            "description": "Stocks with a scored earnings-call transcript",
            "eligible_sql": """
                SELECT DISTINCT sid FROM nlp_scores WHERE doc_type = 'transcript' AND forward_looking_intensity IS NOT NULL
            """,
        },
    },
    "uncertainty_word_density": {
        "label": "Uncertainty Word Density",
        "group": "NLP/Transcript",
        "description": "Loughran-McDonald uncertainty-word hits per 100 words in the latest "
                       "earnings-call transcript (hedged/evasive tone). Look-ahead-safe (#1c).",
        "source_columns": ["nlp_scores.{uncertainty_density,available_date,doc_date}"],
        "filing_lag": "0d (available_date = real BSE filing dt_tm)",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.4)",
        "status_reason": "Shipped 2026-06-14 (§3.2.4). Backtest 46 monthly periods: LARGE t=+2.90 KEEP "
                         "(IC +0.049, ICIR 0.43, CI [1.00,5.24]) BUT the sign is CONTRARIAN — more hedging/"
                         "uncertainty → HIGHER fwd returns, backwards from LM-uncertainty theory; and LARGE-only "
                         "(the tier walk-forward flags ~zero OOS skill), one 2022-26 regime. MID/SMALL DROP. "
                         "NOT wired — PARKED pending sign/regime verification (FACTOR_LIBRARY), like ccc/nwc_to_revenue.",
        "producer": "nlp",
        "pit_range": (0, 50),
        "bench": "LIBRARY",  # LARGE t=+2.90 KEEP but CONTRARIAN sign (more hedging→higher returns, backwards from LM-uncertainty theory) + LARGE-only (OOS-weak tier) — PARKED for sign/regime verification, NOT wired
    },
    "bulk_deal_signal": {
        "label": "Bulk/Block Deal Activity",
        "group": "Smart Money",
        "description": "Net bulk-deal value over trailing 30 days, normalized by avg close",
        "source_columns": ["bulk_deals.{quantity, price, buy_sell, deal_date}"],
        "filing_lag": "0d",
        "v1_verdict_summary": "(60% weight in v1 smart_money_score)",
        "status_reason": "Backfilled to 12 months via nselib (2025-06 → present, 13,652 deals). Was BLOCKED → PARTIAL → READY after discovering nselib.capital_market.bulk_deal_data with date-range support.",
        "cadence": "weekly",
        "producer": "bulk_deal",
        "pit_range": (-100, 100),
        "bench": "PROPOSED",  # TODO amit: classify
    },
    "short_selling_signal": {
        "label": "Short-Selling Activity",
        "group": "Smart Money",
        "description": "Reported short-sold quantity over trailing 30 days, normalized by 30d avg volume",
        "source_columns": ["short_selling_data.{quantity, short_date}"],
        "filing_lag": "0d",
        "v1_verdict_summary": "(NEW signal class — not in v1 roster)",
        "status_reason": "PIT signal compute function shipped (pit_short_selling_signal). 432-714 stocks/snapshot populated across 7 dates from 2025-11. Coverage limited to F&O-eligible names (only those have reported short-selling). Backtest n=5 monthly periods so far; will mature with cron.",
        "cadence": "weekly",
        "producer": "short_selling",
        "pit_range": (0, 10),
        "bench": "LIBRARY",
    },
    "fii_dii_cash_net": {
        "label": "FII/DII Cash Segment Net Flow",
        "group": "Macro",
        "description": "Daily net institutional buying in cash market (FII + DII separately)",
        "source_tables": ["fii_dii_cash_flow"],
        "source_columns": ["fii_dii_cash_flow.{net_value_cr, category}"],
        "filing_lag": "0d (next-day publication)",
        "pit_column_v2": None,
        "v1_verdict_summary": "(NEW signal class — sector-agnostic macro tilt)",
        "status_reason": "Macro-level signal (one row per date per category, not per-stock). Consumed by regime/macro overlay, not daily_snapshots_pit. Daily cron at 14:00 UTC accumulating from 2026-05-03 forward. ~22 trading days of history; will be backtest-grade by 2026-08.",
        "cadence": "weekly",
        "bench": "PROPOSED",
    },
    "fii_dii_fno_positioning": {
        "label": "FII/DII F&O Positioning",
        "group": "Macro",
        "description": "Participant-wise (Client/DII/FII/Pro) Future + Option long/short positioning",
        "source_tables": ["fii_dii_positioning"],
        "source_columns": ["fii_dii_positioning.{future_*, option_*, total_*, client_type}"],
        "filing_lag": "0d (next-day publication)",
        "pit_column_v2": None,
        "v1_verdict_summary": "(NEW signal class)",
        "status_reason": "Macro-level signal (5 rows/day across Client/DII/FII/Pro/TOTAL). Consumed by regime overlay. 220 rows backfilled (Feb-Apr 2026); accumulating forward via daily cron.",
        "cadence": "weekly",
        "bench": "PROPOSED",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 8 — CONSENSUS / FORECAST
    # ═══════════════════════════════════════════════════════════════════

    "pt_upside": {
        "label": "Price Target Upside",
        "group": "Consensus",
        "description": "(Latest analyst PT − current price) / current price",
        "source_columns": ["forecast_history.value WHERE metric='price'", "stock_prices.close"],
        "filing_lag": "0d (use forecast.date for knowability)",
        "v1_verdict_summary": "(component of v1 consensus signal)",
        "status_reason": "Sourced from forecast_history (annual PT snapshots back to 2015), NOT from analyst_consensus (which is snapshot-only).",
        "producer": "pt_upside",
        "pit_range": (-1, 5),
        "bench": "BLOCKED",  # pulled 2026-07-05 (ADR 0045): look-ahead artifact; honest PT history accrues in analyst_consensus_snapshots
        "weight_key": "pt_upside",
        "replay_col": None,  # display-only screener column, no PIT twin
        "family": "Analyst",
    },
    "pt_revision_yoy": {
        "label": "PT Revision YoY",
        "group": "Consensus",
        "description": "(Latest PT / prior-year PT) − 1, from forecast_history.price snapshots",
        "source_columns": ["forecast_history.value WHERE metric='price'"],
        "filing_lag": "0d (use forecast.date as knowability)",
        "v1_verdict_summary": "(component of v1 consensus signal)",
        "status": "DROPPED",
        "status_reason": "Data contaminated (2026-05-23). forecast_history.metric='price' is current-close masquerading as PT, so YoY computation = 1-year price return, not PT revision. Both production (signals/consensus.py) and PIT (tools/reconstruct_pit.py) now hardcode this to NULL. Rebuild planned from analyst_consensus_snapshots monthly history once ≥12mo accumulate (2027-05).",
        "producer": "consensus",
        "pit_range": (-100, 500),
        "bench": "PROPOSED",  # TODO amit: classify
    },
    "eps_revision_yoy": {
        "label": "Fiscal-year EPS growth (reported)",
        "group": "Consensus",
        "description": "Change in REPORTED fiscal-year EPS on the year before, over |base|, winsorised to the range. "
                       "forecast_history eps rows are dated at fiscal year-end and hold the reported figure "
                       "(audit 2026-10): this is not an analyst revision",
        "source_columns": ["forecast_history.{value, change} WHERE metric='eps'"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "(component of v1 consensus signal)",
        "status_reason": "Pattern 6. Small-base-EPS stocks produce noise; combined signal mitigates.",
        "producer": "consensus",
        "pit_range": (-300, 500),   # plan 0015: same quantity as consensus_signal_combined → ONE range
        "bench": "PROPOSED",
        "weight_key": "eps_revision_yoy",
    },
    "consensus_signal_combined": {
        "label": "Consensus (PT + EPS revision)",
        "group": "Consensus",
        "description": "v1's headline consensus signal — was mean of pt_revision_yoy + eps_revision_yoy; now eps_revision_yoy only after pt source contaminated 2026-05-23",
        "source_columns": ["forecast_history.{value} WHERE metric='eps'"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "KEEP / WEAK / WEAK (t=3.52 LARGE — proxy validation in v1, included pt component)",
        "status": "DEGRADED",
        "status_reason": "Originally combined pt_revision_yoy + eps_revision_yoy; pt component dropped 2026-05-23 due to data contamination. Now eps_revision_yoy only — t-stat will differ from v1's 3.52 (which had the pt boost). Re-backtest before relying. Restored when pt source rebuilt from analyst_consensus_snapshots (2027-05+).",
        "producer": "consensus",
        "pit_range": (-300, 500),
        # weights set 2026-07-05 on t: L 1.62 · S 3.74, measured WITHOUT the filing lag. With it
        # (audit 2026-10): L 1.05 · S 2.98. LARGE is below the 1.5 bar → promotion review.
        "weights": {"MID": 0.16},  # t: M 2.31 (L 0.11 and S 1.39 dropped) — promotion review 2026-10-03 (docs/studies/promotion-review-2026-10.md), corrected panel
        "weight_key": "consensus",
        # Plan 0015 D1 (2026-09-27): the `consensus` weight now scores the quantity its
        # evidence was measured on — EPS revision (the screener's inline eps_revision_yoy,
        # = this PIT column). It used to score consensus_signals.consensus_signal (a PT /
        # growth tier blend) that no backtest had validated.
        "screener_col": "eps_revision_yoy",
        "family": "Analyst",
        "eligibility": {
            "description": "Stocks with Tickertape forward-EPS history (forecast_history metric='eps')",
            "eligible_sql": """
                SELECT DISTINCT sid FROM forecast_history
                WHERE metric = 'eps' AND value IS NOT NULL
            """,
        },
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 9 — SENTIMENT
    # ═══════════════════════════════════════════════════════════════════

    "sentiment_7d": {
        "label": "News Sentiment (VADER 7d)",
        "group": "Sentiment",
        "description": "Rolling 7-day mean VADER sentiment across articles tagged for the stock",
        "source_columns": ["news_articles.{title, summary, published_at}", "news_article_stocks.sid"],
        "filing_lag": "0d",
        "v1_verdict_summary": "(used as adjustment in v1 screener, not in C13b)",
        "status_reason": "PIT helper added 2026-05-24 — VADER on PIT-filtered article text. Output empty for eval dates before news_articles begins (2024-04-23).",
        "cadence": "weekly",
        "producer": "sentiment_7d",
        "pit_range": (-1, 1),
        "bench": "PROPOSED",  # TODO amit: classify
    },
    "news_volume": {
        "label": "News Article Volume (7d)",
        "group": "Sentiment",
        "description": "Count of articles in trailing 7 days — attention proxy",
        "source_columns": ["news_article_stocks.sid (count)"],
        "filing_lag": "0d",
        "pit_column_v2": "news_volume_7d",
        "v1_verdict_summary": "(diagnostic)",
        "status_reason": "v2 column populated from news_articles ⟕ news_article_stocks. 0 rows for snapshots before news data starts (2024-04 single-day, then continuous from 2026-03). 10-118 stocks/date for 2026-03+. Forward-only — sentiment analysis (sentiment_7d) blocked on FinBERT setup, see plan 0002 Phase A4.",
        "cadence": "weekly",
        "producer": "news_volume",
        "pit_range": (0, 100),
        "bench": "PROPOSED",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 10 — SECTOR OVERLAYS (regulatory + macro — sector-level, not stock-level)
    # ═══════════════════════════════════════════════════════════════════

    "regulatory_sector_signal": {
        "label": "Regulatory Sector Tilt",
        "group": "Regulatory",
        "description": "Per-sector aggregate of AI-classified regulatory events with 90-day half-life decay",
        "source_tables": ["regulatory_events", "regulatory_signals"],
        "source_columns": ["regulatory_events.published_at", "regulatory_signals.{direction, magnitude, confidence}"],
        "filing_lag": "0d",
        "pit_column_v2": "macro_sector_signals_pit.regulatory_score",
        "v1_verdict_summary": "(post-v1; Plan 0001)",
        "status_reason": "Sector-level (not stock-level) — written to macro_sector_signals_pit. 11 sectors × 7 dates. Coverage limited by classified subset (5,687 of 16,523 events) — older dates have fewer events surviving the published_at filter.",
        "cadence": "sector_portfolio",
        "producer": "sector_overlays",
        "pit_range": (-10, 10),
        "bench": "PROPOSED",
    },
    "macro_sector_signal": {
        "label": "Macro Sector Tilt",
        "group": "Macro",
        "description": "Per-sector aggregate of macro indicator changes (latest vs 90d-prior, weighted by direction)",
        "source_tables": ["macro_history", "macro_indicator_meta", "macro_sector_map"],
        "source_columns": ["macro_history.{value, date}", "macro_sector_map.{sector, direction, weight}"],
        "filing_lag": "varies (1w to 8w by indicator)",
        "pit_column_v2": "macro_sector_signals_pit.macro_score",
        "v1_verdict_summary": "(post-v1; Plan 0002)",
        "status_reason": "Sector-level — written to macro_sector_signals_pit. 11 sectors × 7 dates. Uses 30-row macro_sector_map for indicator→sector weighting.",
        "cadence": "sector_portfolio",
        "producer": "sector_overlays",
        "pit_range": (-10, 10),
        "bench": "PROPOSED",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 11 — TRACK 3 FACTOR LIBRARY
    # ═══════════════════════════════════════════════════════════════════
    # All sourced from fundamentals_screener (Screener Premium scrape).
    # Filing lag 75d annual. Validated tier = |t|≥1.5 on some cap-tier in
    # the most recent backtest; library tier = below that bar but kept
    # computed for re-test as PIT history extends. The FACTOR_LIBRARY list
    # below carries the library-tier signal ids.

    "roic": {
        "label": "Return on Invested Capital",
        "group": "Track 3 — Library",
        "description": "NOPAT / Invested Capital, 3-yr median. NOPAT = (PBT + Interest) × (1 − Tax/PBT)",
        "source_columns": ["{PBT, Interest, Tax, Equity Share Capital, Reserves, Borrowings}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=0.75 LARGE)",
        "status_reason": "Library tier — sub-|t|=1.5 on every tier in the 6-period backtest. Kept computed for re-test as PIT history extends.",
        "producer": "roic",
        "pit_range": (-2, 5),
        "bench": "LIBRARY",  # best |t|=0.75 LARGE
        "family": "Quality",
    },
    "roiic": {
        "label": "Return on Incremental Invested Capital",
        "group": "Track 3 — Library",
        "description": "(NOPAT_t − NOPAT_{t-5}) / (IC_t − IC_{t-5}). Marginal-ROIC over trailing 5y; sister of ROIC. ΔIC ≥ ₹50 cr filter, capped ±5.",
        "source_columns": ["{PBT, Tax, Interest, Equity Share Capital, Reserves, Borrowings} (annual, 6 yrs)"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=0.91 MID, intuitive sign)",
        "status_reason": "Library tier — sub-|t|=1.5 in the 6-period backtest but signs are intuitive (positive marginal ROIC → positive return). Retest as PIT extends.",
        "producer": "roiic",
        "pit_range": (-5, 5),
        "bench": "LIBRARY",  # best |t|=0.91 MID, intuitive sign
    },
    "gross_profitability": {
        "label": "Gross Profitability (Novy-Marx)",
        "group": "Track 3 — Library",
        "description": "(Sales − COGS) / Total Assets, 3y median. COGS = Raw Material + Change in Inventory + Power & Fuel + Other Mfr. Exp. Anchor quality factor of the multibagger funnel.",
        "source_columns": ["{Sales, Raw Material Cost, Change in Inventory, Power and Fuel, Other Mfr. Exp, Total} (annual)"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — not yet backtested (built 2026-06-03 for multibagger funnel)",
        "status_reason": "Multibagger funnel anchor (docs/reference/multibagger-research.md #1). Computed; awaiting first ic_decay/promotion_gate read.",
        "producer": "gross_profitability",
        "pit_range": (-1, 2),
        "bench": "LIBRARY",  # Novy-Marx anchor (multibagger funnel). First backtest 2026-07-05 (audit gap #5): SMALL t=-3.91 KEEP, MID t=-2.18 WEAK, LARGE t=-1.32 DROP — all NEGATIVE sign (opposite of Novy-Marx). Contrarian-sign KEEP, not auto-promotion-eligible — parked pending sign/regime check.
    },
    "fcf_yield": {
        "label": "Free Cash Flow Yield",
        "group": "Track 3 — Library",
        "description": "3-yr median FCF / PIT market_cap. FCF = OCF − (max(Δ(Net Block + CWIP), 0) + Depreciation). PIT market cap uses close × No. of Equity Shares.",
        "source_columns": ["{OCF, Net Block, CWIP, Depreciation, No. of Equity Shares}", "stock_prices.close (PIT)"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.08 SMALL)",
        "status_reason": "Library tier — sub-|t|=1.5 on every tier in the 6-period backtest. Kept computed for re-test as PIT history extends.",
        "producer": "fcf_yield",
        "pit_range": (-2, 2),
        "bench": "LIBRARY",  # best |t|=1.08 SMALL
        "family": "Value",
    },
    "ccc": {
        "label": "Cash Conversion Cycle",
        "group": "Track 3 — Library",
        "description": "DSO + DIO − DPO, 3-yr median. Sales used as denominator (no clean COGS line in Screener).",
        "source_columns": ["{Sales, Receivables, Inventory, Trade Payables}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — LARGE WEAK (t=+1.87, n=5, contrarian sign), MID/SMALL DROP",
        "status_reason": "PARKED — passes |t|≥1.5 bar on LARGE but with contrarian sign (higher CCC predicts higher return). Likely 5-month regime artifact (small-cap rotation period); awaiting more periods before promoting to scoring weights.",
        "producer": "cash_conversion_cycle",
        "pit_range": (-365, 730),
        "bench": "LIBRARY",  # contrarian sign on LARGE (t=+1.87)
    },
    "margin_slope": {
        "label": "Operating Margin Trend (5y slope)",
        "group": "Track 3 — Library",
        "description": "OLS slope of last 5y EBIT/Sales in percentage-points/year. EBIT = PBT + Interest.",
        "source_columns": ["{Sales, PBT, Interest}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.30 MID)",
        "status_reason": "Library tier — signs negative across LARGE/MID, suggesting declining-margin stocks outperformed in the 5-period window. Kept computed for re-test as PIT extends.",
        "producer": "operating_margin_trend",
        "pit_range": (-50, 50),
        "bench": "LIBRARY",
    },
    "wc_intensity": {
        "label": "Working Capital Intensity",
        "group": "Track 3 — Library",
        "description": "(Receivables + Inventory − Trade Payables) / Sales, 3-yr median. Sibling of CCC in ratio form.",
        "source_columns": ["{Sales, Receivables, Inventory, Trade Payables}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.48 LARGE)",
        "status_reason": "Library tier — borderline (t=1.48 just under bar); same regime pattern as CCC. Kept computed.",
        "producer": "working_capital_intensity",
        "pit_range": (-2, 5),
        "bench": "LIBRARY",
    },
    "dso_change_yoy": {
        "label": "DSO YoY Change",
        "group": "Track 3 — Library",
        "description": "Receivables/(Sales/365) − prior year. Rising DSO = receivables outpacing sales (forensic yellow flag). Days.",
        "source_columns": ["{Sales, Receivables}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — LARGE KEEP (t=-2.81), MID WEAK (t=-1.71), SMALL DROP (t=+1.49)",
        "status_reason": "PARKED — strongest factor in 2026-05 forensic batch. Intuitive sign on LARGE+MID (higher Δ DSO → lower return). Promote candidate after one more month of fwd_return matures.",
        "producer": "dso_change_yoy",
        "pit_range": (-365, 365),
        "bench": "LIBRARY",  # KEEP LARGE (t=-2.81) — strongest candidate, intuitive sign
    },
    "dio_change_yoy": {
        "label": "DIO YoY Change",
        "group": "Track 3 — Library",
        "description": "Inventory/(Sales/365) − prior year. Rising DIO = inventory accumulating faster than sales. Days.",
        "source_columns": ["{Sales, Inventory}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=0.97 MID)",
        "status_reason": "Library tier — no edge in the 6-period backtest. Cousin of dso_change_yoy but inventory dynamics are noisier (production decisions).",
        "producer": "dio_change_yoy",
        "pit_range": (-365, 365),
        "bench": "LIBRARY",  # best |t|=0.97 MID
    },
    "nwc_to_revenue": {
        "label": "NWC / Revenue (latest)",
        "group": "Track 3 — Library",
        "description": "(Receivables + Inventory − Trade Payables) / Sales, latest annual. Spot sibling of wc_intensity (which is 3y median).",
        "source_columns": ["{Sales, Receivables, Inventory, Trade Payables}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — LARGE WEAK (t=+1.68), SMALL WEAK (t=+1.92), MID DROP (t=+1.29)",
        "status_reason": "PARKED — passes |t|≥1.5 bar on LARGE+SMALL but with contrarian sign (higher NWC predicts higher return). Likely 6-period regime artifact (same pattern as wc_intensity / ccc); awaiting more periods.",
        "producer": "nwc_to_revenue",
        "pit_range": (-2, 5),
        "bench": "LIBRARY",  # contrarian sign on LARGE+SMALL (t=+1.68/+1.92)
    },
    "sloan_accruals_full": {
        "label": "Sloan Accruals (full BS formula)",
        "group": "Track 3 — Library",
        "description": "(ΔNWC − Depreciation) / avg(Total assets). The original Sloan (1996) measure. Lower = cash-rich earnings.",
        "source_columns": ["{Receivables, Inventory, Trade Payables, Depreciation, Total}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.43 SMALL)",
        "status_reason": "Library tier — sub-|t|=1.5 across tiers. Sibling of cf_accruals/bs_accruals from v1 forensic suite; redundancy possible.",
        "producer": "sloan_accruals_full",
        "pit_range": (-1, 1),
        "bench": "LIBRARY",  # best |t|=1.43 SMALL
    },
    "sga_to_revenue_change": {
        "label": "Δ SG&A Intensity",
        "group": "Track 3 — Library",
        "description": "Selling and admin / Sales − prior year. Rising intensity = operating discipline slipping.",
        "source_columns": ["{Sales, Selling and admin}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=0.69 MID)",
        "status_reason": "Library tier — no edge in the 6-period backtest. Screener's 'Selling and admin' may miss R&D and other overheads broken out separately.",
        "producer": "sga_to_revenue_change",
        "pit_range": (-1, 1),
        "bench": "LIBRARY",  # best |t|=0.69 MID
    },
    "fcf_margin": {
        "label": "FCF Margin",
        "group": "Track 3 — Library",
        "description": "3y median (OCF − Capex) / Sales. Fundamental sibling of fcf_yield (no valuation input).",
        "source_columns": ["{Sales, OCF, Net Block, CWIP, Depreciation}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.28 LARGE)",
        "status_reason": "Library tier — sub-|t|=1.5. Likely correlated with fcf_yield and quality_composite.",
        "producer": "fcf_margin",
        "pit_range": (-2, 2),
        "bench": "LIBRARY",  # best |t|=1.28 LARGE
    },
    "capex_to_dep": {
        "label": "CapEx / Depreciation",
        "group": "Track 3 — Library",
        "description": "3y median (max(Δ(Net Block + CWIP), 0) + Depreciation) / Depreciation. >1 = growing, <1 = harvesting.",
        "source_columns": ["{Net Block, CWIP, Depreciation}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=0.94 SMALL)",
        "status_reason": "Library tier — capital-cycle descriptor more than a return predictor in this regime.",
        "producer": "capex_to_dep",
        "pit_range": (-20, 20),
        "bench": "LIBRARY",  # best |t|=0.94 SMALL
    },
    "goodwill_to_assets": {
        "label": "Intangibles / Total Assets",
        "group": "Track 3 — Library",
        "description": "Intangible Assets / Total. Goodwill proxy — Screener doesn't separate goodwill from other intangibles.",
        "source_columns": ["{Intangible Assets, Total}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=0.89 MID)",
        "status_reason": "Library tier — no edge in 6 periods. Median ratio is 0.6% so the cross-section is thin; mostly a tag for acquisition-driven names.",
        "producer": "goodwill_to_assets",
        "pit_range": (0, 1),
        "bench": "LIBRARY",  # best |t|=0.89 MID
    },
    "debt_structure": {
        "label": "LT Borrowings Share",
        "group": "Track 3 — Library",
        "description": "Long term Borrowings / Borrowings, latest annual. Higher = safer debt maturity profile.",
        "source_columns": ["{Long term Borrowings, Borrowings}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.15 LARGE)",
        "status_reason": "Library tier — debt maturity profile descriptor. Median 27% LT (Indian companies skew short-term); cross-section may need finer maturity buckets to find signal.",
        "producer": "debt_structure",
        "pit_range": (0, 1),
        "bench": "LIBRARY",  # best |t|=1.15 LARGE
    },
    "asset_tangibility": {
        "label": "Asset Tangibility (Net Block / Total)",
        "group": "Track 3 — Library",
        "description": "Net Block / Total assets, latest annual. Higher = capex-heavy / asset-rich business model.",
        "source_columns": ["{Net Block, Total}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — MID WEAK (t=+2.06), LARGE/SMALL DROP",
        "status_reason": "PARKED — WEAK MID with positive sign (capex-heavy mid-caps outperformed in the 6-period window). Likely regime-dependent (industrials/cement rotation); awaiting more periods.",
        "producer": "asset_tangibility",
        "pit_range": (0, 1),
        "bench": "LIBRARY",  # WEAK MID (t=+2.06), regime-dependent positive sign
    },
    "interest_coverage": {
        "label": "Interest Coverage Ratio",
        "group": "Track 3 — Library",
        "description": "(PBT + Interest) / Interest, 3-yr median, capped ±200. Stocks with Interest<₹1cr excluded.",
        "source_columns": ["{PBT, Interest}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — SMALL WEAK (t=+2.41, n=5, intuitive sign), LARGE/MID DROP",
        "status_reason": "PARKED — strongest result of the 2026-05-22 batch; intuitively-signed (higher coverage → higher return) on SMALL. Promote candidate after one more month of fwd_return matures.",
        "producer": "interest_coverage",
        "pit_range": (-200, 200),
        "bench": "LIBRARY",  # intuitive sign on SMALL (t=+2.41)
    },
    "revenue_cv_5y": {
        "label": "Revenue CV (5y stability)",
        "group": "Track 3 — Library",
        "description": "Stdev/|mean| of last 5 YoY Sales growth rates. Lower = more stable top line.",
        "source_columns": ["Sales (annual, 6 yrs)"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.28)",
        "status_reason": "Library tier (plan 0007 cluster).",
        "producer": "revenue_cv",
        "pit_range": (0, 50),
        "bench": "LIBRARY",
    },
    "relative_turnover": {
        "label": "Inventory Turnover vs Sector",
        "group": "Track 3 — Library",
        "description": "Sales/Inventory 3-yr median, divided by sector p50. IT/Comm/Utilities + financials excluded.",
        "source_columns": ["{Sales, Inventory}"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.07)",
        "status_reason": "Library tier (plan 0007 cluster).",
        "producer": "inventory_turnover",
        "pit_range": (0, 20),
        "bench": "LIBRARY",
    },
    "relative_growth": {
        "label": "Sales Growth vs Sector Median",
        "group": "Track 3 — Library",
        "description": "3-yr median YoY Sales growth minus sector median. Financials excluded.",
        "source_columns": ["Sales (annual)"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.19)",
        "status_reason": "Library tier (plan 0007 cluster).",
        "producer": "sales_growth_relative",
        "pit_range": (-2, 5),
        "bench": "LIBRARY",
    },
    "share_momentum": {
        "label": "Market-Cap Share Momentum",
        "group": "Track 3 — Library",
        "description": "Δ market_cap_share within sector over trailing 90 calendar days. Financials excluded.",
        "source_columns": ["close (PIT-adjusted)", "No. of Equity Shares"],
        "filing_lag": "0d price + 75d shares",
        "v1_verdict_summary": "v2-only — KEEP on at least one tier (best |t|=3.21)",
        "status_reason": "VALIDATED — strongest Track-3 signal to date. Eligible for scoring weights pending Track 3.3a weighting work (per CLAUDE.md, don't edit SCREEN.weight_tiers mechanically).",
        "producer": "share_momentum",
        "pit_range": (-1, 5),
        "bench": "LIBRARY",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 12 — FACTOR COMPOSITES (v1 screener inputs)
    # ═══════════════════════════════════════════════════════════════════

    "value_composite": {
        "label": "Value Composite",
        "group": "Composite",
        "description": "v1 screener: 40% earnings_yield + 35% book_to_price + 25% position_52w (within-tier rank)",
        "source_tables": ["—"],
        "source_columns": ["earnings_yield + book_to_price + position_52w"],
        "filing_lag": "max of components (75d annual)",
        "v1_verdict_summary": "value_recon: DROP / DROP / KEEP (t=3.17 SMALL)",
        "status_reason": "Within-tier rank, NaN-tolerant weighted average.",
        "producer": "value_composite",
        "pit_range": (0, 1),
        "bench": "PROPOSED",
        "weight_key": "value_composite",
    },
    "quality_composite": {
        "label": "Quality Composite",
        "group": "Composite",
        "description": "v1 screener: 45% roe + 30% inverse-debt_to_equity + 25% profit_margin (financials' D/E excluded)",
        "source_tables": ["—"],
        "source_columns": ["roe + debt_to_equity + profit_margin"],
        "filing_lag": "75d annual + 60d quarterly",
        "v1_verdict_summary": "quality_recon: DROP all tiers",
        "status_reason": "Within-tier rank. Kept despite v1 DROP.",
        "producer": "quality_composite",
        "pit_range": (0, 1),
        "bench": "PROPOSED",  # TODO amit: classify
    },
    "growth_composite": {
        "label": "Growth Composite",
        "group": "Composite",
        "description": "v1 screener: 50% revenue_growth_yoy + 50% eps_growth_yoy (within-tier rank)",
        "source_tables": ["—"],
        "source_columns": ["revenue_growth_yoy + eps_growth_yoy"],
        "filing_lag": "60d quarterly",
        "v1_verdict_summary": "growth_recon: DROP all tiers (n=16)",
        "status_reason": "Kept despite v1 DROP.",
        "producer": "growth_composite",
        "pit_range": (0, 1),
        "bench": "PROPOSED",  # TODO amit: classify
    },
    "momentum_composite": {
        "label": "Momentum Composite",
        "group": "Composite",
        "description": "v1 screener: 50% mom_6m + 50% mom_12m",
        "source_tables": ["—"],
        "source_columns": ["mom_6m + mom_12m"],
        "filing_lag": "—",
        "pit_column_v2": "mom_composite",
        "v1_verdict_summary": "momentum_recon: DROP all tiers",
        "status_reason": "Equal-weight composite of mom_6m + mom_12m, ranked within cap_tier.",
        "producer": "mom_composite",
        "pit_range": (0, 1),
        "bench": "PROPOSED",
    },
    "screener_final_composite": {
        "label": "Final Screener Composite",
        "group": "Composite",
        "description": "Full screener output incl. all sub-signals + adjustments (forensic, sentiment, insider, macro)",
        "source_tables": ["—"],
        "source_columns": ["all of the above"],
        "filing_lag": "—",
        "pit_column_v2": None,
        "v1_verdict_summary": "(insufficient PIT data — n=0 in v1)",
        "status": "PROPOSED",
        "status_reason": "End-state composite — built only after all sub-signals are PIT-ready. Tracks Track 2.4 portfolio construction work.",
        "cadence": "portfolio",
        "bench": "PROPOSED",  # TODO amit: classify
    },
    "financial_signal": {
        "label": "Financial Sub-Model (Banks + NBFCs) — legacy single-direction",
        "group": "Track 2 — Portfolio",
        "description": "Per-stock composite for Banks + NBFCs only: 40% asset_quality (GNPA/NNPA, direction=lower) + 30% profitability + 15% capital + 15% funding. SUPERSEDED 2026-05-29 by financial_quality + financial_recovery split after backtest showed AQ direction flips by tier. Kept here as the alias column (= financial_quality) so historical PIT and the existing optimizer entry survive.",
        "source_columns": ["gross_npa_pct, net_npa_pct, interest_earned, net_interest_income, net_profit, cost_of_funds_pct"],
        "filing_lag": "60d quarterly + 75d annual",
        "v1_verdict_summary": "Phase 2.2d backtest FAILED done gate (t = -0.75 / -1.30 / -0.34 LARGE/MID/SMALL) — direction-flip diagnostic surfaced. Split into financial_quality + financial_recovery 2026-05-29 session #2.",
        "status": "SUPERSEDED",
        "status_reason": "Single-direction composite invalid by backtest. Use financial_quality (SMALL) + financial_recovery (LARGE/MID) instead.",
        "producer": "financial_signal",
        "pit_range": (-3, 3),
        "bench": "PROPOSED",  # TODO amit: classify
    },
    "financial_quality": {
        "label": "Financial Quality — SMALL banks/NBFCs (low NPA = strong franchise)",
        "group": "Track 2 — Portfolio",
        "description": "Quality direction of Phase 2.2b composite — asset_quality z-scored as direction='lower' (low NPA good). Other 3 components shared with financial_recovery: profitability (NII/NP margin), capital (NULL pre-2.2c), funding (cost_of_funds). Composite renormalised over present components. Backtest hypothesis: SMALL banks' gross_npa_pct t=-3.09 (low NPA persists, quality compounds).",
        "source_columns": ["gross_npa_pct, net_npa_pct, interest_earned, net_interest_income, net_profit, cost_of_funds_pct"],
        "filing_lag": "60d quarterly + 75d annual",
        "v1_verdict_summary": "(v2-only; SMALL-tier validation pending Phase 2.2d-v2 backtest run)",
        "status_reason": "Phase 2.2b-v2 (split) shipped 2026-05-29. PIT helper writes both columns; screener will read this one for SMALL tier post-validation.",
        "producer": "financial_signal",
        "pit_range": (-3, 3),
        "bench": "LIBRARY",
    },
    "financial_recovery": {
        "label": "Financial Recovery — LARGE/MID banks/NBFCs (high NPA = mean-reversion)",
        "group": "Track 2 — Portfolio",
        "description": "Recovery direction of Phase 2.2b composite — asset_quality z-scored as direction='higher' (high NPA = distressed-recovery opportunity). Other 3 components shared with financial_quality. Backtest hypothesis: LARGE net_npa_pct t=+2.39, MID t=+4.16 (NPA-stressed names mean-revert).",
        "source_columns": ["gross_npa_pct, net_npa_pct, interest_earned, net_interest_income, net_profit, cost_of_funds_pct"],
        "filing_lag": "60d quarterly + 75d annual",
        "v1_verdict_summary": "(v2-only; LARGE/MID-tier validation pending Phase 2.2d-v2 backtest run)",
        "status_reason": "Phase 2.2b-v2 (split) shipped 2026-05-29. PIT helper writes both columns; screener will read this one for LARGE/MID tiers post-validation.",
        "producer": "financial_signal",
        "pit_range": (-3, 3),
        "bench": "PROPOSED",  # TODO amit: classify
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP — INDUSTRY (§3.2.6) + MACRO BETAS (§3.2.7)
    # ═══════════════════════════════════════════════════════════════════
    "industry_id": {
        "label": "Industry Identity (categorical control)",
        "group": "Controls",
        "description": "Frozen integer code (1..38, 0=unknown) for the stock's industry. A NEUTRALISATION CONTROL, not a rankable alpha factor — no directional signal, Spearman IC of an arbitrary code is meaningless. Kept out of SIGNAL_COLUMN_MAP / the IC roster; exists for industry one-hot / neutralisation at model-fit time (Plan 0002 §3.2.6 'industry dummies (1)').",
        "source_columns": ["stocks.industry"],
        "filing_lag": "0d (static attribute)",
        "v1_verdict_summary": "(control — not backtested for IC)",
        "status": "CONTROL",
        "status_reason": "Shipped 2026-06-02. Categorical control; not promotable, not IC-gated.",
        "producer": "industry_id",
        "pit_range": (0, 50),
        "bench": "CONTROL",
    },
    "oil_beta": {
        "label": "Oil Beta (β vs Brent crude)",
        "group": "Macro Extensions",
        "description": "Rolling 252-trading-day OLS beta of daily stock returns on Brent crude daily returns. Energy / input-cost exposure (Plan 0002 §3.2.7). Per-stock exposure, NOT the macro level (a level is cross-sectionally constant → 0 IC).",
        "source_columns": ["stock_prices.close", "macro_history.brent_crude"],
        "filing_lag": "0d (daily price + daily macro)",
        "v1_verdict_summary": "(v2-only; macro_history starts 2023-03-13, NULL before ~1y lookback)",
        "status_reason": "Shipped 2026-06-02; re-backtested 2026-06-07 on deepened macro_history (40 monthly periods, was 23). best |t|=0.87 LARGE → DROP, benched (FACTOR_LIBRARY).",
        "producer": "macro_betas",
        "pit_range": (-5, 5),
        "bench": "LIBRARY",  # best |t|=0.87 LARGE — DROP (40 periods)
    },
    "metals_beta": {
        "label": "Metals Beta (β vs copper+aluminium)",
        "group": "Macro Extensions",
        "description": "Rolling 252-trading-day OLS beta of daily stock returns on an equal-weight copper+aluminium daily-return blend. Industrial / capex / metals-cycle exposure (Plan 0002 §3.2.7).",
        "source_columns": ["stock_prices.close", "macro_history.copper", "macro_history.aluminium"],
        "filing_lag": "0d (daily price + daily macro)",
        "v1_verdict_summary": "(v2-only; NULL before ~1y macro lookback)",
        "status_reason": "Shipped 2026-06-02; re-backtested 2026-06-07 on deepened macro_history (40 monthly periods, was 23). LARGE t=+1.96 WEAK (CI [-0.10,3.92] straddles 0; firmed from +1.78), MID/SMALL DROP → benched.",
        "producer": "macro_betas",
        "pit_range": (-5, 5),
        "bench": "LIBRARY",  # LARGE t=+1.96 WEAK (40 periods; cyclical large-cap exposure; CI straddles 0)
    },
    "inr_beta": {
        "label": "INR Beta (β vs USD/INR)",
        "group": "Macro Extensions",
        "description": "Rolling 252-trading-day OLS beta of daily stock returns on USD/INR daily returns. FX / importer-vs-exporter tilt (Plan 0002 §3.2.7). The rankable form of the plan's 'inr_carry_proxy' — a carry LEVEL is cross-sectionally constant, so the per-stock FX exposure is used instead.",
        "source_columns": ["stock_prices.close", "macro_history.usdinr"],
        "filing_lag": "0d (daily price + daily macro)",
        "v1_verdict_summary": "(v2-only; NULL before ~1y macro lookback)",
        "status_reason": "Shipped 2026-06-02; re-backtested 2026-06-07 on deepened macro_history (40 monthly periods, was 23). best |t|=1.01 SMALL → DROP (FX exposure not cross-sectionally priced), benched.",
        "producer": "macro_betas",
        "pit_range": (-5, 5),
        "bench": "LIBRARY",  # best |t|=1.01 SMALL — DROP (FX exposure not cross-sectionally priced)
    },
    "gold_beta": {
        "label": "Gold Beta (β vs gold)",
        "group": "Macro Extensions",
        "description": "Rolling 252-trading-day OLS beta of daily stock returns on gold daily returns. Safe-haven / gold-financier tilt (Plan 0002 §3.2.7). Takes the 4th macro-extension slot in place of india_credit_spread, which is DATA-BLOCKED (no daily India G-Sec / credit series; india_money_rate is monthly + stale). Revisit a rate_beta when a daily G-Sec feed lands.",
        "source_columns": ["stock_prices.close", "macro_history.gold"],
        "filing_lag": "0d (daily price + daily macro)",
        "v1_verdict_summary": "(v2-only; NULL before ~1y macro lookback)",
        "status_reason": "Shipped 2026-06-02; re-backtested 2026-06-07 on deepened macro_history (40 monthly periods, was 23). LARGE t=+1.89 WEAK (CI [-0.21,3.85] straddles 0; firmed from +1.58), MID/SMALL DROP → benched.",
        "producer": "macro_betas",
        "pit_range": (-5, 5),
        "bench": "LIBRARY",  # LARGE t=+1.89 WEAK (40 periods; safe-haven/gold-financier tilt; CI straddles 0)
    },
    "rate_beta": {
        "label": "Rate Beta (β vs 10Y G-Sec gilt ETF)",
        "group": "Macro Extensions",
        "description": "Rolling 252-trading-day OLS beta of daily stock returns on the SBI 10Y Gilt ETF (SETF10GILT) daily returns. Rate / duration exposure (Plan 0002 §3.2.7). The gilt ETF RISES when the 10Y yield FALLS, so +rate_beta = co-moves with bond rallies (duration-like: NBFCs, rate-sensitive growth). Resolves the previously DATA-BLOCKED india rate factor — NSE bond ETFs are the only free daily India-rates feed reachable (FBIL/CCIL/RBI walled, FRED monthly).",
        "source_columns": ["stock_prices.close", "macro_history.gsec10_etf"],
        "filing_lag": "0d (daily price + daily macro)",
        "v1_verdict_summary": "(v2-only; gsec10_etf daily from 2016)",
        "status_reason": "Shipped + backtested 2026-06-07 (§3.2.7, 40 monthly periods). best |t|=0.77 LARGE → DROP, benched (FACTOR_LIBRARY). Rate-sensitivity not cross-sectionally priced in this sample.",
        "producer": "macro_betas",
        "pit_range": (-5, 5),
        "bench": "LIBRARY",  # §3.2.7 (2026-06-07, 40 periods) — best |t|=0.77 LARGE → DROP
    },
    "credit_beta": {
        "label": "Credit Beta (β vs AAA-PSU credit excess)",
        "group": "Macro Extensions",
        "description": "Rolling 252-trading-day OLS beta of daily stock returns on credit_excess_idx — the AAA-PSU-over-gilt excess-return index (Bharat Bond EBBETF0430 minus SBI 10Y Gilt). Credit-cycle exposure (Plan 0002 §3.2.7); +credit_beta = rises when credit spreads tighten. CAVEAT: Bharat Bond is target-maturity → residual duration tilt; orthogonalise vs rate_beta before any wiring.",
        "source_columns": ["stock_prices.close", "macro_history.credit_excess_idx"],
        "filing_lag": "0d (daily price + daily macro)",
        "v1_verdict_summary": "(v2-only; credit_excess_idx daily from 2019)",
        "status_reason": "Shipped + backtested 2026-06-07 (§3.2.7, 40 monthly periods). best |t|=0.68 SMALL → DROP, benched. Credit stress (2018 IL&FS / 2020 COVID) falls OUTSIDE the price-history window (2022+), so the test period sees credit in a calm regime — low power. Duration-tilt caveat moot (no signal either way).",
        "producer": "macro_betas",
        "pit_range": (-5, 5),
        "bench": "LIBRARY",  # §3.2.7 (2026-06-07, 40 periods) — best |t|=0.68 SMALL → DROP (credit stress pre-2022, out of window)
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP — LARGE-TIER CANONICAL REBUILD (audit 2026-07-04 Factor-F3)
    # The three canonical factors the audit's gap map named as absent with
    # data already in-house. BUILD + EVIDENCE only — none wired.
    # ═══════════════════════════════════════════════════════════════════

    "low_vol_252d": {
        "label": "Low Volatility (252d annualized)",
        "group": "Risk",
        "description": "Annualized std of daily log returns over the trailing 252 trading "
                       "days (min 200 obs, split-adjusted closes). Canonical low-risk anomaly "
                       "(Ang 2006, Blitz-van Vliet 2007, BAB): LOW vol → HIGH forward return, "
                       "so the expected IC of the raw vol value is NEGATIVE.",
        "source_columns": ["stock_prices.close (adj, rolling 252d)"],
        "filing_lag": "0d (price)",
        "v1_verdict_summary": "(new — audit Factor-F3 LARGE-tier rebuild candidate #1)",
        "status_reason": "Shipped + backtested 2026-07-05 (audit Factor-F3 #1; 68 monthly anchors "
                         "2020-11→2026-06, incl. the new 2020 price-backfill anchors). LARGE t=+1.96 "
                         "WEAK (IC +0.057, CI [0.14,3.94]) but CONTRARIAN sign — HIGH vol won in the "
                         "mostly-bull 2021-26 sample, opposite the canonical low-vol anomaly; MID +1.26 "
                         "/ SMALL −1.04 DROP (SMALL carries the expected negative sign, insignificant). "
                         "Robust to the timely-anchor fwd_return check (LARGE +1.99). Contrarian-sign "
                         "WEAK on the walk-forward-weakest tier → NOT promotion-eligible; benched "
                         "(FACTOR_LIBRARY). Re-read once a drawdown regime enters the window.",
        "producer": "low_vol",
        "pit_range": (0, 5),
        "bench": "LIBRARY",  # LARGE t=+1.96 WEAK but CONTRARIAN (high vol won, 2021-26 bull sample) — parked, not promotion-eligible
    },
    "st_reversal_21d": {
        "label": "Short-Term Reversal (21d return)",
        "group": "Momentum",
        "description": "Trailing 21-trading-day total return (min 15 obs, split-adjusted "
                       "closes). Canonical short-term reversal (Jegadeesh 1990): last month's "
                       "losers win next month — expected IC NEGATIVE. The horizon mom_6m/12m "
                       "deliberately skip (SKIP_DAYS=22) is exactly this factor.",
        "source_columns": ["stock_prices.close (adj, rolling 21d)"],
        "filing_lag": "0d (price)",
        "v1_verdict_summary": "(new — audit Factor-F3 LARGE-tier rebuild candidate #2)",
        "status_reason": "Shipped + backtested 2026-07-05 (audit Factor-F3 #2; 77 monthly anchors "
                         "2020-02→2026-06). DROP all tiers: SMALL t=−1.50 (expected reversal sign), "
                         "MID −0.40, LARGE +0.04. On the timely-anchor robustness slice SMALL firms "
                         "to −1.93 — the reversal direction looks real in SMALL but stays sub-2.5. "
                         "Benched (FACTOR_LIBRARY); natural retest is weekly cadence (a 21d fast-decay "
                         "factor sampled monthly with a 20d response is structurally handicapped).",
        "producer": "st_reversal",
        "pit_range": (-1, 5),
        "bench": "LIBRARY",  # DROP all; SMALL −1.50 (−1.93 on timely-anchor slice), expected reversal sign, sub-bar — weekly-cadence retest is the natural next test
    },
    "asset_growth_yoy": {
        "label": "Asset Growth YoY (CMA)",
        "group": "Growth",
        "description": "YoY % change in total assets between the two most recent knowable "
                       "annual balance sheets (75d filing lag, book_to_price convention; "
                       "non-financials, prior-year assets ≥ ₹50 cr). Canonical investment "
                       "factor (Cooper-Gulen-Schill 2008 / FF5 CMA): aggressive balance-sheet "
                       "expansion underperforms — expected IC NEGATIVE.",
        "source_columns": ["bs.total_assets"],
        "filing_lag": "75d annual",
        "v1_verdict_summary": "(new — audit Factor-F3 LARGE-tier rebuild candidate #3)",
        "status_reason": "Shipped + backtested 2026-07-05 (audit Factor-F3 #3; 78 monthly anchors "
                         "2020-01→2026-06). Headline: MID t=+2.18 WEAK / LARGE +1.21 / SMALL −0.30. "
                         "The MID '+' is an ARTIFACT of late-anchored responses: pit_fwd_return_20d "
                         "anchors a sid with no prices near an old eval date at its FIRST later price "
                         "row (~40% of pairs at pre-2023 anchors), pairing 2019-era balance-sheet "
                         "growth with wrong-period returns. Restricting to pairs whose response "
                         "anchors within 10d of eval flips MID to −0.92 and gives the expected CMA "
                         "negative sign on ALL tiers (LARGE −0.87 / MID −0.92 / SMALL −0.70), "
                         "insignificant. NOT promotion-eligible; benched (FACTOR_LIBRARY).",
        "producer": "asset_growth",
        "pit_range": (-100, 1000),
        "weights": {"LARGE": -0.20},  # t: L −2.37, low asset growth does better (sign matches the prior) — promotion review 2026-10-03 (docs/studies/promotion-review-2026-10.md), corrected panel
        "family": "Growth",
        "eligibility": {
            "description": "Non-financial stocks with two annual balance sheets",
            "eligible_sql": """
                SELECT sid FROM annual_balance_sheet WHERE total_assets > 0 AND sid NOT IN (SELECT sid FROM stocks WHERE sector = 'Financials') GROUP BY sid HAVING COUNT(*) >= 2
            """,
        },
    },
    "residual_momentum_12_1": {
        "label": "Residual Momentum (12-1, NIFTY-beta-net)",
        "group": "Momentum",
        "description": "12-1 momentum (skip most recent ~21 trading days) residualized "
                       "against NIFTY-50 market beta over the same window (OLS, min 150 "
                       "paired daily-return obs). Jegadeesh-Titman 1993 / Blitz-Huij-Martens "
                       "2011 — removing the market-beta component strengthens raw momentum. "
                       "Designed retest of plain momentum (mom_6m_adj/mom_12m_adj), which "
                       "failed the clean bar at SMALL t=1.34. Expected IC POSITIVE.",
        "source_columns": ["stock_prices.close (adj, 252-21d window)", "macro_history.nifty50"],
        "filing_lag": "0d (price)",
        "v1_verdict_summary": "(new — plan 0012 C3, WS2.6 momentum retest hypothesis 1 of 2)",
        "status_reason": "Shipped + backtested 2026-07-11 (plan 0012 C3; 66 monthly anchors "
                         "2020-02→2026-07). SMALL t=+2.84 KEEP (IC +0.0319), correct hypothesised "
                         "sign; LARGE +1.33 / MID +1.11 both DROP (also correct sign, just weak). "
                         "Multiple-testing: SMALL p_BY=0.8832 — fails BY-FDR outright (naive KEEP "
                         "does not survive correction; likely a false discovery from the ~280-"
                         "hypothesis factor zoo, though sign is right). NOT promotion-eligible on "
                         "this evidence; benched (FACTOR_LIBRARY). Report: "
                         "docs/studies/new-factors-2026-07.md.",
        "producer": "residual_momentum_12_1",
        "pit_range": (-5, 5),
        "weights": {"MID": 0.20, "SMALL": 0.14},  # t: M 3.33 · S 3.98; the momentum representative (0.92 correlated with mom_12m_adj) — promotion review 2026-10-03 (docs/studies/promotion-review-2026-10.md), corrected panel
        "family": "Momentum",
        "eligibility": {
            "description": "Stocks with about 13 months of prices (252 sessions)",
            "eligible_sql": """
                SELECT sid FROM stock_prices WHERE close > 0 GROUP BY sid HAVING COUNT(*) >= 252
            """,
        },
    },
    "max_lottery_21d": {
        "label": "MAX Lottery Factor (21d)",
        "group": "Momentum",
        "description": "Mean of the 5 highest daily simple returns over the trailing 21 "
                       "trading days. Bali-Cakici-Whitelaw 2011: retail lottery preference "
                       "overprices extreme-daily-return names — expected IC NEGATIVE. "
                       "Long-only use is naturally exclusion/penalty-shaped (can't short "
                       "the names to avoid), like governance_resignation.",
        "source_columns": ["stock_prices.close (adj, rolling 21d, top-5 daily returns)"],
        "filing_lag": "0d (price)",
        "v1_verdict_summary": "(new — plan 0012 C4, WS2.7 lottery retest hypothesis 2 of 2)",
        "status_reason": "Shipped + backtested 2026-07-11 (plan 0012 C4; 77 monthly anchors "
                         "2020-02→2026-07). SMALL t=-3.47 KEEP (IC -0.0324), correct hypothesised "
                         "NEGATIVE sign — the strongest clean result of the plan 0012 factor batch. "
                         "LARGE t=+1.84 WEAK but CONTRARIAN (positive — opposite of the lottery-"
                         "penalty hypothesis); MID +0.70 DROP. Multiple-testing: SMALL p_BY=0.2193 "
                         "— fails the 0.05 BY-FDR bar but far less badly than the plan's other new "
                         "factors (closest to survival of the batch). NOT promotion-eligible on "
                         "this evidence; benched (FACTOR_LIBRARY). Report: "
                         "docs/studies/new-factors-2026-07.md.",
        "producer": "max_lottery_21d",
        "pit_range": (-1, 2),
        "bench": "LIBRARY",  # SMALL t=-3.47 KEEP, correct NEGATIVE sign, p_BY=0.2193 (closest-to-surviving of the batch); LARGE +1.84 WEAK but contrarian
    },
}


# ── daily_snapshots_pit columns that are not factors ──
# The per-date base price, the backtest response, and the screener composites
# pit_replay needs to replay the live score end-to-end (plan 0005 Phase E).
PIT_EXTRA = {
    "close_price":      {"producer": "base", "pit_range": (0.01, 10_000_000)},   # = checks.ranges stock_prices.close (SM-REITs trade ~₹10-12 lakh)
    "fwd_return_20d":   {"producer": "fwd_return", "pit_range": (-1, 5)},   # cap extreme returns
    "accruals_signal":  {"producer": "accruals", "pit_range": (0, 1)},      # within-tier percentile blend
    "promoter_signal":  {"producer": "promoter", "pit_range": (0, 1)},      # within-tier percentile blend
    "forensic_penalty": {"producer": "forensic", "pit_range": (-1, 0),      # 0 / -0.10 / -0.20 / -0.30
                         "screener_col": "penalty", "replay_col": "forensic_penalty",
                         "family": "Forensic"},
}


# ── PIT producers: the tools/reconstruct_pit --signal groups, in run order ──
#   fn        pit_* helper in pit.py (by name)
#   inputs    per-date frames it is called with, positionally (pit._pit_input)
#   needs     raw frames that must be LOADED for it to run
#   nonempty  inputs that must be non-empty for it to run
#   after     base columns it composes (composites run after their parts)
#   aliases   extra --signal names that trigger it
#   table     written by reconstruct_pit.main() into a separate table (no per-sid columns)
_FUND = ("stocks", "fund")
PIT_PRODUCERS = {
    "piotroski":        {"fn": "pit_piotroski", "inputs": ("stocks", "qi", "bs", "cf")},
    "accruals":         {"fn": "pit_accruals", "inputs": ("stocks", "qi", "bs", "cf", "fund")},
    "promoter":         {"fn": "pit_promoter", "inputs": ("stocks", "sh")},
    "forensic":         {"fn": "pit_forensic", "inputs": ("stocks", "qi", "bs", "cf", "fund")},
    "earnings_yield":   {"fn": "pit_earnings_yield", "inputs": ("qi", "close")},
    "book_to_price":    {"fn": "pit_book_to_price", "inputs": ("bs", "close", "fund", "adjustments", "eval_date")},
    "momentum":         {"fn": "pit_momentum", "inputs": ("px",)},
    "position_52w":     {"fn": "pit_position_52w", "inputs": ("px", "eval_date")},
    "delivery":         {"fn": "pit_delivery", "inputs": ("px",)},
    "sector_momentum":  {"fn": "pit_sector_momentum", "inputs": ("stocks", "px", "macro_hist", "eval_date")},
    "sector_tilt":      {"fn": "pit_sector_tilt", "inputs": ("stocks", "px", "macro_hist", "macro_map", "eval_date")},
    "fno_oi":           {"fn": "pit_fno_oi", "inputs": ("fno_pcr", "eval_date"), "nonempty": ("fno_pcr",)},
    "fno_iv":           {"fn": "pit_fno_iv", "inputs": ("fno_iv", "px", "eval_date"), "nonempty": ("fno_iv",)},
    "microstructure":   {"fn": "pit_microstructure", "inputs": ("prices_ohlc", "eval_date"),
                         "nonempty": ("prices_ohlc",)},
    "industry_id":      {"fn": "pit_industry_id", "inputs": ("stocks",)},
    "macro_betas":      {"fn": "pit_macro_betas", "inputs": ("px", "macro_hist", "eval_date")},
    "pead":             {"fn": "pit_pead", "inputs": ("qi", "px", "macro_hist", "corp_actions",
                                                      "bse_results", "eval_date")},
    "announcement_car": {"fn": "pit_announcement_car", "inputs": ("px", "macro_hist", "bse_results", "eval_date")},
    "governance":       {"fn": "pit_governance_resignation", "inputs": ("stocks", "bse_gov", "eval_date")},
    "low_vol":          {"fn": "pit_low_vol_252d", "inputs": ("px",)},
    "st_reversal":      {"fn": "pit_st_reversal_21d", "inputs": ("px",)},
    "asset_growth":     {"fn": "pit_asset_growth_yoy", "inputs": ("stocks", "bs")},
    "residual_momentum_12_1": {"fn": "pit_residual_momentum_12_1", "inputs": ("px", "macro_hist", "eval_date")},
    "max_lottery_21d":  {"fn": "pit_max_lottery_21d", "inputs": ("px",)},
    "nlp":              {"fn": "pit_nlp_factors", "inputs": ("stocks", "nlp", "eval_date")},
    "pledge":           {"fn": "pit_pledge_quality", "inputs": ("stocks", "sh")},
    "promoter_trend":   {"fn": "pit_promoter_trend_4q", "inputs": ("stocks", "sh")},
    "macd":             {"fn": "pit_macd_bullish", "inputs": ("px",)},
    "fwd_return":       {"fn": "pit_fwd_return_20d", "inputs": ("eval_date", "prices", "adjustments")},
    "quality_fundamentals": {"fn": "pit_quality_fundamentals", "inputs": ("stocks", "qi", "bs", "financial_sids")},
    "growth_fundamentals":  {"fn": "pit_growth_fundamentals", "inputs": ("stocks", "qi")},
    "consensus":        {"fn": "pit_consensus", "inputs": ("stocks", "fh")},
    "pt_upside":        {"fn": "pit_pt_upside", "inputs": ("stocks", "close", "acs")},
    "bulk_deal":        {"fn": "pit_bulk_deal_signal", "inputs": ("stocks", "bulk", "px", "eval_date"),
                         "needs": ("bulk",)},
    "smart_money":      {"fn": "pit_smart_money", "inputs": ("stocks", "bulk", "px", "eval_date"),
                         "needs": ("bulk",)},
    "short_selling":    {"fn": "pit_short_selling_signal", "inputs": ("stocks", "short", "px", "eval_date"),
                         "needs": ("short",)},
    "earnings_beat_rate": {"fn": "pit_earnings_beat_rate", "inputs": ("stocks", "qi")},
    "news_volume":      {"fn": "pit_news_volume", "inputs": ("stocks", "news", "eval_date"), "needs": ("news",)},
    "sentiment_7d":     {"fn": "pit_sentiment_7d", "inputs": ("news_text", "eval_date"), "needs": ("news_text",)},
    "insider_signal":   {"fn": "pit_insider_signal", "inputs": ("stocks", "insider_trades", "eval_date"),
                         "needs": ("insider_trades",)},
    "financial_signal": {"fn": "pit_financial_signal", "inputs": ("banking_metrics", "eval_date"),
                         "needs": ("banking_metrics",), "aliases": ("financial_quality", "financial_recovery")},
    "revenue_cv":       {"fn": "pit_revenue_cv", "inputs": _FUND, "nonempty": ("fund",)},
    "inventory_turnover": {"fn": "pit_inventory_turnover", "inputs": _FUND, "nonempty": ("fund",)},
    "sales_growth_relative": {"fn": "pit_sales_growth_relative", "inputs": _FUND, "nonempty": ("fund",)},
    "share_momentum":   {"fn": "pit_share_momentum", "inputs": ("stocks", "fund", "px", "eval_date"),
                         "nonempty": ("fund",)},
    "cash_conversion_cycle": {"fn": "pit_cash_conversion_cycle", "inputs": _FUND, "nonempty": ("fund",)},
    "operating_margin_trend": {"fn": "pit_operating_margin_trend", "inputs": _FUND, "nonempty": ("fund",)},
    "working_capital_intensity": {"fn": "pit_working_capital_intensity", "inputs": _FUND, "nonempty": ("fund",)},
    "interest_coverage": {"fn": "pit_interest_coverage", "inputs": _FUND, "nonempty": ("fund",)},
    "roic":             {"fn": "pit_roic", "inputs": _FUND, "nonempty": ("fund",)},
    "gross_profitability": {"fn": "pit_gross_profitability", "inputs": _FUND, "nonempty": ("fund",)},
    "fcf_yield":        {"fn": "pit_fcf_yield", "inputs": ("stocks", "fund", "close"), "nonempty": ("fund",)},
    "roiic":            {"fn": "pit_roiic", "inputs": _FUND, "nonempty": ("fund",)},
    "dso_change_yoy":   {"fn": "pit_dso_change_yoy", "inputs": _FUND, "nonempty": ("fund",)},
    "dio_change_yoy":   {"fn": "pit_dio_change_yoy", "inputs": _FUND, "nonempty": ("fund",)},
    "nwc_to_revenue":   {"fn": "pit_nwc_to_revenue", "inputs": _FUND, "nonempty": ("fund",)},
    "sloan_accruals_full": {"fn": "pit_sloan_accruals_full", "inputs": _FUND, "nonempty": ("fund",)},
    "sga_to_revenue_change": {"fn": "pit_sga_to_revenue_change", "inputs": _FUND, "nonempty": ("fund",)},
    "fcf_margin":       {"fn": "pit_fcf_margin", "inputs": _FUND, "nonempty": ("fund",)},
    "capex_to_dep":     {"fn": "pit_capex_to_dep", "inputs": _FUND, "nonempty": ("fund",)},
    "goodwill_to_assets": {"fn": "pit_goodwill_to_assets", "inputs": _FUND, "nonempty": ("fund",)},
    "debt_structure":   {"fn": "pit_debt_structure", "inputs": _FUND, "nonempty": ("fund",)},
    "asset_tangibility": {"fn": "pit_asset_tangibility", "inputs": _FUND, "nonempty": ("fund",)},
    # Composites — run after their parts, off the assembled per-date frame.
    "mom_composite":    {"fn": "pit_mom_composite", "inputs": ("base",), "after": ("mom_6m", "mom_12m")},
    "value_composite":  {"fn": "pit_value_composite", "inputs": ("base",),
                         "after": ("earnings_yield", "book_to_price", "position_52w")},
    "quality_composite": {"fn": "pit_quality_composite", "inputs": ("base",),
                          "after": ("roe", "debt_to_equity", "profit_margin")},
    "growth_composite": {"fn": "pit_growth_composite", "inputs": ("base",),
                         "after": ("revenue_growth_yoy", "eps_growth_yoy")},
    # Per-sector overlays → macro_sector_signals_pit (regulatory_score, macro_score).
    "sector_overlays":  {"fn": None, "inputs": (), "table": "macro_sector_signals_pit"},
}


# ── The tables behind each producer input (Dataset reads, ADR 0052) ──
# pit._pit_input key → the tables its raw frame(s) are loaded from (pit.RAW_SQL,
# via pit._INPUT_RAW). A factor's `source_tables` DEFAULTS to the union over its
# producer's inputs — the table-level reads, stated once (lineage.FACTOR_LINEAGE and
# the /model page derive from it). tests/test_factor_registry.py checks this map
# against pit.RAW_SQL, so it cannot drift from what the code actually loads.
INPUT_TABLES = {
    "stocks": ("stocks",), "financial_sids": ("stocks",),
    "qi": ("quarterly_income",), "bs": ("annual_balance_sheet",), "cf": ("annual_cash_flow",),
    "sh": ("shareholding",), "fund": ("fundamentals_screener",),
    "px": ("stock_prices", "corporate_adjustments"), "close": ("stock_prices", "corporate_adjustments"),
    "prices": ("stock_prices",), "prices_ohlc": ("stock_prices",), "adjustments": ("corporate_adjustments",),
    "fh": ("forecast_history",), "acs": ("analyst_consensus_snapshots",),
    "bulk": ("bulk_deals",), "short": ("short_selling_data",),
    "news": ("news_articles", "news_article_stocks"), "news_text": ("news_articles", "news_article_stocks"),
    "insider_trades": ("insider_trades",), "banking_metrics": ("banking_metrics",),
    "macro_hist": ("macro_history",), "macro_map": ("macro_sector_map",),
    "fno_pcr": ("fno_pcr_history",), "fno_iv": ("fno_iv_history",),
    "corp_actions": ("corporate_actions",), "bse_results": ("bse_announcements",),
    "bse_gov": ("bse_announcements",), "nlp": ("nlp_scores",),
    "eval_date": (), "base": (),
}


def producer_tables(producer):
    """Sorted tables a PIT producer reads (its inputs + needs + nonempty)."""
    spec = PIT_PRODUCERS.get(producer) or {}
    keys = (*spec.get("inputs", ()), *spec.get("needs", ()), *spec.get("nonempty", ()))
    return sorted({t for k in keys for t in INPUT_TABLES[k]})


# ── Dry-run weight variants (ADR 0028 → superseded by ADR 0049; non-production) ──
# ONE owner: here, as whole-scheme tables — they are tools/optimize_weights.py output
# (pasted wholesale, never tuned per factor) and only feed `scoring.screener
# --variant {return,sharpe}` (print-only), the cockpit variants page and status()
# "VARIANT". Production weights are NOT here — they sit on each FACTORS entry.
# Two optimized weight schemes from the PIT IC backtest (2026-05-28).
# Source: tools/optimize_weights.py reads pit_ic_by_tier_v2 and normalises by tier.
# Each scheme is "aggressive" — no caps, no diversification floor. pt_upside +
# eps_growth dominate because their t-stats earn it (t=7-9 and t=5 respectively).
# Choose by passing --variant {return,sharpe} to scoring/screener.

# MaxReturn: w_i ∝ |t_stat_i| × sign(IC_i). Favours absolute IC magnitude.
# Refresh: python -m tools.optimize_weights --filter-wired
# 2026-05-29: pledge_quality + delivery_anomaly_z now wired (Next-3 #3), so SMALL
# includes both; MID stays at 2 factors until interest_coverage/ccc/etc are wired.
#   2026-07-05 (ADR 0045): pt_upside → 0 in both variants below — look-ahead
#   artifact (audit Factor-F1, CRITICAL). Non-production (dry-run only via
#   --variant), so left un-renormalized per ADR 0045.
SIGNAL_WEIGHTS_RETURN = {
    "LARGE": {
        "pt_upside":         0,       # PULLED — look-ahead artifact (was t=7.15)
        "eps_growth":        0.3475,  # t=5.31
        "consensus":         0.1846,  # t=2.82
    },
    "MID": {
        "pt_upside":         0,       # PULLED — look-ahead artifact (was t=8.40)
        "accruals":         -0.2759,  # t=-3.20 (inverse)
    },
    "SMALL": {
        "pt_upside":         0,       # PULLED — look-ahead artifact (was t=9.14)
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
        "pt_upside":         0,       # PULLED — look-ahead artifact (was ICIR=1.21)
        "consensus":         0.1390,  # ICIR=0.50
    },
    "MID": {
        "pt_upside":         0,       # PULLED — look-ahead artifact (was ICIR=1.42)
        "accruals":         -0.3467,  # ICIR=-0.75 (inverse)
    },
    "SMALL": {
        "pt_upside":         0,       # PULLED — look-ahead artifact (was ICIR=1.54)
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


# ═══════════════════════ Derived views — never hand-edit a copy ═══════════════════════

# The rankable segments, from config.TIERS (pickable tiers, in config order).
TIERS = tuple(config.PICKABLE_TIERS)
WEIGHT_SCHEMES = ("SIGNAL_WEIGHTS", "SIGNAL_WEIGHTS_RETURN", "SIGNAL_WEIGHTS_SHARPE")
BENCHES = ("LIBRARY", "PROPOSED", "BLOCKED", "SUPERSEDED", "CONTROL")

_META_KEYS = ("label", "group", "description", "source_tables", "source_columns", "filing_lag",
              "pit_column_v1", "pit_column_v2", "external_table", "v1_verdict_summary",
              "status", "status_reason")


def pit_column(signal_id):
    """The factor's column in its PIT table (the part after "table." for sector signals)."""
    col = FACTORS[signal_id].get("pit_column_v2")
    return col.split(".", 1)[1] if col and "." in col else col


def _fill_defaults():
    """Materialize the inferable fields in place (an explicit value always wins), so
    every reader of FACTORS[sid][field] sees the full entry. Order matters: a
    weighted factor is a screener input (weight_key), whose column defaults follow."""
    for sid, f in FACTORS.items():
        f.setdefault("pit_column_v1", None)
        f.setdefault("pit_column_v2", sid)
        f.setdefault("status", "READY")
        f.setdefault("status_reason", "")
        f.setdefault("cadence", "monthly")
        if producer_tables(f.get("producer")):
            f.setdefault("source_tables", producer_tables(f["producer"]))
        if "weights" in f:
            f.setdefault("weight_key", sid)
        if "weight_key" in f:
            f.setdefault("screener_col", f["weight_key"])
            f.setdefault("replay_col", pit_column(sid))


_fill_defaults()


def _signal_weights():
    """{tier: {weight_key: w}} from the entries' `weights`, every rankable tier present.
    Within a tier: heaviest |w| first, ties by weight key — a fixed order, because the
    screener sums contributions in this order (float addition is order-sensitive)."""
    out = {t: {} for t in TIERS}
    for sid, f in FACTORS.items():
        for tier, w in f.get("weights", {}).items():
            if tier not in out:
                raise ValueError(f"{sid}: weight for non-rankable tier {tier!r}")
            if f["weight_key"] in out[tier]:
                raise ValueError(f"{sid}: weight key {f['weight_key']!r} weighted twice in {tier}")
            out[tier][f["weight_key"]] = w
    return {t: dict(sorted(tw.items(), key=lambda kw: (-abs(kw[1]), kw[0]))) for t, tw in out.items()}


# Production weights (the derived view every consumer imports; hand-set on the entries).
SIGNAL_WEIGHTS = _signal_weights()

# The historical registry shape: one dict per factor, metadata only.
BACKTEST_SIGNALS = [
    {"signal": sid, **{k: f[k] for k in _META_KEYS if k in f}} for sid, f in FACTORS.items()
]

# Non-monthly cadences (get_backtest_cadence falls back to "monthly").
BACKTEST_CADENCE = {sid: f["cadence"] for sid, f in FACTORS.items() if f["cadence"] != "monthly"}


def get_backtest_cadence(signal_id):
    """Cadence label for a signal. "monthly" for unknown ids — the safe default."""
    return BACKTEST_CADENCE.get(signal_id, "monthly")


FACTOR_LIBRARY = [sid for sid, f in FACTORS.items() if f.get("bench") == "LIBRARY"]
FACTOR_STATUS = {sid: f["bench"] for sid, f in FACTORS.items()
                 if f.get("bench") not in (None, "LIBRARY")}

# Orthogonal-family map, keyed the way SIGNAL_WEIGHTS names factors (weight keys).
SIGNAL_GROUPS = {f.get("weight_key", sid): f["family"]
                 for sid, f in {**FACTORS, **PIT_EXTRA}.items() if "family" in f}

# ── PIT table ──
_PIT_TABLE_PRODUCERS = [p for p, spec in PIT_PRODUCERS.items() if not spec.get("table")]


def _pit_cols_by_producer():
    out = {p: [] for p in ["base", *PIT_PRODUCERS]}
    for sid, f in FACTORS.items():
        if f.get("producer"):
            out[f["producer"]].append(pit_column(sid))
    for col, f in PIT_EXTRA.items():
        out[f["producer"]].append(col)
    return out


PIT_COLUMNS_BY_PRODUCER = _pit_cols_by_producer()
PIT_COLUMNS = ["sid", "snapshot_date", "cap_tier"] + [
    c for p in ["base", *_PIT_TABLE_PRODUCERS] for c in PIT_COLUMNS_BY_PRODUCER[p]]

# (min, max, allow_nan) per PIT column — out-of-range → NaN. Includes the sector-table
# columns (regulatory_score / macro_score).
VALIDATION_RANGES = {
    **{c: (*f["pit_range"], True) for c, f in PIT_EXTRA.items()},
    **{pit_column(sid): (*f["pit_range"], True) for sid, f in FACTORS.items() if "pit_range" in f},
}
PIT_COLUMN_TYPES = {"industry_id": "INTEGER", "piotroski_f": "INTEGER", "macd_bullish": "INTEGER"}


def discard_out_of_range(df, cols):
    """The range rule the validated backtest saw: ±inf and values outside a column's
    VALIDATION_RANGES become NaN — DISCARDED, never clipped. In place; returns
    {col: n_out_of_range}. Used by pit._validate_and_clean and, for the
    same quantities (LIVE_PIT_COLS), by the live screener."""
    n_out = {}
    for col in cols:
        rule = VALIDATION_RANGES.get(col)
        if col not in df.columns or rule is None:
            continue
        lo, hi, _allow_nan = rule
        df[col] = df[col].replace([np.inf, -np.inf], np.nan)
        bad = (df[col] < lo) | (df[col] > hi)
        n_out[col] = int(bad.sum())
        df.loc[bad, col] = np.nan
    return n_out

# --signal choices; the default run is every producer.
PIT_SIGNALS = list(PIT_PRODUCERS) + [a for s in PIT_PRODUCERS.values() for a in s.get("aliases", ())]

# Backtest: registry id → (v1 column, v2 column) for every IC-rankable factor in the
# daily_snapshots_pit panels. Sector-level, portfolio and CONTROL entries are not IC-ranked.
SIGNAL_COLUMN_MAP = {
    sid: (f.get("pit_column_v1"), f.get("pit_column_v2"))
    for sid, f in FACTORS.items()
    if f["cadence"] in ("monthly", "weekly") and f.get("bench") != "CONTROL"
    and (f.get("pit_column_v2") in PIT_COLUMNS or f.get("pit_column_v1"))
}
SIGNAL_COLUMN_MAP["_response"] = ("fwd_return_20d", "fwd_return_20d")

# ── Screener / live ──
# weight_key → the screener column it ranks (the tier-default entry) …
SCREENER_COLS = {f["weight_key"]: f["screener_col"] for f in FACTORS.values()
                 if "weight_key" in f and "tiers" not in f}
# … and per-tier overrides: {(weight_key, tier): column} (momentum → mom_12m in SMALL).
SCREENER_TIER_COLS = {(f["weight_key"], t): f["screener_col"] for f in FACTORS.values()
                      if "tiers" in f for t in f["tiers"]}
# Canonical registry id for each weight key (tier-default).
WEIGHT_KEY_TO_SIGNAL = {f["weight_key"]: sid for sid, f in FACTORS.items()
                        if "weight_key" in f and "tiers" not in f}
# pit_replay: PIT column → screener column, for replaying historical dates.
PIT_TO_SCREENER_COLS = {f["replay_col"]: f["screener_col"]
                        for f in {**FACTORS, **PIT_EXTRA}.values() if f.get("replay_col")}
# Everything score_universe reads, in _load_signals() shape.
SCREENER_INPUT_COLS = (
    ["sid", "ticker", "name", "sector", "cap_tier"]
    + list(dict.fromkeys([*SCREENER_COLS.values(), *SCREENER_TIER_COLS.values(), "penalty"]))
    + ["price_rows", "quarters_present", "fundamental_coverage"]
)
# Screener columns that ARE their factor's PIT quantity (same name in both, same
# function computes both) — the live screener applies the PIT range rule to them.
LIVE_PIT_COLS = [f["screener_col"] for sid, f in FACTORS.items()
                 if f.get("screener_col") and f["screener_col"] == f.get("replay_col") == pit_column(sid)]
# Plan 0005 eligibility: weight_key → {description, eligible_sql}.
SIGNAL_ELIGIBILITY = {f["weight_key"]: f["eligibility"] for f in FACTORS.values() if "eligibility" in f}


def signal_for(weight_key, tier=None):
    """Registry id a config weight key scores in `tier` (momentum → mom_12m_adj in SMALL).
    Keys with no registry entry map to themselves."""
    for f_id, f in FACTORS.items():
        if f.get("weight_key") == weight_key and tier in f.get("tiers", ()):
            return f_id
    return WEIGHT_KEY_TO_SIGNAL.get(weight_key, weight_key)


def weights(scheme="SIGNAL_WEIGHTS"):
    """{tier: {weight_key: weight}} with zero weights dropped."""
    return {t: {k: w for k, w in tw.items() if w} for t, tw in globals()[scheme].items()}


def wired_weight_keys(scheme="SIGNAL_WEIGHTS"):
    """Weight keys carrying a nonzero weight in some tier, in config order."""
    return list(dict.fromkeys(k for tw in weights(scheme).values() for k in tw))


def wired_pairs(scheme="SIGNAL_WEIGHTS"):
    """{(registry id, tier)} with a nonzero weight in `scheme`."""
    return {(signal_for(k, t), t) for t, tw in weights(scheme).items() for k in tw}


def wired_signal_ids(schemes=("SIGNAL_WEIGHTS",)):
    """Registry ids with a nonzero weight in any of `schemes`."""
    return {sid for s in schemes for sid, _ in wired_pairs(s)}


def status(signal_id):
    """COMPUTED lifecycle status: WIRED (nonzero production weight) · VARIANT (weighted
    only in a dry-run SIGNAL_WEIGHTS_RETURN/_SHARPE scheme) · else the factor's bench
    (LIBRARY / PROPOSED / BLOCKED / SUPERSEDED / CONTROL) · UNCLASSIFIED."""
    if signal_id in wired_signal_ids():
        return "WIRED"
    if signal_id in wired_signal_ids(WEIGHT_SCHEMES[1:]):
        return "VARIANT"
    return (FACTORS.get(signal_id) or PIT_EXTRA.get(signal_id) or {}).get("bench") or "UNCLASSIFIED"


def partition_check():
    """ADR 0017 partition: every factor is in exactly ONE of {weighted in some scheme,
    a bench}. Returns (missing, duplicated) — sorted id lists, both empty when it holds."""
    weighted = wired_signal_ids(WEIGHT_SCHEMES)
    missing = sorted(s for s, f in FACTORS.items() if s not in weighted and not f.get("bench"))
    duplicated = sorted(s for s, f in FACTORS.items() if s in weighted and f.get("bench"))
    return missing, duplicated


# ═══════════════════════ Renames (plan 0015 "rename a factor" = 2 places) ═══════════════════════
# {old: new} for a factor id and/or its PIT column. To rename: change the FACTORS key
# (and pit_column_v2 if explicit) in code, add the pair here, and run apply_renames()
# once per database (db migration). Entries stay forever — cheap, and an old DB copy
# still migrates. Idempotent: a pair whose old name is gone is a no-op.
RENAMES = {}
RENAME_PANEL = "daily_snapshots_pit"                          # a column per factor
RENAME_EVIDENCE = ("pit_ic_by_tier_v2", "factor_horizon_gate")   # rows keyed by signal id


def apply_renames(conn, renames=None):
    """Apply RENAMES (or `renames`) to an open sqlite3 connection and commit.
    Panel: ALTER TABLE … RENAME COLUMN old → new (raises if both columns exist — a
    human merges). Evidence: signal ids old → new; where the new id already has a row
    for the same key, that newer row wins and the old row is dropped.
    Returns [(kind, table, old, new, n)] for what changed."""
    renames = RENAMES if renames is None else renames
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    done = []
    for old, new in renames.items():
        if RENAME_PANEL in tables:
            cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{RENAME_PANEL}")')}
            if old in cols and new in cols:
                raise ValueError(f"{RENAME_PANEL} has both {old!r} and {new!r} — merge by hand")
            if old in cols:
                conn.execute(f'ALTER TABLE "{RENAME_PANEL}" RENAME COLUMN "{old}" TO "{new}"')
                done.append(("column", RENAME_PANEL, old, new, 1))
        for table in RENAME_EVIDENCE:
            if table not in tables:
                continue
            n = conn.execute(f'UPDATE OR IGNORE "{table}" SET signal = ? WHERE signal = ?',
                             (new, old)).rowcount
            n_dup = conn.execute(f'DELETE FROM "{table}" WHERE signal = ?', (old,)).rowcount
            if n or n_dup:
                done.append(("rows", table, old, new, n))
    conn.commit()
    return done
