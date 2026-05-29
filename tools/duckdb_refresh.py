"""Rebuild the DuckDB read-replica from the SQLite source of truth.

Run after the nightly pipeline (or manually). Mirrors a curated list of
nightly-written tables so cockpit reads can use columnar scans.

Intraday-written tables (news_articles, 14:00 forward-only tables) are NOT
mirrored — they would be stale by mid-day and should keep reading SQLite.
"""

from __future__ import annotations
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
SQLITE_PATH = ROOT / "data" / "alpha_signal.db"
DUCK_PATH = ROOT / "data" / "alpha_signal.duckdb"

# Curated pilot set — expand once the pattern is trusted.
# All are nightly-written by the 03:30 pipeline.
MIRROR_TABLES = [
    "daily_snapshots_pit",
    "daily_snapshots_pit_v1",
    "pit_ic_by_tier_v1",
    "stock_prices",
    "daily_picks",
    "pick_outcomes",
    "consensus_signals",
]


def refresh() -> dict:
    if not SQLITE_PATH.exists():
        raise FileNotFoundError(f"SQLite source missing: {SQLITE_PATH}")

    t0 = time.perf_counter()
    DUCK_PATH.unlink(missing_ok=True)

    con = duckdb.connect(str(DUCK_PATH))
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{SQLITE_PATH}' AS s (TYPE sqlite, READ_ONLY)")

    per_table = {}
    for tbl in MIRROR_TABLES:
        t_tbl = time.perf_counter()
        con.execute(f'CREATE TABLE "{tbl}" AS SELECT * FROM s."{tbl}"')
        n = con.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
        per_table[tbl] = {"rows": n, "secs": round(time.perf_counter() - t_tbl, 2)}

    con.execute("CHECKPOINT")
    con.close()

    elapsed = round(time.perf_counter() - t0, 2)
    size_mb = round(DUCK_PATH.stat().st_size / 1e6, 1)
    return {"elapsed_s": elapsed, "size_mb": size_mb, "tables": per_table}


def main():
    print(f"Source: {SQLITE_PATH}")
    print(f"Target: {DUCK_PATH}\n")
    result = refresh()
    for tbl, info in result["tables"].items():
        print(f"  {tbl:30s} {info['rows']:>10,} rows  {info['secs']:>5.2f}s")
    print(f"\nTotal: {result['elapsed_s']}s  |  File: {result['size_mb']} MB")


if __name__ == "__main__":
    main()
