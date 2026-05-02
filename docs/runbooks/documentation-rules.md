# Runbook: Documentation Rules

**When to use this:** Before creating any new `.md` file. Or when something feels "off" about where to put something.
**Time:** 2 min read
**Risk:** safe

## The 4 Hard Rules

### Rule 1: Three root files only

The project root contains exactly three markdown files. Forever.

| File | Purpose | Length |
|------|---------|--------|
| `README.md` | What this project is, how to run it | ≤120 lines |
| `CLAUDE.md` | AI assistant context: critical rules + pointers | ≤200 lines |
| `CHANGELOG.md` | What changed, when (newest at top) | grows over time |
| `HANDOFF.md` | Current state: where am I, what's next | ≤80 lines |

If you want to add a fourth file, **stop**. It belongs in `docs/`.

### Rule 2: Every doc has a category

Before creating a `.md` file in `docs/`, decide which folder it belongs to.

| Question you're answering | Folder |
|---------------------------|--------|
| How does the system work right now? | `architecture.md` (one file) |
| Why did we choose X? | `decisions/` |
| How do I do X? | `runbooks/` |
| What is X? (table, signal, source) | `reference/` |
| What might we do? (not built yet) | `plans/` |
| What did we used to think? | `_archive/` |

If your doc doesn't fit any category, the doc is probably wrong — split it
or rethink it. Example: a "data source overview" that mixes (a) what each
source is, (b) why we chose it, and (c) how to refresh it should be split
into reference/data-sources.md, decisions/000N-source-choice.md, and
runbooks/refresh-data.md respectively.

### Rule 3: ADRs are write-once

Once an Architecture Decision Record is committed:
- Never edit the body
- Never renumber
- If the decision changes, write a new ADR that supersedes the old one

This is what makes them trustworthy. Mutable docs decay; immutable ones don't.

### Rule 4: Every doc has an update trigger

Every doc in this project has exactly one event that triggers an update:

| Doc | Update trigger |
|-----|----------------|
| README.md | When the elevator pitch or top-level commands change |
| CLAUDE.md | When Claude does something you want permanently prevented |
| HANDOFF.md | End of every working session (overwritten, never appended) |
| CHANGELOG.md | When something user-visible ships |
| architecture.md | When the system shape actually changes |
| decisions/NNNN-*.md | Never (write-once); supersede with new ADR if needed |
| runbooks/*.md | When the procedure actually changes |
| reference/*.md | When the underlying thing changes |
| plans/NNNN-*.md | Status field updates as lifecycle moves |

If a doc has no update trigger, it's a snapshot. Snapshots belong in
_archive/ with a date prefix.
---

## The Decision Tree

You have new content to capture. Where does it go?

```
Is it a critical rule or a pointer to current state?
└── YES → Goes in CLAUDE.md (root)

Is it a one-paragraph "what is this project"?
└── YES → Goes in README.md (root)

Is it a step-by-step procedure I'll do again?
└── YES → docs/runbooks/

Is it a description of how a specific thing works?
   (table, signal, data source, formula)
└── YES → docs/reference/

Is it the rationale behind a choice?
└── YES → docs/decisions/  (as an ADR — write-once)

Is it about something not yet built?
└── YES → docs/plans/

Is it something that was once true but isn't anymore?
└── YES → docs/_archive/  (with YYYY-MM-DD- prefix)

Is it the current state of in-flight work — what I'm doing right now,
where I left off, what's next?
└── YES → HANDOFF.md (root, overwritten each session)

None of the above?
└── It probably shouldn't be a doc at all.
    Either it's a code comment, or a CHANGELOG entry, or unnecessary.
```

---

## Length budgets

Documents that drift past their length budget are usually doing two jobs.

| Doc type | Budget | If exceeded |
|----------|--------|-------------|
| README.md | 120 lines | Move details to docs/ and link |
| CLAUDE.md | 200 lines | Move architecture/details to docs/architecture.md |
| ADR | 30 lines | You're hedging, not deciding. Trim or split. |
| Runbook | 100 lines | Probably 2 runbooks merged. Split. |
| Reference doc | no limit | But use tables, not prose |

---

## CHANGELOG.md format

Newest at the top. One entry per real change. Format:

```markdown
## YYYY-MM-DD

- **What changed.** Optional one-line "why".
- **Another thing.** Optional context.
```

Skip entries for typos, formatting, comment changes. Only log things future-you would want to know.

---

## When in doubt

If you don't know where a doc goes, ask: would I open this file again
in 3 months? If no, skip it — it's a thought, not a doc. If yes, force
yourself to pick a category. The forcing is the value: it makes you
articulate what the doc is *for*, which often reveals it doesn't need
to exist.

If you genuinely have a half-formed idea worth capturing but not yet
worth a plan, put it in `docs/plans/_ideas/` with a one-line description.
That folder is the only legitimate "I'll figure it out later" location.
---

## Maintenance

Once a quarter (or when it feels stale):

1. Skim `docs/README.md` — does the index still match what's in `docs/`?
2. Skim `docs/plans/` — any plans that have been implemented? Move them to `_archive/`.
3. Skim `CLAUDE.md` — over 200 lines? Push detail down into `docs/`.
4. Skim project root — any new floating MDs? Move them or delete.
5. Glance at HANDOFF.md — is it from this week? If older, write a fresh one.

Don't let it pile up. The whole point of this structure is to **stay scannable**.
