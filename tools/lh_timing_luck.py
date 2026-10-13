"""
Timing luck — how much does a book's result depend on the month it starts?  (READ-ONLY on the DB;
writes data/lh/v2/timing_luck.csv)

PRE-REGISTRATION (2026-10-13, prompted by tools.lh_tier_slow: the same SMALL template made
+0.8 %/yr from 2022-06 and +18.4 %/yr from 2019-12 over the same years):
Start months: the 12 anchors 2022-06 … 2023-05; every run ends 2026-10. Books (tools.lh_book
machinery unchanged: measured costs, Indian tax, tier index, forensic red-flag sale):
  slow:     monthly · top N · sell below 3N · 3-month average · 12-month hold · deferral, N = 10 and 20,
            on tier_slow_v1, slow_select, slow_v2 (SMALL, MID)
  tactical: monthly · top 20 · sell below 40 · raw · no minimum hold · no deferral, on fast_select
  combo:    the monthly mean of the slow (N 20, tier_slow_v1 / slow_select) and tactical excess
Per (book, start): excess CAGR vs the tier index after costs and tax, t_nw (lag 3).
Summary per book: median / min / max excess across the 12 starts, share of starts with
excess > 0, median t. A book is "robust to timing" if >= 10 of 12 starts beat the index.

Usage: python -m tools.lh_timing_luck
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tools.lh_book as B  # noqa: E402
from tools.backtest_pit import _newey_west_se  # noqa: E402

LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"


def scores():
    a = pd.read_parquet(LH / "oos_scores.parquet")
    a = a[a["method"].isin(["slow_select", "fast_select"])]
    b = pd.read_parquet(V2 / "scores_all.parquet")
    b = b[b["method"] == "slow_v2"]
    c = pd.read_parquet(V2 / "tier_scores.parquet")
    c = c[c["method"] == "tier_slow_v1"]
    cols = ["sid", "snapshot_date", "cap_tier", "method", "score", "pct_rank", "oos"]
    return pd.concat([a[cols], b[cols], c[cols]], ignore_index=True)


def tstat(x):
    se = _newey_west_se(np.asarray(x, float), 3)
    return float(np.mean(x) / se) if se and se > 0 else np.nan


def main():
    sc = scores()
    starts = sorted(d for d in sc.loc[sc["method"] == "fast_select", "snapshot_date"].unique())[:12]
    rows = []
    for st in starts:
        d = V2 / "win_timing"
        d.mkdir(parents=True, exist_ok=True)
        sc[sc["snapshot_date"] >= st].to_parquet(d / "oos_scores.parquet", index=False)
        if not (d / "labels.parquet").exists():
            os.symlink(LH / "labels.parquet", d / "labels.parquet")
        B.LH = d
        D = B.Data()
        for tier in ("SMALL", "MID"):
            bench = B.benchmark(D, tier)
            ser = {}

            def go(name, v):
                r, m = B.simulate(D, tier, v, bench)
                a, b = m["atlv"].to_numpy(float), m["bench"].to_numpy(float)
                x = (a[1:] / a[:-1] - 1) - (b[1:] / b[:-1] - 1)
                ser[name] = x
                rows.append(dict(start=st, tier=tier, book=name, excess_cagr=r["excess_cagr"], t=r["t_nw"]))

            for meth in ("tier_slow_v1", "slow_select", "slow_v2"):
                for N in (10, 20):
                    go(f"slow:{meth}:N{N}", dict(method=meth, reb="M", N=N, k=3, score="avg3", min_hold=12,
                                                 defer=True, block="t"))
            go("tactical:fast_select:N20", dict(method="fast_select", reb="M", N=20, k=2, score="raw",
                                                min_hold=0, defer=False, block="t"))
            for meth in ("tier_slow_v1", "slow_select"):
                x = (ser[f"slow:{meth}:N20"] + ser["tactical:fast_select:N20"]) / 2
                years = len(x) / 12
                rows.append(dict(start=st, tier=tier, book=f"combo:{meth}+tactical", excess_cagr=round(
                    float(np.prod(1 + x) ** (1 / years) - 1), 4), t=round(tstat(x), 3)))
    df = pd.DataFrame(rows)
    df.to_csv(V2 / "timing_luck.csv", index=False)
    s = df.groupby(["tier", "book"]).agg(
        median_excess=("excess_cagr", "median"), min_excess=("excess_cagr", "min"), max_excess=("excess_cagr", "max"),
        starts_beating=("excess_cagr", lambda v: f"{int((v > 0).sum())}/{len(v)}"), median_t=("t", "median"),
        min_t=("t", "min"))
    pd.set_option("display.width", 200)
    print(s.round(3).to_string())
    return df


if __name__ == "__main__":
    main()
