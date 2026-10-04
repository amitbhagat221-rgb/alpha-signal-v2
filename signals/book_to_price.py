"""
Alpha Signal v2 — Book-to-Price.

  book_to_price = owners' equity / (shares × close), on one share basis
  (signals._fundamentals.shares_and_book)

off the latest annual statement. One implementation for the live screener,
output/snapshot and pit.py:pit_book_to_price (which passes the
filing-lagged balance sheet and the as-of close).

Reads: annual_balance_sheet, stock_prices
"""

import numpy as np
import pandas as pd

from db import read_sql


def book_to_price(shares, close):
    """Owners' equity / (shares × close) per sid, on one share basis.

    `shares` = signals._fundamentals.shares_and_book() [sid, shares, book_equity_cr];
    `close` = [sid, close_price]. NaN where shares ≤ 0 / equity or close missing /
    close ≤ 0. Returns DataFrame[sid, book_to_price].
    """
    if shares is None or shares.empty:
        return pd.DataFrame(columns=["sid", "book_to_price"])
    merged = shares.merge(close, on="sid", how="left")
    ok = (merged["shares"] > 0) & (merged["close_price"] > 0) & merged["book_equity_cr"].notna()
    merged["book_to_price"] = (merged["book_equity_cr"] * 1e7 / (merged["shares"] * merged["close_price"])).where(ok).round(6)
    return merged[["sid", "book_to_price"]]


def compute_book_to_price():
    """Live B/P: every annual balance sheet and Screener statement × latest close."""
    from signals._fundamentals import SHARE_ITEMS, shares_and_book
    bs = read_sql("SELECT sid, end_date, total_equity, shares_outstanding FROM annual_balance_sheet")
    fund = read_sql("SELECT sid, period_end, line_item, value FROM fundamentals_screener WHERE period_type = 'annual' "
                    f"AND line_item IN ({','.join('?' * len(SHARE_ITEMS))})", params=list(SHARE_ITEMS))
    adjustments = read_sql("SELECT sid, ex_date, factor, inds FROM corporate_adjustments")
    close = read_sql(
        "SELECT sid, close AS close_price FROM stock_prices "
        "WHERE (sid, date) IN (SELECT sid, MAX(date) FROM stock_prices GROUP BY sid)"
    )
    return book_to_price(shares_and_book(bs, fund, adjustments, pd.Timestamp.today().date().isoformat()), close)


if __name__ == "__main__":
    df = compute_book_to_price()
    s = df["book_to_price"].dropna()
    print(f"book_to_price — {len(s):,} stocks; median={s.median():.4f}")
