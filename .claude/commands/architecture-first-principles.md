# First-principles architecture for alpha-signal-v2

## Mission
Design the target architecture of alpha-signal-v2 from first principles, then migrate to it step by step.
Do NOT start from the current code. Start from what the system fundamentally IS, derive the smallest set of building blocks that can express it, and only then map the existing repo onto that design.
The goal is an architecture where, once the building blocks are understood, the rest of the repo is obvious. Every concept has exactly one home, and most of what is hand-maintained today becomes derived.
Think nCr: find the generating rule, not the list of cases.

## Winning criteria
1. **Change locality (headline).** Each change below touches ≤2 places: its definition plus, optionally, a test.
   - add a data source
   - add a table
   - add a factor (live + backtest + weight)
   - add a pipeline step
   - add a quality check
   - add a cockpit page
   - change a cadence or threshold
   - rename a factor or column
   - add a tier
   - replay any past date
2. **Conceptual compression.** The whole system is explained by ≤7 building blocks and ≤5 invariants, written on one page. Anything that doesn't fit one of them has to justify its existence.
3. **Substantial reduction:** net live LOC and the number of files a newcomer must read.
4. **Invariants guaranteed by construction, not by vigilance.** A rule that CLAUDE.md has to warn about is a design failure. Make the violation impossible, or caught by a test.
5. **Zero unintended behaviour change**, proven by equivalence gates.

## Step 1: what is this system? (write this before reading any code)
From README.md, CLAUDE.md and docs/reference/architecture.md only:
- **Purpose, in one sentence.**
- **Essential capabilities:** ingest external data, derive features, score and rank, construct a portfolio, explain it (dossier), surface it (cockpit/email), prove it works (backtest/evidence), and prove the data is trustworthy (health).
- **Invariants.** Candidates to confirm, merge or reject:
  - Time/as-of: nothing may use information not available at t.
  - Rank within tier, never across tiers.
  - Episodic data (analyst PTs) is snapshotted at its natural cadence, never daily.
  - A producer with 0 output is a failure, never a success.
  - LLM narrative contains no numbers.
  - No two harvesters at once, and ≥2s per host.
- **Change scenarios,** from the change-locality list above.

## Step 2: derive the building blocks
Find the minimal vocabulary. Test at least these hypotheses; accept or reject each with reasons.
- **H1 — Live is the backtest at t = today.**
  - Every transformation should be a pure function `f(inputs as-of t) → output`.
  - If so, live signals, PIT reconstruction, pit_replay and backtests are ONE code path evaluated at different t.
  - Today they are three: signals/, tools/reconstruct_pit.py and tools/pit_replay.py.
