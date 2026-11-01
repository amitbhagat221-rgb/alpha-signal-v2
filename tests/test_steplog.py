"""Plan 0030 stage 1 part 3: the step log. steplog.log writes the legacy pipeline_log row and one
step_runs attempt (RUNNING opens it, the terminal status closes it in place, carrying the legacy id);
the readers answer the same under both flags; the sync's mirror and the parity check see nothing new."""
import sqlite3
from datetime import date, timedelta

import pytest

import config
import db
import steplog
import views

TODAY = date.today().isoformat()
YDAY = (date.today() - timedelta(days=1)).isoformat()


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "s.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(config, "DB_PATH", path)
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA_PATH.read_text())
    c.commit()
    yield c
    c.close()


def _rows(c, sql):
    return c.execute(sql).fetchall()


def test_running_then_terminal_is_one_attempt_carrying_the_terminal_log_id(conn):
    steplog.log("screener", "RUNNING", started=f"{TODAY}T03:35:00", conn=conn)
    steplog.log("screener", "SUCCESS", rows=1803, started=f"{TODAY}T03:35:00", conn=conn)
    steplog.log("cron_canary", "FAILED", started=f"{TODAY}T02:45:00", error="boom", conn=conn)     # run.sh `logged`: no RUNNING row
    steplog.log("watchdog_stock_prices_heal", "SUCCESS", started=f"{TODAY}T15:00:00", conn=conn)
    assert _rows(conn, "SELECT COUNT(*) FROM pipeline_log") == [(4,)]
    sr = _rows(conn, "SELECT r.kind, r.official, s.step, s.attempt, s.status, s.rows, s.error, json_extract(s.attrs, '$.log_id'), "
                     "json_extract(s.attrs, '$.from') FROM step_runs s JOIN runs r USING (run_id) ORDER BY s.rowid")
    assert sr == [("morning", 1, "screener", 1, "SUCCESS", 1803, None, 2, "pipeline_log"),
                  ("morning", 1, "cron_canary", 1, "FAILED", None, "boom", 3, "pipeline_log"),
                  ("watchdog", 0, "watchdog_stock_prices_heal", 1, "SUCCESS", None, None, 4, "pipeline_log")]
    # a second attempt the same day is attempt 2
    steplog.log("screener", "RUNNING", started=f"{TODAY}T09:00:00", conn=conn)
    assert _rows(conn, "SELECT attempt, status FROM step_runs WHERE step='screener' ORDER BY attempt") == [(1, "SUCCESS"), (2, "RUNNING")]


def test_readers_agree_under_both_flags_and_the_mirror_adds_nothing(conn, tmp_path, monkeypatch):
    from checks import system
    for d, step, status, started, err in [(YDAY, "a", "RUNNING", f"{YDAY}T03:00:00", None), (YDAY, "a", "SUCCESS", f"{YDAY}T03:00:00", None),
                                          (YDAY, "b", "FAILED", f"{YDAY}T03:10:00", "boom"), (TODAY, "b", "FAILED", f"{TODAY}T03:10:00", "boom"),
                                          (TODAY, "c", "RUNNING", "2020-01-01T03:00:00", None), (TODAY, "d", "RUNNING", f"{TODAY}T09:00:00", None)]:
        steplog.log(step, status, started=started, error=err, run_date=d, conn=conn)
    conn.commit()
    out = {}

    def settled(rows):
        """A legacy RUNNING row carries the log time as finished_at and a duration (a quirk); the open
        step_runs attempt leaves both NULL until it closes. Everything else must agree."""
        return sorted(({k: v for k, v in r.items() if r["status"] not in ("RUNNING", "ABORTED") or k not in ("finished_at", "duration_sec")}
                       for r in rows), key=lambda r: (r["step_name"], r["run_date"]))
    for flag in ("old", "new"):
        monkeypatch.setitem(config.DATA_MODEL, "steps", flag)
        out[flag] = (settled(views.pipeline_status(7)), system.pipeline_facts(1), system.watchdog_facts(),
                     settled(views.step_status().values()))
    assert out["old"] == out["new"]
    assert {r["step_name"]: r["status"] for r in out["new"][0]} == {"a": "SUCCESS", "b": "FAILED", "c": "ABORTED", "d": "RUNNING"}
    assert [s["step"] for s in out["new"][1]["failed_streaks"]] == ["b"]
    # the sync's mirror watermarks on the legacy id the writer stored: nothing to add, parity holds
    from datamodel import reconcile, sync
    monkeypatch.setattr(sync, "DB_PATH", db.DB_PATH)
    monkeypatch.setattr(sync, "MF_DB", tmp_path / "mf.db")
    monkeypatch.setattr(sync, "sync_contributions", lambda c, full: 0)
    before = _rows(conn, "SELECT COUNT(*) FROM step_runs")
    assert sync.main([]) == 0
    assert _rows(conn, "SELECT COUNT(*) FROM step_runs") == before
    (pl,) = [r for r in reconcile.run(write=False) if r[0] == "pipeline_log"]
    assert pl[1] == "PASS" and pl[2] == pl[3] == 5                      # 4 terminal rows + 1 orphan = 5 attempts


def test_log_step_and_the_watchdog_write_through_steplog(conn, monkeypatch):
    import pipeline
    from tools import freshness_watchdog as fw
    pipeline.log_step("x", "RUNNING", started=f"{TODAY}T01:00:00")
    pipeline.log_step("x", "SUCCESS", rows=3, started=f"{TODAY}T01:00:00")
    fw._log_watchdog("stocks", "heal", "FAILED", error="no source")
    assert _rows(conn, "SELECT step, status, rows FROM step_runs ORDER BY rowid") == [("x", "SUCCESS", 3), ("watchdog_stocks_heal", "FAILED", None)]
    assert _rows(conn, "SELECT COUNT(*) FROM pipeline_log") == [(3,)]
