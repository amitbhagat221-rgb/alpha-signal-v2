"""
Plan 0026 phase 1d — the independent reviewer's tests (research 0008), READ-ONLY on the DB.
Writes data/lh/v2/mbc_* . Answer: docs/research/0008-multibagger-critique-response.md.

PRE-REGISTRATION (2026-10-16). The bars are the REVIEWER's, copied from
docs/research/0008-multibagger-critique-findings.md before any of these ran (1d.1 ran first, from a
scratchpad copy of `ew` below; its result is reproduced here, not re-chosen):

Harness: tools.mb_thesis panel + score (v1 thesis, ADR 0075), tools.mb_thesis_v2.simulate / evaluate
(top 30, equal weight, yearly rebalance, 12 staggered starts from the first scored month, realistic costs
by liquidity at the book size, 12.5 % tax on realised gains), benchmark NIFTY SMALLCAP 250.

  ew        (test 1)  top 30 vs the EQUAL-WEIGHT POND (same gates, no score), arm B (survivors, full
                      thesis) and arm A (full market incl. delisted, price-only score).
                      Bar: median (top 30 − pond) >= +5 %/yr and median per-start t >= 1.5.
  dsr       (test 3)  deflated Sharpe ratio (Bailey & López de Prado 2014, with skew and kurtosis) of
                      v1's monthly excess vs SMALLCAP 250. Trials N = every configuration evaluated on this
                      window: 4 (mb_thesis T2) + 31 (mb_thesis_v2) + 6 (mb_funnel) + 2 (ew) + the 1d variants
                      + 1 (the retired quality funnel) + 10 (the trait study that chose the five parts) — counted
                      in code. Reported three ways: (a) observed variance of the trials' Sharpes, N raw;
                      (b) same, N effective from the trials' correlation; (c) the null sampling variance
                      1 / (T − 1) with N raw (does not reward near-clone variants). Headline and bar: (c) >= 0.90.
  tails     (test 2)  arm A (full market incl. delisted, price-only score), October anchors with a 3-year
                      label: lift of P(y3 <= 0.5) and of P(y3 <= 0.3), top 30 vs pond. Bar: halving lift <= 0.7.
  lag       (test 4)  the Tickertape quarterly lag 60 → 90 days (NSE rows already use their filing time);
                      panel rebuilt in a scratch dir, v1 book re-run. Bar: median excess within 2 points.
  capacity  (problem 3) the book at 3× and 10× the tested ₹30 lakh. Bar: excess >= +5 %/yr at 3×.
  livepond  (finding 4.1) market cap from scoring.segment's tier inputs (signals._fundamentals.market_caps,
                      the live source) instead of annual Screener shares; pond size per anchor and the `ew`
                      test on that pond. Reported, no bar of the reviewer's; the house bar: still passes `ew`.
  promoter  (test 5)  promoter_trend_4q (daily_snapshots_pit, 2019-12+) as a sixth part, window 2020-01 starts.
  cashgate  (test 6)  exclude the bottom decile of 3-year CFO / EBITDA and the top decile of the 1-year change
                      in receivable days (annual Screener, 150-day lag) from the pond.
                      Tests 5 and 6: plan 0026 1b's accept rule (median excess >= +1 pt, better in both halves,
                      worst 12 months not worse by > 5 pts, T1 tails not worse by > 0.10); test 6 also reports
                      how many later 3x-in-3y stocks the gate removed vs its share of the pond.

ROUND 2 (2026-10-16, the reviewer's second reply; diagnostics, no new pass bars except where stated):
  crash     name the worst 12-month window of top 30 vs the EW pond (arms A and B) and test the reviewer's
            momentum-crash reading: is it among the pond's best 12-month windows, and did the pond's bottom
            6-month-momentum quintile (at the window start) out-earn / triple more than in a typical window?
            Also: on every backtest path, when would the paper books' risk kill (rolling 12-month top 30 minus
            SMALLCAP 250 below −35 %) have fired, and what was the pond's 12-month return then.
  fundinc   the fundamental parts' increment on survivors: the thesis top 30 minus a price-only top 30 scored
            inside the same survivor pond (survivorship cancels to first order), with the reviewer's bias bound:
            every delisting at twice the full-market pond's rate lands in the top 30 at its observed loss.

Usage: python -m tools.mb_critique [ew dsr tails lag capacity livepond promoter cashgate crash fundinc]
       (default: the round-1 tests)
"""

