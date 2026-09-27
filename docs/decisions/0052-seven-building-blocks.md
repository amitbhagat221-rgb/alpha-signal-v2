# ADR 0052 — Seven building blocks: the system is one as-of dataflow graph

Status: **proposed** 2026-09-27 (awaiting Amit) · Amends [ADR 0004](0004-no-base-classes-no-yaml.md) (one inversion, see below) and [ADR 0017](0017-factor-library-two-tier-registry.md) (weights move into the factor entry) · Plan [0015](../plans/0015-first-principles-architecture.md)

## Decision
The whole system is built from 7 building blocks, **Host, Dataset, Node, Feature, Model, Check, View**, and 5 invariants that the runner enforces.
Each block is a plain dict, declared once and next to the function it describes. Order, lineage, freshness, heal targets, the /flow page, the critical path, eligibility views, PIT columns and the evidence roster are all **derived**; none are hand-kept.
Live is the backtest evaluated at `t = today`: one `features_at(names, t)` code path serves the screener, PIT reconstruction, replay and the backtest.

## Context
A read-only audit on 2026-09-27 found the following. Details and file:line citations are in plan 0015 §Evidence.
- **Pipeline order is hand-kept.** 85 steps are ordered by list position. None declares its inputs, so order, freshness, the /flow page and lineage are hand-kept or regex-scanned. Freshness and heal disagree on who owns a shared table: `db.table_step_meta` takes the last producer, the watchdog takes the first.
- **Live ≠ PIT for wired factors.** Piotroski differs on 819 of 2,220 overlapping (sid, date) rows. `consensus` is a different quantity in PIT: EPS revision instead of the PT/growth blend. Only about 45 of 67 PIT producers share the live function.
- **The backtest panel is frozen at 2026-07-01.** reconstruct_pit is not scheduled, yet the monthly backtest still re-scores that panel.
- **Quality is spread across about 8 registries** (≈1,000 hand-kept fields). Examples: 3 different M-score ranges, MICRO flagged invalid by health.py, and 26 hand-rolled raise-on-zero sites. The one critical fetcher, bhavcopy, returns 0 on a failed download and the runner logs SUCCESS.
- **The picks read-model is written 11 times, with 3 different gate sets.** Dossiers cover only the LARGE top 5, and the email colours the live CALM regime as "unknown".
- **Adding a factor touches 10-11 files.** A tier literal is repeated at 43 sites.

## The blocks (one line each; full definitions in docs/reference/architecture.md)
| Block | Is | Declared in |
|---|---|---|
| Host | an external dependency and its politeness: gap, lock, time or token budget | `hosts.HOSTS` |
| Dataset | a table: kind (event/series/state/feature/log) → write mode, as-of rule, staleness | `schema.sql`; kind inferred from PK, overrides in `datasets.py` |
| Node | `fn(ctx)` plus `NODE = {reads, writes, cadence, hosts}` in the same module | `sources/`, `scoring/`, `output/` modules |
| Feature | a pure `fn(frames_asof) → frame` plus a `FACTORS` entry (range, eligibility, weights) | `signals/` + `factors.py` |
| Model | segment → rank-within-segment → blend → gate → select → size | `scoring/` + `config.TIERS` |
| Check | a predicate on a dataset or node output; one runner, one verdict table | derived from blocks; custom checks in `checks/` |
| View | a named read-model used by every surface | `views.py`; pages in `cockpit/pages.py` |

## Invariants (enforced by the runner or by a test, not by CLAUDE.md)
1. **As-of.** Features and Models see data only through `asof(dataset, t)`. A `signals/` module cannot import `db` (test).
2. **Segment.** Ranking happens only inside `config.TIERS` segments; tiers with `pickable=False` never reach picks.
3. **Kind decides write and staleness.** Writers never choose INSERT mode. Episodic data is a `series` at its cadence.
4. **A node succeeds only when its post-checks pass.** Declared outputs must be fresh as of the expected date and pass their ranges. Narrative columns must contain no numbers.
5. **Politeness.** Every external call goes through one door per Host, with a lock, a gap and a budget. Declared reads must cover the tables SQLite observes the step reading (test).

## ADR 0004 amendment
A Node or Feature may **return frames and let the runner write them**. It may also still write itself and return a row count, which is the strangler path. This inverts control in a single place (`pipeline.run_node`, ≈150 LOC). There are still no base classes, YAML or DSL. The trade-off is that a stack trace passes through the runner once.

## Consequences
- **Every change scenario touches at most 2 places** (plan 0015 table). The exceptions are renaming a core-table column (3 places) and adding a tier (1 place plus the weight content).
- **Projected LOC change: about −4.5K net (range −3.5K to −6K), roughly 8% of the 59K live Python.** This is 5.6K removed and 1.1K added (runner, graph, views, checks). The bigger cut is to hand-kept entries: lineage (105), PIT_PRODUCERS (68), TABLE_PROFILES (36), tier literals (43) and the critical-step lists all disappear. `tools/` (14.5K, mostly research) is out of scope.
- **Unifying live and PIT changes the numbers for 6 wired factors.** It is listed as an intentional behaviour change needing per-factor sign-off (plan 0015 D1). Every other phase must be equivalence-gated to identical output.
- **Not chosen:** a workflow engine such as Airflow or Dagster, because SQLite plus one runner is enough; an ORM; DDL generated from dicts, because schema.sql remains the column owner; and module-level class registries.
