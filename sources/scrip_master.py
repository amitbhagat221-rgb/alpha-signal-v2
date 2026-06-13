"""
sources/scrip_master.py — BSE scrip_cd ↔ ISIN ↔ NSE ticker ↔ universe sid crosswalk.

Fills `bse_announcements.sid` (NULL by harvester design — the join is DEFERRED to this
static map; see sources/bse_announcements.py:22). Unblocks event-time PEAD + transcript
look-ahead wiring (checklist Next-3 #1).

WHY a separate map (not a join in the harvester): `stocks` has the NSE ticker but NO
ISIN, and BSE announcements carry only the numeric BSE scrip code. ISIN is the universal
bridge. One Upstox instrument-master file carries all three keys.

SOURCE — Upstox instrument master (assets.upstox.com CDN, no auth):
  - HARVESTER-SAFE: a DIFFERENT host from the BSE backend (api.bseindia.com), so it never
    competes with the running BSE harvester's IP-block surface.
  - BSE_EQ row: `exchange_token` == BSE scrip_cd; carries `isin`. (verified: Infosys → 500209)
  - NSE_EQ row: `trading_symbol` == NSE ticker (== stocks.ticker); carries `isin`. (→ INFY)
  → scrip_cd → isin → nse_symbol → stocks.sid.
Survivorship supplement (optional, non-fatal) — rohittihiro/BhavCopy_Equity_Database
`ListOfScrips.csv`: delisted/suspended scrip↔ISIN rows the live Upstox file drops. Adds no
sid (delisted ⇒ not in our current universe) but completes the map for non-universe event
studies.

Idempotent: INSERT OR REPLACE into `scrip_master` (PK=scrip_cd); then UPDATE
bse_announcements.sid from the map (only NULL-sid universe rows, so re-runs are cheap).
Re-run after the backfill completes to fill the older dates harvested later. Refresh weekly.

Usage:
    python -m sources.scrip_master              # build map + backfill bse_announcements.sid
    python -m sources.scrip_master --dry-run    # build map, report coverage, write nothing
    python -m sources.scrip_master --no-backfill # rebuild map only
"""
import argparse
import csv
import gzip
import io
import json
import sys
from datetime import datetime, timezone

import requests

from db import get_db, read_sql

