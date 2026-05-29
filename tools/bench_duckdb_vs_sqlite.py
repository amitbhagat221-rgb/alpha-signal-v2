"""Benchmark: SQLite direct vs DuckDB(ATTACH sqlite) vs DuckDB native.

Three representative queries:
  Q1 — Wide column scan on daily_snapshots_pit (360K rows × 68 cols)
  Q2 — Big aggregate on stock_prices (1.5M rows, per-sid window)
  Q3 — Multi-table join: daily_picks × stock_prices for realized 20d return

Each query runs N_RUNS times, reports min/median wall time.
Native DuckDB needs a one-time copy step; that cost is reported separately.
"""

from __future__ import annotations
import os, sys, time, shutil, statistics, sqlite3
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LIVE_DB = ROOT / "data" / "alpha_signal.db"
DUCK_DB = Path("/tmp/alpha_native.duckdb")
N_RUNS = 5

QUERIES = {
    "Q1_wide_pit_scan": """
        SELECT cap_tier,
               AVG(roe) AS roe,
               AVG(roa) AS roa,
               AVG(pt_upside) AS pt_up,
               AVG(eps_growth_yoy) AS eps_g,
               AVG(mom_12m) AS mom12,
               AVG(value_composite) AS valc,
               AVG(quality_composite) AS qualc,
               AVG(fcf_yield) AS fcfy,
               COUNT(*) AS n
        FROM daily_snapshots_pit
        WHERE snapshot_date >= '2025-06-01'
        GROUP BY cap_tier
    """,
    "Q2_prices_window": """
        SELECT sid,
               COUNT(*) AS n_days,
               MIN(close) AS lo,
               MAX(close) AS hi,
               AVG(volume) AS avg_vol
        FROM stock_prices
        WHERE date >= '2025-01-01'
        GROUP BY sid
    """,
    "Q3_picks_join_prices": """
        SELECT p.cap_tier,
               COUNT(*) AS n_picks,
               AVG(pr.close) AS avg_close
        FROM daily_picks p
        LEFT JOIN stock_prices pr
          ON pr.sid = p.sid
         AND pr.date = p.pick_date
        WHERE p.pick_date >= '2025-01-01'
        GROUP BY p.cap_tier
    """,
}


def time_runs(fn, n=N_RUNS):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return min(times), statistics.median(times)


def bench_sqlite(sql: str):
    conn = sqlite3.connect(str(LIVE_DB))
    conn.execute("PRAGMA query_only = 1")
    def run():
        cur = conn.execute(sql)
        cur.fetchall()
    out = time_runs(run)
    conn.close()
    return out


def bench_duck_attached(sql: str):
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{LIVE_DB}' AS s (TYPE sqlite, READ_ONLY)")
    con.execute("USE s")
    def run():
        con.execute(sql).fetchall()
    out = time_runs(run)
    con.close()
    return out


def bench_duck_native(sql: str):
    con = duckdb.connect(str(DUCK_DB), read_only=True)
    def run():
        con.execute(sql).fetchall()
    out = time_runs(run)
    con.close()
    return out


def build_native_copy() -> float:
    """One-time copy from SQLite → DuckDB native. Returns wall seconds."""
    if DUCK_DB.exists():
        DUCK_DB.unlink()
    t0 = time.perf_counter()
    con = duckdb.connect(str(DUCK_DB))
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{LIVE_DB}' AS s (TYPE sqlite, READ_ONLY)")
    for tbl in ("daily_snapshots_pit", "stock_prices", "daily_picks"):
        con.execute(f"CREATE TABLE {tbl} AS SELECT * FROM s.{tbl}")
    con.execute("CHECKPOINT")
    con.close()
    return time.perf_counter() - t0


def fmt_ms(s: float) -> str:
    if s < 1:
        return f"{s*1000:7.1f} ms"
    return f"{s:7.3f} s "


def main():
    print(f"\nLive SQLite DB: {LIVE_DB}  ({LIVE_DB.stat().st_size / 1e9:.2f} GB)")
    print(f"Runs per query: {N_RUNS}\n")

    print("Building DuckDB native copy (one-time)…", end=" ", flush=True)
    copy_secs = build_native_copy()
    duck_size = DUCK_DB.stat().st_size
    print(f"done in {copy_secs:.1f}s — DuckDB file: {duck_size/1e6:.0f} MB\n")

    header = f"{'Query':<24} {'SQLite':>14} {'Duck+ATTACH':>14} {'Duck native':>14} {'speedup':>10}"
    print(header)
    print("-" * len(header))
    for name, sql in QUERIES.items():
        sl_min, sl_med = bench_sqlite(sql)
        da_min, da_med = bench_duck_attached(sql)
        dn_min, dn_med = bench_duck_native(sql)
        speedup = sl_med / dn_med if dn_med else float("inf")
        print(f"{name:<24} {fmt_ms(sl_med):>14} {fmt_ms(da_med):>14} {fmt_ms(dn_med):>14} {speedup:>9.1f}x")

    print(f"\nNative-copy amortization: one rebuild = {copy_secs:.0f}s; pays for itself in cockpit lookups.")


if __name__ == "__main__":
    main()
