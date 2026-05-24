"""
Per-signal eligibility registry — "who SHOULD have a score for this signal?"

Each entry maps a signal_id (matching SIGNAL_WEIGHTS keys in config.py) to a
SQL that returns the SIDs eligible to receive a score. A SID being INELIGIBLE
is NOT a defect — it's a deliberate exclusion from that signal's contribution
to the rank.

Consumed by:
  • tools/refresh_eligibility.py — nightly populates `universe_eligibility` table
  • scoring/screener.py — computes `eligible_coverage` distinct from `weight_coverage`
    (so a small-cap with no analyst attribution isn't penalised for the missing
    consensus_signal — that signal was never going to be available)
  • cockpit/api.py — surfaces per-signal eligible/covered in Health Center

Plan 0005 Phase A. See docs/plans/0005-data-confidence-to-95.md.
"""

# Each entry: signal_id (matches scoring/screener.py SIGNAL_COLS key) →
# dict with `description` (human) and `eligible_sql` (returns DISTINCT sid).
SIGNAL_ELIGIBILITY = {
    "consensus": {
        "description": "Stocks with sell-side analyst attribution (yfinance: total_analysts > 0 OR price_target IS NOT NULL)",
        "eligible_sql": """
            SELECT DISTINCT sid FROM analyst_consensus
            WHERE total_analysts IS NOT NULL OR price_target IS NOT NULL
        """,
    },
    "earnings_yield": {
        "description": "Stocks with ≥4 quarters of EPS in quarterly_income AND a close price",
        "eligible_sql": """
            SELECT DISTINCT qi.sid FROM quarterly_income qi
            WHERE qi.sid IN (SELECT DISTINCT sid FROM stock_prices)
              AND qi.eps IS NOT NULL
            GROUP BY qi.sid HAVING COUNT(*) >= 4
        """,
    },
    "accruals": {
        "description": "Stocks with annual_balance_sheet + annual_cash_flow (Sloan accruals needs both)",
        "eligible_sql": """
            SELECT DISTINCT abs.sid FROM annual_balance_sheet abs
            INNER JOIN annual_cash_flow acf ON acf.sid = abs.sid
        """,
    },
    "piotroski": {
        "description": "Stocks with ≥2 annual periods (YoY F-score components need prior-year baseline)",
        "eligible_sql": """
            SELECT sid FROM annual_balance_sheet
            GROUP BY sid HAVING COUNT(*) >= 2
        """,
    },
    "momentum": {
        "description": "Stocks with ≥126 trading days of price history (~6mo for mom_6m / mom_12m)",
        "eligible_sql": """
            SELECT sid FROM stock_prices
            GROUP BY sid HAVING COUNT(*) >= 126
        """,
    },
    "book_to_price": {
        "description": "Stocks with annual_balance_sheet.total_equity + shares_outstanding>0 + a close price",
        "eligible_sql": """
            SELECT DISTINCT abs.sid FROM annual_balance_sheet abs
            WHERE abs.total_equity IS NOT NULL
              AND abs.shares_outstanding IS NOT NULL AND abs.shares_outstanding > 0
              AND abs.sid IN (SELECT DISTINCT sid FROM stock_prices)
        """,
    },
    "promoter": {
        "description": "Stocks with ≥2 quarterly shareholding snapshots (promoter QoQ delta needs prior quarter)",
        "eligible_sql": """
            SELECT sid FROM shareholding
            GROUP BY sid HAVING COUNT(*) >= 2
        """,
    },
    "smart_money": {
        "description": "Stocks with bulk_deals or delivery activity in last 90d (smart-money signal aggregates both)",
        "eligible_sql": """
            SELECT sid FROM (
                SELECT DISTINCT sid FROM bulk_deals WHERE deal_date >= date('now', '-90 days')
                UNION
                SELECT DISTINCT sid FROM stock_prices WHERE date >= date('now', '-90 days')
            )
        """,
    },
}


# Universe baseline — every sid we're tracking. Used to compute INELIGIBLE rows.
UNIVERSE_SQL = "SELECT sid FROM stocks WHERE ticker IS NOT NULL"


def all_signals():
    """List the signal_ids the registry knows about."""
    return list(SIGNAL_ELIGIBILITY.keys())
