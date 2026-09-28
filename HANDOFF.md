# HANDOFF
Updated: 2026-09-28 | Branch: master (pushed) | HEAD: see `git log -1` (plan 0018 DQ gates + handoff)

## Left off
Ingestion is closed (plan 0018 / ADR 0055).
- **Supply map and monitoring:** `feeds.py` registry, 02:45 canaries + Gate 3 `tools/reconcile.py`, write contracts enforced in `db.insert_df/upsert_df`, a self-calibrated row-count band, the `run_events` run log, replay fixtures, and the ops `/feeds` page.
- **5 new sources:** `market_events`, `analyst_estimates`, `shareholding.n_shareholders`.
- **Overnight, still running** from the two scratchpad queues:
  - Screener universe, then the F&O 2024-07+ backfill + IV, bulk price repair, July insider re-list, transcripts catch-up and the first `screener_schedules` pass, all stopping before 02:30
  - a waiter that deletes Screener-created NULL-% shareholding rows when the in-flight harvest exits

## Pick up here
1. **Verify the overnight work:**
   - `python -m runlog runs --limit 40`
   - `SELECT COUNT(*) FROM shareholding WHERE promoter_pct IS NULL AND n_shareholders IS NOT NULL` → 0
   - `bulk_deals` price=0 → 0
   - `fno_bhav` MIN(trade_date) ≈ 2024-07
   - the first prices reconcile: `SELECT * FROM feed_checks WHERE check_kind='reconcile'`
2. **Investigate the Gate 3 outliers:** MMTC (Tickertape 156.68 vs Screener 0.68 Cr) and GOCL (66.65 vs 4.29), in `quarterly_income` vs `fundamentals_screener`. Find which source has the wrong units or company.
3. **Before any factor reads `analyst_estimates`** (source `yahoo_calendar`, `pit_unverified`): after October results, compare it with the pre-report `yahoo_trend` snapshot. Then start the data-sources stage.

## Watch out
- **Write contracts now raise before writing.** A harvest that "fails" with `ContractViolation` (run log class F) caught garbage. Fix the parser; never loosen the contract.
- **Screener shareholder counts are UPDATE-only** (`sources/screener_pull.py`). Upserting created rows that would have blanked `pledge_quality`.
- **`broker_recommendations.reco_date_imputed = 1`:** 71% of rows carry the fetch date, not a broker date.
- **New crons can skip each other:** `estimates` (Sat 10:00), `transcripts` (Sun 07:00) and `screener_schedules` (3rd/4th of Jan/Apr/Jul/Oct, 20:30) all take the harvest lock and skip if it's held.
- **Scratchpad logs vanish on reboot;** `run_events` is the durable record.
- **Uncommitted, from other sessions** (left untouched): `sources/news_classifier.py`, plans 0016/0017, `architecture.md`, and the 0054 row in `docs/decisions/README.md`.

## Active plan
docs/plans/0018-data-supply-strategy.md (P0 + P1 core shipped; next P3 fallbacks) · master plan docs/plans/0011-roadmap-to-90.md
