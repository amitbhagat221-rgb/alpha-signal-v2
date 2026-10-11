"""Kite minute-bar archive (ADR 0072): the write contract, the stop rule, the file and its
manifest row. Offline: a fake Kite client and a temp DB, never the network or the live DB."""
import re
import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd
import pyarrow.parquet as pq
import pytest

import db
from sources import kite_bars as kb

IST = kb.IST


def _bars(day, n=3, close=100.0, start=(9, 15)):
    t0 = datetime(day.year, day.month, day.day, *start, tzinfo=IST)
    return [{"date": t0 + timedelta(minutes=i), "open": close, "high": close, "low": close,
             "close": close + i * 0.05, "volume": 10 * i} for i in range(n)]


def test_kite_candles_become_four_columns_in_paise_and_utc():
    df = kb.to_frame("RELI", _bars(date(2026, 10, 9)))
    assert list(df.columns) == ["sid", "ts", "close", "volume"]
    assert df["close"].tolist() == [10000, 10005, 10010]
    assert str(df["ts"].iloc[0]) == "2026-10-09 03:45:00+00:00"           # 09:15 IST


def test_2015_placeholders_and_stray_prints_are_cleaned_but_a_real_zero_is_not():
    day = date(2015, 5, 18)
    bars = _bars(day, n=4)
    bars[0] = dict(bars[0], close=0, volume=0)                                # pre-trade placeholder: dropped
    bars.append(dict(bars[2], date=bars[2]["date"] + timedelta(seconds=38)))  # copy of 09:17 at 09:17:38: dropped
    bars.append(dict(bars[3], date=bars[3]["date"] + timedelta(minutes=1, seconds=1), volume=7))  # lone 09:19:01: kept
    df = kb.to_frame("COFO", bars)
    kb.validate(df)
    assert [t.strftime("%H:%M:%S") for t in df["ts"].dt.tz_convert(IST)] == ["09:16:00", "09:17:00", "09:18:00", "09:19:00"]
    with pytest.raises(ValueError, match="non-positive"):
        kb.validate(kb.to_frame("COFO", [dict(_bars(day)[0], close=0, volume=50)]))   # a zero WITH volume is not a placeholder


@pytest.mark.parametrize("break_it, expect", [
    (lambda d: pd.concat([d, d.iloc[[0]]]), "duplicate"),
    (lambda d: d.assign(close=d["close"].where(d.index != 1, 0)), "non-positive"),
    (lambda d: d.assign(volume=d["volume"].where(d.index != 1, -5)), "negative volume"),
    (lambda d: d.assign(ts=d["ts"] - pd.Timedelta(hours=6)), "outside"),
])
def test_contract_rejects_a_bad_bar(break_it, expect):
    good = kb.to_frame("RELI", _bars(date(2026, 10, 9)))
    kb.validate(good)
    with pytest.raises(ValueError, match=expect):
        kb.validate(break_it(good))


def test_a_muhurat_evening_session_is_allowed():
    kb.validate(kb.to_frame("RELI", _bars(date(2025, 10, 21), start=(18, 0))))


class FakeKite:
    """Bars on the given days only; records every request window."""
    def __init__(self, days):
        self.days, self.calls = set(days), []

    def historical_data(self, token, frm, to, interval):
        lo, hi = date.fromisoformat(frm[:10]), date.fromisoformat(to[:10])
        self.calls.append((lo, hi))
        assert (hi - lo).days < kb.CHUNK_DAYS and interval == "minute"
        return [b for d in sorted(self.days) if lo <= d <= hi for b in _bars(d)]


def test_fetch_walks_back_in_60_day_chunks_and_stops_before_listing():
    end = date(2026, 10, 9)
    listed = [end - timedelta(days=k) for k in range(0, 200, 7)]          # ~6.5 months of history
    kite = FakeKite(listed)
    df = kb.fetch_stock(kite, "NEW", 1, end=end)
    assert len(df) == 3 * len(listed)
    assert len(kite.calls) == 4 + kb.EMPTY_STOP                          # 4 chunks with bars, then 2 empty
    assert all(a[0] == b[1] + timedelta(days=1) for a, b in zip(kite.calls, kite.calls[1:]))   # no gaps


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    stmt = re.search(r"CREATE TABLE IF NOT EXISTS intraday_files \(.*?\n\);", db.SCHEMA_PATH.read_text(), re.S).group(0)
    with sqlite3.connect(path) as c:
        c.execute(stmt)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def test_file_round_trips_and_the_manifest_records_it(tmp_path, manifest):
    df = kb.to_frame("RELI", _bars(date(2026, 10, 8)) + _bars(date(2026, 10, 9)))
    path = tmp_path / "bars_1m" / "_staging" / "sid=RELI.parquet"
    kb.record("staging", "RELI", df, path, kb.write_parquet(df, path))
    back = pq.read_table(path).to_pandas().astype({"sid": str})       # sid is dictionary-encoded on disk
    pd.testing.assert_frame_equal(back, df, check_dtype=False)
    assert str(back["ts"].dt.tz) == "UTC" and not path.with_name(path.name + ".tmp").exists()
    row = db.read_sql("SELECT * FROM intraday_files").iloc[0]
    assert (row["key"], row["n_rows"], row["n_days"]) == ("RELI", 6, 2)
    assert row["fetched_on"] == date.today().isoformat()
    assert kb.done_sids() == {"RELI"}
