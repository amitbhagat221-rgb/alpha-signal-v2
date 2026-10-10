"""
The health report's one state (ADR 0059, ADR 0060).

    gather()           run every area of checks.system (facts, concurrently), turn
                       the facts into verdicts, and return the ONE state the
                       terminal block, the email, the push, the MCP and the ops
                       Health page all render. None of them derives its own.
    issues(state)      every failing verdict as one sorted issue list
    scorecard(...)     one row per question in checks.THEMES: OK / WATCH / BROKEN
    catalog(state)     every check the system runs, by question, with its status
                       now and when it last fired
    records(state)     today's status of every check, for checks.history

Everything from `verdicts` down is pure: it takes the gathered state (plain dicts,
one key per area) and never reads the DB. Tests hand it a synthetic state.

Two kinds of check, one shape:
    data checks     checks.run() — ranges, coverage, checks/custom.py. Each check
                    dict carries its own theme / message / why / fix.
    system checks   checks/system.py — SYSTEM_CHECKS (the meaning) and AREAS
                    (facts + verdicts per area).
"""

from datetime import datetime

from checks import CRITICAL, ERROR, INFO, OK, PASS, SEVERITY_RANK, THEMES, WARN, verdict
from checks.feeds import probe_tally
from checks.system import AREAS, FAMILY, SYSTEM_CHECKS  # noqa: F401  (FAMILY: re-exported for tests)

STANDING_DAYS = 14           # a WARN firing this many days running is no longer news: decide


# ─────────────────────── Gather: facts → state ───────────────────────

def gather():
    """The canonical health state: one key per area of checks.system.AREAS (an
    area that crashed holds {"error": …} and is reported as an issue, never
    swallowed), `history`, and what every surface renders:

        issues      CRITICAL + WARN — the ONE list
                    [{severity, theme, code, id, target, message, detail, why, fix,
                      days (firing in a row), standing}]
        tolerated   the INFO findings (measured, no action)
        scorecard   one row per question
        summary     {critical, warn, standing, verdict}
    """
    import concurrent.futures as cf

    from checks import history

    def safe(fn):
        try:
            return fn()
        except Exception as e:                      # noqa: BLE001 — reported as HEALTH_CHECK_CRASHED
            return {"error": f"{type(e).__name__}: {e}"}

    # The areas are independent (each opens its own read-only connection); the slow
    # pair (data checks, table freshness) overlaps instead of adding up.
    facts = {key: f for key, (f, _) in AREAS.items()} | {"history": history.read}
    state = {"as_of": datetime.now().isoformat(timespec="seconds")}
    with cf.ThreadPoolExecutor(max_workers=len(facts)) as ex:
        futures = {key: ex.submit(safe, fn) for key, fn in facts.items()}
        state.update({key: f.result() for key, f in futures.items()})
    return conclude(state)


def conclude(state):
    """Add issues, tolerated, scorecard and summary to a gathered state."""
    state["issues"], state["tolerated"] = issues(state)
    _one_streak(state)
    state["scorecard"] = scorecard(state["issues"], state)
    critical = sum(i["severity"] == CRITICAL for i in state["issues"])
    warn = len(state["issues"]) - critical
    standing = sum(i["standing"] for i in state["issues"])
    text = (f"⚠ {critical} CRITICAL, {warn} warn" if critical else f"⚠ {warn} warn" if warn else "✓ all healthy")
    if standing:
        text += f" ({standing} standing {STANDING_DAYS}+ days)"
    state["summary"] = {"critical": critical, "warn": warn, "standing": standing, "verdict": text}
    return state


def _one_streak(state):
    """One streak definition: the days an issue has been firing (`issue()["days"]`). The pipeline
    detector only decides WHETHER a step is stuck; the number every surface prints (Health's
    "day N", Flow's broken-steps table, the email) is the issue's, so they cannot differ."""
    pipe = _ok(state, "pipeline")
    if not pipe:
        return
    days = {i["id"]: i["days"] for i in state["issues"]}
    for s in pipe.get("failed_streaks") or []:
        s["days"] = days.get(f"PIPELINE_STEP:{s['step']}", s["days"])


# ─────────────────────── State → verdicts ───────────────────────

def _ok(state, key):
    """An area's facts, or None when it did not gather (missing, or crashed)."""
    part = state.get(key)
    return part if part is not None and not part.get("error") else None


