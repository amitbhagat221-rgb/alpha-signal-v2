"""
How many names per tier? Pre-registered test (2026-10-10, checklist "How many names per tier").

READ-ONLY. For each pickable tier and monthly anchor (walk-forward protocol of tools.walk_forward:
expanding training window, 1-anchor embargo, from 2020-06), score the tier with
  oos     the walk-forward out-of-sample selection (factors with training |t| >= 2.5, sign-weighted,
          at most 6) — the honest score
  live    today's production weights (factors.SIGNAL_WEIGHTS) — chosen on this history, optimistic
and hold the equal-weight top N for the next 20 sessions, N in NS plus the top fifth of the tier.
Gross = mean fwd_return_20d of the holding minus the tier's equal-weight mean. Cost = 2 x (share of
names replaced since the previous anchor) x the tier's one-way cost (config.TIERS cost_bps).
Net = gross - cost. The benchmark (an index fund) is taken as costless.
Two holding rules: `monthly` rebuys the top N each anchor; `banded` keeps a held name until its rank
falls below EXIT_RATIO x N (the book's own band: buy top 5, sell below rank 8 — config.PORTFOLIO
rebalance rank_exit) and refills from the top.

Usage:  python -m tools.names_per_tier [--md PATH] [--cost LARGE=15,MID=25,SMALL=50]
"""
import argparse

import numpy as np
import pandas as pd

import factors
from config import PICKABLE_TIERS, TIERS
from tools.walk_forward import (EMBARGO, RESPONSE, _choose, _columns, _ic_table, _ranked_col,
                                composite, load_panel)

NS = [5, 10, 20, 30]
START = "2020-06-01"
RECENT = "2024-09-01"
EXIT_RATIO = 8 / 5      # config.PORTFOLIO["hrp"]["rebalance"]["rank_exit"] / picks
RULES = ("monthly", "banded")


def holdings(tier):
    return [f"top {n}" for n in NS] + ["top fifth"]


def run(costs=None):
    col_of = _columns()
    live = {_ranked_col(k, t) for t, ws in factors.SIGNAL_WEIGHTS.items() for k in ws}
    panel, cols = load_panel(list(col_of) + sorted(live - set(col_of)))
    live_w = {t: {_ranked_col(k, t): w for k, w in ws.items()} for t, ws in factors.SIGNAL_WEIGHTS.items()}
    anchors = sorted(panel["snapshot_date"].unique())
    rows = []
    for tier in PICKABLE_TIERS:
        cost = (costs or {}).get(tier, TIERS[tier]["cost_bps"]) / 10_000
        tdf = panel[panel["cap_tier"] == tier]
        ic_tab = _ic_table(tdf, cols)
        by_date = dict(tuple(tdf.groupby("snapshot_date")))
        prev = {}
        for k, test in enumerate(anchors):
            if test < START or test not in by_date or k - EMBARGO < 1:
                continue
            methods, _ = _choose(ic_tab, set(anchors[:k - EMBARGO]))
            ws = {"oos": methods["select"],
                  "live": {c: w for c, w in live_w.get(tier, {}).items() if c in tdf}}
            g = by_date[test].dropna(subset=[RESPONSE]).set_index("sid")
            if len(g) < 40:
                continue
            bench = g[RESPONSE].mean()
            for m, w in ws.items():
                if not w:
                    continue
                order = composite(g, w).sort_values(ascending=False).index
                rank = {sid: i + 1 for i, sid in enumerate(order)}
                for h in holdings(tier):
                    n = int(h.split()[1]) if h != "top fifth" else max(len(order) // 5, 1)
                    for rule in RULES:
                        last = prev.get((m, h, rule))
                        if rule == "banded" and last is not None:
                            keep = [s for s in last if rank.get(s, 10 ** 9) <= np.ceil(EXIT_RATIO * n)]
                            held = set(keep)
                            for sid in order:
                                if len(held) >= n:
                                    break
                                held.add(sid)
                        else:
                            held = set(order[:n])
                        turn = 1.0 if last is None else len(held - last) / n
                        prev[(m, h, rule)] = held
                        gross = g.loc[list(held), RESPONSE].mean() - bench
                        rows.append({"tier": tier, "method": m, "holding": h, "rule": rule, "n": n,
                                     "anchor": test, "gross": gross, "turnover": turn,
                                     "net": gross - 2 * turn * cost})
    return pd.DataFrame(rows)


def summarise(rec, since=None):
    r = rec if since is None else rec[rec["anchor"] >= since]
    out = []
    for (tier, m, rule, h), g in r.groupby(["tier", "method", "rule", "holding"], sort=False):
        x = g["net"]
        t = x.mean() / x.std(ddof=1) * np.sqrt(len(x)) if len(x) > 2 and x.std(ddof=1) > 0 else np.nan
        out.append({"tier": tier, "scores": m, "rule": rule, "holding": h, "months": len(x),
                    "gross_%/mo": round(g["gross"].mean() * 100, 2),
                    "turnover_%": round(g["turnover"].iloc[1:].mean() * 100),
                    "net_%/mo": round(x.mean() * 100, 2), "net_%/yr": round(x.mean() * 1200, 1),
                    "breakeven_bps": round(g["gross"].mean() / (2 * g["turnover"].iloc[1:].mean()) * 1e4)
                    if g["turnover"].iloc[1:].mean() > 0 else np.nan,
                    "t_net": round(t, 2), "months_up_%": round((x > 0).mean() * 100)})
    return pd.DataFrame(out)


def _md(df):
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", help="also write the tables to this markdown file")
    ap.add_argument("--cost", help="one-way bps per tier instead of config.TIERS, e.g. LARGE=15,MID=25,SMALL=50")
    a = ap.parse_args()
    costs = {k: float(v) for k, v in (kv.split("=") for kv in a.cost.split(","))} if a.cost else None
    rec = run(costs)
    full, recent = summarise(rec), summarise(rec, RECENT)
    pd.set_option("display.width", 250)
    print("=== Full history (from 2020-06) ===")
    print(full.to_string(index=False))
    print(f"\n=== Since {RECENT} ===")
    print(recent.to_string(index=False))
    if a.md:
        with open(a.md, "w") as f:
            f.write(f"## Full history\n\n{_md(full)}\n\n## Since {RECENT}\n\n{_md(recent)}\n")
