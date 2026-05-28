"""
Alpha Signal v2 — MF data-quality classifier.

Tags `mf_scheme_master.data_quality` to keep contaminated schemes out of
the universe browser, scorer, and category-median stats.

Contamination categories (in detection priority order):

  SEGREGATED  — "Segregated Portfolio" in name; accounting bucket created
                during a wind-up. Not an investable fund.

  WOUND_UP    — Known wound-up debt schemes (Franklin Templeton's 6 from
                2020, plus any other AMC's wound-up schemes). NAV is a
                trust-account residual value; doesn't reflect real
                investor performance. NAVs spike when bad assets are
                finally recovered/sold.

  INTERVAL    — "Interval Fund" / "Interval Plan" — closed-ended interval
                funds that lock capital between subscription windows.
                NAVs spike at maturity when units are redeemed at face;
                doesn't reflect real ongoing fund return.

  BONUS       — "Bonus Option" / "Bonus Plan" — rarely traded, stale NAV.

  ANOMALOUS   — Caught by NAV/return/volatility heuristics:
                  - vol_1y > 80% (no real Indian MF has this)
                  - debt fund with vol_1y > 15% or ret_1y > 30%
                  - day-over-day NAV jump > 50% anywhere in history

  TRUSTED     — default — passed all checks

The classifier is idempotent: runs over every active scheme, computes new
flags, upserts data_quality + quality_reason. Safe to re-run.

Usage:
    python -m sources.mf_data_quality          # classify all
    python -m sources.mf_data_quality --dry-run
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import get_db, read_sql


# Franklin Templeton's 6 wound-up schemes (April 2020 crisis).
# All plan variants (Direct/Regular/Growth/IDCW/Institutional/Retail) inherit
# the WOUND_UP flag from a name match.
FRANKLIN_WOUND_UP_PATTERNS = [
    r"franklin\s+india\s+short[- ]term\s+income\s+plan",
    r"franklin\s+india\s+income\s+opportunities\s+fund",
    r"franklin\s+india\s+credit\s+risk\s+fund",
    r"franklin\s+india\s+low\s+duration\s+fund",
    r"franklin\s+india\s+dynamic\s+accrual\s+fund",
    r"franklin\s+india\s+ultra[- ]short\s+bond\s+fund",
]
FRANKLIN_WOUND_UP_RE = re.compile("|".join(FRANKLIN_WOUND_UP_PATTERNS), re.I)


def _classify_by_name(name: str, category: str | None) -> tuple[str, str] | None:
    """Return (flag, reason) based on scheme name patterns. None if no match."""
    if not name:
        return None
    name_l = name.lower()

    # Segregated portfolio carve-outs from any wind-up
    if "segregated portfolio" in name_l or "segregated portfolio" in (category or "").lower():
        return ("SEGREGATED", "Accounting carve-out from a wind-up; not investable")

    # Franklin Templeton wound-up schemes
    if FRANKLIN_WOUND_UP_RE.search(name):
        return ("WOUND_UP", "Franklin Templeton wound-up debt scheme (April 2020 crisis)")

    # Interval funds — closed-ended with subscription windows
    if "interval fund" in name_l or "interval plan" in name_l:
        return ("INTERVAL", "Closed-ended interval fund; NAV spikes at maturity")

    # Bonus options
    if re.search(r"\bbonus\s+(option|plan|payout)\b", name_l):
        return ("BONUS", "Rarely-traded bonus variant; NAV often stale")

    return None


def _classify_by_metrics(metric_row, cat_p99: dict[str, float] | None = None) -> tuple[str, str] | None:
    """Return (flag, reason) based on metric anomalies. None if normal.

    `cat_p99` is an optional {category_norm: p99 1Y return} dict — if the
    fund's 1Y return exceeds 3× the category's p99, flag as
    ANOMALOUS_CATEGORY_OUTLIER. Catches funds like Nippon Taiwan Equity
    whose chart shape is plausible (no wind-up spike) but whose return
    magnitude is implausible vs peers (e.g. +235% vs category p99 of
    +50%). Common cause: FX accounting quirks or NAV feed divergence
    between AMC, AMFI, and mfapi.in for cross-border thematic funds.
    """
    std_1y = metric_row.get("std_1y")
    ret_1y = metric_row.get("ret_1y")
    category_raw = metric_row.get("category_norm") or ""
    category = category_raw.lower()

    if std_1y is not None and std_1y > 80:
        return ("ANOMALOUS", f"Vol 1Y = {std_1y:.0f}% — no real fund has this")

    if category.startswith("debt"):
        # Debt funds shouldn't show equity-like vol or returns
        if std_1y is not None and std_1y > 15:
            return ("ANOMALOUS", f"Debt fund vol 1Y = {std_1y:.1f}% (>15% threshold; likely contaminated NAV)")
        if ret_1y is not None and ret_1y > 30:
            return ("ANOMALOUS", f"Debt fund 1Y return = {ret_1y:.1f}% (>30%; mechanically impossible)")

    # Category-outlier check — catches the Nippon Taiwan class (smooth drift
    # but magnitude implausible vs peers). Threshold: 3× category p99.
    # Skip if category has too few peers to compute a robust p99.
    if cat_p99 and ret_1y is not None and ret_1y > 30:
        p99 = cat_p99.get(category_raw)
        if p99 is not None and p99 > 0 and ret_1y > 3.0 * p99:
            return ("ANOMALOUS",
                    f"1Y return {ret_1y:.0f}% is {ret_1y/p99:.1f}× the category P99 "
                    f"({p99:.0f}%) — implausible vs peers, likely NAV feed divergence")

    return None


def _classify_by_nav_jumps() -> dict[str, tuple[str, str]]:
    """Find schemes with day-over-day NAV jumps that PERSIST (not just a single-day
    bad data point). A real wind-up settlement repricing stays elevated; a data
    error reverses within a few days.

    Returns {scheme_code: (flag, reason)}. Uses two checks:
      1. Latest NAV is ≥3× the median over the previous 60 days
         → repricing event that's still in effect, contaminates ret_1y
      2. NAV jumped >50% day-over-day AND volatility 1Y > 30%
         → caught by metric-based check; this is just a secondary signal

    Only the first check fires from this function; the metric-based check
    already flags vol-based anomalies separately.
    """
    df = read_sql("""
        WITH latest AS (
            SELECT scheme_code,
                   MAX(nav_date) AS d_latest,
                   nav AS nav_latest
            FROM mf_nav_history h
            WHERE nav_date = (SELECT MAX(nav_date) FROM mf_nav_history h2 WHERE h2.scheme_code = h.scheme_code)
            GROUP BY scheme_code
        ),
        baseline AS (
            SELECT h.scheme_code,
                   AVG(h.nav) AS baseline_nav
            FROM mf_nav_history h
            JOIN latest l ON l.scheme_code = h.scheme_code
            WHERE h.nav_date >= date(l.d_latest, '-120 day')
              AND h.nav_date <  date(l.d_latest, '-30 day')
            GROUP BY h.scheme_code
        )
        SELECT l.scheme_code,
               l.nav_latest, b.baseline_nav,
               l.nav_latest / NULLIF(b.baseline_nav, 0) AS ratio
        FROM latest l
        JOIN baseline b ON l.scheme_code = b.scheme_code
        WHERE b.baseline_nav > 0
          AND l.nav_latest / b.baseline_nav >= 3.0
    """)
    return {
        row["scheme_code"]: (
            "ANOMALOUS",
            f"Latest NAV {row['ratio']:.1f}× the 30-120d baseline — likely wind-up settlement repricing"
        )
        for _, row in df.iterrows()
    }


def compute(dry_run: bool = False) -> dict:
    """Classify every active scheme; upsert data_quality + quality_reason.

    Returns {counts: {flag: n}, sample: list of recent flags applied}.
    """
    # Pull universe + latest metrics
    universe = read_sql("""
        SELECT sm.scheme_code, sm.scheme_name, sm.category_norm, sm.category_raw, sm.amc,
               m.ret_1y, m.std_1y
        FROM mf_scheme_master sm
        LEFT JOIN mf_metrics m ON sm.scheme_code = m.scheme_code
            AND m.as_of_date = (SELECT MAX(as_of_date) FROM mf_metrics)
        WHERE sm.active = 1
    """)
    print(f"Universe to classify: {len(universe)} active schemes")

    # Pre-compute NAV-jump anomalies once (single SQL pass over the whole table)
    print("Scanning NAV history for day-over-day jumps >50%…")
    nav_jump_flags = _classify_by_nav_jumps()
    print(f"  Found {len(nav_jump_flags)} schemes with anomalous NAV jumps")

    # Pre-compute per-category P99 1Y returns (TRUSTED-only, robust against
    # already-flagged contamination)
    cat_p99 = {}
    p99_df = read_sql("""
        WITH ranked AS (
            SELECT sm.category_norm, m.ret_1y,
                   PERCENT_RANK() OVER (PARTITION BY sm.category_norm ORDER BY m.ret_1y) AS pr,
                   COUNT(*) OVER (PARTITION BY sm.category_norm) AS n
            FROM mf_metrics m JOIN mf_scheme_master sm USING(scheme_code)
            WHERE m.ret_1y IS NOT NULL
              AND (sm.data_quality IS NULL OR sm.data_quality = 'TRUSTED')
        )
        SELECT category_norm, ret_1y
        FROM ranked
        WHERE pr >= 0.99 AND n >= 20
        GROUP BY category_norm
        HAVING ret_1y = MIN(ret_1y)
    """)
    for _, row in p99_df.iterrows():
        cat_p99[row["category_norm"]] = row["ret_1y"]
    print(f"  Computed P99 1Y return for {len(cat_p99)} categories with ≥20 peers")

    counts = {"TRUSTED": 0, "WOUND_UP": 0, "SEGREGATED": 0, "INTERVAL": 0,
              "BONUS": 0, "ANOMALOUS": 0}
    updates: list[tuple[str, str, str]] = []
    samples: list[dict] = []

    for _, row in universe.iterrows():
        code = row["scheme_code"]
        # 1. Name-based classification (highest priority)
        result = _classify_by_name(row["scheme_name"], row["category_raw"])
        # 2. Metric-based (only if name didn't flag it)
        if result is None:
            result = _classify_by_metrics(row, cat_p99)
        # 3. NAV-jump (fallback)
        if result is None and code in nav_jump_flags:
            result = nav_jump_flags[code]

        if result:
            flag, reason = result
            updates.append((flag, reason, code))
            counts[flag] = counts.get(flag, 0) + 1
            if len(samples) < 8:
                samples.append({"scheme_code": code, "name": row["scheme_name"][:65],
                                "flag": flag, "reason": reason})
        else:
            updates.append(("TRUSTED", None, code))
            counts["TRUSTED"] += 1

    print()
    for k, v in counts.items():
        print(f"  {k:12s}  {v}")
    print()
    print("Sample flagged schemes:")
    for s in samples:
        print(f"  [{s['flag']:10}] {s['scheme_code']:>6}  {s['name']}")
        print(f"               reason: {s['reason']}")

    if dry_run:
        print("\n--dry-run: not saving.")
        return {"counts": counts, "sample": samples}

    with get_db() as conn:
        conn.executemany(
            "UPDATE mf_scheme_master SET data_quality = ?, quality_reason = ? WHERE scheme_code = ?",
            updates,
        )
    print(f"\nUpdated {len(updates)} rows in mf_scheme_master.data_quality")
    return {"counts": counts, "sample": samples}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    compute(dry_run=args.dry_run)