import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools import mb_thesis as v1  # noqa: E402
from tools import mb_thesis_v2 as v2  # noqa: E402
from tools.lh_price_history import load  # noqa: E402

V2 = v2.V2
DB = PROJECT_ROOT / "data" / "alpha_signal.db"
HALVES = ((2016, 2020), (2021, 2026))
TRAIT_STUDY_TRIALS = 10
OLD_FUNNEL_TRIALS = 1
OUT = {}
_EXTRA_TRIALS = []          # monthly excess series of every 1d variant, for the DSR count


def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def say(*a):
    print(*a, flush=True)


# ─────────────────────────── shared state ───────────────────────────

_S = {}


def state():
    if not _S:
        P, _, _ = load()
        _S["P"], _S["PF"], _S["bench"] = P, P.ffill(), v2.bench_series()
        _S["panel"] = pd.read_parquet(V2 / "mb_thesis_panel.parquet")
        _S["df"] = v1.score(_S["panel"])
    return _S


def book(frame, sc, n=30, select=None, start_from=None, keep=True, **kw):
    s = state()
    ser = v2.simulate(frame, s["P"], sc, n=n, bench_daily=s["bench"], PF=s["PF"], select=select,
                      start_from=start_from, **kw)
    st, me = v2.evaluate(ser, s["bench"], HALVES if start_from is None else ((2020, 2022), (2023, 2026)))
    if keep:
        _EXTRA_TRIALS.append(me)
    return ser, st, me


def every(g, ranked, n):
    return ranked


# ─────────────────────────── tests ───────────────────────────

def paired(name, frame, sc):
    top, st_top, _ = book(frame, sc)
    ew, _, _ = book(frame, sc, n=5000, select=every)
    s = state()
    rows = []
    for k in top:
        a, b = top[k], ew[k].reindex(top[k].index)
        yrs = len(a) / 12
        ann = (a.iloc[::12].pct_change() - b.iloc[::12].pct_change()).dropna()
        bb = s["bench"].reindex(a.index).ffill()
        rows.append({"start": k, "top30": a.iloc[-1] ** (1 / yrs) - 1, "ew_pond": b.iloc[-1] ** (1 / yrs) - 1,
                     "smallcap250": (bb.iloc[-1] / bb.iloc[0]) ** (1 / yrs) - 1,
                     "t": ann.mean() / (ann.std() / math.sqrt(len(ann))),
                     "worst12_vs_pond": (a.pct_change(12) - b.pct_change(12)).min()})
    r = pd.DataFrame(rows)
    r["top_minus_pond"] = r["top30"] - r["ew_pond"]
    res = {"top30": r.top30.median(), "ew_pond": r.ew_pond.median(), "smallcap250": r.smallcap250.median(),
           "top_minus_pond": r.top_minus_pond.median(), "t": r.t.median(),
           "worst12_vs_pond": r.worst12_vs_pond.min(), "starts_beating_pond": int((r.top_minus_pond > 0).sum())}
    res["pass"] = bool(res["top_minus_pond"] >= 0.05 and res["t"] >= 1.5)
    say(f"  {name}: top30 {res['top30']:.1%} | EW pond {res['ew_pond']:.1%} | SMALLCAP250 {res['smallcap250']:.1%} | "
        f"top−pond {res['top_minus_pond']:+.1%} t {res['t']:.2f} | beats pond {res['starts_beating_pond']}/12 | "
        f"worst 12m vs pond {res['worst12_vs_pond']:+.1%} → {'PASS' if res['pass'] else 'FAIL'}")
    return res


