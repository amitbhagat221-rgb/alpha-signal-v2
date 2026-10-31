"""
Day / night return factors, results-filing timing and the ASM price trigger — 2026-10 study
(research 0009 S1 S2 S3 F6, research 0010 P2 P3 G1: the candidates that need no minute bars).

READ-ONLY: db.read_sql only; no table writes, no network, no factor registered.

Returns per stock-day from daily prices (split/bonus-adjusted with the live adjustment code):
  intraday  = ln(close / open)                          (same-day ratio, unaffected by adjustment)
  overnight = ln(adj_close_t / adj_close_t-1) − intraday (previous close → today's open)

Pre-registered before the run (formula, sign, horizon fixed in research 0009 / 0010):
  mom_intraday_12_1    Σ intraday, sessions t−252 … t−22              sign +
  mom_overnight_12_1   Σ overnight, same window                        two-sided (US −, India no reversal)
  tug_of_war_3m        share of last 63 sessions with overnight > 0 and intraday < 0     sign +
  overnight_ret_1m     mean overnight, last 21 sessions                sign + (India prior)
  day_night_beta_gap   β(stock intraday on NIFTY 50 intraday) − β(overnight on overnight), 252 sessions
                       two-sided (the paper's long leg was not available)
  ann_in_session       results filed 09:15–15:30 on a trading day vs outside: drift after the reaction day,
                       20 sessions, tier-adjusted          two-sided (US −)
  asm_up_flag          any of the last 5 sessions with 5-day return − NIFTY 50 5-day return ≥ +25 %
                       (the short-term ASM price trigger; the client-concentration leg is not observable)
                       flagged names underperform within tier

Evidence: the backtest's own engine (tools.backtest_pit._compute_ic / _aggregate), monthly anchors of
daily_snapshots_pit, point-in-time cap tier, panel label fwd_return_20d. The survivorship check rebuilds
the same factors on everything that traded (stock_prices_unlisted) with its own 20-session label, split by
90-day traded value like tools/survivorship_study.py.

Usage:  python -m tools.day_night_study [--md PATH]
"""
import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import factors
import pit
from db import read_sql
from signals._prices import apply_adjustments
from tools import backtest_pit as bp
from tools.ownership_flow_study import max_corr_wired, wired_cols
from tools.survivorship_study import _unlisted_prices

TIERS3 = ["LARGE", "MID", "SMALL"]
SIGNS = {"mom_intraday_12_1": 1, "mom_overnight_12_1": 0, "tug_of_war_3m": 1, "overnight_ret_1m": 1,
         "day_night_beta_gap": 0}
CANDIDATES = list(SIGNS)
BAR, BONFERRONI = 2.5, 4.2
TRADEABLE_CR = 1.0
ASM_GAP = 0.25


# ── prices → wide day/night return matrices ────────────────────────────────────────────────
def _prices():
    raw = pit.load_raw({"adjustments"})
    u = read_sql("SELECT sid, date, open, close, volume FROM stock_prices WHERE close > 0 ORDER BY sid, date")
    u = apply_adjustments(u, raw["adjustments"], date.max)
    _, uadj = _unlisted_prices()
    x = read_sql("SELECT '~' || symbol AS sid, date, open, close, volume FROM stock_prices_unlisted "
                 "WHERE close > 0 AND series IN ('EQ', 'BE', 'BZ', 'SM', 'ST') ORDER BY symbol, date")
    x = apply_adjustments(x.drop_duplicates(["sid", "date"]), uadj, date.max)
    px = pd.concat([u, x], ignore_index=True)
    px["date"] = pd.to_datetime(px["date"])
    return px


def _wide(px):
    W = {k: px.pivot(index="date", columns="sid", values=k) for k in ("open", "close", "adj_close", "volume")}
    adj = W["adj_close"]
    prev = adj.ffill(limit=5).shift(1)            # previous close of the same stock, at most 6 sessions back
    total = np.log(adj / prev)
    o = W["open"].where(W["open"] > 0)
    intra = np.log(W["close"] / o)
    intra = intra.where(intra.abs() < 0.5)
    over = (total - intra).where((total - intra).abs() < 0.5)
    value = (W["close"] * W["volume"]) / 1e7                                       # ₹ crore traded
    return dict(adj=adj, intra=intra, over=over, value=value)


