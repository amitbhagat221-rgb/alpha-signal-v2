"""
The agent org (plan 0019) on a fresh schema-built DB: the role registry is
consistent with its charters, agent files and cron job; a desk kind is visible
only to its own role; the validator rejects invented ids, numbers and links;
ingest stores the memo with its asks and hypothesis cards; the CEO's decision
clears the inbox; rollback removes everything an ingest wrote.
"""
import datetime as dt
import re

import pytest

import db
import org

FACTS = {"summary": {"critical": 2, "warn": 14}, "issues": [{"issue_id": "I1", "code": "STEP_FAILED"}],
         "tables": {"stale": [["bulk_deals", 22, 3]]}, "weight": 0.1153, "as_of": "2026-10-02T06:30:00"}
SETS = {"issues": ["I1"], "owners": ["data-engineer", "backend-engineer", "ceo"]}


EL = {"what": "One data source stopped sending rows.", "why": "A few signals are working from old numbers.",
      "do": "Nothing today. The engineer switches to the backup source.", "remember": "One cause, not many."}


def _triage(**over):
    memo = {"headline": "Two critical issues, one root cause", "verdict": "red", "eli5": EL,
            "incidents": [{"issue_id": "I1", "assessment": "real", "likely_cause": "bulk_deals source returned no rows",
                           "proposed_fix": "switch to the fallback route", "fix_type": "source-swap",
                           "owner": "data-engineer", "confidence": "medium"}],
            "top_action": "Repair the bulk deals feed",
            "asks": [{"ask": "Approve pausing the feed until fixed", "recommendation": "approve", "urgency": "now"}]}
    return {**memo, **over}


@pytest.fixture
def q(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "org.db")
    monkeypatch.setattr(org, "LOG", tmp_path / "org_worker.log")     # rejected-memo notes stay out of output/
    (tmp_path / "house-style.md").write_text(org.HOUSE_STYLE.read_text())
    monkeypatch.setattr(org, "HOUSE_STYLE", tmp_path / "house-style.md")
    # seat prompts are files the settings editor rewrites: tests work on copies
    import shutil
    for name, src in (("CHARTERS", org.CHARTERS), ("AGENTS", org.AGENTS)):
        shutil.copytree(src, tmp_path / name)
        monkeypatch.setattr(org, name, tmp_path / name)
    org._settings_cache["v"] = None
    db.init_db()
    from alpha_mcp import tasks
    return tasks


def _queue(tasks, kind="org_data_triage", role="data-engineer", key="2026-10-02", **extra):
    payload = {"role": role, "key": key, "period": key, "as_of": "2026-10-02", **extra, "facts": FACTS, "_sets": SETS}
    tasks.enqueue(kind, items=[(key, payload, 4)])
    return tasks.claim(kind, worker=role)[0]["task_id"]


# ── registry ──

def test_registry_is_consistent():
    from alpha_mcp import tasks
    assert set(org.RUN_ORDER) == {r for r, s in org.ROLES.items() if s["type"] == "desk"}
    for rid, s in org.ROLES.items():
        assert s["reports_to"] in org.ROLES or rid == "ceo", rid
        if s["type"] == "desk":
            assert (org.CHARTERS / f"{rid}.md").exists(), f"no charter for {rid}"
            assert s["kinds"] and all(tasks.TASK_KINDS[k]["role"] == rid for k in s["kinds"]), rid
            assert s["cadence"] == "daily" or s["cadence"].split(":")[1] in org.DOW
        if s["type"] == "builder" or s.get("agent"):
            assert (org.ROOT / ".claude" / "agents" / f"{rid}.md").exists(), f"no agent file for {rid}"
        if rid != "ceo":
            assert s["graded_by"] in org.ROLES and s["graded_by"] != rid
            assert s["gate"] and s["measures"] and s["deliverable"]
    # every org kind belongs to exactly one desk role
    org_kinds = {k for k, s in tasks.TASK_KINDS.items() if s.get("role")}
    assert org_kinds == {k for s in org.ROLES.values() for k in s.get("kinds", [])}


def test_doer_before_grader_before_pack():
    o = org.RUN_ORDER
    assert o[-1] == "chief-of-staff" and o[-2] == "compliance"
    # the grader is never in the reporting line of what it grades
    for rid, s in org.ROLES.items():
        boss = s.get("reports_to")
        while boss:
            assert boss != "compliance" or rid == "compliance", f"{rid} reports into its grader"
            boss = org.ROLES[boss].get("reports_to")


def test_org_job_is_wired_through_run_sh():
    run_sh = (org.ROOT / "run.sh").read_text()
    assert re.search(r"^\s{4}org\)", run_sh, re.M), "run.sh has no `org` job"
    assert "run.sh org " in (org.ROOT / "ops" / "crontab.txt").read_text()


