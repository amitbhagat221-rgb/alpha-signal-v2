"""ADR 0090: a dropped seat is never due, the data-engineer's brief is built only when the health report
has something new, and the Sunday nudge reports the inbox when there is no board pack."""
import datetime as dt
import json

import org
from alpha_mcp import org_kinds

from tests.test_org import q  # noqa: F401  (the fresh-DB fixture)


def test_dropped_seats_are_never_due_but_keep_their_charter_and_kind():
    sunday = dt.date(2026, 11, 8)
    for role in ("chief-of-staff", "ai-scout"):
        assert org.ROLES[role]["enabled"] is False and not org.is_due(role, sunday)
        assert (org.CHARTERS / f"{role}.md").exists() and org.ROLES[role]["kinds"]
    assert org.is_due("risk-officer", sunday) and not org.is_due("risk-officer", dt.date(2026, 11, 9))
    assert org.is_due("compliance", sunday) and not org.is_due("compliance", dt.date(2026, 11, 9))
    assert org.is_due("dq-auditor", sunday) and org.is_due("data-engineer", dt.date(2026, 11, 9))


def test_triage_is_skipped_when_the_health_report_has_nothing_new(q, monkeypatch):  # noqa: F811
    issues = [{"issue_id": "I1", "severity": "WARN", "code": "TABLE_STALE", "message": "x", "detail": ""}]
    assert org_kinds._triage_has_news(issues)                       # no earlier brief: build it
    q.enqueue("org_data_triage", items=[("2026-11-01", {"role": "data-engineer", "key": "2026-11-01", "facts": {"issues": issues},
                                                        "_sets": {"issues": ["I1"], "owners": ["backend-engineer"]}}, 4)])
    (task,) = q.claim("org_data_triage", worker="data-engineer")
    import db
    with db.get_db() as conn:
        conn.execute("UPDATE llm_tasks SET status = 'done', done_at = '2026-11-01T06:31:00' WHERE task_id = ?", (task["task_id"],))
    assert not org_kinds._triage_has_news(issues)                   # the same WARN again: nothing new
    assert org_kinds._triage_has_news(issues + [{"issue_id": "I2", "severity": "WARN", "code": "FEED_DEAD", "message": "y", "detail": ""}])
    assert org_kinds._triage_has_news([{**issues[0], "severity": "CRITICAL"}])


def test_sunday_nudge_reports_the_inbox_once_when_there_is_no_pack(q, monkeypatch):  # noqa: F811
    import db
    from tools import health_report
    sent = []
    monkeypatch.setattr(health_report, "send_ntfy", lambda text, **kw: sent.append(text) or {"ok": True})
    monkeypatch.setattr(health_report, "send_email", lambda *a, **kw: {"ok": True})

    class Sunday(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 8)
    monkeypatch.setattr(org.dt, "date", Sunday)
    with db.get_db() as conn:
        org.save_doc(conn, "ask", "ask1", "Decide X", {"role": "cio", "ask": "x", "recommendation": "y"}, doc_date="2026-11-08")
    out = org.deliver_all(day=dt.date(2026, 11, 8))
    assert out.get("inbox_push") and "1 waiting" in sent[0] and "ask" in sent[0]
    assert "inbox_push" not in org.deliver_all(day=dt.date(2026, 11, 8))      # once a day
