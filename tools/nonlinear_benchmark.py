"""Non-linear models on the factor library: do they beat a linear blend out of sample?  (READ-ONLY)

Same protocol as tools/walk_forward.py (monthly anchors of `daily_snapshots_pit`, the
adjusted next-session 20-day label, one-anchor embargo, expanding window), so the rows are
directly comparable with its `live` / `select` / `ic_wtd` methods, which are re-run here.

Inputs, per (tier, anchor): every factor as its within-tier percentile (the screener's
view); the target is the within-tier percentile of the 20-day return. Linear models see a
missing factor as 0.5 (ADR 0064); trees see it as missing (they route it natively).

Pre-registered models (one fixed configuration each, chosen before any result; nothing is
tuned on test months — RidgeCV picks its penalty on the training window only):
  ridge      ridge on every factor, pooled tiers + tier dummies — the "more factors" control
  gam        cubic splines per factor (5 knots) + ridge — shape, no interactions
  gbm_d1     boosted stumps — shape, no interactions (tree version of gam)
  gbm_d3     boosted depth-3 trees — shape + interactions (the Gu-Kelly-Xiu workhorse)
  rf         random forest, depth 8
  ridge_tier, gbm_d3_tier   the same fitted on one tier only

Read: gbm_d3 > gbm_d1 ≈ ridge → interactions carry the gain; gbm_d1 ≈ gam > ridge → a factor's
shape does; ridge > select → more factors help, non-linearity doesn't.

Usage:
    python -m tools.nonlinear_benchmark                       # all models, writes the study
    python -m tools.nonlinear_benchmark --models ridge,gbm_d3 --out scratch.csv
"""
import argparse
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import SplineTransformer

import factors
from config import MISSING_FACTOR_SCORE, PICKABLE_TIERS
from tools import walk_forward as wf

MIN_TRAIN = 12        # anchors of training data before the first test month (backtest_pit.IC_MIN_PERIODS)
ALPHAS = np.logspace(-1, 4, 11)
SEED = 7


def _ridge():
    return RidgeCV(alphas=ALPHAS)


MODELS = {
    "ridge": (lambda: _ridge(), "linear", "pooled"),
    "gam": (lambda: make_pipeline(SplineTransformer(n_knots=5, degree=3), _ridge()), "linear", "pooled"),
    "gbm_d1": (lambda: HistGradientBoostingRegressor(
        max_depth=1, max_leaf_nodes=2, learning_rate=0.05, max_iter=400, min_samples_leaf=200,
        l2_regularization=1.0, early_stopping=False, random_state=SEED), "tree", "pooled"),
    "gbm_d3": (lambda: HistGradientBoostingRegressor(
        max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=200, max_features=0.5,
        l2_regularization=1.0, early_stopping=False, random_state=SEED), "tree", "pooled"),
    "rf": (lambda: RandomForestRegressor(
        n_estimators=150, max_depth=8, min_samples_leaf=200, max_features=0.33, max_samples=0.3,
        n_jobs=2, random_state=SEED), "tree_filled", "pooled"),
    "ridge_tier": (lambda: _ridge(), "linear", "tier"),
    "gbm_d3_tier": (lambda: HistGradientBoostingRegressor(
        max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=100, max_features=0.5,
        l2_regularization=1.0, early_stopping=False, random_state=SEED), "tree", "tier"),
}


def build_xy():
    """Pickable-tier panel as within-(tier, anchor) percentiles; returns (frame, factor cols)."""
    col_of = wf._columns()
    live = {wf._ranked_col(k, t) for t, ws in factors.SIGNAL_WEIGHTS.items() for k in ws}
    panel, cols = wf.load_panel(list(col_of) + sorted(live - set(col_of)))
    assert not any("fwd" in c for c in cols), "a label column leaked into the features"
    panel = panel[panel["cap_tier"].isin(PICKABLE_TIERS)].reset_index(drop=True)
    cols = [c for c in cols if panel[c].notna().any()]
    g = panel.groupby(["cap_tier", "snapshot_date"])
    X = g[cols].rank(pct=True)
    y = g[wf.RESPONSE].rank(pct=True) - 0.5
    for t in PICKABLE_TIERS[:-1]:
        X[f"tier_{t}"] = (panel["cap_tier"] == t).astype(float)
    out = pd.concat([panel[["sid", "snapshot_date", "cap_tier", wf.RESPONSE]], X], axis=1)
    out["y"] = y
    return out, cols, [c for c in X.columns if c.startswith("tier_")]


def _features(df, cols, dummies, kind):
    """Trees keep NaN (routed natively); linear models read a missing factor as 0.5, centred."""
    if kind == "tree":
        return df[cols + dummies].to_numpy()
    return np.hstack([df[cols].fillna(MISSING_FACTOR_SCORE).to_numpy() - 0.5, df[dummies].to_numpy()])


