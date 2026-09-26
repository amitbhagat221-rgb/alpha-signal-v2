"""Offline parse checks for sources/nselib_pull.py (nselib + DB monkeypatched)."""
import sys
import types
from datetime import date, timedelta

import pandas as pd

from sources import nselib_pull


def _fake_nselib(monkeypatch, **fns):
    cm = types.SimpleNamespace(**fns)
    pkg = types.ModuleType("nselib")
    pkg.capital_market = cm
    pkg.derivatives = cm
    monkeypatch.setitem(sys.modules, "nselib", pkg)
    monkeypatch.setattr(nselib_pull.time, "sleep", lambda s: None)


def test_bulk_deals_reads_nselib_price_column(monkeypatch):
    # Column names exactly as nselib.constants.bulk_deal_data_columns.
    frame = pd.DataFrame([{
        "Date": "25-SEP-2026", "Symbol": "RELIANCE", "SecurityName": "Reliance Industries",
        "ClientName": "SOME FUND", "Buy/Sell": "BUY", "QuantityTraded": "1,00,000",
        "TradePrice/Wght.Avg.Price": "1,400.50", "Remarks": "-",
    }])
    _fake_nselib(monkeypatch, bulk_deal_data=lambda from_date, to_date: frame.copy())
    monkeypatch.setattr(nselib_pull._http, "sid_map", lambda col="ticker": {"RELIANCE": "RELI"})
    got = []
    monkeypatch.setattr(nselib_pull, "insert_df", lambda df, t: got.append(df) or len(df))
    nselib_pull.pull_bulk_deals(months=1)
    row = got[0].iloc[0]
    assert row["price"] == 1400.5 and row["quantity"] == 100000 and row["client_name"] == "SOME FUND"


def test_fii_positioning_skips_loaded_dates(monkeypatch):
    asked = []

    def poi(trade_date):
        asked.append(trade_date)
        return pd.DataFrame()

    _fake_nselib(monkeypatch, participant_wise_open_interest=poi)
    loaded = [(date.today() - timedelta(days=d)).isoformat() for d in range(10)]
    monkeypatch.setattr(nselib_pull, "read_sql",
                        lambda q, params=None: pd.DataFrame({"trade_date": loaded}))
    nselib_pull.pull_fii_positioning(days_back=10)
    assert asked == []


def test_earnings_calendar_keeps_forward_dated_rows(monkeypatch):
    """earnings_calendar must bypass insert_df's >today+2d guard (it's forward-dated)."""
    fwd = (date.today() + timedelta(days=20)).strftime("%d-%b-%Y")
    frame = pd.DataFrame([{"symbol": "RELIANCE", "company": "Reliance", "purpose": "Results",
                           "bm_desc": "Q2", "date": fwd}])
    _fake_nselib(monkeypatch, event_calendar_for_equity=lambda from_date, to_date: frame.copy())
    monkeypatch.setattr(nselib_pull._http, "sid_map", lambda col="ticker": {"RELIANCE": "RELI"})
    got = []
    monkeypatch.setattr(nselib_pull, "_insert_or_ignore", lambda df, t: got.append((t, df)) or len(df))
    monkeypatch.setattr(nselib_pull, "insert_df", lambda df, t: 1 / 0)
    assert nselib_pull.pull_event_calendar() == 1
    assert got[0][0] == "earnings_calendar"
