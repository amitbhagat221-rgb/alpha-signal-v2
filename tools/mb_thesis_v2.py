"""
Plan 0026 phase 1b — test everything the v1 thesis left out (READ-ONLY on the DB; writes data/lh/v2/mb2_*).

Amit 2026-10-15: "test everything, we don't want to go half baked". v1 = tools/mb_thesis.py (ADR 0075):
loose pond, equal-weight percentiles of smallness, cheapness, price, business, tailwind; grade C.

PRE-REGISTRATION (written 2026-10-15 BEFORE any run of this tool; nothing below changes after the first
run — a bug found by a run is fixed in code and logged here as a dated note, the rules and bars stay).

Harness: v1's arm-B panel (data/lh/v2/mb_thesis_panel.parquet: today's universe, monthly anchors =
first session of each month, v1 pond + parts from mb_thesis.score) and v1's labels (y3, y5, halve3).
Every book here uses REALISTIC COSTS (C7): one-way cost per trade = tools.lh_costs.one_way_cost_bps(
ADTV at the anchor, price, trade value, "SMALL", year), trade value = ₹30 lakh book / N names; tax 12.5 %
on positive realised gains at a sale (as v1). v1 is re-run under the same costs as the comparison.

Candidates
  C1 new listings: from 2020, the 30-name book = top 25 thesis names + top 5 of plan 0025 6.2's
     new-listing set by its score (data/lh/v2/newlist_panel.parquet, in_set, at the latest newlist
     anchor <= the book's anchor). Names already held are not bought twice.
  C2 regime (benchmark NIFTY SMALLCAP 250; bear = close <= 0.80 × its 252-session high, ADR 0040's line):
     R1 at a rebalance month in a bear, do not rebalance; retry monthly, rebalance when the bear ends.
     R2 at any month-start in a bear, hold the index instead of the book; buy the thesis book again at
        the first month-start after the bear ends.
  C3 superinvestor entry: a pre-registered list of investors widely known for Indian small caps BEFORE
     2018 (list SI_NAMES below; hindsight risk: they are famous partly for past winners, so only
     entries filed after 2016 count and the list is frozen here). si_entry = 1 if a listed investor
     holds >= 1 % in the stock's latest shareholding filing knowable at the anchor (filed_at <= anchor)
     and did not in that stock's previous filing, and the latest filing is <= 200 days old; else 0.
     Tested (a) as a sixth part, (b) alone: T1 lift of si_entry names vs the pond.
  C4 extra SMALL signals, each tried as a sixth part (percentile within the pond, sign as stated):
     announcement_car (+), delivery_anomaly_z (+), cf_accruals (−), retail holder growth (−; n_retail
     latest filing / previous filing − 1, filed_at PIT), q_margin_chg (+, added inside the business
     part as a third input). PIT-panel inputs (daily_snapshots_pit: latest snapshot <= anchor) start
     2019-12/2020-09, so C4 runs in window W2020.
  C5 ablation: v1 minus one part (5 variants) and each part alone (5 variants).
  C6 holding rules: H2 rebalance every 24 months; H3 band: at each annual rebalance keep a holding
     while it ranks in the pond's top 90, fill the book back to N from the top; H4 conviction: hold
     until ADR 0040's REVIEW signature (drawdown <= −50 % from the high since entry, >= 6 month-starts
     more than 20 % below that high, 6-month return below the benchmark's and its industry's pond
     median 6-month return < 0, unless the benchmark itself is a bear), checked monthly; the sale
     proceeds wait in cash and are re-invested in the top-ranked names not held at the next annual
     rebalance (which otherwise sells nothing).
  C7 costs and liquidity floor: realistic costs everywhere (above); the floor ADTV >= ₹0.5 / 1 / 2 Cr.
  C8 policy: sector_policy_pit.policy_score (sector of the stock, latest month-end <= anchor) averaged
     into the tailwind part with the industry momentum (from 2020-05).
  C9 overlap: share of the final book's names that are in the SMALL top 20 of each method in
     data/lh/oos_scores.parquet at the same anchor (2022-06+), reported, not deciding.

Windows: W_full = 12 staggered starts from the arm's first scored month (2016), run to today (C2, C3,
  C5, C6, C7); W2020 = 12 starts 2020-01 … 2020-12 (C1, C4, C8), each with v1 re-run on the same window.
  T1 (October anchors with a 3-year label) as v1 for every score variant.

Decision rules (per candidate vs v1 on the same window, 30-name book):
  Score variants (C3a, C4, C5, C8): ACCEPT (or, for C5 drop-one, DROP the part) if all hold:
    median excess / yr improves by >= 1.0 point; the excess improves in both halves of the window's
    calendar years (W_full 2016–2020 | 2021–2026, W2020 2020–2022 | 2023–2026; mean calendar excess);
    T1 3x-in-3y lift falls by <= 0.10; halving lift rises by <= 0.10; worst 12-month excess falls by
    <= 5 points.
  Book rules (C1, C2, C6, C7 floor): ACCEPT if the median excess falls by <= 1.0 point in each half
    AND the worst 12-month excess improves by >= 5 points; among several accepted rules of one kind
    the one with the best worst-12-month excess is kept. A rule may also be accepted on the score
    rule's terms (>= 1 point better in both halves, worst not > 5 points worse).
  v2 = v1 + every accepted part / rule − every dropped part. If nothing is accepted, v2 = v1.
Final: v2 evaluated once, W_full where its inputs allow (else W2020 and said so), with T1, T2 and the
  ADR 0073 grade, plus the deflated Sharpe ratio over every variant tried here (N = all score and book
  variants, the variants' monthly excess Sharpe ratios) and PBO (CSCV, S = 8 blocks) over the same set.

Bug fix 2026-10-15 during the first run (code only): T1 divided by max(pond rate, 1e-9), so an anchor
  where no pond stock tripled (Oct 2016) counted as lift 0 instead of being skipped (as v1 does). It
  lowered every variant's T1 mean equally, so the run's accept/drop deltas are unchanged; the T1 levels
  reported in the study are the corrected ones.

Verdict note 2026-10-15 (after the run, data check, not a rule change): C8 passed the score rule
  (+3.7 points, worst −23 % vs −32 %), but its input fails the point-in-time requirement every factor
  has (CLAUDE.md, ADR 0045): `policy_events` is a 28-row list curated in 2026 with magnitudes set in
  hindsight, some rows are outcomes rather than announcements ("record order book", "railway capex
  surge"), and no event has been added since 2025-04. C8 is therefore disqualified and v2 = v1.
  The 'v2 FINAL' row in mb2_results.csv is v1 + C8 and is void.

Usage:  python -m tools.mb_thesis_v2
"""

