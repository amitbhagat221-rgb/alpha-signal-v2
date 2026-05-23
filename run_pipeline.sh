#!/bin/bash
# Alpha Signal v2 — daily pipeline runner
# Mirrors v1's run_pipeline.sh shape but delegates to pipeline.py.

set -u  # error on undefined var; do NOT use -e (we want pipeline.py's own retry/skip behaviour)

cd /home/ubuntu/alpha-signal-v2
source /home/ubuntu/alpha-signal/venv/bin/activate

# Credentials live in v1's run_pipeline.sh exports (single source of truth per
# CLAUDE.md). Read-only import — grep extracts the `export FOO=...` lines and
# eval applies them to this shell. No execution of v1's pipeline body, no
# duplication of secrets into v2.
#
# Previously v2 cron ran without ANTHROPIC_API_KEY / GMAIL_USER → dossier and
# email failed silently for 20+ days (HALC bug 2026-05-22).
V1_PIPELINE="/home/ubuntu/alpha-signal/run_pipeline.sh"
if [ -r "$V1_PIPELINE" ]; then
    eval "$(grep '^export ' "$V1_PIPELINE")"
fi

# Derive v2-style email-sender vars from ALPHA_SIGNAL_*
export GMAIL_USER="${ALPHA_SIGNAL_EMAIL:-}"
export GMAIL_APP_PASSWORD="${ALPHA_SIGNAL_PASSWORD:-}"
export EMAIL_RECIPIENT="${ALPHA_SIGNAL_EMAIL:-}"

echo "=============================="
echo "Alpha Signal v2 - $(date)"
echo "=============================="

python pipeline.py
PIPELINE_RC=$?

# TODO: v2 has no git repo yet. Wire up GitHub backup once remote exists.
# (v1 used the same daily commit-and-push pattern — see /home/ubuntu/alpha-signal/run_pipeline.sh.)

echo "Done! $(date) (pipeline rc=$PIPELINE_RC)"
exit $PIPELINE_RC
