"""The weekly data-quality audit (plan 0020 / plan 0019): the probes notice a planted
fault, and the auditor seat's memo is checked against a re-run of each finding's query."""
import sqlite3

import pytest

import db
import factors
import org
from alpha_mcp import org_kinds
from tools import dq_probes
from tools.reconcile import FUND_FIELDS

from tests.test_org import EL, q  # noqa: F401  (the fresh-DB fixture)


def _reader(tmp_path, rows):
    """A scratch DB with two price days for `rows` = {sid: (close day 1, close day 2)}."""
    path = tmp_path / "px.db"
    with sqlite3.connect(path) as c:
        c.executescript(db.SCHEMA_PATH.read_text())
        c.executemany("INSERT INTO stocks (sid, ticker, name, sector, cap_tier) VALUES (?, ?, ?, 'Energy', 'SMALL')",
                      [(s, s, s) for s in rows])
        for d, i in (("2026-09-30", 0), ("2026-10-01", 1)):
            c.executemany("INSERT INTO stock_prices (sid, date, close, volume, source) VALUES (?, ?, ?, ?, 'bhavcopy')",
                          [(s, d, px[i], 1000 + i * 7) for s, px in rows.items()])
    return dq_probes.reader(path), path


def test_a_probe_finding_carries_the_query_that_shows_it(tmp_path):
    q_, path = _reader(tmp_path, {f"S{i}": (100.0, 101.0) for i in range(30)} | {"SPLIT": (500.0, 100.0)})
    (f,) = dq_probes.rules(q_, only={"stock_prices.close"})
    assert (f["n_bad"], f["verify"]) == (1, "query") and "SPLIT" in f["sample"]
    assert int(q_(f["query"]).iloc[0]["n_bad"]) == f["n_bad"]            # anyone can re-run it
    with sqlite3.connect(path) as c:                                     # a copied day
        c.execute("INSERT INTO stock_prices (sid, date, close, volume, source) "
                  "SELECT sid, '2026-10-02', close, volume, source FROM stock_prices WHERE date = '2026-10-01'")
    assert [f["subject"] for f in dq_probes.rules(q_, only={"stock_prices.date"})] == ["stock_prices.date"]


def test_every_planted_fault_names_a_subject_a_probe_can_report():
    subjects = ({r[1] for r in dq_probes.RULES} | {f"{t}.{c}" for t, c, *_ in FUND_FIELDS}
                | {f"{t}.{c}" for t, c in dq_probes.NAME_FITS})
    for name, _what, _sql, _probe, subject in dq_probes.PLANTS:
        assert subject in subjects, name
    for _probe, subject in dq_probes.KNOWN:
        assert subject in subjects | {"annual_cash_flow.dividends_paid"}


FINDINGS = [
    {"finding_id": "F1", "probe": "impossible", "subject": "t.real", "claim": "x", "n_bad": 400, "n_total": 2000,
     "query": "SELECT 1 AS real", "known": None, "first_reported": None},
    {"finding_id": "F2", "probe": "impossible", "subject": "t.trap", "claim": "x", "n_bad": 600, "n_total": 2000,
     "query": "SELECT 1 AS trap", "known": None, "first_reported": None},
    {"finding_id": "F3", "probe": "recompute", "subject": "sampled", "claim": "x", "n_bad": 9, "n_total": 30,
     "query": None, "known": None, "first_reported": None},
]
PAYLOAD = {"role": "dq-auditor", "facts": {"findings": FINDINGS, "drill": {"planted": 7, "caught": 7}},
           "_sets": {"findings": ["F1", "F2", "F3"], "owners": ["backend-engineer", "ceo"]}}


def _memo(calls, own=None):
    return {"headline": "One real fault this week", "verdict": "issues", "eli5": EL, "top_action": "Fix the column",
            "findings": [{"finding_id": i, "disposition": d, "why": "checked the query"} for i, d in calls.items()],
            **({"own_findings": own} if own else {})}