def t_ew():
    say("\n== test 1: top 30 vs the equal-weight pond ==")
    df = state()["df"]
    a = df.copy()
    a["pond_b"] = a["pond_a"]
    OUT["ew"] = {"arm_B": paired("arm B survivors, full thesis", df, "score_b"),
                 "arm_A": paired("arm A full market incl. delisted, price-only", a, "score_a")}


def t_tails():
    say("\n== test 2: full-market tails (price-only, incl. delisted) ==")
    df = state()["df"]
    rows = []
    for a_, g in df[df["pond_a"].fillna(False).astype(bool) & df["y3"].notna()].groupby("anchor"):
        if a_[5:7] != "10" or len(g) < 100:
            continue
        top = g.nlargest(30, "score_a")
        r = {"anchor": a_, "pond": len(g)}
        for lab, thr in (("halve", 0.5), ("le03", 0.3)):
            base = (g["y3"] <= thr).mean()
            r[lab] = (top["y3"] <= thr).mean() / base if base > 0 else np.nan
        rows.append(r)
    t = pd.DataFrame(rows)
    res = {"anchors": len(t), "halve_lift": float(t["halve"].mean()), "le03_lift": float(t["le03"].mean()),
           "per_anchor": t.round(3).to_dict("records")}
    res["pass"] = bool(res["halve_lift"] <= 0.7)
    say(t.round(2).to_string(index=False))
    say(f"  halving lift {res['halve_lift']:.2f}, ≤0.3x lift {res['le03_lift']:.2f} over {res['anchors']} anchors "
        f"→ {'PASS' if res['pass'] else 'FAIL'} (bar ≤ 0.70)")
    OUT["tails"] = res


def t_capacity():
    say("\n== problem 3: capacity stress ==")
    df = state()["df"]
    base_inr = v2.BOOK_INR
    res = {}
    for mult in (1, 3, 10):
        v2.BOOK_INR = base_inr * mult
        _, st, _ = book(df, "score_b")
        res[f"x{mult}"] = {"book_inr": v2.BOOK_INR, "excess": st["excess"], "t": st["t"], "worst": st["worst"]}
        say(f"  book ₹{v2.BOOK_INR / 1e5:.0f} lakh: excess {st['excess']:+.1%} t {st['t']:.2f} worst {st['worst']:+.1%}")
    v2.BOOK_INR = base_inr
    res["pass"] = bool(res["x3"]["excess"] >= 0.05)
    say(f"  → {'PASS' if res['pass'] else 'FAIL'} (bar: ≥ +5 %/yr at 3×)")
    OUT["capacity"] = res


def t_lag():
    say("\n== test 4: quarterly look-ahead audit (Tickertape lag 60 → 90 days) ==")
    from signals import _quarterly
    import tools.lh_quarterly_nse as lq
    scratch = V2 / "mbc_lag90"
    scratch.mkdir(parents=True, exist_ok=True)
    old_lag, old_v2 = _quarterly.QUARTERLY_LAG, v1.V2
    _quarterly.QUARTERLY_LAG = 90
    if hasattr(lq, "QUARTERLY_LAG"):
        lq.QUARTERLY_LAG = 90
    v1.V2 = scratch
    try:
        panel90, _ = v1.build()
    finally:
        _quarterly.QUARTERLY_LAG, v1.V2 = old_lag, old_v2
    df90 = v1.score(panel90)
    _, st60, _ = book(state()["df"], "score_b")
    _, st90, _ = book(df90, "score_b")
    res = {"excess_lag60": st60["excess"], "excess_lag90": st90["excess"], "diff": st90["excess"] - st60["excess"],
           "worst_lag90": st90["worst"], "t_lag90": st90["t"]}
    res["pass"] = bool(abs(res["diff"]) <= 0.02)
    say(f"  lag 60: {st60['excess']:+.1%} | lag 90: {st90['excess']:+.1%} (t {st90['t']:.2f}, worst {st90['worst']:+.1%}) "
        f"→ {'PASS' if res['pass'] else 'FAIL'} (bar: within 2 points)")
    OUT["lag"] = res


