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

from config import SIGNAL_WEIGHTS, PORTFOLIO, SCREEN
from db import read_sql, get_db, upsert_df


def _load_signals():
    """Load all signal values for the latest snapshot date."""
    stocks = read_sql("SELECT sid, ticker, name, sector, cap_tier FROM stocks")

    # Drop InvIT / REIT / business-trust instruments — different ranking
    # semantics from equities (distribution-yield vehicles, low float).
    # See SCREEN["trust_exclusion_patterns"]. 2026-05-24 audit found SHREI
    # (Shrem InvIT) with 40 of 65 trading days in last 90d ranked into SMALL.
    patterns = SCREEN.get("trust_exclusion_patterns", [])
    if patterns:
        pat_re = "|".join(patterns)
        trust_mask = stocks["name"].str.contains(pat_re, case=False, regex=True, na=False)
        dropped = trust_mask.sum()
        if dropped:
            print(f"  Excluded {dropped} InvIT/REIT/trust instruments from screener universe")
        stocks = stocks[~trust_mask].reset_index(drop=True)

    # Per-sid price-row count, used by the has-prices pick-eligibility gate.
    # A stock with zero (or near-zero) price history can't be charted, can't
    # have momentum/EY/B-P computed, and isn't really actionable even if it
    # scores well on fundamentals alone.
    price_counts = read_sql(
        "SELECT sid, COUNT(*) AS price_rows FROM stock_prices WHERE close > 0 GROUP BY sid"
    )

    # Per-sid quarterly_income row count → fundamental_coverage. INPUT-side
    # coverage (vs weight_coverage which is OUTPUT-side). 2026-05-24 audit:
    # ABSM ranked #164 SMALL with weight_coverage~0.6 because signal modules
    # emit non-NULL outputs from partial inputs (accruals_signal from BS
    # alone, consensus_signal from growth-only). Input coverage catches that.
    fundamental_counts = read_sql(
        "SELECT sid, COUNT(*) AS quarters_present FROM quarterly_income GROUP BY sid"
    )

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
    df = df.merge(price_counts, on="sid", how="left")
    df["price_rows"] = df["price_rows"].fillna(0).astype(int)

    df = df.merge(fundamental_counts, on="sid", how="left")
    df["quarters_present"] = df["quarters_present"].fillna(0).astype(int)
    df["fundamental_coverage"] = (df["quarters_present"] / 8.0).clip(upper=1.0)

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

    # Compute weighted score per tier. We track both the score numerator (sum
    # of weight × pctile for non-null signals) and the weight coverage (sum of
    # weights actually contributing). Coverage is used both for the score
    # denominator AND as a pick-eligibility gate further down.
    scores = pd.Series(0.0, index=df.index)
    weight_sums = pd.Series(0.0, index=df.index)
    tier_total_weight = pd.Series(0.0, index=df.index)

    for tier in ["LARGE", "MID", "SMALL"]:
        tier_mask = df["cap_tier"] == tier
        weights = SIGNAL_WEIGHTS.get(tier, {})
        total_weight = sum(weights.values())
        tier_total_weight.loc[tier_mask] = total_weight

        for signal_key, weight in weights.items():
            pctile_col = f"{signal_key}_pctile"
            if pctile_col in df.columns:
                vals = df.loc[tier_mask, pctile_col]
                valid = vals.notna()
                scores.loc[tier_mask & valid.reindex(df.index, fill_value=False)] += weight * vals[valid]
                weight_sums.loc[tier_mask & valid.reindex(df.index, fill_value=False)] += weight

    # Normalize by actual weights used (handles NaN signals gracefully)
    df["base_score"] = np.where(weight_sums > 0, scores / weight_sums, np.nan)

    # Weight coverage = fraction of the tier's total weight backed by real data.
    # A stock with promoter+smart_money only on SMALL has coverage = 0.35/1.0.
    # Used by select_picks() as an eligibility gate — 2026-05-23 ANO ranked
    # #1 SMALL with coverage=0.25 (1 of 7 signals real after smart_money fix),
    # which is exactly what the gate is meant to catch.
    df["weight_coverage"] = np.where(
        tier_total_weight > 0, weight_sums / tier_total_weight, np.nan
    )

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


