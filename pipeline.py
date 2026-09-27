"""
Alpha Signal v2 — Pipeline Orchestrator

Runs the steps in the order graph.py derives, logs everything
to pipeline_log table, retries on failure, emails on critical errors.

Usage:
    python pipeline.py                  # run all steps
    python pipeline.py --step fetch_vix # run one step
    python pipeline.py --dry-run        # show what would run
    python pipeline.py --status         # show today's log
    python pipeline.py --status 7       # show last 7 days
"""

import argparse
import importlib
import logging
import sys
import time
import traceback
from datetime import date, datetime

from config import PIPELINE, LOG_PATH
import db
from db import get_db

# ── Logging setup ──
# stdout only — cron (run.sh morning) already redirects stdout to LOG_PATH.
# A FileHandler here used to write the SAME lines to LOG_PATH a second time
# (audit Eff-F6); interactive runs still print via the StreamHandler.
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("pipeline")


# ── Step definitions ──
# Read from config.PIPELINE_STEPS — single source of truth.
# Convert to (name, module, function, critical) tuples for the engine.

from config import PIPELINE_STEPS

# Honor the `frequency` field so weekly/monthly steps don't run every day.
# weekly = Sunday only (weekday 6). (fetch_broker_recos moved weekly → daily with a
# 90-min stalest-first budget, 2026-09-26: the ~18h Sunday sweep starved other jobs.)
# `--step <name>` always overrides this gate (manual runs ignore frequency).
def _step_should_run_today(spec):
    freq = (spec.get("frequency") or "daily").lower()
    if freq == "daily":
        return True
    today = date.today()
    if freq == "weekly":
        return today.weekday() == 6  # Sunday
    if freq == "monthly":
        return today.day == 1
    if freq == "quarterly":
        return today.day == 1 and today.month in (1, 4, 7, 10)
    return True  # unknown freq → run (fail-open)


# Full step list (unfiltered) — used for --step lookups so manual runs work
# any day of the week. Cron path filters via _step_should_run_today inside main().
STEPS = [
    (s["name"], s["module"], s["function"], s["critical"])
    for s in PIPELINE_STEPS
]
STEP_SPECS = {s["name"]: s for s in PIPELINE_STEPS}


# ── Pipeline engine ──

