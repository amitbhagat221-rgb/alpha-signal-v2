"""factors.py is the one factor registry — every hand-maintained factor list must
equal its derived version. Where the two disagreed, the discrepancy is spelled out
here and resolved to the correct value in factors.py.
"""
import textwrap

import config
import db
import factors
from tools import backtest_pit, reconstruct_pit


def test_backtest_signals_metadata_unchanged():
    assert factors.BACKTEST_SIGNALS == db.BACKTEST_SIGNALS


def test_cadence():
    # db's dict also spelled out smart_money_score: "monthly" (the default) — same lookup.
    assert {s: factors.get_backtest_cadence(s) for s in factors.FACTORS} == \
        {s: db.get_backtest_cadence(s) for s in factors.FACTORS}


def test_factor_library():
    # Resolved: momentum was dropped from SIGNAL_WEIGHTS 2026-07-05 (clean t=1.34) but never
    # benched, so the partition check failed for both ids → LIBRARY.
    assert set(factors.FACTOR_LIBRARY) == set(db.FACTOR_LIBRARY) | {"mom_6m_adj", "mom_12m_adj"}


def test_factor_status():
    # Resolved: pt_upside only had zero weights left (pulled, ADR 0045) — BLOCKED.
    assert factors.FACTOR_STATUS == {**config.FACTOR_STATUS, "pt_upside": "BLOCKED"}


def test_signal_groups():
    assert factors.SIGNAL_GROUPS == config.SIGNAL_GROUPS


def test_pit_columns_and_ranges():
    assert set(factors.PIT_COLUMNS) == set(reconstruct_pit.PIT_COLUMNS)
    # Resolved: financial_quality/_recovery had no range (financial_signal, their alias, had ±3).
    assert factors.VALIDATION_RANGES == {**reconstruct_pit.VALIDATION_RANGES,
                                         "financial_quality": (-3, 3, True),
                                         "financial_recovery": (-3, 3, True)}


def test_signal_column_map():
    old = dict(backtest_pit.SIGNAL_COLUMN_MAP)
    # Resolved: the registry id is momentum_composite (FACTOR_STATUS said "zero backtest
    # rows" because the backtest wrote it as mom_composite); news_volume was never in the
    # map at all; earnings_beat_rate's v2 column exists since the v2 writer shipped.
    old["momentum_composite"] = old.pop("mom_composite")
    old["news_volume"] = (None, "news_volume_7d")
    old["earnings_beat_rate"] = ("earnings_beat_rate", "earnings_beat_rate")
    assert factors.SIGNAL_COLUMN_MAP == old


def test_eligibility():
    from eligibility.registry import SIGNAL_ELIGIBILITY

    def norm(d):
        return {k: (v["description"], " ".join(textwrap.dedent(v["eligible_sql"]).split()))
                for k, v in d.items()}
    assert norm(factors.SIGNAL_ELIGIBILITY) == norm(SIGNAL_ELIGIBILITY)


def test_partition_holds():
    assert factors.partition_check() == ([], [])


def test_every_producer_fn_exists():
    for name, spec in factors.PIT_PRODUCERS.items():
        if spec["fn"]:
            assert callable(getattr(reconstruct_pit, spec["fn"], None)) or spec["fn"] == "pit_delivery", name
