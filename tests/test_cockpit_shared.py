"""Unit tests for cockpit/_shared.py helpers (no DB, no server)."""
import threading
import time

import cockpit._shared as shared


def _fresh_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "_PERSISTED_CACHE_DIR", tmp_path)


def test_persisted_cache_cold_computes_inline_once(tmp_path, monkeypatch):
    _fresh_cache_dir(tmp_path, monkeypatch)
    calls = []

    @shared._persisted_cache(60, name="t_cold")
    def f():
        calls.append(1)
        time.sleep(0.2)
        return len(calls)

    results = []
    ts = [threading.Thread(target=lambda: results.append(f())) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert results == [1, 1, 1]      # concurrent cold callers share one compute
    assert len(calls) == 1
    assert (tmp_path / "t_cold.pkl").exists()


def test_persisted_cache_serves_stale_and_refreshes_in_background(tmp_path, monkeypatch):
    _fresh_cache_dir(tmp_path, monkeypatch)
    state = {"n": 0}
    release = threading.Event()

    @shared._persisted_cache(0.05, name="t_swr")
    def f():
        state["n"] += 1
        if state["n"] > 1:
            release.wait(2)          # slow refresh
        return state["n"]

    assert f() == 1
    time.sleep(0.1)                  # past the TTL
    t0 = time.time()
    assert f() == 1                  # stale value, immediately
    assert f() == 1                  # refresh still running: no second thread
    assert time.time() - t0 < 0.5
    release.set()
    for _ in range(50):
        if f() == 2:
            break
        time.sleep(0.02)
    assert f() == 2
    assert state["n"] == 2


def test_persisted_cache_force_and_disk_reload(tmp_path, monkeypatch):
    _fresh_cache_dir(tmp_path, monkeypatch)
    state = {"n": 0}

    def make():
        @shared._persisted_cache(60, name="t_disk")
        def f(x=1):
            state["n"] += 1
            return state["n"] * x
        return f

    f = make()
    assert f(x=2) == 2
    assert f(x=2, _force=True) == 4
    g = make()                       # "restart": empty memo, pickle on disk
    assert g(x=2) == 4
    assert state["n"] == 2


def test_persisted_cache_max_entries_bounds_memo(tmp_path, monkeypatch):
    _fresh_cache_dir(tmp_path, monkeypatch)

    @shared._persisted_cache(60, name="t_bound", max_entries=3)
    def f(i):
        return i

    for i in range(10):
        assert f(i) == i
    assert f(9) == 9
