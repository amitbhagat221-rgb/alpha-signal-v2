"""Golden tests: every wired factor's compute function on a small hand-made input, the
expected value worked out from the factor's written definition (plan 0020 P5: what only
breaks when code changes is a test). No DB. sector_tilt has its own in test_sector_tilt.py.

A test here fails when a refactor changes what a wired factor computes; the scenario
it encodes is in its docstring."""
import numpy as np
import pandas as pd
import pytest

import factors
from signals import accruals, announcement_car, asset_growth, consensus_beat, delivery_anomaly, eps_revision, piotroski
from signals.fno_iv_factors import compute_iv_factors
from signals.nlp_factors import compute_nlp_factors
from signals.nlp_scores import score_text
from signals.residual_momentum import compute_residual_momentum_12_1

import pit


def _days(n, start="2025-01-01"):
    return list(pd.bdate_range(start, periods=n).strftime("%Y-%m-%d"))


def test_every_wired_factor_has_a_golden_test():
    covered = {"announcement_car", "iv_skew_25d", "asset_growth_yoy", "forward_looking_intensity",
               "residual_momentum_12_1", "piotroski", "consensus", "accruals", "delivery_anomaly_z",
               "avg_delivery_pct_30d", "sector_tilt", "cons_beat_rate_4q",
               # MID grade-B factors, ADR 0074
               "debt_structure", "pcr_volume", "value_composite", "gold_beta", "fcf_yield"}
    assert {k for ws in factors.SIGNAL_WEIGHTS.values() for k in ws} <= covered


def test_cons_beat_rate_is_the_share_of_the_last_four_results_that_beat():
    """Five reports before the eval date: the oldest (a miss) falls out of the last four,
    which hold 3 beats (one tie counts as no beat) → 0.75. A report ON the eval date is not
    yet known; a re-stated estimate keeps only its latest version; a stock with two reports
    in the window has no reading."""
    rows = []
    for d, act, est in [("2025-06-01", 1.0, 2.0), ("2025-09-01", 3.0, 2.0), ("2025-12-01", 2.0, 2.0),
                        ("2026-03-01", 3.0, 2.0), ("2026-06-01", 3.0, 2.0), ("2026-09-01", 0.0, 9.0)]:
        rows += [("A", "eps_actual", d, act, "2026-10-01"), ("A", "eps_estimate", d, est, "2026-10-01")]
    rows += [("A", "eps_estimate", "2026-06-01", 5.0, "2026-05-01")]      # older version: ignored
    rows += [("B", m, d, v, "2026-10-01") for d in ("2026-03-01", "2026-06-01")
             for m, v in (("eps_actual", 2.0), ("eps_estimate", 1.0))]
    est = pd.DataFrame(rows, columns=["sid", "metric", "target_period", "value", "fetched_at"])
    out = consensus_beat.compute_cons_beat_rate_4q(est, as_of_date="2026-09-01").set_index("sid")
    assert out.loc["A", "cons_beat_rate_4q"] == 0.75
    assert "B" not in out.index


def test_delivery_level_and_anomaly():
    """avg = mean of the last 30 sessions; z = (latest − mean of the earlier rows of the
    90-session window) / their std."""
    vals = [40.0, 60.0] * 20 + [80.0]                          # 40 baseline rows, mean 50, then a spike
    px = pd.DataFrame({"sid": "A", "date": _days(41), "delivery_pct": vals})
    z = delivery_anomaly.delivery_anomaly_z(px)["delivery_anomaly_z"].iloc[0]
    assert z == pytest.approx(round(30 / np.std([40.0, 60.0] * 20, ddof=1), 3))
    avg = pit.pit_avg_delivery(px)["avg_delivery_pct_30d"].iloc[0]
    assert avg == round(np.mean(vals[-30:]), 2)


