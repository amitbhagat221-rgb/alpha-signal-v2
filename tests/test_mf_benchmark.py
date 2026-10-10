"""MF benchmark is the real NIFTY 50 index series, applied to equity funds only."""
import pandas as pd

from signals import mf_metrics as mm


def test_benchmark_is_the_nifty_index_rebased(monkeypatch):
    seen = {}

    def fake_read(sql, params=None):
        seen["params"] = params
        return pd.DataFrame({"date": ["2024-01-01", "2024-01-02"], "bench_nav": [20000.0, 21000.0]})
    monkeypatch.setattr(mm, "read_sql", fake_read)
    b = mm._build_benchmark_nav()
    assert seen["params"] == ["NIFTY 50"]
    assert list(b["bench_nav"]) == [100.0, 105.0]


def test_calendar_bench_is_the_index_return_not_a_constant():
    days = pd.bdate_range("2022-01-03", "2024-12-31")
    nav = pd.DataFrame({"nav_date": days, "nav": [10.0 + 0.001 * i for i in range(len(days))]})
    bench = pd.DataFrame({"date": days, "bench_nav": [100.0 * (1 + 0.0008 * i) for i in range(len(days))]})
    rows = mm._calendar_returns(nav, bench)
    by_year = {r["year"]: r["bench_ret_pct"] for r in rows}
    assert by_year[2022] != by_year[2024]
    assert all(v is not None and v > 0 for v in by_year.values())


def test_no_benchmark_means_no_spread_column_values():
    days = pd.bdate_range("2022-01-03", "2022-12-31")
    nav = pd.DataFrame({"nav_date": days, "nav": [10.0 + 0.001 * i for i in range(len(days))]})
    assert mm._calendar_returns(nav, None)[0]["bench_ret_pct"] is None
