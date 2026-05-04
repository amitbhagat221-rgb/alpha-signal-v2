---
Status: active
Created: 2026-05-03
Last updated: 2026-05-04
Owner: Amit Bhagat
Implementation: tools/reconstruct_pit.py, tools/import_v1_pit.py, tools/apply_splits.py, tools/compute_splits.py, tools/backtest_pit.py; tables daily_snapshots_pit, daily_snapshots_pit_v1, pit_ic_by_tier_v1, split_adjustments
Related ADRs:
---

# PIT Signal Reconstruction — Backtest-Grade Historical Data

> The live `daily_snapshots` table is contaminated with look-ahead: it uses any
> data that's been *fetched*, not just data that was *knowable* on the snapshot
> date. For backtesting, t-stat validation, and D18 XGBoost training, we need
> a separate PIT-clean dataset that respects filing-lag discipline.
>
> Created: 2026-05-03 | Owner: Amit Bhagat

---

## What problem are we solving?

Three concrete failures of the current state, all of which this plan resolves:

1. **Live snapshots violate PIT discipline.** Cross-checking PIT vs live for 2026-05-01: Piotroski differs in **816 / 2,224 stocks (37%)**, because live uses FY2026-03-31 fundamentals that wouldn't be filed until ~mid-June 2026. Any "backtest" against live snapshots silently uses tomorrow's data — every t-stat from such a backtest is overstated.

2. **Backtest history was almost non-existent.** Before today, daily-cadence signal scores existed for only 4 distinct dates (Apr 9, May 1, May 2, May 3). C13b's 36-period validation lived only as CSV files in v1's `data/backtest/` — never migrated into v2's SQLite. The mother plan ([0003](0003-mother-plan.md)) gated D18 on "≥6 months PIT data" with the implicit assumption it was accumulating; it wasn't.

3. **D17 segment-models work needs PIT to validate weight changes.** The mother plan's D17 weight vectors are anchored in C13b t-stats — but the t-stats themselves were computed in v1 and never re-derived in v2. Any weight tweak in D17 that isn't backed by a fresh v2 t-stat is hand-waved.

---

## What does the solution look like?

### What's already built (Phase 1 — done 2026-05-03)

`tools/reconstruct_pit.py` computes signals as-of each eval date by slicing raw history to "what was knowable" given filing-lag rules, then calling each signal's pure `_compute_scores()` function with pre-filtered inputs.

```
Filing lags:
  Annual fundamentals (BS, CF)    →  75 days   (SEBI deadline)
  Quarterly fundamentals (income) →  60 days
  Shareholding                    →  21 days
  Prices                          →   0 days   (same-day close)
```

**Output:** `daily_snapshots_pit` — same schema as `daily_snapshots` minus a few unsupported columns, plus a `reconstructed_at` audit timestamp.

**Coverage today (Phase 1):** 7 monthly dates × 2,448 stocks × 11 signal columns = **17,136 rows**.

| Date | piotroski | cf_accr | bs_accr | earnings_persist | EY | B/P | promoter | mom_6m | mom_12m | m_score | z_score |
|------|-----------|---------|---------|------------------|----|-----|----------|--------|---------|---------|---------|
| 2025-11-03 | 2169 | 2168 | – | – | 1754 | 1767 | 2374 | 1614 | 1527 | 1943 | 2169 |
| 2026-05-01 | 2224 | 2224 | – | – | 1902 | 1910 | 2435 | 1678 | 1612 | 2012 | 2224 |

### What's already built (Phase 1.5 — done 2026-05-03, AFTER initial Phase 1)

`tools/import_v1_pit.py` migrates v1's frozen 36-month reconstruction into v2 SQLite. **This is the canonical historical PIT dataset.**

- `daily_snapshots_pit_v1` — 60,168 rows, **35 monthly eval dates (2023-04-03 → 2026-02-02)**, 1,978 stocks, 13 signal columns + precomputed `fwd_return_20d`.
- `pit_ic_by_tier_v1` — 30 rows of canonical per-signal per-tier IC/t-stat. **This is the source table for the C13b numbers in CLAUDE.md.**

