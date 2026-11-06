"""A step record waits out a locked database instead of vanishing (2026-11-01: the record of a skipped Screener
harvest failed with "database is locked", and the stale table went unnoticed for 22 days)."""
import json
import sqlite3

import pytest

import pipeline


def test_a_locked_database_is_retried_until_it_frees(monkeypatch):
    calls = []

    def log(*a, **kw):
        calls.append(1)
        if len(calls) < 3:
            raise sqlite3.OperationalError("database is locked")
    import steplog
    monkeypatch.setattr(steplog, "log", log)
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    pipeline.log_step("cron_x", "FAILED", error="skipped", wait_s=60)
    assert len(calls) == 3


def test_a_lock_that_never_frees_leaves_a_file_line_and_a_push(monkeypatch, tmp_path):
    import steplog
    from tools import health_report
    monkeypatch.setattr(steplog, "log", lambda *a, **kw: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")))
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    monkeypatch.setattr(pipeline, "UNLOGGED", tmp_path / "unlogged.jsonl")
    pushed = []
    monkeypatch.setattr(health_report, "send_ntfy", lambda text, **kw: pushed.append(text))
    with pytest.raises(sqlite3.OperationalError):
        pipeline.log_step("cron_screener_universe", "FAILED", error="skipped: harvest lock held", wait_s=0)
    rec = json.loads((tmp_path / "unlogged.jsonl").read_text().splitlines()[0])
    assert rec["step"] == "cron_screener_universe" and rec["status"] == "FAILED" and "locked" in rec["why_unlogged"]
    assert pushed and "could not be logged" in pushed[0]


def test_other_database_errors_are_not_retried(monkeypatch):
    import steplog
    monkeypatch.setattr(steplog, "log", lambda *a, **kw: (_ for _ in ()).throw(sqlite3.OperationalError("no such table: x")))
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        pipeline.log_step("cron_x", "SUCCESS", wait_s=60)
