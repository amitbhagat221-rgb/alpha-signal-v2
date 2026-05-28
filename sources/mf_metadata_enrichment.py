"""
Alpha Signal v2 — Mutual Fund metadata enrichment (AUM, expense ratio, manager).

Phase 4d of the MF research plan. Schema already has the columns
(`mf_scheme_master.aum_cr`, `.expense_ratio`); this module is the
ingest path.

Same trade-offs as `sources/mf_holdings.py`:
  - AMFI's AUM/expense data lives on JS-rendered portal pages with
    inconsistent per-AMC formats.
  - Free aggregators (Groww, Kuvera, ValueResearch) gate this behind
    JS / auth / scrape-resistance.
  - Paid feeds (Morningstar, Trendlyne) start at $500+/mo.

This module ships a CSV-ingest path that's productive TODAY:

  python -m sources.mf_metadata_enrichment --csv data/mf_enrichment.csv

CSV format expected:
  scheme_code,aum_cr,expense_ratio,fund_manager,benchmark
  122639,79543,0.62,Rajeev Thakkar,Nifty 500 TRI
  118989,71200,1.51,Chirag Setalvad,Nifty Midcap 150 TRI
  ...

For the deferred automated path: AMFI publishes a quarterly AAUM file +
expense-ratio sheet; once the URL pattern is reverse-engineered (target
v2), this module's `ingest_amfi_aaum()` slot will be populated.

Usage:
    python -m sources.mf_metadata_enrichment --csv path/to/enrichment.csv
    python -m sources.mf_metadata_enrichment --status
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import get_db, read_sql

# Columns this module knows how to ingest, mapped onto mf_scheme_master.
SUPPORTED_COLS = ["aum_cr", "expense_ratio", "fund_manager", "benchmark"]


def ingest_from_csv(path: str, dry_run: bool = False) -> int:
    """Read enrichment CSV → update mf_scheme_master. Returns rows updated."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    df = pd.read_csv(p)
    print(f"Loaded {len(df)} rows from {p}")

    if "scheme_code" not in df.columns:
        raise ValueError("CSV must include `scheme_code` column")

    # Identify which enrichment columns the CSV provides
    present = [c for c in SUPPORTED_COLS if c in df.columns]
    if not present:
        raise ValueError(f"CSV must include at least one of: {SUPPORTED_COLS}")
    print(f"Enrichment columns provided: {present}")

    df["scheme_code"] = df["scheme_code"].astype(str)
    for col in ["aum_cr", "expense_ratio"]:
        if col in present:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Ensure schema columns exist (the master_master schema already declares
    # aum_cr + expense_ratio + benchmark; add fund_manager if missing).
    with get_db() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(mf_scheme_master)")]
        if "fund_manager" not in cols and "fund_manager" in present:
            try:
                conn.execute("ALTER TABLE mf_scheme_master ADD COLUMN fund_manager TEXT")
                print("Added fund_manager column to mf_scheme_master")
            except Exception as e:
                if "duplicate" not in str(e).lower():
                    raise

    if dry_run:
        print("--dry-run: not saving.")
        print(df.head().to_string())
        return 0

    # Build UPDATE statement that only touches columns provided in the CSV.
    set_clause = ", ".join(f"{c} = excluded.{c}" for c in present)
    cols_sql = ", ".join(["scheme_code"] + present)
    placeholders = ", ".join("?" * (1 + len(present)))

    rows = [tuple([r[c] if pd.notna(r[c]) else None for c in ["scheme_code"] + present])
            for _, r in df.iterrows()]

    n_written = 0
    with get_db() as conn:
        for row in rows:
            scheme_code = row[0]
            updates = []
            params = []
            for i, col in enumerate(present, start=1):
                if row[i] is not None:
                    updates.append(f"{col} = ?")
                    params.append(row[i])
            if not updates:
                continue
            params.append(scheme_code)
            cur = conn.execute(
                f"UPDATE mf_scheme_master SET {', '.join(updates)} WHERE scheme_code = ?",
                params,
            )
            n_written += cur.rowcount

    print(f"\nUpdated {n_written} rows in mf_scheme_master")
    return n_written


def status() -> None:
    """Report enrichment coverage across the universe."""
    counts = read_sql("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN aum_cr IS NOT NULL THEN 1 ELSE 0 END) AS with_aum,
            SUM(CASE WHEN expense_ratio IS NOT NULL THEN 1 ELSE 0 END) AS with_expense,
            SUM(CASE WHEN benchmark IS NOT NULL THEN 1 ELSE 0 END) AS with_benchmark
        FROM mf_scheme_master
        WHERE active = 1
    """).iloc[0]
    cols = [r[1] for r in
            __import__("sqlite3").connect("data/alpha_signal.db").execute("PRAGMA table_info(mf_scheme_master)")]
    has_fm = "fund_manager" in cols
    print(f"mf_scheme_master enrichment coverage (active schemes only):")
    print(f"  Total active schemes:  {counts['total']}")
    print(f"  with aum_cr:           {counts['with_aum']:>5} / {counts['total']}")
    print(f"  with expense_ratio:    {counts['with_expense']:>5} / {counts['total']}")
    print(f"  with benchmark:        {counts['with_benchmark']:>5} / {counts['total']}")
    print(f"  fund_manager column:   {'yes' if has_fm else 'not yet created (will be added on first --csv with that column)'}")


def compute() -> int:
    """No-op PIPELINE_STEPS entry point — reports status only."""
    status()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv", help="Enrichment CSV (see module docstring for format)")
    p.add_argument("--status", action="store_true", help="Report current enrichment coverage")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.status or not args.csv:
        status()
    if args.csv:
        ingest_from_csv(args.csv, dry_run=args.dry_run)
