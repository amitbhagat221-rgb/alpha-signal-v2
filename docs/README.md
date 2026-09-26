# Documentation Index

## Root files

| File | Question |
|---|---|
| [../README.md](../README.md) | What is this project? |
| [../CLAUDE.md](../CLAUDE.md) | What are the rules? |
| [../HANDOFF.md](../HANDOFF.md) | Where am I right now? (overwritten each session) |
| [../OPERATOR.md](../OPERATOR.md) | How do I run, recover or inherit it? (cron, services, backups, credentials) |

## docs/ folders

| Folder | Question | Lifecycle |
|---|---|---|
| [plans/](plans/) | What am I building? Index: [plans/README.md](plans/README.md) | active → done/superseded → `_archive/plans/` |
| [decisions/](decisions/) | Why did we choose X? [decisions/README.md](decisions/README.md) gives the current decision per topic plus the full ADR index | write-once; superseded ADRs get a forward `Status:` line |
| [reference/](reference/) | How does X work? Architecture, data playbook, weights, cockpit, commands | edited in place when reality changes |
| [research/](research/) | What did deep research conclude before we build? Charters that gate plan-0011 workstreams | written once per question |
| [studies/](studies/) | What did the evidence say? Backtest/re-baseline/event-study write-ups that ADRs and plans cite | write-once, dated |

[`_archive/`](_archive/) is history. Don't edit it or treat it as authoritative, but search it when you wonder "did we try this?". Subfolders mirror the live tree: `_archive/plans/`, `_archive/decisions/`, `_archive/reference/`. Older flat files use `YYYY-MM-DD-*.md` names. Retired code lives in the repo-root `_archive/`.

## Routing by question

| Your question | Where |
|---|---|
| Where am I right now? | [../HANDOFF.md](../HANDOFF.md), [plans/0000-checklist.md](plans/0000-checklist.md) |
| What's the rule for X? | [../CLAUDE.md](../CLAUDE.md) |
| How does the system fit together? | [reference/architecture.md](reference/architecture.md) |
| Where does data come from? | [reference/data-playbook.md](reference/data-playbook.md). Read it before fetching |
| Which factors carry weight and why? | [reference/signal-weights.md](reference/signal-weights.md) |
| What runs when? | [../OPERATOR.md](../OPERATOR.md) §2, `config.PIPELINE_STEPS` |
| What changed recently? | `git log` |

## The rule

If a new doc doesn't fit a folder above, ask: would I open this in 3 months? If not, skip it. If so, put it in the closest folder. Prefer pointing at code (`config.PIPELINE_STEPS`, `db.BACKTEST_SIGNALS`, `schema.sql`) over copying counts that drift.
