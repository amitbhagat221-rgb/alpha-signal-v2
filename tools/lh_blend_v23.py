"""
Plan 0025 task 2.6 — a 50/50 blend of slow_v2 and slow_v3: keep momentum's edge with a smaller crash?
(READ-ONLY on the DB; writes data/lh/v2/blend_*)

PRE-REGISTRATION (2026-10-13, Amit: "yes test a 50/50 blend of slow_v2 and slow_v3"; before any result):
Scores (SMALL and MID, the real tiers; slow_v2 needs statements, so nothing before 2019-12):
  slow_v2   tools.lh_slow_v2 (mom_6m + quality×value + Piotroski-lite)
  slow_v3   tools.lh_slow_v3 (52-week position + 6-month + 12-month momentum)
  blend     PRIMARY: one book on the mean of the two scores' within-tier percentiles
  pair      secondary: two 20-name books, the monthly excess averaged 50/50
Book (tools.lh_book: measured costs, Indian tax, tier index): monthly · top 20 · sell below 60 ·
3-month average · 12-month hold · tax deferral.
Windows: A = 12 starts 2022-06 … 2023-05 (as the earlier tests); B = 12 starts 2019-12 … 2020-11
(Covid crash, the 2021 boom and the 2022-23 momentum slump: the crash test). Both end 2026-10.
Decision: the blend replaces slow_v2 in the paper sleeve if, in SMALL,
  A: median excess >= slow_v2's AND starts beating the index >= slow_v2's, AND
  B: >= 10/12 starts beat the index, median t >= 1.5, worst 12-month excess >= −15 %.
MID is reported (MID money stays in the index under ADR 0073 unless this changes its grade).

Usage: python -m tools.lh_blend_v23
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

from tools.lh_timing_luck import tstat  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
RULE = dict(reb="M", N=20, k=3, score="avg3", min_hold=12, defer=True, block="blend")


def scores():
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier"])
    lab = lab[lab["cap_tier"].isin(["SMALL", "MID"])]
    anchors = sorted(lab["snapshot_date"].unique())
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ph = ",".join("?" * len(anchors))
    pan = pd.read_sql(f"SELECT sid, snapshot_date, position_52w, mom_6m, mom_12m FROM daily_snapshots_pit "
                      f"WHERE snapshot_date IN ({ph})", con, params=anchors)
    con.close()
    d = lab.merge(pan, on=["sid", "snapshot_date"], how="left")
    g = d.groupby(["snapshot_date", "cap_tier"])
    d["slow_v3"] = pd.concat([g[c].rank(pct=True) for c in ("position_52w", "mom_6m", "mom_12m")], axis=1) \
                     .fillna(0.5).mean(axis=1)
    v2 = pd.read_parquet(V2 / "scores_all.parquet")
    v2 = v2[v2["method"] == "slow_v2"][["sid", "snapshot_date", "score"]].rename(columns={"score": "slow_v2"})
    d = d.merge(v2, on=["sid", "snapshot_date"], how="left")
    g = d.groupby(["snapshot_date", "cap_tier"])
    d["blend"] = pd.concat([g["slow_v2"].rank(pct=True), g["slow_v3"].rank(pct=True)], axis=1).mean(axis=1)
    d = d[d["snapshot_date"] >= "2019-12-01"]
    frames = [d[["sid", "snapshot_date", "cap_tier", m]].rename(columns={m: "score"}).assign(method=m).dropna(subset=["score"])
              for m in ("slow_v2", "slow_v3", "blend")]
    sc = pd.concat(frames, ignore_index=True)
    sc["pct_rank"] = sc.groupby(["method", "snapshot_date", "cap_tier"])["score"].rank(pct=True)
    sc["oos"] = True
    return sc


def run_window(sc, starts, label):
    import tools.lh_book as B
    rows = []
    for st in starts:
        dd = V2 / "win_blend"
        dd.mkdir(parents=True, exist_ok=True)
        sc[sc["snapshot_date"] >= st].to_parquet(dd / "oos_scores.parquet", index=False)
        if not (dd / "labels.parquet").exists():
            os.symlink(LH / "labels.parquet", dd / "labels.parquet")
        B.LH = dd
        D = B.Data()
        for tier in ("SMALL", "MID"):
            bench = B.benchmark(D, tier)
            xs = {}
            for m in ("slow_v2", "slow_v3", "blend"):
                r, mm = B.simulate(D, tier, dict(RULE, method=m), bench)
                a, b = mm["atlv"].to_numpy(float), mm["bench"].to_numpy(float)
                xs[m] = (a[1:] / a[:-1] - 1) - (b[1:] / b[:-1] - 1)
                rows.append(dict(window=label, start=st, tier=tier, method=m, excess=r["excess_cagr"], t=r["t_nw"],
                                 worst12=r["worst_12m_excess"]))
            x = (xs["slow_v2"] + xs["slow_v3"]) / 2
            w12 = pd.Series(1 + x).rolling(12).apply(np.prod, raw=True) - 1
            rows.append(dict(window=label, start=st, tier=tier, method="pair", excess=float(np.prod(1 + x) ** (12 / len(x)) - 1),
                             t=tstat(x), worst12=float(w12.min())))
    return rows


def main():
    sc = scores()
    allst = sorted(sc["snapshot_date"].unique())
    A = [d for d in allst if d >= "2022-06-01"][:12]
    Bw = [d for d in allst if d >= "2019-12-01"][:12]
    rows = run_window(sc, A, "A") + run_window(sc, Bw, "B")
    res = pd.DataFrame(rows)
    res.to_csv(V2 / "blend_books.csv", index=False)
    summ = res.groupby(["window", "tier", "method"]).agg(
        median_excess=("excess", "median"), min_excess=("excess", "min"),
        starts=("excess", lambda v: int((v > 0).sum())), median_t=("t", "median"), worst12=("worst12", "min")).round(4)
    pd.set_option("display.width", 200)
    print(summ.to_string())
    s = summ.loc["A", "SMALL"]
    b = summ.loc["B", "SMALL"]
    out = {}
    for m in ("blend", "pair"):
        a_ok = bool(s.loc[m, "median_excess"] >= s.loc["slow_v2", "median_excess"] and s.loc[m, "starts"] >= s.loc["slow_v2", "starts"])
        b_ok = bool(b.loc[m, "starts"] >= 10 and b.loc[m, "median_t"] >= 1.5 and b.loc[m, "worst12"] >= -0.15)
        out[m] = dict(window_A_beats_v2=a_ok, window_B_crash_test=b_ok, pass_=a_ok and b_ok)
    out["decision"] = ("replace slow_v2 with the blend (primary)" if out["blend"]["pass_"] else "keep slow_v2")
    (V2 / "blend_decision.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
