"""
Checks — the Check block of ADR 0052 (plan 0015 Phase 4, ADR 0059).

A check is a predicate on a dataset or a node output. Every check answers ONE of
the five questions in THEMES, says in plain words what it found (`message`), why
it matters (`why`) and what to do first (`fix`). This package is the ONE runner;
every check yields a verdict row

    {check_id, target, severity, status, detail, ...}     status ∈ PASS / FAIL / ERROR

and every surface is a view over those rows: checks.report (the ONE state behind
the terminal block, the email, the push, the MCP and the ops Health page), the
picks email's pre-send banner (run(theme="picks")), tools/data_sanity (the failing
data verdicts) and health.compute_db_health (the per-table validity score).

The package, one job per module:
    __init__   constants, the data-check runner (run), criticality, post_step
    ranges     the legal values of a column                 custom   the semantic checks
    model      checks on today's ranking (factor inputs)    feeds    per-feed state + verdicts
    system     system checks: meaning + (facts, verdicts) per area
    report     gather → issues → scorecard → catalog        history  when each check last fired

Where each check comes from — declared once, never hand-copied:
    column range / enum      checks/ranges.py COLUMNS (factor columns reuse
                             factors.VALIDATION_RANGES)
    per-stock coverage       tables.TABLES `coverage`
    freshness / empty        db.data_health() (tables.TABLES + the producer's cadence)
    semantic                 checks/custom.py CHECKS
    system (runs, feeds…)    checks/system.py SYSTEM_CHECKS + AREAS
    alert criticality        DERIVED: the email's critical path (graph.py)
    post-step (invariant 4)  graph.writes(step) + the freshness rule — post_step()

Plain functions over dicts (ADR 0004).
"""

CRITICAL, WARN, INFO, OK = "CRITICAL", "WARN", "INFO", "OK"
SEVERITY_RANK = {CRITICAL: 0, WARN: 1, INFO: 2, OK: 3}
PASS, FAIL, ERROR = "PASS", "FAIL", "ERROR"

# What a severity asks of the reader — the only three levels, on every surface.
SEVERITY_MEANING = {
    CRITICAL: "act today: today's picks or the morning email are affected",
    WARN: "look this week: something is degraded, the picks still stand",
    INFO: "known and tolerated: measured, no action needed",
}

# The five questions. Every check belongs to exactly one (tests/test_checks.py).
THEMES = {
    "ran":     ("Did everything run?", "pipeline steps, cron jobs, the self-healing watchdog"),
    "arrived": ("Did the data arrive?", "feeds, table freshness, how many stocks each source covers"),
    "correct": ("Is the data right?", "legal ranges, sources agreeing with each other, mis-mapped fields"),
    "picks":   ("Can today's picks be trusted?", "the factor inputs behind today's ranking, the ranking itself, the AI write-ups, the cockpit"),
    "model":   ("Is the model still sound?", "wired factors losing their predictive edge"),
}
MEANING = ("theme", "why", "fix")      # what every check declares besides its rule
_CARRIED = MEANING + ("family", "family_when", "may_be_empty")      # check fields copied onto its verdict (+ rule())


def verdict(check_id, target, severity, status, detail="", **extra):
    """One verdict row. `extra` carries the surface fields (message, code, n_bad…)."""
    return {"check_id": check_id, "target": target, "severity": severity,
            "status": status, "detail": detail, **extra}


def severity_for(pct, critical_pct=10, warn_pct=1):
    """Severity from the % of rows violating a check."""
    if pct >= critical_pct:
        return CRITICAL
    if pct >= warn_pct:
        return WARN
    return INFO


# ─────────────────────── Criticality (derived, never hand-kept) ───────────────────────

