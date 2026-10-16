"""signals/valuation.py: the maths on synthetic inputs, then a golden check on 3 real names
(skipped when the DB is not present)."""
import numpy as np
import pandas as pd
import pytest

from config import DB_PATH
from signals import valuation as v

CR = v.CRORE


# ── synthetic: each method ──────────────────────────────────────────────────

def test_percentiles_needs_min_n_and_ignores_nan():
    assert v.percentiles([1, 2, np.nan], (10, 50, 90), min_n=3) is None
    assert v.percentiles(np.arange(1, 101), (10, 50, 90)) == pytest.approx((10.9, 50.5, 90.1))


def test_pe_band_is_percentile_multiple_times_eps():
    pe = np.arange(10, 31, dtype=float)                      # 10..30
    r = v._own_band("X", "2026-01-01", "pe_band", np.tile(pe, 3), 5.0, 100.0, "P/E", "TTM EPS 5.00")
    assert (r["low"], r["mid"], r["high"]) == pytest.approx((12 * 5, 20 * 5, 28 * 5))
    assert "TTM EPS 5.00" in r["basis"]


def test_pb_band_same_shape_and_thin_history_is_dropped():
    r = v._own_band("X", "d", "pb_band", [2, 3, 4], 50.0, 100.0, "P/B", "BVPS 50")
    assert np.isnan(r["mid"]) and r["basis"].startswith("insufficient history")


def test_ev_ebitda_band_back_to_equity_per_share():
    # EV = 10 x 100 cr EBITDA = 1000 cr; net debt 200 cr; 10 cr shares -> Rs 80 / share
    assert v.ev_to_price(10, 100 * CR, 200 * CR, 10 * CR) == pytest.approx(80.0)
    assert v.ev_to_price(10, 100 * CR, -200 * CR, 10 * CR) == pytest.approx(120.0)


def test_ev_history_applies_lags_and_counts_quarters():
    qs = pd.date_range("2023-03-31", periods=12, freq="QE")
    q = pd.DataFrame({"end_date": [d.date().isoformat() for d in qs], "ebitda": 100.0})
    ann = pd.DataFrame({"Borrowings": [300.0], "Cash & Bank": [100.0]}, index=["2024-03-31"])
    dates = pd.date_range("2024-01-01", "2025-12-31", freq="W")
    pit = pd.DataFrame({"snapshot_date": [d.date().isoformat() for d in dates]})
    mult, nq = v._ev_history(pit, 10 * CR, q, ann, np.full(len(dates), 100.0))
    # mcap 100 x 10 cr shares = 1000 cr, net debt 200 cr, TTM EBITDA 400 cr -> 3.0x everywhere
    assert set(np.round(mult, 6)) == {3.0}
    assert nq == 6          # TTM windows ending Jun-24 .. Sep-25 are public by then
    # a FY2024 balance sheet is not usable before 2024-03-31 + 150 d: earlier dates are dropped
    first = pd.Timestamp("2024-03-31") + pd.Timedelta(days=150)
    assert len(mult) == (dates >= first).sum()


def test_net_debt_missing_borrowings_counts_as_no_debt():
    ann = pd.DataFrame({"Borrowings": [np.nan], "Cash & Bank": [40.0]}, index=["2025-03-31"])
    assert v._net_debt_cr(ann) == (-40.0, "2025-03-31")


def test_owner_earnings_cfo_less_capex_with_fallback():
    idx = ["2024-03-31", "2025-03-31", "2026-03-31"]
    ann = pd.DataFrame({"Net profit": [50.0, 60.0, 70.0],
                        "Cash from Operating Activity": [100.0, 100.0, 100.0],
                        "Cash from Investing Activity": [-40.0, 30.0, -20.0]}, index=idx)
    oe, label = v._owner_earnings_cr(ann)
    assert oe == pytest.approx((60 + 100 + 80) / 3) and label.startswith("CFO+min(CFI,0)")
    ann["Cash from Investing Activity"] = -500.0           # capex swamps cash flow -> net profit
    oe, label = v._owner_earnings_cr(ann)
    assert oe == pytest.approx(60.0) and "net profit" in label
    ann["Cash from Operating Activity"] = np.nan           # CFO missing -> net profit per year
    assert v._owner_earnings_cr(ann)[0] == pytest.approx(60.0)


def test_cagr3():
    assert v.cagr3(100, 133.1) == pytest.approx(0.10)
    assert v.cagr3(-5, 10) is None and v.cagr3(None, 10) is None


def test_fade_path_hits_6pct_in_year_ten():
    p = v.fade_path(0.30)
    assert len(p) == 10 and p[0] == pytest.approx(0.30) and p[-1] == pytest.approx(0.06)
    assert all(a >= b for a, b in zip(p, p[1:]))


