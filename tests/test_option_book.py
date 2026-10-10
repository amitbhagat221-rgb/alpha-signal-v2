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


def test_strike_pick_takes_the_nearest_0_05_delta():
    deltas = {"C": [(0.12, 23200.0), (0.051, 23400.0), (0.02, 23600.0)],
              "P": [(0.08, 22000.0), (0.047, 21900.0), (0.03, 21800.0)]}
    assert ob.nearest(deltas, 0.05) == {"C": 23400.0, "P": 21900.0}


def test_settlement_is_intrinsic_on_the_index():
    tr = {"rule_id": "r", "underlying": "NIFTY", "expiry": "2026-10-13", "short_call": 23000.0,
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