def test_cadence(q):
    sunday, friday = dt.date(2026, 10, 4), dt.date(2026, 10, 2)
    assert org.is_due("risk-officer", friday) and org.is_due("cio", sunday) and not org.is_due("cio", friday)
    assert org.period_key("risk-officer", friday) == "2026-10-02"
    assert org.period_key("cio", friday) == org.period_key("cio", sunday) == "2026-W40"


# ── role isolation on the queue ──

def test_a_kind_is_visible_only_to_its_role(q):
    assert not any(k.startswith("org_") for k in q.kinds_for("llm-worker"))
    assert q.kinds_for("cio") == ["org_cio_review", "org_cio_outlook"]
    assert list(q.kinds_spec("data-engineer")["kinds"]) == ["org_data_triage"]
    _queue(q)                                               # one claimed triage task
    q.enqueue("org_data_triage", items=[("k2", {"role": "data-engineer", "key": "k2", "facts": {}, "_sets": {}}, 4)])
    assert q.claimable_count() == 0                         # the pipeline worker's count ignores org kinds
    assert q.claimable_count(["org_data_triage"]) == 1
    with pytest.raises(ValueError, match="not claimable"):
        q.claim("org_data_triage", worker="llm-worker")
    with pytest.raises(ValueError, match="not claimable"):
        q.claim("regulatory", worker="cio")


# ── validation ──

def test_validator_rejects_invented_ids_numbers_and_links(q):
    v = q.TASK_KINDS["org_data_triage"]["validate"]
    payload = {"facts": FACTS, "_sets": SETS}
    assert v(_triage(), payload)["verdict"] == "red"
    bad_id = _triage()
    bad_id["incidents"][0]["issue_id"] = "I9"
    with pytest.raises(ValueError, match="not one of the issues"):
        v(bad_id, payload)
    with pytest.raises(ValueError, match="must be one of"):
        v(_triage(verdict="purple"), payload)
    with pytest.raises(ValueError, match="not in the facts"):
        v(_triage(top_action="Backfill the 437 missing rows"), payload)
    with pytest.raises(ValueError, match="link outside evidence"):
        v(_triage(top_action="See https://example.com for the fix"), payload)
    with pytest.raises(ValueError, match="is required"):
        v({k: x for k, x in _triage().items() if k != "top_action"}, payload)
    # grounded numbers pass: exact, a rounding, a fraction quoted as a percent, a date, small counts
    ok = _triage(top_action="bulk_deals is 22 days stale against a threshold of 3; weight 11.5% as of 2026-10-02 06:30")
    assert v(ok, payload)
    # a unit makes even a small number a figure: it must be in the facts
    with pytest.raises(ValueError, match="not in the facts"):
        v(_triage(top_action="Expect a 25% drop in coverage"), payload)
    assert v(_triage(top_action="Recheck in 30 days, then again in 90"), payload)
    assert v(_triage(top_action="Move the worker to Sonnet 5.5 on Python 3.12"), payload)      # versions are names


def test_evidence_must_cite_the_brief_or_a_tool_the_seat_called(q):
    v = q.TASK_KINDS["org_data_triage"]["validate"]
    payload = {"role": "data-engineer", "facts": FACTS, "_sets": SETS}
    cite = lambda tool, **kw: _triage(evidence=[{"tool": tool, "quote": "age_days 437", **kw}])   # noqa: E731
    assert v(cite("facts.tables"), payload)["evidence"][0]["quote"] == "age_days 437"   # numbers in evidence are free
    with pytest.raises(ValueError, match="did not call"):
        v(cite("alpha-ops.freshness"), payload)
    with db.get_db() as c:                                  # the audit log is the witness
        c.execute("INSERT INTO mcp_calls (ts, profile, role, tool) VALUES (?, 'ops', 'data-engineer', 'freshness')",
                  (dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),))
    assert v(cite("alpha-ops.freshness"), payload)
    assert v(cite("mcp__alpha-ops__freshness"), payload)
    with pytest.raises(ValueError, match="did not call"):   # another seat's call does not count
        v(cite("alpha-ops.freshness"), {**payload, "role": "cto"})
    with pytest.raises(ValueError, match="needs a url"):
        v(cite("WebSearch"), payload)
    assert v(cite("WebSearch", url="https://example.com/a"), payload)


