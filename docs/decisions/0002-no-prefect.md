# 0002 — No Prefect, plain Python orchestrator

**Status:** Accepted
**Date:** 2026-04-09 (revised from earlier proposal)
**Decided by:** Amit (with Claude Code)

## Context

Earlier in v2 planning we proposed using **Prefect Cloud** for orchestration: a hosted UI, retries, scheduled flows, task-level visibility. After deeper review, we reversed that decision in favor of plain Python.

The problem with Prefect for this project: it's a framework that owns the execution model. Adding it means learning its mental model, debugging through its abstractions, dealing with its update cadence, and accepting whatever the UI gives us. For a single-VM, single-user project running 20 sequential tasks once a day, the framework cost exceeds the framework value.

## Decision

We use a hand-rolled `pipeline.py` (~100 lines) that:

- Reads pipeline steps from `config.PIPELINE_STEPS` (a Python dict)
- Runs each step as a subprocess
- Logs each step's start, end, status, duration, and error to the `pipeline_log` SQLite table
- Supports `--dry-run`, `--step <name>`, `--status` flags
- Is invoked from system cron at 3:30 AM IST

Visibility comes from `pipeline_log` queries (SQL is the UI) plus the `health.py` cockpit notebook for ad-hoc inspection.

## Alternatives considered

- **Prefect Cloud (free tier).** The original proposal. Rejected: too much framework for too little benefit. We don't need DAG visualization, distributed execution, or a hosted dashboard. We need "did the pipeline run? did any step fail?" — which is `SELECT * FROM pipeline_log WHERE status='FAILED' ORDER BY started_at DESC LIMIT 5`.
- **Airflow / Dagster.** Same logic, more infrastructure. Both require running a server.
- **GNU make.** Could express the dependency graph cleanly. Rejected: less ergonomic for Python data transformation, no built-in logging, no good way to surface "what failed last night" to the user.

## Consequences

**Easier:**
- Zero dependencies beyond Python itself
- Pipeline failures inspectable with `SELECT * FROM pipeline_log`
- New steps added by appending to a Python dict — no DSL, no decorators, no annotations
- Fully understood by the user (no "framework magic")

**Harder:**
- No built-in retries (but: most failures are deterministic — retry won't help, fixing the source will)
- No DAG visualization (but: 20 sequential steps don't need one)
- No hosted UI (but: SQL on `pipeline_log` is faster than clicking through a UI for what we need)

**Will bite us if:**
- The pipeline grows past ~50 steps with complex dependencies — at that point reconsider Dagster
- We ever want to run distributed tasks across machines (we don't)

## References

- Orchestrator: `pipeline.py`
- Step definitions: `config.PIPELINE_STEPS`
- Original Prefect proposal: [../_archive/2026-04-09-prefect-sqlite-architecture.md](../_archive/2026-04-09-prefect-sqlite-architecture.md)
