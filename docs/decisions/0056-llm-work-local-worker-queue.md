# ADR 0056 — LLM work runs on a local subscription worker through a validated queue

**Status:** accepted 2026-09-30 (plan 0016 D1–D6) · **Supersedes:** the 7 direct Anthropic-API call paths as the default executor (they stay behind `config.LLM_WORK["executor"] = "api"`)

**Decision.** Every LLM task (regulatory classification, news enrichment, dossiers, sector dossiers, the news brief) becomes a row in `llm_tasks`. A local `claude -p` worker on the Claude subscription (`ops/llm_worker_local.sh`) drains the queue. Its only tools are the stdio MCP servers `alpha-work` and `alpha-research`, and its only write path is `submit`. On the server, `submit` validates each result with the producer's own validator and writes it through the producer's own save path, recording an undo record. There is no cloud routine and nothing is exposed over HTTPS.

## Why
- API credits have been empty since 2026-08-24, and every LLM step has failed since then (5 standing CRITICALs). The subscription is a separate budget that was already doing the work by hand (`tools/session_classify.py`).
- Cloud routines would need the VM's DB reachable over HTTPS, with tokens and an nginx front. The local worker needs none of that and has the same validation guarantees.
- A queue with leases makes the work resumable and idempotent (`task_id = kind:item:input_hash`). The model never touches SQL, and a manipulated or confused worker can at worst write one valid-shaped wrong verdict, which `rollback(kind, since)` can undo.

## Consequences
- The MCP read surface (`alpha-research`, `alpha-ops`) is read-only by construction, using a `mode=ro` + `query_only` connection, and serves every Claude Code session in the repo.
- The worker must never see `ANTHROPIC_API_KEY`, or the CLI would bill the API.
- Calibration against the API verdicts: `is_regulatory` 91.5%; sector direction 88.9%, where the remaining disagreements are perspective calls. Accepted 2026-10-01.
- Measured throughput: about 1,000 items per 13 minutes. A 13K backlog took about 3 h 20 min.
- Pipeline steps run the worker inline with a deadline (dossier ≤ 20 min, D4). The wiring is pending; see the plan 0016 notes.
