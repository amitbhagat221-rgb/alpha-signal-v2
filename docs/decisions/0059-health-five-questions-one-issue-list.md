# ADR 0059 — Health is five questions and one issue list

**Status:** accepted 2026-10-02 · **Builds on:** ADR 0052 (the Check block), ADR 0019 / 0023 (sensor → surface → alert, Health Center) · **Supersedes:** nothing (it narrows how 0023 and 0033 are *shown*)

**Decision.** Every check answers exactly one of five questions (`checks.THEMES`): did everything run · did the
data arrive · is the data right · can today's picks be trusted · is the model still sound. Every check declares,
next to its rule, what it found (`message`), why it matters (`why`) and what to do first (`fix`).
`checks/report.py` turns the gathered state into **one** issue list, a five-row scorecard and a catalog of every
check. The terminal block, the email, the push, the MCP and the ops Health page render that state; none derives
its own. Three severities, defined once (`checks.SEVERITY_MEANING`): CRITICAL = act today, WARN = look this week,
INFO = known and tolerated.

## Why
- Amit, 2026-10-02: the checks are "overwhelming, complex and confusing", the UHS score is confusing, and it is
  not clear what is being checked.
- The ops page rebuilt the issue list itself, with different severities from the email (every step failure was
  CRITICAL there), and its dossier check read a field that did not exist, so it could never fire.
- The report read every FAILED row of the day, so a step that failed at 03:38 and succeeded on the 05:26 re-run
  still paged. On 2026-10-02 that was 2 of 3 CRITICALs and 8 of 12 WARNs: false alarms.
- One fact alarmed several times: the failed step, the watchdog's failed heal of its table, and the stale table.
- Six vocabularies were on one page: CRITICAL/WARN/INFO, A–F pillar grades, a 0–100 table score, UHS with
  TRUSTED/PRELIMINARY/REVIEW/AVOID, integrity PASS/WARN/FAIL, gate pass rates.

## What changed
- `checks.THEMES`, `checks.SEVERITY_MEANING`; `theme` / `why` / `fix` on every `checks/custom.py` check and on
  the derived range and coverage checks; `checks/system.SYSTEM_CHECKS` for the system families (steps, tables,
  feeds, watchdog, dossiers, integrity, trust, factors). `tests/test_checks.py` enforces all of it.
- `checks/report.gather()` builds the state from `checks/system.AREAS` (a `(facts, verdicts)` pair per area);
  `tools/health_report.py` only renders and sends. Each area that crashes
  becomes a `HEALTH_CHECK_CRASHED` issue.
- A step's **final** state counts (`views.pipeline_status`); a run that died mid-step (ABORTED) is a failure.
- `report.fold`: a failing step absorbs its own stale table and the watchdog heal that failed with it.
- Checks that were page-only now reach the email: per-pick integrity, cockpit endpoint audits. The system
  trust-score alert, which lived in the push text and could never fire alone, is an ordinary issue.
- New checks on the checks: `CHECK_VACUOUS` (a data check that passed on zero rows) and `TRUST_GATE_DORMANT`
  (a trust gate with no verdict in 7 days).
- `python -m tools.health_report --catalog` and the ops tab "What we check" list every check from the registries.
- The trust score ("UHS") has one wording, `scoring/health_score.describe`, and one set of bands,
  `config.TRUST_BANDS`. The stored score, labels and the pick gate are unchanged.

## Consequences
- A new check without `theme` / `why` / `fix`, or a new verdict code missing from `SYSTEM_CHECKS`, fails the
  tests. That is the point.
- Issue `code` no longer carries a `SANITY:` prefix or a `:target` suffix; `id` is the unique key and `target`
  is its own field. Org desk briefs read `code`, `message`, `detail` and keep working.
- The pillar tiles (A–F grades), the page's own issue builder and `_system_uhs_alert` are deleted.
- Not decided here: what the trust score should *be*. Its numbers barely vary across picks and four of its seven
  gates are silent (the new check reports that). Replacing it is a separate decision for Amit.

## Alternatives considered
- A side table mapping codes to themes: rejected, a second place to forget. The meaning sits on the check.
- One composite health score: rejected. A number hides which question failed; that was the complaint about UHS.
