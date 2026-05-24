"""
Alpha Signal v2 — Analyst Consensus Signal

Four sub-signals:
  1. PT Revision 1yr:  YoY change in price target (35%)
  2. PT Upside:        (PT / current price - 1) (15%)
  3. EPS Growth:       forward EPS growth % (35%)
  4. Revenue Growth:   forward revenue growth % (15%)

Within-segment percentile ranking, NaN-tolerant weighted average,
analyst confidence scaling (pulls low-coverage toward neutral 0.5).

No sector exclusions — all stocks included.

Reads: analyst_consensus, forecast_history, stock_prices, stocks
Writes: consensus_signals

Usage:
    python -m signals.consensus            # compute and save
    python -m signals.consensus --dry-run  # compute but don't save
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from db import read_sql, upsert_df

# Sub-signal weights. `pt_rev` dropped 2026-05-23 — its source
# (forecast_history.metric='price') was current close masquerading as PT,
# meaning the YoY computation = 1-year price return, not PT revision. Made
# up 35% of consensus_signal which is 40% of LARGE final_score → 14% of
# every LARGE rank was contaminated. Redistributed proportionally; will
# rebuild from analyst_consensus_snapshots once 12mo accumulates (2027-05).
WEIGHTS = {"pt_up": 0.23, "eps": 0.54, "rev": 0.23}

# Clipping ranges (before ranking)
CLIP = {
    "pt_upside": (-50, 150),
    "eps_growth": (-50, 100),
    "revenue_growth": (-30, 80),
}

# Analyst confidence tiers
def _confidence(n_analysts):
    if pd.isna(n_analysts) or n_analysts < 3:
        return 0.3
    if n_analysts < 5:
        return 0.6
    return 1.0


def _load_data():
    """Load all inputs."""
    stocks = read_sql("SELECT sid, cap_tier FROM stocks")

    # Analyst attribution gate: require total_analysts>0 OR price_target NOT NULL.
    # Was originally `total_analysts IS NOT NULL` — but yfinance returns 0
    # (explicit zero) for some stocks, which passed the IS NOT NULL check. Phase B
    # integrity validator (validators/per_stock_integrity.py) caught 14 stocks
    # ranked with consensus_signal but n=0 and PT=NULL. Tightened to > 0.
    consensus = read_sql(
        "SELECT sid, total_analysts, price_target, eps_growth_pct, revenue_growth_pct "
        "FROM analyst_consensus "
        "WHERE has_analyst_data = 1 "
        "  AND ((total_analysts IS NOT NULL AND total_analysts > 0) OR price_target IS NOT NULL)"
    )

    # NOTE: forecast_history removed 2026-05-23. metric='price' was contaminated
    # (current close labeled as historical PT); eps/revenue forecasts are real
    # but already covered by analyst_consensus.{eps,revenue}_growth_pct.

    # Latest close price per stock
    prices = read_sql(
        "SELECT sid, close FROM stock_prices "
        "WHERE (sid, date) IN ("
        "  SELECT sid, MAX(date) FROM stock_prices GROUP BY sid"
        ")"
    )

    return stocks, consensus, prices


def _compute_scores(stocks, consensus, prices):
    """Compute consensus signal for all stocks."""
    # PT upside — merge consensus PT with latest price
    pt_upside_map = {}
    price_map = prices.set_index("sid")["close"].to_dict()
    for _, row in consensus.iterrows():
        sid = row["sid"]
        pt = row["price_target"]
        cmp = price_map.get(sid)
        if pd.notna(pt) and pd.notna(cmp) and cmp > 0:
            pt_upside_map[sid] = ((pt / cmp) - 1) * 100

    # Build DataFrame
    tier_map = stocks.set_index("sid")["cap_tier"].to_dict()
    consensus_map = consensus.set_index("sid")

    rows = []
    for sid in stocks["sid"]:
        row = {"sid": sid, "cap_tier": tier_map.get(sid)}

        # PT upside
        if sid in pt_upside_map:
            row["pt_upside"] = pt_upside_map[sid]

        # EPS and revenue growth from consensus
        if sid in consensus_map.index:
            c = consensus_map.loc[sid]
            if pd.notna(c.get("eps_growth_pct")):
                row["eps_growth"] = c["eps_growth_pct"]
            if pd.notna(c.get("revenue_growth_pct")):
                row["revenue_growth"] = c["revenue_growth_pct"]

            row["total_analysts"] = c.get("total_analysts")

        rows.append(row)

    df = pd.DataFrame(rows)

    # Clip before ranking
    for col, (lo, hi) in CLIP.items():
        if col in df.columns:
            df[col + "_clipped"] = df[col].clip(lower=lo, upper=hi)

    # Within-segment percentile ranking (higher = better for all sub-signals).
    # pt_rev removed 2026-05-23 (data contamination — see WEIGHTS comment).
    rank_cols = {
        "pt_up": "pt_upside_clipped",
        "eps": "eps_growth_clipped",
        "rev": "revenue_growth_clipped",
    }

    for key, col in rank_cols.items():
        score_col = f"{key}_score"
        if col in df.columns:
            df[score_col] = df.groupby("cap_tier")[col].rank(pct=True)

    # NaN-tolerant weighted average
    score_cols = {k: f"{k}_score" for k in WEIGHTS}
    signals = []
    for _, row in df.iterrows():
        num, den = 0.0, 0.0
        for key, col in score_cols.items():
            val = row.get(col)
            if pd.notna(val):
                num += WEIGHTS[key] * val
                den += WEIGHTS[key]

        if den > 0.01:
            raw = num / den
            # Analyst confidence scaling
            conf = _confidence(row.get("total_analysts"))
            signal = 0.5 + (raw - 0.5) * conf
            signals.append(round(signal, 4))
        else:
            signals.append(None)

    df["consensus_signal"] = signals

    # Output columns matching schema. pt_revision_1yr is now always NULL
    # (column kept for schema compat; legacy historical rows still hold values).
    df["pt_revision_1yr"] = None
    out = df[["sid", "pt_upside", "pt_revision_1yr", "eps_growth",
              "revenue_growth", "consensus_signal"]].copy()
    return out


def compute(dry_run=False):
    """Main entry point. Returns row count."""
    stocks, consensus, prices = _load_data()
    df = _compute_scores(stocks, consensus, prices)

    snapshot = date.today().isoformat()
    df["snapshot_date"] = snapshot

    has_signal = df["consensus_signal"].notna().sum()
    print(f"Consensus: {len(df)} stocks, {has_signal} with signal")
    for col in ["pt_upside", "eps_growth", "revenue_growth"]:
        n = df[col].notna().sum()
        print(f"  {col}: {n} non-null")
    if has_signal > 0:
        print(f"  Signal mean={df['consensus_signal'].mean():.3f}, median={df['consensus_signal'].median():.3f}")

    if dry_run:
        print("\nDry run — not saving.")
        return len(df)

    rows = upsert_df(df, "consensus_signals")
    print(f"Saved {rows} rows to consensus_signals (snapshot={snapshot})")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
