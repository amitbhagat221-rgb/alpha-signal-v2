#!/bin/bash
# Alpha Signal v2 — daily pipeline runner
# Mirrors v1's run_pipeline.sh shape but delegates to pipeline.py.

set -u  # error on undefined var; do NOT use -e (we want pipeline.py's own retry/skip behaviour)

cd /home/ubuntu/alpha-signal-v2
source /home/ubuntu/alpha-signal/venv/bin/activate

# Credentials should be provided via environment variables. Do not hardcode secrets in the repo.
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
export ALPHA_SIGNAL_EMAIL="${ALPHA_SIGNAL_EMAIL:-}"
export ALPHA_SIGNAL_PASSWORD="${ALPHA_SIGNAL_PASSWORD:-}"
export DATAGOV_API_KEY="${DATAGOV_API_KEY:-}"

export GMAIL_USER="$ALPHA_SIGNAL_EMAIL"
export GMAIL_APP_PASSWORD="$ALPHA_SIGNAL_PASSWORD"
export EMAIL_RECIPIENT="$ALPHA_SIGNAL_EMAIL"

echo "=============================="
echo "Alpha Signal v2 - $(date)"
echo "=============================="

python pipeline.py
PIPELINE_RC=$?

# TODO: v2 has no git repo yet. Wire up GitHub backup once remote exists.
# (v1 used the same daily commit-and-push pattern — see /home/ubuntu/alpha-signal/run_pipeline.sh.)

echo "Done! $(date) (pipeline rc=$PIPELINE_RC)"
exit $PIPELINE_RC
