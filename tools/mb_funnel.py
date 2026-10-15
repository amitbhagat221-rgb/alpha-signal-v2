"""
Plan 0026 phase 1c — test the successive funnel's mechanical stage rules (READ-ONLY; writes data/lh/v2/mbf_*).

Amit 2026-10-15: "we need successive funnel structure and then for the final 30 the whole valuation and
detailed shebang"; before that: "all these should be in the funnel no? maybe top 100 and then we look at
other factors as well?" The funnel (plan 0026): universe → safety gates (pond) → thesis score top 100 →
stage-2 evidence → 30 candidates (full valuation + deep dive) → 10 held (Amit). Only the mechanical parts
can be backtested; Amit's stage-2 judgement cannot.

PRE-REGISTRATION (written 2026-10-15 BEFORE any run; rules and bars do not change after the first run —
a bug is fixed in code and logged here with a date):

Harness: tools.mb_thesis_v2.simulate / evaluate (12 staggered starts from 2016, yearly rebalance, realistic
costs by liquidity at ₹30 lakh / 30 names, 12.5 % tax on realised gains, vs NIFTY SMALLCAP 250), the v1
thesis score (tools.mb_thesis.score) and v2's superinvestor flag (si_entry: a frozen-list investor newly
>= 1 % in the latest filing knowable at the anchor, filing <= 200 days old).

Variants (30 names each):
  F0  baseline: top 30 by the thesis score (= v1 under realistic costs).
  F1  industry cap: walk down the thesis ranking, at most 4 names per `stocks.industry`.
  F2  stage cut + promotion: take the top 100; every name in it with si_entry = 1 goes into the 30 first
      (highest score first if more than 30), the rest filled from the top 100 by score.
  F3  F2 with F1's cap applied to the fill.
  F4  liquidity floor ₹0.25 Cr ADTV instead of ₹0.5 Cr (the pond and its percentiles recomputed), top 30,
      realistic costs; F4s = the same with spread and impact doubled (lh_costs stress).
Decision rules (vs F0; halves = calendar 2016–2020 | 2021–2026):
  F1 is a risk control: KEEP if the median excess falls by <= 1.0 point in each half and the worst
     12-month excess is not worse by more than 2 points.
  F2 / F3: ACCEPT if the median excess rises by >= 1.0 point, rises in both halves, the worst 12 months are
     not worse by more than 5 points, and the selected 30's 3-year halving rate (October anchors) is not
     above F0's by more than 0.10 of the pond's rate.
  F4: ACCEPT the lower floor only if F4s (doubled costs) beats F0 (normal costs) in both halves with the
     worst 12 months not worse by more than 5 points.
Reported for the chosen funnel: T2 grade (ADR 0073), and stage capture — of the pond stocks that tripled in
3 years (October anchors), how many sat in the stage-1 top 100 and in the final 30, vs chance.

Usage:  python -m tools.mb_funnel
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools import mb_thesis as v1  # noqa: E402
from tools import mb_thesis_v2 as v2  # noqa: E402
from tools.lh_price_history import load  # noqa: E402

V2 = v2.V2
HALVES = ((2016, 2020), (2021, 2026))
CAP = 4
STAGE1 = 100


def capped(ids, industry, n, cap=CAP, start=()):
    out, count = list(start), {}
    for i in out:
        count[industry.get(i)] = count.get(industry.get(i), 0) + 1
    for i in ids:
        if len(out) >= n:
            break
        if i in out:
            continue
        k = industry.get(i)
        if count.get(k, 0) >= cap:
            continue
        out.append(i)
        count[k] = count.get(k, 0) + 1
    return out


def selector(kind, si_by_anchor, industry):
    """select(g, ranked, n) with the anchor read from g's 'anchor' column."""
    def sel(g, ranked, n):
        a = g["anchor"].iloc[0]
        if kind == "F1":
            return capped(ranked, industry, n)
        top = ranked[:STAGE1]
        flagged = si_by_anchor.get(a, set())
        promoted = [i for i in top if i in flagged][:n]
        if kind == "F2":
            return promoted + [i for i in top if i not in promoted][:n - len(promoted)]
        return capped(top, industry, n, start=promoted)              # F3
    return sel


def selected_sets(df, sc, sel, anchors):
    out = {}
    for a in anchors:
        g = df[(df["anchor"] == a) & df["pond_b"].fillna(False).astype(bool) & df[sc].notna()].set_index("id")
        if len(g) < 100:
            continue
        ranked = list(g[sc].sort_values(ascending=False).index)
        out[a] = (g, ranked, sel(g, ranked, 30) if sel else ranked[:30])
    return out