def test_announcement_car_is_the_market_adjusted_three_day_return():
    """[−1, +1] sessions around the first filing of a cluster: stock 100 → 110 while NIFTY
    1000 → 1050 is a CAR of +5%. A corrigendum 10 days later does not replace it."""
    d = _days(30)
    closes = [100.0] * 10 + [100.0, 104.0, 110.0] + [110.0] * 17   # day0 = d[11]
    nifty = [1000.0] * 10 + [1000.0, 1020.0, 1050.0] + [1050.0] * 17
    car = announcement_car._car_latest(d, closes, d, nifty, [d[11], d[21]], d[-1], d[0])
    assert car == pytest.approx(0.10 - 0.05)
    assert announcement_car._first_of_cluster([d[11], d[21]]) == [d[11]]


def test_residual_momentum_is_the_return_beta_does_not_explain():
    """Stock log return = 0.001 + 1.5 × market every day: β = 1.5 and the residual
    12-1 momentum is 0.001 × the 231 daily returns of the window (skipping the last 21)."""
    rng = np.random.default_rng(7)
    n = 300
    d = _days(n)
    m = rng.normal(0, 0.01, n - 1)
    nifty = 1000 * np.exp(np.concatenate([[0], np.cumsum(m)]))
    stock = 100 * np.exp(np.concatenate([[0], np.cumsum(0.001 + 1.5 * m)]))
    out = compute_residual_momentum_12_1(pd.DataFrame({"sid": "A", "date": d, "close": stock}),
                                         pd.DataFrame({"date": d, "value": nifty}))
    assert out["residual_momentum_12_1"].iloc[0] == pytest.approx(0.231, abs=1e-4)


def test_reported_eps_growth_is_change_over_absolute_base():
    """consensus (MID): year-on-year change of reported EPS over |prior| — a loss of −10
    turning into a profit of 5 is +150%, not −150%."""
    g = lambda a, b: pd.DataFrame({"sid": "A", "date": ["2024-03-31", "2025-03-31"], "value": [a, b]})
    assert eps_revision._yoy(g(10.0, 15.0)) == 50.0
    assert eps_revision._yoy(g(-10.0, 5.0)) == 150.0


def test_asset_growth_and_its_floor():
    bs = pd.DataFrame({"sid": ["A", "A", "B", "B", "F", "F"],
                       "end_date": ["2024-03-31", "2025-03-31"] * 3,
                       "total_assets": [100.0, 120.0, 40.0, 80.0, 100.0, 150.0]})
    stocks = pd.DataFrame({"sid": ["A", "B", "F"], "sector": ["Industrials", "Industrials", "Financials"]})
    out = asset_growth.compute_asset_growth_yoy(bs=bs, stocks=stocks).set_index("sid")["asset_growth_yoy"]
    assert out.to_dict() == {"A": 20.0}        # B: prior base under ₹50 Cr; F: Financials excluded


def test_cash_flow_accruals():
    """(trailing-year net income − operating cash flow) / average total assets:
    (100 − 60) / ((400 + 500) / 2)."""
    qi = pd.DataFrame({"end_date": ["2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31"], "net_income": [25.0] * 4})
    cf = pd.DataFrame({"period": ["2025-03"], "operating_cash_flow": [60.0]})
    bs = pd.DataFrame({"period": ["2024-03", "2025-03"], "total_assets": [400.0, 500.0]})
    assert accruals._cf_accruals(qi, cf, bs) == pytest.approx(40 / 450)


def test_piotroski_all_nine_tests_pass():
    """Better on every leg year on year — profit, cash flow, ROA, accruals, leverage,
    liquidity, no new shares, operating margin, asset turnover — scores 9."""
    q = lambda y, rev, ni, opex: [{"sid": "A", "end_date": f"{y}-{m}", "reporting": "consolidated", "revenue": rev,
                                   "net_income": ni, "operating_expenses": opex, "pbt": ni * 1.3, "period": f"{y}-{m}"}
                                  for m in ("06-30", "09-30", "12-31")] + \
                                 [{"sid": "A", "end_date": f"{y + 1}-03-31", "reporting": "consolidated", "revenue": rev,
                                   "net_income": ni, "operating_expenses": opex, "pbt": ni * 1.3, "period": f"{y + 1}-03-31"}]
    qi = pd.DataFrame(q(2023, 100.0, 5.0, 90.0) + q(2024, 120.0, 10.0, 100.0))
    bs = pd.DataFrame({"sid": "A", "period": ["2024-03", "2025-03"], "total_assets": [1000.0, 1000.0],
                       "current_assets": [300.0, 400.0], "current_liabilities": [200.0, 200.0],
                       "long_term_debt": [300.0, 200.0], "shares_outstanding": [10.0, 10.0]})
    cf = pd.DataFrame({"sid": "A", "period": ["2024-03", "2025-03"], "operating_cash_flow": [30.0, 50.0]})
    stocks = pd.DataFrame({"sid": ["A"], "sector": ["Industrials"], "cap_tier": ["MID"]})
    assert piotroski._compute_scores(stocks, qi, bs, cf).set_index("sid").loc["A", "f_score"] == 9


