"""
Alpha Signal v2 — Track 3.3c — risk-adjusted NAV head-to-head (HRP vs equal-weight).

The §3.3c gate is RISK-ADJUSTED, but tools/portfolio_outcomes.py compares raw
window returns — which structurally under-credits HRP, whose whole thesis is *risk
reduction*, not higher raw return. This tool closes that gap: it builds a daily NAV
path for the same book under HRP weights vs equal-weight and reports the realized
risk-adjusted stats (annualised vol, Sharpe, max drawdown) the gate actually cares
about.

Method — daily-rebalanced NAV from the persisted `portfolio_weights` books:
  • For each trading day t, hold the most recent book with asof_date ≤ t-1 (the book
    is built from prices ≤ its asof close, so it's tradable from the NEXT day —
    look-ahead-safe), and earn that day's constituent returns.
  • port_ret(t) = Σ_i w_i · ret_i(t), weights renormalised over names priced that day.
  • HRP weights = the persisted book; EQW = 1/n over the SAME names (selection held
    constant → isolates the weighting decision). Benchmark = the book's tier-weight
    blend of NIFTY 50 / Midcap 150 / Smallcap 250.

Daily simple returns are clipped to ±0.5 (split-defense on raw closes — same rationale
as signals/sector_momentum.py / the book covariance). Costs are EXCLUDED: both schemes
hold the same names with similar turnover, so transaction costs roughly cancel in the
HRP−EQW spread (noted; a cost-aware execution sim is paper_portfolio.py's job).

ADVISORY — no capital deployed. Report-only (recomputes from books + prices); nothing
persisted. With ~2mo of books this is an EARLY read; it sharpens as history accrues.

Usage:
    python -m tools.portfolio_nav            # full head-to-head report
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql
from tools.compute_pick_outcomes import _load_price_panel, _load_bench_panel, TIER_BENCHMARKS

RET_CLIP = (-0.5, 0.5)
TRADING_DAYS = 252


def _stats(daily_ret: pd.Series) -> dict:
    """Annualised return / vol / Sharpe + max drawdown from a daily-return series."""
    r = daily_ret.dropna()
    if r.empty:
        return {}
    nav = (1.0 + r).cumprod()
    n = len(r)
    total = float(nav.iloc[-1] - 1.0)
    ann_ret = float(nav.iloc[-1] ** (TRADING_DAYS / n) - 1.0) if n else float("nan")
    ann_vol = float(r.std(ddof=1) * np.sqrt(TRADING_DAYS)) if n > 1 else float("nan")
    sharpe = ann_ret / ann_vol if ann_vol and ann_vol > 0 else float("nan")
    maxdd = float((nav / nav.cummax() - 1.0).min())
    return {"n_days": n, "total_pct": total * 100, "ann_ret_pct": ann_ret * 100,
            "ann_vol_pct": ann_vol * 100, "sharpe": sharpe, "maxdd_pct": maxdd * 100}


def _book_as_of(book_dates, t):
    """Latest book asof_date strictly before trading day t (look-ahead-safe)."""
    i = book_dates.searchsorted(t, side="left") - 1
    return book_dates[i] if i >= 0 else None


def _turnover_and_cost(prev_w, target_w, day_rets, tier_of, cost_bps):
    """One-way turnover T_t = 0.5·Σ|target − drifted| (drifted = prev_w grown by
    today's realized returns — what you'd hold if you hadn't traded back to
    target) + the $-cost of closing that gap at each name's tier bps.

    prev_w=None (first day in the series) → turnover/cost undefined (NaN);
    there's no "yesterday" to drift from."""
    if prev_w is None:
        return float("nan"), float("nan")
    common = prev_w.index.intersection(day_rets.index)
    grown = prev_w.reindex(common) * (1 + day_rets.reindex(common))
    drifted = grown / grown.sum() if grown.sum() else grown
    all_names = target_w.index.union(drifted.index)
    dw = target_w.reindex(all_names).fillna(0.0) - drifted.reindex(all_names).fillna(0.0)
    turnover = 0.5 * dw.abs().sum()
    bps = tier_of.reindex(all_names).map(cost_bps).fillna(max(cost_bps.values()))
    cost = float((dw.abs() * bps / 10000.0).sum())
    return float(turnover), cost