**Cross-check on overlapping dates** (3 overlap dates, 5,702 stock-date pairs):

| Signal | Pearson corr (v1 vs v2) | Why diverge |
|--------|-------------------------|-------------|
| book_to_price | 0.9997 | — (same Tickertape source) |
| bs_accruals | 0.9984 | — |
| cf_accruals | 0.9976 | — |
| piotroski_f | 0.9372 | Minor — different min-quarters gating in v2 |
| earnings_yield | 0.8919 | Price source: v1 used yfinance Adj Close, v2 uses NSE bhavcopy raw close |
| mom_6m | 0.7035 | Same price-source diff, compounded 6 months |
| mom_12m | 0.6681 | Same, compounded 12 months |
| **promoter_qoq** | **0.5491** | **Bug suspected** — v1 had only 6 quarters of shareholding; v2 has 53. May have picked different "latest knowable quarter" for QoQ delta. *Investigate before relying on v2 for promoter_qoq.* |

**Verdict:** v1 reconstruction is canonical for dates it covers (2023-04 → 2026-02). v2 reconstruction extends forward and adds m_score / z_score. Don't merge on overlapping dates — pick one source per date.

### What still needs to be built

```
PHASE 1    ✅  Foundation: 7 dates × 7 signals via _compute_scores() reuse (v2 fresh)
PHASE 1.5  ✅  Migrate v1's frozen 36-month reconstruction into SQLite
PHASE 2    ⏳  Coverage gaps: consensus, sentiment, insider, delivery%, smart_money, regulatory, macro
PHASE 3    ⏳  Methodology corrections: cap-tier drift, survivorship bias, financial-sector exclusion
PHASE 3.5  ⏳  Investigate v2 promoter_qoq divergence from v1 (corr 0.55)
PHASE 4    ⏳  Depth: extend v2 reconstruction backward to meet v1 boundary; eventually daily for D18
PHASE 4.5  ⏳  Add fwd_return_20d to v2 reconstruction (v1 has it; v2 doesn't)
PHASE 5    ⏳  Consumption: backtest harness reads from {v1, v2} PIT + screener --pit mode
PHASE 6    ⏳  Operational: incremental writes, smoke test, cockpit /backtest page
```

**Phase 4.1 (extend monthly history) is now mostly resolved by Phase 1.5** — v1 covers 35 monthly dates back to 2023-04, far more than the original 12-month target. Phase 4 is now narrower: extend v2 reconstruction backward enough to meet the v1 boundary (2026-02) without redundant work.

**Phase 5.1 (re-derive C13b in v2) is now substantially de-scoped** — `pit_ic_by_tier_v1` already holds the canonical numbers. Phase 5.1 becomes "compute v2 IC and confirm it agrees with v1 IC where the dates overlap" rather than "rebuild from scratch."

---

## Phase 2 — Coverage gaps (signals not yet reconstructed)

Each row below is a tracked gap with a proposed fix. Listed roughly in order of "alpha relevance" first, "easy wins" second.

### 2.1 — Consensus signal (BLOCKING for D17 LARGE-tier validation)

- **Problem.** `analyst_consensus` is a snapshot table — overwritten on each fetch, no history kept. Consensus is the **#1 signal in the LARGE tier (C13b t=3.52)** so missing history makes large-cap backtests impossible.
- **What we have.** `forecast_history` (29,013 rows, 2015→2026) — dated EPS/revenue forecast revisions per stock. This *is* a PIT-clean source: each row has `date` (the day the forecast was published).
- **Fix.** New module: `signals/consensus_pit.py` (sibling to existing `consensus.py`). For each eval_date, look at last-30-day forecast revisions ending at `eval_date`, compute mean revision direction, magnitude, count. Write to PIT table as new `consensus_signal` column.
- **What can't be PIT-reconstructed.** `buy_pct`, `total_analysts`, `price_target` — these are aggregated metadata that has no historical archive. Use only revision-based signal for historical dates; current-snapshot metadata stays current-only.
- **Effort.** ~1 session.

### 2.2 — Insider signal (already monthly, just needs join hygiene)