def critical_steps(steps=None):
    """Steps whose failure pages: those marked `critical` (they abort the run), the
    email itself, and every step whose OUTPUT the email transitively needs
    (graph.ancestors over blocking reads, computed on the full step list)."""
    import graph
    if steps is None:
        from config import PIPELINE_STEPS as steps
    names = {s["name"] for s in steps}
    out = {s["name"] for s in steps if s.get("critical")}
    out |= graph.ancestors(steps, graph.EMAIL, needed_only=True)
    if graph.EMAIL in names:
        out.add(graph.EMAIL)
    return out


def dataset_table(dataset):
    """The data_health() table a graph dataset maps to: tables are themselves,
    'file:<name>' is the virtual table `_file_<name>` of config.FILE_OUTPUTS."""
    if not dataset.startswith("file:"):
        return dataset
    from config import FILE_OUTPUTS
    virtual = "_file_" + dataset[len("file:"):]
    return virtual if any(f["virtual_table"] == virtual for f in FILE_OUTPUTS) else None


def critical_tables(steps=None):
    """Tables whose OUTDATED state pages: every output of a critical step."""
    import graph
    if steps is None:
        from config import PIPELINE_STEPS as steps
    crit = critical_steps(steps)
    out = set()
    for s in steps:
        if s["name"] in crit:
            out |= {t for t in map(dataset_table, graph.writes(s)) if t}
    return out


# ─────────────────────── Data checks (range · coverage · custom) ───────────────────────

def range_checks():
    """One check per checks.ranges.COLUMNS entry. Severity is derived: a column on
    the email's critical path is CRITICAL from 1% of rows, anything else from 10%;
    WARN from 1%; INFO below."""
    from checks import ranges
    crit_tables = critical_tables()
    out = []
    for (table, column) in ranges.COLUMNS:
        out.append({
            "code": f"RANGE:{table}.{column}",
            "table": table, "column": column,
            "theme": "correct", "family": "RANGE",
            "family_when": "A column holds values outside its legal range (one rule per column, in checks/ranges.py)",
            "severity_text": "CRITICAL from 1% of rows on a table the morning email needs (10% elsewhere), WARN from 1%, INFO below",
            "message": f"{table}.{column} has values outside {ranges.describe(table, column)}",
            "why": "A value outside its legal range is a parse or unit error, and it flows into every factor that reads the column.",
            "fix": f"Look at the offending rows of {table}, then fix the producer's parser. "
                   "Widen the range in checks/ranges.py only if the value is real.",
            "critical_pct": 1 if table in crit_tables else 10, "warn_pct": 1,
            "range": True, "may_be_empty": ranges.COLUMNS[(table, column)].get("may_be_empty"),
        })
    return out


def coverage_checks():
    """One per-stock coverage check per table with a tables.TABLES `coverage` gate."""
    from db import COVERAGE_THRESHOLDS
    out = []
    for tbl, (gap_pct, severe_pct) in COVERAGE_THRESHOLDS.items():
        # critical_pct / warn_pct are % of the universe MISSING — the inverse of
        # the gate's "% present".
        out.append({
            "code": f"COVERAGE_GAP_AUTO_{tbl.upper()}",
            "table": tbl, "column": "sid",
            "theme": "arrived", "family": "COVERAGE_GAP",
            "family_when": "A table has no row at all for some stocks (gates in tables.TABLES `coverage`)",
            "severity_text": "per table: WARN below its coverage gate, CRITICAL below its severe gate, INFO for a few missing stocks",
            "message": f"{tbl} has no row at all for some stocks (it should cover {gap_pct:.0f}% of the universe)",
            "why": "A table can be fresh and still miss a stock; that stock is then ranked on fewer factors than its peers.",
            "fix": f"Rerun the producer of {tbl} for the missing stocks (the example names one). "
                   "The gate is the table's `coverage` in tables.TABLES.",
            "critical_pct": 100 - severe_pct,
            "warn_pct": 100 - gap_pct,
            "sql": f"""
                SELECT
                    (SELECT COUNT(*) FROM stocks WHERE sid NOT IN (SELECT DISTINCT sid FROM {tbl})) AS n_bad,
                    (SELECT COUNT(*) FROM stocks) AS n_total,
                    (SELECT sid || ' (' || ticker || ', ' || cap_tier || ')' FROM stocks
                     WHERE sid NOT IN (SELECT DISTINCT sid FROM {tbl}) LIMIT 1) AS sample
            """,
        })
    return out


