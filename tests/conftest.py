"""Shared test fixtures.

The run log (runlog.py) writes events from shared hooks (_http, run_harvester,
db writes, pipeline.run_step). Tests exercise those paths, so every test gets a
throwaway run-log DB — the live DB must never receive test events.
"""
import sqlite3

import pytest

import runlog
from db import SCHEMA_PATH


@pytest.fixture(autouse=True)
def _isolated_runlog(tmp_path, monkeypatch):
    path = tmp_path / "runlog.db"
    s = SCHEMA_PATH.read_text()
    i = s.index("CREATE TABLE IF NOT EXISTS run_events")
    j = s.index("CREATE INDEX IF NOT EXISTS idx_run_events_level")
    conn = sqlite3.connect(path)
    conn.executescript(s[i:j])
    conn.close()
    monkeypatch.setattr(runlog, "DB_PATH", path)
    monkeypatch.setattr(runlog, "_counts", None)
    saved = dict(runlog._ctx)
    runlog._ctx.clear()
    yield path
    runlog._ctx.clear()
    runlog._ctx.update(saved)


@pytest.fixture(autouse=True)
def _writable_after_alpha_mcp():
    """alpha_mcp.research / ops call _core.install_readonly() at import, which swaps get_db in every
    loaded module (options_live included) for a read-only connection. The MCP servers are their own
    processes; in the suite one `from alpha_mcp import research` would otherwise leave every later
    test's db.get_db read-only (test_views → test_check_drills OPTIONS_LIVE drill, 2026-10-31)."""
    yield
    from alpha_mcp import _core
    _core.uninstall_readonly()
