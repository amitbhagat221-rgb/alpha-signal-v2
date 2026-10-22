"""Option risk-filter study: the point-in-time join (no future data) and the action logic — offline."""

import copy

import numpy as np
import pandas as pd

import tools.option_risk_filters as orf


def _raw(n=420, seed=3):
    rng = np.random.default_rng(seed)
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2019-01-01", periods=n)]
    close = pd.Series(10000 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=dates)
    vix = pd.Series(15 + np.abs(np.cumsum(rng.normal(0, 0.6, n))) % 30, index=dates)
    iv = pd.DataFrame({"atm_iv": rng.uniform(0.1, 0.3, n), "iv_skew_25d": rng.normal(0.03, 0.01, n),
                       "iv_term_structure": rng.normal(0, 0.02, n)}, index=dates)
    pcr = pd.DataFrame({"pcr_oi": rng.uniform(0.5, 1.6, n), "pcr_volume": rng.uniform(0.5, 1.6, n),
                        "max_pain_distance": rng.normal(0, 0.01, n)}, index=dates)
    fii = pd.DataFrame({c: rng.integers(1_000, 90_000, n) for c in
                        ("future_index_long", "future_index_short", "option_index_call_long", "option_index_put_long",
                         "option_index_call_short", "option_index_put_short")}, index=dates)
    macro = {k: pd.Series(rng.uniform(50, 100, n), index=dates) for k in ("us_10y", "usdinr", "brent_crude")}
    return {"close": close, "vix": vix, "iv": iv, "pcr": pcr, "fii": fii, "macro": macro}


def _cut(raw, d, strict_after=True):
    out = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            out[k] = {kk: vv[vv.index <= d] for kk, vv in v.items()}
        else:
            out[k] = v[v.index <= d]
    return out


def test_predictors_use_only_data_known_at_the_entry_close():
    raw = _raw()
    full = orf.build_market(raw)
    for d in (full.index[260], full.index[300], full.index[399]):
        cut = orf.build_market(_cut(raw, d))
        a, b = full.loc[d], cut.loc[d]
        pd.testing.assert_series_equal(a, b, check_names=False)


def test_future_values_cannot_move_todays_row_and_same_day_macro_and_fii_are_excluded():
    raw = _raw()
    full = orf.build_market(raw)
    d = full.index[300]
    pert = copy.deepcopy(raw)
    after = [x for x in raw["close"].index if x > d]
    pert["close"].loc[after] *= 5
    pert["vix"].loc[after] += 40
    for k in pert["macro"]:
        pert["macro"][k].loc[[d] + after] *= 3        # includes the same day: a US close prints after India shuts
    pert["fii"].loc[[d] + after] = 1
    again = orf.build_market(pert)
    pd.testing.assert_series_equal(full.loc[d], again.loc[d], check_names=False)