- **Status.** `insider_signals` table already accumulates 29 monthly snapshots back to 2024-04-01. **Not a coverage gap — a join gap.**
- **Fix.** Either (a) add insider columns to `daily_snapshots_pit` schema and merge in driver, or (b) document the join SQL for backtest consumers.
- **Recommendation.** Option (b) — keep daily_snapshots_pit a single-source-of-truth for *price-derived + fundamentals-derived* signals; insider lives in its own table and joins on `(sid, snapshot_date)`. Cleaner separation of concerns.
- **Effort.** ~30 min (just write the join helper).

### 2.3 — Sentiment (depth audit pending)

- **Problem.** `signals/sentiment.py` writes a single per-day VADER score per stock, computed from `news_articles` over a 7-day rolling window. Don't yet know how deep `news_articles` goes in v2.
- **Fix.** Audit news_articles min/max dates and per-day article counts. If continuous coverage back to ≥2025-11, reconstruct trivially (run sentiment math per eval_date with article filter `published_at BETWEEN eval_date - 7d AND eval_date`). If gappy, document the gap and skip.
- **Effort.** ~1 hour for audit + decision; ~1 session if reconstruction needed.

### 2.4 — Delivery % (already in stock_prices)

- **Status.** `stock_prices` has `delivered_qty` and `delivery_pct` columns from NSE bhavcopy. Forgotten to include in Phase 1.
- **Fix.** Add `delivery_pct` column to `daily_snapshots_pit` (or compute 30-day mean delivery_pct as of eval_date). Single SQL aggregate per date.
- **Effort.** ~30 min.

### 2.5 — Smart money (bulk_deals depth blocker)

- **Problem.** `bulk_deals` only has 13 distinct dates (2026-03-30 → 2026-04-30). NSE bulk deals API returns today-only — no historical archive (this is a known v1 landmine, documented in CLAUDE.md).
- **Fix options:**
  - **(a) Skip permanently** for historical dates; treat as a "going forward" signal only. Mark NULL in PIT for any date before bulk_deals first-row. *Recommended* — backtest will note the gap and weight smart_money to 0 for pre-2026-03-30 windows.
  - **(b) Backfill from a third-party source** (Trendlyne, etc.). Cost + reliability cost. Defer.
- **Recommendation.** Option (a). Document in plan; revisit only if D17 backtests show smart_money is a high-IC signal worth the backfill effort.
- **Effort.** ~10 min (NULL marker) + 0 ongoing.

### 2.6 — Regulatory signal (single-batch problem)

- **Problem.** `regulatory_signals` was classified in one batch on 2026-04-10. Re-running classification across historical events would re-emit signals at the *event date* (which is in the past for many events). The signal is *event-driven*, not snapshot-driven — its PIT representation should be "for date D, sum of regulatory_signal × decay over events with `published_at ≤ D`".
- **Fix.** New module: `signals/regulatory_pit.py` — consume `regulatory_events` joined to `regulatory_signals` (already classified), aggregate per (sector, eval_date) with time-decay. Output is per-sector, not per-stock.
- **Open question.** Sector signal vs stock signal. Per [0003 mother plan](0003-mother-plan.md) open question 5: regulatory probably belongs in a sector tilt overlay, not stock-level composite. If we ship as sector-only, then `daily_snapshots_pit` doesn't need a regulatory column — it goes into a separate `macro_sector_signals_pit` table. Decide before building.
- **Effort.** ~1-2 sessions.

### 2.7 — Macro sector signal

- **Problem.** Same shape as regulatory — sector-level, not stock-level. `macro_history` has 1,143 dates back to 2022 — plenty of depth.
- **Fix.** Build `macro_sector_signals_pit` (separate table, indexed by sector × date) that combines macro_history + macro_sector_map + decay. This is essentially a re-run of the existing `signals/macro.py` per eval_date.
- **Recommendation.** Bundle with 2.6 — both are sector-level tilt overlays; they share the table structure.
- **Effort.** ~1 session if bundled.

---

## Phase 3 — Methodology corrections

These are *correctness* fixes, not coverage. Each one introduces look-ahead bias or degrades signal quality if left unfixed.

