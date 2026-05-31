"""
Alpha Signal v2 — Per-stock data lineage registry.

For any (sid, factor, date) tuple we want to answer: which source rows fed
into this value? Today's BAJA bug (mc_slug pointed to Bajaj Finance, so
analyst_consensus.price_target was wrong) lived in column-level provenance
inside a single table. Catching that class of bug needs three layers:

  1. STATIC factor lineage (FACTOR_LINEAGE) — declarative mapping of every
     canonical factor in `db.BACKTEST_SIGNALS` to its source reads. Sub-
     factors of the same producer share a parent via `inherits_from`;
     composites enumerate their constituents via `composite_of`. This is
     the source of truth — the drift validator in tools/data_sanity.py
     (`LINEAGE_REGISTRY_DRIFT`) ENFORCES that every BACKTEST_SIGNALS entry
     has a FACTOR_LINEAGE entry. Adding a new factor without lineage =
     CRITICAL on every health report.

  2. COLUMN-level provenance (TABLE_COLUMN_SOURCES) — for tables that
     blend multiple feeds at the column level. analyst_consensus is the
     canonical case (yfinance + Tickertape + MoneyControl co-write
     different columns), and stocks.mc_slug is the fragile bridge that
     caused today's contamination.

  3. DYNAMIC lineage (the `signal_lineage` DB table, populated by
     `db._emit_lineage`) — per-(sid, date, factor) records pointing at
     the exact source rows that contributed. Emitted by each signal
     module's `_compute_scores` for a gated set of SIDs (default: top-300
     from latest `daily_picks`, via `LINEAGE_SIDS` env var).

Factor status (informational — comes from the BACKTEST_SIGNALS verdict):
  - "model_active"  — appears in config.SIGNAL_WEIGHTS for ≥1 cap tier
  - "candidate"     — KEEP/WEAK verdict in pit_ic_by_tier_v2, queued for promotion
  - "library"       — registered in FACTOR_LIBRARY, awaiting validation depth
  - "computed"      — produced as a side-output (sector tilt, macro state)
  - "composite"     — built from other factors, no direct source reads

See docs/decisions/0027-per-stock-data-lineage.md.
"""

# ─────────────────────── Column-level provenance for mixed-source tables ───────────────────────

TABLE_COLUMN_SOURCES = {
    "analyst_consensus": {
        "total_analysts":          ["yfinance", "tickertape", "moneycontrol"],
        "buy_pct":                 ["yfinance_derived", "tickertape", "moneycontrol"],
        "price_target":            ["yfinance", "moneycontrol"],
        "price_target_median":     ["yfinance"],
        "price_target_high":       ["yfinance"],
        "price_target_low":        ["yfinance"],
        "recommendation_key":      ["yfinance"],
        "recommendation_mean":     ["yfinance"],
        "n_strong_buy":            ["yfinance"],
        "n_buy":                   ["yfinance"],
        "n_hold":                  ["yfinance"],
        "n_sell":                  ["yfinance"],
        "n_strong_sell":           ["yfinance"],
        "forward_eps":             ["tickertape"],
        "eps_growth_pct":          ["tickertape"],
        "forward_revenue":         ["tickertape"],
        "revenue_growth_pct":      ["tickertape"],
        "next_earnings_date":      ["yfinance"],
        "rating_mix_history":      ["yfinance"],
        "price_target_prev":       ["yfinance_computed"],
        "price_target_changed_at": ["yfinance_computed"],
        "pt_source":               ["yfinance"],
        "has_analyst_data":        ["yfinance", "tickertape", "moneycontrol"],
    },
    "stock_prices": {
        "close":  ["nse", "yfinance_NS_fallback", "yfinance_BO_fallback"],
        "volume": ["nse", "yfinance_NS_fallback", "yfinance_BO_fallback"],
        "delivery_pct": ["nse"],
    },
    # stocks.mc_slug — the BAJA failure mode. Fragile autosuggest bridge;
    # wrong slug poisons every MC-sourced column on that sid.
    "stocks": {
        "mc_slug": ["moneycontrol_autosuggest"],
    },
    "broker_recommendations": {
        "broker":       ["moneycontrol"],
        "reco_date":    ["moneycontrol"],
        "reco_type":    ["moneycontrol"],
        "target_price": ["moneycontrol"],
    },
    "forecast_history": {
        # See ADR 0020: forecast_history.value where metric='price' is
        # contaminated (current close, not PT). pt_revision_yoy DROPPED.
        "value":  ["tickertape"],
        "change": ["tickertape"],
    },
}


