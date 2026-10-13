"""
ADR 0074 applied: propose MID live weights with grade-B factors at half weight, and run the
whole-score test.  (READ-ONLY on the DB; writes data/lh/v2/mid_reweight.json)

PRE-REGISTRATION (2026-10-13, before any result):
Evidence = the live label (fwd_return_20d, the panel's 20-session return), MID, monthly anchors,
full history (as the live weights were set under ADR 0063 / 0071).
  - Candidates: every IC-rankable registry column (tools.walk_forward._columns) with >= 24 anchors,
    not already wired in MID.
  - Grade B: 1.5 <= |t| < 2.5 (plain t of the monthly IC series, as tools.walk_forward) AND the same
    IC sign in both halves of the history.
  - Not a near-copy: mean within-MID rank correlation |rho| < 0.5 with every MID-wired factor and
    every B factor already added (taken in |t| order).
  - Add B factors in |t| order until the tier has 12 factors. Each B weight = 0.5 × the mean |weight|
    of today's MID factors, sign = IC sign; then all MID weights are rescaled so Σ|w| = 1 (today's
    factors keep their relative sizes).
Whole-score test (ADR 0074): MID score = the screener's composite (Σ|w|·pct, missing 0.5), old vs
new weights, on every anchor; rank IC at 21 sessions; the top-20 fast book (monthly · top 20 · sell
below 40 · raw · no hold; tools.lh_book) across the 12 start months 2022-06 … 2023-05, after costs
and tax. Accept if the new median excess >= old AND starts beating the index >= old.
Both weight sets are chosen on this history, so this is an in-sample check of the change; the
out-of-sample case for the rule is tools.lh_relax_test.

Usage: python -m tools.mid_reweight_0074
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import factors  # noqa: E402
from tools.backtest_pit import _compute_ic  # noqa: E402
from tools.walk_forward import _columns, _ranked_col, composite, load_panel  # noqa: E402

LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
TIER = "MID"
RESP = "fwd_return_20d"


def t_of(s):
    return float(s.mean() / (s.std(ddof=1) / np.sqrt(len(s))))


def main():
    col_of = _columns()
    old_keyed = factors.SIGNAL_WEIGHTS[TIER]
    old = {_ranked_col(k, TIER): w for k, w in old_keyed.items()}
    panel, cols = load_panel(sorted(set(col_of) | set(old)))
    mid = panel[panel["cap_tier"] == TIER]
    ic = {}
    for c in cols:
        rows = _compute_ic(mid[["snapshot_date", c, RESP]], c, RESP)
        if len(rows) >= 24:
            ic[c] = pd.Series({d: v for d, v, _ in rows}).sort_index()
    stats = []
    for c, s in ic.items():
        h = len(s) // 2
        stats.append(dict(col=c, signal=col_of.get(c, c), n=len(s), ic=round(s.mean(), 4), t=round(t_of(s), 2),
                          halves_agree=bool(np.sign(s.iloc[:h].mean()) == np.sign(s.iloc[h:].mean()) != 0),
                          wired=c in old))
    st = pd.DataFrame(stats).sort_values("t", key=lambda x: -x.abs())

    # rank correlations (mean per anchor) for the near-copy test
    def rho(a, b):
        vals = [g[a].corr(g[b], method="spearman") for _, g in mid[["snapshot_date", a, b]].dropna().groupby("snapshot_date")
                if len(g) >= 20]
        return float(np.nanmean(vals)) if vals else 0.0

    cands = st[(~st["wired"]) & (st["t"].abs() >= 1.5) & (st["t"].abs() < 2.5) & st["halves_agree"]]
    chosen, rejected = [], []
    slots = 12 - len(old)
    for _, r in cands.iterrows():
        if len(chosen) >= slots:
            break
        others = list(old) + [c["col"] for c in chosen]
        corrs = {o: rho(r["col"], o) for o in others}
        worst = max(corrs.items(), key=lambda kv: abs(kv[1]))
        if abs(worst[1]) >= 0.5:
            rejected.append(dict(col=r["col"], t=r["t"], too_close_to=worst[0], rho=round(worst[1], 2)))
            continue
        chosen.append(dict(col=r["col"], signal=r["signal"], t=r["t"], ic=r["ic"], max_rho=round(worst[1], 2),
                           max_rho_with=worst[0]))
    b_w = 0.5 * np.mean([abs(w) for w in old.values()])
    new = dict(old)
    for c in chosen:
        new[c["col"]] = b_w * np.sign(c["ic"])
    tot = sum(abs(w) for w in new.values())
    new = {c: round(w / tot, 4) for c, w in new.items()}

    # whole-score test
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier", "fwd_21"])
    frames = []
    for name, w in (("mid_old", old), ("mid_new", new)):
        for a, g in mid.groupby("snapshot_date"):
            g = g.set_index("sid")
            s = composite(g, w)
            frames.append(pd.DataFrame({"sid": s.index, "snapshot_date": a, "cap_tier": TIER, "method": name,
                                        "score": s.to_numpy(float), "pct_rank": s.rank(pct=True).to_numpy(float),
                                        "oos": False}))
    sc = pd.concat(frames, ignore_index=True)
    ics = {}
    for name, g in sc.groupby("method"):
        d = g.merge(lab, on=["sid", "snapshot_date"]).dropna(subset=["fwd_21"])
        per = d.groupby("snapshot_date").apply(lambda x: x["score"].rank().corr(x["fwd_21"].rank()))
        ics[name] = dict(ic21=round(per.mean(), 4), t=round(t_of(per.dropna()), 2))
    import tools.lh_book as B
    starts = sorted(sc.loc[sc["snapshot_date"] >= "2022-06-01", "snapshot_date"].unique())[:12]
    rows = []
    for stt in starts:
        d = V2 / "win_mid_reweight"
        d.mkdir(parents=True, exist_ok=True)
        sc[sc["snapshot_date"] >= stt].to_parquet(d / "oos_scores.parquet", index=False)
        if not (d / "labels.parquet").exists():
            os.symlink(LH / "labels.parquet", d / "labels.parquet")
        B.LH = d
        D = B.Data()
        bench = B.benchmark(D, TIER)
        for name in ("mid_old", "mid_new"):
            r, _ = B.simulate(D, TIER, dict(method=name, reb="M", N=20, k=2, score="raw", min_hold=0, defer=False,
                                            block="r"), bench)
            rows.append(dict(start=stt, method=name, excess=r["excess_cagr"], t=r["t_nw"], turnover=r["turnover_pa"]))
    bk = pd.DataFrame(rows)
    summ = bk.groupby("method").agg(median_excess=("excess", "median"), min_excess=("excess", "min"),
                                    starts_beating=("excess", lambda v: int((v > 0).sum())),
                                    median_t=("t", "median"), turnover=("turnover", "median"))
    o, n = summ.loc["mid_old"], summ.loc["mid_new"]
    accept = bool(n["median_excess"] >= o["median_excess"] and n["starts_beating"] >= o["starts_beating"])
    # map columns back to weight keys for factors.py
    key_of = {_ranked_col(k, TIER): k for k in old_keyed}
    new_by_key = {key_of.get(c, col_of.get(c, c)): w for c, w in new.items()}
    out = dict(old=old_keyed, b_weight_raw=round(b_w, 4), chosen=chosen, rejected_near_copy=rejected,
               new_weights_by_column=new, new_weights_by_key=new_by_key, ic=ics,
               books=summ.round(4).reset_index().to_dict("records"), accept=accept,
               candidates=cands[["col", "signal", "n", "ic", "t"]].to_dict("records"))
    (V2 / "mid_reweight.json").write_text(json.dumps(out, indent=1, default=str))
    pd.set_option("display.width", 200)
    print("grade-B candidates:\n", cands[["col", "signal", "n", "ic", "t"]].to_string(index=False))
    print("chosen:", json.dumps(chosen, indent=1))
    print("rejected (near-copy):", rejected)
    print("new MID weights:", json.dumps(new_by_key, indent=1))
    print("IC:", ics)
    print(summ.round(4).to_string())
    print("ACCEPT:", accept)


if __name__ == "__main__":
    main()
