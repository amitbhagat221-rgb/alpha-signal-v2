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

SURVIVORSHIP CAVEAT (audit Data-F1): every anchor's cross-section here is
built from CURRENT sids only — delisted/merged/renamed symbols that were
part of the true historical NSE universe are silently absent. Worst measured
snapshot (2018-04-02): 40.1% of that date's true universe never maps to a
current sid; 1,381 distinct symbols never map at all (1,017 of those still
active as of 2023+). See `python -m tools.survivorship_exposure` for the
full per-snapshot breakdown. Not fixed here — rebuilding the panel against
`historical_universe` has unfixable fundamentals gaps for dead names
(no quarterly_income/balance_sheet history was ever fetched for them).
"""

import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import factors
from config import PICKABLE_TIERS
from db import get_backtest_cadence, get_db, read_sql, upsert_df


# Mapping: signal_id (registry) → (v1_column, v2_column) for every IC-rankable
# factor (v1 column None for v2-only signals), plus "_response" → fwd_return_20d.
# Derived from factors.py — sector/portfolio-level and CONTROL factors (industry_id:
# the IC of a categorical code is meaningless) are not in it.
SIGNAL_COLUMN_MAP = factors.SIGNAL_COLUMN_MAP


IC_MIN_PERIODS = 12  # fewer anchors than this carry no verdict and no CI (a t of 19 on 2 anchors is not evidence)


def _verdict(t, n_periods=IC_MIN_PERIODS):
    """C13b verdict from t-stat absolute value; INSUFFICIENT below IC_MIN_PERIODS anchors."""
    if t is None or pd.isna(t) or n_periods < IC_MIN_PERIODS:
        return "INSUFFICIENT"
    t_abs = abs(t)
    if t_abs >= 2.5:
        return "KEEP"
    if t_abs >= 1.5:
        return "WEAK"
    return "DROP"


def evidence():
    """THE evidence row per (signal, cap_tier) — every reader of pit_ic_by_tier_v2
    takes its row from here (the cockpit, MCP, multiple_testing, optimize_weights,
    expected_return and factor_audit each used to pick their own and disagreed):
    the v2 panel before the frozen v1 archive, then the row with the most anchors."""
    df = read_sql("SELECT * FROM pit_ic_by_tier_v2")
    df["_v1"] = ~df["source"].fillna("").str.startswith("v2_recompute")
    return (df.sort_values(["_v1", "n_periods"], ascending=[True, False])
              .drop_duplicates(["signal", "cap_tier"], keep="first")
              .drop(columns="_v1").reset_index(drop=True))


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
    """95% bootstrap CI on the t-stat: resample the mean IC, scale by the series' own
    standard error (Newey-West when nw_lag > 0), so the interval is centred on the
    reported t. Overlapping series (nw_lag > 0) are resampled in moving blocks of
    nw_lag + 1 anchors — iid resampling would destroy the autocorrelation the
    standard error corrects for. No CI below IC_MIN_PERIODS anchors.
    """
    ics = np.asarray(ics, dtype=float)
    n = len(ics)
    if n < IC_MIN_PERIODS:
        return None, None
    se = _newey_west_se(ics, nw_lag)
    if not se or se <= 0:
        return None, None
    rng = np.random.default_rng(seed)
    block = min(nw_lag + 1, n)
    n_blocks = -(-n // block)
    starts = rng.integers(0, n - block + 1, size=(n_bootstrap, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)).reshape(n_bootstrap, -1)[:, :n]
    ts = ics[idx].mean(axis=1) / se
    return round(float(np.percentile(ts, 2.5)), 2), round(float(np.percentile(ts, 97.5)), 2)


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
        "verdict": _verdict(t_stat, n_periods),
        "source": source + (f":{cadence}+NW{nw_lag}" if nw_lag > 0 else (f":{cadence}" if cadence != "monthly" else "")),
    }


# Per-signal Newey-West lag for weekly cadence.
# Lag = max(signal_window_in_weeks, fwd_horizon_in_weeks - 1).
# fwd_return_20d ≈ 4 weeks → adds lag 3 from return overlap.
# Signal window adds more if > 1 week.
_NW_LAG_WEEKLY = {
    "insider_signal":       13,   # 90d insider window / 7d ≈ 13
    "avg_delivery_pct_30d":  4,   # 30d / 7d ≈ 4
    "smart_money_score":    13,   # 90d composite window / 7d ≈ 13
    "delivery_anomaly_z":   13,   # 90d / 7d ≈ 13
    "sector_momentum":       9,   # 63d medium window / 7d ≈ 9
    "bulk_deal_signal":      4,   # 30d aggregation window
    "short_selling_signal":  4,   # 30d aggregation window
    "sentiment_7d":          3,   # 7d window, only fwd-return overlap matters
    "news_volume":           3,   # same
    "fii_dii_cash_net":      3,
    "fii_dii_fno_positioning": 3,
    # Options/F&O OI factors — same-day reads (buildup is a ~1d Δ within one
    # expiry), so only the fwd_return_20d ≈ 4-week overlap drives the lag.
    "pcr_oi":                3,
    "pcr_volume":            3,
    "max_pain_distance":     3,
    "oi_buildup_signal":     3,
    # IV factors — same-day reads (percentile/realised use trailing windows but the
    # cross-sectional signal is the same-day value); fwd_return_20d overlap → lag 3.
    "iv_skew_25d":           3,
    "iv_term_structure":     3,
    "iv_realised_spread":    3,
    "iv_percentile_1y":      3,
}


def _nw_lag_for(signal_id, cadence):
    """Pick Newey-West lag for (signal, cadence). 0 = classical SE."""
    if cadence == "weekly":
        return _NW_LAG_WEEKLY.get(signal_id, 3)  # default lag 3 for fwd_return_20d overlap
    return 0  # monthly cadence with fwd_return_20d has ~no overlap


TIERS = list(PICKABLE_TIERS)


def _is_month_start_anchor(d):
    """True if `d` is the first business day of its month — generate_eval_dates' monthly anchor."""
    first = pd.Timestamp(d.year, d.month, 1)
    while first.weekday() >= 5:
        first += pd.Timedelta(days=1)
    return pd.Timestamp(d) == first


