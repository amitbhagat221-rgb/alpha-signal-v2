"""
Alpha Signal v2 — Daily MF NAV ingest from AMFI NAVAll.txt.

Single HTTP, <2s runtime, all ~14,000 schemes in one shot. The same
NAVAll.txt file that feeds the scheme master (sources/mf_amfi_master.py)
also carries today's NAV per scheme. Reuses `parse_navall()` from that
module to avoid duplicating parser logic.

Idempotent: PK on `mf_nav_history (scheme_code, nav_date)` means re-runs
the same day insert 0 rows. Holidays/weekends: AMFI still publishes the
file but with the prior business day's NAV — `INSERT OR IGNORE` handles
the repeat gracefully.

Wired into `PIPELINE_STEPS` as `fetch_mf_nav_daily` (frequency: daily).

Gap repair: AMFI's NAV-history report returns EVERY scheme for a date range in
one request (portal.amfiindia.com, ~1.2 MB/day), so a missed stretch is a few
calls — not a per-scheme mfapi.in crawl. (2026-08-19 → 09-26 was lost that way:
AMFI added Plan;Option columns and the fixed-index parser read "Direct Plan" as NAV.)

Usage:
    python -m sources.mf_nav_daily               # daily refresh
    python -m sources.mf_nav_daily --dry-run     # parse + report only
    python -m sources.mf_nav_daily --from 2026-08-19 --to 2026-09-24   # gap repair
"""

import argparse
from datetime import date, datetime, timedelta

import pandas as pd


from db import get_db, read_sql
from sources import _http
from sources.mf_amfi_master import _parse_date, fetch_navall_text, parse_navall

NAV_HISTORY_URL = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"
HISTORY_CHUNK_DAYS = 7


def compute(dry_run: bool = False) -> int:
    """Pull today's NAVs from NAVAll.txt; insert into mf_nav_history."""
    print(f"Fetching NAVAll.txt for today's NAVs…")
    text = fetch_navall_text()
    rows = parse_navall(text)
    print(f"Parsed {len(rows)} scheme rows from AMFI")

    # Keep only rows that have BOTH a numeric NAV AND a parseable date.
    # Some closed-ended / wound-down schemes show their last known NAV with
    # an old date — those are not "today's NAV", skip them at the daily-fetch
    # layer (mf_amfi_master keeps the master entry).
    nav_rows = [
        {"scheme_code": r["scheme_code"], "nav_date": r["nav_date"], "nav": r["nav"]}
        for r in rows
        if r["nav"] is not None and r["nav_date"] is not None
    ]
    print(f"  {len(nav_rows)} have non-null NAV + date")

    if not nav_rows:
        raise RuntimeError("Parsed 0 usable NAV rows — file format may have changed")

    nav_dates = pd.Series([r["nav_date"] for r in nav_rows]).value_counts().head(3)
    print(f"  NAV date distribution (top 3): {dict(nav_dates)}")

    if dry_run:
        print("--dry-run: not saving.")
        return len(nav_rows)

    # INSERT OR IGNORE — re-runs and holiday re-fetches are no-ops on the PK.
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.executemany(
            "INSERT OR IGNORE INTO mf_nav_history (scheme_code, nav_date, nav, fetched_at) "
            "VALUES (?, ?, ?, ?)",
            [(r["scheme_code"], r["nav_date"], r["nav"], now) for r in nav_rows],
        )
        n_new = cursor.rowcount

    print(f"\nInserted {n_new} new NAV rows ({len(nav_rows) - n_new} already-present skipped)")

    # Print a couple of post-state stats
    summary = read_sql("""
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT scheme_code) AS distinct_schemes,
            MIN(nav_date) AS oldest,
            MAX(nav_date) AS latest
        FROM mf_nav_history
    """).iloc[0]
    print(f"mf_nav_history: {summary['total_rows']:,} rows · "
          f"{summary['distinct_schemes']:,} schemes · "
          f"{summary['oldest']} → {summary['latest']}")

    return n_new


def parse_nav_history(text: str) -> list[tuple]:
    """(scheme_code, nav_date, nav) rows from the NAV-history report. Columns are
    located from its header (Scheme Code;NAV Name;Plan;Option;…;Net Asset Value;Date)."""
    out, col = [], None
    for line in text.splitlines():
        if line.startswith("Scheme Code"):
            hdr = [h.strip().lower() for h in line.split(";")]
            col = (hdr.index("scheme code"), hdr.index("net asset value"), hdr.index("date"))
            continue
        if col is None or ";" not in line:
            continue
        parts = line.split(";")
        if len(parts) <= max(col):
            continue
        code, nav_raw, dt = (parts[i].strip() for i in col)
        if not code.isdigit():
            continue
        try:
            nav = float(nav_raw)
        except ValueError:
            continue
        nav_date = _parse_date(dt)
        if nav_date:
            out.append((code, nav_date, nav))
    return out


def backfill_range(start: date, end: date, dry_run: bool = False) -> int:
    """Insert every scheme's NAV for [start, end] from AMFI's history report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total, d = 0, start
    while d <= end:
        chunk_end = min(d + timedelta(days=HISTORY_CHUNK_DAYS - 1), end)
        r = _http.polite_get(NAV_HISTORY_URL, timeout=120, params={
            "frmdt": d.strftime("%d-%b-%Y"), "todt": chunk_end.strftime("%d-%b-%Y")})
        rows = parse_nav_history(r.text) if r is not None else []
        n_dates = len({x[1] for x in rows})
        if dry_run:
            n = len(rows)
        else:
            with get_db() as conn:
                n = conn.executemany(
                    "INSERT OR IGNORE INTO mf_nav_history (scheme_code, nav_date, nav, fetched_at) "
                    "VALUES (?, ?, ?, ?)", [(*x, now) for x in rows]).rowcount
        print(f"  {d} → {chunk_end}: {len(rows)} rows over {n_dates} NAV dates, "
              f"{n} {'parsed' if dry_run else 'new'}", flush=True)
        total += n
        d = chunk_end + timedelta(days=1)
    if total == 0 and not dry_run and (end - start).days >= 3:
        raise RuntimeError(f"AMFI NAV history returned no new rows for {start} → {end}")
    return total


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--from", dest="frm", help="gap repair start YYYY-MM-DD (AMFI history report)")
    p.add_argument("--to", dest="to", help="gap repair end YYYY-MM-DD (default today)")
    args = p.parse_args()
    if args.frm:
        end = date.fromisoformat(args.to) if args.to else date.today()
        backfill_range(date.fromisoformat(args.frm), end, dry_run=args.dry_run)
    else:
        compute(dry_run=args.dry_run)
