"""
Alpha Signal v2 — Days Inventory Outstanding, YoY change

Reads:  fundamentals_screener (annual rows), stocks
Computed point in time only (pit.py); the live step that wrote its *_scores table had no reader and was removed (plan 0020, 2026-10).

  DIO_t = Inventory_t / (Sales_t / 365)
  Δ DIO = DIO_t − DIO_{t-1}   (days)

Rising DIO = inventory accumulating faster than sales — slowing demand,
obsolescence, or aggressive production. Yellow flag in forensic screens.

"""

from signals import _annual

REQUIRED_ITEMS = ["Sales", "Inventory"]
MIN_SALES_CR = 50.0


def _compute(stocks, fund):
    return _annual.days_of_sales_change(fund, "Inventory", "dio_change_yoy", MIN_SALES_CR)
