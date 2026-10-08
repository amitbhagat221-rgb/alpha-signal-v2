"""Walk-forward: does the way we choose factors work on months it has not seen?  (READ-ONLY)

Every t-stat in the evidence table is measured on the same history the factors and
their signs were picked from. This replays the choice month by month on the panel
(`daily_snapshots_pit`: point-in-time tiers, adjusted next-session label, the
corrected inputs of ADR 0062):

  for each monthly anchor k (the first business day of a month):
    train  = the monthly anchors whose 20-session label had matured by k
             (anchor k-1's label ends around k, so it is embargoed: train ends at k-2)
    choose = factors from the training window only, each with its training sign
    score  = month k with the frozen choice, the production composite
             (within-tier percentile, a negative weight inverts it, a missing factor
             counts as 0.5 — config.MISSING_FACTOR_SCORE, ADR 0064)
    record = the composite's rank IC on month k, and the top tenth's 20-day return
             over the tier average

Methods:
  select   factors with |training t| >= 2.5 on >= 12 training anchors, the 6 strongest,
           equal weight, training sign — the promotion bar applied without hindsight
  ic_wtd   every factor with >= 12 training anchors, weight = training mean IC
  live     today's production weights (factors.SIGNAL_WEIGHTS), fixed. NOT out of sample:
           they were chosen on this history. The gap between `live` and `select` is
           roughly what hindsight adds.

Usage:
    python -m tools.walk_forward                     # expanding window
    python -m tools.walk_forward --rolling 36        # last 36 monthly anchors only
    python -m tools.walk_forward --md docs/studies/walk-forward-2026-10.md
"""
import argparse
from datetime import date

import numpy as np
import pandas as pd

import factors
from config import MISSING_FACTOR_SCORE, PICKABLE_TIERS
from db import read_sql
from tools.backtest_pit import IC_MIN_PERIODS, _compute_ic, _is_month_start_anchor

RESPONSE = "fwd_return_20d"
EMBARGO = 1          # anchors between the last training label and the test anchor
SELECT_T = 2.5       # the promotion bar
SELECT_MAX = 6       # at most this many factors per tier (production carries 4-6)
MIN_STOCKS = 20


def _columns():
    """{panel column: signal id} for every IC-rankable registry factor (no hand list)."""
    out = {}
    for sig, (_, v2) in factors.SIGNAL_COLUMN_MAP.items():
        if sig != "_response" and v2:
            out.setdefault(v2, sig)
    return out


def _ranked_col(weight_key, tier):
    """The panel column the screener ranks for a weight key in a tier (its replay column)."""
    f = factors.FACTORS[factors.signal_for(weight_key, tier)]
    return f.get("replay_col") or factors.pit_column(factors.signal_for(weight_key, tier))


def load_panel(cols):
    have = set(read_sql("SELECT * FROM daily_snapshots_pit LIMIT 1").columns)
    use = [c for c in cols if c in have]
    sel = ", ".join(f'"{c}"' for c in ["sid", "snapshot_date", "cap_tier", RESPONSE, *use])
    df = read_sql(f"SELECT {sel} FROM daily_snapshots_pit WHERE {RESPONSE} IS NOT NULL")
    df = df[[_is_month_start_anchor(date.fromisoformat(d)) for d in df["snapshot_date"]]]
    return df, use


def _ic_table(tdf, cols):
    """{column: Series(anchor -> IC)} once per tier; training stats are slices of it."""
    out = {}
    for c in cols:
        rows = _compute_ic(tdf, c, RESPONSE)
        if rows:
            out[c] = pd.Series({d: ic for d, ic, _ in rows}).sort_index()
    return out


def composite(g, weights):
    """The screener's base score on one tier-anchor: Σ|w|·pct (0.5 if missing) / Σ|w|."""
    total = sum(abs(w) for w in weights.values())
    score = pd.Series(0.0, index=g.index)
    for col, w in weights.items():
        pct = g[col].rank(pct=True) if col in g else pd.Series(np.nan, index=g.index)
        pct = (1 - pct) if w < 0 else pct
        score += abs(w) * pct.fillna(MISSING_FACTOR_SCORE)
    return score / total


