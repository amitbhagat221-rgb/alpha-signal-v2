# 0007 — Fresh rebuild as v2 (don't refactor v1)
**2026-04-09 · Accepted**

**Decision.** Build v2 in a fresh folder (`~/alpha-signal-v2/`). Reuse v1's logic, formulas, and harvested data; rebuild structure from scratch. v1 stays running on cron during parallel validation, then v2 takes the cron slot when validated.

**Why.** v1's problems were architectural, not isolated bugs:
- 3 conflicting "universe" files (501/501/2,500); 80+ scattered CSVs
- 11 MB duplicates in `insider_archive.csv` (no UNIQUE constraint)
- `run_pipeline.sh` continues past a failed step; zero tests
- Hardcoded thresholds in 20+ scripts; backups next to live code

Fixing in place would risk breaking the live pipeline that emails daily, and wouldn't address the structural issues.

**Cutover criteria (Phase 9).** v2's `daily_picks` overlap with v1's top 15 by ≥70%; signal values match within ±5% (or differences explained); 3 consecutive green pipeline runs; v1 archived before its cron stops. **Met 2026-05-01.**

**Trade-offs.** Two systems to track during transition (manageable). More upfront work than patching — accepted in exchange for ownership.

**Sub-decisions.** [0001](0001-sqlite-over-csv.md) SQLite · [0002](0002-no-prefect.md) no Prefect · [0003](0003-bhavcopy-over-yfinance.md) bhavcopy · [0004](0004-no-base-classes-no-yaml.md) no YAML · [0005](0005-tier-aware-scoring.md) tier-aware scoring