def test_dcf_hand_computation_zero_growth_gap():
    # growth 6% all ten years (g0 = fade target), coe 14%, terminal 5%: closed form
    oe, shares = 100.0, 1.0
    pv = sum(oe * 1.06 ** t / 1.14 ** t for t in range(1, 11))
    tv = oe * 1.06 ** 10 * 1.05 / (0.14 - 0.05) / 1.14 ** 10
    assert v.dcf_value(oe, shares, 0.06, 0.14) == pytest.approx(pv + tv)
    assert v.dcf_value(-1, 1, 0.1, 0.14) is None


def _coe(mcap=1000.0, adtv=5.0):
    c = v.cost_of_equity(mcap, adtv)
    return c, v._coe_text(c, mcap, adtv)


def test_coe_curve_endpoints_and_log_midpoint():
    assert v.cost_of_equity(20000, 5)["base"] == pytest.approx(0.14)
    assert v.cost_of_equity(500000, 5)["base"] == pytest.approx(0.14)        # above the top: floor
    assert v.cost_of_equity(500, 5)["base"] == pytest.approx(0.20)
    assert v.cost_of_equity(300, 5)["base"] == pytest.approx(0.20)           # below the bottom: cap
    assert v.cost_of_equity(np.sqrt(20000 * 500), 5)["base"] == pytest.approx(0.17)   # log-linear: geometric mid
    c = v.cost_of_equity(500, 5)
    assert (c["bear"], c["bull"]) == pytest.approx((0.21, 0.19))


def test_coe_illiquid_adds_a_point_and_unknown_adtv_does_not():
    assert v.cost_of_equity(500, 0.5)["base"] == pytest.approx(0.21)
    assert v.cost_of_equity(500, 0.5)["illiquid"] and not v.cost_of_equity(500, 1.0)["illiquid"]
    assert v.cost_of_equity(500, None)["base"] == pytest.approx(0.20)


def test_dcf_bear_below_base_below_bull():
    c, txt = _coe()
    d, r = v._dcf_rows("X", "2026-01-01", 100.0, 10 * CR, 100.0, "test", 0.08, 0.15, 0.22, c, txt)
    assert 0 < d["low"] < d["mid"] < d["high"]
    assert "growth bear/base/bull 8.0%/15.0%/22.0%" in d["basis"]
    assert f"coe bear/base/bull {c['bear']:.1%}/{c['base']:.1%}/{c['bull']:.1%}" in d["basis"]


def test_dcf_basis_names_terminal_share_and_flags_above_75pct():
    # growth 6% for 10 years at a 14% coe: terminal is ~ 45% of the value; at 6% coe it is ~ 88%
    assert 0.4 < v.dcf_parts(100.0, 1.0, 0.06, 0.14)[1] < 0.75
    assert v.dcf_parts(100.0, 1.0, 0.06, 0.06)[1] > 0.75
    c, txt = _coe()
    d, _ = v._dcf_rows("X", "d", 100.0, 10 * CR, 100.0, "t", 0.06, 0.06, 0.06, c, txt)
    assert "terminal value x " in d["basis"] and "low confidence" not in d["basis"]
    lo = {**c, "bear": 0.07, "base": 0.06, "bull": 0.055}
    d, _ = v._dcf_rows("X", "d", 100.0, 10 * CR, 100.0, "t", 0.06, 0.06, 0.06, lo, txt)
    assert "low confidence" in d["basis"] and not np.isnan(d["mid"])     # the bar stays


def test_reverse_dcf_round_trip():
    oe, shares = 250 * CR, 10 * CR
    for mcap in (400.0, 3000.0, 40000.0):                      # size-based rates 20 % .. 14 %
        coe = v.cost_of_equity(mcap, 5.0)["base"]
        for target in (100.0, 300.0, 700.0):
            g = v.implied_growth(target, oe, shares, coe)
            assert g is not None
            assert v.dcf_value(oe, shares, g, coe) == pytest.approx(target, rel=1e-6)
    assert v.implied_growth(1e9, oe, shares, 0.14) is None          # beyond reach: no answer, not a clamp


def test_reverse_dcf_row_carries_growth_not_a_bar():
    c, txt = _coe()
    d, r = v._dcf_rows("X", "2026-01-01", 400.0, 10 * CR, 250.0, "test", 0.08, 0.15, 0.22, c, txt)
    assert np.isnan(r["mid"]) and 0 < r["implied_growth_10y"] < 0.8
    assert f"{c['base']:.1%}" in r["basis"]                        # the rate used is named
    # a higher (smaller-company) rate needs more growth to justify the same price
    c2, txt2 = _coe(mcap=400.0)
    _, r2 = v._dcf_rows("X", "2026-01-01", 400.0, 10 * CR, 250.0, "test", 0.08, 0.15, 0.22, c2, txt2)
    assert r2["implied_growth_10y"] > r["implied_growth_10y"]