def iter_panels(v1_df, v2_df, targets):
    """Yield (signal, cadence, source, signal_col, tier, tier_df) for every
    (signal, PIT source, cap tier) a backtest scores — one anchor policy for
    backtest_pit, promotion_gate and ic_decay.

    Cadence dispatch (db.get_backtest_cadence): weekly signals use only the v2
    panel's Friday anchors; monthly signals use the v1 archive then v2, with v2's
    weekly-ONLY Fridays dropped. A monthly anchor is the first business day of its
    month (generate_eval_dates), which is a Friday whenever the 1st itself is — those
    month-start Fridays are legitimate monthly observations and are KEPT. (The old
    "drop all Fridays" filter silently discarded ~1 in 7 monthly anchors, e.g. 6 of 36
    financial anchors, biasing every monthly factor's n low.)

    `targets` = iterable of (signal, (v1_col, v2_col)). Sources whose column is absent
    or all-NULL, and empty tiers, are skipped.
    """
    v2_dates_all = pd.to_datetime(v2_df["snapshot_date"]).dt.date.unique() if not v2_df.empty else []
    # All Friday anchors — used to KEEP weekly-cadence factors on their weekly grid.
    weekly_dates = {d.isoformat() for d in v2_dates_all if pd.Timestamp(d).weekday() == 4}
    # Weekly-ONLY Fridays — for EXCLUDING from monthly backtests.
    weekly_only_dates = {d.isoformat() for d in v2_dates_all
                         if pd.Timestamp(d).weekday() == 4 and not _is_month_start_anchor(d)}
    for signal, (v1_col, v2_col) in targets:
        if signal == "_response":
            continue
        cadence = get_backtest_cadence(signal)
        # Pick source — for weekly cadence skip v1 archive (monthly only)
        sources = [("v2_recompute", v2_df, v2_col)]
        if cadence == "monthly":
            sources.insert(0, ("v1_archive", v1_df, v1_col))
        for src_name, src_df, signal_col in sources:
            if signal_col is None or signal_col not in src_df.columns:
                continue
            if src_df[signal_col].notna().sum() == 0:
                continue
            if cadence == "weekly" and src_name == "v2_recompute":
                df_use = src_df[src_df["snapshot_date"].isin(weekly_dates)]
            elif cadence == "monthly" and src_name == "v2_recompute" and weekly_only_dates:
                df_use = src_df[~src_df["snapshot_date"].isin(weekly_only_dates)]
            else:
                df_use = src_df
            if df_use.empty:
                continue
            for tier in TIERS:
                tier_df = df_use[df_use["cap_tier"] == tier]
                if not tier_df.empty:
                    yield signal, cadence, src_name, signal_col, tier, tier_df


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
    for signal, cadence, src_name, signal_col, tier, tier_df in iter_panels(v1_df, v2_df, targets):
        ic_rows = _compute_ic(tier_df, signal_col, "fwd_return_20d")
        result = _aggregate(ic_rows, signal, tier, src_name, cadence=cadence,
                            nw_lag=_nw_lag_for(signal, cadence))
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

    # computed_at is written explicitly (the column default only fires on INSERT, so an
    # upserted row kept its first date forever), and rows this run no longer produces
    # for the signals it scored are deleted (the source string is part of the key and
    # changes with cadence / NW lag, which left orphan rows behind).
    df["computed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    df_to_write = df.astype(object).where(df.notna(), None)
    n = upsert_df(df_to_write, "pit_ic_by_tier_v2")
    produced = set(zip(df["signal"], df["cap_tier"], df["source"]))
    with get_db() as conn:
        stored = conn.execute(
            f"SELECT signal, cap_tier, source FROM pit_ic_by_tier_v2 WHERE signal IN ({','.join('?' * len(targets))})",
            [sig for sig, _ in targets]).fetchall()
        orphans = [tuple(r) for r in stored if tuple(r) not in produced]
        conn.executemany("DELETE FROM pit_ic_by_tier_v2 WHERE signal = ? AND cap_tier = ? AND source = ?", orphans)
    print(f"\n→ wrote {n} rows to pit_ic_by_tier_v2, removed {len(orphans)} rows no run produces any more")


if __name__ == "__main__":
    main()
