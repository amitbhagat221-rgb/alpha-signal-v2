"""
Promotion review: wire `q_ebitda_chg` (quarterly profit growth YoY) in SMALL?
(READ-ONLY on the DB; writes data/lh/v2/small_promote_q_ebitda.json)

Amit 2026-10-15: "yes promote the strong candidate" (plan 0025 task 5.1,
docs/studies/quarterly-nse-2026-10.md: SMALL 126-session non-overlap t 3.85).

PRE-REGISTRATION (2026-10-15, before any result of this tool):
SMALL keeps the strict rules (ADR 0043 / 0063; ADR 0074's grade B is MID-only).
Evidence = the live label (fwd_return_20d, the panel's 20-session return), monthly anchors, every
anchor where the column has >= 50 SMALL values — as the live weights were set (ADR 0063 / 0071).
  1. Factor gate (all must hold):
     a. SMALL IC t >= 2.5 (plain t of the monthly IC series, as tools.walk_forward), n >= 24 anchors;
     b. the same IC sign in both halves of the history;
     c. not a near-copy: mean within-SMALL rank correlation |rho| < 0.5 with every SMALL-wired factor.
     Reported, not deciding: t on the anchors since 2024-09; IC t on the residual after the six SMALL
     wired factors; MID and LARGE t (the study found ~0 there — no wiring outside SMALL).
  2. Weight (no fitting): grade A = the mean |weight| of today's SMALL factors (1/6), then every SMALL
     weight is rescaled so Σ|w| = 1 (today's factors keep their relative sizes).
  3. Whole-score test (ADR 0074 shape): SMALL composite (Σ|w|·pct, missing 0.5, tools.walk_forward
     .composite), old vs new, on every anchor:
       - rank IC at 21 sessions (labels fwd_21) and its t;
       - top-minus-bottom tenth of the score at 21 sessions;
       - the top-20 fast book (monthly · top 20 · sell below 40 · raw · no hold; tools.lh_book,
         measured costs + Indian tax, NIFTY SMALLCAP 250) across the 12 start months 2022-06 … 2023-05.
     ACCEPT if the factor gate passes AND the new book's median excess >= old AND its starts beating
     the index >= old AND the rank IC t does not fall.
Both weight sets are judged on the history they are measured on (in-sample for the whole-score step);
the factor's own out-of-sample case is the 5.1 study's period split.

Note 2026-10-15 (bug, not a bar): the first run stopped before any result — tools.lh_book opens
PROJECT_ROOT/data/alpha_signal.db and ignores ALPHA_DB; the tool now points B.DB at ALPHA_DB.

Usage: ALPHA_DB=... python -m tools.small_promote_q_ebitda
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
from tools.walk_forward import _ranked_col, composite, load_panel  # noqa: E402

LH = Path(os.environ.get("ALPHA_LH", PROJECT_ROOT / "data" / "lh"))
V2 = LH / "v2"
TIER, COL, RESP = "SMALL", "q_ebitda_chg", "fwd_return_20d"


def t_of(s):
    s = s.dropna()
    return float(s.mean() / (s.std(ddof=1) / np.sqrt(len(s)))) if len(s) > 2 else float("nan")


def ic_series(df, col):
    rows = _compute_ic(df[["snapshot_date", col, RESP]], col, RESP)
    return pd.Series({d: v for d, v, _ in rows}).sort_index()


def residual_ic(df, col, controls):
    out = {}
    for a, g in df.groupby("snapshot_date"):
        g = g[[col, RESP] + controls].dropna()
        if len(g) < 100:
            continue
        r = g.rank(pct=True)
        X = np.column_stack([np.ones(len(r)), r[controls].to_numpy()])
        res = r[col].to_numpy() - X @ np.linalg.lstsq(X, r[col].to_numpy(), rcond=None)[0]
        out[a] = pd.Series(res).corr(r[RESP].reset_index(drop=True), method="spearman")
    return pd.Series(out).sort_index()


def main():
    old_keyed = factors.SIGNAL_WEIGHTS[TIER]
    old = {_ranked_col(k, TIER): w for k, w in old_keyed.items()}
    panel, cols = load_panel(sorted(set(old) | {COL}))
    assert COL in cols, f"{COL} is not in daily_snapshots_pit — run the PIT backfill first"
    tiers = {}
    for tier in ("SMALL", "MID", "LARGE"):
        t = panel[panel["cap_tier"] == tier]
        n_per = t.groupby("snapshot_date")[COL].count()
        t = t[t["snapshot_date"].isin(n_per[n_per >= 50].index)]
        s = ic_series(t, COL)
        h = len(s) // 2
        tiers[tier] = dict(n=len(s), ic=round(s.mean(), 4), t=round(t_of(s), 2),
                           halves=[round(s.iloc[:h].mean(), 4), round(s.iloc[h:].mean(), 4)],
                           t_since_2024_09=round(t_of(s[s.index >= "2024-09-01"]), 2),
                           first=s.index.min() if len(s) else None)
        if tier == TIER:
            small, ic_small = t, s
    sm = tiers[TIER]

    def rho(a, b):
        vals = [g[a].corr(g[b], method="spearman")
                for _, g in small[["snapshot_date", a, b]].dropna().groupby("snapshot_date") if len(g) >= 20]
        return float(np.nanmean(vals)) if vals else 0.0
    corr = {c: round(rho(COL, c), 3) for c in old}
    res = residual_ic(small, COL, list(old))
    gate = dict(t_ok=sm["t"] >= 2.5 and sm["n"] >= 24,
                halves_ok=bool(np.sign(sm["halves"][0]) == np.sign(sm["halves"][1]) == np.sign(sm["ic"]) != 0),
                not_copy=all(abs(v) < 0.5 for v in corr.values()))
    gate["pass"] = all(gate.values())

    w_new = float(np.mean([abs(w) for w in old.values()]))
    new = dict(old)
    new[COL] = w_new
    tot = sum(abs(w) for w in new.values())
    new = {c: round(w / tot, 4) for c, w in new.items()}

    # whole-score test on every SMALL anchor of the panel
    allsmall = panel[panel["cap_tier"] == TIER]
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier", "fwd_21"])
    frames = []
    for name, w in (("small_old", old), ("small_new", new)):
        for a, g in allsmall.groupby("snapshot_date"):
            g = g.set_index("sid")
            s = composite(g, w)
            frames.append(pd.DataFrame({"sid": s.index, "snapshot_date": a, "cap_tier": TIER, "method": name,
                                        "score": s.to_numpy(float), "pct_rank": s.rank(pct=True).to_numpy(float),
                                        "oos": False}))
    sc = pd.concat(frames, ignore_index=True)
    whole = {}
    for name, g in sc.groupby("method"):
        d = g.merge(lab, on=["sid", "snapshot_date"]).dropna(subset=["fwd_21"])
        per = d.groupby("snapshot_date")[["score", "fwd_21"]].apply(lambda x: x["score"].rank().corr(x["fwd_21"].rank()))
        tmb = d.groupby("snapshot_date")[["score", "fwd_21"]].apply(
            lambda x: x.loc[x["score"] >= x["score"].quantile(.9), "fwd_21"].mean()
            - x.loc[x["score"] <= x["score"].quantile(.1), "fwd_21"].mean())
        whole[name] = dict(ic21=round(per.mean(), 4), ic21_t=round(t_of(per), 2),
                           top_minus_bottom=round(tmb.mean(), 4), tmb_t=round(t_of(tmb), 2), anchors=len(per))
    import tools.lh_book as B
    B.DB = Path(os.environ.get("ALPHA_DB", B.DB))   # lh_book ignores ALPHA_DB (worktree has no data/)
    starts = sorted(sc.loc[sc["snapshot_date"] >= "2022-06-01", "snapshot_date"].unique())
    starts = [s for s in starts if s[8:10] <= "07"][:12]
    rows = []
    for stt in starts:
        d = V2 / "win_small_promote"
        d.mkdir(parents=True, exist_ok=True)
        sc[sc["snapshot_date"] >= stt].to_parquet(d / "oos_scores.parquet", index=False)
        if not (d / "labels.parquet").exists():
            os.symlink(LH / "labels.parquet", d / "labels.parquet")
        B.LH = d
        D = B.Data()
        bench = B.benchmark(D, TIER)
        for name in ("small_old", "small_new"):
            r, _ = B.simulate(D, TIER, dict(method=name, reb="M", N=20, k=2, score="raw", min_hold=0, defer=False,
                                            block="r"), bench)
            rows.append(dict(start=stt, method=name, excess=r["excess_cagr"], t=r["t_nw"], turnover=r["turnover_pa"]))
    bk = pd.DataFrame(rows)
    summ = bk.groupby("method").agg(median_excess=("excess", "median"), min_excess=("excess", "min"),
                                    starts_beating=("excess", lambda v: int((v > 0).sum())),
                                    median_t=("t", "median"), turnover=("turnover", "median"))
    o, n = summ.loc["small_old"], summ.loc["small_new"]
    accept = bool(gate["pass"] and n["median_excess"] >= o["median_excess"]
                  and n["starts_beating"] >= o["starts_beating"]
                  and whole["small_new"]["ic21_t"] >= whole["small_old"]["ic21_t"])
    key_of = {_ranked_col(k, TIER): k for k in old_keyed}
    out = dict(factor=tiers, corr_with_wired=corr, residual_ic=dict(mean=round(res.mean(), 4), t=round(t_of(res), 2),
                                                                   n=len(res)),
               gate=gate, old=old_keyed, new_weights={key_of.get(c, c): w for c, w in new.items()},
               whole_score=whole, books=summ.round(4).reset_index().to_dict("records"), accept=accept)
    V2.mkdir(parents=True, exist_ok=True)
    (V2 / "small_promote_q_ebitda.json").write_text(json.dumps(out, indent=1, default=str))
    bk.to_csv(V2 / "small_promote_q_ebitda_books.csv", index=False)
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
