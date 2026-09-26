"""
Alpha Signal v2 — Days Sales Outstanding, YoY change

Reads:  fundamentals_screener (annual rows), stocks
Writes: dso_change_yoy_scores

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

Usage:
    python -m signals.dso_change_yoy
    python -m signals.dso_change_yoy --dry-run
"""

from signals import _annual

REQUIRED_ITEMS = ["Sales", "Receivables"]
MIN_SALES_CR = 50.0


def _load_data():
    return _annual.load(REQUIRED_ITEMS)


def _compute(stocks, fund):
    return _annual.days_of_sales_change(fund, "Receivables", "dso_change_yoy", MIN_SALES_CR)


def compute(dry_run=False):
    return _annual.save(_compute(*_load_data()), "dso_change_yoy_scores", "DSO change YoY", "dso_change_yoy",
                        dry_run, fmt=".1f", unit="d")


if __name__ == "__main__":
    _annual.cli(compute)
