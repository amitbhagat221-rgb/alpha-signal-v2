#!/bin/bash
# Local LLM worker (plan 0016, D1 = local): drains the llm_tasks queue on the Claude
# subscription with `claude -p` against the stdio MCP servers in ops/mcp.local.json.
# The worker gets no built-in tools (--tools ""), only alpha-work + alpha-research;
# every write goes through alpha-work.submit's server-side validation.
#
#   ops/llm_worker_local.sh [MAX_BATCHES]      # default 40 submit calls
#
# Env: LLM_WORKER_KINDS  comma list — only these kinds this run (pipeline steps pass theirs)
#      ALPHA_DB          run against a DB copy (calibration)
#      LLM_WORKER_MODEL  default sonnet;  LLM_WORKER_TIMEOUT  default 45m
# Runs on the subscription login (~/.claude), never an API key: ANTHROPIC_API_KEY (exported by
# run.sh for the old API paths) is unset for the claude call, and claude is called by absolute
# path because cron's PATH lacks ~/.local/bin. Not --bare: that needs an API key.
# Exit: 0 = progress (or nothing claimable); 1 = claude failed, reported an error, or no progress.
# Scheduled by run.sh `llm_local` (cron) and called inline by the pipeline's LLM steps.
set -uo pipefail
cd /home/ubuntu/alpha-signal-v2 || exit 1
source /home/ubuntu/alpha-signal/venv/bin/activate

LOG=output/llm_worker.log
MAX_BATCHES=${1:-40}
MODEL=${LLM_WORKER_MODEL:-sonnet}
CLAUDE_BIN=${CLAUDE_BIN:-/home/ubuntu/.local/bin/claude}
KINDS=${LLM_WORKER_KINDS:-}
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
claimable() { python -m alpha_mcp.tasks claimable ${KINDS//,/ }; }

before=$(claimable) || { echo "$(ts) llm_worker: cannot read llm_tasks (table missing?)" >> "$LOG"; exit 1; }
echo "$(ts) llm_worker start db=${ALPHA_DB:-live} model=$MODEL kinds=${KINDS:-all} claimable=$before max_batches=$MAX_BATCHES" >> "$LOG"
if [ "$before" -eq 0 ]; then echo "$(ts) llm_worker: nothing to do" >> "$LOG"; exit 0; fi

PROMPT="$(cat .claude/routines/llm-worker.md)

Run budget: at most ${MAX_BATCHES} submit calls, then stop and give the final answer."
if [ -n "$KINDS" ]; then
    PROMPT="$PROMPT
This run works ONLY on these kinds: ${KINDS}. Skip every other kind."
fi

out=$(env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN timeout "${LLM_WORKER_TIMEOUT:-45m}" "$CLAUDE_BIN" -p "$PROMPT" \
    --model "$MODEL" \
    --mcp-config ops/mcp.local.json --strict-mcp-config \
    --tools "" \
    --allowedTools "mcp__alpha-work__*" "mcp__alpha-research__*" \
    --permission-mode dontAsk \
    --no-session-persistence \
    --output-format json 2>>"$LOG")
rc=$?
echo "$out" >> "$LOG"
after=$(claimable)
echo "$(ts) llm_worker end rc=$rc claimable $before -> $after" >> "$LOG"

if [ "$rc" -ne 0 ]; then exit 1; fi
if echo "$out" | python -c "import json,sys; sys.exit(0 if json.load(sys.stdin).get('is_error') else 1)" 2>/dev/null; then
    exit 1
fi
[ "$after" -lt "$before" ] || exit 1
exit 0
