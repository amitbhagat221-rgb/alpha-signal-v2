# 0004 — No base classes, no YAML config

**Status:** Accepted
**Date:** 2026-04-09 (revised from earlier proposal)
**Decided by:** Amit (with Claude Code)

## Context

Earlier v2 planning proposed:
- A `BaseSource` abstract class with `fetch()`, `validate()`, `save()` — every data source subclasses it
- A `BaseSignal` abstract class with similar shape
- YAML files (`sources.yaml`, `signals.yaml`, `pipeline.yaml`) as the config layer

The argument was "data sources are pluggable — swap one in via a YAML line." After deeper review we reversed this. The abstraction was solving a problem we don't actually have, and adding indirection that hurts readability.

## Decision

- **No base classes.** Each source / signal is a plain Python module with a clear function (e.g. `fetch_bhavcopy(date)`, `compute_piotroski(snapshot_date)`). They share a *convention*, not an inheritance hierarchy.
- **No YAML.** All config lives in `config.py` as plain Python dicts and constants. Importable, type-checkable, refactor-able.
- **The only "extra tool" is Jupytext** for notebooks. The user wants to see data at each step.

## Alternatives considered

- **BaseSource + YAML registry.** The original plan. Rejected: abstraction without justification. We have ~10 sources, each with idiosyncratic fetch logic. Trying to force them into a common interface produced more accidental complexity than the abstraction saved.
- **Pydantic models for config.** Type validation is nice but at our scale, a Python dict + a couple of asserts in `validate.py` is enough.
- **Hydra / OmegaConf.** Layered configs with overrides. Useful for ML experiments. Overkill for a single-environment pipeline.

## Consequences

**Easier:**
- New source = new file in `sources/`, new entry in `config.PIPELINE_STEPS`. No registry, no metaclass, no plugin protocol.
- Refactoring is `Find/Replace` — no YAML-to-Python coordination needed.
- A reader new to the project can read `pipeline.py` top-to-bottom and understand everything.
- Python config means IDE goto-definition works on every constant.

**Harder:**
- No "swap a source by changing one YAML line." But this turned out to be a hypothetical we never needed — sources differ enough that swapping is always non-trivial regardless.
- Slight risk of inconsistency across sources (one fetcher returns DataFrame, another returns dict). Mitigation: code review on the convention, not enforcement via class hierarchy.

**Will bite us if:**
- We ever genuinely have multiple interchangeable implementations of the same source (e.g. "fetch prices from any of NSE, BSE, broker API"). Then revisit. We don't have this today.

## References

- Config: `config.py`
- Pipeline orchestrator: `pipeline.py`
- Source examples: `sources/nse_insider.py`, `sources/macro_yfinance.py`
- Memory note: [project_prefect_decisions.md](https://github.com/) — captures the reversal