def _nifty(dates):
    n = read_sql("SELECT trade_date, open, close FROM nse_index_history WHERE index_symbol = 'NIFTY 50' ORDER BY trade_date")
    n["date"] = pd.to_datetime(n["trade_date"])
    n = n.set_index("date").reindex(dates)
    intra = np.log(n["close"] / n["open"])
    over = np.log(n["open"] / n["close"].shift(1))
    ret5 = n["close"] / n["close"].shift(5) - 1
    return intra, over, ret5


# ── factors at one anchor ──────────────────────────────────────────────────────────────────
def _beta(y, x):
    """column-wise OLS slope of y (T×N) on x (T), pairwise-complete, ≥ 150 obs."""
    m = y.notna() & x.notna().values[:, None]
    xv = np.where(m, x.values[:, None], np.nan)
    yv = y.where(m).values
    xm, ym = np.nanmean(xv, 0), np.nanmean(yv, 0)
    cov = np.nansum((xv - xm) * (yv - ym), 0)
    var = np.nansum((xv - xm) ** 2, 0)
    b = cov / np.where(var > 0, var, np.nan)
    return pd.Series(np.where(m.sum(0).values >= 150, b, np.nan), index=y.columns)


def factors_at(W, mkt, i):
    """All candidates using sessions up to and including row i (the anchor's last close)."""
    intra, over = W["intra"], W["over"]
    win = slice(max(0, i - 251), i + 1)
    I12, O12 = intra.iloc[max(0, i - 251): i - 20], over.iloc[max(0, i - 251): i - 20]
    I63, O63 = intra.iloc[max(0, i - 62): i + 1], over.iloc[max(0, i - 62): i + 1]
    O21 = over.iloc[max(0, i - 20): i + 1]
    f = pd.DataFrame({
        "mom_intraday_12_1": I12.sum(min_count=150),
        "mom_overnight_12_1": O12.sum(min_count=150),
        "mom_total_12_1": (I12 + O12).sum(min_count=150),          # reference: the two halves together
        "tug_of_war_3m": ((O63 > 0) & (I63 < 0)).where(O63.notna() & I63.notna()).mean().where(
            (O63.notna() & I63.notna()).sum() >= 40),
        "overnight_ret_1m": O21.mean().where(O21.notna().sum() >= 15),
    })
    mi, mo, _ = mkt
    f["day_night_beta_gap"] = _beta(intra.iloc[win], mi.iloc[win]) - _beta(over.iloc[win], mo.iloc[win])
    v = W["value"].iloc[max(0, i - 62): i + 1]
    f["adtv_cr"] = v.mean()
    return f


def asm_gap(W, mkt):
    """5-session stock return − NIFTY 50 5-session return, every stock-day (computed once)."""
    adj = W["adj"]
    return (adj / adj.shift(5) - 1).sub(mkt[2], axis=0)


def asm_flag_at(G, i):
    gap = G.iloc[max(0, i - 4): i + 1]
    up = (gap >= ASM_GAP).any().where(gap.notna().any())
    dn = (gap <= -ASM_GAP).any().where(gap.notna().any())
    return pd.DataFrame({"asm_up_flag": up.astype(float), "asm_down_flag": dn.astype(float)})


def own_label(W, i):
    """20-session return from the first close after the anchor; a series that ends inside the window
    exits at its last close (a delisting is a return)."""
    adj = W["adj"]
    if i + 21 >= len(adj):
        return pd.Series(np.nan, index=adj.columns)
    entry = adj.iloc[i + 1]
    fut = adj.iloc[i + 1: i + 22]
    exit_ = fut.iloc[-1].fillna(fut.ffill().iloc[-1])
    return exit_ / entry - 1


