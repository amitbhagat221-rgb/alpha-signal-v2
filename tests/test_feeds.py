"""
feeds.FEEDS is the data-supply map (plan 0018). These tests hold it to the code so
it cannot drift into a stale diagram:

  coverage     every sources/ module, every source step and every RAW table maps to a feed
  schedule     every production feed is scheduled by a real step or a real run.sh job
               that ops/crontab.txt runs (class H "orphan" can't be introduced silently)
  resilience   every T1 feed has a live fallback or a serve-stale limit, and a canary
  canaries     every declared canary exists; every canary is used by a live feed
  derivation   tiers come from the graph; known-critical feeds stay T1
  gates        the canary judge catches each symptom class offline (no network)
"""
import gzip
import os
import pkgutil
import re
import time
from pathlib import Path

import pandas as pd
import pytest

import feeds
from checks import CRITICAL, INFO, WARN
from config import PIPELINE_STEPS
from hosts import HOSTS
from tables import TABLES

ROOT = Path(__file__).resolve().parent.parent
LIVE = [n for n, f in feeds.FEEDS.items() if f["status"] in feeds.LIVE]


# ─────────────────────────────── registry shape ───────────────────────────────

def test_entries_are_well_formed():
    for name, f in feeds.FEEDS.items():
        assert f["family"] in feeds.FAMILIES, name
        assert f["status"] in feeds.STATUSES, name
        assert f.get("what"), f"{name}: say what it delivers"
        if f["status"] in feeds.LIVE:
            for key in ("modules", "writes", "hosts", "routes", "cadence", "schedule"):
                assert key in f, f"{name}: live feed needs `{key}`"
            assert f["cadence"] in feeds.CADENCES, name
            for h in f["hosts"]:
                assert h in HOSTS, f"{name}: host {h} not declared in hosts.HOSTS"
            for t in f["writes"]:
                assert t in TABLES, f"{name}: writes unknown table {t}"
            for r in f["routes"]:
                assert r["kind"] in feeds.ROUTE_KINDS, (name, r)
                assert r["host"] is None or r["host"] in HOSTS, (name, r)
            assert f.get("canary") or f.get("canary_waiver"), f"{name}: needs a canary or a canary_waiver"
            if f.get("derived_from"):
                assert all(u in feeds.FEEDS for u in f["derived_from"]), name
        if f["status"] in feeds.DISCOVERY + ("retired",):
            assert f.get("probe") or f.get("need") or f.get("modules"), f"{name}: record the evidence"


def test_symptom_classes_and_incidents():
    assert set(feeds.SYMPTOM_CLASSES) == set("ABCDEFGH")
    for inc in feeds.INCIDENTS:
        d, feed, cls, *_ = inc
        assert len(inc) == 7 and re.match(r"\d{4}-\d{2}-\d{2}$", d), inc
        assert feed in feeds.FEEDS and cls in feeds.SYMPTOM_CLASSES, inc


# ─────────────────────────────── coverage ───────────────────────────────

def test_every_sources_module_belongs_to_a_feed():
    covered = {m for f in feeds.FEEDS.values() for m in f.get("modules") or []}
    for m in pkgutil.iter_modules([str(ROOT / "sources")]):
        if m.name.startswith("_") or m.name == "canaries":
            continue
        assert f"sources.{m.name}" in covered, f"sources.{m.name} has no feed in feeds.py"
    for mod in covered:
        assert (ROOT / (mod.replace(".", "/") + ".py")).exists(), f"feed names a missing module {mod}"


def test_every_source_step_belongs_to_exactly_one_feed():
    owner = {}
    for name in feeds.FEEDS:
        for s in feeds.steps_of(name):
            assert s not in owner, f"step {s} claimed by {owner[s]} and {name}"
            owner[s] = name
    for s in PIPELINE_STEPS:
        if not isinstance(s, str) and s["module"].startswith("sources."):
            assert s["name"] in owner, f"source step {s['name']} has no feed"


def test_every_raw_table_is_fed_or_explicitly_not():
    fed = {t for f in feeds.FEEDS.values() for t in f.get("writes") or []}
    for t, e in TABLES.items():
        if e.get("kind") == "RAW":
            assert t in fed or t in feeds.NON_FEED_TABLES, f"RAW table {t} has no feed (or NON_FEED_TABLES reason)"
    for t in feeds.NON_FEED_TABLES:
        assert t in TABLES, f"NON_FEED_TABLES lists unknown table {t}"


