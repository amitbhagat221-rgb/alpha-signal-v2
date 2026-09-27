# Plans

> Quick "what's done / what's pending" view: [0000-checklist.md](0000-checklist.md). Start there.

A plan is temporary scaffolding: what problem, what the solution looks like, **Done when**, open
questions, considered-and-rejected. When a plan is done or superseded, its lasting content goes into
`decisions/` or `reference/` and the file moves to [`../_archive/plans/`](../_archive/plans/)
(same filename, so links and `git log --follow` still work).

Status values: `active` · `paused` · `done` / `implemented` · `superseded` · `closed`.
Numbering is chronological and never reused ([ADR 0016](../decisions/0016-plan-numbering-fresh-start.md)).
Work inside plan 0011 is labelled by workstream (`WS1.1`, `WS2.8`, …); the older
Track 1/2/3 labels ([ADR 0015](../decisions/0015-track-numbering-and-rename.md)) appear only in archived plans.

## Active

| Plan | What |
|---|---|
| [0011-roadmap-to-90.md](0011-roadmap-to-90.md) | **Master plan.** Roadmap to a 90/100 shop — workstreams WS1–WS7; decisions D1–D12 in [ADR 0051](../decisions/0051-roadmap-to-90-decisions-d1-d12.md) |
| [0014-data-acquisition-roadmap.md](0014-data-acquisition-roadmap.md) | Data-layer view across plan 0011's workstreams — free-first; paid fork costed separately |
| [0015-first-principles-architecture.md](0015-first-principles-architecture.md) | **Proposed.** First-principles architecture: 7 building blocks, 5 invariants, strangler migration P0–P6 ([ADR 0052](../decisions/0052-seven-building-blocks.md)) |

## Paused (kept live; resume only via a checklist bullet)

| Plan | What |
|---|---|
| [0003-market-share-momentum-factor.md](0003-market-share-momentum-factor.md) | Sector-narrative factor cluster (4 factors) |
| [0004-consumer-demand-pulse.md](0004-consumer-demand-pulse.md) | Search-pulse consumer-demand signal, research-first |
| [0009-crypto-convex-cockpit.md](0009-crypto-convex-cockpit.md) | Separate crypto "lottery-ticket" product (own repo/venv/DB); Phase 0 kill-gate not started |

## Archived (`../_archive/plans/`)

| Plan | Outcome |
|---|---|
| [0001 mother-plan](../_archive/plans/0001-mother-plan.md) | Superseded by plan 0011 (Track 2 Portfolio ladder) |
| [0002 100-factors-and-model](../_archive/plans/0002-100-factors-and-model.md) | Superseded by plan 0011 (Track 3 Factor model) |
| [0005 data-confidence-to-95](../_archive/plans/0005-data-confidence-to-95.md) | Implemented — [ADR 0024](../decisions/0024-per-signal-eligibility-and-per-stock-integrity.md) |
| [0006 sector-dossiers](../_archive/plans/0006-sector-dossiers.md) | Implemented 2026-05-31 |
| [0007 trust-pipeline-uhs](../_archive/plans/0007-trust-pipeline-uhs.md) | Implemented — [ADR 0033](../decisions/0033-trust-pipeline-uhs.md), [0037](../decisions/0037-per-stock-uhs-and-pt-plausibility.md) |
| [0008 multibagger-model](../_archive/plans/0008-multibagger-model.md) | Closed — selection track closed by [ADR 0040](../decisions/0040-multibagger-holding-not-selection.md) |
| [0010 audit-remediation](../_archive/plans/0010-audit-remediation.md) | Done 2026-07-05 |
| [0012 sonnet-tasks-execution-and-factors](../_archive/plans/0012-sonnet-tasks-execution-and-factors.md) | Done 2026-07-11 — evidence in [`../studies/`](../studies/) |
| [0013 sonnet-tasks-event-infra-and-factors](../_archive/plans/0013-sonnet-tasks-event-infra-and-factors.md) | Done 2026-07-11 — event studies NULL |

Pre-2026-05-22 plans (old numbering) live in `../_archive/` as `2026-05-22-plan-NNNN-*.md`:
regulatory-signal, macro-data, pit-reconstruction (ADRs 0010/0012), sector-intelligence-page (ADRs 0013/0014).
