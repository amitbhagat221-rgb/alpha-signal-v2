"""Backtest engine and label rules fixed by the factor audit (plan 0020)."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

import pit
from tools import backtest_pit as bt
from tools.compute_corporate_adjustments import parse_bonus_factor


def _prices(closes, sid="A", start="2026-01-01"):
    days = pd.bdate_range(start, periods=len(closes)).strftime("%Y-%m-%d")
    return pd.DataFrame({"sid": sid, "date": days, "close": closes})


def test_label_is_on_one_share_basis():
    """A 5:1 split inside the 20-day window is not an 80% loss."""
    px = _prices([100.0] * 10 + [20.0] * 20)
    adj = pd.DataFrame({"sid": ["A"], "ex_date": [px["date"][10]], "factor": [0.2]})
    raw = pit.pit_fwd_return_20d(date(2026, 1, 1), px)
    fixed = pit.pit_fwd_return_20d(date(2026, 1, 1), px, adj)
    assert raw["fwd_return_20d"].iloc[0] == -0.8
    assert fixed["fwd_return_20d"].iloc[0] == 0.0


def test_bonus_of_preference_shares_is_not_a_price_adjustment():
    assert parse_bonus_factor("Bonus 1:1") == 0.5
    assert parse_bonus_factor("Scheme Of Arrangement - Bonus Ncrps 4:1") is None
    assert parse_bonus_factor("Bonus Debentures 1:1") is None


def test_no_verdict_or_interval_on_a_handful_of_anchors():
    few = [(f"d{i}", ic, 50) for i, ic in enumerate([0.30, 0.31])]
    row = bt._aggregate(few, "x", "LARGE", "v2_recompute")
    assert row["verdict"] == "INSUFFICIENT" and row["t_stat_ci_lo"] is None
    assert bt._verdict(19.4, n_periods=2) == "INSUFFICIENT"
    assert bt._verdict(3.0, n_periods=bt.IC_MIN_PERIODS) == "KEEP"


def test_interval_brackets_the_reported_t():
    """The CI is centred on the reported (Newey-West) t, also for overlapping series."""
    rng = np.random.default_rng(0)
    ics = 0.03 + 0.05 * np.convolve(rng.standard_normal(123), np.ones(4) / 4, mode="valid")   # autocorrelated
    for lag in (0, 3, 13):
        row = bt._aggregate([(f"d{i}", x, 50) for i, x in enumerate(ics)], "x", "SMALL", "v2_recompute",
                            cadence="weekly" if lag else "monthly", nw_lag=lag)
        assert row["t_stat_ci_lo"] < row["t_stat"] < row["t_stat_ci_hi"], (lag, row)


def test_fiscal_year_eps_is_not_known_at_year_end():
    """forecast_history eps rows are dated at fiscal year-end; they become an input
    only after the annual filing lag."""
    fh = pd.DataFrame({"sid": "A", "metric": "eps", "date": ["2024-03-31", "2025-03-31"], "value": [10.0, 12.0]})
    raw = {"fh": fh}
    assert list(pit._pit_input({}, raw, "fh", date(2025, 4, 1))["date"]) == ["2024-03-31"]
    assert len(pit._pit_input({}, raw, "fh", date(2025, 3, 31) + pd.Timedelta(days=pit.ANNUAL_LAG))) == 2


def test_a_past_anchor_carries_the_tier_of_its_own_date():
    """tiers_at ranks by the market cap of THAT day; today's tier in `stocks` plays no part."""
    n = 300
    sids = [f"S{i:03d}" for i in range(n)]
    px = pd.DataFrame({"sid": sids, "date": "2021-06-01", "close": 100.0, "volume": 1e6, "adj_close": 100.0})
    raw = {
        "bs": pd.DataFrame({"sid": sids, "end_date": "2020-03-31", "total_equity": 1000.0,
                            "shares_outstanding": [float(n - i + 10) for i in range(n)]}),   # S000 is the largest; all ≥ ₹1,000 Cr
        "fund_screener": pd.DataFrame(columns=["sid", "period_end", "line_item", "value"]),
        "adjustments": pd.DataFrame(columns=["sid", "ex_date", "factor", "inds"]),
        "qi": pd.DataFrame({"sid": [s for s in sids for _ in range(4)], "end_date": "2020-12-31"}),
    }
    tiers = pit.tiers_at(date(2021, 6, 1), raw, px)
    assert [tiers[s] for s in ("S000", "S099", "S100", "S249", "S250")] == ["LARGE", "LARGE", "MID", "MID", "SMALL"]
    thin = px.assign(volume=px["volume"].where(px["sid"] != "S299", 10.0))                # ₹0.0001 Cr a day
    assert pit.tiers_at(date(2021, 6, 1), raw, thin)["S299"] == "SMALL"                   # illiquid, but large enough and with 4 quarters
    raw["qi"] = raw["qi"][raw["qi"]["sid"] != "S299"]
    assert pit.tiers_at(date(2021, 6, 1), raw, thin)["S299"] == "MICRO"


