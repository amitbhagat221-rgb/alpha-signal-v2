# Plans — Active Proposals

Active proposals for things **not yet built**. A plan is a thinking document — it captures what we'd do, why, and what we considered before committing to code.

---

## The Plan Lifecycle

```
[draft a plan] → [discuss] → [implement] → [archive]
                              │
                              ↓
                              ↓ extract permanent learnings into:
                              ↓   - architecture.md  (how it works now)
                              ↓   - reference/       (its details)
                              ↓   - decisions/       (an ADR if a key choice)
                              ↓
                              [move plan to _archive/ with date prefix]
```

A plan should never become a permanent doc. **Plans are temporary scaffolding.** When the work is done, the plan's job is done — its useful content has been distilled into reference/ and decisions/, and the plan itself becomes history in `_archive/`.

---

## Plan Format

A plan can be loose, but should answer:

1. **What problem are we solving?**
2. **What does the solution look like?** (sketch, schema, sequence)
3. **What are the open questions?**
4. **What does success look like?**
5. **What did we consider and reject?**

---

## Status Header Fields

Each plan file starts with a YAML frontmatter block:

```yaml
---
Status: [leave blank or use: draft, active, blocked, ready-to-implement, paused]
Created: YYYY-MM-DD
Last updated: YYYY-MM-DD
Owner: [name]
Implementation: [link to related code/PR, or leave blank]
Related ADRs: [comma-separated ADR filenames, or leave blank]
---
```

---

## Index

| Plan | Status | Created | Owner |
|------|--------|---------|-------|
| [0001-regulatory-signal.md](0001-regulatory-signal.md) | Implemented — distillation pending | 2026-04-10 | Amit Bhagat |
| [0002-macro-data.md](0002-macro-data.md) | Implemented — distillation pending | 2026-04-10 | Amit Bhagat |
