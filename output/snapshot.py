"""
Alpha Signal v2 — Daily Snapshot Archiver

Archives all signal values per stock into daily_snapshots table.
One row per stock per day — point-in-time record for backtesting.

Reads: stocks, all signal tables, stock_prices
Writes: daily_snapshots

Usage:
    python -m output.snapshot
    python -m output.snapshot --dry-run
"""

import argparse
from datetime import date

import pandas as pd

from db import read_sql, upsert_df


def _latest(table, cols, key="sid"):
    """Get latest snapshot per stock from a signal table."""
    col_list = ", ".join(cols)
    return read_sql(
        f"SELECT {key}, {col_list} FROM [{table}] "
        f"WHERE ({key}, snapshot_date) IN "
        f"(SELECT {key}, MAX(snapshot_date) FROM [{table}] GROUP BY {key})"
    )


def compute(dry_run=False):
    """Archive today's signal snapshot."""
    today = date.today().isoformat()

    stocks = read_sql("SELECT sid, cap_tier FROM stocks")
    df = stocks.copy()

    # Latest close price
    prices = read_sql(
        "SELECT sid, close AS close_price FROM stock_prices "
        "WHERE (sid, date) IN (SELECT sid, MAX(date) FROM stock_prices GROUP BY sid)"
    )
    df = df.merge(prices, on="sid", how="left")

    # Piotroski
    pio = _latest("piotroski_scores", ["f_score AS piotroski_f"])
    df = df.merge(pio, on="sid", how="left")

    # Accruals
    acc = _latest("accruals_scores", ["cf_accruals_ratio AS cf_accruals", "bs_accruals_ratio AS bs_accruals"])
    df = df.merge(acc, on="sid", how="left")

    # Consensus
    con = _latest("consensus_signals", ["consensus_signal"])
    df = df.merge(con, on="sid", how="left")

    # Promoter
    pro = _latest("promoter_signals", ["promoter_qoq"])
    df = df.merge(pro, on="sid", how="left")

    # Smart money
    sm = _latest("smart_money_scores", ["smart_money_score AS smart_money"])
    df = df.merge(sm, on="sid", how="left")

    # Sentiment
    sent = _latest("sentiment_scores", ["sentiment_7d"])
    df = df.merge(sent, on="sid", how="left")

    # Earnings yield + momentum (inline)
    from signals.earnings_yield import compute_earnings_yield
    from signals.momentum import compute_momentum

    ey = compute_earnings_yield()[["sid", "earnings_yield"]]
    df = df.merge(ey, on="sid", how="left")

    mom = compute_momentum()[["sid", "mom_6m", "mom_12m"]]
    df = df.merge(mom, on="sid", how="left")

    # Book-to-price
    bp = read_sql(
        "SELECT sid, total_equity / shares_outstanding / sp.close AS book_to_price "
        "FROM annual_balance_sheet bs "
        "JOIN (SELECT sid, close FROM stock_prices "
        "      WHERE (sid, date) IN (SELECT sid, MAX(date) FROM stock_prices GROUP BY sid)) sp USING(sid) "
        "WHERE (bs.sid, bs.period) IN (SELECT sid, MAX(period) FROM annual_balance_sheet GROUP BY sid) "
        "AND shares_outstanding > 0 AND sp.close > 0"
    )
    df = df.merge(bp, on="sid", how="left")

    # Delivery % (latest 30d avg)
    deliv = read_sql(
        "SELECT sid, AVG(delivery_pct) AS delivery_pct FROM stock_prices "
        "WHERE date >= date('now', '-30 days') AND delivery_pct IS NOT NULL "
        "GROUP BY sid"
    )
    df = df.merge(deliv, on="sid", how="left")

    df["snapshot_date"] = today

    # Select output columns matching schema
    out_cols = [
        "sid", "snapshot_date", "cap_tier", "close_price",
        "piotroski_f", "cf_accruals", "bs_accruals", "earnings_yield",
        "book_to_price", "consensus_signal", "promoter_qoq", "delivery_pct",
        "mom_6m", "mom_12m", "smart_money", "sentiment_7d",
    ]
    for col in out_cols:
        if col not in df.columns:
            df[col] = None

    out = df[out_cols]

    print(f"Snapshot: {len(out)} stocks, date={today}")
    filled = {col: out[col].notna().sum() for col in out_cols[3:]}  # skip sid/date/tier
    for col, n in filled.items():
        print(f"  {col}: {n}")

    if dry_run:
        print("\nDry run — not saving.")
        return len(out)

    rows = upsert_df(out, "daily_snapshots")
    print(f"Saved {rows} rows to daily_snapshots")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
