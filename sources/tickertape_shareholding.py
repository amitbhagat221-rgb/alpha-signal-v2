"""
Alpha Signal v2 — Tickertape Shareholding Pattern

Ports the shareholding chunk of v1's 22_data_harvester.py. Uses the same
Bharat_sm_data Tickertape client that v2's sources/tickertape.py uses for
fundamentals (so we get the same auth + cookie path automatically).

Writes:
    shareholding — PK (sid, end_date). One row per quarter per stock with
                   promoter %, FII, DII, MF, insurance, retail/HNI, public,
                   pledge %.

Reads:
    stocks.slug — Tickertape slug (e.g. "stocks/reliance-industries-RELI").

Tickertape field map (from get_share_holding_pattern):
    date            — Quarter end date (ISO)
    data_pmPctT     — Promoter holding % (total)
    data_pmPctP     — Promoter pledged %
    data_plPctT     — Public holding %
    data_mfPctT     — Mutual fund %
    data_isPctT     — Insurance %
    data_diPctT     — DII %
    data_fiPctT     — FII %
    data_rhPctT     — Retail / HNI %
    data_othPctT    — Other %

Usage:
    python -m sources.tickertape_shareholding              # full refresh
    python -m sources.tickertape_shareholding --limit 3    # smoke test
    python -m sources.tickertape_shareholding --dry-run
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# v2's tickertape.py adds v1 scripts path for the Bharat_sm_data library.
sys.path.insert(0, str(Path.home() / "alpha-signal" / "scripts"))

from config import API
from db import read_sql, upsert_df

DELAY = API["tickertape_delay"]


def _get_client():
    from Fundamentals.TickerTape import Tickertape
    return Tickertape()


_OUT_OF_RANGE_LOG: list = []  # populated per-run; surfaced in summary
_CLAMP_TOLERANCE = 0.05  # percentage points — wider than empirical max drift seen


def _normalise(value, *, sid=None, col=None, end_date=None):
    """Coerce pandas/numpy types to plain Python so sqlite3 doesn't trip on numpy scalars.

    Tickertape derives `data_othPctT` as `100 - sum(other categories)`. Empirically:
    - Most rounding drift is ±1e-15 (snap silently).
    - Occasional drift up to ±0.01 pp (snap silently — still data-faithful).
    - Genuine outliers > ±0.05 pp (drop the column, log it — better than failing the whole row).
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if -_CLAMP_TOLERANCE <= v < 0:
        return 0.0
    if 100 < v <= 100 + _CLAMP_TOLERANCE:
        return 100.0
    if v < 0 or v > 100:
        _OUT_OF_RANGE_LOG.append({"sid": sid, "col": col, "end_date": end_date, "value": v})
        return None
    return v


def compute(limit=None, dry_run=False):
    """Pipeline entry point — fetch shareholding pattern for all sids with a slug."""
    stocks = read_sql(
        "SELECT sid, slug FROM stocks WHERE slug IS NOT NULL AND slug LIKE 'stocks/%' ORDER BY sid"
    )
    if limit:
        stocks = stocks.head(limit)

    total = len(stocks)
    print(f"Tickertape Shareholding: {total} stocks")

    if dry_run:
        print(f"  Estimated time: ~{total * DELAY / 60:.0f} min ({DELAY}s × {total} stocks)")
        return 0

    client = _get_client()
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    saved = 0
    errors = 0
    no_data = 0

    for i, (sid, slug) in enumerate(stocks.itertuples(index=False), 1):
        try:
            sh = client.get_share_holding_pattern(slug)
        except Exception:
            errors += 1
            time.sleep(DELAY)
            continue

        if sh is None or len(sh) == 0:
            no_data += 1
            time.sleep(DELAY)
            continue

        for _, r in sh.iterrows():
            raw_date = str(r.get("date", ""))
            end_date = raw_date[:10] if raw_date else None
            if not end_date or end_date.startswith("1899"):
                # Tickertape sometimes returns a sentinel 1899-12-31 — drop.
                continue
            rows.append({
                "sid": sid,
                "end_date": end_date,
                "promoter_pct": _normalise(r.get("data_pmPctT"), sid=sid, col="promoter_pct", end_date=end_date),
                "fii_pct": _normalise(r.get("data_fiPctT"), sid=sid, col="fii_pct", end_date=end_date),
                "mf_pct": _normalise(r.get("data_mfPctT"), sid=sid, col="mf_pct", end_date=end_date),
                "dii_pct": _normalise(r.get("data_diPctT"), sid=sid, col="dii_pct", end_date=end_date),
                "public_pct": _normalise(r.get("data_plPctT"), sid=sid, col="public_pct", end_date=end_date),
                "pledge_pct": _normalise(r.get("data_pmPctP"), sid=sid, col="pledge_pct", end_date=end_date),
                "insurance_pct": _normalise(r.get("data_isPctT"), sid=sid, col="insurance_pct", end_date=end_date),
                "retail_hni_pct": _normalise(r.get("data_rhPctT"), sid=sid, col="retail_hni_pct", end_date=end_date),
                "other_pct": _normalise(r.get("data_othPctT"), sid=sid, col="other_pct", end_date=end_date),
                "fetched_at": fetched_at,
            })

        if i % 200 == 0:
            if rows:
                upsert_df(pd.DataFrame(rows), "shareholding")
                saved += len(rows)
                rows = []
            print(f"  [{i}/{total}] {saved} rows saved")

        time.sleep(DELAY)

    if rows:
        upsert_df(pd.DataFrame(rows), "shareholding")
        saved += len(rows)

    oor = len(_OUT_OF_RANGE_LOG)
    print(f"Done: {saved} rows. No data: {no_data}. Errors: {errors}. Out-of-range values dropped: {oor}.")
    if oor:
        sample = _OUT_OF_RANGE_LOG[:5]
        print(f"  Sample: {sample}")
    return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Limit to first N stocks (smoke test)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(limit=args.limit, dry_run=args.dry_run)
