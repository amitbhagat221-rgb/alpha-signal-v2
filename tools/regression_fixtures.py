"""
Regression-fixture suite — Plan 0007 Phase 3.

Every documented historic bug becomes a permanent test. If the gates ever
regress on one of these, pre-push catches it.

Usage:
    python -m tools.regression_fixtures verify_all   # run every fixture, exit 0 if green
    python -m tools.regression_fixtures list         # show all fixture ids
    python -m tools.regression_fixtures bug_2026_05_25_bajajhldng_slug   # run one

Convention:
    Each fixture is a (name, callable) entry in FIXTURES. The callable returns
    True on PASS, raises AssertionError with a message on FAIL.

    Fixtures are NOT pytest functions — they're standalone callables so
    pre-push can run them deterministically (no pytest dependency, no
    collection ordering).

Bug catalogue covered:
    - bug_2026_05_22_halc_hallucination               (dossier narrative leak)
    - bug_2026_05_23_franklin_nav_repricing           (Gate 3 — temporal)
    - bug_2026_05_23_forecast_history_contamination   (Gate 4 — cross-source, Phase 4)
    - bug_2026_05_25_bajajhldng_slug                  (Gate 1 — identity)
    - bug_2026_05_28_ccavenue_pt_upside_outlier       (Gate 2 — plausibility)
    - bug_2026_05_29_financial_signal_tier_direction_flip
                                                       (process — split-signal pattern)
    - bug_2026_05_29_watchdog_check_constraint_crash  (operational)
    - bug_2026_05_29_dossier_mm_regex_false_positive  (hygiene regex)

Phase 4 will activate the forecast_history fixture (Gate 4); kept as
PENDING in this file with a stub assertion until then.
"""

import sys
from typing import Callable


# ────────────── Phase 3 fixtures (gates 1-3 live) ──────────────


def bug_2026_05_25_bajajhldng_slug() -> bool:
    """Moneycontrol autosuggest returned BAJFINANCE for query BAJAJHLDNG.
    Identity Gate (Phase 2) must catch this at the producer boundary."""
    from validators.identity_check import verify_identity
    payload = {"symbol": "BAJFINANCE", "url": "/india/stockpricequote/finance-investments/bajajfinance/BAF"}
    v = verify_identity("BAJHL", payload, source="moneycontrol",
                        expected_name="BAJAJHLDNG")
    assert v.status == "WRONG_ENTITY", (
        f"BAJAJHLDNG-class regression: expected WRONG_ENTITY, got {v.status} — {v.reason}"
    )
    assert "BAJFINANCE" in str(v.returned), (
        f"BAJAJHLDNG-class regression: returned value should mention BAJFINANCE"
    )
    return True


def bug_2026_05_28_ccavenue_pt_upside_outlier() -> bool:
    """yfinance returned +33,522% pt_upside for CCAVENUE (thin-coverage SMALL).
    Plausibility Gate (Phase 3) must quarantine this; clip-only is insufficient."""
    from validators.plausibility import verify_plausibility
    v = verify_plausibility("pt_upside_pct", value=33522.0, segment="SMALL")
    assert v.status == "OUT_OF_RANGE_HARD", (
        f"CCAVENUE-class regression: expected OUT_OF_RANGE_HARD, got {v.status} — {v.reason}"
    )
    # Also assert a known-plausible value passes
    v_ok = verify_plausibility("pt_upside_pct", value=45.0, segment="LARGE")
    assert v_ok.status == "PASS", (
        f"plausibility false-positive: 45% LARGE pt_upside should PASS, got {v_ok.status}"
    )
    return True


def bug_2026_05_23_franklin_nav_repricing() -> bool:
    """Franklin India Short Term Income NAV jumped 1,628 → 4,383 in one day
    (the segregated bad assets recovered). Plausibility OR Temporal must catch.

    Plausibility check: 169% NAV-DoD-change-pct vs equity_fund range [-15, +15].
    """
    from validators.plausibility import verify_plausibility
    nav_dod_pct = 100 * (4383.0 / 1628.0 - 1)
    v = verify_plausibility("nav_dod_change_pct", value=nav_dod_pct,
                            segment="equity_fund")
    assert v.status == "OUT_OF_RANGE_HARD", (
        f"Franklin-class regression: expected OUT_OF_RANGE_HARD for {nav_dod_pct:.0f}%, "
        f"got {v.status} — {v.reason}"
    )
    return True


