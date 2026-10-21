"""
Alpha Signal v2 — exploratory: which stop level? (pre-registration addendum, 2026-10-21)

Amit: "figure out for the strangle what should have been the stop loss that protects us against the worst case
but keeps the profit as well". EXPLORATORY and walk-forward; reported apart from the pre-registered verdict.
READ-ONLY (reuses tools.option_intraday_study: same entry, fills, costs, settlement, lots).

Grid on the naked strangle: premium stop k x entry price per leg, k in {1.5,2,2.5,3,4,5,7,10}; index stop at
d % from a short strike (both legs), d in {0,0.25,0.5,1.0}; combinations (each leg exits at whichever fires first).
Choice, on NIFTY expiries before 2024-01-01 only: highest annual P&L at sizing B (10 % of capital as the worst-case
budget), ties to the wider stop. The chosen stop is then reported untouched on NIFTY 2024-01 onward and on SENSEX.

Sizing B here: the worst-case loss per unit is each stop's OWN worst observed loss in the selection window (as a
share of the forward, so NIFTY and SENSEX share one rule) and is FROZEN for the unseen windows. 'B-own' re-measures
it inside each window (hindsight) for comparison. A: fill the margin.

Usage:
  python -m tools.option_stop_grid --trades grid.csv --chart docs/studies/option-stop-frontier-2026-10.png
  python -m tools.option_stop_grid --from-csv grid.csv
"""

from __future__ import annotations

import argparse
import math

import numpy as np
import pandas as pd

from tools import option_intraday_study as st
from tools.option_intraday_study import (CAPITAL, WORST_CASE_SHARE, _ro, _result, _shorts, _naked_margin, index_stop,
                                         intrinsic, premium_stop, price_at, table, v_baseline)

GRID_K = (1.5, 2, 2.5, 3, 4, 5, 7, 10)           # premium stop multiples
GRID_D = (0.0, 0.25, 0.5, 1.0)                   # index stop distances, % from a short strike
SEL_END = "2024-01-01"                           # selection window: NIFTY expiries before this; the rest is unseen
WINDOWS = ("SEL", "OOS", "SENSEX")


def gname(k=None, d=None):
    if k is None and d is None:
        return "base"
    return "|".join(x for x in (f"ps{k:g}" if k is not None else "", f"is{d:g}" if d is not None else "") if x)


def v_stop(c, k=None, d=None):
    """Naked strangle with a premium stop (k x entry, per leg), an index stop (d % from a short strike, both legs),
    or both (each leg exits at whichever fires first). Fills as the pre-registered variants."""
    base = v_baseline(c)
    if d is not None and c.idx is None:
        return None
    pst = {}
    if k is not None:
        for cp, bars, e in (("C", c.bars_c, c.ec), ("P", c.bars_p, c.ep)):
            sp = premium_stop(bars, c.entry, e, k, until=c.expiry)
            if sp is not None:
                pst[cp] = sp
    ist = index_stop(c.idx, c.entry, c.kc, c.kp, band=d / 100.0, until=c.expiry) if d is not None else None
    exits, gaps = {}, 0
    for cp, bars, K in (("C", c.bars_c, c.kc), ("P", c.bars_p, c.kp)):
        cands = ([(pst[cp]["ts"], "p")] if cp in pst else []) + ([(ist["ts"], "i")] if ist else [])
        if not cands:
            continue
        if min(cands)[1] == "p":
            exits[cp] = pst[cp]
            gaps += pst[cp]["gap"]
        else:
            px = price_at(bars, ist["ts"], ist["gap"], floor=intrinsic(cp, K, ist["level"]))
            if px is not None:
                exits[cp] = {"px": px, "day": ist["day"]}
                gaps += int(ist["gap"])
    r = _result(c, gname(k, d), _shorts(c, c.ec, c.ep, exits), margin_pts=_naked_margin(c), bound_pts=np.nan,
                triggered=int(bool(exits)), gap_fills=gaps, hold_net_pts=base["net_pts"], credit_pts=c.ec + c.ep)
    r["whipsaw"] = int(bool(exits) and all(intrinsic(cp, c.kc if cp == "C" else c.kp, c.S) == 0 for cp in exits))
    return r


def grid_names():
    return ([gname(k=k) for k in GRID_K] + [gname(d=d) for d in GRID_D]
            + [gname(k=k, d=d) for k in GRID_K for d in GRID_D])


