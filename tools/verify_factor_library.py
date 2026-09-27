"""
Alpha Signal v2 — Factor registry partition check (audit Factor-F2, ADR 0017 debt).

ADR 0017 promised a two-tier registry (wired vs library) but nothing ever
enforced that every backtested signal actually LANDS in one of the tiers. A
signal can be computed, backtested (has rows in pit_ic_by_tier_v2), and yet
be registered in NEITHER factors.SIGNAL_WEIGHTS* NOR db.FACTOR_LIBRARY NOR
factors.FACTOR_STATUS — invisible to any promotion review. This checker makes
that gap a hard, visible failure instead of a silent one.

Partition rule: every factor in factors.FACTORS must be in EXACTLY ONE of:
  - a nonzero factors.SIGNAL_WEIGHTS / SIGNAL_WEIGHTS_RETURN / SIGNAL_WEIGHTS_SHARPE
    weight (weight key resolved to its registry id by factors.signal_for)
  - a bench: LIBRARY (factors.FACTOR_LIBRARY) or PROPOSED / BLOCKED /
    SUPERSEDED / CONTROL (factors.FACTOR_STATUS)

Read-only. Exit 0 = partition holds. Exit 1 = prints every violator (missing
from all three, or present in more than one) and exits non-zero.

Usage:
    python -m tools.verify_factor_library
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import factors


def check():
    """Return (ok, missing, duplicated) — missing/duplicated are sorted id lists."""
    missing, duplicated = factors.partition_check()
    return (not missing and not duplicated), missing, duplicated


def main():
    ok, missing, duplicated = check()
    n_signals = len(factors.FACTORS)
    print(f"verify_factor_library: {n_signals} registered signals")
    if ok:
        print(f"✓ partition holds — every signal is in exactly one of "
              f"{{wired, FACTOR_LIBRARY, FACTOR_STATUS}}")
        return 0

    if missing:
        print(f"\n✗ {len(missing)} signal(s) in NONE of the three buckets (invisible to promotion review):")
        for sid in missing:
            print(f"    {sid}")
    if duplicated:
        print(f"\n✗ {len(duplicated)} signal(s) in MORE THAN ONE bucket (registry drift):")
        for sid in duplicated:
            print(f"    {sid}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
