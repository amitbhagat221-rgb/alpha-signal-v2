"""The system-architect on a cadence (plan 0032 stage 6): the probes catch planted faults, the memo must call
every finding, `fix` / `inline` calls become one work order per tier (A waits for the CEO, B self-approves),
and the seat keeps its builder file."""
import pytest

import org
from alpha_mcp import org_kinds
from tools import arch_probes

from tests.test_org import EL, q  # noqa: F401  (the fresh-DB fixture)

FINDINGS = [
    {"finding_id": "A1", "probe": "undeclared_io", "subject": "fetch_x writes prices", "claim": "undeclared write",
     "evidence": {"module": "sources.x", "undeclared_writes": ["prices"]}, "touches": ["post-checks decide success"], "first_raised": None},
    {"finding_id": "A2", "probe": "tier_literals", "subject": "signals/sig.py:12", "claim": "a hard-coded tier list",
     "evidence": {"line": 12}, "touches": ["the tiers"], "first_raised": None},
    {"finding_id": "A3", "probe": "sleep_outside_door", "subject": "config.py:40", "claim": "time.sleep outside the door",
     "evidence": {"line": 40}, "touches": [], "first_raised": None},
    {"finding_id": "A4", "probe": "single_caller", "subject": "tools/util.py:helper", "claim": "called once",
     "evidence": {"lines": 50, "caller": "tools/user.py"}, "touches": [], "first_raised": None},
]
PAYLOAD = {"role": "system-architect", "facts": {"findings": FINDINGS, "drill": {"planted": 7, "caught": 7}},
           "_sets": {"findings": ["A1", "A2", "A3", "A4"], "owners": ["backend-engineer", "ceo"]}}


def _memo(calls):
    return {"headline": "Four findings this week", "verdict": "drift", "eli5": EL, "top_action": "Declare the write",
            "findings": [{"finding_id": i, "call": c, "why": "read the evidence"} for i, c in calls.items()]}


def test_every_planted_fault_is_caught():
    d = arch_probes.drill()
    assert d["missed"] == [], d


def test_tier_follows_the_path():
    assert org_kinds.tier_for("config.py:40") == "A" and org_kinds.tier_for("run.sh probe") == "A"
    assert org_kinds.tier_for("signals/sig.py:12") == "B" and org_kinds.tier_for("fetch_x writes prices") == "B"


def test_the_review_must_call_every_finding(q):  # noqa: F811
    v = org_kinds.KINDS["org_arch_review"]["validate"]
    assert v(_memo({"A1": "fix", "A2": "fix", "A3": "fix", "A4": "inline"}), PAYLOAD)
    with pytest.raises(ValueError, match="exactly one call"):
        v(_memo({"A1": "fix", "A2": "fix"}), PAYLOAD)


def test_fix_and_inline_calls_draft_one_order_per_tier(q):  # noqa: F811
    q.enqueue("org_arch_review", items=[("2026-W44", {**PAYLOAD, "key": "2026-W44", "period": "2026-W44", "as_of": "2026-10-31"}, 4)])
    (task,) = q.claim("org_arch_review", worker="system-architect")
    out = q.submit([{"task_id": task["task_id"], "result": _memo({"A1": "fix", "A2": "keep", "A3": "fix", "A4": "inline"})}],
                   worker="system-architect")
    assert out["counts"] == {"done": 1}, out
    (memo,) = org.docs(["arch_review"])
    assert memo["fields"]["findings"][0]["subject"] == "fetch_x writes prices"
    orders = sorted((w for w in org.work_orders() if w["role"] == "system-architect"), key=lambda w: w["tier"])
    assert [w["tier"] for w in orders] == ["A", "B"]
    a, b = orders
    assert a["auto_approve_at"] is None and [i["title"] for i in a["items"]] == ["Fix config.py:40"]
    assert b["auto_approve_at"] and sorted(i["title"] for i in b["items"]) == ["Fix fetch_x writes prices", "Inline tools/util.py:helper"]
    assert all(org.docs(["work_order"])[i]["parent_doc_id"] == memo["doc_id"] for i in range(2))
    # a keep with a reason is not raised again next week
    nxt = org_kinds.build("org_arch_review", __import__("datetime").date(2026, 11, 7), "2026-W45")
    (key, item, _p), = nxt
    assert "signals/sig.py:12" not in {f["subject"] for f in item["facts"]["findings"]}


def test_the_architect_is_a_weekly_desk_seat_that_keeps_its_builder_file():
    s = org.ROLES["system-architect"]
    assert s["type"] == "desk" and s["agent"] and s["cadence"] == "weekly:sat" and s["reports_to"] == "cto"
    assert (org.ROOT / ".claude" / "agents" / "system-architect.md").exists()
    assert "system-architect" in org.RUN_ORDER and org.RUN_ORDER.index("system-architect") < org.RUN_ORDER.index("cto")