import itertools
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools import lh_costs  # noqa: E402
from tools import mb_thesis as v1  # noqa: E402
from tools.lh_price_history import load  # noqa: E402
from tools.lh_quarterly_nse import asof as q_asof, history as q_history  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
V2 = PROJECT_ROOT / "data" / "lh" / "v2"
BOOK_INR = 30e5
CR = 1e7
SI_NAMES = {   # investor → upper-case substrings matched against holder_name (frozen 2026-10-15)
    "Ashish Kacholia": ["ASHISH KACHOLIA", "ASHISH RAMESHCHANDRA KACHOLIA", "BENGAL FINANCE & INVESTMENT"],
    "Vijay Kedia": ["VIJAY KISHANLAL KEDIA", "VIJAY KEDIA", "KEDIA SECURITIES"],
    "Dolly Khanna": ["DOLLY KHANNA", "RAJIV KHANNA"],
    "Mukul Agrawal": ["MUKUL MAHAVIR AGRAWAL", "MUKUL AGRAWAL", "PARAM CAPITAL"],
    "Porinju Veliyath": ["PORINJU", "EQUITY INTELLIGENCE INDIA"],
    "Rakesh / Rekha Jhunjhunwala": ["RAKESH RADHEYSHYAM JHUNJHUNWALA", "REKHA RAKESH JHUNJHUNWALA",
                                    "RAKESH JHUNJHUNWALA", "REKHA JHUNJHUNWALA", "RARE INVESTMENTS"],
    "Radhakishan Damani": ["RADHAKISHAN SHIVKISHAN DAMANI", "RADHAKISHAN DAMANI", "DERIVE TRADING",
                           "BRIGHT STAR INVESTMENTS"],
    "Ramesh Damani": ["RAMESH SHRICHAND DAMANI", "RAMESH DAMANI"],
    "Anil Kumar Goel": ["ANIL KUMAR GOEL", "SEEMA GOEL"],
    "Ashish Dhawan": ["ASHISH DHAWAN"],
    "Nemish Shah": ["NEMISH S SHAH", "NEMISH SHAH", "ENAM SECURITIES"],
    "Akash Bhanshali": ["AKASH BHANSHALI", "AKASH PRAKASH BHANSHALI"],
    "Satpal Khattar": ["SATPAL KHATTAR", "KHATTAR HOLDINGS"],
    "Sunil Singhania": ["ABAKKUS", "SUNIL SINGHANIA"],
    "Madhusudan Kela": ["MADHUSUDAN KELA", "MADHURI MADHUSUDAN KELA", "SINGULARITY"],
}
PARTS = v1.PARTS
PART_SIGN = {"announcement_car": 1, "delivery_anomaly_z": 1, "cf_accruals": -1, "retail_growth": -1,
             "si_entry": 1}


