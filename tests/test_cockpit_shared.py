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


def test_db_rows_one_scalar(tmp_path, monkeypatch):
    import sqlite3
    import db
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE t (sid TEXT, x REAL, n INTEGER)")
    c.executemany("INSERT INTO t VALUES (?,?,?)",
                  [("A", 1.5, 1), ("B", None, 2), ("C", float("inf"), None)])
    c.commit()
    c.close()
    monkeypatch.setattr(db, "DB_PATH", p)

    rs = db.rows("SELECT * FROM t ORDER BY sid")
    assert rs[0] == {"sid": "A", "x": 1.5, "n": 1.0}
    assert rs[1]["x"] is None and rs[2]["x"] is None and rs[2]["n"] is None
    assert db.rows("SELECT * FROM t WHERE sid = ?", ["Z"]) == []
    assert db.one("SELECT sid, n FROM t WHERE sid = ?", ["B"]) == {"sid": "B", "n": 2}
    assert db.one("SELECT * FROM t WHERE sid = 'Z'") == {}
    assert db.scalar("SELECT MAX(n) FROM t") == 2
    assert db.scalar("SELECT n FROM t WHERE sid = 'C'", default=0) == 0
    assert db.scalar("SELECT n FROM t WHERE sid = 'Z'", default="x") == "x"


# ── shell guards (frontend phase 1) ──────────────────────────────────────────
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATES = [*(_ROOT / "cockpit" / "templates").glob("*.html"), *(_ROOT / "cockpit_ops" / "templates").glob("*.html")]


def test_no_template_loads_tailwind_cdn():
    bad = [t.name for t in _TEMPLATES if "tailwindcss" in t.read_text()]
    assert not bad, f"Tailwind CDN back in {bad}: the reset lives in cockpit.css"


def test_every_script_src_is_local():
    """All <script src> point at /static or a vendor() call: nothing loads from a CDN."""
    bad = []
    for t in _TEMPLATES:
        for src in re.findall(r"<script[^>]*\ssrc=[\"']([^\"']+)", t.read_text()):
            if not (src.startswith("/static/") or src.startswith("{{ vendor(")):
                bad.append((t.name, src))
    assert not bad, bad
    # and no script URL is assembled from a CDN host in JS either
    assert not [t.name for t in _TEMPLATES if re.search(r"cdn\.jsdelivr|unpkg\.com|cdnjs", t.read_text())]


def test_vendored_files_exist():
    for name, f in shared.VENDOR.items():
        assert (shared.COCKPIT_STATIC / f).is_file(), name
        assert shared.vendor(name).startswith("/static/vendor/")


def test_inr_groups_thousands_by_default():
    from formatting import inr
    assert inr(43155) == "₹43,155"
    assert inr(43155, group=False) == "₹43155"
