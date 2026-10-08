"""
Alpha Signal v2 — Book-to-Price.

  book_to_price = owners' equity / (shares × close), on one share basis
  (signals._fundamentals.shares_and_book)

off the latest annual statement. One implementation for the live screener,
output/snapshot and pit.py:pit_book_to_price (which passes the
filing-lagged balance sheet and the as-of close).

Reads: annual_balance_sheet, stock_prices
"""

import pandas as pd



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