def verdicts(state):
    """Every failing verdict of the gathered state, folded. A crashed area is a
    verdict of its own (HEALTH_CHECK_CRASHED), not a silent gap."""
    out = [verdict(f"HEALTH_CHECK_CRASHED:{key}", key, WARN, ERROR, part["error"], code="HEALTH_CHECK_CRASHED",
                   message=f"The '{key}' part of the health report crashed")
           for key, part in state.items() if isinstance(part, dict) and part.get("error")]
    for key, (_, build) in AREAS.items():
        if _ok(state, key) is not None:
            out += build(state[key])
    return fold(out)


def fold(vs):
    """One fact, one verdict. When a step is failing, two things follow from it and
    are not separate problems: the table it writes going stale, and the watchdog's
    attempt to heal that table failing too. Both move into the step's verdict (which
    takes the worse severity) instead of alarming again."""
    import graph
    from checks import dataset_table
    from config import PIPELINE_STEPS
    writes = {s["name"]: {dataset_table(d) for d in graph.writes(s)} for s in PIPELINE_STEPS}
    steps = [v for v in vs if v["code"] == "PIPELINE_STEP" and not _heal_table(v["target"])]

    def owner_of(v):
        table = v["target"] if v["code"] == "TABLE_STALE" else \
            _heal_table(v["target"]) if v["code"] == "PIPELINE_STEP" else None
        return next((s for s in steps if table and table in writes.get(s["target"], ())), None)

    out = []
    for v in vs:
        owner = owner_of(v)
        if owner is None:
            out.append(v)
            continue
        owner.setdefault("leaves", []).append(
            "the watchdog could not heal it either" if v["code"] == "PIPELINE_STEP" else v["message"])
        if SEVERITY_RANK[v["severity"]] < SEVERITY_RANK[owner["severity"]]:
            owner["severity"] = v["severity"]
    return out


def _heal_table(step):
    """The table a watchdog heal step re-runs for (`watchdog_<table>_heal`), else None."""
    return step[len("watchdog_"):-len("_heal")] if step.startswith("watchdog_") and step.endswith("_heal") else None


def family(v):
    """The catalog row a verdict belongs to: a data check's `family` (RANGE,
    COVERAGE_GAP) or its own code."""
    return v.get("family") or v["code"]


# ─────────────────────── The one issue list ───────────────────────

def issue(v, history=None):
    """A failing verdict in the shape every surface renders. `days` = how many
    recorded days in a row it has been firing, today included (1 = new today)."""
    meta = SYSTEM_CHECKS.get(v["code"], v)
    detail = v.get("detail") or ""
    if v.get("leaves"):
        detail = "; ".join(filter(None, [detail, "also: " + ", ".join(dict.fromkeys(v["leaves"]))]))
    days = 1 + ((history or {}).get("streaks") or {}).get(v["check_id"], 0)
    return {"severity": v["severity"], "theme": meta["theme"], "code": v["code"], "id": v["check_id"],
            "target": v["target"], "message": v["message"], "detail": detail,
            "why": meta["why"], "fix": meta["fix"], "table": v.get("table"), "sample": v.get("sample"),
            "days": days, "standing": v["severity"] == WARN and days >= STANDING_DAYS}


def issues(state):
    """(actionable, tolerated): CRITICAL + WARN issues, and the INFO ones, each
    sorted by severity, then new before standing, then question, then code."""
    order = list(THEMES)
    rows = sorted((issue(v, state.get("history")) for v in verdicts(state)),
                  key=lambda i: (SEVERITY_RANK[i["severity"]], i["standing"], order.index(i["theme"]), i["id"]))
    return ([i for i in rows if i["severity"] in (CRITICAL, WARN)],
            [i for i in rows if i["severity"] == INFO])


STATUS = {CRITICAL: "BROKEN", WARN: "WATCH", OK: "OK"}      # a question's answer


def scorecard(actionable, state):
    """One row per question: {theme, question, covers, status, critical, warn, facts}.
    `facts` is the one-line healthy summary, so a green row still says something."""
    facts = _facts(state)
    out = []
    for theme, (question, covers) in THEMES.items():
        mine = [i for i in actionable if i["theme"] == theme]
        crit = sum(i["severity"] == CRITICAL for i in mine)
        out.append({"theme": theme, "question": question, "covers": covers,
                    "status": STATUS[CRITICAL if crit else WARN if mine else OK],
                    "critical": crit, "warn": len(mine) - crit, "facts": facts.get(theme, "")})
    return out


