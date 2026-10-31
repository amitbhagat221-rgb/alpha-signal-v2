"""Strategy views for /options/capital and /options/live (option_strategy, plan 0029) — offline, temp DB."""

import sqlite3

import pytest

import db
import option_strategy as os_
from sources.fno_iv import R, _black76

U, E, T0, T1 = "SENSEX", "2026-10-29", "2026-10-27", "2026-10-28"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "s.db"
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA_PATH.read_text())
    rows = []
    for td, S, px in ((T0, 73500.0, {("PE", 71800): 25.0, ("CE", 75300): 18.75, ("PE", 73500): 420.0, ("CE", 73500): 440.0,
                                       ("PE", 70500): 4.85, ("CE", 76600): 3.2}),
                      (T1, 73246.0, {("PE", 71800): 18.4, ("CE", 75300): 3.1, ("PE", 73200): 260.0, ("CE", 73200): 300.0,
                                       ("PE", 70500): 3.25, ("CE", 76600): 1.35})):
        for (o, k), v in px.items():
            rows.append((U, E, float(k), o, td, v, S, 1000))
    c.executemany("INSERT INTO fno_bhav (symbol, instrument_type, expiry_date, strike, option_type, trade_date, settle, "
                  "underlying_price, oi) VALUES (?, 'IDO', ?, ?, ?, ?, ?, ?, ?)", rows)
    c.commit()
    monkeypatch.setattr(db, "DB_PATH", path)
    yield c
    c.close()


def _trade(**over):
    r = {"underlying": U, "expiry": E, "entry_date": T0, "forward": 73573.7, "lot": 20, "status": "OPEN",
         "short_call": 75300.0, "short_put": 71800.0, "call_entry": 18.75, "put_entry": 25.0, "entry_cost_pts": 2.86,
         "net_rs": None, "settle_index": None, "mark": {"mtm_rs": (43.75 - 21.5 - 2.86) * 20}, "margin_source": "kite",
         "span_rs": 104000, "exposure_rs": 58860, "expiry_extra_rs": 58860, "expiry_margin_rs": 221720,
         "w_call": 76600.0, "w_put": 70500.0, "w_cost_pts": 8.3, "w_span_rs": 1, "w_exposure_rs": 1, "w_extra_rs": 1,
         "w_expiry_margin_rs": 1, "w_pnl": None, "w_max_loss_rs": 25000}
    r.update(over)
    return r


def test_open_paper_trade_is_priced_at_the_latest_settle(conn):
    v = os_.paper(_trade())
    assert [(l["cp"], l["K"], l["side"], l["entry"], l["now"]) for l in v["legs_naked"]] == \
        [("P", 71800.0, -1, 25.0, 18.4), ("C", 75300.0, -1, 18.75, 3.1)]
    assert v["spot"] == 73246.0 and v["now"].startswith(T1 + "T15:30")
    T = os_.years(os_.close_ts(T1), os_.close_ts(E))
    for l in v["legs_naked"]:          # the builder's Black-76 at (spot, now) gives back the last settle
        assert abs(_black76(v["spot"], l["K"], T, l["iv"], l["cp"]) - l["now"]) < 1e-6
    w = v["legs_winged"]
    assert [(l["K"], l["side"]) for l in w] == [(70500.0, 1), (71800.0, -1), (75300.0, -1), (76600.0, 1)]
    assert abs(v["cost_winged"] - (2.86 + 8.3 - 4.85 - 3.2)) < 1e-9          # wing charges only, prices are legs
    assert v["oi"] and v["oi_date"] == T1 and v["r"] == R and v["step"] == 100


def test_settled_paper_trade_ends_at_intrinsic(conn):
    v = os_.paper(_trade(status="SETTLED", settle_index=75500.0, net_rs=-1000.0))
    assert v["spot"] == 75500.0 and v["now"].startswith(E + "T15:30")
    assert [l["now"] for l in v["legs_naked"]] == [0.0, 200.0]
    assert v["pnl_naked"] == -1000.0


def test_live_view_groups_open_legs_and_signs_quantities(conn):
    L = {"open": [
        {"underlying": U, "expiry": E, "source": "live", "tradingsymbol": "SENSEX26OCT71700PE", "option_type": "PE",
         "strike": 71700.0, "net_qty": -300, "sell_avg": 22.19, "buy_avg": None, "mark_price": 25.0, "lot": 20,
         "mark_at": "2026-10-28T09:31:32+00:00", "mtm_rs": -800.0, "charges_rs": 30.0, "margin_rs": 3.3e6},
        {"underlying": U, "expiry": E, "source": "live", "tradingsymbol": "SENSEX26OCT70500PE", "option_type": "PE",
         "strike": 70500.0, "net_qty": 300, "sell_avg": None, "buy_avg": 5.0, "mark_price": 4.0, "lot": 20,
         "mark_at": "2026-10-28T09:31:32+00:00", "mtm_rs": -310.0, "charges_rs": 10.0},
        {"underlying": U, "expiry": E, "source": "live", "tradingsymbol": "SENSEX26OCT75200CE", "option_type": "CE",
         "strike": 75200.0, "net_qty": 0, "mark_at": None}],          # bought back: not in the builder
        "sizing": {"quote": {"at": "2026-10-28T09:31:26+00:00", "markets": {U: {"spot": 73300.0}}}}}
    (v,) = os_.live(L)
    assert v["key"] == f"{U}:{E}:live" and v["spot"] == 73300.0 and v["cost_rs"] == 40.0
    assert [(l["K"], l["side"], l["qty"], l["entry"]) for l in v["legs"]] == [(70500.0, 1, 300, 5.0), (71700.0, -1, 300, 22.19)]
    assert all(l["iv"] for l in v["legs"]) and v["margin_rs"] == 3.3e6 and v["mtm_rs"] == -1110.0

