"""
System checks (ADR 0059, 0060): what can go wrong with a run, a table, a feed, a
pick or the model — everything that is not a rule over the rows of one table
(those are the data checks: checks/custom.py, ranges.py, tables.TABLES coverage).

Three things, each in ONE place:

    SYSTEM_CHECKS   what every check means: the question it answers, when it
                    alerts, why it matters, what to do first, how severe it is.
    an area         a pair of plain functions: `<area>_facts()` reads the DB and
                    returns a dict; `<area>_verdicts(facts)` is pure and returns
                    the failing verdicts. Facts and verdicts sit together.
    AREAS           the registry at the bottom: {key: (facts, verdicts)}.
                    checks.report runs it; nothing else lists the areas.

To add a system check: its meaning in SYSTEM_CHECKS, its area (or a new verdict in
an existing one), a drill in tests/test_check_drills.py. To change a threshold:
the constants below.

Not here, on purpose (ADR 0060): a rule that can only break when code or a
registry changes (an unregistered feed, a factor in two buckets, a table with no
date column). Those are tests — they run when the code changes, not every morning.
"""

import re
from datetime import date, datetime
from pathlib import Path

import db
import views
from checks import CRITICAL, FAIL, INFO, OK, PASS, WARN, verdict
from db import data_health, read_sql

ROOT = Path(__file__).resolve().parent.parent

FAILURE_STREAK_DAYS = 2      # the same step failing this many days running = systemic
WATCHDOG_MAX_AGE_H = 36      # the watchdog is a daily cron
GATE_SILENT_DAYS = 7         # a write-time gate with no verdict for this long has stopped running