MIN_WEIGHT_COVERAGE = 0.50  # ≥50% of tier signal weight backed by non-NULL signal OUTPUT
MIN_PRICE_ROWS = 60         # ≈3 months of trading days
MIN_FUNDAMENTAL_COVERAGE = 0.50  # ≥4 of 8 quarterly_income rows (INPUT-side, added 2026-05-24)
# Thresholds + rationale: docs/decisions/0021-pick-eligibility-gate.md


def _pick_eligible(df):
    """Boolean Series: True where stock qualifies for daily_picks."""
    has_coverage = df["weight_coverage"].fillna(0) >= MIN_WEIGHT_COVERAGE
    has_prices = df["price_rows"].fillna(0) >= MIN_PRICE_ROWS
    has_fundamentals = df["fundamental_coverage"].fillna(0) >= MIN_FUNDAMENTAL_COVERAGE
    return has_coverage & has_prices & has_fundamentals


def select_picks(df, picks_per_tier=None):
    """Select top stocks per tier for daily output.

    Two-part gate:
      • `weight_coverage` ≥ 50% — at least half the tier signal weight backed
        by real data (rather than missing-signal renormalization inflating the
        score of a stock with only 1-2 signals).
      • `price_rows` ≥ 60 — at least ~3 months of price history. Without
        prices the stock has no chart, no momentum/EY/B-P, and isn't really
        actionable even if fundamentals look strong.
    """
    if picks_per_tier is None:
        picks_per_tier = PORTFOLIO["picks_per_tier"]

    eligible = _pick_eligible(df)
    dropped_coverage = ((df["weight_coverage"].fillna(0) < MIN_WEIGHT_COVERAGE)).sum()
    dropped_prices = ((df["price_rows"].fillna(0) < MIN_PRICE_ROWS)).sum()
    dropped_fundamentals = ((df["fundamental_coverage"].fillna(0) < MIN_FUNDAMENTAL_COVERAGE)).sum()
    print(f"  Pick gate: {(~eligible).sum()} excluded "
          f"({dropped_coverage} below {MIN_WEIGHT_COVERAGE:.0%} weight, "
          f"{dropped_prices} below {MIN_PRICE_ROWS}d prices, "
          f"{dropped_fundamentals} below {MIN_FUNDAMENTAL_COVERAGE:.0%} fundamentals)")

    picks = []
    for tier, n in picks_per_tier.items():
        tier_df = df[(df["cap_tier"] == tier) & eligible].nsmallest(n, "rank")
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

    # Save to daily_picks. Apply pick gate before saving — data-sparse and
    # priceless stocks stay out of daily_picks entirely so dossier/email
    # pipelines can't surface them as recommendations. Rank is re-densified
    # within the eligible set so the saved column reads as 1..N_eligible
    # without gaps.
    pick_date = today
    eligible_mask = _pick_eligible(df)
    eligible = df[eligible_mask].copy()
    gated_out = (~eligible_mask).sum()
    if gated_out:
        print(f"  Pick gate excluded {gated_out} stocks from daily_picks")

    eligible["rank"] = eligible.groupby("cap_tier")["final_score"].rank(
        ascending=False, method="first", na_option="keep"
    ).astype("Int64")

    out = eligible[["sid", "final_score", "rank", "base_score", "cap_tier", "sector",
                    "consensus", "accruals", "promoter",
                    "weight_coverage", "price_rows", "fundamental_coverage"]].copy()
    out["pick_date"] = pick_date
    out["sentiment_adj"] = 0  # placeholder
    out["insider_adj"] = 0
    out["forensic_adj"] = eligible["penalty"]
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
                     "smart_money_adj", "cap_tier", "sector",
                     "weight_coverage", "price_rows", "fundamental_coverage"]]

    # Delete today's prior rows before insert. Upsert is REPLACE on (sid, pick_date)
    # which leaves rows untouched if today's run drops a sid (gated out by
    # coverage). Without this, rank gaps + duplicate rank values from prior
    # runs accumulate in the table.
    from db import get_db
    with get_db() as conn:
        conn.execute("DELETE FROM daily_picks WHERE pick_date = ?", (pick_date,))

    rows = upsert_df(picks_out, "daily_picks")
    print(f"\nSaved {rows} rows to daily_picks (date={pick_date})")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--top", type=int, default=5, help="Show top N per tier")
    args = parser.parse_args()
    compute(dry_run=args.dry_run, top=args.top)
