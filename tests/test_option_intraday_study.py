"""Fill logic of the intraday stops / wings / sizing study — synthetic minute frames, offline."""

import pandas as pd
import pytest

import option_book as ob
from tools import option_intraday_study as st


def bars(rows):
    """rows: (day, 'HH:MM', open, close) → a leg's minute frame (days as ISO strings, like the loader)."""
    d = pd.DataFrame(rows, columns=["trading_day", "hm", "open", "close"])
    d["ts"] = pd.to_datetime(d.trading_day + " " + d.hm).dt.tz_localize("Asia/Kolkata")
    d["high"] = d[["open", "close"]].max(axis=1)
    d["low"] = d[["open", "close"]].min(axis=1)
    return d[["ts", "trading_day", "open", "high", "low", "close"]]


T, D1, D2 = "2026-03-02", "2026-03-03", "2026-03-04"      # entry, next session, expiry


def test_entry_price_is_the_average_of_the_1520_to_1529_closes():
    b = bars([(T, "14:00", 9, 9), (T, "15:19", 8, 8), (T, "15:20", 10, 10), (T, "15:25", 12, 12),
              (T, "15:29", 14, 14), (T, "15:30", 99, 99)])
    px, how = st.window_price(b, T)
    assert px == pytest.approx(12.0) and how == "window"            # 15:19 and 15:30 are outside the window


def test_entry_price_falls_back_to_the_last_close_before_the_window_and_labels_it():
    b = bars([(T, "14:00", 9, 9), (T, "15:10", 7, 7)])
    assert st.window_price(b, T) == (7.0, "last_before")
    assert st.window_price(b, D1) == (None, "none")


def test_premium_stop_fires_at_the_first_close_at_or_above_k_times_entry():
    b = bars([(T, "15:25", 10, 10), (D1, "09:15", 10, 11), (D1, "10:00", 11, 19.9), (D1, "10:01", 19, 20.0),
              (D1, "10:02", 20, 40)])
    s = st.premium_stop(b, T, 10.0, 2)
    assert s["px"] == 20.0 and not s["gap"] and s["ts"].strftime("%H:%M") == "10:01"
    assert st.premium_stop(b, T, 10.0, 5) is None                   # 5x = 50: never reached


def test_premium_stop_gap_through_fills_at_the_open_not_the_close():
    b = bars([(T, "15:25", 10, 10), (D1, "09:15", 35, 30), (D1, "09:16", 30, 28)])
    s = st.premium_stop(b, T, 10.0, 3)                              # stop 30; the session opens at 35
    assert s["gap"] and s["px"] == 35.0


def test_premium_stop_ignores_the_entry_day_and_bars_after_expiry():
    b = bars([(T, "15:29", 10, 50), (D2, "10:00", 10, 10), ("2026-03-05", "10:00", 10, 90)])
    assert st.premium_stop(b, T, 10.0, 2, until=D2) is None


def test_index_stop_fires_within_half_a_percent_of_either_strike():
    idx = bars([(T, "15:29", 100, 100), (D1, "09:15", 100, 100), (D1, "11:00", 100, 100.4), (D1, "11:01", 100, 100.6)])
    s = st.index_stop(idx, T, 101.0, 90.0)                          # call zone starts at 101 x 0.995 = 100.495
    assert s["ts"].strftime("%H:%M") == "11:01" and not s["gap"] and s["level"] == 100.6
    low = bars([(D1, "09:15", 100, 100), (D1, "12:00", 100, 90.4)])
    assert st.index_stop(low, T, 110.0, 90.0)["level"] == 90.4      # put zone: <= 90 x 1.005 = 90.45


def test_index_stop_gap_through_uses_the_session_open():
    idx = bars([(D1, "09:15", 101.5, 100), (D1, "09:16", 100, 100)])
    s = st.index_stop(idx, T, 102.0, 90.0)
    assert s["gap"] and s["level"] == 101.5