def _record(test, score):
    sub = pd.DataFrame({"s": score, "r": test[wf.RESPONSE].to_numpy(), "sid": test["sid"].to_numpy()}).dropna()
    if len(sub) < wf.MIN_STOCKS:
        return None
    ic = sub["s"].rank().corr(sub["r"].rank())
    top_mask = sub["s"] >= sub["s"].quantile(0.9)
    return ic, sub.loc[top_mask, "r"].mean() - sub["r"].mean(), frozenset(sub.loc[top_mask, "sid"])


def run(models, start=None):
    df, cols, dummies = build_xy()
    live = {t: {wf._ranked_col(k, t): w for k, w in ws.items()} for t, ws in factors.SIGNAL_WEIGHTS.items()}
    anchors = sorted(df["snapshot_date"].unique())
    by_date = dict(tuple(df.groupby("snapshot_date")))
    rec = []
    for k, test_date in enumerate(anchors):
        train_dates = anchors[:max(k - wf.EMBARGO, 0)]   # never a negative slice: k=0 would wrap to the future
        if len(train_dates) < MIN_TRAIN or (start and test_date < start):
            continue
        train = df[df["snapshot_date"].isin(train_dates)]
        test = by_date[test_date]
        t0 = time.time()
        for tier in PICKABLE_TIERS:   # today's weights again, here only for the top tenth's turnover
            te = test[test["cap_tier"] == tier]
            w = {c: v for c, v in live.get(tier, {}).items() if c in te}
            r = _record(te, wf.composite(te, w).to_numpy()) if w else None
            if r:
                rec.append({"tier": tier, "anchor": test_date, "method": "live_turnover",
                            "ic": r[0], "top": r[1], "top_set": r[2]})
        for name in models:
            make, kind, scope = MODELS[name]
            fits = [(PICKABLE_TIERS, [])] if scope == "pooled" else [([t], []) for t in PICKABLE_TIERS]
            for tiers, _ in fits:
                d = dummies if scope == "pooled" else []
                tr = train[train["cap_tier"].isin(tiers)]
                fk = "tree" if kind == "tree" else "linear"
                Xtr = _features(tr, cols, d, fk)
                if kind == "tree_filled":
                    Xtr = np.nan_to_num(Xtr, nan=0.0)
                m = make().fit(Xtr, tr["y"].to_numpy())
                for tier in tiers:
                    te = test[test["cap_tier"] == tier]
                    Xte = _features(te, cols, d, fk)
                    if kind == "tree_filled":
                        Xte = np.nan_to_num(Xte, nan=0.0)
                    r = _record(te, m.predict(Xte))
                    if r:
                        rec.append({"tier": tier, "anchor": test_date, "method": name,
                                    "ic": r[0], "top": r[1], "top_set": r[2]})
        print(f"{test_date} train={len(train_dates):>2} anchors {len(train):>6} rows  {time.time() - t0:5.1f}s", flush=True)
    return pd.DataFrame(rec)


def baselines():
    """walk_forward's live / select / ic_wtd, with the top tenth's members for turnover."""
    rec, _ = wf.run()
    return rec


def _turnover(g):
    sets = [x if isinstance(x, frozenset) else None for x in g.sort_values("anchor")["top_set"]]
    ch = [1 - len(a & b) / max(len(b), 1) for a, b in zip(sets[:-1], sets[1:]) if a and b]
    return np.mean(ch) if ch else np.nan


def summarise(rec, ref=("ridge", "live")):
    rows = []
    for (tier, m), g in rec.groupby(["tier", "method"]):
        ic = g["ic"].to_numpy()
        n = len(ic)
        sd = ic.std(ddof=1)
        row = {"tier": tier, "method": m, "months": n, "mean_ic": round(ic.mean(), 4),
               "t": round(ic.mean() / (sd / np.sqrt(n)), 2) if n > 1 and sd > 0 else np.nan,
               "pct_pos": round((ic > 0).mean() * 100), "top10_vs_tier_pct": round(g["top"].mean() * 100, 2),
               "top10_turnover": round(_turnover(g), 2)}
        for r in ref:
            base = rec[(rec["tier"] == tier) & (rec["method"] == r)].set_index("anchor")["ic"]
            d = (g.set_index("anchor")["ic"] - base).dropna()
            row[f"t_vs_{r}"] = round(d.mean() / (d.std(ddof=1) / np.sqrt(len(d))), 2) \
                if m != r and len(d) > 2 and d.std(ddof=1) > 0 else np.nan
        rows.append(row)
    order = {t: i for i, t in enumerate(PICKABLE_TIERS)}
    return pd.DataFrame(rows).sort_values(["tier", "t"], key=lambda s: s.map(order) if s.name == "tier" else -s)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--start", help="first test anchor (smoke tests)")
    ap.add_argument("--out", default="output/nonlinear_benchmark.pkl", help="per-anchor records")
    a = ap.parse_args()
    rec = run(a.models.split(","), a.start)
    base = baselines()
    base = base[base["anchor"] >= rec["anchor"].min()]
    allrec = pd.concat([rec, base], ignore_index=True)
    allrec.to_pickle(a.out)
    s = summarise(allrec)
    print(s.to_string(index=False))
    print(); print(wf.by_year(allrec).to_string())