### 3.1 — Cap-tier drift (fixable, currently a caveat)

- **Problem.** `tools/reconstruct_pit.py` uses `stocks.cap_tier` (current value) for all historical eval dates. A stock that was MID in 2025-11 and is now SMALL gets put in SMALL bucket for the historical period — distorting within-segment ranking.
- **Severity.** Low for 7-month lookback (tier migration is rare quarter-to-quarter), medium for 36-month, high for D18.
- **Fix.** Reconstruct cap_tier per eval_date from `stock_prices` × `shares_outstanding`:
  - Compute market_cap on eval_date as last_close × shares_outstanding (from latest knowable BS).
  - Rank within universe.
  - LARGE = top 100, MID = 101-250, SMALL = 251+ (matching current rule from CLAUDE.md).
- **Effort.** ~1 session. Low risk if added as a `--pit-tier` flag with the current behavior as default.

### 3.2 — Survivorship bias (the hard one)

- **Problem.** `stocks` table has 2,448 *currently-listed* names. Stocks delisted before 2026-05-03 are not in the universe at all. Any backtest using daily_snapshots_pit overstates returns by ~4.4% annually (the survivorship-bias number from CLAUDE.md).
- **Fix options:**
  - **(a) Don't fix** — note the bias in every backtest output. *Acceptable for now.*
  - **(b) Build a delisted-stocks shadow universe** — scrape NSE delisted-companies archive, mark with `delisted_date`, include in PIT eval if `delisted_date > snapshot_date`. *Substantial work — defer until D17 backtests need higher fidelity.*
- **Recommendation.** (a) for Phases 1-5; revisit (b) only if D17 backtests show the 4.4% bias is meaningfully changing weight rankings.
- **Effort.** Now: 0 (just document). Later: 2-3 sessions.

### 3.3 — Financial-sector exclusion not enforced in forensic

- **Observed.** PIT data shows HDBK (HDFC Bank, Financials) has m_score=-2.83 and z_score=0.76 — but [signals/forensic.py](../../signals/forensic.py) excludes financials per CLAUDE.md rule. Spot-check shows the *live* signal also includes financials → this is a **live signal bug, not a PIT bug**. PIT correctly mirrors live behavior.
- **Fix.** Out of scope for this plan (it's a live-signal correctness issue). File as separate follow-up. PIT will inherit the fix automatically when live is corrected (same `_compute_scores` is called).
- **Effort.** Track separately, not part of this plan.

### 3.5 — Investigate v2 promoter_qoq vs v1 divergence (NEW from Phase 1.5 cross-check)

- **Problem.** v1 ↔ v2 cross-check shows promoter_qoq Pearson corr **0.55** on 5,702 overlapping (sid, date) pairs. v1 mean –0.026, v2 mean –0.258 — v2 is ~10× more negative on average. Suggests v1 and v2 are picking *different* "latest knowable quarter" rows for the QoQ delta.
- **Hypothesis.** v1 had 6 quarters cached; v2 has 53. For a given eval_date, v2's larger window means there's a knowable quarter v1 simply didn't have access to. Different latest-quarter picks → different QoQ values.
- **Validation step.** For 5–10 sample stocks on 2025-12-01: print v1's chosen `(end_date_latest, end_date_prev, promoter_pct_latest, promoter_pct_prev)` vs v2's. If they differ, hypothesis confirmed and v2's value is more correct (it's using the actual most-recent knowable filing, v1 was stale-quarter-bound).
- **Resolution paths:**
  - **(a)** Confirm v2 is correct → trust v2 promoter_qoq, document v1 as having a stale-quarter ceiling.
  - **(b)** Discover a v2 bug → fix and re-run reconstruction.
- **Effort.** ~1 hour to investigate.

### 3.4 — Filing-lag conservatism

- **Observed.** 75-day annual lag is the SEBI ceiling. Many companies file in 30-45 days. Using 75d uniformly *under*-counts knowable data — some signals get 1 fewer year of history than reality.
- **Fix options:**
  - **(a) Stay at 75d.** Conservative; backtests are if-anything pessimistic. *Recommended* — it's the C13b standard, and being conservative is the right error in a backtest.
  - **(b) Per-stock filing-date lookup.** No reliable source for actual filing dates per stock per period. Would need scraping BSE/NSE filings. Not worth it.
