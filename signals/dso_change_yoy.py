"""
Alpha Signal v2 — Days Sales Outstanding, YoY change

Reads:  fundamentals_screener (annual rows), stocks
Computed point in time only (pit.py); the live step that wrote its *_scores table had no reader and was removed (plan 0020, 2026-10).

  DSO_t = Receivables_t / (Sales_t / 365)
  Δ DSO = DSO_t − DSO_{t-1}   (days)

Positive Δ DSO = receivables growing faster than sales — early sign of
channel-stuffing, revenue-pull-forward, or credit-policy laxity. The forensic
literature treats rising DSO as a yellow flag.

Filters:
  - Sales ≥ ₹50 cr in both endpoints (avoid tiny-base noise)
  - Both endpoints must have Receivables and Sales non-null
  - Need ≥2 distinct annual periods

Sign convention: signal is the *change*; lower (= shrinking DSO) is better.

"""

from signals import _annual

REQUIRED_ITEMS = ["Sales", "Receivables"]
MIN_SALES_CR = 50.0


def _compute(stocks, fund):
    return _annual.days_of_sales_change(fund, "Receivables", "dso_change_yoy", MIN_SALES_CR)
