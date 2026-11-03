"""
Which three models?  Slow, Fast and Blend, selected under a better factor bar.  (READ-ONLY on the DB; writes
only under data/lh/model_select/. Changes no live weight and not the paper sleeve.)

Amit 2026-11-03: "this is needless have 3 models at max slow fast and blend and use a better bar, do backtesting
and select the three models."

PRE-REGISTRATION (written 2026-11-03, before any result of this test).

Candidates. Every month, per tier (MID, SMALL), from the training window only, a bar chooses at most K factors,
equal weight, training sign. Slow learns on the 126-session label (K 8, Newey-West t lag 6, the embargo of
tools.lh_slow_model). Fast learns on the 20-session label (K 6, the embargo of tools.walk_forward). Four bars:
  old    today's rule, the control: |t| >= 2.5, at least 12 training months.
  fdr    at least 24 training months; two-sided p from t with n-1 degrees of freedom; Benjamini-Yekutieli
         adjusted p <= 0.05 across every factor eligible that month (ADR 0043's headline correction).
  long   |t| >= 2.5, at least 24 training months, AND the long-side test: the quintile the sign says to buy beat
         the tier average with t >= 2.0 in training. A long-only book cannot earn an IC that lives in the losers.
  full   fdr AND the long-side test AND the same sign in each of the three equal thirds of training AND no two
         chosen factors alike (greedy from the strongest; skip one whose mean rank correlation with a chosen
         factor over the last 12 training months exceeds 0.7 in absolute value).
A month with no factor passing carries the last non-empty set forward. Before any set exists the book holds cash,
and those months count against it.

Blend. No search of its own: the mean of the winning Slow and winning Fast scores, on a rule fixed here as the
midpoint of the two: top 20 by this month's score, sell below rank 50, 6-month minimum hold.

Books. tools.lh_book unchanged (measured costs, Indian tax, tier index with dividends, after-tax liquidation value,
monthly Newey-West t lag 3). As the paper books run: trusts and names under the Rs 1 crore 20-session median traded
value are never bought, sells are never blocked, ranks stay on the whole tier, no forensic forced sale.
  Slow  top 20 by the 3-month average score, sell below rank 60, 12-month minimum hold, tax deferral.
  Fast  top 20 by this month's score, sell below rank 40, no minimum hold, no deferral.

Selection window: anchors 2022-06-01 to 2026-06-01. June 2026 onward (the paper books' window, which Amit and I have
both already seen) never enters the decision and is reported separately as a hold-out.

Decision. One bar for Slow and one bar for Fast, the same in both tiers, because choosing per tier on 48 months
doubles the selection. Highest mean of the MID and SMALL book t. Within 0.25 of the top, the stricter bar wins
(full, then fdr, then long, then old). If `old` wins, it stays, and the report says the better bar added nothing.
Whole-tier rank IC is reported and does not decide.

Grades. ADR 0073 unchanged, per tier, on the selection window, over every series run in that tier (controls included):
  A  t >= 2.0 after the Bonferroni variant haircut; DSR(N_eff) >= 0.95; PBO <= 0.20.
  B  t >= 1.5; DSR >= 0.90 or PBO <= 0.30; beats the index in >= 3 of 5 calendar years and in >= 10 of 12 staggered
     start months (2022-06 to 2023-05); worst 12-month excess >= -15 %.
  C  anything less. A grade C model still takes its slot on the page, labelled C: Amit asked for three models, and
     the grade says how far to trust each.

Controls, run on the same engine, never selectable: slow_v2 and fast_v1 (fixed recipes chosen on this same history),
slow_icw (no bar), blend as it stood (mean of the old slow and fast, on the old 12-month slow rule).

Known limits: today's listed universe (survivorship ~2.8 %/yr in SMALL, ADR 0073), and MID's benchmark before
2023-06 is the tier equal-weight average (tools.lh_book).

Usage:
  python -m tools.model_select --smoke     # SMALL, one start, to 2023-06
  python -m tools.model_select             # the test (writes data/lh/model_select/results.json)
  python -m tools.model_select --reuse     # the test on the saved candidate scores
  python -m tools.model_select --score     # the selected models only: data/lh/model_select/models.parquet
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tools.lh_book as B  # noqa: E402
from tools.lh_luck import n_effective, pbo  # noqa: E402
from tools.lh_slow_model import FAST, EMBARGO_MIN, LABEL_SESSIONS, MIN_TRAIN, evaluate, ic_table, load, nw_t  # noqa: E402
from tools.backtest_pit import IC_MIN_PERIODS  # noqa: E402
from tools.multiple_testing import _bh_adjusted  # noqa: E402
from tools.walk_forward import composite  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
OUT = LH / "model_select"
TIERS = ("MID", "SMALL")
BARS = ("old", "fdr", "long", "full")
STRICTNESS = {"full": 3, "fdr": 2, "long": 1, "old": 0}     # the tie-break
MODELS = {"slow": dict(resp="fwd_126", lag=6, K=8), "fast": dict(resp=FAST, lag=1, K=6)}
MIN_N = 24
T_OLD, LONG_T, BY_Q, REDUNDANT, TIE = 2.5, 2.0, 0.05, 0.7, 0.25
WINDOW = ("2022-06-01", "2026-06-01")
N_STARTS = 12
FLOOR_INR = 1e7
RULES = {"slow": dict(reb="M", N=20, k=3, score="avg3", min_hold=12, defer=True, block="t"),
         "fast": dict(reb="M", N=20, k=2, score="raw", min_hold=0, defer=False, block="t"),
         "blend": dict(reb="M", N=20, k=2.5, score="raw", min_hold=6, defer=False, block="t")}
# The result of the pre-registered test (2026-11-03, data/lh/model_select/results.json; docs/studies/model-select-2026-11.md)
SELECTED = {"slow": "long", "fast": "fdr"}


def log(*a):
    print(*a, flush=True)


# ── the bars ───────────────────────────────────────────────────────────────────────────────────

def tail_tables(tdf, cols, resp):
    """{col: DataFrame(anchor -> top, bot)}: each quintile's mean label minus the tier mean, per anchor."""
    out = {c: {} for c in cols}
    for a, g in tdf.groupby("snapshot_date"):
        r = g[resp]
        ok = r.notna()
        if ok.sum() < 20:
            continue
        mean = r[ok].mean()
        for c in cols:
            v = g[c][ok]
            if v.notna().sum() < 20:
                continue
            pct = v.rank(pct=True)
            out[c][a] = (float(r[ok][pct >= 0.8].mean() - mean), float(r[ok][pct <= 0.2].mean() - mean))
    return {c: pd.DataFrame.from_dict(d, orient="index", columns=["top", "bot"]).sort_index() for c, d in out.items() if d}


