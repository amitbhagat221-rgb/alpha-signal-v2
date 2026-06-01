"""
Alpha Signal v2 — Pick Outcomes Computation

For every (sid, pick_date) in `daily_picks`, compute the realized close-to-
close return over fixed forward windows (default 20/63/126 TRADING days ≈
1mo / 3mo / 6mo) using `stock_prices.close`, plus the matching benchmark:

  cap_tier  → benchmark
  LARGE     → NIFTY 50
  MID       → NIFTY MIDCAP 150
  SMALL     → NIFTY SMALLCAP 250

Windows are TRADING days (rows in the stock's own price series), NOT calendar
days. This matches the backtest's `fwd_return_20d` (reconstruct_pit.py:
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

from db import read_sql, upsert_df

DEFAULT_WINDOWS = (20, 63, 126)  # trading days ≈ 1mo / 3mo / 6mo
TIER_BENCHMARKS = {
    "LARGE": "NIFTY 50",
    "MID":   "NIFTY MIDCAP 150",
    "SMALL": "NIFTY SMALLCAP 250",
}


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
    the stock's own series — matches reconstruct_pit.pit_fwd_return_20d).

    Returns (exit_date, close) or None if the window hasn't matured yet.
    """
    s = series_map.get(sid)
    if s is None:
        return None
    tgt = entry_pos + window
    if tgt >= len(s):
        return None
    return s.index[tgt], float(s.iloc[tgt])


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
        print("⚠ no picks to score")
        return 0
    picks["pick_date"] = pd.to_datetime(picks["pick_date"])

    price_panel = _load_price_panel()
    if price_panel.empty:
        raise RuntimeError("stock_prices empty — cannot compute outcomes")
    price_series = _build_series(price_panel)

    bench_panel = _load_bench_panel() if include_bench else pd.DataFrame()
    bench_series = _build_series(bench_panel) if not bench_panel.empty else {}
    bench_max = bench_panel.index.max() if not bench_panel.empty else None
    if bench_max is not None and bench_max.date() < datetime.now().date():
        stale_d = (datetime.now().date() - bench_max.date()).days
        print(f"⚠ NIFTY benchmark latest = {bench_max.date()} ({stale_d}d stale) — "
              f"recent picks will have NULL bench_return_pct until it matures")

    out_rows = []

    for window in windows:
        scored = 0
        for _, row in picks.iterrows():
            sid = row["sid"]
            entry_dt = row["pick_date"]
            tier = row["cap_tier"]

            entry = _entry(price_series, sid, entry_dt)
            if entry is None:
                continue
            entry_pos, entry_used_dt, entry_close = entry
            ex = _exit_trading(price_series, sid, entry_pos, window)
            if ex is None:  # window not yet matured for this pick
                continue
            exit_dt, exit_close = ex

            fwd_ret = 100.0 * (exit_close / entry_close - 1.0)

            bench_ret = None
            bench_name = TIER_BENCHMARKS.get(tier)
            if include_bench and bench_name and bench_name in bench_series:
                b_entry = _entry(bench_series, bench_name, entry_dt)
                if b_entry is not None:
                    b_ex = _exit_trading(bench_series, bench_name, b_entry[0], window)
                    if b_ex is not None:
                        bench_ret = 100.0 * (b_ex[1] / b_entry[2] - 1.0)
            scored += 1

            out_rows.append({
                "sid": sid,
                "pick_date": entry_dt.strftime("%Y-%m-%d"),
                "window_days": int(window),
                "cap_tier": tier,
                "rank_at_pick": int(row["rank"]) if pd.notna(row["rank"]) else None,
                "final_score": float(row["final_score"]) if pd.notna(row["final_score"]) else None,
                "entry_price": round(entry_close, 4),
                "exit_date": exit_dt.strftime("%Y-%m-%d"),
                "exit_price": round(exit_close, 4),
                "fwd_return_pct": round(fwd_ret, 4),
                "bench_index": bench_name,
                "bench_return_pct": round(bench_ret, 4) if bench_ret is not None else None,
                "excess_return_pct": round(fwd_ret - bench_ret, 4) if bench_ret is not None else None,
                "computed_at": datetime.now().isoformat(timespec="seconds"),
            })

        print(f"  window {window:>3}d: scored {scored:,} matured picks "
              f"(of {len(picks):,} total)")

    if not out_rows:
        print("⚠ no outcomes computed (no mature picks?)")
        return 0

    out = pd.DataFrame(out_rows)
    n = upsert_df(out, "pick_outcomes")
    print(f"✓ wrote/updated {n:,} pick_outcomes rows")
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
