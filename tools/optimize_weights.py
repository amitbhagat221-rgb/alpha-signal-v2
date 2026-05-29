"""
Optimize factor weights for two objectives from the PIT IC backtest.

Reads `pit_ic_by_tier_v2` (signal × cap_tier IC + t-stat + ICIR), filters to
KEEP-verdict factors (|t| >= 2.5), then emits two weight schemes per cap_tier:

  MaxReturn  — w_i ∝ |t_i| × sign(IC_i)
               favors absolute IC magnitude → maximizes long-short spread
  MaxSharpe  — w_i ∝ ICIR_i × sign(IC_i)
               favors information ratio (mean/vol of IC) → maximizes Sharpe

User chose "aggressive" — no caps, no diversification floor. pt_upside dominates
because it earns it (t=7-9). If pt_upside breaks (yfinance API change), the
model degrades hard — see docs/decisions/0028-... [TODO]

Maps backtest signal_id → production SIGNAL_WEIGHTS key. Signals not yet wired
into scoring/screener.py are flagged in the report; the script still emits
weight dicts for the wired set.

Usage:
    python -m tools.optimize_weights              # report + dry-print dicts
    python -m tools.optimize_weights --write      # write to config.py
"""

import argparse
from db import read_sql


# Signal-id (in pit_ic_by_tier_v2) → SIGNAL_WEIGHTS key (used by screener).
# Multiple backtest signals can map to the same production key when the
# screener picks one of them per tier (e.g. mom_6m for LARGE, mom_12m for SMALL).
SIGNAL_ID_TO_KEY = {
    "consensus_signal_combined": "consensus",
    "earnings_yield":            "earnings_yield",
    "cf_accruals_ratio":         "accruals",
    "piotroski_f_score":         "piotroski",
    "mom_6m_adj":                "momentum",       # LARGE/MID variant
    "mom_12m_adj":               "momentum",       # SMALL variant (overrides)
    "book_to_price":             "book_to_price",
    "promoter_qoq":              "promoter",
    "pledge_quality":            "pledge_quality", # NEW — needs wiring
    "avg_delivery_pct_30d":      "smart_money",
    "delivery_anomaly_z":        "delivery_anomaly_z", # NEW — needs wiring
    "pt_upside":                 "pt_upside",      # NEW — needs wiring (t=7-9)
    "interest_coverage":         "interest_coverage", # NEW
    "ccc":                       "ccc",            # NEW
    "fcf_margin":                "fcf_margin",     # NEW
    "roic":                      "roic",           # NEW
    "goodwill_to_assets":        "goodwill_to_assets", # NEW
    "nwc_to_revenue":            "nwc_to_revenue", # NEW
    "eps_revision_yoy":          "eps_revision",   # NEW
    "eps_growth_yoy":            "eps_growth",     # NEW
}

# Production keys already wired into scoring/screener.py:_load_signals().
# Keys outside this set are flagged "needs wiring" in the report and still
# included in the weight dicts (so we know what they'd be worth) but the
# screener will silently drop them until wired.
WIRED_KEYS = {
    "consensus", "earnings_yield", "accruals", "piotroski",
    "momentum", "book_to_price", "promoter", "smart_money",
    # Wired 2026-05-28 (from consensus_signals, both columns already present):
    "pt_upside", "eps_growth",
    # Wired 2026-05-29 (Next-3 #3):
    "pledge_quality", "delivery_anomaly_z",
}


def _load_canonical_ics():
    """Read pit_ic_by_tier_v2, dedupe (signal, cap_tier) by max n_periods.

    Multiple backtest runs across v1/v2 PIT sources leave duplicate rows.
    The row with the most observations is the most reliable estimate.
    """
    df = read_sql("""
        SELECT signal, cap_tier, n_periods, mean_ic, icir, t_stat, verdict
        FROM pit_ic_by_tier_v2
        WHERE cap_tier IN ('LARGE','MID','SMALL')
          AND t_stat IS NOT NULL
    """)
    # Keep row with most periods per (signal, cap_tier)
    df = df.sort_values("n_periods", ascending=False).drop_duplicates(
        subset=["signal", "cap_tier"], keep="first"
    )
    return df


def _filter_wired(weights_by_tier: dict) -> dict:
    """Drop unwired keys and renormalize within each tier so |w| sums to 1.0.

    The full dicts (unfiltered) show what's *theoretically* worth; this is what's
    *actually scoreable today*. Use this for config.py SIGNAL_WEIGHTS_* writes.
    """
    out = {}
    for tier, items in weights_by_tier.items():
        wired = {k: w for k, w in items.items() if k in WIRED_KEYS}
        abs_total = sum(abs(w) for w in wired.values())
        if abs_total <= 0:
            out[tier] = {}
            continue
        out[tier] = {k: round(w / abs_total, 4) for k, w in wired.items()}
    return out