def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def pct(s):
    return s.rank(pct=True)


# ─────────────────────────────── extra features ───────────────────────────────

def asof_join(df, feat, cols, key="sid", date_col="snapshot_date"):
    """Latest feat row per sid with date <= anchor."""
    feat = feat.sort_values(date_col)
    left = df[["id", "anchor"]].assign(_d=pd.to_datetime(df["anchor"])).sort_values("_d")
    right = feat.rename(columns={key: "id"}).assign(_d=pd.to_datetime(feat[date_col]))[["id", "_d"] + cols]
    right = right.sort_values("_d")
    m = pd.merge_asof(left, right, on="_d", by="id", direction="backward")
    return m.set_index(left.index)[cols]


def superinvestors(conn):
    h = pd.read_sql("SELECT sid, end_date, filed_at, upper(holder_name) AS n, pct FROM shareholding_holders "
                    "WHERE end_date >= '2015-01-01' AND pct >= 1", conn)
    def who(n):
        for inv, pats in SI_NAMES.items():
            if any(p in n for p in pats):
                return inv
        return None
    names = pd.Series(h["n"].unique())
    m = dict(zip(names, names.map(who)))
    h["inv"] = h["n"].map(m)
    filings = pd.read_sql("SELECT DISTINCT sid, end_date, filed_at FROM shareholding_categories "
                          "WHERE end_date >= '2015-01-01'", conn)
    filings = filings.sort_values(["sid", "end_date", "filed_at"]).drop_duplicates(["sid", "end_date"], keep="first")
    held = h.dropna(subset=["inv"]).groupby(["sid", "end_date"])["inv"].apply(set)
    filings["invs"] = [held.get((s, e), set()) for s, e in zip(filings["sid"], filings["end_date"])]
    filings["prev"] = filings.groupby("sid")["invs"].shift(1)
    filings["new"] = [len(a - (b if isinstance(b, set) else set())) > 0 if isinstance(b, set) else False
                      for a, b in zip(filings["invs"], filings["prev"])]
    filings["si_present"] = filings["invs"].map(len) > 0
    filings["snapshot_date"] = filings["filed_at"].str[:10]
    filings["filed"] = pd.to_datetime(filings["snapshot_date"], errors="coerce")
    print(f"superinvestors: {h['inv'].notna().sum():,} holding rows matched, "
          f"{filings['new'].sum():,} entries over {filings.loc[filings['new'], 'sid'].nunique()} stocks; by investor:",
          h.dropna(subset=["inv"]).groupby("inv")["sid"].nunique().to_dict(), flush=True)
    return filings.dropna(subset=["filed"])[["sid", "snapshot_date", "filed", "new", "si_present"]]


def retail_growth(conn):
    c = pd.read_sql("SELECT sid, end_date, filed_at, n_retail FROM shareholding_categories WHERE n_retail > 0", conn)
    c = c.sort_values(["sid", "end_date", "filed_at"]).drop_duplicates(["sid", "end_date"], keep="first")
    c["retail_growth"] = c.groupby("sid")["n_retail"].pct_change(fill_method=None)
    c["snapshot_date"] = c["filed_at"].str[:10]
    return c[["sid", "snapshot_date", "retail_growth"]]


def add_features(df):
    conn = ro()
    pit = pd.read_sql("SELECT sid, snapshot_date, announcement_car, delivery_anomaly_z, cf_accruals "
                      "FROM daily_snapshots_pit WHERE snapshot_date >= '2019-12-01'", conn)
    si = superinvestors(conn)
    rg = retail_growth(conn)
    pol = pd.read_sql("SELECT sector, snapshot_date, policy_score FROM sector_policy_pit", conn)
    qh = q_history(conn)
    conn.close()
    df = df.copy()
    df[["announcement_car", "delivery_anomaly_z", "cf_accruals"]] = asof_join(
        df, pit, ["announcement_car", "delivery_anomaly_z", "cf_accruals"]).values
    s = asof_join(df, si, ["new", "filed"])
    fresh = (pd.to_datetime(df["anchor"]) - s["filed"]).dt.days <= 200
    df["si_entry"] = (s["new"].astype("boolean").fillna(False).astype(bool) & fresh.fillna(False)).astype(float)
    df["retail_growth"] = asof_join(df, rg, ["retail_growth"])["retail_growth"].values
    # sector policy: latest month-end <= anchor, by the stock's sector
    pol["_d"] = pd.to_datetime(pol["snapshot_date"])
    df["_d"] = pd.to_datetime(df["anchor"])
    left = df[["sector", "_d"]].reset_index().dropna(subset=["sector"]).sort_values("_d")
    m = pd.merge_asof(left, pol.sort_values("_d")[["sector", "_d", "policy_score"]], on="_d", by="sector",
                      direction="backward").set_index("index")
    df["policy_score"] = m["policy_score"].reindex(df.index)
    anchors = sorted(df.loc[df["anchor"] >= "2019-01-01", "anchor"].unique())
    q = q_asof(qh, anchors)[["sid", "snapshot_date", "q_margin_chg"]].rename(columns={"sid": "id", "snapshot_date": "anchor"})
    df = df.merge(q, on=["id", "anchor"], how="left")
    return df.drop(columns=["_d"])