def _live_mcaps(anchors):
    """Market cap per (anchor, sid) from the live source (scoring.segment tier inputs), raw loaded once."""
    import pit
    from datetime import timedelta
    raw = pit.load_raw(set(pit.TIER_INPUTS) | {"adjustments"})
    con = ro()
    out = []
    for a in anchors:
        t = pd.Timestamp(a).date()
        px = pd.read_sql("SELECT sid, date, close, volume FROM stock_prices WHERE close > 0 AND date <= ? AND date >= ?",
                         con, params=[t.isoformat(), (t - timedelta(days=100)).isoformat()])
        px = pit.apply_pit_adjustments(px.sort_values(["sid", "date"]), raw["adjustments"], t)
        ti = pit.tier_inputs(t, raw, px)
        out.append(ti[["sid", "mcap_cr"]].assign(anchor=a))
    con.close()
    return pd.concat(out, ignore_index=True)


def t_livepond():
    say("\n== finding 4.1: live-like pond (market cap from the live source) ==")
    s = state()
    panel = s["panel"].copy()
    anchors = sorted(a for a in panel["anchor"].unique() if a >= "2015-01-01")
    mc = _live_mcaps(anchors).rename(columns={"sid": "id", "mcap_cr": "mcap_live"})
    panel = panel.merge(mc, on=["id", "anchor"], how="left")
    old = panel["mcap_cr"].copy()
    have = panel["mcap_live"].notna()
    # cheapness ratios move with the market cap they divide by
    for c in ("bp", "sp", "ep"):
        panel.loc[have & old.notna(), c] = panel.loc[have & old.notna(), c] * old[have & old.notna()] / panel.loc[have & old.notna(), "mcap_live"]
    panel.loc[have, "mcap_cr"] = panel.loc[have, "mcap_live"]
    med = panel.groupby("anchor")["mcap_cr"].median()
    panel["mcap_max"] = panel["anchor"].map(v1.MCAP_MAX_CR * med / med.dropna().iloc[-1])
    df = v1.score(panel)
    sizes_old = s["df"][s["df"]["pond_b"].fillna(False).astype(bool)].groupby("anchor").size()
    sizes_new = df[df["pond_b"].fillna(False).astype(bool)].groupby("anchor").size()
    octs = [a for a in sizes_new.index if a[5:7] == "10"]
    say("  pond size (October anchors) old → live-like: " +
        ", ".join(f"{a[:4]} {int(sizes_old.get(a, 0))}→{int(sizes_new.get(a, 0))}" for a in octs))
    res = paired("live-like pond, full thesis", df, "score_b")
    res["pond_sizes"] = {a: [int(sizes_old.get(a, 0)), int(sizes_new.get(a, 0))] for a in octs}
    OUT["livepond"] = res


def _accept(st, base):
    return bool(st["excess"] - base["excess"] >= 0.01 and st["half1"] > base["half1"] and st["half2"] > base["half2"]
                and st["worst"] - base["worst"] >= -0.05)


