"""factors.py is the one factor registry; every factor list is derived from it.

The hand-kept lists it replaced were checked equal to their derived versions
before deletion (commit "feat(factors): one factor registry"); the resolved
discrepancies are pinned here, plus the invariants that keep the registry whole.
"""
import config
import db
import factors
from eligibility import registry as eligibility
import pit
from tools import backtest_pit, pit_replay
from scoring import health_score


def test_consumers_use_the_registry():
    assert db.BACKTEST_SIGNALS is factors.BACKTEST_SIGNALS
    assert db.FACTOR_LIBRARY is factors.FACTOR_LIBRARY
    assert db.get_backtest_cadence is factors.get_backtest_cadence
    assert config.FACTOR_STATUS is factors.FACTOR_STATUS
    assert config.SIGNAL_GROUPS is factors.SIGNAL_GROUPS
    assert backtest_pit.SIGNAL_COLUMN_MAP is factors.SIGNAL_COLUMN_MAP
    assert pit.PIT_COLUMNS is factors.PIT_COLUMNS
    assert pit.VALIDATION_RANGES is factors.VALIDATION_RANGES
    assert eligibility.SIGNAL_ELIGIBILITY is factors.SIGNAL_ELIGIBILITY
    assert pit_replay.INPUT_COLS is factors.SCREENER_INPUT_COLS


def test_resolved_discrepancies():
    # momentum: dropped from SIGNAL_WEIGHTS 2026-07-05 but never benched
    assert {"mom_6m_adj", "mom_12m_adj"} <= set(factors.FACTOR_LIBRARY)
    # pt_upside: pulled (ADR 0045), only zero weights were left
    assert factors.FACTOR_STATUS["pt_upside"] == "BLOCKED"
    # financial_quality/_recovery carry their alias financial_signal range
    assert factors.VALIDATION_RANGES["financial_quality"] == (-3, 3, True)
    # backtest keys on the registry id; news_volume is backtested; v2 column known
    assert "momentum_composite" in factors.SIGNAL_COLUMN_MAP and "mom_composite" not in factors.SIGNAL_COLUMN_MAP
    assert factors.SIGNAL_COLUMN_MAP["news_volume"] == (None, "news_volume_7d")
    assert factors.SIGNAL_COLUMN_MAP["earnings_beat_rate"] == ("earnings_beat_rate", "earnings_beat_rate")
    # momentum ranks mom_12m in SMALL, mom_6m elsewhere — one alias, tier-aware
    assert factors.signal_for("momentum", "SMALL") == "mom_12m_adj"
    assert factors.signal_for("momentum", "LARGE") == factors.signal_for("momentum") == "mom_6m_adj"


def test_partition_holds():
    assert factors.partition_check() == ([], [])


def test_wired_factors_follow_weights():
    wired = {k for tw in config.SIGNAL_WEIGHTS.values() for k, w in tw.items() if w}
    assert set(health_score.WIRED_FACTORS) == wired
    for key in wired:   # every wired factor is scored, frozen and trust-rolled-up
        assert key in factors.SCREENER_COLS
        assert factors.SCREENER_COLS[key] in pit_replay.INPUT_COLS
        assert key in health_score.FACTOR_UPSTREAM_TABLES
        assert factors.status(factors.signal_for(key)) == "WIRED"


def test_pit_columns_ranged_and_produced():
    for col in factors.PIT_COLUMNS[3:]:
        assert col in factors.VALIDATION_RANGES, col
    for name, spec in factors.PIT_PRODUCERS.items():
        if spec["fn"]:
            assert callable(getattr(pit, spec["fn"], None)), name
    for sid, (v1, v2) in factors.SIGNAL_COLUMN_MAP.items():
        assert v2 is None or v2 in factors.PIT_COLUMNS, sid


def test_live_pit_cols_are_screener_columns():
    assert set(factors.LIVE_PIT_COLS) <= set(factors.SCREENER_INPUT_COLS)


def test_one_range_per_column():
    """A PIT column registered under two factor ids must carry ONE validation range
    (plan 0015: eps_revision_yoy vs consensus_signal_combined disagreed)."""
    import factors
    eps = {tuple(factors.FACTORS[k]["pit_range"]) for k in ("eps_revision_yoy", "consensus_signal_combined")}
    assert len(eps) == 1
