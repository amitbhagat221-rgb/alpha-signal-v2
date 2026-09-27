"""
Alpha Signal v2 — Factor decay monitor (audit Factor-F4).

Read-only. A factor's t-stat at wiring time is a POINT-IN-TIME measurement —
nothing re-checks whether the edge that justified its weight is still there.
This computes, for every currently-wired factor per tier, a rolling-window
IC comparison: the last 12 anchors vs the factor's full history. Flags
DECAYED when the recent window's sign no longer matches the wired weight's
sign, or its magnitude has fallen below a quarter of the all-time mean —
the pattern the audit found in governance_resignation (yearly IC swung
−0.081 → −0.002, sign-adjacent to zero, while the wired weight is negative).

Per-anchor IC uses the SAME helper as tools/backtest_pit.py (Spearman IC of
the factor's v2 PIT column vs fwd_return_20d, min 20 stocks/anchor) — no
re-derivation, so this monitor and the backtest can never silently disagree
on methodology.

Usage:
    python -m tools.factor_decay
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

import factors
from db import read_sql
from tools.backtest_pit import SIGNAL_COLUMN_MAP, _compute_ic

# weight key → registry id (tier-default); re-exported for tools/expected_return.
WEIGHT_KEY_TO_SIGNAL = factors.WEIGHT_KEY_TO_SIGNAL

RECENT_WINDOW = 12
DECAY_MAGNITUDE_FLOOR = 0.25   # last-12 |mean IC| < 25% of all-time |mean IC| → decayed


def _factor_ic_series(v2_col, cap_tier):
    """Per-anchor Spearman IC for one (column, tier), oldest→newest."""
    df = read_sql(
        f"SELECT snapshot_date, [{v2_col}], fwd_return_20d FROM daily_snapshots_pit "
        f"WHERE cap_tier = ? AND [{v2_col}] IS NOT NULL AND fwd_return_20d IS NOT NULL",
        params=[cap_tier],
    )
    if df.empty:
        return []
    ic_rows = _compute_ic(df, v2_col, "fwd_return_20d")
    ic_rows.sort(key=lambda r: r[0])  # (eval_date, ic, n_stocks), oldest first
    return ic_rows


def analyze():
    """Return a list of dicts: one row per (weight_key, tier) that resolves to
    a scored v2 column, with all-time / recent mean IC, n anchors, and verdict."""
    rows = []
    for tier, weights in factors.SIGNAL_WEIGHTS.items():
        for weight_key, weight in weights.items():
            if weight == 0:
                continue
            signal_id = factors.signal_for(weight_key, tier)
            col_map = SIGNAL_COLUMN_MAP.get(signal_id)
            v2_col = col_map[1] if col_map else None
            if not v2_col:
                rows.append({
                    "tier": tier, "weight_key": weight_key, "signal_id": signal_id,
                    "weight": weight, "n_all": 0, "n_recent": 0,
                    "ic_all": None, "ic_recent": None, "decayed": None,
                    "note": "no v2 PIT column registered — cannot compute IC",
                })
                continue

            ic_rows = _factor_ic_series(v2_col, tier)
            n_all = len(ic_rows)
            if n_all == 0:
                rows.append({
                    "tier": tier, "weight_key": weight_key, "signal_id": signal_id,
                    "weight": weight, "n_all": 0, "n_recent": 0,
                    "ic_all": None, "ic_recent": None, "decayed": None,
                    "note": "0 anchors with both signal + fwd_return_20d populated",
                })
                continue

            ics_all = np.array([r[1] for r in ic_rows])
            ic_all = float(ics_all.mean())
            recent = ic_rows[-RECENT_WINDOW:]
            ics_recent = np.array([r[1] for r in recent])
            n_recent = len(recent)
            ic_recent = float(ics_recent.mean())

            sign_wired = 1 if weight > 0 else -1
            sign_recent = 1 if ic_recent > 0 else (-1 if ic_recent < 0 else 0)
            sign_mismatch = sign_recent != 0 and sign_recent != sign_wired
            magnitude_collapsed = abs(ic_all) > 1e-9 and abs(ic_recent) < DECAY_MAGNITUDE_FLOOR * abs(ic_all)
            decayed = bool(sign_mismatch or magnitude_collapsed)

            rows.append({
                "tier": tier, "weight_key": weight_key, "signal_id": signal_id,
                "weight": weight, "n_all": n_all, "n_recent": n_recent,
                "ic_all": round(ic_all, 4), "ic_recent": round(ic_recent, 4),
                "decayed": decayed,
                "note": ("thin panel (<12 anchors) — decay read is provisional"
                         if n_all < RECENT_WINDOW else ""),
            })
    return rows


def main():
    rows = analyze()
    print(f"\n══ Factor decay monitor — last {RECENT_WINDOW} anchors vs all-time IC ══\n")
    print(f"  {'TIER':6s} {'FACTOR':22s} {'WEIGHT':>8s} {'N(all)':>7s} {'N(recent)':>9s} "
          f"{'IC(all)':>8s} {'IC(recent)':>10s}  FLAG")
    n_decayed = 0
    for r in sorted(rows, key=lambda x: (x["tier"], x["weight_key"])):
        if r["decayed"] is None:
            print(f"  {r['tier']:6s} {r['weight_key']:22s} {r['weight']:>+8.2f} "
                  f"{r['n_all']:>7d} {'—':>9s} {'—':>8s} {'—':>10s}  ({r['note']})")
            continue
        flag = "⚠ DECAYED" if r["decayed"] else ""
        if r["decayed"]:
            n_decayed += 1
        print(f"  {r['tier']:6s} {r['weight_key']:22s} {r['weight']:>+8.2f} "
              f"{r['n_all']:>7d} {r['n_recent']:>9d} {r['ic_all']:>8.4f} {r['ic_recent']:>10.4f}  {flag}"
              + (f"  ({r['note']})" if r["note"] else ""))
    print(f"\n  {n_decayed} of {sum(1 for r in rows if r['decayed'] is not None)} "
          f"scoreable (weight_key, tier) pairs flagged DECAYED.\n")
    return rows


if __name__ == "__main__":
    main()
