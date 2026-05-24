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
    """Min-max normalize column within each cap_tier to 0-100.

    Stocks with NaN in `col` stay NaN (we don't know vs. we know they're
    median). Pre-2026-05-23 a default 50.0 was substituted, which let the
    screener treat "no data" as "neutral" — ANO ranked #1 SMALL on a single
    promoter signal because bulk-deals/delivery were missing but smart_money
    came back 50 anyway.
    """
    result = pd.Series(np.nan, index=df.index)
    for tier in df[tier_col].dropna().unique():
        mask = df[tier_col] == tier
        vals = df.loc[mask, col]
        valid = vals.notna()
        if valid.sum() < 2:
            continue
        vmin, vmax = vals[valid].min(), vals[valid].max()
        if vmax > vmin:
            scaled = ((vals - vmin) / (vmax - vmin) * 100)
            # Keep NaN inputs as NaN in the output
            result.loc[mask & valid.reindex(df.index, fill_value=False)] = scaled[valid]
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

    # Merge bulk metrics. Stocks with no bulk deals are not "missing data" —
    # they're a real "0 net buy" observation. Fill with 0 so they participate
    # in the tier's min-max scaling instead of dropping out as NaN.
    df = df.merge(bulk_metrics, on="sid", how="left")
    for col in ["net_buy_qty", "buy_deals", "sell_deals", "repeat_buyers"]:
        if col in df.columns:
            df[col] = df[col].fillna(0)

    # Merge delivery metrics. Stocks with no price rows have genuinely missing
    # delivery data — keep as NaN so the composite propagates NaN, and the
    # screener treats smart_money as "unknown" rather than substituting a
    # phantom 50. See 2026-05-23 ANO bug: defaulted 50 made data-blank stocks
    # rank #1 SMALL on a single promoter signal.
    df = df.merge(deliv_metrics, on="sid", how="left")

    # Min-max normalize within tier (NaN inputs stay NaN per _minmax_by_tier)
    df["bulk_score"] = _minmax_by_tier(df, "net_buy_qty")
    df["delivery_score"] = _minmax_by_tier(df, "avg_deliv_pct")

    # Composite. NaN in either component propagates — that's intentional: a
    # stock with no delivery data has no smart_money read at all.
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

    # net_buy_qty is fillna(0), so notna() ≠ "has deals". Count distinct sids
    # with any bulk-deal activity instead.
    has_bulk = (df["buy_deals"].fillna(0) + df["sell_deals"].fillna(0) > 0).sum()
    has_deliv = df["delivery_score"].notna().sum()
    has_score = df["smart_money_score"].notna().sum()

    print(f"Smart Money: {len(df)} stocks")
    print(f"  Bulk deals: {has_bulk} stocks with deals in last {LOOKBACK_DAYS}d")
    print(f"  Delivery data: {has_deliv} stocks")
    print(f"  Computed score: {has_score} / {len(df)} stocks (rest NaN — no delivery data)")
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
