#!/bin/bash
# Local LLM worker (plan 0016, D1 = local): drains the llm_tasks queue on the Claude
# subscription with `claude -p` against the stdio MCP servers in ops/mcp.local.json.
# The worker gets no built-in tools (--tools ""), only alpha-work + alpha-research;
# every write goes through alpha-work.submit's server-side validation.
#
#   ops/llm_worker_local.sh [MAX_BATCHES]      # default 40 submit calls (~40 min)
#
# Env: ALPHA_DB (run against a DB copy — calibration), LLM_WORKER_MODEL (default sonnet),
#      LLM_WORKER_TIMEOUT (default 45m). Not --bare: that needs an API key.
# Exit: 0 = ran and made progress (or nothing was claimable); 1 = claude failed, the
#       run reported an error, or items were claimable and none got done.
# Scheduling: not in cron yet. run.sh should gain `llm_local) logged llm_local ops/llm_worker_local.sh ;;`
# (owned by the run.sh session) — see docs/reference/mcp.md.
set -uo pipefail
cd /home/ubuntu/alpha-signal-v2 || exit 1
source /home/ubuntu/alpha-signal/venv/bin/activate

LOG=output/llm_worker.log
MAX_BATCHES=${1:-40}
MODEL=${LLM_WORKER_MODEL:-sonnet}
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
claimable() { python -m alpha_mcp.tasks status | python -c "
import json,sys; k=json.load(sys.stdin).get('kinds',{})
print(sum(v.get('counts',{}).get(s,0) for v in k.values() for s in ('queued','invalid')))"; }

before=$(claimable) || { echo "$(ts) llm_worker: cannot read llm_tasks (table missing?)" >> "$LOG"; exit 1; }
echo "$(ts) llm_worker start db=${ALPHA_DB:-live} model=$MODEL claimable=$before max_batches=$MAX_BATCHES" >> "$LOG"
if [ "$before" -eq 0 ]; then echo "$(ts) llm_worker: nothing to do" >> "$LOG"; exit 0; fi

PROMPT="$(cat .claude/routines/llm-worker.md)

Run budget: at most ${MAX_BATCHES} submit calls, then stop and give the final answer."

out=$(timeout "${LLM_WORKER_TIMEOUT:-45m}" claude -p "$PROMPT" \
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
