"""
Alpha Signal v2 — Per-stock data lineage registry.

For any (sid, factor, date) tuple we want to answer: which source rows fed
into this value? Today's BAJA bug (mc_slug pointed to Bajaj Finance, so
analyst_consensus.price_target was wrong) lived in column-level provenance
inside a single table. Catching that class of bug needs three layers:

  1. STATIC factor lineage (FACTOR_LINEAGE) — DERIVED for every factors.FACTORS
     key: table-level reads from the entry's `source_tables` (its PIT producer's
     input tables), plus the column-level / sector-exclusion detail in
     LINEAGE_DETAIL below. Composites enumerate constituents via `composite_of`.
     A factor cannot lack lineage (no drift check needed — plan 0015 Phase 6).

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
  - "model_active"  — carries a nonzero weight (factors.SIGNAL_WEIGHTS) in ≥1 tier
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
    # MISNAMED: the values are RUPEES (frozen v1 universe.csv snapshot, April 2026,
    # NULL for 726 stocks) — verified 2026-09-27 (RELIANCE 1.83e13). scoring/segment.py
    # computes a fresh ₹-crore market cap instead of reading this column.
    ("stocks", "market_cap_cr"):            "inr_raw",
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


# ─────────────────────── Factor lineage: only what the registry can't say ───────────────────────
#
# The TABLE-level reads of every factor are stated once, in factors.FACTORS
# `source_tables` (by default its PIT producer's input tables — factors.
# producer_tables, checked against pit.RAW_SQL by a test). FACTOR_LINEAGE below is
# DERIVED from it for every registry key, so a factor can never lack lineage
# (the old LINEAGE_REGISTRY_DRIFT check is vacuous) and lineage can never claim a
# table the code doesn't read. LINEAGE_DETAIL keeps only the genuinely extra facts:
#   reads              column-level specs (cols/key/select/filter/line_items) for SOME
#                      of the factor's tables — a table without a spec gets a bare one;
#                      a spec for a table outside source_tables fails the tests
#   sector_exclusions  sectors the factor is structurally N/A for      [default: []]
#   module             only for factors with no PIT producer            [default: pit.<fn>]
#   composite_of       constituents of a composite factor
#   validation / note  free-text evidence pointers
# Keyed by the factors.FACTORS id.

LINEAGE_DETAIL = {

    # ════════════════════════════ Value family ════════════════════════════
    "earnings_yield": {
        "reads": [
            _qi(["eps"], n=4),
            _prices_latest(),
        ],
    },
    "book_to_price": {
        "reads": [
            _bs(["total_assets", "long_term_debt", "current_liabilities", "shares_outstanding"], n=1),
        ],
    },
    "position_52w": {
        "reads": [_prices_window(252, contribution="52w_high_low")],
    },
    "value_composite": {
        "composite_of": ["earnings_yield", "book_to_price", "position_52w"],
    },

    # ════════════════════════════ Quality / Forensic / Accruals ════════════════════════════
    "piotroski_f_score": {
        "reads": [
            _qi(["revenue", "net_income", "operating_expenses"], n=8),
            _bs(["total_assets", "current_assets", "current_liabilities",
                 "long_term_debt", "shares_outstanding"], n=2),
            _cf(["operating_cash_flow"], n=1),
            _stocks(("sid", "sector"), contribution="sector_exclusion_check"),
        ],
        "sector_exclusions": ["Financials"],
    },
    "m_score": {
        "reads": [
            _qi(["revenue", "net_income", "pbt"], n=8),
            _bs(["total_assets", "current_assets", "receivables"], n=2),
            _cf(["operating_cash_flow"], n=1),
            _stocks(("sid", "sector")),
        ],
        "sector_exclusions": ["Financials"],
    },
    "z_score": {
        "reads": [
            _bs(["total_assets", "current_assets", "current_liabilities", "long_term_debt"], n=2),
            _cf(["operating_cash_flow"], n=1),
            _stocks(("sid", "sector")),
        ],
        "sector_exclusions": ["Financials"],
    },
    "bs_accruals_ratio": {
        "reads": [
            _bs(["current_assets", "current_liabilities", "cash_and_equivalents"], n=2),
            _cf(["capex"], n=1),
        ],
        "sector_exclusions": ["Financials"],
    },
    "cf_accruals_ratio": {
        "reads": [
            _qi(["net_income"], n=4),
            _cf(["operating_cash_flow"], n=1),
            _bs(["total_assets"], n=1),
        ],
        "sector_exclusions": ["Financials"],
    },
    "earnings_persistence": {
        "reads": [_qi(["net_income"], n=8, reporting_preference="consolidated")],
    },
    "earnings_beat_rate": {
        "reads": [_qi(["net_income"], n=8)],
    },
    "roe": {
        "reads": [_qi(["net_income"], n=4), _bs(["total_equity"], n=1)],
    },
    "roa": {
        "reads": [_qi(["net_income"], n=4), _bs(["total_assets"], n=1)],
    },
    "debt_to_equity": {
        "reads": [_bs(["long_term_debt", "total_equity"], n=1)],
        "sector_exclusions": ["Financials"],
    },
    "profit_margin": {
        "reads": [_qi(["revenue", "net_income"], n=4)],
    },
    "quality_composite": {
        "composite_of": ["roe", "debt_to_equity", "profit_margin"],
    },

    # ════════════════════════════ Growth ════════════════════════════
    "revenue_growth_yoy": {
        "reads": [_qi(["revenue"], n=8)],
    },
    "eps_growth_yoy": {
        "reads": [_qi(["net_income"], n=8)],
    },
    "growth_composite": {
        "composite_of": ["revenue_growth_yoy", "eps_growth_yoy"],
    },

    # ════════════════════════════ Momentum (price-based) ════════════════════════════
    "mom_6m_adj": {
        "reads": [_prices_window(126, contribution="6m_minus_1m_return")],
    },
    "mom_12m_adj": {
        "reads": [_prices_window(252, contribution="12m_minus_1m_return")],
    },
    "macd_signal": {
        "reads": [_prices_window(252, contribution="ema_12_26_9")],
    },
    "momentum_composite": {
        "composite_of": ["mom_6m_adj", "mom_12m_adj"],
    },

    # ════════════════════════════ Shareholding / Insider ════════════════════════════
    "promoter_qoq": {
        "reads": [
            {"table": "shareholding", "cols": ["promoter_pct"],
             "key": ["sid", "period_end"], "select": "last_n_periods", "n": 2,
             "contribution": "qoq_promoter_delta"},
            _stocks(("sid", "cap_tier")),
        ],
    },
    "promoter_trend_4q": {
        "reads": [
            {"table": "shareholding", "cols": ["promoter_pct"],
             "key": ["sid", "period_end"], "select": "last_n_periods", "n": 5,
             "contribution": "trend_slope_5q"},
        ],
    },
    "pledge_quality": {
        "reads": [
            {"table": "shareholding", "cols": ["pledge_pct"],
             "key": ["sid", "period_end"], "select": "last_n_periods", "n": 4,
             "contribution": "pledge_level_+_trend"},
        ],
    },
    "insider_signal": {
        "reads": [
            {"table": "insider_trades",
             "cols": ["sid", "trade_date", "person_category", "transaction_type", "value_lakhs"],
             "key": ["sid", "trade_date", "person_category", "transaction_type"],
             "select": "all", "filter": "last 90d",
             "contribution": "category_weighted_net_flow"},
            _stocks(("sid",)),
        ],
        "validation": {"weekly_NW_t": None, "tier": None},   # SMALL t≈DROP per current PIT
    },

    # ════════════════════════════ Smart money / Micro-flow ════════════════════════════
    "avg_delivery_pct_30d": {
        "reads": [
            {"table": "stock_prices", "cols": ["delivery_pct"],
             "key": ["sid", "date"], "select": "window",
             "filter": "last 30d", "contribution": "30d_mean_delivery_pct"},
        ],
        "validation": {"weekly_NW_t": 4.21, "tier": "SMALL"},
    },
    "delivery_anomaly_z": {
        "reads": [
            {"table": "stock_prices", "cols": ["delivery_pct"],
             "key": ["sid", "date"], "select": "window",
             "filter": "last 90d", "contribution": "z_score_of_30d_vs_90d_baseline"},
        ],
        "validation": {"weekly_NW_t": 4.11, "tier": "SMALL"},
    },
    "bulk_deal_signal": {
        "reads": [
            {"table": "bulk_deals",
             "cols": ["sid", "deal_date", "client_name", "buy_sell", "quantity"],
             "key": ["sid", "deal_date", "client_name"], "select": "all",
             "filter": "last 90d", "contribution": "net_qty_by_qib_repeat_buyer"},
            _prices_window(90, contribution="adv_normaliser"),
            _stocks(("sid", "cap_tier")),
        ],
        "validation": {"weekly_NW_t": 2.56, "tier": "SMALL"},
    },
    "smart_money_score": {
        "reads": [
            {"table": "bulk_deals",
             "cols": ["sid", "deal_date", "client_name", "buy_sell", "quantity"],
             "key": ["sid", "deal_date", "client_name"], "select": "all",
             "filter": "last 90d", "contribution": "bulk_score_component"},
            {"table": "stock_prices", "cols": ["delivery_pct"],
             "key": ["sid", "date"], "select": "window",
             "filter": "last 30d", "contribution": "delivery_score_component"},
            _stocks(("sid", "cap_tier")),
        ],
        "validation": {"weekly_NW_t": None, "tier": "SMALL",
                       "note": "registered 2026-06-02; PIT-thin (n≈6, bulk_deals ~1mo depth) — preliminary"},
    },
    "short_selling_signal": {
        "reads": [
            {"table": "short_selling_data",
             "cols": ["sid", "short_date", "quantity"],
             "key": ["sid", "short_date"], "select": "all", "filter": "last 30d",
             "contribution": "short_qty_vs_adv"},
            _prices_window(30, contribution="adv_normaliser"),
        ],
    },
    "fii_dii_cash_net": {
        "module": "(sector-level, applied to all stocks in sector)",
        "reads": [
            {"table": "fii_dii_cash_flow", "cols": ["net_value_cr", "category"],
             "key": ["date", "category"], "select": "window", "filter": "last 30d",
             "contribution": "sector_flow"},
        ],
    },
    "fii_dii_fno_positioning": {
        "module": "(market-level signal)",
        "reads": [
            {"table": "fii_dii_positioning",
             "cols": ["future_index_long", "future_index_short", "option_index_call_long",
                      "option_index_put_long", "client_type"],
             "key": ["date", "client_type"], "select": "window", "filter": "last 30d",
             "contribution": "fii_net_positioning"},
        ],
    },

    # ════════════════════════════ Track 2 — Financial sub-model (Banks + NBFCs) ════════════════════════════
    # Financial-ONLY factors (inverse of the usual sector_exclusions=["Financials"]):
    # they run exclusively on industry IN ("Banks", "NBFCs / Finance"). Shared read
    # spec across all three (per signals/financial_signal.py:_load_inputs) — latest
    # knowable quarterly + latest knowable annual row per sid from banking_metrics,
    # z-scored within (industry, cap_tier). PIT filing lags: 60d quarterly, 75d annual.
    "financial_quality": {
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
        ],
        "note": "Financials-only (Banks + NBFCs). SMALL-tier direction (low NPA = strong franchise).",
        "validation": {"weekly_NW_t": -1.88, "tier": "SMALL"},   # WEAK; on bench, re-test ~Q1 FY27
    },
    "financial_recovery": {
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
        ],
        "note": "Financials-only (Banks + NBFCs). LARGE/MID-tier direction (high NPA = mean-reversion).",
        "validation": {"weekly_NW_t": 1.55, "tier": "MID"},   # WEAK; on bench, re-test ~Q1 FY27
    },
    "financial_signal": {
        "reads": [
            {"table": "banking_metrics",
             "cols": ["gross_npa_pct", "net_npa_pct", "interest_earned",
                      "net_interest_income", "net_profit", "cost_of_funds_pct"],
             "key": ["sid", "period_end", "period_type"],
             "select": "latest_quarterly_+_annual_per_sid",
             "contribution": "back_compat_alias_=_financial_quality"},
        ],
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
        "reads": [
            {"table": "analyst_consensus_snapshots",
             "cols": ["snapshot_date", "target_mean", "n_analysts"],
             "key": ["sid", "snapshot_date", "source"], "select": "latest_per_sid_asof",
             "filter": "target_mean NOT NULL (monthly snapshots only — ADR 0045)"},
            _prices_latest(contribution="pt_upside_denominator"),
            _stocks(("sid", "cap_tier"), contribution="ranking_segment"),
        ],
        # The display-only live pt_upside (consensus_signals) still derives from
        # analyst_consensus.price_target — column-level provenance in
        # TABLE_COLUMN_SOURCES (the BAJA mc_slug contamination class).
    },
    "pt_revision_yoy": {
        "reads": [
            {"table": "forecast_history",
             "cols": ["value", "date"],
             "key": ["sid", "date"],
             "select": "all",
             "filter": "metric='price' AND year-end snapshots only",
             "contribution": "contaminated_currently — see ADR 0020"},
        ],
    },
    "eps_revision_yoy": {
        "reads": [
            {"table": "forecast_history",
             "cols": ["value", "change", "date"],
             "key": ["sid", "date"],
             "select": "all", "filter": "metric='eps'",
             "contribution": "yoy_revision"},
        ],
    },
    "consensus_signal_combined": {
        "reads": [
            {"table": "forecast_history",
             "cols": ["metric", "date", "value", "change"],
             "key": ["sid", "metric", "date"], "select": "window",
             "filter": "metric='eps' (EPS revision — the D1 quantity, plan 0015)"},
            _stocks(("sid", "cap_tier")),
        ],
    },

    # ════════════════════════════ News / Sentiment ════════════════════════════
    "sentiment_7d": {
        "reads": [
            {"table": "news_articles",
             "cols": ["article_id", "title", "summary", "published_at"],
             "key": ["article_id"], "select": "window", "filter": "last 7d"},
            {"table": "news_article_stocks",
             "cols": ["article_id", "sid"], "key": ["article_id", "sid"], "select": "all",
             "contribution": "article_sid_linkage"},
        ],
        "validation": {"weekly_NW_t": -3.88, "tier": "LARGE"},   # preliminary, n=4
    },
    "news_volume": {
        "reads": [
            {"table": "news_article_stocks",
             "cols": ["article_id", "sid"], "key": ["article_id", "sid"], "select": "all",
             "filter": "joined with news_articles WHERE published_at >= today-7d",
             "contribution": "article_count_per_sid"},
            _stocks(("sid",)),
        ],
    },

    # ════════════════════════════ Regulatory / Macro ════════════════════════════
    "regulatory_sector_signal": {
        "reads": [
            {"table": "regulatory_events", "cols": ["event_id", "published_at"],
             "key": ["event_id"], "select": "all", "filter": "last 30d",
             "contribution": "raw_event_count"},
            {"table": "regulatory_signals", "cols": ["direction", "magnitude", "confidence"],
             "key": ["event_id"], "select": "all",
             "contribution": "classified_tilt"},
        ],
    },
    "macro_sector_signal": {
        "reads": [
            {"table": "macro_history", "cols": ["value", "date"],
             "key": ["indicator", "date"], "select": "window",
             "filter": "last 90d per indicator"},
            {"table": "macro_indicator_meta", "cols": ["indicator_id", "category"],
             "key": ["indicator_id"], "select": "all"},
            {"table": "macro_sector_map", "cols": ["sector", "direction", "weight"],
             "key": ["indicator", "sector"], "select": "all"},
        ],
    },

    "sector_momentum": {
        "reads": [
            {"table": "stock_prices", "cols": ["close"],
             "key": ["sid", "date"], "select": "window",
             "filter": "last 252d", "contribution": "sector_cap_weighted_return"},
            {"table": "macro_history", "cols": ["value", "date"],
             "key": ["indicator_id", "date"], "select": "window",
             "filter": "nifty50 last 252d", "contribution": "benchmark_return"},
            _stocks(("sid", "sector", "market_cap_cr")),
        ],
    },
    "sector_tilt": {
        "reads": [
            {"table": "stock_prices", "cols": ["close"],
             "key": ["sid", "date"], "select": "window",
             "filter": "last 126d", "contribution": "sector_basket_6m_momentum"},
            {"table": "macro_history", "cols": ["value", "date"],
             "key": ["indicator_id", "date"], "select": "window",
             "filter": "latest vs 60-120d before, <= eval_date", "contribution": "macro_score_leg"},
            {"table": "macro_sector_map", "cols": ["direction", "weight"],
             "key": ["indicator_id", "sector"], "select": "row",
             "filter": "indicator -> sector", "contribution": "macro_score_leg"},
            _stocks(("sid", "sector")),
        ],
    },

    # ════════════════════════════ Options / F&O OI factors (§3.2.2) ════════════════════════════
    # All four read the pre-computed nearest-expiry rollup in fno_pcr_history
    # (ADR 0034). Stock-only: index underlyings carry sid=NULL and are filtered.
    "pcr_oi": {
        "reads": [
            {"table": "fno_pcr_history", "cols": ["pcr_oi"],
             "key": ["sid", "trade_date"], "select": "row",
             "filter": "latest ≤ as-of", "contribution": "put_oi_over_call_oi"},
        ],
    },
    "pcr_volume": {
        "reads": [
            {"table": "fno_pcr_history", "cols": ["pcr_volume"],
             "key": ["sid", "trade_date"], "select": "row",
             "filter": "latest ≤ as-of", "contribution": "put_vol_over_call_vol"},
        ],
    },
    "max_pain_distance": {
        "reads": [
            {"table": "fno_pcr_history", "cols": ["max_pain_distance"],
             "key": ["sid", "trade_date"], "select": "row",
             "filter": "latest ≤ as-of", "contribution": "spot_minus_maxpain_over_spot"},
        ],
    },
    "oi_buildup_signal": {
        "reads": [
            {"table": "fno_pcr_history",
             "cols": ["total_call_oi", "total_put_oi", "underlying_price", "expiry_date"],
             "key": ["sid", "trade_date"], "select": "window",
             "filter": "latest + prior same-expiry row",
             "contribution": "4state_oi_vs_price_buildup"},
        ],
    },

    # ════════════════════════════ Options / F&O IV factors (§3.2.2, ADR 0035) ════════════════════════════
    # All read fno_iv_history (Black-76 inversion of fno_bhav settle prices). The
    # surface itself is built by sources/fno_iv.py; these factors derive from it.
    "iv_skew_25d": {
        "reads": [
            {"table": "fno_iv_history", "cols": ["iv_skew_25d"],
             "key": ["sid", "trade_date"], "select": "row",
             "filter": "latest ≤ as-of", "contribution": "iv_25d_put_minus_call"},
        ],
    },
    "iv_term_structure": {
        "reads": [
            {"table": "fno_iv_history", "cols": ["iv_term_structure"],
             "key": ["sid", "trade_date"], "select": "row",
             "filter": "latest ≤ as-of", "contribution": "atm_iv_near_minus_far"},
        ],
    },
    "iv_realised_spread": {
        "reads": [
            {"table": "fno_iv_history", "cols": ["atm_iv"],
             "key": ["sid", "trade_date"], "select": "row",
             "filter": "latest ≤ as-of", "contribution": "atm_iv_level"},
            {"table": "stock_prices", "cols": ["close"],
             "key": ["sid", "date"], "select": "window",
             "filter": "last 21d", "contribution": "realised_vol_subtrahend"},
        ],
    },
    "iv_percentile_1y": {
        "reads": [
            {"table": "fno_iv_history", "cols": ["atm_iv"],
             "key": ["sid", "trade_date"], "select": "window",
             "filter": "trailing ≤252d", "contribution": "percentile_rank_of_latest_atm_iv"},
        ],
    },

    # ════════════════════════════ Microstructure factors (§3.2.3, daily-derivable) ════════════════════════════
    # All read daily OHLCV from stock_prices — no Kite. (The other 3 §3.2.3 factors
    # need intraday/tick → gated on 3.1c, on hold.)
    "intraday_range_compression": {
        "reads": [{"table": "stock_prices", "cols": ["high", "low", "close"],
                   "key": ["sid", "date"], "select": "window", "filter": "last 21d",
                   "contribution": "atr5_over_atr20"}],
    },
    "closing_strength_1m": {
        "reads": [{"table": "stock_prices", "cols": ["high", "low", "close"],
                   "key": ["sid", "date"], "select": "window", "filter": "last 21d",
                   "contribution": "mean_close_position_in_range"}],
    },
    "opening_gap_freq_1m": {
        "reads": [{"table": "stock_prices", "cols": ["open", "close"],
                   "key": ["sid", "date"], "select": "window", "filter": "last 21d",
                   "contribution": "freq_overnight_gap_gt_1pct"}],
    },
    "vwap_deviation_5d": {
        "reads": [{"table": "stock_prices", "cols": ["high", "low", "close"],
                   "key": ["sid", "date"], "select": "window", "filter": "last 5d",
                   "contribution": "close_vs_typical_price"}],
    },
    "bidask_spread_proxy": {
        "reads": [{"table": "stock_prices", "cols": ["high", "low"],
                   "key": ["sid", "date"], "select": "window", "filter": "last 20d pairs",
                   "contribution": "corwin_schultz_spread"}],
    },
    "kyle_lambda": {
        "reads": [{"table": "stock_prices", "cols": ["close", "volume"],
                   "key": ["sid", "date"], "select": "window", "filter": "last 21d",
                   "contribution": "amihud_illiquidity"}],
    },

    # ════════════════════════════ Event-time / PEAD factors (§3.2.5) ════════════════════════════
    "earnings_surprise_std": {
        "reads": [{"table": "quarterly_income", "cols": ["eps", "end_date"],
                   "key": ["sid", "end_date"], "select": "window", "filter": "last ~8 quarters",
                   "contribution": "seasonal_random_walk_SUE"}],
    },
    "pead_drift_60d": {
        "reads": [
            {"table": "quarterly_income", "cols": ["end_date"], "key": ["sid", "end_date"],
             "select": "row", "filter": "latest knowable", "contribution": "announce_anchor"},
            {"table": "stock_prices", "cols": ["close"], "key": ["sid", "date"],
             "select": "window", "filter": "announce→eval", "contribution": "abnormal_return"},
            {"table": "macro_history", "cols": ["value", "date"], "key": ["indicator_id", "date"],
             "select": "window", "filter": "nifty50 announce→eval", "contribution": "benchmark_return"},
        ],
    },
    "corporate_action_density": {
        "reads": [{"table": "corporate_actions", "cols": ["ex_date"], "key": ["sid", "ex_date"],
                   "select": "window", "filter": "last 365d", "contribution": "action_count"}],
    },
    "buyback_announcement_30d": {
        "reads": [{"table": "corporate_actions", "cols": ["ex_date", "subject"], "key": ["sid", "ex_date"],
                   "select": "window", "filter": "last 30d, subject~buyback", "contribution": "buyback_flag"}],
    },
    "announcement_car": {
        "reads": [{"table": "bse_announcements", "cols": ["sid", "dt_tm", "category"],
                   "key": ["sid", "dt_tm"], "select": "window",
                   "filter": "latest Result print ≤ eval within 90d, window closed",
                   "contribution": "event_anchor_date"},
                  {"table": "stock_prices", "cols": ["close"], "key": ["sid", "date"],
                   "select": "window", "filter": "[-1,+1] trading days around day0 (adj)",
                   "contribution": "stock_leg_return"},
                  {"table": "macro_history", "cols": ["value"], "key": ["date"],
                   "select": "window", "filter": "nifty50 over the same window dates",
                   "contribution": "benchmark_leg_return"}],
    },
    "governance_resignation": {
        "reads": [{"table": "bse_announcements", "cols": ["sid", "subcategory", "dt_tm"],
                   "key": ["sid", "dt_tm"], "select": "window",
                   "filter": "last 365d, resignation/cessation subcategories",
                   "contribution": "weighted_resignation_density"}],
    },

    # ═══════════ LARGE-tier canonical rebuild candidates (audit 2026-07-04 Factor-F3) ═══════════
    "low_vol_252d": {
        "reads": [{"table": "stock_prices", "cols": ["close"], "key": ["sid", "date"],
                   "select": "window", "filter": "last 252 trading days (adj), min 200 obs",
                   "contribution": "annualized_logret_std"}],
    },
    "st_reversal_21d": {
        "reads": [{"table": "stock_prices", "cols": ["close"], "key": ["sid", "date"],
                   "select": "window", "filter": "last 21 trading days (adj), min 15 obs",
                   "contribution": "trailing_21d_total_return"}],
    },
    "asset_growth_yoy": {
        "reads": [{"table": "annual_balance_sheet", "cols": ["total_assets", "end_date"],
                   "key": ["sid", "end_date"], "select": "window",
                   "filter": "two latest knowable annual rows (75d lag), prior assets ≥ ₹50 cr",
                   "contribution": "yoy_total_asset_growth_pct"}],
        "sector_exclusions": ["financial_sectors"],
    },

    # ═══════════════════════════ Plan 0012 C3/C4 — momentum/lottery retest (WS2.6/WS2.7) ═══════════════════════════
    "residual_momentum_12_1": {
        "reads": [{"table": "stock_prices", "cols": ["close"], "key": ["sid", "date"],
                   "select": "window", "filter": "trading days [D-252, D-21] (adj), min 150 paired obs vs NIFTY",
                   "contribution": "12m_momentum_net_of_nifty_beta"},
                  {"table": "macro_history", "cols": ["value"], "key": ["date"],
                   "select": "window", "filter": "indicator_id='nifty50', same window",
                   "contribution": "market_beta_regressor"}],
    },
    "max_lottery_21d": {
        "reads": [{"table": "stock_prices", "cols": ["close"], "key": ["sid", "date"],
                   "select": "window", "filter": "last 21 trading days (adj), min 15 obs",
                   "contribution": "mean_top5_daily_return"}],
    },

    # ════════════════════════════ Earnings-call NLP (§3.2.4) ════════════════════════════
    # Latest-call values off the nlp_scores enriched layer, look-ahead-safe on available_date.
    "earnings_call_tone_qoq": {
        "reads": [{"table": "nlp_scores", "cols": ["sid", "net_tone", "available_date", "doc_date"],
                   "key": ["sid", "doc_date"], "select": "window",
                   "filter": "latest 2 calls within 400d, available_date<=eval",
                   "contribution": "net_tone_latest_minus_prior"}],
    },
    "forward_looking_intensity": {
        "reads": [{"table": "nlp_scores", "cols": ["sid", "forward_looking_intensity", "available_date", "doc_date"],
                   "key": ["sid", "doc_date"], "select": "latest",
                   "filter": "latest call within 400d, available_date<=eval",
                   "contribution": "latest_call_value"}],
    },
    "uncertainty_word_density": {
        "reads": [{"table": "nlp_scores", "cols": ["sid", "uncertainty_density", "available_date", "doc_date"],
                   "key": ["sid", "doc_date"], "select": "latest",
                   "filter": "latest call within 400d, available_date<=eval",
                   "contribution": "latest_call_value"}],
    },

    # ════════════════════════════ Industry control (§3.2.6) ════════════════════════════
    # Categorical neutralisation control — frozen integer code, no source reads
    # beyond the static stock attribute.
    "industry_id": {
        "reads": [_stocks(("sid", "industry"), contribution="industry_code")],
    },

    # ════════════════════════════ Macro betas (§3.2.7) ════════════════════════════
    # Per-stock rolling 252d OLS beta of daily returns on a macro factor's daily
    # returns. macro_history holds the daily macro series; stock_prices the close.
    "oil_beta": {
        "reads": [
            {"table": "stock_prices", "cols": ["close"], "key": ["sid", "date"],
             "select": "window", "filter": "last 252d", "contribution": "stock_returns"},
            {"table": "macro_history", "cols": ["value", "date"], "key": ["indicator_id", "date"],
             "select": "window", "filter": "brent_crude last 252d", "contribution": "oil_returns"},
        ],
    },
    "metals_beta": {
        "reads": [
            {"table": "stock_prices", "cols": ["close"], "key": ["sid", "date"],
             "select": "window", "filter": "last 252d", "contribution": "stock_returns"},
            {"table": "macro_history", "cols": ["value", "date"], "key": ["indicator_id", "date"],
             "select": "window", "filter": "copper+aluminium blend last 252d", "contribution": "metals_returns"},
        ],
    },
    "inr_beta": {
        "reads": [
            {"table": "stock_prices", "cols": ["close"], "key": ["sid", "date"],
             "select": "window", "filter": "last 252d", "contribution": "stock_returns"},
            {"table": "macro_history", "cols": ["value", "date"], "key": ["indicator_id", "date"],
             "select": "window", "filter": "usdinr last 252d", "contribution": "fx_returns"},
        ],
    },
    "gold_beta": {
        "reads": [
            {"table": "stock_prices", "cols": ["close"], "key": ["sid", "date"],
             "select": "window", "filter": "last 252d", "contribution": "stock_returns"},
            {"table": "macro_history", "cols": ["value", "date"], "key": ["indicator_id", "date"],
             "select": "window", "filter": "gold last 252d", "contribution": "gold_returns"},
        ],
    },
    "rate_beta": {
        "reads": [
            {"table": "stock_prices", "cols": ["close"], "key": ["sid", "date"],
             "select": "window", "filter": "last 252d", "contribution": "stock_returns"},
            {"table": "macro_history", "cols": ["value", "date"], "key": ["indicator_id", "date"],
             "select": "window", "filter": "gsec10_etf last 252d", "contribution": "gsec_returns"},
        ],
    },
    "credit_beta": {
        "reads": [
            {"table": "stock_prices", "cols": ["close"], "key": ["sid", "date"],
             "select": "window", "filter": "last 252d", "contribution": "stock_returns"},
            {"table": "macro_history", "cols": ["value", "date"], "key": ["indicator_id", "date"],
             "select": "window", "filter": "credit_excess_idx last 252d", "contribution": "credit_returns"},
        ],
    },

    # ════════════════════════════ Fundamentals_screener factors (17) ════════════════════════════
    "roic": {
        "reads": [_fund(["Profit before tax", "Interest", "Tax", "Equity Share Capital",
                         "Reserves", "Borrowings"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "roiic": {
        "reads": [_fund(["Profit before tax", "Tax", "Interest", "Equity Share Capital",
                         "Reserves", "Borrowings"], n=6),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "fcf_yield": {
        "reads": [_fund(["Cash from Operating Activity", "Net Block",
                         "Capital Work in Progress", "Depreciation",
                         "No. of Equity Shares"], n=2),
                  _prices_latest(),
                  _stocks(("sid", "sector", "market_cap_cr"))],
        "sector_exclusions": ["Financials"],
    },
    "gross_profitability": {
        "reads": [_fund(["Sales", "Raw Material Cost", "Change in Inventory",
                         "Power and Fuel", "Other Mfr. Exp", "Total"], n=3),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "ccc": {
        "reads": [_fund(["Sales", "Receivables", "Inventory", "Trade Payables"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "margin_slope": {
        "reads": [_fund(["Sales", "Profit before tax", "Interest"], n=3),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "wc_intensity": {
        "reads": [_fund(["Sales", "Receivables", "Inventory", "Trade Payables"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "dso_change_yoy": {
        "reads": [_fund(["Sales", "Receivables"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "dio_change_yoy": {
        "reads": [_fund(["Sales", "Inventory"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "nwc_to_revenue": {
        "reads": [_fund(["Sales", "Receivables", "Inventory", "Trade Payables"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "sloan_accruals_full": {
        "reads": [_fund(["Receivables", "Inventory", "Trade Payables",
                         "Depreciation", "Total"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "sga_to_revenue_change": {
        "reads": [_fund(["Sales", "Selling and admin"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "fcf_margin": {
        "reads": [_fund(["Sales", "Cash from Operating Activity", "Net Block",
                         "Capital Work in Progress", "Depreciation"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "capex_to_dep": {
        "reads": [_fund(["Net Block", "Capital Work in Progress", "Depreciation"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "goodwill_to_assets": {
        "reads": [_fund(["Intangible Assets", "Total"], n=1),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "debt_structure": {
        "reads": [_fund(["Long term Borrowings", "Borrowings"], n=1),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "asset_tangibility": {
        "reads": [_fund(["Net Block", "Total"], n=1),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "interest_coverage": {
        "reads": [_fund(["Profit before tax", "Interest"], n=2),
                  _stocks(("sid", "sector"))],
        "sector_exclusions": ["Financials"],
    },
    "revenue_cv_5y": {
        "reads": [_fund(["Sales"], n=6),
                  _stocks(("sid", "sector"))],
    },
    "relative_turnover": {
        "reads": [_fund(["Sales", "Inventory"], n=1),
                  _stocks(("sid", "sector"))],
    },
    "relative_growth": {
        "reads": [_fund(["Sales"], n=3),
                  _stocks(("sid", "sector"))],
    },
    "share_momentum": {
        "reads": [_prices_window(252, contribution="pit_adjusted_price"),
                  _fund(["No. of Equity Shares"], n=2,
                        contribution="share_count_pit"),
                  _stocks(("sid", "sector", "market_cap_cr"))],
    },

    # ════════════════════════════ Top-level composites ════════════════════════════
    "screener_final_composite": {
        "composite_of": [
            "value_composite", "quality_composite", "growth_composite",
            "momentum_composite", "pt_upside", "piotroski_f_score",
            "promoter_qoq", "delivery_anomaly_z", "bulk_deal_signal",
        ],
        "weight_lookup": "factors.SIGNAL_WEIGHTS (per cap-tier)",
    },
}


import factors  # noqa: E402  (after the detail literal; factors never imports lineage)

# Lifecycle status is COMPUTED, never stored: factors.status() from the factor's
# weights / bench (a hand-kept copy here went stale — it still called pulled
# pt_upside model_active and missed most wired factors).
_LINEAGE_STATUS = {"WIRED": "model_active", "VARIANT": "candidate",
                   "LIBRARY": "library", "PROPOSED": "candidate"}


def _bare_read(table):
    """A table the factor reads with no column-level detail declared."""
    return {"table": table, "cols": [], "key": ["sid"], "select": "as_of",
            "contribution": "producer_input"}


def _derive(sid, f):
    detail = LINEAGE_DETAIL.get(sid, {})
    st = factors.status(sid)
    if "composite_of" in detail:
        return {**detail, "status": _LINEAGE_STATUS.get(st, st.lower())}
    tables = [t for t in f.get("source_tables", []) if t != "—"]
    specs = [r for r in detail.get("reads", []) if r["table"] in tables]
    have = {r["table"] for r in specs}
    producer = factors.PIT_PRODUCERS.get(f.get("producer")) or {}
    entry = {
        "module": detail.get("module") or (f"pit.{producer['fn']}" if producer.get("fn") else
                                           f"tools/reconstruct_pit ({f.get('producer')})"),
        "reads": specs + [_bare_read(t) for t in tables if t not in have],
        "sector_exclusions": detail.get("sector_exclusions", []),
    }
    entry.update({k: v for k, v in detail.items() if k not in ("module", "reads", "sector_exclusions")})
    entry["status"] = _LINEAGE_STATUS.get(st, st.lower())
    return entry


# Every registry factor, in registry order.
FACTOR_LINEAGE = {sid: _derive(sid, f) for sid, f in factors.FACTORS.items()}


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
    """BACKTEST_SIGNALS factors that lack a FACTOR_LINEAGE entry — always [] now that
    FACTOR_LINEAGE is derived from the registry (kept for tools/data_sanity's
    LINEAGE_REGISTRY_DRIFT until that check is dropped)."""
    from db import BACKTEST_SIGNALS
    declared = {s["signal"] for s in BACKTEST_SIGNALS}
    in_registry = set(FACTOR_LINEAGE.keys())
    return sorted(declared - in_registry)


def orphan_factors():
    """LINEAGE_DETAIL keys that are no longer registry factors (stale detail).
    tests/test_factor_registry.py asserts this is empty."""
    return sorted(set(LINEAGE_DETAIL) - set(factors.FACTORS))
