"""sources/hf_options_1m — the HF index-option minute-bar ingest: schema gate, normaliser,
fno_bhav check, files + manifest, and the hash-checked download. Offline, tiny fixture frames."""
import hashlib
import re
import sqlite3
from datetime import date

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import db
from sources import hf_options_1m as h


def _raw(rows, symbol="NIFTY", expiry="2022-06-23"):
    """rows: (IST 'YYYY-MM-DD HH:MM', strike, CE/PE, o, hi, lo, c, volume_units)."""
    df = pd.DataFrame(rows, columns=["t", "strike", "option_type", "open", "high", "low", "close", "volume"])
    ts = pd.to_datetime(df.pop("t")).dt.tz_localize("+05:30")
    return pd.DataFrame({
        "timestamp": ts, "open": df["open"].astype(float), "high": df["high"].astype(float),
        "low": df["low"].astype(float), "close": df["close"].astype(float), "volume": df["volume"].astype("int64"),
        "open_interest": 0, "trading_day": ts.dt.strftime("%Y-%m-%d"), "symbol": symbol,
        "strike": df["strike"].astype("int32"), "option_type": df["option_type"], "expiry": expiry,
    })


BARS = [("2022-06-22 15:00", 15700, "CE", 10, 11, 9, 10, 500),
        ("2022-06-22 15:01", 15700, "CE", 10, 12, 10, 12, 1000),
        ("2022-06-22 15:01", 15700, "PE", 5, 5, 5, 5, 150)]


# ─────────────────────────── normaliser ───────────────────────────

def test_doubled_rows_are_dropped_and_volume_becomes_contracts():
    raw = _raw(BARS + BARS)                                    # 2021-2023 files store every row twice
    df, st = h.normalise_options(raw, "NIFTY", "2022-06-23")
    assert len(df) == 3 and st["dup_rows"] == 3
    assert df["volume_contracts"].tolist() == [10.0, 20.0, 3.0]     # NIFTY lot 50 in 2022
    assert list(df.columns) == h.OPT_SCHEMA.names and "open_interest" not in df
    assert st["lots"] == [50] and st["offlot_bars"] == 0


def test_lot_follows_the_trade_day_and_an_override_wins():
    raw = _raw([("2025-07-01 10:00", 25000, "CE", 50, 50, 50, 50, 750)], expiry="2025-07-03")
    assert h.normalise_options(raw, "NIFTY", "2025-07-03")[0]["volume_contracts"].iloc[0] == 10   # lot 75
    df, st = h.normalise_options(raw, "NIFTY", "2025-07-03", lots={date(2025, 7, 1): 25})
    assert df["volume_contracts"].iloc[0] == 30 and st["lots"] == [25]


def test_timestamps_stay_ist_and_the_trading_day_is_the_ist_date():
    df, _ = h.normalise_options(_raw(BARS), "NIFTY", "2022-06-23")
    assert str(df["ts"].dt.tz) == h.IST
    assert df["ts"].iloc[0].strftime("%Y-%m-%d %H:%M") == "2022-06-22 15:00"
    assert (df["trading_day"] == date(2022, 6, 22)).all() and (df["expiry"] == date(2022, 6, 23)).all()


def test_post_close_snapshot_bars_go_and_stray_trades_are_counted_up_to_a_limit(monkeypatch):
    late = ("2022-06-22 15:44", 15700, "CE", 12, 12, 12, 12, 0)     # 2025+ files: zero-volume LTP snapshots
    df, st = h.normalise_options(_raw(BARS + [late]), "NIFTY", "2022-06-23")
    assert len(df) == 3 and (st["late_rows"], st["stray_rows"]) == (1, 0)
    stray = [("2022-06-22 15:31", 15700, "PE", 5, 5, 5, 5, 50), ("2022-06-22 09:14", 15700, "PE", 5, 5, 5, 5, 50)]
    with pytest.raises(ValueError, match="traded bars outside"):     # 2 of 5 rows: a stamping bug, not strays
        h.normalise_options(_raw(BARS + stray), "NIFTY", "2022-06-23")
    monkeypatch.setattr(h, "STRAY_MAX", 0.5)
    df, st = h.normalise_options(_raw(BARS + stray), "NIFTY", "2022-06-23")
    assert len(df) == 3 and st["stray_rows"] == 2


def test_all_zero_placeholder_bars_are_dropped():
    zero = ("2022-06-18 12:30", 15700, "CE", 0, 0, 0, 0, 0)          # 2024-05-18 Saturday session style
    df, st = h.normalise_options(_raw(BARS + [zero]), "NIFTY", "2022-06-23")
    assert len(df) == 3 and st["zero_rows"] == 1


