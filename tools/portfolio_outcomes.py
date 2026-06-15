"""
Alpha Signal v2 — Track 3.3c — HRP book realized-return head-to-head.

For every HRP book in `portfolio_weights` (one per asof_date), compute the book's
realized close-to-close return over fixed forward TRADING-day windows and compare
three constructions on the SAME selection:

  hrp_return_pct  — Σ(weight_i · fwd_ret_i)  using the persisted HRP weights
  eqw_return_pct  — mean(fwd_ret_i)          equal-weight over the same names
  bench_return_pct— tier-weight-blended NIFTY (LARGE→50, MID→Midcap150, SMALL→Smallcap250)

HRP vs EQW isolates the *weighting* decision (selection held constant), which is
exactly what HRP is — does risk-parity × alpha-tilt beat naive equal-weight? HRP vs
bench is the passive-alternative check. Writes `portfolio_outcomes`
(PK = asof_date + window_days); idempotent upsert.

Reuses the price-series + trading-day entry/exit logic from
tools.compute_pick_outcomes, so the horizon matches the validated backtest
(reconstruct_pit fwd_return_20d). A book only gets a row for window N once ≥80% of
its names have N trading days of forward prices; weights are renormalised over the
matured subset so a not-yet-matured / delisted name doesn't leak in.

This is the evidence that accumulates toward the plan-0002 §3.3c hard gate (HRP book
beats the current portfolio by ≥1.5% risk-adjusted over 18-24mo). ADVISORY — no
capital is deployed. With only ~2mo of post-cutover history, 20d is the only matured
window today; 63d/126d fill in as the book history ages.

Usage:
    python -m tools.portfolio_outcomes                 # compute all windows + report
    python -m tools.portfolio_outcomes --windows 20    # one window
    python -m tools.portfolio_outcomes --report-only   # just print the summary
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, upsert_df
from tools.compute_pick_outcomes import (
    DEFAULT_WINDOWS, TIER_BENCHMARKS,
    _load_price_panel, _load_bench_panel, _build_series, _entry, _exit_trading,
)

MIN_MATURED_FRAC = 0.8  # need ≥80% of book names matured before booking a window


def _book_window_return(book, window, price_series, bench_series):
    """Realized return of one book at one window. Returns a dict of the three
    constructions + maturity counts, or None if too few names have matured."""
    fwd, weights, tier_w = {}, {}, {}
    for r in book.itertuples():
        e = _entry(price_series, r.sid, r.entry_dt)
        if e is None:
            continue
        ex = _exit_trading(price_series, r.sid, e[0], window)
        if ex is None:                       # window not matured for this name
            continue
        fwd[r.sid] = 100.0 * (ex[1] / e[2] - 1.0)
        weights[r.sid] = float(r.weight or 0.0)
        tier_w[r.sid] = r.cap_tier

    n_names, n_matured = len(book), len(fwd)
    if n_matured == 0 or n_matured < MIN_MATURED_FRAC * n_names:
        return None

    wsum = sum(weights.values()) or 1.0
    hrp = sum(weights[s] / wsum * fwd[s] for s in fwd)        # HRP, renorm over matured
    eqw = sum(fwd.values()) / n_matured                       # equal-weight, same names

    # Each tier's share of (matured, renormalised) book weight — the blend the
    # tier benchmark is mixed by in _bench_blended().
    tshare = {}
    for s in fwd:
        tshare[tier_w[s]] = tshare.get(tier_w[s], 0.0) + weights[s] / wsum
    return {"hrp": hrp, "eqw": eqw, "n_names": n_names, "n_matured": n_matured,
            "tshare": tshare}


def _bench_blended(tshare, window, asof_dt, bench_series):
    """Tier-weight-blended benchmark window return for one book."""
    num, den = 0.0, 0.0
    for tier, share in tshare.items():
        bname = TIER_BENCHMARKS.get(tier)
        if not bname or bname not in bench_series:
            continue
        be = _entry(bench_series, bname, asof_dt)
        if be is None:
            continue
        bex = _exit_trading(bench_series, bname, be[0], window)
        if bex is None:
            continue
        num += share * 100.0 * (bex[1] / be[2] - 1.0)
        den += share
    return (num / den) if den else None


def compute(windows=DEFAULT_WINDOWS):
    books = read_sql(
        "SELECT asof_date, sid, weight, cap_tier FROM portfolio_weights "
        "ORDER BY asof_date")
    if books.empty:
        print("⚠ no portfolio_weights — run `python -m portfolio_construction --backfill` first")
        return 0
    books["entry_dt"] = pd.to_datetime(books["asof_date"])

    price_series = _build_series(_load_price_panel())
    bench_panel = _load_bench_panel()
    bench_series = _build_series(bench_panel) if not bench_panel.empty else {}

    rows = []
    for window in windows:
        booked = 0
        for asof, book in books.groupby("asof_date"):
            res = _book_window_return(book, window, price_series, bench_series)
            if res is None:
                continue
            bench = _bench_blended(res["tshare"], window,
                                   pd.to_datetime(asof), bench_series)
            rows.append({
                "asof_date": asof,
                "window_days": int(window),
                "hrp_return_pct": round(res["hrp"], 4),
                "eqw_return_pct": round(res["eqw"], 4),
                "bench_return_pct": round(bench, 4) if bench is not None else None,
                "hrp_vs_eqw_pct": round(res["hrp"] - res["eqw"], 4),
                "hrp_excess_pct": round(res["hrp"] - bench, 4) if bench is not None else None,
                "n_names": res["n_names"],
                "n_matured": res["n_matured"],
                "computed_at": datetime.now().isoformat(timespec="seconds"),
            })
            booked += 1
        print(f"  window {window:>3}d: booked {booked} of "
              f"{books['asof_date'].nunique()} books")

    if not rows:
        print("⚠ no matured books yet (need ≥1 window of forward prices)")
        return 0
    out = pd.DataFrame(rows)
    n = upsert_df(out, "portfolio_outcomes")
    print(f"✓ wrote/updated {n} portfolio_outcomes rows")
    return n


def report():
    """Aggregate head-to-head across all booked asof_dates, per window."""
    df = read_sql("SELECT * FROM portfolio_outcomes")
    if df.empty:
        print("no portfolio_outcomes yet"); return
    print(f"\n══ HRP BOOK vs EQUAL-WEIGHT — realized head-to-head (ADVISORY) ══")
    print(f"  {'WIN':>4} {'n':>4} {'HRP':>8} {'EQW':>8} {'BENCH':>8} "
          f"{'HRP−EQW':>8} {'win%':>6} {'HRP−BMK':>8}")
    for w, g in df.groupby("window_days"):
        n = len(g)
        hrp, eqw = g["hrp_return_pct"].mean(), g["eqw_return_pct"].mean()
        bmk = g["bench_return_pct"].mean(skipna=True)
        edge = g["hrp_vs_eqw_pct"].mean()
        winrate = 100.0 * (g["hrp_vs_eqw_pct"] > 0).mean()
        exc = g["hrp_excess_pct"].mean(skipna=True)
        print(f"  {w:>4} {n:>4} {hrp:>7.2f}% {eqw:>7.2f}% {bmk:>7.2f}% "
              f"{edge:>+7.2f}% {winrate:>5.0f}% {exc:>+7.2f}%")
    print("\n  HRP−EQW = the weighting edge (selection held constant); win% = share of")
    print("  books where HRP beat equal-weight. §3.3c gate wants a durable risk-adjusted")
    print("  edge over 18-24mo — these are EARLY (mostly 20d, ~2mo of books). ADVISORY.\n")


def main():
    ap = argparse.ArgumentParser(description="Track 3.3c — HRP book realized returns")
    ap.add_argument("--windows", default="20,63,126")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()
    if not args.report_only:
        compute(windows=tuple(int(w) for w in args.windows.split(",")))
    report()


if __name__ == "__main__":
    main()