# ── evaluation ─────────────────────────────────────────────────────────────────────────────
def ic_table(P, sigs, group_col, groups, label="fwd_return_20d"):
    dates = sorted(P["snapshot_date"].unique())
    split = dates[len(dates) // 2]
    rows = []
    for sig in sigs:
        for g in groups:
            d = P[P[group_col] == g]
            ics = bp._compute_ic(d, sig, label)
            agg = bp._aggregate(ics, sig, g, "day_night_study") if ics else None
            if not agg:
                rows.append(dict(signal=sig, group=g, n=0))
                continue
            ic = pd.Series({e: v for e, v, _ in ics})
            h1, h2 = ic[ic.index < split], ic[ic.index >= split]
            rows.append(dict(signal=sig, group=g, n=agg["n_periods"], stocks=agg["n_stocks_avg"],
                             mean_ic=agg["mean_ic"], t=agg["t_stat"], ic_h1=h1.mean(), ic_h2=h2.mean(),
                             halves=bool(np.sign(h1.mean()) == np.sign(h2.mean()) == np.sign(ic.mean())
                                         and len(h1) >= 6 and len(h2) >= 6)))
    return pd.DataFrame(rows), split


def verdict(sig, r, corr):
    if r["n"] < 36:
        return "INSUFFICIENT (n<36)"
    s = SIGNS[sig]
    if s and np.sign(r["mean_ic"]) != s and abs(r["t"]) >= 1.5:
        return "WRONG SIGN"
    if abs(r["t"]) >= BAR and r["halves"] and not (pd.notna(corr) and abs(corr) >= 0.5):
        return "KEEP" + (" (clears Bonferroni)" if abs(r["t"]) >= BONFERRONI else "") + (" — two-sided" if not s else "")
    return "WEAK" if abs(r["t"]) >= 1.5 else "DROP"


def gate_table(P, flag, groups, group_col, label):
    """per anchor: mean label of flagged − unflagged within group; t across anchors with ≥ 3 flagged."""
    out = []
    for g in groups:
        d = P[(P[group_col] == g) & P[label].notna() & P[flag].notna()]
        diffs, nflag = [], []
        for _, a in d.groupby("snapshot_date"):
            f = a[a[flag] == 1]
            if len(f) >= 3 and (a[flag] == 0).sum() >= 20:
                diffs.append(f[label].mean() - a.loc[a[flag] == 0, label].mean())
                nflag.append(len(f))
        if len(diffs) < 6:
            out.append(dict(flag=flag, group=g, anchors=len(diffs)))
            continue
        x = np.array(diffs)
        out.append(dict(flag=flag, group=g, anchors=len(x), flagged_avg=float(np.mean(nflag)),
                        diff_20d=float(x.mean()), t=float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))),
                        hit=float((x < 0).mean())))
    return pd.DataFrame(out)


def incremental(P, sig, controls):
    """IC of `sig` after removing, per anchor and tier, its rank-linear fit on each control (one at a
    time, then all together): does it add to the momentum we already have?"""
    rows = []
    for ctl in [[c] for c in controls if c in P.columns] + [[c for c in controls if c in P.columns]]:
        for tier in TIERS3:
            parts = []
            for d, g in P[P.cap_tier == tier].groupby("snapshot_date"):
                g = g[["sid", "snapshot_date", sig, "fwd_return_20d"] + ctl].dropna()
                if len(g) < 30:
                    continue
                y = g[sig].rank(pct=True).values
                X = np.column_stack([np.ones(len(g))] + [g[c].rank(pct=True).values for c in ctl])
                g = g.assign(resid=y - X @ np.linalg.lstsq(X, y, rcond=None)[0])
                parts.append(g)
            Q = pd.concat(parts)
            agg = bp._aggregate(bp._compute_ic(Q, "resid", "fwd_return_20d"), sig, tier, "incr")
            rows.append(dict(signal=sig, net_of=" + ".join(ctl), tier=tier, n=agg["n_periods"],
                             mean_ic=agg["mean_ic"], t=agg["t_stat"]))
    return pd.DataFrame(rows)


