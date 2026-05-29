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
    # Behavior tier — PIT helpers shipped 2026-05-24
    "insider_signal":      (None, "insider_score"),
    "sentiment_7d":        (None, "sentiment_7d"),
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
    # Track 3 cluster (plan 0003)
    "revenue_cv_5y":       (None, "revenue_cv_5y"),
    "relative_turnover":   (None, "relative_turnover"),
    "relative_growth":     (None, "relative_growth"),
    "share_momentum":      (None, "share_momentum"),
    # Track 3 standalone factors
    "ccc":                 (None, "ccc"),
    "margin_slope":        (None, "margin_slope"),
    "wc_intensity":        (None, "wc_intensity"),
    "interest_coverage":   (None, "interest_coverage"),
    "roic":                (None, "roic"),
    "fcf_yield":           (None, "fcf_yield"),
    "roiic":               (None, "roiic"),
    # Forensic / capital-allocation batch (plan 0002 §3.2.1)
    "dso_change_yoy":        (None, "dso_change_yoy"),
    "dio_change_yoy":        (None, "dio_change_yoy"),
    "nwc_to_revenue":        (None, "nwc_to_revenue"),
    "sloan_accruals_full":   (None, "sloan_accruals_full"),
    "sga_to_revenue_change": (None, "sga_to_revenue_change"),
    "fcf_margin":            (None, "fcf_margin"),
    "capex_to_dep":          (None, "capex_to_dep"),
    "goodwill_to_assets":    (None, "goodwill_to_assets"),
    "debt_structure":        (None, "debt_structure"),
    "asset_tangibility":     (None, "asset_tangibility"),
    # Track 2.2b — Financial sub-model (Banks + NBFCs only)
    "financial_signal":      (None, "financial_signal"),
    # Phase 2.2b-v2 (2026-05-29 #2) — direction-split:
    "financial_quality":     (None, "financial_quality"),
    "financial_recovery":    (None, "financial_recovery"),
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


def _newey_west_se(ics, lag):
    """Newey-West standard error for serially-correlated IC series.

    Standard SE = std(ics) / sqrt(n). Newey-West corrects for autocorrelation
    when consecutive IC observations overlap (e.g. signal lookback > eval gap,
    or fwd_return window > eval gap). Bartlett kernel with `lag` truncation.
    """
    n = len(ics)
    if n < 2 or lag <= 0:
        return float(np.std(ics, ddof=1) / np.sqrt(n)) if n > 1 else None
    mean = float(np.mean(ics))
    centered = ics - mean
    # γ_0 = variance
    var = float(np.dot(centered, centered) / n)
    # Add 2 * Σ_l (1 - l/(L+1)) * γ_l
    for l in range(1, min(lag, n - 1) + 1):
        weight = 1.0 - l / (lag + 1.0)
        cov = float(np.dot(centered[l:], centered[:-l]) / n)
        var += 2.0 * weight * cov
    if var <= 0:
        # Negative-variance edge: fall back to classical std
        return float(np.std(ics, ddof=1) / np.sqrt(n))
    return float(np.sqrt(var) / np.sqrt(n))


def _bootstrap_t_ci(ics, n_bootstrap=1000, nw_lag=0, seed=42):
    """95% bootstrap CI on the t-stat (resample IC series with replacement).

    Plan 0005 Phase D.5: point-estimate t-stats hide their own uncertainty.
    A t=3.0 with [CI 1.2, 4.8] is much weaker evidence than t=3.0 with
    [CI 2.8, 3.2]. Bootstrap is non-parametric — works whether IC is normal
    or fat-tailed.
    """
    n = len(ics)
    if n < 4:  # below 4, bootstrap is meaningless
        return None, None
    rng = np.random.default_rng(seed)
    ts = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        sample = rng.choice(ics, size=n, replace=True)
        mu = sample.mean()
        sd = sample.std(ddof=1)
        if sd <= 0:
            ts[i] = 0.0
            continue
        if nw_lag > 0:
            se = _newey_west_se(sample, nw_lag) or (sd / np.sqrt(n))
        else:
            se = sd / np.sqrt(n)
        ts[i] = mu / se if se > 0 else 0.0
    lo = float(np.percentile(ts, 2.5))
    hi = float(np.percentile(ts, 97.5))
    return round(lo, 2), round(hi, 2)