# code: (theme, when it alerts, why it matters, what to do first, how severe)
_S = {
    # ── Did everything run? ──
    "PIPELINE_STEP": ("ran",
        "A step of the latest run ended in failure (a later successful re-run clears it), or the run died mid-step",
        "A failed step leaves its tables as they were yesterday; everything downstream reads old data. "
        f"The same step failing {FAILURE_STREAK_DAYS}+ days running is a broken source or a bug that will not heal itself.",
        "Read the error, fix it, rerun the step (Rerun on the ops Flow page, or `python pipeline.py --step <name>`). "
        "For a streak: `python -m runlog bundle <feed>` shows the evidence. A shadow job or gap-fill (WARN) can wait for the week.",
        f"CRITICAL when the morning email needs the step's output or it has failed {FAILURE_STREAK_DAYS}+ days running, else WARN. "
        "Always WARN for a step in config.NON_PAGING_STEPS (a v3 shadow job or a gap-fill the picks do not depend on)"),
    "WATCHDOG": ("ran",
        f"The self-healing watchdog has not run in the last {WATCHDOG_MAX_AGE_H} hours",
        "The watchdog re-runs the producers of stale tables every day; without it silent failures pile up.",
        "Check the crontab line `run.sh watchdog` (15:00 UTC) and output/watchdog.log.",
        "CRITICAL if it has never run, else WARN"),
    "HEALTH_CHECK_CRASHED": ("ran",
        "A part of this health report crashed, so its checks did not run",
        "A crashed check reports nothing, which looks the same as healthy.",
        "The evidence carries the exception; fix the checker before trusting that section.",
        "WARN"),
    # ── Did the data arrive? ──
    "TABLE_STALE": ("arrived",
        "A table is past its refresh limit",
        "Everything reading the table works on old data while reporting success.",
        "The watchdog tries to heal it at 15:00 UTC. If it is still stale tomorrow rerun its producer; "
        "if the source is dead, see docs/reference/feed-runbook.md.",
        "CRITICAL when it is more than twice past the limit and the morning email needs the table, else WARN "
        "(INFO for a best-effort source)"),
    "TABLE_EMPTY": ("arrived",
        "A table that should have rows is empty",
        "A producer wrote nothing where rows are expected.",
        "Rerun the producer and read its log. A table that may legitimately be empty is marked `may_be_empty` in tables.TABLES. "
        "A WARN is a new or optional feed (probation) or a file the cockpit can do without: it cannot change today's picks.",
        "CRITICAL. INFO for a table only a candidate feed writes or one marked `may_be_empty`; WARN for a table only a probation "
        "feed writes or an optional file (config.FILE_OUTPUTS `optional`); an empty quarantine table is clean"),
    "FEED_PROBE": ("arrived",
        "The 02:45 UTC one-item probe of a data feed failed, warned, crashed, or did not run",
        "The probe runs before the morning harvest: a failure means that feed's data will not arrive, or will arrive in a changed shape.",
        "`python -m runlog bundle <feed>`, then follow the symptom in docs/reference/feed-runbook.md. "
        "If many feeds have no probe result, the cron `run.sh canary` is dead.",
        "CRITICAL for a must-have (T1) feed on auth, shape drift or a second failure in a row, else WARN"),
    "FEED_VOLUME": ("arrived",
        "A normally steady step wrote far fewer (under 60%) or far more (over 3x) rows than its usual",
        "The step 'succeeded' but most of the data did not arrive, or arrived twice.",
        "Compare with the source: a holiday, a changed endpoint returning a short page, or duplicate writes? "
        "Over 3x while `run.sh backfill` is running (INFO) is the backfill's history being recomputed: no action.",
        "CRITICAL for a must-have (T1) feed under 25% of normal, else WARN. INFO for an over-3x jump while a declared "
        "backfill runs (output/backfill_active, written by `run.sh backfill`, is under 26 hours old)"),
    # ── Is the data right? ──
    "FEED_RECONCILE_FAIL": ("correct",
        "A feed disagrees with an independent second source on the same numbers",
        "When two sources disagree, one of them is feeding wrong numbers into the factors.",
        "The evidence lists the worst mismatches: `SELECT * FROM feed_checks WHERE check_kind='reconcile'`, then compare those stocks by hand.",
        "CRITICAL for a must-have (T1) feed on FAIL, else WARN"),
    "CHECK_VACUOUS": ("correct",
        "A data check had no rows to look at, so it checked nothing",
        "A check that cannot fail gives false comfort: the column it guards is empty, or its input stopped arriving.",
        "Fill the column or delete the check. Either is fine; a silent check is not.",
        "WARN"),
    # ── Can today's picks be trusted? ──
    "PICK_INTEGRITY": ("picks",
        "A pick contradicts itself across fields (for example an upside figure that does not match its target and price)",
        "A contradicting pick is removed from the morning brief and the action queue.",
        "Open the stock named in the evidence; the reason names the two fields that disagree.",
        "CRITICAL when a pick was removed, WARN for a minor inconsistency"),
    "TRUST_GATE_DORMANT": ("correct",
        f"A write-time data gate (identity, plausibility) has written no verdict in the last {GATE_SILENT_DAYS} days",
        "These gates stop a wrong-company or impossible value before it is written; a silent gate means bad rows "
        "are going straight into the analyst and banking tables again.",
        "Check that the producers still call validators.identity_check / validators.plausibility "
        "(the verdicts land in trust_verdicts).",
        "WARN"),
    "DOSSIER_HALLUCINATION": ("picks",
        "AI write-ups in the latest dossier file put raw numbers into their prose",
        "Numbers in narrative are where the model invents plausible figures; the cockpit refuses to show these write-ups.",
        "If it is more than one or two, tune the dossier prompt; the validator is in output/dossier.py.",
        "CRITICAL"),
    "COCKPIT_ENDPOINT": ("picks",
        "A cockpit data endpoint failed its coverage audit",
        "A page of the trading cockpit is showing gaps for stocks that should have data.",
        "Open the endpoint for the stock named in the evidence.",
        "from the audit: CRITICAL or WARN"),
    # ── Is the model still sound? ──
    "FACTOR_DECAY": ("model",
        "A wired factor's recent predictive power has flipped sign or fallen under a quarter of its long-run level, "
        "by more than sampling noise (2+ standard errors)",
        "The weight was set on the long-run evidence; if the edge is gone the factor is adding noise to the ranking.",
        "A review trigger, not an emergency: `python -m tools.factor_decay`, then take it to a promotion review. Never change a weight mechanically.",
        "WARN"),
}
SYSTEM_CHECKS = {code: dict(zip(("theme", "when", "why", "fix", "severity"), row)) for code, row in _S.items()}

