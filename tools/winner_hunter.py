"""
Plan 0025 task 6.1 — a "winner hunter" sleeve: can a score built for Netweb / SSWL-type runs catch big
winners better than chance, and does its book earn after costs and tax?  (READ-ONLY on the DB;
writes data/lh/v2/hunter_*)

Why: every score we have catches the top-5 % six-month SMALL winners at about chance (slow_v2 top 20:
6.4 % became top-5 % winners vs 5 % by chance; Netweb was never in any top 400). Those runs were
expensive momentum stocks with accelerating quarterly profits; our slow scores reward cheap + quality.

PRE-REGISTRATION (written 2026-10-13, BEFORE the quarterly history exists; nothing below may change
after the first `run`):

Data readiness gate (`check`): `run` refuses to start until quarterly_results_nse covers >= 70 % of
non-Financial SMALL + MID stocks with >= 8 quarters between 2017-04-01 and 2022-12-31.

Quarterly inputs, point in time:
  2017-04 … 2024-12 quarters: quarterly_results_nse, known from `filed_at` (latest filing per quarter
    and basis at or before the anchor; consolidated where filed). core = pbt_pre_exceptional +
    finance_costs + depreciation − other_income (operating profit before one-offs).
  2025+ quarters: quarterly_income (Tickertape), known at period end + 60 days (pit.QUARTERLY_LAG),
    consolidated preferred; core = ebitda.
  A year-on-year comparison uses two quarters from the SAME source, else it is missing.
Features at each monthly anchor (data/lh/labels.parquet anchors), within-tier percentiles:
  M   mom_6m (PIT panel)
  H   position_52w (PIT panel; near the 52-week high)
  A1  core profit acceleration: g_q − g_{q−1}, g_q = (core_q − core_{q−4}) / revenue_{q−4}
  A2  revenue growth, latest quarter: revenue_q / revenue_{q−4} − 1
  A3  core margin change: core_q / revenue_q − core_{q−4} / revenue_{q−4}
Score: hunter = mean of the five percentiles (missing = 0.5). No value or quality component
  (expensive stocks allowed). Eligibility gate: revenue growth (A2) > 0 AND mom_6m > 0.
Universe: SMALL (decides); MID reported. Liquidity floor ₹1 crore 20-session median traded value
  at the anchor; trusts excluded (config.SCREEN trust_exclusion_patterns); Financials excluded.

Tests (window: first anchor with features for >= 50 % of SMALL → last anchor with a 126-session label):
  T1 winner capture (the purpose): per anchor, the share of the hunter's top 20 that became top-5 %
     SMALL winners over 126 sessions (chance 5 %), and the share of all top-5 % winners inside the
     top 20 (chance 20 / n). PASS if the mean hit rate >= 10 % (2× chance) with non-overlap t >= 2.0
     on (hit rate − 5 %).
  T2 book: tools.lh_book machinery (measured costs, Indian tax, NIFTY SMALLCAP 250), across the 12
     staggered start months; primary rule = monthly · top 20 · sell below 60 · raw · 3-month minimum
     hold · no deferral; grid of 8 (N 10 / 20 × k 2 / 3 × hold 0 / 3) for DSR(N_eff) and PBO.
     Graded by ADR 0073 (A / B / C).
  T3 risk: worst 12-month excess, max drawdown vs the index, share of holdings that lost > 30 %.
  Case check (reported, not deciding): NETWEB, SSWL, TIMETECHNO, ATHERENERG ranks at each anchor of their runs.
Decision: T1 PASS and T2 grade B or better → a small hunter sleeve under ADR 0073 (sized below the
  slow / tactical books). T1 PASS but T2 C → watchlist only (a "names to research" list, no book).
  T1 fail → no hunter; record the verdict.

Usage:
  python -m tools.winner_hunter check     # data readiness (safe any time)
  python -m tools.winner_hunter run       # the test (only once `check` says READY)
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

from config import SCREEN  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
FLOOR = 1e7
QLAG = 60
CASES = {"NETWE": "NETWEB", "STWH": "SSWL", "TIME": "TIMETECHNO", "ATHER": "ATHERENERG"}


def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def check(verbose=True):
    con = ro()
    univ = pd.read_sql("SELECT sid FROM stocks WHERE cap_tier IN ('SMALL','MID') AND "
                       "(sector IS NULL OR sector != 'Financials')", con)
    q = pd.read_sql("SELECT sid, COUNT(DISTINCT period_end) AS n FROM quarterly_results_nse "
                    "WHERE period_end BETWEEN '2017-04-01' AND '2022-12-31' GROUP BY sid", con)
    con.close()
    have = univ.merge(q, on="sid", how="left").fillna({"n": 0})
    share = float((have["n"] >= 8).mean())
    ready = share >= 0.70
    if verbose:
        print(f"quarterly_results_nse: {int((have['n'] >= 8).sum())} of {len(have)} SMALL+MID non-Financial stocks "
              f"have >= 8 quarters 2017-04 → 2022-12 ({share:.0%}; gate 70 %) → {'READY' if ready else 'NOT READY'}")
    return ready, share


def quarterly(con):
    nse = pd.read_sql("SELECT sid, period_end, basis, filed_at, revenue, other_income, finance_costs, depreciation, "
                      "pbt_pre_exceptional FROM quarterly_results_nse", con)
    nse["core"] = (nse["pbt_pre_exceptional"] + nse["finance_costs"].fillna(0) + nse["depreciation"].fillna(0)
                   - nse["other_income"].fillna(0))
    nse["known"] = pd.to_datetime(nse["filed_at"].str[:10], errors="coerce")
    nse["src"] = "nse"
    tt = pd.read_sql("SELECT sid, end_date AS period_end, reporting, revenue, ebitda FROM quarterly_income "
                     "WHERE end_date >= '2025-01-01'", con)
    tt["basis"] = np.where(tt["reporting"] == "consolidated", "consolidated", "standalone")
    tt["core"] = tt["ebitda"]
    tt["known"] = pd.to_datetime(tt["period_end"]) + pd.Timedelta(days=QLAG)
    tt["src"] = "tt"
    q = pd.concat([nse[["sid", "period_end", "basis", "known", "revenue", "core", "src"]],
                   tt[["sid", "period_end", "basis", "known", "revenue", "core", "src"]]], ignore_index=True)
    return q.dropna(subset=["known", "revenue"])


def features_at(q, anchor):
    """Latest-knowable quarterly features per sid at `anchor` (consolidated preferred)."""
    k = q[q["known"] <= pd.Timestamp(anchor)]
    k = k.sort_values("known").drop_duplicates(["sid", "period_end", "basis"], keep="last")
    cons = set(k.loc[k["basis"] == "consolidated", "sid"])
    k = k[(k["basis"] == "consolidated") | ~k["sid"].isin(cons)].sort_values(["sid", "period_end"])
    out = []
    for sid, g in k.groupby("sid"):
        g = g.set_index("period_end")
        ends = list(g.index)
        if len(ends) < 5:                    # A2 / A3 need q−4; A1 also needs q−5
            continue

        def yoy(i):
            e, e4 = ends[i], ends[i - 4] if i >= 4 else None
            if e4 is None or abs((pd.Timestamp(e) - pd.Timestamp(e4)).days - 365) > 15:
                return None
            a, b = g.loc[e], g.loc[e4]
            if a["src"] != b["src"] or not b["revenue"] or b["revenue"] <= 0:
                return None
            return dict(g=(a["core"] - b["core"]) / b["revenue"], rev=a["revenue"] / b["revenue"] - 1,
                        dm=(a["core"] / a["revenue"] - b["core"] / b["revenue"]) if a["revenue"] else None)
        cur, prev = yoy(len(ends) - 1), yoy(len(ends) - 2)
        if cur is None:
            continue
        out.append(dict(sid=sid, A1=None if prev is None else cur["g"] - prev["g"], A2=cur["rev"], A3=cur["dm"]))
    return pd.DataFrame(out)


def build_scores():
    con = ro()
    q = quarterly(con)
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier", "fwd_126"])
    anchors = sorted(lab["snapshot_date"].unique())
    ph = ",".join("?" * len(anchors))
    pan = pd.read_sql(f"SELECT sid, snapshot_date, cap_tier, mom_6m, position_52w FROM daily_snapshots_pit "
                      f"WHERE snapshot_date IN ({ph}) AND cap_tier IN ('SMALL','MID')", con, params=anchors)
    st = pd.read_sql("SELECT sid, name, sector FROM stocks", con)
    px = pd.read_sql("SELECT sid, date, close * volume AS tv FROM stock_prices WHERE close > 0", con)
    con.close()
    pats = SCREEN.get("trust_exclusion_patterns", [])
    bad = set(st.loc[st["sector"].eq("Financials") | (st["name"].str.contains("|".join(pats), case=False, regex=True,
                                                                              na=False) if pats else False), "sid"])
    rows = []
    for a in anchors:
        f = features_at(q, a)
        g = pan[pan["snapshot_date"] == a].merge(f, on="sid", how="left")
        g = g[~g["sid"].isin(bad)]
        last = sorted(px.loc[px["date"] <= a, "date"].unique())[-20:]
        liq = px[px["date"].isin(last)].groupby("sid")["tv"].median()
        g = g[g["sid"].map(liq).fillna(0) >= FLOOR]
        for tier, t in g.groupby("cap_tier"):
            t = t.copy()
            pc = [t[c].rank(pct=True) for c in ("mom_6m", "position_52w", "A1", "A2", "A3")]
            t["score"] = pd.concat(pc, axis=1).fillna(0.5).mean(axis=1)
            t["coverage"] = t["A2"].notna()
            t = t[(t["A2"].fillna(-1) > 0) & (t["mom_6m"].fillna(-1) > 0)]   # eligibility gate
            rows.append(t[["sid", "snapshot_date", "cap_tier", "score", "coverage"]])
    sc = pd.concat(rows, ignore_index=True)
    sc["method"] = "hunter"
    sc["pct_rank"] = sc.groupby(["snapshot_date", "cap_tier"])["score"].rank(pct=True)
    sc["oos"] = True
    sc.to_parquet(V2 / "hunter_scores.parquet", index=False)
    return sc


def run():
    ready, share = check()
    if not ready:
        raise SystemExit("winner_hunter: data gate not met — fill quarterly_results_nse first (sources.nse_results).")
    sc = build_scores()
    # T1 and the case check, then T2 via the lh_book machinery (same pattern as tools.lh_timing_luck)
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier", "fwd_126"])
    small = lab[lab["cap_tier"] == "SMALL"].dropna(subset=["fwd_126"]).copy()
    small["win"] = small.groupby("snapshot_date")["fwd_126"].rank(pct=True) >= 0.95
    cov = sc[sc["cap_tier"] == "SMALL"].groupby("snapshot_date")["coverage"].mean()
    first = cov[cov >= 0.5].index.min()
    s = sc[(sc["cap_tier"] == "SMALL") & (sc["snapshot_date"] >= first)].copy()
    s["rank"] = s.groupby("snapshot_date")["score"].rank(ascending=False, method="first")
    d = small.merge(s[["sid", "snapshot_date", "rank"]], on=["sid", "snapshot_date"], how="left")
    per = d[d["rank"] <= 20].groupby("snapshot_date")["win"].mean() - 0.05
    ts = [x.mean() / (x.std() / np.sqrt(len(x))) for x in (per.iloc[o::6] for o in range(6)) if len(x) >= 3 and x.std() > 0]
    t1 = dict(first_anchor=first, anchors=len(per), hit_rate=round(float(per.mean() + 0.05), 4),
              t_nonoverlap=round(float(np.mean(ts)), 2) if ts else None,
              winners_in_top20=round(float((d.loc[d["win"], "rank"] <= 20).mean()), 4))
    t1["pass"] = bool(t1["hit_rate"] >= 0.10 and (t1["t_nonoverlap"] or 0) >= 2.0)
    cases = {name: s[s["sid"] == sid].set_index("snapshot_date")["rank"].astype(int).to_dict() for sid, name in CASES.items()}
    import tools.lh_book as B
    from tools.lh_timing_luck import tstat
    from tools.lh_luck import n_effective, pbo, sharpe
    starts = sorted(s["snapshot_date"].unique())[:12]
    rows, grid_x = [], {}
    for k, stt in enumerate(starts):
        d2 = V2 / "win_hunter"
        d2.mkdir(parents=True, exist_ok=True)
        sc[sc["snapshot_date"] >= stt].drop(columns=["coverage"]).to_parquet(d2 / "oos_scores.parquet", index=False)
        if not (d2 / "labels.parquet").exists():
            os.symlink(LH / "labels.parquet", d2 / "labels.parquet")
        B.LH = d2
        D = B.Data()
        bench = B.benchmark(D, "SMALL")
        for N in (10, 20):
            for kk in (2, 3):
                for mh in (0, 3):
                    v = dict(method="hunter", reb="M", N=N, k=kk, score="raw", min_hold=mh, defer=False, block="h")
                    r, m = B.simulate(D, "SMALL", v, bench)
                    a_, b_ = m["atlv"].to_numpy(float), m["bench"].to_numpy(float)
                    x = (a_[1:] / a_[:-1] - 1) - (b_[1:] / b_[:-1] - 1)
                    if k == 0:
                        grid_x[B.vname(v)] = x
                    rows.append(dict(start=stt, variant=B.vname(v), primary=(N == 20 and kk == 3 and mh == 3),
                                     excess=r["excess_cagr"], t=r["t_nw"], worst12=r["worst_12m_excess"],
                                     max_dd=r.get("max_drawdown"), turnover=r["turnover_pa"]))
    bk = pd.DataFrame(rows)
    prim = bk[bk["primary"]]
    X = pd.DataFrame(grid_x)
    srs = X.apply(sharpe)
    ne, _, _ = n_effective(X)
    dsr, _, _ = B.deflated_sharpe(X[srs.idxmax()], srs.values, max(ne, 2))
    p = pbo(X)
    t2 = dict(median_excess=round(float(prim["excess"].median()), 4), starts_beating=int((prim["excess"] > 0).sum()),
              median_t=round(float(prim["t"].median()), 3), worst12=float(prim["worst12"].min()),
              dsr=round(dsr, 3), pbo=p["pbo"])
    strict = t2["median_t"] >= 2.0 and dsr >= 0.95 and p["pbo"] <= 0.20
    good = (t2["median_t"] >= 1.5 and (dsr >= 0.90 or p["pbo"] <= 0.30) and t2["starts_beating"] >= 10
            and t2["worst12"] >= -0.15)
    t2["grade"] = "A" if strict else ("B" if good else "C")
    verdict = ("hunter sleeve (ADR 0073, small)" if t1["pass"] and t2["grade"] in "AB" else
               "watchlist only" if t1["pass"] else "no hunter")
    out = dict(data_share=share, T1=t1, T2=t2, cases=cases, verdict=verdict)
    (V2 / "hunter_result.json").write_text(json.dumps(out, indent=1, default=str))
    bk.to_csv(V2 / "hunter_books.csv", index=False)
    print(json.dumps(out, indent=1, default=str))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "run"])
    a = ap.parse_args()
    check() if a.cmd == "check" else run()


if __name__ == "__main__":
    main()