# ─────────────────────────────── schedule (class H) ───────────────────────────────

def _run_sh_jobs():
    return set(re.findall(r"^\s{4}([a-z_]+)\)", (ROOT / "run.sh").read_text(), re.M))


def _cron_jobs():
    return set(re.findall(r"alpha-signal-v2/run\.sh (\w+)", (ROOT / "ops/crontab.txt").read_text()))


def test_schedules_point_at_real_steps_and_cron_jobs():
    steps = {s["name"] for s in PIPELINE_STEPS if not isinstance(s, str)}
    jobs, cron = _run_sh_jobs(), _cron_jobs()
    for name in feeds.FEEDS:
        for kind, target in feeds.schedule_kinds(name):
            assert kind in ("step", "cron", "manual"), (name, kind)
            if kind == "step":
                assert target in steps, f"{name}: no PIPELINE_STEPS step {target}"
            if kind == "cron":
                assert target in jobs, f"{name}: run.sh has no job {target}"
                assert target in cron, f"{name}: ops/crontab.txt never runs job {target}"


def test_production_feeds_are_scheduled():
    for name, f in feeds.FEEDS.items():
        if f["status"] == "production":
            assert f.get("schedule"), f"{name} is production but unscheduled — schedule it or mark it degraded"


def test_canary_job_is_wired():
    assert "canary" in _run_sh_jobs() and "canary" in _cron_jobs()
    assert "harvest_lock" in (ROOT / "run.sh").read_text().split("canary)")[1].split(";;")[0]


# ─────────────────────────────── tiers + resilience ───────────────────────────────

def test_tiers_are_derived():
    t = feeds.tiers(refresh=True)
    for must in ("nse_bhavcopy", "tickertape_fundamentals", "tickertape_shareholding", "bse_announcements",
                 "fno_bhav", "fno_iv", "corporate_actions", "tickertape_analyst"):
        assert t[must] == "T1", f"{must} feeds a wired factor / the email — must derive T1, got {t[must]}"
    for name, f in feeds.FEEDS.items():
        if f["status"] == "retired":
            assert t[name] is None
        elif f["status"] in feeds.DISCOVERY + ("probation",):
            assert t[name] == "T3", name


def test_t1_feeds_are_resilient_and_canaried():
    from sources.canaries import CANARIES
    for name, tier in feeds.tiers().items():
        if tier != "T1":
            continue
        assert feeds.resilience(name) != "none", f"{name} (T1) needs a live fallback route or serve_stale_days"
        if not feeds.FEEDS[name].get("derived_from"):
            assert feeds.FEEDS[name].get("canary") in CANARIES, f"{name} (T1) needs a live canary"


def test_dead_route_is_not_resilience():
    f = {"routes": [{"id": "p", "kind": "primary", "host": None, "how": ""},
                    {"id": "fb", "kind": "fallback", "host": None, "how": "", "dead": "404"}]}
    feeds.FEEDS["_t"] = {**f, "family": "prices", "status": "production", "what": "x"}
    try:
        assert not feeds.has_fallback("_t") and feeds.resilience("_t") == "none"
    finally:
        del feeds.FEEDS["_t"]


def test_every_canary_is_declared_and_used():
    from sources.canaries import CANARIES
    used = {f["canary"] for f in feeds.FEEDS.values() if f.get("canary")}
    assert used <= set(CANARIES), used - set(CANARIES)
    live_used = {feeds.FEEDS[n]["canary"] for n in LIVE if feeds.FEEDS[n].get("canary")}
    assert set(CANARIES) <= live_used, f"canaries no live feed uses: {set(CANARIES) - live_used}"


def test_log_steps_parse_run_sh():
    assert feeds.log_steps("bse_announcements") == ["cron_bse_announcements"]
    assert feeds.log_steps("nse_market_daily") == ["cron_nselib_daily_forward"]
    assert feeds.log_steps("tickertape_fundamentals") == ["cron_tickertape"]
    assert feeds.log_steps("nse_bhavcopy") == ["fetch_bhavcopy"]


# ─────────────────────────────── canary gates (offline) ───────────────────────────────

from tools import canary as C  # noqa: E402