# ─────────────────────── Unit Contracts (Plan 0007 Phase 4 — Gate 5) ───────────────────────
# Declarative registry of expected units for (table, column). Producers and
# consumers reference this via validators.unit_contract — mismatches raise
# UnitMismatchError at the boundary (LOUD, not silent quarantine — a unit
# mismatch is a code bug, not data corruption).
#
# UNITS
#   pct_100       0..100 (or -100..+1000 for ratios)
#   ratio_1       0..1 (or -1..+10)
#   inr_crore     ₹ in crores
#   inr_lakh      ₹ in lakhs
#   inr_raw       ₹ raw rupees
#   days          calendar days
#   timestamp_iso ISO 8601 string
#   timestamp_unix Unix epoch seconds
#   sid           Tickertape SID (TEXT, opaque)
#   ticker        NSE ticker (TEXT, opaque)
#
# Adding a new entry below means the producer/consumer pair gets a runtime
# contract assertion. Don't add a unit you can't enforce — undeclared columns
# default to "trust the caller".
UNIT_CONTRACTS = {
    # ─── consensus_signals ───
    # pt_upside is canonically PERCENT (signals/consensus.py line 178 clips
    # to [-50, +150]). The %-vs-fraction bug class (CCAVENUE was an outlier
    # AT the % scale, not a unit mismatch — but the unit mismatch would be
    # if a future fetcher returned 0.45 (45% as ratio) and overwrote.
    ("consensus_signals", "pt_upside"):     "pct_100",
    ("consensus_signals", "eps_growth"):    "pct_100",
    ("consensus_signals", "revenue_growth"): "pct_100",
    ("consensus_signals", "consensus_signal"): "ratio_1",  # composite 0-1
    # ─── analyst_consensus ───
    ("analyst_consensus", "buy_pct"):       "pct_100",
    ("analyst_consensus", "price_target"):  "inr_raw",
    ("analyst_consensus", "forward_eps"):   "inr_raw",
    ("analyst_consensus", "eps_growth_pct"): "pct_100",
    ("analyst_consensus", "revenue_growth_pct"): "pct_100",
    # ─── stock_prices ───
    ("stock_prices", "close"):              "inr_raw",
    ("stock_prices", "open"):               "inr_raw",
    ("stock_prices", "high"):               "inr_raw",
    ("stock_prices", "low"):                "inr_raw",
    ("stock_prices", "delivery_pct"):       "pct_100",
    # ─── banking_metrics ───
    ("banking_metrics", "gross_npa_pct"):   "pct_100",
    ("banking_metrics", "net_npa_pct"):     "pct_100",
    ("banking_metrics", "nim_pct"):         "pct_100",
    ("banking_metrics", "roa_pct"):         "pct_100",
    ("banking_metrics", "car_pct"):         "pct_100",
    ("banking_metrics", "crar_pct"):        "pct_100",
    ("banking_metrics", "cost_of_funds_pct"): "pct_100",
    ("banking_metrics", "casa_pct"):        "pct_100",
    ("banking_metrics", "interest_earned"): "inr_crore",
    ("banking_metrics", "net_interest_income"): "inr_crore",
    ("banking_metrics", "net_profit"):      "inr_crore",
    ("banking_metrics", "advances"):        "inr_crore",
    ("banking_metrics", "deposits"):        "inr_crore",
    # ─── daily_picks ───
    ("daily_picks", "final_score"):         "ratio_1",
    ("daily_picks", "base_score"):          "ratio_1",
    ("daily_picks", "weight_coverage"):     "ratio_1",
    ("daily_picks", "eligible_coverage"):   "ratio_1",
    ("daily_picks", "fundamental_coverage"): "ratio_1",
    # ─── piotroski_scores ───
    # f_score is an integer 0-9 — neither ratio nor percent. Omit from the
    # unit registry; consumers know it's the canonical Piotroski 0-9 score.
    # ─── stocks ───
    ("stocks", "adtv_6m_cr"):               "inr_crore",
    ("stocks", "market_cap_cr"):            "inr_crore",
    ("stocks", "shares_outstanding"):       "ratio_1",   # raw count
    # ─── mf_metrics ───
    ("mf_metrics", "composite_score"):      "pct_100",   # 0-100 absolute quality score
    ("mf_metrics", "ret_1y"):               "pct_100",
    ("mf_metrics", "ret_3y_cagr"):          "pct_100",
    ("mf_metrics", "max_drawdown"):         "pct_100",
}


# ─────────────────────── Read-spec builders ───────────────────────


def _stocks(cols=("sid", "sector", "cap_tier"), contribution="stock_metadata"):
    return {"table": "stocks", "cols": list(cols), "key": ["sid"], "select": "row",
            "contribution": contribution}


def _prices_latest(contribution="current_price"):
    return {"table": "stock_prices", "cols": ["close"], "key": ["sid", "date"],
            "select": "latest_per_sid", "contribution": contribution}


def _prices_window(days, cols=("close",), contribution=None):
    return {"table": "stock_prices", "cols": list(cols), "key": ["sid", "date"],
            "select": "window", "filter": f"last {days} trading days",
            "contribution": contribution or f"{days}d_window"}


