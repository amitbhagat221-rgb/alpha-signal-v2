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
    monkeypatch.setattr(macro_gov.macro_official, "fetch_all", lambda dry_run=False: 0)   # MoSPI/OEA dead
    monkeypatch.setattr(macro_gov, "polite_get",
                        lambda url, timeout=None: _Resp("observation_date,X\n2026-01-01,1.5\n2026-02-01,1.6\n"))
    saved = []
    monkeypatch.setattr(macro_gov, "upsert_df", lambda df, t: saved.append(t))
    with pytest.raises(RuntimeError, match="0 rows from MoSPI/OEA"):
        macro_gov.compute()
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
    with pytest.raises(RuntimeError, match="yfinance analyst: 0 of 2"):
        ya.compute(ticker=None)


# ── bhavcopy: the one CRITICAL fetcher (plan 0015 Phase 0) ──

def _bhav_env(monkeypatch, newest, fetch_result):
    """nse.compute() for a fixed today (Tue 2026-09-29) with offline stubs."""
    import datetime as _dt
    from sources import nse

    class _D(_dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 29)
    monkeypatch.setattr(nse, "date", _D)
    monkeypatch.setattr(nse, "_loaded_dates", lambda since: set())
    monkeypatch.setattr(nse, "_fetch_date", lambda d: fetch_result)
    monkeypatch.setattr(nse, "read_sql", lambda q, params=None: pd.DataFrame({"d": [newest]}))
    return nse


def test_bhavcopy_raises_on_download_error(monkeypatch):
    nse = _bhav_env(monkeypatch, "2026-09-28", (None, ["ConnectionError: unreachable"]))
    with pytest.raises(RuntimeError, match="download failed"):
        nse.compute()


def test_bhavcopy_404_is_holiday_not_failure(monkeypatch):
    nse = _bhav_env(monkeypatch, "2026-09-28", (None, ["404 — likely holiday"]))
    assert nse.compute() == 0            # nothing new, prices fresh → a no-op, not a failure


def test_bhavcopy_raises_when_prices_stale(monkeypatch):
    # newest Wed 09-23 → Thu, Fri, Mon missing before Tue 09-29 = 3 weekdays
    nse = _bhav_env(monkeypatch, "2026-09-23", (None, ["404 — likely holiday"]))
    with pytest.raises(RuntimeError, match="stale"):
        nse.compute()


def test_bhavcopy_two_holidays_tolerated(monkeypatch):
    nse = _bhav_env(monkeypatch, "2026-09-24", (None, ["404 — likely holiday"]))  # Fri, Mon missing
    assert nse.compute() == 0
