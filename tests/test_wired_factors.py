"""Golden tests: every wired factor's compute function on a small hand-made input, the
expected value worked out from the factor's written definition (plan 0020 P5: what only
breaks when code changes is a test). No DB. sector_tilt has its own in test_sector_tilt.py.

A test here fails when a refactor changes what a wired factor computes; the scenario
it encodes is in its docstring."""
import numpy as np
import pandas as pd
import pytest

import factors
from signals import accruals, announcement_car, asset_growth, delivery_anomaly, eps_revision, piotroski
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
               "avg_delivery_pct_30d", "sector_tilt"}
    assert {k for ws in factors.SIGNAL_WEIGHTS.values() for k in ws} <= covered


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
