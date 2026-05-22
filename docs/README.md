# Documentation Index

3 files in head, 3 folders in head. That's the whole system.

---

## Root (3 files)

| File | Question |
|---|---|
| [../README.md](../README.md) | What is this project? |
| [../CLAUDE.md](../CLAUDE.md) | What are the rules? |
| [../HANDOFF.md](../HANDOFF.md) | Where am I right now? (overwritten each session) |

No other files belong at root.

---

## docs/ (3 folders)

| Folder | Question |
|---|---|
| [plans/](plans/) | What am I building? Numbered proposals with status (proposed / active / implemented). |
| [decisions/](decisions/) | Why did we choose X? ADRs, write-once, ≤30 lines each. |
| [reference/](reference/) | How does X work? Schema, signals, data sources, architecture, commands. |

[`_archive/`](_archive/) is dated history — never edit, search when you wonder "did we try this?".

---

## Routing by question

| Your question | Where |
|---|---|
| Where am I right now? | [../HANDOFF.md](../HANDOFF.md) |
| What's the rule for X? | [../CLAUDE.md](../CLAUDE.md) |
| How does the system fit together? | [reference/architecture.md](reference/architecture.md) |
| Where does data come from? | [reference/data-playbook.md](reference/data-playbook.md) ⚠ read before fetching |
| What's the schema / signal weights / commands? | [reference/](reference/) |
| Why did we choose X? | [decisions/](decisions/) |
| What's planned next? | [plans/](plans/) |
| What did v1 look like? | [_archive/](_archive/) |
| What changed recently? | `git log` |

---

## The rule

If a new doc doesn't fit `plans/`, `decisions/`, or `reference/`, ask: would I open this in 3 months? If no, skip. If yes, force one of the three.