# ─────────────────────────────── scoring variants ───────────────────────────────

def variant_score(g, parts, extras=(), margin=False, policy=False):
    """Score one anchor's pond: mean of the chosen v1 parts (+ an extra sixth part)."""
    P = pd.DataFrame(index=g.index)
    for p in parts:
        P[p] = g[p]
    if margin and "business" in parts:
        b = pd.concat([pct(g["q_ebitda_chg"]), pct(g["q_rev_yoy"]), pct(g["q_margin_chg"])], axis=1).mean(axis=1)
        P["business"] = b.where(b.notna(), g["business"])
    if policy and "tailwind" in parts:
        t = pd.concat([pct(g["tailwind"]), pct(g["policy_score"])], axis=1).mean(axis=1)
        P["tailwind"] = t.where(t.notna(), g["tailwind"])
    for extra in extras:
        x = g[extra] * PART_SIGN.get(extra, 1)
        P[extra] = pct(x) if x.notna().sum() >= 20 else np.nan
    rm = P.mean(axis=1)
    P = P.apply(lambda c: c.fillna(rm))
    return P.mean(axis=1)


def scored(df, name, **kw):
    out = pd.Series(np.nan, index=df.index)
    pond = df["pond_b"].fillna(False).astype(bool) & df["score_b"].notna()
    for a, g in df[pond].groupby("anchor"):
        out.loc[g.index] = variant_score(g, **kw).values
    return out.rename(name)


# ─────────────────────────────── book simulator ───────────────────────────────

def bench_series():
    conn = ro()
    b = pd.read_sql("SELECT trade_date AS date, close FROM nse_index_history WHERE index_symbol = ?", conn,
                    params=[v1.BENCH]).set_index("date")["close"]
    conn.close()
    return b


def is_bear(bench_daily, a):
    w = bench_daily.loc[:a].iloc[-252:]
    return len(w) >= 200 and w.iloc[-1] <= 0.80 * w.max()


_COST_MODEL = lh_costs._model()
lh_costs._model = lambda: _COST_MODEL          # read costs.json once, not per trade


def cost_frac(adtv, price, trade_inr, year, stress=False):
    if trade_inr <= 0:
        return 0.0
    try:
        return lh_costs.one_way_cost_bps(float(adtv) if pd.notna(adtv) else None, float(price), trade_inr,
                                         "SMALL", year=int(year), stress=stress) / 1e4
    except Exception:
        return 0.0031