# checks/feeds.py keeps one code per feed symptom (the Data Supply page labels them);
# the health report files each under the check it belongs to.
FAMILY = {"FEED_CANARY_FAIL": "FEED_PROBE", "FEED_CANARY_WARN": "FEED_PROBE", "FEED_CANARY_ERROR": "FEED_PROBE",
          "FEED_CANARY_MISSING": "FEED_PROBE", "FEED_VOLUME_DROP": "FEED_VOLUME", "FEED_VOLUME_SPIKE": "FEED_VOLUME"}



# ═══════════════════════════ Did everything run? ═══════════════════════════

def pipeline_facts(since_days=1):
    """The latest run in its FINAL state (views.pipeline_status: a step that failed
    and then succeeded on a re-run is a success; a run that died mid-step is
    ABORTED) + the steps failing several days running."""
    out = {"last_run_date": None, "last_run_status": None, "n_steps": 0,
           "failed_steps_today": [], "failed_streaks": []}
    last_date = db.scalar("SELECT MAX(run_date) FROM pipeline_log")
    if last_date is None:
        return out
    out["last_run_date"] = last_date

    age = (date.today() - date.fromisoformat(last_date)).days
    final = views.pipeline_status(max(age, 0) + 2)
    # cockpit endpoint audits log here too but are a check of their own (endpoint_facts)
    final = [r for r in final if not r["step_name"].startswith("endpoint_audit_")]
    today = [r for r in final if r["run_date"] == last_date]
    out["n_steps"] = len(today)
    # run.sh cron-only jobs (cron_*) can land on the previous run_date (the 14:00
    # forward job): take each one's newest row if it finished in the last 26 hours.
    newest_cron = {}
    for r in final:                                 # newest first
        if r["step_name"].startswith("cron_"):
            newest_cron.setdefault(r["step_name"], r)
    recent = (datetime.now().timestamp() - 26 * 3600)
    late_cron = [r for r in newest_cron.values() if r["run_date"] != last_date and r["finished_at"]
                 and datetime.fromisoformat(r["finished_at"].replace(" ", "T")).timestamp() >= recent]
    out["failed_steps_today"] = sorted(
        ({"step": r["step_name"], "at": r["started_at"],
          "error": (r["error_message"] or ("the run died before this step finished"
                                           if r["status"] == "ABORTED" else ""))[:200]}
         for r in today + late_cron if r["status"] in ("FAILED", "ABORTED")),
        key=lambda f: f["at"] or "")

    # Failure streaks: same step failing N+ days in a row AND not yet recovered.
    # A step that failed Mon+Tue but succeeded Wed is historical noise, not actionable.
    streaks = read_sql(
        """
        WITH latest_status AS (
            SELECT step_name,
                   status,
                   ROW_NUMBER() OVER (PARTITION BY step_name ORDER BY id DESC) AS rn
            FROM pipeline_log
            WHERE status IN ('SUCCESS', 'FAILED')
        ),
        currently_broken AS (
            SELECT step_name FROM latest_status WHERE rn = 1 AND status = 'FAILED'
        )
        SELECT pl.step_name,
               COUNT(DISTINCT pl.run_date) AS n_days,
               MAX(pl.error_message) AS sample_error
        FROM pipeline_log pl
        JOIN currently_broken cb ON cb.step_name = pl.step_name
        WHERE pl.status = 'FAILED'
          AND pl.run_date >= date('now', ?)
        GROUP BY pl.step_name
        HAVING n_days >= ?
        ORDER BY n_days DESC
        """,
        params=[f"-{since_days + FAILURE_STREAK_DAYS} days", FAILURE_STREAK_DAYS],
    )
    # Exempt best-effort sources' heal steps: a `watchdog_<table>_heal` for a table in
    # BEST_EFFORT_STALE can't be healed by re-running (the upstream source has no data),
    # so its "failed N days" is not a systemic failure → don't escalate to CRITICAL.
    from db import BEST_EFFORT_STALE
    _exempt = {f"watchdog_{t}_heal" for t in BEST_EFFORT_STALE}
    out["failed_streaks"] = [
        {"step": r["step_name"], "days": int(r["n_days"]), "sample_error": (r["sample_error"] or "")[:200]}
        for _, r in streaks.iterrows()
        if r["step_name"] not in _exempt and not r["step_name"].startswith("endpoint_audit_")
    ]
    out["last_run_status"] = "FAILED" if out["failed_steps_today"] else "SUCCESS"
    return out