def test_ev_sales_history_uses_revenue_and_loss_maker_still_prices():
    qs = pd.date_range("2023-03-31", periods=12, freq="QE")
    q = pd.DataFrame({"end_date": [d.date().isoformat() for d in qs], "ebitda": -10.0, "revenue": 250.0})
    ann = pd.DataFrame({"Borrowings": [300.0], "Cash & Bank": [100.0]}, index=["2024-03-31"])
    dates = pd.date_range("2024-01-01", "2025-12-31", freq="W")
    pit = pd.DataFrame({"snapshot_date": [d.date().isoformat() for d in dates]})
    adj = np.full(len(dates), 100.0)
    assert len(v._ev_history(pit, 10 * CR, q, ann, adj)[0]) == 0           # EBITDA < 0: no EV/EBITDA multiple
    mult, nq = v._ev_history(pit, 10 * CR, q, ann, adj, col="revenue", max_mult=100)
    assert set(np.round(mult, 6)) == {1.2} and nq == 6                      # (1000 + 200) / TTM sales 1000
    assert v.ev_to_price(1.2, 1000 * CR, 200 * CR, 10 * CR) == pytest.approx(100.0)


def test_midcycle_median_of_three_annual_windows_needs_12_quarters():
    qs = pd.date_range("2023-03-31", periods=12, freq="QE")
    ebitda = [10] * 4 + [40] * 4 + [20] * 4                 # windows 40, 160, 80 -> median 80, latest TTM 80
    q = pd.DataFrame({"end_date": [d.date().isoformat() for d in qs], "ebitda": [float(x) for x in ebitda]})
    mid, label = v._midcycle(q, "ebitda")
    assert mid == 80.0 and label.startswith("mid-cycle EBITDA")
    q2 = pd.DataFrame({"end_date": q["end_date"], "ebitda": [10.0] * 8 + [30.0] * 4})   # windows 40, 40, 120 -> 40
    assert v._midcycle(q2, "ebitda")[0] == 40.0 and v._ttm(q2, "ebitda")[0] == 120.0
    short, label = v._midcycle(q2.tail(8), "ebitda")
    assert short == 120.0 and label.startswith("TTM EBITDA")
    assert v._midcycle(q2.tail(3), "ebitda") == (None, None)


def test_method_order_reverse_dcf_first():
    assert v.METHODS[0] == "reverse_dcf" and v.METHODS[-3:] == ("dcf", "analyst", "range_52w")
    assert v.METHODS.index("ev_ebitda_band") < v.METHODS.index("ev_sales") < v.METHODS.index("pe_band")
    assert v.METHODS.index("peer_ev_sales") < v.METHODS.index("peer_pe")


def test_guard_rail_drops_absurd_mid_and_sorts():
    bad = v._row("X", "d", "dcf", 1.0, 5000.0, 9000.0, "b", 100.0)           # mid > 20x price
    assert np.isnan(bad["mid"]) and bad["basis"].startswith("out of range")
    neg = v._row("X", "d", "dcf", -5.0, -1.0, 2.0, "b", 100.0)               # mid <= 0
    assert np.isnan(neg["mid"]) and neg["basis"].startswith("out of range")
    ok = v._row("X", "d", "dcf", 120.0, 80.0, 100.0, "b", 100.0)
    assert (ok["low"], ok["mid"], ok["high"]) == (80.0, 100.0, 120.0)


def test_peer_set_falls_back_to_industry_when_tier_is_thin():
    rows = [(f"S{i}", "Ind", "SMALL" if i < 2 else "MID", 10.0 + i, np.nan, np.nan) for i in range(8)]
    peers = pd.DataFrame(rows, columns=["sid", "industry", "cap_tier", "pe", "ev", "g3"])
    st = {"industry": "Ind", "cap_tier": "SMALL"}
    got, scope = v._peer_set(peers, "ME", st, "pe")
    assert len(got) == 8 and "all tiers" in scope
    st = {"industry": "Ind", "cap_tier": "MID"}
    got, scope = v._peer_set(peers, "ME", st, "pe")
    assert len(got) == 6 and scope == "Ind/MID"


# ── golden: 3 real names on the read-only DB ────────────────────────────────

GOLDEN = {"KEIN": "MID industrial", "GRSE": "SMALL industrial", "HDBK": "LARGE financial"}
NON_FIN = set(v.METHODS)
assert len(v.METHODS) == 11