def test_asof_strict_is_strictly_before():
    s = pd.Series([1.0, 2.0, 3.0], index=["2024-01-02", "2024-01-03", "2024-01-05"])
    got = orf.asof_strict(s, ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-09"])
    assert np.isnan(got.iloc[0])
    assert list(got.iloc[1:]) == [1.0, 2.0, 2.0, 3.0]


def test_events_inside_hold_and_holiday_detection():
    assert orf.event_flags("2022-06-06", "2022-06-09")["ev_rbi"] == 1.0        # MPC decision 2022-06-08 inside
    assert orf.event_flags("2022-06-08", "2022-06-10")["ev_rbi"] == 0.0        # entry after the decision at the close... same day
    assert orf.event_flags("2022-07-26", "2022-07-28")["ev_fomc"] == 1.0       # FOMC 2022-07-27 US evening -> Indian 07-28
    assert orf.event_flags("2023-03-01", "2023-03-03")["ev_any"] == 0.0
    sessions = ["2024-03-26", "2024-03-27", "2024-03-28", "2024-04-01"]       # 03-29 Good Friday missing
    assert orf.holiday_in_window("2024-03-27", "2024-04-01", sessions)
    assert not orf.holiday_in_window("2024-03-26", "2024-03-28", sessions)


def test_regime_is_a_vix_band_with_three_day_hysteresis():
    v = pd.Series([12.0, 12.0, 12.0, 30.0, 30.0, 30.0, 12.0], index=[f"2024-01-0{i}" for i in range(1, 8)])
    r = orf.regime_series(v)
    assert list(r) == [0, 0, 0, 0, 0, 2, 2]


def test_size_actions_and_signed_tails():
    flag = np.array([0.0, 1.0, 0.0, 1.0])
    assert list(orf.make_sizes(flag, "skip")) == [1, 0, 1, 0]
    assert list(orf.make_sizes(flag, "half")) == [1, 0.5, 1, 0.5]
    X = pd.DataFrame({"pcr_oi": [0.5, 1.0, np.nan, 1.5]})
    hi = orf.flags_for({"pred": "pcr_oi", "tail": "hi", "thr": 1.0}, X)
    lo = orf.flags_for({"pred": "pcr_oi", "tail": "lo", "thr": -1.0}, X)
    assert list(hi) == [0, 1, 0, 1]            # missing is never flagged
    assert list(lo) == [1, 1, 0, 0]


def test_book_drawdown_and_decision_rule_at_equal_margin():
    ret = np.array([0.02, 0.02, -0.05, 0.02, 0.02, 0.02])
    base = orf.book(ret, np.ones(6), 1.0)
    assert abs(base["dd"] + 0.05) < 1e-12 and base["worst"] == -0.05
    skip = orf.book(ret, np.array([1, 1, 0, 1, 1, 1.0]), 1.0)
    assert skip["dd"] == 0 and skip["n"] == 5
    c1, c2, c3, nums = orf.verdict_conditions(base, skip)
    assert c1 and c2 and c3                      # drawdown gone, ratio better, P&L at equal margin >= 85 %
    half_everything = orf.book(ret, np.full(6, 0.5), 1.0)
    c1, c2, c3, nums = orf.verdict_conditions(base, half_everything)
    assert abs(nums["dd_change_em"]) < 1e-12 and not c1 and not c2   # a uniform cut is not a risk filter


def test_threshold_is_picked_on_the_choose_window_only():
    entry = pd.Series(["2019-03-01"] * 10 + ["2022-06-01"] * 10 + ["2024-01-01"] * 10)
    x = np.arange(30, dtype=float)
    ret = np.full(30, 0.01)
    ret[19] = -0.05                                # worst trade has x=19, inside the choose window
    ret[29] = -0.20                                # a test-window disaster that must not move the pick
    pick = orf.choose_threshold(x, ret, entry, "skip")
    assert pick is not None and pick[1] <= 19.0
    ret2 = ret.copy()
    ret2[29] = 0.01
    assert orf.choose_threshold(x, ret2, entry, "skip") == pick


def test_risk_scaled_size_has_mean_one_and_walk_forward_ignores_the_future():
    x = np.array([10.0, 20.0, 40.0, 80.0])
    s = orf.scaled_size(x, np.ones(4, bool))
    assert abs(np.nanmean(s) - 1) < 1e-12 and s[0] > s[3]
    rng = np.random.default_rng(1)
    n = 260
    entry = np.array([d.strftime("%Y-%m-%d") for d in pd.bdate_range("2019-02-01", periods=n * 2)[::2]])
    expiry = np.array([d.strftime("%Y-%m-%d") for d in pd.bdate_range("2019-02-05", periods=n * 2)[::2]])
    t = pd.DataFrame({"entry": entry, "expiry": expiry, "ret": rng.normal(0.003, 0.01, n)})
    X = pd.DataFrame(rng.normal(size=(n, 3)), columns=["a", "b", "c"])
    size, _ = orf.walk_forward(X, t, ["a", "b", "c"], first_year=2021)
    t2, X2 = t.copy(), X.copy()
    late = t.entry >= "2023-01-01"
    t2.loc[late, "ret"] = -0.5
    X2.loc[late, "a"] += 9
    size2, _ = orf.walk_forward(X2, t2, ["a", "b", "c"], first_year=2021)
    early = (t.entry < "2023-01-01").values
    assert (size[early] == size2[early]).all()
