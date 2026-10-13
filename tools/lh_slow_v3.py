"""
Plan 0025 task 2.5 — slow_v3: a momentum-centred slow score, tested over 15 years on the full market
and against slow_v2 on 2019+.  (READ-ONLY on the DB; writes data/lh/v2/v3_*)

PRE-REGISTRATION (2026-10-13, after tools.lh_price_history found the 52-week position t 6.33 and
6-month momentum t 6.04 in the small-cap proxy; before any slow_v3 book result):

slow_v3 = equal-weight mean of within-group percentiles of
          position in the 52-week range · 6-month momentum · 12-month momentum
          (15-year panel: pos_52w, mom_6m, mom_12_1 from tools.lh_price_history;
           2019+ panel: position_52w, mom_6m, mom_12m from daily_snapshots_pit). Missing = 0.5.
slow_v3q (2019+ only, statements needed) = the same four-way mean with quality × value
          (mean percentile of a_roce and book_to_price, tools.lh_growth) as the fourth part.

Part LONG — 15 years, full market incl. delisted (data/lh/v2/pricehist_panel.parquet groups):
  book = monthly · top 20 · sell below rank 60 · 12-month minimum hold · equal weight at entry,
  T3 (small proxy) and T2 (mid proxy), month-to-month returns from the next session's close to the
  next anchor's next session (a name that stops trading exits at its last close), 30.5 bps one way
  (T3) / 17.9 bps (T2), PRE-TAX (the 12-month hold makes almost every gain long-term).
  Benchmark: the group's equal-weight average (survivorship-free; no index exists for 2011-15).
  Starts: the 12 anchors 2011-02 … 2012-01, all to the last anchor with a next-month return.
  Also run: pos_52w alone, mom_6m alone.
Part RECENT — 2019+, real tiers (tools.lh_book: measured costs, Indian tax, tier index):
  the same template on slow_v3, slow_v3q and slow_v2, SMALL and MID, 12 starts 2022-06 … 2023-05.
Decision (slow book upgrade): slow_v3 (or slow_v3q) replaces slow_v2 in the paper sleeve if
  LONG T3: >= 10/12 starts beat the group average, median t >= 1.5, worst 12-month excess >= −15 %; AND
  RECENT SMALL: median excess across starts >= slow_v2's AND starts beating the index >= slow_v2's.
  Between slow_v3 and slow_v3q, the higher RECENT SMALL median excess wins.

Usage: python -m tools.lh_slow_v3 [long|recent|both]
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.backtest_pit import _newey_west_se  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
COST = {"T3": 0.00305, "T2": 0.00179}


def tstat(x):
    x = np.asarray(x, float)
    se = _newey_west_se(x, 3)
    return float(x.mean() / se) if se and se > 0 else np.nan


# ───────────────────────── LONG: 15 years, full market ─────────────────────────

def month_returns():
    """{anchor: Series(id -> return from the session after this anchor to the session after the next)}"""
    from tools.lh_price_history import load
    P, _, _ = load()
    dates = P.index
    first = pd.Series(dates, index=pd.to_datetime(dates)).groupby(pd.to_datetime(dates).to_period("M")).first()
    anchors = [d for d in first.values if d >= "2011-01-01"]
    pos = {d: i for i, d in enumerate(dates)}
    out = {}
    for a, b in zip(anchors[:-1], anchors[1:]):
        i, j = pos[a] + 1, pos[b] + 1
        if j >= len(dates):
            break
        seg = P.iloc[i:j + 1]
        start = seg.iloc[0]
        end = seg.iloc[-1].where(seg.iloc[-1].notna(), seg.ffill().iloc[-1])
        out[a] = (end / start - 1).dropna()
    return out


def simulate_long(df, mret, group, score_col, start, N=20, sell_rank=60, min_hold=12):
    g = df[df["group"] == group]
    anchors = sorted(a for a in g["anchor"].unique() if a >= start and a in mret)
    held, xs = {}, []
    for k, a in enumerate(anchors):
        cur = g[g["anchor"] == a].set_index("id")
        rank = cur[score_col].rank(ascending=False, method="first")
        trades = 0.0
        for i in list(held):
            r = rank.get(i)
            if (r is None or np.isnan(r) or r > sell_rank) and k - held[i] >= min_hold:
                del held[i]
                trades += 1
        for i in rank.sort_values().index:
            if len(held) >= N:
                break
            if i not in held:
                held[i] = k
                trades += 1
        rets = mret[a]
        book = rets.reindex(list(held)).fillna(0.0).mean() if held else 0.0
        bench = rets.reindex(cur.index).mean()
        cost = trades / N * COST[group]
        xs.append(book - cost - bench)
        for i in list(held):                 # names that stopped trading leave the book
            if i not in rets.index:
                del held[i]
    x = np.array(xs)
    yrs = len(x) / 12
    w12 = pd.Series(1 + x).rolling(12).apply(np.prod, raw=True) - 1
    return dict(excess_pa=float(np.prod(1 + x) ** (1 / yrs) - 1), t=tstat(x), worst12=float(w12.min()), months=len(x))


def long_part():
    df = pd.read_parquet(V2 / "pricehist_panel.parquet")
    for grp in ("T2", "T3"):
        m = df["group"] == grp
        p = {c: df[m].groupby("anchor")[c].rank(pct=True) for c in ("pos_52w", "mom_6m", "mom_12_1")}
        df.loc[m, "slow_v3"] = pd.concat(p.values(), axis=1).fillna(0.5).mean(axis=1)
    mret = month_returns()
    starts = sorted(df["anchor"].unique())[:12]
    rows = []
    for grp in ("T3", "T2"):
        for sc in ("slow_v3", "pos_52w", "mom_6m"):
            for st in starts:
                r = simulate_long(df, mret, grp, sc, st)
                rows.append(dict(group=grp, score=sc, start=st, **r))
    res = pd.DataFrame(rows)
    res.to_csv(V2 / "v3_long.csv", index=False)
    summ = res.groupby(["group", "score"]).agg(median_excess=("excess_pa", "median"), min_excess=("excess_pa", "min"),
                                              starts_beating=("excess_pa", lambda v: int((v > 0).sum())),
                                              median_t=("t", "median"), worst12=("worst12", "min")).round(4)
    print("LONG (pre-tax, after costs, vs the group's equal-weight average incl. delisted):\n", summ.to_string())
    return summ


# ───────────────────────── RECENT: 2019+, real tiers ─────────────────────────

def recent_part():
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier"])
    lab = lab[lab["cap_tier"].isin(["SMALL", "MID"])]
    anchors = sorted(lab["snapshot_date"].unique())
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ph = ",".join("?" * len(anchors))
    pan = pd.read_sql(f"SELECT sid, snapshot_date, position_52w, mom_6m, mom_12m, book_to_price FROM daily_snapshots_pit "
                      f"WHERE snapshot_date IN ({ph})", con, params=anchors)
    con.close()
    gf = pd.read_parquet(LH / "growth_features.parquet", columns=["sid", "snapshot_date", "a_roce"])
    d = lab.merge(pan, on=["sid", "snapshot_date"], how="left").merge(gf, on=["sid", "snapshot_date"], how="left")
    grp = d.groupby(["snapshot_date", "cap_tier"])
    pc = {c: grp[c].rank(pct=True) for c in ("position_52w", "mom_6m", "mom_12m", "a_roce", "book_to_price")}
    qv = pd.concat([pc["a_roce"], pc["book_to_price"]], axis=1).mean(axis=1)
    mom = [pc["position_52w"], pc["mom_6m"], pc["mom_12m"]]
    d["slow_v3"] = pd.concat(mom, axis=1).fillna(0.5).mean(axis=1)
    d["slow_v3q"] = pd.concat(mom + [qv], axis=1).fillna(0.5).mean(axis=1)
    frames = [d[["sid", "snapshot_date", "cap_tier", m]].rename(columns={m: "score"}).assign(method=m)
              for m in ("slow_v3", "slow_v3q")]
    v2 = pd.read_parquet(V2 / "scores_all.parquet")
    frames.append(v2[v2["method"] == "slow_v2"][["sid", "snapshot_date", "cap_tier", "score", "method"]])
    sc = pd.concat(frames, ignore_index=True)
    sc["pct_rank"] = sc.groupby(["method", "snapshot_date", "cap_tier"])["score"].rank(pct=True)
    sc["oos"] = True
    import tools.lh_book as B
    starts = sorted(sc.loc[sc["snapshot_date"] >= "2022-06-01", "snapshot_date"].unique())[:12]
    rows = []
    for st in starts:
        dd = V2 / "win_v3"
        dd.mkdir(parents=True, exist_ok=True)
        sc[sc["snapshot_date"] >= st].to_parquet(dd / "oos_scores.parquet", index=False)
        if not (dd / "labels.parquet").exists():
            os.symlink(LH / "labels.parquet", dd / "labels.parquet")
        B.LH = dd
        D = B.Data()
        for tier in ("SMALL", "MID"):
            bench = B.benchmark(D, tier)
            for m in ("slow_v3", "slow_v3q", "slow_v2"):
                r, _ = B.simulate(D, tier, dict(method=m, reb="M", N=20, k=3, score="avg3", min_hold=12, defer=True,
                                                block="v3"), bench)
                rows.append(dict(start=st, tier=tier, method=m, excess=r["excess_cagr"], t=r["t_nw"],
                                 worst12=r["worst_12m_excess"]))
    res = pd.DataFrame(rows)
    res.to_csv(V2 / "v3_recent.csv", index=False)
    summ = res.groupby(["tier", "method"]).agg(median_excess=("excess", "median"), min_excess=("excess", "min"),
                                               starts_beating=("excess", lambda v: int((v > 0).sum())),
                                               median_t=("t", "median"), worst12=("worst12", "min")).round(4)
    print("RECENT (after measured costs and Indian tax, vs the tier index):\n", summ.to_string())
    return summ


def decide(long_s, recent_s):
    L = long_s.loc[("T3", "slow_v3")]
    long_ok = bool(L["starts_beating"] >= 10 and L["median_t"] >= 1.5 and L["worst12"] >= -0.15)
    v2 = recent_s.loc[("SMALL", "slow_v2")]
    cands = {m: recent_s.loc[("SMALL", m)] for m in ("slow_v3", "slow_v3q")}
    ok = {m: bool(r["median_excess"] >= v2["median_excess"] and r["starts_beating"] >= v2["starts_beating"])
          for m, r in cands.items()}
    winner = max((m for m in ok if ok[m]), key=lambda m: cands[m]["median_excess"], default=None)
    v = dict(long_T3_pass=long_ok, recent_beats_v2=ok,
             decision=(f"upgrade the slow book to {winner}" if long_ok and winner else "keep slow_v2"))
    (V2 / "v3_decision.json").write_text(json.dumps(v, indent=1, default=str))
    print(json.dumps(v, indent=1, default=str))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("part", nargs="?", default="both", choices=["long", "recent", "both"])
    a = ap.parse_args()
    L = long_part() if a.part in ("long", "both") else None
    R = recent_part() if a.part in ("recent", "both") else None
    if L is not None and R is not None:
        decide(L, R)


if __name__ == "__main__":
    main()
