"""
The step log (plan 0030 stage 1 part 3): every step attempt as a row of `step_runs` under its `runs` row.

Writer — `log(step, status, …)`, what `pipeline.log_step`, run.sh `logged`, the watchdog and the
endpoint audit call. It still writes the legacy `pipeline_log` row (dual write until the drop) and
puts the same attempt in `step_runs`: RUNNING opens an attempt, the terminal status closes it in
place (the legacy log keeps two rows, the v3 table one). The attempt carries the legacy row's id in
`attrs.log_id`, so `datamodel/sync.py`'s mirror sees nothing new (it watermarks on that id — it only
catches up rows a process on older code wrote) and `datamodel/reconcile.py`'s parity check holds:
legacy terminal rows + orphan RUNNING rows = step_runs attempts.

Readers — `source()`: the FROM clause for pipeline_log-shaped SQL under `config.DATA_MODEL["steps"]`:
"old" is the legacy table, "new" a subquery over step_runs ⋈ runs with the same columns
(`id` = the attempt's creation order). Every reader of the step log builds its SQL on it, so the
flag is the rollback. pipeline_log cannot be a view (one row per attempt vs two), hence the code change.
"""
import json
from contextlib import nullcontext
from datetime import date, datetime

import config

NEW_SOURCE = """(SELECT s.rowid AS id, r.as_of_date AS run_date, s.step AS step_name,
            CASE WHEN s.status = 'RUNNING(orphan)' THEN 'RUNNING' ELSE s.status END AS status,
            s.rows AS rows_affected, s.started_at, s.finished_at,
            json_extract(s.attrs, '$.duration_sec') AS duration_sec, s.error AS error_message
     FROM step_runs s JOIN runs r ON r.run_id = s.run_id
     WHERE json_extract(s.attrs, '$.from') = 'pipeline_log')"""


def source():
    """What a reader puts after FROM: `pipeline_log`, or the step_runs subquery when the flag is 'new'."""
    return NEW_SOURCE if config.DATA_MODEL.get("steps") == "new" else "pipeline_log"


def run_kind(step):
    """The runs.kind a step logs under: the watchdog and the endpoint audit have runs of their own."""
    for prefix, kind in (("watchdog_", "watchdog"), ("endpoint_audit_", "endpoint_audit")):
        if step.startswith(prefix):
            return kind
    return "morning"


def log(step, status, rows=None, started=None, error=None, run_date=None, conn=None):
    """Record a step attempt: the legacy pipeline_log row and the step_runs attempt, one transaction.
    `started` ties a terminal status to the RUNNING row it closes (pipeline.run_step passes it); a
    terminal status with no open attempt (run.sh `logged`, the watchdog) is an attempt of its own."""
    from db import get_db
    now = datetime.now().isoformat(timespec="seconds")
    duration = None
    if started:
        try:
            duration = round((datetime.now() - datetime.fromisoformat(started)).total_seconds(), 2)
        except ValueError:
            pass
    run_date = run_date or date.today().isoformat()
    with (nullcontext(conn) if conn is not None else get_db()) as c:
        cur = c.execute(
            """INSERT INTO pipeline_log
               (run_date, step_name, status, rows_affected, started_at, finished_at, duration_sec, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_date, step, status, rows, started, now, duration, error))
        _step_run(c, run_date, step, status, rows, started, now, duration, error, cur.lastrowid)


def _step_run(c, run_date, step, status, rows, started, now, duration, error, log_id):
    from datamodel import decisions
    kind = run_kind(step)
    run_id = decisions.run_for(c, kind, run_date, official=int(kind == "morning"))
    if status != "RUNNING":
        open_ = c.execute("SELECT attempt FROM step_runs WHERE run_id = ? AND step = ? AND status = 'RUNNING' AND started_at IS ? "
                          "ORDER BY attempt DESC LIMIT 1", (run_id, step, started)).fetchone()
        if open_:
            c.execute("UPDATE step_runs SET status = ?, finished_at = ?, rows = ?, error = ?, "
                      "attrs = json_set(COALESCE(attrs, '{}'), '$.log_id', ?, '$.duration_sec', ?) WHERE run_id = ? AND step = ? AND attempt = ?",
                      (status, now, rows, error, log_id, duration, run_id, step, open_[0]))
            return
    attempt = 1 + (c.execute("SELECT MAX(attempt) FROM step_runs WHERE run_id = ? AND step = ?", (run_id, step)).fetchone()[0] or 0)
    c.execute("INSERT INTO step_runs (run_id, step, attempt, status, started_at, finished_at, rows, error, attrs) VALUES (?,?,?,?,?,?,?,?,?)",
              (run_id, step, attempt, status, started or now, None if status == "RUNNING" else now,
               None if status == "RUNNING" else rows, None if status == "RUNNING" else error,
               json.dumps({"from": "pipeline_log", "log_id": log_id, "duration_sec": None if status == "RUNNING" else duration})))