def all_checks():
    """Every data check: the custom semantic ones, then the derived range and
    coverage checks."""
    from checks.custom import CHECKS
    return list(CHECKS) + range_checks() + coverage_checks()


def range_counts(conn, table):
    """{column: (n_bad, n_non_null)} for every registered column of `table` — one
    table scan. Columns absent from the live table are skipped."""
    from checks import ranges
    cols = ranges.for_table(table)
    present = {r[1] for r in conn.execute(f"PRAGMA table_info([{table}])")}
    cols = [c for c in cols if c in present]
    if not cols:
        return {}
    exprs = []
    for c in cols:
        exprs += [f"SUM(CASE WHEN {ranges.bad_sql(table, c)} THEN 1 ELSE 0 END)", f"COUNT([{c}])"]
    row = conn.execute(f"SELECT {', '.join(exprs)} FROM [{table}]").fetchone()
    return {c: (int(row[2 * i] or 0), int(row[2 * i + 1] or 0)) for i, c in enumerate(cols)}


def _severity(check, pct):
    if check.get("severity") is not None:
        return check["severity"]
    if pct is None:
        return WARN
    return severity_for(pct, check.get("critical_pct", 10), check.get("warn_pct", 1))


def rule(check):
    """The check's severity rule in words (the catalog shows it)."""
    if check.get("severity_text"):
        return check["severity_text"]
    if check.get("severity") is not None:
        return f"always {check['severity']}"
    crit, warn = check.get("critical_pct", 10), check.get("warn_pct", 1)
    middle = "" if warn >= crit else ", WARN for any row" if warn == 0 else f", WARN from {warn:g}%"
    return f"CRITICAL from {crit:g}% of rows{middle}" + ("" if warn == 0 else ", INFO below")


def _result(check, n_bad, n_total, sample, extra=None, severity=None):
    pct = (100.0 * n_bad / n_total) if n_total else None
    failed = n_bad > 0
    sev = (severity or _severity(check, pct)) if failed else OK
    counted = n_total and n_total > 1           # a yes/no check has nothing to count
    detail = " · ".join(filter(None, [
        f"{n_bad:,} of {n_total:,} ({pct:.1f}%)" if counted else "",
        f"e.g. {sample}" if sample not in (None, "") else ""])) if failed else ""
    return verdict(check["code"], f"{check.get('table')}.{check.get('column')}", sev,
                   FAIL if failed else PASS, detail,
                   code=check["code"], table=check.get("table"), column=check.get("column"),
                   message=check["message"], n_bad=n_bad, n_total=n_total,
                   pct=round(pct, 1) if pct is not None else None, sample=sample,
                   rule=rule(check), **{k: check.get(k) for k in _CARRIED}, **(extra or {}))


def _run_one(check, conn, range_cache):
    if check.get("range"):
        table, column = check["table"], check["column"]
        if table not in range_cache:
            try:
                range_cache[table] = range_counts(conn, table)
            except Exception:           # table absent on this DB
                range_cache[table] = {}
        n_bad, n_total = range_cache[table].get(column, (0, 0))
        sample = None
        if n_bad:
            from checks import ranges
            sample = conn.execute(f"SELECT [{column}] FROM [{table}] "
                                  f"WHERE {ranges.bad_sql(table, column)} LIMIT 1").fetchone()[0]
        return _result(check, n_bad, n_total, sample)
    if "sql" in check:
        import pandas as pd
        df = pd.read_sql_query(check["sql"], conn)
        row = {} if df.empty else df.iloc[0].to_dict()
        return _result(check, int(row.get("n_bad", 0) or 0), int(row.get("n_total") or 0),
                       row.get("sample"))
    res = check["fn"]() or {}
    extra = {k: v for k, v in res.items() if k not in ("n_bad", "n_total", "sample", "severity")}
    return _result(check, int(res.get("n_bad", 0) or 0), int(res.get("n_total") or 0),
                   res.get("sample"), extra, severity=res.get("severity"))


