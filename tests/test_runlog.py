"""runlog: structured, queryable run events an outside agent can act on (plan 0018).

Every test runs against the throwaway run-log DB from conftest.py.
"""
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import runlog

ROOT = Path(__file__).resolve().parent.parent


def _events(path, **where):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    q = " AND ".join(f"{k} = ?" for k in where) or "1=1"
    return [dict(r) for r in c.execute(f"SELECT * FROM run_events WHERE {q} ORDER BY id", list(where.values()))]


class _Resp:
    def __init__(self, status, body=b"", ctype="text/html"):
        self.status_code, self.content, self.headers = status, body, {"content-type": ctype}


# ─────────────────────────────── redaction ───────────────────────────────

def test_redacts_secrets(monkeypatch):
    monkeypatch.setenv("SCREENER_PASSWORD", "hunter2-super-secret")
    s = runlog.redact("GET https://x/api?symbol=RELI&access_token=abc123&apikey=zz "
                      "Cookie: sessionid=qwerty; Authorization: Bearer abcdefghijklmnop "
                      "and the pw hunter2-super-secret")
    for leaked in ("abc123", "apikey=zz", "qwerty", "abcdefghijklmnop", "hunter2-super-secret"):
        assert leaked not in s, leaked
    assert "symbol=RELI" in s


# ─────────────────────────────── location ───────────────────────────────

def test_location_points_at_repo_frame_and_feed_origin():
    frames = [{"file": "sources/nse.py", "line": 60, "func": "_fetch_date", "code": "", "repo": True, "lib": False},
              {"file": "sources/_http.py", "line": 155, "func": "polite_request", "code": "", "repo": True, "lib": False},
              {"file": "/venv/lib/site-packages/requests/models.py", "line": 1, "func": "raise_for_status",
               "code": "", "repo": False, "lib": True}]
    point, origin = runlog.location(frames, "sources.nse")
    assert point == "sources/_http.py:155 in polite_request"
    assert origin == "sources/nse.py:60 in _fetch_date"


@pytest.mark.parametrize("exc,sym", [(KeyError("author"), "D"), (PermissionError("login page"), "C"),
                                     (RuntimeError("x: 0 of 3 items returned data"), "E"),
                                     (RuntimeError("Your credit balance is too low"), "G")])
def test_classify_exception(exc, sym):
    assert runlog.classify_exception(exc)[1] == sym


# ─────────────────────────────── lifecycle ───────────────────────────────

def test_run_lifecycle_counts_and_queries(_isolated_runlog):
    rid = runlog.start("fetch_bhavcopy", module="sources.nse")
    print("fetched 0 rows for 2026-09-25")
    runlog.request("nse_archives", "https://archives.nseindia.com/x.csv?token=SECRET1", status=200, nbytes=10)
    runlog.request("nse_archives", "https://archives.nseindia.com/y.csv", status=403,
                   response=_Resp(403, b"<html>Access Denied</html>"), will_retry=True)
    runlog.request("nse_archives", "https://archives.nseindia.com/y.csv", status=404)       # counted, not logged
    try:
        {}["CLOSE_PRICE"]
    except KeyError as e:
        runlog.item_error("bhavcopy", "2026-09-25", e)
    runlog.count_write("stock_prices", 7)
    runlog.end("SUCCESS")
    ev = _events(_isolated_runlog, run_id=rid)
    kinds = [e["event"] for e in ev]
    assert kinds == ["run_start", "request", "item_error", "run_end"], kinds
    req = ev[1]
    assert req["http_status"] == 403 and req["symptom"] == "A" and req["level"] == "WARN"
    assert "Access Denied" in json.loads(req["detail"])["response"]["snippet"]
    item = ev[2]
    assert item["error_type"] == "KeyError" and item["symptom"] == "D"
    assert item["location"].startswith("tests/test_runlog.py:")
    end = json.loads(ev[3]["detail"])
    assert end["requests"]["nse_archives"] == {"200": 1, "403": 1, "404": 1}
    assert end["retries"] == {"nse_archives": 1} and end["rows_written"] == {"stock_prices": 7}
    assert any("fetched 0 rows" in line for line in end["output_tail"])
    assert ev[0]["feed"] == "nse_bhavcopy", "step → feed resolved from feeds.log_steps"
    r = runlog.runs(feed="nse_bhavcopy")[0]
    assert r["status"] == "SUCCESS" and r["n_warn"] == 2
    assert [e["event"] for e in runlog.events(run_id=rid, level="WARN")] == ["item_error", "request"]


def test_event_caps_prevent_floods(_isolated_runlog, monkeypatch):
    monkeypatch.setitem(runlog.CAPS, "request", 5)
    rid = runlog.start("fetch_x")
    for _ in range(12):
        runlog.request("h", "https://h/x", status=503)
    runlog.end("FAILED")
    ev = _events(_isolated_runlog, run_id=rid)
    assert sum(e["event"] == "request" for e in ev) == 5
    assert json.loads(ev[-1]["detail"])["suppressed_events"] == {"request": 7}


# ─────────────────────────────── cron child process ───────────────────────────────