def _oos_record(g, weights):
    if not weights:
        return None
    s = composite(g, weights)
    sub = pd.DataFrame({"s": s, "r": g[RESPONSE]}).dropna()
    if len(sub) < MIN_STOCKS:
        return None
    ic = sub["s"].rank().corr(sub["r"].rank())
    top = sub[sub["s"] >= sub["s"].quantile(0.9)]["r"].mean() - sub["r"].mean()
    return ic, top


def _choose(ic_tab, train_dates):
    stats = {}
    for c, s in ic_tab.items():
        x = s[s.index.isin(train_dates)]
        if len(x) >= IC_MIN_PERIODS and x.std(ddof=1) > 0:
            stats[c] = (x.mean(), x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))
    strong = sorted((c for c, (_, t) in stats.items() if abs(t) >= SELECT_T),
                    key=lambda c: -abs(stats[c][1]))[:SELECT_MAX]
    select = {c: float(np.sign(stats[c][0])) for c in strong}
    ic_wtd = {c: m for c, (m, _) in stats.items() if m != 0}
    return {"select": select, "ic_wtd": ic_wtd}, strong


def run(rolling=None, start="2020-06-01"):
    col_of = _columns()
    live = {_ranked_col(k, t) for t, ws in factors.SIGNAL_WEIGHTS.items() for k in ws}
    panel, cols = load_panel(list(col_of) + sorted(live - set(col_of)))
    live_w = {t: {_ranked_col(k, t): w for k, w in ws.items()} for t, ws in factors.SIGNAL_WEIGHTS.items()}
    anchors = sorted(panel["snapshot_date"].unique())
    rec, picks = [], []
    for tier in PICKABLE_TIERS:
        tdf = panel[panel["cap_tier"] == tier]
        ic_tab = _ic_table(tdf, cols)
        by_date = dict(tuple(tdf.groupby("snapshot_date")))
        for k, test in enumerate(anchors):
            if test < start or test not in by_date or k - EMBARGO < 1:
                continue
            train = anchors[:k - EMBARGO]
            if rolling:
                train = train[-rolling:]
            methods, strong = _choose(ic_tab, set(train))
            methods["live"] = {c: w for c, w in live_w.get(tier, {}).items() if c in tdf}
            picks.append({"tier": tier, "anchor": test, "chosen": ", ".join(strong)})
            for m, w in methods.items():
                r = _oos_record(by_date[test], w)
                if r:
                    rec.append({"tier": tier, "anchor": test, "method": m, "ic": r[0], "top": r[1]})
    return pd.DataFrame(rec), pd.DataFrame(picks)


def summarise(rec):
    rows = []
    for (tier, m), g in rec.groupby(["tier", "method"]):
        ic = g["ic"].to_numpy()
        n = len(ic)
        t = ic.mean() / (ic.std(ddof=1) / np.sqrt(n)) if n > 1 and ic.std(ddof=1) > 0 else np.nan
        rows.append({"tier": tier, "method": m, "months": n, "mean_ic": round(ic.mean(), 4),
                     "t": round(t, 2), "pct_pos": round((ic > 0).mean() * 100),
                     "top10_vs_tier_pct": round(g["top"].mean() * 100, 2)})
    order = {t: i for i, t in enumerate(PICKABLE_TIERS)}
    return pd.DataFrame(rows).sort_values(["tier", "method"], key=lambda s: s.map(order) if s.name == "tier" else s)


def by_year(rec):
    r = rec.assign(year=rec["anchor"].str[:4])
    return r.pivot_table(index=["tier", "method"], columns="year", values="ic", aggfunc="mean").round(3)


def _md(df):
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rolling", type=int, default=None, help="train on the last N monthly anchors only")
    ap.add_argument("--md", help="also write the tables to this markdown file")
    a = ap.parse_args()
    rec, picks = run(rolling=a.rolling)
    s, y = summarise(rec), by_year(rec).reset_index()
    print(s.to_string(index=False)); print(); print(y.to_string(index=False))
    last = picks.sort_values("anchor").groupby("tier").tail(1)
    print(); print(last.to_string(index=False))
    if a.md:
        open(a.md, "w").write(
            f"Walk-forward, {'rolling ' + str(a.rolling) if a.rolling else 'expanding'} window "
            f"(`python -m tools.walk_forward`)\n\n{_md(s)}\n\nMean OOS IC by year\n\n{_md(y)}\n\n"
            f"Factors `select` chose at the latest anchor\n\n{_md(last)}\n")
