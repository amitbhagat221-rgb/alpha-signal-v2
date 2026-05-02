# Archive

Dated history. **Never edit. Never delete. Never reference as authoritative.**

## What lives here

- Old planning docs that were implemented (the plan is done; the file is history)
- Past instructions from one-off sessions (C12, C13, D14 etc.)
- Backups of CLAUDE.md from earlier eras
- Anything that was once "current" but isn't anymore

## What does NOT live here

- Things we might still need: those go in `reference/` or `runbooks/`
- Decisions: those become ADRs in `decisions/`
- Active plans: those stay in `plans/`

## Filename format

```
YYYY-MM-DD-short-kebab-title.md
```

The date is when the doc became *historical*, not when it was originally written. (i.e. the date you moved it to archive.)

## Why we keep this

Three reasons:

1. **Git already has history**, but git history is hard to skim. A flat folder of dated MDs is grep-able.
2. **Past plans contain context** — why we considered a thing, what we rejected, what surprised us. Useful when the same question comes up again.
3. **The user said "log them, don't delete"** — early principle of this project: understand provenance before removing things.

## Index (auto-grows over time)

```bash
ls -la docs/_archive/
```

Recent archives appear at the top of the listing when sorted by date prefix.
