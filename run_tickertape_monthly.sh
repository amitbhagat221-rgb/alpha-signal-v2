#!/bin/bash
# Alpha Signal v2 — monthly Tickertape fundamentals refresh.
# Wired in the user's crontab; takes ~4 hours for 2,448 stocks.
# Schedules itself far from the daily 03:30 UTC pipeline so they don't overlap.

set -u
cd /home/ubuntu/alpha-signal-v2

# No-two-harvesters-at-once (CLAUDE.md) — same lock as run_pipeline.sh /
# run_daily_forward.sh. This 4-hour harvest used to run unlocked.
exec 200>/tmp/alpha_signal_harvest.lock
flock -n 200 || { echo "another harvester holds the lock, exiting $(date)"; exit 0; }
source /home/ubuntu/alpha-signal/venv/bin/activate

LOG=/home/ubuntu/alpha-signal-v2/output/tickertape_$(date +%Y%m).log
echo "=============================="
echo "Tickertape monthly refresh - $(date)"
echo "=============================="

# Resume-aware. Clear the checkpoint so we re-fetch every stock for the new cycle.
rm -f /home/ubuntu/alpha-signal-v2/output/tickertape_harvest_log.json

python -m sources.tickertape >> "$LOG" 2>&1
RC=$?

echo "Tickertape finished rc=$RC at $(date)"
exit $RC
