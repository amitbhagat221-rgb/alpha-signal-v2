"""
Plan 0026 — did the thesis miss high-quality beaten-down multibaggers? (READ-ONLY on the DB; writes data/lh/v2/mbqd_*)

Amit 2026-10-17: "did we miss out on high quality beaten down stocks that might be multibaggers as well given we
just focused on ones having very good momentum … agreed please run".

PRE-REGISTRATION (written 2026-10-17 before any result; nothing below changes after the first run):

Harness: tools.mb_thesis — its panel (data/lh/v2/mb_thesis_panel.parquet: monthly anchors, labels y3 / y5 /
halve3 / stopped3, survivors' annual fundamentals knowable at period_end + 150 days), its book simulator (12
staggered starts, annual rebalance, 31 bps one-way, 12.5 % LTCG on sales) and its grade. Prices: tools.lh_price_history
(full NSE market incl. delisted, split/bonus adjusted).

QD rule ("quality dip"), on the thesis pond (arm B: liquidity + market-cap cap + sales > 0 + no auditor resignation /
CIRP in 365 days; survivors only, because annuals exist only for today's universe):
  quality  3-year average ROCE >= 15 % ((PBT + interest) / (equity + reserves + borrowings), the last 3 annuals
           knowable at the anchor, all 3 present), latest D/E <= 0.5, latest annual net profit > 0
  dip      price <= 60 % of its highest close in the last 756 sessions (3 years)
  cheap    book/price >= its own median book/price over the previous 36 monthly anchors (>= 24 present),
           i.e. P/B at or below its own 3-year median
  rank     mean within-set percentile of ROCE (high), depth of dip (low price / 3-year high) and book/price (high)
Arm F (full market incl. delisted, price only): the dip leg alone (price <= 60 % of 3-year high) on arm A's
liquidity pond, beside the same leg on survivors only — this measures how much of any dip effect is survivorship.

Tests (anchors with a 3-year label; own-history cheapness needs 24 prior anchors, so QD starts 2017):
  T1 tails, October anchors: P(y3 >= 3), P(y5 >= 5), P(halve3), P(stopped3), median y3 for the QD set, the pond and
     the thesis top 30; lifts = set rate / pond rate, averaged over anchors. Also every monthly anchor, split by
     regime at the anchor: bear = NIFTY SMALLCAP 250 <= 0.80 × its 252-session high (ADR 0040's line).
  T2 book: the QD set, top 30 by rank (all of it when fewer), against the equal-weight pond and the index, from
     the first month QD has >= 10 names; 12 staggered starts; same costs and tax as the thesis.
  Overlap: share of QD names already in the same anchor's thesis top 100.

PASS as a separate "quality dip" lens (all three):
  (a) T1 mean lift on P(y3 >= 3) >= 1.3 with mean halving lift <= 1.0, over October anchors with >= 10 QD names;
  (b) T2 30-name book median excess over the equal-weight pond >= +3 pts/yr with median t >= 1.5;
  (c) arm F: the full-market dip leg's halving lift is not more than 1.5x the survivors-only dip leg's
      (otherwise the survivor result is called survivorship and (a) does not count).
A pass adds a labelled lens next to the thesis, never a sixth part of the thesis score. A fail is recorded and the
thesis is left as it is. Regime results are reported but do not change the verdict (pre-registered as descriptive).

Usage:  python -m tools.mb_quality_dip
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools import mb_thesis as T  # noqa: E402
from tools.lh_price_history import load  # noqa: E402

V2 = T.V2
ROCE_MIN, DE_MAX, DIP_MAX, OWN_WIN, OWN_MIN = 0.15, 0.5, 0.60, 36, 24
TOP = 30


def roce3(conn):
    """(sid, known) → mean ROCE of the last 3 annual rows knowable at `known` (NaN unless all 3 exist)."""
    w = T.annuals(conn)
    eq = w["Equity Share Capital"] + w["Reserves"]
    w["roce"] = (w["Profit before tax"] + w["Interest"].fillna(0)) / (eq + w["Borrowings"].fillna(0))
    w.loc[(eq + w["Borrowings"].fillna(0)) <= 0, "roce"] = np.nan
    w = w.sort_values(["sid", "period_end"])
    w["roce3"] = w.groupby("sid")["roce"].transform(lambda s: s.rolling(3, min_periods=3).mean())
    w["np"] = w["Net profit"]
    return w[["sid", "known", "roce3", "np"]]


def add_inputs(df, P):
    """pos_3y (price / 3-year high), roce3 and latest net profit as knowable, own-history book/price median."""
    dates = P.index
    pos = {d: n for n, d in enumerate(dates)}
    out = []
    for a, g in df.groupby("anchor"):
        i = pos[a]
        g = g.copy()
        if i >= 755:
            hi = P.iloc[i - 755:i + 1][g["id"]].max()
            g["pos_3y"] = (P.iloc[i][g["id"]] / hi).values
        else:
            g["pos_3y"] = np.nan
        out.append(g)
    df = pd.concat(out, ignore_index=True)
    conn = T.ro()
    R = roce3(conn)
    conn.close()
    df["anchor_ts"] = pd.to_datetime(df["anchor"])
    df = df.sort_values("anchor_ts")
    R = R.sort_values("known")
    m = pd.merge_asof(df[["id", "anchor_ts"]].reset_index(), R.rename(columns={"sid": "id"}), left_on="anchor_ts",
                      right_on="known", by="id", direction="backward").set_index("index")
    df["roce3"] = m["roce3"]
    df["np_latest"] = m["np"]
    df = df.sort_values(["id", "anchor_ts"])
    df["bp_own_med"] = df.groupby("id")["bp"].transform(
        lambda s: s.shift(1).rolling(OWN_WIN, min_periods=OWN_MIN).median())
    return df.sort_values(["anchor_ts", "id"]).reset_index(drop=True)


def qd_flags(df):
    pond = df["pond_b"].fillna(False).astype(bool)
    q = (df["roce3"] >= ROCE_MIN) & (df["de"] <= DE_MAX) & (df["np_latest"] > 0)
    dip = df["pos_3y"] <= DIP_MAX
    cheap = df["bp"] >= df["bp_own_med"]
    df["qd"] = pond & q & dip & cheap
    df["qd_score"] = np.nan
    for a, g in df[df["qd"]].groupby("anchor"):
        s = (T.pct(g["roce3"]) + T.pct(-g["pos_3y"]) + T.pct(g["bp"])) / 3
        df.loc[g.index, "qd_score"] = s
    df["dip_a"] = df["pond_a"].fillna(False).astype(bool) & (df["pos_3y"] <= DIP_MAX)
    df["dip_a_surv"] = df["dip_a"] & df["survivor"].astype(bool)
    df["pond_a_surv"] = df["pond_a"].fillna(False).astype(bool) & df["survivor"].astype(bool)
    return df


def rates(s):
    y3 = s["y3"]
    return {"n": len(s), "3x3": (y3 >= 3).mean() if y3.notna().any() else np.nan,
            "5x5": (s["y5"] >= 5).mean() if s["y5"].notna().any() else np.nan,
            "halve3": (y3 <= 0.5).mean() if y3.notna().any() else np.nan,
            "stopped3": s["stopped3"].mean(), "med3": y3.median()}


def t1(df, anchors, bear):
    rows = []
    for a in anchors:
        g = df[df["anchor"] == a]
        pb = g[g["pond_b"].fillna(False).astype(bool)]
        if pb["y3"].notna().sum() == 0:
            continue
        top30 = pb.nlargest(TOP, "score_b") if pb["score_b"].notna().any() else pb.iloc[0:0]
        r = {"anchor": a, "bear": bool(bear.get(a, False))}
        for k, s in (("pond", pb), ("qd", g[g["qd"]]), ("thesis30", top30),
                     ("pondA", g[g["pond_a"].fillna(False).astype(bool)]), ("dipA", g[g["dip_a"]]),
                     ("pondA_surv", g[g["pond_a_surv"]]), ("dipA_surv", g[g["dip_a_surv"]])):
            for m, v in rates(s).items():
                r[f"{k}_{m}"] = v
        r["qd_in_thesis100"] = float(g.loc[g["qd"], "score_b"].rank(ascending=False).le(100).mean()) \
            if g["qd"].any() else np.nan
        top100 = set(pb.nlargest(100, "score_b")["id"]) if pb["score_b"].notna().any() else set()
        r["qd_in_thesis100"] = float(g.loc[g["qd"], "id"].isin(top100).mean()) if g["qd"].any() else np.nan
        rows.append(r)
    t = pd.DataFrame(rows)
    for k, base in (("qd", "pond"), ("thesis30", "pond"), ("dipA", "pondA"), ("dipA_surv", "pondA_surv")):
        for m in ("3x3", "5x5", "halve3"):
            t[f"{k}_lift_{m}"] = t[f"{k}_{m}"] / t[f"{base}_{m}"]
    return t


def bear_flags(dates):
    b = T.bench_monthly(dates).sort_index()
    hi = b.rolling(252, min_periods=200).max()
    return (b <= 0.80 * hi).to_dict()


def main():
    pd.set_option("display.width", 250)
    pd.set_option("display.float_format", lambda x: f"{x:.3f}")
    df = pd.read_parquet(V2 / "mb_thesis_panel.parquet")
    P, _, _ = load()
    df = T.score(df)
    df = add_inputs(df, P)
    df = qd_flags(df)
    bear = bear_flags(P.index)
    labelled = sorted(a for a in df["anchor"].unique() if df.loc[df["anchor"] == a, "y3"].notna().any())
    octs = [a for a in labelled if a[5:7] == "10" and a >= "2017-01-01"]
    t_oct = t1(df, octs, bear)
    t_all = t1(df, [a for a in labelled if a >= "2017-01-01"], bear)
    t_oct.to_csv(V2 / "mbqd_t1_october.csv", index=False)
    t_all.to_csv(V2 / "mbqd_t1_monthly.csv", index=False)

    print("== QD set size per October anchor ==")
    print(t_oct[["anchor", "pond_n", "qd_n", "qd_in_thesis100"]].to_string(index=False))
    cols = ["anchor", "qd_n", "pond_3x3", "qd_3x3", "qd_lift_3x3", "thesis30_lift_3x3", "pond_5x5", "qd_5x5",
            "qd_lift_5x5", "pond_halve3", "qd_halve3", "qd_lift_halve3", "thesis30_lift_halve3", "pond_med3", "qd_med3"]
    print("\n== T1 October anchors ==\n", t_oct[cols].to_string(index=False))
    ok = t_oct[t_oct["qd_n"] >= 10]
    a_lift, a_halve = ok["qd_lift_3x3"].mean(), ok["qd_lift_halve3"].mean()
    print(f"\n(a) anchors with >= 10 QD names: {len(ok)}; mean lift P(3x in 3y) {a_lift:.2f} (bar 1.3); "
          f"mean halving lift {a_halve:.2f} (bar <= 1.0); thesis top 30 for comparison: lift "
          f"{ok['thesis30_lift_3x3'].mean():.2f}, halving {ok['thesis30_lift_halve3'].mean():.2f}")
    pass_a = bool(a_lift >= 1.3 and a_halve <= 1.0)

    print("\n== T1 every monthly anchor, by regime at the anchor (descriptive) ==")
    m = t_all[t_all["qd_n"] >= 10]
    print(m.groupby("bear")[["qd_n", "qd_lift_3x3", "qd_lift_halve3", "thesis30_lift_3x3", "thesis30_lift_halve3",
                             "qd_med3", "pond_med3"]].agg(["mean", "count"]).round(3).to_string())

    fa = t_oct[["dipA_lift_3x3", "dipA_lift_halve3", "dipA_surv_lift_3x3", "dipA_surv_lift_halve3", "dipA_n",
                "dipA_stopped3", "pondA_stopped3"]].mean()
    print("\n== Arm F: dip leg alone, full market incl. delisted vs survivors only (October anchors) ==\n", fa.to_string())
    pass_c = bool(fa["dipA_lift_halve3"] <= 1.5 * fa["dipA_surv_lift_halve3"])

    bench = T.bench_monthly(P.index)
    df["one"] = 1.0
    first = sorted(a for a, g in df[df["qd"]].groupby("anchor") if len(g) >= 10)
    sub = df[df["anchor"] >= first[0]] if first else df.iloc[0:0]
    r_qd, s_qd = T.grade(T.book(sub, P, "qd_score", "qd", TOP), bench)
    pond_series = T.book(sub, P, "one", "pond_b", 10_000)
    qd_series = T.book(sub, P, "qd_score", "qd", TOP)
    ex = []
    for start, v in qd_series.items():
        pv = pond_series[start].reindex(v.index).ffill()
        yrs = len(v) / 12
        cq, cp = v.iloc[-1] ** (1 / yrs) - 1, (pv.iloc[-1] / pv.iloc[0]) ** (1 / yrs) - 1
        ann = (v.iloc[::12].pct_change() - pv.iloc[::12].pct_change()).dropna()
        ex.append({"start": start, "qd_cagr": cq, "pond_cagr": cp, "excess_vs_pond": cq - cp,
                   "t": ann.mean() / (ann.std() / np.sqrt(len(ann))) if len(ann) > 1 else np.nan,
                   "worst_12m_vs_pond": (v.pct_change(12) - pv.pct_change(12)).min()})
    ex = pd.DataFrame(ex)
    ex.to_csv(V2 / "mbqd_book_vs_pond.csv", index=False)
    b_ex, b_t = float(ex["excess_vs_pond"].median()), float(ex["t"].median())
    print(f"\n== T2 30-name QD book from {first[0] if first else '-'} (31 bps, 12.5 % LTCG) ==")
    print(f"vs NIFTY SMALLCAP 250: median CAGR {s_qd['median_cagr']:.1%}, excess {s_qd['median_excess_pa']:+.1%}/yr, "
          f"t {s_qd['median_t']:.2f}, starts beat {s_qd['beats_starts']}/12, worst 12m {s_qd['worst_12m_excess']:+.1%}, "
          f"grade {s_qd['grade_ex_dsr']}")
    print(f"vs equal-weight pond: median excess {b_ex:+.1%}/yr (bar +3.0), median t {b_t:.2f} (bar 1.5), "
          f"starts beat {int((ex['excess_vs_pond'] > 0).sum())}/12, worst 12m {ex['worst_12m_vs_pond'].min():+.1%}")
    pass_b = bool(b_ex >= 0.03 and b_t >= 1.5)

    latest = df[df["anchor"] == df["anchor"].max()]
    cur = latest[latest["qd"]].sort_values("qd_score", ascending=False)
    cur[["id", "industry", "mcap_cr", "roce3", "de", "pos_3y", "bp", "bp_own_med", "qd_score", "score_b"]].to_csv(
        V2 / "mbqd_latest.csv", index=False)
    print(f"\nlatest anchor {latest['anchor'].iloc[0]}: {len(cur)} QD names "
          f"({int(cur['id'].isin(set(latest[latest['pond_b'].fillna(False).astype(bool)].nlargest(100, 'score_b')['id'])).sum())} "
          f"already in the thesis top 100) → data/lh/v2/mbqd_latest.csv")
    verdict = "PASS" if (pass_a and pass_b and pass_c) else "FAIL"
    print(f"\nVERDICT: {verdict}  (a) tails {pass_a}  (b) book vs pond {pass_b}  (c) not survivorship {pass_c}")
    pd.Series({"verdict": verdict, "pass_a": pass_a, "pass_b": pass_b, "pass_c": pass_c, "lift_3x3": a_lift,
               "lift_halve3": a_halve, "book_excess_vs_pond": b_ex, "book_t_vs_pond": b_t,
               "book_vs_index": s_qd}).to_json(V2 / "mbqd_summary.json", default_handler=str)


if __name__ == "__main__":
    main()