def train_stats(ic_tab, train, lag, simple=False):
    """{col: dict(mean, t, n, p)} on the training anchors."""
    out = {}
    for c, s in ic_tab.items():
        x = s[s.index.isin(train)]
        n = len(x)
        if n < IC_MIN_PERIODS or x.std(ddof=1) == 0:
            continue
        v = x.to_numpy()
        t = float(v.mean() / (v.std(ddof=1) / np.sqrt(n))) if simple else nw_t(v, lag)
        if not np.isfinite(t):
            continue
        out[c] = dict(mean=float(v.mean()), t=t, n=n, p=float(2 * stats.t.sf(abs(t), n - 1)))
    return out


def by_pass(st):
    """Columns whose Benjamini-Yekutieli adjusted p clears the bar, over every factor with >= MIN_N months."""
    cols = [c for c, s in st.items() if s["n"] >= MIN_N]
    if not cols:
        return set()
    adj = _bh_adjusted(np.array([st[c]["p"] for c in cols]), float(np.sum(1 / np.arange(1, len(cols) + 1))))
    return {c for c, a in zip(cols, adj) if a <= BY_Q}


def long_pass(c, s, tails, train, lag):
    """The quintile the sign says to buy beat the tier average in training, with t >= LONG_T."""
    d = tails.get(c)
    if d is None:
        return False
    y = d.loc[d.index.isin(train), "top" if s["mean"] > 0 else "bot"].to_numpy()
    if len(y) < MIN_N:
        return False
    t = nw_t(y, lag)
    return bool(np.isfinite(t) and t >= LONG_T and y.mean() > 0)