- **Recommendation.** (a). Document in code comment; close as wontfix.
- **Effort.** 0.

---

## Phase 4 — Depth

### 4.1 — Extend monthly history: 7 → 12 → 36 dates

- **Why 12 next.** C13b's `MIN_PERIODS_FOR_IC = 6` was the floor for stable IC. v1 used 36. Twelve gives a comfortable backtest window without exhausting price-data depth (stock_prices goes back to 2022-07; 36 months = back to 2023-05, well within range).
- **Why not 36 immediately.** Compute is fine (~5 min). Risk is *new* gaps surfacing the further back you go (e.g. shareholding for older quarters may be sparse for newly-listed stocks). Stage in two passes: 12, then 36.
- **Fix.** Single CLI: `python -m tools.reconstruct_pit --months 12` then `--months 36`.
- **Effort.** 5 min × 2.

### 4.5 — Add fwd_return_20d to v2 reconstruction (NEW from Phase 1.5 cross-check)

- **Problem.** v1 reconstruction includes a precomputed `fwd_return_20d` column (the 20-trading-day forward return — backtest response variable). v2 reconstruction omits it. Without it, every backtest consumer has to re-derive forward returns from `stock_prices` per query — slow and error-prone.
- **Fix.** Add `fwd_return_20d` to `daily_snapshots_pit` schema. Compute as: for (sid, snapshot_date), join to `stock_prices` and find close on `snapshot_date + 20 trading days`; pct_change. NULL if 20 trading days haven't elapsed yet (latest 1 month of dates).
- **Note.** Use the same 20-day horizon as v1 for consistency. Some signals (D14 quality gate, D17 portfolio rebalance windows) may want 60-day or 90-day horizons later — add as separate columns if needed (`fwd_return_60d`, etc.) rather than overloading.
- **Effort.** ~30 min.

### 4.2 — Daily cadence (for D18)

- **Why.** XGBoost training on monthly snapshots over 36 months = 36 × 2,448 ≈ 88K rows. Daily cadence over 12 months = 252 × 2,448 ≈ 617K rows. Daily is the right shape for ML; monthly is the right shape for IC validation.
- **Fix.** Add `--cadence daily` flag. Daily reconstruction is just a tighter `generate_eval_dates`.
- **When.** Defer until D17 ships and D18 starts; don't compute daily until you need it.
- **Cost.** ~5 min per month of daily history × 12 months = ~1 hour wall time (and ~600K rows).
- **Effort.** ~1 session including optimization (chunk the per-date work to avoid loading all prices into memory per date).

---

## Phase 5 — Consumption (backtest harness + screener integration)

### 5.1 — Per-tier IC + t-stat backtest (DE-SCOPED by Phase 1.5)

- **Status.** Mostly resolved. `pit_ic_by_tier_v1` now holds 30 rows of canonical per-signal per-tier IC/t-stat from the v1 reconstruction — exactly the C13b numbers in CLAUDE.md.
- **Remaining work.** Build `tools/backtest_pit.py` only to **cross-validate v2 reconstruction agrees with v1 IC where dates overlap** (and to extend forward as v2 covers 2026-03 onward where v1 stops). The primary t-stat reference table already exists.
- **Step:**
  1. For each signal × tier × overlapping date range, compute v2 IC.
  2. Compare to `pit_ic_by_tier_v1.t_stat` for same signal × tier.
  3. Tolerance: ±0.3 t-stat = pass; >0.5 = bug.
  4. Then extend the IC computation forward over 2026-03+ dates and append rows to a new `pit_ic_by_tier_v2_extension` table.
- **Effort.** ~30 min for cross-validation; ~1 hour for forward extension.

### 5.2 — Screener `--pit` mode for backtest output

