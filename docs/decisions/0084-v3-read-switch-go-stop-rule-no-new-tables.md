# ADR 0084 — Data model v3 read switch: go with a stop rule, no new tables, ranking stages merge on Amit's OK

**Status:** accepted 2026-10-31 (Amit: "yes to all please implement the plan", on plan 0030 D1–D3 as proposed). Extends ADR 0054 (tables grow with concepts) to the read side; plan [0030](../plans/0030-v3-read-switch.md) is the schedule.

## Decision
- **D1 — Go, with a stop rule.** Stages 0–2 of plan 0030 run (measure, Decisions, Company facts), then a review. A concept whose readers are not switched within 8 weeks of its stage starting has its mirror stopped and its v3 tables dropped after a Parquet export; the legacy tables stay the model for that concept. Nothing is synced forever without a reader.
- **D2 — No new tables.** From 2026-10-31 a new dataset is a `catalog` row in an existing concept (Documents, Events, Company facts, Bars, Decisions, Reference, Series, Features) unless it is ops state: a lock, a ledger, a cache or a manifest. The tables added outside v3 since 2026-10-01 each get a target concept or a written "stays as-is" reason in plan 0030's stage-0 notes (12 fold in, 8 stay).
- **D3 — Ranking-affecting stages (2, 4, 5, 6) merge only on Amit's OK**, after a measured identical-ranks gate on 3 dates. Stages 1 and 3 merge on the standard parity gate.

## Why
- Measured 2026-10-31 (stage 0): the 24 v3 tables and their indexes hold 12.6 GiB, 51.5 % of the 24.4 GiB file, while nothing in production reads them; `events` is 2.8× `bse_announcements` and `feature_values` 9× `daily_snapshots_pit` plus the score tables. The mirror is a cost until a stage drops its legacy tables, so an open-ended mirror is the worst of both.
- 311 production files name a mirrored legacy table (`stocks` 220, `stock_prices` 89); the switch has to be ordered and bounded or it never ends.
- About 20 tables were created outside the design in October alone, which broke plan 0017's "0 tables per new thing" criterion within a month of approval. D2 is the habit change; the mapping is in plan 0030's notes.

## Consequences
- Stage 0 is done (reader inventory, disk per table, the mapping); stage 1 (Decisions) is next, on a worktree branch.
- `datamodel/reconcile.py`'s RETIRED list is the register of D2 exceptions; a new "kept as-is" entry needs the reason written there.