def stable_pass(s_ic, train, sign):
    """The same sign in each of the three equal consecutive thirds of training."""
    x = s_ic[s_ic.index.isin(train)].to_numpy()
    return all(np.sign(part.mean()) == sign for part in np.array_split(x, 3) if len(part))


def dedupe(ordered, K, by_date, train):
    """Greedy from the strongest: skip a factor too alike a chosen one over the last 12 training months."""
    if len(ordered) < 2:
        return ordered[:K]
    frames = [by_date[a][ordered].rank().corr().abs() for a in sorted(train)[-12:] if a in by_date]
    corr = sum(frames) / len(frames) if frames else None
    chosen = []
    for c in ordered:
        if corr is None or all(not (corr.loc[c, k] > REDUNDANT) for k in chosen):
            chosen.append(c)
        if len(chosen) == K:
            break
    return chosen


def choose(bar, st, ic_tab, tails, train, K, lag, by_date):
    """{col: sign} under one bar, from training stats only."""
    strength = lambda c: -abs(st[c]["t"])
    if bar == "old":
        keep = [c for c, s in st.items() if abs(s["t"]) >= T_OLD]
    elif bar == "fdr":
        keep = list(by_pass(st))
    elif bar == "long":
        keep = [c for c, s in st.items() if s["n"] >= MIN_N and abs(s["t"]) >= T_OLD and long_pass(c, s, tails, train, lag)]
    elif bar == "full":
        keep = [c for c in by_pass(st) if long_pass(c, st[c], tails, train, lag)
                and stable_pass(ic_tab[c], train, np.sign(st[c]["mean"]))]
    else:
        raise ValueError(bar)
    keep = sorted(keep, key=strength)
    keep = dedupe(keep, K, by_date, train) if bar == "full" else keep[:K]
    return {c: float(np.sign(st[c]["mean"])) for c in keep}


# ── walk forward ───────────────────────────────────────────────────────────────────────────────

def walk(bars=BARS, tiers=TIERS, end=None):
    """Candidate scores for every (model, bar). Returns (scores, choices, IC records)."""
    df, cols, anchors, entry, _ = load()
    # labels.parquet has no session count for the newest month until its next rebuild, and load() casts that NaN to a
    # huge negative number, which would silently drop the newest anchor. Only that anchor's own position needs it, and
    # the 126-session embargo keeps it far from any training month, so a 21-session estimate is safe.
    entry = entry.copy()
    for i in range(1, len(entry)):
        if entry[i] < entry[i - 1]:
            entry[i] = entry[i - 1] + 21
    frames, choices, recs = [], [], []
    for tier in tiers:
        tdf = df[df["cap_tier"] == tier]
        log(f"[{tier}] IC and quintile tables on {len(cols)} columns …")
        ic = {m: ic_table(tdf[["snapshot_date", *cols, c["resp"]]], cols, c["resp"]) for m, c in MODELS.items()}
        tails = {m: tail_tables(tdf, cols, c["resp"]) for m, c in MODELS.items()}
        by_date = {a: g.set_index("sid") for a, g in tdf.groupby("snapshot_date")}
        last = {}
        for k, a in enumerate(anchors):
            if a not in by_date or (end and a > end):
                continue
            slow_train = [anchors[j] for j in range(k) if k - j >= EMBARGO_MIN and entry[k] - entry[j] >= LABEL_SESSIONS + 1]
            if len(slow_train) < MIN_TRAIN:
                continue
            train = {"slow": set(slow_train), "fast": set(anchors[:k - 1])}
            g = by_date[a]
            for m, c in MODELS.items():
                old_st = train_stats(ic[m], train[m], c["lag"], simple=m == "fast")
                new_st = train_stats(ic[m], train[m], c["lag"])
                for bar in bars:
                    st = old_st if bar == "old" else new_st
                    w = choose(bar, st, ic[m], tails[m], train[m], c["K"], c["lag"], by_date)
                    empty = not w
                    w = w or last.get((m, bar), {})
                    if w:
                        last[(m, bar)] = w
                    w = {x: v for x, v in w.items() if x in g.columns}
                    name = f"{m}_{bar}"
                    choices.append(dict(tier=tier, anchor=a, method=name, n_factors=len(w), carried=empty,
                                        factors=json.dumps(w), t=json.dumps({x: round(st[x]["t"], 2) for x in w if x in st})))
                    if not w:
                        continue
                    s = composite(g, w)
                    recs.append(dict(tier=tier, anchor=a, method=name, n_factors=len(w), **evaluate(g, s)))
                    frames.append(pd.DataFrame({"sid": s.index, "snapshot_date": a, "cap_tier": tier, "method": name,
                                                "score": s.to_numpy(float), "pct_rank": s.rank(pct=True).to_numpy(float),
                                                "oos": True}))
            if k % 12 == 0:
                log(f"  {tier} {a} done")
    return pd.concat(frames, ignore_index=True), pd.DataFrame(choices), pd.DataFrame(recs)