def test_a_muhurat_evening_session_is_kept_only_on_its_own_day():
    muhurat = [("2022-10-24 18:15", 17700, "CE", 20, 21, 19, 20, 100), ("2022-10-24 19:14", 17700, "CE", 20, 20, 20, 20, 50)]
    df, st = h.normalise_options(_raw(BARS + muhurat, expiry="2022-10-27"), "NIFTY", "2022-10-27")
    assert len(df) == 5 and st["muhurat_days"] == 1 and st["late_rows"] == 0
    with pytest.raises(ValueError, match="outside"):                 # an evening bar on a regular day still fails
        h.normalise_options(_raw(BARS + [("2022-06-22 18:15", 15700, "CE", 10, 10, 10, 10, 50)]), "NIFTY", "2022-06-23")


@pytest.mark.parametrize("bad, match", [
    ([("2022-06-22 15:00", 15700, "CE", 10, 11, 9, 11, 500)], "conflicting duplicate"),   # same minute, other price
    ([("2022-06-22 09:10", 15700, "CE", 10, 11, 9, 10, 500)], "traded bars outside 09:15-15:30"),
    ([("2022-06-22 10:00", 15700, "CE", 0, 0, 0, 0, 50)], "non-positive prices"),
    ([("2022-06-22 10:00", 15700, "CE", 10, 9, 8, 10, 50)], "high/low"),
    ([("2022-06-22 10:00", 15700, "XX", 10, 10, 10, 10, 50)], "CE/PE"),
    ([("2022-06-24 10:00", 15700, "CE", 10, 10, 10, 10, 50)], "after expiry"),
])
def test_the_contract_rejects_a_bad_bar(bad, match):
    with pytest.raises(ValueError, match=match):
        h.normalise_options(_raw(BARS + bad), "NIFTY", "2022-06-23")


def test_a_file_of_another_symbol_or_expiry_is_rejected():
    with pytest.raises(ValueError, match="symbol"):
        h.normalise_options(_raw(BARS, symbol="BANKNIFTY"), "NIFTY", "2022-06-23")
    with pytest.raises(ValueError, match="expiry column"):
        h.normalise_options(_raw(BARS, expiry="2022-06-30"), "NIFTY", "2022-06-23")


def test_index_keeps_the_pre_open_bar_and_drops_volume():
    raw = _raw([("2022-06-22 09:07", 0, "CE", 15000, 15000, 15000, 15000, 0),
                ("2022-06-22 09:15", 0, "CE", 15001, 15010, 14990, 15005, 0),
                ("2022-06-22 15:35", 0, "CE", 15005, 15005, 15005, 15005, 0)])
    raw = raw.drop(columns=["open_interest", "strike", "option_type", "expiry"])
    df, st = h.normalise_index(raw, "NIFTY")
    assert len(df) == 2 and st["late_rows"] == 1 and list(df.columns) == h.IDX_SCHEMA.names


# ─────────────────────────── schema gate (untrusted file) ───────────────────────────

def _write(tmp_path, df):
    path = tmp_path / "src.parquet"
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), path)
    return path


@pytest.mark.parametrize("mutate, match", [
    (lambda d: d.drop(columns=["strike"]), "missing strike"),
    (lambda d: d.assign(close=d["close"].astype(str)), "close is string"),
    (lambda d: d.assign(timestamp=d["timestamp"].dt.tz_localize(None)), "timestamp is timestamp"),
    (lambda d: d.assign(timestamp=d["timestamp"].dt.tz_convert("UTC")), "timestamp is timestamp"),
    (lambda d: d.assign(volume=d["volume"].astype(float)), "volume is double"),
])
def test_schema_gate_rejects_a_bad_file_before_reading_rows(tmp_path, mutate, match):
    good = _raw(BARS)
    assert len(h.read_source(_write(tmp_path, good), "options")) == 3
    with pytest.raises(ValueError, match=match):
        h.read_source(_write(tmp_path, mutate(good)), "options")


def test_schema_gate_rejects_an_oversized_file(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "MAX_SRC_ROWS", 2)
    with pytest.raises(ValueError, match="rows >"):
        h.read_source(_write(tmp_path, _raw(BARS)), "options")


# ─────────────────────────── check vs fno_bhav ───────────────────────────

def _bhav(rows):
    return pd.DataFrame(rows, columns=["trade_date", "strike", "option_type", "close", "volume"])


def test_vwap_check_matches_the_15_00_window_vwap():
    df, _ = h.normalise_options(_raw(BARS), "NIFTY", "2022-06-23")
    vwap_ce = ((11 + 9 + 10) / 3 * 10 + (12 + 10 + 12) / 3 * 20) / 30
    good = h.vwap_check(df, _bhav([("2022-06-22", 15700.0, "CE", vwap_ce, 30), ("2022-06-22", 15700.0, "PE", 5.0, 3)]),
                        "NIFTY", "2022-06-23")
    assert (good["n"], good["match"], good["vol_ratio"], good["days"]) == (2, 1.0, 1.0, 1)
    bad = h.vwap_check(df, _bhav([("2022-06-22", 15700.0, "CE", vwap_ce * 1.05, 30)]), "NIFTY", "2022-06-23")
    assert bad["match"] == 0.0
    cheap = h.vwap_check(df, _bhav([("2022-06-22", 15700.0, "PE", 5.10, 3)]), "NIFTY", "2022-06-23")
    assert cheap["match"] == 1.0                                    # within ₹0.10 though 2 % off


