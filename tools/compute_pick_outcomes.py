"""
Alpha Signal v2 — Pick Outcomes Computation

For every (sid, pick_date) in `daily_picks`, compute the realized close-to-
close return over fixed forward windows (default 20/63/126 TRADING days ≈
1mo / 3mo / 6mo) using split/bonus/dividend-ADJUSTED closes (`pit.forward_returns`, the one label), plus the matching benchmark:

  cap_tier  → benchmark
  LARGE     → NIFTY 50
  MID       → NIFTY MIDCAP 150
  SMALL     → NIFTY SMALLCAP 250

Windows are TRADING days (rows in the stock's own price series), NOT calendar
days. This matches the backtest's `fwd_return_20d` (pit.py:
anchor_idx + 20 trading days), so the live mirror measures the same horizon
the factor model was validated on. 20d = model-native reference; 63d/126d =
the positional (1–6 month) holding horizon the product actually targets. The
old 5d window (≈3 trading days) was microstructure noise and was dropped.

Writes to `pick_outcomes` (PK = sid + pick_date + window_days). Idempotent;
re-runs UPDATE existing rows in place via upsert_df. A pick only gets a row
for window N once it has N trading days of prices after entry — newer picks
stay absent for the longer windows until they mature (~3mo / ~6mo out).

WHY: the factor model is hypothesis; this is the realization. ADR 0028 ships
factor-weight variants on |t-stat| and ICIR — both derived from BACKTEST
returns, not live picks. Without this table there's no honest mirror.

Usage:
    python -m tools.compute_pick_outcomes                    # all windows, all picks
    python -m tools.compute_pick_outcomes --windows 20       # one window
    python -m tools.compute_pick_outcomes --since 2026-05-01 # from cutover
    python -m tools.compute_pick_outcomes --no-bench         # skip benchmark calc
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import TIERS
from db import read_sql, upsert_df

DEFAULT_WINDOWS = (20, 63, 126)  # trading days ≈ 1mo / 3mo / 6mo
TIER_BENCHMARKS = {t: spec["benchmark"] for t, spec in TIERS.items() if "benchmark" in spec}


def _load_price_panel():
    """Wide panel of close prices: rows=date, cols=sid. Forward-fill within
    a stock so non-trading-day gaps don't drop the exit."""
    df = read_sql("SELECT sid, date, close FROM stock_prices WHERE close IS NOT NULL")
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    panel = df.pivot_table(index="date", columns="sid", values="close", aggfunc="last")
    panel = panel.sort_index()
    return panel


def _load_bench_panel():
    df = read_sql(
        "SELECT index_symbol, trade_date, close FROM nse_index_history "
        f"WHERE index_symbol IN ({','.join('?' * len(TIER_BENCHMARKS))})",
        params=list(TIER_BENCHMARKS.values()),
    )
    if df.empty:
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    panel = df.pivot_table(index="trade_date", columns="index_symbol",
                           values="close", aggfunc="last").sort_index()
    return panel


def _build_series(panel):
    """sid -> NaN-dropped, date-sorted close Series. Built once so the
    per-pick trading-day offset is a cheap positional lookup."""
    return {c: panel[c].dropna().sort_index()
            for c in panel.columns if panel[c].notna().any()}


def _entry(series_map, sid, entry_date):
    """First trading row on/after entry_date (handles pick made on a holiday).

    Returns (pos, exit_date, close) where pos is the row index in the stock's
    own trading series — the anchor for the forward trading-day offset. None if
    the stock has no price on/after entry_date.
    """
    s = series_map.get(sid)
    if s is None or s.empty:
        return None
    pos = int(s.index.searchsorted(entry_date, side="left"))
    if pos >= len(s):
        return None
    return pos, s.index[pos], float(s.iloc[pos])


def _exit_trading(series_map, sid, entry_pos, window):
    """Close `window` TRADING days after the anchor (entry_pos + window rows in
    the stock's own series — matches pit.pit_fwd_return_20d).

    Returns (exit_date, close) or None if the window hasn't matured yet.
    """
    s = series_map.get(sid)
    if s is None:
        return None
    tgt = entry_pos + window
    if tgt >= len(s):
        return None
    return s.index[tgt], float(s.iloc[tgt])


def trading_dates(prices):
    """The market calendar: every date on which any stock traded."""
    return pd.DatetimeIndex(sorted(pd.to_datetime(prices["date"].unique())))


def _bench_at(bench_series, name, day):
    """Index close on `day` (None if the index has no row that day)."""
    s = bench_series.get(name)
    if s is None or day not in s.index:
        return None
    return float(s.loc[day])


