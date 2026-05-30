"""Walk-forward out-of-sample test of the factor-weighting method.

The problem this solves: our t-stats are computed on the SAME 36-month panel we
used to pick the factors and their weights. That's circular — it measures fit,
not skill. Waiting for live data gives only ~2 independent periods by autumn.

The fix (no waiting required): walk-forward on the existing PIT history.
  - The v1 PIT panel has 35 *monthly* snapshots (2023-04 → 2026-02), each with a
    20-day forward return. Monthly spacing ≈ the return horizon, so consecutive
    test periods barely overlap — this also sidesteps the overlapping-window
    artifact that inflated the live-IC read.
  - For each test month k: FIT factor weights using ONLY months < k (the weights,
    including each factor's sign, are derived from the training window's mean IC),
    then SCORE month k with those frozen weights and record the composite's IC on
    that unseen month. Roll forward. With min_train=12 that's ~23 genuinely
    out-of-sample monthly periods per tier.

Three weighting strategies are compared, all fit the same way OOS:
  - ic_weighted : w_i = mean training IC of factor i (signed). The honest OOS
                  version of what tools/optimize_weights.py does in-sample.
  - equal       : w_i = sign(training IC) / n_factors. Does fitting magnitudes help?
  - best_single : the single highest-|IC| training factor, used alone. Does
                  combining beat just using the best factor?

CAVEAT surfaced by the data: pt_upside and eps_growth (the factors that dominate
the in-sample SIGNAL_WEIGHTS_RETURN/SHARPE variants) are NOT in the v1 panel —
analyst price targets are episodic and only snapshotted since 2026. They cannot
be validated over this history; this harness tests the production factor set.

Usage:
    python -m tools.walk_forward
    python -m tools.walk_forward --min-train 12 --window expanding
    python -m tools.walk_forward --rolling 18      # rolling 18-month train window
"""
import argparse

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from db import read_sql

RESPONSE = "fwd_return_20d"
# Factor columns present in daily_snapshots_pit_v1 with usable coverage.
# Signs are NOT hardcoded — each is learned from the training window's IC.
FACTORS = [
    "book_to_price", "bs_accruals", "cf_accruals", "mom_6m", "mom_12m",
    "earnings_yield", "piotroski_f", "pledge_quality", "promoter_qoq",
    "avg_delivery_pct_30d", "eps_cv", "earnings_beat_rate",
]
MIN_STOCKS = 20          # min stocks on a date to compute a stable IC
MIN_TRAIN_OBS = 4        # min training dates a factor must appear on to be used


def _zscore(s):
    """Cross-sectional z-score, clipped to ±3, NaN preserved."""
    mu, sd = s.mean(), s.std(ddof=0)
    if not sd or np.isnan(sd):
        return pd.Series(np.nan, index=s.index)
    return ((s - mu) / sd).clip(-3, 3)


def _factor_ic(panel_by_date, factor):
    """{date: IC} of one factor vs forward return, per date."""
    out = {}
    for d, g in panel_by_date:
        sub = g[[factor, RESPONSE]].dropna()
        if len(sub) < MIN_STOCKS:
            continue
        ic, _ = spearmanr(sub[factor], sub[RESPONSE])
        if not np.isnan(ic):
            out[d] = float(ic)
    return out


def _composite_ic_on_date(g, weights):
    """Weighted-sum composite for one date's stocks, then IC vs forward return."""
    score = pd.Series(0.0, index=g.index)
    used = False
    for f, w in weights.items():
        if w == 0 or f not in g.columns:
            continue
        z = _zscore(g[f]).fillna(0.0)   # missing factor → neutral exposure
        score = score + w * z
        used = True
    if not used:
        return None
    sub = pd.DataFrame({"score": score, "ret": g[RESPONSE]}).dropna()
    if len(sub) < MIN_STOCKS:
        return None
    ic, _ = spearmanr(sub["score"], sub["ret"])
    return None if np.isnan(ic) else float(ic)


def _summary(ics):
    n = len(ics)
    if n < 2:
        return dict(n=n, mean_ic=np.nan, icir=np.nan, t=np.nan, ci=(np.nan, np.nan), pos=np.nan)
    a = np.array(ics)
    mean = a.mean()
    sd = a.std(ddof=1)
    icir = mean / sd if sd else np.nan
    t = mean / (sd / np.sqrt(n)) if sd else np.nan
    # bootstrap 95% CI on mean IC
    rng = np.random.default_rng(42)
    boot = [rng.choice(a, n, replace=True).mean() for _ in range(2000)]
    ci = (float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5)))
    return dict(n=n, mean_ic=mean, icir=icir, t=t, ci=ci, pos=float((a > 0).mean()))


