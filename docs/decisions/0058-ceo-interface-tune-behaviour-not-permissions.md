# ADR 0058 — The CEO's interface to the org: tune behaviour, never permissions

**Status:** accepted 2026-10-02 (plan 0019 §5b–5f, decided with Amit in session) · **Builds on:** ADR 0057 (roles on the queue), ADR 0056 (validated queue)

**Decision.** Everything Amit can change about an agent seat from the Boardroom changes how it *behaves*; nothing he
or a seat can do there changes what a seat is *allowed to write*. Five choices follow from that:

1. **Seat settings.** Variables (on/off, schedule, model, effort, web search, per-run cap, a standing directive) are
   an `org.settings` document applied by `org.seat(role)`. Prompts are the seat's own files (charter / agent file),
   rewritten by the page so `git diff` shows the edit; each save keeps the text as history. Kinds, gate, memo schema
   and validators are code and are not settings.
2. **House style is enforced in code.** Every CEO-facing memo opens with an `eli5` block (what / why / do / remember)
   and a gate rejects trade jargon, code names and long sentences in anything addressed to the CEO
   (`org_kinds._JARGON`). The style text itself (`.claude/routines/house-style.md`) is his to edit; the gate is not.
3. **Web search is on for the research seats** (CIO, sector desk, scout; the quant-researcher builder). This revises
   ADR 0057's "only the scout". The write path is unchanged: a schema-checked memo, web figures only in `evidence`
   with a url, provenance checked against `mcp_calls`.
4. **Chat reads; work orders carry fixes.** A chat has no write path (no `alpha-work`). What is agreed in chat becomes
   a numbered work order → inbox approval → a human-led Claude Code session runs `/work-order N` with builders in a
   worktree. Approval starts nothing: no seat changes code unattended.
5. **Delivery is an installable web app over HTTPS**, not a native app: one codebase, and it put the cockpit's login
   behind TLS (`ops/nginx/alpha-ops.conf`, certbot). The service worker caches static files only.

## Why
- Amit must be able to steer employees daily without a session, and a prompt edit must never be able to weaken a
  guardrail. Splitting "behaviour = data he owns" from "permission = code" gives both.
- The first live runs showed prompts alone drift: seats skipped research, cited tools they had not called, and wrote
  jargon. Each fix that stuck was a server-side check, so the plain-language rule is a check too.
- A misread sentence in a chat must not change production code, so the chat → fix path keeps two human gates
  (approve the order, merge the result).

## Consequences
- Read a seat through `org.seat(role)`, never `ROLES[role]`; expect uncommitted prompt edits in `.claude/routines/`
  and `.claude/agents/` and do not revert them.
- The Claude subscription's usage windows are the org's budget, shared with the pipeline's LLM steps; the Boardroom
  shows the last reading (`org.note_subscription`). A heavy research run can starve the morning dossiers.
- A rejected desk memo keeps its lease and may be resubmitted (5 attempts); pipeline kinds keep the old behaviour.

## Rejected
- Letting an approved work order start a builder with no session (unattended code changes): deferred, not built.
- Prompt-only style guidance; a native Android app; storing prompts only in the DB (two sources of truth).
