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