def test_sensex_expiry_day_is_not_checked():
    raw = _raw([("2025-06-10 15:05", 81000, "CE", 10, 10, 10, 10, 200)], symbol="SENSEX", expiry="2025-06-10")
    df, _ = h.normalise_options(raw, "SENSEX", "2025-06-10")
    chk = h.vwap_check(df, _bhav([("2025-06-10", 81000.0, "CE", 99.0, 10)]), "SENSEX", "2025-06-10")
    assert chk["n"] == 0 and chk["days"] == 0


def test_fno_bhav_contract_counts_override_a_wrong_lot():
    raw = _raw([("2024-12-20 15:05", 24000, "CE", 10, 10, 10, 10, 750)], expiry="2024-12-26")
    df, _ = h.normalise_options(raw, "NIFTY", "2024-12-26")         # table says lot 25 → 30 contracts
    lots = h.infer_lots(df, _bhav([("2024-12-20", 24000.0, "CE", 10.0, 10)]), "NIFTY", "2024-12-26")
    assert lots == {date(2024, 12, 20): 75}
    assert h.infer_lots(df, _bhav([("2024-12-20", 24000.0, "CE", 10.0, 30)]), "NIFTY", "2024-12-26") == {}


# ─────────────────────────── files + manifest ───────────────────────────

@pytest.fixture
def manifest(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    stmt = re.search(r"CREATE TABLE IF NOT EXISTS intraday_files \(.*?\n\);", db.SCHEMA_PATH.read_text(), re.S).group(0)
    with sqlite3.connect(path) as c:
        c.execute(stmt)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def test_file_round_trips_and_an_unchanged_source_is_skipped(tmp_path, manifest, monkeypatch):
    df, _ = h.normalise_options(_raw(BARS), "NIFTY", "2022-06-23")
    path = tmp_path / "options_1m" / "NIFTY" / "2022-06-23.parquet"
    h.record("expiry", "NIFTY/2022-06-23", df, path, h.write_parquet(df, path, h.OPT_SCHEMA),
             "status=ok; vwap_match=1.000; src_sha256=abc")
    back = pd.read_parquet(path)
    assert str(back["ts"].dt.tz) == h.IST
    assert back["volume_contracts"].tolist() == df["volume_contracts"].tolist()
    row = db.read_sql("SELECT * FROM intraday_files").iloc[0]
    assert (row["dataset"], row["kind"], row["n_rows"], row["n_days"]) == ("options_1m", "expiry", 3, 1)
    have = h.manifest()
    assert h._done(have, "expiry", "NIFTY/2022-06-23", {"sha256": "abc"})
    assert not h._done(have, "expiry", "NIFTY/2022-06-23", {"sha256": "changed"})
    called = []
    monkeypatch.setattr(h, "download", lambda *a: called.append(a))
    entry = {"path": "options/NIFTY/2022-06-23.parquet", "size": 1, "sha256": "abc"}
    assert h.ingest_expiry(entry, "NIFTY", have) is None and not called    # no download at all


# ─────────────────────────── download (through the door) ───────────────────────────

class _Resp:
    def __init__(self, body):
        self.body = body

    def iter_content(self, n):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]


def test_download_checks_the_hash_and_falls_back_to_the_mirror(tmp_path, monkeypatch):
    body = b"PAR1-not-really-parquet"
    entry = {"path": "options/NIFTY/x.parquet", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    urls = []

    def fake_get(url, **kw):
        urls.append(url)
        return _Resp(b"tampered-bytes-of-same-" if h.REPOS[0] in url else body)

    monkeypatch.setattr(h._http, "polite_get", fake_get)
    repo, sha = h.download(entry, tmp_path / "x.parquet")
    assert repo == h.REPOS[1] and sha == entry["sha256"] and (tmp_path / "x.parquet").read_bytes() == body
    assert all(u.startswith("https://huggingface.co/datasets/") for u in urls)
    assert len(urls) == h.RETRIES + 1                               # primary retried, then the mirror

    monkeypatch.setattr(h._http, "polite_get", lambda url, **kw: _Resp(b"x" * (len(body) + 5)))
    with pytest.raises(ValueError):
        h.download(entry, tmp_path / "y.parquet")
    assert not (tmp_path / "y.parquet").exists()                    # nothing untrusted left behind
