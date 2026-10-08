"""
Large-cap factor study (plan 0020 open item "new LARGE factors"), 2026-10.

READ-ONLY: db.read_sql only; no table writes, no network. Candidate factors are computed IN MEMORY at
each monthly anchor of daily_snapshots_pit from data knowable at that anchor, then scored with the
backtest's own evidence engine (tools.backtest_pit._compute_ic / _aggregate), within cap tier.

As-of notes
  * Returns/volume: stock_prices up to the anchor row only. Prices are fully adjusted for every
    corporate action; any return between two dates <= anchor is identical to the PIT-strict
    adj_close return (a later action scales both ends), so no information after the anchor is used.
  * Shareholding: pit.knowable_shareholding (end_date + 21d <= anchor).
  * Result filings: bse_announcements date <= anchor - 335d (year-ago window only).
  * Industry/sector: stocks.industry (static, current classification; peers demeaned at each anchor).
  * Labels/tier/existing columns: panel daily_snapshots_pit (fwd_return_20d entry next session).

Usage:  ALPHA_DB=/path/alpha_signal.db python -m tools.large_factor_study [--md PATH]
"""
import argparse
import sys
from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import pit
from db import read_sql
from signals._prices import apply_adjustments
from tools import backtest_pit as bp

TIERS3 = ["LARGE", "MID", "SMALL"]
SPLIT = pd.Timestamp("2023-01-01")
WIRED = ["announcement_car", "iv_skew_25d", "asset_growth_yoy", "forward_looking_intensity"]

# Existing panel columns re-read on every tier (not new hypotheses; reported separately).
EXISTING = ["position_52w", "st_reversal_21d", "low_vol_252d", "max_lottery_21d", "residual_momentum_12_1",
            "mom_12m", "mom_6m", "iv_skew_25d", "iv_term_structure", "iv_realised_spread", "iv_percentile_1y",
            "pcr_oi", "pcr_volume", "promoter_qoq", "promoter_trend_4q", "announcement_car",
            "asset_growth_yoy", "gross_profitability", "forward_looking_intensity", "delivery_anomaly_z"]

NEW = ["mom_12_1", "fip_id", "mom_cont",
       "seas_same", "seas_other", "seas_diff",
       "high52", "high52_ind",
       "ivol60", "ivol60_ind", "st_rev_ind",
       "d_fii", "d_mf", "d_dii", "inst_breadth",
       "abvol", "abvol_signed",
       "ann_car_ind", "resmom_ind",
       "beta252", "ann_premium"]


def _rank(s):
    return s.rank(pct=True)


def load():
    px = read_sql("SELECT sid, date, close, volume FROM stock_prices WHERE close > 0 ORDER BY sid, date")
    adj = read_sql("SELECT sid, ex_date, factor FROM corporate_adjustments ORDER BY sid, ex_date")
    px = apply_adjustments(px, adj, date.max)
    A = px.pivot(index="date", columns="sid", values="adj_close").sort_index()
    V = px.pivot(index="date", columns="sid", values="volume").reindex(A.index)
    sh = read_sql("SELECT sid, end_date, fii_pct, mf_pct, dii_pct FROM shareholding ORDER BY sid, end_date")
    res = read_sql(f"SELECT sid, date(dt_tm) AS d FROM bse_announcements WHERE "
                   f"{pit.factors.RESULT_FILING_SQL} AND sid IS NOT NULL AND dt_tm IS NOT NULL")
    ind = read_sql("SELECT sid, industry, sector FROM stocks")
    ind["grp"] = ind["industry"].fillna(ind["sector"])
    cols = ["sid", "snapshot_date", "cap_tier", "fwd_return_20d"] + sorted(set(EXISTING))
    panel = read_sql("SELECT " + ", ".join(cols) + " FROM daily_snapshots_pit WHERE cap_tier IN ('LARGE','MID','SMALL')")
    panel["dt"] = pd.to_datetime(panel["snapshot_date"])
    panel = panel[panel["dt"].map(bp._is_month_start_anchor)].copy()
    return A, V, sh, res, ind.set_index("sid")["grp"], panel


def _ind_demean(s, grp):
    g = grp.reindex(s.index)
    return s - s.groupby(g).transform("mean")


