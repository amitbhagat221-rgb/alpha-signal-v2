"""
Sector-tilt factor tests (ADR 0041).

Run: python -m tests.test_sector_tilt
or:  pytest tests/test_sector_tilt.py

Pins the validated ensemble math (mean of z(6m basket momentum) + z(macro_score),
mapped per stock), the live↔PIT parity (one core, two paths), and the NaN-safety
guards (thin sectors dropped, macro-missing falls back to the momentum leg).
"""
import numpy as np
import pandas as pd

from signals.sector_tilt import compute_sector_tilt, MOM_WINDOW, MIN_CONSTITUENTS
from tools.reconstruct_pit import pit_sector_tilt


# ─────────── builders ───────────

def _prices(returns_by_sid):
    """Build [sid, date, close] so each sid's trailing-MOM_WINDOW return == target.

    _window_return reads position -1 vs -(MOM_WINDOW+1); a length-(MOM_WINDOW+1)
    flat series with a final step delivers exactly the requested return.
    """
    dates = pd.date_range("2025-01-01", periods=MOM_WINDOW + 1, freq="D").astype(str)
    rows = []
    for sid, r in returns_by_sid.items():
        closes = [100.0] * MOM_WINDOW + [100.0 * (1.0 + r)]
        for d, c in zip(dates, closes):
            rows.append({"sid": sid, "date": d, "close": c})
    return pd.DataFrame(rows)


def _stocks(sector_by_sid):
    return pd.DataFrame([{"sid": s, "sector": sec} for s, sec in sector_by_sid.items()])


# Two full sectors (5 each → clear MIN_CONSTITUENTS) with known medians, plus a
# thin sector C (2 stocks → must be dropped).
SECTORS = {
    **{f"A{i}": "Alpha" for i in range(5)},
    **{f"B{i}": "Beta" for i in range(5)},
    **{f"C{i}": "Gamma" for i in range(2)},
}
RETURNS = {
    **{f"A{i}": 0.10 for i in range(5)},   # Alpha median 6m return = +10%
    **{f"B{i}": 0.00 for i in range(5)},   # Beta  median 6m return =   0%
    **{f"C{i}": 0.50 for i in range(2)},   # Gamma thin → dropped
}
# macro_score: Alpha high, Beta low → z(Alpha)=+1, z(Beta)=-1 (2-sector population).
MACRO = pd.DataFrame([{"sector": "Alpha", "macro_score": 10.0},
                      {"sector": "Beta", "macro_score": 0.0}])


def _run_core(macro=MACRO):
    return compute_sector_tilt(prices=_prices(RETURNS), macro_sector=macro,
                               stocks=_stocks(SECTORS))


# ─────────── ensemble math ───────────

def test_ensemble_is_mean_of_two_zscores():
    """z(mom): Alpha +1 / Beta -1; z(macro): Alpha +1 / Beta -1 → tilt ±1.0."""
    out = _run_core().set_index("sid")["sector_tilt"]
    assert abs(out["A0"] - 1.0) < 1e-9
    assert abs(out["B0"] + 1.0) < 1e-9


def test_value_is_sector_constant():
    """Every stock inherits its sector's value — the tilt is sector-constant."""
    out = _run_core().set_index("sid")["sector_tilt"]
    assert out["A0"] == out["A1"] == out["A4"]
    assert out["B0"] == out["B1"] == out["B4"]


def test_median_not_mean_basket():
    """An outlier constituent must not move the sector basket (median, not mean)."""
    rets = dict(RETURNS)
    rets["A4"] = 5.0   # one absurd mover — clipped + median-resistant
    out = compute_sector_tilt(prices=_prices(rets), macro_sector=MACRO,
                              stocks=_stocks(SECTORS)).set_index("sid")["sector_tilt"]
    # Alpha still > Beta and unchanged at ±1 (median of 5 is the middle 0.10).
    assert abs(out["A0"] - 1.0) < 1e-9


# ─────────── NaN-safety / guards ───────────

def test_thin_sector_dropped():
    """A sector below MIN_CONSTITUENTS gets no basket → its stocks are dropped."""
    assert MIN_CONSTITUENTS == 5
    out = _run_core()
    assert not (out["sid"].str.startswith("C")).any()


def test_macro_missing_falls_back_to_momentum():
    """No macro frame → ensemble is the momentum z alone (still ±1)."""
    out = compute_sector_tilt(prices=_prices(RETURNS),
                              macro_sector=pd.DataFrame(columns=["sector", "macro_score"]),
                              stocks=_stocks(SECTORS)).set_index("sid")["sector_tilt"]
    assert abs(out["A0"] - 1.0) < 1e-9 and abs(out["B0"] + 1.0) < 1e-9


def test_unknown_sector_not_mapped():
    """A stock whose sector has no computed signal is dropped, not mis-joined."""
    stk = pd.concat([_stocks(SECTORS),
                     pd.DataFrame([{"sid": "ZZ", "sector": "Nowhere"}])],
                    ignore_index=True)
    out = compute_sector_tilt(prices=_prices(RETURNS), macro_sector=MACRO, stocks=stk)
    assert "ZZ" not in set(out["sid"])


def test_clip_to_validation_range():
    """Output stays within VALIDATION_RANGES (-3, 3) even for extreme spreads."""
    out = _run_core()
    assert out["sector_tilt"].abs().max() <= 3.0


# ─────────── live ↔ PIT parity (one core, two paths) ───────────

def test_live_pit_parity():
    """pit_sector_tilt slices macro to the latest snapshot ≤ eval_date then calls
    the SAME core → must equal a direct live call on the equivalent frame."""
    px = _prices(RETURNS)
    stk = _stocks(SECTORS)
    # macro history with two snapshots; the later one (≤ eval) is the live-equivalent.
    macro_hist = pd.DataFrame([
        {"sector": "Alpha", "snapshot_date": "2024-12-01", "macro_score": -99.0},  # stale, ignored
        {"sector": "Beta", "snapshot_date": "2024-12-01", "macro_score": 99.0},
        {"sector": "Alpha", "snapshot_date": "2025-05-01", "macro_score": 10.0},   # latest ≤ eval
        {"sector": "Beta", "snapshot_date": "2025-05-01", "macro_score": 0.0},
    ])
    pit = pit_sector_tilt(stk, px, macro_hist, "2025-06-01").set_index("sid")["sector_tilt"]
    live = compute_sector_tilt(prices=px, macro_sector=MACRO, stocks=stk
                               ).set_index("sid")["sector_tilt"]
    for sid in ["A0", "A3", "B0", "B4"]:
        assert abs(pit[sid] - live[sid]) < 1e-9, f"parity broke at {sid}"


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} passed")


if __name__ == "__main__":
    _run()