- **H2 — The pipeline is a dataflow graph, not a list.**
  - Each node declares its inputs (tables), outputs (tables), cadence and cost class.
  - From that declaration, derive:
    - the run order (topological sort; today it's 85 hand-ordered dicts in config.PIPELINE_STEPS)
    - the critical path to the email
    - lineage (today lineage.py is ~1.2K lines of hand-kept metadata)
    - freshness expectations (from cadence)
    - rerun and heal targets
    - the /flow page
    - which failures block what
- **H3 — A table's kind fixes its semantics.**
  - There are only a few kinds: append-only events, snapshots keyed by date, current state, and derived features.
  - The kind should determine:
    - write mode (the INSERT OR IGNORE vs REPLACE rule)
    - the time column and as-of filter
    - staleness
    - quarantine
  - Today these are separate registries and CLAUDE.md rules.
- **H4 — Quality is a property of graph edges.**
  - Freshness, raise-on-zero, validation ranges, cross-source checks and trust gates attach to nodes and edges declaratively.
  - One runner enforces them; no module re-implements a guard.
  - health.py, tools/health_report.py, tools/data_sanity.py, validators/ and the freshness watchdog would become views over one quality model.
- **H5 — Presentation reads from named read-models.**
  - The cockpit, email and dossier consume a small set of queries/views owned in one place, not ad-hoc SQL spread across 3K-line api files.
- **H6 — Evidence is a function of the graph.**
  - Backtests, the promotion gate and multiple-testing run over any feature node's output across t.
  - The factor registry is the feature-node subset of the graph, not a separate universe.

Output: the final list of building blocks (e.g. Source, Dataset, Node, Feature, Model, Surface, Check, AsOf), each with a one-paragraph definition, what it owns, and what is derived from it.

## Step 3: map the current repo onto the model (read-only)
- For every package, registry and major file, say:
  - which building block it is
  - which part of it is essential
  - which part is accidental: hand-maintained, duplicated, or a workaround
- List every place where the same fact is stated twice. Name the building block that should own it.
- Build the change-locality table for today, counting real files and edit sites for each scenario.

**Build on the 2026-09-26 cleanup; don't redo it.** Read `git log --oneline 8700769^..HEAD` and HANDOFF.md first. These already exist and are proven by equivalence tests, so the target design must absorb or extend them. Replace one only if the building blocks demand it, and say why.
- `factors.FACTORS`: the factor registry; derived lists are enforced by `tests/test_factor_registry.py`.
- `tables.TABLES`: the table registry with one freshness engine (`tests/test_tables.py`).
- `sources/_http.py`: `polite_get`, `run_harvester` (raise-on-zero), `sid_map`.
- `validators/_verdicts.py`: one trust-verdict writer.
- `cockpit/_shared.py`, `formatting.py`, `db.rows/one/scalar`, `output/_llm.py`.
- Shared live/PIT compute functions, e.g. `signals/delivery_anomaly.py` and `signals/_annual.py`.

Current state (from the 2026-09-26 cleanup; verify it):
- `factors.FACTORS` and `tables.TABLES` are registries, but separate ones.
- config.PIPELINE_STEPS is a hand-ordered list of 85 steps; `pipeline.py` runs them serially.
- `reconstruct_pit.py` (~2K lines) still orchestrates PIT separately from live.
- `cockpit/api.py` and `cockpit_ops/api.py` are ~2.5–3K lines each.
- `lineage.py` holds hand-kept metadata.
- There are 135 tables and ~65 signal modules.
- `run_*.sh` and 7 cron lines share one preamble.

## Step 4: design the target architecture
- **One-page architecture:**
  - the building blocks and invariants
  - a diagram (source → dataset → node → feature → model → surface, with AsOf and Check as cross-cutting concerns)
  - the directory layout, where each top-level folder maps to one building block
  - "where the truth lives": exactly one owner per concept
- **For each change scenario, the after-state:** the exact edit a developer makes, as a ≤10-line example (e.g. a new factor is one dict entry plus one pure function).
- **What becomes derived:** list every hand-maintained artifact that disappears, and its LOC.
- **Constraints:**
  - ADR 0004 (plain functions and dicts; no base classes, frameworks, YAML or DSLs) stays the default.
  - If first principles argue for breaking it, say so explicitly with the trade-off; don't just do it.
  - SQLite stays. No new infrastructure unless its benefit is overwhelming and stated.
- **Stress-test the design:** show how it handles the hard cases before claiming it is simpler:
  - PT data cadence (episodic snapshots)
  - Financials eligibility (ADR 0048)
  - quarantine
  - MICRO tier exclusion
  - LLM steps with budgets
  - rate-limited scrapers with time budgets (moneycontrol)
  - monthly/weekly cadence
  - the critical-path ordering incident (a slow weekly step before the screener delayed the email)
- **Write it as a new ADR** (decision in the first 10 lines, ≤60 lines) plus docs/reference/architecture.md.

## Step 5: STOP and present
Present all of the following to Amit, then wait for approval:
- the building blocks
- the invariants
- the hypothesis verdicts
- the before/after change-locality table
- the projected reduction
- the migration plan
- the top risks

Do not write production code before he approves.

## Step 6: migrate incrementally (strangler pattern; only after approval)
- Order phases by leverage. Likely first: the dataflow graph, which derives order, lineage and freshness. Then live = PIT. Then quality-as-declaration, then read-models.
- Each phase is independently shippable. It is built in an isolated git worktree and moves consumers over one at a time. Old and new run side by side only behind an equivalence test, and the old path is deleted in the same phase.
- **Equivalence gates for every phase:**
  - Tests pass, `pipeline.py --dry-run` works, and every module in every package imports.
  - PIT: `reconstruct_one_date` on 3 monthly dates gives identical columns (rtol 1e-12, same NaN positions).
  - Live: today's screener ranks per tier are identical.
  - Cockpit: both apps on test ports 3100/3101 with `COCKPIT_CACHE_DIR` in the scratchpad; all routes return 200 and the HTML matches after normalisation.
  - Email HTML is byte-identical, and health/sanity output is identical.
  - Step order and critical-path runtime to the email are no worse.
- List intentional behaviour changes separately, with measured impact.

## Safety (learned the hard way)
- Production runs from /home/ubuntu/alpha-signal-v2 on the 03:30 UTC cron. Never edit, merge, deploy there, or restart services without Amit's explicit OK.
- Verify each worktree's base with `git merge-base --is-ancestor <master> HEAD`; worktrees have been created from stale commits.
- The DB is live (8.6 GB) and READ-ONLY. Test writes on temp copies. No network, except 3-item smokes under `flock -n /tmp/alpha_signal_harvest.lock` with ≥2s per host.
- Before editing anything, check for other live sessions (`git status`, ListAgents). Never stage anyone else's uncommitted files.
- "Unused" ≠ dead. Check crontab, run_*.sh, PIPELINE_STEPS dynamic imports, .claude/, templates/JS, commands in docs, and whether it is the ONLY writer of a live table.
- Runtime and step order are behaviour. State the critical-path effect of every cadence, rate-limit or ordering change.
- Agent audit claims were wrong ~10% of the time; verify every claim in code.
- Run ≤4 subagents at once (5 hit the usage limit). Each has an explicit file-ownership list and commits often.
- CLAUDE.md rules bind: no `git add .` / `-A`, no `--amend`, never `pkill -f "uvicorn cockpit.app"`. Add a checklist bullet before starting.

## Done means
Someone reading only README.md and the one-page architecture can predict where any concept lives, and can add a source, factor, check or page by editing one or two places.
