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


def compute_nav():
    books = read_sql("SELECT asof_date, sid, weight, cap_tier FROM portfolio_weights")
    if books.empty:
        print("⚠ no portfolio_weights — run `python -m portfolio_construction --backfill`")
        return None
    books["asof_date"] = pd.to_datetime(books["asof_date"])
    bw = {d: g.set_index("sid")["weight"] for d, g in books.groupby("asof_date")}
    btier = {d: g.set_index("sid")["cap_tier"] for d, g in books.groupby("asof_date")}
    book_dates = pd.DatetimeIndex(sorted(bw.keys()))

    price = _load_price_panel()
    # fill_method=None: a stock not priced on day t → NaN return (dropped that day),
    # not a fabricated 0% from forward-fill.
    rets = price.pct_change(fill_method=None).clip(*RET_CLIP)
    rets = rets[rets.index > book_dates[0]]   # start the day after the first book

    bench_panel = _load_bench_panel()
    bench_rets = (bench_panel.pct_change(fill_method=None).clip(*RET_CLIP)
                  if not bench_panel.empty else pd.DataFrame())

    hrp_r, eqw_r, bmk_r, idx = [], [], [], []
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
        hrp_r.append(float((wsub * day).sum()))
        eqw_r.append(float(day.mean()))

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
    return (pd.Series(hrp_r, index=idx), pd.Series(eqw_r, index=idx),
            pd.Series(bmk_r, index=idx))


def report():
    res = compute_nav()
    if res is None:
        return
    hrp, eqw, bmk = res
    s_hrp, s_eqw, s_bmk = _stats(hrp), _stats(eqw), _stats(bmk)
    spread = _stats(hrp - eqw)   # HRP-minus-EQW daily spread → info-ratio-like

    print(f"\n══ HRP vs EQUAL-WEIGHT — risk-adjusted NAV (daily-rebal, {s_hrp.get('n_days','?')} trading days, ADVISORY) ══\n")
    print(f"  {'':14}{'TOTAL':>9}{'ANN.RET':>9}{'ANN.VOL':>9}{'SHARPE':>8}{'MAX DD':>9}")
    for label, s in [("HRP", s_hrp), ("Equal-weight", s_eqw), ("Bench (NIFTY)", s_bmk)]:
        if not s:
            continue
        print(f"  {label:14}{s['total_pct']:>8.2f}%{s['ann_ret_pct']:>8.1f}%"
              f"{s['ann_vol_pct']:>8.1f}%{s['sharpe']:>8.2f}{s['maxdd_pct']:>8.1f}%")
    print(f"\n  Sharpe edge (HRP − EQW): {s_hrp.get('sharpe', float('nan')) - s_eqw.get('sharpe', float('nan')):+.2f}"
          f"   ·   vol reduction: {s_eqw.get('ann_vol_pct', 0) - s_hrp.get('ann_vol_pct', 0):+.1f}pp")
    print(f"  HRP−EQW spread: ann {spread.get('ann_ret_pct', float('nan')):+.1f}% at "
          f"{spread.get('ann_vol_pct', float('nan')):.1f}% vol (info-ratio {spread.get('sharpe', float('nan')):+.2f})")
    print(f"\n  Selection held constant → this is the WEIGHTING edge. Costs excluded (cancel in")
    print(f"  the spread). EARLY (~2mo books); §3.3c gate wants a durable edge over 18-24mo. ADVISORY.\n")


def main():
    argparse.ArgumentParser(description="Track 3.3c — risk-adjusted NAV head-to-head").parse_args()
    report()


if __name__ == "__main__":
    main()
