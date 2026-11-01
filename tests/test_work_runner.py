"""The unattended Tier B runner (plan 0032 stage 7, ADR 0091): every guardrail that does not need a real
builder is exercised here — refusal rules, the scope check, the quiet window, the kill switch, the attempt
cap, and the memo. The builder itself is never started in a test."""
import datetime as dt

import org
from tools import work_runner as wr

from tests.test_org import q  # noqa: F401  (the fresh-DB fixture)

ITEM = {"title": "Delete tools/old_thing.py", "what": "Remove it.", "where": "tools/old_thing.py",
        "done_when": "suite green", "owner": "backend-engineer", "size": "S"}


def _order(q, tier="B", items=None, title="Clutter"):  # noqa: F811
    n = org.save_work_order("code-janitor", None, {"title": title, "summary": "x", "items": items or [ITEM], "tier": tier})
    return org.work_order(n)


def test_refusals(q, monkeypatch):  # noqa: F811
    b = _order(q)
    assert wr.refusal(b) == "status is awaiting approval"
    # a runner failure gets one retry: blocked with a [runner] note is eligible, blocked by a person is not
    assert wr.refusal({**b, "status": "blocked", "note": "[runner] the builder changed nothing"}) is None
    assert wr.refusal({**b, "status": "blocked", "note": "waiting on Amit"}) == "status is blocked"
    org.decide(org.work_order_doc_id(b["number"]), "approve")
    assert wr.refusal(org.work_order(b["number"])) is None
    a = _order(q, tier="A", title="Weights")
    org.decide(org.work_order_doc_id(a["number"]), "approve")
    assert "Tier A" in wr.refusal(org.work_order(a["number"]))
    c = _order(q, items=[{**ITEM, "where": "config.py", "title": "Edit config"}], title="Config")
    org.decide(org.work_order_doc_id(c["number"]), "approve")
    assert "Tier A path" in wr.refusal(org.work_order(c["number"]))
    # the attempt cap: two runner notes and it is done trying
    for i in (1, 2):
        org.work_status(b["number"], "in_progress", f"[runner] attempt {i}")
        org.work_status(b["number"], "blocked", f"[runner] the builder changed nothing")
    org.decide(org.work_order_doc_id(b["number"]), "approve")
    w = org.work_order(b["number"])
    assert wr.attempts(w) == 2 and "already tried" in (wr.refusal({**w, "status": "approved"}) or "")


def test_scope_check_rejects_tier_a_paths_off_limits_files_and_unnamed_deletions():
    order = {"items": [ITEM]}
    assert wr.scope_problems([(" M", "tools/helper.py"), (" D", "tools/old_thing.py")], order) == []
    probs = wr.scope_problems([(" M", "config.py"), (" M", "ops/crontab.txt"), (" D", "signals/x.py")], order)
    assert any("Tier A" in p for p in probs) and any("off limits" in p for p in probs) and any("deleted" in p for p in probs)
    assert any("cap" in p for p in wr.scope_problems([(" M", f"tools/f{i}.py") for i in range(30)], order))


def test_quiet_window_and_kill_switch(tmp_path, monkeypatch):
    assert wr.in_quiet_window(dt.datetime(2026, 11, 2, 3, 30, tzinfo=dt.timezone.utc))
    assert not wr.in_quiet_window(dt.datetime(2026, 11, 2, 21, 30, tzinfo=dt.timezone.utc))
    monkeypatch.setattr(wr, "KILL_FILE", tmp_path / "off")
    assert not wr.kill_switch()
    (tmp_path / "off").write_text("")
    assert wr.run(dry=True)["stopped"].startswith("kill switch")


def test_dry_run_takes_nothing_and_reports(q, monkeypatch):  # noqa: F811
    b = _order(q)
    org.decide(org.work_order_doc_id(b["number"]), "approve")
    monkeypatch.setattr(wr, "KILL_FILE", org.ROOT / "output" / "no-such-kill-file")
    out = wr.run(dry=True)
    (facts,) = out["ran"]
    assert facts["order"] == b["number"] and facts["problems"] == ["dry run: nothing started"] and not facts["merged"]
    assert org.work_order(b["number"])["status"] == "approved"             # a dry run records nothing


def test_memo_reads_like_a_story_and_carries_the_undo():
    facts = {"order": 9, "title": "Clutter: 1 deletion", "tier": "B", "started_at": "2026-11-02T21:31:00", "finished_at": "2026-11-02T21:49:00",
             "items": ["Delete tools/old_thing.py"], "merged": True, "sha": "abc1234def", "branch": "wo-9", "pushed": True,
             "changed": ["tools/old_thing.py", "tests/test_old.py"], "lines": 120, "suite": "1131 passed", "problems": [], "dry": False,
             "summary": {"headline": "An unused tool is gone", "story": "The job was to remove a script nothing called. I deleted it and its test. The whole suite still passes.",
                         "items": [{"title": "Delete tools/old_thing.py", "done": True, "what_i_did": "removed the file and its test", "how_checked": "suite green"}],
                         "worries": []}}
    f = wr.memo_fields(facts)
    assert f["role"] == "work-runner" and f["verdict"] == "merged" and f["headline"] == "An unused tool is gone"
    assert f["eli5"]["what"].startswith("Last night the runner picked up work order #9") and "git revert -m 1 abc1234" in f["eli5"]["do"]
    assert f["undo"] == "git revert -m 1 abc1234def" and f["items"][0]["done"] is True
    stopped = wr.memo_fields({**facts, "merged": False, "sha": None, "summary": None, "problems": ["the test suite failed in the worktree: 1 failed"]})
    assert stopped["verdict"] == "stopped" and "stopped short" in stopped["headline"] and stopped["undo"] is None
