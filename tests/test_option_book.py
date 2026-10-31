"""Option paper book (plan 0022): entry-day placement, strike pick, settlement — offline."""

import pandas as pd

import option_book as ob

HOL = {"2026-10-02", "2026-10-20", "2026-11-10"}


def test_entry_day_is_two_sessions_before_expiry():
    assert ob.entry_day("2026-10-13", HOL) == "2026-10-09"        # Tue expiry → Fri entry (weekend skipped)
    assert ob.entry_day("2026-10-15", HOL) == "2026-10-13"        # Thu → Tue
    assert ob.entry_day("2026-10-06", HOL) == "2026-10-01"        # holiday Fri 2 Oct skipped


def test_sessions_skip_weekends_and_holidays():
    from datetime import date
    assert not ob.is_session(date(2026, 10, 10), HOL)             # Saturday
    assert not ob.is_session(date(2026, 10, 20), HOL)             # Dussehra
    assert ob.is_session(date(2026, 10, 19), HOL)


def test_lot_sizes_follow_the_measured_history():
    assert ob.lot_size("NIFTY", "2020-03-11") == 75
    assert ob.lot_size("NIFTY", "2022-06-01") == 50
    assert ob.lot_size("NIFTY", "2026-10-09") == 65
    assert ob.lot_size("SENSEX", "2026-10-13") == 20


def test_contract_keeps_its_listing_lot_across_a_revision():
    # NIFTY 25 → 75 revision: the 2024-12-26 weekly was listed at 25, entered 2024-12-24 (table says 25 then, 75 after)
    assert ob.lot_size("NIFTY", "2024-12-26") == 75                       # by date alone: wrong for that contract
    assert ob.lot_size("NIFTY", "2024-12-26", "2024-12-26") == 25
    assert ob.lot_size("NIFTY", "2025-12-30", "2025-12-30") == 75         # 75 → 65: old contract keeps 75
    assert ob.lot_size("NIFTY", "2025-12-30", "2026-01-06") == 65         # a contract listed after takes the new lot
    assert ob.lot_size("NIFTY", "2021-07-05", "2021-07-08") == 75
    assert ob.lot_size("SENSEX", "2025-01-24", "2025-01-28") == 10
    assert ob.lot_size("SENSEX", "2025-01-01", "2025-01-03") == 10        # entered the day the table flips to 20
    assert ob.lot_size("NIFTY", "2026-10-09", "2026-10-13") == 65          # paper-book contracts unchanged


def test_strike_pick_takes_the_nearest_0_05_delta():
    deltas = {"C": [(0.12, 23200.0), (0.051, 23400.0), (0.02, 23600.0)],
              "P": [(0.08, 22000.0), (0.047, 21900.0), (0.03, 21800.0)]}
    assert ob.nearest(deltas, 0.05) == {"C": 23400.0, "P": 21900.0}


def test_settlement_is_intrinsic_on_the_index():
    tr = {"rule_id": "r", "underlying": "NIFTY", "expiry": "2026-10-13", "entry_date": "2026-10-09", "short_call": 23000.0,
          "short_put": 21950.0, "credit_pts": 13.6, "entry_cost_pts": 0.9, "lot": 65, "margin_rs": 176000.0}
    calm = ob.settle_trade(tr, 22500.0)
    assert calm["call_exit"] == 0 and calm["put_exit"] == 0
    assert round(calm["net_pts"], 2) == 12.7 and round(calm["net_rs"], 1) == 825.5
    crash = ob.settle_trade(tr, 21800.0)                           # put 150 points in the money
    assert crash["put_exit"] == 150.0 and round(crash["net_pts"], 2) == -137.3
    assert crash["ret_on_margin"] < 0


def test_slice_deltas_reads_a_chain_frame():
    rows = []
    for k, c, p in ((22400, 160.0, 60.0), (22500, 100.0, 100.0), (22600, 60.0, 160.0),
                    (23000, 6.0, 500.0), (22000, 500.0, 7.0)):
        rows += [{"option_type": "CE", "strike": float(k), "settle": c, "volume": 10},
                 {"option_type": "PE", "strike": float(k), "settle": p, "volume": 10}]
    F, deltas = ob.slice_deltas(pd.DataFrame(rows), "2026-10-09", "2026-10-13")
    assert 22400 < F < 22600
    assert {K for _, K in deltas["C"]} >= {23000.0} and {K for _, K in deltas["P"]} >= {22000.0}


