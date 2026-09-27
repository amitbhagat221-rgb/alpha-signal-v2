# Architecture

> **Status:** the "Target" part of this doc is **PROPOSED** ([ADR 0052](../decisions/0052-seven-building-blocks.md) and [plan 0015](../plans/0015-first-principles-architecture.md)). It is not built yet. As each migration phase ships, the matching part of "Today" is deleted. Until then, "Today" describes the running code.

## Target: one page

**What the system is.** Every trading morning it turns public Indian-market data into a point-in-time-honest, tier-ranked list of picks with an explanation, and it carries the evidence that both the picks and the data can be trusted. Mechanically it is **one as-of dataflow graph**: nodes read datasets and write datasets, and features are pure functions of the data knowable at `t`. Live is that graph evaluated at `t = today`.

### Seven building blocks
| Block | Definition | Owns | Derived from it |
|---|---|---|---|
| **Host** | An external dependency: NSE, BSE, Tickertape, Screener, yfinance, Moneycontrol, Anthropic… | min gap, shared lock, time budget or token/$ budget, user agent, identity check | pacing for every call; budget stops; "who hits NSE"; LLM spend view |
| **Dataset** | A table. Its **kind** is one of `event` (append-only facts), `series` (entity × date [× source]), `state` (entity → current value), `feature` (derived per sid × date), `log`. It optionally has an availability lag (for example 60 days after quarter-end). | columns and PK (in schema.sql); kind (inferred from PK); overrides (stale tolerance, quarantine, coverage, mirror) | write mode (event → insert-or-ignore; series/state/feature → column upsert; log → append); `asof(dataset, t)`; staleness from the producer's cadence; quarantine mirror DDL |
| **Node** | A module-level `NODE = {reads, writes, cadence, hosts, slot}` declared beside `fn(ctx)` | what it touches and when it runs | run order (topological); critical path to the email; lineage; the /flow graph; the producer used for freshness and heal; which failures block what |
| **Feature** | A pure `fn(frames_asof, t) → frame[sid, cols]` plus a `factors.FACTORS` entry: range, eligibility, family, bench, **weights** | the math and its metadata | live scores, the PIT panel, the replay, PIT columns, validation, the eligibility table, the evidence roster, the weight table |
| **Model** | segment → rank within segment → weighted blend → gates → select → size | `config.TIERS` (rule, pickable), gates, portfolio params | daily picks, the sized book, replay at any `t` |
| **Check** | A predicate attached to a dataset, a node or a feature: fresh, non-empty, in range, covered, identity, cross-source, no numbers in narrative | the one runner and the one verdict table | node success or failure; the health email, push, watchdog heals and the ops Health page are all **views** over verdicts |
| **View** | A named read-model: `picks(date, gated)`, `stock(sid)`, `features(sid, t)`, `pipeline_status()`, `health()` | the SQL that surfaces use | cockpit pages, ops pages, email, dossier context; nav comes from `PAGES` |

### Five invariants, each held by the runner or a test
1. **As-of.** Features and Models see data only through `asof(dataset, t)`. `signals/` cannot import `db`. Live, PIT, replay and backtest run the same code at different `t`.
2. **Segment.** Ranking happens only inside `config.TIERS` segments, and tiers with `pickable: False` never reach picks.
3. **Kind decides write, cadence decides freshness.** No writer chooses an INSERT mode. Episodic data (analyst PTs) is a `series` at its natural cadence, and the runner rejects off-cadence rows.
4. **A node succeeds only when its post-checks pass.** Declared outputs must be fresh as of the expected date and in range. LLM narrative columns must contain no numbers. Zero rows on a stale output is a failure, and zero rows on a fresh output is a no-op.
5. **Politeness.** Every external call goes through one door per Host, with a lock, a gap and a budget. Declared `reads` must cover the reads SQLite observes (test via `set_authorizer`).

### Diagram
```
 Host ─┐                                  AsOf: asof(dataset, t) ── every Feature/Model input
       ▼
  Node(fetch) ─writes→ Dataset(event|series|state) ─asof→ Feature ─writes→ Dataset(feature: panel)
                                                                 │
                         Model: segment → rank → blend → gate → select → size ─→ picks / book
                                                                 │
                             View(read-models) ─→ cockpit · ops · email · dossier(LLM Host)
 Check: attached to every Dataset/Node/Feature edge ──→ verdicts ──→ health email · push · watchdog · ops page
 Order = topological sort of blocking edges; lagged edges (coarser cadence or slow writer) run after the email
```

