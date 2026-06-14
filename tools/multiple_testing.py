"""
Multiple-testing correction for the factor zoo (Harvey-Liu-Zhu 2016, "...and the
Cross-Section of Expected Returns").

We have backtested ~270 (signal, tier) hypotheses. Picking the winners by a naive
|t|≥2.5 bar ignores that, under the null, testing M hypotheses at α=0.05 yields ~0.05·M
false "discoveries" by chance alone. HLZ's prescription: control the family-wide error
(Bonferroni / Holm) or the false-discovery rate (Benjamini-Hochberg / Benjamini-Yekutieli)
across the *whole* cross-section of t-stats, which raises the effective significance bar.

This is a READ-ONLY diagnostic — it changes no weights. It tells us which "KEEP" factors
are robust to the data-mining burden vs which are likely false discoveries, to inform the
deliberate weight reviews (signal-weights.md) and the FACTOR_LIBRARY two-tier split (ADR 0017).

Method notes:
- One test per (signal, tier); duplicate sources (cadence/NW variants, v1 archive) are the
  SAME hypothesis → deduped to the canonical lens (v2_recompute monthly > weekly > v1).
- p-values are two-sided from |t| with df = n_periods − 1 (Student-t), so thin-n tests
  (n=5-8) get appropriately wide p-values — a t=5.3 on 8 periods is far weaker than on 40.
- BY (Benjamini-Yekutieli) is the headline: it controls FDR under ARBITRARY dependence,
  which factor tests have (correlated factors). HLZ recommend it for exactly this setting.

Usage:
    python -m tools.multiple_testing                 # full report
    python -m tools.multiple_testing --alpha 0.05    # FDR/FWER level (default 0.05)
    python -m tools.multiple_testing --min-n 6       # drop tests thinner than n periods
"""

import argparse

import numpy as np
import pandas as pd
from scipy import stats

from config import SIGNAL_WEIGHTS
from db import read_sql

# config SIGNAL_WEIGHTS key → backtest signal id (canonical, from promotion_gate._LIVE_ALIAS)
_ALIAS = {
    "consensus": "consensus_signal_combined", "accruals": "cf_accruals_ratio",
    "piotroski": "piotroski_f_score", "momentum": "mom_12m_adj",
    "promoter": "promoter_qoq", "smart_money": "smart_money_score",
}
def _wired_pairs() -> set:
    return {(_ALIAS.get(k, k), tier) for tier, w in SIGNAL_WEIGHTS.items() for k in w}


def load_tests(min_n: int = 4) -> pd.DataFrame:
    """One row per (signal, tier) — the deduped hypothesis set with two-sided p-values."""
    df = read_sql(
        "SELECT signal, cap_tier, n_periods, mean_ic, t_stat, verdict, source "
        "FROM pit_ic_by_tier_v2 WHERE t_stat IS NOT NULL AND n_periods >= ?",
        params=[min_n])
    # Dedup sources to one test per (signal,tier): the cadence/NW variants + v1 archive
    # are the SAME hypothesis. Represent each by its MOST-POWERED test — prefer non-v1,
    # then max n_periods (so e.g. delivery_anomaly_z is its n=103 weekly test, not a
    # thin monthly recompute; iv_skew its 48-week panel).
    df["is_v1"] = (df["source"] == "v1_archive").astype(int)
    df = (df.sort_values(["is_v1", "n_periods"], ascending=[True, False])
            .drop_duplicates(["signal", "cap_tier"], keep="first")
            .drop(columns="is_v1").reset_index(drop=True))
    df["p"] = 2.0 * stats.t.sf(df["t_stat"].abs(), df["n_periods"] - 1)
    df["abs_t"] = df["t_stat"].abs()
    return df


def _bh_adjusted(p: np.ndarray, c: float) -> np.ndarray:
    """Step-up adjusted p-values. c=1 → Benjamini-Hochberg; c=Σ1/i → Benjamini-Yekutieli."""
    m = len(p)
    order = np.argsort(p)
    ranked = p[order]
    factor = m * c / np.arange(1, m + 1)
    adj_sorted = np.minimum.accumulate((ranked * factor)[::-1])[::-1]
    adj_sorted = np.clip(adj_sorted, 0, 1)
    out = np.empty(m)
    out[order] = adj_sorted
    return out


def _holm_adjusted(p: np.ndarray) -> np.ndarray:
    m = len(p)
    order = np.argsort(p)
    ranked = p[order]
    adj_sorted = np.maximum.accumulate(ranked * (m - np.arange(m)))
    adj_sorted = np.clip(adj_sorted, 0, 1)
    out = np.empty(m)
    out[order] = adj_sorted
    return out


