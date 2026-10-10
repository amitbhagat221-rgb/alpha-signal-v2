"""pick_outcomes: adjusted returns (the one label) and one pick date per trading day."""
import pandas as pd

from tools.compute_pick_outcomes import score_picks, TIER_BENCHMARKS


def _frames(n=30, split_at=None):
    days = pd.bdate_range("2026-06-01", periods=n)
    rows = []
    for i, d in enumerate(days):
        px = 100.0 + i
        if split_at is not None and i >= split_at:
            px /= 5.0                       # 5:1 split: raw close drops 80%
        rows.append({"sid": "AAA", "date": d.strftime("%Y-%m-%d"), "close": px})
    return days, pd.DataFrame(rows)


def _adj(split_idx, days):
    # factor 0.2 applies to rows BEFORE ex_date (see pit.apply_adjustments)
    return pd.DataFrame([{"sid": "AAA", "ex_date": days[split_idx].strftime("%Y-%m-%d"),
                          "factor": 0.2, "inds": "split"}])


def _picks(dates):
    return pd.DataFrame([{"sid": "AAA", "pick_date": d, "cap_tier": "LARGE", "rank": 1,
                          "final_score": 0.9} for d in dates])


def test_split_inside_window_is_not_a_loss():
    days, prices = _frames(split_at=10)
    out = score_picks(_picks([days[3].strftime("%Y-%m-%d")]), prices, _adj(10, days), {}, (20,), include_bench=False)
    assert len(out) == 1
    # price path 103 -> 123 on one share basis: about +19%, not -80%
    assert 15 < out.iloc[0]["fwd_return_pct"] < 25


def test_non_trading_pick_dates_are_dropped():
    days, prices = _frames()
    sat = (days[4] + pd.Timedelta(days=1)).strftime("%Y-%m-%d")      # Saturday after a Friday
    assert pd.Timestamp(sat).weekday() == 5
    picks = _picks([days[4].strftime("%Y-%m-%d"), sat])
    out = score_picks(picks, prices, pd.DataFrame(columns=["sid", "ex_date", "factor", "inds"]), {}, (5,),
                      include_bench=False)
    assert list(out["pick_date"].unique()) == [days[4].strftime("%Y-%m-%d")]


def test_benchmark_uses_the_same_sessions():
    days, prices = _frames()
    bname = TIER_BENCHMARKS["LARGE"]
    bench = {bname: pd.Series(range(1000, 1000 + len(days)), index=days, dtype=float)}
    out = score_picks(_picks([days[2].strftime("%Y-%m-%d")]), prices, pd.DataFrame(columns=["sid", "ex_date", "factor", "inds"]),
                      bench, (5,))
    r = out.iloc[0]
    assert r["exit_date"] == days[7].strftime("%Y-%m-%d")
    assert abs(r["bench_return_pct"] - 100 * (1007 / 1002 - 1)) < 1e-3