def _sample(**kw):
    base = {"expect": "json", "records": [{"a": 1, "b": 2}], "raw": b'[{"a":1,"b":2}]', "http": 200}
    return {**base, **kw}


def test_gate_pass_and_baseline():
    v = C.judge(_sample(), ["a", "b"])
    assert v["status"] == "PASS" and v["symptom"] is None and v["fingerprint"] == C.fingerprint(["b", "a"])


@pytest.mark.parametrize("http,sym", [(403, "A"), (404, "B"), (401, "C"), (429, "G"), (503, "E")])
def test_gate_http_codes(http, sym):
    v = C.judge(_sample(http=http), ["a", "b"])
    assert (v["status"], v["symptom"]) == ("FAIL", sym)


def test_gate_html_where_data_expected():
    v = C.judge(_sample(raw=b"<!DOCTYPE html><html><head><title>Access Denied</title>"), None)
    assert (v["status"], v["symptom"]) == ("FAIL", "A")
    v = C.judge(_sample(raw=b"<html><head></head><body>Please login to continue</body>"), None)
    assert (v["status"], v["symptom"]) == ("FAIL", "C")


def test_gate_empty_and_floor():
    assert C.judge(_sample(records=[]), None)["symptom"] == "B"
    assert C.judge(_sample(min_rows=5), None)["symptom"] == "E"


def test_gate_shape_drift():
    removed = C.judge(_sample(records=[{"a": 1}]), ["a", "b"])
    assert (removed["status"], removed["symptom"]) == ("FAIL", "D")
    added = C.judge(_sample(records=[{"a": 1, "b": 2, "c": 3}]), ["a", "b"])
    assert (added["status"], added["symptom"]) == ("WARN", "D")
    frame = C.judge({"expect": "frame", "records": pd.DataFrame({"b": [1], "a": [2]}), "raw": b"x", "http": None}, ["a", "b"])
    assert frame["status"] == "PASS", "column ORDER must not count as drift"


def test_gate_required_and_checks():
    assert C.judge(_sample(required=["z"]), None)["symptom"] == "D"
    v = C.judge(_sample(checks=[("logged_in", False, "cookie rejected")]), None)
    assert (v["status"], v["symptom"]) == ("FAIL", "C")
    v = C.judge(_sample(checks=[("fallback_route", False, "404", "B", "WARN")]), None)
    assert (v["status"], v["symptom"]) == ("WARN", "B")


def test_exception_classes():
    import json
    import requests
    assert C.classify_exception(ImportError("x")) == ("ERROR", None)
    assert C.classify_exception(requests.ConnectionError("Connection reset by peer")) == ("FAIL", "A")
    assert C.classify_exception(requests.Timeout("timed out")) == ("FAIL", "E")
    assert C.classify_exception(KeyError("data")) == ("FAIL", "D")
    assert C.classify_exception(json.JSONDecodeError("Expecting value", "<html>", 0)) == ("FAIL", "A")


def test_raw_zone_landing_and_prune(tmp_path):
    s = _sample()
    good = C.land_raw("k", s, True, root=tmp_path)
    assert good.name == "last_good.json.gz" and gzip.decompress(good.read_bytes()) == s["raw"]
    old = C.land_raw("k", s, False, root=tmp_path)
    past = time.time() - 40 * 86400
    os.utime(old, (past, past))
    new = C.land_raw("k", s, False, root=tmp_path, now=pd.Timestamp("2030-01-01"))
    C.save_baseline("k", ["a"], "t", root=tmp_path)
    removed = C.prune(root=tmp_path)
    assert old in removed and new.exists() and good.exists() and (tmp_path / "k/baseline.json").exists()
    C.prune(root=tmp_path, cap_bytes=0)
    assert not new.exists() and good.exists(), "cap pruning removes failures only, never last_good/baseline"


# ─────────────────────────────── verdict severities ───────────────────────────────

def _row(tier="T1", last=None, prev=None, schedule=("step:x",), resilience="fallback", canary="k"):
    return {"feed": "f", "tier": tier, "status": "production", "canary": canary, "canary_last": last,
            "canary_prev": prev, "canary_gates": [], "schedule": list(schedule), "resilience": resilience,
            "serve_stale_days": 1, "fallback_plan": None, "notes": None}


