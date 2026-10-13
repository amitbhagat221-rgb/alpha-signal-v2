"""
Plan 0025 tasks 3.1–3.3 — a SMALL-only tactical book on fast scores, after real costs and
Indian tax (READ-ONLY on the DB; writes data/lh/v2/tactical_*).

PRE-REGISTRATION (2026-10-13, before any tactical result):
Score sources (data/lh/oos_scores.parquet, plan 0024 H2):
  fast_select  walk-forward, chosen and weighted on the 20-session label from past anchors only
               → the HONEST out-of-sample fast score. Decides the verdict.
  live         today's live weights applied to history → in-sample (the weights were set on this
               period). Reported for reference only; never decides.
Machinery: tools.lh_book unchanged (monthly anchors; measured Zerodha costs: SMALL 30.5 bps
one-way at ₹1 L; STCG 20 % + cess, LTCG 12.5 % + cess above ₹1.25 L, set-off; benchmark
NIFTY SMALLCAP 250 + dividends; window 2022-06 → 2026-10; forensic red-flag forced sale).
Task 3.1 (names-per-tier at measured cost + tax) is the N dimension of this grid.
Grid (12 variants, all reported): monthly review · top N = 10 / 20 · sell below k·N, k = 1.5 / 2 / 3 ·
raw score · minimum hold 0 or 1 month · no tax deferral (a tactical book doesn't wait for LTCG).
Bar (all): the best variant's excess after costs and tax has t_nw >= 2.0; DSR(N_eff) >= 0.95;
PBO <= 0.20 (tools.lh_luck, S = 8). Turnover is reported, not capped.
Also reported: plan 0024's status quo (top 5 / sell below 8, monthly) on fast_select and live;
3.3 overlap with the slow books: mean share of tactical holdings also held by the slow template
book (slow_select and slow_v2), and the correlation of their monthly excess returns.

Usage: python -m tools.tactical_book [--tier SMALL|MID]   (MID added 2026-10-13, same pre-registered grid and bar;
       outputs get a _MID suffix)
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tools.lh_book as B  # noqa: E402
from tools.lh_luck import n_effective, pbo, sharpe  # noqa: E402

LH = PROJECT_ROOT / "data" / "lh"
OUT = LH / "v2"
TIER = "SMALL"


def grid(method):
    return [dict(method=method, reb="M", N=N, k=k, score="raw", min_hold=mh, defer=False, block="tactical")
            for N in (10, 20) for k in (1.5, 2, 3) for mh in (0, 1)]


def excess(m):
    a, b = m["atlv"].to_numpy(float), m["bench"].to_numpy(float)
    return (a[1:] / a[:-1] - 1) - (b[1:] / b[:-1] - 1)


def main():
    import argparse
    global TIER
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="SMALL", choices=["SMALL", "MID"])
    TIER = ap.parse_args().tier
    sfx = "" if TIER == "SMALL" else f"_{TIER}"
    d = OUT / "win_tactical"
    d.mkdir(parents=True, exist_ok=True)
    sc = pd.read_parquet(LH / "oos_scores.parquet")
    sc = sc[sc["method"].isin(["fast_select", "live", "slow_select"])]
    v2 = pd.read_parquet(OUT / "scores_all.parquet")
    v2 = v2[(v2["method"] == "slow_v2") & (v2["snapshot_date"] >= sc["snapshot_date"].min())]
    pd.concat([sc, v2], ignore_index=True).to_parquet(d / "oos_scores.parquet", index=False)
    if not (d / "labels.parquet").exists():
        os.symlink(LH / "labels.parquet", d / "labels.parquet")
    B.LH = d
    D = B.Data()
    bench = B.benchmark(D, TIER)

    rows, series, holdings = [], {}, {}

    def go(v, kind):
        r, m = B.simulate(D, TIER, v, bench)
        name = B.vname(v)
        rows.append({**{k: r[k] for k in ("excess_cagr", "t_nw", "cagr_after_tax", "bench_cagr_after_tax",
                                         "turnover_pa", "median_hold_km_m", "lt_share_of_gains",
                                         "costs_bps_pa", "tax_paid_inr", "worst_12m_excess", "trades",
                                         "excess_cagr_vs_ew")},
                     "variant": name, "kind": kind, "method": v["method"]})
        series[name] = pd.Series(excess(m))
        holdings[name] = m
        return r

    for meth in ("fast_select", "live"):
        for v in grid(meth):
            go(v, f"grid_{meth}")
        go(dict(method=meth, reb="M", N=5, k=1.6, score="raw", min_hold=0, defer=False, block="sq"), "status_quo")
    for meth in ("slow_select", "slow_v2"):
        go(dict(method=meth, reb="M", N=10, k=3, score="avg3", min_hold=12, defer=True, block="slow"), "slow_template")

    res = pd.DataFrame(rows)
    res.to_csv(OUT / f"tactical_variants{sfx}.csv", index=False)
    summ = {}
    for meth in ("fast_select", "live"):
        g = res[res["kind"] == f"grid_{meth}"]
        X = pd.DataFrame({n: series[n] for n in g["variant"]})
        srs = X.apply(sharpe)
        ne, rho, _ = n_effective(X)
        from tools.lh_book import deflated_sharpe
        dsr, _, _ = deflated_sharpe(X[srs.idxmax()], srs.values, max(ne, 2))
        p = pbo(X)
        best = g.loc[g["t_nw"].idxmax()]
        summ[meth] = dict(best=best.to_dict(), grid_median_excess=float(g["excess_cagr"].median()),
                          grid_median_t=float(g["t_nw"].median()),
                          share_beating_index=float((g["excess_cagr"] > 0).mean()),
                          n_eff=round(ne, 1), dsr_neff=round(dsr, 3), **p,
                          verdict_pass=bool(best["t_nw"] >= 2.0 and dsr >= 0.95 and p["pbo"] <= 0.20))
    # 3.3 overlap: correlation of monthly excess between the best honest tactical variant and slow templates
    bt = summ["fast_select"]["best"]["variant"]
    ov = {}
    for sl in res.loc[res["kind"] == "slow_template", "variant"]:
        ov[f"corr_excess:{bt} vs {sl}"] = round(float(series[bt].corr(series[sl])), 3)
    summ["overlap"] = ov
    (OUT / f"tactical_summary{sfx}.json").write_text(json.dumps(summ, indent=1, default=str))
    pd.set_option("display.width", 230)
    print(res.sort_values(["kind", "t_nw"], ascending=[True, False]).to_string(index=False))
    for k, s in summ.items():
        print("\n==", k, {a: b for a, b in s.items() if a != "best"})
        if "best" in s:
            print("   best:", {a: s["best"][a] for a in ("variant", "excess_cagr", "t_nw", "turnover_pa", "lt_share_of_gains", "costs_bps_pa")})


if __name__ == "__main__":
    main()
