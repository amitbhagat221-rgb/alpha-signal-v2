"""Offline tests for sources/_http.py (no network, no DB writes)."""
import time

import pandas as pd
import pytest
import requests

from sources import _http


def _resp(status, headers=None):
    r = requests.Response()
    r.status_code = status
    r.headers.update(headers or {})
    r._content = b"ok"
    r.url = "https://example.test/x"
    return r


class FakeSession:
    """Returns queued responses / raises queued exceptions, records call times."""
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(time.monotonic())
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    monkeypatch.setattr(_http, "_LAST_CALL", {})
    monkeypatch.setattr(_http, "_SID_MAPS", {})
    monkeypatch.setattr(_http, "_backoff", lambda resp, gap, attempt: 0.0)


def test_polite_get_paces_same_host():
    s = FakeSession(_resp(200), _resp(200))
    _http.polite_get("https://a.test/1", session=s, min_gap=0.3)
    _http.polite_get("https://a.test/2", session=s, min_gap=0.3)
    assert s.calls[1] - s.calls[0] >= 0.29


def test_polite_get_does_not_pace_other_hosts():
    s = FakeSession(_resp(200), _resp(200))
    _http.polite_get("https://a.test/1", session=s, min_gap=5)
    _http.polite_get("https://b.test/1", session=s, min_gap=5)
    assert s.calls[1] - s.calls[0] < 1


def test_polite_get_404_returns_none():
    assert _http.polite_get("https://a.test/", session=FakeSession(_resp(404)), min_gap=0) is None


def test_polite_get_retries_429_then_succeeds():
    s = FakeSession(_resp(429), _resp(503), _resp(200))
    r = _http.polite_get("https://a.test/", session=s, min_gap=0, retries=2)
    assert r.status_code == 200 and len(s.calls) == 3


def test_polite_get_403_raises_without_retry():
    s = FakeSession(_resp(403), _resp(200))
    with pytest.raises(requests.HTTPError):
        _http.polite_get("https://a.test/", session=s, min_gap=0, retries=2)
    assert len(s.calls) == 1


def test_polite_get_raises_after_retries_exhausted():
    s = FakeSession(requests.Timeout("t1"), requests.ConnectionError("c"), requests.Timeout("t2"))
    with pytest.raises(requests.Timeout):
        _http.polite_get("https://a.test/", session=s, min_gap=0, retries=2)
    assert len(s.calls) == 3


def test_host_gap_from_config():
    from config import API
    assert API["min_gap"] >= 2.0
    assert all(g >= API["min_gap"] for g in API["host_min_gap"].values())


def test_sid_map_is_cached(monkeypatch):
    calls = []

    def fake_read_sql(q, params=None):
        calls.append(q)
        return pd.DataFrame({"sid": ["RELI", "TCS"], "k": ["RELIANCE", "TCS"]})

    monkeypatch.setattr(_http, "read_sql", fake_read_sql)
    assert _http.sid_map()["RELIANCE"] == "RELI"
    _http.sid_map()
    assert len(calls) == 1


def test_run_harvester_flushes_and_counts():
    written = []

    def fetch(i):
        if i == 2:
            raise ValueError("boom")
        return [] if i == 3 else [{"i": i}]

    ok, err, n = _http.run_harvester(range(5), fetch, lambda rows: written.append(list(rows)),
                                     flush_every=2, label="t")
    assert (ok, err, n) == (3, 1, 3)
    assert [len(b) for b in written] == [2, 1]


def test_run_harvester_raises_when_nothing_returned():
    def fetch(i):
        raise requests.ConnectionError("down")

    with pytest.raises(RuntimeError, match="0 of 3 items"):
        _http.run_harvester([1, 2, 3], fetch, lambda rows: None, label="t")


def test_run_harvester_empty_items_is_quiet():
    assert _http.run_harvester([], lambda i: [1], lambda rows: None, label="t") == (0, 0, 0)


def test_every_sources_module_imports():
    """Not just PIPELINE_STEPS modules — cron/manual harvesters (bse_announcements,
    transcripts_pull, screener_pull …) must import too."""
    import importlib
    import pathlib
    failed = []
    for f in sorted(pathlib.Path(_http.__file__).parent.glob("*.py")):
        try:
            importlib.import_module(f"sources.{f.stem}")
        except Exception as e:
            failed.append(f"{f.stem}: {type(e).__name__}: {e}")
    assert not failed, "\n".join(failed)
