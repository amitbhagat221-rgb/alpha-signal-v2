"""
Plan 0025 tasks 1.3 / 2.1 / 2.2 — the `slow_v2` score, its horizon test and its long-hold book
(READ-ONLY on the DB; writes only under data/lh/v2/).

PRE-REGISTRATION (written 2026-10-13 before any slow_v2 result):

slow_v2 (equal weights, nothing fitted). At each monthly anchor, within each tier, the mean of
three within-tier percentiles (higher = better; a missing component counts 0.5, as
config.MISSING_FACTOR_SCORE):
  1. mom_6m                         (PIT panel)
  2. quality x value                = mean percentile of a_roce and book_to_price (tools.lh_growth
                                      features; Financials have no a_roce, so book_to_price alone)
  3. a_piotroski_lite               (tools.lh_growth: 8 Piotroski tests on annual Screener, 2019+;
                                      used throughout for one consistent definition; the live
                                      piotroski_f starts 2024-09 and is NOT mixed in)
No delivery, event, consensus or option signal.
Honesty note: these components were picked after tools.lh_growth looked at 2019–26, so this is
in-sample *selection* with no fitted weights. Per-period signs, the luck tests and the forward /
pre-2019 history (plan 0025 5.2) are the out-of-sample evidence; nothing here is.

fast_v1 (task 1.2 snapshot, for comparison and for the tactical book): today's live weights
(factors.FACTORS weights, pit_column_v2) applied to the PIT panel percentiles, missing = 0.5,
minus forensic_penalty. Approximation: no eligibility renormalisation for Financials.

2.1 horizon test: rank IC at 21 / 63 / 126 / 252 sessions (data/lh/labels.parquet), Newey-West t
(lag = horizon in months), non-overlap t (mean of the every-(h/21)-th-anchor subsample t's),
top-decile mean excess vs the tier median, IC by period 2020-22 / 2023-24 / 2025-26, and the
mean cross-sectional correlation with plan 0024's slow_select.
  Bar: SMALL or MID non-overlap t >= 2.0 at 126 with the sign held in every period.

2.2 book (tools.lh_book machinery unchanged: costs, Indian tax, benchmark, forensic red-flag
forced sale):
  Window A = 2022-06 → 2026-10 (plan 0024's window, comparable); window B = 2019-12 → 2026-10.
  Primary: the template rule  monthly · top 10 · sell below 30 · 3-month average · 12-month min
  hold · tax deferral, on slow_v2, SMALL and MID, window A.
  Bar: excess after costs and tax with t_nw >= 2.0 (monthly book returns, NW lag 3 as plan 0024)
  AND the full 48 grid on slow_v2 in window A has DSR(N_eff) >= 0.95 and PBO <= 0.20
  (tools.lh_luck).
  Reported, not deciding: window B; the template on slow_select and fast_v1 (window A); the
  template with the forensic red-flag sale switched off; LARGE.

Usage:
  python -m tools.lh_slow_v2 build      # scores → data/lh/v2/scores_all.parquet
  python -m tools.lh_slow_v2 horizon    # 2.1 → data/lh/v2/horizon.csv
  python -m tools.lh_slow_v2 book       # 2.2 → data/lh/v2/book_*.{csv,parquet,json}
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import factors  # noqa: E402
from tools.backtest_pit import _aggregate, _compute_ic  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
TIERS = ("LARGE", "MID", "SMALL")
HORIZONS = (21, 63, 126, 252)
NW_LAG = {21: 1, 63: 3, 126: 6, 252: 12}
PERIODS = {"2020-22": ("0000", "2022-12-31"), "2023-24": ("2023-01-01", "2024-12-31"),
           "2025-26": ("2025-01-01", "9999")}
WINDOW_A = "2022-06-01"
TEMPLATE = dict(reb="M", N=10, k=3, score="avg3", min_hold=12, defer=True)


def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


# ───────────────────────────── 1.3 build ─────────────────────────────

def build():
    V2.mkdir(parents=True, exist_ok=True)
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier"])
    lab = lab[lab["cap_tier"].isin(TIERS)]
    anchors = sorted(lab["snapshot_date"].unique())
    gf = pd.read_parquet(LH / "growth_features.parquet",
                         columns=["sid", "snapshot_date", "a_roce", "a_piotroski_lite"])
    wired = {k: f for k, f in factors.FACTORS.items() if f.get("weights")}
    col = {k: f.get("pit_column_v2") or k for k, f in wired.items()}
    need = sorted(set(col.values()) | {"mom_6m", "book_to_price", "forensic_penalty"})
    con = ro()
    ph = ",".join("?" * len(anchors))
    pan = pd.read_sql(f"SELECT sid, snapshot_date, {', '.join(need)} FROM daily_snapshots_pit "
                      f"WHERE snapshot_date IN ({ph})", con, params=anchors)
    con.close()
    df = lab.merge(pan, on=["sid", "snapshot_date"], how="left").merge(gf, on=["sid", "snapshot_date"], how="left")
    grp = df.groupby(["snapshot_date", "cap_tier"])
    pct = lambda c: grp[c].rank(pct=True)  # noqa: E731

    # slow_v2
    qv = pd.concat([pct("a_roce"), pct("book_to_price")], axis=1).mean(axis=1)  # mean of available
    comps = pd.concat([pct("mom_6m"), qv, pct("a_piotroski_lite")], axis=1).fillna(0.5)
    df["slow_v2"] = comps.mean(axis=1)
    df["slow_v2_cover"] = pd.concat([df["mom_6m"].notna(), qv.notna(), df["a_piotroski_lite"].notna()],
                                    axis=1).sum(axis=1)

    # fast_v1 = live weights on the panel
    fast = pd.Series(0.0, index=df.index)
    for tier in TIERS:
        m = df["cap_tier"] == tier
        ws = {k: f["weights"][tier] for k, f in wired.items() if tier in f["weights"]}
        tot = sum(abs(w) for w in ws.values())
        s = sum(abs(w) * (pct(col[k])[m].fillna(0.5) if w > 0 else 1 - pct(col[k])[m].fillna(0.5))
                for k, w in ws.items())
        fast[m] = s / tot
    df["fast_v1"] = fast + df["forensic_penalty"].fillna(0.0)

    rows = []
    for meth in ("slow_v2", "fast_v1"):
        x = df[["sid", "snapshot_date", "cap_tier", meth]].rename(columns={meth: "score"}).dropna()
        x["pct_rank"] = x.groupby(["snapshot_date", "cap_tier"])["score"].rank(pct=True)
        rows.append(x.assign(method=meth, oos=True))
    old = pd.read_parquet(LH / "oos_scores.parquet")
    rows.append(old[old["method"] == "slow_select"])
    out = pd.concat(rows, ignore_index=True)[["sid", "snapshot_date", "cap_tier", "method", "score", "pct_rank", "oos"]]
    out.to_parquet(V2 / "scores_all.parquet", index=False)
    cov = df.groupby("cap_tier")["slow_v2_cover"].apply(lambda s: s.value_counts(normalize=True).round(3).to_dict())
    print("slow_v2 components present (share of rows):", cov.to_dict())
    print(out.groupby("method")["snapshot_date"].agg(["min", "max", "nunique"]))
    return out


# ───────────────────────────── 2.1 horizon ─────────────────────────────

def nonoverlap_t(rows, h):
    step = max(h // 21, 1)
    s_all = pd.Series([r[1] for r in rows], index=[r[0] for r in rows]).sort_index()
    ts = [s.mean() / (s.std() / np.sqrt(len(s))) for s in (s_all.iloc[o::step] for o in range(step))
          if len(s) >= 3 and s.std() > 0]
    return float(np.mean(ts)) if ts else None


def horizon():
    sc = pd.read_parquet(V2 / "scores_all.parquet")
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier"]
                          + [f"fwd_{h}" for h in HORIZONS])
    piv = sc.pivot_table(index=["sid", "snapshot_date"], columns="method", values="score").reset_index()
    df = lab.merge(piv, on=["sid", "snapshot_date"], how="inner")
    recs = []
    for meth in ("slow_v2", "fast_v1", "slow_select"):
        for tier in TIERS:
            tdf = df[df["cap_tier"] == tier]
            for h in HORIZONS:
                rows = _compute_ic(tdf, meth, f"fwd_{h}")
                r = _aggregate(rows, meth, tier, "lh", cadence="monthly", nw_lag=NW_LAG[h]) if rows else None
                if not r:
                    continue
                ex = []
                for _, g in tdf[[meth, f"fwd_{h}"]].join(tdf["snapshot_date"]).dropna().groupby("snapshot_date"):
                    if len(g) >= 30:
                        ex.append(g.loc[g[meth] >= g[meth].quantile(.9), f"fwd_{h}"].mean() - g[f"fwd_{h}"].median())
                rec = dict(method=meth, tier=tier, h=h, n=r["n_periods"], first=min(x[0] for x in rows)[:7],
                           ic=round(r["mean_ic"], 4), t_nw=round(r["t_stat"], 2),
                           t_nonoverlap=round(nonoverlap_t(rows, h), 2), top10_excess=round(float(np.mean(ex)), 4))
                for p, (lo, hi) in PERIODS.items():
                    sub = [x[1] for x in rows if lo <= x[0] <= hi]
                    rec[f"ic_{p}"] = round(float(np.mean(sub)), 4) if len(sub) >= 3 else None
                recs.append(rec)
    t = pd.DataFrame(recs)
    # correlation of slow_v2 with slow_select and fast_v1 (mean per-anchor Spearman, within tier)
    corr = {}
    for tier in TIERS:
        tdf = df[df["cap_tier"] == tier]
        for other in ("slow_select", "fast_v1"):
            cs = [g["slow_v2"].corr(g[other], method="spearman") for _, g in
                  tdf[["snapshot_date", "slow_v2", other]].dropna().groupby("snapshot_date") if len(g) >= 20]
            corr[f"{tier}:{other}"] = round(float(np.mean(cs)), 3) if cs else None
    t.to_csv(V2 / "horizon.csv", index=False)
    (V2 / "horizon_corr.json").write_text(json.dumps(corr, indent=1))
    pd.set_option("display.width", 220)
    print(t.to_string(index=False))
    print("mean within-tier rank correlation:", corr)
    return t


# ───────────────────────────── 2.2 book ─────────────────────────────

def _prepare_dir(window):
    d = V2 / f"win_{window}"
    d.mkdir(parents=True, exist_ok=True)
    sc = pd.read_parquet(V2 / "scores_all.parquet")
    lo = WINDOW_A if window == "A" else "0000"
    meths = ("slow_v2", "slow_select", "fast_v1") if window == "A" else ("slow_v2", "fast_v1")
    sc = sc[(sc["snapshot_date"] >= lo) & sc["method"].isin(meths)]
    sc.to_parquet(d / "oos_scores.parquet", index=False)
    link = d / "labels.parquet"
    if not link.exists():
        os.symlink(LH / "labels.parquet", link)
    return d


def book(windows=("A", "B")):
    import tools.lh_book as B
    from tools.lh_luck import n_effective, pbo, sharpe
    summary = {}
    for w in windows:
        B.LH = _prepare_dir(w)
        D = B.Data()
        flags_real = D.flags
        results, monthly = [], []
        for tier in TIERS:
            cache = {}

            def go(v, kind, trials, flags=None):
                key = (0.0, "today", B.CAPITAL)
                if key not in cache:
                    cache[key] = B.benchmark(D, tier)
                D.flags = flags if flags is not None else flags_real
                r, m = B.simulate(D, tier, v, cache[key])
                D.flags = flags_real
                r["t_haircut"] = round(B.haircut_t(r["t_nw"], r["n_months"], trials), 3) if r["t_nw"] is not None else None
                r.update(tier=tier, kind=kind, variant=B.vname(v) + ("|noflag" if flags is not None else ""),
                         window=w, **{k_: v[k_] for k_ in ("method", "reb", "N", "k", "score", "min_hold")})
                results.append(r)
                monthly.append(m.assign(tier=tier, variant=r["variant"], kind=kind, window=w))
                return r

            tmpl = dict(TEMPLATE, method="slow_v2", block="template")
            go(tmpl, "template", 1)
            go(tmpl, "template_noflag", 1, flags=[set() for _ in D.flags])
            if w == "A":
                for meth in ("slow_select", "fast_v1"):
                    go(dict(tmpl, method=meth), "template_compare", 1)
                for v in B.grid(method="slow_v2"):
                    go(v, "grid", 48)
        res = pd.DataFrame([{k: v for k, v in r.items() if k != "_x"} for r in results])
        mon = pd.concat(monthly, ignore_index=True)
        res.to_csv(V2 / f"book_variants_{w}.csv", index=False)
        mon.to_parquet(V2 / f"book_monthly_{w}.parquet", index=False)
        for tier in TIERS:
            rr = res[res["tier"] == tier]
            s = {}
            for _, r in rr[rr["kind"] != "grid"].iterrows():
                s[r["variant"]] = dict(excess_cagr=r["excess_cagr"], t_nw=r["t_nw"], hold=r["median_hold_km_m"],
                                       turnover=r["turnover_pa"], worst12=r["worst_12m_excess"],
                                       lt_share=r["lt_share_of_gains"], cagr=r["cagr_after_tax"],
                                       bench=r["bench_cagr_after_tax"], months=r["n_months"])
            if w == "A":
                g = mon[(mon["tier"] == tier) & (mon["kind"] == "grid")].sort_values(["variant", "i"])
                X = pd.DataFrame({v: (lambda a, b: (a[1:] / a[:-1] - 1) - (b[1:] / b[:-1] - 1))(
                    gg["atlv"].to_numpy(float), gg["bench"].to_numpy(float)) for v, gg in g.groupby("variant")})
                from tools.lh_book import deflated_sharpe
                srs = X.apply(sharpe)
                ne, rho, _ = n_effective(X)
                dsr, _, _ = deflated_sharpe(X[srs.idxmax()], srs.values, max(ne, 2))
                p = pbo(X)
                gr = rr[rr["kind"] == "grid"]
                s["grid"] = dict(n=len(gr), median_excess=float(gr["excess_cagr"].median()),
                                 median_t=float(gr["t_nw"].median()), max_t=float(gr["t_nw"].max()),
                                 share_beating_index=float((gr["excess_cagr"] > 0).mean()),
                                 best_by_sharpe=srs.idxmax(), n_eff=round(ne, 1), dsr_neff=round(dsr, 3), **p)
            summary[f"{w}:{tier}"] = s
    (V2 / "book_summary.json").write_text(json.dumps(summary, indent=1, default=str))
    for k, s in summary.items():
        print(f"\n== {k}")
        for name, d in s.items():
            print(f"  {name}: {d}")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["build", "horizon", "book"])
    ap.add_argument("--window", choices=["A", "B", "both"], default="both")
    a = ap.parse_args()
    if a.step == "build":
        build()
    elif a.step == "horizon":
        horizon()
    else:
        book(("A", "B") if a.window == "both" else (a.window,))


if __name__ == "__main__":
    main()
