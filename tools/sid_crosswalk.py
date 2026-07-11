"""
Alpha Signal v2 — tools/sid_crosswalk.py — bse_announcements.scrip_cd -> sid map (plan 0013 A2).

Read-only. Research 0003 found event sid-mapping ~53% via the raw `bse_announcements.sid`
column, halving usable event-study n. This helper builds the best available in-house
scrip_cd -> sid map so A3 (event_calendar) can recover events the raw column misses.

Primary source: `scrip_master` (sources/scrip_master.py's Upstox-derived BSE crosswalk,
scrip_cd -> isin -> nse_symbol -> sid). Fallback: for any scrip_cd `scrip_master` doesn't
map to a sid, fall back to the populated (scrip_cd, sid) pairs already sitting in
`bse_announcements` itself (a scrip_cd can appear on many rows; per-scrip_cd sid is
consistent in-DB — verified no scrip_cd carries two different non-NULL sids).

Live finding (2026-07-11): `sources/scrip_master.py` already backfills
`bse_announcements.sid` from this same map on every run (its own docstring), so
`scrip_master` alone does NOT meaningfully out-cover the raw `sid` column anymore —
the coverage lift here is small (few extra scrip_cd where `scrip_master` has the
scrip_cd row but a NULL sid, while the raw column was filled some other way). The
~53%-mapped research-0003 finding does not reproduce against the current in-house
crosswalk; the binding constraint on event usable-n is the scrip_cd itself being
absent from `scrip_master`/BSE, not this table's freshness. See coverage report below.

Usage:
    python -m tools.sid_crosswalk       # coverage report
    from tools.sid_crosswalk import scrip_cd_to_sid
"""
from __future__ import annotations

from db import read_sql


def scrip_cd_to_sid() -> dict[int, str]:
    """scrip_cd -> sid map. scrip_master primary; bse_announcements' own populated
    pairs fill any gap scrip_master leaves. Read-only; writes nothing."""
    m: dict[int, str] = {}
    sm = read_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='scrip_master'")
    if len(sm):
        rows = read_sql("SELECT scrip_cd, sid FROM scrip_master WHERE sid IS NOT NULL")
        m.update(dict(zip(rows["scrip_cd"], rows["sid"])))

    fallback = read_sql(
        "SELECT DISTINCT scrip_cd, sid FROM bse_announcements WHERE sid IS NOT NULL")
    for scrip_cd, sid in zip(fallback["scrip_cd"], fallback["sid"]):
        m.setdefault(scrip_cd, sid)
    return m


def _coverage_report() -> None:
    raw = read_sql(
        "SELECT COUNT(DISTINCT sid) n FROM bse_announcements WHERE sid IS NOT NULL")["n"][0]
    unmapped_scrip_cds = read_sql(
        "SELECT COUNT(DISTINCT scrip_cd) n FROM bse_announcements WHERE sid IS NULL")["n"][0]
    m = scrip_cd_to_sid()

    null_rows = read_sql("SELECT DISTINCT scrip_cd FROM bse_announcements WHERE sid IS NULL")
    newly_mapped = sum(1 for c in null_rows["scrip_cd"] if c in m)

    print(f"scrip_cd_to_sid(): {len(m):,} scrip_cd -> sid entries")
    print(f"raw bse_announcements.sid: {raw:,} distinct non-NULL sid")
    print(f"NULL-sid scrip_cd in bse_announcements: {unmapped_scrip_cds:,}; "
          f"newly mappable via this helper: {newly_mapped:,}")


if __name__ == "__main__":
    _coverage_report()
