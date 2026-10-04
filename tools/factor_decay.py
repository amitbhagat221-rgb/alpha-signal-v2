"""
Alpha Signal v2 — Factor decay monitor (audit Factor-F4).

Read-only. A factor's t-stat at wiring time is a POINT-IN-TIME measurement —
nothing re-checks whether the edge that justified its weight is still there.
This computes, for every currently-wired factor per tier, a rolling-window
IC comparison: the the last year of the factor's own anchors (12 monthly / 52 weekly) vs its full history. Flags
DECAYED when the recent window's sign no longer matches the wired weight's
sign, or its magnitude has fallen below a quarter of the all-time mean —
the pattern the audit found in governance_resignation (yearly IC swung
−0.081 → −0.002, sign-adjacent to zero, while the wired weight is negative) —
AND the recent mean sits at least DECAY_MIN_SE standard errors below the
all-time mean. Twelve anchors of a weak factor flip sign by chance about one
time in three: without the second condition 8 of 16 weights were flagged every
day for 89 days (2026-10-02), 5 of them inside sampling noise.

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
from tools.backtest_pit import _compute_ic, _newey_west_se, _nw_lag_for, iter_panels

# weight key → registry id (tier-default); re-exported for tools/expected_return.
WEIGHT_KEY_TO_SIGNAL = factors.WEIGHT_KEY_TO_SIGNAL

RECENT_WINDOW = {"monthly": 12, "weekly": 52}   # one year of the factor's own anchors
DECAY_MAGNITUDE_FLOOR = 0.25   # recent |mean IC| < 25% of all-time |mean IC| → decayed
DECAY_MIN_SE = 2.0             # …and the drop is at least this many standard errors of the recent mean

_PANEL = None


def _panel():
    global _PANEL
    if _PANEL is None:
        cols = sorted({factors.FACTORS[s].get("replay_col") or factors.pit_column(s) for s in factors.wired_signal_ids()})
        _PANEL = read_sql("SELECT snapshot_date, cap_tier, fwd_return_20d, "
                          + ", ".join(f"[{c}]" for c in cols) + " FROM daily_snapshots_pit")
    return _PANEL


def _factor_ic_series(col, cap_tier, signal_id):
    """Per-anchor Spearman IC for one (column, tier), oldest→newest, on the SAME
    anchors the backtest scores (iter_panels: a weekly factor on Fridays, a monthly
    one on month-start anchors). Taking every anchor with a value mixed the two
    grids: "the last 12 anchors" was nine weeks of 4×-overlapping windows for every
    factor, and the all-time IC disagreed with the evidence table."""
    panel = _panel()
    for *_, tier, tier_df in iter_panels(panel.iloc[:0], panel, [(signal_id, (None, col))]):
        if tier == cap_tier:
            return sorted(_compute_ic(tier_df, col, "fwd_return_20d"), key=lambda r: r[0])
    return []


def analyze():
    """Return a list of dicts: one row per (weight_key, tier) that resolves to
    a scored v2 column, with all-time / recent mean IC, n anchors, and verdict."""
    rows = []
    for tier, weights in factors.SIGNAL_WEIGHTS.items():
        for weight_key, weight in weights.items():
            if weight == 0:
                continue
            signal_id = factors.signal_for(weight_key, tier)
            # the column the screener SCORES (accruals: the composite, not its cf component)
            v2_col = factors.FACTORS[signal_id].get("replay_col") or factors.pit_column(signal_id)
            cadence = factors.get_backtest_cadence(signal_id)
            window = RECENT_WINDOW.get(cadence, 12)
            if not v2_col:
                rows.append({
                    "tier": tier, "weight_key": weight_key, "signal_id": signal_id,
                    "weight": weight, "n_all": 0, "n_recent": 0,
                    "ic_all": None, "ic_recent": None, "decayed": None,
                    "note": "no v2 PIT column registered — cannot compute IC",
                })
                continue

            ic_rows = _factor_ic_series(v2_col, tier, signal_id)
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
            recent = ic_rows[-window:]
            ics_recent = np.array([r[1] for r in recent])
            n_recent = len(recent)
            ic_recent = float(ics_recent.mean())

            sign_wired = 1 if weight > 0 else -1
            sign_recent = 1 if ic_recent > 0 else (-1 if ic_recent < 0 else 0)
            sign_mismatch = sign_recent != 0 and sign_recent != sign_wired
            magnitude_collapsed = abs(ic_all) > 1e-9 and abs(ic_recent) < DECAY_MAGNITUDE_FLOOR * abs(ic_all)
            # how far the recent mean is below the all-time mean, in the wired direction,
            # in standard errors of the recent mean (None: too few anchors to say)
            se = (_newey_west_se(ics_recent, _nw_lag_for(signal_id, cadence)) or 0.0) if n_recent >= 3 else 0.0
            gap_se = sign_wired * (ic_all - ic_recent) / se if se > 0 else None
            decayed = bool((sign_mismatch or magnitude_collapsed) and gap_se is not None and gap_se >= DECAY_MIN_SE)

            rows.append({
                "tier": tier, "weight_key": weight_key, "signal_id": signal_id,
                "weight": weight, "n_all": n_all, "n_recent": n_recent,
                "ic_all": round(ic_all, 4), "ic_recent": round(ic_recent, 4),
                "gap_se": None if gap_se is None else round(gap_se, 1),
                "decayed": decayed,
                "note": ("thin panel — under two years of anchors, the recent window is most of the history"
                         if n_all < 2 * window else ""),
            })
    return rows


def main():
    rows = analyze()
    print(f"\n══ Factor decay monitor — last year of anchors vs all-time IC ══\n")
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