def add_blend(sc, slow_method, fast_method, name):
    a = sc[sc["method"] == slow_method].set_index(["sid", "snapshot_date", "cap_tier"])["score"]
    b = sc[sc["method"] == fast_method].set_index(["sid", "snapshot_date", "cap_tier"])["score"]
    s = pd.concat([a, b], axis=1).mean(axis=1).rename("score").reset_index()
    s["method"] = name
    s["pct_rank"] = s.groupby(["snapshot_date", "cap_tier"])["score"].rank(pct=True)
    s["oos"] = True
    return pd.concat([sc, s[sc.columns]], ignore_index=True)


def controls():
    cols = ["sid", "snapshot_date", "cap_tier", "method", "score", "pct_rank", "oos"]
    a = pd.read_parquet(LH / "oos_scores.parquet", columns=cols)
    a = a[a["method"].isin(["slow_icw", "blend"])]
    b = pd.read_parquet(LH / "v2" / "scores_all.parquet", columns=cols)
    b = b[b["method"].isin(["slow_v2", "fast_v1"])]
    out = pd.concat([a, b], ignore_index=True)
    out["method"] = out["method"].map(lambda m: f"ctl_{m}")
    return out


CONTROL_RULES = {"ctl_slow_v2": "slow", "ctl_slow_icw": "slow", "ctl_blend": "slow", "ctl_fast_v1": "fast"}


# ── the book test ──────────────────────────────────────────────────────────────────────────────

def trusts():
    from config import SCREEN
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    st = pd.read_sql("SELECT sid, name FROM stocks", con)
    con.close()
    pats = SCREEN.get("trust_exclusion_patterns", [])
    return set(st.loc[st["name"].str.contains("|".join(pats), case=False, regex=True, na=False), "sid"]) if pats else set()


def load_data(sc, lo, hi, tr):
    """lh_book's Data on one window, with the paper books' buying rules: the buy list drops trusts and names under the
    floor, the ranks that decide a sale stay on the whole tier, and no forensic forced sale."""
    win = OUT / "win"
    win.mkdir(parents=True, exist_ok=True)
    sc[(sc["snapshot_date"] >= lo) & (sc["snapshot_date"] <= hi)].to_parquet(win / "oos_scores.parquet", index=False)
    link = win / "labels.parquet"
    if not link.exists():
        os.symlink(LH / "labels.parquet", link)
    B.LH = win
    D = B.Data()
    D.flags = [set() for _ in D.anchors]
    for per in D.rank.values():
        for i, r in enumerate(per):
            adtv = D.adtv[i]
            r["order"] = {t: [s for s in o if s not in tr and adtv.get(s, 0) >= FLOOR_INR] for t, o in r["order"].items()}
    return D


def rule_of(method):
    if method in CONTROL_RULES:
        return RULES[CONTROL_RULES[method]]
    return RULES[method.split("_")[0]]


