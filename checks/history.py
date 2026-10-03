"""
When did each check last fire? (ADR 0060)

One row per check per day in `check_results` (catalog check 'health'): a firing
verdict under its id with its severity, every other check one PASS under its code.
It answers the two questions a check must survive: how long has this been firing,
and has it ever fired at all.

    read()          {streaks, last_fired, since} — part of the gathered state
    record(rows)    write today's rows (checks.report.records); idempotent per day

Only the health CLI records. The MCP and the ops page read, they never write.
"""

import json
from datetime import date, datetime

import db
from checks import CRITICAL, PASS, WARN

HISTORY_DAYS = 400


def _check_id(conn, create=False):
    if create:
        conn.execute("INSERT OR IGNORE INTO catalog(kind, name, first_seen) VALUES ('check', 'health', ?)",
                     [date.today().isoformat()])
    row = conn.execute("SELECT catalog_id FROM catalog WHERE kind = 'check' AND name = 'health'").fetchone()
    return row[0] if row else None


def read():
    """{streaks: {issue id: days firing in a row up to the last recorded day before
    today}, last_fired: {check code: date}, since: first recorded date}."""
    out = {"streaks": {}, "last_fired": {}, "since": None}
    today = date.today().isoformat()
    with db.get_db() as conn:
        cid = _check_id(conn)
        if cid is None:
            return out
        rows = conn.execute(
            "SELECT subject, date, status, detail FROM check_results WHERE check_id = ? AND date >= date('now', ?) "
            "ORDER BY date DESC", [cid, f"-{HISTORY_DAYS} days"]).fetchall()
    if not rows:
        return out
    out["since"] = min(r[1] for r in rows)
    recorded = sorted({r[1] for r in rows if r[1] < today}, reverse=True)
    fired = {}
    for subject, day, status, detail in rows:
        if status == PASS:
            continue
        code = json.loads(detail or "{}").get("code") or subject
        out["last_fired"][code] = max(day, out["last_fired"].get(code, ""))
        if status in (CRITICAL, WARN) and day < today:
            fired.setdefault(subject, set()).add(day)
    for subject, days in fired.items():
        n = 0
        for d in recorded:
            if d not in days:
                break
            n += 1
        if n:
            out["streaks"][subject] = n
    return out


def record(rows):
    """Write today's [(subject, check code, status, n_bad)]; returns the row count."""
    today, now = date.today().isoformat(), datetime.now().isoformat(timespec="seconds")
    with db.get_db() as conn:
        cid = _check_id(conn, create=True)
        conn.execute("DELETE FROM check_results WHERE check_id = ? AND date = ?", [cid, today])
        conn.executemany(
            "INSERT INTO check_results(check_id, subject, entity_id, date, status, score, detail, checked_at) "
            "VALUES (?, ?, 0, ?, ?, ?, ?, ?)",
            [(cid, subject, today, status, n_bad, json.dumps({"code": code}), now)
             for subject, code, status, n_bad in rows])
        conn.commit()
    return len(rows)