def run(min_train=12, rolling=None):
    df = read_sql("SELECT * FROM daily_snapshots_pit_v1")
    if "cap_tier" not in df.columns:
        st = read_sql("SELECT sid, cap_tier FROM stocks")
        df = df.merge(st, on="sid", how="left")
    dates = sorted(df["snapshot_date"].unique())
    print(f"PIT panel: {len(df):,} rows · {len(dates)} monthly dates "
          f"({dates[0]} → {dates[-1]})")
    win = f"rolling {rolling}m" if rolling else "expanding"
    print(f"Train window: {win} · min_train={min_train} · "
          f"OOS test periods per tier ≈ {len(dates) - min_train}\n")

    strategies = ["ic_weighted", "equal", "best_single"]
    results = {tier: {s: [] for s in strategies} for tier in ["LARGE", "MID", "SMALL"]}

    for tier in ["LARGE", "MID", "SMALL"]:
        tdf = df[df["cap_tier"] == tier]
        by_date = {d: g for d, g in tdf.groupby("snapshot_date")}

        for k in range(min_train, len(dates)):
            test_date = dates[k]
            train_dates = dates[k - rolling:k] if rolling else dates[:k]
            train = tdf[tdf["snapshot_date"].isin(train_dates)]
            test_g = by_date.get(test_date)
            if test_g is None or len(test_g) < MIN_STOCKS:
                continue

            # FIT: mean training IC per factor (this fixes both sign and magnitude)
            tr_by_date = list(train.groupby("snapshot_date"))
            train_ic = {}
            for f in FACTORS:
                ics = _factor_ic(tr_by_date, f)
                if len(ics) >= MIN_TRAIN_OBS:
                    train_ic[f] = float(np.mean(list(ics.values())))
            if not train_ic:
                continue

            # Build the three weight vectors (all from training only)
            ic_w = {f: v for f, v in train_ic.items()}
            tot = sum(abs(v) for v in ic_w.values()) or 1.0
            ic_w = {f: v / tot for f, v in ic_w.items()}

            eq_w = {f: np.sign(v) / len(train_ic) for f, v in train_ic.items()}

            best_f = max(train_ic, key=lambda f: abs(train_ic[f]))
            best_w = {best_f: np.sign(train_ic[best_f])}

            for name, w in [("ic_weighted", ic_w), ("equal", eq_w), ("best_single", best_w)]:
                ic = _composite_ic_on_date(test_g, w)
                if ic is not None:
                    results[tier][name].append(ic)

    # ── Report ──
    print(f"{'tier':6} {'strategy':12} {'n':>3} {'meanIC':>8} {'ICIR':>6} "
          f"{'t':>6} {'95% CI (mean IC)':>20} {'%+':>5}")
    print("-" * 74)
    for tier in ["LARGE", "MID", "SMALL"]:
        for s in strategies:
            r = _summary(results[tier][s])
            ci = f"[{r['ci'][0]:+.3f},{r['ci'][1]:+.3f}]" if not np.isnan(r['ci'][0]) else "—"
            verdict = ""
            if not np.isnan(r['ci'][0]) and r['ci'][0] > 0:
                verdict = "  ← OOS-positive (CI>0)"
            print(f"{tier:6} {s:12} {r['n']:>3} {r['mean_ic']:>+8.4f} {r['icir']:>+6.2f} "
                  f"{r['t']:>+6.2f} {ci:>20} {r['pos']*100:>4.0f}%{verdict}")
        print()

    print("Read: an OOS mean IC whose 95% CI is entirely > 0 is genuine, "
          "non-circular evidence the\nweighting works on unseen months. "
          "Compare ic_weighted vs equal vs best_single to see if\nfitting "
          "weights actually adds anything over equal-weighting or the single best factor.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-train", type=int, default=12)
    ap.add_argument("--rolling", type=int, default=None,
                    help="rolling train window length (months); default expanding")
    a = ap.parse_args()
    run(min_train=a.min_train, rolling=a.rolling)