def run_books(D, tier, methods):
    bench = B.benchmark(D, tier)
    res, series = {}, {}
    for m in methods:
        if (m, RULES["slow"]["score"]) not in D.rank:
            continue
        v = dict(method=m, **rule_of(m))
        r, mon = B.simulate(D, tier, v, bench)
        a, b = mon["atlv"].to_numpy(float), mon["bench"].to_numpy(float)
        x = pd.Series((a[1:] / a[:-1] - 1) - (b[1:] / b[:-1] - 1), index=mon["date"].to_numpy()[1:])
        years = {}
        for y in sorted({str(d)[:4] for d in mon["date"]}):
            idx = [i for i, d in enumerate(mon["date"]) if str(d)[:4] == y]
            lo = max(idx[0] - 1, 0)
            years[y] = float(a[idx[-1]] / a[lo] / (b[idx[-1]] / b[lo]) - 1)
        res[m] = dict(excess_cagr=r["excess_cagr"], cagr=r["cagr_after_tax"], bench_cagr=r["bench_cagr_after_tax"], t=r["t_nw"],
                      worst_12m=r["worst_12m_excess"], max_dd=r["max_drawdown"], turnover=r["turnover_pa"],
                      costs_bps=r["costs_bps_pa"], months_no_score=r["months_without_scores"],
                      cash=r["avg_cash_share"], n_months=r["n_months"], years=years)
        series[m] = x
    return res, series


def ic_summary(rec):
    out = {}
    if rec.empty:
        return out
    for (tier, m), g in rec.groupby(["tier", "method"]):
        g = g.sort_values("anchor")
        row = dict(avg_factors=round(float(g["n_factors"].mean()), 1))
        for h, lag in ((21, 1), (126, 6)):
            for label, part in (("sel", g[g["anchor"] < WINDOW[1]]), ("live", g[g["anchor"] >= WINDOW[1]])):
                x = part[f"ic{h}"].dropna() if f"ic{h}" in part else pd.Series(dtype=float)
                row[f"ic{h}_{label}"] = round(float(x.mean()), 4) if len(x) else None
                row[f"n{h}_{label}"] = len(x)
                row[f"t{h}_{label}"] = round(nw_t(x.to_numpy(), lag), 2) if len(x) > 3 else None
        out[f"{tier}|{m}"] = row
    return out


def pick(table, model):
    """Highest mean MID/SMALL t; within TIE of the top the stricter bar wins."""
    rows = []
    for bar in BARS:
        ts = [table[t][f"{model}_{bar}"]["t"] for t in table if f"{model}_{bar}" in table[t] and table[t][f"{model}_{bar}"]["t"] is not None]
        if len(ts) == len(table):
            rows.append((bar, float(np.mean(ts))))
    top = max(t for _, t in rows)
    near = [b for b, t in rows if t >= top - TIE]
    return max(near, key=lambda b: STRICTNESS[b]), dict(rows)


def grade(tier, m, table, series, starts):
    """ADR 0073, over every series run in this tier."""
    r = table[tier][m]
    X = pd.DataFrame(series[tier]).dropna()
    n_eff, rho, _ = n_effective(X)
    sr = [float(X[c].mean() / X[c].std(ddof=1)) for c in X.columns]
    dsr, _, _ = B.deflated_sharpe(X[m].to_numpy(), sr, max(n_eff, 2.0))
    p = pbo(X)
    hair = B.haircut_t(r["t"], len(X), X.shape[1])
    ys = r["years"]
    beat_years = sum(v > 0 for v in ys.values())
    st = [s[tier][m]["excess_cagr"] for s in starts if m in s.get(tier, {})]
    beat_starts = sum(v > 0 for v in st)
    worst = r["worst_12m"]
    a = hair is not None and hair >= 2.0 and dsr >= 0.95 and p["pbo"] <= 0.20
    b = (r["t"] or -9) >= 1.5 and (dsr >= 0.90 or p["pbo"] <= 0.30) and beat_years >= 3 and beat_starts >= 10 and (worst or -9) >= -0.15
    return dict(grade="A" if a else "B" if b else "C", t=r["t"], t_haircut=hair, dsr=round(dsr, 3), pbo=p["pbo"], n_eff=round(n_eff, 2),
                beat_years=beat_years, n_years=len(ys), beat_starts=beat_starts, n_starts=len(st), worst_12m=worst,
                starts_median=round(float(np.median(st)), 4) if st else None, trials=X.shape[1])