def _child(tmp_path, body, db):
    script = tmp_path / "child.py"
    script.write_text(textwrap.dedent(body))
    env = {**os.environ, "ALPHA_STEP": "cron_bse_announcements", "ALPHA_RUN_ID": "cron_bse_announcements:T:1",
           "ALPHA_RUNLOG_DB": str(db), "PYTHONPATH": str(ROOT)}
    return subprocess.run([sys.executable, str(script)], cwd=ROOT, env=env, capture_output=True, text=True)


def test_cron_child_logs_uncaught_exception(tmp_path, _isolated_runlog):
    p = _child(tmp_path, """
        from sources import _http            # import opens the run (ALPHA_STEP)
        def parse(rows):
            return rows[0]["NEWSID"]
        print("page 1: 50 rows")
        parse([{}])
    """, _isolated_runlog)
    assert p.returncode == 1 and "KeyError" in p.stderr, "the original traceback still reaches the cron log"
    ev = _events(_isolated_runlog, run_id="cron_bse_announcements:T:1")
    assert [e["event"] for e in ev] == ["run_start", "exception", "run_end"]
    exc = ev[1]
    assert exc["feed"] == "bse_announcements" and exc["error_type"] == "KeyError" and exc["symptom"] == "D"
    frames = json.loads(exc["detail"])["frames"]
    assert frames[-1]["func"] == "parse" and "NEWSID" in frames[-1]["code"]
    assert ev[2]["error_type"] == "FAILED"
    assert "page 1: 50 rows" in json.loads(ev[2]["detail"])["output_tail"]


def test_cron_child_exit_code(tmp_path, _isolated_runlog):
    p = _child(tmp_path, """
        import sys
        from sources import _http
        sys.exit(3)
    """, _isolated_runlog)
    assert p.returncode == 3
    end = _events(_isolated_runlog, event="run_end")[0]
    assert end["error_type"] == "FAILED" and end["message"] == "exit 3"


# ─────────────────────────────── pipeline hook ───────────────────────────────

def test_pipeline_step_failure_is_located(_isolated_runlog, monkeypatch, tmp_path):
    import pipeline
    logged = []
    monkeypatch.setattr(pipeline, "log_step", lambda *a, **k: logged.append((a, k)))
    monkeypatch.setattr(pipeline, "_post_check", lambda name: [])
    mod = tmp_path / "boom_mod.py"
    mod.write_text("def compute():\n    return int('not a number')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert pipeline.run_step("fetch_boom", "boom_mod", "compute", critical=False) is False
    err = logged[-1][1]["error"]
    assert err.startswith("ValueError") and "boom_mod.py:2 in compute" in err
    ev = _events(_isolated_runlog, step="fetch_boom")
    assert [e["event"] for e in ev] == ["run_start", "exception", "run_end"]


# ─────────────────────────────── incident bundle ───────────────────────────────

def test_bundle_has_everything_an_agent_needs(_isolated_runlog, monkeypatch):
    monkeypatch.setattr(runlog, "_rows", runlog._rows)          # feed_checks absent here → empty canaries
    rid = runlog.start("fetch_bhavcopy", module="sources.nse")
    runlog.request("nse_archives", "https://archives.nseindia.com/a.csv", status=403,
                   response=_Resp(403, b"<html>Access Denied</html>"))
    try:
        raise RuntimeError("fetch_bhavcopy: 0 of 1 items returned data")
    except RuntimeError as e:
        runlog.exception(e)
    runlog.end("FAILED", error="RuntimeError")
    b = runlog.bundle("nse_bhavcopy")
    assert b["tier"] == "T1" and b["failing_run"]["run_id"] == rid
    assert {"A", "E"} <= set(b["symptom_playbook"])
    assert b["code"]["modules"] == ["sources/nse.py"] and b["code"]["failure_points"]
    assert any(e["event"] == "request" for e in b["failing_run_events"])
    assert any("tools.canary --feed nse_bhavcopy" in v for v in b["verify_with"])
    json.dumps(b, default=str)                                   # ships as JSON over MCP


def test_job_entry_point_adopts_the_logged_run(_isolated_runlog, monkeypatch):
    monkeypatch.setenv("ALPHA_STEP", "cron_canary")
    monkeypatch.setenv("ALPHA_RUN_ID", "cron_canary:T:9")
    assert runlog.start("canary", module="tools.canary", adopt_env=True) == "cron_canary:T:9"
    runlog.end("SUCCESS")
    runlog.exit_code("cron_canary:T:9", "cron_canary", "0")
    r = runlog.runs(step="cron_canary")
    assert len(r) == 1 and r[0]["status"] == "SUCCESS"


def test_item_failed_records_the_detecting_line(_isolated_runlog):
    runlog.start("fetch_banking_metrics", module="sources.banking_metrics")
    runlog.item_failed("banking_metrics", "BJAT", "ALL_FAIL: identity_gate WRONG_ENTITY", symptom="F")
    runlog.end("SUCCESS")
    e = [x for x in runlog.events(step="fetch_banking_metrics") if x["event"] == "item_error"][0]
    assert e["symptom"] == "F" and e["location"].startswith("tests/test_runlog.py:")
    assert e["feed"] == "banking_metrics"
