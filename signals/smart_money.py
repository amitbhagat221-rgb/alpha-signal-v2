"""
Alpha Signal v2 — Smart Money Signal

Two components:
  1. Bulk Score (60%): net buy quantity, deal counts, repeat buyers from bulk/block deals
  2. Delivery Score (40%): avg delivery % over 30 days from stock_prices

Both min-max normalized within cap_tier. Final: 0-100 scale.

Reads: bulk_deals, stock_prices, stocks
Writes: smart_money_scores

Usage:
    python -m signals.smart_money            # compute and save
    python -m signals.smart_money --dry-run  # compute but don't save
"""

import argparse
from datetime import date, timedelta

import numpy as np
import pandas as pd

from db import read_sql, upsert_df

BULK_WEIGHT = 0.60
DELIVERY_WEIGHT = 0.40
LOOKBACK_DAYS = 30


def _minmax_by_tier(df, col, tier_col="cap_tier"):
    """Min-max normalize column within each cap_tier to 0-100."""
    result = pd.Series(50.0, index=df.index)  # default neutral
    for tier in df[tier_col].dropna().unique():
        mask = df[tier_col] == tier
        vals = df.loc[mask, col]
        if vals.notna().sum() < 2:
            continue
        vmin, vmax = vals.min(), vals.max()
        if vmax > vmin:
            result[mask] = ((vals - vmin) / (vmax - vmin) * 100).fillna(50.0)
    return result


def _load_data():
    """Load bulk deals, delivery data, and universe."""
    stocks = read_sql("SELECT sid, cap_tier FROM stocks")

    cutoff = (date.today() - timedelta(days=LOOKBACK_DAYS + 5)).isoformat()

    bulk = read_sql(
        "SELECT sid, symbol, client_name, buy_sell, quantity, price, deal_date "
        "FROM bulk_deals WHERE deal_date >= ?",
        params=[cutoff],
    )

    # Delivery % from stock_prices (last 30 days)
    delivery = read_sql(
        "SELECT sid, date, delivery_pct, close "
        "FROM stock_prices WHERE date >= ? AND delivery_pct IS NOT NULL",
        params=[cutoff],
    )

    return stocks, bulk, delivery


def _compute_bulk_metrics(bulk):
    """Compute per-stock bulk deal metrics."""
    if bulk.empty:
        return pd.DataFrame(columns=["sid", "net_buy_qty", "buy_deals", "sell_deals", "repeat_buyers"])

    rows = []
    for sid, group in bulk.groupby("sid"):
        buys = group[group["buy_sell"].str.upper().str.startswith("B")]
        sells = group[group["buy_sell"].str.upper().str.startswith("S")]

        net_buy_qty = buys["quantity"].sum() - sells["quantity"].sum()
        buy_deals = len(buys)
        sell_deals = len(sells)

        # Repeat buyers: clients buying on 2+ distinct dates
        if not buys.empty:
            buyer_dates = buys.groupby("client_name")["deal_date"].nunique()
            repeat_buyers = (buyer_dates >= 2).sum()
        else:
            repeat_buyers = 0

        rows.append({
            "sid": sid,
            "net_buy_qty": net_buy_qty,
            "buy_deals": buy_deals,
            "sell_deals": sell_deals,
            "repeat_buyers": repeat_buyers,
        })

    return pd.DataFrame(rows)


def _compute_delivery_metrics(delivery):
    """Compute per-stock delivery metrics (30-day avg)."""
    if delivery.empty:
        return pd.DataFrame(columns=["sid", "avg_deliv_pct"])

    metrics = delivery.groupby("sid").agg(
        avg_deliv_pct=("delivery_pct", "mean"),
    ).reset_index()

    return metrics


def _compute_scores(stocks, bulk, delivery):
    """Compute smart money score for all stocks."""
    bulk_metrics = _compute_bulk_metrics(bulk)
    deliv_metrics = _compute_delivery_metrics(delivery)

    # Start with all stocks
    df = stocks.copy()

    # Merge bulk metrics
    df = df.merge(bulk_metrics, on="sid", how="left")

    # Merge delivery metrics
    df = df.merge(deliv_metrics, on="sid", how="left")

    # Min-max normalize within tier
    df["bulk_score"] = _minmax_by_tier(df, "net_buy_qty")
    df["delivery_score"] = _minmax_by_tier(df, "avg_deliv_pct")

    # Composite
    df["smart_money_score"] = (
        df["bulk_score"] * BULK_WEIGHT + df["delivery_score"] * DELIVERY_WEIGHT
    ).round(1)

    # Output columns matching schema
    out_cols = ["sid", "bulk_score", "delivery_score", "smart_money_score",
                "net_buy_qty", "buy_deals", "sell_deals", "repeat_buyers"]
    for col in out_cols:
        if col not in df.columns:
            df[col] = None

    # Convert deal counts to int where present
    for col in ["buy_deals", "sell_deals", "repeat_buyers"]:
        df[col] = df[col].apply(lambda x: int(x) if pd.notna(x) else None)

    return df[out_cols]


def compute(dry_run=False):
    """Main entry point. Returns row count."""
    stocks, bulk, delivery = _load_data()
    df = _compute_scores(stocks, bulk, delivery)

    snapshot = date.today().isoformat()
    df["snapshot_date"] = snapshot

    has_bulk = df["net_buy_qty"].notna().sum()
    has_deliv = df["delivery_score"].notna().sum()

    print(f"Smart Money: {len(df)} stocks")
    print(f"  Bulk deals: {has_bulk} stocks with deals in last {LOOKBACK_DAYS}d")
    print(f"  Delivery data: {has_deliv} stocks")
    print(f"  Score mean={df['smart_money_score'].mean():.1f}, median={df['smart_money_score'].median():.1f}")

    if dry_run:
        print("\nDry run — not saving.")
        return len(df)

    rows = upsert_df(df, "smart_money_scores")
    print(f"Saved {rows} rows to smart_money_scores (snapshot={snapshot})")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