def _fund(items, n=2, contribution=None):
    return {"table": "fundamentals_screener",
            "cols": ["sid", "period_end", "line_item", "value"],
            "key": ["sid", "period_end", "line_item"],
            "select": "last_n_periods", "n": n,
            "filter": "period_type='annual' AND line_item IN (...)",
            "line_items": list(items),
            "contribution": contribution or f"last_{n}_annual_periods"}


def _qi(cols, n=4, reporting_preference="consolidated"):
    return {"table": "quarterly_income", "cols": list(cols),
            "key": ["sid", "end_date", "reporting"], "select": "last_n_periods", "n": n,
            "filter": f"prefer reporting={reporting_preference}"}


def _bs(cols, n=2):
    return {"table": "annual_balance_sheet", "cols": list(cols),
            "key": ["sid", "period"], "select": "last_n_periods", "n": n}


def _cf(cols, n=1):
    return {"table": "annual_cash_flow", "cols": list(cols),
            "key": ["sid", "period"], "select": "last_n_periods", "n": n}


# ─────────────────────── Factor → source mapping (all 63 canonical factors) ───────────────────────
#
# Keyed by `signal` field of db.BACKTEST_SIGNALS.
# Three entry shapes:
#   (A) Full read spec:  {"status":..., "module":..., "reads":[...], ...}
#   (B) Sub-factor:      {"inherits_from": "<parent_factor>", "sub_contribution": "..."}
#   (C) Composite:       {"composite_of": [<factor>, <factor>, ...], "weights": {...}}

