"""sources.nse_insider: XBRL filing → insider_trades rows (offline; structure copied
from a real NSE PIT filing, IT_13962_WebXMLFile_20260926, trimmed to 2 disclosures)."""
from sources import nse_insider as ni

XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:in-bse-co="http://www.bseindia.com/xbrl/co/2017-09-15/in-bse-co"
            xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="MainI"/>
  <in-bse-co:NameOfTheCompany contextRef="MainI">DAMODAR INDUSTRIES LIMITED</in-bse-co:NameOfTheCompany>
  <in-bse-co:CategoryOfPerson contextRef="Disclosure1">Promoter Group</in-bse-co:CategoryOfPerson>
  <in-bse-co:NameOfThePerson contextRef="Disclosure1">Arunkumar Biyani</in-bse-co:NameOfThePerson>
  <in-bse-co:SecuritiesAcquiredOrDisposedNumberOfSecurity contextRef="Disclosure1">4200</in-bse-co:SecuritiesAcquiredOrDisposedNumberOfSecurity>
  <in-bse-co:SecuritiesAcquiredOrDisposedValueOfSecurity contextRef="Disclosure1">124110</in-bse-co:SecuritiesAcquiredOrDisposedValueOfSecurity>
  <in-bse-co:SecuritiesAcquiredOrDisposedTransactionType contextRef="Disclosure1">Sell</in-bse-co:SecuritiesAcquiredOrDisposedTransactionType>
  <in-bse-co:DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate contextRef="Disclosure1">2026-09-23</in-bse-co:DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate>
  <in-bse-co:CategoryOfPerson contextRef="Disclosure2">Promoter Group</in-bse-co:CategoryOfPerson>
  <in-bse-co:NameOfThePerson contextRef="Disclosure2">Manju Biyani</in-bse-co:NameOfThePerson>
  <in-bse-co:SecuritiesAcquiredOrDisposedNumberOfSecurity contextRef="Disclosure2">4000</in-bse-co:SecuritiesAcquiredOrDisposedNumberOfSecurity>
  <in-bse-co:SecuritiesAcquiredOrDisposedValueOfSecurity contextRef="Disclosure2">118119</in-bse-co:SecuritiesAcquiredOrDisposedValueOfSecurity>
  <in-bse-co:SecuritiesAcquiredOrDisposedTransactionType contextRef="Disclosure2">Buy</in-bse-co:SecuritiesAcquiredOrDisposedTransactionType>
  <in-bse-co:DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate contextRef="Disclosure2">2099-01-01</in-bse-co:DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate>
</xbrli:xbrl>"""

FILING = {"symbol": "DAMODARIND ", "companyName": "DAMODAR INDUSTRIES LIMITED",
          "xmlFileName": "https://nsearchives.nseindia.com/corporate/xbrl/IT_13962_WebXMLFile_20260926_200221686.xml"}


def test_parse_xbrl_one_record_per_disclosure_context():
    recs = sorted(ni.parse_xbrl(XML), key=lambda r: r["person"])
    assert [r["person"] for r in recs] == ["Arunkumar Biyani", "Manju Biyani"]
    assert recs[0] == {"person": "Arunkumar Biyani", "person_category": "Promoter Group",
                       "tx_type": "Sell", "shares": "4200", "value": "124110",
                       "trade_date": "2026-09-23"}


def test_rows_keep_the_old_vocabulary_and_drop_future_trades():
    rows = ni._rows_for_filing(FILING, ni.parse_xbrl(XML), "DAMO", "2026-09-27")
    assert len(rows) == 1                                   # 2099 trade is a glitch
    r = rows[0]
    assert (r["sid"], r["symbol"], r["transaction_type"], r["shares"]) == ("DAMO", "DAMODARIND", "Sell", 4200.0)
    assert abs(r["value_lakhs"] - 1.2411) < 1e-9             # rupees → lakhs
    assert r["source"] == "nse_pit"
    assert r["filing_id"] == "IT_13962_WebXMLFile_20260926_200221686.xml"


def test_direction_maps_onto_stored_values():
    assert [ni._direction(x) for x in ("Buy", "Acquisition", "Sell", "Disposal", "Pledge Creation",
                                       "Pledge Revoke", "Pledge Invocation", "Gift")] == \
        ["Buy", "Buy", "Sell", "Sell", "Pledge", "Pledge Revoke", "Pledge Invoke", "Gift"]


class _Resp:
    def __init__(self, status=200, body=b"", js=None):
        self.status_code, self.content, self._js = status, body, js
        self.text = body.decode() if isinstance(body, bytes) else body
        self.headers = {}

    def json(self):
        return self._js

    def raise_for_status(self):
        pass


def _offline(monkeypatch, listing, seen=()):
    import time
    import pandas as pd
    import requests
    from sources import _http
    calls, written = [], []

    def fake_request(self, method, url, **kw):
        calls.append((url, dict(kw.get("params") or {})))
        if url.rstrip("/") == "https://www.nseindia.com":
            return _Resp(200, b"home")
        if url.endswith("/api/corporates-pit-gg"):
            return _Resp(200, b"{}", {"data": listing})
        if url.endswith(".xml"):
            return _Resp(200, XML)
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(_http, "_cffi", None)
    monkeypatch.setattr(_http, "_LAST_CALL", {})
    monkeypatch.setattr(_http, "sid_map", lambda col="ticker": {"DAMODARIND": "DAMO"})
    monkeypatch.setattr(ni, "read_sql", lambda q, params=None: pd.DataFrame({"filing_id": list(seen)}))
    monkeypatch.setattr(ni, "insert_df", lambda df, t: written.append((t, df)) or len(df))
    return calls, written


def test_fetch_lists_via_gg_and_fetches_only_new_universe_filings(monkeypatch):
    from datetime import date
    other = {**FILING, "symbol": "NOTOURS", "xmlFileName": "https://nsearchives.nseindia.com/x/IT_2.xml"}
    old = {**FILING, "xmlFileName": "https://nsearchives.nseindia.com/x/IT_OLD.xml"}
    calls, written = _offline(monkeypatch, [FILING, other, old], seen=["IT_OLD.xml"])
    n = ni.fetch_insider(date(2026, 9, 20), date(2026, 9, 27))
    xml_calls = [u for u, _ in calls if u.endswith(".xml")]
    assert xml_calls == [FILING["xmlFileName"]]                 # not NOTOURS, not the stored one
    assert [p for u, p in calls if u.endswith("-gg")] == [
        {"index": "equities", "from_date": "20-09-2026", "to_date": "27-09-2026"}]
    assert n == 1 and written[0][0] == "insider_trades"         # 2099 disclosure dropped


def test_empty_listing_over_a_week_fails_loudly(monkeypatch):
    import pytest
    from datetime import date
    _offline(monkeypatch, [])
    with pytest.raises(RuntimeError, match="0 filings"):
        ni.fetch_insider(date(2026, 9, 20), date(2026, 9, 27))
