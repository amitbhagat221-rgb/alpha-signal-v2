"""Every AMFI category label stored in mf_scheme_master maps to a compact 'Family / Sub' label."""
import os
import sqlite3

import pytest

from sources.mf_amfi_master import _normalise_category


def test_plural_and_singular_labels_merge():
    a = _normalise_category("Equity Scheme - Mid Cap Fund")
    assert a == _normalise_category("Equity Schemes - Mid Cap Fund") == "Equity / Mid Cap"
    assert _normalise_category("Hybrid Schemes - Arbitrage Fund") == _normalise_category("Hybrid Scheme - Arbitrage Fund")
    assert _normalise_category("Income/Debt Oriented Schemes - Liquid Fund") == "Debt / Liquid"


def test_overseas_and_debt_index_funds_leave_the_nifty_group():
    raw = "Other Scheme - Index Funds"
    assert _normalise_category(raw, "ICICI Prudential NASDAQ 100 Index Fund") == "Index / Overseas"
    assert _normalise_category(raw, "Motilal Oswal S&P 500 Index Fund") == "Index / Overseas"
    assert _normalise_category(raw, "Axis CRISIL IBX 50:50 Gilt Plus SDL June 2028 Index Fund") == "Index / Debt"
    assert _normalise_category(raw, "UTI Nifty 50 Index Fund") == "Index / Equity"
    from signals.mf_metrics import has_equity_benchmark
    assert not has_equity_benchmark("Index / Overseas")
    assert not has_equity_benchmark("Index / Debt")
    assert has_equity_benchmark("Index / Equity")


def test_every_stored_raw_category_is_mapped():
    path = os.environ.get("ALPHA_DB", "")
    if not path or not os.path.exists(path):
        pytest.skip("no live DB")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        raws = [r[0] for r in conn.execute("SELECT DISTINCT category_raw FROM mf_scheme_master WHERE category_raw IS NOT NULL")]
    except sqlite3.OperationalError:
        pytest.skip("no mf_scheme_master")
    bad = [r for r in raws if " / " not in (_normalise_category(r) or "")]
    assert not bad, bad
