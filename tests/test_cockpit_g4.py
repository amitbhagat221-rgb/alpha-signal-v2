"""Mutual-fund list sort / debt guard and news text helpers (frontend clean-up G4)."""
import pandas as pd

from cockpit import api, mf


def _pool():
    return pd.DataFrame({
        "scheme_code": ["a", "b", "c", "d"],
        "scheme_name": ["A", "B", "C", "D"], "amc": ["x"] * 4,
        "category_norm": ["Equity / Large Cap"] * 4, "plan_type": ["DIRECT"] * 4,
        "option_type": ["GROWTH"] * 4,
        "nav": [10.0, 300.0, 55.0, None], "nav_date": ["2026-09-30"] * 3 + [None],
        "ret_1y": [1.0] * 4, "ret_3y_cagr": [1.0] * 4, "ret_5y_cagr": [1.0] * 4,
        "sharpe_1y": [1.0] * 4, "max_drawdown": [-1.0] * 4,
        "composite_score": [20.0, 40.0, 30.0, 10.0], "score_percentile": [100.0] * 4,
        "peer_rank_3y": [1] * 4, "investable": [1] * 4,
    })


def test_nav_sort_is_numeric_descending_and_missing_last(monkeypatch):
    monkeypatch.setattr(mf, "_mf_universe_pool", lambda: _pool())
    rows = mf.get_mf_universe_overview(sort="nav")["rows"]
    assert [r["scheme_code"] for r in rows] == ["b", "c", "a", "d"]


def test_default_sort_breaks_percentile_ties_by_score(monkeypatch):
    monkeypatch.setattr(mf, "_mf_universe_pool", lambda: _pool())
    rows = mf.get_mf_universe_overview()["rows"]
    assert [r["scheme_code"] for r in rows] == ["b", "c", "a", "d"]


def test_debt_guard_covers_every_category_spelling():
    assert mf.is_debt_category("Income/Debt Oriented Schemes - Banking and PSU Debt Fund")
    assert mf.is_debt_category("Debt / Liquid")
    assert not mf.is_debt_category("Equity / Large Cap")
    assert not mf.is_debt_category(None)


def test_clean_news_text_unescapes_once_or_twice_escaped():
    assert api.clean_news_text("S&amp;P 500") == "S&P 500"
    assert api.clean_news_text("oil &amp;amp; gas") == "oil & gas"
    assert api.clean_news_text(None) == ""


def test_dedupe_headlines_by_normalised_title():
    rows = [{"title": "Oil &amp; gas jumps"}, {"title": "OIL & GAS jumps!"}, {"title": "Other"}]
    assert [r["title"] for r in api.dedupe_headlines(rows)] == ["Oil &amp; gas jumps", "Other"]


def test_news_source_names_cover_feed_ids():
    assert api.news_source_name("et_markets") == "Economic Times Markets"
    assert api.news_source_name("livemint_markets") == "Mint Markets"
    assert api.news_source_name("gnews_trade") == "Google News: Trade"
    assert api.news_source_name("unknown_feed") == "unknown_feed"


def test_equity_benchmark_only_for_equity_categories():
    for cat in ("Equity / Large Cap", "Equity Schemes - Flexi Cap Fund", "Index Funds - Equity Funds",
                "Equity Schemes - ELSS- Tax Saver Fund"):
        assert mf.has_equity_benchmark(cat), cat
    for cat in ("Income/Debt Oriented Schemes - Banking and PSU Debt Fund", "Debt / Liquid",
                "Hybrid Schemes - Aggressive Hybrid Fund", "Hybrid / Arbitrage", "FoF / Overseas",
                "Exchange Traded Funds (ETFs) - Gold ETF", "Index Funds - Debt Funds", None):
        assert not mf.has_equity_benchmark(cat), cat
