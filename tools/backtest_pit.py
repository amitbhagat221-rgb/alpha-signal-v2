"""
Alpha Signal v2 — PIT Backtest Harness.

For each (signal, cap_tier): compute Spearman IC vs forward 20-day return per
eval_date, then aggregate to t-stat. Writes pit_ic_by_tier_v2.

Two sources of PIT data:
  - daily_snapshots_pit_v1  (35 dates, 2023-04 → 2026-02, has fwd_return_20d)
  - daily_snapshots_pit     (7 dates, 2025-11 → 2026-05, fwd_return for older only)

Strategy:
  - For each (signal, tier), use whichever PIT source has the column populated.
  - When both have it, prefer v1 (canonical historical). When only v2 has it
    (m_score, z_score, all the new ones), use v2.

Verdict thresholds (from C13b):
  |t| ≥ 2.5 → KEEP   (primary, 1.0× weight in screener)
  |t| 1.5-2.5 → WEAK (secondary, 0.5×)
  |t| 0.5-1.5 → DROP (tertiary, 0.2×)
  |t| < 0.5  → DROP

Usage:
    python -m tools.backtest_pit              # all signals × all tiers
    python -m tools.backtest_pit --signal piotroski_f
    python -m tools.backtest_pit --dry-run    # don't write
"""

import argparse
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from db import get_db, read_sql, upsert_df


# Mapping: signal_id (registry) → (v1_column, v2_column)
# v1 column may be None for v2-only signals (m_score, z_score, etc.)
# Some signals are pure-stock-feature → ranked vs forward return
SIGNAL_COLUMN_MAP = {
    # Quality
    "piotroski_f_score":   ("piotroski_f", "piotroski_f"),
    "cf_accruals_ratio":   ("cf_accruals", "cf_accruals"),
    "bs_accruals_ratio":   ("bs_accruals", "bs_accruals"),
    "earnings_persistence": ("eps_cv", "earnings_persistence"),
    "earnings_beat_rate":  ("earnings_beat_rate", None),
    "roe":                 (None, "roe"),
    "roa":                 (None, "roa"),
    "debt_to_equity":      (None, "debt_to_equity"),
    "profit_margin":       (None, "profit_margin"),
    # Value
    "earnings_yield":      ("earnings_yield", "earnings_yield"),
    "book_to_price":       ("book_to_price", "book_to_price"),
    "position_52w":        (None, "position_52w"),
    # Growth
    "revenue_growth_yoy":  (None, "revenue_growth_yoy"),
    "eps_growth_yoy":      (None, "eps_growth_yoy"),
    # Momentum
    "mom_6m_adj":          ("mom_6m", "mom_6m"),
    "mom_12m_adj":         ("mom_12m", "mom_12m"),
    "macd_signal":         (None, "macd_bullish"),
    # Ownership
    "promoter_qoq":        ("promoter_qoq", "promoter_qoq"),
    "promoter_trend_4q":   (None, "promoter_trend_4q"),
    "pledge_quality":      ("pledge_quality", "pledge_quality"),
    # Forensic
    "m_score":             (None, "m_score"),
    "z_score":             (None, "z_score"),
    # Smart Money
    "avg_delivery_pct_30d": ("avg_delivery_pct_30d", "avg_delivery_pct_30d"),
    "delivery_anomaly_z":  (None, "delivery_anomaly_z"),
    "bulk_deal_signal":    (None, "bulk_deal_signal"),
    "short_selling_signal": (None, "short_selling_signal"),
    # Consensus
    "pt_upside":           (None, "pt_upside"),
    "pt_revision_yoy":     (None, "pt_revision_yoy"),
    "eps_revision_yoy":    (None, "eps_revision_yoy"),
    "consensus_signal_combined": (None, "consensus_signal_combined"),
    # Composites
    "value_composite":     (None, "value_composite"),
    "quality_composite":   (None, "quality_composite"),
    "growth_composite":    (None, "growth_composite"),
    "mom_composite":       (None, "mom_composite"),
    # F-track cluster (plan 0007)
    "revenue_cv_5y":       (None, "revenue_cv_5y"),
    "relative_turnover":   (None, "relative_turnover"),
    "relative_growth":     (None, "relative_growth"),
    "share_momentum":      (None, "share_momentum"),
    # forward return — same column in both
    "_response": ("fwd_return_20d", "fwd_return_20d"),
}


def _verdict(t):
    """C13b verdict from t-stat absolute value."""
    if t is None or pd.isna(t):
        return "INSUFFICIENT"
    t_abs = abs(t)
    if t_abs >= 2.5:
        return "KEEP"
    if t_abs >= 1.5:
        return "WEAK"
    return "DROP"


def _compute_ic(df, signal_col, fwd_col):
    """Per-period spearman IC of signal vs forward return.

    Returns: list of (eval_date, ic, n_stocks) tuples.
    """
    out = []
    for eval_date, group in df.groupby("snapshot_date"):
        sub = group[[signal_col, fwd_col]].dropna()
        if len(sub) < 20:  # need at least 20 stocks for stable IC
            continue
        try:
            ic, _ = spearmanr(sub[signal_col], sub[fwd_col])
            if pd.isna(ic):
                continue
            out.append((eval_date, float(ic), len(sub)))
        except Exception:
            continue
    return out


