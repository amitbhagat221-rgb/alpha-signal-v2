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

Iteration 2 (ADR 0046) adds `--matrix`: {debounce 1/2/3} × {full/partial re-size on a name
change} × {trigger-only/weekly full re-size}, same window + cost model, winner by net Sharpe
(tiebreak lower turnover). Partial re-size = survivors keep their drifted weights and the sold
names' vacated mass funds the incoming buys (no HRP re-run) — this kills the ~4.7pp/day of HRP
jitter that iteration 1's full-rebuild-on-trigger paid in the UNCHANGED names.

`--sweep` (plan 0012 B2, WS1.1 evidence, HUMAN GATE G1) adds a THIRD grid: {exit-rank 8/10/12}
x {drift band 2/3/4pp} x {score-EMA halflife None/3/5/10 trading days}, on top of the
production debounce=3/partial-resize/no-weekly-full defaults (unchanged from `--matrix`'s
winner). EMA is applied to each sid's `final_score` history BEFORE the banded builder ranks —
implemented by monkeypatching `pc.select_candidates`/`pc._rank_ok_lastn` for the sweep's
lifetime only (production `portfolio_construction.py` is never touched; the plain no-flag
report path never invokes these patches). Acceptance bar (plan 0011 WS1.1): turnover <=1.5%/day
AND net_ann within 4pp of gross_ann AND daily-return corr vs the (rank_exit=8, drift_pp=2.0,
ema=None) reference cell (today's actual production config) >=0.90. Writes ONLY
docs/studies/cadence-sweep-2026-07.md — does NOT change any production default (G1: that's
Amit's call).

Usage:
    python -m tools.rebalance_sim               # daily vs banded (current config)
    python -m tools.rebalance_sim --matrix      # iteration-2 3×2×2 grid + winner
    python -m tools.rebalance_sim --sweep       # iteration-3 3x3x4 cadence/EMA sweep (plan 0012 B2)
    python -m tools.rebalance_sim --end 2026-07-04
"""

import argparse
import sys
import time
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

STUDY_OUT = PROJECT_ROOT / "docs" / "studies" / "cadence-sweep-2026-07.md"
SWEEP_RANK_EXIT = [8, 10, 12]
SWEEP_DRIFT_PP = [2.0, 3.0, 4.0]
SWEEP_EMA_HALFLIFE = [None, 3, 5, 10]
ACCEPT_TURNOVER_PCT_DAY = 1.5
ACCEPT_NET_GROSS_GAP_PP = 4.0
ACCEPT_MIN_CORR = 0.90
SWEEP_WALLCLOCK_LIMIT_S = 3600

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
    traded = res["n_traded"].dropna()
    return {
        "label": label,
        "turnover_pct": res["turnover"].mean() * 100,
        "n_traded": res["n_traded"].mean(),
        "trade_days_pct": float((traded > 0).mean() * 100) if len(traded) else float("nan"),
        "gross_sharpe": g.get("sharpe", float("nan")),
        "net_sharpe": net.get("sharpe", float("nan")),
        "gross_ann": g.get("ann_ret_pct", float("nan")),
        "net_ann": net.get("ann_ret_pct", float("nan")),
        "cost_ann": res["cost"].fillna(0.0).mean() * TRADING_DAYS * 100,
        "n_days": g.get("n_days", 0),
    }


# ── fast in-memory price IO (matrix mode) ────────────────────────────────────
# 12 matrix cells × 65 dates × (returns + ADTV) SQL round-trips is slow;
# preloading the close/turnover panels once and slicing replicates production
# semantics at ~20× speed. Patches pc.daily_returns/pc.adtv for THIS PROCESS
# only — production IO and the DB are untouched. Sanity anchor: the
# (debounce=1, full, trigger-only) cell must reproduce iteration 1's numbers.
def _install_fast_io(dates, start_sids):
    depth = max(int(pc.REBAL.get("rank_exit", 8)),
                max(pc.PICKS_PER_TIER.values()) * 3)
    ph = ",".join("?" * len(dates))
    pool = read_sql(f"SELECT DISTINCT sid FROM daily_picks WHERE pick_date IN ({ph}) "
                    f"AND rank <= ?", params=[*dates, depth])
    sids = sorted(set(pool["sid"]) | set(start_sids))
    s_ph = ",".join("?" * len(sids))
    px = read_sql(f"SELECT date, sid, close, volume FROM stock_prices "
                  f"WHERE sid IN ({s_ph}) AND date >= '2023-06-01'", params=sids)
    close = px.pivot(index="date", columns="sid", values="close").sort_index()
    valid = (px["close"] > 0) & (px["volume"] > 0)
    turn = (px[valid].assign(turnover=px["close"] * px["volume"])
            .pivot(index="date", columns="sid", values="turnover").sort_index())

    def fast_daily_returns(want, asof):
        cols = sorted(s for s in set(want) if s in close.columns)
        wide = close.loc[close.index <= asof, cols].dropna(how="all")
        wide = wide.tail(pc.HRP["cov_lookback_days"] + 1)
        rets = np.log(wide / wide.shift(1))
        lo, hi = pc.HRP["ret_clip"]
        rets = rets.clip(lower=lo, upper=hi)
        good = [s for s in rets.columns
                if rets[s].notna().sum() >= pc.HRP["cov_min_obs"]]
        return rets[good].dropna()

    def fast_adtv(want, asof):
        cols = [s for s in set(want) if s in turn.columns]
        sub = turn.loc[turn.index <= asof, cols]
        return pd.Series({s: sub[s].dropna().tail(pc.ADTV_WINDOW).median()
                          for s in cols}).dropna()

    pc.daily_returns, pc.adtv = fast_daily_returns, fast_adtv


def matrix_report(end=None):
    """ADR 0046 iteration 2 — {debounce 1/2/3} × {full vs partial re-size} ×
    {trigger-only vs weekly full re-size}. Winner = best NET Sharpe, tiebreak
    lower turnover. Read-only."""
    daily_books = load_stored_books(end)
    if len(daily_books) < 2:
        print("⚠ need ≥2 stored portfolio_weights books"); return
    dates = sorted(daily_books)
    start = daily_books[dates[0]]

    price = _load_price_panel()
    rets = price.pct_change(fill_method=None).clip(*RET_CLIP)
    if end:
        rets = rets[rets.index <= pd.Timestamp(end)]
    _install_fast_io(dates[1:], start["sid"].tolist())

    rows = [(_row("daily", nav_replay(daily_books, rets, TRANSACTION_COSTS_BPS)), {})]
    for db in (1, 2, 3):
        for rs in ("full", "partial"):
            for wk in (None, 0):
                pc.REBAL.update({"debounce_days": db, "resize": rs,
                                 "full_resize_weekday": wk})
                books, actions = replay_banded(start, dates[1:])
                res = nav_replay(books, rets, TRANSACTION_COSTS_BPS)
                acts = {}
                for a in actions:
                    acts[a[1]] = acts.get(a[1], 0) + 1
                label = f"d{db}/{rs[:4]}/{'wk' if wk is not None else 'trig'}"
                rows.append((_row(label, res), acts))
                print(f"  … {label}: {rows[-1][0]['turnover_pct']:.1f}%/day, "
                      f"net Sharpe {rows[-1][0]['net_sharpe']:+.2f}   [{acts}]")

    print(f"\n══ REBALANCE MATRIX — iter 2 (top-{pc.REBAL['rank_exit']} exit, "
          f"{pc.REBAL['drift_pp']}pp band), {rows[0][0]['n_days']} trading days, ADVISORY ══\n")
    print(f"  {'CELL':14}{'TURNOVER':>10}{'NAMES':>8}{'TRD-DAYS':>9}{'GROSS':>8}{'NET':>8}"
          f"{'GROSS':>8}{'NET':>8}{'COST':>8}")
    print(f"  {'':14}{'%/day 1-way':>10}{'trd/day':>8}{'% days':>9}{'Shrp':>8}{'Shrp':>8}"
          f"{'ann%':>8}{'ann%':>8}{'%/yr':>8}")
    for r, _ in rows:
        print(f"  {r['label']:14}{r['turnover_pct']:>9.1f}%{r['n_traded']:>8.1f}"
              f"{r['trade_days_pct']:>8.0f}%{r['gross_sharpe']:>8.2f}{r['net_sharpe']:>8.2f}"
              f"{r['gross_ann']:>7.1f}%{r['net_ann']:>7.1f}%{r['cost_ann']:>7.1f}%")

    banded = [r for r, _ in rows[1:]]
    win = max(banded, key=lambda r: (round(r["net_sharpe"], 2), -r["turnover_pct"]))
    print(f"\n  WINNER (net Sharpe, tiebreak lower turnover): {win['label']} — "
          f"{win['turnover_pct']:.1f}%/day, net Sharpe {win['net_sharpe']:+.2f} → "
          f"{'PASS' if win['turnover_pct'] < 5 else 'FAIL'} vs <5%/day target")
    print(f"  Read-only replay; stored portfolio_weights untouched. ADVISORY.\n")
    return rows


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

    acts = {}
    for a in actions:
        key = a[1] if isinstance(a[1], str) and not a[1].startswith("SKIP") else "SKIP"
        acts[key] = acts.get(key, 0) + 1
    n_carry = acts.get("carry", 0)
    n_names = (acts.get("rebalance (names)", 0) + acts.get("rebalance (partial)", 0)
               + acts.get("rebalance (weekly)", 0))
    n_drift = acts.get("rebalance (drift)", 0)
    n_skip = acts.get("SKIP", 0)

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


# ── --sweep (plan 0012 B2): exit-rank x drift-band x score-EMA halflife ──────
def _ema_adjusted_picks(halflife, end=None):
    """Full daily_picks history (up to `end`). halflife=None is the identity
    transform (raw daily_picks). Otherwise: per-sid EWM(halflife) on
    `final_score` over that sid's own observed pick_dates only (no reindex to
    a full date grid — a sid missing from a date simply isn't in its own
    series, so it carries no value there, per plan 0012 B2), then re-ranked
    within (pick_date, cap_tier) by the smoothed score descending."""
    where = "WHERE pick_date <= ?" if end else ""
    df = read_sql(
        f"SELECT pick_date, sid, rank, final_score, cap_tier, sector FROM daily_picks {where} "
        f"ORDER BY sid, pick_date", params=[end] if end else None)
    if halflife is None:
        return df
    df = df.sort_values(["sid", "pick_date"]).reset_index(drop=True)
    df["ema_score"] = df.groupby("sid")["final_score"].transform(
        lambda s: s.ewm(halflife=halflife).mean())
    df["rank"] = (df.groupby(["pick_date", "cap_tier"])["ema_score"]
                  .rank(ascending=False, method="first").astype(int))
    df["final_score"] = df["ema_score"]
    return df.drop(columns=["ema_score"])


def _make_select_candidates(picks_df):
    def _select(asof, min_depth=0):
        day = picks_df[picks_df["pick_date"] == asof]
        parts = []
        for tier, k in pc.PICKS_PER_TIER.items():
            sub = day[day["cap_tier"] == tier].nsmallest(max(k * 3, min_depth), "rank")
            parts.append(sub[["sid", "rank", "final_score", "cap_tier", "sector"]])
        if not parts or all(p.empty for p in parts):
            return pd.DataFrame(columns=["sid", "rank", "final_score", "cap_tier", "sector"])
        return pd.concat(parts, ignore_index=True)
    return _select


def _make_rank_ok_lastn(picks_df):
    def _rank_ok(sids, asof, n, rank_exit):
        dates = sorted(picks_df.loc[picks_df["pick_date"] <= asof, "pick_date"].unique())[-n:]
        if not dates or not sids:
            return set()
        sub = picks_df[picks_df["pick_date"].isin(dates) & picks_df["sid"].isin(sids)
                       & (picks_df["rank"] <= rank_exit)]
        return set(sub["sid"])
    return _rank_ok


def _sweep_label(rank_exit, drift_pp, halflife):
    return f"rx{rank_exit}/dp{drift_pp:g}/ema{halflife if halflife else 'none'}"


def _to_md(df):
    if df.empty:
        return "_(no rows)_"
    cols = list(df.columns)
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = "\n".join(
        "| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |"
        for row in df.itertuples(index=False)
    )
    return "\n".join([header, sep, body])


def sweep_report(end=None):
    """36-cell {exit-rank}x{drift-band}x{EMA halflife} grid (plan 0012 B2,
    WS1.1 evidence, HUMAN GATE G1 — recommendation only, no production write)."""
    daily_books = load_stored_books(end)
    if len(daily_books) < 2:
        print("⚠ need ≥2 stored portfolio_weights books"); return
    dates = sorted(daily_books)
    start = daily_books[dates[0]]

    price = _load_price_panel()
    rets = price.pct_change(fill_method=None).clip(*RET_CLIP)
    if end:
        rets = rets[rets.index <= pd.Timestamp(end)]
    _install_fast_io(dates[1:], start["sid"].tolist())

    orig_select_candidates, orig_rank_ok_lastn = pc.select_candidates, pc._rank_ok_lastn
    orig_rank_exit, orig_drift_pp = pc.REBAL.get("rank_exit"), pc.REBAL.get("drift_pp")

    picks_cache = {hl: _ema_adjusted_picks(hl, end=end) for hl in SWEEP_EMA_HALFLIFE}

    print(f"running {len(SWEEP_RANK_EXIT) * len(SWEEP_DRIFT_PP) * len(SWEEP_EMA_HALFLIFE)}-cell "
          f"sweep (exit-rank x drift-pp x EMA halflife), production debounce="
          f"{pc.REBAL.get('debounce_days')}/resize={pc.REBAL.get('resize')} held fixed …")

    rows = []
    reference_ret = None
    t0 = time.time()
    truncated = False
    grid = [(rx, dp, hl) for rx in SWEEP_RANK_EXIT for dp in SWEEP_DRIFT_PP for hl in SWEEP_EMA_HALFLIFE]
    for rank_exit, drift_pp, hl in grid:
        if time.time() - t0 > SWEEP_WALLCLOCK_LIMIT_S:
            truncated = True
            break
        pc.REBAL["rank_exit"] = rank_exit
        pc.REBAL["drift_pp"] = drift_pp
        pdf = picks_cache[hl]
        pc.select_candidates = _make_select_candidates(pdf)
        pc._rank_ok_lastn = _make_rank_ok_lastn(pdf)
        books, actions = replay_banded(start, dates[1:])
        res = nav_replay(books, rets, TRANSACTION_COSTS_BPS)
        r = _row(_sweep_label(rank_exit, drift_pp, hl), res)
        r.update({"rank_exit": rank_exit, "drift_pp": drift_pp, "ema_halflife": hl})
        rows.append((r, res["gross"]))
        if rank_exit == 8 and drift_pp == 2.0 and hl is None:
            reference_ret = res["gross"]
        print(f"  … {r['label']}: {r['turnover_pct']:.2f}%/day, net_ann {r['net_ann']:+.1f}%, "
              f"gross_ann {r['gross_ann']:+.1f}%, net Sharpe {r['net_sharpe']:+.2f}")

    pc.select_candidates, pc._rank_ok_lastn = orig_select_candidates, orig_rank_ok_lastn
    pc.REBAL["rank_exit"], pc.REBAL["drift_pp"] = orig_rank_exit, orig_drift_pp

    if reference_ret is None:
        print("⚠ reference cell (rx8/dp2.0/ema-none) not reached — cannot score corr; aborting sweep report.")
        return rows

    for r, gross in rows:
        r["corr_vs_reference"] = round(float(gross.corr(reference_ret)), 4)

    cell_rows = [r for r, _ in rows]
    for r in cell_rows:
        r["pass_turnover"] = r["turnover_pct"] <= ACCEPT_TURNOVER_PCT_DAY
        r["pass_net_gross_gap"] = (r["gross_ann"] - r["net_ann"]) <= ACCEPT_NET_GROSS_GAP_PP
        r["pass_corr"] = r["corr_vs_reference"] >= ACCEPT_MIN_CORR
        r["pass_all"] = r["pass_turnover"] and r["pass_net_gross_gap"] and r["pass_corr"]

    passers = [r for r in cell_rows if r["pass_all"]]
    winner = None
    if passers:
        winner = max(passers, key=lambda r: (round(r["net_ann"], 4), -r["turnover_pct"]))

    def _miss_score(r):
        return (max(0.0, r["turnover_pct"] - ACCEPT_TURNOVER_PCT_DAY) / ACCEPT_TURNOVER_PCT_DAY
                + max(0.0, (r["gross_ann"] - r["net_ann"]) - ACCEPT_NET_GROSS_GAP_PP) / ACCEPT_NET_GROSS_GAP_PP
                + max(0.0, ACCEPT_MIN_CORR - r["corr_vs_reference"]) / ACCEPT_MIN_CORR)

    nearest_misses = sorted(cell_rows, key=_miss_score)[:3]

    # drift_pp sensitivity check: did widening the band ever change a single cell?
    by_rx_ema = {}
    for r in cell_rows:
        by_rx_ema.setdefault((r["rank_exit"], r["ema_halflife"]), []).append(r["turnover_pct"])
    # tolerance matches the study table's own 2-decimal display precision
    drift_pp_inert = all(len(set(round(v, 2) for v in vals)) == 1 for vals in by_rx_ema.values())

    # Best net_ann cell overall, regardless of pass/fail — informational only (G1 unaffected).
    best_net_ann = max(cell_rows, key=lambda r: r["net_ann"])

    print(f"\n══ CADENCE SWEEP — {len(cell_rows)} cells, {'TRUNCATED (>60min)' if truncated else 'complete'} ══\n")
    print(f"  {len(passers)}/{len(cell_rows)} cells pass all 3 acceptance criteria "
          f"(turnover<={ACCEPT_TURNOVER_PCT_DAY}%/day, gap<={ACCEPT_NET_GROSS_GAP_PP}pp, "
          f"corr>={ACCEPT_MIN_CORR}).")
    if winner:
        print(f"  WINNER: {winner['label']} — turnover {winner['turnover_pct']:.2f}%/day, "
              f"net_ann {winner['net_ann']:+.1f}%, gross_ann {winner['gross_ann']:+.1f}%, "
              f"corr {winner['corr_vs_reference']:.3f}")
    else:
        print("  NO cell passes all 3 criteria. Nearest misses:")
        for r in nearest_misses:
            print(f"    {r['label']}: turnover {r['turnover_pct']:.2f}%/day "
                  f"(<= {ACCEPT_TURNOVER_PCT_DAY}: {r['pass_turnover']}), "
                  f"gap {(r['gross_ann'] - r['net_ann']):.1f}pp "
                  f"(<= {ACCEPT_NET_GROSS_GAP_PP}: {r['pass_net_gross_gap']}), "
                  f"corr {r['corr_vs_reference']:.3f} (>= {ACCEPT_MIN_CORR}: {r['pass_corr']})")

    if drift_pp_inert:
        print(f"  NOTE: drift_pp had zero effect on every cell in this window — no drift-band "
              f"re-size ever triggered (matches the baseline run's '0 drift-band of 65' actions); "
              f"the sweep's drift_pp dimension is inert here, all turnover is rank-exit-driven.")
    print(f"  FYI (not a G1 recommendation): best net_ann cell overall is {best_net_ann['label']} "
          f"at {best_net_ann['net_ann']:+.1f}% (turnover {best_net_ann['turnover_pct']:.2f}%/day) "
          f"— fails the strict WS1.1 bar but is a large improvement over today's "
          f"production config's +2.0% net_ann.")

    _write_sweep_study(cell_rows, winner, nearest_misses, truncated, drift_pp_inert, best_net_ann)
    print(f"\n  G1: production defaults NOT changed. Study -> {STUDY_OUT}\n")
    return rows


def _write_sweep_study(cell_rows, winner, nearest_misses, truncated, drift_pp_inert=False, best_net_ann=None):
    df = pd.DataFrame([{
        "cell": r["label"], "rank_exit": r["rank_exit"], "drift_pp": r["drift_pp"],
        "ema_halflife_sort": r["ema_halflife"] if r["ema_halflife"] else 0,
        "ema_halflife": r["ema_halflife"] if r["ema_halflife"] else "none",
        "turnover_pct_day": round(r["turnover_pct"], 2),
        "gross_ann_pct": round(r["gross_ann"], 2), "net_ann_pct": round(r["net_ann"], 2),
        "net_sharpe": round(r["net_sharpe"], 2) if r["net_sharpe"] == r["net_sharpe"] else None,
        "corr_vs_reference": r["corr_vs_reference"],
        "pass_all": r["pass_all"],
    } for r in cell_rows]).sort_values(["rank_exit", "drift_pp", "ema_halflife_sort"]).drop(columns=["ema_halflife_sort"])

    lines = []
    lines.append("# Cadence/EMA parameter sweep (plan 0012 B2)\n")
    lines.append(
        f"Read-only, sim-only ({{'exit-rank': {SWEEP_RANK_EXIT}}} x "
        f"{{'drift_pp': {SWEEP_DRIFT_PP}}} x {{'EMA halflife (trading days)': "
        f"{SWEEP_EMA_HALFLIFE}}} = {len(SWEEP_RANK_EXIT)*len(SWEEP_DRIFT_PP)*len(SWEEP_EMA_HALFLIFE)} cells), "
        "via `tools/rebalance_sim.py --sweep`'s in-memory replay of production "
        "`portfolio_construction._build_banded()` — nothing written to `portfolio_weights` or "
        "config. Production `debounce_days`/`resize` held at their current (ADR 0046 winner) "
        f"values: debounce={pc.REBAL.get('debounce_days')}, resize={pc.REBAL.get('resize')}.\n"
    )
    lines.append(
        f"**Acceptance bar (plan 0011 WS1.1):** turnover <= {ACCEPT_TURNOVER_PCT_DAY}%/day AND "
        f"net_ann within {ACCEPT_NET_GROSS_GAP_PP}pp of gross_ann AND daily-return corr vs the "
        "current production config (rank_exit=8, drift_pp=2.0, EMA=none) >= "
        f"{ACCEPT_MIN_CORR}.\n"
    )
    if truncated:
        lines.append("**NOTE: sweep exceeded the 60-minute wall-clock STOP-IF and was truncated "
                      "before completing the full grid** — see the cell count below.\n")
    lines.append(f"## All {len(cell_rows)} cells\n")
    lines.append(_to_md(df))
    lines.append("\n\n## Verdict\n")
    if winner:
        lines.append(
            f"**{winner['label']}** passes all 3 criteria and has the highest net_ann among "
            f"passers (tiebreak: lower turnover): turnover {winner['turnover_pct']:.2f}%/day, "
            f"net_ann {winner['net_ann']:+.1f}%, gross_ann {winner['gross_ann']:+.1f}%, corr "
            f"{winner['corr_vs_reference']:.3f} vs the current production config. **G1: this is "
            "a recommendation only — Amit decides whether to flip the production default.**\n"
        )
    else:
        miss_df = pd.DataFrame([{
            "cell": r["label"], "turnover_pct_day": round(r["turnover_pct"], 2),
            "net_gross_gap_pp": round(r["gross_ann"] - r["net_ann"], 2),
            "corr_vs_reference": r["corr_vs_reference"],
        } for r in nearest_misses])
        lines.append(
            "**No cell passes all 3 criteria.** Nearest misses (by normalized violation "
            "distance):\n\n" + _to_md(miss_df) +
            "\n\n**G1: no production default change is recommended from this sweep** — the "
            "target as specified isn't reachable within this grid; a human should decide "
            "whether to widen the grid, relax the acceptance bar, or pursue a different lever "
            "(e.g. sector/name budget caps) instead.\n"
        )
    if drift_pp_inert:
        lines.append(
            "\n**Note: `drift_pp` was inert across the whole grid** — every cell's turnover is "
            "identical across drift_pp in {2,3,4} for a given (rank_exit, EMA halflife). This "
            "matches the earlier `--matrix` baseline's own action log (\"0 drift-band of 65\"): "
            "in this ~61-trading-day window, no rebalance was ever triggered by weight drift "
            "alone — every trade was rank-exit-driven. `drift_pp` may still matter over a longer "
            "or more volatile window; this sweep's window can't speak to that.\n"
        )
    if best_net_ann is not None:
        lines.append(
            f"\n**FYI, not a G1 recommendation:** the single best net_ann cell in the whole grid "
            f"is **{best_net_ann['label']}** at {best_net_ann['net_ann']:+.1f}% net_ann "
            f"(turnover {best_net_ann['turnover_pct']:.2f}%/day, net Sharpe "
            f"{best_net_ann['net_sharpe']:+.2f}) — it fails the strict WS1.1 turnover/gap bar, "
            "but is a large improvement over today's production config's +2.0% net_ann / 0.11 "
            "Sharpe. EMA-smoothing the ranking score (halflife=10 trading days) shows up "
            "repeatedly among the best cells — worth a closer look even outside this specific "
            "acceptance bar.\n"
        )
    STUDY_OUT.parent.mkdir(parents=True, exist_ok=True)
    STUDY_OUT.write_text("\n".join(lines))


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
    ap.add_argument("--matrix", action="store_true",
                    help="iteration-2 grid: {debounce 1/2/3} × {full/partial "
                         "re-size} × {trigger-only/weekly full re-size}")
    ap.add_argument("--sweep", action="store_true",
                    help="iteration-3 grid (plan 0012 B2): {exit-rank 8/10/12} x "
                         "{drift-pp 2/3/4} x {score-EMA halflife None/3/5/10} — "
                         "WS1.1 evidence, writes docs/studies/cadence-sweep-2026-07.md, "
                         "changes no production default (HUMAN GATE G1)")
    args = ap.parse_args()
    if args.sweep:
        sweep_report(end=args.end)
        return
    if args.rank_exit is not None:
        pc.REBAL["rank_exit"] = args.rank_exit
    if args.drift_pp is not None:
        pc.REBAL["drift_pp"] = args.drift_pp
    if args.matrix:
        matrix_report(end=args.end)
    else:
        report(end=args.end)


if __name__ == "__main__":
    main()
