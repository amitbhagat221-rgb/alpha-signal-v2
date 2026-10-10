"""bulk_deals stores the counterparty (Client Name), never the Security Name, and its
uniqueness key keeps a same-day BUY and SELL of one quantity apart."""
import sqlite3
from pathlib import Path

from sources import nse_bulk

_HEAD = "Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
_ROWS = ("10-OCT-2026,LODHA,Lodha Developers Limited,FMRC FIDELITY ADVISOR FUND,BUY,13264600,937.85,-\n"
         "10-OCT-2026,LODHA,Lodha Developers Limited,HIGHTOWN CONSTRUCTIONS PRIVATE LIMITED,SELL,17424032,937.85,-\n")


def test_client_name_is_the_counterparty_not_the_security(monkeypatch):
    monkeypatch.setattr(nse_bulk._http, "sid_map", lambda: {"LODHA": "LOD"})
    df = nse_bulk._parse_deals(_HEAD + _ROWS, "bulk")
    assert list(df["client_name"]) == ["FMRC FIDELITY ADVISOR FUND", "HIGHTOWN CONSTRUCTIONS PRIVATE LIMITED"]
    assert not df["client_name"].str.contains("Lodha Developers").any()


def test_client_wins_whatever_the_column_order(monkeypatch):
    monkeypatch.setattr(nse_bulk._http, "sid_map", lambda: {"LODHA": "LOD"})
    head = "Date,Symbol,Client Name,Security Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
    row = "10-OCT-2026,LODHA,SOME FUND,Lodha Developers Limited,BUY,100,937.85,-\n"
    assert list(nse_bulk._parse_deals(head + row + row.replace("100", "200"), "bulk")["client_name"]) == ["SOME FUND"] * 2


def test_same_client_buy_and_sell_of_one_quantity_are_both_kept():
    conn = sqlite3.connect(":memory:")
    conn.executescript(Path(__file__).resolve().parent.parent.joinpath("schema.sql").read_text())
    ins = ("INSERT OR IGNORE INTO bulk_deals (sid, symbol, client_name, deal_type, buy_sell, quantity, price, deal_date) "
           "VALUES ('LOD','LODHA','X FUND','bulk',?,100,10,'2026-10-10')")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(ins, ("BUY",)); conn.execute(ins, ("SELL",)); conn.execute(ins, ("SELL",))
    assert conn.execute("SELECT COUNT(*) FROM bulk_deals").fetchone()[0] == 2
