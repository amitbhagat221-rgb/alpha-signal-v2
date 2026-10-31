"""The Code Janitor (plan 0032 stage 3, ADR 0085): the probes catch planted clutter, the seat's memo
must call every finding, and `dead` / `sticker` calls become one Tier B work order the server drafts."""
import pytest

import org
from alpha_mcp import org_kinds
from tools import code_probes

from tests.test_org import EL, q  # noqa: F401  (the fresh-DB fixture)

FINDINGS = [
    {"finding_id": "C1", "probe": "unreferenced", "subject": "tools/old_thing.py", "claim": "nothing refers to it",
     "evidence": {"refs_code": 0, "refs_cron": 0, "refs_tests": [], "last_touched": "2026-03-01", "ran_in_90d": 0, "lines": 80},
     "sticker_hits_90d": None, "first_raised": None, "kept_before": None},
    {"finding_id": "C2", "probe": "tests_cannot_fail", "subject": "tests/test_x.py::test_nothing", "claim": "no assert",
     "evidence": {"lines": 3, "line": 10}, "sticker_hits_90d": None, "first_raised": None, "kept_before": None},
    {"finding_id": "C3", "probe": "flaky_steps", "subject": "fetch_x", "claim": "failed then succeeded",
     "evidence": {"days_flaky": 3}, "sticker_hits_90d": None, "first_raised": None, "kept_before": None},
]
PAYLOAD = {"role": "code-janitor", "facts": {"findings": FINDINGS, "drill": {"planted": 5, "caught": 5}},
           "_sets": {"findings": ["C1", "C2", "C3"], "owners": ["backend-engineer", "ceo"]}}


def _memo(calls):
    return {"headline": "Three pieces of clutter", "verdict": "clutter", "eli5": EL, "top_action": "Delete the old tool",
            "findings": [{"finding_id": i, "call": c, "why": "read the evidence"} for i, c in calls.items()]}


def test_every_planted_kind_of_clutter_is_caught():
    d = code_probes.drill()
    assert d["missed"] == [], d


def test_the_sweep_must_call_every_finding(q):  # noqa: F811
    v = org_kinds.KINDS["org_code_sweep"]["validate"]
    assert v(_memo({"C1": "sticker", "C2": "dead", "C3": "keep"}), PAYLOAD)
    with pytest.raises(ValueError, match="exactly one call"):
        v(_memo({"C1": "sticker", "C2": "dead"}), PAYLOAD)


def test_dead_and_sticker_calls_draft_one_tier_b_order(q):  # noqa: F811
    q.enqueue("org_code_sweep", items=[("2026-W44", {**PAYLOAD, "key": "2026-W44", "period": "2026-W44", "as_of": "2026-11-01"}, 4)])
    (task,) = q.claim("org_code_sweep", worker="code-janitor")
    out = q.submit([{"task_id": task["task_id"], "result": _memo({"C1": "sticker", "C2": "dead", "C3": "keep"})}], worker="code-janitor")
    assert out["counts"] == {"done": 1}, out
    (memo,) = org.docs(["code_sweep"])
    assert memo["fields"]["findings"][0]["subject"] == "tools/old_thing.py"       # readable without the brief
    (wo,) = [w for w in org.work_orders() if w["role"] == "code-janitor"]
    assert wo["tier"] == "B" and wo["status"] == "awaiting approval" and wo["auto_approve_at"]
    titles = sorted(i["title"] for i in wo["items"])
    assert titles == ["Delete tests/test_x.py::test_nothing", "Sticker on tools/old_thing.py"]
    assert 'runlog.note("sticker:tools.old_thing")' in wo["items"][0]["what"] + wo["items"][1]["what"]
    assert org.docs(["work_order"])[0]["parent_doc_id"] == memo["doc_id"]
    # all keeps → no order
    q.enqueue("org_code_sweep", items=[("2026-W45", {**PAYLOAD, "key": "2026-W45", "period": "2026-W45", "as_of": "2026-11-08"}, 4)])
    (task,) = q.claim("org_code_sweep", worker="code-janitor")
    q.submit([{"task_id": task["task_id"], "result": _memo({"C1": "keep", "C2": "keep", "C3": "keep"})}], worker="code-janitor")
    assert len([w for w in org.work_orders() if w["role"] == "code-janitor"]) == 1


def test_the_janitor_is_a_weekly_desk_seat_under_the_cto():
    s = org.ROLES["code-janitor"]
    assert s["type"] == "desk" and s["reports_to"] == "cto" and s["cadence"] == "weekly:sun"
    assert "code-janitor" in org.RUN_ORDER and org.RUN_ORDER.index("code-janitor") < org.RUN_ORDER.index("cto")
