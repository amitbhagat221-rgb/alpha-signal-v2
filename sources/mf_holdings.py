"""
Alpha Signal v2 — Mutual Fund holdings ingest (stub + CSV path).

Phase 4c of the MF research plan. Original intent was an automated scrape
from AMFI's monthly portfolio disclosures. Reality check after probing
2026-05-26:
  - AMFI's portal at amfiindia.com/research-information/... is JS-rendered;
    static fetches return only the shell page (no links to the actual XLSX
    files we'd need).
  - Per-AMC monthly portfolios live under each AMC's own site with no
    common URL pattern (~50 AMCs would need ~50 parsers).
  - Free aggregators (Kuvera, Tickertape, Groww) hide MF holdings behind
    JS / authenticated endpoints we don't have.
  - Paid sources (Morningstar, Trendlyne, ValueResearch Premium) start at
    $500+/mo and are out of scope for v1.

This module ships TWO concrete paths that work TODAY without a scraper:

  1. ingest_from_csv(path) — accepts a hand-curated or vendor-exported CSV
     and writes to `mf_holdings`. Schema below. Use this when you have a
     small set of priority funds whose holdings you want to compare.

  2. ingest_amfi_archive_xlsx(path) — accepts an AMFI half-yearly
     consolidated XLSX (downloaded manually from AMFI's "Disclosure of
     Half-Yearly Portfolio" page). One file per half-year covers most
     equity schemes. Parses + dedupes + upserts. Manual quarterly drop is
     fine — holdings don't change daily.

Future automated path (deferred to v2):
  - Per-AMC monthly portfolio scrapers, prioritised by AUM
  - OR a paid feed (Morningstar Direct, Trendlyne data feed)

CSV format expected by ingest_from_csv:
  scheme_code,as_of_date,holding_rank,instrument_type,sid,isin,instrument_name,sector,pct_of_aum,market_value_cr
  122639,2026-03-31,1,EQUITY,POWR,INE752E01010,Power Grid Corporation of India,Utilities,8.5,2150.5
  122639,2026-03-31,2,EQUITY,HDFB,INE040A01034,HDFC Bank,Financials,7.2,1820.7
  ...

The `sid` column should map to `stocks.sid` if the holding is a tracked
Indian equity (allows cross-link to the stock detail page). NULL otherwise.

Usage:
    python -m sources.mf_holdings --csv /path/to/holdings.csv
    python -m sources.mf_holdings --status      # report current ingest state
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import get_db, read_sql


REQUIRED_COLS = [
    "scheme_code", "as_of_date", "holding_rank",
    "instrument_name", "pct_of_aum",
]
OPTIONAL_COLS = ["instrument_type", "sid", "isin", "sector", "market_value_cr"]


def ingest_from_csv(path: str, dry_run: bool = False) -> int:
    """Read holdings CSV → write mf_holdings. Returns rows written."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    df = pd.read_csv(p)
    print(f"Loaded {len(df)} rows from {p}")

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")

    # Ensure all expected columns exist
    for col in OPTIONAL_COLS:
        if col not in df.columns:
            df[col] = None

    # Coerce types
    df["scheme_code"] = df["scheme_code"].astype(str)
    df["as_of_date"] = pd.to_datetime(df["as_of_date"]).dt.date.astype(str)
    df["holding_rank"] = df["holding_rank"].astype(int)
    df["pct_of_aum"] = pd.to_numeric(df["pct_of_aum"], errors="coerce")
    df["market_value_cr"] = pd.to_numeric(df["market_value_cr"], errors="coerce")

    # Try to auto-match sid via ISIN if sid empty and isin present
    if df["sid"].isna().any() and df["isin"].notna().any():
        sid_map = read_sql("SELECT sid, isin FROM stocks WHERE isin IS NOT NULL")
        if not sid_map.empty:
            isin_to_sid = dict(zip(sid_map["isin"], sid_map["sid"]))
            df.loc[df["sid"].isna(), "sid"] = df.loc[df["sid"].isna(), "isin"].map(isin_to_sid)
            n_matched = df["sid"].notna().sum()
            print(f"  ISIN→sid auto-matched: {n_matched} of {len(df)}")

    print(f"\nBreakdown by scheme:")
    print(df.groupby("scheme_code").size().to_string())

    if dry_run:
        print("\n--dry-run: not saving.")
        return 0

    rows = df[REQUIRED_COLS + OPTIONAL_COLS].to_records(index=False).tolist()
    with get_db() as conn:
        # PRIMARY KEY (scheme_code, as_of_date, holding_rank) — INSERT OR REPLACE
        cursor = conn.executemany(
            """INSERT OR REPLACE INTO mf_holdings
               (scheme_code, as_of_date, holding_rank, instrument_name, pct_of_aum,
                instrument_type, sid, isin, sector, market_value_cr)
               VALUES (?,?,?,?,?, ?,?,?,?,?)""",
            [tuple(r) for r in rows],
        )
        n_written = cursor.rowcount
    print(f"\nWrote {n_written} rows to mf_holdings")

    # Auto-populate sector_allocation from holdings (sum pct_of_aum by sector per scheme/date)
    with get_db() as conn:
        sectors = read_sql("""
            SELECT scheme_code, as_of_date, sector, SUM(pct_of_aum) AS pct_of_aum
            FROM mf_holdings
            WHERE sector IS NOT NULL
            GROUP BY scheme_code, as_of_date, sector
        """)
        if not sectors.empty:
            secs = sectors.to_records(index=False).tolist()
            conn.executemany(
                """INSERT OR REPLACE INTO mf_sector_allocation
                   (scheme_code, as_of_date, sector, pct_of_aum) VALUES (?,?,?,?)""",
                [tuple(r) for r in secs],
            )
            print(f"Updated mf_sector_allocation: {len(secs)} rows")

    return n_written


def status() -> None:
    """Report current state of holdings tables."""
    overall = read_sql("""
        SELECT COUNT(DISTINCT scheme_code) AS schemes_with_data,
               COUNT(*) AS total_rows,
               MIN(as_of_date) AS oldest,
               MAX(as_of_date) AS newest
        FROM mf_holdings
    """).iloc[0]
    print(f"mf_holdings: {overall['total_rows']} rows across {overall['schemes_with_data']} schemes")
    if overall['schemes_with_data']:
        print(f"  date range: {overall['oldest']} → {overall['newest']}")
    print()
    sectors = read_sql("SELECT COUNT(*) AS n FROM mf_sector_allocation").iloc[0]['n']
    print(f"mf_sector_allocation: {sectors} rows")


def compute() -> int:
    """No-op so this module can sit in PIPELINE_STEPS without breaking the pipeline.

    Returns 0 (nothing ingested by default — caller must use --csv flag explicitly).
    Pipeline step is informational only; until the AMFI scraper ships, this just
    reports the current state.
    """
    status()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv", help="Path to holdings CSV (see module docstring for format)")
    p.add_argument("--status", action="store_true", help="Report current ingest state")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.status or not args.csv:
        status()
    if args.csv:
        ingest_from_csv(args.csv, dry_run=args.dry_run)
