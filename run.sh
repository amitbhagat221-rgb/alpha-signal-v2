#!/bin/bash
# Alpha Signal v2 — the ONE cron entry point (plan 0015 Phase 1b).
#
#   run.sh <job>          run a job (crontab: one line per job, each redirecting to its log)
#   DRY=1 run.sh <job>    print what would run
#
# One preamble for every job: repo dir, shared venv, credentials imported READ-ONLY
# from v1's run_pipeline.sh exports (CLAUDE.md — never duplicate secrets), and the
# email-sender variables. Harvesting jobs take the shared non-blocking harvest lock
# (no two harvesters at once) and skip the run if another holds it.
set -u

ROOT=/home/ubuntu/alpha-signal-v2
cd "$ROOT" || { echo "FATAL: cd $ROOT failed"; exit 1; }
# shellcheck disable=SC1091
source /home/ubuntu/alpha-signal/venv/bin/activate

V1_PIPELINE=/home/ubuntu/alpha-signal/run_pipeline.sh
if [ -r "$V1_PIPELINE" ]; then
    eval "$(grep '^export ' "$V1_PIPELINE")"
fi
export GMAIL_USER="${ALPHA_SIGNAL_EMAIL:-}"
export GMAIL_APP_PASSWORD="${ALPHA_SIGNAL_PASSWORD:-}"
export EMAIL_RECIPIENT="${ALPHA_SIGNAL_EMAIL:-}"

run() {            # run a command, or print it under DRY=1
    if [ -n "${DRY:-}" ]; then echo "+ $*"; return 0; fi
    "$@"
}

logged() {         # logged <step_name> <cmd...>: run a cron-only job and record it in pipeline_log
    local step="$1"; shift  # (review F3: cron jobs wrote no log row, so a dead one — the Screener
                            # harvest at 2448/2448 failures, BSE at 8/8 day errors — was invisible)
    if [ -n "${DRY:-}" ]; then echo "+ [pipeline_log ← $step]"; "$@"; return; fi
    local t0 rc; t0=$(date +%Y-%m-%dT%H:%M:%S)
    "$@"; rc=$?
    python -c 'import sys; from pipeline import log_step; ok = sys.argv[2] == "0"
log_step(sys.argv[1], "SUCCESS" if ok else "FAILED", started=sys.argv[3],
         error=None if ok else f"exit {sys.argv[2]} (see the run.sh {sys.argv[4]} log)")' \
        "$step" "$rc" "$t0" "$JOB" >/dev/null || echo "[warn] could not log $step to pipeline_log"
    return $rc
}

harvest_lock() {   # shared with the watchdog heal runner and the cockpit rerun endpoint
    [ -n "${DRY:-}" ] && { echo "+ flock -n /tmp/alpha_signal_harvest.lock"; return 0; }
    exec 200>/tmp/alpha_signal_harvest.lock
    flock -n 200 || { echo "another harvester holds the lock, exiting $(date -u)"; exit 0; }
}

JOB="${1:?usage: run.sh <job>}"
echo "=== run.sh $JOB — $(date -u +'%Y-%m-%d %H:%M:%S UTC')"

case "$JOB" in
    morning)            # 03:30 UTC — the daily pipeline, then the DuckDB read replica
        harvest_lock
        run python pipeline.py
        RC=$?
        run python -m tools.duckdb_refresh || echo "[warn] duckdb_refresh failed; cockpit falls back to SQLite reads"
        echo "Done $(date -u) (pipeline rc=$RC)"
        exit $RC ;;
    forward)            # 14:00 UTC — forward-only sources with no historical archive
        harvest_lock
        logged cron_nselib_daily_forward run python -m sources.nselib_pull --source daily_forward; echo "Exit code (nselib daily_forward): $?"
        # scrip_master must follow bse_announcements (it backfills sid on the new rows)
        logged cron_bse_announcements run python -m sources.bse_announcements --days 7; echo "Exit code (bse_announcements): $?"
        logged cron_scrip_master run python -m sources.scrip_master;          echo "Exit code (scrip_master): $?" ;;
    watchdog)           # 15:00 UTC — re-run producers of stale tables (takes the lock itself)
        run python -m tools.freshness_watchdog ;;
    health)             # 04:00 UTC — health email + push
        run python -m tools.health_report --email --push ;;
    pt_snapshot)        # 1st of month — monthly analyst PT snapshot (episodic data, CLAUDE.md)
        logged cron_pt_snapshot run python -m sources.yfinance_analyst --snapshot ;;
    backtest)           # 2nd of month — IC refresh
        logged cron_backtest run python -m tools.backtest_pit ;;
    expected_return)    # 1st of month
        logged cron_expected_return run python -m tools.expected_return ;;
    screener_cookie)    # 3x/day — keep the Screener session alive; re-login (path A) when it
                        # dies, push only if that fails too (the cookie sat dead Jul→Sep with
                        # no re-login attempt and no NTFY_TOPIC to deliver the push)
        cookie_ok() { run python -m sources.screener_pull --check-cookie || \
            { run python -m sources.screener_pull --login && run python -m sources.screener_pull --check-cookie; }; }
        logged cron_screener_cookie cookie_ok || {
            [ -n "${NTFY_TOPIC:-}" ] && run curl -s -H "Title: Screener cookie DEAD" -H "Priority: high" \
                -d "Re-extract sessionid from browser into ~/.cache/screener_cookie.json" "https://ntfy.sh/$NTFY_TOPIC"; } ;;
    secrets_backup)     # 05:30 UTC — GPG-encrypted VM-only secrets + wiring → Drive (review F13)
        logged cron_secrets_backup run "$ROOT/backup_secrets.sh" ;;
    screener_universe)  # 1st + 15th — Screener fundamentals harvest
        harvest_lock
        logged cron_screener_universe run python -m sources.screener_pull --universe ;;
    tickertape)         # 1st of month 19:07 UTC — ~4h Tickertape fundamentals harvest
        harvest_lock
        run rm -f "$ROOT/output/tickertape_harvest_log.json"   # resume checkpoint → full cycle
        LOG="$ROOT/output/tickertape_$(date +%Y%m).log"
        tickertape_run() { python -m sources.tickertape >> "$LOG" 2>&1; }
        if [ -n "${DRY:-}" ]; then echo "+ [pipeline_log ← cron_tickertape] python -m sources.tickertape >> $LOG"; RC=0
        else logged cron_tickertape tickertape_run; RC=$?; fi
        echo "Tickertape finished rc=$RC at $(date -u)"
        exit $RC ;;
    *)
        echo "unknown job '$JOB' (morning forward watchdog health pt_snapshot backtest expected_return screener_cookie secrets_backup screener_universe tickertape)"
        exit 2 ;;
esac
