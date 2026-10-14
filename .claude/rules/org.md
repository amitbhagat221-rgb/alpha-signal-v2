---
paths:
  - "org.py"
  - "org_chat.py"
  - "alpha_mcp/**"
  - ".claude/routines/**"
  - ".claude/agents/**"
---
# The agent org (plan 0019)

- Every agent seat is ONE `org.ROLES` entry. A desk seat = a charter in `.claude/routines/roles/` + a role-owned task kind in `alpha_mcp/org_kinds.py` (brief, schema, ingest); a builder seat = `.claude/agents/<id>.md`. `tests/test_org.py` enforces it.
- Desk seats write ONLY through `alpha-work.submit` into `documents` (`source='org'`): never give one a shell, a table write, or a path to weights / config / cron.
- Memo numbers must come from the brief (validator-enforced); doer and grader are different seats.
- Amit tunes a seat (schedule, model, directive, prompt) from the ops cockpit `/org`: read the effective seat with `org.seat(role)`, never `ROLES[role]` directly. Charter / agent files may carry his uncommitted edits — don't revert them.
- Fixes he agrees with a seat arrive as numbered work orders: run one with `/work-order N` only if approved (`python -m org work N` shows it with its chat). Runbook: [org.md](../../docs/reference/org.md).