def pipeline_verdicts(p):
    """A step whose FINAL state is failed pages when it is critical
    (checks.critical_steps); a streak always pages. Except a step in
    config.NON_PAGING_STEPS (a shadow job, a gap-fill): WARN however long it fails."""
    from checks import critical_steps
    from config import NON_PAGING_STEPS
    crit = critical_steps()
    streak = {s["step"]: s for s in p["failed_streaks"]}
    today = {f["step"]: f for f in p["failed_steps_today"]}
    out = []
    for step in dict.fromkeys([*streak, *today]):
        s = streak.get(step)
        pages = (s or step in crit) and step not in NON_PAGING_STEPS
        out.append(verdict(f"PIPELINE_STEP:{step}", step, CRITICAL if pages else WARN, FAIL,
                           s["sample_error"] if s else today[step]["error"], code="PIPELINE_STEP",
                           message=(f"{step} is failing and has not recovered" if s
                                    else f"{step} failed in the latest run")))
    return out



def watchdog_facts():
    """Last watchdog run summary from pipeline_log."""
    out = {"last_run": None, "age_hours": None, "healed": 0, "failed": 0, "skipped": 0}
    df = read_sql(
        "SELECT step_name, status, started_at FROM pipeline_log "
        "WHERE step_name LIKE 'watchdog_%' "
        "ORDER BY started_at DESC LIMIT 100"
    )
    if df.empty:
        return out
    out["last_run"] = df.iloc[0]["started_at"]
    out["age_hours"] = (datetime.now() - datetime.fromisoformat(out["last_run"])).total_seconds() / 3600
    same_day = df[df["started_at"].str[:10] == out["last_run"][:10]]
    for key, status in (("healed", "SUCCESS"), ("failed", "FAILED"), ("skipped", "SKIPPED")):
        out[key] = int((same_day["status"] == status).sum())
    return out



def watchdog_verdicts(w):
    if w["last_run"] is None:
        return [verdict("WATCHDOG", "freshness_watchdog", CRITICAL, FAIL, "", code="WATCHDOG",
                        message="The self-healing watchdog has never run")]
    if w["age_hours"] > WATCHDOG_MAX_AGE_H:
        return [verdict("WATCHDOG", "freshness_watchdog", WARN, FAIL, f"last run {w['last_run'][:16]}",
                        code="WATCHDOG", message=f"The self-healing watchdog last ran {w['age_hours']:.0f} hours ago")]
    return []



# ═══════════════════════════ Did the data arrive? ═══════════════════════════

