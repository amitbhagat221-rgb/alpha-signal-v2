"""
Feed checks (plan 0018): per-feed state and the verdicts the health report pages on.

feed_state()     one row per feed: registry facts (feeds.py) + derived tier/resilience
                 + latest canary (feed_checks) + latest run (pipeline_log) + freshness
                 of what it writes (db.data_health) — the ops Data Supply page renders it.
feed_verdicts()  checks/ verdict rows. Severity follows the tier (plan 0018 §2.2):

  FEED_CANARY_FAIL      T1: CRITICAL on shape drift (D) or auth (C) at once, or on a
                        2nd consecutive failure; a first transport blip is WARN.  T2: WARN.
  FEED_CANARY_WARN      T1 WARN (additive drift, dead fallback route…); T2 INFO
  FEED_CANARY_ERROR     WARN — the canary itself crashed (our bug, not the upstream)
  FEED_CANARY_MISSING   WARN — a T1 feed with no canary verdict in 36 h (T2: 8 days):
                        the canary cron is dead or skipped it
  FEED_ORPHAN           WARN — a live feed nothing schedules (class H)
  FEED_NO_FALLBACK      WARN — a T1 feed with neither a live fallback nor a serve-stale limit
  FEED_SINGLE_SOURCE    INFO — a T1 feed that can only serve stale (page, not email)
  FEED_REGISTRY_DRIFT   WARN — a source module / source step / RAW table no feed covers
"""

import json
from datetime import datetime, timedelta

from checks import CRITICAL, FAIL, INFO, WARN, verdict

MISSING_HOURS = {"T1": 36, "T2": 8 * 24}


def _latest_canaries():
    from db import read_sql
    try:
        df = read_sql("""SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY feed ORDER BY id DESC) rn
                         FROM feed_checks WHERE check_kind = 'canary') WHERE rn <= 2""")
        rate = read_sql("""SELECT feed, COUNT(*) n, SUM(status = 'PASS') n_pass FROM feed_checks
                           WHERE check_kind = 'canary' AND run_date >= date('now', '-30 days') GROUP BY feed""")
    except Exception:                                     # table not created yet (fresh DB)
        return {}, {}
    last = {}
    for r in df.sort_values("rn").to_dict("records"):
        last.setdefault(r["feed"], []).append(r)
    return last, {r["feed"]: (int(r["n"]), int(r["n_pass"] or 0)) for r in rate.to_dict("records")}


def _latest_runs(names):
    from db import read_sql
    if not names:
        return {}
    ph = ",".join("?" * len(names))
    df = read_sql(f"""SELECT step_name, status, finished_at, started_at, rows_affected, error_message FROM (
                        SELECT *, ROW_NUMBER() OVER (PARTITION BY step_name ORDER BY id DESC) rn FROM pipeline_log
                        WHERE step_name IN ({ph}) AND status IN ('SUCCESS', 'FAILED', 'COVERAGE_GAP', 'COVERAGE_SEVERE'))
                      WHERE rn = 1""", params=list(names))
    return {r["step_name"]: r for r in df.to_dict("records")}


def _freshness():
    from db import data_health
    try:
        df = data_health(cache_ttl=60)
    except Exception:
        return {}
    return {r["table"]: r for r in df.to_dict("records")}


_FRESH_RANK = {"OUTDATED": 0, "STALE": 1, "NO_DATE_ANCHOR": 2, "FRESH": 3}


def registry_drift():
    """[(what, name)] the registry does not cover — runtime twin of tests/test_feeds.py."""
    import pkgutil
    from pathlib import Path

    import feeds
    from config import PIPELINE_STEPS
    from tables import TABLES
    covered_mods = {m for f in feeds.FEEDS.values() for m in f.get("modules") or []}
    covered_steps = {s for name in feeds.FEEDS for s in feeds.steps_of(name)}
    covered_tables = {t for f in feeds.FEEDS.values() for t in f.get("writes") or []}
    src = Path(__file__).resolve().parent.parent / "sources"
    out = []
    for m in pkgutil.iter_modules([str(src)]):
        if not m.name.startswith("_") and m.name != "canaries" and f"sources.{m.name}" not in covered_mods:
            out.append(("module", f"sources.{m.name}"))
    for s in PIPELINE_STEPS:
        if not isinstance(s, str) and s["module"].startswith("sources.") and s["name"] not in covered_steps:
            out.append(("step", s["name"]))
    for t, e in TABLES.items():
        if e.get("kind") == "RAW" and t not in covered_tables and t not in feeds.NON_FEED_TABLES:
            out.append(("table", t))
    return out


