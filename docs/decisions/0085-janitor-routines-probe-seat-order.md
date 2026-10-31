# ADR 0085 — Janitor routines: a probe finds, a seat judges, a work order changes

**Status:** accepted 2026-10-31 (Amit: "yes to all please implement the plan", calls J1–J6 as proposed, J4 "not yet"). Extends ADR 0057 (the agent org) and ADR 0058 (no unattended builder runs); plan [0032](../plans/0032-janitor-routines.md).

## Decision
- **Three janitor routines, in this order (J1):** the Data Bug Fixer (plan 0027's error classes as probe rules, the pick-touching ones daily), the Code Janitor (dead code, tests that cannot fail, flaky steps, stale flags, duplicates), the Data Simplifier (tables with no reader, one concept in two tables; gated on ADR 0084).
- **Every janitor is the same three parts.** A deterministic **probe** on cron sees code or data and writes facts with the query or scan that shows each one (`tools/dq_probes.py` for data, a `tools/code_probes.py` to come). A desk **seat** judges the facts and writes a memo; it has no shell and no file access, and the server re-runs its counts. A **work order**, approved by Amit and run with `/work-order N` in a Claude Code session, makes the change on a branch. The schedule can change nothing.
- **J3 — a confirmed fault touching the picks drafts its own work order.** When the dq-auditor calls a brief finding `real` with impact `picks`, the server (`alpha_mcp.org_kinds._draft_fix_order`) writes one work order "awaiting approval", parented to the memo, with two steps per finding: quarantine the rows and attach the pick diff first, then fix at the source. Amit still approves each. The seat never writes it.
- **J4 — no unattended instrumentation yet.** The Code Janitor's "log first, delete later" stickers (`run_events` lines on suspect code) are a work order for the first month; revisit after the accept rate is known.
- **J5 — cadence and model:** janitor memos weekly on Sunday on the stronger model, like the dq-auditor; pick-touching data rules every morning as the health check `DATA_FAULT_IN_PICK_INPUTS`.
- **J6 — what counts as dead:** no static reference and 90 days of silence in `run_events` after the sticker; a deletion reverted within 30 days counts against the seat. Accepted versus rejected proposals per seat is the scorecard (the merge rate).

## Why
- Anthropic's Claude Code team runs about twelve daily maintenance routines on its six codebases through Slack: 388 PRs in the first weeks, 180 merged after two reviews; misses tune the instruction, not the code (The Decoder, 2026-08-14; `docs/research/0021…html`). The transferable parts are one job per routine, always a draft never a commit, and tuning the note.
- Our faults have lived in data, not code: every one of plan 0027's eleven error classes was found by an agent reading a filing, never by a check. Rules with planted faults turn that into a morning check.
- A `tools/dq_probes.py` drill had been failing silently since 2026-10-08 (a rule read `transcripts`, which the scratch copy never held); the weekly brief swallowed the error. The fix is in this change, and a drill that cannot run is now a finding of its own.

## Consequences
- Plan 0027 classes 1–5 and 8 are rules with a planted fault each; classes 6, 7, 9 and 11 need text reading and stay the seat's own digging until an LLM probe exists.
- `org.save_work_order` takes a parent; a re-run memo retires its drafted order like its asks and cards.