def run(only=None, theme=None):
    """Run every data check — or only the one whose code == `only`, or only those
    answering the question `theme`. Returns one verdict per check: PASS (severity
    OK), FAIL (severity by the check's rule) or ERROR (the check itself raised — WARN)."""
    from db import get_db
    out, range_cache = [], {}
    with get_db() as conn:
        for check in all_checks():
            if (only and check["code"] != only) or (theme and check["theme"] != theme):
                continue
            try:
                out.append(_run_one(check, conn, range_cache))
            except Exception as e:
                out.append(verdict(check["code"], f"{check.get('table')}.{check.get('column')}",
                                   WARN, ERROR, f"{type(e).__name__}: {e}",
                                   code=check["code"], table=check.get("table"),
                                   column=check.get("column"),
                                   message=f"The check {check['code']} itself crashed ({type(e).__name__}: {e})",
                                   n_bad=None, n_total=None, pct=None, sample=None,
                                   rule=rule(check), **{k: check.get(k) for k in _CARRIED}))
    return out


# ─────────────────────── Empty-table policy ───────────────────────

def empty_table_severity(table):
    """Severity of an EMPTY table. A quarantine mirror that is empty is clean (OK);
    a table registered `may_be_empty` is a feature not live yet (INFO); anything
    else is a producer that wrote 0 rows where rows are expected (CRITICAL) -- unless
    the table is not on the picks path, which its producer declares:
      - every feed that writes it is still a candidate / wanted (not scheduled): INFO;
      - every feed that writes it is on probation (scheduled, not yet trusted): WARN;
      - a file output marked `optional` in config.FILE_OUTPUTS (readers fall back): WARN."""
    from tables import TABLES
    e = TABLES.get(table, {})
    if e.get("kind") == "QUARANTINE":
        return OK
    if e.get("may_be_empty"):
        return INFO
    from config import FILE_OUTPUTS
    if any(f["virtual_table"] == table and f.get("optional") for f in FILE_OUTPUTS):
        return WARN
    import feeds
    status = {f["status"] for f in feeds.FEEDS.values() if table in (f.get("writes") or [])}
    if status and status <= set(feeds.DISCOVERY):
        return INFO
    if status and "production" not in status and "degraded" not in status:
        return WARN
    return CRITICAL


# ─────────────────────── Post-step check (invariant 4) ───────────────────────

def post_step(step_spec):
    """Failures of a step's post-condition, checked right after it ran: every table
    it declares writing (graph.writes, `file:*` hand-offs skipped) must not be
    OUTDATED by the freshness rule db.data_health uses (the table's primary
    producer cadence + tables.TABLES `stale_days`). Zero rows written into a table
    that is still fresh is a no-op, not a failure. A `best_effort` table (upstream
    legitimately carries no fresh data) is exempt, as it is from heals and streak
    alerts. Returns [] when the step passes."""
    import graph
    from db import (BEST_EFFORT_STALE, _compute_freshness, _table_date_range, get_db,
                    table_step_meta)
    meta = table_step_meta()
    fails = []
    with get_db() as conn:
        for table in graph.writes(step_spec):
            if table.startswith("file:") or table in BEST_EFFORT_STALE:
                continue
            try:
                _, latest, _ = _table_date_range(conn, table)
            except Exception as e:
                fails.append(f"{table}: unreadable after {step_spec['name']} ({type(e).__name__}: {e})")
                continue
            status, age, threshold = _compute_freshness(
                latest, meta.get(table, {}).get("frequency"), table)
            if status == "OUTDATED":
                fails.append(f"{table} is OUTDATED after {step_spec['name']} "
                             f"({age}d old, threshold {threshold}d)")
    return fails