def _aggregate(ic_rows, signal, cap_tier, source, cadence="monthly", nw_lag=0):
    """Aggregate per-period IC list into a single (signal, tier) result.

    For overlapping-window signals (e.g. insider 90d at weekly cadence),
    pass nw_lag > 0 to apply Newey-West variance correction.
    """
    if not ic_rows:
        return None
    ics = np.array([r[1] for r in ic_rows])
    n_stocks = int(np.mean([r[2] for r in ic_rows]))
    n_periods = len(ic_rows)
    mean_ic = float(ics.mean())
    std_ic = float(ics.std(ddof=1)) if n_periods > 1 else None
    if nw_lag > 0 and n_periods > 1:
        se = _newey_west_se(ics, nw_lag)
        t_stat = mean_ic / se if se and se > 0 else None
        icir = mean_ic / std_ic if std_ic and std_ic > 0 else None  # report classical ICIR
    else:
        icir = mean_ic / std_ic if std_ic and std_ic > 0 else None
        # t-stat = ICIR * sqrt(n_periods); equivalent to mean/SE_classical
        t_stat = icir * np.sqrt(n_periods) if icir is not None else None

    # Bootstrap 95% CI on the t-stat (plan 0005 Phase D.5)
    t_ci_lo, t_ci_hi = _bootstrap_t_ci(ics, nw_lag=nw_lag)

    return {
        "signal": signal,
        "cap_tier": cap_tier,
        "n_periods": n_periods,
        "n_stocks_avg": n_stocks,
        "mean_ic": round(mean_ic, 4) if mean_ic is not None else None,
        "std_ic": round(std_ic, 4) if std_ic is not None else None,
        "icir": round(icir, 3) if icir is not None else None,
        "t_stat": round(float(t_stat), 2) if t_stat is not None else None,
        "t_stat_ci_lo": t_ci_lo,
        "t_stat_ci_hi": t_ci_hi,
        "verdict": _verdict(t_stat),
        "source": source + (f":{cadence}+NW{nw_lag}" if nw_lag > 0 else (f":{cadence}" if cadence != "monthly" else "")),
    }


# Per-signal Newey-West lag for weekly cadence.
# Lag = max(signal_window_in_weeks, fwd_horizon_in_weeks - 1).
# fwd_return_20d ≈ 4 weeks → adds lag 3 from return overlap.
# Signal window adds more if > 1 week.
_NW_LAG_WEEKLY = {
    "insider_signal":       13,   # 90d insider window / 7d ≈ 13
    "avg_delivery_pct_30d":  4,   # 30d / 7d ≈ 4
    "delivery_anomaly_z":   13,   # 90d / 7d ≈ 13
    "bulk_deal_signal":      4,   # 30d aggregation window
    "short_selling_signal":  4,   # 30d aggregation window
    "sentiment_7d":          3,   # 7d window, only fwd-return overlap matters
    "news_volume":           3,   # same
    "fii_dii_cash_net":      3,
    "fii_dii_fno_positioning": 3,
}


def _nw_lag_for(signal_id, cadence):
    """Pick Newey-West lag for (signal, cadence). 0 = classical SE."""
    if cadence == "weekly":
        return _NW_LAG_WEEKLY.get(signal_id, 3)  # default lag 3 for fwd_return_20d overlap
    return 0  # monthly cadence with fwd_return_20d has ~no overlap


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

    # Cadence dispatch — each signal uses the cadence registered in db.py.
    # For weekly signals we filter v2_df to weekly Friday dates and apply
    # Newey-West variance correction for overlapping signal/return windows.
    from db import get_backtest_cadence
    v2_dates_all = pd.to_datetime(v2_df["snapshot_date"]).dt.date.unique() if not v2_df.empty else []
    weekly_dates = {d.isoformat() for d in v2_dates_all if pd.Timestamp(d).weekday() == 4}

    out_rows = []
    for signal, (v1_col, v2_col) in targets:
        if signal == "_response":
            continue
        cadence = get_backtest_cadence(signal)

        # Pick source — for weekly cadence skip v1 archive (monthly only)
        sources = [("v2_recompute", v2_df, v2_col, "fwd_return_20d")]
        if cadence == "monthly":
            sources.insert(0, ("v1_archive", v1_df, v1_col, "fwd_return_20d"))

        for src_name, src_df, signal_col, fwd_col in sources:
            if signal_col is None or signal_col not in src_df.columns or fwd_col not in src_df.columns:
                continue
            if src_df[signal_col].notna().sum() == 0:
                continue
            # Filter to cadence-appropriate dates
            if cadence == "weekly" and src_name == "v2_recompute":
                df_use = src_df[src_df["snapshot_date"].isin(weekly_dates)]
            elif cadence == "monthly":
                # Monthly: keep only first-of-month-style dates (anything not Friday OR is the first day of month)
                df_use = src_df[~src_df["snapshot_date"].isin(weekly_dates)] if src_name == "v2_recompute" and weekly_dates else src_df
            else:
                df_use = src_df
            if df_use.empty:
                continue

            nw_lag = _nw_lag_for(signal, cadence)
            for tier in ["LARGE", "MID", "SMALL"]:
                tier_df = df_use[df_use["cap_tier"] == tier]
                if tier_df.empty:
                    continue
                ic_rows = _compute_ic(tier_df, signal_col, fwd_col)
                result = _aggregate(ic_rows, signal, tier, src_name, cadence=cadence, nw_lag=nw_lag)
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
