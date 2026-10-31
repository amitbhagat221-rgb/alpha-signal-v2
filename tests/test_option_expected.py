"""Expected-profit defaults (option_expected, plan 0029): the backtest's weeks with the live VIX guard — offline."""

import pandas as pd

import option_expected as oe

S = {"vix_halve": 27.0, "vix_halt": 30.0}


B = 20.0 * 1.18                                     # brokerage + GST an order, added back per lot


def _trades():
    rows = [("2023-01-03", 10.0, 9.0, 14.0), ("2023-01-10", 10.0, -30.0, 15.0), ("2023-01-17", 10.0, 9.2, 28.0),
            ("2024-01-02", 10.0, 8.8, 16.0), ("2024-01-09", 10.0, -500.0, 35.0)]     # the last: VIX 35, guard sits out
    return pd.DataFrame([{"entry": e, "expiry": e, "credit": c, "net": n - 2 * B / 50, "vix": v, "lot": 50, "F": 20000.0}
                         for e, c, n, v in rows])


def test_stats_apply_the_vix_guard_and_split_wins_from_losses():
    st = oe.stats(_trades(), S, 2)
    assert st["n"] == 4 and st["n_all"] == 5 and st["traded_share"] == 0.8      # VIX ≥ 30: no entry
    assert abs(st["keep"] - (0.9 + 0.92 + 0.88) / 3) < 1e-9                       # winners, as a share of credit
    assert abs(st["loss"] - 3.0) < 1e-9 and abs(st["worst"] - 3.0) < 1e-9
    assert abs(st["loss_pct"] - 30.0 / 20000) < 1e-12 and len(st["losses_pct"]) == 1   # the same loss as a share of the index     # the −50× week never traded
    assert abs(st["loss_per_year"] - 52 / 4) < 1e-9
    assert [w["w"] for w in st["weeks"]] == [1.0, 1.0, 0.5, 1.0]
    assert abs(st["weeks"][0]["r"] - 0.9) < 1e-9                                  # one lot's brokerage is not in r                  # VIX 28 > 27: half the lots
    assert [(y["year"], y["weeks"], y["loss_weeks"]) for y in st["years"]] == [("2023", 3, 1), ("2024", 1, 0)]


def test_expected_week_from_the_defaults_is_the_backtest_mean():
    st = oe.stats(_trades(), S, 2)
    p = st["loss_per_year"] / 52
    assert abs((1 - p) * st["keep"] - p * st["loss"] - st["mean"]) < 1e-9        # the page's week = the average week