def table_facts():
    """Freshness breakdown from data_health()."""
    # cache_ttl lets this share the scan with cockpit's get_data_freshness on a
    # cold /system load (same 60s window) instead of recomputing the ~7s scan.
    df = data_health(cache_ttl=60)

    def rows(status):
        return [(r["table"], r["age_days"], r["threshold_days"], r["produced_by"])
                for _, r in df[df["freshness"] == status].iterrows()]
    return {"fresh": int((df["freshness"] == "FRESH").sum()),
            "stale": rows("STALE"), "outdated": rows("OUTDATED"),
            "empty": df[df["status"] == "EMPTY"]["table"].tolist()}



def freshness_verdicts(t):
    """Past the limit warns; more than twice past it pages when the table is on the
    email's critical path (checks.critical_tables). A best-effort table (its upstream
    legitimately has nothing new: db.BEST_EFFORT_STALE, the same list the watchdog and
    the post-step check exempt) is tolerated. EMPTY follows checks.empty_table_severity."""
    from checks import critical_tables, empty_table_severity
    from db import BEST_EFFORT_STALE
    crit = critical_tables()
    out = []
    for late, sev_of in ((t["outdated"], lambda tbl: CRITICAL if tbl in crit else WARN), (t["stale"], lambda tbl: WARN)):
        for tbl, age, limit, producer in late:
            best_effort = tbl in BEST_EFFORT_STALE
            out.append(verdict(f"TABLE_STALE:{tbl}", tbl, INFO if best_effort else sev_of(tbl), FAIL,
                               "best-effort source: nothing new upstream is normal" if best_effort else f"written by {producer}",
                               code="TABLE_STALE", message=f"{tbl} has not updated for {age:.0f} days (limit {limit:.0f})"))
    for tbl in t.get("empty", []):
        sev = empty_table_severity(tbl)
        if sev != OK:
            out.append(verdict(f"TABLE_EMPTY:{tbl}", tbl, sev, FAIL,
                               {INFO: "feature not live yet", WARN: "new or optional: not on the picks path"}.get(sev, ""),
                               code="TABLE_EMPTY", message=f"{tbl} is empty"))
    return out



def feed_facts():
    """Per-feed state + verdicts (plan 0018: probes, row volumes, cross-source reconcile)."""
    from checks.feeds import feed_state, feed_verdicts as per_feed
    rows = feed_state()
    return {"rows": rows, "verdicts": per_feed(rows)}


def feed_verdicts(f):
    """checks.feeds verdicts, filed under their check (FAMILY). Three or more 'no
    recent probe' collapse into one — that is the probe cron being dead, not N
    separate feed problems."""
    vs = [dict(v, code=FAMILY.get(v["code"], v["code"]), symptom=v["code"]) for v in f.get("verdicts") or []]
    missing = [v for v in vs if v["symptom"] == "FEED_CANARY_MISSING"]
    if len(missing) >= 3:
        vs = [v for v in vs if v["symptom"] != "FEED_CANARY_MISSING"]
        vs.append(verdict("FEED_PROBE:canary_cron", "canary cron", WARN, FAIL, ", ".join(v["target"] for v in missing),
                          code="FEED_PROBE",
                          message=f"{len(missing)} feeds have no recent probe: is `run.sh canary` (02:45 UTC) running?"))
    return vs




# ═══════════════════════════ Is the data right? ═══════════════════════════

def data_facts():
    """Every data check's verdict, passing ones included (the catalog shows them)."""
    import checks
    return {"verdicts": checks.run()}


def data_verdicts(d):
    """The failing data checks, plus the ones that had nothing to look at."""
    return [v for v in d["verdicts"] if v["status"] != PASS] + _vacuous(d["verdicts"])


def _vacuous(data):
    """Data checks that passed on zero rows — one collapsed verdict. A column
    declared `may_be_empty` (checks/ranges.py) is expected to have nothing yet."""
    empty = [v["code"] for v in data if v["status"] == PASS and v.get("n_total") == 0 and not v.get("may_be_empty")]
    if not empty:
        return []
    return [verdict("CHECK_VACUOUS", f"{len(empty)} data checks", WARN, FAIL, ", ".join(empty), code="CHECK_VACUOUS",
                    message=f"{len(empty)} check(s) are checking nothing (0 rows in scope)")]



