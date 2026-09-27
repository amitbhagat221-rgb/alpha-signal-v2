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

Rate limit: ≥2s/call per CLAUDE.md (polite_get; was 0.5s) — mfapi.in is a free
community service. Expected runtime for ~5,000 Growth schemes ≈ 3h. Run in background.

Idempotent: re-runs skip schemes already marked `has_full_history=1`. INSERT
OR IGNORE on `mf_nav_history` covers the within-scheme retry case.

Usage:
    python -m sources.mf_nav_backfill                  # full Growth backfill
    python -m sources.mf_nav_backfill --limit 20       # smoke test 20 schemes
    python -m sources.mf_nav_backfill --include-idcw   # add IDCW variants too
    python -m sources.mf_nav_backfill --scheme 122639  # single scheme
"""

import argparse
import time
from datetime import datetime


from db import get_db, read_sql
from sources._http import polite_get, run_harvester

MFAPI_URL = "https://api.mfapi.in/mf/{code}"


def fetch_scheme_history(scheme_code: str) -> dict | None:
    """GET mfapi.in/mf/{code} → {meta, data}. None on 404/410; raises once
    polite_get's retries (timeouts / 429 / 5xx) are spent."""
    r = polite_get(MFAPI_URL.format(code=scheme_code))
    return r.json() if r is not None else None


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

    t0 = time.time()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def fetch(code):
        payload = fetch_scheme_history(code)
        rows = _parse_nav_rows(code, payload) if payload and payload.get("data") else []
        if not rows:
            return []
        meta = payload.get("meta", {}) or {}
        name = meta.get("scheme_name") or ""
        # Inception date (earliest nav_date) goes to mf_schemes alongside the NAVs.
        scheme = (code, meta.get("scheme_name"), meta.get("fund_house"), meta.get("scheme_type"),
                  _detect_plan(name), _detect_option(name), min(r[1] for r in rows), now)
        return [("nav", r) for r in rows] + [("scheme", scheme)]

    def write(tagged):
        # NAV rows and the has_full_history=1 mark land in ONE transaction, so a
        # crash can never flag a scheme done without its history.
        with get_db() as conn:
            inserted = conn.executemany(
                "INSERT OR IGNORE INTO mf_nav_history "
                "(scheme_code, nav_date, nav, fetched_at) VALUES (?,?,?,?)",
                [(c, d, n, now) for kind, (c, d, n, *_) in tagged if kind == "nav"],
            ).rowcount
            conn.executemany(
                """INSERT INTO mf_schemes
                    (scheme_code, scheme_name, fund_house, scheme_type,
                     direct_or_regular, growth_or_dividend, is_top50,
                     inception_date, has_full_history, fetched_at)
                   VALUES (?,?,?,?,?,?,0,?,1,?)
                   ON CONFLICT(scheme_code) DO UPDATE SET
                     inception_date = excluded.inception_date,
                     has_full_history = 1,
                     fetched_at = excluded.fetched_at""",
                [v for kind, v in tagged if kind == "scheme"],
            )
        return inserted

    # Errors are counted + logged by run_harvester, which RAISES if no scheme
    # returned any NAV history (mfapi.in down / blocked).
    n_success, n_err, total_rows = run_harvester(target_codes, fetch, write, flush_every=50,
                                                 label="mfapi NAV backfill")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed/60:.1f}min.")
    print(f"  schemes: {n_success} success · {len(target_codes) - n_success - n_err} no_data · {n_err} error")
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