def test_invalid_memo_is_returned_with_reasons_and_writes_nothing(q):
    tid = _queue(q)
    out = q.submit([{"task_id": tid, "result": _triage(top_action="Backfill 437 rows")}], worker="data-engineer")
    assert out["counts"] == {"invalid": 1} and "437" in out["results"][0]["reasons"][0]
    assert org.docs(days=None) == []
    # a desk seat keeps its lease on a rejected memo: it fixes and resubmits the same task_id
    assert "resubmit" in out["results"][0]
    assert q.submit([{"task_id": tid, "result": _triage()}], worker="llm-worker")["counts"] == {"rejected": 1}
    assert q.submit([{"task_id": tid, "result": _triage()}], worker="data-engineer")["counts"] == {"done": 1}


def test_a_desk_memo_fails_after_five_rejections(q):
    tid = _queue(q)
    bad = [{"task_id": tid, "result": _triage(top_action="Backfill 437 rows")}]
    statuses = [q.submit(bad, worker="data-engineer")["results"][0]["status"] for _ in range(5)]
    assert statuses == ["invalid"] * 4 + ["failed"]
    assert q.submit([{"task_id": tid, "result": _triage()}], worker="data-engineer")["counts"] == {"rejected": 1}


# ── ingest, inbox, decision, rollback ──

def test_memo_ingest_inbox_decide_and_rollback(q):
    tid = _queue(q)
    memo = _triage(hypotheses=[])
    out = q.submit([{"task_id": tid, "result": memo}], worker="data-engineer")
    assert out["counts"] == {"done": 1}
    memos = org.docs(["data_triage"])
    assert len(memos) == 1 and memos[0]["title"] == memo["headline"] and memos[0]["fields"]["role"] == "data-engineer"
    box = org.inbox()
    assert [i["type"] for i in box] == ["ask"] and box[0]["parent_doc_id"] == memos[0]["doc_id"]
    assert box[0]["fields"]["urgency"] == "now" and box[0]["fields"]["role"] == "data-engineer"
    # the ledger and the audit attribute the work to the role
    assert db.one("SELECT step, n_calls FROM llm_usage") == {"step": "org:data-engineer", "n_calls": 1}
    assert db.scalar("SELECT claimed_by FROM llm_tasks WHERE task_id = ?", [tid]) == "data-engineer"
    # the CEO decides: the item leaves the inbox; deciding again supersedes
    d = org.decide(box[0]["doc_id"], "park", "after the backfill")
    assert org.inbox() == []
    org.decide(box[0]["doc_id"], "approve")
    assert [x["fields"]["verdict"] for x in org.docs(["decision"])] == ["approve"]
    with pytest.raises(ValueError):
        org.decide(memos[0]["doc_id"], "approve")           # a memo is not an inbox item
    assert d["verdict"] == "park"
    # rollback removes the memo, its ask and the decision on it
    since = (dt.datetime.utcnow() - dt.timedelta(minutes=5)).isoformat(timespec="seconds")
    assert q.rollback("org_data_triage", since)["rolled_back"] == 1
    assert org.docs(days=None) == [] and org.inbox() == []


def test_grade_attaches_to_the_memo_and_feeds_the_scorecard(q):
    tid = _queue(q)
    q.submit([{"task_id": tid, "result": _triage()}], worker="data-engineer")
    memo = org.docs(["data_triage"])[0]
    from alpha_mcp import org_kinds
    items = org_kinds.build("org_grade", dt.date.today(), "x")
    assert [i[0] for i in items] == [f"doc{memo['doc_id']}"]
    assert items[0][1]["facts"]["brief_the_author_was_given"] == FACTS
    q.enqueue("org_grade", items=items)
    gid = q.claim("org_grade", worker="compliance")[0]["task_id"]
    grade = {"grounded": 2, "actionable": 1, "in_charter": 2, "calibrated": 2, "verdict": "good",
             "issues": ["'one root cause' is asserted, the brief lists 2 critical issues"]}
    assert q.submit([{"task_id": gid, "result": grade}], worker="compliance")["counts"] == {"done": 1}
    g = org.docs(["grade"])[0]
    assert g["parent_doc_id"] == memo["doc_id"] and g["fields"]["total"] == 7
    assert org_kinds.build("org_grade", dt.date.today(), "x") == []            # graded once
    card = org.scorecard()
    assert card["data-engineer"]["grade"] == 7.0 and card["data-engineer"]["done"] == 1
    assert card["data-engineer"]["first_pass"] == 1.0
    ov = org.overview()
    assert ov["memos"][0]["grade"]["total"] == 7 and len(ov["inbox"]) == 1
    assert next(r for r in ov["roles"] if r["id"] == "data-engineer")["latest"]["headline"] == memo["title"]