def t_promoter():
    say("\n== test 5: promoter overlay (2020+) ==")
    df = state()["df"].copy()
    con = ro()
    pit = pd.read_sql("SELECT sid, snapshot_date, promoter_trend_4q FROM daily_snapshots_pit "
                      "WHERE snapshot_date >= '2019-12-01' AND promoter_trend_4q IS NOT NULL", con)
    con.close()
    df["promoter_trend_4q"] = v2.asof_join(df, pit, ["promoter_trend_4q"])["promoter_trend_4q"].values
    df["sc_base"] = v2.scored(df, "sc_base", parts=v1.PARTS)
    df["sc_prom"] = v2.scored(df, "sc_prom", parts=v1.PARTS, extras=("promoter_trend_4q",))
    _, b, _ = book(df, "sc_base", start_from="2020-01-01")
    _, x, _ = book(df, "sc_prom", start_from="2020-01-01")
    res = {"base": b, "with_promoter": x, "accept": _accept(x, b)}
    say(f"  base {b['excess']:+.1%} (h {b['half1']:+.1%}/{b['half2']:+.1%}, worst {b['worst']:+.1%}) | "
        f"+promoter {x['excess']:+.1%} (h {x['half1']:+.1%}/{x['half2']:+.1%}, worst {x['worst']:+.1%}) → "
        f"{'ACCEPT' if res['accept'] else 'reject'}")
    OUT["promoter"] = res


def _cash_features():
    items = ["Cash from Operating Activity", "Profit before tax", "Interest", "Depreciation", "Other Income",
             "Sales", "Trade receivables", "Receivables"]
    con = ro()
    q = ("SELECT sid, period_end, line_item, value FROM fundamentals_screener WHERE period_type='annual' "
         f"AND line_item IN ({','.join('?' * len(items))})")
    f = pd.read_sql(q, con, params=items)
    con.close()
    w = f.pivot_table(index=["sid", "period_end"], columns="line_item", values="value", aggfunc="last").reset_index()
    w = w.sort_values(["sid", "period_end"])
    rec = w["Trade receivables"].fillna(w.get("Receivables"))
    w["ebitda"] = w["Profit before tax"] + w["Interest"].fillna(0) + w["Depreciation"].fillna(0) - w["Other Income"].fillna(0)
    g = w.groupby("sid")
    cfo3 = g["Cash from Operating Activity"].transform(lambda s: s.rolling(3, min_periods=3).sum())
    eb3 = g["ebitda"].transform(lambda s: s.rolling(3, min_periods=3).sum())
    w["cfo_ebitda_3y"] = np.where(eb3 > 0, cfo3 / eb3, np.nan)
    w["rec_days"] = np.where(w["Sales"] > 0, rec / w["Sales"] * 365, np.nan)
    w["rec_days_chg"] = w["rec_days"] - g["rec_days"].shift(1)
    w["snapshot_date"] = (pd.to_datetime(w["period_end"]) + pd.Timedelta(days=v1.ANNUAL_LAG)).dt.strftime("%Y-%m-%d")
    return w[["sid", "snapshot_date", "cfo_ebitda_3y", "rec_days_chg"]]


def t_cashgate():
    say("\n== test 6: cash-conversion gate ==")
    df = state()["df"].copy()
    cf = _cash_features()
    df[["cfo_ebitda_3y", "rec_days_chg"]] = v2.asof_join(df, cf, ["cfo_ebitda_3y", "rec_days_chg"]).values
    pond = df["pond_b"].fillna(False).astype(bool)
    q_lo = df[pond].groupby("anchor")["cfo_ebitda_3y"].transform(lambda s: s.quantile(0.10))
    q_hi = df[pond].groupby("anchor")["rec_days_chg"].transform(lambda s: s.quantile(0.90))
    fail = pd.Series(False, index=df.index)
    fail.loc[q_lo.index] = (df.loc[q_lo.index, "cfo_ebitda_3y"] < q_lo) | (df.loc[q_hi.index, "rec_days_chg"] > q_hi)
    gated = df.copy()
    gated.loc[fail, "pond_b"] = False
    # the gate removes names; the survivors keep their pond percentiles (the score is not refitted)
    gated["sc"] = gated["score_b"].where(~fail)
    _, b, _ = book(df, "score_b")
    _, x, _ = book(gated, "sc")
    lab = df[pond & df["y3"].notna()]
    w3 = lab["y3"] >= 3
    removed = fail.loc[lab.index]
    res = {"base": b, "gated": x, "accept": _accept(x, b),
           "share_of_pond_removed": float(removed.mean()), "share_of_3x_removed": float(removed[w3].mean()),
           "n_3x_removed": int(removed[w3].sum()), "n_3x": int(w3.sum())}
    say(f"  base {b['excess']:+.1%} | gated {x['excess']:+.1%} (h {x['half1']:+.1%}/{x['half2']:+.1%}, worst {x['worst']:+.1%}) "
        f"→ {'ACCEPT' if res['accept'] else 'reject'}; gate removes {res['share_of_pond_removed']:.0%} of the pond and "
        f"{res['n_3x_removed']} of {res['n_3x']} later 3x stocks ({res['share_of_3x_removed']:.0%})")
    OUT["cashgate"] = res