def feed_state():
    """One dict per feed (registry order), everything the page and the verdicts need."""
    import feeds
    tiers = feeds.tiers()
    canaries, rates = _latest_canaries()
    runs = _latest_runs({s for name in feeds.FEEDS for s in feeds.log_steps(name)})
    fresh = _freshness()
    rows = []
    for name, f in feeds.FEEDS.items():
        c = canaries.get(name, [])
        last = c[0] if c else None
        gates = []
        if last is not None and last.get("detail"):
            try:
                gates = json.loads(last["detail"]).get("gates", [])
            except ValueError:
                gates = []
        run_rows = [runs[s] for s in feeds.log_steps(name) if s in runs]
        run = max(run_rows, key=lambda r: r.get("finished_at") or r.get("started_at") or "") if run_rows else None
        tables = []
        for t in f.get("writes") or []:
            h = fresh.get(t)
            if h is not None:
                tables.append({"table": t, "freshness": h.get("freshness"), "age_days": h.get("age_days"),
                               "latest": h.get("latest_date"), "rows": h.get("rows")})
        worst = min(tables, key=lambda x: _FRESH_RANK.get(x["freshness"], 3)) if tables else None
        n, n_pass = rates.get(name, (0, 0))
        rows.append({
            "feed": name, "family": f["family"], "family_label": feeds.FAMILIES[f["family"]][0],
            "status": f["status"], "tier": tiers.get(name), "what": f.get("what", ""),
            "schedule": f.get("schedule") or [], "cadence": f.get("cadence"),
            "hosts": f.get("hosts") or [], "routes": f.get("routes") or [],
            "resilience": feeds.resilience(name) if f["status"] in feeds.LIVE else None,
            "serve_stale_days": f.get("serve_stale_days"), "fallback_plan": f.get("fallback_plan"),
            "canary": f.get("canary"), "canary_waiver": f.get("canary_waiver"),
            "canary_every": feeds.canary_every(name) if f["status"] in feeds.LIVE else None,
            "canary_last": last, "canary_prev": c[1] if len(c) > 1 else None, "canary_gates": gates,
            "pass_rate_30d": (n_pass / n) if n else None, "checks_30d": n,
            "last_run": run, "tables": tables, "worst_freshness": worst,
            "derived_from": f.get("derived_from") or [], "pit": f.get("pit"), "tos": f.get("tos"),
            "notes": f.get("notes"), "probe": f.get("probe"), "ref": f.get("ref"), "need": f.get("need"),
        })
    return rows


def _age_hours(ts):
    try:
        return (datetime.now() - datetime.fromisoformat(str(ts).replace("T", " ").split(".")[0])).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def feed_verdicts(rows, drift=None, now=None):
    """Verdict rows from feed_state() rows (plan 0018 §2.2 severities)."""
    import feeds
    out = []
    for r in rows:
        if r["status"] not in feeds.LIVE or r["tier"] not in ("T1", "T2"):
            continue
        name, tier, last, prev = r["feed"], r["tier"], r["canary_last"], r["canary_prev"]
        t1 = tier == "T1"
        if last is not None:
            st, sym = last["status"], last.get("symptom")
            bad = "; ".join(f"{g[0]}: {g[3]}" for g in r["canary_gates"] if g[1] != "PASS")[:240]
            label = feeds.SYMPTOM_CLASSES.get(sym, ("?",))[0] if sym else ""
            if st == "FAIL":
                repeat = prev is not None and prev["status"] == "FAIL"
                sev = CRITICAL if t1 and (sym in ("C", "D") or repeat) else WARN
                out.append(verdict(f"FEED_CANARY_FAIL:{name}", name, sev, FAIL, bad, code="FEED_CANARY_FAIL",
                                   message=f"{name} ({tier}) canary FAILED — class {sym} {label}"
                                           + (" (2nd in a row)" if repeat else "")))
            elif st == "WARN":
                out.append(verdict(f"FEED_CANARY_WARN:{name}", name, WARN if t1 else INFO, FAIL, bad,
                                   code="FEED_CANARY_WARN", message=f"{name} ({tier}) canary WARN — class {sym} {label}"))
            elif st == "ERROR":
                out.append(verdict(f"FEED_CANARY_ERROR:{name}", name, WARN, FAIL, bad, code="FEED_CANARY_ERROR",
                                   message=f"{name} canary crashed (canary code, not the upstream)"))
        if r["canary"]:
            age = _age_hours(last["checked_at"]) if last is not None else None
            if age is None or age > MISSING_HOURS[tier]:
                out.append(verdict(f"FEED_CANARY_MISSING:{name}", name, WARN, FAIL,
                                   "never probed" if age is None else f"last canary {age:.0f} h ago",
                                   code="FEED_CANARY_MISSING",
                                   message=f"{name} ({tier}) has no recent canary verdict — is `run.sh canary` running?"))
        if not r["schedule"]:
            out.append(verdict(f"FEED_ORPHAN:{name}", name, WARN, FAIL, r.get("notes") or "",
                               code="FEED_ORPHAN", message=f"{name} is live but nothing schedules it (class H)"))
        if t1 and r["resilience"] == "none":
            out.append(verdict(f"FEED_NO_FALLBACK:{name}", name, WARN, FAIL, r.get("fallback_plan") or "",
                               code="FEED_NO_FALLBACK", message=f"{name} (T1) has no fallback and no serve-stale limit"))
        elif t1 and r["resilience"] == "serve-stale":
            out.append(verdict(f"FEED_SINGLE_SOURCE:{name}", name, INFO, FAIL, r.get("fallback_plan") or "",
                               code="FEED_SINGLE_SOURCE",
                               message=f"{name} (T1) is single-source — serves stale ≤{r['serve_stale_days']}d if it dies"))
    for what, name in (drift if drift is not None else registry_drift()):
        out.append(verdict(f"FEED_REGISTRY_DRIFT:{what}:{name}", name, WARN, FAIL, what,
                           code="FEED_REGISTRY_DRIFT", message=f"{what} {name} is not covered by any feed (feeds.py)"))
    return out