def test_price_at_uses_last_print_first_print_on_a_gap_and_the_intrinsic_floor():
    b = bars([(D1, "09:20", 5, 6), (D1, "10:00", 6, 8)])
    ts = pd.Timestamp(f"{D1} 10:30", tz="Asia/Kolkata")
    assert st.price_at(b, ts, gap=False) == 8.0
    assert st.price_at(b, ts, gap=True) == 5.0
    assert st.price_at(b, ts, gap=False, floor=12.0) == 12.0
    assert st.price_at(b, pd.Timestamp(f"{D1} 09:15", tz="Asia/Kolkata"), gap=False) == 5.0   # nothing yet: first print


def test_pick_wing_takes_the_nearest_listed_priced_strike_at_or_beyond():
    listed = {110: True, 112: False, 115: True, 120: True, 90: True, 88: False, 85: True}
    assert st.pick_wing(listed, 111, "C") == 115                    # 112 unpriced → next
    assert st.pick_wing(listed, 110, "C") == 110                    # at the target counts
    assert st.pick_wing(listed, 89, "P") == 85                      # beyond = lower for puts
    assert st.pick_wing(listed, 130, "C") is None


def ctx(S, ec=4.0, ep=3.0, listed=None, bars_c=None, bars_p=None, idx=None):
    listed = listed or {"c": {}, "p": {}}
    return st.Ctx(underlying="NIFTY", expiry=D2, entry=T, lot=50, F=100.0, S=S, kc=103.0, kp=97.0, ec=ec, ep=ep,
                  vwap_c=ec, vwap_p=ep, bars_c=bars_c if bars_c is not None else bars([(D1, "10:00", 1, 1)]),
                  bars_p=bars_p if bars_p is not None else bars([(D1, "10:00", 1, 1)]), idx=idx,
                  listed_c=listed["c"], listed_p=listed["p"], bars_by_leg={})


def test_baseline_pays_intrinsic_at_settlement_and_the_option_book_costs():
    c = ctx(S=105.0)                                                # call finishes 2 in the money
    r = st.v_baseline(c)
    cost = (ob.leg_cost(4.0, "sell", 50, ob.SLIP, T) + ob.leg_cost(3.0, "sell", 50, ob.SLIP, T))
    assert r["gross_pts"] == pytest.approx(4.0 + 3.0 - 2.0)
    assert r["net_pts"] == pytest.approx(5.0 - cost)
    assert st.v_baseline(ctx(S=100.0))["gross_pts"] == pytest.approx(7.0)


def test_wings_cap_the_loss_at_width_minus_net_credit():
    listed = {"c": {105.0: 0.5, 110.0: 0.2}, "p": {95.0: 0.4, 90.0: 0.1}}
    c = ctx(S=120.0, listed=listed)                                 # blow through both sides' wings (call side)
    r = st.v_wings(c, 0.05)                                         # 5 % of F=100 beyond: call ≥108 → 110, put ≤92 → 90
    assert (r["wing_c"], r["wing_p"]) == (110.0, 90.0)
    width = 110.0 - 103.0
    net_credit = 4.0 + 3.0 - 0.2 - 0.1
    assert r["gross_pts"] == pytest.approx(net_credit - width)      # short call -17, wing +10 → -7 + premiums
    assert r["bound_pts"] >= -r["net_pts"] - 1e-9                   # the worst-case bound really bounds the loss
    # hedged margin = width - net credit + exposure margin on both short legs
    assert r["margin_pts"] == pytest.approx(width - net_credit + 0.02 * 100.0 * 2)
    # the wing finishing in the money pays STT on exercise (as the backtest does)
    assert r["cost_pts"] > ob.leg_cost(4.0, "sell", 50, ob.SLIP, T) + ob.leg_cost(3.0, "sell", 50, ob.SLIP, T)
    calm = st.v_wings(ctx(S=100.0, listed=listed), 0.05)
    assert calm["gross_pts"] == pytest.approx(net_credit) and calm["triggered"] == 0
    assert st.v_wings(ctx(S=100.0, listed={"c": {105.0: 0.5}, "p": {}}), 0.05) is None   # a side with no priced wing


