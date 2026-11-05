"""A partial sync must not move another step's starting point, and a step-log row the watermark jumped past is
still carried (both broke parity from 2026-11-01: a `--only decisions` run hid the 31 Oct harvest from the next full
sync, and steplog.py's first write stranded 98 pipeline_log rows)."""
import json
import sqlite3

from datamodel import reconcile, sync


def _runs(*rows):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE runs (run_id INTEGER PRIMARY KEY, kind TEXT, started_at TEXT, status TEXT, attrs TEXT)")
    for started, status, steps in rows:
        c.execute("INSERT INTO runs (kind, started_at, status, attrs) VALUES ('datamodel_sync', ?, ?, ?)",
                  (started, status, None if steps is None else json.dumps({"steps": steps})))
    return c


def test_a_partial_sync_moves_only_its_own_steps_starting_point():
    c = _runs(("2026-10-31T05:55:00", "ok", "events,decisions,ops"), ("2026-11-01T08:44:38", "ok", "decisions"))
    assert sync.last_sync(c, "events") == "2026-10-31T05:55:00"
    assert sync.last_sync(c, "decisions") == "2026-11-01T08:44:38"
    assert sync.last_sync(c) == "2026-11-01T08:44:38"


def test_a_failed_or_running_sync_does_not_count_and_no_steps_means_all():
    c = _runs(("2026-10-30T05:00:00", "ok", None), ("2026-10-31T05:00:00", "failed", "events"), ("2026-11-01T05:00:00", "running", "events"))
    assert sync.last_sync(c, "events") == "2026-10-30T05:00:00"
    assert sync.last_sync(_runs(), "events") is None


def test_the_reconcile_and_the_sync_share_one_definition():
    c = _runs(("2026-10-31T05:55:00", "ok", "events"), ("2026-11-01T08:44:38", "ok", "decisions"))
    assert reconcile.watermark(c, "events") == sync.last_sync(c, "events") == "2026-10-31T05:55:00"


def _log(rows, mirrored):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE pipeline_log (id INTEGER PRIMARY KEY, status TEXT)")
    c.execute("CREATE TABLE step_runs (attrs TEXT)")
    c.executemany("INSERT INTO pipeline_log VALUES (?, ?)", rows)
    c.executemany("INSERT INTO step_runs VALUES (?)", [(json.dumps({"from": "pipeline_log", "log_id": i}),) for i in mirrored])
    return c


def test_a_terminal_row_below_the_watermark_is_carried_once():
    # 1 mirrored; 2 and 3 stranded when steplog wrote 5 (2 RUNNING, closed by 3); 4 and 5 written by steplog itself
    rows = [(1, "SUCCESS"), (2, "RUNNING"), (3, "FAILED"), (4, "SKIPPED"), (5, "SUCCESS")]
    c = _log(rows, mirrored=[1, 4, 5])
    assert list(sync.unmirrored_log(c, 5)["id"]) == [3]
    c.execute("INSERT INTO step_runs VALUES (?)", (json.dumps({"from": "pipeline_log", "log_id": 3}),))
    assert sync.unmirrored_log(c, 5).empty                     # carried: never again


def test_rows_past_the_watermark_still_come_including_running_ones():
    c = _log([(1, "SUCCESS"), (2, "RUNNING"), (3, "SUCCESS")], mirrored=[1])
    assert list(sync.unmirrored_log(c, 1)["id"]) == [2, 3]


def test_the_planner_statistics_table_is_internal():
    assert "sqlite_stat1" in reconcile.RETIRED
