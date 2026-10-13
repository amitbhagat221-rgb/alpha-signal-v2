"""
Tier-wise slow model v1 — built from the slow evidence found in plan 0024 / 0025 and the winners
post-mortem (READ-ONLY on the DB; writes data/lh/v2/tier_*).

PRE-REGISTRATION (2026-10-13, before any tier_slow_v1 result). Equal weights, nothing fitted.
Each component is a within-tier percentile at the monthly anchor (sign applied; missing = 0.5,
config.MISSING_FACTOR_SCORE); the score is their mean.
  SMALL (6): + mom_6m · + cons_beat_rate_4q · + quality×value (a_roce & book_to_price) ·
             + sector_tilt · − cf_accruals_long · + a_piotroski_lite
  MID   (5): + mom_6m · + a_piotroski_lite · + cons_beat_rate_4q · + q_margin_chg (from 2024-12;
             0.5 before) · − cf_accruals_long
  MID sensitivity (reported, never deciding): + − a_roce_min5 ("avoid steady high-ROCE").
  LARGE: no model (index), not run.
Sources: PIT panel (mom_6m, cons_beat_rate_4q, sector_tilt, book_to_price), tools.lh_growth
features (a_roce, a_piotroski_lite, q_margin_chg, a_roce_min5), tools.lh_forensic statements
(cf_accruals_long, annual Screener, period end + 150 days).
Honesty: every component was chosen after looking at 2019–26 → in-sample *selection*.

Tests:
 1. Horizon: rank IC at 21 / 63 / 126 / 252, non-overlap t, top-decile excess vs tier median,
    IC by period 2020-22 / 2023-24 / 2025-26 (as tools.lh_slow_v2).
 2. Book (tools.lh_book machinery: measured costs, Indian tax, tier index, forensic red-flag sale):
    template = monthly · top 10 · sell below 30 · 3-month average · 12-month hold · tax deferral,
    window A 2022-06 → 2026-10 and window B 2019-12 → 2026-10; the 48 grid in window A for DSR(N_eff)
    and PBO (tools.lh_luck).
 3. Grade, Amit's "good enough" framework (2026-10-13), on the window-A template:
    A = t_nw >= 2.0 AND DSR >= 0.95 AND PBO <= 0.20 (the strict bar);
    B = t_nw >= 1.5 AND (DSR >= 0.90 OR PBO <= 0.30) AND excess > 0 in >= 3 of 5 calendar years
        AND worst 12-month excess >= −15 %;
    C = otherwise (research only).
    Planning return = half the back-tested excess.

Usage: python -m tools.lh_tier_slow
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.backtest_pit import _aggregate, _compute_ic  # noqa: E402
from tools.lh_forensic import statements  # noqa: E402
from tools.lh_growth import asof  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
HORIZONS = (21, 63, 126, 252)
NW_LAG = {21: 1, 63: 3, 126: 6, 252: 12}
PERIODS = {"2020-22": ("0000", "2022-12-31"), "2023-24": ("2023-01-01", "2024-12-31"),
           "2025-26": ("2025-01-01", "9999")}
TEMPLATE = dict(reb="M", N=10, k=3, score="avg3", min_hold=12, defer=True)
MODEL = {
    "SMALL": [("mom_6m", 1), ("cons_beat_rate_4q", 1), ("qv", 1), ("sector_tilt", 1),
              ("cf_accruals_long", -1), ("a_piotroski_lite", 1)],
    "MID": [("mom_6m", 1), ("a_piotroski_lite", 1), ("cons_beat_rate_4q", 1), ("q_margin_chg", 1),
            ("cf_accruals_long", -1)],
}
MID_SENS = MODEL["MID"] + [("a_roce_min5", -1)]


def build():
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier"])
    lab = lab[lab["cap_tier"].isin(["MID", "SMALL"])]
    anchors = sorted(lab["snapshot_date"].unique())
    gf = pd.read_parquet(LH / "growth_features.parquet",
                         columns=["sid", "snapshot_date", "a_roce", "a_piotroski_lite", "q_margin_chg", "a_roce_min5"])
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ph = ",".join("?" * len(anchors))
    pan = pd.read_sql(f"SELECT sid, snapshot_date, mom_6m, cons_beat_rate_4q, sector_tilt, book_to_price "
                      f"FROM daily_snapshots_pit WHERE snapshot_date IN ({ph})", con, params=anchors)
    acc = asof(statements(con), "period_end", 150, anchors, ["cf_accruals_long"])
    con.close()
    df = (lab.merge(pan, on=["sid", "snapshot_date"], how="left")
             .merge(gf, on=["sid", "snapshot_date"], how="left")
             .merge(acc, on=["sid", "snapshot_date"], how="left"))
    grp = df.groupby(["snapshot_date", "cap_tier"])
    pct = {c: grp[c].rank(pct=True) for c in ("mom_6m", "cons_beat_rate_4q", "sector_tilt", "book_to_price",
                                               "a_roce", "a_piotroski_lite", "q_margin_chg", "a_roce_min5",
                                               "cf_accruals_long")}
    pct["qv"] = pd.concat([pct["a_roce"], pct["book_to_price"]], axis=1).mean(axis=1)

    def score(spec, m):
        parts = [(pct[c][m] if s > 0 else 1 - pct[c][m]).fillna(0.5) for c, s in spec]
        return pd.concat(parts, axis=1).mean(axis=1)

    out = []
    for tier, spec in MODEL.items():
        m = df["cap_tier"] == tier
        out.append(df.loc[m, ["sid", "snapshot_date", "cap_tier"]].assign(method="tier_slow_v1", score=score(spec, m)))
        cover = pd.concat([pct[c][m].notna() for c, _ in spec], axis=1).mean(axis=1)
        print(f"{tier}: mean share of components present {cover.mean():.2f}")
    m = df["cap_tier"] == "MID"
    out.append(df.loc[m, ["sid", "snapshot_date", "cap_tier"]].assign(method="tier_slow_v1_roce", score=score(MID_SENS, m)))
    sc = pd.concat(out, ignore_index=True)
    sc["pct_rank"] = sc.groupby(["method", "snapshot_date", "cap_tier"])["score"].rank(pct=True)
    sc["oos"] = True
    sc.to_parquet(V2 / "tier_scores.parquet", index=False)
    return sc


def nonoverlap_t(rows, h):
    step = max(h // 21, 1)
    s = pd.Series([r[1] for r in rows], index=[r[0] for r in rows]).sort_index()
    ts = [x.mean() / (x.std() / np.sqrt(len(x))) for x in (s.iloc[o::step] for o in range(step))
          if len(x) >= 3 and x.std() > 0]
    return float(np.mean(ts)) if ts else np.nan


def horizon(sc):
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier"]
                          + [f"fwd_{h}" for h in HORIZONS])
    recs = []
    for meth, g in sc.groupby("method"):
        df = lab.merge(g[["sid", "snapshot_date", "score"]], on=["sid", "snapshot_date"])
        for tier, tdf in df.groupby("cap_tier"):
            for h in HORIZONS:
                rows = _compute_ic(tdf, "score", f"fwd_{h}")
                r = _aggregate(rows, meth, tier, "lh", cadence="monthly", nw_lag=NW_LAG[h])
                ex = [g2.loc[g2["score"] >= g2["score"].quantile(.9), f"fwd_{h}"].mean() - g2[f"fwd_{h}"].median()
                      for _, g2 in tdf[["snapshot_date", "score", f"fwd_{h}"]].dropna().groupby("snapshot_date") if len(g2) >= 30]
                rec = dict(method=meth, tier=tier, h=h, n=r["n_periods"], ic=round(r["mean_ic"], 4),
                           t_nw=round(r["t_stat"], 2), t_nonoverlap=round(nonoverlap_t(rows, h), 2),
                           top10_excess=round(float(np.mean(ex)), 4))
                for p, (lo, hi) in PERIODS.items():
                    sub = [x[1] for x in rows if lo <= x[0] <= hi]
                    rec[f"ic_{p}"] = round(float(np.mean(sub)), 4) if len(sub) >= 3 else None
                recs.append(rec)
    t = pd.DataFrame(recs)
    t.to_csv(V2 / "tier_horizon.csv", index=False)
    return t


def books(sc):
    import tools.lh_book as B
    from tools.lh_luck import n_effective, pbo, sharpe
    res = {}
    for w, lo in (("A", "2022-06-01"), ("B", "0000")):
        d = V2 / f"win_tier_{w}"
        d.mkdir(parents=True, exist_ok=True)
        sc[sc["snapshot_date"] >= lo].to_parquet(d / "oos_scores.parquet", index=False)
        if not (d / "labels.parquet").exists():
            os.symlink(LH / "labels.parquet", d / "labels.parquet")
        B.LH = d
        D = B.Data()
        for tier in ("MID", "SMALL"):
            bench = B.benchmark(D, tier)
            meths = ("tier_slow_v1", "tier_slow_v1_roce") if tier == "MID" else ("tier_slow_v1",)
            for meth in meths:
                r, m = B.simulate(D, tier, dict(TEMPLATE, method=meth, block="t"), bench)
                a, b = m["atlv"].to_numpy(float), m["bench"].to_numpy(float)
                x = pd.Series((a[1:] / a[:-1] - 1) - (b[1:] / b[:-1] - 1),
                              index=pd.to_datetime([str(e.date()) for e in D.entry[1:]]))
                yearly = (1 + x).groupby(x.index.year).prod() - 1
                rec = dict(excess_cagr=r["excess_cagr"], t_nw=r["t_nw"], cagr=r["cagr_after_tax"],
                           bench=r["bench_cagr_after_tax"], worst12=r["worst_12m_excess"],
                           hold=r["median_hold_km_m"], turnover=r["turnover_pa"], lt_share=r["lt_share_of_gains"],
                           years_positive=f"{int((yearly > 0).sum())}/{len(yearly)}",
                           yearly={int(k): round(float(v), 3) for k, v in yearly.items()})
                if w == "A" and meth == "tier_slow_v1":
                    X = {}
                    for v in B.grid(method=meth):
                        _, mm = B.simulate(D, tier, v, bench)
                        aa, bb = mm["atlv"].to_numpy(float), mm["bench"].to_numpy(float)
                        X[B.vname(v)] = (aa[1:] / aa[:-1] - 1) - (bb[1:] / bb[:-1] - 1)
                    X = pd.DataFrame(X)
                    srs = X.apply(sharpe)
                    ne, _, _ = n_effective(X)
                    dsr, _, _ = B.deflated_sharpe(X[srs.idxmax()], srs.values, max(ne, 2))
                    p = pbo(X)
                    ex_all = X.mean() * 12
                    rec.update(grid_median_excess_pa=round(float(ex_all.median()), 4),
                               grid_share_beating=round(float((ex_all > 0).mean()), 3),
                               n_eff=round(ne, 1), dsr=round(dsr, 3), pbo=p["pbo"],
                               is_best_loses_oos=p["is_best_loses_to_index_oos"])
                    yp = int((yearly > 0).sum())
                    strict = r["t_nw"] >= 2.0 and dsr >= 0.95 and p["pbo"] <= 0.20
                    good = (r["t_nw"] >= 1.5 and (dsr >= 0.90 or p["pbo"] <= 0.30) and yp >= 3
                            and r["worst_12m_excess"] >= -0.15)
                    rec["grade"] = "A" if strict else ("B" if good else "C")
                    rec["planning_excess_pa"] = round(r["excess_cagr"] / 2, 4)
                res[f"{w}:{tier}:{meth}"] = rec
    (V2 / "tier_books.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def main():
    sc = build()
    t = horizon(sc)
    pd.set_option("display.width", 230)
    print(t.to_string(index=False))
    res = books(sc)
    for k, v in res.items():
        print(f"\n== {k}\n  ", {a: b for a, b in v.items()})


if __name__ == "__main__":
    main()