def build_grid(u, limit=None):
    """Per-trade rows for the no-stop baseline and every grid point (one pass over the files)."""
    days, status, idx = st.sessions(), st.manifest_status(), st.load_index(u)
    idx_last = idx["trading_day"].max()
    first, last = st.hf_span(u)
    rows, n = [], 0
    with _ro() as conn:
        for e, t in st.candidate_expiries(u, days):
            if e < first or e > last or status.get((u, e)) in (None, "stub", "suspect"):
                continue
            if limit and n >= limit:
                break
            c, _ = st.load_ctx(u, e, t, idx if e <= idx_last else None, conn)
            if c is None:
                continue
            n += 1
            b = v_baseline(c)
            b["variant"] = "base"
            rows.append(b)
            for k in (None,) + GRID_K:
                for d in (None,) + GRID_D:
                    if k is None and d is None:
                        continue
                    r = v_stop(c, k, d)
                    if r is not None:
                        rows.append(r)
    return pd.DataFrame(rows)


def size_frac(df, w_frac, capital):
    """Sizing B with the worst case as a share of the forward per unit (scale-free across NIFTY / SENSEX)."""
    d = df.copy()
    d["lots"] = [int(math.floor(capital * WORST_CASE_SHARE / (w_frac * f * l))) for f, l in zip(d.F, d.lot)]
    d["pnl_rs"] = d.lots * d.lot * d.net_pts
    d["margin_rs"] = d.lots * d.lot * d.margin_pts
    d["ret_on_margin"] = d.net_pts / d.margin_pts
    return d


def worst_frac(df):
    """Worst observed loss per unit as a share of the forward; floored at 0.2 % so a calm window cannot size absurd lots."""
    return max(float((-df.net_pts / df.F).max()), 0.002)


def windows(g):
    return {"SEL": (g.underlying == "NIFTY") & (g.expiry < SEL_END),
            "OOS": (g.underlying == "NIFTY") & (g.expiry >= SEL_END),
            "SENSEX": g.underlying == "SENSEX"}


def grid_eval(g, capital=CAPITAL):
    """{(variant, window): row}. Sizing B uses the worst case measured on the variant's SEL trades, frozen."""
    wins = windows(g)
    out = {}
    for v in g.variant.unique():
        gv = g[g.variant == v]
        sel = gv[wins["SEL"].loc[gv.index]]
        if sel.empty:
            continue
        wf = worst_frac(sel)
        for w, m in wins.items():
            t = gv[m.loc[gv.index]]
            if t.empty:
                continue
            row = {"variant": v, "window": w, "w_frac_pct": 100 * wf, "n": len(t)}
            sa = st.stats(st.size_trades(t, "A", capital, np.nan), capital)
            row.update({f"A_{k}": sa[k] for k in ("annual_rs", "worst_rs", "maxdd_rs")})
            for tag, wfx in (("B", wf), ("Bown", worst_frac(t))):
                sb = st.stats(size_frac(t, wfx, capital), capital)
                row.update({f"{tag}_{k}": sb[k] for k in ("annual_rs", "worst_rs", "maxdd_rs")})
            row["trig%"] = 100 * float((t.triggered > 0).mean())
            row["whip%"] = 100 * float((t.whipsaw > 0).mean())
            row["given_up_pts"] = float((t.hold_net_pts - t.net_pts).sum()) if t.hold_net_pts.notna().all() else 0.0
            out[(v, w)] = row
    return out


def choose(ev):
    """Highest SEL annual P&L at sizing B within a family; ties go to the wider stop (fewer triggers on SEL)."""
    best = {}
    for fam, names in (("premium", [gname(k=k) for k in GRID_K]), ("index", [gname(d=d) for d in GRID_D])):
        best[fam] = max((ev[(v, "SEL")]["B_annual_rs"], -ev[(v, "SEL")]["trig%"], v) for v in names if (v, "SEL") in ev)[2]
    best["combo"] = gname(k=float(best["premium"][2:]), d=float(best["index"][2:]))
    return best


