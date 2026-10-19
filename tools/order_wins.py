"""
Plan 0025 task 7.4 — order-win intensity as a factor: does the count of a company's recent BSE order-win filings
predict its return within its tier, beyond momentum?  (READ-ONLY on the DB; writes data/lh/v2/order_wins_*)

Why: 7.1's ablation (docs/studies/asymmetric-sleeves-2026-10.md) found order wins are the theme book's engine —
without them the SMALL book fell from +25.5 % to +10.1 %/yr. Amit 2026-10-14: test the factor first; if it holds,
paper-track the theme book (plan 0025 D5).
CAVEAT: the hypothesis came out of the 7.1 ablation on 2020-25, so this test re-uses most of the same history. It
can kill the idea (no IC, or only momentum in disguise); it cannot prove it. Only a forward record can.

PRE-REGISTRATION (2026-10-14, before any result of this tool):
Panel  every monthly anchor of data/lh/labels.parquet, PIT tiers SMALL and MID (LARGE not tested: ~100 names and no
       factor has shown out-of-sample skill there, memory large_cap_factors_none_2026_10). Outcomes fwd_21 / 63 / 126 /
       252 (adjusted, sessions after the anchor's next close). Today's listed universe (survivorship as plan 0024).
Features at anchor a (BSE 'Award of Order / Receipt of Order' filings, dated by dt_tm, strictly before a):
  order_wins_6m   filings in [a − 182 days, a)            ← PRIMARY
  order_wins_3m   filings in [a − 91 days, a)
  order_wins_12m  filings in [a − 365 days, a)
  order_wins_chg  order_wins_6m − filings in [a − 364, a − 182)   (are wins speeding up)
  No filing = 0 (a real count). Ranks within (anchor, tier) absorb the ~5× rise in filings after 2023.
Tests per (feature, tier, horizon): monthly within-tier Spearman IC; Newey-West t (lag = horizon in months, as
  tools.lh_horizon); non-overlap t (tools.lh_growth.nonoverlap_t); mean IC per period 2019-12…2022-12 /
  2023-01…2024-12 / 2025-01…; filer excess = mean fwd of stocks with >= 1 filing in the window − the tier median.
  Incremental (PRIMARY only): IC of the residual of the feature's percentile regressed on the percentiles of
  6-month momentum and 52-week position (per anchor, OLS), Newey-West t.
  Industry-neutral (PRIMARY only, diagnostic): percentile minus its (anchor, tier, industry) mean.
Bar ("holds"), PRIMARY in SMALL or MID at 126 sessions, all of:
  1. IC > 0 with Newey-West t >= 2.5 and non-overlap t >= 2.0
  2. IC > 0 in each of the three periods
  3. incremental (residual) Newey-West t >= 2.0
Multiple testing: the family is the 4 features × 2 tiers × 4 horizons; Bonferroni |t| reported, and the ADR 0043
  programme-wide bar (|t| ≈ 4.2) stated beside it.
Decision  holds in a tier → order_wins_6m becomes a LIBRARY factor candidate (factors.FACTORS, signals/ module, PIT
  twin, on a worktree branch) for a promotion review — no weight from this tool — and D5 paper-tracks the 7.1 theme
  book;  fails 3 only → the theme book's edge is momentum in disguise, D5 = nothing;  fails 1 or 2 → no factor, D5 =
  nothing.

Usage: python -m tools.order_wins
"""

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from signals import announcements  # noqa: E402  (BSE history + NSE live, ADR 0082)
from tools.backtest_pit import _compute_ic, _newey_west_se  # noqa: E402
from tools.lh_growth import nonoverlap_t  # noqa: E402
from tools.theme_momentum import ORDER_SUB, TIERS, build  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
HORIZONS = (21, 63, 126, 252)
NW_LAG = {21: 1, 63: 3, 126: 6, 252: 12}
PERIODS = {"2019-22": ("2019-12-01", "2022-12-31"), "2023-24": ("2023-01-01", "2024-12-31"),
           "2025-26": ("2025-01-01", "2026-12-31")}
FEATURES = ("order_wins_6m", "order_wins_3m", "order_wins_12m", "order_wins_chg")
PRIMARY = "order_wins_6m"


def panel():
    d = build()[["sid", "snapshot_date", "cap_tier", "industry", "mom_6m", "pos_52w", "artifact"]]
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date"] + [f"fwd_{h}" for h in HORIZONS])
    d = d.merge(lab, on=["sid", "snapshot_date"], how="left")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    od = pd.read_sql(f"SELECT sid, substr(dt_tm, 1, 10) AS d FROM ({announcements.sql()}) a "
                     "WHERE subcategory = ? AND sid IS NOT NULL AND dt_tm IS NOT NULL", con, params=[ORDER_SUB])
    con.close()
    parts = []
    for a in sorted(d["snapshot_date"].unique()):
        t = pd.Timestamp(a)

        def n(lo, hi):
            lo_s, hi_s = (t - pd.Timedelta(days=lo)).date().isoformat(), (t - pd.Timedelta(days=hi)).date().isoformat()
            return od[(od["d"] >= lo_s) & (od["d"] < hi_s)].groupby("sid").size()
        parts.append(pd.DataFrame({"w3": n(91, 0), "w6": n(182, 0), "w12": n(365, 0), "prev6": n(364, 182)})
                     .rename_axis("sid").reset_index().assign(snapshot_date=a))
    c = pd.concat(parts, ignore_index=True)
    d = d.merge(c, on=["sid", "snapshot_date"], how="left")
    for col in ("w3", "w6", "w12", "prev6"):
        d[col] = d[col].fillna(0)
    d["order_wins_6m"], d["order_wins_3m"], d["order_wins_12m"] = d["w6"], d["w3"], d["w12"]
    d["order_wins_chg"] = d["w6"] - d["prev6"]
    for h in HORIZONS:                       # AURUM/MAJC special-dividend label artifact (HANDOFF)
        d.loc[d["artifact"], f"fwd_{h}"] = np.nan
    g = d.groupby(["snapshot_date", "cap_tier"])
    d["p_primary"] = g[PRIMARY].rank(pct=True)
    d["p_mom"] = g["mom_6m"].rank(pct=True)
    d["p_pos"] = g["pos_52w"].rank(pct=True)
    d["primary_ind_neutral"] = d["p_primary"] - d.groupby(["snapshot_date", "cap_tier", "industry"])["p_primary"].transform("mean")
    res = []
    for _, gg in d.groupby(["snapshot_date", "cap_tier"]):
        s = gg[["p_primary", "p_mom", "p_pos"]].dropna()
        if len(s) < 30:
            continue
        X = np.column_stack([np.ones(len(s)), s["p_mom"], s["p_pos"]])
        beta, *_ = np.linalg.lstsq(X, s["p_primary"].to_numpy(), rcond=None)
        res.append(pd.Series(s["p_primary"].to_numpy() - X @ beta, index=s.index))
    d["primary_resid_mom"] = pd.concat(res)
    return d