def test_premium_stop_variant_books_the_stop_loss_and_counts_the_whipsaw():
    b_c = bars([(D1, "10:00", 4, 8.5), (D1, "14:00", 8, 0.5)])      # call doubles then dies
    c = ctx(S=100.0, bars_c=b_c)
    r = st.v_pstop(c, 2)
    assert r["triggered"] == 1 and r["whipsaw"] == 1               # stopped leg would have expired worthless
    exit_cost = ob.leg_cost(8.5, "buy", 50, ob.SLIP, D1)
    base = st.v_baseline(c)
    assert r["gross_pts"] == pytest.approx((4.0 - 8.5) + 3.0)       # call bought back at 8.5, put kept
    assert r["cost_pts"] == pytest.approx(base["cost_pts"] + exit_cost)
    assert r["hold_net_pts"] == pytest.approx(base["net_pts"])


def test_index_stop_exits_both_legs_at_their_last_prints():
    idx = bars([(D1, "09:15", 100, 100), (D1, "11:00", 100, 102.6)])        # within 0.5 % of the 103 call strike
    b_c = bars([(D1, "10:59", 6, 6), (D1, "11:00", 6, 9)])
    b_p = bars([(D1, "10:30", 1, 1.5)])
    r = st.v_istop(ctx(S=100.0, bars_c=b_c, bars_p=b_p, idx=idx))
    assert r["triggered"] == 1
    assert r["gross_pts"] == pytest.approx((4.0 - 9.0) + (3.0 - 1.5))
    assert st.v_istop(ctx(S=100.0, idx=None)) is None              # no index file: no result


def test_sizing_a_by_margin_and_b_by_worst_case():
    assert st.lots_A(3_500_000, margin_pts=12.0, lot=50) == 5833
    assert st.lots_A(3_500_000, 2400.0, 75) == 19                  # 3.5e6 / 180000 = 19.4 → 19
    assert st.lots_B(3_500_000, worst_pts=500.0, lot=75) == 9      # 3.5e5 / 37500 = 9.33 → 9
    assert st.lots_B(3_500_000, worst_pts=500.0, lot=25) == 28     # a smaller lot buys more lots for the same risk


def test_size_trades_naked_uses_baseline_worst_and_hedged_uses_its_own_bound():
    df = pd.DataFrame({"expiry": ["2026-01-01", "2026-01-08"], "entry": ["2025-12-30", "2026-01-06"], "lot": [50, 50],
                       "margin_pts": [2400.0, 2400.0], "bound_pts": [float("nan")] * 2, "net_pts": [10.0, -400.0]})
    a = st.size_trades(df, "A", 3_500_000, 400.0)
    assert list(a.lots) == [29, 29] and a.pnl_rs.iloc[1] == pytest.approx(29 * 50 * -400.0)
    b = st.size_trades(df, "B", 3_500_000, 400.0)
    assert list(b.lots) == [17, 17]                                # 3.5e5 / (400 x 50) = 17.5
    assert b.pnl_rs.min() >= -3_500_000 * 0.10
    h = df.assign(bound_pts=[100.0, 100.0], margin_pts=[300.0, 300.0])
    assert list(st.size_trades(h, "B", 3_500_000, 400.0).lots) == [70, 70]   # its own bound, not the baseline's


def test_stats_annual_worst_drawdown_and_losing_years():
    d = pd.DataFrame({"entry": ["2024-01-02", "2024-06-04", "2025-01-07", "2025-06-03"],
                      "expiry": ["2024-01-04", "2024-06-06", "2025-01-09", "2025-06-05"],
                      "pnl_rs": [100.0, -300.0, 50.0, -20.0], "ret_on_margin": [0.01, -0.03, 0.005, -0.002]})
    s = st.stats(d, 3_500_000)
    assert s["n"] == 4 and s["win%"] == 50.0 and s["worst_rs"] == -300.0
    assert s["maxdd_rs"] == pytest.approx(-300.0)                   # peak 100, trough -200 → -300
    assert s["losing_years"] == 1 and s["years"] == 2               # 2024: -200, 2025: +30