def grid_report(g, chart=None):
    ev = grid_eval(g)
    ch = choose(ev)
    cols = [("Stop", "variant", "{}"), ("Trades", "n", "{:.0f}"),
            ("A annual ₹", "A_annual_rs", "{:,.0f}"), ("A worst ₹", "A_worst_rs", "{:,.0f}"), ("A max DD ₹", "A_maxdd_rs", "{:,.0f}"),
            ("B annual ₹", "B_annual_rs", "{:,.0f}"), ("B worst ₹", "B_worst_rs", "{:,.0f}"), ("B max DD ₹", "B_maxdd_rs", "{:,.0f}"),
            ("B-own annual ₹", "Bown_annual_rs", "{:,.0f}"), ("B-own worst ₹", "Bown_worst_rs", "{:,.0f}"),
            ("Fired %", "trig%", "{:.1f}"), ("Whipsaw %", "whip%", "{:.1f}"), ("Given up (pts)", "given_up_pts", "{:,.0f}")]
    order = ["base"] + grid_names()
    for w in WINDOWS:
        print(f"\n#### Window {w}\n")
        print(table([ev[(v, w)] for v in order if (v, w) in ev], cols))
    print("\nChosen on SEL:", ch)
    print("SEL worst-case share of the forward used for sizing B (%):",
          {v: round(ev[(v, 'SEL')]['w_frac_pct'], 3) for v in ["base"] + list(ch.values())})
    print("\n#### Verdict against the bar (unseen windows)\n")
    for name in ch.values():
        for w in ("OOS", "SENSEX"):
            s, b = ev.get((name, w)), ev.get(("base", w))
            if not s or not b:
                continue
            for tag in ("B", "Bown"):
                c1 = s[f"{tag}_worst_rs"] >= 0.5 * b[f"{tag}_worst_rs"]
                c2 = s[f"{tag}_annual_rs"] >= 0.7 * b[f"{tag}_annual_rs"]
                print(f"{name:10s} {w:7s} {tag:5s} worst {s[f'{tag}_worst_rs']:>10,.0f} vs {b[f'{tag}_worst_rs']:>10,.0f} "
                      f"(ratio {s[f'{tag}_worst_rs'] / b[f'{tag}_worst_rs']:.2f}, need <=0.5: {c1}) | annual "
                      f"{s[f'{tag}_annual_rs']:>10,.0f} vs {b[f'{tag}_annual_rs']:>10,.0f} "
                      f"(ratio {s[f'{tag}_annual_rs'] / b[f'{tag}_annual_rs']:.2f}, need >=0.7: {c2}) -> {'PASS' if c1 and c2 else 'fail'}")
    if chart:
        frontier_chart(ev, ch, chart)
    return ev, ch


def frontier_chart(ev, ch, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.5))
    titles = {"SEL": "NIFTY 2021-05 to 2023-12 (selection)", "OOS": "NIFTY 2024-01 to 2026-08 (unseen)",
              "SENSEX": "SENSEX 2023-08 to 2026-07 (unseen)"}
    for ax, w in zip(axes, WINDOWS):
        for v in ["base"] + grid_names():
            r = ev.get((v, w))
            if not r:
                continue
            kind = "base" if v == "base" else "combo" if "|" in v else "premium" if v.startswith("ps") else "index"
            col = {"base": "black", "premium": "tab:blue", "index": "tab:orange", "combo": "tab:gray"}[kind]
            x, y = -r["B_worst_rs"] / 1e5, r["B_annual_rs"] / 1e5
            ax.scatter(x, y, c=col, s=14 if kind == "combo" else 55, alpha=0.4 if kind == "combo" else 0.9,
                       marker="s" if kind == "base" else "o")
            if kind != "combo":
                ax.annotate(v, (x, y), fontsize=7, xytext=(3, 3), textcoords="offset points")
        for v in ch.values():
            r = ev.get((v, w))
            if r:
                ax.scatter(-r["B_worst_rs"] / 1e5, r["B_annual_rs"] / 1e5, s=190, facecolors="none", edgecolors="red", linewidths=1.6)
        ax.set_title(titles[w], fontsize=10)
        ax.set_xlabel("worst single trade, ₹ lakh (left = safer)")
        ax.set_ylabel("annual P&L, ₹ lakh on ₹35 L")
        ax.grid(alpha=0.3)
    fig.suptitle("Stop level frontier (sizing B, worst case frozen from the selection window). Black = no stop, blue = premium stop, "
                 "orange = index stop, grey = combinations, red ring = chosen", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print("chart:", path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--underlying", choices=("NIFTY", "SENSEX", "both"), default="both")
    ap.add_argument("--smoke", action="store_true", help="3 trades per underlying")
    ap.add_argument("--trades", help="write the per-trade grid table to this CSV")
    ap.add_argument("--from-csv", help="report from a saved grid CSV")
    ap.add_argument("--chart", help="write the frontier chart (PNG) here")
    a = ap.parse_args()
    if a.from_csv:
        g = pd.read_csv(a.from_csv)
    else:
        us = ("NIFTY", "SENSEX") if a.underlying == "both" else (a.underlying,)
        g = pd.concat([build_grid(u, limit=3 if a.smoke else None) for u in us], ignore_index=True)
        if a.trades:
            g.to_csv(a.trades, index=False)
    if a.smoke:
        print(g.groupby(["underlying", "variant"]).net_pts.mean().head(20))
        return
    grid_report(g, a.chart)


if __name__ == "__main__":
    main()