def test_scheduled_period_is_queued_once_and_adhoc_leaves_it_free(q, monkeypatch):
    from alpha_mcp import org_kinds
    calls = []

    def fake_build(kind, day, key):
        calls.append(key)
        return [(key, {"role": "risk-officer", "key": key, "facts": {"n": len(calls)}, "_sets": {}}, 4)]
    monkeypatch.setattr(org_kinds, "build", fake_build)
    day = dt.date(2026, 10, 2)
    assert org.enqueue_role("risk-officer", day) == 1
    assert org.enqueue_role("risk-officer", day) == 0 and calls == ["2026-10-02"]      # not rebuilt
    assert org.enqueue_role("risk-officer", day, adhoc=True) == 1 and calls[-1].startswith("adhoc-")
    assert org.enqueue_role("risk-officer", dt.date(2026, 10, 3)) == 1


def test_desk_cards_go_through_the_cio_before_the_ceo(q):
    """A sector-desk card waits in the CIO's queue; only a forwarded card reaches the inbox."""
    facts = {"sector": "Energy"}
    q.enqueue("org_sector_view", items=[("w:Energy", {"role": "sector-desk", "key": "w:Energy", "sector": "Energy",
                                                        "facts": facts, "_sets": {"tickers": [], "universe": ["BPCL"]}}, 5)])
    tid = q.claim("org_sector_view", worker="sector-desk")[0]["task_id"]
    view = {"headline": "Energy: mixed", "eli5": EL, "view": "neutral", "confidence": "low", "thesis": "Inputs disagree.",
            "drivers": ["refining margins"], "risks": ["tariffs"],
            "ideas": [{"ticker": "BPCL", "stance": "avoid", "reason": "Margins are peaking.", "risk": "Crude falls",
                       "horizon": "3-6 months", "conviction": "low"}],
            "hypotheses": [{"title": "Windfall tax cuts lift refiners", "rationale": "margin pass-through",
                            "test": "event study around the notifications"}]}
    with db.get_db() as c:
        c.execute("INSERT INTO mcp_calls (ts, profile, role, tool) VALUES (?, 'research', 'sector-desk', 'stock')",
                  (dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),))
    assert q.submit([{"task_id": tid, "result": view}], worker="sector-desk")["counts"] == {"done": 1}
    card = org.card_queue()
    assert len(card) == 1 and org.inbox() == []
    from alpha_mcp import org_kinds
    sets = {"factors": ["f1"], "tiers": ["LARGE"], "cards": [card[0]["doc_id"]]}
    q.enqueue("org_cio_review", items=[("w", {"role": "cio", "key": "w", "facts": {}, "_sets": sets}, 4)])
    cid = q.claim("org_cio_review", worker="cio")[0]["task_id"]
    review = {"headline": "Hold", "eli5": EL, "stance": "Nothing changed.", "factor_calls": [],
              "card_triage": [{"item_id": card[0]["doc_id"], "call": "forward", "why": "testable on event data"}]}
    bad = {**review, "card_triage": [{"item_id": 999999, "call": "forward", "why": "x"}]}
    assert q.submit([{"task_id": cid, "result": bad}], worker="cio")["counts"] == {"invalid": 1}
    cid = q.claim("org_cio_review", worker="cio")[0]["task_id"]
    assert q.submit([{"task_id": cid, "result": review}], worker="cio")["counts"] == {"done": 1}
    assert org.card_queue() == [] and [i["doc_id"] for i in org.inbox()] == [card[0]["doc_id"]]
    assert org_kinds.build  # (the CIO's own cards skip the queue: the CIO reports to the CEO)


# ── seat settings: what the CEO may change from the Boardroom ──

def test_ceo_changes_a_seats_variables(q):
    friday = dt.date(2026, 10, 2)
    assert org.seat("cio")["model"] == "opus" and not org.is_due("cio", friday)
    v = org.save_settings("cio", {"model": "sonnet", "cadence": "daily", "effort": "medium", "max_submits": 5,
                                  "directive": "This month, look hardest at the LARGE tier."}, note="cheaper")
    assert v["vars"]["model"] == "sonnet" and set(v["edited"]) == {"model", "cadence", "effort", "max_submits",
                                                                  "directive"}
    assert org.seat("cio")["model"] == "sonnet" and org.is_due("cio", friday) and org.period_key("cio", friday) == "2026-10-02"
    # the directive reaches the worker; the fixed rules still follow whatever the prompt says
    text = q.kinds_spec("cio")["kinds"]["org_cio_review"]["instructions"]
    assert "Standing directive from the CEO" in text and "look hardest at the LARGE tier" in text
    assert "Rules for every memo" in text
    # switched off: not due, and --all would skip it
    org.save_settings("cio", {"enabled": False})
    assert not org.is_due("cio", friday) and org.seat("cio")["enabled"] is False
    # back to the registry value = no longer an edit
    v = org.save_settings("cio", {"model": "opus", "enabled": True})
    assert "model" not in v["edited"] and "enabled" not in v["edited"] and org.seat("cio")["model"] == "opus"
    for bad in ({"model": "gpt-4"}, {"cadence": "hourly"}, {"max_submits": 500}, {"enabled": "yes"},
                {"kinds": ["regulatory"]}, {"gate": "none"}, {"directive": "x" * 5000}):
        with pytest.raises(ValueError):
            org.save_settings("cio", bad)
    with pytest.raises(ValueError):
        org.save_settings("ceo", {"model": "opus"})