def test_forward_looking_intensity_counts_per_thousand_words():
    text = ("revenue was steady this period " * 199) + "we will grow and expect more guidance next year"
    s = score_text(text)
    assert s["word_count"] == 1004
    assert s["forward_looking_intensity"] == round(4 / (1004 / 1000), 2)   # will, expect, guidance, next year


def test_forward_looking_intensity_uses_the_latest_call_known_then():
    nlp = pd.DataFrame({"sid": ["A", "A"], "doc_date": ["2026-05-01", "2026-08-01"],
                        "available_date": ["2026-05-20", "2026-08-20"], "net_tone": [0.0, 0.0],
                        "uncertainty_density": [0.0, 0.0], "forward_looking_intensity": [10.0, 14.0]})
    early = compute_nlp_factors(nlp=nlp, as_of_date="2026-08-10").set_index("sid")
    late = compute_nlp_factors(nlp=nlp, as_of_date="2026-08-25").set_index("sid")
    assert early.loc["A", "forward_looking_intensity"] == 10.0     # the August call was filed on the 20th
    assert late.loc["A", "forward_looking_intensity"] == 14.0


def test_iv_skew_is_today_reading_and_a_stale_one_is_dropped():
    """iv_skew_25d is the stored 25-delta skew of the latest trade date; a reading older than
    pit.DERIVATIVE_MAX_AGE_DAYS is not scored (SAIL ranked on an expired contract, 2026-10-03)."""
    iv = pd.DataFrame({"sid": ["A", "B"], "trade_date": ["2026-10-07", "2026-09-11"],
                       "atm_iv": [0.30, 0.40], "iv_skew_25d": [0.05, 0.09], "iv_term_structure": [0.01, 0.02]})
    out = compute_iv_factors(iv_hist=iv, prices=None, as_of_date="2026-10-08",
                             max_age_days=pit.DERIVATIVE_MAX_AGE_DAYS).set_index("sid")
    assert out.loc["A", "iv_skew_25d"] == pytest.approx(0.05)
    assert "B" not in out.index or pd.isna(out.loc["B", "iv_skew_25d"])


def test_snapshot_rows_bind_in_sqlite():
    """output.snapshot writes pd.NA-bearing nullable integers (piotroski_f): every value
    must reach sqlite as a plain value or None (failed the first live write, 2026-10-09)."""
    import sqlite3
    out = pd.DataFrame({"sid": ["A", "B"], "piotroski_f": pd.array([7, pd.NA], dtype="Int64"), "x": [1.0, np.nan]})
    clean = out.astype(object).where(out.notna(), None)
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE t (sid, piotroski_f, x)")
    con.executemany("INSERT INTO t VALUES (?, ?, ?)", clean.itertuples(index=False))
    assert con.execute("SELECT COUNT(*) FROM t WHERE piotroski_f IS NULL AND x IS NULL").fetchone()[0] == 1


# ── MID grade-B factors wired under ADR 0074 (2026-10-13) ──

def _fund(rows):
    return pd.DataFrame(rows, columns=["sid", "period_end", "line_item", "value"])


