# ADR 0090 — Org trim: the chief-of-staff and the AI scout are dropped, three seats run less often

**Status:** accepted 2026-11-01 (Amit: "agree with all the recommendation for the org change"). Amends ADR 0057 (the org) and plan 0019's roster.

## Decision
- **Dropped** (`enabled: False` in `org.ROLES`; the charters, kinds and code stay, so either can be switched back on from `/org`): **chief-of-staff** (its weekly board pack was a digest of the other memos; the Boardroom inbox is that digest) and **ai-scout** (eight memos, nothing adopted; its charter's default was "no change").
- **Demoted:** **risk-officer** daily → weekly (it comments on a paper book); **compliance** daily → weekly, grading the week's memos in one batch (`_build_grade` already picks up every ungraded memo of the last 8 days); **data-engineer** stays daily but its brief is built only when the health report carries an issue the last brief did not, or a CRITICAL (`org_kinds._triage_has_news`), because the health email already lists the same issues.
- **The Sunday nudge survives the pack:** when no board pack exists, `org.deliver_all` sends one push on Sundays with the inbox count and kinds, once per day (a `delivery` document keyed `inbox<date>`).
- Unchanged: cio, cto, dq-auditor, sector-desk, code-janitor, system-architect, and the builder roles.

## Why
- Four weeks of record (2026-10-02 → 2026-11-01): compliance used 2.64 M input tokens, 37 % of the org's total, to produce grades between 6.3 and 6.6 for every seat, which do not tell the seats apart; the data-engineer's 32 daily memos restated the health email's issues; the risk-officer's 32 daily notes concerned an advisory book; the chief-of-staff's 8 packs summarised memos the inbox already showed; the ai-scout's 8 memos recommended nothing that was adopted.
- The dq-auditor, whose calls are re-run against the database (40 of 40 right), and the cio, whose asks were the ones the CEO decided on (10 of 14), are the seats that earned their cost; the two new janitors are built on the auditor's pattern.

## Consequences
- 15 registry entries, 13 active; the daily spend roughly halves (compliance and the data-engineer were most of it).
- `tests/test_org_trim.py`: a disabled seat is never due, the triage is skipped when nothing is new, the inbox nudge fires once.
