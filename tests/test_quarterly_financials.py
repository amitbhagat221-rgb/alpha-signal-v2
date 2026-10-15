"""The stock page's quarterly table (cockpit/api.get_quarterly_financials).

2026-10-15: /stocks/HDB and /api/quarterly/HDB returned 500 — HDB's consolidated rows carry
no operating_expenses, so the EBITDA column came back all-NULL (object dtype) and .round()
raised. They also stopped at 2025-03 while standalone runs to 2026-06 (24 stocks like it), so
even without the crash the page showed quarters 15 months old."""
import pandas as pd

from cockpit import api


def _rows(basis_end, n, opex):
    ends = pd.date_range(end=basis_end, periods=n, freq="QE").strftime("%Y-%m-%d")[::-1]
    return pd.DataFrame({"period": ends, "end_date": ends, "revenue": 100.0, "net_income": 10.0, "eps": 1.0,
                         "ebitda": 20.0, "operating_profit": 15.0, "pbt": 12.0,
                         "operating_expenses": [opex] * n})


def _fake(cons, stand):
    def read_sql(sql, params=None):
        return (cons if params[1] == "consolidated" else stand).copy()
    return read_sql


def test_all_null_operating_expenses_falls_back_to_stored_ebitda(monkeypatch):
    monkeypatch.setattr(api, "read_sql", _fake(_rows("2026-06-30", 8, None), _rows("2026-06-30", 8, 70.0)))
    out = api.get_quarterly_financials("X")
    assert out["quarters"][0]["ebitda"] == 20.0 and out["quarters"][0]["ebitda_margin"] == 20.0


def test_stale_consolidated_gives_way_to_fresher_standalone(monkeypatch):
    monkeypatch.setattr(api, "read_sql", _fake(_rows("2025-03-31", 8, 70.0), _rows("2026-06-30", 8, 70.0)))
    assert api.get_quarterly_financials("X")["quarters"][0]["end_date"] == "2026-06-30"


def test_current_consolidated_is_kept(monkeypatch):
    cons = _rows("2026-06-30", 8, 70.0).assign(revenue=200.0)
    monkeypatch.setattr(api, "read_sql", _fake(cons, _rows("2026-06-30", 8, 70.0)))
    assert api.get_quarterly_financials("X")["quarters"][0]["revenue"] == 200.0
