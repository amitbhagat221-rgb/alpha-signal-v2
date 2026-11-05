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
    # the attempt cap: two charged failures and it is done trying; the runner's own faults are free; a reset starts again
    for i in (1, 2):
        org.work_status(b["number"], "in_progress", f"[runner] started attempt {i} at t")
        org.work_status(b["number"], "blocked", "[runner] not charged, the runner's own problem: no login")
    w = org.work_order(b["number"])
    assert wr.attempts(w) == 0 and wr.refusal(w) is None
    for i in (1, 2):
        org.work_status(b["number"], "in_progress", f"[runner] started attempt {i} at t")
        org.work_status(b["number"], "blocked", f"[runner] attempt {i} failed: 1 test(s) fail")
    w = org.work_order(b["number"])
    assert wr.attempts(w) == 2 and "already tried" in (wr.refusal(w) or "")
    w = wr.reset(b["number"])
    assert wr.attempts(w) == 0 and wr.refusal(w) is None
    # a run that died mid-way may be picked up again
    org.work_status(b["number"], "in_progress", "[runner] started attempt 1 at t")
    assert wr.refusal(org.work_order(b["number"])) is None
    # free faults are still capped
    for i in range(wr.MAX_STARTS):
        org.work_status(b["number"], "in_progress", f"[runner] started attempt 1 at t{i}")
    assert "needs a look" in wr.refusal(org.work_order(b["number"]))


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
    assert f["eli5"]["what"].startswith("The runner picked up work order #9") and "git revert -m 1 abc1234" in f["eli5"]["do"]
    assert f["undo"] == "git revert -m 1 abc1234def" and f["items"][0]["done"] is True
    stopped = wr.memo_fields({**facts, "merged": False, "sha": None, "summary": None, "problems": ["the test suite failed in the worktree: 1 failed"]})
    assert stopped["verdict"] == "stopped" and "stopped short" in stopped["headline"] and stopped["undo"] is None


def test_the_suite_gate_counts_only_failures_a_clean_copy_does_not_have():
    text = """..F
FAILED tests/test_a.py::test_one - sqlite3.OperationalError: no such table
ERROR tests/test_b.py::test_two[x y] - boom
FAILED tests/test_c.py::test_three
2 failed, 10 passed, 1 error in 3.00s"""
    failed, tail, ran = wr.parse_suite(text)
    assert failed == {"tests/test_a.py::test_one", "tests/test_b.py::test_two[x", "tests/test_c.py::test_three"} and ran
    assert not wr.parse_suite("collecting ... crashed")[2]
    base = {"failed": {"tests/test_a.py::test_one"}}
    assert wr.new_failures({"failed": failed}, base) == ["tests/test_b.py::test_two[x", "tests/test_c.py::test_three"]
    assert wr.new_failures({"failed": {"tests/test_a.py::test_one"}}, base) == []


def test_a_stray_database_is_removed_only_inside_a_worktree(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "WORKTREES", tmp_path / "wt")
    inside = tmp_path / "wt" / "wo-3" / "data"
    outside = tmp_path / "elsewhere" / "data"
    for d in (inside, outside):
        d.mkdir(parents=True)
        (d / "alpha_signal.db").write_text("")
    wr._clear_stray_data(inside.parent)
    wr._clear_stray_data(outside.parent)
    assert not inside.exists() and outside.exists()


def test_orders_that_need_data_or_only_change_the_ranking_stay_with_a_session(q):  # noqa: F811
    data = org.save_work_order("dq-auditor", None, {"title": "Faults", "summary": "x", "items": [ITEM], "tier": "B"})
    org.decide(org.work_order_doc_id(data), "approve")
    assert "live database" in wr.refusal(org.work_order(data))
    owner = _order(q, items=[{**ITEM, "owner": "data-engineer"}], title="Backfill")
    org.decide(org.work_order_doc_id(owner["number"]), "approve")
    assert "live database" in wr.refusal(org.work_order(owner["number"]))
    pick = {**ITEM, "where": "signals/sector_tilt.py", "title": "Fold it"}
    only = _order(q, items=[pick], title="Ranking")
    org.decide(org.work_order_doc_id(only["number"]), "approve")
    assert "ranking" in wr.refusal(org.work_order(only["number"]))
    mixed = _order(q, items=[pick, ITEM], title="Mixed")
    org.decide(org.work_order_doc_id(mixed["number"]), "approve")
    m = org.work_order(mixed["number"])
    assert wr.refusal(m) is None and "Fold it" in wr.prompt_for(m).split("Rules that are enforced")[0].split("Leave these items")[1]
    assert any("ranking" in p for p in wr.scope_problems([(" M", "signals/sector_tilt.py")], m))


def test_memos_say_whose_fault_it_was_and_when_a_branch_is_only_ready():
    facts = {"order": 9, "title": "T", "started_at": "2026-11-05T21:31:00", "items": ["a"], "merged": False, "sha": None, "branch": "wo-9",
             "changed": ["tools/x.py"], "lines": 5, "suite": None, "problems": ["the merge did not apply: x"], "summary": None, "dry": False,
             "runner_fault": True, "attempt": 1}
    assert "not charged" in wr.memo_fields(facts)["eli5"]["do"]
    ready = wr.memo_fields({**facts, "problems": [], "runner_fault": False, "ready": True})
    assert ready["verdict"] == "ready" and "not merged" in ready["headline"]