### Directory layout (one top-level home per block)
```
hosts.py      Host        HOSTS = {name: {gap, lock, budget, ua, identity}}
schema.sql    Dataset     columns + PK (owner of columns)
datasets.py   Dataset     kind inference + overrides (was tables.py)
db.py         Dataset     connection, write(dataset, df), asof(dataset, t)
graph.py      Node        collects NODE/FACTORS → order, critical path, lineage, producers
pipeline.py   Node        runner: slot/cadence gate, host door, post-checks, pipeline_log, --asof
sources/      Node        nodes that touch a Host (fetch)
signals/      Feature     pure feature functions (no db import)
factors.py    Feature     FACTORS registry (metadata + weights)
scoring/      Model       segment, rank, gate, select; portfolio sizing
config.py     Model       TIERS + model parameters only
checks/       Check       runner + the custom semantic checks (ex health/data_sanity/validators)
views.py      View        read-models
cockpit/ cockpit_ops/ output/   surfaces (pages, email, dossier); PAGES list per app
tools/        research only: nothing in the graph imports tools/
```

### Where the truth lives (exactly one owner per concept)
| Concept | Owner |
|---|---|
| Columns, PK | `schema.sql` |
| Table semantics (write mode, time column, staleness) | Dataset kind (inferred) plus `datasets.py` overrides |
| What a step reads, writes, and when it runs | that step's `NODE` dict |
| Run order, critical path, lineage, /flow | derived by `graph.py`, never written |
| Politeness and budgets | `hosts.HOSTS` |
| Factor math | its `signals/` function |
| Factor metadata and weights | its `factors.FACTORS` entry |
| Tiers | `config.TIERS` |
| Expectations and health | Check verdicts (derived plus `checks/` custom) |
| What a page or email shows | a `views.py` read-model |
| Schedule | crontab has one line per slot, and every line calls `run.sh <slot>` |

## Today (until plan 0015 lands)

```
                        ORCHESTRATION
   pipeline.py runs config.PIPELINE_STEPS in list order (85 steps)
   each step: {name, module, function, critical, table, source, data_freq, frequency}
   frequency gate: daily · weekly (Sunday) · monthly (1st); --step overrides
   critical=True (fetch_bhavcopy, quality_gate, screener) aborts the run
   every step → one pipeline_log row; 11 crontab lines run jobs outside the list

 SOURCES  ────────→  SIGNALS  ────────→  SCORING  ────────→  OUTPUT
 sources/*           signals/*           scoring/*           output/*
 external → DB       DB → *_scores       quality_gate,       snapshot → dossier
                     (+ inline factors   regime, screener    (Claude API) → email
                      in screener)       → daily_picks
      PIT twin: tools/reconstruct_pit.py → daily_snapshots_pit (not scheduled)
                              ↓
               SQLite data/alpha_signal.db (WAL) + DuckDB read replica (ADR 0031)
                              ↓
            TRUST & OBSERVABILITY: eligibility/ · validators/ · tools/data_sanity
            · health.py · tools/health_report · tools/freshness_watchdog · lineage.py
                              ↓
            cockpit/ (:3000) · cockpit_ops/ (:3001 Health Center, /flow, /sql)
```

| Fact | Source of truth today |
|---|---|
| Steps, order, cadence | `config.PIPELINE_STEPS` (hand-ordered; heavy steps kept after `email` by position) |
| Tables | `schema.sql` + `tables.TABLES` (`tests/test_tables.py`) |
| Factor registry | `factors.FACTORS` (+ `PIT_PRODUCERS`); db re-exports the derived views |
| Production weights | `config.SIGNAL_WEIGHTS` → [signal-weights.md](signal-weights.md) |
| Tiers | `stocks.cap_tier`, `config.TIERS`, `config.EXCLUDED_FROM_PICKS`, `tools/classify_micro_tier.py` |
| Eligibility | `factors` eligibility → `tools/refresh_eligibility` → `universe_eligibility` |
| Factor lineage | `lineage.FACTOR_LINEAGE` (hand-kept, same keys as FACTORS) |
| Freshness-watched files | `config.FILE_OUTPUTS` |
| Cron | `crontab -l` (table in [OPERATOR.md](../../OPERATOR.md)) |

Tier-aware scoring:
- LARGE is the top 100, MID is 101–250, SMALL is the rest.
- MICRO is carved out of SMALL and never picked (ADR 0026).
- Signals are percentile-ranked within each tier, weighted per tier, and re-ranked within the tier (ADR 0005).
- The pick gate is `eligible_coverage` plus the weight-coverage and price-row floors (ADR 0021 → 0024).
- Financials use the generic weights (ADR 0048).
- The advisory book is HRP with banded rebalancing (ADRs 0044/0046).