def down_flag_robustness(F):
    """asm_down_flag on everything that traded: universe only vs delisted only, without the 2020 crash
    months, and the median instead of the mean."""
    rows = []
    for name, mask in (("everything", F["sid"].notna()), ("universe only", ~F["outside"]),
                       ("everything, excl. 2020-03…2020-05", ~F["snapshot_date"].between("2020-03-01", "2020-05-31"))):
        g = gate_table(F[mask], "asm_down_flag", ["tradeable", "thin"], "bucket", "own_fwd_20d")
        g["sample"] = name
        rows.append(g)
    T = pd.concat(rows, ignore_index=True)
    fl = F[(F["asm_down_flag"] == 1) & F["own_fwd_20d"].notna()]
    T.attrs["flagged"] = dict(n=len(fl), outside_share=float(fl["outside"].mean()),
                              median=float(fl["own_fwd_20d"].median()), mean=float(fl["own_fwd_20d"].mean()),
                              median_unflagged=float(F.loc[F["asm_down_flag"] == 0, "own_fwd_20d"].median()))
    return T


# ── results-filing timing (event study) ────────────────────────────────────────────────────
def filing_timing(W, tiers):
    f = read_sql("SELECT sid, dt_tm FROM bse_announcements WHERE sid IS NOT NULL AND dt_tm IS NOT NULL AND "
                 + factors.RESULT_FILING_SQL)
    f["ts"] = pd.to_datetime(f["dt_tm"].str[:19], errors="coerce")
    f = f.dropna(subset=["ts"]).sort_values(["sid", "ts"])
    keep, last = [], {}
    for sid, ts in zip(f["sid"], f["ts"]):                       # first results filing per 30-day cluster
        if sid not in last or (ts - last[sid]).days > 30:
            keep.append(True)
            last[sid] = ts
        else:
            keep.append(False)
    f = f[keep]
    adj = W["adj"]
    dates = adj.index
    pos = {d: k for k, d in enumerate(dates)}
    tier_mean = {}
    rows = []
    for sid, ts in zip(f["sid"], f["ts"]):
        if sid not in adj.columns:
            continue
        day = ts.normalize()
        s = adj[sid]
        traded_today = day in pos and pd.notna(s.iloc[pos[day]])
        hm = ts.strftime("%H:%M")
        in_sess = traded_today and "09:15" <= hm < "15:30"
        if in_sess or (traded_today and hm < "09:15"):
            k = pos[day]
        else:
            k = int(dates.searchsorted(day, side="right"))           # first session after the filing day
        if k < 1 or k + 20 >= len(dates):
            continue
        p0, pR, p20 = s.iloc[k - 1], s.iloc[k], s.iloc[k + 20]
        if not (pd.notna(p0) and pd.notna(pR) and pd.notna(p20)):
            continue
        tier = tiers.get((sid, dates[k].strftime("%Y-%m")))
        if tier is None:
            continue
        rows.append(dict(sid=sid, ts=ts, k=k, tier=tier, in_session=in_sess,
                         reaction=np.log(pR / p0), drift=np.log(p20 / pR)))
    E = pd.DataFrame(rows)
    # tier-adjust: subtract the equal-weight mean of the same tier's stocks over the same 20 sessions
    fwd = np.log(adj.shift(-20) / adj)
    tier_of = {}
    for (sid, ym), t in tiers.items():
        tier_of.setdefault(ym, {})[sid] = t
    bench = {}
    for k in E["k"].unique():
        ym = dates[k].strftime("%Y-%m")
        m = pd.Series(tier_of.get(ym, {}))
        r = fwd.iloc[k].reindex(m.index)
        bench[k] = r.groupby(m).mean().to_dict()
    E["drift_ab"] = E["drift"] - [bench[k].get(t, np.nan) for k, t in zip(E["k"], E["tier"])]
    E["month"] = E["ts"].dt.to_period("M")
    out = []
    for tier in TIERS3 + ["ALL"]:
        d = E if tier == "ALL" else E[E["tier"] == tier]
        for name, col in (("drift (tier-adjusted)", d["drift_ab"]),
                          ("drift × sign(reaction)", d["drift_ab"] * np.sign(d["reaction"])),
                          ("reaction day", d["reaction"])):
            g = pd.DataFrame({"m": d["month"], "ins": d["in_session"], "v": col}).dropna()
            per = g.groupby(["m", "ins"])["v"].mean().unstack()
            per = per.dropna()
            x = (per[True] - per[False]) if True in per and False in per else pd.Series(dtype=float)
            out.append(dict(tier=tier, measure=name, events=len(g), in_session_share=float(g["ins"].mean()),
                            mean_in=float(g.loc[g["ins"], "v"].mean()), mean_out=float(g.loc[~g["ins"], "v"].mean()),
                            months=len(x), diff=float(x.mean()) if len(x) else np.nan,
                            t=float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 5 else np.nan))
    return pd.DataFrame(out), E


