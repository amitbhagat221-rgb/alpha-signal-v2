"""The minute → session summary behind the intraday factors (tools/intraday_slow_study.py): sums
not ratios, the session window, the 10-minute candles, the tick rule. Offline, synthetic bars."""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from sources import kite_bars as kb
from tools import intraday_slow_study as st


def _bars(day, closes, volumes, start=(9, 15)):
    t0 = datetime(day.year, day.month, day.day, *start, tzinfo=kb.IST)
    return pd.DataFrame({"sid": "X", "ts": [pd.Timestamp(t0 + timedelta(minutes=i)).tz_convert("UTC") for i in range(len(closes))],
                         "close": [int(round(c * 100)) for c in closes], "volume": volumes})


def test_one_flat_session_has_zero_moments_and_full_counts():
    closes, vols = [100.0] * 375, [10] * 375
    d = st.daily_summary(_bars(datetime(2026, 10, 9), closes, vols))
    r = d.iloc[0]
    assert len(d) == 1 and r["n_bars"] == 375 and r["vol"] == 3750 and r["value"] == pytest.approx(375000.0)
    assert r["rv_10m"] == 0 and r["rv_5m"] == 0 and r["r3_10m"] == 0 and r["bpv_10m"] == 0
    assert r["n_10m"] == 37 and r["n_5m"] == 74          # 375 minutes → 38 ten-minute candles → 37 returns
    assert r["vol_first30"] == 300 and r["vol_last30"] == 300 and r["vwap_close_den"] == 300
    assert r["r_first30"] == 0 and r["r_mid"] == 0 and r["r_last30"] == 0
    assert r["signed_vol"] == 0                           # no tick ever moved: nothing is signed
    assert r["flat_at_high_min"] == 375 and r["flat_at_low_min"] == 375


def test_tick_rule_and_ten_minute_returns():
    # price steps up 1 % at minute 10, flat otherwise, then down 1 % at minute 20
    closes = [100.0] * 10 + [101.0] * 10 + [99.99] * 355
    vols = [1] * 375
    r = st.daily_summary(_bars(datetime(2026, 10, 9), closes, vols)).iloc[0]
    # tick rule: bar 10 up (+1), bars 11-19 carry +1, bar 20 down (−1), bars 21.. carry −1; bars 0-9 unsigned
    assert r["signed_vol"] == (10 - 355)
    # 10-minute candles: last closes 100, 101, 99.99, 99.99 … → two non-zero returns
    expect = np.log(101 / 100) ** 2 + np.log(99.99 / 101) ** 2
    assert r["rv_10m"] == pytest.approx(expect)
    assert r["rs_up_10m"] == pytest.approx(np.log(101 / 100) ** 2)
    assert r["r_first30"] == pytest.approx(np.log(99.99 / 100))


def test_bars_outside_the_regular_session_are_ignored_and_days_are_separate():
    day = datetime(2026, 10, 9)
    regular = _bars(day, [100.0] * 5, [1] * 5)
    muhurat = _bars(day, [200.0] * 5, [1] * 5, start=(18, 0))
    nxt = _bars(day + timedelta(days=1), [50.0] * 5, [2] * 5)
    d = st.daily_summary(pd.concat([regular, muhurat, nxt], ignore_index=True))
    assert list(d["n_bars"]) == [5, 5] and list(d["px_last"]) == [100.0, 50.0] and list(d["vol"]) == [5, 10]


def test_label_90d_enters_after_the_anchor_and_exits_inside_ninety_days():
    dates = pd.bdate_range("2025-01-01", "2025-06-30")
    adj = pd.DataFrame({"A": np.linspace(100, 200, len(dates))}, index=dates)
    lab = st.label_90d(adj, pd.Timestamp("2025-02-03"))
    i = dates.searchsorted(pd.Timestamp("2025-02-03"), side="right")
    j = dates.searchsorted(pd.Timestamp("2025-05-04"), side="right") - 1
    assert lab["A"] == pytest.approx(adj["A"].iloc[j] / adj["A"].iloc[i] - 1)
    assert st.label_90d(adj, pd.Timestamp("2025-06-01")) is None     # window not complete
