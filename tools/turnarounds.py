"""
Plan 0025 task 7.2 — turnarounds: does a deleveraging + profit-turn + price-confirmation screen catch asymmetric
winners (re-ratings of companies coming back from distress) without the lottery-ticket downside?
(READ-ONLY on the DB; writes data/lh/v2/turnaround_*)

Why: the doubler study (docs/studies/doubler-study-2026-10.md) listed turnarounds as one of the three shapes of the
big runs the live model missed. Sibling of tools/theme_momentum.py (task 7.1): same labels, same book machinery
(tools.lh_book), same asymmetry measurement, same output layout, so the two verdicts are comparable.

PRE-REGISTRATION (written 2026-10-14, before any result of this tool; choices the plan leaves open are marked
"(filled in 2026-10-14 before any run)"). Nothing below may change after the first run; bugs get a dated note.

Panel  every monthly anchor of data/lh/labels.parquet (PIT tiers; 2019-12 → 2026-10); scored tiers SMALL and MID.
       SMALL decides; MID is reported.
Universe  non-Financial (stocks.sector != 'Financials'), not a trust (config.SCREEN trust_exclusion_patterns),
       ₹1 crore floor on the 20-session median close × volume at the anchor (Amit's floor). (filled in 2026-10-14
       before any run: Financials are out because debt / assets means nothing for a lender.)
Inputs at anchor a (only data knowable on or before a):
  Annual (fundamentals_screener, period_type 'annual', known at fiscal year end + 150 days as tools/lh_growth.py and
    tools/lh_forensic.py; rows need both 'Borrowings' and 'Total' (total assets); only the sid's usual fiscal
    year-end month, so half-year balance sheets are ignored; the latest knowable year must end within 550 days of a):
    da_t = Borrowings / Total.
    DELEV  (debt / assets falling two years running) = da_t < da_{t−1} < da_{t−2}, three consecutive fiscal years
           (330–400 days apart), and da_{t−2} >= 0.10 (it was a levered company; filled in 2026-10-14 before any run).
    delev_amt = da_{t−2} − da_t (ranking input; computed whenever the three years exist).
  Quarterly (filled in 2026-10-14 before any run, conventions of tools/winner_hunter.py):
    2017-04 … 2024-12 quarters: quarterly_results_nse (80–100-day periods), known from `filed_at`; the latest filing
      per (quarter, basis) at or before a; consolidated where the sid has any consolidated filing known by a.
      profit = pbt_pre_exceptional (pbt if missing); interest = finance_costs.
    2025+ quarters: fundamentals_screener period_type 'quarterly' (Screener; 'Profit before tax', 'Interest'), known at
      period end + 60 days (pit.QUARTERLY_LAG). Tickertape quarterly_income has no interest line, so Screener is used
      for both legs after 2024. The prior quarters of a 2025 quarter may come from NSE: the legs are sign / threshold
      tests, so the mixed source is accepted (caveat, not a fix).
    The latest knowable quarter q must end within 200 days of a; its "prior quarters" are those ending in the 380
    days before q (at least 3 needed).
    TURN_P (profit turning positive) = profit_q > 0 AND at least one prior quarter with profit <= 0.
    TURN_C (interest coverage crossing 1.5) = icr_q >= 1.5 AND at least one prior quarter with icr < 1.5, where
           icr = (profit + interest) / interest, defined only when interest > 0.
    TURN = TURN_P OR TURN_C.
  ACQ   (a credible acquirer) = any BSE filing by the stock in subcategory 'Open Offer', 'Public Announcement-Open
        Offer', 'Open Offer - Updates' or 'Acquisition' dated in [a − 365 days, a) (bse_announcements, 2018+).
        CAVEAT written before any run: 'Acquisition' is mostly the company buying something, not being bought.
  mom_3m  63-session return on adjusted closes (signals._prices.apply_adjustments), the stock's own price.
PRIMARY RULE (gate; filled in 2026-10-14 before any run — the acquirer is a ranking input, not a gate leg, because a
       required open offer would leave almost no names):
       gate = DELEV AND TURN AND mom_3m > 0 AND universe AND not a label artifact.
Ranking among passers  score = equal-weight mean of within-(anchor, tier) percentiles (over the universe) of
       delev_amt, mom_3m and ACQ (0/1, a real value); a missing input counts 0.5. No fitted weight. Top 20 per tier.
Exit = the gate (as 7.1): a stock failing the gate gets no score, so tools.lh_book sells it at the next monthly
       review (the turnaround condition or the price confirmation has lapsed). An anchor where a tier has no passer:
       lh_book's own rule (no buys, no band sales that month); a placeholder row keeps the return chain unbroken when
       neither tier has a passer.
Label hygiene  a (stock, anchor) whose next 12 months hold a pure-dividend adjustment factor < 0.5 is dropped (as 7.1).
Book   tools.lh_book unchanged (measured costs, Indian tax, tier index + dividends; MID = equal-weight tier average
       before 2023-06; forensic red-flag sale). Grid of 6: monthly · top 20 · sell below k·20, k = 1.5 / 2 / 3 · min
       hold 0 / 1 month · raw score · no tax deferral. PRIMARY = k 2, hold 0. Starts: the 12 anchors 2019-12 … 2020-11
       (the first 12 anchors; every input exists from 2019-12), each run to the last anchor.
Grade (ADR 0073), per tier, on the PRIMARY variant from the first start unless stated (as 7.1):
  A  t_nw haircut over the 6 variants >= 2.0, DSR(N_eff of the grid) >= 0.95, PBO (S = 8, the grid) <= 0.20
  B  t_nw >= 1.5; DSR >= 0.90 or PBO <= 0.30; beats the index in >= 3 of the 5 calendar years 2021-25 (2020 is
     reported, not counted, to match 7.1); >= 10 of 12 starts beat the index (excess CAGR > 0); worst 12-month
     excess >= −15 %
  C  anything less
Asymmetry bar  top 20 by score among gated names per (anchor, tier), anchors 2019-12 … 2025-09 (a 12-month outcome
       exists): P(double: fwd_252 >= +100 %) >= 2 × the tier base rate, P(halve: <= −50 %) <= base, median excess
       (fwd_252 − the tier median at that anchor) >= 0. Base = every tier stock (not an artifact) at the same anchors
       (as 7.1). Reported also for 2019-22 and 2023-25 (diagnostic).
Book shape (ADR 0073: at least 20 names)  the median number of gated SMALL names per anchor must be >= 20 for a
       sleeve; below that the book is mostly cash and cannot be the ADR's 20-name sleeve.
Decision (SMALL; filled in 2026-10-14 before any run, closing the hole 7.1 hit):
       grade >= B AND asymmetry AND book shape → a turnaround sleeve candidate (paper, Amit to approve);
       asymmetry passes otherwise (grade C, or too few names) → a turnaround watch-list, not a book;
       asymmetry fails → no turnaround sleeve, whatever the grade (phase 7 needs both; a B without asymmetry is
       reported as a near-miss, nothing more).
Diagnostics (never decide): asymmetry for each gate variant — acquirer as an OR-leg ((DELEV OR ACQ) AND TURN AND
       mom), acquirer required (gate AND ACQ), no price confirmation, DELEV alone (+ mom), TURN alone (+ mom), each
       TURN leg alone (with DELEV + mom); the base restricted to the universe; passers per anchor; today's top 20.

Usage: python -m tools.turnarounds [smoke|asym|book|all]
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

from config import SCREEN  # noqa: E402
from signals._prices import apply_adjustments  # noqa: E402
from tools.lh_growth import asof  # noqa: E402
from signals import announcements  # noqa: E402  (BSE history + NSE live, ADR 0082)

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
TIERS = ("SMALL", "MID")
ACQ_SUB = ("Open Offer", "Public Announcement-Open Offer", "Open Offer - Updates", "Acquisition")
FLOOR_INR = 1e7
TOP = 20
ANNUAL_LAG, QLAG = 150, 60
DA_MIN = 0.10
ICR_BAR = 1.5
ASYM_FROM, ASYM_TO = "2019-12-01", "2025-09-01"
START_FROM = "2019-12-01"
INPUTS = ("delev_amt", "mom_3m", "acq")
PLACEHOLDER = "__none__"


def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


# ───────────────────────── inputs ─────────────────────────

def annual(con):
    raw = pd.read_sql("SELECT sid, period_end, line_item, value FROM fundamentals_screener "
                      "WHERE period_type='annual' AND line_item IN ('Borrowings','Total')", con)
    w = raw.pivot_table(index=["sid", "period_end"], columns="line_item", values="value", aggfunc="last").reset_index()
    w = w.dropna(subset=["Borrowings", "Total"])
    w = w[w["Total"] > 0]
    w["m"] = w["period_end"].str[5:7]
    modal = w.groupby("sid")["m"].agg(lambda s: s.mode().iloc[0])
    w = w[w["m"] == w["sid"].map(modal)].sort_values(["sid", "period_end"]).copy()
    w["da"] = w["Borrowings"] / w["Total"]
    g = w.groupby("sid")
    pe = pd.to_datetime(w["period_end"])
    c1 = (pe - pd.to_datetime(g["period_end"].shift(1))).dt.days.between(330, 400)
    c2 = (pd.to_datetime(g["period_end"].shift(1)) - pd.to_datetime(g["period_end"].shift(2))).dt.days.between(330, 400)
    da1, da2 = g["da"].shift(1), g["da"].shift(2)
    both = c1 & c2
    w["delev"] = both & (w["da"] < da1) & (da1 < da2) & (da2 >= DA_MIN)
    w["delev_amt"] = (da2 - w["da"]).where(both)
    w["pe"] = w["period_end"]
    return w[["sid", "period_end", "pe", "da", "delev", "delev_amt"]]


def quarterly(con):
    nse = pd.read_sql("SELECT sid, period_start, period_end, basis, filed_at, pbt_pre_exceptional, pbt, finance_costs "
                      "FROM quarterly_results_nse", con)
    days = (pd.to_datetime(nse["period_end"]) - pd.to_datetime(nse["period_start"])).dt.days
    nse = nse[days.between(80, 100)].copy()
    nse["profit"] = nse["pbt_pre_exceptional"].fillna(nse["pbt"])
    nse["interest"] = nse["finance_costs"]
    nse["known"] = pd.to_datetime(nse["filed_at"].str[:10], errors="coerce")
    scr = pd.read_sql("SELECT sid, period_end, line_item, value FROM fundamentals_screener WHERE period_type='quarterly' "
                      "AND period_end >= '2025-01-01' AND line_item IN ('Profit before tax','Interest')", con)
    scr = (scr.pivot_table(index=["sid", "period_end"], columns="line_item", values="value", aggfunc="last")
              .reset_index().rename(columns={"Profit before tax": "profit", "Interest": "interest"}))
    scr["basis"] = "screener"
    scr["known"] = pd.to_datetime(scr["period_end"]) + pd.Timedelta(days=QLAG)
    cols = ["sid", "period_end", "basis", "known", "profit", "interest"]
    q = pd.concat([nse[cols], scr[cols]], ignore_index=True).dropna(subset=["known", "profit"])
    q["pe_t"] = pd.to_datetime(q["period_end"])
    return q


def turn_at(q, anchor):
    """TURN_P / TURN_C per sid at `anchor` (see docstring)."""
    a = pd.Timestamp(anchor)
    k = q[q["known"] <= a].sort_values("known").drop_duplicates(["sid", "period_end", "basis"], keep="last")
    cons = set(k.loc[k["basis"] == "consolidated", "sid"])
    k = k[(k["basis"] != "standalone") | ~k["sid"].isin(cons)]
    k = k.sort_values(["sid", "period_end", "known"]).drop_duplicates(["sid", "period_end"], keep="last")
    k = k.groupby("sid").tail(6).copy()
    k["icr"] = ((k["profit"] + k["interest"]) / k["interest"]).where(k["interest"] > 0)
    last = k.groupby("sid").tail(1).set_index("sid")
    last = last[last["pe_t"] >= a - pd.Timedelta(days=200)]
    pr = k.merge(last[["pe_t"]].rename(columns={"pe_t": "q_pe"}), left_on="sid", right_index=True)
    pr = pr[(pr["pe_t"] < pr["q_pe"]) & (pr["pe_t"] >= pr["q_pe"] - pd.Timedelta(days=380))]
    agg = pr.groupby("sid").agg(n_prior=("profit", "size"), min_profit=("profit", "min"),
                                weak_icr=("icr", lambda s: bool((s < ICR_BAR).any())))
    f = last[["profit", "icr"]].join(agg, how="inner")
    f = f[f["n_prior"] >= 3]
    f["turn_p"] = (f["profit"] > 0) & (f["min_profit"] <= 0)
    f["turn_c"] = (f["icr"] >= ICR_BAR) & f["weak_icr"].astype(bool)
    return f[["turn_p", "turn_c"]].rename_axis("sid").reset_index()


def build(only=None):
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier", "fwd_252"])
    anchors = sorted(lab["snapshot_date"].unique())
    if only:
        anchors = [anchors[i] for i in only]
        lab = lab[lab["snapshot_date"].isin(anchors)]
    con = ro()
    st = pd.read_sql("SELECT sid, name, sector, industry FROM stocks", con)
    px = pd.read_sql("SELECT sid, date, close, volume FROM stock_prices WHERE close > 0 AND date >= '2019-06-01'", con)
    adj = pd.read_sql("SELECT sid, ex_date, factor, inds FROM corporate_adjustments", con)
    acq = pd.read_sql(f"SELECT sid, substr(dt_tm, 1, 10) AS d FROM ({announcements.sql()}) a WHERE subcategory IN "
                      f"({','.join('?' * len(ACQ_SUB))}) AND sid IS NOT NULL AND dt_tm IS NOT NULL", con, params=list(ACQ_SUB))
    ann = annual(con)
    q = quarterly(con)
    con.close()

    ann_at = asof(ann, "period_end", ANNUAL_LAG, anchors, ["pe", "da", "delev", "delev_amt"])
    fresh = (pd.to_datetime(ann_at["snapshot_date"]) - pd.to_datetime(ann_at["pe"])).dt.days <= 550
    ann_at = ann_at[fresh]

    px = apply_adjustments(px, adj, date.max)
    P = px.pivot_table(index="date", columns="sid", values="adj_close").sort_index()
    TV = (px.assign(tv=px["close"] * px["volume"]).pivot_table(index="date", columns="sid", values="tv")
            .reindex(P.index))
    del px
    Pf = P.ffill(limit=5)
    dates = P.index.to_numpy()
    divs = adj[(adj["inds"] == "DIVIDEND") & (adj["factor"] < 0.5)]

    rows = []
    for a in anchors:
        k = int(np.searchsorted(dates, a, side="right"))
        if k < 64:
            continue
        last = Pf.iloc[k - 1]
        f = pd.DataFrame({"mom_3m": last / Pf.iloc[k - 1 - 63] - 1, "adtv": TV.iloc[k - 20:k].median()})
        f = f.rename_axis("sid").reset_index()
        lo_d = (pd.Timestamp(a) - pd.Timedelta(days=365)).date().isoformat()
        f["acq"] = f["sid"].isin(acq.loc[(acq["d"] >= lo_d) & (acq["d"] < a), "sid"]).astype(float)
        hi_d = (pd.Timestamp(a) + pd.Timedelta(days=365)).date().isoformat()
        f["artifact"] = f["sid"].isin(divs[(divs["ex_date"] > a) & (divs["ex_date"] <= hi_d)]["sid"])
        f = f.merge(turn_at(q, a), on="sid", how="left")
        rows.append(f.assign(snapshot_date=a))
    feat = pd.concat(rows, ignore_index=True)
    d = lab[lab["cap_tier"].isin(TIERS)].merge(feat, on=["sid", "snapshot_date"], how="left")
    d = d.merge(ann_at, on=["sid", "snapshot_date"], how="left")
    d = d.merge(st[["sid", "name", "sector", "industry"]], on="sid", how="left")
    pats = SCREEN.get("trust_exclusion_patterns", [])
    trust = d["name"].str.contains("|".join(pats), case=False, regex=True, na=False) if pats else False
    for c in ("artifact", "delev", "turn_p", "turn_c"):
        d[c] = d[c].astype("boolean").fillna(False).astype(bool)
    d["universe"] = ~d["sector"].eq("Financials") & ~trust & (d["adtv"] >= FLOOR_INR)
    d["ex"] = d["fwd_252"] - d.groupby(["snapshot_date", "cap_tier"])["fwd_252"].transform("median")
    d["turn"] = d["turn_p"] | d["turn_c"]
    d["mom_ok"] = d["mom_3m"] > 0
    base = d["universe"] & ~d["artifact"]
    for c in INPUTS:
        d[f"p_{c}"] = d[c].where(d["universe"]).groupby([d["snapshot_date"], d["cap_tier"]]).rank(pct=True)
    d["score"] = d[[f"p_{c}" for c in INPUTS]].fillna(0.5).mean(axis=1)
    acq1 = d["acq"] > 0
    d["gate"] = base & d["delev"] & d["turn"] & d["mom_ok"]
    d["g_acq_or"] = base & (d["delev"] | acq1) & d["turn"] & d["mom_ok"]
    d["g_acq_and"] = d["gate"] & acq1
    d["g_no_price"] = base & d["delev"] & d["turn"]
    d["g_delev_only"] = base & d["delev"] & d["mom_ok"]
    d["g_turn_only"] = base & d["turn"] & d["mom_ok"]
    d["g_profit_leg"] = base & d["delev"] & d["turn_p"] & d["mom_ok"]
    d["g_icr_leg"] = base & d["delev"] & d["turn_c"] & d["mom_ok"]
    return d


GATES = ("gate", "g_acq_or", "g_acq_and", "g_no_price", "g_delev_only", "g_turn_only", "g_profit_leg", "g_icr_leg")


def scores(d):
    """Gated score columns: NaN = not eligible (not bought / sold at the next review)."""
    return pd.DataFrame({("turnaround" if g == "gate" else g[2:]): d["score"].where(d[g]) for g in GATES})


def passers(d):
    c = d.groupby(["snapshot_date", "cap_tier"])[list(GATES)].sum().unstack("cap_tier")
    c.columns = [f"{g}_{t}" for g, t in c.columns]
    return c.reset_index()


# ───────────────────────── asymmetry ─────────────────────────

def asymmetry(d, S):
    rows = []
    span = (d["snapshot_date"] >= ASYM_FROM) & (d["snapshot_date"] <= ASYM_TO)
    periods = {"2019-12…2025-09": lambda x: x == x, "2019-22": lambda x: x < "2023-01-01",
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
                bu = b[b["universe"]]
                r = dict(tier=tier, score=col, period=per, anchors=t["snapshot_date"].nunique(),
                         names_per_anchor=round(len(t) / max(t["snapshot_date"].nunique(), 1), 1),
                         n_obs=len(tv), with_outcome=round(len(tv) / len(t), 3),
                         p_double=tv["fwd_252"].ge(1.0).mean(), base_double=b["fwd_252"].ge(1.0).mean(),
                         p_halve=tv["fwd_252"].le(-0.5).mean(), base_halve=b["fwd_252"].le(-0.5).mean(),
                         median_ex=tv["ex"].median(), mean_ex=tv["ex"].mean(),
                         univ_base_double=bu["fwd_252"].ge(1.0).mean(), univ_base_halve=bu["fwd_252"].le(-0.5).mean())
                r["lift_double"] = r["p_double"] / r["base_double"] if r["base_double"] else np.nan
                r["passes"] = bool(r["p_double"] >= 2 * r["base_double"] and r["p_halve"] <= r["base_halve"]
                                   and r["median_ex"] >= 0)
                rows.append(r)
    return pd.DataFrame(rows)


# ───────────────────────── book ─────────────────────────

def grid():
    return [dict(method="turnaround", reb="M", N=TOP, k=k, score="raw", min_hold=mh, defer=False, block="turn")
            for k in (1.5, 2, 3) for mh in (0, 1)]


PRIMARY = dict(method="turnaround", reb="M", N=TOP, k=2, score="raw", min_hold=0, defer=False, block="turn")


def books(d, S):
    import tools.lh_book as B
    from tools.lh_luck import n_effective, pbo, sharpe

    sc = d[["sid", "snapshot_date", "cap_tier"]].assign(method="turnaround", score=S["turnaround"]).dropna(subset=["score"])
    all_anchors = sorted(d["snapshot_date"].unique())
    gap = sorted(set(all_anchors) - set(sc["snapshot_date"]))
    if gap:   # placeholder keeps the return chain (LARGE is not simulated; see docstring)
        sc = pd.concat([sc, pd.DataFrame({"sid": PLACEHOLDER, "snapshot_date": gap, "cap_tier": "LARGE",
                                          "method": "turnaround", "score": 0.0})], ignore_index=True)
    sc["pct_rank"] = sc.groupby(["snapshot_date", "cap_tier"])["score"].rank(pct=True)
    sc["oos"] = True
    starts = [a for a in all_anchors if a >= START_FROM][:12]
    rows, first = [], {}
    for st in starts:
        w = sc[sc["snapshot_date"] >= st]
        dd = V2 / "win_turnaround"
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
                                                      "no_signal_exits", "positions", "n_months",
                                                      "months_without_scores")}))
                if st == starts[0]:
                    a_, b_ = m["atlv"].to_numpy(float), m["bench"].to_numpy(float)
                    x = pd.Series((a_[1:] / a_[:-1]) - (b_[1:] / b_[:-1]), index=m["entry"].iloc[1:].values)
                    first[(tier, name)] = dict(x=x, rb=pd.Series(a_[1:] / a_[:-1], index=x.index),
                                               rx=pd.Series(b_[1:] / b_[:-1], index=x.index))
        print(f"start {st} done", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(V2 / "turnaround_books.csv", index=False)

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
        cal = {int(y): round(float(rb[yrs == y].prod() / rx[yrs == y].prod() - 1), 4) for y in range(2020, 2026)}
        t_h = B.haircut_t(r0["t_nw"], int(r0["n_months"]), len(grid()))
        beat = int((prim["excess_cagr"] > 0).sum())
        g = dict(t_nw=r0["t_nw"], t_haircut=t_h, dsr=round(dsr, 3), n_eff=round(ne, 2), pbo=p["pbo"],
                 calendar_excess=cal, years_beating_2021_25=sum(cal[y] > 0 for y in range(2021, 2026)),
                 starts_beating=f"{beat}/{len(prim)}", median_excess_across_starts=float(prim["excess_cagr"].median()),
                 min_excess_across_starts=float(prim["excess_cagr"].min()), median_t_across_starts=float(prim["t_nw"].median()),
                 worst_12m=r0["worst_12m_excess"], excess_cagr_first_start=r0["excess_cagr"],
                 turnover_pa=r0["turnover_pa"], avg_cash_share=r0["avg_cash_share"])
        A = (t_h or 0) >= 2.0 and dsr >= 0.95 and p["pbo"] <= 0.20
        Bg = (r0["t_nw"] >= 1.5 and (dsr >= 0.90 or p["pbo"] <= 0.30) and g["years_beating_2021_25"] >= 3
              and beat >= 10 and r0["worst_12m_excess"] >= -0.15)
        g["grade"] = "A" if A else ("B" if Bg else "C")
        grades[tier] = g
    return res, grades


def latest(d, S):
    a = d["snapshot_date"].max()
    t = d[d["snapshot_date"] == a].assign(s=S["turnaround"]).dropna(subset=["s"])
    t = t.sort_values("s", ascending=False).groupby("cap_tier").head(TOP)
    return t[["cap_tier", "sid", "name", "industry", "s", "da", "delev_amt", "turn_p", "turn_c", "acq", "mom_3m", "adtv"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("part", nargs="?", default="all", choices=["smoke", "asym", "book", "all"])
    part = ap.parse_args().part
    pd.set_option("display.width", 240)
    V2.mkdir(parents=True, exist_ok=True)
    if part == "smoke":
        d = build(only=[0, 30, 60])
        print(passers(d).to_string(index=False))
        print(d[d["gate"]][["snapshot_date", "cap_tier", "sid", "name", "da", "delev_amt", "turn_p", "turn_c", "acq",
                            "mom_3m"]].head(15).to_string(index=False))
        return
    d = build()
    S = scores(d)
    keep = ["sid", "snapshot_date", "cap_tier", "name", "sector", "fwd_252", "ex", "artifact", "universe", "adtv",
            "mom_3m", "acq", "da", "delev", "delev_amt", "turn_p", "turn_c", "score", *GATES]
    d[keep].to_parquet(V2 / "turnaround_panel.parquet", index=False)
    pc = passers(d)
    pc.to_csv(V2 / "turnaround_passers.csv", index=False)
    med = {t: float(pc[f"gate_{t}"].median()) for t in TIERS}
    mean = {t: round(float(pc[f"gate_{t}"].mean()), 1) for t in TIERS}
    print(f"panel {len(d):,} rows; gated names per anchor median {med}, mean {mean}; anchors {pc['snapshot_date'].min()}"
          f" → {pc['snapshot_date'].max()} ({len(pc)}); anchors with zero SMALL passers {int((pc['gate_SMALL'] == 0).sum())}")
    out = {"passers_median": med, "passers_mean": mean, "anchors": len(pc)}
    if part in ("asym", "all"):
        A = asymmetry(d, S)
        A.to_csv(V2 / "turnaround_asymmetry.csv", index=False)
        print("\nASYMMETRY (top 20 per anchor; base = the whole tier at the same anchors):")
        print(A.round(3).to_string(index=False))
        out["asymmetry"] = {t: A[(A["tier"] == t) & (A["score"] == "turnaround") & (A["period"] == "2019-12…2025-09")]
                            .iloc[0][["p_double", "base_double", "p_halve", "base_halve", "median_ex", "lift_double",
                                      "names_per_anchor", "n_obs", "passes"]].to_dict() for t in TIERS}
        lt = latest(d, S)
        lt.to_csv(V2 / "turnaround_latest.csv", index=False)
        print(f"\nTODAY's gated top {TOP} ({d['snapshot_date'].max()}):\n", lt.round(3).to_string(index=False))
    if part in ("book", "all"):
        res, grades = books(d, S)
        print("\nBOOKS:\n", res.round(4).to_string(index=False))
        print("\nGRADES:", json.dumps(grades, indent=1, default=str))
        out["grades"] = grades
    if part == "all":
        s_ok = bool(out["asymmetry"]["SMALL"]["passes"])
        s_g = out["grades"]["SMALL"]["grade"]
        shape = med["SMALL"] >= TOP
        out["book_shape_ok"] = shape
        out["decision"] = ("turnaround sleeve candidate (paper; Amit to approve)" if s_g in ("A", "B") and s_ok and shape
                           else "turnaround watch-list, not a book" if s_ok
                           else "no turnaround sleeve" + (" (near-miss: grade B without asymmetry)" if s_g in ("A", "B") else ""))
        print("\nDECISION (SMALL):", out["decision"])
    (V2 / f"turnaround_summary_{part}.json").write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
