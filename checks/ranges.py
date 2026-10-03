"""
One range / enum per column (plan 0015 Phase 4, the Check block of ADR 0052).

COLUMNS is the ONE place a column's legal values are declared. Every consumer
reads it: health.factor_validity (the per-table score), the range verdicts of
checks.run() (what tools/data_sanity and the health email show), the write-time
plausibility gate (validators/plausibility) and the per-pick integrity checks
(validators/per_stock_integrity). Before this, M-score alone had three ranges.

A spec is a dict with exactly one of:
    factor: <PIT column>   the range is factors.VALIDATION_RANGES[<col>] — the rule
                           the validated backtest applies (reused, never copied)
    range:  (lo, hi)       closed interval
    min:    lo             lower bound only ("never negative")
    in:     [...]          enum (tier / regime enums come from config)
and optionally
    typical: (lo, hi)      plausibility's review band: inside `range` but outside
                           `typical` = unusual but possibly real (PENDING_REVIEW)
    may_be_empty: <why>    the column is declared but nothing fills it yet: its rule
                           is ready for the write-time gate, and the daily check
                           finding zero values is expected, not a silent check.
                           Remove it the day a source fills the column.

NULL always passes (missing data is the null-rate check's business). Numeric
bounds carry a 1e-9 tolerance so float round-off (a weighted average of ranks
landing on 1.0000000000000002) is never a violation.
"""

from config import EXCLUDED_FROM_PICKS, REGIMES, TIERS

PCT = (0, 100)
EPS = 1e-9
PICKABLE_TIERS = [t for t in TIERS if t not in EXCLUDED_FROM_PICKS]

COLUMNS = {
    # ── Universe & prices ──
    ("stocks", "cap_tier"): {"in": list(TIERS)},
    # 1e7, not the PIT panel's 1e6: two SM-REITs (PSP, PST) trade at ₹10-12 lakh
    # a unit — 194 real rows that a 1e6 cap flags (evidence 2026-09-27).
    ("stock_prices", "close"): {"range": (0.01, 1e7)},
    ("stock_prices", "delivery_pct"): {"range": PCT},
    ("vix_history", "vix"): {"range": (5, 100)},
    ("regime_state", "regime"): {"in": list(REGIMES)},
    ("regime_state", "alloc_large"): {"range": (0, 1)},

    # ── Fundamentals ──
    ("quarterly_income", "revenue"): {"min": 0},
    ("shareholding", "promoter_pct"): {"range": PCT},
    ("shareholding", "fii_pct"): {"range": PCT},
    ("shareholding", "dii_pct"): {"range": PCT},
    ("shareholding", "pledge_pct"): {"range": PCT},
    ("analyst_consensus", "price_target"): {"min": 0},
    ("analyst_consensus", "buy_pct"): {"range": PCT},
    # Banking: GNPA > 35 / NNPA > 15 / CAR < 5 are parse errors (consolidated vs
    # standalone mix-up, decimal shift); `typical` is the review band. UCO Bank's
    # all-time worst GNPA was ~24%; RBI mandates CAR >= 9%.
    ("banking_metrics", "gross_npa_pct"): {"range": (0, 35), "typical": (0, 20)},
    ("banking_metrics", "net_npa_pct"): {"range": (0, 15), "typical": (0, 8)},
    ("banking_metrics", "nim_pct"): {"range": (-2, 20), "typical": (0, 10), "may_be_empty": "no source fills it yet (banking plan 2.2c: RBI disclosures)"},
    ("banking_metrics", "cost_of_funds_pct"): {"range": (0, 25), "typical": (3, 15)},
    ("banking_metrics", "roa_pct"): {"range": (-10, 8), "typical": (-3, 3), "may_be_empty": "no source fills it yet (banking plan 2.2c: RBI disclosures)"},
    ("banking_metrics", "car_pct"): {"range": (5, 35), "typical": (8, 25), "may_be_empty": "no source fills it yet (banking plan 2.2c: RBI disclosures)"},
    ("banking_metrics", "casa_pct"): {"range": PCT, "typical": (10, 80), "may_be_empty": "no source fills it yet (banking plan 2.2c: RBI disclosures)"},

    # ── Trades ──
    ("insider_trades", "value_lakhs"): {"min": 0},
    ("bulk_deals", "buy_sell"): {"in": ["BUY", "SELL", "Buy", "Sell"]},
    ("bulk_deals", "quantity"): {"min": 0},

    # ── Macro & regulatory ──
    ("macro_sector_map", "direction"): {"range": (-1, 1)},
    ("macro_sector_signals", "macro_score"): {"range": PCT},
    # UNKNOWN = a sector with no macro score yet; signals/regulatory.py writes it
    # (with a NULL macro_score) on purpose — a legal value, not a violation.
    ("macro_sector_signals", "macro_signal"): {
        "in": ["TAILWIND", "FAVORABLE", "NEUTRAL", "HEADWIND", "ADVERSE", "UNKNOWN"]},
    ("regulatory_events", "classifier_status"): {
        "in": ["pending", "haiku_rejected", "haiku_rejected_inferred",
               "haiku_passed_sonnet_failed", "classified", "unknown"]},
    ("regulatory_signals", "direction"): {"range": (-1, 1)},

    # ── Computed signals: the factor's own range (the backtest's discard rule) ──
    ("piotroski_scores", "f_score"): {"factor": "piotroski_f"},
    ("daily_snapshots", "piotroski_f"): {"factor": "piotroski_f"},
    ("daily_snapshots", "mom_6m"): {"factor": "mom_6m"},
    ("daily_snapshots", "mom_12m"): {"factor": "mom_12m"},
    ("forensic_scores", "m_score"): {"factor": "m_score"},
    ("forensic_scores", "z_score"): {"factor": "z_score"},
    ("sentiment_scores", "sentiment_7d"): {"factor": "sentiment_7d"},

    # ── Output ──
    ("daily_picks", "cap_tier"): {"in": PICKABLE_TIERS},
    ("daily_picks", "final_score"): {"range": (0, 1)},
    ("daily_picks", "base_score"): {"range": (0, 1)},
    ("daily_changes", "severity"): {"in": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},

    # ── Pipeline ──
    ("pipeline_log", "status"): {"in": ["RUNNING", "SUCCESS", "FAILED", "SKIPPED", "ABORTED"]},
}