def simulate(df, P, sc, n=30, start_from=None, rule="annual", regime=None, floor=0.5 * CR,
             newlist=None, flat_cost=False, bench_daily=None, PF=None, select=None, stress=False):
    """Monthly-marked books from 12 staggered starts. Returns {start: Series(value)} (value 1.0 at start).
    select(g, ranked, n) → target ids overrides the top-n pick (tools.mb_funnel); stress doubles spread and
    impact (tools.lh_costs). Both default off, so tools.mb_thesis_v2's own run is unchanged."""
    dates = P.index
    PF = P.ffill() if PF is None else PF
    months = v1.month_firsts(dates, "2016-01-01")
    D = df[df["pond_b"].fillna(False).astype(bool) & df[sc].notna() & (df["adtv"] >= floor)]
    by = {a: g.set_index("id") for a, g in D.groupby("anchor")}
    scored_m = [a for a in months if a in by and (start_from is None or a >= start_from)]
    months = months[months.index(scored_m[0]):]
    adtv_all = df.set_index(["anchor", "id"])["adtv"].to_dict()
    industry = df.dropna(subset=["industry"]).drop_duplicates("id", keep="last").set_index("id")["industry"].to_dict()
    ind_mom = df.groupby(["anchor", "industry"])["mom_6m"].median().to_dict()
    bclose = {a: float(bench_daily.loc[:a].iloc[-1]) for a in months}
    bear_m = {a: is_bear(bench_daily, a) for a in months}
    b6 = {a: (float(bench_daily.loc[:a].iloc[-1] / bench_daily.loc[:a].iloc[-127] - 1)
              if len(bench_daily.loc[:a]) > 127 else 0.0) for a in months}
    pos = {d: k for k, d in enumerate(dates)}

    def price(a, i):
        return float(PF.at[a, i]) if i in PF.columns else np.nan

    def cost(a, i, p, inr):
        if flat_cost:
            return 0.0031
        return cost_frac(adtv_all.get((a, i)), p, inr, a[:4], stress)

    series = {}
    for s in range(12):
        cash, hold, value = 1.0, {}, {}          # hold: id → [units, avg cost, peak, months_under]
        idx_units, pending, started = 0.0, True, False
        rebal_months = set(months[s::24] if rule == "h24" else months[s::12])
        for a in months[s:]:
            for i in hold:
                p = price(a, i)
                hold[i][2] = max(hold[i][2], p)
                hold[i][3] = hold[i][3] + 1 if p < 0.8 * hold[i][2] else 0
            bear = bear_m[a]
            if a in rebal_months:
                pending = True
            # R2: hold the index while the benchmark is in a bear
            if regime == "R2" and bear:
                if hold or cash > 0:
                    for i in list(hold):
                        p = price(a, i)
                        v = hold[i][0] * p
                        cash += v * (1 - cost(a, i, p, v * BOOK_INR)) - max(hold[i][0] * (p - hold[i][1]), 0) * v1.LTCG
                    hold = {}
                    idx_units += cash / bclose[a]
                    cash = 0.0
                    pending = True
                value[a] = idx_units * bclose[a]
                continue
            if idx_units:
                cash += idx_units * bclose[a]
                idx_units = 0.0
            # H4: monthly REVIEW exits (ADR 0040 signature)
            if rule == "h4" and hold and not bear:
                j = pos[a]
                for i in list(hold):
                    p = price(a, i)
                    if j < 127:
                        continue
                    r6 = p / float(PF[i].iloc[j - 126]) - 1
                    im = ind_mom.get((a, industry.get(i)), 0.0)
                    if p / hold[i][2] - 1 <= -0.5 and hold[i][3] >= 6 and r6 < b6[a] and im < 0:
                        v = hold[i][0] * p
                        cash += v * (1 - cost(a, i, p, v * BOOK_INR)) - max(hold[i][0] * (p - hold[i][1]), 0) * v1.LTCG
                        del hold[i]
            do_rebal = pending and a in by and not (regime == "R1" and bear and started)
            if do_rebal:
                g = by[a]
                ranked = [i for i in g[sc].sort_values(ascending=False).index if i in PF.columns]
                if newlist is not None:
                    nl = [x for x in newlist.get(a, []) if x in PF.columns and x not in ranked[:n - 5]][:5]
                    target = ranked[:n - len(nl)] + nl
                elif select is not None:
                    target = select(g, ranked, n)
                else:
                    target = ranked[:n]
                if rule == "h3":
                    keep = [i for i in hold if i in ranked[:3 * n]]
                    target = keep + [i for i in ranked if i not in keep][:n - len(keep)]
                if rule == "h4" and started:
                    target = list(hold) + [i for i in ranked if i not in hold][:max(n - len(hold), 0)]
                nav = cash + sum(hold[i][0] * price(a, i) for i in hold)
                tgt = nav / max(len(target), 1)
                for i in list(hold):                                   # sells / trims
                    if rule == "h4" and i in target:
                        continue
                    p = price(a, i)
                    cur = hold[i][0] * p
                    want = tgt if i in target else 0.0
                    sell = cur - want
                    if sell <= 1e-12:
                        continue
                    frac = sell / cur
                    gain = hold[i][0] * frac * (p - hold[i][1])
                    cash += sell * (1 - cost(a, i, p, sell * BOOK_INR)) - max(gain, 0) * v1.LTCG
                    hold[i][0] *= (1 - frac)
                    if want == 0:
                        del hold[i]
                for i in target:                                       # buys
                    p = price(a, i)
                    if not np.isfinite(p) or p <= 0:
                        continue
                    cur = hold[i][0] * p if i in hold else 0.0
                    buy = min(max(tgt - cur, 0.0), cash)
                    if buy <= 1e-12:
                        continue
                    units = buy * (1 - cost(a, i, p, buy * BOOK_INR)) / p
                    if i in hold:
                        tot = hold[i][0] + units
                        hold[i][1] = (hold[i][1] * hold[i][0] + p * units) / tot
                        hold[i][0] = tot
                    else:
                        hold[i] = [units, p, p, 0]
                    cash -= buy
                pending, started = False, True
            value[a] = cash + sum(hold[i][0] * price(a, i) for i in hold)
        series[months[s]] = pd.Series(value)
    return series