def t_dsr():
    say("\n== test 3: honest deflated Sharpe ==")
    from tools.lh_book import deflated_sharpe
    from tools.lh_luck import n_effective
    M = pd.read_parquet(V2 / "mb2_monthly_excess.parquet")
    trials = [M[c] for c in M.columns] + _EXTRA_TRIALS
    n_counted = 4 + M.shape[1] + 6 + len(_EXTRA_TRIALS) + OLD_FUNNEL_TRIALS + TRAIT_STUDY_TRIALS
    X = pd.concat(trials, axis=1).dropna(how="all")
    X.columns = range(X.shape[1])
    srs = (X.mean() / X.std()).values
    x = M["v1"].dropna()
    T = len(x)
    n_eff = n_effective(X.dropna())[0]
    a = deflated_sharpe(x, srs, n_counted)
    b = deflated_sharpe(x, srs, max(int(round(n_eff)), 2))
    c_sr = x.mean() / x.std(ddof=1)
    g = 0.5772156649
    sr0 = math.sqrt(1 / (T - 1)) * ((1 - g) * stats.norm.ppf(1 - 1 / n_counted) + g * stats.norm.ppf(1 - 1 / (n_counted * math.e)))
    sk, ku = stats.skew(x), stats.kurtosis(x, fisher=False)
    c = float(stats.norm.cdf((c_sr - sr0) * math.sqrt(T - 1) / math.sqrt(max(1 - sk * c_sr + (ku - 1) / 4 * c_sr ** 2, 1e-12))))
    res = {"T_months": T, "n_trials_counted": n_counted, "n_effective": n_eff, "sr_monthly": float(c_sr),
           "sd_trial_sr": float(np.std(srs, ddof=1)), "skew": float(sk), "kurtosis": float(ku),
           "dsr_observed_var_N": a[0], "dsr_observed_var_Neff": b[0], "dsr_null_var_N": c, "sr0_null": sr0}
    res["pass"] = bool(c >= 0.90)
    say(f"  T {T} months, monthly SR {c_sr:.3f} (annualised {c_sr * math.sqrt(12):.2f}), skew {sk:.2f}, kurtosis {ku:.2f}")
    say(f"  trials counted {n_counted} (N_eff {n_eff:.1f}); sd of trial SRs {res['sd_trial_sr']:.3f} vs null sd {math.sqrt(1 / (T - 1)):.3f}")
    say(f"  DSR (a) observed var, N {a[0]:.3f} | (b) observed var, N_eff {b[0]:.3f} | (c) null var, N {c:.3f} "
        f"→ {'PASS' if res['pass'] else 'FAIL'} (bar (c) ≥ 0.90)")
    OUT["dsr"] = res


def _paths(frame, sc):
    top, _, _ = book(frame, sc, keep=False)
    ew, _, _ = book(frame, sc, n=5000, select=every, keep=False)
    return top, ew


def _fwd12(P, a, ids):
    dates = P.index
    i = dates.get_loc(a)
    end = str((pd.Timestamp(a) + pd.DateOffset(years=1)).date())
    k = int(np.searchsorted(dates, end))
    fut = P.iloc[i + 1:k + 1][ids]
    return fut.ffill().iloc[-1] / fut.iloc[0]


