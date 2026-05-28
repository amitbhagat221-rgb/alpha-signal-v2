"""
Alpha Signal v2 — Historical MF NAV backfill via mfapi.in.

One-off bootstrap script that fills `mf_nav_history` with the full multi-year
NAV time series for every scheme. AMFI's NAVAll.txt only gives today's NAV;
mfapi.in (community-run JSON wrapper) gives the complete history per scheme
back to inception (typically 10-15 years for older funds).

Selectivity:
  - Default: schemes where mf_scheme_master.active=1 AND option_type='GROWTH'
    AND has_full_history=0 (in mf_schemes). Skips already-done + IDCW variants.
  - --include-idcw: also backfill IDCW variants (doubles the volume; their NAV
    is meaningfully different due to dividend distributions, so worth doing in v2).
  - --limit N: cap to first N schemes for smoke-testing.

Rate limit: 0.5s/call by design — mfapi.in is a free community service. Total
expected runtime for ~5,000 Growth schemes ≈ 42 min. Run in background.

Idempotent: re-runs skip schemes already marked `has_full_history=1`. INSERT
OR IGNORE on `mf_nav_history` covers the within-scheme retry case.

Usage:
    python -m sources.mf_nav_backfill                  # full Growth backfill
    python -m sources.mf_nav_backfill --limit 20       # smoke test 20 schemes
    python -m sources.mf_nav_backfill --include-idcw   # add IDCW variants too
    python -m sources.mf_nav_backfill --scheme 122639  # single scheme
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import get_db, read_sql, upsert_df

MFAPI_URL = "https://api.mfapi.in/mf/{code}"
DELAY = 0.5         # be polite to free service
TIMEOUT = 15
MAX_RETRIES = 2
HEADERS = {"User-Agent": "Mozilla/5.0 alpha-signal-v2/1.0"}


def fetch_scheme_history(scheme_code: str) -> dict | None:
    """GET mfapi.in/mf/{code} → {meta, data}. Returns None on permanent failure."""
    url = MFAPI_URL.format(code=scheme_code)
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (404, 410):
                return None
        except requests.RequestException:
            pass
        time.sleep(2)
    return None


def _parse_nav_rows(scheme_code: str, payload: dict) -> list[tuple]:
    """mfapi.in returns date as 'DD-MM-YYYY'. Convert to ISO; return (code, iso, nav)."""
    rows = []
    for entry in payload.get("data", []):
        d_raw = entry.get("date", "")
        nav_raw = entry.get("nav", "")
        try:
            iso = datetime.strptime(d_raw, "%d-%m-%Y").date().isoformat()
            nav = float(nav_raw)
        except (ValueError, TypeError):
            continue
        rows.append((scheme_code, iso, nav))
    return rows


def compute(limit: int | None = None,
            include_idcw: bool = False,
            scheme: str | None = None) -> int:
    """Backfill historical NAVs. Returns total rows written across all schemes."""
    # Universe selection
    if scheme:
        target_codes = [scheme]
        print(f"Single-scheme mode: {scheme}")
    else:
        opts = ("GROWTH",) if not include_idcw else ("GROWTH", "IDCW")
        ph = ",".join("?" * len(opts))
        # Subquery: schemes NOT already marked has_full_history=1 in mf_schemes
        already_done = set(read_sql(
            "SELECT scheme_code FROM mf_schemes WHERE has_full_history=1"
        )["scheme_code"].tolist())
        target_df = read_sql(
            f"""SELECT scheme_code FROM mf_scheme_master
                WHERE active = 1 AND option_type IN ({ph})
                ORDER BY scheme_code""",
            params=list(opts),
        )
        target_codes = [c for c in target_df["scheme_code"] if c not in already_done]
        if limit:
            target_codes = target_codes[:limit]
        print(f"Target universe: {len(target_codes)} schemes "
              f"(options={opts}, skipping {len(already_done)} already done)")

    total_rows = 0
    n_success = 0
    n_no_data = 0
    n_err = 0
    n_inception_filled = 0

    t0 = time.time()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for i, code in enumerate(target_codes, 1):
        payload = fetch_scheme_history(code)
        if payload is None:
            n_err += 1
        elif not payload.get("data"):
            n_no_data += 1
        else:
            rows = _parse_nav_rows(code, payload)
            if rows:
                with get_db() as conn:
                    cursor = conn.executemany(
                        "INSERT OR IGNORE INTO mf_nav_history "
                        "(scheme_code, nav_date, nav, fetched_at) VALUES (?,?,?,?)",
                        [(c, d, n, now) for c, d, n in rows],
                    )
                    inserted = cursor.rowcount
                total_rows += inserted

                # Capture inception date (earliest nav_date) into mf_schemes
                inception = min(r[1] for r in rows)
                meta = payload.get("meta", {}) or {}
                with get_db() as conn:
                    conn.execute(
                        """INSERT INTO mf_schemes
                            (scheme_code, scheme_name, fund_house, scheme_type,
                             direct_or_regular, growth_or_dividend, is_top50,
                             inception_date, has_full_history, fetched_at)
                           VALUES (?,?,?,?,?,?,0,?,1,?)
                           ON CONFLICT(scheme_code) DO UPDATE SET
                             inception_date = excluded.inception_date,
                             has_full_history = 1,
                             fetched_at = excluded.fetched_at""",
                        (code,
                         meta.get("scheme_name"),
                         meta.get("fund_house"),
                         meta.get("scheme_type"),
                         _detect_plan(meta.get("scheme_name") or ""),
                         _detect_option(meta.get("scheme_name") or ""),
                         inception, now),
                    )
                n_inception_filled += 1
                n_success += 1
            else:
                n_no_data += 1

        if i % 50 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed
            eta_min = (len(target_codes) - i) / rate / 60 if rate > 0 else 0
            print(f"  [{i}/{len(target_codes)}]  success={n_success} no_data={n_no_data} "
                  f"err={n_err}  rows={total_rows:,}  rate={rate:.1f}/s  ETA={eta_min:.1f}min",
                  flush=True)

        time.sleep(DELAY)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed/60:.1f}min.")
    print(f"  schemes: {n_success} success · {n_no_data} no_data · {n_err} error")
    print(f"  rows: {total_rows:,} new")
    return total_rows


# Plan/option helpers (kept simple — match against scheme name string)


def _detect_plan(name: str) -> str:
    name_lower = (name or "").lower()
    if "direct" in name_lower:
        return "Direct"
    if "regular" in name_lower or "retail" in name_lower:
        return "Regular"
    return None


def _detect_option(name: str) -> str:
    name_lower = (name or "").lower()
    if "idcw" in name_lower or "dividend" in name_lower:
        return "IDCW"
    if "growth" in name_lower:
        return "Growth"
    return None


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, help="Stop after N schemes (smoke test)")
    p.add_argument("--include-idcw", action="store_true",
                   help="Also backfill IDCW variants (doubles volume)")
    p.add_argument("--scheme", help="Single scheme code (smoke test)")
    args = p.parse_args()
    compute(limit=args.limit, include_idcw=args.include_idcw, scheme=args.scheme)