def _build_weights(df, objective: str) -> dict:
    """Per cap_tier, build {prod_key: weight} dict normalized to sum=1.0.

    objective:
      'return' → weight ∝ |t_stat|         (favors magnitude)
      'sharpe' → weight ∝ |icir|           (favors info ratio)

    Sign(mean_ic) is preserved: inverse factors get negative weight (the
    screener inverts the percentile when weight < 0). Only KEEP-verdict
    rows (|t| >= 2.5) are eligible.
    """
    keep = df[df["verdict"] == "KEEP"].copy()

    if objective == "return":
        keep["raw"] = keep["t_stat"].abs()
    elif objective == "sharpe":
        keep["raw"] = keep["icir"].abs()
    else:
        raise ValueError(f"unknown objective: {objective}")

    # Sign carries forward — inverse-IC factors get a negative weight.
    keep["signed"] = keep["raw"] * keep["mean_ic"].apply(lambda x: 1.0 if x >= 0 else -1.0)

    out = {}
    for tier in ["LARGE", "MID", "SMALL"]:
        sub = keep[keep["cap_tier"] == tier].copy()
        if sub.empty:
            out[tier] = {}
            continue

        # Resolve mom_6m vs mom_12m per tier — keep whichever has higher |t|.
        # (mapping above collapses both to "momentum", so dedupe.)
        sub["key"] = sub["signal"].map(SIGNAL_ID_TO_KEY)
        sub = sub.dropna(subset=["key"])
        sub = sub.sort_values("raw", ascending=False).drop_duplicates(subset=["key"], keep="first")

        # Normalize the absolute (un-signed) weights to sum to 1.0;
        # then re-apply sign to the result.
        abs_total = sub["raw"].sum()
        if abs_total <= 0:
            out[tier] = {}
            continue
        weights = {}
        for _, row in sub.iterrows():
            sign = 1.0 if row["mean_ic"] >= 0 else -1.0
            weights[row["key"]] = round(sign * row["raw"] / abs_total, 4)
        out[tier] = weights
    return out


def _print_block(name: str, weights_by_tier: dict, df: 'pd.DataFrame'):
    print(f"\n{'='*78}")
    print(f"{name}")
    print(f"{'='*78}")
    print(f"{name} = {{")
    for tier in ["LARGE", "MID", "SMALL"]:
        items = weights_by_tier.get(tier, {})
        print(f"    {tier!r}: {{")
        # Sort by abs weight desc for readability
        for key, w in sorted(items.items(), key=lambda kv: -abs(kv[1])):
            wired_flag = "" if key in WIRED_KEYS else "  # ⚠ needs wiring in screener"
            # Look up the underlying signal+t for inline annotation
            sigs = df[(df["cap_tier"] == tier) & (df["signal"].map(SIGNAL_ID_TO_KEY) == key)]
            if not sigs.empty:
                sig_id = sigs["signal"].iloc[0]
                t = sigs["t_stat"].iloc[0]
                icir = sigs["icir"].iloc[0]
                comment = f"  # {sig_id} t={t:.2f} icir={icir:.2f}{wired_flag.lstrip('  #')}"
            else:
                comment = wired_flag
            print(f"        {key!r:30}: {w:+.4f},{comment}")
        print(f"    }},")
    print(f"}}")


def _coverage_report(weights_by_tier: dict):
    """Show how much weight each tier puts on already-wired vs needs-wiring."""
    print(f"\n{'='*78}")
    print("COVERAGE: how much weight requires new factor wiring?")
    print(f"{'='*78}")
    print(f"{'Tier':<8} {'Wired weight':>15} {'Unwired weight':>17} {'Unwired share':>15}")
    print("-" * 78)
    for tier in ["LARGE", "MID", "SMALL"]:
        items = weights_by_tier.get(tier, {})
        wired = sum(abs(w) for k, w in items.items() if k in WIRED_KEYS)
        unwired = sum(abs(w) for k, w in items.items() if k not in WIRED_KEYS)
        total = wired + unwired
        share = unwired / total if total else 0
        print(f"{tier:<8} {wired:>15.4f} {unwired:>17.4f} {share*100:>14.1f}%")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--objective", choices=["return", "sharpe", "both"], default="both")
    p.add_argument("--filter-wired", action="store_true",
                   help="Drop unwired keys + renormalise per tier — paste-ready for config.py.")
    args = p.parse_args()

    df = _load_canonical_ics()
    print(f"Loaded {len(df)} canonical (signal × cap_tier) IC rows.")

    if args.objective in ("return", "both"):
        w_ret = _build_weights(df, "return")
        if args.filter_wired:
            w_ret = _filter_wired(w_ret)
        _print_block("SIGNAL_WEIGHTS_RETURN", w_ret, df)
        if args.objective == "return":
            _coverage_report(w_ret)

    if args.objective in ("sharpe", "both"):
        w_sh = _build_weights(df, "sharpe")
        if args.filter_wired:
            w_sh = _filter_wired(w_sh)
        _print_block("SIGNAL_WEIGHTS_SHARPE", w_sh, df)
        _coverage_report(w_sh)


if __name__ == "__main__":
    main()
