"""
Alpha Signal v2 — Factor Correlation Diagnostic

Computes pairwise Spearman correlation between every PIT-shipped factor in
`daily_snapshots_pit`, per cap_tier. Surfaces colinear pairs so the screener
weight optimizer isn't double-counting overlapping signals.

WHY: ADR 0028 ships SIGNAL_WEIGHTS_RETURN ∝ |t| and SIGNAL_WEIGHTS_SHARPE ∝
ICIR, but neither penalizes redundancy. Two factors with the same t-stat sign
and overlapping inputs (e.g. cf_accruals + bs_accruals + accruals_signal)
contribute three weight blocks for one idea. Run this before promoting new
factors to live picks.

Output:
  - data/factor_correlation_{cap_tier}.json — full matrix
  - stdout report — top cross-group |ρ| pairs + composite-component pairs

Usage:
    python -m tools.factor_correlation                 # all 3 tiers
    python -m tools.factor_correlation --tier LARGE    # one tier
    python -m tools.factor_correlation --threshold 0.5 # lower flag bar
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, BACKTEST_SIGNALS

OUT_DIR = PROJECT_ROOT / "data"
TIERS = ("LARGE", "MID", "SMALL")

# Composites are flagged differently — high |ρ| with a component is
# expected by construction, not a model bug. Keep this list in sync with
# screener's composite columns. Anything not listed here is treated as a
# standalone factor.
COMPOSITE_COMPONENTS = {
    "accruals_signal":   ["cf_accruals", "bs_accruals", "sloan_accruals_full"],
    "promoter_signal":   ["promoter_qoq", "promoter_trend_4q", "pledge_quality"],
    "forensic_penalty":  ["m_score", "z_score", "earnings_persistence"],
    "smart_money_score": ["avg_delivery_pct_30d", "delivery_anomaly_z", "bulk_deal_signal", "short_selling_signal", "insider_score"],
    "value_composite":   ["earnings_yield", "book_to_price", "position_52w"],
    "quality_composite": ["piotroski_f", "roe", "roa"],
    "growth_composite":  ["revenue_growth_yoy", "eps_growth_yoy"],
    "mom_composite":     ["mom_6m", "mom_12m", "macd_bullish"],
    "consensus_signal_combined": ["pt_revision_yoy", "eps_revision_yoy", "pt_upside"],
}


def _signal_to_group():
    """Map pit_column_v2 → group label from BACKTEST_SIGNALS registry."""
    out = {}
    for s in BACKTEST_SIGNALS:
        col = s.get("pit_column_v2")
        grp = s.get("group", "Other")
        if col:
            out[col] = grp
    return out


def _is_expected_composite_pair(a, b):
    """True if (a, b) is a composite ↔ its own component."""
    for comp, parts in COMPOSITE_COMPONENTS.items():
        if (a == comp and b in parts) or (b == comp and a in parts):
            return True
    return False


def _load_panel(tier):
    """Return (df, factor_cols) — wide panel of factor z-scores for the tier.

    Some BACKTEST_SIGNALS entries point to columns in OTHER tables (e.g.
    macro_sector_signals_pit.*) — those are joined at backtest time, not
    stored in daily_snapshots_pit. Filter to columns that actually exist.
    """
    actual_cols = set(
        read_sql("SELECT name FROM pragma_table_info('daily_snapshots_pit')")
        ["name"].tolist()
    )
    factor_cols = [
        s["pit_column_v2"] for s in BACKTEST_SIGNALS
        if s.get("pit_column_v2") and s["pit_column_v2"] in actual_cols
    ]
    factor_cols = sorted(set(factor_cols))
    cols_sql = ", ".join(f'"{c}"' for c in factor_cols)
    df = read_sql(
        f"SELECT sid, snapshot_date, {cols_sql} "
        f"FROM daily_snapshots_pit WHERE cap_tier = ?",
        params=[tier],
    )
    return df, factor_cols


def compute_correlation(tier, min_pairs=200):
    """Spearman matrix per tier. Drops pairs with <min_pairs joint observations.

    Spearman (rank-based) is robust to outliers; some factors have heavy
    tails (e.g. pt_upside pre-clip), Pearson would be misleading.
    """
    df, factor_cols = _load_panel(tier)
    if df.empty:
        return None, factor_cols, {}

    n_per_col = df[factor_cols].notna().sum().to_dict()

    # Pandas' rank-then-corr is the documented fast Spearman path.
    ranked = df[factor_cols].rank(method="average")
    corr = ranked.corr(method="pearson", min_periods=min_pairs)
    return corr, factor_cols, n_per_col


def _top_pairs(corr, threshold, signal_to_group, exclude_composites=False):
    """Return [{a, b, rho, group_a, group_b, cross_group, expected_composite}, ...].

    Sorted by |rho| desc.
    """
    cols = corr.columns.tolist()
    pairs = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = cols[i], cols[j]
            rho = corr.iloc[i, j]
            if pd.isna(rho) or abs(rho) < threshold:
                continue
            is_composite = _is_expected_composite_pair(a, b)
            if exclude_composites and is_composite:
                continue
            ga = signal_to_group.get(a, "Other")
            gb = signal_to_group.get(b, "Other")
            pairs.append({
                "a": a, "b": b,
                "rho": float(rho),
                "group_a": ga, "group_b": gb,
                "cross_group": ga != gb,
                "expected_composite": is_composite,
            })
    pairs.sort(key=lambda x: abs(x["rho"]), reverse=True)
    return pairs


def _clusters(pairs, threshold=0.6):
    """Union-find clusters from |ρ|≥threshold pairs (excluding composite legs)."""
    parent = {}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(x, y):
        parent.setdefault(x, x)
        parent.setdefault(y, y)
        parent[find(x)] = find(y)

    for p in pairs:
        if p["expected_composite"]:
            continue
        if abs(p["rho"]) < threshold:
            continue
        union(p["a"], p["b"])

    groups = {}
    for node in list(parent.keys()):
        root = find(node)
        groups.setdefault(root, []).append(node)
    # Only return clusters with ≥2 members
    return [sorted(members) for members in groups.values() if len(members) >= 2]


def print_report(tier, corr, n_per_col, signal_to_group, threshold):
    pairs = _top_pairs(corr, threshold=threshold, signal_to_group=signal_to_group)
    cross = [p for p in pairs if p["cross_group"] and not p["expected_composite"]]
    same = [p for p in pairs if not p["cross_group"] and not p["expected_composite"]]
    composites = [p for p in pairs if p["expected_composite"]]

    print(f"\n━━━ {tier} ─ |ρ| ≥ {threshold} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  factors with PIT data: {sum(1 for v in n_per_col.values() if v > 0)} / {len(n_per_col)}")
    print()

    if composites:
        print(f"  EXPECTED (composite ↔ component, {len(composites)} pairs) — sanity check, not a finding:")
        for p in composites[:6]:
            print(f"    {p['rho']:+.2f}  {p['a']:30s} ↔ {p['b']}")
        if len(composites) > 6:
            print(f"    … (+{len(composites)-6} more)")
        print()

    if same:
        print(f"  WITHIN-GROUP redundancy ({len(same)} pairs) — same family, often by construction:")
        for p in same[:12]:
            mark = "  "
            print(f"    {mark}{p['rho']:+.2f}  [{p['group_a']:10s}] {p['a']:30s} ↔ {p['b']}")
        if len(same) > 12:
            print(f"    … (+{len(same)-12} more)")
        print()

    if cross:
        print(f"  ★ CROSS-GROUP redundancy ({len(cross)} pairs) — the interesting finding:")
        for p in cross[:20]:
            print(f"    {p['rho']:+.2f}  [{p['group_a']:10s}↔{p['group_b']:10s}]  {p['a']:30s} ↔ {p['b']}")
        if len(cross) > 20:
            print(f"    … (+{len(cross)-20} more)")
        print()
    else:
        print(f"  ★ CROSS-GROUP redundancy: none at |ρ| ≥ {threshold}.\n")

    clusters = _clusters(pairs, threshold=threshold)
    if clusters:
        print(f"  CLUSTERS at |ρ| ≥ {threshold} (excluding composites):")
        for i, c in enumerate(clusters, 1):
            print(f"    cluster {i} ({len(c)} factors): {', '.join(c)}")
        print()


def save_json(tier, corr, n_per_col, threshold):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "tier": tier,
        "threshold": threshold,
        "factors": sorted(corr.columns.tolist()),
        "n_observations": {k: int(v) for k, v in n_per_col.items()},
        "matrix": {
            a: {b: (None if pd.isna(corr.loc[a, b]) else float(corr.loc[a, b]))
                for b in corr.columns}
            for a in corr.columns
        },
        "computed_at": pd.Timestamp.now().isoformat(timespec="seconds"),
    }
    path = OUT_DIR / f"factor_correlation_{tier}.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"  → {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", choices=list(TIERS) + ["all"], default="all")
    parser.add_argument("--threshold", type=float, default=0.6,
                        help="|ρ| threshold for reporting (default 0.6)")
    parser.add_argument("--no-save", action="store_true",
                        help="skip JSON output")
    args = parser.parse_args()

    signal_to_group = _signal_to_group()
    tiers = TIERS if args.tier == "all" else [args.tier]

    for tier in tiers:
        corr, factor_cols, n_per_col = compute_correlation(tier)
        if corr is None:
            print(f"⚠ {tier}: no PIT rows, skipping")
            continue
        print_report(tier, corr, n_per_col, signal_to_group, args.threshold)
        if not args.no_save:
            save_json(tier, corr, n_per_col, args.threshold)


if __name__ == "__main__":
    main()
