# HANDOFF
Updated: 2026-09-28 | Branch: master (0 unpushed) | HEAD: 723d2b2 docs(handoff): ingestion closed — ADR 0055, plan 0018 DQ notes, runbook, checklist

## Left off
Ingestion is closed and gated (plan 0018 / ADR 0055): `feeds.py`, 02:45 canaries + `tools/reconcile.py`, write contracts in `db.insert_df/upsert_df`, a row-count band, the `run_events` log, replay fixtures, and 5 new sources. Overnight, the scratchpad queues finish the Screener universe (with shareholder counts) → F&O/IV backfill → bulk price repair → July insider re-list → transcripts catch-up → first `screener_schedules` pass, all before 02:30; a waiter deletes any NULL-% shareholding rows the old-code Screener run still creates.

## Pick up here
1. **Verify the overnight work:**
   - `python -m runlog runs --limit 40`
   - `SELECT COUNT(*) FROM shareholding WHERE promoter_pct IS NULL AND n_shareholders IS NOT NULL` → 0
   - `bulk_deals` price=0 → 0
   - `fno_bhav` MIN(trade_date) ≈ 2024-07
   - `SELECT * FROM feed_checks WHERE check_kind='reconcile'` (first prices run)
2. **Chase the Gate 3 outliers:** MMTC (Tickertape 156.68 vs Screener 0.68 Cr) and GOCL (66.65 vs 4.29), in `quarterly_income` vs `fundamentals_screener`.
3. **Before any factor reads `analyst_estimates`:** check that Yahoo froze each estimate at the report. After the October results, compare `yahoo_calendar` estimates with the pre-report `yahoo_trend` snapshot.

## Watch out
- **A `ContractViolation` means the gate worked.** It blocks the batch before any write. Fix the parser; never loosen the contract.
- **A same-day resume of `sources/yahoo_estimates.py` raises "0 of N items"** when only data-less stocks remain (16:00 today). It is benign; the fix is to skip *attempted* stocks, not only ones that returned data. Saturday's weekly cron is unaffected.
- **Screener shareholder counts are UPDATE-only.** Upserting blanked `pledge_quality`'s latest shareholding row.
- **`broker_recommendations.reco_date_imputed = 1`:** 71% of rows carry the fetch date, not a broker date.

## Active plan
docs/plans/0018-data-supply-strategy.md (P0 + P1 core shipped; next P3 fallbacks) · master plan docs/plans/0011-roadmap-to-90.md