def _aggregate(ic_rows, signal, cap_tier, source):
    """Aggregate per-period IC list into a single (signal, tier) result."""
    if not ic_rows:
        return None
    ics = np.array([r[1] for r in ic_rows])
    n_stocks = int(np.mean([r[2] for r in ic_rows]))
    n_periods = len(ic_rows)
    mean_ic = float(ics.mean())
    std_ic = float(ics.std(ddof=1)) if n_periods > 1 else None
    icir = mean_ic / std_ic if std_ic and std_ic > 0 else None
    # t-stat = ICIR * sqrt(n_periods); approximation
    t_stat = icir * np.sqrt(n_periods) if icir is not None else None

    return {
        "signal": signal,
        "cap_tier": cap_tier,
        "n_periods": n_periods,
        "n_stocks_avg": n_stocks,
        "mean_ic": round(mean_ic, 4) if mean_ic is not None else None,
        "std_ic": round(std_ic, 4) if std_ic is not None else None,
        "icir": round(icir, 3) if icir is not None else None,
        "t_stat": round(float(t_stat), 2) if t_stat is not None else None,
        "verdict": _verdict(t_stat),
        "source": source,
    }


def _load_pit(table, columns, fwd_col):
    """Load PIT table with cap_tier joined from stocks if not present."""
    cols_sql = ", ".join(f"p.[{c}]" for c in columns + [fwd_col, "snapshot_date", "sid"])
    # If table has cap_tier, use it; else join stocks
    df = read_sql(
        f"SELECT p.*, COALESCE(p.cap_tier, s.cap_tier) AS _tier "
        f"FROM {table} p LEFT JOIN stocks s ON p.sid = s.sid"
    )
    # Use _tier for grouping if cap_tier was null
    if "cap_tier" in df.columns:
        df["cap_tier"] = df["cap_tier"].fillna(df.get("_tier"))
    elif "_tier" in df.columns:
        df["cap_tier"] = df["_tier"]
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal", help="single signal to compute (default: all)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Loading PIT data...")
    v1_df = read_sql("SELECT * FROM daily_snapshots_pit_v1")
    v2_df = read_sql("SELECT * FROM daily_snapshots_pit")
    print(f"  v1: {len(v1_df)} rows, {v1_df['snapshot_date'].nunique()} dates")
    print(f"  v2: {len(v2_df)} rows, {v2_df['snapshot_date'].nunique()} dates")

    targets = list(SIGNAL_COLUMN_MAP.items())
    if args.signal:
        targets = [(s, c) for s, c in targets if s == args.signal]
        if not targets:
            print(f"No signal '{args.signal}' in registry")
            return

    out_rows = []
    for signal, (v1_col, v2_col) in targets:
        if signal == "_response":
            continue

        # Pick source
        for src_name, src_df, signal_col, fwd_col in [
            ("v1_archive", v1_df, v1_col, "fwd_return_20d"),
            ("v2_recompute", v2_df, v2_col, "fwd_return_20d"),
        ]:
            if signal_col is None or signal_col not in src_df.columns or fwd_col not in src_df.columns:
                continue
            # Skip if all values null
            if src_df[signal_col].notna().sum() == 0:
                continue

            for tier in ["LARGE", "MID", "SMALL"]:
                tier_df = src_df[src_df["cap_tier"] == tier]
                if tier_df.empty:
                    continue
                ic_rows = _compute_ic(tier_df, signal_col, fwd_col)
                result = _aggregate(ic_rows, signal, tier, src_name)
                if result:
                    out_rows.append(result)

    if not out_rows:
        print("No IC computed.")
        return

    df = pd.DataFrame(out_rows)
    print(f"\nComputed {len(df)} (signal, tier, source) rows")

    # Show top performers
    keep = df[df["verdict"] == "KEEP"].sort_values("t_stat", key=lambda x: x.abs(), ascending=False)
    if not keep.empty:
        print("\n=== KEEP signals (|t| ≥ 2.5) ===")
        print(keep[["signal", "cap_tier", "source", "n_periods", "mean_ic", "t_stat", "verdict"]].to_string(index=False))
    weak = df[df["verdict"] == "WEAK"].sort_values("t_stat", key=lambda x: x.abs(), ascending=False)
    if not weak.empty:
        print("\n=== WEAK signals (1.5 ≤ |t| < 2.5) ===")
        print(weak[["signal", "cap_tier", "source", "n_periods", "mean_ic", "t_stat", "verdict"]].head(15).to_string(index=False))

    if args.dry_run:
        print(f"\n[dry-run] not writing")
        return

    df_to_write = df.astype(object).where(df.notna(), None)
    n = upsert_df(df_to_write, "pit_ic_by_tier_v2")
    print(f"\n→ wrote {n} rows to pit_ic_by_tier_v2")


if __name__ == "__main__":
    main()