def gate_facts():
    """The write-time gates (validators/_verdicts.GATES): is each still writing verdicts?"""
    from validators._verdicts import GATES
    cols = ", ".join(
        f"MAX(CASE WHEN {g} IS NOT NULL THEN snapshot_date END) AS last_{i}, "
        f"SUM(CASE WHEN {g} IS NOT NULL AND snapshot_date >= date('now', '-{GATE_SILENT_DAYS} days') THEN 1 ELSE 0 END) AS recent_{i}"
        for i, g in enumerate(GATES))
    row = db.one(f"SELECT {cols} FROM trust_verdicts")
    return {"gates": [{"gate": col, "name": name, "means": means, "last": row.get(f"last_{i}"),
                       "dormant": not int(row.get(f"recent_{i}") or 0)}
                      for i, (col, (name, means)) in enumerate(GATES.items())]}


def gate_verdicts(g):
    dormant = [x for x in g["gates"] if x["dormant"]]
    if not dormant:
        return []
    detail = "; ".join(f"{x['name']} (last verdict {x['last'] or 'never'})" for x in dormant)
    return [verdict("TRUST_GATE_DORMANT", "trust_verdicts", WARN, FAIL, detail, code="TRUST_GATE_DORMANT",
                    message=f"{len(dormant)} of {len(g['gates'])} write-time data gates have gone silent")]


# ═══════════════════════════ Can today's picks be trusted? ═══════════════════════════

def integrity_facts():
    """Today's ranked stocks, and the ones the per-stock integrity checks failed or flagged."""
    latest = "pick_date = (SELECT MAX(pick_date) FROM daily_picks)"
    return {"n_picks": int(db.scalar(f"SELECT COUNT(*) FROM daily_picks WHERE {latest}", default=0) or 0),
            "rows": db.rows(f"SELECT sid, integrity_status, integrity_reasons FROM daily_picks "
                            f"WHERE {latest} AND integrity_status IN ('FAIL', 'WARN')")}


def integrity_verdicts(i):
    out = []
    for status, sev, what in (("FAIL", CRITICAL, "contradict themselves and were removed from the brief"),
                              ("WARN", WARN, "have a minor inconsistency")):
        rows = [r for r in i["rows"] if r["integrity_status"] == status]
        if rows:
            out.append(verdict(f"PICK_INTEGRITY:{status}", "daily_picks", sev, FAIL,
                               f"{rows[0]['sid']}: {(rows[0]['integrity_reasons'] or '')[:160]}",
                               code="PICK_INTEGRITY", message=f"{len(rows)} pick(s) {what}", sample=rows[0]["sid"]))
    return out



def dossier_facts():
    """Inspect the newest dossier file for hallucinated content.

    Returns { latest_file, n_total, n_thesis, n_validated, n_failed_validation,
              failed_samples: [{ticker, n_violations, sample}] }.
    """
    import glob as _glob
    import json as _json
    out = {
        "latest_file": None, "latest_date": None,
        "n_total": 0, "n_thesis": 0,
        "n_validated": 0, "n_failed_validation": 0,
        "failed_samples": [],
    }
    files = sorted(_glob.glob(str(ROOT / "output" / "dossiers_*.json")), reverse=True)
    if not files:
        return out
    latest = files[0]
    out["latest_file"] = Path(latest).name
    m = re.search(r"(\d{4}-\d{2}-\d{2})", Path(latest).name)
    if m:
        out["latest_date"] = m.group(1)
    with open(latest) as fh:
        data = _json.load(fh)
    out["n_total"] = len(data)
    for d in data:
        if not isinstance(d, dict) or not d.get("thesis"):
            continue
        out["n_thesis"] += 1
        v = d.get("validation")
        if v is None:
            continue                # legacy dossier (pre-validator) — neither pass nor fail
        if v.get("ok"):
            out["n_validated"] += 1
            continue
        out["n_failed_validation"] += 1
        if len(out["failed_samples"]) < 3 and v.get("violations"):
            sample = v["violations"][0]
            out["failed_samples"].append({
                "ticker": d.get("ticker", d.get("sid", "?")),
                "n_violations": len(v["violations"]),
                "sample": f"{sample['field']}: '{sample['snippet']}' ({sample['kind']})",
            })
    return out



