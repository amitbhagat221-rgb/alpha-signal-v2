# Health checks

How the system answers "is it healthy?" ([ADR 0059](../decisions/0059-health-five-questions-one-issue-list.md)).
The list of checks is generated, not written here:

```bash
python -m tools.health_report             # the five answers + today's issues (same as the 04:00 UTC email)
python -m tools.health_report --catalog   # every check, by question, with what it means and its status now
python -m tools.data_sanity --check CODE  # run one data check and see its example row
```

The ops cockpit shows the same two views: `/system` → **Overview** and **What we check**.

## The five questions

Defined in `checks.THEMES`. Every check belongs to exactly one.

| Question | What it covers |
|---|---|
| Did everything run? | pipeline steps, cron jobs, the self-healing watchdog |
| Did the data arrive? | feeds, table freshness, how many stocks each source covers |
| Is the data right? | legal ranges, sources agreeing with each other, mis-mapped fields |
| Can today's picks be trusted? | the factor inputs behind today's ranking, the ranking itself, the AI write-ups, the cockpit |
| Is the model still sound? | wired factors losing their predictive edge |

Each question is **OK**, **WATCH** (something to look at) or **BROKEN** (something to act on today).

## The three severities

Defined in `checks.SEVERITY_MEANING`.

| Severity | Means | Where it shows |
|---|---|---|
| CRITICAL | Act today: today's picks or the morning email are affected | terminal, email, push, ops page |
| WARN | Look this week: something is degraded, the picks still stand | terminal, email, ops page |
| INFO | Known and tolerated: measured, no action needed | ops page only ("Known and tolerated") |

Which step or table is CRITICAL is derived, not listed: a step pages when the morning email needs its output
(`checks.critical_steps`), a table when such a step writes it (`checks.critical_tables`).

## What earns a place in the daily report

[ADR 0060](../decisions/0060-a-check-must-be-able-to-fail.md). A check stays only if all four hold:

1. It can fail **today because the world changed**: data arrived wrong, a factor input died, the ranking broke.
   A rule that can only break when code or a registry changes is a test, not a daily check.
2. It guards something the models read or the reader sees today.
3. It has a **fire drill** in `tests/test_check_drills.py` that breaks what it guards and proves the check notices.
4. It looks at rows. A check whose scope is empty is reported (`CHECK_VACUOUS`), never passed.

The catalog is capped at 30 checks (24 today). A new one replaces one or earns its place.

## Where a check lives

| Kind | Declared in | Example |
|---|---|---|
| Model check | `checks/custom.py` → `checks/model.py` | `FACTOR_INPUT`: a wired factor's input collapsed in today's ranking |
| Semantic data check | `checks/custom.py CHECKS` | an analyst price target that cannot be real |
| Column range / enum | `checks/ranges.py COLUMNS` | `banking_metrics.cost_of_funds_pct` in [0, 25] |
| Per-stock coverage | `tables.TABLES` → `coverage` | `quarterly_income` covers most of the universe |
| System check | `checks/system.py`: meaning in `SYSTEM_CHECKS`, a `(facts, verdicts)` pair in `AREAS` | a failed step, a stale table, a failed feed probe |

The model checks read what the screener actually used (`pit_replay_snapshots.inputs_json`, frozen every day after
the ranking) and take their scope from `factors.SIGNAL_WEIGHTS`. They compare today with the factor's own last
20 days, so there is no number to maintain per factor.

One issue per fact: a failing step absorbs its own stale table and the watchdog heal that failed with it
(`report.fold`). A step that failed and then succeeded on a re-run is a success.

## The code, one job per module

| Module | Job |
|---|---|
| `checks/__init__.py` | constants, the data-check runner `run(only=, theme=)`, alert criticality, the post-step check |
| `checks/ranges.py` · `custom.py` · `model.py` | the data checks: column ranges, semantic checks, checks on today's ranking |
| `checks/feeds.py` | per-feed state and verdicts (also the Data Supply page) |
| `checks/system.py` | system checks: `SYSTEM_CHECKS` (meaning) and `AREAS` = `{key: (facts, verdicts)}`; `facts()` reads the DB, `verdicts(facts)` is pure |
| `checks/report.py` | `gather()` → the one state; `issues`, `scorecard`, `catalog`, `records` (all pure) |
| `checks/history.py` | when each check last fired (`check_results`) |
| `tools/health_report.py` | renders the state (terminal, catalog, email, push) and sends it. Nothing else. |

Thresholds are named constants at the top of the module that uses them (`system.py`, `model.py`, `report.py`).

## Before the picks go out

The picks email runs `checks.run(theme="picks")` first (a dead factor input, a ranking that broke from yesterday's,
a thin tier). A failure puts a "Read before acting on today's picks" banner at the top of the email and a ⚠ in the
subject. The freeze of the day's inputs therefore runs before the email (`config.PIPELINE_STEPS`, order derived).

## How long has it been firing

Each CLI run of `tools.health_report` records the status of every check for the day (`check_results`, catalog
check `health`). From that:

- every issue shows **new**, **day N**, or **standing, day N** (a WARN firing 14+ days: fix it, accept it, or
  delete the check);
- the catalog shows when each check **last fired**.

## Adding a check

1. Ask the four questions above first. If the rule can only break when code changes, write a test.
2. Data check: append a dict to `checks/custom.py CHECKS` with its rule (`sql` or `fn`) and its meaning:
   `theme`, `message` (what it found), `why` (why it matters), `fix` (what to do first).
3. System check: its meaning in `checks/system.py SYSTEM_CHECKS`, then a verdict in an existing area or a new
   `(facts, verdicts)` pair in `AREAS`. Nothing else lists the areas.
4. Add its drill to `tests/test_check_drills.py`. The suite fails without it.
5. Plain words. No plan numbers or internal jargon in `message`, `why` or `fix`.

## The data behind a pick

The per-pick trust score (UHS) was retired in [ADR 0061](../decisions/0061-retire-uhs-and-dead-gates.md). What
replaces it is the number the pick gate already uses: **the share of the factor weight that applies to this
stock which was backed by a real value** (`daily_picks.eligible_coverage`, 0–100%). It varies stock by stock and
means one thing. `views.pick_data` words it for every surface (stock page "Data" tab and badge, picks email
footer, MCP `stock.data`, dossier prompt): **Complete** (every applicable factor had a value) or **Partial**
(ranked on the factors that had values, the missing ones named). Below `config.PICK_GATE["min_eligible_coverage"]`
the screener never writes the row, so a published pick is never below 60%.

System-level trust is the five-question scorecard, not a number.

The two write-time gates that stop bad rows before they are written (identity, plausibility —
`validators/_verdicts.GATES`) stay; `TRUST_GATE_DORMANT` fires if either stops writing verdicts.
