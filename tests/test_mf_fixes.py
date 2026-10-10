"""Funds fix round 2026-10: calendar-year Nifty over the same dates, peer rank by 3Y, name sort, partial-year labels."""
import numpy as np
import pandas as pd

from cockpit import mf
from signals import mf_metrics as mm


def _series(start, end, v0, v1):
    d = pd.bdate_range(start, end)
    return pd.DataFrame({"nav_date": d, "nav": np.linspace(v0, v1, len(d))})


def test_calendar_bench_uses_the_funds_own_dates():
    nav = _series("2023-12-01", "2024-12-31", 10, 20)         # launched Dec 2023
    nav = nav[nav["nav_date"] >= "2024-02-12"].reset_index(drop=True)   # launch mid-Feb 2024
    d = pd.bdate_range("2019-01-01", "2024-12-31")
    bench = pd.DataFrame({"date": d, "bench_nav": np.linspace(100, 300, len(d))})
    row = [r for r in mm._calendar_returns(nav, bench) if r["year"] == 2024][0]
    full_year = (bench["bench_nav"].iloc[-1] / bench[bench["date"] <= "2023-12-31"]["bench_nav"].iloc[-1] - 1) * 100
    assert row["bench_ret_pct"] is not None and row["bench_ret_pct"] < full_year   # shorter window, smaller move


def test_no_benchmark_before_the_index_series_starts():
    nav = _series("2018-03-01", "2019-12-31", 10, 12)
    d = pd.bdate_range("2019-01-01", "2019-12-31")
    bench = pd.DataFrame({"date": d, "bench_nav": np.linspace(100, 120, len(d))})
    rows = {r["year"]: r for r in mm._calendar_returns(nav, bench)}
    assert rows[2018]["bench_ret_pct"] is None
    assert rows[2019]["bench_ret_pct"] is None      # base date 2018-12-31 predates the index series


def test_partial_year_labels():
    assert mf._calendar_partial(2024, "2024-02-12", "2026-10-09") == "from launch 12 Feb"
    assert mf._calendar_partial(2026, "2024-02-12", "2026-10-09") == "YTD to 9 Oct"
    assert mf._calendar_partial(2025, "2024-02-12", "2026-10-09") is None
    assert mf._calendar_partial(2026, "2026-03-02", "2026-10-09") == "from launch 2 Mar, YTD to 9 Oct"


def test_peer_rank_3y_is_within_category_and_plan():
    master = pd.DataFrame({"scheme_code": list("ABCD"), "category_norm": ["X", "X", "X", "Y"],
                           "plan_type": ["DIRECT", "DIRECT", "REGULAR", "DIRECT"]})
    metrics = pd.DataFrame({"scheme_code": list("ABCD"), "ret_3y_cagr": [10.0, 14.0, 20.0, 5.0]})
    out = mm._compute_composite_score(metrics, pd.DataFrame(), master).set_index("scheme_code")
    assert out.loc["B", "peer_rank_3y"] == 1 and out.loc["A", "peer_rank_3y"] == 2
    assert out.loc["B", "peer_count"] == 2
    assert out.loc["C", "peer_rank_3y"] == 1 and out.loc["D", "peer_rank_3y"] == 1


def test_scheme_name_sort_ignores_case(monkeypatch):
    pool = pd.DataFrame({"scheme_code": ["1", "2", "3"], "scheme_name": ["UTI Nifty", "quant Small", "Axis Bluechip"],
                         "amc": "x", "category_norm": "c", "plan_type": "DIRECT", "option_type": "GROWTH",
                         "nav_date": "2026-10-09", "composite_score": [1.0, 2.0, 3.0], "investable": 1})
    monkeypatch.setattr(mf, "_mf_universe_pool", lambda: pool)
    names = [r["scheme_name"] for r in mf.get_mf_universe_overview(sort="name")["rows"]]
    assert names == ["Axis Bluechip", "quant Small", "UTI Nifty"]


def test_page_beyond_the_end_lands_on_last_page(monkeypatch):
    pool = pd.DataFrame({"scheme_code": [str(i) for i in range(5)], "scheme_name": list("abcde"), "amc": "x",
                         "category_norm": "c", "plan_type": "DIRECT", "option_type": "GROWTH",
                         "nav_date": "2026-10-09", "composite_score": [1.0] * 5, "investable": 1})
    monkeypatch.setattr(mf, "_mf_universe_pool", lambda: pool)
    out = mf.get_mf_universe_overview(sort="name", page=99, page_size=2)
    assert out["page"] == 3 and len(out["rows"]) == 1