def dossier_verdicts(d):
    if not d["n_failed_validation"]:
        return []
    samples = "; ".join(f"{s['ticker']}: {s['sample']}" for s in d["failed_samples"])
    return [verdict("DOSSIER_HALLUCINATION", d["latest_file"], CRITICAL, FAIL, samples,
                    code="DOSSIER_HALLUCINATION",
                    message=f"{d['n_failed_validation']} of {d['n_thesis']} AI write-ups put raw numbers in their prose")]



def endpoint_facts():
    """The cockpit endpoint audits whose newest run did not pass."""
    df = read_sql(
        """
        SELECT step_name, status, error_message FROM (
            SELECT step_name, status, error_message,
                   ROW_NUMBER() OVER (PARTITION BY step_name ORDER BY id DESC) AS rn
            FROM pipeline_log WHERE step_name LIKE 'endpoint_audit_%')
        WHERE rn = 1 AND status != 'SUCCESS'
        """)
    return {"rows": [{"endpoint": r["step_name"][len("endpoint_audit_"):], "status": r["status"],
                      "error": (r["error_message"] or "").strip()} for _, r in df.iterrows()]}



def endpoint_verdicts(e):
    out = []
    for r in e["rows"]:
        err = r["error"]
        sev = CRITICAL if "[CRITICAL]" in err else WARN if "[WARN]" in err else (CRITICAL if r["status"] == "FAILED" else WARN)
        out.append(verdict(f"COCKPIT_ENDPOINT:{r['endpoint']}", r["endpoint"], sev, FAIL, err[:240],
                           code="COCKPIT_ENDPOINT", message=f"Cockpit endpoint '{r['endpoint']}' failed its audit"))
    return out



# ═══════════════════════════ Is the model still sound? ═══════════════════════════

def factor_facts():
    """Rolling-window IC decay per wired (factor, tier) — tools.factor_decay."""
    from tools.factor_decay import analyze
    return {"decay": analyze()}


def decay_verdicts(f):
    decay = f["decay"]
    decayed = [r for r in decay if r.get("decayed")]
    if not decayed:
        return []
    detail = "; ".join(f"{r['weight_key']} {r['tier']} (long-run IC {r['ic_all']:+.3f}, last year {r['ic_recent']:+.3f}"
                       + (f", {r['gap_se']:.1f} standard errors below" if r.get("gap_se") is not None else "") + ")"
                       for r in decayed)
    return [verdict("FACTOR_DECAY", "wired factors", WARN, FAIL, detail, code="FACTOR_DECAY",
                    message=f"{len(decayed)} of {len(decay)} factor weights have lost their recent edge")]



# ═══════════════════════════ The registry ═══════════════════════════

AREAS = {   # key in the gathered state: (facts, verdicts)
    "pipeline":  (pipeline_facts,  pipeline_verdicts),
    "watchdog":  (watchdog_facts,  watchdog_verdicts),
    "tables":    (table_facts,     freshness_verdicts),
    "feeds":     (feed_facts,      feed_verdicts),
    "data":      (data_facts,      data_verdicts),
    "gates":     (gate_facts,      gate_verdicts),
    "integrity": (integrity_facts, integrity_verdicts),
    "dossiers":  (dossier_facts,   dossier_verdicts),
    "endpoints": (endpoint_facts,  endpoint_verdicts),
    "factors":   (factor_facts,    decay_verdicts),
}
