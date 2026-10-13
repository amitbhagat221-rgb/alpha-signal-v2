"""LARGE re-audit 2026-10-10 (docs/studies/large-reaudit-2026-10-10.md). READ-ONLY (db.read_sql only).

Usage: ALPHA_DB=... python -m tools.large_reaudit OUT.csv   |   python -m tools.large_reaudit --followup

A. Every registered PIT column, per tier: monthly first-business-day anchors, 20d rank IC
   (backtest_pit engine), halves split 2023-01-01, recent window since 2024-09-01, max |corr|
   with wired LARGE factors.
B. Pre-registered consensus-surprise factors from Yahoo history (analyst_estimates,
   source yahoo_calendar), report date strictly before the anchor:
     cons_surprise     (actual - estimate)/|estimate| of the latest report <= 90d old, clipped +-1
     cons_beat         sign(actual - estimate) of that report
     cons_beat_rate_4q share of beats over the last 4 reports within 400d (>= 3 reports)
   plus each one's IC after removing announcement_car (residual of within-anchor rank OLS).
"""
import sys
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import factors
from db import read_sql
from tools import backtest_pit as bp

SPLIT = pd.Timestamp("2023-01-01")
RECENT = pd.Timestamp("2024-09-01")
WIRED_L = ["announcement_car", "iv_skew_25d", "asset_growth_yoy", "forward_looking_intensity"]
META = {"sid", "snapshot_date", "cap_tier", "fwd_return_20d", "close_price", "forensic_penalty", "industry_id"}
TIERS = ["LARGE", "MID", "SMALL"]


def ic_series(df, col):
    rows = bp._compute_ic(df, col, "fwd_return_20d")
    return pd.Series({pd.Timestamp(d): ic for d, ic, _ in rows}, dtype=float)


def tstat(s):
    if len(s) < 3 or s.std(ddof=1) == 0:
        return np.nan
    return s.mean() / s.std(ddof=1) * np.sqrt(len(s))


def evaluate(P, cols):
    out = []
    for col in cols:
        for tier in TIERS:
            d = P[P.cap_tier == tier]
            if d[col].notna().sum() == 0:
                continue
            ic = ic_series(d, col)
            if ic.empty:
                continue
            h1, h2, rc = ic[ic.index < SPLIT], ic[ic.index >= SPLIT], ic[ic.index >= RECENT]
            out.append(dict(col=col, tier=tier, n=len(ic), ic=ic.mean(), t=tstat(ic),
                            n_h1=len(h1), ic_h1=h1.mean() if len(h1) else np.nan,
                            ic_h2=h2.mean() if len(h2) else np.nan,
                            n_rc=len(rc), t_rc=tstat(rc)))
    return pd.DataFrame(out)


def max_corr(P, cols, tier="LARGE"):
    d = P[P.cap_tier == tier]
    res = {}
    for col in cols:
        best, who = np.nan, ""
        for w in WIRED_L:
            if w == col:
                continue
            cs = []
            for _, g in d.groupby("snapshot_date"):
                sub = g[[col, w]].dropna()
                if len(sub) >= 20 and sub[col].nunique() > 1 and sub[w].nunique() > 1:
                    cs.append(spearmanr(sub[col], sub[w])[0])
            if cs:
                c = float(np.nanmean(cs))
                if np.isnan(best) or abs(c) > abs(best):
                    best, who = c, w
        res[col] = (best, who)
    return res


def surprise_features(anchors):
    e = read_sql("SELECT sid, metric, target_period, value FROM analyst_estimates "
                 "WHERE source='yahoo_calendar' AND metric IN ('eps_actual','eps_estimate')")
    e = e.pivot_table(index=["sid", "target_period"], columns="metric", values="value").reset_index()
    e = e.dropna(subset=["eps_actual", "eps_estimate"])
    e["d"] = pd.to_datetime(e["target_period"])
    den = e["eps_estimate"].abs().clip(lower=0.01)
    e["surp"] = ((e["eps_actual"] - e["eps_estimate"]) / den).clip(-1, 1)
    e["beat"] = np.sign(e["eps_actual"] - e["eps_estimate"])
    e = e.sort_values(["sid", "d"])
    rows = []
    for a in anchors:
        k = e[(e.d < a) & (e.d >= a - pd.Timedelta(days=400))]
        if k.empty:
            continue
        last = k.groupby("sid").tail(1)
        fresh = last[last.d >= a - pd.Timedelta(days=90)]
        l4 = k.groupby("sid").tail(4)
        br = l4.groupby("sid")["beat"].agg(lambda s: (s > 0).mean() if len(s) >= 3 else np.nan)
        f = pd.DataFrame({"cons_beat_rate_4q": br})
        f["cons_surprise"] = fresh.set_index("sid")["surp"]
        f["cons_beat"] = fresh.set_index("sid")["beat"]
        f["snapshot_date"] = a.strftime("%Y-%m-%d")
        rows.append(f.reset_index())
    return pd.concat(rows, ignore_index=True)


def residual_on(P, col, ctrl, tier):
    d = P[P.cap_tier == tier].copy()
    out = []
    for dt, g in d.groupby("snapshot_date"):
        sub = g[[col, ctrl, "fwd_return_20d"]].dropna()
        if len(sub) < 20 or sub[col].nunique() < 2:
            continue
        x = sub[ctrl].rank(pct=True).values
        y = sub[col].rank(pct=True).values
        b = np.polyfit(x, y, 1)
        r = y - np.polyval(b, x)
        out.append((pd.Timestamp(dt), spearmanr(r, sub["fwd_return_20d"])[0]))
    s = pd.Series(dict(out)).dropna()
    return len(s), tstat(s), tstat(s[s.index >= RECENT])


