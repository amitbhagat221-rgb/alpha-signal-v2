"""The macro desk waits out the morning sync's write lock instead of losing the day (2026-11-04 to 11-07:
`desk_snapshots` stopped updating because every 05:45 run met the datamodel sync)."""
import sqlite3

import pytest

from output import macro_desk


def _raise(msg):
    def fn(*a, **kw):
        raise sqlite3.OperationalError(msg)
    return fn


def test_a_locked_write_is_retried_until_the_lock_frees(monkeypatch):
    calls = []

    def run(*a):
        calls.append(a)
        if len(calls) < 3:
            raise sqlite3.OperationalError("database is locked")
        return "saved"
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert macro_desk._wait_out_lock(run, "2026-11-07", "live", wait_s=600) == "saved" and len(calls) == 3


def test_it_gives_up_after_the_wait(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        macro_desk._wait_out_lock(_raise("database is locked"), wait_s=0)


def test_other_database_errors_are_not_retried(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        macro_desk._wait_out_lock(_raise("no such table: x"), wait_s=600)
