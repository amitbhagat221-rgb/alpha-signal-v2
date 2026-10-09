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
    local t0 rc run_id; t0=$(date +%Y-%m-%dT%H:%M:%S)
    run_id="$step:$(date -u +%Y%m%dT%H%M%S):$$"   # plan 0018: every python process of this job
    ALPHA_STEP="$step" ALPHA_RUN_ID="$run_id" "$@"; rc=$?   # logs to run_events under this run_id
    python -c 'import sys; from pipeline import log_step; import runlog; ok = sys.argv[2] == "0"
log_step(sys.argv[1], "SUCCESS" if ok else "FAILED", started=sys.argv[3],
         error=None if ok else f"exit {sys.argv[2]} (python -m runlog events --run {sys.argv[5]})")
runlog.exit_code(sys.argv[5], sys.argv[1], sys.argv[2], started=sys.argv[3])' \
        "$step" "$rc" "$t0" "$JOB" "$run_id" >/dev/null || echo "[warn] could not log $step to pipeline_log"
    return $rc
}

harvest_lock() {   # shared with the watchdog heal runner and the cockpit rerun endpoint
    [ -n "${DRY:-}" ] && { echo "+ flock -n /tmp/alpha_signal_harvest.lock"; return 0; }
    exec 200>/tmp/alpha_signal_harvest.lock
    # Wait for the job holding it (the morning run can still be going at 06:00 on the 1st),
    # and if it never frees, record the skip: `exit 0` here made the 2026-10-01 Screener
    # harvest vanish with no pipeline_log row.
    flock -w "${LOCK_WAIT_S:-7200}" 200 || {
        echo "another harvester held the lock for ${LOCK_WAIT_S:-7200}s — $JOB skipped $(date -u)"
        python -c 'import sys; from pipeline import log_step
log_step(sys.argv[1], "FAILED", error="skipped: harvest lock held by another job")' "cron_$JOB" \
            || echo "[warn] could not log the skip to pipeline_log"
        exit 1; }
}

JOB="${1:?usage: run.sh <job>}"
echo "=== run.sh $JOB — $(date -u +'%Y-%m-%d %H:%M:%S UTC')"