def compute_nav():
    from config import TRANSACTION_COSTS_BPS

    books = read_sql("SELECT asof_date, sid, weight, cap_tier FROM portfolio_weights")
    if books.empty:
        print("⚠ no portfolio_weights — run `python -m portfolio_construction --backfill`")
        return None
    books["asof_date"] = pd.to_datetime(books["asof_date"])
    bw = {d: g.set_index("sid")["weight"] for d, g in books.groupby("asof_date")}
    btier = {d: g.set_index("sid")["cap_tier"] for d, g in books.groupby("asof_date")}
    book_dates = pd.DatetimeIndex(sorted(bw.keys()))
    # Static sid→cap_tier lookup (most recently seen) — covers names that later
    # drop out of the book entirely, so an exit still gets priced at ITS tier's
    # cost rather than falling back to the worst-case default.
    tier_lookup = books.sort_values("asof_date").groupby("sid")["cap_tier"].last()

    price = _load_price_panel()
    # fill_method=None: a stock not priced on day t → NaN return (dropped that day),
    # not a fabricated 0% from forward-fill.
    rets = price.pct_change(fill_method=None).clip(*RET_CLIP)
    rets = rets[rets.index > book_dates[0]]   # start the day after the first book

    bench_panel = _load_bench_panel()
    bench_rets = (bench_panel.pct_change(fill_method=None).clip(*RET_CLIP)
                  if not bench_panel.empty else pd.DataFrame())

    hrp_r, eqw_r, bmk_r, idx = [], [], [], []
    hrp_to, eqw_to, hrp_cost, eqw_cost = [], [], [], []
    prev_hrp_w, prev_eqw_w = None, None   # weights actually held at end of prior day
    for t in rets.index:
        bd = _book_as_of(book_dates, t)
        if bd is None:
            continue
        w = bw[bd]
        day = rets.loc[t, [s for s in w.index if s in rets.columns]].dropna()
        if day.empty:
            continue
        names = day.index
        wsub = w.reindex(names).fillna(0.0)
        wsub = wsub / wsub.sum() if wsub.sum() else wsub
        eqw_target = pd.Series(1.0 / len(names), index=names)
        hrp_r.append(float((wsub * day).sum()))
        eqw_r.append(float(day.mean()))

        tier_of = tier_lookup.reindex(names.union(
            prev_hrp_w.index if prev_hrp_w is not None else names))
        to_h, c_h = _turnover_and_cost(prev_hrp_w, wsub, day, tier_of, TRANSACTION_COSTS_BPS)
        to_e, c_e = _turnover_and_cost(prev_eqw_w, eqw_target, day, tier_of, TRANSACTION_COSTS_BPS)
        hrp_to.append(to_h); hrp_cost.append(c_h)
        eqw_to.append(to_e); eqw_cost.append(c_e)
        prev_hrp_w, prev_eqw_w = wsub, eqw_target

        # tier-weight-blended benchmark for this book
        bmk = np.nan
        if not bench_rets.empty:
            tsh = wsub.groupby(btier[bd].reindex(names)).sum()
            num = den = 0.0
            for tier, share in tsh.items():
                bn = TIER_BENCHMARKS.get(tier)
                if bn in bench_rets.columns and t in bench_rets.index and pd.notna(bench_rets.loc[t, bn]):
                    num += share * bench_rets.loc[t, bn]; den += share
            bmk = num / den if den else np.nan
        bmk_r.append(bmk)
        idx.append(t)

    if not idx:
        print("⚠ no overlapping trading days between books and prices yet")
        return None
    return {
        "hrp": pd.Series(hrp_r, index=idx), "eqw": pd.Series(eqw_r, index=idx),
        "bmk": pd.Series(bmk_r, index=idx),
        "hrp_turnover": pd.Series(hrp_to, index=idx), "eqw_turnover": pd.Series(eqw_to, index=idx),
        "hrp_cost": pd.Series(hrp_cost, index=idx), "eqw_cost": pd.Series(eqw_cost, index=idx),
    }


