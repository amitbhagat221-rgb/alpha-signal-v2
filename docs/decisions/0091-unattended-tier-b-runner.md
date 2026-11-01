# ADR 0091 — Approved Tier B work orders run unattended at night, inside hard limits, each with a plain-words memo

**Status:** accepted 2026-11-01 (Amit: "build the unattended … a memo in finshots style … guardrails such that the unattended does not run indefinitely and does not break anything"). Switches on what ADR 0086 allowed and ADR 0058 had forbidden; plan [0032](../plans/0032-janitor-routines.md) stage 7.

## Decision
- **`run.sh work_orders` at 21:30 UTC runs `tools/work_runner.py`:** every work order that is `approved` (by the CEO or by the 48-hour default), Tier B, with no item on a Tier A path, oldest first, at most two a night. Each runs as a headless Claude Code builder (`claude -p`, the owner seat's agent file as system prompt) in its own worktree branched from master.
- **The runner merges a result only when all of these hold:** the builder exited cleanly and changed something; the diff is at most 25 files and 1,500 lines, touches no Tier A path and nothing under `ops/`, settings, hooks, `data/`, `run.sh`, `schema.sql` or secrets; a deleted file is named by an item; the full test suite passes in the worktree; no other session has uncommitted edits in the same files. Then it merges with `--no-ff`, pushes master through the usual pre-push suite, and records `done` with the sha. Anything else records `blocked` (or leaves the order `approved` for one more try) with the reason.
- **It cannot run away:** a kill-switch file (`output/work_runner.off`), a quiet window 02:00–08:00 UTC around the pipeline and the org, one runner at a time, 45 minutes per order, 110 minutes a night, two attempts per order ever, a tool allowlist (file tools, pytest, git diff / status / log, ls, the probes; nothing else), no `ALPHA_DB` in the worktree, no API key (the subscription, as the org).
- **Every order gets a memo on the Boardroom** (`runner_memo`, role `work-runner`): the builder's own story for a non-programmer (what the job was, what changed, how it was checked, what was left alone and why), the files and lines, the suite result, whether it merged and pushed, the worries, and the one undo command `git revert -m 1 <sha>`. A push goes to the phone when a run happens.

## Why
- The approvals no longer waited for Amit (ADR 0086), but the execution still did: an approved order ran only when someone opened a session and typed `/work-order N`.
- The headless mechanism already carried the org for a month (`run.sh org`): same binary, same subscription, same "no human at the keyboard".
- The limits are the ones a careful colleague would set for a night shift: small diffs, no money or schedule paths, tests before merging, a way to stop it, and a note on the desk in the morning.

## Consequences
- The seat that proposed an order is scored on it (plan 0032 stage 5): a merge reverted within 30 days counts against it.
- `tests/test_work_runner.py` covers every guardrail that needs no live builder; the builder itself is exercised by the first nights.
- `org.MEMO_TYPES` includes `runner_memo`; `WORK_STATUSES` unchanged.