def log_step(step_name: str, status: str, rows: int = None,
             started: str = None, error: str = None):
    """Write a row to pipeline_log."""
    now = datetime.now().isoformat(timespec="seconds")
    duration = None
    if started:
        try:
            t0 = datetime.fromisoformat(started)
            duration = round((datetime.now() - t0).total_seconds(), 2)
        except ValueError:
            pass

    with get_db() as conn:
        conn.execute(
            """INSERT INTO pipeline_log
               (run_date, step_name, status, rows_affected, started_at, finished_at, duration_sec, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (date.today().isoformat(), step_name, status, rows, started, now, duration, error),
        )


UNDECLARED = {}   # step → {"reads": [...], "writes": [...]} seen at run time but not declared


def _check_declared(name, seen):
    """Plan 0015 Phase 1a: compare a step's traced tables with its declaration.
    Records mismatches in UNDECLARED (written out by run_pipeline); never raises."""
    try:
        import graph
        spec = STEP_SPECS.get(name)
        if not spec or "reads" not in spec:
            return
        declared_w = set(graph.writes(spec))
        declared_r = set(spec["reads"]) | declared_w
        skip = graph.RUNNER_TABLES | {"pipeline_log"}
        r = sorted(seen["reads"] - declared_r - skip)
        w = sorted(seen["writes"] - declared_w - skip)
        if r or w:
            UNDECLARED[name] = {"reads": r, "writes": w}
            log.warning(f"[GRAPH] {name}: undeclared reads {r} writes {w}")
    except Exception as e:
        log.warning(f"[GRAPH] declaration check failed for {name}: {e}")


def _post_check(name):
    """Plan 0015 invariant 4: a step succeeds only if the tables it declares writing
    are not OUTDATED afterwards (checks.post_step). A check that itself errors is
    logged and ignored — it must never break the run."""
    spec = STEP_SPECS.get(name)
    if not spec:
        return []
    try:
        import checks
        return checks.post_step(spec)
    except Exception as e:
        log.warning(f"[CHECK] post-check for {name} could not run: {type(e).__name__}: {e}")
        return []


def run_step(name: str, module_path: str, func_name: str, critical: bool):
    """
    Import module, call function, check its outputs, log the result.
    Returns True on success, False when the step raised (worth one retry), and None
    when it ran but its post-check failed (its output is still OUTDATED — re-running
    it now would not help, so it is not retried).
    The called function should return an int (rows affected) or None.
    """
    started = datetime.now().isoformat(timespec="seconds")
    log_step(name, "RUNNING", started=started)
    log.info(f"[START] {name}")

    db.trace_start()
    try:
        mod = importlib.import_module(module_path)
        func = getattr(mod, func_name)
        result = func()
        _check_declared(name, db.trace_stop())
        rows = result if isinstance(result, int) else None
        failures = _post_check(name)
        if failures:
            error_msg = "post-check: " + "; ".join(failures)
            log_step(name, "FAILED", rows=rows, started=started, error=error_msg)
            log.error(f"[FAIL]  {name}  — {error_msg}")
            return None
        log_step(name, "SUCCESS", rows=rows, started=started)
        log.info(f"[DONE]  {name}  ({rows} rows)" if rows else f"[DONE]  {name}")
        return True

    except Exception as e:
        _check_declared(name, db.trace_stop())
        error_msg = f"{type(e).__name__}: {e}"
        log_step(name, "FAILED", started=started, error=error_msg)
        log.error(f"[FAIL]  {name}  — {error_msg}")
        log.debug(traceback.format_exc())
        return False


def shadow_order(steps: list[tuple], write: bool = True):
    """Derive today's order from the steps' declared reads/writes (graph.py) and
    record it vs the hand order (output/graph_shadow/). Never raises; returns the
    report dict, or None when the order can't be derived (then the list order runs)."""
    try:
        import json
        import graph
        from config import PROJECT_ROOT
        specs = [STEP_SPECS[s[0]] for s in steps]
        undeclared = [s["name"] for s in specs if "reads" not in s]
        if undeclared:
            log.info(f"graph shadow: {len(undeclared)} step(s) without `reads` — skipped")
            return None
        derived = graph.order(specs)
        before, after = graph.diff(specs, derived)
        report = {
            "date": date.today().isoformat(),
            "current": [s["name"] for s in specs],
            "derived": derived,
            "critical_path": sorted(graph.ancestors(specs)),
            "needed_by_email": sorted(graph.ancestors(specs, needed_only=True)),
            "moved_before_email": before,
            "moved_after_email": after,
        }
        if write:
            out = PROJECT_ROOT / "output" / "graph_shadow"
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{report['date']}.json").write_text(json.dumps(report, indent=1))
        log.info(f"graph shadow: {len(report['critical_path'])} steps precede the email "
                 f"({len(report['needed_by_email'])} needed by it); "
                 f"derived order would move {len(before)} before / {len(after)} after the email")
        return report
    except Exception as e:  # shadow mode must never affect the run
        log.warning(f"graph shadow failed: {type(e).__name__}: {e}")
        return None


def run_pipeline(steps: list[tuple], dry_run: bool = False):
    """Run all steps in order. Retry failed steps once. Stop on critical failure."""
    retry_count = PIPELINE["retry_count"]
    failed_critical = False
    critical_failed = []

    log.info(f"{'=' * 50}")
    log.info(f"Pipeline run — {date.today()} — {len(steps)} steps")
    log.info(f"{'=' * 50}")
    if len(steps) > 1:
        report = shadow_order(steps, write=not dry_run)
        if PIPELINE.get("derived_order") and report:
            by_name = {s[0]: s for s in steps}
            steps = [by_name[n] for n in report["derived"]]
            log.info("Running the DERIVED order (config.PIPELINE['derived_order'])")
        elif PIPELINE.get("derived_order"):
            log.warning("derived order unavailable — running the PIPELINE_STEPS list order")

    if dry_run:
        for name, module, func, critical in steps:   # in the order that would run
            tag = "CRITICAL" if critical else "optional"
            log.info(f"  [{tag:8s}] {name:25s} → {module}.{func}()")
        log.info("Dry run — nothing executed.")
        return

    t_start = time.time()
    passed, failed, skipped = 0, 0, 0

    for name, module_path, func_name, critical in steps:
        if failed_critical:
            log_step(name, "SKIPPED")
            log.warning(f"[SKIP]  {name}  (prior critical failure)")
            skipped += 1
            continue

        success = run_step(name, module_path, func_name, critical)

        if success is False and retry_count > 0:      # None = post-check failed: no retry
            log.info(f"[RETRY] {name}  (attempt 2/{retry_count + 1})")
            time.sleep(2)
            success = run_step(name, module_path, func_name, critical)

        if success:
            passed += 1
        else:
            failed += 1
            if critical:
                log.error(f"Critical step '{name}' failed — skipping remaining steps.")
                failed_critical = True
                critical_failed.append(name)

    try:
        import json
        from config import PROJECT_ROOT
        out = PROJECT_ROOT / "output" / "graph_shadow"
        out.mkdir(parents=True, exist_ok=True)
        f = out / f"{date.today().isoformat()}_undeclared.json"
        merged = json.loads(f.read_text()) if f.exists() else {}   # reruns add, never erase
        merged.update(UNDECLARED)
        f.write_text(json.dumps(merged, indent=1))
        log.info(f"graph shadow: {len(UNDECLARED)} step(s) touched undeclared tables")
    except Exception as e:
        log.warning(f"graph shadow: could not write undeclared report: {e}")

    elapsed = round(time.time() - t_start, 1)
    log.info(f"{'=' * 50}")
    log.info(f"Done in {elapsed}s — {passed} passed, {failed} failed, {skipped} skipped")
    log.info(f"{'=' * 50}")

    if failed_critical and PIPELINE.get("email_on_failure") and not dry_run:
        _alert_critical(critical_failed)
    return {"passed": passed, "failed": failed, "skipped": skipped,
            "failed_critical": failed_critical}


def _alert_critical(names):
    """URGENT email + push the moment a critical step aborts the run (review F3: this
    was a log line, so a dead bhavcopy/screener waited for the 04:00 digest). The
    alert must never raise — a failed alert is logged and the run's exit code stands."""
    try:
        from db import read_sql
        from tools.health_report import send_email, send_ntfy
        errs = read_sql(
            "SELECT step_name, error_message FROM pipeline_log WHERE run_date = ? "
            "AND step_name IN ({}) AND status = 'FAILED' ORDER BY id".format(",".join("?" * len(names))),
            params=[date.today().isoformat(), *names])
        lines = [f"{r.step_name}: {(r.error_message or '')[:300]}" for r in errs.itertuples()] or names
        subject = f"Pipeline ABORTED {date.today()} — critical step failed: {', '.join(names)}"
        html = ("<p>The morning run stopped; no picks or email follow until it is fixed.</p><ul>"
                + "".join(f"<li><code>{l}</code></li>" for l in lines)
                + "</ul><p>Runbook: OPERATOR.md §7.</p>")
        send_email(html, subject, urgent=True)
        send_ntfy(subject, urgent=True)
    except Exception as e:                           # alerting must not mask the failure
        log.error(f"critical-failure alert could not be sent: {e}")


def show_status(days: int = 1):
    """Print pipeline_log for recent runs."""
    from db import read_sql
    df = read_sql(
        "SELECT run_date, step_name, status, rows_affected, duration_sec, error_message "
        "FROM pipeline_log WHERE run_date >= date('now', ?) ORDER BY id",
        params=[f"-{days} days"],
    )
    if df.empty:
        print(f"No pipeline runs in the last {days} day(s).")
    else:
        print(df.to_string(index=False))


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(description="Alpha Signal v2 pipeline")
    parser.add_argument("--step", help="Run a single step by name")
    parser.add_argument("--dry-run", action="store_true", help="Show steps without running")
    parser.add_argument("--status", nargs="?", const=1, type=int, metavar="DAYS",
                        help="Show pipeline log (default: today)")
    args = parser.parse_args()

    if args.status is not None:
        show_status(args.status)
        return

    active_steps = [s for s in STEPS if not isinstance(s, str)]  # skip comments

    if args.step:
        matches = [s for s in active_steps if s[0] == args.step]
        if not matches:
            available = [s[0] for s in active_steps]
            print(f"Unknown step '{args.step}'. Available: {available}")
            sys.exit(1)
        active_steps = matches
    else:
        # Cron path: filter weekly/monthly/quarterly steps to their firing day
        before = len(active_steps)
        active_steps = [s for s in active_steps if _step_should_run_today(STEP_SPECS[s[0]])]
        skipped = before - len(active_steps)
        if skipped:
            log.info(f"Frequency gate: {skipped} step(s) skipped today (weekly/monthly/quarterly)")

    if not active_steps:
        print("No active steps defined yet. Uncomment steps in STEPS list as modules are built.")
        print(f"\nAll {len(STEPS)} steps (commented out):")
        # Show the commented-out steps for reference
        import re
        with open(__file__) as f:
            for line in f:
                if line.strip().startswith('# ("'):
                    name = re.search(r'"([^"]+)"', line)
                    if name:
                        print(f"  - {name.group(1)}")
        return

    result = run_pipeline(active_steps, dry_run=args.dry_run)
    # Non-zero exit when the run aborted, or when a --step run failed, so run.sh, cron
    # logs and manual callers can tell (review F3: it always exited 0).
    if result and (result["failed_critical"] or (args.step and result["failed"])):
        sys.exit(1)


if __name__ == "__main__":
    main()