def _chk(status, sym=None, hours=1):
    ts = (pd.Timestamp.now() - pd.Timedelta(hours=hours)).isoformat()
    return {"status": status, "symptom": sym, "checked_at": ts}


def _sev(rows, code):
    from checks.feeds import feed_verdicts
    return [v["severity"] for v in feed_verdicts(rows) if v["code"] == code]


def feed_verdicts_codes(rows):
    from checks.feeds import feed_verdicts
    return [v["code"] for v in feed_verdicts(rows)]


def test_verdict_severities():
    assert _sev([_row(last=_chk("FAIL", "D"))], "FEED_CANARY_FAIL") == [CRITICAL]     # drift pages at once
    assert _sev([_row(last=_chk("FAIL", "E"))], "FEED_CANARY_FAIL") == [WARN]         # first blip
    assert _sev([_row(last=_chk("FAIL", "E"), prev=_chk("FAIL", "E"))], "FEED_CANARY_FAIL") == [CRITICAL]
    assert _sev([_row(tier="T2", last=_chk("FAIL", "D"))], "FEED_CANARY_FAIL") == [WARN]
    assert _sev([_row(last=_chk("WARN", "B"))], "FEED_CANARY_WARN") == [WARN]
    assert _sev([_row(tier="T2", last=_chk("WARN", "B"))], "FEED_CANARY_WARN") == [INFO]
    assert _sev([_row(last=_chk("PASS", hours=48))], "FEED_CANARY_MISSING") == [WARN]
    assert _sev([_row(tier="T2", last=_chk("PASS", hours=48))], "FEED_CANARY_MISSING") == []
    # registry facts (unscheduled, no fallback) are tests above, never daily verdicts (ADR 0060)
    assert feed_verdicts_codes([_row(last=_chk("PASS"), schedule=(), resilience="none")]) == []
    assert _sev([_row(last=_chk("ERROR"))], "FEED_CANARY_ERROR") == [WARN]


def test_registry_has_no_drift_now():
    from checks.feeds import registry_drift
    assert registry_drift() == []


# ─────────────────────────────── ops page renders (offline) ───────────────────────────────

def test_data_supply_page_renders(monkeypatch):
    """/feeds renders every tab from synthetic state: a failing T1 canary (drift),
    a warn, a never-run canary and an orphan — no live DB reads."""
    import checks.feeds as CF
    from starlette.requests import Request
    from cockpit_ops import api
    from cockpit_ops.app import templates

    now = pd.Timestamp.now().isoformat()
    canaries = {
        "nse_bhavcopy": [{"status": "FAIL", "symptom": "D", "checked_at": now, "fingerprint": "abc", "baseline": "def",
                          "n_rows": 10, "bytes": 99, "detail": '{"gates": [["shape", "FAIL", "D", "fields removed [\'X\']"]]}'}],
        "scrip_master": [{"status": "WARN", "symptom": "B", "checked_at": now, "detail": "{}"}],
    }
    monkeypatch.setattr(CF, "_latest_canaries", lambda: (canaries, {"nse_bhavcopy": (10, 9)}))
    monkeypatch.setattr(CF, "_latest_runs", lambda names: {"fetch_bhavcopy": {"step_name": "fetch_bhavcopy",
                        "status": "FAILED", "finished_at": now, "error_message": "boom"}})
    monkeypatch.setattr(CF, "_freshness", lambda: {"stock_prices": {"freshness": "OUTDATED", "age_days": 4,
                        "latest_date": "2026-01-01", "rows": 5}})
    data = api.get_feed_overview.__wrapped__()
    assert data["summary"]["critical"] >= 1 and data["summary"]["drift"] == 1
    req = Request({"type": "http", "method": "GET", "path": "/feeds", "headers": [], "query_string": b"",
                   "server": ("t", 80), "scheme": "http", "root_path": ""})
    html = templates.env.get_template("feeds.html").render(request=req, page="feeds", **data)
    for s in ("Data Supply", "working", "need a look", "broken", "nse_bhavcopy", "Health check failed",
              "fields removed", "New sources", "incident report"):
        assert s in html, s
    row = next(r for r in data["simple"] if r["feed"] == "nse_bhavcopy")
    assert row["state"] == "Broken" and row["check"] == "failed" and row["age_bad"]
    assert data["simple"][0]["state"] == "Broken", "broken feeds sort first"
