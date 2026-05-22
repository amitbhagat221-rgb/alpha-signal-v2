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
| 0006 | [Classifier status tracking](0006-classifier-status-tracking.md) | Accepted | Regulatory classifier state lives in `regulatory_events.classifier_status` |
| 0007 | [Fresh rebuild for v2](0007-fresh-rebuild-v2.md) | Accepted | v2 is greenfield, not a v1 refactor |
| 0008 | [Cockpit as a write-side surface](0008-cockpit-write-surface.md) | Accepted | Cockpit can mutate state (rerun steps), with strict guardrails |
| 0009 | [Track 3 parallel to Track 2](0009-factor-track-parallel-to-d-track.md) | Accepted | Factor model (Track 3) runs concurrent with Portfolio (Track 2). Terminology per ADR 0015. |
| 0010 | [PIT-strict corporate-action adjustment](0010-pit-strict-corporate-action-adjustment.md) | Accepted | Splits/bonuses/dividends compose at signal-compute time, not at ingest |
| 0011 | [Long format for new fundamentals tables](0011-long-format-for-new-fundamentals-tables.md) | Accepted | Track 3 and onward use long-format; legacy wide tables stay wide |
| 0012 | [PIT archive refresh on signal fix](0012-pit-archive-refresh-on-signal-fix.md) | Accepted | Refresh v2 PIT archive when signal logic changes; v1 archive is frozen |
| 0013 | [Industry, not GICS sector, as drill unit](0013-industry-not-sector-as-drill-unit.md) | Accepted | 25-industry IIM-style taxonomy + market-cap-weighted composite |
| 0014 | [LLM-sourced competitive landscape](0014-llm-sourced-competitive-landscape.md) | Accepted | Sonnet+web-search generates industry share including private players |
| 0015 | [Track numbering and rename](0015-track-numbering-and-rename.md) | Accepted | Three tracks (Foundation/Portfolio/Factor model) + decimal phases + fork suffixes + ↔ parallels |
