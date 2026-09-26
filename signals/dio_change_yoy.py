"""
Alpha Signal v2 — Days Inventory Outstanding, YoY change

Reads:  fundamentals_screener (annual rows), stocks
Writes: dio_change_yoy_scores

  DIO_t = Inventory_t / (Sales_t / 365)
  Δ DIO = DIO_t − DIO_{t-1}   (days)

Rising DIO = inventory accumulating faster than sales — slowing demand,
obsolescence, or aggressive production. Yellow flag in forensic screens.

Usage:
    python -m signals.dio_change_yoy
"""

from signals import _annual

REQUIRED_ITEMS = ["Sales", "Inventory"]
MIN_SALES_CR = 50.0


def _load_data():
    return _annual.load(REQUIRED_ITEMS)


def _compute(stocks, fund):
    return _annual.days_of_sales_change(fund, "Inventory", "dio_change_yoy", MIN_SALES_CR)


def compute(dry_run=False):
    return _annual.save(_compute(*_load_data()), "dio_change_yoy_scores", "DIO change YoY", "dio_change_yoy",
                        dry_run, fmt=".1f", unit="d")


if __name__ == "__main__":
    _annual.cli(compute)
