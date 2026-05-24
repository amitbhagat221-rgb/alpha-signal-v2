"""
Alpha Signal v2 — Promoter Buying Momentum Signal

Three components:
  1. Promoter QoQ:     latest quarter change in promoter % (35%)
  2. Promoter Trend:   1-year change in promoter % (35%)
  3. Pledge Quality:   1 - (pledge% / 100) (30%)

Asymmetric adjustment: selling dampened before ranking (Brochet et al. 2017).
Holding level modifier: >75% or <25% stake dampens signal (Selarka 2006).
Within-segment percentile ranking + NaN-tolerant weighted average.

Reads: shareholding, stocks
Writes: promoter_signals

Usage:
    python -m signals.promoter            # compute and save
    python -m signals.promoter --dry-run  # compute but don't save
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from db import read_sql, upsert_df

# Composite weights
WEIGHTS = {"qoq": 0.35, "trend": 0.35, "pledge": 0.30}


def _asymmetric_adjust(val):
    """Dampen selling signals (non-informative) while preserving buying."""
    if pd.isna(val):
        return val
    if val >= 0:
        return val  # buying: full strength
    if val < -2.0:
        return val * 0.3  # significant selling: 30%
    return val * 0.5  # small selling: 50%


def _holding_modifier(promoter_latest):
    """Nonlinear modifier based on absolute stake level.

    Returns None when promoter_latest is unknown — caller must treat that as
    "no modifier" (signal = raw, not raw * 0.9). Pre-2026-05-24 returned 0.9
    on NaN which let stocks without a known stake migrate to a fixed signal
    cluster (see 2026-05-24 audit: 398/2448 promoter_signal values at 0.60).
    """
    if pd.isna(promoter_latest):
        return None
    if promoter_latest > 75:
        return 0.7  # concentrated, governance risk
    if 40 <= promoter_latest <= 65:
        return 1.0  # sweet spot
    if promoter_latest < 25:
        return 0.8  # dispersed
    return 0.9  # default (25-40 or 65-75)


def _load_data():
    """Load shareholding and stock metadata."""
    stocks = read_sql("SELECT sid, cap_tier FROM stocks")
    sh = read_sql(
        "SELECT sid, end_date, promoter_pct, pledge_pct "
        "FROM shareholding ORDER BY sid, end_date"
    )
    return stocks, sh


def _compute_scores(stocks, sh):
    """Compute promoter signal for all stocks."""
    sh_by_sid = dict(list(sh.groupby("sid")))
    tier_map = stocks.set_index("sid")["cap_tier"].to_dict()

    rows = []
    for sid in stocks["sid"]:
        row = {"sid": sid, "cap_tier": tier_map.get(sid)}

        g = sh_by_sid.get(sid)
        if g is None or len(g) == 0:
            rows.append(row)
            continue

        g = g.sort_values("end_date")
        latest = g.iloc[-1]

        row["promoter_latest"] = latest["promoter_pct"]

        # QoQ change (need >= 2 quarters)
        if len(g) >= 2:
            row["promoter_qoq"] = g.iloc[-1]["promoter_pct"] - g.iloc[-2]["promoter_pct"]

        # 1-year trend (need >= 5 quarters)
        if len(g) >= 5:
            row["promoter_trend_4q"] = g.iloc[-1]["promoter_pct"] - g.iloc[-5]["promoter_pct"]

        # Pledge quality
        pledge = latest.get("pledge_pct")
        if pd.notna(pledge):
            row["pledge_quality"] = 1.0 - (pledge / 100.0)

        rows.append(row)

    df = pd.DataFrame(rows)

    # Asymmetric adjustment before ranking
    df["qoq_adj"] = df.get("promoter_qoq", pd.Series(dtype=float)).apply(_asymmetric_adjust)
    df["trend_adj"] = df.get("promoter_trend_4q", pd.Series(dtype=float)).apply(_asymmetric_adjust)

    # Within-segment percentile ranking (qoq and trend only; pledge is direct 0-1)
    for tier in df["cap_tier"].dropna().unique():
        mask = df["cap_tier"] == tier
        df.loc[mask, "qoq_score"] = df.loc[mask, "qoq_adj"].rank(pct=True)
        df.loc[mask, "trend_score"] = df.loc[mask, "trend_adj"].rank(pct=True)

    # NaN-tolerant weighted average
    score_map = {"qoq": "qoq_score", "trend": "trend_score", "pledge": "pledge_quality"}
    signals = []

    for _, row in df.iterrows():
        num, den = 0.0, 0.0
        for key, col in score_map.items():
            val = row.get(col)
            if pd.notna(val):
                num += WEIGHTS[key] * val
                den += WEIGHTS[key]

        if den > 0.01:
            raw = num / den
            modifier = _holding_modifier(row.get("promoter_latest"))
            if modifier is None:
                signals.append(round(raw, 4))  # no stake info → don't dampen
            else:
                signals.append(round(raw * modifier, 4))
        else:
            signals.append(None)

    df["promoter_signal"] = signals

    # Determine promoter_trend label
    def _trend_label(row):
        qoq = row.get("promoter_qoq")
        trend = row.get("promoter_trend_4q")
        if pd.isna(qoq) and pd.isna(trend):
            return None
        qoq = qoq if pd.notna(qoq) else 0
        trend = trend if pd.notna(trend) else 0
        if qoq > 0 and trend > 0:
            return "ACCUMULATING"
        if qoq < 0 and trend < 0:
            return "REDUCING"
        if abs(qoq) < 0.01 and abs(trend) < 0.5:
            return "STABLE"
        return "MIXED"

    df["promoter_trend"] = df.apply(_trend_label, axis=1)

    # Output columns matching v2 schema
    out = df[["sid", "promoter_qoq", "promoter_trend", "pledge_quality",
              "promoter_signal"]].copy()
    return out


def compute(dry_run=False):
    """Main entry point. Returns row count."""
    stocks, sh = _load_data()
    df = _compute_scores(stocks, sh)

    snapshot = date.today().isoformat()
    df["snapshot_date"] = snapshot

    has_signal = df["promoter_signal"].notna().sum()
    print(f"Promoter: {len(df)} stocks, {has_signal} with signal")
    print(f"  QoQ: {df['promoter_qoq'].notna().sum()} non-null")
    print(f"  Pledge quality: {df['pledge_quality'].notna().sum()} non-null")
    if has_signal > 0:
        print(f"  Signal mean={df['promoter_signal'].mean():.3f}, median={df['promoter_signal'].median():.3f}")
    print(f"  Trend: {df['promoter_trend'].value_counts().to_dict()}")

    if dry_run:
        print("\nDry run — not saving.")
        return len(df)

    rows = upsert_df(df, "promoter_signals")
    print(f"Saved {rows} rows to promoter_signals (snapshot={snapshot})")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