def main():
    cols = [c for c in factors.PIT_COLUMNS if c not in META]
    P = read_sql("SELECT " + ", ".join(["sid", "snapshot_date", "cap_tier", "fwd_return_20d"] + cols)
                 + " FROM daily_snapshots_pit WHERE cap_tier IN ('LARGE','MID','SMALL')")
    P = P[pd.to_datetime(P.snapshot_date).map(bp._is_month_start_anchor)].copy()
    anchors = sorted(pd.to_datetime(P.snapshot_date.unique()))
    print(f"anchors {len(anchors)}: {anchors[0].date()} .. {anchors[-1].date()}", file=sys.stderr)

    S = surprise_features(anchors)
    P = P.merge(S, on=["sid", "snapshot_date"], how="left")
    new = ["cons_surprise", "cons_beat", "cons_beat_rate_4q"]
    for c in new:
        cov = P[P.cap_tier == "LARGE"].groupby("snapshot_date")[c].apply(lambda s: s.notna().mean())
        print(f"{c} LARGE coverage per anchor: median {cov.median():.2f}, min {cov.min():.2f}", file=sys.stderr)

    E = evaluate(P, cols + new)
    E.to_csv(sys.argv[1], index=False)
    L = E[E.tier == "LARGE"].copy()
    cand = L[(L.t.abs() >= 1.5) & (L.n >= 20)]
    mc = max_corr(P, list(cand.col))
    cand = cand.assign(max_corr=[mc[c][0] for c in cand.col], corr_with=[mc[c][1] for c in cand.col],
                       halves=[("agree" if np.sign(r.ic_h1) == np.sign(r.ic_h2) == np.sign(r.ic) else "split")
                               if r.n_h1 >= 6 else "one-half" for r in cand.itertuples()])
    pd.set_option("display.width", 250)
    print("\n=== LARGE, |t|>=1.5 and n>=20 ===")
    print(cand.sort_values("t", key=abs, ascending=False).round(3).to_string(index=False))
    print("\n=== Consensus surprise, all tiers ===")
    print(E[E.col.isin(new)].round(3).to_string(index=False))
    print("\n=== Surprise after removing announcement_car (n, t, recent t) ===")
    for c in new:
        for tier in TIERS:
            print(c, tier, *[round(v, 2) if isinstance(v, float) else v for v in residual_on(P, c, "announcement_car", tier)])
    mc2 = max_corr(P, new)
    print("\nLARGE corr of new with wired:", {k: (round(v[0], 2), v[1]) for k, v in mc2.items()})
    d = P[P.cap_tier == "LARGE"]
    for c in new:
        for o in ["earnings_beat_rate", "earnings_surprise_std", "eps_growth_yoy"]:
            cs = [spearmanr(g[c], g[o], nan_policy="omit")[0] for _, g in d.groupby("snapshot_date")
                  if g[[c, o]].dropna().shape[0] >= 20]
            print(f"corr {c} ~ {o}: {np.nanmean(cs):.2f} over {len(cs)} anchors")


W_TIER = {"MID": ["iv_skew_25d","residual_momentum_12_1","piotroski_f","consensus_signal_combined","cf_accruals","announcement_car"],
     "SMALL": ["delivery_anomaly_z","announcement_car","piotroski_f","residual_momentum_12_1","sector_tilt","avg_delivery_pct_30d"]}


def followup():
    """MID/SMALL: overlap of the surprise factors with each tier's wired factors, and IC after all of them."""
    W = W_TIER
    cols = sorted(set(sum(W.values(), [])))
    P = read_sql("SELECT sid, snapshot_date, cap_tier, fwd_return_20d, " + ",".join(cols) + " FROM daily_snapshots_pit WHERE cap_tier IN ('MID','SMALL')")
    P = P[pd.to_datetime(P.snapshot_date).map(bp._is_month_start_anchor)]
    P = P.merge(surprise_features(sorted(pd.to_datetime(P.snapshot_date.unique()))), on=["sid","snapshot_date"], how="left")
    for tier, ws in W.items():
        d = P[P.cap_tier == tier]
        for c in ["cons_surprise", "cons_beat_rate_4q"]:
            cov = d.groupby("snapshot_date")[c].apply(lambda s: s.notna().mean())
            cs = {}
            for w in ws:
                v = [spearmanr(g[c], g[w], nan_policy="omit")[0] for _, g in d.groupby("snapshot_date") if g[[c, w]].dropna().shape[0] >= 20]
                cs[w] = round(float(np.nanmean(v)), 2)
            print(tier, c, f"coverage median {cov.median():.2f} recent {cov[cov.index >= '2024-09-01'].median():.2f}", cs)
            # residual on every wired factor in the tier at once
            out = []
            for dt, g in d.groupby("snapshot_date"):
                sub = g[[c, "fwd_return_20d"] + ws].dropna(subset=[c, "fwd_return_20d"])
                if len(sub) < 20: continue
                X = sub[ws].rank(pct=True).fillna(0.5).values; X = np.c_[np.ones(len(X)), X]
                y = sub[c].rank(pct=True).values
                r = y - X @ np.linalg.lstsq(X, y, rcond=None)[0]
                out.append((pd.Timestamp(dt), spearmanr(r, sub["fwd_return_20d"])[0]))
            s = pd.Series(dict(out)).dropna()
            print("   after all wired factors: n", len(s), "t", round(tstat(s), 2), "recent t", round(tstat(s[s.index >= pd.Timestamp('2024-09-01')]), 2))


if __name__ == "__main__":
    followup() if sys.argv[1] == "--followup" else main()
