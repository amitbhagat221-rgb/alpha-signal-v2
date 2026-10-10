"""Cockpit v2, ops group: five questions once, the real error line, issues grouped by cause, since-yesterday,
flow stages, the Boardroom inbox (board-pack call, per-option decide, settled flags)."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

import webauth
from cockpit_ops import api
from tests.test_org import _queue, _triage, q  # noqa: F401  (fixture + helpers on a throwaway DB)


def _issue(code, target, severity="CRITICAL", theme="ran", detail="", days=1, **kw):
    return {"severity": severity, "theme": theme, "code": code, "id": kw.get("id", f"{code}:{target}"), "target": target,
            "message": kw.get("message", f"{target} problem"), "detail": detail, "why": "because", "fix": kw.get("fix", "Do it, then `x <feed>`."),
            "days": days, "standing": False, "drilldown_url": None, "drilldown_label": None}


# ── the real error line ──

def test_real_error_reads_the_recorded_line_and_falls_back_to_run_events(monkeypatch):
    e = api.real_error("only 9.6 GB free on the DB disk (exit 1; python -m runlog events --run datamodel_sync:T:1)")
    assert e == {"error": "only 9.6 GB free on the DB disk", "rc": 1, "evidence": "python -m runlog events --run datamodel_sync:T:1"}
    import runlog
    monkeypatch.setattr(runlog, "events", lambda **k: [{"event": "run_exit", "message": "exit 1"},
                                                       {"event": "exception", "error_type": "KeyError", "message": "'shareholding_filing'"}])
    old = api.real_error("exit 1 (python -m runlog events --run cron_x:T:2)")
    assert old["error"] == "KeyError: 'shareholding_filing'" and old["rc"] == 1
    monkeypatch.setattr(runlog, "events", lambda **k: [])
    assert api.real_error("exit 1 (python -m runlog events --run cron_x:T:2)")["error"] is None
    assert api.real_error("ContractViolation: boom")["error"] == "ContractViolation: boom"      # a pipeline.py message passes through


def test_pipeline_status_rows_carry_the_error_text(monkeypatch):
    import views
    monkeypatch.setattr(views, "pipeline_status", lambda days: [
        {"step_name": "a", "status": "FAILED", "error_message": "disk full (exit 1; python -m runlog events --run a:T:1)"},
        {"step_name": "b", "status": "SUCCESS", "error_message": None}])
    rows = api.get_pipeline_status()
    assert rows[0]["error_text"] == "disk full" and "error_text" not in rows[1]


# ── grouping and the fix text ──

def test_issues_sharing_a_cause_are_one_group_and_placeholders_are_filled():
    probes = [_issue("FEED_PROBE", f, "WARN", "arrived", "transport: HTTP 500") for f in ("banking_metrics", "screener_fundamentals", "transcripts")]
    spikes = [_issue("FEED_VOLUME", f, "WARN", "arrived", id=f"FEED_VOLUME_SPIKE:{f}:s") for f in ("fno_bhav", "fno_iv")]
    empty = [_issue("TABLE_EMPTY", "_file_dossiers", "CRITICAL", "arrived", message="_file_dossiers is empty")]
    groups = api.group_issues(probes + spikes + empty, backfill={"active": True, "last": "2026-10-10"})
    by = {g["code"]: g for g in groups}
    assert len(groups) == 3 and groups[0]["severity"] == "CRITICAL"                  # worst first
    assert by["FEED_PROBE"]["n"] == 3 and "screener host" in by["FEED_PROBE"]["cause"]
    assert "Expected while the history backfill runs" in by["FEED_VOLUME"]["note"]
    assert "output file dossiers" in by["TABLE_EMPTY"]["title"]
    assert "<" not in by["FEED_PROBE"]["fix"] and "banking_metrics" in by["FEED_PROBE"]["fix"]
    quiet = api.group_issues(spikes, backfill={"active": False, "last": None})
    assert quiet[0]["note"] is None


def test_datamodel_jobs_are_one_group_and_each_member_keeps_its_error():
    a = _issue("PIPELINE_STEP", "datamodel_sync", detail="only 9.6 GB free (exit 1; python -m runlog events --run datamodel_sync:T:1)")
    b = _issue("PIPELINE_STEP", "datamodel_reconcile", detail="exit 1 (python -m runlog events --run datamodel_reconcile:T:2)")
    [g] = api.group_issues([a, b])
    assert g["n"] == 2 and "data-model jobs" in g["title"] and "python -m datamodel.sync" in g["fix"]
    errs = {m["target"]: m["error"] for m in g["members"]}
    assert errs["datamodel_sync"] == "only 9.6 GB free"


def test_a_failed_dag_step_gets_its_exact_rerun_command():
    [g] = api.group_issues([_issue("PIPELINE_STEP", "fetch_prices_fallback", detail="ContractViolation: x")])
    assert "python pipeline.py --step fetch_prices_fallback" in g["fix"] and "<" not in g["fix"]
    [h] = api.group_issues([_issue("PIPELINE_STEP", "datamodel_sync", detail="exit 1")])
    assert "python -m datamodel.sync" in h["fix"]


def test_since_yesterday():
    issues = [_issue("A", "a", id="A:a", days=1), _issue("B", "b", id="B:b", days=3)]
    s = api.since_yesterday(issues, {"day": "2026-10-09", "firing": {"B:b": "WARN", "C:old": "CRITICAL"}})
    assert [x["id"] for x in s["new"]] == ["A:a"] and [x["id"] for x in s["open"]] == ["B:b"]
    assert s["cleared"] == [{"id": "C:old", "label": "old"}]
    assert api.since_yesterday(issues, {"day": None, "firing": {}}) is None


def test_previous_firing_reads_the_last_recorded_day(q):                                # noqa: F811
    from checks import history
    today = dt.date.today()
    with __import__("db").get_db() as conn:
        cid = history._check_id(conn, create=True)
        for day, subj, st in ((today - dt.timedelta(days=2), "OLD", "WARN"), (today - dt.timedelta(days=1), "X:y", "CRITICAL"),
                              (today - dt.timedelta(days=1), "OK:z", "PASS"), (today, "TODAY", "WARN")):
            conn.execute("INSERT INTO check_results(check_id, subject, entity_id, date, status, score, detail, checked_at) "
                         "VALUES (?, ?, 0, ?, ?, 0, '{}', 'now')", [cid, subj, day.isoformat(), st])
        conn.commit()
    assert history.previous_firing() == {"day": (today - dt.timedelta(days=1)).isoformat(), "firing": {"X:y": "CRITICAL"}}


# ── the Health page renders each question once ──

def _overview(groups):
    sc = [{"theme": "ran", "question": "Did everything run?", "status": "BROKEN", "critical": 1, "warn": 0, "facts": "53 of 54", "covers": ""},
          {"theme": "arrived", "question": "Did the data arrive?", "status": "OK", "critical": 0, "warn": 0, "facts": "all fresh", "covers": ""}]
    return {"as_of": "2026-10-10T04:00:00", "verdict": "⚠ 1 CRITICAL", "verdict_severity": "CRITICAL", "scorecard": sc,
            "severity_meaning": {"CRITICAL": "act today", "WARN": "look at", "INFO": "no action"}, "tolerated": [],
            "sections": [{**sc[0], "groups": groups}, {**sc[1], "groups": []}], "issues": [1], "since": None,
            "integrity": {"fails": [], "warns": []}}


def test_health_renders_each_question_once_with_the_real_error():
    from cockpit_ops.app import templates
    [g] = api.group_issues([_issue("PIPELINE_STEP", "fetch_prices_fallback",
                                   detail="ContractViolation: stock_prices write blocked (exit 1; python -m runlog events --run r:1)")])
    html = templates.env.get_template("system.html").render(overview=_overview([g]), page="system")
    assert html.count("Did everything run?") == 1 and html.count("Did the data arrive?") == 1
    assert "ContractViolation: stock_prices write blocked" in html and "python pipeline.py --step fetch_prices_fallback" in html
    assert "<name>" not in html and "all clear" in html


# ── Flow stages ──

def test_every_pipeline_step_sits_in_a_stage():
    from config import PIPELINE_STEPS
    stages = {sid for sid, _, _ in api.STAGES}
    assert [s["name"] for s in PIPELINE_STEPS if api.stage_of(s["name"]) not in stages] == []
    assert set(api.STAGE_OF.values()) <= stages


# ── Boardroom inbox ──

def test_settled_refs_find_a_card_id_in_an_adr_or_a_commit(tmp_path):
    (tmp_path / "0070-x.md").write_text("Settles #768589 by benching.")
    log = "abc1234\x1ffix(model): weights\x1fCloses card 768630.\x1e"
    refs = api._settled_refs([768589, 768630, 111], git_log=log, adr_dir=tmp_path)
    assert refs[768589] == ["ADR 0070"] and refs[768630][0].startswith("commit abc1234") and 111 not in refs


def test_inbox_cards_sort_by_the_board_call_and_carry_options():
    inbox = [{"doc_id": 1, "type": "hypothesis", "age_days": 20, "fields": {}},
             {"doc_id": 2, "type": "ask", "age_days": 2, "fields": {"options": ["Do it now", "Wait"], "recommendation": "Do it now. Cheap."}},
             {"doc_id": 3, "type": "ask", "age_days": 2, "fields": {}}]
    pack = {"fields": {"decisions": [{"item_id": 3, "recommendation": "discuss", "why_now": "w"},
                                     {"item_id": 2, "recommendation": "approve", "why_now": "v"}]}}
    ov = api._inbox_cards({"inbox": inbox, "board_pack": pack})
    assert [i["doc_id"] for i in ov["inbox"]] == [2, 3, 1]
    c = ov["inbox"][0]
    assert c["board"]["recommendation"] == "approve" and [o["recommended"] for o in c["option_list"]] == [True, False]
    assert ov["inbox"][2]["stale"] and not ov["inbox"][0]["stale"]


@pytest.fixture
def ops_client(q, monkeypatch, tmp_path):                                                # noqa: F811
    monkeypatch.delenv("COCKPIT_PREVIEW", raising=False)
    monkeypatch.setattr(webauth, "AUTH_FILE", tmp_path / "auth.json")
    webauth.set_password("correct horse battery")
    from cockpit_ops.app import app
    monkeypatch.setattr(api, "invalidate_org_overview", lambda: None)
    return TestClient(app, cookies={webauth.COOKIE: webauth.make_token()})


def test_decide_endpoint_takes_the_chosen_option(ops_client, q):                          # noqa: F811
    import org
    ask = {"ask": "Which way", "options": ["Bench now", "Wait for the re-test"], "recommendation": "Wait", "urgency": "now"}
    q.submit([{"task_id": _queue(q), "result": _triage(asks=[ask])}], worker="data-engineer")
    item = org.inbox()[0]
    bad = ops_client.post("/api/org/decide", json={"item_id": item["doc_id"], "option": 7})
    assert bad.status_code == 400 and org.inbox()
    ok = ops_client.post("/api/org/decide", json={"item_id": item["doc_id"], "option": 1, "note": "ok"})
    assert ok.status_code == 200 and ok.json()["option"] == "Wait for the re-test"
    f = org.docs(["decision"])[0]["fields"]
    assert f["verdict"] == "approve" and f["option_index"] == 1 and f["note"].startswith("Chose: Wait for the re-test")
    assert org.inbox() == []


def test_inbox_renders_one_button_per_option(q):                                          # noqa: F811
    import org
    from cockpit_ops.app import templates
    ask = {"ask": "Which way", "options": ["Bench now", "Wait for the re-test", "Keep"], "recommendation": "Wait", "urgency": "now"}
    q.submit([{"task_id": _queue(q), "result": _triage(asks=[ask])}], worker="data-engineer")
    ov = api._inbox_cards({"inbox": org.inbox(), "board_pack": None})
    for i in ov["inbox"]:
        i["role_title"] = "Data engineer"
    ctx = {"page": "org", "inbox": ov["inbox"], "board_pack": None, "summary": {"inbox": 1, "agents": 1, "desk": 1, "memos": 0, "avg_grade": None},
           "work_orders": [], "decisions": [], "cio_queue": [], "memos": [], "memo_filter": {"mfrom": "", "mto": "", "mrole": "", "active": False, "capped": False, "quick": [], "first": None},
           "tree": [], "roles": [], "ideas": {}, "outlook": None, "running": False, "mpage": 1, "memo_per_page": 12, "decided": {}}
    html = templates.env.get_template("org.html").render(**ctx)
    assert html.count('data-option="') == 3 and "Choose for " in html and "#' + id" not in html and "decide(" in html


# ── phase 3: every ops page agrees with the one gathered report ──

def _gathered(days_in_history=8):
    from checks import report
    from tests.test_checks import _state
    st = _state(pipeline={"last_run_date": "2026-01-02", "last_run_status": "FAILED", "n_steps": 55,
                          "failed_steps_today": [{"step": "fetch_x", "error": "e", "at": "t"}],
                          "failed_streaks": [{"step": "fetch_x", "days": 4, "sample_error": "e"}]},
                feeds={"rows": [{"feed": "a", "canary_last": {"status": "PASS"}}, {"feed": "b", "canary_last": {"status": "FAIL"}},
                                {"feed": "c", "canary_last": None}], "verdicts": []},
                history={"streaks": {"PIPELINE_STEP:fetch_x": days_in_history}, "last_fired": {}, "since": "2025-12-01"})
    return report.conclude(st)


def test_one_streak_number_for_health_and_flow():
    """Health prints the issue's days; Flow's broken-steps table reads the same number (the detector's own count is not shown)."""
    st = _gathered()
    (issue,) = [i for i in st["issues"] if i["id"] == "PIPELINE_STEP:fetch_x"]
    assert issue["days"] == 9 and st["pipeline"]["failed_streaks"][0]["days"] == issue["days"]
    assert "days in a row" not in issue["message"]


def test_run_line_and_probe_count_are_defined_once():
    from checks import report
    from checks.feeds import probe_tally
    st = _gathered()
    facts = {q["theme"]: q["facts"] for q in st["scorecard"]}
    assert report.run_line(st["pipeline"]) in facts["ran"]
    assert probe_tally(st["feeds"]["rows"]) == (1, 2) and "1 of 2 feed probes pass" in facts["arrived"]


def test_flow_header_prints_health_run_line_and_defined_steps_as_a_different_noun(monkeypatch):
    from checks import report
    from cockpit_ops.app import templates
    st = _gathered()
    monkeypatch.setattr(api, "get_health_overview", lambda force=False: {"pipeline_summary": st["pipeline"]})
    run = api.get_run_summary()
    assert run["line"] == report.run_line(st["pipeline"]) and (run["n_ok"], run["n_logged"]) == (54, 55)
    html = templates.env.get_template("flow.html").render(layers=[], failures=[], outside_failures=[], step_count=67,
                                                            n_ok=66, n_never=0, run=run, page="flow", edges=[])
    assert "54 of 55 logged steps ok" in html and "67 steps" in html and "66 succeeded" not in html


def test_feed_severity_is_the_gathered_issue_severity():
    rows = [{"feed": "yfinance_prices", "status": "live"}]
    import feeds
    name = next(iter(n for n, f in feeds.FEEDS.items() if f["status"] in feeds.LIVE and feeds.steps_of(n)))
    step = feeds.steps_of(name)[0]
    rows = [{"feed": name, "status": feeds.FEEDS[name]["status"]}]
    crit = _issue("PIPELINE_STEP", step)
    out = api.feed_issues(rows, ([crit], []))
    assert out[name][0]["severity"] == "CRITICAL" and api._PLAIN[out[name][0]["code"]] == "Last run failed"


def test_backticks_render_as_code_and_factor_ids_as_labels():
    from cockpit_ops.app import _ticks
    assert str(_ticks("run `run.sh canary` <now>")) == 'run <code class="mono">run.sh canary</code> &lt;now&gt;'
    assert api.factor_label("announcement_car") != "announcement_car" and "_" not in api.factor_label("not_a_factor_id")


def test_org_card_leads_with_the_subject_and_keeps_the_id_as_a_reference():
    from pathlib import Path
    src = (Path(api.__file__).parent / "templates" / "org.html").read_text()
    head = src[src.index('<div class="og-row" id="item-'):]
    head = head[:head.index('<div class="og-sub">')]
    assert 'class="og-title">{{ i.title }}' in head and head.index("og-title") < head.index("ref {{ i.doc_id }}")
    assert "#{{ i.doc_id }}" not in src and "title=" not in src.replace("x-text", "").replace("og-title", "").replace("chat.title", "")


def test_inventory_coverage_is_an_integer_and_retired_wording_is_gone():
    from pathlib import Path
    import re
    import tables
    src = (Path(api.__file__).parent / "templates" / "system_tabs" / "inventory.html").read_text()
    assert "row.stock_count|int" in src
    text = " ".join(str(v) for e in tables.TABLES.values() for k, v in e.items() if k in ("description", "depth", "source"))
    assert not re.search(r"C13b|\buhs_|trust[- ]gate", text, re.I)


def test_compare_maps_every_ops_page_and_tab():
    import preview
    from cockpit_ops import pages
    for p in pages.PAGES:
        assert p["path"] in preview.COMPARE["ops"], p["path"]
        for key, _ in p.get("tabs") or []:
            assert f"{p['path']}#{key}" in preview.COMPARE["ops"], (p["path"], key)
    assert preview.COMPARE["ops"]["/feeds#data"] == "/system#health"
