"""
Alpha Signal v2 — Book-to-Price.

  book_to_price = (total_equity / shares_outstanding) / close

off the latest annual balance sheet. One implementation for the live screener,
output/snapshot and pit.py:pit_book_to_price (which passes the
filing-lagged balance sheet and the as-of close).

Reads: annual_balance_sheet, stock_prices
"""

import numpy as np
import pandas as pd

from db import read_sql


def book_to_price(bs, close):
    """Latest balance sheet's book equity per share / close, per sid.

    `bs` = [sid, end_date, total_equity, shares_outstanding] (as-of filtered by the
    caller); `close` = [sid, close_price]. NaN where shares ≤ 0 / equity or close
    missing / close ≤ 0. Returns DataFrame[sid, book_to_price].
    """
    if bs.empty:
        return pd.DataFrame(columns=["sid", "book_to_price"])

    latest_bs = (bs.sort_values(["sid", "end_date"])
                 .groupby("sid")
                 .tail(1)[["sid", "total_equity", "shares_outstanding"]])

    latest_bs["book_per_share"] = np.where(
        (latest_bs["shares_outstanding"].notna()) & (latest_bs["shares_outstanding"] > 0),
        latest_bs["total_equity"] / latest_bs["shares_outstanding"],
        np.nan,
    )

    merged = latest_bs.merge(close, on="sid", how="left")
    merged["book_to_price"] = np.where(
        (merged["close_price"].notna()) & (merged["close_price"] > 0)
        & (merged["book_per_share"].notna()),
        (merged["book_per_share"] / merged["close_price"]).round(6),
        np.nan,
    )
    return merged[["sid", "book_to_price"]]


def compute_book_to_price():
    """Live B/P: latest annual balance sheet × latest close."""
    bs = read_sql(
        "SELECT sid, end_date, total_equity, shares_outstanding FROM annual_balance_sheet "
        "WHERE (sid, period) IN (SELECT sid, MAX(period) FROM annual_balance_sheet GROUP BY sid)"
    )
    close = read_sql(
        "SELECT sid, close AS close_price FROM stock_prices "
        "WHERE (sid, date) IN (SELECT sid, MAX(date) FROM stock_prices GROUP BY sid)"
    )
    return book_to_price(bs, close)


if __name__ == "__main__":
    df = compute_book_to_price()
    s = df["book_to_price"].dropna()
    print(f"book_to_price — {len(s):,} stocks; median={s.median():.4f}")
