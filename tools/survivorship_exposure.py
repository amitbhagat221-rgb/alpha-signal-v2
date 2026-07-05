"""
Alpha Signal v2 — Survivorship exposure report (audit Data-F1, measurement half).

Read-only measurement, NOT a fix. `tools/backtest_pit.py`'s PIT panel is built
from CURRENT sids only (`stocks` table) — any symbol that was part of the true
historical NSE universe on a given date but has since delisted, merged, or
renamed beyond what the scrip-master crosswalk can resolve is silently absent
from every backtest anchor's cross-section. `historical_universe` (nselib
bhav_copy_with_delivery reconstruction, see memory survivorship_universe_
via_bhavcopy) carries the TRUE historical universe per snapshot date with a
`sid` column populated only where a current-sid mapping exists — this tool
just counts what doesn't map.

Rebuilding the PIT panel against `historical_universe` instead (fixing the
bias) is a redesign with unfixable fundamentals gaps for dead names (no
quarterly_income/balance_sheet history was ever fetched for delisted
symbols) — Amit's call, not attempted here (per plan 0010 Task 6.4).

Usage:
    python -m tools.survivorship_exposure
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql


def compute():
    """Return (per_date_rows, total_never_mapping, since_2023_never_mapping)."""
    df = read_sql("SELECT snapshot_date, symbol, sid FROM historical_universe ORDER BY snapshot_date")
    if df.empty:
        return [], 0, 0

    rows = []
    for snapshot_date, g in df.groupby("snapshot_date"):
        total = len(g)
        absent = int(g["sid"].isna().sum())
        rows.append({
            "snapshot_date": snapshot_date,
            "year": snapshot_date[:4],
            "total_universe": total,
            "absent": absent,
            "pct_absent": round(100.0 * absent / total, 1) if total else None,
        })

    never_mapping = df[df["sid"].isna()]
    total_never = int(never_mapping["symbol"].nunique())
    since_2023 = int(never_mapping[never_mapping["snapshot_date"] >= "2023-01-01"]["symbol"].nunique())
    return rows, total_never, since_2023


def main():
    rows, total_never, since_2023 = compute()
    if not rows:
        print("⚠ historical_universe is empty — nothing to measure.")
        return

    print("\n══ Survivorship exposure — historical_universe vs current-sid mapping ══\n")
    print(f"  {'SNAPSHOT DATE':14s} {'YEAR':6s} {'TRUE UNIVERSE':>14s} {'ABSENT':>8s} {'% ABSENT':>9s}")
    for r in rows:
        print(f"  {r['snapshot_date']:14s} {r['year']:6s} {r['total_universe']:>14d} "
              f"{r['absent']:>8d} {r['pct_absent']:>8.1f}%")

    worst = max(rows, key=lambda r: r["pct_absent"])
    print(f"\n  Worst snapshot: {worst['snapshot_date']} — {worst['pct_absent']}% of that date's true "
          f"NSE universe never maps to a current sid (delisted/merged/renamed beyond crosswalk).")
    print(f"  {total_never:,} distinct symbols never map to a current sid across all snapshots "
          f"({since_2023:,} of those present as recently as 2023+).")
    print(f"\n  Every tools/backtest_pit.py anchor's cross-section is implicitly survivors-only by")
    print(f"  roughly this magnitude (higher for older anchors, per the trend above). ADVISORY —")
    print(f"  measurement only; see this file's docstring for why the panel isn't rebuilt here.\n")
    return rows


if __name__ == "__main__":
    main()
