"""One analyst target set per stock: the average is written with the range it came with
(2026-10: the daily broker aggregate overwrote Yahoo's average, leaving it outside its low-high)."""
import sqlite3
import sys
import types
from datetime import date

import pytest

import db
from validators.plausibility import pt_outside_range, pt_outside_range_sql

TODAY = date.today().isoformat()


def test_outside_range_rule():
    assert pt_outside_range(1888, 1000, 1615) and pt_outside_range(10, 20, 30)
    assert not pt_outside_range(1500, 1000, 1615) and not pt_outside_range(1000, 1000, 1615)
    assert not pt_outside_range(1500, None, None) and not pt_outside_range(None, 1, 2)
    assert "price_target_low" in pt_outside_range_sql("price_target", "price_target_low", "price_target_high")


def test_yahoo_mean_outside_its_range_is_dropped(monkeypatch):
    from sources import yfinance_analyst as ya
    info = {"symbol": "LODHA.NS", "targetMeanPrice": 1888, "targetMedianPrice": 1388,
            "targetHighPrice": 1615, "targetLowPrice": 1000, "numberOfAnalystOpinions": 1}
    fake = types.SimpleNamespace(Ticker=lambda t: types.SimpleNamespace(info=info, recommendations=None))
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    out = ya._fetch_one("LODHA")
    assert out["target_mean"] is None and out["target_median"] == 1388
    info["targetMeanPrice"] = 1300
    assert ya._fetch_one("LODHA")["target_mean"] == 1300


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA_PATH.read_text())
    c.commit()
    monkeypatch.setattr(db, "DB_PATH", path)
    yield c
    c.close()


def test_broker_aggregate_leaves_yahoo_average_alone(conn):
    from sources import moneycontrol_recos as mc
    for sid in ("Y", "M"):
        conn.execute("INSERT INTO stock_prices (sid, date, close) VALUES (?, ?, 100)", (sid, TODAY))
        conn.execute("INSERT INTO broker_recommendations (sid, broker, reco_date, reco_type, target_price, fetched_at) "
                     "VALUES (?, 'B1', ?, 'BUY', 150, ?)", (sid, TODAY, TODAY))
    conn.execute("INSERT INTO analyst_consensus (sid, price_target, price_target_low, price_target_median, "
                 "price_target_high, total_analysts, pt_source, fetched_at) "
                 "VALUES ('Y', 110, 90, 110, 130, 7, 'yfinance', ?)", (TODAY,))
    conn.execute("INSERT INTO analyst_consensus (sid, fetched_at) VALUES ('M', ?)", (TODAY,))
    conn.commit()
    mc.aggregate_consensus()
    rows = {r[0]: r[1:] for r in conn.execute(
        "SELECT sid, price_target, total_analysts, buy_pct FROM analyst_consensus")}
    assert rows["Y"] == (110, 7, 100.0)         # Yahoo's set intact, broker buy_pct added
    assert rows["M"] == (150, 1, 100.0)         # no Yahoo coverage: broker mean fills in