def test_ceo_edits_a_prompt_with_history_reset_and_restore(q):
    original = org.charter("risk-officer")
    v1 = org.save_settings("risk-officer", {"prompt": original + "\nAlways name the single largest risk first."})
    assert "single largest risk first" in org.charter("risk-officer") and v1["edited"] == ["prompt"]
    assert v1["version"] != org.save_settings("risk-officer", {"model": "haiku"})["version"]    # version tracks changes
    assert org.seat("risk-officer")["model"] == "haiku"
    hist = org.seat_settings("risk-officer")["history"]
    assert len(hist) == 2 and hist[0]["current"] and not hist[1]["current"]
    # restore the first saved version: its prompt, and the model it had then (sonnet)
    org.restore_settings("risk-officer", hist[1]["doc_id"])
    assert org.seat("risk-officer")["model"] == "sonnet" and "single largest risk first" in org.charter("risk-officer")
    # reset: the charter as it was before the first edit, no overrides
    v = org.reset_settings("risk-officer")
    assert org.charter("risk-officer").strip() == original.strip() and v["edited"] == []
    with pytest.raises(ValueError):
        org.save_settings("risk-officer", {"prompt": "   "})
    with pytest.raises(ValueError):
        org.save_settings("risk-officer", {"agent_prompt": "a desk-only seat has no agent file"})


def test_builder_prompt_and_model_live_in_the_agent_file(q):
    head = org._agent_parts("quant-researcher")[0]
    assert org.seat("quant-researcher")["model"] == "sonnet"
    org.save_settings("quant-researcher", {"model": "opus"})
    assert org.seat("quant-researcher")["model"] == "opus"
    assert org._agent_parts("quant-researcher")[0] == head.replace("model: sonnet", "model: opus")
    body = org.prompts("quant-researcher")["agent_prompt"]
    org.save_settings("quant-researcher", {"agent_prompt": body + "\nReport the turnover of the factor too."})
    text = (org.AGENTS / "quant-researcher.md").read_text()
    assert text.startswith("---\nname: quant-researcher\n") and "model: opus" in text
    assert text.rstrip().endswith("Report the turnover of the factor too.")
    v = org.reset_settings("quant-researcher")
    assert v["vars"] == {"model": "sonnet"} and org.prompts("quant-researcher")["agent_prompt"].strip() == body.strip()
    # the data engineer has both: a desk charter and a fix-mode agent file
    assert set(org.prompts("data-engineer")) == {"prompt", "agent_prompt"}
    with pytest.raises(ValueError):
        org.save_settings("quant-researcher", {"cadence": "daily"})         # builders have no schedule


def test_memo_is_stamped_with_the_prompt_version(q):
    tid = _queue(q)
    q.submit([{"task_id": tid, "result": _triage()}], worker="data-engineer")
    assert org.docs(["data_triage"])[0]["fields"]["prompt_version"] == org.prompt_version("data-engineer")


def test_boardroom_api_saves_resets_and_refuses_bad_settings(q, monkeypatch):
    """The ops cockpit's seat endpoints (called directly: no login round-trip needed here)."""
    import asyncio
    import json
    import cockpit_ops.app as A

    class Req:
        def __init__(self, body):
            self.body = body

        async def json(self):
            return self.body

    seat = A.api_org_seat("cio")
    assert seat["vars"]["model"] == "opus" and "prompt" in seat["prompts"] and seat["fixed"]["gate"]
    assert A.api_org_seat("nobody").status_code == 404
    out = asyncio.run(A.api_org_seat_save("cio", Req({"changes": {"model": "sonnet", "directive": "Be brief."},
                                                      "note": "test"})))
    assert out["vars"]["model"] == "sonnet" and out["history"][0]["note"] == "test"
    bad = asyncio.run(A.api_org_seat_save("cio", Req({"changes": {"kinds": ["dossier"]}})))
    assert bad.status_code == 400 and "not a setting" in json.loads(bad.body)["error"]
    assert A.api_org_seat_reset("cio")["edited"] == []
    # Run now: refused for a builder, and while another run holds the lock
    assert A.api.org_run("quant-researcher")["ok"] is False
    monkeypatch.setattr(A.api, "org_running", lambda: True)
    assert "already in progress" in A.api.org_run("cio")["error"]