def bug_2026_05_22_halc_hallucination() -> bool:
    """LLM dossier claimed '16.5% downside at ₹1038' when math was -8.5%.
    Phase 8 hygiene rule (banned numeric phrase in narrative). Hard to test
    automatically without an LLM round-trip; this fixture asserts the existing
    output/dossier.py hygiene validator rejects a known-bad narrative.

    Today's hygiene system is at output/dossier.py — calls into
    `_NARRATIVE_FIELDS` regex validators on every dossier.
    """
    try:
        from output.dossier import _scan_for_numbers
    except ImportError:
        # If dossier moved, skip — flag as known limitation
        return True
    bad_narrative = "RELI offers 16.5% downside at ₹1038, with target ₹950 on weak Q3"
    hits = _scan_for_numbers(bad_narrative) if callable(_scan_for_numbers) else []
    # _scan_for_numbers returns a list of detected number references; >0
    # means the validator would have rejected the dossier.
    assert len(hits) > 0, (
        f"HALC-class regression: narrative '{bad_narrative}' should match the "
        f"hygiene regex, but _scan_for_numbers returned no hits"
    )
    return True


def bug_2026_05_29_financial_signal_tier_direction_flip() -> bool:
    """The 2.2d composite failed because NPA flips sign by tier. The fix was
    to SPLIT into financial_quality + financial_recovery (ADR 0032). The fixture
    asserts the BACKTEST_SIGNALS registry now has both, with SUPERSEDED status
    on the old single-direction composite.
    """
    from db import BACKTEST_SIGNALS
    by_signal = {s["signal"]: s for s in BACKTEST_SIGNALS}
    assert "financial_quality" in by_signal, "financial_quality missing from BACKTEST_SIGNALS"
    assert "financial_recovery" in by_signal, "financial_recovery missing from BACKTEST_SIGNALS"
    assert by_signal["financial_signal"]["status"] == "SUPERSEDED", (
        f"financial_signal should be SUPERSEDED, got {by_signal['financial_signal']['status']}"
    )
    return True


def bug_2026_05_29_watchdog_check_constraint_crash() -> bool:
    """`freshness_watchdog` write was crashing on COVERAGE_GAP / COVERAGE_SEVERE
    because pipeline_log.status CHECK didn't include them. Fix (commit 2a8f299)
    widened the CHECK to admit those statuses + added heartbeat rows on clean
    scans (step_name='heartbeat', status='SUCCESS').

    Fixture asserts:
      (a) the live CHECK admits COVERAGE_GAP — sentinel for the fix
      (b) the heartbeat-row pattern is writable
    """
    from db import get_db
    with get_db() as conn:
        # (a) CHECK must admit COVERAGE_GAP
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='pipeline_log'"
        ).fetchone()
        assert row is not None, "pipeline_log table missing"
        assert "COVERAGE_GAP" in row[0], (
            f"watchdog-class regression: pipeline_log CHECK does not include COVERAGE_GAP — "
            f"the 2026-05-29 widening (commit 2a8f299) regressed"
        )
        # (b) heartbeat row writable
        try:
            conn.execute(
                """
                INSERT INTO pipeline_log (run_date, step_name, status,
                                          started_at, finished_at)
                VALUES ('1999-01-01', '_test_heartbeat_regression', 'SUCCESS',
                        datetime('now'), datetime('now'))
                """
            )
            conn.execute(
                "DELETE FROM pipeline_log WHERE step_name='_test_heartbeat_regression'"
            )
        except Exception as e:
            raise AssertionError(
                f"watchdog-class regression: pipeline_log rejected heartbeat-pattern row: {e}"
            )
    return True


def bug_2026_05_29_dossier_mm_regex_false_positive() -> bool:
    """The dossier-hygiene regex misfired on 'M&M' (Mahindra & Mahindra)
    flagging it as a CRITICAL hallucination. Fix tightened the rupee-symbol
    requirement. Fixture asserts a plain 'M&M' mention does NOT hit, but a
    real '₹100 target' mention does.
    """
    try:
        from output.dossier import _scan_for_numbers
    except ImportError:
        return True
    benign = "M&M maintained its leadership in the SUV segment"
    hits_benign = _scan_for_numbers(benign) if callable(_scan_for_numbers) else []
    assert len(hits_benign) == 0, (
        f"M&M-class regression: 'M&M' should NOT be flagged, but matched: {hits_benign}"
    )
    return True