def test_debt_structure_is_the_long_term_share_of_borrowings_latest_year():
    """Long-term borrowings / total borrowings from the newest annual statement, clipped to 0-1;
    a stock with under ₹50 cr of borrowings is not scored (MIN_BORROWINGS_CR)."""
    from signals import debt_structure
    fund = _fund([("A", "2024-03-31", "Long term Borrowings", 10), ("A", "2024-03-31", "Borrowings", 100),
                  ("A", "2025-03-31", "Long term Borrowings", 30), ("A", "2025-03-31", "Borrowings", 120),
                  ("B", "2025-03-31", "Long term Borrowings", 20), ("B", "2025-03-31", "Borrowings", 40)])
    out = debt_structure._compute(None, fund).set_index("sid")
    assert list(out.index) == ["A"]
    assert out.loc["A", "debt_structure"] == pytest.approx(0.25)


def test_fcf_is_the_three_year_median_of_cfo_minus_capex():
    """capex = max(ΔPP&E, 0) + depreciation, PP&E = Net Block + CWIP; FCF = CFO − capex; the yield's
    numerator is the median of the last 3 years and needs all 3 (signals/fcf_yield.fcf_median)."""
    from signals.fcf_yield import fcf_median
    rows = []
    for y, ppe in zip((2022, 2023, 2024, 2025), (100, 120, 110, 150)):
        d = f"{y}-03-31"
        rows += [("A", d, "Net Block", ppe), ("A", d, "Capital Work in Progress", 0),
                 ("A", d, "Depreciation", 10), ("A", d, "Cash from Operating Activity", 50)]
    out = fcf_median(_fund(rows)).set_index("sid")
    # FCF: 2023 50-(20+10)=20 · 2024 50-(0+10)=40 · 2025 50-(40+10)=0 → median 20
    assert out.loc["A", "fcf"] == pytest.approx(20.0)
    assert out.loc["A", "years_used"] == 3


def test_pcr_volume_is_the_latest_put_call_volume_ratio_capped():
    """Today's put/call volume ratio from the newest option-chain row, capped at 20 (PCR_CLIP)."""
    from signals.fno_oi_factors import compute_oi_factors
    h = pd.DataFrame({"sid": ["A", "A", "B"], "trade_date": ["2026-10-01", "2026-10-02", "2026-10-02"],
                      "expiry_date": ["2026-10-29"] * 3, "underlying_price": [100, 101, 50],
                      "total_call_oi": [10, 10, 5], "total_put_oi": [8, 9, 4], "pcr_oi": [0.8, 0.9, 0.8],
                      "pcr_volume": [1.5, 0.7, 25.0], "max_pain_distance": [0.01, 0.01, 0.02]})
    out = compute_oi_factors(h).set_index("sid")
    assert out.loc["A", "pcr_volume"] == pytest.approx(0.7)
    assert out.loc["B", "pcr_volume"] == pytest.approx(20.0)


def test_gold_beta_is_the_ols_slope_and_needs_120_days():
    """β(stock, gold) = cov / var over overlapping daily returns; fewer than 120 days → no value."""
    from signals.macro_betas import _beta
    rng = np.random.default_rng(7)
    g = pd.Series(rng.normal(0, 0.01, 150), index=pd.RangeIndex(150))
    assert _beta(2.0 * g, g) == pytest.approx(2.0)
    assert np.isnan(_beta(2.0 * g.iloc[:100], g.iloc[:100]))


def test_value_composite_weights_earnings_yield_book_to_price_and_52w_position():
    """Within-tier percentiles weighted 40 % earnings yield, 35 % book-to-price, 25 % 52-week
    position; a missing part drops out and the rest are renormalised."""
    df = pd.DataFrame({"sid": ["a", "b", "c"], "cap_tier": "MID", "earnings_yield": [1, 2, 3],
                       "book_to_price": [3, 2, 1], "position_52w": [np.nan, 1, 2]})
    out = pit.pit_value_composite(df).set_index("sid")["value_composite"]
    assert out["a"] == pytest.approx((0.40 / 3 + 0.35 * 1) / 0.75, abs=1e-4)
    assert out["b"] == pytest.approx(0.40 * 2 / 3 + 0.35 * 2 / 3 + 0.25 * 0.5, abs=1e-4)
    assert out["c"] == pytest.approx(0.40 + 0.35 / 3 + 0.25, abs=1e-4)