def test_a_factor_with_no_value_counts_as_the_middle_of_the_tier():
    """Two stocks identical on the factors both have; one lacks a factor. It must not score
    higher than the complete one for lacking it, and its score is pulled towards 0.5."""
    import factors
    from config import MISSING_FACTOR_SCORE
    from scoring import screener
    tier = "MID"
    w = factors.SIGNAL_WEIGHTS[tier]
    cols = {k: factors.SCREENER_TIER_COLS.get((k, tier)) or factors.SCREENER_COLS[k] for k in w}
    n = 60
    df = pd.DataFrame({"sid": [f"S{i:02d}" for i in range(n)], "cap_tier": tier, "sector": "Energy", "penalty": 0.0})
    for k, c in cols.items():
        df[c] = np.arange(n, dtype=float) if w[k] > 0 else -np.arange(n, dtype=float)      # S59 is best on everything
    first = next(iter(cols.values()))
    df.loc[df["sid"] == "S58", first] = np.nan                                              # second best, one factor missing
    out = screener.score_universe(df, weights={tier: w}).set_index("sid")
    top, gap = out.loc["S59", "base_score"], out.loc["S58", "base_score"]
    assert top == pytest.approx(1.0, abs=0.01) and gap < top
    k0 = next(iter(w))
    full_rank = 59 / 60                                                                     # S58's percentile on the factors it has
    assert gap == pytest.approx((1 - abs(w[k0])) * full_rank + abs(w[k0]) * MISSING_FACTOR_SCORE, abs=0.02)


def test_a_wired_factors_input_is_never_silently_optional(monkeypatch):
    """bse_results feeds the wired announcement_car: an empty or unreadable frame must stop
    the run, not turn into an empty input that scores every stock as neutral (ADR 0064)."""
    import pandas as pd
    assert "bse_results" in pit._wired_raw_keys() and "bse_results" in pit.RAW_OPTIONAL
    monkeypatch.setattr(pit, "read_sql", lambda sql, **kw: pd.DataFrame())
    with pytest.raises(RuntimeError, match="bse_results"):
        pit.load_raw({"bse_results"})
    optional_unwired = next(k for k in pit.RAW_OPTIONAL if k not in pit._wired_raw_keys())
    assert pit.load_raw({optional_unwired})[optional_unwired].empty    # benched input: still optional


def test_one_label_function_for_every_horizon():
    """forward_returns is the panel label and the horizon label: 20 sessions equals
    pit_fwd_return_20d, a horizon that has not elapsed has no column."""
    px = _prices([100.0 + i for i in range(30)])
    fr = pit.forward_returns(date(2026, 1, 1), px, None, (5, 20, 60))
    assert fr["fwd_return_20d"].iloc[0] == pit.pit_fwd_return_20d(date(2026, 1, 1), px)["fwd_return_20d"].iloc[0]
    entry = px.loc[px["date"] > "2026-01-01", "close"].iloc[0]
    assert fr["fwd_return_5d"].iloc[0] == round(px["close"].iloc[px.index[px["close"] == entry][0] + 5] / entry - 1, 4)
    assert "fwd_return_60d" not in fr


def test_dead_names_get_a_tier_from_traded_value():
    """A dead name has no share count: MICRO when illiquid, else the tier of its nearest
    listed neighbours by traded value (tools/unlisted_panel)."""
    from tools import unlisted_panel as up
    listed = pd.DataFrame({"cap_tier": ["LARGE"] * 30 + ["MID"] * 30 + ["SMALL"] * 30,
                           "adtv_cr": [500.0 + i for i in range(30)] + [50.0 + i for i in range(30)] + [5.0 + i / 10 for i in range(30)]})
    t = up.estimate_tiers(pd.Series({"big": 520.0, "mid": 60.0, "small": 6.0, "thin": 0.4}), listed)
    assert t.to_dict() == {"big": "LARGE", "mid": "MID", "small": "SMALL", "thin": "MICRO"}
    assert set(up.PRODUCERS) >= {"momentum", "delivery", "residual_momentum_12_1"}   # derived from the registry


def test_full_market_rows_are_never_the_evidence_row():
    assert bt.FULL_MARKET.startswith("v2_full_market")
