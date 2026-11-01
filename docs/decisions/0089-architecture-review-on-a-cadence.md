# ADR 0089 — The architecture review runs weekly from probes, and a drafted work order's tier follows the path it touches

**Status:** accepted 2026-11-01 (Amit: "build 8 and 9 and other functionality that system architect was supposed to do … run on a cadence and make it tiered"). Extends ADR 0085 (janitor routines) and ADR 0086 (approval tiers); plan [0032](../plans/0032-janitor-routines.md) stage 6.

## Decision
- **The system-architect seat is a desk seat with a cadence and keeps its builder file.** Every Saturday `tools/arch_probes.py` runs and the seat judges the findings in a memo (`org_arch_review`: `fix` / `inline` / `keep` / `adr` / `needs-more-data`). As a builder it still writes ADRs when a session asks. A `keep` with a reason is never raised again.
- **The mechanical part of the seven blocks and five invariants is probed, not remembered:** layer crossings (a block importing a block above it), single-caller abstractions and pass-through wrappers outside the view layer, home-made base classes and YAML (ADR 0004), hard-coded tier lists (segment), the same constant bound twice, `time.sleep` outside the host door (politeness), a pipeline step touching a registered table its `PIPELINE_STEPS` entry does not declare (post-checks decide success), modules over 1,500 lines and functions over 120. Each has a planted fault in the drill. The three ratchet tests on push stay.
- **A drafted work order's tier is decided by the path it touches** (`org_kinds.tier_for`, `TIER_A_PATHS`): live options, `run.sh`, the crontab, `config.py`, `factors.py`, `schema.sql`, the Kite sources are Tier A and wait for the CEO; everything else is Tier B and approves itself after 48 h. The server drafts one order per tier from a memo, so a Tier A item never delays the Tier B ones.

## Why
- Routines 8 and 9 of the Anthropic list (abstraction police, abstraction improver) had no counterpart: three invariants were ratcheted on push, the rest was a rule in an agent file that ran only when someone asked.
- First sweep 2026-11-01: 11 pipeline steps touch tables they do not declare (`signal_multibagger` reads six, `fetch_corp_actions` writes three), 57 hard-coded tier lists, 18 sleeps outside the door, 16 layer crossings, 2 home-made base classes. None of it was visible before.
- `validators/` and `views.py` are core (write contracts, the read model), not the check or view block: the first calibration misfiled 35 imports because of that.

## Consequences
- `org.ROLES["system-architect"]` is `type: desk, agent: True, cadence: weekly:sat`; charter `.claude/routines/roles/system-architect.md`; graded by compliance.
- The checklist item "graph_shadow undeclared reads ≠ {}" (plan 0015) is now a weekly finding instead of a note.