def t_crash():
    say("\n== round 2: the worst 12 months vs the pond — momentum crash? ==")
    s = state()
    df, P, bench = s["df"], s["P"], s["bench"]
    a = df.copy()
    a["pond_b"] = a["pond_a"]
    res = {}
    for arm, frame, sc in (("A full market, price-only", a, "score_a"), ("B survivors, thesis", df, "score_b")):
        top, ew = _paths(frame, sc)
        worst = []
        for k in top:
            t, p = top[k], ew[k].reindex(top[k].index)
            r = (t.pct_change(12) - p.pct_change(12)).dropna()
            worst.append((r.min(), r.idxmin(), k, p.pct_change(12).loc[r.idxmin()], p.pct_change(12).dropna()))
        w, end, start_k, pond12, pond_all = min(worst, key=lambda x: x[0])
        months = list(top[start_k].index)
        begin = months[months.index(end) - 12]
        pond_rank = float((pond_all <= pond12).mean())            # 1.0 = the pond's best 12 months on that path
        g = frame[(frame["anchor"] == begin) & frame["pond_b"].fillna(False).astype(bool)].set_index("id")
        q = pd.qcut(g["mom_6m"].rank(method="first"), 5, labels=False)
        f = _fwd12(P, begin, list(g.index))
        by_q = {int(k_): {"median_12m": float(f[q == k_].median() - 1), "share_2x": float((f[q == k_] >= 2).mean()),
                          "share_3x": float((f[q == k_] >= 3).mean())} for k_ in range(5)}
        typ = []                                                  # the bottom quintile's 12-month median in every window
        for b_ in sorted(x for x in frame["anchor"].unique() if x[5:7] in ("01", "04", "07", "10")):
            gg = frame[(frame["anchor"] == b_) & frame["pond_b"].fillna(False).astype(bool)].set_index("id")
            if len(gg) < 100 or str((pd.Timestamp(b_) + pd.DateOffset(years=1)).date()) > P.index[-1]:
                continue
            qq = pd.qcut(gg["mom_6m"].rank(method="first"), 5, labels=False)
            ff = _fwd12(P, b_, list(gg.index))
            typ.append(float(ff[qq == 0].median() - 1) - float(ff[qq == 4].median() - 1))
        spread = by_q[0]["median_12m"] - by_q[4]["median_12m"]
        kills = []                                                # the paper books' risk kill on every path
        for k in top:
            t = top[k]
            bb = bench.reindex(t.index).ffill()
            ex = (t.pct_change(12) - bb.pct_change(12)).dropna()
            pp = ew[k].reindex(t.index).pct_change(12)
            for d in ex[ex < -0.35].index:
                kills.append({"start": k, "month": d, "excess_vs_index": float(ex[d]), "pond_12m": float(pp[d])})
        res[arm] = {"worst_vs_pond": float(w), "window": [begin, end], "start": start_k, "pond_12m": float(pond12),
                    "pond_12m_rank_on_path": pond_rank, "momentum_quintiles_12m": by_q,
                    "bottom_minus_top_quintile": spread, "bottom_minus_top_typical_median": float(np.median(typ)),
                    "bottom_minus_top_typical_p90": float(np.quantile(typ, 0.9)), "risk_kill_firings": kills}
        say(f"  {arm}: worst {w:+.1%} vs pond, window {begin} → {end} (start {start_k}); pond +{pond12:.0%} "
            f"(percentile {pond_rank:.0%} of that path's 12-month windows)")
        say(f"    pond by 6-month-momentum quintile at {begin}: " + ", ".join(
            f"Q{k_ + 1} {v['median_12m']:+.0%} ({v['share_3x']:.0%} tripled)" for k_, v in by_q.items()))
        say(f"    bottom − top quintile {spread:+.0%} vs typical {np.median(typ):+.0%} (90th pct {np.quantile(typ, 0.9):+.0%})")
        months_k = sorted({x['month'] for x in kills})
        say(f"    risk kill (top 30 − SMALLCAP 250 < −35 %) fires in {len(kills)} path-months: "
            + (", ".join(f"{m}" for m in months_k[:8]) or "never")
            + (f"; pond 12m then {np.median([x['pond_12m'] for x in kills]):+.0%} (median)" if kills else ""))
    OUT["crash"] = res