def test_decision_rule_three_conditions():
    base = {"worst_rs": -350_000.0, "annual_rs": 1_000_000.0}
    ok = {"worst_rs": -150_000.0, "annual_rs": 800_000.0, "mean_rs_2021-23": 5.0, "n_2021-23": 9,
          "mean_rs_2024-26": 7.0, "n_2024-26": 9}
    res = {("COMBINED", "B", "w"): ok, ("COMBINED", "B", "w@base"): base}
    v = st.decision(res, which=("w",))[("COMBINED", "w")]
    assert v["pass"] and v["worst_ratio"] == pytest.approx(150 / 350)
    bad = dict(ok, annual_rs=600_000.0)
    res[("COMBINED", "B", "w")] = bad
    assert not st.decision(res, which=("w",))[("COMBINED", "w")]["pass"]
    res[("COMBINED", "B", "w")] = dict(ok, **{"mean_rs_2021-23": -1.0})
    assert not st.decision(res, which=("w",))[("COMBINED", "w")]["c3_regimes"]


# ── exploratory stop-level grid (tools/option_stop_grid.py) ──

def test_grid_combo_each_leg_exits_at_whichever_stop_fires_first():
    from tools import option_stop_grid as gr
    idx = bars([(D1, "09:15", 100, 100), (D1, "11:00", 100, 102.6)])           # index trigger 11:00 (0.5 % band)
    b_c = bars([(D1, "10:00", 4, 9), (D1, "11:00", 9, 12)])                    # call premium stop (2x = 8) fires 10:00
    b_p = bars([(D1, "10:30", 1, 1.5), (D1, "11:00", 1.5, 2.0)])               # put never reaches its stop
    r = gr.v_stop(ctx(S=100.0, bars_c=b_c, bars_p=b_p, idx=idx), k=2, d=0.5)
    assert r["variant"] == "ps2|is0.5"
    assert r["gross_pts"] == pytest.approx((4.0 - 9.0) + (3.0 - 2.0))          # call at its own stop, put at the index stop
    assert gr.v_stop(ctx(S=100.0, idx=None), d=0.5) is None


def test_grid_index_stop_distance_zero_means_strike_touched():
    from tools import option_stop_grid as gr
    idx = bars([(D1, "09:15", 100, 100), (D1, "10:00", 100, 102.9), (D1, "10:01", 100, 103.0)])
    assert st.index_stop(idx, T, 103.0, 97.0, band=0.0)["ts"].strftime("%H:%M") == "10:01"
    assert gr.gname(k=1.5) == "ps1.5" and gr.gname(d=1.0) == "is1" and gr.gname() == "base"


def test_grid_sizing_b_uses_the_frozen_worst_case_share_of_the_forward():
    from tools import option_stop_grid as gr
    df = pd.DataFrame({"F": [24000.0, 24000.0], "lot": [75, 75], "net_pts": [5.0, -240.0], "margin_pts": [2880.0] * 2})
    assert gr.worst_frac(df) == pytest.approx(0.01)                            # 240 / 24000
    s = gr.size_frac(df, 0.01, 3_500_000)
    assert list(s.lots) == [19, 19]                                            # 3.5e5 / (0.01 x 24000 x 75) = 19.4
    assert s.pnl_rs.min() == pytest.approx(19 * 75 * -240.0)


def test_grid_choice_takes_best_sel_pnl_and_the_wider_stop_on_a_tie():
    from tools import option_stop_grid as gr
    ev = {(v, "SEL"): {"B_annual_rs": 100.0, "trig%": 50.0} for v in gr.grid_names()}
    ev[("ps3", "SEL")] = {"B_annual_rs": 500.0, "trig%": 20.0}
    ev[("ps4", "SEL")] = {"B_annual_rs": 500.0, "trig%": 10.0}               # tie on P&L, wider stop (fewer triggers)
    ev[("is0.5", "SEL")] = {"B_annual_rs": 300.0, "trig%": 30.0}
    assert gr.choose(ev) == {"premium": "ps4", "index": "is0.5", "combo": "ps4|is0.5"}