# ── run ────────────────────────────────────────────────────────────────────────────────────
def run():
    px = _prices()
    W = _wide(px)
    mkt = _nifty(W["adj"].index)
    print(f"prices: {W['adj'].shape[1]} symbols, {W['adj'].shape[0]} sessions", file=sys.stderr)
    wired = sorted({c for cs in wired_cols().values() for c in cs} | {"mom_6m", "st_reversal_21d", "max_lottery_21d",
                                                                         "low_vol_252d", "kyle_lambda"})
    cols = ["sid", "snapshot_date", "cap_tier", "fwd_return_20d"] + wired
    have = set(read_sql("SELECT * FROM daily_snapshots_pit LIMIT 1").columns)
    cols = [c for c in cols if c in have]
    panel = read_sql("SELECT " + ", ".join(cols) + " FROM daily_snapshots_pit "
                     "WHERE cap_tier IN ('LARGE','MID','SMALL') AND fwd_return_20d IS NOT NULL")
    panel["dt"] = pd.to_datetime(panel["snapshot_date"])
    panel = panel[panel["dt"].map(bp._is_month_start_anchor)].copy()
    dates = W["adj"].index
    G = asm_gap(W, mkt)
    full = []
    for a in sorted(panel["dt"].unique()):
        i = int(dates.searchsorted(a, side="right")) - 1           # last session on or before the anchor
        f = factors_at(W, mkt, i).join(asm_flag_at(G, i))
        f["own_fwd_20d"] = own_label(W, i)
        f["snapshot_date"] = pd.Timestamp(a).strftime("%Y-%m-%d")
        f.index.name = "sid"
        f = f.reset_index()
        live = W["adj"].iloc[max(0, i - 7): i + 1].notna().any()   # traded in the last week
        f = f[f["sid"].map(live)]
        full.append(f)
    F = pd.concat(full, ignore_index=True)
    P = panel.merge(F.drop(columns=["own_fwd_20d"]), on=["sid", "snapshot_date"], how="left")

    ic, split = ic_table(P, CANDIDATES, "cap_tier", TIERS3)
    corr = {(s, t): max_corr_wired(P, s, t, {t: [c for c in wired if c in P.columns] for t in TIERS3})
            for s in CANDIDATES for t in TIERS3}
    ic["max_corr"] = [corr[(s, t)][0] for s, t in zip(ic["signal"], ic["group"])]
    ic["max_corr_with"] = [corr[(s, t)][1] for s, t in zip(ic["signal"], ic["group"])]
    ic["verdict"] = [verdict(s, r, c) if r["n"] else "no data" for s, r, c in
                     zip(ic["signal"], ic.to_dict("records"), ic["max_corr"])]
    # correlation with mom_6m specifically (S1/S2 decompose it)
    mom = {(s, t): np.nanmean([g[[s, "mom_6m"]].corr("spearman").iloc[0, 1]
                               for _, g in P[P.cap_tier == t].groupby("snapshot_date") if g[[s, "mom_6m"]].dropna().shape[0] >= 20])
           for s in CANDIDATES for t in TIERS3} if "mom_6m" in P.columns else {}
    ic["corr_mom_6m"] = [mom.get((s, t), np.nan) for s, t in zip(ic["signal"], ic["group"])]

    # survivorship: universe only vs everything that traded, own label, by traded value
    F["outside"] = F["sid"].str.startswith("~")
    F["bucket"] = np.where(F["adtv_cr"] >= TRADEABLE_CR, "tradeable", "thin")
    surv = []
    for scope, sub in (("universe only", F[~F["outside"]]), ("everything that traded", F)):
        t_, _ = ic_table(sub, CANDIDATES, "bucket", ["tradeable", "thin"], label="own_fwd_20d")
        t_["scope"] = scope
        surv.append(t_)
    surv = pd.concat(surv, ignore_index=True)

    # ASM gate: panel tiers (survivors) and full market (own label)
    gate = pd.concat([gate_table(P, fl, TIERS3, "cap_tier", "fwd_return_20d") for fl in ("asm_up_flag", "asm_down_flag")])
    gate_full = pd.concat([gate_table(F, fl, ["tradeable", "thin"], "bucket", "own_fwd_20d")
                           for fl in ("asm_up_flag", "asm_down_flag")])
    # does the flag add beyond max_lottery? matched: flagged vs unflagged inside the top max_lottery quintile
    if "max_lottery_21d" in P.columns:
        P["lot_q"] = P.groupby(["snapshot_date", "cap_tier"])["max_lottery_21d"].transform(
            lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) if s.notna().sum() >= 25 else np.nan)
        Q = P[P["lot_q"] == 4]
        gate_lot = gate_table(Q, "asm_up_flag", TIERS3, "cap_tier", "fwd_return_20d")
    else:
        gate_lot = pd.DataFrame()

    ref, _ = ic_table(P, ["mom_total_12_1"], "cap_tier", TIERS3)
    incr = incremental(P, "mom_intraday_12_1", ["mom_6m", "residual_momentum_12_1", "mom_total_12_1"])
    down = down_flag_robustness(F)

    tiers = {(s, pd.Timestamp(d).strftime("%Y-%m")): t for s, d, t in zip(panel["sid"], panel["dt"], panel["cap_tier"])}
    timing, E = filing_timing(W, tiers)
    return dict(P=P, ic=ic, ref=ref, incr=incr, down=down, split=split, surv=surv, gate=gate, gate_full=gate_full, gate_lot=gate_lot,
                timing=timing, events=len(E), anchors=P["snapshot_date"].nunique(),
                span=(P["snapshot_date"].min(), P["snapshot_date"].max()))