- **Problem.** `scoring/screener.py` reads live `daily_snapshots`. There's no way to ask "what would today's screener have ranked on 2025-12-01?"
- **Fix.** Add `--snapshot-date YYYY-MM-DD` flag to screener. When set, source from `daily_snapshots_pit` instead of `daily_snapshots`. All scoring math identical.
- **Effort.** ~30 min.

### 5.3 — Cockpit `/backtest` page

- **Why.** The IC/t-stat output is useless if you have to query it manually. A page that shows per-tier per-signal heatmap with current vs C13b reference would make the data load-bearing.
- **Defer.** Build this only after Phase 5.1 produces validated numbers — no point UI-ing nothing.
- **Effort.** ~1 session when ready.

---

## Phase 6 — Operational

### 6.1 — Smoke test for the reconstructor

- **Problem.** `tests/test_smoke.py` doesn't cover `tools/reconstruct_pit.py`. A regression in a `_compute_scores` function or a schema change would silently corrupt PIT output.
- **Fix.** Add `test_pit_reconstruction_smoke`:
  - Run reconstruction for 2 most recent dates × 2 signals (`--months 2 --signal piotroski --signal momentum --dry-run`).
  - Assert: row count = 2 × universe size, no exceptions, at least 50% non-null per signal.
- **Effort.** ~30 min.

### 6.2 — Incremental save (avoid the PIB-scraper landmine)

- **Problem.** The PIB scraper landmine in CLAUDE.md: "saves only at the END of all 110K iterations. Crash mid-run loses everything." Current `reconstruct_pit.py` writes per-date *inside* the loop (good) but doesn't checkpoint progress on resume. A 36-month run that crashes at month 30 has to redo months 1-30 (already-written rows are upserted, so no data loss — just wasted compute).
- **Fix.** Add `--skip-existing` flag: query distinct snapshot_dates from `daily_snapshots_pit` and skip any eval_date already covered.
- **Effort.** ~30 min.

### 6.3 — Reconstruction in pipeline?

- **Question.** Should `pipeline.py` run `reconstruct_pit.py` daily? Daily would only re-add the latest eval date if the cadence is monthly (most days = no-op), so cost is trivial.
- **Recommendation.** No. PIT reconstruction is a **research-time** tool, not a daily-pipeline tool. Run on demand when extending history or after a signal-math change. The daily pipeline is for live ranking.
- **Effort.** 0 (decision recorded).

---

## What does success look like?

This plan is done when:

1. ✅ Phase 1.5 done — v1 reconstruction migrated, cross-checked, documented. *(complete 2026-05-03)*
2. ⏳ `daily_snapshots_pit` has v2 reconstruction extending forward from 2026-03 (where v1 stops) to current month, with all stock-level signals including **consensus**, **sentiment**, **delivery%**, **fwd_return_20d**. [Phases 2.1 + 2.3 + 2.4 + 4.5]
3. ⏳ Insider signal join documented and consumable in backtests. [Phase 2.2]
4. ⏳ Sector signals (regulatory, macro) live in `macro_sector_signals_pit`. [Phases 2.6 + 2.7]
5. ⏳ Cap-tier reconstructed per eval date. [Phase 3.1]
6. ⏳ Promoter_qoq divergence investigated and resolved. [Phase 3.5]
7. ⏳ v2 IC cross-validates against `pit_ic_by_tier_v1` within ±0.3 t-stat on overlapping dates. [Phase 5.1]
8. ⏳ `screener --snapshot-date` runs and produces a sensible top-15. [Phase 5.2]
9. ⏳ Smoke test in tests/. [Phase 6.1]
10. ⏳ Survivorship-bias caveat documented in `architecture.md` and any backtest output. [Phase 3.2]

When all eight hold, this plan is archived to `_archive/`. Permanent learnings distill into:
- `architecture.md` — describe `daily_snapshots_pit` as a load-bearing table.
- `docs/reference/data-sources.md` — filing-lag rules.
- An ADR for "PIT reconstruction methodology" if any non-obvious choice persists (e.g. survivorship-bias deferral).

---

## What did we consider and reject?