def bounds(table, column):
    """(lo, hi) of a numeric column (hi None = open above); None when the column
    has no numeric range (unregistered, or an enum)."""
    spec = COLUMNS.get((table, column))
    if spec is None:
        return None
    if "factor" in spec:
        from factors import VALIDATION_RANGES
        lo, hi, _allow_nan = VALIDATION_RANGES[spec["factor"]]
        return (lo, hi)
    if "range" in spec:
        return tuple(spec["range"])
    if "min" in spec:
        return (spec["min"], None)
    return None


def typical(table, column):
    """The review band (lo, hi); the hard range when no band is declared."""
    spec = COLUMNS.get((table, column)) or {}
    return tuple(spec["typical"]) if "typical" in spec else bounds(table, column)


def describe(table, column):
    """'[lo, hi]', '>= lo' or '{A, B}' — for messages."""
    spec = COLUMNS[(table, column)]
    if "in" in spec:
        return "{" + ", ".join(spec["in"]) + "}"
    lo, hi = bounds(table, column)
    return f">= {lo:g}" if hi is None else f"[{lo:g}, {hi:g}]"


def in_range(table, column, value):
    """True when `value` is legal for the column (NULL, NaN, unregistered: True)."""
    spec = COLUMNS.get((table, column))
    if spec is None or value is None:
        return True
    if "in" in spec:
        return value in spec["in"]
    try:
        v = float(value)
    except (TypeError, ValueError):
        return True
    if v != v:  # NaN
        return True
    lo, hi = bounds(table, column)
    return v >= lo - EPS and (hi is None or v <= hi + EPS)


def bad_sql(table, column):
    """SQL predicate, TRUE for a row that violates the column's spec."""
    spec = COLUMNS[(table, column)]
    c = f"[{column}]"
    if "in" in spec:
        values = ",".join("'" + str(v).replace("'", "''") + "'" for v in spec["in"])
        return f"{c} IS NOT NULL AND {c} NOT IN ({values})"
    lo, hi = bounds(table, column)
    cond = f"{c} < {lo - EPS!r}"
    if hi is not None:
        cond += f" OR {c} > {hi + EPS!r}"
    return f"{c} IS NOT NULL AND ({cond})"


def for_table(table):
    """The registered columns of one table, in declaration order."""
    return [c for (t, c) in COLUMNS if t == table]
