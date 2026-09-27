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


def test_polite_get_uses_host_gap_and_headers(monkeypatch):
    """No min_gap/headers passed → the declared host's gap and headers apply;
    two netlocs of one host share a single gap."""
    from hosts import HOSTS
    sent = []

    def fake_get(url, headers=None, params=None, timeout=None):
        sent.append((time.monotonic(), headers))
        return _resp(200)

    monkeypatch.setattr(_http.requests, "get", fake_get)
    monkeypatch.setitem(HOSTS, "t_host", {"netlocs": ["a.t.test", "b.t.test"], "gap": 0.3,
                                          "headers": {"User-Agent": "T"}})
    monkeypatch.setattr(_http, "_NETLOC_HOST", {**_http._NETLOC_HOST,
                                                "a.t.test": "t_host", "b.t.test": "t_host"})
    _http.polite_get("https://a.t.test/1")
    _http.polite_get("https://b.t.test/2")
    assert sent[1][0] - sent[0][0] >= 0.29
    assert sent[0][1] == {"User-Agent": "T"}


def test_polite_request_check_false_returns_raw_response():
    s = FakeSession(_resp(302, {"location": "/login/"}))
    r = _http.polite_request("GET", "https://a.test/", session=s, min_gap=0, check=False)
    assert r.status_code == 302 and len(s.calls) == 1


def test_polite_request_check_false_still_retries_transport_errors():
    s = FakeSession(requests.ConnectionError("c"), _resp(500))
    r = _http.polite_request("GET", "https://a.test/", session=s, min_gap=0, check=False, retries=1)
    assert r.status_code == 500 and len(s.calls) == 2


@pytest.fixture
def vclock(monkeypatch):
    """Virtual monotonic clock: sleep() advances it instantly."""
    now = [1000.0]
    monkeypatch.setattr(_http.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(_http.time, "sleep", lambda s: now.__setitem__(0, now[0] + max(s, 0)))
    return now


def test_pace_spaces_library_calls(vclock):
    stamps = []
    for _ in range(2):
        with _http.pace("t_pace_host.test"):
            stamps.append(time.monotonic())
    assert stamps[1] - stamps[0] == 2.0   # undeclared → DEFAULT gap


def test_pace_stamps_end_even_when_the_call_raises():
    with pytest.raises(ValueError):
        with _http.pace("https://x.test/"):
            raise ValueError("boom")
    assert "x.test" in _http._LAST_CALL


def test_host_resolution():
    assert _http.host("https://api.bseindia.com/x?y=1")[0] == "bse_api"
    assert _http.host("www.screener.in")[0] == "screener"            # bare netloc
    key, entry = _http.host("https://unknown.example/")
    assert key == "unknown.example" and entry["gap"] == 2.0
    with pytest.raises(KeyError):
        _http.host("yahooo")                                          # typo'd host name


def test_time_budget(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(_http.time, "monotonic", lambda: now[0])
    over = _http.time_budget("moneycontrol")          # host default: 90 min
    now[0] += 89 * 60
    assert not over()
    now[0] += 2 * 60
    assert over()
    assert not _http.time_budget("moneycontrol", None)()   # None = no budget


def test_run_harvester_paces_per_host(vclock):
    stamps = []
    _http.run_harvester(range(3), lambda i: stamps.append(time.monotonic()) or [i],
                        lambda rows: None, label="t", host="t_harvest_host.test")
    assert [b - a for a, b in zip(stamps, stamps[1:])] == [2.0, 2.0]


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