def _md(df, floatfmt=4):
    df = df.copy()
    for c in df.columns:
        if df[c].dtype.kind == "f":
            df[c] = df[c].map(lambda v: "" if pd.isna(v) else f"{v:+.{floatfmt}f}" if abs(v) < 10 else f"{v:,.1f}")
    head = "| " + " | ".join(df.columns) + " |\n|" + "---|" * len(df.columns)
    return head + "\n" + "\n".join("| " + " | ".join(str(v) for v in r) + " |" for r in df.values)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md")
    a = ap.parse_args()
    R = run()
    parts = [f"Anchors: {R['anchors']} monthly ({R['span'][0]} → {R['span'][1]}); halves split at {R['split']}. "
             f"Results-filing events: {R['events']}.",
             "## Factor ICs (panel, PIT tier, label fwd_return_20d)",
             _md(R["ic"][["signal", "group", "n", "stocks", "mean_ic", "t", "ic_h1", "ic_h2", "halves",
                          "corr_mom_6m", "max_corr", "max_corr_with", "verdict"]]),
             "## Reference: total 12-1 momentum computed the same way", _md(R["ref"][["signal", "group", "n", "mean_ic", "t"]]),
             "## mom_intraday_12_1 net of the momentum we already have (rank residual IC)", _md(R["incr"]),
             "## Survivorship check (own 20-session label; delisted names exit at last close)",
             _md(R["surv"][["scope", "signal", "group", "n", "stocks", "mean_ic", "t"]]),
             "## ASM price-trigger gate: flagged − unflagged 20-day return (panel tiers)", _md(R["gate"]),
             "## ASM gate on everything that traded (own label)", _md(R["gate_full"]),
             "## ASM down-flag robustness", _md(R["down"]), str(R["down"].attrs.get("flagged")),
             "## ASM up-flag inside the top max_lottery quintile", _md(R["gate_lot"]) if len(R["gate_lot"]) else "n/a",
             "## Results filed in session vs outside (in − out, month-clustered t)", _md(R["timing"])]
    out = "\n\n".join(parts)
    print(out)
    if a.md:
        Path(a.md).write_text(out + "\n")


if __name__ == "__main__":
    main()
