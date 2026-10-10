"""
Ownership-flow factor study (plan 0011 WS2.4 / plan 0014 D1), 2026-10.

The 2026-10 LARGE study (docs/studies/large-factors-2026-10.md) left d_fii / d_mf / d_dii /
inst_breadth INSUFFICIENT: Tickertape `shareholding` gives about 20 monthly anchors. The BSE
filings now in `shareholding_categories` reach back to 2016, so the same factors (plus the
retail holder count) can be read on every labelled anchor of the panel.

READ-ONLY: db.read_sql only; no table writes, no network. Each factor is computed by
pit.pit_ownership_flows at each monthly anchor of daily_snapshots_pit from filings broadcast
on or before the anchor, then scored with the backtest's own evidence engine
(tools.backtest_pit._compute_ic / _aggregate), within point-in-time cap tier, against the
panel label fwd_return_20d (entry next session).

Pre-registered signs (before the run): fii_qoq, mf_qoq, dii_qoq, inst_breadth POSITIVE
(institutions buying); retail_holders_qoq NEGATIVE (retail crowding).

Usage:  ALPHA_DB=/path/alpha_signal.db python -m tools.ownership_flow_study [--md PATH]
"""
import argparse
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import factors
import pit
from db import read_sql
from tools import backtest_pit as bp

TIERS3 = ["LARGE", "MID", "SMALL"]
SIGNS = {"fii_qoq": 1, "mf_qoq": 1, "dii_qoq": 1, "inst_breadth": 1, "retail_holders_qoq": -1}
REFERENCE = ["promoter_qoq"]          # existing panel column (Tickertape + v1), re-read for comparison
BAR, BONFERRONI = 2.5, 4.2            # ADR 0043: |t| 2.5 necessary, ~4.2 the multiple-testing bar


def wired_cols():
    """{tier: [panel columns of the factors wired in that tier]}, from the registry."""
    return {t: [factors.FACTORS[k].get("replay_col") or factors.pit_column(k)
                for k, f in factors.FACTORS.items() if f.get("weights", {}).get(t)] for t in TIERS3}


def load():
    shc = read_sql("SELECT sid, end_date, filed_at, foreign_inst_pct, domestic_inst_pct, mf_pct, n_retail "
                   "FROM shareholding_categories")
    w = sorted({c for cs in wired_cols().values() for c in cs})
    cols = ["sid", "snapshot_date", "cap_tier", "fwd_return_20d"] + REFERENCE + w
    panel = read_sql("SELECT " + ", ".join(cols) + " FROM daily_snapshots_pit "
                     "WHERE cap_tier IN ('LARGE','MID','SMALL') AND fwd_return_20d IS NOT NULL")
    panel["dt"] = pd.to_datetime(panel["snapshot_date"])
    panel = panel[panel["dt"].map(bp._is_month_start_anchor)].copy()
    return shc, panel


def build(shc, panel):
    frames = []
    for anchor in sorted(panel["dt"].unique()):
        f = pit.pit_ownership_flows(shc, pd.Timestamp(anchor).date())
        f["dt"] = pd.Timestamp(anchor)
        frames.append(f)
    return panel.merge(pd.concat(frames, ignore_index=True), on=["sid", "dt"], how="left")