def evaluate(series, bench, halves):
    rows, cal_all, monthly_ex = [], [], []
    for start, v in series.items():
        bv = bench.reindex(v.index).ffill()
        bv = bv / bv.iloc[0]
        vv = v / v.iloc[0]
        yrs = len(v) / 12
        cagr, bcagr = vv.iloc[-1] ** (1 / yrs) - 1, bv.iloc[-1] ** (1 / yrs) - 1
        r12 = (vv.pct_change(12) - bv.pct_change(12)).dropna()
        ann = (vv.iloc[::12].pct_change() - bv.iloc[::12].pct_change()).dropna()
        yi = pd.to_datetime(vv.index).year
        cal = vv.groupby(yi).last() / vv.groupby(yi).first() - (bv.groupby(yi).last() / bv.groupby(yi).first())
        rows.append({"start": start, "excess_pa": cagr - bcagr, "cagr": cagr, "worst": r12.min(),
                     "t": ann.mean() / (ann.std() / math.sqrt(len(ann))) if len(ann) > 2 else np.nan})
        cal_all.append(cal)
        monthly_ex.append(vv.pct_change() - bv.pct_change())
    r = pd.DataFrame(rows)
    cal = pd.concat(cal_all, axis=1).mean(axis=1)
    h1 = cal[(cal.index >= halves[0][0]) & (cal.index <= halves[0][1])].mean()
    h2 = cal[(cal.index >= halves[1][0]) & (cal.index <= halves[1][1])].mean()
    last5 = cal.iloc[-6:-1] if len(cal) > 5 else cal
    me = pd.concat(monthly_ex, axis=1).mean(axis=1).dropna()
    s = {"excess": float(r["excess_pa"].median()), "cagr": float(r["cagr"].median()), "t": float(r["t"].median()),
         "worst": float(r["worst"].min()), "starts": int((r["excess_pa"] > 0).sum()), "last5": int((last5 > 0).sum()),
         "half1": float(h1), "half2": float(h2)}
    s["grade"] = "B" if (s["t"] >= 1.5 and s["last5"] >= 3 and s["starts"] >= 10 and s["worst"] >= -0.15) else "C"
    return s, me


def t1(df, sc):
    rows = []
    for a in sorted(x for x in df["anchor"].unique() if x[5:7] == "10"):
        g = df[(df["anchor"] == a) & df["pond_b"].fillna(False).astype(bool) & df[sc].notna()]
        if len(g) < 100 or g["y3"].isna().all():
            continue
        top = g.nlargest(30, sc)
        b3, bh = (g["y3"] >= 3).mean(), (g["y3"] <= 0.5).mean()
        rows.append({"anchor": a, "l3": (top["y3"] >= 3).mean() / b3 if b3 > 0 else np.nan,
                     "lh": (top["y3"] <= 0.5).mean() / bh if bh > 0 else np.nan})
    t = pd.DataFrame(rows)
    return {"t1_lift3": float(t["l3"].mean()) if len(t) else np.nan,
            "t1_halve": float(t["lh"].mean()) if len(t) else np.nan, "t1_n": len(t)}


def dsr(sr_best, srs, T):
    srs = np.asarray([x for x in srs if np.isfinite(x)])
    N = len(srs)
    if N < 2:
        return np.nan
    emc = 0.5772156649
    v = srs.var(ddof=1)
    sr0 = math.sqrt(v) * ((1 - emc) * stats.norm.ppf(1 - 1 / N) + emc * stats.norm.ppf(1 - 1 / (N * math.e)))
    return float(stats.norm.cdf((sr_best - sr0) * math.sqrt(T - 1)))