- **Refactor live signal modules to take `as_of_date` instead of building a separate reconstructor.** Tempting because single source of truth. Rejected — invasive change to 7+ signal modules, each needing its data-loading rewritten to be date-parametric, with a regression risk to live pipeline. The current approach (reuse `_compute_scores()` after slicing data externally) is non-invasive and arrives at the same answer.

- **Daily reconstruction in Phase 1.** Rejected for now — monthly is the C13b standard, sufficient for IC validation, and 7× faster to compute. Daily comes back as Phase 4.2 when D18 needs it.

- **Backfill bulk_deals from third-party source.** Rejected — cost + reliability + the smart_money signal isn't in any tier's primary weights per the C13b validated map. Re-evaluate only if D17 surfaces it as high-IC.

- **Build the delisted-stocks shadow universe to fix survivorship bias.** Deferred (Phase 3.2 option b). Documenting the bias is enough for now; building it is justified only when the bias materially distorts a D17 weight decision.

- **Run reconstruction in the daily pipeline.** Rejected — research tool, not a daily artifact. Triggers on demand from CLI.

- **Use individual signal-table writes (piotroski_scores_pit, accruals_scores_pit, etc.).** Considered for symmetry with live tables. Rejected — single wide PIT table matches `daily_snapshots` shape, simplifies join-once consumption for backtests, and there's no INSERT-OR-IGNORE concern (each row is reconstructed cleanly per run).

- **Treat live `daily_snapshots` as PIT-clean and skip this plan entirely.** Rejected — empirically false (37% Piotroski divergence between live and PIT on 2026-05-01). Live is fine for daily ranking; backtests need their own clean dataset.

- **Re-run v1's reconstruction in v2 and discard the v1 CSV.** Considered. Rejected — v1's frozen CSV is the *source-of-truth* for the C13b t-stats already cited in CLAUDE.md and the mother plan. Re-deriving in v2 risks subtly different numbers (different price source, deeper Tickertape harvest, etc.) that would invalidate every weight choice anchored in C13b. Treat v1 reconstruction as historical record; use v2 reconstruction to extend forward only.

- **Merge v1 and v2 reconstructions on overlapping dates (e.g. averaging or v2-overrides).** Rejected — they have different price sources (yfinance Adj Close vs NSE bhavcopy raw close), different shareholding depths, and one signal (promoter_qoq) shows only 0.55 corr between them. Mixing creates uncomputable provenance. Pick one source per date: v1 for 2023-04 → 2026-02, v2 for 2026-03 onward.

---

## Open questions

1. **Regulatory + macro: per-stock or per-sector PIT?** Recommendation in 2.6: per-sector tilt overlay, separate `macro_sector_signals_pit` table. But D17's segment composite needs to know whether to include them as stock-level features — decide before Phase 2.6 starts.

2. **Cap-tier reconstruction rule.** CLAUDE.md says LARGE=1-100, MID=101-250, SMALL=251+. But the rule is over what universe? Ranking by *total market cap including delisted* would be different from *current 2,448-name universe*. Suggest: rank within current universe (stocks present in `stocks` table at eval time), not historical universe — keeps it simple and consistent.

3. **What ±IC tolerance accepts a v2 backtest as "matching" C13b?** I proposed ±0.3 t-stat. If we're stricter (±0.1), we may have to investigate every minor divergence. If looser (±0.5), we may miss a real bug. Decide before Phase 5.1.

4. **Should `reconstruct_pit.py` move to `signals/`?** It calls into signals/, lives in tools/, but conceptually belongs alongside signals. Mild bikeshedding — defer until directory structure is reviewed.

---

## Cross-references

- **Mother plan, where this fits:** [0003-mother-plan.md](0003-mother-plan.md) — D17 weight validation depends on this plan; D18 ML training depends on Phase 4.2 (daily cadence).
- **C13b methodology source:** [v1 38_signal_reconstructor.py](../../../alpha-signal/scripts/38_signal_reconstructor.py) — the original, with its filing-lag constants and 36-monthly date list. v2 reconstructor inherits the lag constants but uses a generated date set rather than the hardcoded 36.
- **CLAUDE.md filing-lag rule:** annual 75d, quarterly 60d, shareholding 21d.
- **Sister plans:** [0001-regulatory-signal.md](0001-regulatory-signal.md), [0002-macro-data.md](0002-macro-data.md) — both relevant to Phase 2.6 + 2.7.

