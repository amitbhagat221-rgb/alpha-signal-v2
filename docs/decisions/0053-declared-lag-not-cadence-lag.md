# ADR 0053 — Lag is declared, and a lagged read sees the previous run's data

Status: accepted 2026-09-27 · Partly supersedes [ADR 0052](0052-seven-building-blocks.md) (it tied lagged edges to "coarser cadence or slow writer") · Plan [0015](../plans/0015-first-principles-architecture.md)

## Decision
1. **A read is blocking by default.** The reader sees THIS run's write, so the writer runs first.
2. **A read is lagged only by declaration.**
   - Writer side: `lagged_writes: [dataset]` ("my readers get this next run").
   - Reader side: `lagged_reads: [dataset | "dataset@writer"]`.
   - A lagged reader sees the PREVIOUS run's version, so it runs BEFORE the writer. Which version a read sees is fixed by declaration, never by scheduling.
3. **Slow steps are guarded by a check, not by a lag rule.** `graph.slow_on_critical_path` flags a step with a high p90 runtime that the email needs; the fix is to declare its write lagged.
4. **Declarations are verified at run time.** The runner traces every step's SQLite reads and writes against its declaration (`output/graph_shadow/*_undeclared.json`). The derived order went live without the planned 3-day shadow wait, at Amit's request.

## Why
The ADR 0052 rule "a weekly writer feeding a daily reader is lagged" was tested on 2026-09-27 and rejected. On Sundays the weekly `fetch_macro_gov` runs BEFORE its daily readers, which should see its fresh data. Treating that edge as cadence-lagged flipped those reads to last week's data. It also created cycles with blocking edges.

The 2026-09-27 incident was about cost, not cadence: a 14-minute weekly fetch sat on the email's path.

`lagged_from_order` seeded the declarations from the hand order. That makes the derived order provably preserve every read's version (tests/test_graph.py, checked on every weekday, month starts and Sundays).

## Consequences
- Per-writer lag (`stocks@classify_micro_tier`) is verbose on `stocks`, which has four writers. Splitting `stocks` into per-producer state would remove it.
- A new step that reads another step's table must choose blocking or lagged explicitly; the default is blocking.
- One undeclared read (`refresh_eligibility` → `forecast_history`) was caught by the runtime check during the offline gate run and fixed before deploy.
