# Runbooks

Step-by-step guides for things you do periodically. **Imperative, not theoretical.** A good runbook answers "what do I type, in what order, to accomplish X."

## When to write a runbook

Write a runbook the **second time** you do a task. The first time you're learning; the second time you're reproducing — that's the moment to capture the steps.

## When NOT to write a runbook

If something only happens once (a migration, a rebuild), it's not a runbook — it's an `_archive/` entry after the fact.

## Format

Every runbook follows this structure:

```markdown
# Runbook: [Task Name]

**When to use this:** One-line trigger ("after a failed pipeline run", "monthly")
**Time:** 5 min | 1 hour | etc.
**Risk:** safe | requires care | destructive

## Prerequisites
- Things that must be true before starting

## Steps
1. Concrete command or action
2. What to expect
3. ...

## Verification
How to confirm it worked.

## Troubleshooting
Common failures and what to do.

## Related
- Pointers to ADRs, reference docs, or other runbooks
```

## Index

| Runbook | When |
|---------|------|
| [daily-pipeline.md](daily-pipeline.md) | Running the daily pipeline manually |
| [add-new-signal.md](add-new-signal.md) | Adding a new signal to the system |
| [add-new-source.md](add-new-source.md) | Adding a new data source |
| [debug-failed-run.md](debug-failed-run.md) | A pipeline step failed, what now |
| [documentation-rules.md](documentation-rules.md) | Where docs go and how to write them |
