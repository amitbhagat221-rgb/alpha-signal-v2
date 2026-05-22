# Plans

> Quick "what's done / what's pending" view: [0000-checklist.md](0000-checklist.md). Start there.

Proposals for things being built or about to be built. Temporary scaffolding — when work is done, the plan's permanent content distills into `architecture.md` / `reference/` / `decisions/`, and the plan moves to `_archive/`.

## Plan format

Each plan starts with frontmatter:

```yaml
---
Status: proposed | active | implemented | paused | blocked
Created: YYYY-MM-DD
Last updated: YYYY-MM-DD
Owner: <name>
Implementation: <link to code or short status>
Related ADRs: <list>
---
```

A plan answers: **What problem? · What does the solution look like? · Done when? · Open questions? · Considered & rejected?**

Naming + numbering convention: see [ADR 0015](../decisions/0015-track-numbering-and-rename.md). Three tracks (Foundation / Portfolio / Factor model); decimal phases (2.1, 2.2); forks (3.1a, 3.1b); cross-track parallels (↔).

## Active

| Plan | Status |
|---|---|
| [0001-mother-plan.md](0001-mother-plan.md) | active — Track 2 (Portfolio) ladder, 2.2 next |
| [0002-100-factors-and-model.md](0002-100-factors-and-model.md) | active — Track 3 (Factor model), Phase 3.1a done, 3.2 underway |

## Proposed

| Plan | Status |
|---|---|
| [0003-market-share-momentum-factor.md](0003-market-share-momentum-factor.md) | proposed — 4-factor cluster, ~7 hr |
| [0004-consumer-demand-pulse.md](0004-consumer-demand-pulse.md) | proposed — research-first, validation-gated |

## Archived (in `_archive/` as `YYYY-MM-DD-plan-NNNN-*.md`)

- 0001 regulatory-signal — implemented
- 0002 macro-data — implemented
- 0004 pit-reconstruction — shipped (ADRs [0010](../decisions/0010-pit-strict-corporate-action-adjustment.md), [0012](../decisions/0012-pit-archive-refresh-on-signal-fix.md))
- 0006 sector-intelligence-page — implemented (ADRs [0013](../decisions/0013-industry-not-sector-as-drill-unit.md), [0014](../decisions/0014-llm-sourced-competitive-landscape.md))