def report():
    res = compute_nav()
    if res is None:
        return
    hrp, eqw, bmk = res["hrp"], res["eqw"], res["bmk"]
    hrp_net = hrp - res["hrp_cost"].fillna(0.0)
    eqw_net = eqw - res["eqw_cost"].fillna(0.0)
    s_hrp, s_eqw, s_bmk = _stats(hrp), _stats(eqw), _stats(bmk)
    s_hrp_net, s_eqw_net = _stats(hrp_net), _stats(eqw_net)
    spread = _stats(hrp - eqw)   # HRP-minus-EQW daily spread → info-ratio-like

    print(f"\n══ HRP vs EQUAL-WEIGHT — risk-adjusted NAV (daily-rebal, {s_hrp.get('n_days','?')} trading days, ADVISORY) ══\n")
    print(f"  {'':14}{'TOTAL':>9}{'ANN.RET':>9}{'ANN.VOL':>9}{'SHARPE':>8}{'MAX DD':>9}")
    for label, s in [("HRP (gross)", s_hrp), ("HRP (net)", s_hrp_net),
                     ("Equal-wt (gross)", s_eqw), ("Equal-wt (net)", s_eqw_net),
                     ("Bench (NIFTY)", s_bmk)]:
        if not s:
            continue
        print(f"  {label:14}{s['total_pct']:>8.2f}%{s['ann_ret_pct']:>8.1f}%"
              f"{s['ann_vol_pct']:>8.1f}%{s['sharpe']:>8.2f}{s['maxdd_pct']:>8.1f}%")
    print(f"\n  Sharpe edge (HRP − EQW), gross: {s_hrp.get('sharpe', float('nan')) - s_eqw.get('sharpe', float('nan')):+.2f}"
          f"   ·   net: {s_hrp_net.get('sharpe', float('nan')) - s_eqw_net.get('sharpe', float('nan')):+.2f}"
          f"   ·   vol reduction: {s_eqw.get('ann_vol_pct', 0) - s_hrp.get('ann_vol_pct', 0):+.1f}pp")
    print(f"  HRP−EQW spread: ann {spread.get('ann_ret_pct', float('nan')):+.1f}% at "
          f"{spread.get('ann_vol_pct', float('nan')):.1f}% vol (info-ratio {spread.get('sharpe', float('nan')):+.2f})")

    to_hrp_mean = res["hrp_turnover"].mean() * 100
    to_eqw_mean = res["eqw_turnover"].mean() * 100
    cost_hrp_ann = res["hrp_cost"].fillna(0.0).mean() * TRADING_DAYS * 100
    cost_eqw_ann = res["eqw_cost"].fillna(0.0).mean() * TRADING_DAYS * 100
    print(f"\n  Turnover (mean daily, one-way): HRP {to_hrp_mean:.1f}%/day   ·   Equal-wt {to_eqw_mean:.1f}%/day")
    print(f"  Cost drag (annualised, from daily-rebalance-to-target): HRP {cost_hrp_ann:.1f}%/yr"
          f"   ·   Equal-wt {cost_eqw_ann:.1f}%/yr")
    print(f"\n  Selection held constant → gross spread is the WEIGHTING edge; net numbers show what")
    print(f"  survives daily-rebalance-to-target transaction costs (config.TRANSACTION_COSTS_BPS,")
    print(f"  per-tier one-way). Real execution would use banded/hysteresis rebalancing (far lower")
    print(f"  turnover than this daily-reset simulation) — see HUMAN TASKS in plan 0010.")
    print(f"  EARLY (~2mo books); §3.3c gate wants a durable edge over 18-24mo. ADVISORY.\n")


def main():
    argparse.ArgumentParser(description="Track 3.3c — risk-adjusted NAV head-to-head").parse_args()
    report()


if __name__ == "__main__":
    main()
