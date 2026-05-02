# Architecture Decision Records (ADRs)

One file per immutable decision. Each ADR captures **what we decided, why, and what we considered**, at the moment we decided it. The reasons drift over time — that's fine. The record stays.

## Format

```
NNNN-short-kebab-case-title.md
```

Numbers are sequential (0001, 0002, 0003...). Never renumber.

Each ADR follows this template:

```markdown
# NNNN — Title

**Status:** Accepted | Superseded by ADR-XXXX | Deprecated
**Date:** YYYY-MM-DD
**Decided by:** Amit (with Claude Code)

## Context
What's the problem we're solving? What constraints exist?

## Decision
What did we pick?

## Alternatives considered
What else did we look at? Why did we reject them?

## Consequences
What does this make easy? What does this make hard? What might bite us later?

## References
Links to discussions, specs, related ADRs.
```

## Rules

1. **Write-once.** Once an ADR is committed, do not edit the body. If a decision changes, write a new ADR that supersedes the old one.
2. **One decision per file.** If you find yourself writing about two things, split them.
3. **Keep them short.** A good ADR fits on one screen. If it's longer, you're probably justifying after the fact.
4. **Capture the "why we rejected X" too.** Future-you will ask "why didn't we just use Prefect?" — answer it now.

## Index

| # | Title | Status | Summary |
|---|-------|--------|---------|
| 0001 | [SQLite over CSV files](0001-sqlite-over-csv.md) | Accepted | Single DB instead of 80+ scattered CSV files |
| 0002 | [No Prefect, plain Python](0002-no-prefect.md) | Accepted | `pipeline.py` orchestrator + SQLite log table |
| 0003 | [Bhavcopy over yfinance](0003-bhavcopy-over-yfinance.md) | Accepted | NSE official close prices + delivery % |
| 0004 | [No base classes, no YAML](0004-no-base-classes-no-yaml.md) | Accepted | Plain functions, Python config dict |
| 0005 | [Tier-aware scoring](0005-tier-aware-scoring.md) | Accepted | Within-segment ranking, never universe-wide |