def run(alpha: float = 0.05, min_n: int = 4) -> pd.DataFrame:
    df = load_tests(min_n=min_n)
    m = len(df)
    c_m = float(np.sum(1.0 / np.arange(1, m + 1)))  # BY dependence factor

    df["p_bonf"] = np.clip(df["p"] * m, 0, 1)
    df["p_holm"] = _holm_adjusted(df["p"].values)
    df["p_bh"] = _bh_adjusted(df["p"].values, c=1.0)
    df["p_by"] = _bh_adjusted(df["p"].values, c=c_m)

    wired = _wired_pairs()
    df["wired"] = [(s, t) in wired for s, t in zip(df["signal"], df["cap_tier"])]

    naive = (df["p"] < alpha).sum()
    keep = (df["abs_t"] >= 2.5).sum()
    print(f"\n{'='*78}\nMULTIPLE-TESTING CORRECTION — factor zoo (Harvey-Liu-Zhu 2016)\n{'='*78}")
    print(f"M = {m} deduped (signal,tier) hypotheses · α = {alpha} · min n_periods = {min_n}")
    print(f"Expected FALSE positives at naive α: {alpha*m:.1f}   (≈ the data-mining tax)")
    print(f"Naive 'significant' (p<{alpha}): {naive}   |   naive KEEP (|t|≥2.5): {keep}")
    print()
    # representative |t| bars (Student-t at the median df across tests)
    med_df = int(df["n_periods"].median() - 1)
    t_bonf = stats.t.ppf(1 - (alpha / m) / 2, med_df)
    print(f"Survivors after correction (FWER/FDR ≤ {alpha}):")
    for name, col, kind in [("Bonferroni (FWER)", "p_bonf", "fwer"),
                            ("Holm       (FWER)", "p_holm", "fwer"),
                            ("Benjamini-Hochberg (FDR)", "p_bh", "fdr"),
                            ("Benjamini-Yekutieli (FDR, dep.)", "p_by", "fdr")]:
        n_sig = (df[col] <= alpha).sum()
        n_wired_sig = ((df[col] <= alpha) & df["wired"]).sum()
        print(f"  {name:34} {n_sig:3d} survive  ({n_wired_sig} of them wired)")
    print(f"\nImplied |t| bar — Bonferroni at median df={med_df}: |t| ≥ {t_bonf:.2f}   "
          f"(vs naive 2.5; HLZ's factor-zoo bar ≈ 3.0)")
    print(f"BY dependence factor c(M) = Σ1/i = {c_m:.2f}")

    # ── wired factors: are the weights we deploy multiple-testing-robust? ──
    w = df[df["wired"]].sort_values("p_by")
    print(f"\n{'─'*78}\nWIRED factors (config.SIGNAL_WEIGHTS) — robustness to multiple testing")
    print(f"{'─'*78}\n{'signal':28} {'tier':5} {'n':>3} {'t':>6} {'p':>8} {'p_BH':>7} {'p_BY':>7}  BY?")
    for _, r in w.iterrows():
        flag = "✓ real" if r["p_by"] <= alpha else ("~ FDR-only" if r["p_bh"] <= alpha else "✗ fails")
        print(f"{r['signal'][:27]:28} {r['cap_tier']:5} {int(r['n_periods']):3d} "
              f"{r['t_stat']:+6.2f} {r['p']:8.4f} {r['p_bh']:7.4f} {r['p_by']:7.4f}  {flag}")

    # ── KEEP (|t|≥2.5) but NOT robust → likely false discoveries / thin-n ──
    susp = df[(df["abs_t"] >= 2.5) & (df["p_by"] > alpha)].sort_values("p_by")
    print(f"\n{'─'*78}\nKEEP by naive |t|≥2.5 but FAILS BY-FDR — likely false discovery or thin-n")
    print(f"{'─'*78}\n{'signal':28} {'tier':5} {'n':>3} {'t':>6} {'p_BY':>7}  wired?")
    for _, r in susp.iterrows():
        print(f"{r['signal'][:27]:28} {r['cap_tier']:5} {int(r['n_periods']):3d} "
              f"{r['t_stat']:+6.2f} {r['p_by']:7.4f}  {'WIRED' if r['wired'] else ''}")
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--alpha", type=float, default=0.05, help="FWER/FDR level (default 0.05)")
    ap.add_argument("--min-n", type=int, default=4, help="drop tests with fewer periods (default 4)")
    args = ap.parse_args()
    run(alpha=args.alpha, min_n=args.min_n)


if __name__ == "__main__":
    main()
