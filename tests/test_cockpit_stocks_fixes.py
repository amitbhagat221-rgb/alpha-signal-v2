"""Stock-page review fixes: own-name bulk deals, calendar price window, number wording."""
import formatting
from cockpit import api


def test_company_name_spellings_match():
    sun = api._core_name("Sun Pharmaceutical Industries Ltd")
    assert api._is_company("Sun Pharma Industries Ltd", sun)
    thy = api._core_name("Thyrocare Technologies Limited")
    assert api._is_company("Thyrocare Tech Ltd", thy)
    assert not api._is_company("Goldman Sachs Fund", sun)
    assert not api._is_company("Sun Life Insurance", api._core_name("Sunteck Realty Ltd"))


def test_zero_and_negative_formats():
    assert formatting.pct(-0.2, 0, signed=True) == "0%"
    assert formatting.pct(-1.4, 0, signed=True) == "-1%"
    assert formatting.inr(-0.16, 2) == "-₹0.16"
    assert formatting.long_date("2023-10-25") == "25 Oct 2023"


def test_price_window_is_calendar_days(monkeypatch):
    seen = {}
    monkeypatch.setattr(api.db, "rows", lambda sql, params=None: seen.setdefault("sql", sql) and seen.setdefault("params", params) and [])
    api.get_price_series_extended("X", days=366)
    assert "-366 days" in seen["params"] and "LIMIT" not in seen["sql"]