@pytest.fixture
def rerun(monkeypatch):
    """The server's re-run: the real finding still shows 400 bad rows, the trap shows 3."""
    def check(query):
        if "bogus" in query:
            raise ValueError("no such table")
        return ({"SELECT 1 AS real": 400, "SELECT 1 AS trap": 3}.get(query, 12), 2000)
    monkeypatch.setattr(dq_probes, "check", check)


def test_the_memo_must_call_every_finding_and_prove_its_own(q, rerun):  # noqa: F811
    v = q.TASK_KINDS["org_dq_audit"]["validate"]
    assert v(_memo({"F1": "real", "F2": "does-not-reproduce", "F3": "needs-more-data"}), PAYLOAD)
    with pytest.raises(ValueError, match="exactly one call"):
        v(_memo({"F1": "real", "F2": "does-not-reproduce"}), PAYLOAD)
    own = {"title": "A second column", "claim": "Another column is wrong too", "query": "SELECT 12 AS n_bad", "n_bad": 12}
    assert v(_memo({"F1": "real", "F2": "does-not-reproduce", "F3": "real"}, [own]), PAYLOAD)
    with pytest.raises(ValueError, match="returned n_bad 12, the memo states 90"):
        v(_memo({"F1": "real", "F2": "does-not-reproduce", "F3": "real"}, [{**own, "n_bad": 90}]), PAYLOAD)
    with pytest.raises(ValueError, match="did not run"):
        v(_memo({"F1": "real", "F2": "does-not-reproduce", "F3": "real"}, [{**own, "query": "SELECT bogus"}]), PAYLOAD)


def test_a_call_that_does_not_match_the_rerun_is_on_the_record(q, rerun):  # noqa: F811
    honest = org_kinds._dq_score(_memo({"F1": "real", "F2": "does-not-reproduce", "F3": "real"}), PAYLOAD)
    assert (honest["checked"], honest["right"], honest["new_real"]) == (2, 2, 2)      # F3 has no query: not checked
    lazy = org_kinds._dq_score(_memo({"F1": "real", "F2": "real", "F3": "real"}), PAYLOAD)       # never ran the trap's query
    assert lazy["claimed_real_but_not"] == ["F2"] and lazy["right"] == 1
    blind = org_kinds._dq_score(_memo({"F1": "does-not-reproduce", "F2": "does-not-reproduce", "F3": "real"}), PAYLOAD)
    assert blind["dismissed_but_real"] == ["F1"]


def test_the_audit_memo_is_stored_with_its_score_and_feeds_the_scorecard(q, rerun):  # noqa: F811
    q.enqueue("org_dq_audit", items=[("2026-W40", {**PAYLOAD, "key": "2026-W40", "period": "2026-W40", "as_of": "2026-10-04"}, 4)])
    (task,) = q.claim("org_dq_audit", worker="dq-auditor")
    out = q.submit([{"task_id": task["task_id"], "result": _memo({"F1": "real", "F2": "real", "F3": "needs-more-data"})}],
                   worker="dq-auditor")
    assert out["counts"] == {"done": 1}, out
    (doc,) = org.docs(["dq_audit"])
    assert doc["fields"]["score"]["claimed_real_but_not"] == ["F2"]
    assert doc["fields"]["findings"][0]["subject"] == "t.real"                       # readable without the brief
    card = org.scorecard()["dq-auditor"]["audit"]
    assert (card["audits"], card["checked"], card["right"], card["claimed_real_but_not"]) == (1, 2, 1, 1)


def test_the_auditor_is_a_weekly_read_only_seat():
    s = org.ROLES["dq-auditor"]
    assert s["cadence"].startswith("weekly:") and s["graded_by"] == "compliance" and "dq_audit" in org_kinds.GRADED
    assert org.RUN_ORDER.index("dq-auditor") < org.RUN_ORDER.index("compliance")
    assert factors.SIGNAL_WEIGHTS                                                    # the probes read the registry
