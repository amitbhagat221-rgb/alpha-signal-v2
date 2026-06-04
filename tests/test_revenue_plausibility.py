"""
Revenue-plausibility hard-exclusion tests.

Run: python -m tests.test_revenue_plausibility
or:  pytest tests/test_revenue_plausibility.py

THE RAJESH EXPORTS CASE
    2026-06-03: SEBI alleged ~₹15.15 lakh cr of fabricated revenue at Rajesh
    Exports (REXP) across FY21-25 (~99.8% of consolidated). Our entire forensic
    suite endorsed it — Beneish M = CLEAN, Altman Z = 13.7 SAFE, Piotroski 6/9,
    accruals 0.76 — and it sat in daily_picks at rank 79, UHS 90 TRUSTED. Every
    model is a YoY-change/distress detector; the fraud was steady-state with a
    fabricated cash side, so it hid. The tell they all miss is the LEVEL: ~₹7.8
    lakh cr of TTM revenue on ₹29,372 cr of assets — ~26x turnover at ~0.01%
    margin.

    These tests pin the predicate that catches exactly that signature, and pin
    that it does NOT catch legitimate high-turnover businesses.
"""
from signals.revenue_plausibility import flag_revenue_implausible


# ─────────── The signature that must be caught ───────────

def test_rexp_actual_numbers_flagged():
    """REXP's real TTM figures (2026-06-04 DB) must trip the gate."""
    flagged, reason = flag_revenue_implausible(
        rev_ttm=778_989.0, ni_ttm=112.5, total_assets=29_372.0,
        sector="Consumer Discretionary",
    )
    assert flagged, "REXP (26x turnover, ~0% margin) must be flagged"
    assert "implausible asset turnover" in reason


def test_pure_round_tripping_zero_margin_flagged():
    """Huge revenue, no profit, thin asset base → flagged."""
    flagged, _ = flag_revenue_implausible(
        rev_ttm=500_000.0, ni_ttm=10.0, total_assets=20_000.0, sector="Materials",
    )
    assert flagged


# ─────────── Legitimate high-turnover businesses must NOT be caught ───────────

def test_distributor_high_turnover_real_margin_passes():
    """A distributor (Redington-like): ~4x turnover at a real ~2% margin → pass."""
    flagged, _ = flag_revenue_implausible(
        rev_ttm=119_000.0, ni_ttm=2_380.0, total_assets=28_000.0, sector="Industrials",
    )
    assert not flagged


def test_staffing_passthrough_passes():
    """Staffing (TeamLease-like): ~5.6x turnover but ~1.2% margin → pass."""
    flagged, _ = flag_revenue_implausible(
        rev_ttm=11_900.0, ni_ttm=140.0, total_assets=2_100.0, sector="Industrials",
    )
    assert not flagged


def test_high_turnover_but_healthy_margin_passes():
    """Elitecon-like: 19x turnover but 6.7% margin → not the zero-profit signature."""
    flagged, _ = flag_revenue_implausible(
        rev_ttm=4_800.0, ni_ttm=322.0, total_assets=250.0, sector="Industrials",
    )
    assert not flagged


# ─────────── Conservative guards — never exclude on absent/thin evidence ───────────

def test_financials_exempt():
    """Lenders have different turnover/margin semantics — always exempt."""
    flagged, _ = flag_revenue_implausible(
        rev_ttm=500_000.0, ni_ttm=10.0, total_assets=20_000.0, sector="Financials",
    )
    assert not flagged


def test_sub_floor_assets_not_flagged():
    """Below the asset floor the ratio is rounding noise — never flag."""
    flagged, _ = flag_revenue_implausible(
        rev_ttm=5_000.0, ni_ttm=0.1, total_assets=50.0, sector="Materials",
    )
    assert not flagged


def test_missing_margin_not_flagged():
    """No net-income evidence → cannot confirm the zero-profit half → pass."""
    flagged, _ = flag_revenue_implausible(
        rev_ttm=500_000.0, ni_ttm=None, total_assets=20_000.0, sector="Materials",
    )
    assert not flagged


def test_normal_company_passes():
    """A vanilla manufacturer: ~1x turnover, 10% margin → pass."""
    flagged, _ = flag_revenue_implausible(
        rev_ttm=5_000.0, ni_ttm=500.0, total_assets=5_000.0, sector="Materials",
    )
    assert not flagged


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