def test_settlement_row_carries_every_not_null_column():
    """The settlement upsert's INSERT half is checked for NOT NULL before it turns into an
    update: a row without entry_date failed the first real settlement (2026-10-14)."""
    import re
    from db import SCHEMA_PATH
    ddl = re.search(r"CREATE TABLE IF NOT EXISTS option_paper_trades \((.*?)\n\);", SCHEMA_PATH.read_text(), re.S).group(1)
    required = set(re.findall(r"^\s+(\w+)\s+\w+\s+NOT NULL", ddl, re.M))
    tr = {"rule_id": "r", "underlying": "NIFTY", "expiry": "2026-10-13", "entry_date": "2026-10-09",
          "short_call": 23000.0, "short_put": 21950.0, "credit_pts": 13.6, "entry_cost_pts": 0.9,
          "lot": 65, "margin_rs": 176000.0}
    assert required and required <= set(ob.settle_trade(tr, 22500.0)), required - set(ob.settle_trade(tr, 22500.0))


def test_expiry_day_extra_is_two_percent_of_each_short_legs_notional():
    assert abs(ob.expiry_day_extra(73_124.0, 300) - 0.02 * 73_124.0 * 300 * 2) < 1e-6   # 15 SENSEX lots ≈ ₹8.77 L
    assert ob.expiry_day_extra(25_800.0, 65, short_legs=1) == 0.02 * 25_800.0 * 65


def test_margin_parts_split_span_exposure_and_expiry_extra():
    p = ob.margin_parts(159_000.0, 22_600.0, 65)          # one NIFTY lot, Kite quote ₹1.59 L
    assert abs(p["exposure_rs"] - 0.02 * 22_600 * 65 * 2) < 1e-6
    assert abs(p["span_rs"] + p["exposure_rs"] - 159_000.0) < 1e-6
    assert abs(p["expiry_margin_rs"] - (159_000.0 + p["expiry_extra_rs"])) < 1e-6


def test_wing_view_prices_the_same_trade_with_wings(monkeypatch):
    import pandas as pd
    chain = pd.DataFrame({"option_type": ["CE", "CE", "CE", "PE", "PE", "PE"],
                          "strike": [23000.0, 23400.0, 23450.0, 22000.0, 21600.0, 21550.0],
                          "settle": [8.0, 3.0, 2.5, 9.0, 3.5, 3.0]})
    monkeypatch.setattr(ob, "read_sql", lambda sql, params=None: chain)
    r = {"underlying": "NIFTY", "entry_date": "2026-10-23", "expiry": "2026-10-27", "forward": 22500.0, "lot": 65,
         "short_call": 23000.0, "short_put": 22000.0, "credit_pts": 17.0, "entry_cost_pts": 0.9, "status": "SETTLED",
         "settle_index": 21000.0, "net_rs": -60_000.0}
    w = ob.wing_view(r)
    assert (w["w_call"], w["w_put"]) == (23400.0, 21600.0)        # first traded strikes 1.75 % (393.75 pts) beyond
    cost, pay = w["w_cost_pts"], 21600.0 - 21000.0                 # the put wing finishes 600 in the money
    assert cost > 3.0 + 3.5
    assert abs(w["w_pnl"] - (-60_000.0 + (pay - cost - ob.STT_EXERCISE * pay) * 65)) < 1e-6
    assert abs(w["w_margin_rs"] - (0.04 + 400 / 22500) * 22500 * 65) < 1e-6
    assert w["w_expiry_margin_rs"] == w["w_margin_rs"] + ob.expiry_day_extra(22500.0, 65)
    assert abs(w["w_max_loss_rs"] - (400 - 17.0 + 0.9 + cost) * 65) < 1e-6
    assert ob.wing_view({**r, "forward": None}) == {}