def test_desk_ideas_get_the_models_numbers_and_a_cio_second_pass(q, monkeypatch):
    """An idea must be a stock the model ranks in that sector; the server attaches the model's
    numbers; it reaches the CEO's conviction list only through the CIO's review."""
    from alpha_mcp import org_kinds
    monkeypatch.setattr(org_kinds, "_model_rows", lambda: {
        "BPCL": {"sid": "BPCL", "name": "BPCL Ltd", "sector": "Energy", "tier": "LARGE", "rank": 4, "score": 0.74,
                 "data_coverage": 0.91, "published": True}})
    q.enqueue("org_sector_view", items=[("w:Energy", {"role": "sector-desk", "key": "w:Energy", "sector": "Energy",
                                                        "facts": {"sector": "Energy"},
                                                        "_sets": {"tickers": [], "universe": ["BPCL", "ONGC"]}}, 5)])
    tid = q.claim("org_sector_view", worker="sector-desk")[0]["task_id"]
    idea = {"ticker": "BPCL", "stance": "buy", "reason": "Windfall tax cut lifts refining margins.",
            "risk": "Crude spikes", "horizon": "3-6 months", "conviction": "medium"}
    view = {"headline": "Energy: mixed", "eli5": EL, "view": "neutral", "confidence": "low", "thesis": "Inputs disagree.",
            "drivers": ["refining margins"], "risks": ["tariffs"], "ideas": [idea]}
    # no stock looked up in this run → the memo is refused, whatever it says
    out = q.submit([{"task_id": tid, "result": view}], worker="sector-desk")
    assert out["counts"] == {"invalid": 1} and "needs research" in out["results"][0]["reasons"][0]
    with db.get_db() as c:
        c.execute("INSERT INTO mcp_calls (ts, profile, role, tool) VALUES (?, 'research', 'sector-desk', 'stock')",
                  (dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),))
    tid = q.claim("org_sector_view", worker="sector-desk")[0]["task_id"]
    bad = {**view, "ideas": [{**idea, "ticker": "TSLA"}]}
    assert q.submit([{"task_id": tid, "result": bad}], worker="sector-desk")["counts"] == {"invalid": 1}
    tid = q.claim("org_sector_view", worker="sector-desk")[0]["task_id"]
    assert q.submit([{"task_id": tid, "result": view}], worker="sector-desk")["counts"] == {"done": 1}
    queue = org.idea_queue()
    assert len(queue) == 1 and queue[0]["fields"]["model"] == {"name": "BPCL Ltd", "tier": "LARGE", "rank": 4,
                                                              "score": 0.74, "data_coverage": 0.91, "published": True}
    assert org.ideas()["pending"][0]["ticker"] == "BPCL" and org.inbox() == []
    sets = {"sectors": ["Energy"], "ideas": [queue[0]["doc_id"]]}
    q.enqueue("org_cio_outlook", items=[("w", {"role": "cio", "key": "w", "facts": {}, "_sets": sets}, 4)])
    cid = q.claim("org_cio_outlook", worker="cio")[0]["task_id"]
    outlook = {"headline": "Cautious", "eli5": EL, "macro": "Growth holds, foreign money is leaving.",
               "market": {"stance": "cautious", "horizon": "3-6 months", "view": "Foreign selling dominates."},
               "be_careful": ["Further foreign selling"],
               "sectors": [{"sector": "Energy", "call": "pursue", "reason": "Refining margins"},
                           {"sector": "Energy", "call": "hold", "reason": "x"}, {"sector": "Energy", "call": "avoid", "reason": "y"}],
               "idea_review": [{"item_id": queue[0]["doc_id"], "call": "conviction", "why": "Published pick, clear catalyst."}]}
    assert q.submit([{"task_id": cid, "result": outlook}], worker="cio")["counts"] == {"done": 1}
    got = org.ideas()
    assert org.idea_queue() == [] and got["pending"] == []
    assert got["conviction"][0]["ticker"] == "BPCL" and got["conviction"][0]["cio_why"].startswith("Published pick")
    assert org.overview()["outlook"]["fields"]["market"]["stance"] == "cautious"


# ── work orders: chat → inbox → a Claude Code session ──

