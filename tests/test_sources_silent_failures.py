"""Harvesters must RAISE when a real batch produced nothing (CLAUDE.md "silent
failures are the enemy"). Offline: network + DB writes are monkeypatched."""
import json

import pandas as pd
import pytest
import requests

from sources import _http


class _Resp:
    def __init__(self, text):
        self.text = text
        self.status_code = 200

    def json(self):
        return json.loads(self.text)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(_http.time, "sleep", lambda s: None)


def _down(*a, **k):
    raise requests.ConnectionError("unreachable")


def test_tickertape_analyst_raises_when_every_page_fails(monkeypatch):
    from sources import tickertape_analyst as ta
    monkeypatch.setattr(ta, "read_sql", lambda q, params=None: pd.DataFrame(
        {"sid": ["A", "B", "C"], "slug": ["stocks/a-A", "stocks/b-B", "stocks/c-C"]}))
    monkeypatch.setattr(ta, "polite_get", _down)
    monkeypatch.setattr(ta, "upsert_df", lambda df, t: pytest.fail("must not write"))
    with pytest.raises(RuntimeError, match="0 of 3"):
        ta.compute()


def test_tickertape_analyst_writes_both_tables(monkeypatch):
    from sources import tickertape_analyst as ta
    blob = {"props": {"pageProps": {
        "securitySummary": {"forecast": {"totalReco": 12, "percBuyReco": 75}},
        "forecastsHistory": {"eps": [{"date": "2025-03-31", "value": 10}, {"date": "2026-03-31", "value": 12}],
                             "revenue": [], "price": [{"date": "2025-12-28", "value": 999}]}}}}
    html = f'<html><script id="__NEXT_DATA__">{json.dumps(blob)}</script></html>'
    monkeypatch.setattr(ta, "read_sql", lambda q, params=None: pd.DataFrame(
        {"sid": ["A", "B"], "slug": ["stocks/a-A", "stocks/b-B"]}))
    monkeypatch.setattr(ta, "polite_get", lambda url, headers=None: _Resp(html))
    written = {}
    monkeypatch.setattr(ta, "upsert_df", lambda df, t: written.setdefault(t, []).append(df))
    assert ta.compute() == 2
    assert len(written["analyst_consensus"][0]) == 2
    fh = written["forecast_history"][0]
    assert set(fh["metric"]) == {"eps"} and len(fh) == 4   # price rows never ingested (ADR 0045)


def test_nse_bulk_raises_when_bulk_file_unreachable(monkeypatch):
    from sources import nse_bulk
    monkeypatch.setattr(nse_bulk._http, "polite_get", _down)
    with pytest.raises(RuntimeError, match="bulk.csv yielded 0"):
        nse_bulk.fetch_today()


def test_nse_bulk_quiet_on_duplicate_only_day(monkeypatch):
    from sources import nse_bulk
    csv = ("Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
           "25-Sep-2026,RELIANCE,Reliance,SOME FUND,BUY,100000,1400.5,-\n")
    monkeypatch.setattr(nse_bulk._http, "polite_get", lambda url, headers=None: _Resp(csv))
    monkeypatch.setattr(nse_bulk._http, "sid_map", lambda col="ticker": {"RELIANCE": "RELI"})
    seen = []
    monkeypatch.setattr(nse_bulk, "insert_df", lambda df, t: seen.append(df) or 0)   # all dupes
    assert nse_bulk.fetch_today() == 0
    assert seen[0]["client_name"].iloc[0] == "SOME FUND"   # not the Security Name column


def test_macro_gov_raises_naming_dead_source_after_saving_the_rest(monkeypatch):
    from sources import macro_gov
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        if "data.gov.in" in url:
            raise requests.Timeout("read timed out")
        return _Resp("observation_date,X\n2026-01-01,1.5\n2026-02-01,1.6\n")

    monkeypatch.setattr(macro_gov, "polite_get", fake_get)
    saved = []
    monkeypatch.setattr(macro_gov, "upsert_df", lambda df, t: saved.append(t))
    with pytest.raises(RuntimeError, match="0 rows from data.gov.in"):
        macro_gov.compute()
    assert sum("data.gov.in" in u for u in calls) == 1   # fail-fast after first timeout
    assert "macro_history" in saved                        # FRED rows still written


def test_regulatory_incremental_raises_on_zero_articles(monkeypatch):
    from sources import regulatory_harvester as rh
    monkeypatch.setattr(rh, "polite_get", _down)
    with pytest.raises(RuntimeError, match="0 articles"):
        rh.harvest_incremental()


def test_yfinance_analyst_raises_when_no_stock_has_data(monkeypatch):
    from sources import yfinance_analyst as ya

    def fake_read_sql(q, params=None):
        if "FROM stocks" in q:
            return pd.DataFrame({"sid": ["A", "B"], "ticker": ["AAA", "BBB"], "cap_tier": ["LARGE"] * 2})
        if "stock_prices" in q:
            return pd.DataFrame({"sid": [], "close": []})
        if "price_target IS NULL" in q:
            return pd.DataFrame({"sid": []})
        return pd.DataFrame({"sid": [], "price_target": [], "price_target_changed_at": []})

    monkeypatch.setattr(ya, "read_sql", fake_read_sql)
    monkeypatch.setattr(ya, "_fetch_one", lambda t, sid_for_gate=None: None)
    monkeypatch.setattr(ya, "DELAY", 0)
    with pytest.raises(RuntimeError, match="yfinance analyst: 0 of 2"):
        ya.compute(ticker=None)