def holdout(sc, tr, tiers, methods):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    last = con.execute("SELECT MAX(date) FROM stock_prices").fetchone()[0]
    con.close()
    anchors = sorted(a for a in sc["snapshot_date"].unique() if a < last)
    i0 = anchors.index(WINDOW[1])
    if len(anchors) - i0 < 2:
        return {}
    # The 3-month average needs the months before the first buy, or June's basket would rest on June's score alone.
    D = load_data(sc, anchors[i0 - 2], anchors[-1], tr)
    for attr in ("anchors", "entry", "ret", "tier_of", "ew", "flags", "adtv", "price", "div", "tier_div_yield"):
        setattr(D, attr, getattr(D, attr)[2:])
    D.idx_level = {k: v[2:] for k, v in D.idx_level.items()}
    D.rank = {k: v[2:] for k, v in D.rank.items()}
    out = {}
    for t in tiers:
        res, series = run_books(D, t, methods)
        out[t] = {m: dict(excess=round(float((1 + series[m]).prod() - 1), 4), months=len(series[m])) for m in res}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--holdout", action="store_true", help="recompute only the hold-out in results.json (it never decides)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    if a.score:
        if not SELECTED:
            raise SystemExit("SELECTED is empty: run the test first")
        sc, cho, _ = walk(bars=tuple({SELECTED["slow"], SELECTED["fast"]}))
        slow, fast = f"slow_{SELECTED['slow']}", f"fast_{SELECTED['fast']}"
        sc = add_blend(sc, slow, fast, "blend")
        keep = {slow: "slow", fast: "fast", "blend": "blend"}
        sc = sc[sc["method"].isin(keep)].assign(method=lambda d: d["method"].map(keep))
        if sc.empty:
            raise SystemExit("no model scores produced")
        sc.to_parquet(OUT / "models.parquet", index=False)
        cho[cho["method"].isin(keep)].assign(method=lambda d: d["method"].map(keep)).to_csv(OUT / "model_factors.csv", index=False)
        log(f"wrote {OUT / 'models.parquet'}: {len(sc):,} rows to {sc['snapshot_date'].max()} in {time.time() - t0:.0f}s")
        return

    if a.holdout:
        r = json.loads((OUT / "results.json").read_text())
        sc = pd.read_parquet(OUT / "candidates.parquet")
        ctl = controls()
        ctl = ctl[ctl["cap_tier"].isin(TIERS) & (ctl["snapshot_date"] >= sc["snapshot_date"].min())]
        pool = add_blend(pd.concat([sc, ctl[sc.columns]], ignore_index=True), r["chosen"]["slow"], r["chosen"]["fast"], "blend_chosen")
        methods = [f"{m}_{b}" for m in MODELS for b in BARS] + list(CONTROL_RULES) + ["blend_chosen"]
        r["holdout"] = holdout(pool, trusts(), TIERS, methods)
        (OUT / "results.json").write_text(json.dumps(r, indent=1, default=str))
        for t in TIERS:
            log(t, {m: r["holdout"][t][m] for m in r["chosen"].values()})
        return

    tiers = ("SMALL",) if a.smoke else TIERS
    bars = ("old", "full") if a.smoke else BARS
    hi = "2023-06-01" if a.smoke else WINDOW[1]
    if a.reuse:
        sc = pd.read_parquet(OUT / "candidates.parquet")
        cho = pd.read_csv(OUT / "choices.csv")
        rec = pd.read_csv(OUT / "ic_records.csv")
    else:
        sc, cho, rec = walk(bars=bars, tiers=tiers, end=hi if a.smoke else None)
        if sc.empty:
            raise SystemExit("no candidate scores produced")
        sc.to_parquet(OUT / ("candidates_smoke.parquet" if a.smoke else "candidates.parquet"), index=False)
        cho.to_csv(OUT / ("choices_smoke.csv" if a.smoke else "choices.csv"), index=False)
        rec.to_csv(OUT / ("ic_records_smoke.csv" if a.smoke else "ic_records.csv"), index=False)
    ctl = controls()
    ctl = ctl[ctl["cap_tier"].isin(tiers) & (ctl["snapshot_date"] >= sc["snapshot_date"].min())]
    pool = pd.concat([sc, ctl[sc.columns]], ignore_index=True)
    tr = trusts()
    candidates = [f"{m}_{b}" for m in MODELS for b in bars]
    methods = candidates + list(CONTROL_RULES)

    log(f"[books] selection window {WINDOW[0]} to {hi}")
    D = load_data(pool, WINDOW[0], hi, tr)
    table, series = {}, {}
    for t in tiers:
        table[t], series[t] = run_books(D, t, methods)
    slow_bar, slow_means = pick(table, "slow")
    fast_bar, fast_means = pick(table, "fast")
    log(f"chosen: slow={slow_bar} {slow_means} · fast={fast_bar} {fast_means}")

    pool = add_blend(pool, f"slow_{slow_bar}", f"fast_{fast_bar}", "blend_chosen")
    methods = methods + ["blend_chosen"]
    D = load_data(pool, WINDOW[0], hi, tr)
    for t in tiers:
        table[t], series[t] = run_books(D, t, methods)

    starts = []
    anchors = sorted(a for a in pool["snapshot_date"].unique() if WINDOW[0] <= a <= hi)
    for st in anchors[:1 if a.smoke else N_STARTS]:
        log(f"[starts] {st}")
        Ds = load_data(pool, st, hi, tr)
        starts.append({t: run_books(Ds, t, methods)[0] for t in tiers})

    chosen = {"slow": f"slow_{slow_bar}", "fast": f"fast_{fast_bar}", "blend": "blend_chosen"}
    grades = {t: {m: grade(t, m, table, series, starts) for m in methods if m in table[t]} for t in tiers}
    hold = {} if a.smoke else holdout(pool, tr, tiers, methods)
    n_set = cho.groupby(["tier", "method"]).agg(months=("anchor", "size"), carried=("carried", "sum"),
                                                avg_factors=("n_factors", "mean"), latest=("factors", "last")).reset_index()
    out = dict(computed=time.strftime("%Y-%m-%d"), window=[WINDOW[0], hi], tiers=list(tiers), chosen=chosen,
               slow_bar=slow_bar, fast_bar=fast_bar, slow_means=slow_means, fast_means=fast_means, books=table, grades=grades,
               holdout=hold, ic=ic_summary(rec), sets=json.loads(n_set.to_json(orient="records")),
               starts={t: {m: [s[t][m]["excess_cagr"] for s in starts if m in s[t]] for m in methods} for t in tiers})
    (OUT / ("results_smoke.json" if a.smoke else "results.json")).write_text(json.dumps(out, indent=1, default=str))
    pd.DataFrame({f"{t}|{m}": s for t in tiers for m, s in series[t].items()}).to_parquet(
        OUT / ("series_smoke.parquet" if a.smoke else "series.parquet"))

    rows = [dict(tier=t, method=m, excess=table[t][m]["excess_cagr"], t=table[t][m]["t"], worst12=table[t][m]["worst_12m"],
                 turn=table[t][m]["turnover"], cost=table[t][m]["costs_bps"], nosc=table[t][m]["months_no_score"],
                 grade=grades[t][m]["grade"], hair=grades[t][m]["t_haircut"], dsr=grades[t][m]["dsr"], pbo=grades[t][m]["pbo"],
                 yrs=f"{grades[t][m]['beat_years']}/{grades[t][m]['n_years']}", starts=f"{grades[t][m]['beat_starts']}/{grades[t][m]['n_starts']}",
                 hold=hold.get(t, {}).get(m, {}).get("excess")) for t in tiers for m in methods if m in table[t]]
    pd.set_option("display.width", 220)
    log(pd.DataFrame(rows).to_string(index=False))
    log(f"chosen {chosen}; finished in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
