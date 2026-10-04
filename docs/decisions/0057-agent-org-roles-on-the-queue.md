# ADR 0057 — The agent org: roles are a registry, desk work is a task kind, memos are documents

**Status:** accepted 2026-10-02 (plan 0019) · **Builds on:** ADR 0056 (validated LLM queue), ADR 0054 (tables grow with concepts) · **Supersedes:** nothing

**Decision.** The fund is run as an org with one human (the CEO) and agent seats. Every seat is one entry in
`org.ROLES`. A seat that works unattended (a **desk** seat) is a task kind on the `llm_tasks` queue that belongs to
that role: deterministic code builds a facts brief, a local `claude -p` worker running as the role answers it, and
`alpha-work.submit` validates the memo server-side and stores it as a `documents` row (`source='org'`). A seat that
changes code (a **builder** seat) is a subagent definition spawned by a human-led session in a worktree. No seat can
change weights, config, cron, credentials or production code without the CEO.

## Why
- The queue from ADR 0056 already gives what an org needs: a claim/submit door, server-side validation, undo
  records, per-role attribution (`claimed_by`, `mcp_calls.role`). A role is that plus a charter.
- The failure this system keeps having is confident wrong output, not slow output. So the design puts the checks in
  code (closed ids, grounded numbers, no links) and makes a separate seat grade every memo.
- A new table for memos would be a thing-table. A memo, an ask, a hypothesis card and a decision are all documents
  with a type and a parent.

## Consequences
- `tasks.kinds_for(worker)`: a kind with `"role"` is visible and claimable only by that role. The pipeline's
  llm-worker and its `claimable` count ignore org kinds.
- One cron line (`run.sh org`, 06:30 UTC) runs the due seats in `org.RUN_ORDER`: doers, then Compliance, then the
  Chief of Staff. A seat with work and no output fails `cron_org`.
- Org documents are written natively to v3 `documents` (no legacy table, so no parity row in `datamodel.reconcile`).
  `llm_tasks.result_json` keeps every memo, so the documents can be rebuilt from the queue.
- Narrative figures must appear in the brief. A role that needs a figure it looked up puts it in `evidence` with the
  tool name, and the server checks that tool against `mcp_calls` for that role. This is the dossier no-numbers rule,
  relaxed to "no numbers we did not give you".
- Ideas follow the chain of command: a card from a seat under the CIO reaches the CEO only if the CIO forwards it.
- Delivery is pull (cockpit `/org`, `alpha-ops.org`), plus one weekly email and a push only for `urgency: now`.

## Rejected
- **One mega-agent with every tool.** No separation of doer and grader, no per-role cost, no least privilege.
- **Managed/cloud agents.** Plan 0016 D1 chose local-only; API credits are empty; nothing is exposed over HTTPS.
- **Agents with a shell on prod for fixes.** Fixes are builder work in a worktree behind tests and a human merge.
- **A framework (CrewAI/LangGraph).** ADR 0004: plain functions and a dict. The org is about 900 lines.
