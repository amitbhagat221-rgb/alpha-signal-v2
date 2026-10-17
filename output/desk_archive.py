"""Dated archive for the Markets / macro page and the industry explainers (plan 0028).

Every part the desk produces (the daily brief, weekly hot spots, monthly chapters, regime, house view, playbooks,
external readings, industry explainers) is saved here with the date it describes. Nothing is overwritten:
saving an identical payload again is a no-op, a changed payload for the same date becomes a new version.
The cockpit's "As of" filter calls latest(part, item, as_of).

    from output import desk_archive as A
    A.save("brief", payload, "2026-10-16")
    A.latest("brief", as_of="2026-10-05")       # the brief as it read on (or before) that day
    A.dates("chapter", "in-4")                   # the dates a chapter has versions for
"""
import json

import db

PARTS = ("brief", "hotspots", "chapter", "industry_explainer", "regime", "house_view", "playbook", "external")
METHODS = ("live", "retrospective", "manual")


def _dump(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, default=str)


def save(part, payload, snapshot_date, item="", sources=None, method="live", conn=None):
    """Append a snapshot. Returns the version written, or the existing version if this exact payload is already
    stored for (date, part, item). Raises on an unknown part or method so a typo never creates a silent new part.
    With conn=None it opens and commits its own connection; with a conn it never commits (the caller owns the
    transaction, so a dry run can roll everything back)."""
    if part not in PARTS:
        raise ValueError(f"unknown desk part {part!r}; known: {PARTS}")
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}")
    body = _dump(payload)
    if conn is None:
        with db.get_db() as c:
            return _save(c, part, body, snapshot_date, item, sources, method)
    return _save(conn, part, body, snapshot_date, item, sources, method)   # caller owns the transaction


def _save(conn, part, body, snapshot_date, item, sources, method):
    rows = conn.execute("SELECT version, payload FROM desk_snapshots WHERE snapshot_date = ? AND part = ? AND item = ? "
                        "ORDER BY version", (snapshot_date, part, item)).fetchall()
    for version, existing in rows:
        if existing == body:
            return version
    version = (rows[-1][0] + 1) if rows else 1
    conn.execute("INSERT OR IGNORE INTO desk_snapshots (snapshot_date, part, item, version, payload, sources, method) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (snapshot_date, part, item, version, body, _dump(sources) if sources else None, method))
    return version


def latest(part, item="", as_of=None, conn=None):
    """The newest version on or before as_of (default: the newest overall), as a dict with the payload decoded;
    None when nothing is archived yet."""
    sql = ("SELECT snapshot_date, version, payload, sources, method, created_at FROM desk_snapshots "
           "WHERE part = ? AND item = ?" + (" AND snapshot_date <= ?" if as_of else "") +
           " ORDER BY snapshot_date DESC, version DESC LIMIT 1")
    params = [part, item] + ([as_of] if as_of else [])
    row = (conn.execute(sql, params).fetchone() if conn else db.one(sql, params))
    if not row:
        return None
    row = dict(zip(("snapshot_date", "version", "payload", "sources", "method", "created_at"), row)) if not isinstance(row, dict) else dict(row)
    row["payload"] = json.loads(row["payload"])
    row["sources"] = json.loads(row["sources"]) if row["sources"] else []
    return row


def dates(part, item=None, conn=None):
    """Sorted distinct dates archived for a part (and item, if given): what the date filter offers."""
    sql = "SELECT DISTINCT snapshot_date FROM desk_snapshots WHERE part = ?" + (" AND item = ?" if item is not None else "") + " ORDER BY snapshot_date"
    params = [part] + ([item] if item is not None else [])
    rows = conn.execute(sql, params).fetchall() if conn else db.rows(sql, params)
    return [r[0] if not isinstance(r, dict) else r["snapshot_date"] for r in rows]


def summary(conn=None):
    """Per part: items, dates, first and last date, rows. For the archive page and health."""
    sql = ("SELECT part, COUNT(DISTINCT item) items, COUNT(DISTINCT snapshot_date) days, MIN(snapshot_date) first, "
           "MAX(snapshot_date) last, COUNT(*) n FROM desk_snapshots GROUP BY part ORDER BY part")
    rows = conn.execute(sql).fetchall() if conn else db.rows(sql)
    keys = ("part", "items", "days", "first", "last", "rows")
    return [dict(zip(keys, r)) if not isinstance(r, dict) else dict(r) for r in rows]