FACTOR_LINEAGE = {

    # ════════════════════════════ Value family ════════════════════════════
    "earnings_yield": {
        "status": "model_active", "module": "signals/earnings_yield.py",
        "reads": [
            _qi(["revenue", "net_income", "pbt", "interest"], n=4),
            {"table": "stocks", "cols": ["sid", "shares_outstanding"], "key": ["sid"], "select": "row"},
            _prices_latest(),
        ],
        "sector_exclusions": [],
    },
    "book_to_price": {
        "status": "model_active", "module": "scoring/screener.py (inline)",
        "reads": [
            {"table": "stocks", "cols": ["sid", "market_cap_cr"], "key": ["sid"], "select": "row"},
            _bs(["total_assets", "long_term_debt", "current_liabilities", "shares_outstanding"], n=1),
        ],
        "sector_exclusions": [],
    },
    "position_52w": {
        "status": "library", "module": "scoring/screener.py (inline)",
        "reads": [_prices_window(252, contribution="52w_high_low")],
        "sector_exclusions": [],
    },
    "value_composite": {
        "status": "composite",
        "composite_of": ["earnings_yield", "book_to_price", "position_52w"],
    },

    # ════════════════════════════ Quality / Forensic / Accruals ════════════════════════════
    "piotroski_f_score": {
        "status": "model_active", "module": "signals/piotroski.py",
        "reads": [
            _qi(["revenue", "net_income", "pbt", "interest"], n=8),
            _bs(["total_assets", "current_assets", "current_liabilities",
                 "long_term_debt", "shares_outstanding"], n=2),
            _cf(["operating_cash_flow"], n=1),
            _stocks(("sid", "sector"), contribution="sector_exclusion_check"),
        ],
        "sector_exclusions": ["Financials"],
    },
    "m_score": {
        "status": "library", "module": "signals/forensic.py",
        "reads": [
            _qi(["revenue", "net_income", "pbt", "depreciation"], n=8),
            _bs(["total_assets", "current_assets", "receivables", "inventory"], n=2),
            _cf(["operating_cash_flow"], n=1),
            _stocks(("sid", "sector")),
        ],
        "sector_exclusions": ["Financials"],
    },
    "z_score": {
        "status": "library", "module": "signals/forensic.py",
        "reads": [
            _bs(["total_assets", "current_assets", "current_liabilities", "long_term_debt"], n=2),
            _cf(["operating_cash_flow"], n=1),
            _stocks(("sid", "sector")),
        ],
        "sector_exclusions": ["Financials"],
    },
    "bs_accruals_ratio": {
        "status": "library", "module": "signals/accruals.py",
        "reads": [
            _bs(["current_assets", "current_liabilities", "cash_equivalents"], n=2),
            _cf(["capex", "depreciation"], n=1),
        ],
        "sector_exclusions": ["Financials"],
    },
    "cf_accruals_ratio": {
        "status": "library", "module": "signals/accruals.py",
        "reads": [
            _qi(["net_income"], n=4),
            _cf(["operating_cash_flow"], n=1),
            _bs(["total_assets"], n=1),
        ],
        "sector_exclusions": ["Financials"],
    },
    "earnings_persistence": {
        "status": "library", "module": "signals/earnings_yield.py (derivative)",
        "reads": [_qi(["net_income"], n=8, reporting_preference="consolidated")],
        "sector_exclusions": [],
    },
    "earnings_beat_rate": {
        "status": "library", "module": "signals/earnings_yield.py (derivative)",
        "reads": [_qi(["net_income"], n=8)],
        "sector_exclusions": [],
    },
    "roe": {
        "status": "library", "module": "scoring/screener.py (inline)",
        "reads": [_qi(["net_income"], n=4), _bs(["total_equity"], n=1)],
        "sector_exclusions": [],
    },
    "roa": {
        "status": "library", "module": "scoring/screener.py (inline)",
        "reads": [_qi(["net_income"], n=4), _bs(["total_assets"], n=1)],
        "sector_exclusions": [],
    },
    "debt_to_equity": {
        "status": "library", "module": "scoring/screener.py (inline)",
        "reads": [_bs(["long_term_debt", "total_equity"], n=1)],
        "sector_exclusions": ["Financials"],
    },
    "profit_margin": {
        "status": "library", "module": "scoring/screener.py (inline)",
        "reads": [_qi(["revenue", "net_income"], n=4)],
        "sector_exclusions": [],
    },
    "quality_composite": {
        "status": "composite",
        "composite_of": ["roe", "debt_to_equity", "profit_margin"],
    },

    # ════════════════════════════ Growth ════════════════════════════
    "revenue_growth_yoy": {
        "status": "library", "module": "scoring/screener.py (inline)",
        "reads": [_qi(["revenue"], n=8)],
        "sector_exclusions": [],
    },
    "eps_growth_yoy": {
        "status": "library", "module": "scoring/screener.py (inline)",
        "reads": [_qi(["net_income"], n=8),
                  _bs(["shares_outstanding"], n=1)],
        "sector_exclusions": [],
    },
    "growth_composite": {
        "status": "composite",
        "composite_of": ["revenue_growth_yoy", "eps_growth_yoy"],
    },

    # ════════════════════════════ Momentum (price-based) ════════════════════════════
    "mom_6m_adj": {
        "status": "library", "module": "signals/momentum.py",
        "reads": [_prices_window(126, contribution="6m_minus_1m_return")],
        "sector_exclusions": [],
    },
    "mom_12m_adj": {
        "status": "model_active", "module": "signals/momentum.py",
        "reads": [_prices_window(252, contribution="12m_minus_1m_return")],
        "sector_exclusions": [],
    },
    "macd_signal": {
        "status": "library", "module": "signals/momentum.py",
        "reads": [_prices_window(252, contribution="ema_12_26_9")],
        "sector_exclusions": [],
    },
    "momentum_composite": {
        "status": "composite",
        "composite_of": ["mom_6m_adj", "mom_12m_adj"],
    },

    # ════════════════════════════ Shareholding / Insider ════════════════════════════
    "promoter_qoq": {
        "status": "model_active", "module": "signals/promoter.py",
        "reads": [
            {"table": "shareholding", "cols": ["promoter_pct"],
             "key": ["sid", "period_end"], "select": "last_n_periods", "n": 2,
             "contribution": "qoq_promoter_delta"},
            _stocks(("sid", "cap_tier")),
        ],
        "sector_exclusions": [],
    },
    "promoter_trend_4q": {
        "status": "library", "module": "signals/promoter.py",
        "reads": [
            {"table": "shareholding", "cols": ["promoter_pct"],
             "key": ["sid", "period_end"], "select": "last_n_periods", "n": 5,
             "contribution": "trend_slope_5q"},
        ],
        "sector_exclusions": [],
    },
    "pledge_quality": {
        "status": "library", "module": "signals/promoter.py",
        "reads": [
            {"table": "shareholding", "cols": ["promoter_pledged_pct"],
             "key": ["sid", "period_end"], "select": "last_n_periods", "n": 4,
             "contribution": "pledge_level_+_trend"},
        ],
        "sector_exclusions": [],
    },
    "insider_signal": {
        "status": "candidate", "module": "signals/insider_signal.py",
        "reads": [
            {"table": "insider_trades",
             "cols": ["sid", "trade_date", "person_category", "transaction_type", "value_lakhs"],
             "key": ["sid", "trade_date", "person_category", "transaction_type"],
             "select": "all", "filter": "last 90d",
             "contribution": "category_weighted_net_flow"},
            _stocks(("sid",)),
        ],
        "sector_exclusions": [],
        "validation": {"weekly_NW_t": None, "tier": None},   # SMALL t≈DROP per current PIT
    },

    # ════════════════════════════ Smart money / Micro-flow ════════════════════════════
    "avg_delivery_pct_30d": {
        "status": "candidate", "module": "signals/smart_money.py (sub: delivery_score)",
        "reads": [
            {"table": "stock_prices", "cols": ["delivery_pct"],
             "key": ["sid", "date"], "select": "window",
             "filter": "last 30d", "contribution": "30d_mean_delivery_pct"},
            _stocks(("sid", "cap_tier")),
        ],
        "sector_exclusions": [],
        "validation": {"weekly_NW_t": 4.21, "tier": "SMALL"},
    },
    "delivery_anomaly_z": {
        "status": "candidate", "module": "signals/smart_money.py (sub: anomaly_z)",
        "reads": [
            {"table": "stock_prices", "cols": ["delivery_pct"],
             "key": ["sid", "date"], "select": "window",
             "filter": "last 90d", "contribution": "z_score_of_30d_vs_90d_baseline"},
            _stocks(("sid", "cap_tier")),
        ],
        "sector_exclusions": [],
        "validation": {"weekly_NW_t": 4.11, "tier": "SMALL"},
    },
    "bulk_deal_signal": {
        "status": "candidate", "module": "signals/smart_money.py (sub: bulk_score)",
        "reads": [
            {"table": "bulk_deals",
             "cols": ["sid", "deal_date", "client_name", "buy_sell", "qty"],
             "key": ["sid", "deal_date", "client_name"], "select": "all",
             "filter": "last 90d", "contribution": "net_qty_by_qib_repeat_buyer"},
            _prices_window(90, contribution="adv_normaliser"),
            _stocks(("sid", "cap_tier")),
        ],
        "sector_exclusions": [],
        "validation": {"weekly_NW_t": 2.56, "tier": "SMALL"},
    },
    "short_selling_signal": {
        "status": "library", "module": "signals/smart_money.py (sub: short_score)",
        "reads": [
            {"table": "short_selling_data",
             "cols": ["sid", "short_date", "quantity"],
             "key": ["sid", "short_date"], "select": "all", "filter": "last 30d",
             "contribution": "short_qty_vs_adv"},
            _prices_window(30, contribution="adv_normaliser"),
        ],
        "sector_exclusions": [],
    },
    "fii_dii_cash_net": {
        "status": "library", "module": "(sector-level, applied to all stocks in sector)",
        "reads": [
            {"table": "fii_dii_cash_flow", "cols": ["net_value_cr", "category"],
             "key": ["date", "category"], "select": "window", "filter": "last 30d",
             "contribution": "sector_flow"},
        ],
        "sector_exclusions": [],
    },
    "fii_dii_fno_positioning": {
        "status": "library", "module": "(market-level signal)",
        "reads": [
            {"table": "fii_dii_positioning",
             "cols": ["future_index_long", "future_index_short", "option_index_call_long",
                      "option_index_put_long", "client_type"],
             "key": ["date", "client_type"], "select": "window", "filter": "last 30d",
             "contribution": "fii_net_positioning"},
        ],
        "sector_exclusions": [],
    },

    # ════════════════════════════ Track 2 — Financial sub-model (Banks + NBFCs) ════════════════════════════
    # Financial-ONLY factors (inverse of the usual sector_exclusions=["Financials"]):
    # they run exclusively on industry IN ("Banks", "NBFCs / Finance"). Shared read
    # spec across all three (per signals/financial_signal.py:_load_inputs) — latest
    # knowable quarterly + latest knowable annual row per sid from banking_metrics,
    # z-scored within (industry, cap_tier). PIT filing lags: 60d quarterly, 75d annual.
    "financial_quality": {
        "status": "candidate", "module": "signals/financial_signal.py",
        "reads": [
            {"table": "banking_metrics",
             "cols": ["gross_npa_pct", "net_npa_pct", "interest_earned",
                      "net_interest_income", "net_profit"],
             "key": ["sid", "period_end", "period_type"],
             "select": "latest_quarterly_per_sid",
             "filter": "period_type='quarterly' AND period_end ≤ pit_date − 60d",
             "contribution": "asset_quality(direction=lower)_+_profitability"},
            {"table": "banking_metrics",
             "cols": ["cost_of_funds_pct"],
             "key": ["sid", "period_end", "period_type"],
             "select": "latest_annual_per_sid",
             "filter": "period_type='annual' AND period_end ≤ pit_date − 75d",
             "contribution": "funding_cost"},
            _stocks(("sid", "industry", "cap_tier"), contribution="financial_segment"),
        ],
        "sector_exclusions": [],
        "note": "Financials-only (Banks + NBFCs). SMALL-tier direction (low NPA = strong franchise).",
        "validation": {"weekly_NW_t": -1.88, "tier": "SMALL"},   # WEAK; on bench, re-test ~Q1 FY27
    },
    "financial_recovery": {
        "status": "candidate", "module": "signals/financial_signal.py",
        "reads": [
            {"table": "banking_metrics",
             "cols": ["gross_npa_pct", "net_npa_pct", "interest_earned",
                      "net_interest_income", "net_profit"],
             "key": ["sid", "period_end", "period_type"],
             "select": "latest_quarterly_per_sid",
             "filter": "period_type='quarterly' AND period_end ≤ pit_date − 60d",
             "contribution": "asset_quality(direction=higher)_+_profitability"},
            {"table": "banking_metrics",
             "cols": ["cost_of_funds_pct"],
             "key": ["sid", "period_end", "period_type"],
             "select": "latest_annual_per_sid",
             "filter": "period_type='annual' AND period_end ≤ pit_date − 75d",
             "contribution": "funding_cost"},
            _stocks(("sid", "industry", "cap_tier"), contribution="financial_segment"),
        ],
        "sector_exclusions": [],
        "note": "Financials-only (Banks + NBFCs). LARGE/MID-tier direction (high NPA = mean-reversion).",
        "validation": {"weekly_NW_t": 1.55, "tier": "MID"},   # WEAK; on bench, re-test ~Q1 FY27
    },
    "financial_signal": {
        "status": "superseded", "module": "signals/financial_signal.py",
        "reads": [
            {"table": "banking_metrics",
             "cols": ["gross_npa_pct", "net_npa_pct", "interest_earned",
                      "net_interest_income", "net_profit", "cost_of_funds_pct"],
             "key": ["sid", "period_end", "period_type"],
             "select": "latest_quarterly_+_annual_per_sid",
             "contribution": "back_compat_alias_=_financial_quality"},
            _stocks(("sid", "industry", "cap_tier"), contribution="financial_segment"),
        ],
        "sector_exclusions": [],
        "note": "SUPERSEDED 2026-05-29 by financial_quality + financial_recovery split "
                "(ADR 0032). Kept as the alias column (= financial_quality) so historical "
                "PIT and the optimizer entry survive; not routed live.",
    },

    # ════════════════════════════ Analyst consensus + PT family ════════════════════════════
    # `consensus` doesn't appear in BACKTEST_SIGNALS by that name — the
    # consumer-facing factors are pt_upside, eps_growth_yoy (consensus
    # version uses analyst_consensus.eps_growth_pct), pt_revision_yoy
    # (DROPPED 2026-05-23), eps_revision_yoy, consensus_signal_combined.
    "pt_upside": {
        "status": "model_active", "module": "signals/consensus.py (sub: pt_up_score)",
        "reads": [
            {"table": "analyst_consensus",
             "cols": ["price_target", "total_analysts"],
             "key": ["sid"], "select": "row",
             "filter": "has_analyst_data=1 AND price_target NOT NULL"},
            _prices_latest(contribution="pt_upside_denominator"),
            _stocks(("sid", "cap_tier"), contribution="ranking_segment"),
        ],
        "sector_exclusions": [],
        # CRITICAL: this factor reads analyst_consensus.price_target which
        # has column-level provenance — see TABLE_COLUMN_SOURCES. Today's
        # BAJA bug contaminated this field via wrong stocks.mc_slug.
    },
    "pt_revision_yoy": {
        "status": "library", "module": "DROPPED 2026-05-23 (ADR 0020)",
        "reads": [
            {"table": "forecast_history",
             "cols": ["value", "date"],
             "key": ["sid", "date"],
             "select": "all",
             "filter": "metric='price' AND year-end snapshots only",
             "contribution": "contaminated_currently — see ADR 0020"},
        ],
        "sector_exclusions": [],
    },
    "eps_revision_yoy": {
        "status": "library", "module": "(awaiting 12mo analyst_consensus_snapshots)",
        "reads": [
            {"table": "forecast_history",
             "cols": ["value", "change", "date"],
             "key": ["sid", "date"],
             "select": "all", "filter": "metric='eps'",
             "contribution": "yoy_revision"},
        ],
        "sector_exclusions": [],
    },
    "consensus_signal_combined": {
        "status": "library", "module": "signals/consensus.py (degraded — eps only)",
        "reads": [
            {"table": "analyst_consensus",
             "cols": ["eps_growth_pct", "total_analysts"],
             "key": ["sid"], "select": "row",
             "filter": "has_analyst_data=1"},
            _stocks(("sid", "cap_tier")),
        ],
        "sector_exclusions": [],
    },

    # ════════════════════════════ News / Sentiment ════════════════════════════
    "sentiment_7d": {
        "status": "candidate", "module": "signals/sentiment.py",
        "reads": [
            {"table": "news_articles",
             "cols": ["article_id", "title", "summary", "published_at"],
             "key": ["article_id"], "select": "window", "filter": "last 7d"},
            {"table": "news_article_stocks",
             "cols": ["article_id", "sid"], "key": ["article_id", "sid"], "select": "all",
             "contribution": "article_sid_linkage"},
            {"table": "sentiment_scores",
             "cols": ["article_id", "score"], "key": ["article_id"], "select": "all",
             "contribution": "per_article_sentiment"},
            _stocks(("sid",)),
        ],
        "sector_exclusions": [],
        "validation": {"weekly_NW_t": -3.88, "tier": "LARGE"},   # preliminary, n=4
    },
    "news_volume": {
        "status": "library", "module": "signals/sentiment.py (sub: volume)",
        "reads": [
            {"table": "news_article_stocks",
             "cols": ["article_id", "sid"], "key": ["article_id", "sid"], "select": "all",
             "filter": "joined with news_articles WHERE published_at >= today-7d",
             "contribution": "article_count_per_sid"},
            _stocks(("sid",)),
        ],
        "sector_exclusions": [],
    },

    # ════════════════════════════ Regulatory / Macro ════════════════════════════
    "regulatory_sector_signal": {
        "status": "computed", "module": "signals/regulatory.py",
        "reads": [
            {"table": "regulatory_events", "cols": ["sector", "published_at"],
             "key": ["event_id"], "select": "all", "filter": "last 30d",
             "contribution": "raw_event_count"},
            {"table": "regulatory_signals", "cols": ["direction", "magnitude", "confidence"],
             "key": ["event_id"], "select": "all",
             "contribution": "classified_tilt"},
            _stocks(("sid", "sector")),
        ],
        "sector_exclusions": [],
    },
    "macro_sector_signal": {
        "status": "computed", "module": "signals/macro.py",
        "reads": [
            {"table": "macro_history", "cols": ["value", "date"],
             "key": ["indicator", "date"], "select": "window",
             "filter": "last 90d per indicator"},
            {"table": "macro_indicator_meta", "cols": ["indicator", "direction"],
             "key": ["indicator"], "select": "all"},
            {"table": "macro_sector_map", "cols": ["sector", "direction", "weight"],
             "key": ["indicator", "sector"], "select": "all"},
            _stocks(("sid", "sector")),
        ],
        "sector_exclusions": [],
    },

    "sector_momentum": {
        "status": "candidate", "module": "signals/sector_momentum.py",
        "reads": [
            {"table": "stock_prices", "cols": ["close"],
             "key": ["sid", "date"], "select": "window",
             "filter": "last 252d", "contribution": "sector_cap_weighted_return"},
            {"table": "macro_history", "cols": ["value", "date"],
             "key": ["indicator_id", "date"], "select": "window",
             "filter": "nifty50 last 252d", "contribution": "benchmark_return"},
            _stocks(("sid", "sector", "market_cap_cr")),
        ],
        "sector_exclusions": [],
    },

    # ════════════════════════════ Fundamentals_screener factors (16) ════════════════════════════
    "roic": {
        "status": "candidate", "module": "signals/roic.py",
        "reads": [_fund(["Profit before tax", "Interest", "Tax", "Equity Share Capital",
                         "Reserves", "Borrowings"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "roiic": {
        "status": "library", "module": "signals/roiic.py",
        "reads": [_fund(["Profit before tax", "Tax", "Interest", "Equity Share Capital",
                         "Reserves", "Borrowings"], n=6),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "fcf_yield": {
        "status": "candidate", "module": "signals/fcf_yield.py",
        "reads": [_fund(["Cash from Operating Activity", "Net Block",
                         "Capital Work in Progress", "Depreciation",
                         "No. of Equity Shares"], n=2),
                  _prices_latest(),
                  _stocks(("sid", "sector", "market_cap_cr"))],
        "sector_exclusions": ["Financials"],
    },
    "ccc": {
        "status": "library", "module": "signals/cash_conversion_cycle.py",
        "reads": [_fund(["Sales", "Receivables", "Inventory", "Trade Payables"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "margin_slope": {
        "status": "library", "module": "signals/operating_margin_trend.py",
        "reads": [_fund(["Sales", "Profit before tax", "Interest"], n=3),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "wc_intensity": {
        "status": "library", "module": "signals/working_capital_intensity.py",
        "reads": [_fund(["Sales", "Receivables", "Inventory", "Trade Payables"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "dso_change_yoy": {
        "status": "candidate", "module": "signals/dso_change_yoy.py",
        "reads": [_fund(["Sales", "Receivables"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "dio_change_yoy": {
        "status": "library", "module": "signals/dio_change_yoy.py",
        "reads": [_fund(["Sales", "Inventory"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "nwc_to_revenue": {
        "status": "candidate", "module": "signals/nwc_to_revenue.py",
        "reads": [_fund(["Sales", "Receivables", "Inventory", "Trade Payables"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "sloan_accruals_full": {
        "status": "library", "module": "signals/sloan_accruals_full.py",
        "reads": [_fund(["Receivables", "Inventory", "Trade Payables",
                         "Depreciation", "Total"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "sga_to_revenue_change": {
        "status": "library", "module": "signals/sga_to_revenue_change.py",
        "reads": [_fund(["Sales", "Selling and admin"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "fcf_margin": {
        "status": "library", "module": "signals/fcf_margin.py",
        "reads": [_fund(["Sales", "Cash from Operating Activity", "Net Block",
                         "Capital Work in Progress", "Depreciation"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "capex_to_dep": {
        "status": "library", "module": "signals/capex_to_dep.py",
        "reads": [_fund(["Net Block", "Capital Work in Progress", "Depreciation"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "goodwill_to_assets": {
        "status": "library", "module": "signals/goodwill_to_assets.py",
        "reads": [_fund(["Intangible Assets", "Total"], n=1),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "debt_structure": {
        "status": "library", "module": "signals/debt_structure.py",
        "reads": [_fund(["Long term Borrowings", "Borrowings"], n=1),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "asset_tangibility": {
        "status": "library", "module": "signals/asset_tangibility.py",
        "reads": [_fund(["Net Block", "Total"], n=1),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "interest_coverage": {
        "status": "library", "module": "signals/interest_coverage.py",
        "reads": [_fund(["Profit before tax", "Interest"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "revenue_cv_5y": {
        "status": "library", "module": "signals/revenue_cv.py",
        "reads": [_fund(["Sales"], n=6),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": [],
    },
    "relative_turnover": {
        "status": "library", "module": "signals/sales_growth_relative.py (related)",
        "reads": [_fund(["Sales", "Inventory"], n=1),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": [],
    },
    "relative_growth": {
        "status": "library", "module": "signals/sales_growth_relative.py",
        "reads": [_fund(["Sales"], n=3),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": [],
    },
    "share_momentum": {
        "status": "library", "module": "signals/share_momentum.py",
        "reads": [_prices_window(252, contribution="pit_adjusted_price"),
                  _fund(["No. of Equity Shares"], n=2,
                        contribution="share_count_pit"),
                  _stocks(("sid", "sector", "market_cap_cr"))],
        "sector_exclusions": [],
    },

    # ════════════════════════════ Top-level composites ════════════════════════════
    "screener_final_composite": {
        "status": "composite",
        "composite_of": [
            "value_composite", "quality_composite", "growth_composite",
            "momentum_composite", "pt_upside", "piotroski_f_score",
            "promoter_qoq", "delivery_anomaly_z", "bulk_deal_signal",
        ],
        "weight_lookup": "config.SIGNAL_WEIGHTS (per cap-tier)",
    },
}


# ─────────────────────── Helpers ───────────────────────


def get_factor_lineage(factor_name):
    """Return lineage entry for a factor (resolving inherits_from chains)."""
    entry = FACTOR_LINEAGE.get(factor_name)
    if not entry:
        return None
    if "inherits_from" in entry:
        parent = FACTOR_LINEAGE.get(entry["inherits_from"])
        if parent:
            merged = dict(parent)
            merged["sub_contribution"] = entry.get("sub_contribution")
            merged["inherits_from"] = entry["inherits_from"]
            return merged
    return entry


def get_column_sources(table_name, column_name):
    """Return list of sources for a mixed-source table column.

    Returns None for single-source tables (caller treats as "single implicit source").
    """
    table_map = TABLE_COLUMN_SOURCES.get(table_name)
    if not table_map:
        return None
    return table_map.get(column_name)


def get_factor_status(factor_name):
    """Quick lookup: factor's tier label (model_active/candidate/library/computed/composite)."""
    entry = FACTOR_LINEAGE.get(factor_name) or {}
    return entry.get("status", "unknown")


def factors_by_status(status):
    """Return list of factor names matching a given status tag."""
    return [name for name, entry in FACTOR_LINEAGE.items()
            if entry.get("status") == status]


def lineage_active_sids():
    """Return the SID set to emit dynamic lineage for.

    Default: top-300 by composite_score from latest daily_picks snapshot.
    Override with LINEAGE_SIDS env var (comma-separated) for testing.

    Returns set or None — None means "emit lineage for every sid the signal
    happens to score" (use with care; full-universe emission can balloon
    the signal_lineage table).
    """
    import os
    raw = os.environ.get("LINEAGE_SIDS")
    if raw:
        return set(s.strip() for s in raw.split(",") if s.strip())

    from db import read_sql
    try:
        df = read_sql(
            "SELECT sid FROM daily_picks "
            "WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks) "
            "ORDER BY final_score DESC LIMIT 300"
        )
        if df.empty:
            return None
        return set(df["sid"].tolist())
    except Exception:
        return None


def missing_factors():
    """Return list of BACKTEST_SIGNALS factors that lack a FACTOR_LINEAGE entry.

    Used by the LINEAGE_REGISTRY_DRIFT sanity check — any new factor added
    to BACKTEST_SIGNALS without a corresponding lineage entry fires CRITICAL.
    """
    from db import BACKTEST_SIGNALS
    declared = {s["signal"] for s in BACKTEST_SIGNALS}
    in_registry = set(FACTOR_LINEAGE.keys())
    return sorted(declared - in_registry)


def orphan_factors():
    """Factors in FACTOR_LINEAGE that no longer exist in BACKTEST_SIGNALS.

    Surfaces as INFO — drift in the other direction (a factor was removed
    from the canonical list but lineage entry was not cleaned up).
    """
    from db import BACKTEST_SIGNALS
    declared = {s["signal"] for s in BACKTEST_SIGNALS}
    in_registry = set(FACTOR_LINEAGE.keys())
    return sorted(in_registry - declared)