def t_fundinc():
    say("\n== round 2: the fundamental parts' increment on survivors ==")
    s = state()
    df = s["df"].copy()
    pond = df["pond_b"].fillna(False).astype(bool) & df["score_b"].notna()
    pr = pd.Series(np.nan, index=df.index)
    for _, g in df[pond].groupby("anchor"):
        pr.loc[g.index] = ((v1.pct(-np.log(g["adtv"])) + v1.pct(g["mom_6m"]) + v1.pct(g["pos_52w"])) / 3).values
    df["sc_price_surv"] = pr
    th, _, _ = book(df, "score_b", keep=False)
    po, _, _ = book(df, "sc_price_surv", keep=False)
    rows = []
    for k in th:
        a_, b_ = th[k], po[k].reindex(th[k].index)
        yrs = len(a_) / 12
        ann = (a_.iloc[::12].pct_change() - b_.iloc[::12].pct_change()).dropna()
        rows.append({"start": k, "thesis": a_.iloc[-1] ** (1 / yrs) - 1, "price_only": b_.iloc[-1] ** (1 / yrs) - 1,
                     "t": ann.mean() / (ann.std() / math.sqrt(len(ann)))})
    r = pd.DataFrame(rows)
    r["inc"] = r["thesis"] - r["price_only"]
    # the reviewer's bound: delistings at 2x the full-market pond's yearly rate, each at its observed loss
    full = s["df"][s["df"]["pond_a"].fillna(False).astype(bool) & s["df"]["stopped3"].notna()]
    yearly_rate = 1 - (1 - full["stopped3"].mean()) ** (1 / 3)
    dead = full[full["stopped3"] == 1]
    loss = float(1 - dead["y3"].median()) if len(dead) else 1.0
    bound = 2 * yearly_rate * loss
    res = {"thesis": float(r.thesis.median()), "price_only_survivors": float(r.price_only.median()),
           "increment": float(r.inc.median()), "t": float(r.t.median()), "starts_positive": int((r.inc > 0).sum()),
           "delist_rate_per_year": float(yearly_rate), "delist_median_loss": loss, "bias_bound_per_year": float(bound),
           "increment_after_bound": float(r.inc.median() - bound)}
    say(f"  thesis {res['thesis']:.1%} | price-only on the same survivors {res['price_only_survivors']:.1%} | "
        f"increment {res['increment']:+.1%}/yr (t {res['t']:.2f}, {res['starts_positive']}/12 starts positive)")
    say(f"  bias bound: full-market pond delists {yearly_rate:.1%}/yr at a median loss of {loss:.0%}; ×2 into the top 30 "
        f"→ −{bound:.1%}/yr; increment after the bound {res['increment_after_bound']:+.1%}/yr")
    OUT["fundinc"] = res


TESTS = {"ew": t_ew, "tails": t_tails, "capacity": t_capacity, "lag": t_lag, "livepond": t_livepond,
         "promoter": t_promoter, "cashgate": t_cashgate, "dsr": t_dsr, "crash": t_crash, "fundinc": t_fundinc}
ROUND1 = ["ew", "tails", "capacity", "lag", "livepond", "promoter", "cashgate", "dsr"]


def main():
    want = sys.argv[1:] or ROUND1
    for k in want:                                           # dsr last: it counts every variant run before it
        if k != "dsr":
            TESTS[k]()
    if "dsr" in want:
        t_dsr()
    name = "mbc_results.json" if set(want) & set(ROUND1) else "mbc_round2.json"
    pd.Series(OUT, dtype=object).to_json(V2 / name, default_handler=str)
    say(f"\nwrote {V2 / name}")


if __name__ == "__main__":
    main()
