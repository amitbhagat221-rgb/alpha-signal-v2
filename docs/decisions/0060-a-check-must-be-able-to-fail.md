# ADR 0060 — A daily check must be able to fail, and prove it

**Status:** accepted 2026-10-02 · **Builds on:** ADR 0059 (five questions, one issue list), ADR 0052 (Check block) · **Supersedes:** the check list of ADR 0059 (60 checks → 24)

**Decision.** A check stays in the daily health report only if all four hold:
1. **It can fail today because the world changed** (data arrived wrong, a factor input died, the ranking broke).
   A rule that can only break when code or a registry changes is a test: it runs when the code changes.
2. **It guards something the models read or the reader sees today**, derived from the registries so a factor wired
   tomorrow is covered tomorrow.
3. **It has a fire drill** in `tests/test_check_drills.py` that breaks what it guards and asserts the check notices.
   `test_every_check_has_a_drill` fails for a check without one.
4. **It looks at rows.** A check whose scope is empty is reported (`CHECK_VACUOUS`), never passed.

Every check's status is recorded each day (`check_results`, catalog check `health`), so each issue shows how many
days it has been firing and the catalog shows when each check last fired. A WARN firing 14+ days is "standing":
fix it, accept it, or delete the check.

## Why (evidence, 133 days of `output/health.log` + the live DB, 2026-10-02)
- **Could never fire:** `DAILY_PICKS_RANK_DUPLICATE` (the primary key forbids it), `DAILY_PICK_NO_PRICES` and
  `DAILY_PICK_THIN_SIGNAL_COVERAGE` (the pick gate refuses those stocks before `daily_picks` is written),
  `EXTERNAL_ANCHOR_DRIFT` (Gate 7 has never written a verdict), four banking range checks (columns nothing fills).
- **Guarded what the model no longer reads:** the factor checks covered Piotroski, smart-money, `pt_upside` and an
  8-signal list from May. Six of the ten wired factors had no daily check at all. The ranking reads
  `pit.features_at`, not the `*_scores` tables those checks looked at.
- **Fired once after the bug that inspired them, then never:** `FORECAST_HISTORY_*`, `PIOTROSKI_F_SUM_MISMATCH`,
  `SCORE_TABLE_DEFAULT_PROLIFERATION` and others. They are code regressions; tests guard those.
- **Fired every day and changed nothing:** `FACTOR_DECAY` 89 days, registry partition 83, no-date-anchor 85.

## What changed
- **New, model-first (`checks/model.py`):** `FACTOR_INPUT` judges every wired (tier, factor) on the values the
  screener actually used (`pit_replay_snapshots.inputs_json`) against that factor's own last 20 days: coverage
  collapsed, or one value for every stock. `PICKS_RESHUFFLED`: rank correlation with yesterday under 0.6 (150 days
  of history: usually 0.95+, 0.37 on the one day the weights changed).
- **Retired to tests:** rank uniqueness, the pick gate, the dossier growth clip (`tests/test_check_drills.py`),
  registry partition and lineage (`tests/test_factor_registry.py`), unscheduled / no-fallback / unregistered feeds
  (`tests/test_feeds.py`), tables without a date column (`tests/test_tables.py`).
- **Retired as covered:** date drift, monthly-snapshot and regulatory-dark (table freshness), eligibility regression
  and the Piotroski trio (`FACTOR_INPUT`), anchor drift and broker-vs-Yahoo targets (the daily feed reconcile).
- **Merged:** three price-target checks → `ANALYST_TARGET_IMPLAUSIBLE` (WARN: targets are shown, not ranked on,
  since ADR 0045; CRITICAL only at 10%+, a broken feed). Step failure + streak → `PIPELINE_STEP`; stale + outdated →
  `TABLE_STALE`; four probe codes → `FEED_PROBE`; two volume codes → `FEED_VOLUME`.
- **Tolerated by rule, not by habit:** a stale best-effort table (`db.BEST_EFFORT_STALE`) is INFO; a column
  declared `may_be_empty` in `checks/ranges.py` is not a silent check.

## Consequences
- 24 checks, each with a drill. `test_catalog_lists_every_check_once` caps the catalog at 30: a new check must
  replace one or earn its place.
- `FACTOR_INPUT` needs `pit_replay_freeze` to have run; if the picks are newer than the freeze it says so.
- History starts 2026-10-02; "last fired" is blank before that.

## Closed on 2026-10-03 (the findings above, fixed at the cause)
- **Checked before the picks go out.** The picks email runs `checks.run(theme="picks")` and carries a banner when a
  factor input is dead or the ranking broke; the freeze of the day's inputs now runs before the email.
- **`FACTOR_DECAY` flagged noise.** Twelve anchors of a weak factor flip sign by chance. It now also needs the recent
  mean to sit 2+ standard errors below the long-run mean: 8 of 16 flagged → 3 (MID and SMALL book-to-price, SMALL
  delivery anomaly), which are for a promotion review.
- **Bad analyst targets came back every morning.** The daily Moneycontrol broker aggregate rewrote
  `analyst_consensus.price_target` from calls that can be years old; the Yahoo sweep that nulls them runs weekly.
  One rule now (`validators.plausibility.PT_CLOSE_RATIO`) at both writers and in the check: 32 → 0.
- **Cost of funds of 7,700%.** A ratio over almost no borrowings is not a value: the producer keeps it only inside
  the column's legal range. Four never-filled banking columns are declared `may_be_empty`.
- **`datamodel_reconcile` could never pass.** It counted the sync's own log row, written after the sync read the
  table: off by exactly one, a CRITICAL every day. It now compares the rows the sync has seen.
- **Layout.** A system check is a `(facts, verdicts)` pair in `checks/system.AREAS` next to its meaning;
  `checks/report.gather()` is the one state; `tools/health_report.py` only renders.

## The data-trust score (UHS) and its gates — retired: [ADR 0061](0061-retire-uhs-and-dead-gates.md)
Gates 3/4/5 ran once by hand on 2026-05-31 and were never scheduled; Gate 7's step never wrote a verdict; the score
was 97–98 for almost every pick and hid 4–16 SMALL picks on eight Tuesdays for a price target the ranking does not
use. Evidence and the replacement (factor coverage per pick) are in ADR 0061.
