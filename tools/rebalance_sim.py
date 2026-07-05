"""
Alpha Signal v2 — banded vs daily rebalancing replay (ADR 0046, audit Port-F1).

The 2026-07-04 audit measured 18.5%/day one-way turnover on the daily-rebuilt
advisory HRP book (~2.7 of 15 names replaced daily) — cost-fatal vs the measured
gross edge. This tool quantifies what banded/hysteresis rebalancing (enter top-5,
exit below top-8 within-tier, re-size only on >2pp weight drift) does to turnover
and net-of-cost Sharpe BEFORE trusting the flipped default.

Method — READ-ONLY, writes nothing anywhere:
  • DAILY arm  = the stored `portfolio_weights` books as-is. Through 2026-07-04
    every stored book is a fresh daily rebuild, so this arm reproduces the audit's
    turnover number (sanity check). After the 2026-07-05 default flip the stored
    stream is banded — pass --end 2026-07-04 (default) to keep this arm pure.
  • BANDED arm = start from the FIRST stored book, then replay every subsequent
    daily_picks date through portfolio_construction._build_banded() in memory —
    the exact production code path (same rank-exit / drift-band / investability
    logic, full HRP + tilt + caps re-run on trigger days). No approximation
    beyond production's own carry-forward rule: on within-band days the stored
    targets carry unchanged (drift is treated as execution detail).
  • NAV: for each trading day hold the latest book with asof_date < t
    (look-ahead-safe, mirrors tools/portfolio_nav.py); one-way turnover
    T_t = 0.5·Σ|target − drifted| vs the weights you'd hold having not traded;
    cost = per-name |Δw| × config.TRANSACTION_COSTS_BPS at its cap tier.

Usage:
    python -m tools.rebalance_sim               # full replay + report
    python -m tools.rebalance_sim --end 2026-07-04
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import portfolio_construction as pc                     # noqa: E402
from config import TRANSACTION_COSTS_BPS                # noqa: E402
from db import read_sql                                 # noqa: E402
from tools.compute_pick_outcomes import _load_price_panel  # noqa: E402
from tools.portfolio_nav import _book_as_of, _stats, RET_CLIP, TRADING_DAYS  # noqa: E402

BOOK_COLS = ("asof_date, sid, weight, factor_score, marginal_risk_contrib, "
             "cap_tier, sector, name, rank")
TRADE_EPS = 1e-3   # |Δw| above 0.1pp counts as a traded name


# ── book streams ─────────────────────────────────────────────────────────────
def load_stored_books(end=None):
    """Stored portfolio_weights books keyed by asof_date string (ascending)."""
    where = "WHERE asof_date <= ?" if end else ""
    df = read_sql(f"SELECT {BOOK_COLS} FROM portfolio_weights {where} "
                  f"ORDER BY asof_date", params=[end] if end else None)
    return {d: g.reset_index(drop=True) for d, g in df.groupby("asof_date")}


def replay_banded(start_book, dates):
    """Run production _build_banded() forward from `start_book` over `dates`.

    Returns (books dict, actions list). Skips a date (carrying the prior book as
    'previous') only if the production code raises — same as the pipeline's
    non-critical failure semantics."""
    books, actions = {start_book["asof_date"].iloc[0]: start_book}, []
    prev = start_book
    for d in dates:
        try:
            book, diag = pc._build_banded(d, prev, history=books)
        except Exception as e:
            actions.append((d, f"SKIP ({type(e).__name__}: {e})"))
            continue
        books[d] = book
        actions.append((d, diag.get("action"),
                        len(diag.get("sold", {})), len(diag.get("bought", []))))
        prev = book
    return books, actions


# ── NAV / turnover replay ────────────────────────────────────────────────────
def nav_replay(books, rets, cost_bps):
    """Daily gross return, one-way turnover, cost and names-traded series for a
    date→book-DataFrame stream. Mirrors tools/portfolio_nav.py mechanics."""
    bw = {pd.Timestamp(d): b.set_index("sid")["weight"].astype(float)
          for d, b in books.items()}
    book_dates = pd.DatetimeIndex(sorted(bw.keys()))
    tier_lookup = (pd.concat(books.values())
                   .groupby("sid")["cap_tier"].last())

    out = {"gross": [], "turnover": [], "cost": [], "n_traded": []}
    idx, prev_w = [], None
    for t in rets.index[rets.index > book_dates[0]]:
        bd = _book_as_of(book_dates, t)
        if bd is None:
            continue
        w = bw[bd]
        day = rets.loc[t, [s for s in w.index if s in rets.columns]].dropna()
        if day.empty:
            continue
        wsub = w.reindex(day.index).fillna(0.0)
        wsub = wsub / wsub.sum() if wsub.sum() else wsub
        out["gross"].append(float((wsub * day).sum()))

        if prev_w is None:
            to, cost, n_tr = np.nan, np.nan, np.nan
        else:
            common = prev_w.index.intersection(day.index)
            grown = prev_w.reindex(common) * (1 + day.reindex(common))
            drifted = grown / grown.sum() if grown.sum() else grown
            names = wsub.index.union(drifted.index)
            dw = (wsub.reindex(names).fillna(0.0)
                  - drifted.reindex(names).fillna(0.0))
            to = float(0.5 * dw.abs().sum())
            bps = tier_lookup.reindex(names).map(cost_bps).fillna(
                max(cost_bps.values()))
            cost = float((dw.abs() * bps / 10000.0).sum())
            n_tr = int((dw.abs() > TRADE_EPS).sum())
        out["turnover"].append(to)
        out["cost"].append(cost)
        out["n_traded"].append(n_tr)
        prev_w = wsub
        idx.append(t)
    return {k: pd.Series(v, index=idx) for k, v in out.items()}


def _row(label, res):
    g = _stats(res["gross"])
    net = _stats(res["gross"] - res["cost"].fillna(0.0))
    return {
        "label": label,
        "turnover_pct": res["turnover"].mean() * 100,
        "n_traded": res["n_traded"].mean(),
        "gross_sharpe": g.get("sharpe", float("nan")),
        "net_sharpe": net.get("sharpe", float("nan")),
        "gross_ann": g.get("ann_ret_pct", float("nan")),
        "net_ann": net.get("ann_ret_pct", float("nan")),
        "cost_ann": res["cost"].fillna(0.0).mean() * TRADING_DAYS * 100,
        "n_days": g.get("n_days", 0),
    }


def report(end=None):
    daily_books = load_stored_books(end)
    if len(daily_books) < 2:
        print("⚠ need ≥2 stored portfolio_weights books"); return
    dates = sorted(daily_books)
    start = daily_books[dates[0]]
    print(f"replaying banded book from {dates[0]} over {len(dates) - 1} pick dates "
          f"(production _build_banded, in memory — nothing written) …")
    banded_books, actions = replay_banded(start, dates[1:])

    price = _load_price_panel()
    rets = price.pct_change(fill_method=None).clip(*RET_CLIP)
    if end:
        rets = rets[rets.index <= pd.Timestamp(end)]

    res_d = nav_replay(daily_books, rets, TRANSACTION_COSTS_BPS)
    res_b = nav_replay(banded_books, rets, TRANSACTION_COSTS_BPS)

    n_carry = sum(1 for a in actions if a[1] == "carry")
    n_names = sum(1 for a in actions if a[1] == "rebalance (names)")
    n_drift = sum(1 for a in actions if a[1] == "rebalance (drift)")
    n_skip = len(actions) - n_carry - n_names - n_drift

    print(f"\n══ REBALANCE SIM — daily vs banded (top-{pc.REBAL['rank_exit']} exit / "
          f"{pc.REBAL['drift_pp']}pp band), {res_d['gross'].shape[0]} trading days, ADVISORY ══\n")
    hdr = (f"  {'MODE':10}{'TURNOVER':>10}{'NAMES':>8}{'GROSS':>9}{'NET':>9}"
           f"{'GROSS':>9}{'NET':>9}{'COST':>9}")
    print(hdr)
    print(f"  {'':10}{'%/day 1-way':>10}{'trd/day':>8}{'Sharpe':>9}{'Sharpe':>9}"
          f"{'ann%':>9}{'ann%':>9}{'%/yr':>9}")
    for r in (_row("daily", res_d), _row("banded", res_b)):
        print(f"  {r['label']:10}{r['turnover_pct']:>9.1f}%{r['n_traded']:>8.1f}"
              f"{r['gross_sharpe']:>9.2f}{r['net_sharpe']:>9.2f}"
              f"{r['gross_ann']:>8.1f}%{r['net_ann']:>8.1f}%{r['cost_ann']:>8.1f}%")

    track = (res_d["gross"] - res_b["gross"]).dropna()
    ts = _stats(track)
    corr = float(res_d["gross"].corr(res_b["gross"]))
    print(f"\n  banded trigger days: {n_names} name-change + {n_drift} drift-band of "
          f"{len(actions)} ({n_carry} carry-forward, {n_skip} skipped)")
    print(f"  tracking (daily − banded): {ts.get('ann_ret_pct', float('nan')):+.1f}%/yr at "
          f"{ts.get('ann_vol_pct', float('nan')):.1f}% TE · daily-return corr {corr:.3f}")
    to_d = res_d["turnover"].mean() * 100
    to_b = res_b["turnover"].mean() * 100
    print(f"  sanity: daily arm {to_d:.1f}%/day vs audit's 18.5%/day · "
          f"banded {to_b:.1f}%/day → {'PASS (<5%)' if to_b < 5 else 'FAIL (≥5% target)'} "
          f"· reduction {to_d / to_b:.1f}×" if to_b > 0 else "")
    print(f"\n  Read-only replay; stored portfolio_weights untouched. Costs = "
          f"config.TRANSACTION_COSTS_BPS per side by tier. ADVISORY — no capital.\n")


def main():
    ap = argparse.ArgumentParser(description="daily vs banded rebalancing replay (ADR 0046)")
    ap.add_argument("--end", default="2026-07-04",
                    help="last book/pricing date (default 2026-07-04 — the last "
                         "pure daily-mode stored book before the default flip)")
    ap.add_argument("--rank-exit", type=int,
                    help="sensitivity override for REBAL['rank_exit'] (sim only, "
                         "config untouched)")
    ap.add_argument("--drift-pp", type=float,
                    help="sensitivity override for REBAL['drift_pp'] (sim only)")
    args = ap.parse_args()
    if args.rank_exit is not None:
        pc.REBAL["rank_exit"] = args.rank_exit
    if args.drift_pp is not None:
        pc.REBAL["drift_pp"] = args.drift_pp
    report(end=args.end)


if __name__ == "__main__":
    main()
