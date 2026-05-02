# Documentation Index

The map of every doc in this project. CLAUDE.md and README.md both link
here as the entry point — start here when you need to find something.

If you're not sure where something belongs, see [runbooks/documentation-rules.md](runbooks/documentation-rules.md).

---

## How docs are organized

~/alpha-signal-v2/
├── README.md            ← What this project is
├── CLAUDE.md            ← Rules for Claude Code sessions
├── HANDOFF.md           ← Where I am right now (overwritten each session)
├── CHANGELOG.md         ← What shipped, when
└── docs/
├── architecture.md  ← ONE file: how the system works today
├── decisions/       ← ADRs: why we made each choice (write-once)
├── runbooks/        ← How-to: operational procedures
├── reference/       ← What-is: schema, signals, sources (current state)
├── plans/           ← Active proposals: not yet built
└── _archive/        ← Dated history: never edit, never delete

**Rule of thumb — where does this go?**
- *"What was I just doing?"* → `HANDOFF.md` (root)
- *"How does X work right now?"* → `docs/architecture.md` or `docs/reference/`
- *"How do I do X?"* → `docs/runbooks/`
- *"Why did we choose X?"* → `docs/decisions/`
- *"What's next?"* → `docs/plans/`
- *"What did we used to think?"* → `docs/_archive/`
- *None of the above* → it probably shouldn't be a doc

---

## Top-level docs (project root)

Only **four** files live in the project root. They are intentionally short.

| File | Purpose | Length | Update trigger |
|------|---------|--------|----------------|
| [README.md](../README.md) | What this project is, how to run it | ≤120 lines | When the elevator pitch or top-level commands change |
| [CLAUDE.md](../CLAUDE.md) | AI assistant context: critical rules + pointers | ≤200 lines | When Claude does something to permanently prevent |
| [HANDOFF.md](../HANDOFF.md) | Current state: where I am, what's next | ≤80 lines | End of every working session (overwritten) |
| [CHANGELOG.md](../CHANGELOG.md) | What changed, when (newest at top) | grows | When something user-visible ships |

If you find yourself wanting to add a 5th file to the root, **stop**. It belongs in `docs/`.

---

## docs/ contents

### [architecture.md](architecture.md)
Single source of truth for how the system works **right now**. Present tense only — no future plans, no past designs. Updated when reality changes (new layer added, modules restructured, data flow reroutes).

### [decisions/](decisions/) — Architecture Decision Records (ADRs)
One file per immutable decision. Format: `NNNN-short-title.md`. Once written, never edit content — only supersede with a new ADR if the decision changes. Target ≤30 lines each (longer means you're hedging, not deciding). See [decisions/README.md](decisions/README.md).

### [runbooks/](runbooks/) — Operational How-Tos
Step-by-step guides for tasks you do periodically but not daily. Write one the second time you do something — once is luck, twice is a procedure. Target ≤100 lines each. See [runbooks/README.md](runbooks/README.md).

### [reference/](reference/) — Long-Lived Reference
Schema definitions, signal formulas, data source gotchas. The encyclopedia. Updated when the underlying thing changes. Use tables over prose. See [reference/README.md](reference/README.md).

### [plans/](plans/) — Active Plans
Numbered proposals for things being built or about to be built. Format: `NNNN-name.md` with a status header (Draft / Active / Implemented / Deferred). When marked Implemented, the relevant changes get reflected in `architecture.md` / `reference/`, and the plan moves to `_archive/` within 30 days. See [plans/README.md](plans/README.md).

### [_archive/](_archive/) — Dated History
Old planning docs, instructions from past sessions, superseded designs. Filename format: `YYYY-MM-DD-short-title.md`. Never edited, never deleted. Search this when you wonder "did we already try this?" See [_archive/README.md](_archive/README.md).

---

## Quick links by question

Marked *(planned)* if the file doesn't exist yet.

| Your question | Where to look |
|---------------|---------------|
| Where am I right now? | [../HANDOFF.md](../HANDOFF.md) |
| How do I run the daily pipeline? | [runbooks/daily-pipeline.md](runbooks/daily-pipeline.md) |
| How do I add a new signal? | [runbooks/add-new-signal.md](runbooks/add-new-signal.md) *(planned)* |
| How do I add a new data source? | [runbooks/add-new-source.md](runbooks/add-new-source.md) *(planned)* |
| The pipeline failed, what now? | [runbooks/debug-failed-run.md](runbooks/debug-failed-run.md) *(planned)* |
| What's the schema of table X? | [reference/schema.md](reference/schema.md) *(planned)* |
| What does signal Y measure? | [reference/signals.md](reference/signals.md) *(planned)* |
| Why didn't we use Prefect? | [decisions/0002-no-prefect.md](decisions/0002-no-prefect.md) |
| Why bhavcopy instead of yfinance? | [decisions/0003-bhavcopy-over-yfinance.md](decisions/0003-bhavcopy-over-yfinance.md) |
| What's planned next? | [plans/](plans/) |
| What did v1 look like? | [_archive/](_archive/) (search for `v1` or `2026-04`) |

---

## Files that don't fit this structure

A few categories of files legitimately live outside `docs/`:

- `.claude/` — Claude Code configuration (commands, agents, hooks)
- `tests/` — test code, not documentation
- `scripts/` — utility scripts; if a script needs explaining, put a `--help` in it, not a doc
- `notebooks/` — jupyter notebooks for exploration and validation

If you're tempted to write a `.md` file inside one of these, ask: would it be more useful as a runbook in `docs/runbooks/`? Usually yes.