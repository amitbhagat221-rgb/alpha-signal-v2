"""
Alpha Signal v2 — VIX Regime Module

Reads India VIX from vix_history table.
Determines current regime: CALM / NORMAL / CAUTION / CRISIS.
Writes allocation weights to regime_state table.

Hysteresis: 3 consecutive days in new regime required before switching.

Usage:
    python -m scoring.regime            # update regime state
    python -m scoring.regime --dry-run  # show without saving
"""

import argparse
import json
from datetime import date

import pandas as pd

from config import PICKABLE_TIERS, REGIMES, VIX_HYSTERESIS_DAYS
from db import read_sql, get_db


def _get_regime_for_vix(vix):
    """Determine regime based on VIX level."""
    for regime, spec in REGIMES.items():
        lo, hi = spec["vix"]
        if lo <= vix < hi:
            return regime
    return "NORMAL"


def _get_allocations(regime):
    """{tier: allocation} for a regime (config.REGIMES, keyed by tier name)."""
    return dict(REGIMES[regime]["alloc"])


def compute(dry_run=False):
    """Update regime state based on latest VIX data."""
    # Get recent VIX history
    vix_df = read_sql(
        "SELECT date, vix FROM vix_history ORDER BY date DESC LIMIT 30"
    )

    if vix_df.empty:
        print("No VIX data available.")
        return 0

    latest_vix = vix_df.iloc[0]["vix"]
    latest_date = vix_df.iloc[0]["date"]
    vix_20d = vix_df.head(20)["vix"].mean()

    # Determine regime from latest VIX
    new_regime = _get_regime_for_vix(latest_vix)

    # Check hysteresis: last N days must agree
    if len(vix_df) >= VIX_HYSTERESIS_DAYS:
        recent_regimes = [_get_regime_for_vix(v) for v in vix_df.head(VIX_HYSTERESIS_DAYS)["vix"]]
        if all(r == new_regime for r in recent_regimes):
            confirmed_regime = new_regime
        else:
            # Fall back to current stored regime
            current = read_sql("SELECT regime FROM regime_state WHERE id = 1")
            confirmed_regime = current.iloc[0]["regime"] if not current.empty else new_regime
    else:
        confirmed_regime = new_regime

    alloc = _get_allocations(confirmed_regime)

    print(f"VIX Regime Update:")
    print(f"  Latest VIX: {latest_vix:.1f} (date: {latest_date})")
    print(f"  20-day avg: {vix_20d:.1f}")
    print(f"  Regime: {confirmed_regime}")
    print("  Allocation: " + " ".join(f"{t}={alloc[t]:.0%}" for t in PICKABLE_TIERS))

    if dry_run:
        print("\nDry run — not saving.")
        return 1

    # regime_state stores one alloc_<tier> column per pickable tier (schema.sql).
    alloc_cols = [f"alloc_{t.lower()}" for t in PICKABLE_TIERS]
    with get_db() as conn:
        conn.execute(
            f"""INSERT OR REPLACE INTO regime_state
               (id, regime, vix_latest, vix_20d_avg, {", ".join(alloc_cols)}, updated_at)
               VALUES (1, ?, ?, ?, {", ".join("?" * len(alloc_cols))}, datetime('now'))""",
            (confirmed_regime, latest_vix, vix_20d, *(alloc[t] for t in PICKABLE_TIERS)),
        )

    print(f"Saved regime_state: {confirmed_regime}")
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
