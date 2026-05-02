# 0007 — Fresh rebuild as v2 (don't refactor v1)

**Status:** Accepted
**Date:** 2026-04-09
**Decided by:** Amit (with Claude Code)

## Context

After auditing v1 we identified systemic issues that weren't isolated bugs but architectural problems:

- Three different "universe" files used by different scripts (501 vs 501 vs 2,500)
- 80+ scattered CSV files, no schema enforcement
- 11 MB of duplicate rows in `insider_archive.csv` (no UNIQUE constraint)
- Zero tests
- `run_pipeline.sh` runs 20 scripts sequentially with no error handling — script 6 fails, 7-20 still run on stale data
- Hardcoded thresholds in 20+ scripts
- Backups (`.bak`) sitting next to live code
- The next bug wouldn't be in any single script — it would be in the assumptions between scripts

The user articulated the deeper issue: "Misses are inevitable without systematic guardrails. I want to OWN the system, not just use it."

We considered fixing v1 in place. The problems were too entangled — every fix would risk breaking the live pipeline that's emailing the user every day.

## Decision

Build v2 in a fresh folder (`~/alpha-signal-v2/`). Reuse v1's logic, signal formulas, and harvested data, but rebuild the structure from scratch on:

- One SQLite database (not 80 CSVs) — see [0001-sqlite-over-csv.md](0001-sqlite-over-csv.md)
- Plain Python orchestration with logging — see [0002-no-prefect.md](0002-no-prefect.md)
- NSE bhavcopy as primary price source — see [0003-bhavcopy-over-yfinance.md](0003-bhavcopy-over-yfinance.md)
- No frameworks, no YAML — see [0004-no-base-classes-no-yaml.md](0004-no-base-classes-no-yaml.md)
- Tier-aware scoring as a hard rule — see [0005-tier-aware-scoring.md](0005-tier-aware-scoring.md)

v1 stays running on cron unchanged. v2 is built and validated alongside it. When v2 is fully tested and matches v1's output within tolerance, cron switches over and v1 is archived (not deleted).

The user explicitly committed to slow, methodical, one-piece-at-a-time work: "I'll pay deep attention so that I am not caught off guard."

## Alternatives considered

- **Refactor v1 in place.** Too risky — every fix could break the live pipeline. Also doesn't address the structural problem (tests, contracts, single source of truth).
- **Half-rebuild — new database, keep scripts.** The scripts themselves encode the wrong assumptions (which universe to use, which CSV to read). Rebuilding cleanly is faster than auditing every script.
- **Stop building, just patch bugs as they arrive.** Misses the point — the user wants ownership, not just functionality.

## Consequences

**Easier:**
- v1 keeps emailing daily picks while v2 is built — no pressure, no blast radius
- v2 starts with consistent foundations from day 1
- All v1 lessons captured in docs/decisions/ and docs/_archive/ — nothing forgotten
- Clean structure makes the system inspectable: data_health() shows everything in one place

**Harder:**
- Two systems to track during the transition (manageable: v2 work isolated to its folder)
- Risk of v2 producing different picks than v1 — must validate during parallel run before cutover
- More upfront work than patching v1 — but the project's complexity already exceeded what patching could maintain

**Cutover criteria (Phase 9):**
- v2's `daily_picks` overlap with v1's `enriched_*.csv` top 15 by ≥ 70%
- All signal values match v1 within ±5% (or differences explained — e.g. bhavcopy vs yfinance closes)
- 3 consecutive days of green pipeline runs in v2
- Backup of v1 archived before stopping its cron

## References

- v1 audit findings: [../_archive/2026-04-09-v1-audit-notes.md](../_archive/2026-04-09-v1-audit-notes.md)
- System hardening plan that became v2: [../_archive/2026-04-09-system-hardening-plan.md](../_archive/2026-04-09-system-hardening-plan.md)
- v2 build plan (now superseded by execution): [../_archive/2026-04-09-v2-build-plan.md](../_archive/2026-04-09-v2-build-plan.md)
