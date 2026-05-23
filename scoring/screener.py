"""
Alpha Signal v2 — Tier-Aware Scoring Engine

THE replacement for v1's 03_screener.py + 08_integrate_sentiment.py.

Reads all signal tables + inline signals (momentum, earnings yield).
Applies tier-specific weights from config.SIGNAL_WEIGHTS.
Ranks within each cap_tier. Applies forensic penalty.
Outputs scored universe to daily_picks table.

Usage:
    python -m scoring.screener            # score and save
    python -m scoring.screener --dry-run  # score but don't save
    python -m scoring.screener --top 20   # show top N per tier
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SIGNAL_WEIGHTS, PORTFOLIO
from db import read_sql, get_db, upsert_df


def _load_signals():
    """Load all signal values for the latest snapshot date."""
    stocks = read_sql("SELECT sid, ticker, name, sector, cap_tier FROM stocks")

    # Signal tables — get latest snapshot per stock
    piotroski = read_sql(
        "SELECT sid, f_score FROM piotroski_scores "
        "WHERE (sid, snapshot_date) IN (SELECT sid, MAX(snapshot_date) FROM piotroski_scores GROUP BY sid)"
    )
    accruals = read_sql(
        "SELECT sid, accruals_signal FROM accruals_scores "
        "WHERE (sid, snapshot_date) IN (SELECT sid, MAX(snapshot_date) FROM accruals_scores GROUP BY sid)"
    )
    consensus = read_sql(
        "SELECT sid, consensus_signal FROM consensus_signals "
        "WHERE (sid, snapshot_date) IN (SELECT sid, MAX(snapshot_date) FROM consensus_signals GROUP BY sid)"
    )
    promoter = read_sql(
        "SELECT sid, promoter_signal FROM promoter_signals "
        "WHERE (sid, snapshot_date) IN (SELECT sid, MAX(snapshot_date) FROM promoter_signals GROUP BY sid)"
    )
    forensic = read_sql(
        "SELECT sid, penalty FROM forensic_scores "
        "WHERE (sid, snapshot_date) IN (SELECT sid, MAX(snapshot_date) FROM forensic_scores GROUP BY sid)"
    )
    smart_money = read_sql(
        "SELECT sid, smart_money_score FROM smart_money_scores "
        "WHERE (sid, snapshot_date) IN (SELECT sid, MAX(snapshot_date) FROM smart_money_scores GROUP BY sid)"
    )

    # Inline signals (no DB table — compute on the fly)
    from signals.momentum import compute_momentum
    from signals.earnings_yield import compute_earnings_yield

    momentum = compute_momentum()
    earnings_yield = compute_earnings_yield()

    # Book-to-price: total_equity / (shares_outstanding * close_price)
    book_to_price = _compute_book_to_price()

    # Merge everything onto stocks
    df = stocks.copy()
    df = df.merge(piotroski, on="sid", how="left")
    df = df.merge(accruals.rename(columns={"accruals_signal": "accruals"}), on="sid", how="left")
    df = df.merge(consensus.rename(columns={"consensus_signal": "consensus"}), on="sid", how="left")
    df = df.merge(promoter.rename(columns={"promoter_signal": "promoter"}), on="sid", how="left")
    df = df.merge(forensic, on="sid", how="left")
    df = df.merge(smart_money.rename(columns={"smart_money_score": "smart_money"}), on="sid", how="left")
    df = df.merge(momentum, on="sid", how="left")
    df = df.merge(earnings_yield, on="sid", how="left")
    df = df.merge(book_to_price, on="sid", how="left")

    # Normalize smart_money from 0-100 to 0-1 for consistent percentile ranking
    df["smart_money"] = df["smart_money"] / 100.0

    return df


def _compute_book_to_price():
    """Compute B/P = book value per share / price."""
    bs = read_sql(
        "SELECT sid, total_equity, shares_outstanding FROM annual_balance_sheet "
        "WHERE (sid, period) IN (SELECT sid, MAX(period) FROM annual_balance_sheet GROUP BY sid)"
    )
    prices = read_sql(
        "SELECT sid, close FROM stock_prices "
        "WHERE (sid, date) IN (SELECT sid, MAX(date) FROM stock_prices GROUP BY sid)"
    )

    merged = bs.merge(prices, on="sid")
    rows = []
    for _, r in merged.iterrows():
        bvps = None
        if (pd.notna(r["total_equity"]) and pd.notna(r["shares_outstanding"])
                and r["shares_outstanding"] > 0 and r["close"] > 0):
            bvps = r["total_equity"] / r["shares_outstanding"]
            bp = bvps / r["close"]
            rows.append({"sid": r["sid"], "book_to_price": bp})
        else:
            rows.append({"sid": r["sid"], "book_to_price": None})

    return pd.DataFrame(rows)


def _percentile_rank_within_tier(df, col):
    """Rank column within cap_tier as 0-1 percentile."""
    return df.groupby("cap_tier")[col].rank(pct=True)


def score_universe(df):
    """
    Apply tier-specific weights, rank within segment, apply forensic penalty.
    Returns scored DataFrame with final_score and rank columns.
    """
    # Signal column mapping: config key → DataFrame column
    SIGNAL_COLS = {
        "consensus": "consensus",
        "earnings_yield": "earnings_yield",
        "accruals": "accruals",
        "piotroski": "f_score",
        "momentum": "mom_6m",        # 6M for LARGE, 12M for SMALL (handled below)
        "book_to_price": "book_to_price",
        "promoter": "promoter",
        "smart_money": "smart_money",
    }

    # Percentile-rank all signals within tier (higher = better for all)
    for signal_key, col in SIGNAL_COLS.items():
        if col in df.columns:
            df[f"{signal_key}_pctile"] = _percentile_rank_within_tier(df, col)

    # For SMALL cap momentum, use 12M instead of 6M
    if "mom_12m" in df.columns:
        mom_12m_pctile = _percentile_rank_within_tier(df, "mom_12m")
        small_mask = df["cap_tier"] == "SMALL"
        df.loc[small_mask, "momentum_pctile"] = mom_12m_pctile[small_mask]

    # Compute weighted score per tier
    scores = pd.Series(0.0, index=df.index)
    weight_sums = pd.Series(0.0, index=df.index)

    for tier in ["LARGE", "MID", "SMALL"]:
        tier_mask = df["cap_tier"] == tier
        weights = SIGNAL_WEIGHTS.get(tier, {})

        for signal_key, weight in weights.items():
            pctile_col = f"{signal_key}_pctile"
            if pctile_col in df.columns:
                vals = df.loc[tier_mask, pctile_col]
                valid = vals.notna()
                scores.loc[tier_mask & valid.reindex(df.index, fill_value=False)] += weight * vals[valid]
                weight_sums.loc[tier_mask & valid.reindex(df.index, fill_value=False)] += weight

    # Normalize by actual weights used (handles NaN signals gracefully)
    df["base_score"] = np.where(weight_sums > 0, scores / weight_sums, np.nan)

    # Apply forensic penalty
    df["penalty"] = df["penalty"].fillna(0)
    df["final_score"] = df["base_score"] + df["penalty"]
    df["final_score"] = df["final_score"].clip(lower=0)

    # Rank within tier (1 = best). Tie-break by sid for a deterministic 1..N
    # ordering — `method="min"` collapses ties to a shared rank and breaks
    # `SANITY:DAILY_PICKS_RANK_DUPLICATE` (PK (pick_date, cap_tier, rank)).
    df = df.sort_values(["cap_tier", "sid"], kind="mergesort").reset_index(drop=True)
    df["rank"] = df.groupby("cap_tier")["final_score"].rank(
        ascending=False, method="first", na_option="keep"
    ).astype("Int64")

    return df


def select_picks(df, picks_per_tier=None):
    """Select top stocks per tier for daily output."""
    if picks_per_tier is None:
        picks_per_tier = PORTFOLIO["picks_per_tier"]

    picks = []
    for tier, n in picks_per_tier.items():
        tier_df = df[df["cap_tier"] == tier].nsmallest(n, "rank")
        picks.append(tier_df)

    return pd.concat(picks).sort_values(["cap_tier", "rank"])


def compute(dry_run=False, top=None):
    """Main entry point. Returns row count."""
    print("Loading signals...")
    df = _load_signals()

    print("Scoring universe...")
    df = score_universe(df)

    today = date.today().isoformat()

    # Summary
    for tier in ["LARGE", "MID", "SMALL"]:
        t = df[df["cap_tier"] == tier]
        scored = t["final_score"].notna().sum()
        print(f"  {tier}: {scored} scored, mean={t['final_score'].dropna().mean():.3f}")

    # Show top picks
    show_n = top or 5
    picks = select_picks(df, {t: show_n for t in ["LARGE", "MID", "SMALL"]})
    print(f"\nTop {show_n} per tier:")
    display_cols = ["rank", "cap_tier", "sid", "ticker", "sector", "final_score", "base_score", "penalty"]
    print(picks[display_cols].to_string(index=False))

    if dry_run:
        print("\nDry run — not saving.")
        return len(df)

    # Save to daily_picks
    pick_date = today
    out = df[["sid", "final_score", "rank", "base_score", "cap_tier", "sector",
              "consensus", "accruals", "promoter"]].copy()
    out["pick_date"] = pick_date
    out["sentiment_adj"] = 0  # placeholder
    out["insider_adj"] = 0
    out["forensic_adj"] = df["penalty"]
    out["macro_adj"] = 0
    out["piotroski_adj"] = 0
    out["accruals_adj"] = 0
    out["consensus_adj"] = 0
    out["promoter_adj"] = 0
    out["smart_money_adj"] = 0

    # Match daily_picks schema
    picks_out = out[["sid", "pick_date", "final_score", "rank", "base_score",
                     "sentiment_adj", "insider_adj", "forensic_adj", "macro_adj",
                     "piotroski_adj", "accruals_adj", "consensus_adj", "promoter_adj",
                     "smart_money_adj", "cap_tier", "sector"]]

    rows = upsert_df(picks_out, "daily_picks")
    print(f"\nSaved {rows} rows to daily_picks (date={pick_date})")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--top", type=int, default=5, help="Show top N per tier")
    args = parser.parse_args()
    compute(dry_run=args.dry_run, top=args.top)