---

## Implementation notes — 2026-05-04

### Phase 2 (Coverage gaps) — substantially complete

- `earnings_beat_rate` computed via QoQ-positive proxy in [tools/reconstruct_pit.py](../../tools/reconstruct_pit.py) `pit_earnings_beat_rate`. 2,161-2,221 stocks populated across all 7 snapshot dates. Status flipped READY in [db.py BACKTEST_SIGNALS](../../db.py).
- `news_volume_7d` computed in `pit_news_volume`. 0 rows for snapshots before 2026-03 (no news data); 10-118 stocks/date for 2026-03+. Forward-only by data availability.
- `m_score`, `z_score` reclassified READY — data was always populated (13,922 / 15,504 rows); status was conservative.
- `fii_dii_cash_net`, `fii_dii_fno_positioning` reclassified READY — these are macro-level signals (per-date, not per-stock), consumed by regime overlay; daily forward cron at 14:00 UTC accumulating.
- `short_selling_signal` reclassified READY (was PROPOSED). Compute function was already wired; registry just hadn't been flipped.

### Phase 3 (Methodology corrections)

- **mom_6m / mom_12m split adjustment shipped.** [tools/compute_splits.py](../../tools/compute_splits.py) parsed 104 of 207 `corporate_actions` SPLIT/BONUS events. [tools/apply_splits.py](../../tools/apply_splits.py) populates `stock_prices.adj_close` (new column). [tools/reconstruct_pit.py](../../tools/reconstruct_pit.py) `pit_momentum` switched to use `adj_close` via `COALESCE(adj_close, close)`. **v1↔v2 mom_12m correlation improved 0.67→0.78**, mom_6m 0.70→0.72. Both reclassified READY.
- **Remaining gap on mom signals: dividend adjustment.** v1's yfinance Adj Close adjusts splits AND dividends; our adj_close only adjusts splits. The remaining 0.22-0.28 correlation gap is plausibly all dividend-driven. Requires a second pass over `corporate_actions` for DIVIDEND events. Tracked but deferred.
- **promoter_qoq diagnostic.** Raw v1↔v2 correlation 0.42-0.63 looked alarming. Diagnostic 2026-05-04: median |v1−v2 diff|=0.000 across 1,896 overlap stocks. On the subset where both signals are >0.05 in absolute value (n=303), **sign-match=97.4%**. The low correlation was scatter-dominated by the agreement-at-zero majority. The signal is directionally clean for ranking. Reclassified READY.

### Phase 6 (Operational)

- Full PIT reconstruction across all 22 signals × 7 monthly dates × 2,448 stocks runs cleanly in ~210 seconds (`python -m tools.reconstruct_pit --months 7`). 17,136 rows written.
- Checkpoint log (`pit_reconstruction_log`) populates RUNNING → SUCCESS rows per (eval_date, signals_run) tuple. `--skip-existing` flag works correctly.
- Validation guardrails active: `consensus_signal_combined` ranges-out warning fires consistently (small-base-EPS divisions produce extreme YoY values; clipper catches them).

### Bug found (deferred)

- [db.py:181](../../db.py#L181) `upsert_df` uses `INSERT OR REPLACE` which deletes the existing row and inserts a new one. Effect: running `python -m tools.reconstruct_pit --signal X` nulls every column not in df for affected rows. Caused mid-session data loss; recovered via final full reconstruction. **Hard rule until fixed: always run full reconstruction.** Fix: switch to `INSERT ... ON CONFLICT(<pk>) DO UPDATE SET <only-provided-cols>`.

### What's still open in this plan

- Phase 4 (PIT depth past 2023) — gated on EODHD subscription or alternative deep history source.
- Phase 5 (backtest harness consumption) — [tools/backtest_pit.py](../../tools/backtest_pit.py) ships and validates v1 archive; integration into screener weight selection (D17) is the open piece.
- Dividend adjustment for mom signals — closes the residual mom v1↔v2 gap.
