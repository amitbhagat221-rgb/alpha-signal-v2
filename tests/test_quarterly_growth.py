"""q_ebitda_chg (signals/quarterly_growth.py): one compute function for live and PIT.
The rules that keep it honest: YoY only inside one source + basis, NSE first filing only,
known strictly after filed_at, a staleness gate, Financials excluded."""
import pandas as pd

from signals.quarterly_growth import compute_q_ebitda_chg

STOCKS = pd.DataFrame({"sid": ["A", "B", "BANK"], "sector": ["Industrials", "Industrials", "Financials"]})


def _nse(sid, quarters, filed_offset_days=45, basis="consolidated"):
    rows = []
    for pe, rev, pbt in quarters:
        rows.append(dict(sid=sid, period_end=pe, basis=basis,
                         filed_at=(pd.Timestamp(pe) + pd.Timedelta(days=filed_offset_days)).strftime("%Y-%m-%d %H:%M:%S"),
                         revenue=rev, other_income=0.0, finance_costs=0.0, depreciation=0.0,
                         pbt_pre_exceptional=pbt))
    return pd.DataFrame(rows)


QS = [("2023-06-30", 100, 10), ("2023-09-30", 100, 10), ("2023-12-31", 100, 10), ("2024-03-31", 100, 10),
      ("2024-06-30", 120, 25)]


def test_yoy_inside_nse_scaled_by_year_ago_revenue():
    out = compute_q_ebitda_chg(STOCKS, _nse("A", QS), None, "2024-09-30").set_index("sid")
    assert out.loc["A", "q_ebitda_chg"] == (25 - 10) / 100


def test_filing_on_the_anchor_day_is_not_yet_known():
    nse = _nse("A", QS)
    anchor = nse["filed_at"].iloc[-1][:10]                  # the 2024-06 quarter's filing day
    out = compute_q_ebitda_chg(STOCKS, nse, None, anchor)
    assert out.empty                                         # 2024-03 has no year-ago quarter


def test_first_filing_wins_over_a_later_restatement():
    nse = _nse("A", QS)
    restated = nse.iloc[[-1]].assign(pbt_pre_exceptional=99.0, filed_at="2024-09-01 10:00:00")
    out = compute_q_ebitda_chg(STOCKS, pd.concat([nse, restated]), None, "2024-10-01").set_index("sid")
    assert out.loc["A", "q_ebitda_chg"] == 0.15


def test_never_compares_across_sources():
    nse = _nse("B", QS[:4])                                  # 2023-06 … 2024-03 on NSE
    qi = pd.DataFrame({"sid": ["B"], "end_date": ["2024-06-30"], "reporting": ["consolidated"],
                       "revenue": [120.0], "ebitda": [25.0]})   # the next quarter only on Tickertape
    assert compute_q_ebitda_chg(STOCKS, nse, qi, "2024-09-30").empty


def test_stale_quarters_are_dropped():
    assert compute_q_ebitda_chg(STOCKS, _nse("A", QS), None, "2025-06-30").empty


def test_financials_are_null():
    assert compute_q_ebitda_chg(STOCKS, _nse("BANK", QS), None, "2024-09-30").empty
