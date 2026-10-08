"""
MICRO-tier reclassifier (the daily tier step after scoring/segment.py).

A SMALL stock becomes MICRO when it is illiquid (90-day average traded value under
₹1 Cr/day) AND either small (market cap under ₹500 Cr) or has too little history to
trust (fewer than 4 knowable quarterly statements) — scoring.segment.carve on
pit.tier_inputs, the rule and inputs the backtest's point-in-time tiers use (ADR 0026).
MICRO stocks are EXCLUDED from daily_picks (scoring/screener.py); they remain visible in
the cockpit Explorer with a MICRO tag.

It also writes stocks.market_cap_cr (₹ crore) from the same market cap every day: the
column was a frozen April-2026 snapshot in rupees (work order 1), and the old MICRO
"mcap < 500" leg compared those rupees with crore, so it fired only for missing values.

Until 2026-10 the live rule also carved stocks with a Piotroski score ≤ 3 (read from the
unlagged piotroski_scores table) and counted standalone and consolidated quarters twice;
neither was in the tier definition the evidence was measured on.

Idempotent. Run nightly.

Usage:
    python -m tools.classify_micro_tier            # apply
    python -m tools.classify_micro_tier --dry-run  # preview
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TIERS
from db import get_db, read_sql
from scoring import segment

# The carve-out tier and the tier it is carved from (config.TIERS, ADR 0026). Runs
# AFTER the segment node (scoring/segment.py), which assigns LARGE/MID/SMALL and
# leaves this tier's members alone.
MICRO = next(t for t, spec in TIERS.items() if spec.get("carve_from"))
CARVE_FROM = TIERS[MICRO]["carve_from"]


def reclassify(dry_run: bool = False, as_of=None) -> int:
    """Apply the MICRO carve-out to today's SMALL/MICRO stocks and refresh
    stocks.market_cap_cr. Returns the number of MICRO stocks."""
    ti = segment.inputs(as_of)
    if len(ti) < 0.5 * len(read_sql("SELECT sid FROM stocks")):
        raise RuntimeError(f"classify_micro_tier: tier inputs for only {len(ti)} stocks — refusing to re-carve")
    stocks = read_sql("SELECT sid, cap_tier FROM stocks").set_index("sid")["cap_tier"]
    pool = stocks[stocks.isin([CARVE_FROM, MICRO])]
    # a stock with no tier inputs today (no recent close / statements) keeps its tier
    known = pool[pool.index.isin(ti["sid"])]
    new = segment.carve(pd.Series(CARVE_FROM, index=known.index), ti)
    to_micro = new[(new == MICRO) & (known != MICRO)].index.tolist()
    to_small = new[(new == CARVE_FROM) & (known == MICRO)].index.tolist()
    n_micro = int((new == MICRO).sum() + (pool[~pool.index.isin(ti["sid"])] == MICRO).sum())

    x = ti.set_index("sid").reindex(known.index)
    thin = x["adtv_cr"] < segment.MICRO_ADTV_CR
    print(f"MICRO rule: ADTV < ₹{segment.MICRO_ADTV_CR} Cr/day AND (mcap < ₹{segment.MICRO_MCAP_CR:.0f} Cr "
          f"OR < {segment.MICRO_MIN_QUARTERS} quarters)")
    print(f"  {n_micro} MICRO · {len(to_micro)} {CARVE_FROM} → {MICRO} · {len(to_small)} {MICRO} → {CARVE_FROM}")
    print(f"  legs among the illiquid: mcap < {segment.MICRO_MCAP_CR:.0f} Cr = {int((thin & (x['mcap_cr'] < segment.MICRO_MCAP_CR)).sum())}, "
          f"< {segment.MICRO_MIN_QUARTERS} quarters = {int((thin & (x['quarters'] < segment.MICRO_MIN_QUARTERS)).sum())}")
    if dry_run:
        print("DRY RUN — no DB changes")
        return n_micro

    with get_db() as conn:
        if to_small:
            conn.executemany("UPDATE stocks SET cap_tier = ? WHERE sid = ?", [(CARVE_FROM, s) for s in to_small])
        if to_micro:
            conn.executemany("UPDATE stocks SET cap_tier = ? WHERE sid = ?", [(MICRO, s) for s in to_micro])
        # ₹ crore, from the one market cap; a stock with none today gets NULL, not a stale value
        conn.execute("UPDATE stocks SET market_cap_cr = NULL")
        conn.executemany("UPDATE stocks SET market_cap_cr = ? WHERE sid = ?",
                         [(round(float(m), 2), s) for s, m in zip(ti["sid"], ti["mcap_cr"])])
    return n_micro


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    reclassify(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