@pytest.fixture(scope="module")
def field():
    if not DB_PATH.exists():
        pytest.skip("no production DB (set ALPHA_DB)")
    return v.compute(list(GOLDEN))


@pytest.mark.skipif(not DB_PATH.exists(), reason="no production DB (set ALPHA_DB)")
def test_golden_method_set_and_sanity(field):
    assert set(field["sid"]) == set(GOLDEN)
    for sid, g in field.groupby("sid"):
        assert set(g["method"]) == NON_FIN, sid
        assert (g["price"] > 0).all()
        live = g.dropna(subset=["mid"])
        assert {"pe_band", "pb_band", "peer_pe", "analyst", "range_52w"} <= set(live["method"]), sid
        assert (live["low"] >= 0).all() and (live["mid"] > 0).all()
        assert (live["low"] <= live["mid"]).all() and (live["mid"] <= live["high"]).all()
        assert (live["mid"] <= 20 * live["price"]).all()
        assert g["basis"].str.len().gt(0).all()
    fin = field[field["sid"] == "HDBK"].set_index("method")
    for m in ("ev_ebitda_band", "peer_ev_ebitda", "ev_sales", "peer_ev_sales", "dcf", "reverse_dcf"):
        assert fin.loc[m, "basis"] == "n/a for financials" or fin.loc[m, "basis"].startswith("n/a for financials")
    ind = field[field["sid"] == "KEIN"].set_index("method")
    assert ind.loc["reverse_dcf", "implied_growth_10y"] > 0
    assert ind.loc["dcf", "mid"] > 0
    assert ind.loc["ev_sales", "mid"] > 0 and "EV/Sales p10/50/90" in ind.loc["ev_sales", "basis"]
    assert "mid-cycle EBITDA" in ind.loc["ev_ebitda_band", "basis"]
    assert "terminal value x " in ind.loc["dcf", "basis"] and "size curve" in ind.loc["dcf", "basis"]
    assert "size curve" in ind.loc["reverse_dcf", "basis"]
    assert "analysts, fetched" in ind.loc["analyst", "basis"]
    assert list(field[field["sid"] == "KEIN"]["method"]) == list(v.METHODS)       # display order


@pytest.mark.skipif(not DB_PATH.exists(), reason="no production DB (set ALPHA_DB)")
def test_golden_pe_band_hand_recompute(field):
    """KEIN: mid = median historical P/E x TTM EPS, recomputed here from the tables."""
    ey = v._read("SELECT earnings_yield e FROM daily_snapshots_pit WHERE sid='KEIN' AND earnings_yield > 0")["e"]
    q = v._read("SELECT eps FROM quarterly_income WHERE sid='KEIN' ORDER BY end_date DESC LIMIT 4")["eps"]
    want = float(np.median(1 / ey)) * float(q.sum())
    got = field[(field["sid"] == "KEIN") & (field["method"] == "pe_band")]["mid"].iloc[0]
    assert got == pytest.approx(want, rel=1e-6)


@pytest.mark.skipif(not DB_PATH.exists(), reason="no production DB (set ALPHA_DB)")
def test_golden_range_52w_is_split_adjusted(field):
    r = field[(field["sid"] == "HDBK") & (field["method"] == "range_52w")].iloc[0]
    assert r["low"] < r["price"] < r["high"] * 1.0001        # HDFC Bank bonus-split inside the window must not break it
    assert r["high"] < 3 * r["price"]


@pytest.mark.skipif(not DB_PATH.exists(), reason="no production DB (set ALPHA_DB)")
def test_golden_analyst_needs_three_houses():
    n = v._read("SELECT total_analysts n FROM analyst_consensus WHERE sid='KEIN'")["n"].iloc[0]
    assert n >= v.PARAMS["min_analysts"]        # KEIN is covered; the rule itself is unit-tested below


@pytest.mark.skipif(not DB_PATH.exists(), reason="no production DB (set ALPHA_DB)")
def test_golden_thinly_covered_name_has_no_analyst_bar():
    """IRF has one analyst in analyst_consensus: no bar, and the basis says why."""
    n = v._read("SELECT total_analysts n FROM analyst_consensus WHERE sid='IRF'")
    if n.empty or n["n"].iloc[0] is None or n["n"].iloc[0] >= v.PARAMS["min_analysts"]:
        pytest.skip("IRF coverage changed; pick another thinly covered name")
    r = v.compute(["IRF"]).set_index("method").loc["analyst"]
    assert np.isnan(r["mid"]) and r["basis"].startswith("fewer than 3 analysts")