def nw_t(rows, h):
    x = np.array([r[1] for r in rows], float)
    se = _newey_west_se(x, NW_LAG[h])
    return float(x.mean() / se) if se and se > 0 else None


def filer_excess(tdf, col, fwd):
    out = []
    for _, g in tdf[[col, fwd, "snapshot_date"]].dropna().groupby("snapshot_date"):
        f = g[g[col] >= 1]
        if len(f) >= 5:
            out.append(f[fwd].mean() - g[fwd].median())
    return float(np.mean(out)) if out else None


def tests(d):
    recs = []
    cols = list(FEATURES) + ["primary_resid_mom", "primary_ind_neutral"]
    for col in cols:
        for tier in TIERS:
            tdf = d[d["cap_tier"] == tier]
            for h in HORIZONS:
                rows = _compute_ic(tdf, col, f"fwd_{h}")
                if len(rows) < 12:
                    continue
                r = dict(feature=col, tier=tier, h=h, n=len(rows), ic=float(np.mean([x[1] for x in rows])),
                         t_nw=nw_t(rows, h), t_nonoverlap=nonoverlap_t(rows, h),
                         stocks=float(np.mean([x[2] for x in rows])))
                for p, (lo, hi) in PERIODS.items():
                    sub = [x[1] for x in rows if lo <= x[0] <= hi]
                    r[f"ic_{p}"] = float(np.mean(sub)) if len(sub) >= 3 else None
                if col in FEATURES:
                    r["filer_excess"] = filer_excess(tdf, col if col != "order_wins_chg" else "order_wins_6m", f"fwd_{h}")
                recs.append(r)
    t = pd.DataFrame(recs)
    fam = t["feature"].isin(FEATURES)
    m = int(fam.sum())
    t["p"] = 2 * stats.t.sf(t["t_nw"].abs(), (t["n"] - 1).clip(lower=1))
    t["bonferroni_pass"] = fam & (t["p"] * m < 0.05)
    return t, m


def verdict(t):
    out = {}
    for tier in TIERS:
        p = t[(t["feature"] == PRIMARY) & (t["tier"] == tier) & (t["h"] == 126)].iloc[0]
        r = t[(t["feature"] == "primary_resid_mom") & (t["tier"] == tier) & (t["h"] == 126)].iloc[0]
        bars = {"1_ic_t": bool(p["ic"] > 0 and p["t_nw"] >= 2.5 and (p["t_nonoverlap"] or 0) >= 2.0),
                "2_all_periods": bool(all((p[f"ic_{k}"] or 0) > 0 for k in PERIODS)),
                "3_beyond_momentum": bool((r["t_nw"] or 0) >= 2.0)}
        out[tier] = dict(bars=bars, holds=all(bars.values()), ic=round(p["ic"], 4), t_nw=round(p["t_nw"], 2),
                         t_nonoverlap=round(p["t_nonoverlap"], 2), resid_t=round(r["t_nw"], 2),
                         periods={k: round(p[f"ic_{k}"], 4) for k in PERIODS})
    held = [k for k in TIERS if out[k]["holds"]]
    if held:
        dec = f"holds in {', '.join(held)}: library factor candidate (worktree) + promotion review; D5 paper-tracks the theme book"
    elif any(out[k]["bars"]["1_ic_t"] and out[k]["bars"]["2_all_periods"] for k in TIERS):
        dec = "momentum in disguise: no factor; D5 = nothing"
    else:
        dec = "no factor; D5 = nothing"
    out["decision"] = dec
    return out


def main():
    pd.set_option("display.width", 240)
    d = panel()
    d.to_parquet(V2 / "order_wins_panel.parquet", index=False)
    cov = d.groupby("cap_tier").apply(lambda g: (g["order_wins_6m"] > 0).mean()).round(3).to_dict()
    print(f"panel {len(d):,} stock-months; share with >= 1 order-win filing in 6 months: {cov}")
    t, m = tests(d)
    t.to_csv(V2 / "order_wins_tests.csv", index=False)
    print(f"family {m} tests; Bonferroni |t| ≈ {stats.t.isf(0.025 / m, 60):.2f}; ADR 0043 programme bar ≈ 4.2")
    print(t.drop(columns=["p"]).round(4).to_string(index=False))
    v = verdict(t)
    (V2 / "order_wins_summary.json").write_text(json.dumps(v, indent=1, default=str))
    print(json.dumps(v, indent=1, default=str))


if __name__ == "__main__":
    main()