def pbo(M, S=8):
    """CSCV: M = T × N matrix of monthly excess returns per variant."""
    M = M.dropna()
    T = len(M) - len(M) % S
    blocks = np.array_split(np.arange(T), S)
    logits = []
    for comb in itertools.combinations(range(S), S // 2):
        ins = np.concatenate([blocks[i] for i in comb])
        oos = np.concatenate([blocks[i] for i in range(S) if i not in comb])
        sr_in = M.iloc[ins].mean() / M.iloc[ins].std()
        sr_out = M.iloc[oos].mean() / M.iloc[oos].std()
        best = sr_in.idxmax()
        w = (sr_out.rank(pct=True)[best])
        w = min(max(w, 1e-6), 1 - 1e-6)
        logits.append(math.log(w / (1 - w)))
    return float(np.mean(np.array(logits) <= 0))


def main():
    df = pd.read_parquet(V2 / "mb_thesis_panel.parquet")
    P, _, _ = load()
    PF = P.ffill()
    df = v1.score(df)
    df = add_features(df)
    bench = bench_series()
    HALVES = {"full": ((2016, 2020), (2021, 2026)), "w2020": ((2020, 2022), (2023, 2026))}
    res, monthly, spec, cols = {}, {}, {}, {}

    nl = pd.read_parquet(V2 / "newlist_panel.parquet")
    nl = nl[nl["in_set"].astype(bool) & nl["score"].notna()]
    nl_dates = sorted(nl["snapshot_date"].unique())
    nl_by = {}
    for a in v1.month_firsts(P.index, "2019-12-01"):
        prior = [d for d in nl_dates if d <= a]
        if prior:
            nl_by[a] = list(nl[nl["snapshot_date"] == prior[-1]].sort_values("score", ascending=False)["sid"])

    def run(name, score_kw, window="full", **kw):
        col = "sc_" + "_".join(sorted(score_kw.get("parts", PARTS))) + "_" + "_".join(score_kw.get("extras", ())) \
              + ("_m" if score_kw.get("margin") else "") + ("_p" if score_kw.get("policy") else "")
        if col not in df:
            df[col] = scored(df, col, **score_kw)
        if kw.get("newlist") == "use":
            kw["newlist"] = nl_by
        ser = simulate(df, P, col, start_from="2020-01-01" if window == "w2020" else None, bench_daily=bench,
                       PF=PF, **kw)
        st, me = evaluate(ser, bench, HALVES[window])
        st.update(t1(df, col))
        st["window"] = window
        res[name], monthly[name], spec[name], cols[name] = st, me, (score_kw, window, kw), col
        print(f"{name:34s} {window:5s} excess {st['excess']:+.1%} (h1 {st['half1']:+.1%} h2 {st['half2']:+.1%}) "
              f"t {st['t']:.2f} worst {st['worst']:+.1%} starts {st['starts']}/12 last5 {st['last5']}/5 "
              f"T1 lift3 {st['t1_lift3']:.2f} halve {st['t1_halve']:.2f} grade {st['grade']}", flush=True)

    V1 = {"parts": PARTS}
    run("v1 flat-31bps", V1, flat_cost=True)
    run("v1", V1)
    run("v1 [w2020]", V1, window="w2020")
    run("v1 top 10", V1, n=10)
    for p in PARTS:                                                       # C5
        run(f"drop {p}", {"parts": [x for x in PARTS if x != p]})
    for p in PARTS:
        run(f"only {p}", {"parts": [p]})
    run("+ superinvestor entry", {"parts": PARTS, "extras": ("si_entry",)})          # C3
    g = df[df["pond_b"].fillna(False).astype(bool) & df["y3"].notna()]
    si = g[g["si_entry"] == 1]
    print(f"   superinvestor entries in the pond with a 3y label: {len(si)} rows / {si['id'].nunique()} stocks; "
          f"P(3x in 3y) {(si['y3'] >= 3).mean():.3f} vs pond {(g['y3'] >= 3).mean():.3f}; P(halve) "
          f"{(si['y3'] <= 0.5).mean():.3f} vs {(g['y3'] <= 0.5).mean():.3f}; median y3 {si['y3'].median():.2f} "
          f"vs {g['y3'].median():.2f}", flush=True)
    for x in ("announcement_car", "delivery_anomaly_z", "cf_accruals", "retail_growth"):           # C4
        run(f"+ {x}", {"parts": PARTS, "extras": (x,)}, window="w2020")
    run("+ q_margin_chg (business)", {"parts": PARTS, "margin": True}, window="w2020")
    run("+ policy (tailwind)", {"parts": PARTS, "policy": True}, window="w2020")              # C8
    run("+ 5 new listings", V1, window="w2020", newlist="use")                                  # C1
    run("regime R1 (no rebalance in bear)", V1, regime="R1")                                    # C2
    run("regime R2 (index in bear)", V1, regime="R2")
    run("hold H2 (24 months)", V1, rule="h24")                                                  # C6
    run("hold H3 (band top 90)", V1, rule="h3")
    run("hold H4 (conviction exits)", V1, rule="h4")
    run("floor ADTV >= 1 Cr", V1, floor=1 * CR)                                                 # C7
    run("floor ADTV >= 2 Cr", V1, floor=2 * CR)

    # ── decisions (pre-registered rules) ──
    R = pd.DataFrame(res).T
    base = {"full": res["v1"], "w2020": res["v1 [w2020]"]}
    accepted, dropped = [], []
    for name, st in res.items():
        if name.startswith(("v1", "only")):
            R.loc[name, "verdict"] = "reference"
            continue
        b = base[st["window"]]
        d_ex, d1, d2, d_w = st["excess"] - b["excess"], st["half1"] - b["half1"], st["half2"] - b["half2"], \
            st["worst"] - b["worst"]
        score_ok = (d_ex >= 0.01 and d1 > 0 and d2 > 0 and d_w >= -0.05
                    and st["t1_lift3"] >= b["t1_lift3"] - 0.10 and st["t1_halve"] <= b["t1_halve"] + 0.10)
        is_book = name.startswith(("regime", "hold", "floor", "+ 5 new"))
        book_ok = is_book and d1 >= -0.01 and d2 >= -0.01 and d_w >= 0.05
        ok = score_ok or book_ok
        R.loc[name, "verdict"] = ("DROP part" if name.startswith("drop") else "ACCEPT") if ok else "reject"
        if ok:
            (dropped if name.startswith("drop") else accepted).append(name)
    print("\n== verdicts ==")
    print(R[["window", "excess", "half1", "half2", "worst", "t", "starts", "last5", "t1_lift3", "t1_halve",
             "grade", "verdict"]].to_string(float_format=lambda x: f"{x:.3f}"), flush=True)
    print("\naccepted:", accepted, "\ndropped:", dropped, flush=True)

    # ── assemble v2 ──
    parts = [p for p in PARTS if f"drop {p}" not in dropped]
    score_kw = {"parts": parts, "extras": tuple(spec[a][0]["extras"][0] for a in accepted
                                                if spec[a][0].get("extras")),
                "margin": any(spec[a][0].get("margin") for a in accepted),
                "policy": any(spec[a][0].get("policy") for a in accepted)}
    book_kw = {}
    for kind, key in (("regime", "regime"), ("hold", "rule"), ("floor", "floor")):
        cands = [a for a in accepted if a.startswith(kind)]
        if cands:
            best = max(cands, key=lambda a: res[a]["worst"])
            book_kw[key] = spec[best][2][key]
    if "+ 5 new listings" in accepted:
        book_kw["newlist"] = "use"
    window = "w2020" if any(spec[a][1] == "w2020" for a in accepted) else "full"
    print(f"\nv2 = parts {parts} extras {score_kw['extras']} margin {score_kw['margin']} "
          f"policy {score_kw['policy']} book {book_kw} window {window}", flush=True)
    if not accepted and not dropped:
        print("nothing accepted: v2 = v1", flush=True)
    run("v2 FINAL", score_kw, window=window, **book_kw)
    if window == "w2020":
        run("v1 FINAL-window", V1, window="w2020")
    R = pd.DataFrame(res).T
    R.to_csv(V2 / "mb2_results.csv")
    M = pd.DataFrame(monthly)
    M.to_parquet(V2 / "mb2_monthly_excess.parquet")
    srs = (M.mean() / M.std())
    T = int(M.notna().sum().median())
    full_cols = [c for c in M if res[c]["window"] == "full"]
    print(f"\nDSR of v2 FINAL over {M.shape[1]} variants: {dsr(srs['v2 FINAL'], srs.values, T):.3f} "
          f"(its monthly SR {srs['v2 FINAL']:.3f}, best {srs.max():.3f}); "
          f"PBO over the {len(full_cols)} W_full variants (CSCV S=8): {pbo(M[full_cols]):.2f}", flush=True)
    # C9 overlap with the SMALL paper-sleeve scores
    o = pd.read_parquet(PROJECT_ROOT / "data" / "lh" / "oos_scores.parquet")
    o = o[o["cap_tier"] == "SMALL"]
    col = cols["v2 FINAL"]
    fin = df[df["pond_b"].fillna(False).astype(bool)]
    rows = []
    for meth, om in o.groupby("method"):
        for a, g2 in om.groupby("snapshot_date"):
            f = fin[fin["anchor"] == a]
            if f.empty:
                continue
            top_v2 = set(f.nlargest(30, col)["id"])
            top_m = set(g2.nlargest(20, "score")["sid"])
            rows.append({"method": meth, "anchor": a, "overlap": len(top_v2 & top_m) / 30})
    if rows:
        ov = pd.DataFrame(rows).groupby("method")["overlap"].mean()
        print("\nC9 overlap: share of the final top 30 also in each SMALL method's top 20 (mean over anchors):\n",
              ov.round(3).to_dict(), flush=True)


if __name__ == "__main__":
    main()