def features_at(anchor, A, V, R, mkt, M, sh, res, grp):
    """All candidate features for every sid at `anchor` (Timestamp). Uses rows <= anchor only."""
    a = anchor.strftime("%Y-%m-%d")
    i = int(np.searchsorted(A.index.values, a, side="right")) - 1
    if i < 260:
        return None
    sids = A.columns
    out = pd.DataFrame(index=sids)
    close = A.values
    # momentum 12-1 and information discreteness
    p0, p1 = close[i - 252], close[i - 21]
    mom = p1 / p0 - 1
    rw = R[i - 251:i - 20]                                   # daily returns across the 12-1 window
    n_ok = np.isfinite(rw).sum(0)
    neg = (rw < 0).sum(0) / np.maximum(n_ok, 1)
    pos = (rw > 0).sum(0) / np.maximum(n_ok, 1)
    ok = (n_ok >= 150) & np.isfinite(mom)
    out["mom_12_1"] = np.where(ok, mom, np.nan)
    out["fip_id"] = np.where(ok, np.sign(mom) * (neg - pos), np.nan)
    # reversal, 52w-high ratio, idio vol, beta
    ret21 = close[i] / close[i - 21] - 1
    out["_ret21"] = ret21
    hi = np.nanmax(close[i - 251:i + 1], axis=0)
    cnt = np.isfinite(close[i - 251:i + 1]).sum(0)
    out["high52"] = np.where(cnt >= 150, close[i] / hi, np.nan)
    ry = R[i - 59:i + 1]
    rm = mkt[i - 59:i + 1][:, None]
    m = np.isfinite(ry)
    n = m.sum(0)
    ym = np.where(m, ry, 0.0)
    xm = np.where(m, rm, 0.0)
    ybar = ym.sum(0) / np.maximum(n, 1)
    xbar = xm.sum(0) / np.maximum(n, 1)
    cov = (np.where(m, (ry - ybar) * (rm - xbar), 0.0)).sum(0)
    var = (np.where(m, (rm - xbar) ** 2, 0.0)).sum(0)
    beta = cov / np.where(var > 0, var, np.nan)
    resid = np.where(m, (ry - ybar) - beta * (rm - xbar), 0.0)
    ivol = np.sqrt((resid ** 2).sum(0) / np.maximum(n - 2, 1))
    out["ivol60"] = np.where(n >= 45, ivol, np.nan)
    ry2, rm2 = R[i - 251:i + 1], mkt[i - 251:i + 1][:, None]
    m2 = np.isfinite(ry2)
    n2 = m2.sum(0)
    yb = np.where(m2, ry2, 0).sum(0) / np.maximum(n2, 1)
    xb = np.where(m2, rm2, 0).sum(0) / np.maximum(n2, 1)
    c2 = np.where(m2, (ry2 - yb) * (rm2 - xb), 0).sum(0)
    v2 = np.where(m2, (rm2 - xb) ** 2, 0).sum(0)
    out["beta252"] = np.where(n2 >= 150, c2 / v2, np.nan)
    # abnormal volume: last 5 sessions vs prior 50
    v5 = np.nanmean(V.values[i - 4:i + 1], axis=0)
    v50 = np.nanmean(V.values[i - 54:i - 4], axis=0)
    ab = np.log(np.where((v5 > 0) & (v50 > 0), v5 / v50, np.nan))
    r5 = close[i] / close[i - 5] - 1
    out["abvol"] = ab
    out["abvol_signed"] = ab * np.sign(r5)
    # seasonality (Heston-Sadka): same calendar month, previous 5 years (>=3), other months control
    per = anchor.to_period("M")
    mrow = M.loc[M.index < per]
    same = [M.loc[per - 12 * k] if (per - 12 * k) in M.index else None for k in range(1, 6)]
    same = pd.concat([s for s in same if s is not None], axis=1) if any(s is not None for s in same) else None
    if same is not None:
        s_ok = same.notna().sum(1) >= 3
        out["seas_same"] = same.mean(1).where(s_ok).reindex(sids)
    last60 = mrow.iloc[-60:]
    oth = last60[[p.month != per.month for p in last60.index]]
    if len(oth) >= 36:
        out["seas_other"] = oth.mean().where(oth.notna().sum() >= 36).reindex(sids)
    out["seas_diff"] = out.get("seas_same") - out.get("seas_other") if "seas_same" in out and "seas_other" in out else np.nan
    # industry-adjusted
    out["high52_ind"] = _ind_demean(out["high52"], grp)
    out["ivol60_ind"] = _ind_demean(out["ivol60"], grp)
    out["st_rev_ind"] = _ind_demean(out["_ret21"], grp)
    # ownership flows
    cut = (anchor - pd.Timedelta(days=pit.SHAREHOLDING_LAG)).strftime("%Y-%m-%d")
    s = sh[sh["end_date"] <= cut]
    g = s.groupby("sid")
    last = g.tail(1).set_index("sid")
    prev = s.drop(g.tail(1).index).groupby("sid").tail(1).set_index("sid")
    j = last.join(prev, rsuffix="_p", how="inner")
    gap = (pd.to_datetime(j["end_date"]) - pd.to_datetime(j["end_date_p"])).dt.days
    fresh = (anchor - pd.to_datetime(j["end_date"])).dt.days <= 140
    j = j[(gap >= 70) & (gap <= 120) & fresh]
    for c, nm in (("fii_pct", "d_fii"), ("mf_pct", "d_mf"), ("dii_pct", "d_dii")):
        out[nm] = (j[c] - j[c + "_p"]).reindex(sids)
    d3 = out[["d_fii", "d_mf", "d_dii"]]
    out["inst_breadth"] = (d3 > 0).sum(1).where(d3.notna().all(1))
    # earnings-announcement premium: a result filing in the year-ago 30-day window (Frazzini-Lamont)
    lo = (anchor - pd.Timedelta(days=364)).strftime("%Y-%m-%d")
    hi_ = (anchor - pd.Timedelta(days=335)).strftime("%Y-%m-%d")
    base = (anchor - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    rr = res[(res["d"] >= base) & (res["d"] <= (anchor - pd.Timedelta(days=335)).strftime("%Y-%m-%d"))]
    has = rr.groupby("sid").size()
    inw = set(rr[(rr["d"] >= lo) & (rr["d"] <= hi_)]["sid"])
    ap = pd.Series(np.nan, index=sids)
    ap.loc[ap.index.intersection(has.index)] = 0.0
    ap.loc[ap.index.intersection(list(inw))] = 1.0
    out["ann_premium"] = ap
    return out.drop(columns=["_ret21"])


def build_features(A, V, sh, res, grp, panel):
    R = A.pct_change(fill_method=None).clip(-0.5, 0.5).values
    mkt = np.nanmean(R, axis=1)
    # month-end adjusted returns for seasonality
    me = A.groupby(pd.to_datetime(A.index).to_period("M")).tail(1)
    me.index = pd.to_datetime(me.index).to_period("M")
    me = me.reindex(pd.period_range(me.index.min(), me.index.max(), freq='M'))   # a missing month stays NaN
    M = me.pct_change(fill_method=None)
    frames = []
    for anchor in sorted(panel["dt"].unique()):
        anchor = pd.Timestamp(anchor)
        f = features_at(anchor, A, V, R, mkt, M, sh, res, grp)
        if f is None:
            continue
        f = f.reset_index().rename(columns={"index": "sid"})
        f["dt"] = anchor
        frames.append(f)
        print(f"  features {anchor.date()}", file=sys.stderr, end="\r")
    F = pd.concat(frames, ignore_index=True)
    P = panel.merge(F, on=["sid", "dt"], how="left")
    P["snapshot_date"] = P["snapshot_date"].astype(str)
    # panel-column industry neutral versions
    g = P["sid"].map(grp)
    for src, nm in (("announcement_car", "ann_car_ind"), ("residual_momentum_12_1", "resmom_ind")):
        P[nm] = P[src] - P.groupby([P["dt"], g])[src].transform("mean")
    # momentum conditioned on continuous information (ranks within tier-anchor)
    key = [P["dt"], P["cap_tier"]]
    pm = P.groupby(key)["mom_12_1"].rank(pct=True)
    pi = P.groupby(key)["fip_id"].rank(pct=True)
    P["mom_cont"] = (pm - 0.5) * (1 - pi)
    return P


def evaluate(P, signals):
    rows = []
    for sig in signals:
        for tier in TIERS3:
            d = P[P["cap_tier"] == tier]
            ics = bp._compute_ic(d, sig, "fwd_return_20d")
            if not ics:
                rows.append(dict(signal=sig, tier=tier, n=0))
                continue
            agg = bp._aggregate(ics, sig, tier, "large_factor_study")
            ic = pd.Series({pd.Timestamp(e): v for e, v, _ in ics})
            h1, h2 = ic[ic.index < SPLIT], ic[ic.index >= SPLIT]
            rows.append(dict(signal=sig, tier=tier, n=agg["n_periods"], stocks=agg["n_stocks_avg"],
                             mean_ic=agg["mean_ic"], t=agg["t_stat"],
                             ic_h1=round(h1.mean(), 4) if len(h1) else np.nan, n_h1=len(h1),
                             ic_h2=round(h2.mean(), 4) if len(h2) else np.nan, n_h2=len(h2)))
    T = pd.DataFrame(rows)
    T["halves_agree"] = (np.sign(T["ic_h1"]) == np.sign(T["ic_h2"])) & (np.sign(T["ic_h1"]) == np.sign(T["mean_ic"])) \
        & (T["n_h1"] >= 6) & (T["n_h2"] >= 6)
    return T


def corr_with_wired(P, signals, tier="LARGE"):
    d = P[P["cap_tier"] == tier]
    out = {}
    for sig in signals:
        for w in WIRED:
            if sig == w:
                continue
            cs = []
            for _, g in d.groupby("snapshot_date"):
                s = g[[sig, w]].dropna()
                if len(s) >= 20 and s[sig].nunique() > 1 and s[w].nunique() > 1:
                    cs.append(spearmanr(s[sig], s[w])[0])
            out[(sig, w)] = (float(np.nanmean(cs)) if len(cs) >= 12 else np.nan)
    C = pd.Series(out).unstack()
    C["max_abs"] = C.abs().max(1)
    return C


def label(row, maxcorr):
    if row["tier"] != "LARGE" or row.get("n", 0) == 0:
        return ""
    if pd.isna(row["t"]):
        return "n/a"
    if row["n"] < 36:
        return "INSUFFICIENT (n<36)"
    if abs(row["t"]) >= 2.5 and not pd.isna(maxcorr) and maxcorr >= 0.5:
        return "NOT NEW (corr>=0.5)"
    if abs(row["t"]) >= 2.5 and row["n"] >= 36 and row["halves_agree"] and (pd.isna(maxcorr) or maxcorr < 0.5):
        return "PROMISING"
    if abs(row["t"]) >= 1.5:
        return "WEAK"
    return "DROP"


def to_md(T, C, nnew, nex):
    w = T.pivot(index="signal", columns="tier")
    lines = []
    for grp_name, sigs in (("NEW candidates", NEW), ("Existing panel columns (re-read)", sorted(set(EXISTING)))):
        lines.append(f"\n### {grp_name}\n")
        lines.append("| signal | LARGE n | mean IC | t | H1 IC (20-22) | H2 IC (23-26) | halves | max abs corr wired | label | MID t | SMALL t |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for s in sigs:
            r = T[(T.signal == s) & (T.tier == "LARGE")]
            if r.empty or r.iloc[0].get("n", 0) == 0:
                lines.append(f"| {s} | 0 | - | - | - | - | - | - | no data | - | - |")
                continue
            r = r.iloc[0]
            mc = C["max_abs"].get(s, np.nan) if C is not None else np.nan
            if s not in NEW:
                mc = np.nan
            mid = T[(T.signal == s) & (T.tier == "MID")].iloc[0]
            sm = T[(T.signal == s) & (T.tier == "SMALL")].iloc[0]
            f = lambda x: "-" if pd.isna(x) else f"{x:.2f}"
            lines.append(f"| {s} | {int(r['n'])} | {r['mean_ic']:+.4f} | {r['t']:+.2f} | {r['ic_h1']:+.4f} | {r['ic_h2']:+.4f} | "
                         f"{'agree' if r['halves_agree'] else 'split'} | {f(mc)} | {label(r, mc) if s in NEW else 'reference'} | "
                         f"{f(mid.get('t'))} (n={int(mid.get('n', 0))}) | {f(sm.get('t'))} (n={int(sm.get('n', 0))}) |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", help="write the markdown table to this path")
    a = ap.parse_args()
    A, V, sh, res, grp, panel = load()
    print(f"panel monthly anchors: {panel['dt'].nunique()}  prices {A.shape}", file=sys.stderr)
    P = build_features(A, V, sh, res, grp, panel)
    sigs = NEW + sorted(set(EXISTING))
    T = evaluate(P, sigs)
    C = corr_with_wired(P, NEW)
    pd.set_option("display.width", 250, "display.max_rows", 500)
    print(f"\nNEW hypotheses tested: {len(NEW)} (x3 tiers = {len(NEW) * 3} cells); existing re-reads: {len(set(EXISTING))}")
    md = to_md(T, C, len(NEW), len(set(EXISTING)))
    print(md)
    print("\nCorrelation with wired LARGE factors (mean per-anchor Spearman):")
    print(C.round(2).to_string())
    prom = [s for s in NEW if (lambda r: label(r.iloc[0], C["max_abs"].get(s, np.nan)) if len(r) else "")(T[(T.signal == s) & (T.tier == "LARGE")]) == "PROMISING"]
    print("\nPROMISING:", prom or "none")
    if a.md:
        with open(a.md, "w") as fh:
            fh.write(md + "\n\nCorrelation with wired LARGE factors:\n\n" + "```\n" + C.round(2).to_string() + "\n```" + "\n")


if __name__ == "__main__":
    main()
