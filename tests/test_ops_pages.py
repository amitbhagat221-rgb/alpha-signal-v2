"""Ops cockpit pages (G5): the /org cancel path, the /flow outside-the-DAG banner, the /system Data card colour."""
import re
from pathlib import Path

ORG = Path(__file__).resolve().parent.parent / "cockpit_ops" / "templates" / "org.html"


def test_org_cancel_on_the_note_prompt_records_no_decision():
    """prompt() returns null on Cancel. The old code turned that into '' and still POSTed a Reject / Park."""
    src = ORG.read_text()
    body = src[src.index("async decide(id, verdict)"): src.index("load(data)")]
    assert "|| ''" not in body.split("prompt(")[1].split(";")[0]          # null is no longer folded into ''
    assert body.index("if (n === null) return;") < body.index("post('/api/org/decide'")   # abort before the POST
    assert "confirm('Approve" in body and body.index("confirm('Approve") < body.index("post('/api/org/decide'")
    assert "location.reload" not in body                                   # the card leaves in place


def test_org_run_all_asks_first():
    src = ORG.read_text()
    run = src[src.index("async run(role)"):]
    assert run.index("confirm('Run every enabled desk seat") < run.index("post('/api/org/run'")


def _flow(monkeypatch, rows):
    import views
    from cockpit_ops import api
    monkeypatch.setattr(views, "step_status", lambda: rows)
    return api.get_flow_overview()


def test_flow_banner_lists_recent_failed_steps_outside_the_dag(monkeypatch):
    import datetime as dt
    today = dt.date.today().isoformat()
    old = (dt.date.today() - dt.timedelta(days=40)).isoformat()
    rows = {
        "cron_bse_shp_backfill": {"status": "FAILED", "error_message": "exit 1", "run_date": today},
        "datamodel_sync": {"status": "ABORTED", "error_message": None, "run_date": today},
        "cron_ok_job": {"status": "SUCCESS", "run_date": today},
        "test_fail": {"status": "FAILED", "error_message": "old", "run_date": old},
    }
    out = _flow(monkeypatch, rows)
    names = [f["name"] for f in out["outside_failures"]]
    assert names == ["cron_bse_shp_backfill", "datamodel_sync"]       # failed, recent, not a DAG step
    assert out["failures"] == []                                       # nothing inside the DAG failed


def test_flow_banner_renders_with_a_link_to_health(monkeypatch):
    from cockpit_ops.app import templates
    import datetime as dt
    rows = {"datamodel_sync": {"status": "FAILED", "error_message": "boom", "run_date": dt.date.today().isoformat()}}
    out = _flow(monkeypatch, rows)
    html = templates.env.get_template("flow.html").render(**out, page="flow")
    assert "datamodel_sync" in html and 'href="/system"' in html and "NEED ATTENTION" in html


def _health_html(status, verdict):
    from cockpit_ops.app import templates
    overview = {"scorecard": [{"theme": "arrived", "question": "Did the data arrive?", "status": status,
                               "critical": 0, "warn": 0, "facts": "85 of 86 tables fresh", "covers": ""}],
                "eligibility": []}
    summary = {"verdict": verdict, "total_rows": 10, "total_tables": 2, "db_size_mb": 5.0, "last_run": {},
               "kind_counts": {}, "fresh_counts": {"FRESH": 1, "STALE": 0, "OUTDATED": 1, "N/A": 0}}
    return templates.env.get_template("system_tabs/health.html").render(overview=overview, summary=summary, health_scores=None)


def test_system_data_card_colour_comes_from_the_gathered_verdict():
    """The freshness scan's sentence says NEEDS ATTENTION, the report says the data question is OK:
    the card follows the report (st-ok), never a string match on the sentence."""
    html = _health_html("OK", "NEEDS ATTENTION — 1 table(s) outdated past 2× their refresh window.")
    card = re.search(r'<div class="card sy-card (st-[a-z-]+)" data-data-card>', html)
    assert card and card.group(1) == "st-ok"
    html = _health_html("BROKEN", "HEALTHY — all refreshable tables are fresh.")
    assert 'sy-card st-broken" data-data-card' in html


def test_model_validation_wired_rows_cover_every_weighted_pair(monkeypatch):
    """Weight keys (piotroski) differ from evidence ids (piotroski_f_score): every
    nonzero SIGNAL_WEIGHTS entry must come out as one wired evidence row."""
    import pandas as pd
    import factors
    import tools.backtest_pit as bp
    from cockpit_ops import api
    recs = [{"signal": factors.signal_for(k, t), "cap_tier": t, "t_stat": 2.0, "mean_ic": .02,
             "icir": .3, "n_periods": 40, "n_stocks_avg": 100, "verdict": "KEEP",
             "computed_at": "2026-10-01"}
            for t, tw in factors.SIGNAL_WEIGHTS.items() for k in tw]
    monkeypatch.setattr(bp, "evidence", lambda: pd.DataFrame(recs))
    out = api.get_validation_evidence()
    total = sum(1 for tw in factors.SIGNAL_WEIGHTS.values() for w in tw.values() if w)
    assert out["meta"]["n_wired"] == total


def test_factor_counts_are_one_definition(monkeypatch):
    """/system Factors header, its funnel and /command all quote factor_counts(): the
    header's validated is the funnel's (KEEP + WEAK), never a second rule."""
    from cockpit_ops import api
    summary = {"total": 105, "wired": 11, "funnel": {"validated": 64}}
    monkeypatch.setattr(api, "get_factor_health", lambda: {"summary": summary, "factors": []})
    assert api.factor_counts() == {"total": 105, "validated": 64, "wired": 11, "not_wired": 94}
    src = Path(api.__file__).read_text()
    assert '"validated": funnel["validated"]' in src and 'if r["in_model"]' not in src


def test_cold_data_tab_returns_at_once_while_the_scan_runs_in_the_background(monkeypatch, tmp_path):
    import threading
    import time
    import cockpit._shared as shared
    import db
    import health
    from cockpit_ops import api, app as ops_app
    gate = threading.Event()
    monkeypatch.setattr(shared, "_PERSISTED_CACHE_DIR", tmp_path)
    api._data_health_scores.cache_clear()
    api.get_db_summary.cache_clear()
    monkeypatch.setattr(health, "compute_db_health", lambda *a, **k: gate.wait(10) or {"tables": []})
    monkeypatch.setattr(db, "db_summary", lambda: gate.wait(10) or {})
    monkeypatch.setattr(api, "get_health_overview", lambda: None)
    t0 = time.time()
    ctx = ops_app._system_tab_context("health")
    assert time.time() - t0 < 2
    assert ctx["scan_running"] and ctx["health_scores"] is None and ctx["summary"] is None
    gate.set()
    api._data_health_scores.cache_clear()
    api.get_db_summary.cache_clear()