UPSTOX_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
LISTOFSCRIPS_URL = (
    "https://raw.githubusercontent.com/rohittihiro/"
    "BhavCopy_Equity_Database/main/ListOfScrips.csv"
)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_table():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scrip_master (
                scrip_cd   INTEGER PRIMARY KEY,
                isin       TEXT,
                nse_symbol TEXT,
                sid        TEXT,
                name       TEXT,
                status     TEXT,
                source     TEXT,
                updated_at TEXT
            )
            """
        )


def fetch_upstox():
    """Parse the Upstox master into the maps we need.

    Returns:
      bse_scrips   {scrip_cd: (isin, name)}     — BSE_EQ row's exchange_token is the scrip code
      nse_sym2isin {nse_symbol: isin}           — NSE_EQ trading_symbol → isin
      bse_sym2isin {bse_symbol: isin}           — BSE_EQ trading_symbol → isin (catches BSE-primary names)
      nse_isin2sym {isin: nse_symbol}           — reverse, for the stored nse_symbol column
    """
    r = requests.get(UPSTOX_URL, timeout=120)
    r.raise_for_status()
    data = json.load(gzip.open(io.BytesIO(r.content)))
    bse_scrips, nse_sym2isin, bse_sym2isin, nse_isin2sym = {}, {}, {}, {}
    for row in data:
        seg = row.get("segment")
        isin = row.get("isin")
        ts = row.get("trading_symbol")
        if not isin:
            continue
        if seg == "BSE_EQ":
            tok = str(row.get("exchange_token") or "")
            if tok.isdigit():
                bse_scrips[int(tok)] = (isin, row.get("name"))
            if ts:
                bse_sym2isin.setdefault(ts, isin)
        elif seg == "NSE_EQ" and ts:
            nse_sym2isin.setdefault(ts, isin)
            nse_isin2sym.setdefault(isin, ts)
    if not bse_scrips or not nse_sym2isin:
        raise RuntimeError(
            f"Upstox parse yielded empty maps (bse={len(bse_scrips)}, "
            f"nse={len(nse_sym2isin)}) — field names or segments changed; do NOT write."
        )
    return bse_scrips, nse_sym2isin, bse_sym2isin, nse_isin2sym


def fetch_listofscrips():
    """Optional delisted supplement → {scrip_cd: (isin, name, status)}. Non-fatal."""
    try:
        r = requests.get(LISTOFSCRIPS_URL, timeout=60)
        r.raise_for_status()
        out = {}
        reader = csv.DictReader(io.StringIO(r.text))
        for row in reader:
            code = (row.get("Security Code") or "").strip()
            isin = (row.get("ISIN No") or "").strip()
            if not code.isdigit() or not isin:
                continue
            out[int(code)] = (isin, (row.get("Security Name") or "").strip(),
                              (row.get("Status") or "").strip())
        return out
    except Exception as e:  # noqa: BLE001 — supplement only
        print(f"  [warn] ListOfScrips supplement unavailable ({e}); continuing Upstox-only")
        return {}


def build_rows():
    bse_scrips, nse_sym2isin, bse_sym2isin, nse_isin2sym = fetch_upstox()
    los = fetch_listofscrips()

    # ISIN-centric: resolve each universe stock's ISIN via its NSE ticker, falling back to
    # its BSE trading symbol (catches BSE-primary names). Then a BSE scrip maps to a sid
    # purely by ISIN — no dependence on the scrip's NSE symbol matching our ticker exactly.
    isin2sid = {}
    for sid, ticker in read_sql("SELECT sid, ticker FROM stocks").itertuples(index=False, name=None):
        isin = nse_sym2isin.get(ticker) or bse_sym2isin.get(ticker)
        if isin:
            isin2sid.setdefault(isin, sid)

    rows, now, seen = [], _now(), set()
    for scrip_cd, (isin, name) in bse_scrips.items():
        rows.append((scrip_cd, isin, nse_isin2sym.get(isin), isin2sid.get(isin),
                     name, "Active", "upstox", now))
        seen.add(scrip_cd)
    # Supplement: delisted/suspended scrips not in the live file (isin only, no sid)
    for scrip_cd, (isin, name, status) in los.items():
        if scrip_cd in seen:
            continue
        rows.append((scrip_cd, isin, None, isin2sid.get(isin), name,
                     status or "Delisted", "listofscrips", now))
    return rows


def store(rows):
    sql = (
        "INSERT OR REPLACE INTO scrip_master "
        "(scrip_cd, isin, nse_symbol, sid, name, status, source, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)"
    )
    with get_db() as conn:
        conn.executemany(sql, rows)


def backfill_bse():
    """Fill bse_announcements.sid from the map (only NULL-sid universe rows)."""
    with get_db() as conn:
        before = conn.total_changes
        conn.execute(
            """
            UPDATE bse_announcements
               SET sid = (SELECT sm.sid FROM scrip_master sm
                           WHERE sm.scrip_cd = bse_announcements.scrip_cd)
             WHERE sid IS NULL
               AND scrip_cd IN (SELECT scrip_cd FROM scrip_master WHERE sid IS NOT NULL)
            """
        )
        return conn.total_changes - before


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--dry-run", action="store_true", help="build + report, write nothing")
    ap.add_argument("--no-backfill", action="store_true", help="rebuild map only, skip bse update")
    args = ap.parse_args()

    _ensure_table()
    rows = build_rows()
    n_with_sid = sum(1 for r in rows if r[3])
    n_distinct_sid = len({r[3] for r in rows if r[3]})
    n_universe = len(read_sql("SELECT sid FROM stocks"))
    print(f"scrip_master: {len(rows)} scrips mapped · {n_with_sid} scrips carry a sid · "
          f"{n_distinct_sid}/{n_universe} = {100*n_distinct_sid/n_universe:.1f}% of universe reached")

    # spot-check the recipe on three known names
    spot = {r[0]: r for r in rows}
    for code, want in [(500209, "INFY"), (500325, "RELIANCE"), (500180, "HDFCBANK")]:
        r = spot.get(code)
        print(f"  spot {code}: nse={r[2] if r else None} sid={r[3] if r else None} "
              f"(expect nse≈{want})")

    if args.dry_run:
        print("[dry-run] nothing written.")
        return

    store(rows)
    print(f"  wrote {len(rows)} rows to scrip_master.")
    if not args.no_backfill:
        n = backfill_bse()
        cov = read_sql(
            "SELECT COUNT(*) tot, SUM(sid IS NOT NULL) with_sid FROM bse_announcements"
        ).iloc[0]
        print(f"  backfilled bse_announcements.sid: {n} rows updated this run · "
              f"{int(cov['with_sid'])}/{int(cov['tot'])} "
              f"({100*cov['with_sid']/cov['tot']:.1f}%) now carry a sid.")
        print("  NOTE: re-run after the backfill harvester finishes to fill older dates.")


if __name__ == "__main__":
    main()
