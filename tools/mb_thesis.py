"""
Plan 0026 phase 1 — test the multibagger thesis (READ-ONLY on the DB; writes data/lh/v2/mb_thesis_*).

PRE-REGISTRATION (written 2026-10-15 before any result; nothing below changes after the first run):

Thesis v1 (plan 0026): a loose pond (safety gates only, no quality hurdle), ranked by an equal-weight
within-pond percentile score of five parts: smallness, cheapness, price trigger, business trigger,
industry tailwind. Two arms, because fundamentals exist only for today's universe:

ARM A — price only, FULL NSE market incl. delisted (tools.lh_price_history.load: today's universe
  split/bonus adjusted + stock_prices_unlisted EQ/BE with band-impossible jumps neutralised).
  Pond: >= 200 prices in the past 252 sessions, ADTV (126-session median close × volume) >= ₹0.5 Cr,
  ADTV rank > 250 (outside the most liquid 250 = LARGE/MID stand-in).
  Score: mean percentile of smallness (−log ADTV), mom_6m (P(t)/P(t−126) − 1), pos_52w (P(t)/max 252).
ARM B — the full thesis, SURVIVORS only (today's universe; Screener annuals exist only for it).
  Pond: arm A's liquidity rules + market cap <= ₹5,000 Cr deflated to the anchor by the ratio of the
  universe median market cap (anchor vs latest), annual Sales > 0, no "Resignation of Statutory
  Auditors" and no CIRP subcategory filing in the 365 days before the anchor (bse_announcements,
  so this gate only bites from 2019; earlier anchors pass it). Pledge, SEBI orders and GSM are not
  available historically and are not applied (stated in the verdict).
  Parts (each a within-pond percentile; a stock missing a part gets the mean of its other parts):
    smallness  −log market cap (raw close × "No. of Equity Shares", latest annual knowable)
    cheapness  mean percentile of book/price, sales/price, earnings/price (latest annual)
    price      mean percentile of mom_6m and pos_52w
    business   mean percentile of q_ebitda_chg and q_rev_yoy (tools.lh_quarterly_nse history/asof:
               NSE XBRL first filing at filed_at, Tickertape at quarter end + 60 days) — exists from 2019
    industry   median mom_6m of the stock's `stocks.industry` inside the pond
  Annuals are knowable at period_end + 150 days (as tools.lh_growth).

Labels: entry at the anchor's next session close; exit at the first session >= anchor + 3 / 5 calendar
  years, or the last traded close if the name stopped trading (kept, never dropped).
  y3 = multiple at 3 years, y5 = at 5 years; halve3 = y3 <= 0.5; stopped3 = no price at the 3-year exit.

T1 tail capture — October anchors (arm A 2011–2023, arm B 2015–2023; y5 needs anchor <= 2021):
  per anchor, the top-30 by score vs the whole pond: P(y3 >= 3), P(y5 >= 5), P(halve3), P(stopped3),
  median y3. Lift = top-30 rate / pond rate. Reported per anchor and averaged.
T2 book — first session of every month 2016-01 → latest; 12 staggered start months (Jan…Dec 2016);
  from each start, each year buy the top N (10 and 30) equal weight, hold 12 months (buy-and-hold
  drift, marked monthly, a stopped name is held at its last close), rebalance on the anniversary.
  Cost 31 bps one-way on the traded weight (plan 0024 measured SMALL cost); tax: 12.5 % on the
  positive realised gain of every name sold at a rebalance (all held >= 12 months = long term),
  losses not carried (conservative). Benchmark: NIFTY SMALLCAP 250 price index, untaxed, uncosted.
  Graded by ADR 0073: t (annual excess, mean over starts / (sd / sqrt n)), beats the index in >= 3 of 5
  calendar years and in >= 10 of 12 starts, worst 12-month excess >= −15 %. DSR/PBO are not computed
  (four variants, no grid search); with 4 variants the two-sided Bonferroni bar is t ≈ 2.5,
  reported beside the ADR 0073 grade.
T3 head-to-head (arm B pond, same anchors): the old funnel's gates as far as history allows —
  ROCE >= 18 %, D/E <= 0.5, market cap ₹1,000–20,000 Cr deflated, 3-year PAT CAGR >= 20 % — T1 rates
  for everything that passes it, and the equal-weight pond as the "no score" baseline.

Pass (plan 0026 1.1, grade B): arm B top-30 lift >= 1.5 on P(y5 >= 5) [or on P(y3 >= 3) where y5 is
  missing] with P(halve3) <= the pond's in >= 70 % of anchors, AND the 30-name arm B book grade >= B.
Decision (Amit D1, 2026-10-15): whatever the grade, the thesis ships as a labelled "where to look" list;
  the grade sets the label and the size, not whether it ships.

Bug fixes after the first run (2026-10-15, code only, no rule changed): the T1 pass share counted
  anchors with no 3-year label yet (2024–26) in its denominator; T2 stopped a start's book at the first
  rebalance month with no arm-B score (small early ponds) — it now keeps the holdings (or cash) until a
  score exists. Second fix (same day): that "cash" made a start's worst 12 months the index's 2016
  rally against a book that did not exist yet, so each arm's 12 staggered starts now begin at its first
  scored month (arm B's survivor pond reaches 100 names only later in 2016). Third fix (same day,
  found in the latest longlist): market cap used the annual share count with today's price, so a split
  or bonus after the period end shrank the cap (KAMDHENU ₹101 Cr vs ₹1,072 Cr); shares are now carried
  to the anchor through corporate_adjustments split/bonus factors. The "industry" part is renamed
  "tailwind" (its column overwrote the industry name in the output; scores were unaffected).
Rule change 2026-10-19 (Amit: "add fraud/default as red flags"), labelled as a change, not a fix: the red-flag
  gate reads MB_THESIS["red_flags"] through signals.announcements, the live gate's rule — auditor resignation,
  CIRP, a Reg 30 fraud filing, a loan/debt default disclosure (BSE history + NSE live, ADR 0082).

Usage:  python -m tools.mb_thesis [--reuse]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import MB_THESIS  # noqa: E402
from signals import announcements  # noqa: E402
from signals.multibagger import PARTS, liquidity_pond, thesis  # noqa: E402
from tools.lh_price_history import load  # noqa: E402
from tools.lh_quarterly_nse import asof as q_asof, history as q_history  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
V2 = PROJECT_ROOT / "data" / "lh" / "v2"
CR = 1e7
ADTV_MIN = MB_THESIS["adtv_min_cr"] * CR          # the gates live in config.MB_THESIS (ADR 0075)
MCAP_MAX_CR = MB_THESIS["mcap_max_cr"]
ANNUAL_LAG = MB_THESIS["annual_lag_days"]
COST = 0.0031
LTCG = 0.125
TOP = 30
BENCH = "NIFTY SMALLCAP 250"
ANNUAL = ["Sales", "Net profit", "Profit before tax", "Interest", "Borrowings", "Equity Share Capital",
          "Reserves", "No. of Equity Shares"]


def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def pct(s):
    return s.rank(pct=True)


def month_firsts(dates, start):
    s = pd.Series(dates, index=pd.to_datetime(dates))
    return [d for d in s.groupby(s.index.to_period("M")).first().values if d >= start]


def annuals(conn):
    q = ("SELECT sid, period_end, line_item, value FROM fundamentals_screener WHERE period_type='annual' "
         f"AND line_item IN ({','.join('?' * len(ANNUAL))})")
    f = pd.read_sql(q, conn, params=ANNUAL)
    w = f.pivot_table(index=["sid", "period_end"], columns="line_item", values="value", aggfunc="last").reset_index()
    w["known"] = pd.to_datetime(w["period_end"]) + pd.Timedelta(days=ANNUAL_LAG)
    w = w.sort_values(["sid", "period_end"])
    g = w.groupby("sid")
    pat3 = g["Net profit"].shift(3)
    w["pat_cagr_3y"] = np.where(pat3 > 0, (w["Net profit"] / pat3).clip(lower=0) ** (1 / 3) - 1, np.nan)
    return w


def latest_annual(w, anchor):
    k = w[w["known"] <= pd.Timestamp(anchor)]
    return k.drop_duplicates("sid", keep="last").set_index("sid")


def red_flags(conn, kinds=None):
    """[sid, d] of every red-flag filing — the live gate's rule (signals.multibagger.red_flag_events):
    MB_THESIS["red_flags"] through signals.announcements (BSE history + NSE live, ADR 0082). Since 2026-10-19
    the kinds include fraud and loan/debt default (Amit); `kinds` narrows them (e.g. the pre-2026-10-19 pair)."""
    spec = {k: v for k, v in MB_THESIS["red_flags"].items() if kinds is None or k in kinds}
    b = announcements.events(spec, conn).rename(columns={"date": "d"})[["sid", "d"]]
    return b.dropna()


def share_events(conn):
    a = pd.read_sql("SELECT sid, substr(ex_date,1,10) AS ex, factor FROM corporate_adjustments "
                    "WHERE inds LIKE '%SPLIT%' OR inds LIKE '%BONUS%'", conn)
    a["ex"] = pd.to_datetime(a["ex"])
    return a


def shares_now(fa, ev, anchor):
    """Annual share count carried to the anchor: divide by every split/bonus factor between the
    period end and the anchor (factor < 1 multiplies pre-ex prices, so shares grow by 1 / factor)."""
    t = pd.Timestamp(anchor)
    pe = pd.to_datetime(fa["period_end"])
    e = ev[ev["sid"].isin(fa.index) & (ev["ex"] <= t)].merge(pe.rename("pe"), left_on="sid", right_index=True)
    mult = (1 / e.loc[e["ex"] > e["pe"], "factor"]).groupby(e["sid"]).prod()
    return fa["No. of Equity Shares"] * mult.reindex(fa.index).fillna(1.0)


def raw_closes(conn, dates):
    q = f"SELECT sid, date, close FROM stock_prices WHERE date IN ({','.join('?' * len(dates))})"
    return pd.read_sql(q, conn, params=list(dates)).pivot(index="date", columns="sid", values="close")


def labels(P, i, ids, a):
    dates = P.index
    out = {}
    for yrs in (3, 5):
        end = str((pd.Timestamp(a) + pd.DateOffset(years=yrs)).date())
        if end > dates[-1]:
            out[f"y{yrs}"] = pd.Series(np.nan, index=ids)
            out[f"stopped{yrs}"] = pd.Series(np.nan, index=ids)
            continue
        k = int(np.searchsorted(dates, end))
        fut = P.iloc[i + 1:k + 1][ids]
        out[f"y{yrs}"] = fut.ffill().iloc[-1] / fut.iloc[0]
        out[f"stopped{yrs}"] = fut.iloc[-1].isna().astype(float)
    return pd.DataFrame(out)


def build():
    P, TV, survivors = load()
    conn = ro()
    dates = P.index
    pos = {d: n for n, d in enumerate(dates)}
    W = annuals(conn)
    flags = red_flags(conn)
    EV = share_events(conn)
    stocks = pd.read_sql("SELECT sid, industry, sector FROM stocks", conn).set_index("sid")
    anchors = month_firsts(dates, "2011-01-01")
    RC = raw_closes(conn, anchors)
    QH = q_history(conn)
    conn.close()
    Q = q_asof(QH, [a for a in anchors if a >= "2015-01-01"]).set_index(["snapshot_date", "sid"])
    latest_med = None
    rows = []
    R = P.pct_change(fill_method=None)
    for a in anchors:
        i = pos[a]
        if i < 252:
            continue
        win = P.iloc[i - 252:i + 1]
        tvw = TV.iloc[i - 125:i + 1]
        adtv = tvw.median()
        ok = (win.notna().sum() >= 200) & P.iloc[i].notna() & (tvw.notna().mean() >= 0.5)
        ids = ok[ok].index
        f = pd.DataFrame(index=ids)
        f["adtv"] = adtv[ids]
        f["adtv_rank"] = f["adtv"].rank(ascending=False)
        f["mom_6m"] = P.iloc[i][ids] / P.iloc[i - 126][ids] - 1
        f["pos_52w"] = P.iloc[i][ids] / win[ids].max()
        f["vol_1y"] = R.iloc[i - 251:i + 1][ids].std()
        f["survivor"] = f.index.isin(survivors)
        f = f.join(labels(P, i, ids, a))
        # arm B fundamentals (survivors only)
        if a >= "2015-01-01":
            an = latest_annual(W, a)
            rc = RC.loc[a] if a in RC.index else pd.Series(dtype=float)
            sv = f.index[f["survivor"]]
            fa = an.reindex(sv)
            mcap = rc.reindex(sv) * shares_now(fa, EV, a) / CR
            eq = fa["Equity Share Capital"] + fa["Reserves"]
            f.loc[sv, "mcap_cr"] = mcap
            f.loc[sv, "bp"] = eq / mcap
            f.loc[sv, "sp"] = fa["Sales"] / mcap
            f.loc[sv, "ep"] = fa["Net profit"] / mcap
            f.loc[sv, "sales"] = fa["Sales"]
            f.loc[sv, "roce"] = (fa["Profit before tax"] + fa["Interest"]) / (eq + fa["Borrowings"].fillna(0))
            f.loc[sv, "de"] = fa["Borrowings"].fillna(0) / eq
            f.loc[sv, "pat_cagr_3y"] = fa["pat_cagr_3y"]
            f.loc[sv, "industry"] = stocks["industry"].reindex(sv)
            f.loc[sv, "sector"] = stocks["sector"].reindex(sv)
            fl = flags[(flags["d"] <= pd.Timestamp(a)) & (flags["d"] > pd.Timestamp(a) - pd.Timedelta(days=365))]
            f["red_flag"] = f.index.isin(set(fl["sid"]))
            if a in Q.index.get_level_values(0):
                q = Q.loc[a]
                f.loc[f.index.intersection(q.index), "q_ebitda_chg"] = q["q_ebitda_chg"]
                f.loc[f.index.intersection(q.index), "q_rev_yoy"] = q["q_rev_yoy"]
        if "red_flag" not in f:
            f["red_flag"] = False
        f["anchor"] = a
        rows.append(f.reset_index(names="id"))
    df = pd.concat(rows, ignore_index=True)
    # deflate the ₹5,000 Cr cap by the universe median market cap, anchor vs latest
    med = df.groupby("anchor")["mcap_cr"].median()
    latest_med = med.dropna().iloc[-1]
    df["mcap_max"] = df["anchor"].map(MCAP_MAX_CR * med / latest_med)
    df["mcap_scale"] = df["anchor"].map(med / latest_med)
    V2.mkdir(parents=True, exist_ok=True)
    df.to_parquet(V2 / "mb_thesis_panel.parquet", index=False)
    return df, P


def score(df):
    """Adds pond_a / score_a (full market) and pond_b / score_b (survivors) per anchor."""
    out = []
    for a, g in df.groupby("anchor"):
        g = g.copy()
        g["pond_a"] = liquidity_pond(g, ADTV_MIN / CR)
        pa = g[g["pond_a"]]
        sa = (pct(-np.log(pa["adtv"])) + pct(pa["mom_6m"]) + pct(pa["pos_52w"])) / 3
        g.loc[pa.index, "score_a"] = sa
        # arm B IS the live thesis (signals.multibagger.thesis): same gates, same parts, same fill rule
        t = thesis(g, min_pond=100, adtv_min_cr=ADTV_MIN / CR)
        g["pond_b"] = t["thesis_pond"]
        if t["thesis_score"].notna().any():
            g[PARTS] = t[PARTS]
            g["score_b"] = t["thesis_score"]
            scale = g["mcap_scale"].iloc[0]
            g["old_funnel"] = (g["pond_a"] & g["survivor"] & (g["roce"] >= 0.18) & (g["de"] <= 0.5)
                               & g["mcap_cr"].between(1_000 * scale, 20_000 * scale) & (g["pat_cagr_3y"] >= 0.20))
        out.append(g)
    return pd.concat(out, ignore_index=True)


def t1(df):
    rows = []
    octs = sorted(a for a in df["anchor"].unique() if a[5:7] == "10")
    for arm, pond, sc in (("A full market", "pond_a", "score_a"), ("B thesis survivors", "pond_b", "score_b"),
                          ("B price-only survivors", "pond_b", "score_a")):
        for a in octs:
            g = df[(df["anchor"] == a) & df[pond].fillna(False).astype(bool)]
            if len(g) < 100 or g[sc].isna().all():
                continue
            top = g.nlargest(TOP, sc)
            sets = {"pond": g, "top30": top}
            if arm.startswith("B thesis"):
                sets["old_funnel"] = g[g["old_funnel"].fillna(False).astype(bool)]
            r = {"arm": arm, "anchor": a, "n_pond": len(g), "n_old_funnel": len(sets.get("old_funnel", []))}
            for k, s in sets.items():
                r[f"{k}_3x3"] = (s["y3"] >= 3).mean() if s["y3"].notna().any() else np.nan
                r[f"{k}_5x5"] = (s["y5"] >= 5).mean() if s["y5"].notna().any() else np.nan
                r[f"{k}_halve3"] = (s["y3"] <= 0.5).mean() if s["y3"].notna().any() else np.nan
                r[f"{k}_stopped3"] = s["stopped3"].mean()
                r[f"{k}_med3"] = s["y3"].median()
            rows.append(r)
    t = pd.DataFrame(rows)
    for k in ("top30", "old_funnel"):
        for m in ("3x3", "5x5", "halve3"):
            if f"{k}_{m}" in t:
                t[f"{k}_lift_{m}"] = t[f"{k}_{m}"] / t[f"pond_{m}"]
    return t


def bench_monthly(dates):
    conn = ro()
    b = pd.read_sql("SELECT trade_date AS date, close FROM nse_index_history WHERE index_symbol = ?", conn,
                    params=[BENCH]).set_index("date")["close"]
    conn.close()
    return b


def book(df, P, sc, pond, n):
    """12 staggered starts in 2016; annual rebalance; monthly marks; returns per-start monthly value series."""
    dates = P.index
    months = month_firsts(dates, "2016-01-01")
    sc_by = {a: g for a, g in df[df[pond].fillna(False).astype(bool)].groupby("anchor")}
    scored = [a for a in months if a in sc_by and sc_by[a][sc].notna().any()]
    months = months[months.index(scored[0]):]          # the 12 starts begin at the arm's first scored month
    series = {}
    for s in range(12):
        start = months[s]
        val, hold, tax_paid, value = 1.0, None, 0.0, {}
        rebal = months[s::12]
        for j, a in enumerate(months[s:]):
            if a in rebal:
                g = sc_by.get(a)
                if g is None or g[sc].isna().all():        # no score yet: keep what is held (or stay in cash)
                    if hold is not None:
                        px_now = P.loc[a, hold["ids"]].fillna(P.loc[:a, hold["ids"]].ffill().iloc[-1])
                        value[a] = float((hold["w"] * px_now / hold["px"]).sum())
                    else:
                        value[a] = val
                    continue
                new = list(g.nlargest(n, sc)["id"])
                if hold is not None:
                    px_now = P.loc[a, hold["ids"]].fillna(P.loc[:a, hold["ids"]].ffill().iloc[-1])
                    w_now = hold["w"] * px_now / hold["px"]
                    val = float(w_now.sum())
                    # sell what leaves: realised gain taxed, costs on traded weight
                    gone = [x for x in hold["ids"] if x not in new]
                    gain = float((w_now[gone] - hold["w"][gone]).clip(lower=0).sum())
                    val -= LTCG * gain
                    target = val / len(new)
                    kept = pd.Series(w_now).reindex(new).fillna(0)
                    traded = float((target - kept).abs().sum() + w_now[gone].sum())
                    val -= COST * traded
                else:
                    val -= COST * val
                px = P.loc[a, new]
                hold = {"ids": new, "w": pd.Series(val / len(new), index=new), "px": px}
            if hold is None:
                value[a] = val
                continue
            px_now = P.loc[a, hold["ids"]].fillna(P.loc[:a, hold["ids"]].ffill().iloc[-1])
            value[a] = float((hold["w"] * px_now / hold["px"]).sum())
        series[start] = pd.Series(value)
    return series


def grade(series, bench):
    rows, yearly = [], []
    for start, v in series.items():
        b = bench.reindex(v.index).ffill()
        bv = b / b.iloc[0]
        ex = (v / v.iloc[0]) / bv
        yrs = len(v) / 12
        cagr, bcagr = v.iloc[-1] ** (1 / yrs) - 1, bv.iloc[-1] ** (1 / yrs) - 1
        r12 = (v.pct_change(12) - bv.pct_change(12)).dropna()
        ann = (v.iloc[::12].pct_change() - bv.iloc[::12].pct_change()).dropna()
        rows.append({"start": start, "cagr": cagr, "bench_cagr": bcagr, "excess_pa": cagr - bcagr,
                     "worst_12m_excess": r12.min(), "t_annual": ann.mean() / (ann.std() / np.sqrt(len(ann)))})
        cal = v.groupby(pd.to_datetime(v.index).year).last() / v.groupby(pd.to_datetime(v.index).year).first()
        bcal = bv.groupby(pd.to_datetime(bv.index).year).last() / bv.groupby(pd.to_datetime(bv.index).year).first()
        yearly.append(cal - bcal)
    r = pd.DataFrame(rows)
    cal = pd.concat(yearly, axis=1).mean(axis=1)
    last5 = cal.iloc[-6:-1] if len(cal) > 5 else cal
    t = float(r["t_annual"].median())
    beats_starts = int((r["excess_pa"] > 0).sum())
    beats_years = int((last5 > 0).sum())
    worst = float(r["worst_12m_excess"].min())
    g = "B" if (t >= 1.5 and beats_years >= 3 and beats_starts >= 10 and worst >= -0.15) else "C"
    return r, {"median_excess_pa": float(r["excess_pa"].median()), "median_cagr": float(r["cagr"].median()),
               "median_t": t, "beats_starts": beats_starts, "beats_last5_years": beats_years,
               "worst_12m_excess": worst, "grade_ex_dsr": g, "calendar_excess": cal.round(3).to_dict()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true")
    args = ap.parse_args()
    if args.reuse and (V2 / "mb_thesis_panel.parquet").exists():
        df = pd.read_parquet(V2 / "mb_thesis_panel.parquet")
        P, _, _ = load()
    else:
        df, P = build()
    df = score(df)
    T = t1(df)
    T.to_csv(V2 / "mb_thesis_t1.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.float_format", lambda x: f"{x:.3f}")
    cols = ["arm", "anchor", "n_pond", "pond_3x3", "top30_3x3", "top30_lift_3x3", "pond_5x5", "top30_5x5",
            "top30_lift_5x5", "pond_halve3", "top30_halve3", "pond_stopped3", "top30_stopped3", "pond_med3", "top30_med3"]
    print("\n== T1 tail capture (October anchors) ==")
    print(T[cols].to_string(index=False))
    summ = T.groupby("arm")[["top30_lift_3x3", "top30_lift_5x5", "top30_lift_halve3"]].mean()
    print("\nmean lifts by arm:\n", summ)
    b = T[(T["arm"] == "B thesis survivors") & T["pond_3x3"].notna()].copy()     # anchors with a 3-year label
    b["lift_main"] = b["top30_lift_5x5"].fillna(b["top30_lift_3x3"])
    b["pass_anchor"] = (b["lift_main"] >= 1.5) & (b["top30_halve3"] <= b["pond_halve3"])
    print(f"\nT1 arm B: anchors passing (lift >= 1.5 and halve <= pond): {int(b['pass_anchor'].sum())}/{len(b)}"
          f" = {b['pass_anchor'].mean():.0%} (bar 70 %)")
    of = T[T["arm"] == "B thesis survivors"][["anchor", "n_old_funnel", "old_funnel_3x3", "old_funnel_lift_3x3",
                                               "old_funnel_5x5", "old_funnel_lift_5x5", "old_funnel_halve3"]]
    print("\n== T3 old funnel gates on the arm-B pond ==\n", of.to_string(index=False))
    bench = bench_monthly(P.index)
    out = {}
    for name, sc, pond in (("B thesis", "score_b", "pond_b"), ("A full market", "score_a", "pond_a")):
        for n in (10, 30):
            r, s = grade(book(df, P, sc, pond, n), bench)
            out[f"{name} top{n}"] = s
            r.to_csv(V2 / f"mb_thesis_book_{name.split()[0]}_{n}.csv", index=False)
    print("\n== T2 books vs NIFTY SMALLCAP 250 (after 31 bps cost and 12.5 % LTCG on sales) ==")
    for k, s in out.items():
        print(f"{k:22s} median CAGR {s['median_cagr']:.1%}  median excess {s['median_excess_pa']:+.1%}/yr  "
              f"t {s['median_t']:.2f}  starts beat {s['beats_starts']}/12  last-5-years beat {s['beats_last5_years']}/5  "
              f"worst 12m {s['worst_12m_excess']:+.1%}  grade {s['grade_ex_dsr']}")
        print("   calendar excess:", s["calendar_excess"])
    pd.Series(out).to_json(V2 / "mb_thesis_books.json")
    latest = df[df["anchor"] == df["anchor"].max()]
    lp = latest[latest["pond_b"].fillna(False).astype(bool)].nlargest(60, "score_b")
    lp[["id", "industry", "mcap_cr", "score_b"] + PARTS].to_csv(V2 / "mb_thesis_longlist_latest.csv", index=False)
    print(f"\nlatest anchor {latest['anchor'].iloc[0]}: pond B {int(latest['pond_b'].sum())} names; top-60 written")


if __name__ == "__main__":
    main()
