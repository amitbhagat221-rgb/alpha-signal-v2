"""
Does a "good enough" factor bar improve MID or LARGE?  (READ-ONLY on the DB; writes
data/lh/v2/relax_*)

Amit 2026-10-13: "small is already set, see if it improves anything for middle and large, then only
relax and make it good enough, else let it be."

PRE-REGISTRATION (2026-10-13, before any result). Walk-forward, factors chosen from past anchors
only (the tools.lh_slow_model / tools.walk_forward machinery and candidate columns, unchanged):
  slow_strict   = plan 0024 slow_select: training NW t (lag 6) of IC126 |t| >= 2.5, the 8 strongest,
                  weight ±1.
  slow_relaxed  = A factors as slow_strict (weight ±1) PLUS B factors: 1.5 <= |t| < 2.5 AND the same
                  IC sign in both halves of the training window; weight ±0.5; at most 16 factors.
  fast_strict   = tools.walk_forward `select`: plain t of IC20 |t| >= 2.5, 6 strongest, ±1, embargo 1.
  fast_relaxed  = fast_strict PLUS B factors 1.5 <= |t| < 2.5 with the same sign in both halves,
                  ±0.5, at most 12 factors.
Tiers: MID and LARGE (SMALL is settled).
Evaluation (out of sample only):
  1. rank IC at 21 and 126, non-overlap t;
  2. the top-20 book across the 12 start months 2022-06 … 2023-05 to 2026-10, after measured costs
     and Indian tax (tools.lh_book): slow scores use monthly · top 20 · sell below 60 · 3-month
     average · 12-month hold; fast scores use monthly · top 20 · sell below 40 · raw · no hold.
Decision rule per tier: relax only if, for the slow or the fast pair, the relaxed book's median
excess across the 12 starts is >= +1.0 %/yr above strict, its count of starts beating the index is
not lower, and its OOS IC (126 for slow, 21 for fast) is not lower. Otherwise keep ADR 0043's bar.

Usage: python -m tools.lh_relax_test
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tools.lh_slow_model as S  # noqa: E402
from tools.walk_forward import EMBARGO, composite  # noqa: E402

LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
TIERS = ("MID", "LARGE")


def _halves_agree(x):
    h = len(x) // 2
    return h >= 3 and np.sign(np.mean(x[:h])) == np.sign(np.mean(x[h:])) != 0


def choose(ic_tab, train, t_fn, max_a, max_all):
    st = {}
    for c, s in ic_tab.items():
        x = s[s.index.isin(train)].to_numpy()
        if len(x) >= S.SLOW_MIN_N and x.std(ddof=1) > 0:
            st[c] = (float(x.mean()), t_fn(x), x)
    a = sorted((c for c, v in st.items() if abs(v[1]) >= 2.5), key=lambda c: -abs(st[c][1]))[:max_a]
    strict = {c: float(np.sign(st[c][0])) for c in a}
    b = sorted((c for c, v in st.items() if 1.5 <= abs(v[1]) < 2.5 and _halves_agree(v[2])),
               key=lambda c: -abs(st[c][1]))
    relaxed = dict(strict)
    for c in b:
        if len(relaxed) >= max_all:
            break
        relaxed[c] = 0.5 * float(np.sign(st[c][0]))
    return strict, relaxed


def walk():
    df, cols, anchors, entry, _ = S.load()
    frames, choices = [], []
    plain_t = lambda x: float(np.mean(x) / (np.std(x, ddof=1) / np.sqrt(len(x))))  # noqa: E731
    for tier in TIERS:
        tdf = df[df["cap_tier"] == tier]
        ic126 = S.ic_table(tdf[["snapshot_date", *cols, "fwd_126"]], cols, "fwd_126")
        ic20 = S.ic_table(tdf[["snapshot_date", *cols, S.FAST]], cols, S.FAST)
        by_date = dict(tuple(tdf.groupby("snapshot_date")))
        for k, a in enumerate(anchors):
            if a not in by_date:
                continue
            train = [anchors[j] for j in range(k)
                     if k - j >= S.EMBARGO_MIN and entry[k] - entry[j] >= S.LABEL_SESSIONS + 1]
            if len(train) < S.MIN_TRAIN:
                continue
            g = by_date[a].set_index("sid")
            ss, sr = choose(ic126, set(train), lambda x: S.nw_t(x, S.NW_LAG[126]), 8, 16)
            fs, fr = choose(ic20, set(anchors[:k - EMBARGO]), plain_t, 6, 12)
            for m, w in (("slow_strict", ss), ("slow_relaxed", sr), ("fast_strict", fs), ("fast_relaxed", fr)):
                choices.append(dict(tier=tier, anchor=a, method=m, n=len(w), weights=json.dumps(w)))
                if not w:
                    continue
                s = composite(g, w)
                frames.append(pd.DataFrame({"sid": s.index, "snapshot_date": a, "cap_tier": tier, "method": m,
                                            "score": s.to_numpy(float), "pct_rank": s.rank(pct=True).to_numpy(float),
                                            "oos": True}))
        print(f"[{tier}] done", flush=True)
    sc = pd.concat(frames, ignore_index=True)
    sc.to_parquet(V2 / "relax_scores.parquet", index=False)
    pd.DataFrame(choices).to_csv(V2 / "relax_choices.csv", index=False)
    return sc


def ic_summary(sc):
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "fwd_21", "fwd_126"])
    out = []
    for (m, tier), g in sc.groupby(["method", "cap_tier"]):
        d = g.merge(lab, on=["sid", "snapshot_date"])
        for h in (21, 126):
            per = d.dropna(subset=[f"fwd_{h}"]).groupby("snapshot_date").apply(
                lambda x: x["score"].rank().corr(x[f"fwd_{h}"].rank()) if len(x) >= 20 else np.nan).dropna()
            step = max(h // 21, 1)
            ts = [s.mean() / (s.std() / np.sqrt(len(s))) for s in (per.iloc[o::step] for o in range(step))
                  if len(s) >= 3 and s.std() > 0]
            out.append(dict(method=m, tier=tier, h=h, n=len(per), ic=round(per.mean(), 4),
                            t_nonoverlap=round(float(np.mean(ts)), 2) if ts else np.nan))
    return pd.DataFrame(out)


def books(sc):
    import tools.lh_book as B
    starts = sorted(sc.loc[sc["snapshot_date"] >= "2022-06-01", "snapshot_date"].unique())[:12]
    rows = []
    for st in starts:
        d = V2 / "win_relax"
        d.mkdir(parents=True, exist_ok=True)
        sc[sc["snapshot_date"] >= st].to_parquet(d / "oos_scores.parquet", index=False)
        if not (d / "labels.parquet").exists():
            os.symlink(LH / "labels.parquet", d / "labels.parquet")
        B.LH = d
        D = B.Data()
        for tier in TIERS:
            bench = B.benchmark(D, tier)
            for m in ("slow_strict", "slow_relaxed", "fast_strict", "fast_relaxed"):
                v = (dict(method=m, reb="M", N=20, k=3, score="avg3", min_hold=12, defer=True, block="r")
                     if m.startswith("slow") else
                     dict(method=m, reb="M", N=20, k=2, score="raw", min_hold=0, defer=False, block="r"))
                r, _ = B.simulate(D, tier, v, bench)
                rows.append(dict(start=st, tier=tier, method=m, excess=r["excess_cagr"], t=r["t_nw"],
                                 turnover=r["turnover_pa"]))
    df = pd.DataFrame(rows)
    df.to_csv(V2 / "relax_books.csv", index=False)
    return df


def main():
    sc = walk()
    ic = ic_summary(sc)
    bk = books(sc)
    summ = bk.groupby(["tier", "method"]).agg(
        median_excess=("excess", "median"), min_excess=("excess", "min"), max_excess=("excess", "max"),
        starts_beating=("excess", lambda v: int((v > 0).sum())), median_t=("t", "median"),
        turnover=("turnover", "median")).reset_index()
    verdict = {}
    for tier in TIERS:
        for kind, h in (("slow", 126), ("fast", 21)):
            s = summ[(summ["tier"] == tier) & (summ["method"] == f"{kind}_strict")].iloc[0]
            r = summ[(summ["tier"] == tier) & (summ["method"] == f"{kind}_relaxed")].iloc[0]
            ics = ic[(ic["tier"] == tier) & (ic["h"] == h)].set_index("method")["ic"]
            ok = (r["median_excess"] - s["median_excess"] >= 0.01 and r["starts_beating"] >= s["starts_beating"]
                  and ics.get(f"{kind}_relaxed", -9) >= ics.get(f"{kind}_strict", 9))
            verdict[f"{tier}:{kind}"] = dict(relax=bool(ok), d_median_excess=round(r["median_excess"] - s["median_excess"], 4),
                                             starts=f"{r['starts_beating']} vs {s['starts_beating']}",
                                             ic_relaxed=ics.get(f"{kind}_relaxed"), ic_strict=ics.get(f"{kind}_strict"))
    (V2 / "relax_verdict.json").write_text(json.dumps(verdict, indent=1, default=str))
    pd.set_option("display.width", 200)
    print(ic.to_string(index=False))
    print(summ.round(3).to_string(index=False))
    print(json.dumps(verdict, indent=1, default=str))
    ch = pd.read_csv(V2 / "relax_choices.csv")
    print(ch.groupby(["tier", "method"])["n"].mean().round(1).to_string())


if __name__ == "__main__":
    main()