def score_picks(picks, prices, adjustments, bench_series, windows, include_bench=True):
    """Outcome rows for `picks` (sid, pick_date, cap_tier, rank, final_score).

    Returns are `pit.forward_returns` (the one label: split/bonus/dividend-adjusted
    closes, anchor-proximity guards). Picks are made before the open on pick_date from
    the prior close, so eval_date = the last session BEFORE pick_date and the label's
    entry (first session after eval_date) is the pick_date close. Pick dates that are not
    a trading day (weekend/holiday screener runs copy the prior session) are dropped: one
    pick date per trading day. The benchmark is the index close on the same entry and exit
    sessions (the market calendar the label uses).
    """
    import pit
    cal = trading_dates(prices)
    picks = picks.copy()
    picks["pick_date"] = pd.to_datetime(picks["pick_date"])
    picks = picks[picks["pick_date"].isin(cal)]
    if adjustments is not None and not adjustments.empty:
        adj = pit._fully_adjusted(prices, adjustments)
    else:
        adj = prices.assign(adj_close=prices["close"])
    adj = adj.assign(date=pd.to_datetime(adj["date"]))
    adj_close = adj.pivot_table(index="date", columns="sid", values="adj_close", aggfunc="last")
    horizons = tuple(int(w) for w in windows)
    rows = []
    for pdt, grp in picks.groupby("pick_date"):
        i = int(cal.get_loc(pdt))
        if i == 0:
            continue
        labels = pit.forward_returns(cal[i - 1].date(), prices, adjustments, horizons).set_index("sid")
        for w in horizons:
            col = f"fwd_return_{w}d"
            if col not in labels or i + w >= len(cal):
                continue
            entry_dt, exit_dt = cal[i], cal[i + w]
            for r in grp.itertuples():
                ret = labels[col].get(r.sid)
                if ret is None or pd.isna(ret):
                    continue
                fwd = 100.0 * float(ret)
                bname = TIER_BENCHMARKS.get(r.cap_tier)
                bret = None
                if include_bench and bname:
                    b0, b1 = _bench_at(bench_series, bname, entry_dt), _bench_at(bench_series, bname, exit_dt)
                    if b0 and b1:
                        bret = 100.0 * (b1 / b0 - 1.0)
                p0 = adj_close.at[entry_dt, r.sid] if r.sid in adj_close.columns else None
                p1 = adj_close.at[exit_dt, r.sid] if r.sid in adj_close.columns else None
                rows.append({
                    "sid": r.sid, "pick_date": pdt.strftime("%Y-%m-%d"), "window_days": w,
                    "cap_tier": r.cap_tier,
                    "rank_at_pick": int(r.rank) if pd.notna(r.rank) else None,
                    "final_score": float(r.final_score) if pd.notna(r.final_score) else None,
                    "entry_price": round(float(p0), 4) if p0 is not None and pd.notna(p0) else None,
                    "exit_date": exit_dt.strftime("%Y-%m-%d"),
                    "exit_price": round(float(p1), 4) if p1 is not None and pd.notna(p1) else None,
                    "fwd_return_pct": round(fwd, 4),
                    "bench_index": bname,
                    "bench_return_pct": round(bret, 4) if bret is not None else None,
                    "excess_return_pct": round(fwd - bret, 4) if bret is not None else None,
                    "computed_at": datetime.now().isoformat(timespec="seconds"),
                })
    return pd.DataFrame(rows)


def _drop_superseded_rows(started, since):
    """Rows this run did not rewrite are old-basis rows (weekend/holiday pick dates, or
    pairs the adjusted label now rejects): upsert never deletes, so remove them. Scoped to
    the picks this run covered (`since`)."""
    from db import get_db
    with get_db() as conn:
        cur = conn.execute("DELETE FROM pick_outcomes WHERE computed_at < ?"
                           + (" AND pick_date >= ?" if since else ""),
                           (started, since) if since else (started,))
        return cur.rowcount


def compute(windows=DEFAULT_WINDOWS, since=None, include_bench=True):
    where = "WHERE pick_date >= ?" if since else ""
    params = [since] if since else []
    picks = read_sql(
        f"SELECT sid, pick_date, cap_tier, rank, final_score "
        f"FROM daily_picks {where} "
        f"ORDER BY pick_date, cap_tier, rank",
        params=params,
    )
    if picks.empty:
        print("no picks to score")
        return 0

    started = datetime.now().isoformat(timespec="seconds")
    import pit
    raw = pit.load_raw({"prices", "adjustments"})
    prices = raw["prices"][["sid", "date", "close"]]
    if prices.empty:
        raise RuntimeError("stock_prices empty — cannot compute outcomes")

    bench_panel = _load_bench_panel() if include_bench else pd.DataFrame()
    bench_series = _build_series(bench_panel) if not bench_panel.empty else {}
    bench_max = bench_panel.index.max() if not bench_panel.empty else None
    if bench_max is not None and bench_max.date() < datetime.now().date():
        stale_d = (datetime.now().date() - bench_max.date()).days
        print(f"NIFTY benchmark latest = {bench_max.date()} ({stale_d}d stale) — "
              f"recent picks will have NULL bench_return_pct until it matures")

    out = score_picks(picks, prices, raw["adjustments"], bench_series, windows, include_bench)
    if out.empty:
        raise RuntimeError("no pick outcomes computed (no mature trading-day picks?) — "
                           "a producer that writes zero rows must raise")
    print(f"  scored {len(out):,} outcomes over {out['pick_date'].nunique()} trading pick dates "
          f"({picks['pick_date'].nunique()} pick dates in daily_picks)")
    n = upsert_df(out, "pick_outcomes")
    dropped = _drop_superseded_rows(started, since)
    print(f"wrote/updated {n:,} pick_outcomes rows; removed {dropped:,} superseded rows "
          f"(non-trading pick dates, pairs the adjusted label rejects)")
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows", type=str, default="20,63,126",
                        help="Comma-separated forward windows in TRADING days")
    parser.add_argument("--since", type=str, default=None,
                        help="Only score picks made on/after this date (YYYY-MM-DD)")
    parser.add_argument("--no-bench", action="store_true",
                        help="Skip benchmark return computation")
    args = parser.parse_args()

    windows = tuple(int(w) for w in args.windows.split(","))
    compute(windows=windows, since=args.since, include_bench=not args.no_bench)


if __name__ == "__main__":
    main()