def test_work_order_waits_for_approval_then_tracks_progress(q):
    import org_chat
    wo = {"title": "Fix the market cap unit", "summary": "The field holds rupees but is named crore.",
          "items": [{"title": "Convert at the source", "what": "Divide by 1e7 where the view is built.",
                     "done_when": "POWERINDIA shows about 112963 crore", "owner": "backend-engineer", "size": "M"}],
          "open_questions": ["Convert or rename?"]}
    org_chat._save("backend-engineer", "c1", "ceo", "The market cap unit is wrong, **fix it**.")
    org_chat._save("backend-engineer", "c1", "seat", "Agreed. Press Make work order.", session_id="s1")
    n = org.save_work_order("backend-engineer", "c1", wo)
    assert n == 1 and org.save_work_order("backend-engineer", "c1", {**wo, "title": "Second"}) == 2
    w = org.work_order(1)
    assert w["status"] == "awaiting approval" and w["items"][0]["owner"] == "backend-engineer"
    # it is in the CEO inbox, and a session cannot start it before he approves
    box = [i for i in org.inbox() if i["type"] == "work_order"]
    assert [i["fields"]["number"] for i in box] == [1, 2]
    with pytest.raises(ValueError, match="approves it"):
        org.work_status(1, "in_progress")
    org.decide(w["doc_id"], "approve")
    assert org.work_order(1)["status"] == "approved" and len([i for i in org.inbox() if i["type"] == "work_order"]) == 1
    assert org.work_status(1, "in_progress")["status"] == "in_progress"
    done = org.work_status(1, "done", "item 1: converted, 335 tests pass")
    assert done["status"] == "done" and done["note"].startswith("item 1")
    with pytest.raises(ValueError):
        org.work_status(1, "merged")
    # rejected work orders cannot be run; cancelling is always allowed
    org.decide(org.work_order(2)["doc_id"], "reject")
    with pytest.raises(ValueError):
        org.work_status(2, "in_progress")
    assert org.work_status(2, "cancelled")["status"] == "cancelled"
    # the session reads the order together with the chat it came from
    assert [m["who"] for m in org_chat.transcript("backend-engineer", "c1")] == ["ceo", "seat"]
    assert org_chat.chats()["backend-engineer"]["preview"] == "Agreed. Press Make work order."
    assert org_chat.chats()["backend-engineer"]["n"] == 2 and org.overview()["work_orders"][0]["number"] == 2


def test_chat_cannot_write_and_tells_the_seat_how_to_draw(q):
    import json
    import org_chat
    cfg = json.loads(org_chat._mcp_config("cio"))["mcpServers"]
    assert set(cfg) == {"alpha-research", "alpha-ops"}                 # no alpha-work: a chat has no write path
    p = org_chat.system_prompt("cio")
    assert "`chart`" in p and "`mermaid`" in p and "Make work order" in p and "cannot change anything" in p
    with pytest.raises(ValueError):
        org_chat.make_work_order("cio")                                 # nothing to write from an empty chat
    with pytest.raises(ValueError):
        org_chat.history("ceo")


def test_boardroom_app_files_are_complete():
    """The installable app: a valid manifest whose icons exist, a service worker that never
    caches pages or API data, and the page head that links them."""
    import json
    static = org.ROOT / "cockpit" / "static" / "boardroom"
    m = json.loads((static / "manifest.webmanifest").read_text())
    assert m["display"] == "standalone" and m["start_url"] == "/org" and m["scope"] == "/"
    sizes = set()
    for icon in m["icons"]:
        assert (org.ROOT / "cockpit" / icon["src"].lstrip("/")).exists(), icon["src"]
        sizes.add(icon["sizes"])
    assert {"192x192", "512x512"} <= sizes and any(i.get("purpose") == "maskable" for i in m["icons"])
    sw = (static / "sw.js").read_text()
    assert "startsWith('/api/')" in sw and "offline.html" in sw and (static / "offline.html").exists()
    head = (org.ROOT / "cockpit_ops" / "templates" / "ops_base.html").read_text()
    assert "manifest.webmanifest" in head and "serviceWorker" in head and "isSecureContext" in head
    import cockpit_ops.app as A
    assert A.service_worker().media_type == "application/javascript"


# ── house style: explain it like I'm five ──