def tail_stats(df, sc, sel):
    octs = sorted(a for a in df["anchor"].unique() if a[5:7] == "10")
    rows = []
    for a, (g, ranked, chosen) in selected_sets(df, sc, sel, octs).items():
        g = g[g["y3"].notna()]
        if g.empty:
            continue
        w = set(g.index[g["y3"] >= 3])
        bh = (g["y3"] <= 0.5).mean()
        ch = g.loc[[i for i in chosen if i in g.index]]
        rows.append({"anchor": a, "pond": len(g), "winners": len(w),
                     "in_top100": len(w & set(ranked[:STAGE1])), "chance100": len(w) * min(STAGE1, len(g)) / len(g),
                     "in_30": len(w & set(chosen)), "chance30": len(w) * 30 / len(g),
                     "halve_lift": (ch["y3"] <= 0.5).mean() / bh if bh > 0 else np.nan})
    return pd.DataFrame(rows)


def main():
    P, _, _ = load()
    PF = P.ffill()
    bench = v2.bench_series()
    panel = pd.read_parquet(V2 / "mb_thesis_panel.parquet")
    df = v2.add_features(v1.score(panel))
    df["sc"] = df["score_b"]
    industry = df.dropna(subset=["industry"]).drop_duplicates("id", keep="last").set_index("id")["industry"].to_dict()
    si_by_anchor = df[df["si_entry"] == 1].groupby("anchor")["id"].apply(set).to_dict()
    res, tails = {}, {}

    def run(name, frame, sel=None, stress=False, floor=0.5 * v1.CR):
        ser = v2.simulate(frame, P, "sc", bench_daily=bench, PF=PF, select=sel, stress=stress, floor=floor)
        st, _ = v2.evaluate(ser, bench, HALVES)
        t = tail_stats(frame, "sc", sel)
        tails[name] = t
        st["halve_lift"] = float(t["halve_lift"].mean())
        st["won_30"], st["chance_30"] = int(t["in_30"].sum()), float(t["chance30"].sum())
        st["won_100"], st["chance_100"] = int(t["in_top100"].sum()), float(t["chance100"].sum())
        res[name] = st
        print(f"{name:34s} excess {st['excess']:+.1%} (h1 {st['half1']:+.1%} h2 {st['half2']:+.1%}) t {st['t']:.2f} "
              f"worst {st['worst']:+.1%} starts {st['starts']}/12 last5 {st['last5']}/5 halve-lift "
              f"{st['halve_lift']:.2f} winners in 30 {st['won_30']} (chance {st['chance_30']:.0f}) "
              f"in top100 {st['won_100']} (chance {st['chance_100']:.0f}) grade {st['grade']}", flush=True)

    run("F0 top 30", df)
    run("F1 top 30, <= 4 per industry", df, selector("F1", si_by_anchor, industry))
    run("F2 top 100 + investor promotion", df, selector("F2", si_by_anchor, industry))
    run("F3 F2 + industry cap", df, selector("F3", si_by_anchor, industry))
    v1.ADTV_MIN = 0.25 * v1.CR
    df4 = v1.score(panel)
    df4["sc"] = df4["score_b"]
    run("F4 floor 0.25 Cr", df4, floor=0.25 * v1.CR)
    run("F4s floor 0.25 Cr, costs x2", df4, stress=True, floor=0.25 * v1.CR)
    v1.ADTV_MIN = 0.5 * v1.CR

    b = res["F0 top 30"]
    verdict = {}
    f1 = res["F1 top 30, <= 4 per industry"]
    verdict["F1"] = (f1["half1"] - b["half1"] >= -0.01 and f1["half2"] - b["half2"] >= -0.01
                     and f1["worst"] - b["worst"] >= -0.02)
    for k, name in (("F2", "F2 top 100 + investor promotion"), ("F3", "F3 F2 + industry cap")):
        s = res[name]
        verdict[k] = (s["excess"] - b["excess"] >= 0.01 and s["half1"] > b["half1"] and s["half2"] > b["half2"]
                      and s["worst"] - b["worst"] >= -0.05 and s["halve_lift"] <= b["halve_lift"] + 0.10)
    s = res["F4s floor 0.25 Cr, costs x2"]
    verdict["F4"] = s["half1"] > b["half1"] and s["half2"] > b["half2"] and s["worst"] - b["worst"] >= -0.05
    print("\nverdicts:", verdict, flush=True)
    pd.DataFrame(res).T.to_csv(V2 / "mbf_results.csv")
    pd.concat(tails, names=["variant"]).to_csv(V2 / "mbf_tails.csv")


if __name__ == "__main__":
    main()
