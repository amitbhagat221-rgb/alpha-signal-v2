"""
Alpha Signal v2 — Factor registry partition check (audit Factor-F2, ADR 0017 debt).

ADR 0017 promised a two-tier registry (wired vs library) but nothing ever
enforced that every backtested signal actually LANDS in one of the tiers. A
signal can be computed, backtested (has rows in pit_ic_by_tier_v2), and yet
be registered in NEITHER config.SIGNAL_WEIGHTS* NOR db.FACTOR_LIBRARY NOR
config.FACTOR_STATUS — invisible to any promotion review. This checker makes
that gap a hard, visible failure instead of a silent one.

Partition rule: every id in db.BACKTEST_SIGNALS must be in EXACTLY ONE of:
  - a config.SIGNAL_WEIGHTS / SIGNAL_WEIGHTS_RETURN / SIGNAL_WEIGHTS_SHARPE
    key (resolved through the same weight-key→signal-id alias map
    cockpit_ops/api.py uses for its promotion-funnel accounting — the two
    must stay in sync or "in_production" and this checker disagree)
  - config.FACTOR_STATUS (mapped to a non-wired classification)
  - db.FACTOR_LIBRARY

Read-only. Exit 0 = partition holds. Exit 1 = prints every violator (missing
from all three, or present in more than one) and exits non-zero.

Usage:
    python -m tools.verify_factor_library
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import config
from db import BACKTEST_SIGNALS, FACTOR_LIBRARY

# Mirrors cockpit_ops/api.py's _WEIGHT_KEY_TO_SIGNAL — the screener's weight
# keys are abstracted names ("consensus", "smart_money") that map to one
# canonical BACKTEST_SIGNALS id. Keep both copies in sync; a drift here is
# exactly the class of bug ADR notes ("mis-alias ... borrowed via a mis-alias
# in _WEIGHT_KEY_TO_SIGNAL / health_score / promotion_gate") already caused once.
WEIGHT_KEY_TO_SIGNAL = {
    "consensus":          "consensus_signal_combined",
    "earnings_yield":     "earnings_yield",
    "accruals":           "cf_accruals_ratio",
    "piotroski":          "piotroski_f_score",
    "momentum":           "mom_6m_adj",
    "book_to_price":      "book_to_price",
    "promoter":           "promoter_qoq",
    "smart_money":        "smart_money_score",
    "pt_upside":          "pt_upside",
    "eps_growth":         "eps_growth_yoy",
    "pledge_quality":     "pledge_quality",
    "delivery_anomaly_z": "delivery_anomaly_z",
}


def _wired_signal_ids():
    wired = set()
    for scheme_name in ("SIGNAL_WEIGHTS", "SIGNAL_WEIGHTS_RETURN", "SIGNAL_WEIGHTS_SHARPE"):
        for tier_weights in (getattr(config, scheme_name, {}) or {}).values():
            for key in tier_weights:
                wired.add(WEIGHT_KEY_TO_SIGNAL.get(key, key))
    if "mom_6m_adj" in wired:
        wired.add("mom_12m_adj")  # SMALL tier swaps in the 12m variant
    return wired


def check():
    """Return (ok, missing, duplicated) — missing/duplicated are sorted id lists."""
    wired = _wired_signal_ids()
    library = set(FACTOR_LIBRARY)
    status = set(getattr(config, "FACTOR_STATUS", {}).keys())

    missing, duplicated = [], []
    for entry in BACKTEST_SIGNALS:
        sid = entry["signal"]
        n = sum(1 for bucket in (wired, library, status) if sid in bucket)
        if n == 0:
            missing.append(sid)
        elif n > 1:
            duplicated.append(sid)
    return (not missing and not duplicated), sorted(missing), sorted(duplicated)


def main():
    ok, missing, duplicated = check()
    n_signals = len(BACKTEST_SIGNALS)
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