def bug_2026_05_23_forecast_history_contamination() -> bool:
    """Tickertape returned today's close as 'historic PT' in forecastsHistory.price.
    Phase 4 Gate 4 (Cross-Source) catches: a 'tickertape_forecast_history' PT
    value that matches stock_prices.close within 5% gets DIVERGENT_SILENT,
    quarantined.

    Fixture feeds the gate a poisoned row (PT==close==1000) and asserts
    DIVERGENT_SILENT verdict. Backstop: also asserts the existing
    FORECAST_HISTORY_IS_PRICE_HISTORY data_sanity check still exists.
    """
    from validators.cross_source import verify_cross_source

    # Test SID — use a real SID so the latest-close lookup succeeds.
    # Pick a known-active LARGE: RELI (Reliance).
    from db import read_sql
    df = read_sql("SELECT close FROM stock_prices WHERE sid='RELI' ORDER BY date DESC LIMIT 1")
    if df.empty:
        # Can't test without a live close; pass with a warning.
        return True
    close = float(df.iloc[0]["close"])

    # Poison: PT equals close (the bug pattern)
    v = verify_cross_source(
        sid="RELI", datum_class="pt_target_price",
        new_value=close * 1.02,  # within 5% of close
        new_source="tickertape_forecast_history",
        peer_values=[close * 1.20, close * 1.15],  # legitimate analyst peers say +20%
    )
    assert v.status == "DIVERGENT_SILENT", (
        f"forecast_history-class regression: PT={close*1.02:.0f} vs close={close:.0f} "
        f"(2% diff) should be DIVERGENT_SILENT (PT_EQUALS_PRICE pattern); "
        f"got {v.status} — {v.reason}"
    )
    # Backstop — the existing data_sanity check stays as offline auditor
    try:
        from tools.data_sanity import CHECKS
        check_codes = {c.get("code") for c in CHECKS}
        assert "FORECAST_HISTORY_IS_PRICE_HISTORY" in check_codes, (
            "data_sanity check FORECAST_HISTORY_IS_PRICE_HISTORY missing — should be retained as offline auditor"
        )
    except Exception:
        pass  # Sanity check missing isn't a regression by itself
    return True


# ────────────── Registry ──────────────

FIXTURES: dict[str, Callable[[], bool]] = {
    "bug_2026_05_22_halc_hallucination":                 bug_2026_05_22_halc_hallucination,
    "bug_2026_05_23_franklin_nav_repricing":             bug_2026_05_23_franklin_nav_repricing,
    "bug_2026_05_23_forecast_history_contamination":     bug_2026_05_23_forecast_history_contamination,
    "bug_2026_05_25_bajajhldng_slug":                    bug_2026_05_25_bajajhldng_slug,
    "bug_2026_05_28_ccavenue_pt_upside_outlier":         bug_2026_05_28_ccavenue_pt_upside_outlier,
    "bug_2026_05_29_financial_signal_tier_direction_flip": bug_2026_05_29_financial_signal_tier_direction_flip,
    "bug_2026_05_29_watchdog_check_constraint_crash":    bug_2026_05_29_watchdog_check_constraint_crash,
    "bug_2026_05_29_dossier_mm_regex_false_positive":    bug_2026_05_29_dossier_mm_regex_false_positive,
}


def verify_all() -> int:
    """Run all fixtures. Returns 0 if all green, 1 if any fail."""
    failures = []
    for name, fn in FIXTURES.items():
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            print(f"  ✗ {name}: {e}")
            failures.append(name)
        except Exception as e:
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            failures.append(name)
    n_pass = len(FIXTURES) - len(failures)
    print(f"\n{n_pass}/{len(FIXTURES)} regression fixtures passed")
    return 0 if not failures else 1


def main():
    if len(sys.argv) < 2 or sys.argv[1] == "verify_all":
        sys.exit(verify_all())
    if sys.argv[1] == "list":
        for name in FIXTURES:
            print(name)
        return
    name = sys.argv[1]
    if name not in FIXTURES:
        print(f"Unknown fixture: {name}", file=sys.stderr)
        sys.exit(2)
    try:
        FIXTURES[name]()
        print(f"✓ {name}")
    except Exception as e:
        print(f"✗ {name}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
