"""
Alpha Signal v2 — Pipeline Orchestrator

THE replacement for run_pipeline.sh. Runs steps in order, logs everything
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
from db import get_db

# ── Logging setup ──

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, mode="a"),
    ],
)
log = logging.getLogger("pipeline")


# ── Step definitions ──
# Read from config.PIPELINE_STEPS — single source of truth.
# Convert to (name, module, function, critical) tuples for the engine.

from config import PIPELINE_STEPS

# Honor the `frequency` field so weekly/monthly steps don't run every day.
# 2026-05-25: fetch_broker_recos is weekly (8hr at 12s rate-limit) — running
# daily would hammer Moneycontrol's WAF. weekly = Sunday only (weekday 6).
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


def run_step(name: str, module_path: str, func_name: str, critical: bool) -> bool:
    """
    Import module, call function, log result. Returns True on success.
    The called function should return an int (rows affected) or None.
    """
    started = datetime.now().isoformat(timespec="seconds")
    log_step(name, "RUNNING", started=started)
    log.info(f"[START] {name}")

    try:
        mod = importlib.import_module(module_path)
        func = getattr(mod, func_name)
        result = func()
        rows = result if isinstance(result, int) else None
        log_step(name, "SUCCESS", rows=rows, started=started)
        log.info(f"[DONE]  {name}  ({rows} rows)" if rows else f"[DONE]  {name}")
        return True

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        log_step(name, "FAILED", started=started, error=error_msg)
        log.error(f"[FAIL]  {name}  — {error_msg}")
        log.debug(traceback.format_exc())
        return False


def run_pipeline(steps: list[tuple], dry_run: bool = False):
    """Run all steps in order. Retry failed steps once. Stop on critical failure."""
    retry_count = PIPELINE["retry_count"]
    failed_critical = False

    log.info(f"{'=' * 50}")
    log.info(f"Pipeline run — {date.today()} — {len(steps)} steps")
    log.info(f"{'=' * 50}")

    if dry_run:
        for name, module, func, critical in steps:
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

        if not success and retry_count > 0:
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

    elapsed = round(time.time() - t_start, 1)
    log.info(f"{'=' * 50}")
    log.info(f"Done in {elapsed}s — {passed} passed, {failed} failed, {skipped} skipped")
    log.info(f"{'=' * 50}")

    if failed_critical and PIPELINE.get("email_on_failure"):
        log.info("Email alert would fire here (email_sender not yet built)")


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

    run_pipeline(active_steps, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