def test_every_ceo_facing_memo_needs_a_plain_words_block_and_no_jargon(q):
    from alpha_mcp import org_kinds as K
    v = q.TASK_KINDS["org_data_triage"]["validate"]
    payload = {"facts": FACTS, "_sets": SETS}
    with pytest.raises(ValueError, match="eli5 is required"):
        v({k: x for k, x in _triage().items() if k != "eli5"}, payload)
    # jargon, code names and long sentences are sent back with the plain way to say it
    for bad, why in (({**EL, "why": "The t-stat fell and breadth is thin."}, "jargon 't-stat'"),
                     ({**EL, "what": "The book_to_price weight looks wrong."}, "code name 'book_to_price'"),
                     ({**EL, "do": " ".join(["word"] * 40) + "."}, "sentence too long")):
        with pytest.raises(ValueError, match=why):
            v(_triage(eli5=bad), payload)
    with pytest.raises(ValueError, match="jargon 'FPI'"):
        v(_triage(headline="FPI outflows hit the feed"), payload)
    with pytest.raises(ValueError, match="jargon"):
        v(_triage(asks=[{"ask": "Approve a capex review?", "recommendation": "Yes."}]), payload)
    # the technical detail fields stay free: an engineer may name a step or a factor there
    ok = _triage()
    ok["incidents"][0]["likely_cause"] = "The cron step classify_news hit a traceback in the upsert."
    assert v(ok, payload)
    # every CEO-facing kind carries the block; the grade (read by the scorecard) does not
    with_block = {k for k, x in K.KINDS.items() if "eli5" in x["schema_internal"]["properties"]}
    assert with_block == set(K.KINDS) - {"org_grade"}


def test_house_style_reaches_every_seat_and_the_ceo_can_edit_it(q):
    import org_chat
    assert "explain it like I'm five" in q.kinds_spec("risk-officer")["kinds"]["org_risk_note"]["instructions"]
    assert "explain it like I'm five" in org_chat.system_prompt("cto")
    before = org.prompt_version("cio")
    v = org.save_house_style(org.house_style() + "\nAlways give the comparison.", note="more analogies")
    assert v["edited"] and "Always give the comparison." in q.kinds_spec("cio")["kinds"]["org_cio_outlook"]["instructions"]
    assert org.prompt_version("cio") != before                     # a style change is a new version of every seat
    assert org.save_house_style(v["default"])["edited"] is False
    with pytest.raises(ValueError):
        org.save_house_style("  ")


# ── looking back: memo date filter and chat history ──

def test_memos_can_be_filtered_by_date_and_employee(q):
    with db.get_db() as c:
        for day, role, typ in (("2026-09-01", "cio", "cio_review"), ("2026-09-20", "risk-officer", "risk_note"),
                               ("2026-10-02", "cio", "cio_outlook")):
            org.save_doc(c, typ, f"k-{day}", f"memo {day}", {"role": role, "headline": f"memo {day}"}, doc_date=day)
    assert [m["doc_date"] for m in org.memos("2026-09-01", "2026-09-30")] == ["2026-09-20", "2026-09-01"]
    assert [m["doc_date"] for m in org.memos(since="2026-09-10")] == ["2026-10-02", "2026-09-20"]
    assert [m["title"] for m in org.memos(since="2000-01-01", role="cio")] == ["memo 2026-10-02", "memo 2026-09-01"]
    assert org.memos(until="2026-08-31") == []
    from cockpit_ops import api
    ov = api.get_org_overview("2026-09-01", "2026-09-30", None)
    assert [m["title"] for m in ov["memos"]] == ["memo 2026-09-20", "memo 2026-09-01"] and ov["memo_filter"]["active"]
    assert api.get_org_overview("not-a-date", None, "nobody")["memo_filter"]["active"] is False      # bad input = no filter


def test_chat_history_lists_every_conversation_and_reopens_one(q):
    import org_chat
    org_chat._save("cio", "old1", "ceo", "How is the **market** looking?")
    org_chat._save("cio", "old1", "seat", "Cautious.", session_id="s-old")
    org_chat._save("cto", "c9", "ceo", "Is the platform healthy?")
    org_chat._save("cio", "new2", "ceo", "Which sectors do you like?")
    org_chat._save("cio", "new2", "seat", "Health care.", session_id="s-new", work_order=3)
    convs = org_chat.conversations()
    assert [(c["role"], c["conv"], c["n"]) for c in convs] == [("cio", "new2", 2), ("cto", "c9", 1), ("cio", "old1", 2)]
    assert convs[0]["first"] == "Which sectors do you like?" and convs[0]["work_orders"] == [3]
    assert [c["conv"] for c in org_chat.conversations("cio")] == ["new2", "old1"]
    # the current conversation by default; an earlier one on request, with the session to continue it
    assert org_chat.history("cio")["conv"] == "new2"
    old = org_chat.history("cio", "old1")
    assert [m["who"] for m in old["messages"]] == ["ceo", "seat"] and old["session_id"] == "s-old"
    with pytest.raises(ValueError):
        org_chat.history("cio", "nope")
    with pytest.raises(ValueError):
        org_chat.conversations("ceo")
