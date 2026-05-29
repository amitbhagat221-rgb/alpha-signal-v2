"""
Alpha Signal v2 — Pick Outcomes Computation

For every (sid, pick_date) in `daily_picks`, compute the realized close-to-
close return over fixed forward windows (default 5/20/60d) using
`stock_prices.close`, plus the matching benchmark return:

  cap_tier  → benchmark
  LARGE     → NIFTY 50
  MID       → NIFTY MIDCAP 150
  SMALL     → NIFTY SMALLCAP 250

Writes to `pick_outcomes` (PK = sid + pick_date + window_days). Idempotent;
re-runs UPDATE existing rows in place via upsert_df.

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

DEFAULT_WINDOWS = (5, 20, 60)
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


def _forward_close(panel, sid, entry_date, window_days):
    """Close on the first trading day on/after entry_date+window_days.

    Returns (exit_date, exit_close) or (None, None) if no row available.
    """
    if sid not in panel.columns:
        return None, None
    target = entry_date + pd.Timedelta(days=window_days)
    col = panel[sid].dropna()
    if col.empty:
        return None, None
    eligible = col[col.index >= target]
    if eligible.empty:
        return None, None
    exit_date = eligible.index[0]
    return exit_date, float(eligible.iloc[0])


def _entry_close(panel, sid, entry_date):
    """Close on entry_date itself (or the next trading day if entry was a holiday).

    The screener writes daily_picks every calendar day; not every calendar day
    is a trading day. Use first available close on/after entry_date.
    """
    if sid not in panel.columns:
        return None, None
    col = panel[sid].dropna()
    if col.empty:
        return None, None
    eligible = col[col.index >= entry_date]
    if eligible.empty:
        return None, None
    return eligible.index[0], float(eligible.iloc[0])


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

    bench_panel = _load_bench_panel() if include_bench else pd.DataFrame()
    bench_max = bench_panel.index.max() if not bench_panel.empty else None
    if bench_max is not None and bench_max.date() < datetime.now().date():
        stale_d = (datetime.now().date() - bench_max.date()).days
        print(f"⚠ NIFTY benchmark latest = {bench_max.date()} ({stale_d}d stale) — "
              f"newer picks will have NULL bench_return_pct")

    out_rows = []
    today = pd.Timestamp.now().normalize()

    for window in windows:
        # Only score picks whose forward window has fully realized
        cutoff = today - pd.Timedelta(days=window)
        mature = picks[picks["pick_date"] <= cutoff]
        print(f"  window {window:>2}d: {len(mature):,} mature picks "
              f"(out of {len(picks):,} total)")

        for _, row in mature.iterrows():
            sid = row["sid"]
            entry_dt = row["pick_date"]
            tier = row["cap_tier"]

            _, entry_close = _entry_close(price_panel, sid, entry_dt)
            exit_dt, exit_close = _forward_close(price_panel, sid, entry_dt, window)
            if entry_close is None or exit_close is None:
                continue

            fwd_ret = 100.0 * (exit_close / entry_close - 1.0)

            bench_ret = None
            bench_name = TIER_BENCHMARKS.get(tier)
            if include_bench and bench_name and not bench_panel.empty and bench_name in bench_panel.columns:
                _, b_entry = _entry_close(bench_panel.rename_axis(index="date"), bench_name, entry_dt)
                _, b_exit = _forward_close(bench_panel.rename_axis(index="date"), bench_name, entry_dt, window)
                if b_entry is not None and b_exit is not None:
                    bench_ret = 100.0 * (b_exit / b_entry - 1.0)

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

    if not out_rows:
        print("⚠ no outcomes computed (no mature picks?)")
        return 0

    out = pd.DataFrame(out_rows)
    n = upsert_df(out, "pick_outcomes")
    print(f"✓ wrote/updated {n:,} pick_outcomes rows")
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows", type=str, default="5,20,60",
                        help="Comma-separated forward windows in days")
    parser.add_argument("--since", type=str, default=None,
                        help="Only score picks made on/after this date (YYYY-MM-DD)")
    parser.add_argument("--no-bench", action="store_true",
                        help="Skip benchmark return computation")
    args = parser.parse_args()

    windows = tuple(int(w) for w in args.windows.split(","))
    compute(windows=windows, since=args.since, include_bench=not args.no_bench)


if __name__ == "__main__":
    main()