def evaluate(P, signals):
    dates = sorted(P["dt"].unique())
    split = pd.Timestamp(dates[len(dates) // 2])
    rows = []
    for sig in signals:
        for tier in TIERS3:
            d = P[P["cap_tier"] == tier]
            ics = bp._compute_ic(d, sig, "fwd_return_20d")
            cover = d.groupby("snapshot_date")[sig].apply(lambda s: s.notna().mean()).mean()
            if not ics:
                rows.append(dict(signal=sig, tier=tier, n=0, coverage=cover))
                continue
            agg = bp._aggregate(ics, sig, tier, "ownership_flow_study")
            ic = pd.Series({pd.Timestamp(e): v for e, v, _ in ics})
            h1, h2 = ic[ic.index < split], ic[ic.index >= split]
            rows.append(dict(signal=sig, tier=tier, n=agg["n_periods"], stocks=agg["n_stocks_avg"], coverage=cover,
                             mean_ic=agg["mean_ic"], t=agg["t_stat"], ic_h1=h1.mean(), ic_h2=h2.mean(),
                             n_h1=len(h1), n_h2=len(h2), hit=(np.sign(ic) == np.sign(ic.mean())).mean()))
    T = pd.DataFrame(rows)
    T["halves_agree"] = ((np.sign(T["ic_h1"]) == np.sign(T["ic_h2"])) & (np.sign(T["ic_h1"]) == np.sign(T["mean_ic"]))
                         & (T["n_h1"] >= 6) & (T["n_h2"] >= 6))
    T["sign_ok"] = [SIGNS.get(s, 0) * np.sign(m) > 0 if pd.notna(m) else False
                    for s, m in zip(T["signal"], T.get("mean_ic", np.nan))]
    return T, split


def max_corr_wired(P, sig, tier, wired):
    d = P[P["cap_tier"] == tier]
    best = (np.nan, None)
    for w in wired[tier]:
        cs = [spearmanr(g[sig], g[w])[0] for _, g in d.groupby("snapshot_date")
              if (s := g[[sig, w]].dropna()).shape[0] >= 20 and s[sig].nunique() > 1 and s[w].nunique() > 1
              for g in [s]]
        m = float(np.nanmean(cs)) if len(cs) >= 12 else np.nan
        if pd.notna(m) and (pd.isna(best[0]) or abs(m) > abs(best[0])):
            best = (m, w)
    return best


def verdict(r, corr):
    if r.get("n", 0) < 36:
        return "INSUFFICIENT (n<36)"
    if pd.isna(r["t"]):
        return "n/a"
    if not r["sign_ok"] and abs(r["t"]) >= 1.5:
        return "WRONG SIGN"
    if abs(r["t"]) >= BAR and r["halves_agree"] and not (pd.notna(corr) and abs(corr) >= 0.5):
        return "KEEP" + (" (clears Bonferroni)" if abs(r["t"]) >= BONFERRONI else "")
    if abs(r["t"]) >= 1.5:
        return "WEAK"
    return "DROP"


def report(T, P, split, signals):
    wired = wired_cols()
    lines = [f"Anchors: {P['dt'].nunique()} monthly ({P['dt'].min().date()} → {P['dt'].max().date()}); "
             f"halves split at {split.date()}.", "",
             "| signal | tier | n | coverage | mean IC | t | IC H1 | IC H2 | halves | hit rate | max corr wired | verdict |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for sig in signals:
        for tier in TIERS3:
            r = T[(T.signal == sig) & (T.tier == tier)].iloc[0]
            if not r.get("n"):
                lines.append(f"| {sig} | {tier} | 0 | {r['coverage']:.0%} | - | - | - | - | - | - | - | no data |")
                continue
            c, w = max_corr_wired(P, sig, tier, wired) if sig in SIGNS else (np.nan, None)
            cs = "-" if pd.isna(c) else f"{c:+.2f} ({w})"
            v = verdict(r, c) if sig in SIGNS else "reference"
            lines.append(f"| {sig} | {tier} | {int(r['n'])} | {r['coverage']:.0%} | {r['mean_ic']:+.4f} | {r['t']:+.2f} | "
                         f"{r['ic_h1']:+.4f} | {r['ic_h2']:+.4f} | {'agree' if r['halves_agree'] else 'split'} | "
                         f"{r['hit']:.0%} | {cs} | {v} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", help="write the markdown table to this path")
    a = ap.parse_args()
    shc, panel = load()
    print(f"filings {len(shc)} ({shc['sid'].nunique()} stocks); panel anchors {panel['dt'].nunique()}", file=sys.stderr)
    P = build(shc, panel)
    signals = list(SIGNS) + REFERENCE
    T, split = evaluate(P, signals)
    md = report(T, P, split, signals)
    print(md)
    if a.md:
        with open(a.md, "w") as fh:
            fh.write(md + "\n")


if __name__ == "__main__":
    main()