case "$JOB" in
    morning)            # 03:30 UTC — the daily pipeline, then the DuckDB read replica
        harvest_lock
        run python pipeline.py
        RC=$?
        run python -m tools.duckdb_refresh || echo "[warn] duckdb_refresh failed; cockpit falls back to SQLite reads"
        # Data model v3 shadow (ADR 0054): mirror into the new tables, then record old-vs-new parity.
        # After the email, so a failure here never touches picks; `logged` puts it in pipeline_log.
        # Forward record of the investor-playbook sleeves (sleeves.py): today's members, after the
        # pipeline so it reads today's factor values; a failure here never touches picks.
        logged playbook_members run python -m tools.playbook_backtest --record || echo "[warn] playbook_members record failed"
        logged datamodel_sync run python -m datamodel.sync || echo "[warn] datamodel sync failed (v3 shadow only)"
        logged datamodel_reconcile run python -m datamodel.reconcile || echo "[warn] datamodel parity FAIL: python -m datamodel.reconcile --show"
        echo "Done $(date -u) (pipeline rc=$RC)"
        exit $RC ;;
    forward)            # 14:00 UTC — forward-only sources with no historical archive
        harvest_lock
        logged cron_nselib_daily_forward run python -m sources.nselib_pull --source daily_forward; echo "Exit code (nselib daily_forward): $?"
        # scrip_master must follow bse_announcements (it backfills sid on the new rows)
        logged cron_bse_announcements run python -m sources.bse_announcements --days 7; echo "Exit code (bse_announcements): $?"
        logged cron_scrip_master run python -m sources.scrip_master;          echo "Exit code (scrip_master): $?"
        logged cron_nse_events run python -m sources.nse_events --ratings --days 10 --ipos; echo "Exit code (nse_events): $?" ;;
    canary)             # 02:45 UTC — 1-item live probe per feed before the morning run (plan 0018):
                        # T1 daily, T2 on Sundays; verdicts → feed_checks → health report
        harvest_lock
        logged cron_canary run python -m tools.canary --due
        logged cron_reconcile run python -m tools.reconcile ;;     # Gate 3 cross-source checks
    transcripts)        # Sunday 07:00 UTC — concall transcripts for stocks that reported in the last
                        # 45 days (they appear 1-4 weeks after results), then their BSE filing dates
                        # (the look-ahead-safe availability) — plan 0018; orphaned since 2026-06-07
        harvest_lock
        logged cron_transcripts run python -m sources.transcripts_pull --reported-days 45 --min-analysts 1 --max-docs 2
        logged cron_transcripts_dates run python -m sources.transcripts_pull --backfill-filing-dates
        # score the new calls: forward_looking_intensity (wired, LARGE) reads nlp_scores, and nothing
        # scheduled this — 721 calls fetched 2026-06 → 10 sat unscored (plan 0020, 2026-10-08)
        logged cron_nlp_scores run python -m signals.nlp_scores
        # named >1% holders for stocks missing the latest quarter (filings land within ~21 days
        # of quarter end); budgeted and resumable, stalest first
        logged cron_bse_shp run python -m sources.bse_shp --due --budget-min 180 ;;
    backfill)           # TEMPORARY (2026-10-04) — one-off history backfills in the windows no other
                        # job uses: 08:00 Sun-Fri, 16:00 (not the 1st), 21:00 UTC; `run.sh backfill <minutes>`.
                        # Each part is resumable and returns at once when it has nothing left; remove the
                        # cron lines when both report nothing to fetch.
        harvest_lock
        END=$((SECONDS + ${2:-240} * 60))
        left() { echo $(( (END - SECONDS) / 60 )); }
        # pre-2020 prices (legacy NSE archive). Starts where corporate_actions start (2018-03):
        # older prices cannot be adjusted for splits and bonuses until earlier actions are loaded.
        [ "$(left)" -gt 5 ] && logged cron_nse_legacy run python -m sources.nse --legacy --start 2018-03-01 --end 2019-12-31 --budget-min "$(left)"
        # named >1% holders: every XBRL filing since 2016, largest stocks first
        [ "$(left)" -gt 5 ] && logged cron_bse_shp_backfill run python -m sources.bse_shp --universe --quarters 0 --budget-min "$(left)" ;;
    screener_schedules) # 3rd + 4th of Jan/Apr/Jul/Oct 20:30 UTC — Screener '+'-row breakdowns
                        # (Intangible Assets etc., annual items): ~9 h for the universe, so two
                        # resumable 5-hour night windows per quarter, clear of every other job
        harvest_lock
        logged cron_screener_schedules run python -m sources.screener_schedules --universe --budget-min 300 ;;
    estimates)          # Saturday 10:00 UTC — Yahoo EPS trend snapshots (covered stocks) + surprises
                        # for stocks that reported in the last 3 weeks (plan 0018)
        harvest_lock
        logged cron_estimates run python -m sources.yahoo_estimates --trend --covered
        logged cron_estimates_history run python -m sources.yahoo_estimates --history --reported-days 21 ;;
    llm_local)          # 05:07 + 14:37 UTC — catch-up drain of the llm_tasks queue (plan 0016): the
                        # morning LLM steps run the worker inline with deadlines; this picks up leftovers
                        # (expired leases, items past a deadline). No harvest lock: no external fetch.
        logged cron_llm_local run "$ROOT/ops/llm_worker_local.sh" 40 ;;
    org)                # 06:30 UTC — the agent org (plan 0019): every desk role due today runs as its own
                        # `claude -p` worker on the subscription, in org.RUN_ORDER (daily: data triage, risk
                        # note, compliance grades; Sunday: sector desk, CIO, CTO, scout, board pack + email).
                        # No harvest lock: it fetches no market data. Its own lock: org runs never overlap.
        if [ -z "${DRY:-}" ]; then
            exec 201>/tmp/alpha_signal_org.lock
            flock -n 201 || { echo "another org run holds the lock, exiting $(date -u)"; exit 0; }
        fi
        logged cron_org run python -m org run ;;
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
        echo "unknown job '$JOB' (morning forward canary estimates transcripts screener_schedules llm_local org watchdog health pt_snapshot backtest expected_return screener_cookie secrets_backup screener_universe tickertape)"
        exit 2 ;;
esac
