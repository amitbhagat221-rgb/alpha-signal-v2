"""
Plan 0025 task 7.1 — policy-capex theme momentum: does a theme book catch the asymmetric winners (defence,
power T&D, rail …) without the lottery-ticket downside?  (READ-ONLY on the DB; writes data/lh/v2/theme_*)

Why: the doubler study (docs/studies/doubler-study-2026-10.md) found defence 26 % double / 0 % halve and 9 of the
40 biggest runs were policy-capex themes, where the live model sat in the middle. CAVEAT: the theme idea was found
by looking at 2019-25 doublers, so this test is NOT out of sample for the idea itself; the rule below is fixed before
any theme result, and the 2020-22 / 2023-25 split is reported so a one-period fluke shows.

PRE-REGISTRATION (2026-10-13, before any result of this tool):
Panel  every monthly anchor of data/lh/labels.parquet (PIT tiers); scored tiers SMALL and MID. SMALL decides.
Inputs at anchor a (only data dated before or on a):
  ind_mom   median 6-month return (126 sessions, adjusted closes) of all universe stocks (any tier, incl. MICRO) in
            the stock's industry (stocks.industry, today's label; >= 5 members with a value, else the sector median).
  policy    sector_policy_pit.policy_score of the stock's sector, the latest month-end <= a (exists 2020-05 →).
  orders    BSE 'Award of Order / Receipt of Order' filings by the stock with a date in [a − 182 days, a).
  pos_52w   (close − 252-session low) / (high − low); >= 200 sessions needed.
  adtv      median close × volume of the 20 sessions <= a.
Score  theme = equal-weight mean of within-(anchor, tier) percentiles of ind_mom, policy, orders (no filing = 0, a
       real count), pos_52w; a missing input counts 0.5. No fitted weight.
Gate = the exit rule  a stock is held or bought only while ind_mom > 0 AND pos_52w >= 0.5 AND adtv >= ₹1 crore
       (Amit's floor). A stock failing the gate gets no score, so tools.lh_book sells it at the next monthly review
       ("exit when industry momentum or the stock's 52-week position breaks").
Label hygiene  a (stock, anchor) whose next 12 months hold a pure-dividend adjustment factor < 0.5 is dropped
       (AURUM/MAJC's ×24 special-dividend artifact, HANDOFF watch-out).
Book   tools.lh_book unchanged (measured costs, Indian tax, tier index + dividends; MID = equal-weight tier average
       before 2023-06; forensic red-flag sale). Grid of 6: monthly · top 20 · sell below k·20, k = 1.5 / 2 / 3 · min
       hold 0 / 1 month · raw score · no tax deferral. PRIMARY = k 2, hold 0.
       Starts: the 12 anchors 2020-06 … 2021-05, each run to the last anchor.
Grade (ADR 0073), per tier, on the PRIMARY variant from the first start unless stated:
  A  t_nw haircut over the 6 variants >= 2.0, DSR(N_eff of the grid) >= 0.95, PBO (S = 8, the grid) <= 0.20
  B  t_nw >= 1.5; DSR >= 0.90 or PBO <= 0.30; beats the index in >= 3 of the 5 calendar years 2021-25; >= 10 of 12
     starts beat the index (excess CAGR > 0); worst 12-month excess >= −15 %
  C  anything less
Asymmetry bar  top 20 by theme among gated names per (anchor, tier), anchors 2020-06 … 2025-09 (a 12-month outcome
       exists): P(double: fwd_252 >= +100 %) >= 2 × the tier base rate, P(halve: <= −50 %) <= base, median excess
       (fwd_252 − the tier median at that anchor) >= 0. Base = every tier stock at the same anchors. Reported also
       for 2020-22 and 2023-25 (diagnostic).
Decision (SMALL):  grade >= B AND asymmetry → a theme sleeve candidate (paper, Amit to approve);
                   asymmetry only → a theme watch-list, not a book;  neither → no theme sleeve.
Diagnostics (never decide): the asymmetry table for each input alone (gated), the score without orders / without
policy, and the score without the gate; today's gated top 20 per tier.

POST-HOC DIAGNOSTIC (added 2026-10-13 AFTER the results above; decides nothing): `diag` runs the PRIMARY book from
the first start on the score without orders, without policy, the price-only score (ind_mom + pos_52w, gated) and the
ungated score, to show whether the theme inputs add anything over momentum + the gate.

Usage: python -m tools.theme_momentum [asym|book|all|diag]
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from signals._prices import apply_adjustments  # noqa: E402
from signals import announcements  # noqa: E402  (BSE history + NSE live, ADR 0082)

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
TIERS = ("SMALL", "MID")
ORDER_SUB = "Award of Order / Receipt of Order"
FLOOR_INR = 1e7
TOP = 20
ASYM_FROM, ASYM_TO = "2020-06-01", "2025-09-01"
START_FROM = "2020-06-01"
INPUTS = ("ind_mom", "policy", "orders", "pos_52w")


# ───────────────────────── panel ─────────────────────────

def build():
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier", "fwd_252"])
    anchors = sorted(lab["snapshot_date"].unique())
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    st = pd.read_sql("SELECT sid, sector, industry FROM stocks", con)
    px = pd.read_sql("SELECT sid, date, close, volume FROM stock_prices WHERE close > 0 AND date >= '2018-09-01'", con)
    adj = pd.read_sql("SELECT sid, ex_date, factor, inds FROM corporate_adjustments", con)
    pol = pd.read_sql("SELECT sector, snapshot_date, policy_score FROM sector_policy_pit", con)
    od = pd.read_sql(f"SELECT sid, substr(dt_tm, 1, 10) AS d FROM ({announcements.sql()}) a "
                     "WHERE subcategory = ? AND sid IS NOT NULL AND dt_tm IS NOT NULL", con, params=[ORDER_SUB])
    con.close()

    px = apply_adjustments(px, adj, date.max)
    P = px.pivot_table(index="date", columns="sid", values="adj_close").sort_index()
    TV = (px.assign(tv=px["close"] * px["volume"]).pivot_table(index="date", columns="sid", values="tv")
            .reindex(P.index))
    Pf = P.ffill(limit=5)
    dates = P.index.to_numpy()
    ind = st.set_index("sid")["industry"]
    sec = st.set_index("sid")["sector"]
    od = od.sort_values("d")
    pol = pol.sort_values("snapshot_date")
    divs = adj[(adj["inds"] == "DIVIDEND") & (adj["factor"] < 0.5)]

    rows = []
    for a in anchors:
        k = int(np.searchsorted(dates, a, side="right"))
        if k < 253:
            continue
        last = Pf.iloc[k - 1]
        mom = last / Pf.iloc[k - 1 - 126] - 1
        w = P.iloc[k - 252:k]
        hi, lo, cnt = w.max(), w.min(), w.count()
        pos = ((last - lo) / (hi - lo)).where((cnt >= 200) & (hi > lo))
        adtv = TV.iloc[k - 20:k].median()
        f = pd.DataFrame({"mom_6m": mom, "pos_52w": pos, "adtv": adtv}).dropna(subset=["mom_6m"])
        f["industry"] = ind.reindex(f.index).values
        f["sector"] = sec.reindex(f.index).values
        im = f.groupby("industry")["mom_6m"].agg(["median", "count"])
        sm = f.groupby("sector")["mom_6m"].agg(["median", "count"])
        i_med = f["industry"].map(im["median"].where(im["count"] >= 5))
        s_med = f["sector"].map(sm["median"].where(sm["count"] >= 5))
        f["ind_mom"] = i_med.fillna(s_med)
        lo_d = (pd.Timestamp(a) - pd.Timedelta(days=182)).date().isoformat()
        f["orders"] = od[(od["d"] >= lo_d) & (od["d"] < a)].groupby("sid").size().reindex(f.index).fillna(0).values
        p_now = pol[pol["snapshot_date"] <= a].groupby("sector")["policy_score"].last()
        f["policy"] = f["sector"].map(p_now)
        hi_d = (pd.Timestamp(a) + pd.Timedelta(days=365)).date().isoformat()
        f["artifact"] = f.index.isin(divs[(divs["ex_date"] > a) & (divs["ex_date"] <= hi_d)]["sid"])
        rows.append(f.rename_axis("sid").reset_index().assign(snapshot_date=a))
    feat = pd.concat(rows, ignore_index=True)
    d = lab[lab["cap_tier"].isin(TIERS)].merge(feat, on=["sid", "snapshot_date"], how="left")
    d["artifact"] = d["artifact"].fillna(False).astype(bool)
    d["ex"] = d["fwd_252"] - d.groupby(["snapshot_date", "cap_tier"])["fwd_252"].transform("median")
    g = d.groupby(["snapshot_date", "cap_tier"])
    for c in INPUTS:
        d[f"p_{c}"] = g[c].rank(pct=True)
    d["gate"] = (d["ind_mom"] > 0) & (d["pos_52w"] >= 0.5) & (d["adtv"] >= FLOOR_INR) & ~d["artifact"]

    def mean_pct(cols):
        return d[[f"p_{c}" for c in cols]].fillna(0.5).mean(axis=1)

    d["theme"] = mean_pct(INPUTS)
    d["theme_no_orders"] = mean_pct(["ind_mom", "policy", "pos_52w"])
    d["theme_no_policy"] = mean_pct(["ind_mom", "orders", "pos_52w"])
    return d


def scores(d):
    """Gated score columns: NaN = not eligible (not bought / sold at the next review)."""
    s = {"theme": d["theme"].where(d["gate"]),
         "theme_ungated": d["theme"].where(~d["artifact"]),
         "theme_no_orders": d["theme_no_orders"].where(d["gate"]),
         "theme_no_policy": d["theme_no_policy"].where(d["gate"])}
    for c in INPUTS:
        s[f"only_{c}"] = d[f"p_{c}"].where(d["gate"])
    return pd.DataFrame(s)


# ───────────────────────── asymmetry ─────────────────────────

def asymmetry(d, S):
    rows = []
    span = (d["snapshot_date"] >= ASYM_FROM) & (d["snapshot_date"] <= ASYM_TO)
    periods = {"2020-06…2025-09": lambda x: x == x, "2020-22": lambda x: x < "2023-01-01",
               "2023-25": lambda x: x >= "2023-01-01"}
    for tier in TIERS:
        base_all = d[span & (d["cap_tier"] == tier) & ~d["artifact"] & d["fwd_252"].notna()]
        for col in S.columns:
            cand = d.loc[span & (d["cap_tier"] == tier)].assign(s=S[col]).dropna(subset=["s"])
            top = cand.sort_values("s", ascending=False).groupby("snapshot_date").head(TOP)
            for per, f in periods.items():
                t = top[f(top["snapshot_date"])]
                tv = t[t["fwd_252"].notna()]
                b = base_all[f(base_all["snapshot_date"]) & base_all["snapshot_date"].isin(t["snapshot_date"].unique())]
                if tv.empty or b.empty:
                    continue
                r = dict(tier=tier, score=col, period=per, anchors=t["snapshot_date"].nunique(),
                         names_per_anchor=round(len(t) / max(t["snapshot_date"].nunique(), 1), 1),
                         with_outcome=round(len(tv) / len(t), 3),
                         p_double=tv["fwd_252"].ge(1.0).mean(), base_double=b["fwd_252"].ge(1.0).mean(),
                         p_halve=tv["fwd_252"].le(-0.5).mean(), base_halve=b["fwd_252"].le(-0.5).mean(),
                         median_ex=tv["ex"].median(), mean_ex=tv["ex"].mean())
                r["lift_double"] = r["p_double"] / r["base_double"] if r["base_double"] else np.nan
                r["passes"] = bool(r["p_double"] >= 2 * r["base_double"] and r["p_halve"] <= r["base_halve"]
                                   and r["median_ex"] >= 0)
                rows.append(r)
    return pd.DataFrame(rows)


# ───────────────────────── book ─────────────────────────

def grid():
    return [dict(method="theme", reb="M", N=TOP, k=k, score="raw", min_hold=mh, defer=False, block="theme")
            for k in (1.5, 2, 3) for mh in (0, 1)]


PRIMARY = dict(method="theme", reb="M", N=TOP, k=2, score="raw", min_hold=0, defer=False, block="theme")


def books(d, S):
    import tools.lh_book as B
    from tools.lh_luck import n_effective, pbo, sharpe

    sc = d[["sid", "snapshot_date", "cap_tier"]].assign(method="theme", score=S["theme"]).dropna(subset=["score"])
    sc["pct_rank"] = sc.groupby(["snapshot_date", "cap_tier"])["score"].rank(pct=True)
    sc["oos"] = True
    all_anchors = sorted(d["snapshot_date"].unique())
    starts = [a for a in all_anchors if a >= START_FROM][:12]
    rows, first = [], {}
    for st in starts:
        w = sc[sc["snapshot_date"] >= st]
        missing = sorted(set(a for a in all_anchors if a >= st) - set(w["snapshot_date"]))
        assert not missing, f"anchors with no gated name would break the return chain: {missing}"
        dd = V2 / "win_theme"
        dd.mkdir(parents=True, exist_ok=True)
        w.to_parquet(dd / "oos_scores.parquet", index=False)
        if not (dd / "labels.parquet").exists():
            os.symlink(LH / "labels.parquet", dd / "labels.parquet")
        B.LH = dd
        D = B.Data()
        for tier in TIERS:
            bench = B.benchmark(D, tier)
            for v in (grid() if st == starts[0] else [PRIMARY]):
                r, m = B.simulate(D, tier, v, bench)
                name = B.vname(v)
                rows.append(dict(start=st, tier=tier, variant=name, primary=v == PRIMARY,
                                 **{k: r[k] for k in ("excess_cagr", "t_nw", "worst_12m_excess", "cagr_after_tax",
                                                      "bench_cagr_after_tax", "excess_cagr_vs_ew", "turnover_pa",
                                                      "median_hold_closed_m", "avg_cash_share", "costs_bps_pa",
                                                      "no_signal_exits", "positions", "n_months")}))
                if st == starts[0]:
                    a_, b_ = m["atlv"].to_numpy(float), m["bench"].to_numpy(float)
                    x = pd.Series((a_[1:] / a_[:-1]) - (b_[1:] / b_[:-1]), index=m["entry"].iloc[1:].values)
                    first[(tier, name)] = dict(x=x, rb=pd.Series(a_[1:] / a_[:-1], index=x.index),
                                               rx=pd.Series(b_[1:] / b_[:-1], index=x.index))
    res = pd.DataFrame(rows)
    res.to_csv(V2 / "theme_books.csv", index=False)

    grades = {}
    pname = B.vname(PRIMARY)
    for tier in TIERS:
        X = pd.DataFrame({n: first[(t, n)]["x"] for (t, n) in first if t == tier})
        srs = X.apply(sharpe)
        ne, _, _ = n_effective(X)
        dsr, _, _ = B.deflated_sharpe(X[pname], srs.values, max(ne, 2))
        p = pbo(X)
        prim = res[(res["tier"] == tier) & res["primary"]]
        r0 = prim[prim["start"] == starts[0]].iloc[0]
        rb, rx = first[(tier, pname)]["rb"], first[(tier, pname)]["rx"]
        yrs = pd.Index(pd.to_datetime(rb.index).year)
        cal = {int(y): round(float(rb[yrs == y].prod() / rx[yrs == y].prod() - 1), 4) for y in range(2021, 2026)}
        t_h = B.haircut_t(r0["t_nw"], int(r0["n_months"]), len(grid()))
        beat = int((prim["excess_cagr"] > 0).sum())
        g = dict(t_nw=r0["t_nw"], t_haircut=t_h, dsr=round(dsr, 3), n_eff=round(ne, 2), pbo=p["pbo"],
                 calendar_excess=cal, years_beating=sum(v > 0 for v in cal.values()),
                 starts_beating=f"{beat}/{len(prim)}", median_excess_across_starts=float(prim["excess_cagr"].median()),
                 min_excess_across_starts=float(prim["excess_cagr"].min()), median_t_across_starts=float(prim["t_nw"].median()),
                 worst_12m=r0["worst_12m_excess"], excess_cagr_first_start=r0["excess_cagr"],
                 turnover_pa=r0["turnover_pa"], avg_cash_share=r0["avg_cash_share"])
        A = (t_h or 0) >= 2.0 and dsr >= 0.95 and p["pbo"] <= 0.20
        Bg = (r0["t_nw"] >= 1.5 and (dsr >= 0.90 or p["pbo"] <= 0.30) and g["years_beating"] >= 3 and beat >= 10
              and r0["worst_12m_excess"] >= -0.15)
        g["grade"] = "A" if A else ("B" if Bg else "C")
        grades[tier] = g
    return res, grades


def diag(d, S):
    """Post-hoc (see docstring): the PRIMARY book from the first start on ablated scores."""
    import tools.lh_book as B
    S = S.assign(price_only=d[["p_ind_mom", "p_pos_52w"]].fillna(0.5).mean(axis=1).where(d["gate"]))
    meths = ["theme", "theme_no_orders", "theme_no_policy", "price_only", "theme_ungated"]
    sc = pd.concat([d[["sid", "snapshot_date", "cap_tier"]].assign(method=m, score=S[m]) for m in meths],
                   ignore_index=True).dropna(subset=["score"])
    sc = sc[sc["snapshot_date"] >= START_FROM]
    sc["pct_rank"] = sc.groupby(["method", "snapshot_date", "cap_tier"])["score"].rank(pct=True)
    sc["oos"] = True
    dd = V2 / "win_theme_diag"
    dd.mkdir(parents=True, exist_ok=True)
    sc.to_parquet(dd / "oos_scores.parquet", index=False)
    if not (dd / "labels.parquet").exists():
        os.symlink(LH / "labels.parquet", dd / "labels.parquet")
    B.LH = dd
    D = B.Data()
    rows = []
    for tier in TIERS:
        bench = B.benchmark(D, tier)
        for m in meths:
            r, _ = B.simulate(D, tier, {**PRIMARY, "method": m}, bench)
            rows.append(dict(tier=tier, score=m, **{k: r[k] for k in ("excess_cagr", "t_nw", "worst_12m_excess",
                                                                       "turnover_pa", "avg_cash_share")}))
    res = pd.DataFrame(rows)
    res.to_csv(V2 / "theme_diag.csv", index=False)
    print("POST-HOC DIAGNOSTIC (decides nothing):\n", res.round(4).to_string(index=False))


def latest(d, S):
    a = d["snapshot_date"].max()
    t = d[d["snapshot_date"] == a].assign(s=S["theme"]).dropna(subset=["s"])
    t = t.sort_values("s", ascending=False).groupby("cap_tier").head(TOP)
    return t[["cap_tier", "sid", "industry", "s", "ind_mom", "policy", "orders", "pos_52w", "adtv"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("part", nargs="?", default="all", choices=["asym", "book", "all", "diag"])
    part = ap.parse_args().part
    pd.set_option("display.width", 240)
    d = build()
    S = scores(d)
    d.assign(**{f"s_{c}": S[c] for c in S.columns}).to_parquet(V2 / "theme_panel.parquet", index=False)
    print(f"panel {len(d):,} rows, gated share {d['gate'].mean():.3f}; gated names per anchor (median) "
          f"{d[d['gate']].groupby(['snapshot_date', 'cap_tier']).size().groupby('cap_tier').median().to_dict()}")
    out = {}
    if part == "diag":
        return diag(d, S)
    if part in ("asym", "all"):
        A = asymmetry(d, S)
        A.to_csv(V2 / "theme_asymmetry.csv", index=False)
        print("\nASYMMETRY (top 20 per anchor; base = the whole tier at the same anchors):")
        print(A.round(3).to_string(index=False))
        out["asymmetry"] = {t: A[(A["tier"] == t) & (A["score"] == "theme") & (A["period"] == "2020-06…2025-09")]
                            .iloc[0][["p_double", "base_double", "p_halve", "base_halve", "median_ex", "passes"]].to_dict()
                            for t in TIERS}
        lt = latest(d, S)
        lt.to_csv(V2 / "theme_latest.csv", index=False)
        print(f"\nTODAY's gated top {TOP} ({d['snapshot_date'].max()}):\n", lt.round(3).to_string(index=False))
    if part in ("book", "all"):
        res, grades = books(d, S)
        print("\nBOOKS:\n", res.round(4).to_string(index=False))
        print("\nGRADES:", json.dumps(grades, indent=1, default=str))
        out["grades"] = grades
    if part == "all":
        s_ok = out["asymmetry"]["SMALL"]["passes"]
        s_g = out["grades"]["SMALL"]["grade"]
        out["decision"] = ("theme sleeve candidate (paper; Amit to approve)" if s_g in ("A", "B") and s_ok else
                           "theme watch-list, not a book" if s_ok else "no theme sleeve")
        print("\nDECISION (SMALL):", out["decision"])
    (V2 / f"theme_summary_{part}.json").write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