def run_line(p):
    """The latest run in one sentence. Health and Flow both print it, so the count cannot differ.
    It counts what the run logged (DAG steps plus cron and datamodel jobs), not the DAG's declared steps."""
    return f"run of {p['last_run_date']}: {p['n_steps'] - len(p['failed_steps_today'])} of {p['n_steps']} logged steps ok"


def _facts(state):
    """Plain one-liners per question, from whatever gathered cleanly."""
    def part(key):
        return _ok(state, key)
    out = {}
    p, w = part("pipeline"), part("watchdog")
    if p and p.get("last_run_date"):
        out["ran"] = run_line(p) + (f" · watchdog healed {w['healed']}" if w and w.get("healed") else "")
    t, f = part("tables"), part("feeds")
    if t:
        n = t["fresh"] + len(t["stale"]) + len(t["outdated"])
        out["arrived"] = f"{t['fresh']} of {n} tracked tables fresh"
        n_pass, n_probed = probe_tally((f or {}).get("rows", []))
        if n_probed:
            out["arrived"] += f" · {n_pass} of {n_probed} feed probes pass"
    d = part("data")
    if d:
        vs = d["verdicts"]
        out["correct"] = f"{sum(v['status'] == PASS for v in vs)} of {len(vs)} data checks pass"
        fi = next((v for v in vs if v["code"] == "FACTOR_INPUT"), None)
        if fi and fi.get("n_total"):
            out["picks"] = f"{fi['n_total'] - (fi.get('n_bad') or 0)} of {fi['n_total']} factor inputs healthy"
    ig = part("integrity")
    if ig and ig.get("n_picks"):
        removed = sum(r["integrity_status"] == "FAIL" for r in ig["rows"])
        out["picks"] = " · ".join(filter(None, [f"{ig['n_picks']:,} stocks ranked", out.get("picks"),
                                                f"{removed} removed for contradicting themselves"]))
    fa = part("factors")
    if fa:
        out["model"] = (f"{len(fa['decay'])} factor weights checked · "
                        f"{sum(bool(r.get('decayed')) for r in fa['decay'])} losing edge")
    return out


# ─────────────────────── The catalog: every check, by question ───────────────────────

def catalog(state):
    """Every check the system runs: {theme, code, when, why, fix, severity, n_checks,
    failing: [..targets], status, last_fired, tracked_since}. Data checks that share
    a `family` (RANGE, COVERAGE_GAP) are one row. `last_fired` comes from the recorded
    history (None = not since tracking began on `tracked_since`)."""
    firing = {}
    for v in verdicts(state):
        firing.setdefault(family(v), []).append(v)
    hist = state.get("history") or {}
    last, since = hist.get("last_fired") or {}, hist.get("since")
    rows = []
    for code, c in SYSTEM_CHECKS.items():
        fs = firing.get(code, [])
        rows.append({"theme": c["theme"], "code": code, "when": c["when"], "why": c["why"], "fix": c["fix"],
                     "severity": c["severity"], "n_checks": None, "failing": [v["target"] for v in fs],
                     "status": _worst(fs)})
    fam = {}
    for v in (state.get("data") or {}).get("verdicts") or []:
        fam.setdefault(family(v), []).append(v)
    for code, vs in fam.items():
        head, fs = vs[0], [v for v in vs if v["status"] != PASS]
        rows.append({"theme": head["theme"], "code": code, "when": head.get("family_when") or head["message"],
                     "why": head["why"], "fix": head["fix"], "severity": head["rule"],
                     "n_checks": len(vs) if len(vs) > 1 else None,
                     "failing": [v["target"] if len(vs) > 1 else v["detail"] for v in fs], "status": _worst(fs)})
    today = (state.get("as_of") or "")[:10]
    for r in rows:
        r["last_fired"] = today if r["status"] in (CRITICAL, WARN) else last.get(r["code"])
        r["tracked_since"] = since
    order = list(THEMES)
    return sorted(rows, key=lambda r: (order.index(r["theme"]), r["code"]))


def _worst(vs):
    return min((v["severity"] for v in vs), key=SEVERITY_RANK.get, default=OK)


def records(state):
    """Today's status of every check, for the history: [(subject, family code, status,
    n_bad)]. A firing verdict records its severity under its id; a check with nothing
    firing records one PASS under its code."""
    out, fired = [], set()
    for v in verdicts(state):
        out.append((v["check_id"], family(v), v["severity"], v.get("n_bad")))
        fired.add(family(v))
    passing = set(SYSTEM_CHECKS) | {family(v) for v in (state.get("data") or {}).get("verdicts") or []}
    out += [(code, code, PASS, 0) for code in sorted(passing - fired)]
    return out
