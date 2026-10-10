# ADR 0070 — Shadow, optional and not-yet-live jobs never page

**Status:** accepted 2026-10-10. Extends ADR 0059 / 0060 (one health state; every check can fail). Severity is still decided only in the checks.

## Decision
1. **Shadow pipeline steps are capped at WARN, even on a streak.** `config.NON_PAGING_STEPS` maps each step name to a plain-words reason. `checks.pipeline_verdicts` applies the cap. A drill fails if a listed name is not a real step or `run.sh` job.
   - Steps that are not on today's picks or email path: the plan 0017 v3 `datamodel_sync` / `datamodel_reconcile`, and the REIT price fallback.
2. **An empty table's severity follows the status of the feed that writes it** (`checks.empty_table_severity`):
   - candidate or wanted feed → INFO;
   - probation feed → WARN;
   - production writer → CRITICAL.
   A file output marked `optional` in `config.FILE_OUTPUTS` is WARN.
3. **A volume spike during a declared backfill is INFO.** `run.sh backfill` writes `output/backfill_active`, and `checks.feeds.backfill_active()` honours it for 26 hours. A drop is never excused.

## Why
On 2026-10-10 all four CRITICALs failed the page's own definition ("today's picks or the morning email are affected"). They were two v3 shadow jobs, a Kite feed not yet live, and 29 zero-volume REIT rows. Pages that cry wolf get ignored. Health went from 5 CRITICAL / 9 WARN to 0 CRITICAL.

## Consequences
A new shadow job or candidate feed is declared once, in config or the feeds registry, never by name inside a check. Re-grading back to paging is a one-line removal from `NON_PAGING_STEPS` or a feed status change.
