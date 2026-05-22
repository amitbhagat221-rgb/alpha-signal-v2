# 0016 — Plan numbering reset to chronological fresh start
**2026-05-22 · Accepted**

**Decision.** The four active/proposed plans are renumbered to a contiguous chronological sequence starting at 0001. `0000-checklist.md` (meta/index) keeps its slot.

| Old | New | Plan |
|---|---|---|
| `0003-mother-plan.md` | `0001-mother-plan.md` | Track 2 (Portfolio) ladder · Created 2026-05-03 |
| `0005-100-factors-and-model.md` | `0002-100-factors-and-model.md` | Track 3 (Factor model) · Created 2026-05-03 |
| `0007-market-share-momentum-factor.md` | `0003-market-share-momentum-factor.md` | Sector-narrative factor cluster · Created 2026-05-10 |
| `0008-consumer-demand-pulse.md` | `0004-consumer-demand-pulse.md` | Research-gated search-pulse signal · Created 2026-05-12 |

**Why.** Plan numbering had gaps from archiving (0001, 0002, 0004, 0006 are in `_archive/`). The gaps were historical noise that made the active set look fragmented. A fresh contiguous sequence reads cleanly and the archive keeps the historical numbering via its dated filenames (`2026-05-22-plan-0001-regulatory-signal.md`, etc.). Plan slugs are not load-bearing identifiers — they exist for human navigation.

**What stays.**
- **ADR numbers** are write-once and contiguous; no ADR renumbered.
- **Archived plans** in `_archive/` keep their old numbers in the filename — they're historical record.
- **Plan slugs** (the kebab-case part after the number) are unchanged.

**Side effects.** Cross-references in plans, ADRs, reference docs, root docs, and code comments updated to new numbers in the same commit. Verified by grep returning zero stale `plan 0003/0005/0007/0008` or `0003-mother-plan` / `0005-100-factors` / `0007-market-share` / `0008-consumer-demand` references.

**Rollback.** Forward-only. The mapping table above is the historical record.

**Related.**
- [ADR 0015](0015-track-numbering-and-rename.md) — track numbering convention (the same coherence drive). That ADR's body claimed "plan filenames keep their slugs" — superseded by this ADR only on that point.
