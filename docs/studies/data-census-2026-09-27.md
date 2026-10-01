# Data census — 2026-09-27

**Purpose:** Phase A of the data-model redesign ([ADR 0054](../decisions/0054-tables-grow-with-concepts.md), [plan 0017](../plans/0017-data-model-redesign.md)). Every table in `data/alpha_signal.db`: what it is, its size, how fast it grows, whether it can answer "what did I know on date D", and where it goes in the new model.

**Method:**
- Sizes come from `dbstat` on a `VACUUM INTO` snapshot taken 2026-09-27 18:43 UTC (8.1 GB compacted; the live file is 8.75 GB).
- Rows and dates come from the same snapshot. "Rows/mo" is the number of rows whose registry `date_col` falls in the last 90 days, divided by 3. For tables anchored on `fetched_at` it counts re-fetches, not new facts.
- Writers and readers were found by static scan and then read and verified by four read-only auditors (appendices A–D). The lead re-checked the load-bearing claims in code or SQL: the pre-push hook deleting RELI rows, `stocks` having no INSERT path, `macro_sector_map` having no writer, the two-transaction rerun of `daily_picks`, the forecast_history EPS filter having no lag, and `bse_announcements` bytes per row.
- Code at master 7996712.

## Summary by target concept

| Concept | Tables today | Rows | Data MB | Index MB |
|---|---|---|---|---|
| Reference | 5 | 35,026 | 3 | 1 |
| Bars | 3 | 9,349,267 | 936 | 716 |
| Series | 3 | 72,009 | 7 | 4 |
| Events | 13 | 2,931,599 | 1,771 | 434 |
| Documents | 6 | 108,801 | 763 | 10 |
| Company facts | 9 | 1,254,116 | 93 | 92 |
| Features | 49 | 7,939,483 | 576 | 476 |
| Decisions | 7 | 1,251,173 | 401 | 67 |
| Research | 2 | 584 | 0 | 0 |
| Ops | 16 | 334,578 | 86 | 40 |
| MF (mf.db) | 11 | 9,538,708 | 520 | 542 |
| DESIGN Q | 1 | 230,220 | 38 | 42 |
| DELETE | 9 | 736,675 | 54 | 58 |
| **Total** | **134** | **33,782,239** | **5,249** | **2,482** |

- **The 134 tables are:** 32 `*_scores` · 11 `*_quarantine` · 11 `mf_*` · 80 others. There are 52 foreign keys to `stocks(sid)`.
- **Where the space goes.** Raw data dominates: `bse_announcements` 2.07 GB, `fno_bhav` 1.31 GB, `mf_nav_history` 0.98 GB, `transcripts` 0.73 GB and `universe_eligibility` 0.39 GB. The 32 `*_scores` tables together are 0.30 GB (0.16 data + 0.14 index). Indexes are 32% of the file.
- **Fastest growth (rows/month):** `universe_eligibility` (663K), `fno_bhav` (418K), `fundamentals_screener` re-fetches (233K), `mf_nav_history` (187K), and each daily per-stock signal table (~74K).

## Findings that change the design (verified)

1. **No point-in-time history for the hub.** `stocks.cap_tier` and `sector` are overwritten in place, so the backtest panel uses today's tier for every past date. Also, `stocks` has no INSERT path, so the universe can't add a listing or drop a delisting. This means we need `classifications` with valid_from/valid_to, and an entity master that includes dead names (`historical_universe` already has them).
2. **Snapshot tables that aren't snapshots.**
   - `forecast_history` is overwritten monthly and dated by fiscal period. The wired `consensus` factor reads EPS with `date <= D` and no filing lag (pit.py `_pit_input` "fh"). That is the same float-then-freeze class of problem as ADR 0045, and it is unmeasured for EPS.
   - `analyst_consensus_snapshots` rows are backdated.
   - `analyst_consensus` has a second, undeclared writer.

   Only versioned rows (`fetched_at` + `last_seen_at`) make "as of D" answerable.
3. **Event dedup keys lose rows.**
   - `insider_trades`' UNIQUE key omits `person`, and there is no disclosure date.
   - `bulk_deals`' UNIQUE key omits `buy_sell` and `deal_type`.
   - `regulatory_events` has mixed date formats, so RFC-2822 rows silently drop out of the PIT data.

   The fix is one `source_key` per source plus `available_at`.
4. **Text that isn't narrative.** Of the 5 "TEXT" signal tables, none needs a document store. The flags, grades and trends are threshold enums of numbers, and one of them is mis-ranked alphabetically (multibagger ranks `promoter_trend` ACCUMULATING lowest). Enum codes declared in the catalog fix that whole class of bug.
5. **The same fact stored twice, with the copies drifting apart:**
   - pick UHS: `health_score` vs `daily_picks.uhs_*`
   - `vix_history` vs `macro_history`
   - `external_anchors` vs `stock_prices`
   - quarantine mirrors vs `trust_verdicts` (320 QUARANTINED verdicts with 0 mirror rows)
   - `macro_sector_map` vs `signals/macro.py:32`
6. **Multi-producer OR REPLACE is still live.** `sector_briefs` NULLs `horizon_*`, and `news_enriched` wipes `image_url`. Both are the analyst_consensus class of bug, so they need one write rule per concept, enforced.
7. **Churn with no reader.** `uhs_calibration_log` rewrites ~210K rows nightly for no reader. 17 of the 22 annual-ratio tables are written daily for no reader, and ~97% of their rows re-stamp unchanged values.
8. **The live screener no longer reads `*_scores`.** It computes every factor through `pit.features_at` from raw tables (since 4af1d6f). The per-factor tables now serve surfaces, gates and the MICRO rule only, so migrating Features is off the ranking path. The exact per-pick inputs survive only in `pit_replay_snapshots.inputs_json`.
9. **Production-data hazards outside the schema:**
   - **Every git push wipes live rows.** `.git/hooks/pre-push` → `tools/regression_fixtures.py:185-226` runs against the live DB and deletes all of RELI's `trust_verdicts` and `external_anchors`.
   - **Gate 7 can never fire.** `stock_prices`' PK is (sid, date), so a second price source can't be stored next to the first.

## Per-table census

| Table | Rows | Cols | Data+idx MB | Rows/mo (last 90d) | Date span | PIT-safe today | Target | Note |
|---|---|---|---|---|---|---|---|---|
| `scrip_master` | 14,780 | 8 | 1.7 | 4832 | 2026-06-09 → 2026-09-27 | n/a | identifiers | Upstox instrument map rebuilt daily |
| `historical_universe` | 17,691 | 7 | 1.6 | 0 | 2018-04-02 → 2026-05-29 | yes | entities (dead names) + classifications(listed) | survivorship-free listing per bhavcopy date; manual tool |
| `stocks` | 2,448 | 26 | 0.8 | 812 | 2026-04-09 → 2026-09-27 | no | entities + classifications + identifiers | hub (52 FKs); cap_tier/sector overwritten in place → backtest uses today's tier; no INSERT path; 14 dead columns |
| `macro_indicator_meta` | 77 | 8 | 0.0 | — | — | n/a | catalog (kind=series) |  |
| `macro_sector_map` | 30 | 5 | 0.0 | — | — | n/a | catalog.spec of each series (sector weights) | NO writer, NO seed in schema.sql — rebuild loses sector_tilt's macro leg; live uses a different hard-coded map (signals/macro.py:32) |
| `fno_bhav` | 6,873,962 | 15 | 1,313.6 | 417835 | 2025-05-26 → 2026-09-25 | yes | derivative_bars | 0.75 GB + 0.6 GB indexes |
| `stock_prices` | 2,462,992 | 13 | 336.5 | 51208 | 2020-01-01 → 2026-09-25 | yes | bars_daily | PK (sid,date) — one source per day |
| `nse_index_history` | 12,313 | 9 | 1.9 | 277 | 2016-01-01 → 2026-09-25 | yes | bars_daily (entity kind=index) |  |
| `macro_history` | 65,977 | 9 | 10.4 | 561 | 2015-06-25 → 2026-09-26 | partly | series_values (versioned) | already long (indicator_id, date, value) |
| `fii_dii_positioning` | 5,840 | 17 | 0.7 | 106 | 2022-01-03 → 2026-09-25 | yes | series_values |  |
| `fii_dii_cash_flow` | 192 | 6 | 0.0 | 38 | 2026-05-03 → 2026-09-25 | yes | series_values |  |
| `bse_announcements` | 2,596,559 | 21 | 2,073.2 | 34372 | 2026-06-08 → 2026-09-27 | yes (dissem_dt) | events + documents(filing text, future) | 1.77 GB = 2.6M rows × ~480 B short strings, not full text (verified) |
| `regulatory_events` | 93,201 | 12 | 83.0 | 15233 | 1993-11-01 → Wed, 31 Ma | no (mixed date formats) | events | RFC-2822 rows silently dropped from PIT |
| `news_articles` | 26,034 | 7 | 16.8 | 4630 | 2024-04-23 → 2026-09-27 | yes | events + documents(body) |  |
| `bulk_deals` | 56,294 | 10 | 8.5 | 1950 | 2021-01-01 → 2026-09-25 | yes (EOD) | events | UNIQUE omits buy_sell/deal_type |
| `insider_trades` | 33,430 | 13 | 7.3 | 496 | 2020-10-20 → 2026-09-25 | no (no disclosure date) | events | UNIQUE omits person |
| `short_selling_data` | 41,645 | 6 | 4.5 | 2341 | 2026-05-03 → 2026-09-25 | yes | events |  |
| `corporate_actions` | 20,047 | 9 | 3.9 | 408 | 2026-05-03 → 2026-09-25 | yes | events |  |
| `broker_recommendations` | 11,379 | 8 | 2.8 | 2662 | 2026-05-24 → 2026-09-27 | partly | events (type broker_reco) | missing reco_date filled with today |
| `surveillance_flags` | 20,217 | 7 | 2.4 | 4105 | 2026-05-03 → 2026-09-27 | yes | events |  |
| `news_article_stocks` | 21,006 | 3 | 1.4 | — | — | yes | event_links |  |
| `corporate_adjustments` | 9,384 | 7 | 1.1 | 3128 | 2026-09-27 → 2026-09-27 | yes | events (type price_adjustment, derived) | rebuilt daily from corporate_actions |
| `earnings_calendar` | 2,375 | 8 | 0.6 | 724 | 2026-04-08 → 2026-10-27 | yes | events |  |
| `policy_events` | 28 | 7 | 0.0 | — | — | yes | events |  |
| `transcripts` | 15,471 | 13 | 734.1 | 0 | 2026-06-06 → 2026-06-07 | yes (available_date) | documents | 0.73 GB text; no step since 06-07 |
| `regulatory_signals` | 72,286 | 10 | 23.8 | 14478 | 2026-04-10 → 2026-09-27 | no (labelled later with hindsight) | documents (type regulatory_classification) | per-event × sector |
| `news_enriched` | 20,357 | 13 | 11.4 | 4622 | 2026-05-24 → 2026-09-27 | n/a | documents (type news_classification, event-linked) | OR REPLACE wipes image_url (2 writers) |
| `sector_dossiers` | 565 | 12 | 2.5 | 119 | 2026-05-31 → 2026-08-23 | n/a | documents | LLM |
| `sector_metadata` | 48 | 6 | 0.9 | — | — | n/a | entities(kind=sector).attrs + documents | hand-maintained |
| `news_briefs` | 74 | 7 | 0.1 | 15 | 2026-05-24 → 2026-08-23 | n/a | documents | LLM; stale since 08-23 (credits) |
| `fundamentals_screener` | 1,125,537 | 7 | 168.4 | 232742 | 2026-05-10 → 2026-09-27 | lag-rule | fundamentals (versioned) | already long (sid, period_end, line_item, value) |
| `quarterly_income` | 26,440 | 13 | 4.2 | 739 | 2012-03-31 → 2026-06-30 | lag-rule | fundamentals (versioned) | available_at = end_date + 60d |
| `annual_balance_sheet` | 20,679 | 16 | 3.6 | 0 | 2015-03-31 → 2026-03-31 | lag-rule | fundamentals (versioned) | +75d |
| `annual_cash_flow` | 20,624 | 12 | 2.8 | 0 | 2015-03-31 → 2026-03-31 | lag-rule | fundamentals (versioned) | +75d |
| `forecast_history` | 31,457 | 6 | 2.8 | 1 | 2015-12-30 → 2026-06-30 | NO (eps: date<=D, no lag) | estimates (versioned) | overwritten monthly; metric=price is contaminated (ADR 0045) |
| `shareholding` | 18,948 | 12 | 2.3 | 784 | 2016-12-31 → 2026-08-31 | lag-rule | fundamentals (family ownership, versioned) | +21d; category %s, not holder-level |
| `analyst_consensus_snapshots` | 4,536 | 11 | 0.7 | 909 | 2026-05-01 → 2026-09-01 | partly | estimates (monthly view = as-of the 1st) | snapshot_date backdated (05-01 row fetched 05-22) |
| `banking_metrics` | 3,455 | 28 | 0.6 | 1007 | 2026-05-29 → 2026-08-01 | lag-rule | fundamentals (versioned) | Screener; auth dead since Aug |
| `analyst_consensus` | 2,440 | 25 | 0.3 | 811 | 2026-03-29 → 2026-09-27 | no | estimates (current = latest version view) | hidden 2nd writer (moneycontrol_recos.py:347) overwrites PT under pt_source='yfinance' |
| `universe_eligibility` | 2,714,832 | 5 | 391.3 | 663408 | 2026-05-23 → 2026-09-27 | no | feature_values (elig_* features) | 22K 0/1 rows/day computed from current tables; with run_id it becomes reproducible |
| `daily_snapshots_pit` | 494,496 | 109 | 190.0 | 13056 | 2019-12-02 → 2026-09-25 | yes (lag rules) — but cap_tier = today's | feature_values (history → Parquet) | 109 cols, all numeric |
| `daily_snapshots` | 369,648 | 16 | 59.6 | 74256 | 2026-04-09 → 2026-09-27 | as-of = run date | feature_values | live wide snapshot |
| `smart_money_scores` | 369,648 | 9 | 32.9 | 74256 | 2026-04-09 → 2026-09-27 | as-of = run date | feature_values |  |
| `sentiment_scores` | 378,837 | 10 | 29.5 | 74256 | 2026-03-15 → 2026-09-27 | as-of = run date | feature_values | latest_headline holds a number as text |
| `insider_signals` | 231,195 | 6 | 27.3 | 26928 | 2024-04-01 → 2026-07-31 | as-of = run date | feature_values (+ enum codes) | description regenerable from insider trades; stale since 07-31 |
| `consensus_signals` | 315,594 | 7 | 25.3 | 74256 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | integrity gate + display read it directly; 'consensus' name clash |
| `share_momentum_scores` | 207,588 | 5 | 18.3 | 45445 | 2026-05-10 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `accruals_scores` | 193,392 | 6 | 18.2 | 15504 | 2026-04-09 → 2026-09-27 | as-of = run date | feature_values |  |
| `forensic_scores` | 193,392 | 7 | 17.3 | 15504 | 2026-04-09 → 2026-09-27 | as-of = run date | feature_values (+ enum-coded flags) | flags are thresholds of m/z score |
| `promoter_signals` | 193,392 | 6 | 16.4 | 15504 | 2026-04-09 → 2026-09-27 | as-of = run date | feature_values (+ enum-coded trend) | promoter_trend TEXT is mis-ranked alphabetically by multibagger |
| `piotroski_scores` | 176,213 | 12 | 13.8 | 13927 | 2026-04-09 → 2026-09-27 | as-of = run date | feature_values | integrity gate + MICRO tier read it directly |
| `fno_pcr_history` | 72,035 | 15 | 11.7 | 4584 | 2025-05-26 → 2026-09-25 | yes | feature_values | backtest-only |
| `sales_growth_relative_scores` | 114,383 | 6 | 11.4 | 10883 | 2026-05-10 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `daily_snapshots_pit_v1` | 60,168 | 20 | 11.4 | 0 | 2023-04-03 → 2026-02-02 | yes | feature_values (v1.* features, archive run) | 4–6 readers, all switchable |
| `roic_scores` | 103,346 | 6 | 10.2 | 9916 | 2026-05-10 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `fno_iv_history` | 69,450 | 11 | 9.9 | 4428 | 2025-05-26 → 2026-09-25 | yes | feature_values (+ series for index rows) | wired via iv_skew_25d (MID) |
| `inventory_turnover_scores` | 96,532 | 6 | 9.5 | 9171 | 2026-05-10 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `revenue_cv_scores` | 108,803 | 5 | 8.9 | 10444 | 2026-05-10 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `asset_tangibility_scores` | 104,500 | 4 | 8.6 | 11905 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `dso_change_yoy_scores` | 100,468 | 4 | 8.2 | 11486 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `fcf_yield_scores` | 82,034 | 6 | 8.1 | 7779 | 2026-05-10 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `operating_margin_trend_scores` | 82,072 | 6 | 8.1 | 9498 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `sga_to_revenue_change_scores` | 99,266 | 4 | 8.1 | 11271 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `cash_conversion_cycle_scores` | 74,168 | 7 | 8.0 | 8393 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `dio_change_yoy_scores` | 93,992 | 4 | 7.7 | 10746 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `interest_coverage_scores` | 91,184 | 4 | 7.5 | 10513 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `nwc_to_revenue_scores` | 82,468 | 4 | 6.7 | 9334 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `sloan_accruals_full_scores` | 80,844 | 4 | 6.6 | 9151 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `goodwill_to_assets_scores` | 81,248 | 4 | 6.5 | 9199 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `multibagger_scores` | 31,878 | 31 | 6.5 | 7283 | 2026-06-03 → 2026-09-27 | as-of = run date | feature_values (+ 0/1 reason features) | ranks TEXT promoter_trend alphabetically (bug) |
| `roiic_scores` | 64,860 | 6 | 6.4 | 7671 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `gross_profitability_scores` | 64,422 | 6 | 6.4 | 9184 | 2026-06-03 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `working_capital_intensity_scores` | 74,168 | 4 | 6.1 | 8393 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `fcf_margin_scores` | 74,880 | 4 | 6.1 | 8680 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `capex_to_dep_scores` | 76,240 | 4 | 6.1 | 8812 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `debt_structure_scores` | 73,128 | 4 | 5.9 | 8281 | 2026-05-22 → 2026-09-27 | as-of = run date | feature_values | 22 annual-ratio tables: ~97% rows re-stamp unchanged values; 17 have no reader |
| `financial_signal_scores` | 17,202 | 23 | 3.4 | 4277 | 2026-05-29 → 2026-09-27 | as-of = run date | feature_values (+ enum codes) | financial_signal == financial_quality in every row |
| `sector_force_breakdown` | 4,057 | 8 | 2.7 | 1011 | 2026-05-29 → 2026-09-27 | yes | feature_values (entity=sector) |  |
| `nlp_scores` | 15,031 | 11 | 2.2 | — | — | yes (available_date; 96 bad rows) | feature_values (date = available_date) ; doc grain via documents | OR REPLACE |
| `sector_briefs` | 1,342 | 20 | 1.1 | 333 | 2026-05-29 → 2026-09-27 | n/a | feature_values(sector) + documents | OR REPLACE NULLs horizon_* written by sector_momentum |
| `macro_sector_signals` | 2,839 | 5 | 0.5 | 578 | 2026-04-09 → 2026-09-27 | yes | feature_values (entity=sector) | live twin ≠ PIT twin (two maps) |
| `managerial_ability_scores` | 1,736 | 18 | 0.4 | 0 | 2026-06-09 → 2026-06-09 | as-of = run date | feature_values (+ enum grade) | manual, no step |
| `management_scores` | 1,609 | 20 | 0.3 | 0 | 2026-06-06 → 2026-06-06 | as-of = run date | feature_values (+ enum grade) | manual, no step |
| `macro_sector_signals_pit` | 737 | 7 | 0.2 | 58 | 2022-08-01 → 2026-09-25 | yes | feature_values (entity=sector) | live input to wired sector_tilt |
| `regime_state` | 1 | 8 | 0.0 | 0 | 2026-09-27 → 2026-09-27 | no | runs.attrs + feature_values(entity=market) | single row overwritten; display only |
| `macro_indicators` | 44 | 5 | 0.0 | 7 | 2026-04-09 → 2026-09-27 | ? | feature_values (entity=market) |  |
| `sector_analyst_breadth_pit` | 44 | 8 | 0.0 | 11 | 2026-06-01 → 2026-09-01 | yes | feature_values (entity=sector) | no reader yet |
| `sector_sentiment_breadth_pit` | 77 | 7 | 0.0 | 11 | 2026-03-31 → 2026-08-31 | yes | feature_values (entity=sector) | no reader yet |
| `pit_replay_snapshots` | 246,103 | 9 | 171.3 | 56259 | 2024-09-02 → 2026-09-27 | yes | runs + picks + pick_contributions | exact inputs per pick; replay never run automatically |
| `daily_picks` | 279,107 | 26 | 122.0 | 53140 | 2026-04-09 → 2026-09-27 | n/a | picks (+ pick_contributions) | no run id/sha; rerun = DELETE then upsert in 2 transactions; 9 *_adj cols hard-coded 0 |
| `health_score` | 213,464 | 14 | 82.9 | 53779 | 2026-04-30 → 2026-09-27 | n/a | check_results (+ picks.uhs for pick rows) | pick UHS stored twice |
| `pick_outcomes` | 346,012 | 14 | 69.2 | 36209 | 2026-04-09 → 2026-08-28 | n/a | outcomes |  |
| `daily_changes` | 164,094 | 9 | 21.8 | 35243 | 2026-05-01 → 2026-09-27 | n/a | view over picks (run vs previous run) |  |
| `portfolio_weights` | 2,210 | 10 | 0.3 | 455 | 2026-04-09 → 2026-09-27 | n/a | book_weights | no run id |
| `portfolio_outcomes` | 183 | 10 | 0.0 | 21 | 2026-04-09 → 2026-08-28 | n/a | outcomes (entity = the book) |  |
| `factor_horizon_gate` | 245 | 19 | 0.1 | — | — | n/a | factor_tests | manual; stale since 06-02 but shown |
| `pit_ic_by_tier_v2` | 339 | 13 | 0.0 | — | — | n/a | factor_tests | computed_at never updated |
| `trust_verdicts` | 300,635 | 15 | 120.1 | 68084 | 2026-05-31 → 2026-09-27 | n/a | row_issues (fails) + check_results (pass counts) | 99% pass rows; gates 6/7 never populated; pre-push hook deletes RELI rows |
| `pipeline_log` | 17,777 | 9 | 2.2 | 3757 | 2026-04-09 → 2026-09-27 | n/a | runs + step_runs | no run id; RUNNING + terminal rows pair on (step,started_at) |
| `pit_reconstruction_log` | 2,341 | 11 | 2.1 | — | — | n/a | step_runs (kind=reconstruct) | 5 orphaned RUNNING rows |
| `screener_pull_errors` | 7,768 | 7 | 1.4 | — | — | n/a | row_issues |  |
| `llm_usage` | 5,850 | 9 | 0.5 | — | — | n/a | llm_usage (+ mode column) | 8 session rows with 0 tokens (session_classify) |
| `sector_narrative_runs` | 4 | 8 | 0.0 | — | — | n/a | step_runs | LLM run log |
| `regulatory_batches` | 124 | 6 | 0.0 | — | — | n/a | step_runs | LLM batch state |
| `analyst_consensus_quarantine` | 0 | 28 | 0.0 | — | — | n/a | row_issues | mirror; 63+16 rows total across all 11; never released |
| `analyst_consensus_snapshots_quarantine` | 0 | 14 | 0.0 | — | — | n/a | row_issues | mirror; 63+16 rows total across all 11; never released |
| `annual_balance_sheet_quarantine` | 0 | 19 | 0.0 | — | — | n/a | row_issues | mirror; 63+16 rows total across all 11; never released |
| `annual_cash_flow_quarantine` | 0 | 15 | 0.0 | — | — | n/a | row_issues | mirror; 63+16 rows total across all 11; never released |
| `banking_metrics_quarantine` | 16 | 31 | 0.0 | 3 | 2026-06-01 → 2026-08-01 | n/a | row_issues | mirror; 63+16 rows total across all 11; never released |
| `broker_recommendations_quarantine` | 63 | 11 | 0.0 | 0 | 2026-05-25 → 2026-05-31 | n/a | row_issues | mirror; 63+16 rows total across all 11; never released |
| `consensus_signals_quarantine` | 0 | 10 | 0.0 | — | — | n/a | row_issues | mirror; 63+16 rows total across all 11; never released |
| `forecast_history_quarantine` | 0 | 9 | 0.0 | — | — | n/a | row_issues | mirror; 63+16 rows total across all 11; never released |
| `quarterly_income_quarantine` | 0 | 16 | 0.0 | — | — | n/a | row_issues | mirror; 63+16 rows total across all 11; never released |
| `mf_nav_history` | 8,842,351 | 4 | 975.5 | 187024 | 2026-05-03 → 2026-09-27 | yes | mf.fund_nav | 0.47 GB + 0.51 GB indexes |
| `mf_holdings` | 304,624 | 10 | 43.4 | 11956 | 2026-05-28 → 2026-09-01 | no (as_of = scrape date) | mf.fund_holdings |  |
| `mf_rolling_returns` | 228,289 | 6 | 18.3 | — | — | n/a | mf.fund_metrics |  |
| `mf_metrics` | 45,554 | 32 | 12.1 | 10273 | 2026-05-28 → 2026-09-01 | n/a | mf.fund_metrics | Nifty proxy from today's top-50 (survivorship) |
| `mf_scheme_master` | 14,673 | 21 | 5.1 | 4824 | 2026-05-26 → 2026-09-27 | n/a | mf.funds | ALTER TABLE at runtime in 2 modules |
| `mf_sector_allocation` | 56,767 | 4 | 4.6 | 1859 | 2026-05-28 → 2026-09-01 | no | mf.fund_holdings (holding_type=sector) |  |
| `mf_calendar_returns` | 40,746 | 4 | 1.9 | — | — | n/a | mf.fund_metrics |  |
| `mf_schemes` | 5,206 | 12 | 1.0 | 0 | 2026-05-03 → 2026-05-26 | n/a | mf.funds (fold its 2 useful cols in) |  |
| `mf_category_stats` | 498 | 10 | 0.1 | 95 | 2026-05-26 → 2026-09-01 | n/a | mf.fund_metrics (entity = category) |  |
| `mf_holdings_quarantine` | 0 | 13 | 0.0 | — | — | n/a | mf.row_issues | mirror; never written |
| `mf_sector_allocation_quarantine` | 0 | 7 | 0.0 | — | — | n/a | mf.row_issues | mirror; never written |
| `signal_lineage` | 230,220 | 8 | 80.7 | 36433 | 2026-05-25 → 2026-09-27 | n/a | DESIGN QUESTION — retire (recommended) or documents(type lineage) | only 2 of ~105 factors emit it; feeds UHS gate 6 |
| `external_anchors` | 522,729 | 7 | 82.6 | 131558 | 2026-05-30 → 2026-09-26 | n/a | DELETE (gate 7 → check over bars_daily sources) | copy of stock_prices; gate 7 can never fire |
| `uhs_calibration_log` | 209,741 | 9 | 28.6 | 36209 | 2026-05-30 → 2026-08-28 | n/a | DELETE → view over outcomes ⋈ picks | rewrites ~210K rows nightly; no reader |
| `vix_history` | 2,760 | 2 | 0.2 | 21 | 2015-06-25 → 2026-09-25 | yes | series_values (india_vix) — DELETE the copy | pure copy of macro_history india_vix |
| `sector_policy_pit` | 836 | 4 | 0.1 | 11 | 2020-05-31 → 2026-08-31 | NO (hindsight-curated) | DELETE | no reader; built from a list curated 2026-06 |
| `event_calendar` | 354 | 7 | 0.0 | — | — | n/a | DELETE | hand-loaded 2026-07-11; no scheduled writer, no reader |
| `pit_ic_by_tier_v1` | 30 | 13 | 0.0 | — | — | n/a | DELETE | no value reader; same evidence in v2 source='v1_archive' |
| `paper_positions` | 65 | 13 | 0.0 | — | — | n/a | DELETE | only writer is _archive/paper_portfolio.py; no reader |
| `paper_trades` | 115 | 13 | 0.0 | 3 | 2026-05-04 → 2026-06-29 | n/a | DELETE | same |
| `paper_nav_history` | 45 | 10 | 0.0 | — | — | n/a | DELETE | same |

## Appendix A — prices, company facts, events


Conventions. `insert_df` = `INSERT OR IGNORE` (db.py:341-357, drops rows dated > today+2d). `upsert_df` = `INSERT … ON CONFLICT(pk) DO UPDATE` of the supplied columns only (db.py:582-640). FKs are enforced on every write connection (db.py:84 `PRAGMA foreign_keys=ON`). "morning" = cron `run.sh morning` 03:30 UTC → `pipeline.py` (config.PIPELINE_STEPS). "forward" = cron `run.sh forward` 14:00 UTC (run.sh:48-53). Ranking path = the screener (scoring/screener.py). It reads `stocks` and `universe_eligibility` directly, and takes every factor from `pit.features_at` (screener.py:109-116). Those producers read these tables: annual_balance_sheet, annual_cash_flow, bse_announcements, bulk_deals, corporate_adjustments, fno_iv_history, forecast_history, macro_history, macro_sector_signals_pit, quarterly_income, shareholding, stock_prices, stocks (computed via `pit.producers_for` + `factors.producer_tables`). PIT lag constants: pit.py:29-31 (ANNUAL 75d, QUARTERLY 60d, SHAREHOLDING 21d). Registry-only mentions (tables.py, lineage.py, factors.py source_columns, health.py TABLE_PROFILES, checks/ranges.py, cockpit_ops/api.py:~1396-1473 inventory lists) are metadata, not readers, and are not repeated below.

---
#### Universe & Prices

##### fno_bhav
1. NSE F&O end-of-day contract grid: one row per contract per day (options and futures).
2. Grain: (symbol, instrument_type, expiry, strike, option_type, trade_date). No PK. `UNIQUE(symbol,instrument_type,expiry_date,strike,option_type,trade_date)`. `sid` is NULL for index underlyings.
3. `insert_df` (OR IGNORE) at sources/fno_pull.py:125 (`pull_fno_bhav`). Step `fetch_fno_bhav` in the morning run (config.py:298). Manual backfill with `--backfill` (fno_pull.py:145).
4. Readers:
   - Producers: fno_pull.py:271 (the PCR rollup) and sources/fno_iv.py:217,249 (the IV inversion).
   - Tools: sources/kite_pull.py:182, a manual pull of F&O names.
   - Ranking path: no direct read; it reaches ranking only through fno_iv_history.
5. Time columns:
   - `trade_date` is the session date (end of day).
   - `fetched_at` is the insert time.
   - PIT-safe: yes. End-of-day data, first-write-wins, never overwritten.
6. TEXT columns: symbol, instrument_type, option_type (identifiers only).
7. Target: **Bars (derivative_bars)**.
8. The dedup key is `symbol`, not `sid`. Sid mapping is done at write time from `stocks.ticker`.

##### fno_iv_history
1. Implied-volatility surface summary (Black-76 inversion of fno_bhav settle prices): one row per underlying per day.
2. Grain: (symbol, trade_date). No PK. `UNIQUE(symbol, trade_date)`.
3. `INSERT OR REPLACE` at sources/fno_iv.py:240. Step `compute_fno_iv` in the morning run (config.py:306). There is a single producer, so OR REPLACE is safe here.
4. Readers:
   - **Ranking path: yes.** pit.py:1500 `RAW_SQL["fno_iv"]` feeds the `fno_iv` producer, and `iv_skew_25d` is **WIRED** with MID weight 0.26.
   - Live signal: signals/fno_iv_factors.py:78.
   - Confidence score: scoring/health_score.py:97,635 (UHS).
5. Time columns:
   - `trade_date` is the as-of date.
   - `computed_at` is the write time.
   - PIT-safe: yes (derived from end-of-day data).
6. No TEXT columns beyond keys.
7. Target: **Features** (a derived per-sid daily value). Alternatively a Series if the index rows (NULL sid) are kept.
8. Index rows carry `sid=NULL` and are dropped by every reader.

##### fno_pcr_history
1. Per-underlying daily rollup of the nearest expiry: put/call ratio on open interest and volume, plus max-pain.
2. Grain: (symbol, trade_date). `UNIQUE(symbol, trade_date)`.
3. `INSERT OR REPLACE` at sources/fno_pull.py:295. Step `compute_fno_pcr` in the morning run (config.py:302).
4. Readers:
   - Backtest: pit.py:1499 (the `fno_oi` producer, which is **not wired**).
   - signals/fno_oi_factors.py:84 (library code; no pipeline step).
   - Ranking path: no.
5. Time columns: `trade_date` and `computed_at`. PIT-safe: yes.
6. No TEXT columns.
7. Target: **Features**.
8. Nothing live reads it; it exists only for the backtest.

##### nse_index_history
1. Daily OHLCV for NSE indices (NIFTY 50/100/500, SMALLCAP 250, smart-beta indices).
2. Grain: (index_symbol, trade_date). PK `(index_symbol, trade_date)`.
3. `insert_df` at sources/nselib_pull.py:530. Step `fetch_nse_indices` in the morning run (config.py:669). A 120-month backfill is manual.
4. Readers:
   - Outcomes: tools/compute_pick_outcomes.py:67 (benchmark; `portfolio_outcomes` imports the same helpers).
   - Multibagger watchlist: scoring/regime_smallcap.py:50, reached via signals/multibagger.py:48,330.
   - Cockpit: cockpit/api.py:1451 (the multibagger "REVIEW" guard) and :2401.
   - Research: tools/multibagger_cohort.py.
   - Ranking path: no.
5. Time columns: `trade_date` is the event date; `fetched_at` is the write time. PIT-safe: yes.
6. TEXT columns: `index_symbol` only.
7. Target: **Bars (bars_daily)**, with indices as securities in the Reference layer. Alternatively a Series.
8. Overlaps macro_history (for example `nifty50`). Two index price stores exist.

##### regime_state
1. Current VIX regime label plus per-tier allocation weights, in a single row.
2. Grain: one row. PK `id INTEGER CHECK(id=1)`.
3. `INSERT OR REPLACE … VALUES (1, …)` at scoring/regime.py:85. Step `regime_update` in the morning run (config.py:632).
4. Readers:
   - Surface helper: views.py:314 `regime()`.
   - Email: output/email_sender.py:346.
   - Cockpit: cockpit/api.py:659-662, cockpit/app.py:132, and templates morning_brief.html:19-20, model.html:50-51,126-127 and portfolio.html:260.
   - Self-read for hysteresis: regime.py:64.
   - **Ranking path: no.** portfolio_construction.py never reads `alloc_*`; the allocation is display-only.
5. Time columns: `updated_at` only. **Overwritten in place; no history.** PIT-safe: no.
6. TEXT columns: `regime` (a label).
7. Target: **Decisions** (a regime label and allocations recorded per run on `runs`). Alternatively a Series `regime_label`.
8. Docstring drift: output/diff_engine.py:15 says it reads regime_state, but the code reads `vix_history` (diff_engine.py:214) and recomputes the regime itself.

##### scrip_master
1. Crosswalk from BSE scrip_cd to ISIN, NSE symbol and universe sid (from the Upstox instrument master plus a delisted supplement).
2. Grain: one BSE scrip. PK `scrip_cd`.
3. `INSERT OR REPLACE` full rebuild at sources/scrip_master.py:157. Cron: forward, via `python -m sources.scrip_master` (run.sh:53). The same module also runs `UPDATE bse_announcements SET sid=…` (scrip_master.py:170-175).
4. Readers:
   - scrip_master.py:172-175 (the backfill of bse_announcements.sid).
   - tools/sid_crosswalk.py:38, used by tools/build_event_calendar.py.
   - Ranking path: indirect only. It supplies bse_announcements.sid, which the ranking uses.
5. Time columns: `updated_at` is set to now on every run. Overwritten in place, so there is no history of mappings or symbol changes. PIT-safe: no, but this is identity data.
6. TEXT columns: isin, nse_symbol, name, status, source.
7. Target: **Reference (security_links)**, with ISIN as the bridge key.
8. `stocks` itself has no ISIN (scrip_master.py:7-10), so this table is the only ISIN store.

##### stock_prices
1. Daily raw (unadjusted) NSE bhavcopy OHLCV plus delivery quantity, per stock.
2. Grain: (sid, date). PK `(sid, date)`. FK to stocks.
3. Writers:
   - `insert_df` at sources/nse.py:207, step `fetch_bhavcopy` (critical).
   - `insert_df` at sources/yfinance_prices.py:131, step `fetch_prices_fallback` (fills gaps for BSE-only listings, InvITs and REITs, source=`yfinance.*`).
   - tools/regression_fixtures.py:192,204,226 **write to the live DB**: INSERT then DELETE of a synthetic RELI 1999-01-15 row. This runs from `.git/hooks/pre-push:20`.
4. Readers (about 70 files):
   - **Ranking path: yes.** pit.py:1483 `prices` and :1501 `prices_ohlc`, screener, scoring/segment.py:77 (market cap for tiering), tools/classify_micro_tier.py:51, and portfolio_construction.py:91-115.
   - Signals: every price signal (signals/_prices.py:68, momentum, low_vol, delivery_anomaly, sector_*, smart_money:67, consensus:77, …).
   - Cockpit: cockpit/api.py:47,910,1401, views.py:259-300, templates model_outcomes.html:65 and mf_detail.html:301.
   - Outcomes and quality: compute_pick_outcomes.py:56,133, anchor_audit.py:59-157, validators/cross_source.py:92,226.
   - Tools: ic_decay, event_study, rebalance_sim and others.
5. Time columns:
   - `date` is the session date. There is no fetched_at or available_at.
   - PIT-safe: yes. Rows are write-once (OR IGNORE).
   - Adjustments are applied at read time from `corporate_adjustments` (pit.py:1397).
6. TEXT columns: `source` (a label).
7. Target: **Bars (bars_daily)**.
8. Surprises:
   - The pre-push hook's fixture also runs `DELETE FROM trust_verdicts WHERE sid='RELI'` (regression_fixtures.py:191,225), which wipes RELI's real trust verdicts on every push.
   - The fallback writes first-wins, so a yfinance row can never be superseded by a later bhavcopy row.

##### stocks  (hub — 52 FKs point here, counted via pragma_foreign_key_list)
1. The universe master: identity, classification, tier, and a set of fundamentals seeded once in April.
2. Grain: one security. PK `sid`. 2,448 rows (LARGE 100, MID 150, SMALL 1,629, MICRO 569).
3. There is **no INSERT path anywhere in the code**; every row has `created_at` = 2026-04-09 18:19:36 (seeded once). Because FKs are enforced and nothing deletes, the universe can never add a listing or drop a delisting. Per-column writers:

   | column(s) | writer | trigger | live state |
   |---|---|---|---|
   | sid, ticker, name, created_at | none (seed) | none | 2,448 filled |
   | sector | tools/classify_industries.py:248 `UPDATE … SET industry=?, sector=?` (only with sync_sector) | manual tool | 2,448 filled |
   | industry | tools/classify_industries.py:248,255 | manual tool | 2,444 filled |
   | cap_tier | scoring/segment.py:172 (LARGE/MID/SMALL, ±10% hysteresis) **and** tools/classify_micro_tier.py:101,107 (MICRO ↔ SMALL) | step `segment_tiers` (monthly), step `classify_micro_tier` (daily) | overwritten in place, no history |
   | market_cap_cr | none (seed); **stored in RUPEES, not crores** (signals/fcf_yield.py:40, RELI = 1.83e13) | none | 1,722 filled, frozen at 04-09 |
   | adtv_6m_cr | none (seed) | none | 1,942 filled, frozen |
   | in_nifty500 | none (seed) | none | 500 set; read only by kite_pull.py:185 |
   | slug (Tickertape) | none (seed) | none | 2,439 filled; read by tickertape_analyst.py:185, checks/custom.py:726-777 |
   | pe_ratio, pb_ratio, roe, debt_to_equity, dividend_yield, revenue_growth, profit_margin, free_cashflow, beta, fifty_two_week_high, fifty_two_week_low, avg_volume | **none** | none | **all NULL in every row**, yet health.py:653 still lists 4 of them as outlier_columns |
   | mc_slug | sources/moneycontrol_recos.py:200,206 | step `fetch_broker_recos` (daily) | 2,230 filled |
   | mc_checked_at | sources/moneycontrol_recos.py:496 | same step | 197 filled |
   | updated_at | sources/universe.py:49 (a liveness bump for stocks that traded in the last 7 days) | step `universe_liveness` | freshness anchor (tables.py) |

4. Readers: nearly every module (about 150 files).
   - **Ranking path:**
     - screener.py:57-63 (universe, tier, sector).
     - pit.py:1478 `RAW_SQL["stocks"]` (cap_tier, sector, industry, market_cap_cr for every PIT date).
     - eligibility/registry.py:26 (UNIVERSE_SQL).
     - segment and micro-tier.
   - Cockpit: api.py, pages.py, app.py, templates explorer/model/sectors/portfolio/morning_brief/…
   - Email: email_sender.py:177.
   - Dossiers: dossier and sector_dossier.
   - Every source that maps symbol to sid.
5. Time columns: created_at (the seed), updated_at (the liveness bump), mc_checked_at. **Not PIT-safe:**
   - The backtest uses today's `cap_tier`, `sector` and `market_cap_cr` for every historical date (pit.py:1409 `base = raw["stocks"][["sid","cap_tier"]]`), so tier membership and sector are look-ahead and survivorship-biased.
   - Tiers are overwritten in place, so there is no tier history.
6. TEXT columns: ticker, name, sector, industry, cap_tier, slug, mc_slug.
7. Target: **Reference**, split three ways:
   - `securities`: sid, ticker, name, ISIN taken from scrip_master.
   - `security_tiers`: a dated cap_tier history.
   - `security_links`: slug, mc_slug, scrip_cd.
   - The 12 dead fundamentals columns, plus market_cap_cr and adtv_6m_cr, should be **dropped** (derive them from Bars × Fundamentals).
8. Surprises:
   - **Live tiering bug:** tools/classify_micro_tier.py:62-73 compares `stocks.market_cap_cr` (in rupees) against `MCAP_LIMIT_CR=500` (crores). The mcap leg fires only for NULL-mcap stocks. The same query prefers the frozen April `adtv_6m_cr` over the live 90-day ADTV (`COALESCE(st.adtv_6m_cr, p.adtv_cr_90d, 0)`). MICRO is excluded from picks, so both bugs affect ranking.
   - signals/share_momentum.py:46-48 and fcf_yield.py:51-53 filter `market_cap_cr >= 200` on rupee values (always true).
   - `cap_tier` has two writers with different cadences.

##### universe_eligibility
1. Per-signal eligibility flag: whether a sid should have a score for that signal. It drives the eligible_coverage renormalization.
2. Grain: (sid, signal, snapshot_date). PK the same. About 22,032 rows per day (2,448 sids × 9 signals); 128 dates since 2026-05-23.
3. `INSERT … ON CONFLICT DO UPDATE` at tools/refresh_eligibility.py:86. Step `refresh_eligibility` in the morning run (config.py:625). Append-only by date.
4. Readers:
   - **Ranking path: yes.** screener.py:39-41 reads the latest snapshot ≤ as_of.
   - scoring/health_score.py:324-339.
   - checks/custom.py:602-615.
   - Backtest: not read (pit.py has no reference).
5. Time columns:
   - `snapshot_date` is the as-of date.
   - `refreshed_at` is the write time.
   - PIT-safe: yes for dates ≥ 2026-05-23. It is not reproducible from history, because `eligible_sql` runs against the current tables (factors.SIGNAL_ELIGIBILITY).
6. TEXT columns: `signal` (a label).
7. Target: **DESIGN QUESTION.** This is a boolean mask derived from current data coverage. Two options:
   - Store it as a run-scoped Decisions input (e.g. `run_inputs`, or on pick_contributions).
   - Compute it on the fly per run.
   - A daily row per (sid, signal) is about 2.8M rows of 0/1, and mostly 1s.
8. It grows about 22K rows per day forever, and nothing ever prunes it.

##### vix_history
1. India VIX daily close.
2. Grain: date. PK `date`.
3. `upsert_df` at sources/macro_yfinance.py:204 `_sync_vix_history`. It copies `macro_history WHERE indicator_id='india_vix'`. Step `fetch_macro_market` in the morning run (config.py:234 `writes`).
4. Readers:
   - scoring/regime.py:43 (feeds regime_state).
   - output/diff_engine.py:214.
   - Ranking path: no.
5. Time columns: `date` only. PIT-safe: yes.
6. No TEXT columns.
7. Target: **Series**. **Drop this table**: it is a redundant mirror of macro_history `india_vix` (macro_yfinance.py:181-204). Point the two readers at the Series.
8. It is a pure duplicate that exists only for "contract" reasons (macro_yfinance.py:182).

---
#### Fundamentals

##### analyst_consensus
1. Latest analyst aggregate per stock: price target, analyst count, buy %, forward EPS and revenue, rating mix.
2. Grain: one stock (the latest state). PK `sid`.
3. `upsert_df` from **three producers**, co-owning columns:
   - sources/yfinance_analyst.py:346-388: price_target, the median/high/low PTs, total_analysts, recommendation_*, n_*, pt_source, next_earnings_date, rating_mix_history, price_target_prev and changed_at, has_analyst_data, fetched_at.
     - Runs as step `fetch_yf_analyst` (**weekly**, config.py:865) and as cron `pt_snapshot` on the 1st of the month.
     - It also `UPDATE … SET price_target=NULL…` in the plausibility sweep (yfinance_analyst.py:220).
   - sources/tickertape_analyst.py:210-219: total_analysts, buy_pct, forward_eps, eps_growth_pct, forward_revenue, revenue_growth_pct, has_analyst_data, fetched_at. Step `fetch_analyst` (monthly).
   - sources/moneycontrol_recos.py:347-351 `aggregate_consensus`: **total_analysts, buy_pct, price_target**, has_analyst_data, fetched_at, rebuilt from broker_recommendations. Step `fetch_broker_recos` (**daily**, moneycontrol_recos.py:486).
4. Readers:
   - signals/consensus.py:66-247 writes consensus_signals. The screener carries its `pt_upside` for display only, **unweighted** (screener.py:121-125).
   - scoring/health_score.py:67,87 (UHS).
   - cockpit/api.py:69-87 and stock_detail.html:619,627.
   - output/dossier.py:421 (the LLM dossier).
   - sources/transcripts_pull.py:402.
   - checks/custom.py and validators/cross_source.py:71.
   - **Ranking path: no.** Consensus eligibility uses forecast_history, not this table.
5. Time columns:
   - fetched_at (last writer).
   - price_target_changed_at (self-computed).
   - next_earnings_date (future event).
   - **Overwritten in place.** PIT-safe: no.
6. TEXT/JSON columns:
   - `rating_mix_history` holds JSON arrays (for example `[["-3m",5,25,0,0,1],…]`).
   - recommendation_key, pt_source.
7. Target: **Estimates (versioned)**, with one row per (sid, source, observed_at). The "latest" row becomes a view.
8. **Contradiction with CLAUDE.md and the docstrings.** Both CLAUDE.md and tickertape_analyst.py:88-91 say "yfinance is the sole writer of price_target". In fact the Moneycontrol aggregate overwrites `price_target`, `total_analysts` and `buy_pct` daily, while `pt_source` stays `yfinance`. Live evidence: RELI has total_analysts=2, price_target=1726.5 (a 2-decimal mean of Moneycontrol brokers), price_target_median=1690 (from yfinance), pt_source=yfinance, fetched_at 06:59 today. So the cockpit "current PT", the dossier and consensus_signals mix sources silently.

##### analyst_consensus_snapshots
1. Monthly snapshot of the yfinance PT aggregate: the only honest PT history (ADR 0045).
2. Grain: (sid, snapshot_date, source). PK the same. About 900 rows per month; 5 months so far.
3. `upsert_df` at sources/yfinance_analyst.py:369,388, only with `--snapshot`. Cron `pt_snapshot`, 1st of month 04:30 UTC (run.sh:57).
4. Readers:
   - Backtest: pit.py:1486 `acs` (the `pt_upside` producer, **pulled and not wired**).
   - signals/sector_breadth.py:42-52 (step `sector_analyst_breadth`, monthly).
   - checks/custom.py:132-138.
   - Ranking path: no.
5. Time columns:
   - `snapshot_date` = the 1st business day of the **current** month (yfinance_analyst.py:52-58), whatever the fetch date.
   - `fetched_at` = the actual observation time.
   - PIT-safe: mostly. **Backdated rows exist:** 2026-05-01 was fetched 05-22 and 2026-06-01 was fetched 06-03. A mid-month re-run overwrites the month's row with later data.
6. TEXT columns: recommendation_key, source.
7. Target: **Estimates (versioned)**, keyed on observed_at = fetched_at.
8. Use `fetched_at` as `available_at`, not snapshot_date.

##### annual_balance_sheet
1. Annual balance sheet from Tickertape (Bharat_sm_data).
2. Grain: (sid, period). PK `(sid, period)`. `period` is a label such as 'FY 2016'.
3. `upsert_df` at sources/tickertape.py:85, via `_harvest(…,"annual_balance_sheet")` at :211. Cron `run.sh tickertape`, 1st of month 19:07 (run.sh:73-80). Seeded 2026-04-09 from v1.
4. Readers:
   - **Ranking path: yes.** pit.py:1480 `bs` feeds piotroski (WIRED MID .18/SMALL .06), accruals (WIRED MID .22), book_to_price (WIRED) and forensic. Also scoring/segment.py:91 (the share-count fallback for tiering) and eligibility.
   - Live signals: accruals.py:61, asset_growth.py:56, book_to_price.py:52, forensic.py:94, piotroski.py:60.
   - Cockpit: cockpit/api.py:990,1114.
   - health_score.py:91 and validators/per_stock_integrity.py:197.
5. Time columns:
   - `end_date` is the fiscal period end.
   - `fetched_at` is the last write.
   - **Restatements overwrite in place.**
   - PIT: lag rule only (end_date + 75d, pit.py:70). No filing date is stored.
6. TEXT columns: `period` (a label).
7. Target: **Fundamentals (versioned, long)**, with columns sid, period_end, basis, line_item, value, source, available_at.
8. It is a narrow-typed duplicate of line items that fundamentals_screener also holds (from a different vendor).

##### annual_cash_flow
1. Annual cash-flow statement from Tickertape.
2. Grain: (sid, period). PK `(sid, period)`.
3. `upsert_df` at sources/tickertape.py:85, via :251. Cron `run.sh tickertape` (monthly).
4. Readers:
   - **Ranking path: yes.** pit.py:1481 `cf` feeds piotroski and accruals (both WIRED) and forensic.
   - signals/accruals.py:66, forensic.py:99, piotroski.py:67, managerial_ability.py:134.
   - cockpit/api.py:996.
   - health_score.py:92.
5. Time columns: end_date and fetched_at. Overwritten in place. PIT: lag rule only (75d).
6. TEXT columns: `period`.
7. Target: **Fundamentals (versioned, long)**.
8. None.

##### banking_metrics
1. Bank and NBFC metrics scraped from Screener.in: NII, NPA, CASA, CAR and so on.
2. Grain: (sid, period_end, period_type). PK the same.
3. `upsert_df` at sources/banking_metrics.py:477. Step `fetch_banking_metrics` (monthly, config.py:883).
4. Readers:
   - signals/financial_signal.py:101-191 (step `compute_financial_signal` → financial_signal_scores, **display-only per ADR 0048**).
   - Backtest: pit.py:1498 `banking_metrics` (financial_signal producer).
   - health_score.py:93.
   - validators/plausibility.py:48-54.
   - Ranking path: no.
5. Time columns:
   - period_end is the fiscal period end.
   - fetched_at is the last write.
   - Overwritten in place.
   - PIT: lag rule only (60/75d, financial_signal.py:97-135).
6. TEXT columns: period_type, source.
7. Target: **Fundamentals (versioned, long)**, sector-specific line items with no separate table.
8. Many columns are all-NULL in the sampled rows (pcr/slippage/casa/car/nim/… for HDBK); only about 9 of 23 metrics populate. config.py:887 lists `reads: broker_recommendations` for this step; unverified that the code actually reads it.

##### broker_recommendations
1. Individual sell-side broker calls scraped from Moneycontrol: broker, date, rating, target, PDF link.
2. Grain: (sid, broker, reco_date, target_price). PK the same. About 11.4K rows, 2024-11 → 2026-09.
3. `upsert_df` at sources/moneycontrol_recos.py:464,472. Step `fetch_broker_recos` (daily, with a host budget).
4. Readers:
   - moneycontrol_recos.py:318 `aggregate_consensus`, which writes analyst_consensus.
   - scoring/health_score.py:185.
   - validators/cross_source.py:77.
   - tools/trust_backfill.py:305.
   - Ranking path: no.
5. Time columns:
   - reco_date is the publication event.
   - fetched_at is the last write.
   - PIT-safe: yes, if reco_date is true. **But reco_date falls back to TODAY when it is missing** (moneycontrol_recos.py:301), which fabricates an event date.
6. TEXT columns: broker, reco_type, report_url.
7. Target: **Estimates (versioned)**, one row per broker call. Alternatively **Events** (type=broker_call, payload).
8. Having target_price in the PK means a revised target on the same date adds a row rather than a revision.

##### forecast_history
1. Tickertape `forecastsHistory` series per stock and metric: eps and revenue by fiscal year, plus the dead `price` rows.
2. Grain: (sid, metric, date). PK the same. Long format.
3. `upsert_df` at sources/tickertape_analyst.py:210-219. Step `fetch_analyst` (monthly). `price` has not been written since 2026-09-26 (commit 8700769), but **the old price rows are still in the table** (for example RELI price 2022-12-28…2025-12-27, fetched 2026-09-01).
4. Readers:
   - **Ranking path: yes.** pit.py:1485 `fh` (eps only) feeds the consensus producer → `eps_revision_yoy`, i.e. **consensus_signal_combined WIRED LARGE .28 / SMALL .16**.
   - eligibility `consensus`.
   - signals/eps_revision.py:74.
   - signals/consensus.py:71.
   - cockpit/api.py:1054 and stock_detail.html:442.
   - validators/cross_source.py:61-168.
   - checks/custom.py:77-127.
5. Time columns:
   - `date` is the **fiscal-period date** (for example 2026-03-31), not the observation date.
   - `fetched_at` is the last write.
   - Values are **overwritten in place on every monthly fetch**.
   - **PIT: NO.** pit.py:1366 filters `date <= eval_date` on the period date, so a backtest at date D sees the value as of the latest fetch. This is the same float-then-freeze upstream that contaminated `price` (memory `forecast_history_price_contaminated`). The magnitude for eps is **unverified**.
6. TEXT columns: `metric` (a label).
7. Target: **Estimates (versioned)**, columns sid, metric, fiscal_period, value, observed_at/available_at. Delete the `price` rows.
8. There is a real risk that the wired eps_revision_yoy carries look-ahead. The factor also measures fiscal-year-over-year EPS change, not a revision (eps_revision.py:33-55).

##### fundamentals_screener
1. Screener.in financial statements in long format: annual and quarterly line items (about 60 per period).
2. Grain: (sid, period_end, period_type, line_item). PK the same.
3. Writers:
   - `upsert_df` at sources/screener_pull.py:425. Cron `screener_universe` on the 1st and 15th (run.sh:70-72).
   - `upsert_df` at sources/screener_schedules.py:208 (sub-schedules). **No cron or step invokes it; manual only.**
4. Readers:
   - **Ranking path: yes.** scoring/segment.py:84 ('No. of Equity Shares' → market cap → tiers).
   - Backtest and library: pit.py:1497 `fund_screener` (about 25 non-wired factors), signals/_annual.py:40, and 25 `signals/*` weekly steps (roic, fcf_yield, …).
   - signals/multibagger.py:144.
   - sources/banking_metrics.py:328.
   - cockpit_ops/api.py:1417-1704.
5. Time columns:
   - period_end is the fiscal end.
   - `filing_date` is **never populated** (no non-null row found).
   - fetched_at is the last write.
   - Overwritten in place.
   - PIT: lag rule only (75d for annual, pit.py:80).
6. TEXT columns: period_type, line_item (a label). Values are all numeric.
7. Target: **Fundamentals (versioned, long)**. It is already the right shape; add `source`, `basis` and `available_at`.
8. Two writers share one PK namespace: screener_schedules can overwrite parent line items with the same name (unverified whether names collide).

##### quarterly_income
1. Quarterly income statement from Tickertape.
2. Grain: (sid, period, reporting). PK the same. `reporting` is consolidated or standalone; both exist (for example AADM standalone).
3. `upsert_df` at sources/tickertape.py:85, via :153. Cron `run.sh tickertape` (monthly).
4. Readers:
   - **Ranking path: yes.** pit.py:1479 `qi` (piotroski, accruals, earnings_yield, forensic).
   - scoring/screener.py:98-99 (a quarters_present count) and :278,294.
   - tools/classify_micro_tier.py:58 (the MICRO data gate).
   - Eligibility for earnings_yield.
   - Signals: earnings_yield.py:69, pead.py:123, piotroski.py:45.
   - cockpit/api.py:922-1030.
   - output/snapshot.py.
5. Time columns: end_date and fetched_at. Overwritten in place. PIT: lag rule only (60d).
6. TEXT columns: period, reporting.
7. Target: **Fundamentals (versioned, long)**, with `basis` taken from `reporting`.
8. The consolidated/standalone choice lives in the PK but not in pit.py:1479, which loads both (the dedup logic is inside the compute functions; unverified).

##### shareholding
1. Quarterly shareholding pattern: promoter, FII, MF, DII, public, pledge, insurance, retail.
2. Grain: (sid, end_date). PK the same.
3. `upsert_df` at sources/tickertape_shareholding.py:134. Step `fetch_shareholding` (monthly).
4. Readers:
   - **Ranking path: yes.** pit.py:1482 `sh` feeds promoter and pledge (**pledge_quality WIRED SMALL .10**); also eligibility `promoter`.
   - signals/promoter.py:64.
   - signals/multibagger.py:134.
   - cockpit/api.py:161,591,604, app.py:209,528 and stock_detail.html:952-1680.
   - health_score.py:94.
5. Time columns:
   - end_date is the quarter end. Odd dates exist (for example RELI 2024-10-31).
   - fetched_at is the last write; each row is rewritten on each fetch.
   - PIT: lag rule only (21d, pit.py:75).
6. No TEXT columns.
7. Target: **Ownership** (holder_class × pct per as-of date, long).
8. None beyond the in-place overwrite.

---
#### Trades & Corporate

##### bse_announcements  (≈1.77 GB, ≈2.6M rows)
1. BSE corporate-disclosure firehose (results, board meetings, resignations, credit ratings, …), back to 2018, including delisted companies.
2. Grain: one BSE announcement. PK `news_id` (a TEXT UUID).
3. Writers:
   - `INSERT OR IGNORE` at sources/bse_announcements.py:107 `_store`. Cron forward, `--days 7` (run.sh:52).
   - `UPDATE … SET sid` at sources/scrip_master.py:170-175, which backfills NULL sid right after.
4. Readers:
   - **Ranking path: yes.** pit.py:1503 `bse_results` feeds announcement_car (**WIRED LARGE .35 / SMALL .14**); pit.py:1514 `_bse_gov_sql` feeds governance (**WIRED MID -.14**); eligibility `announcement_car`.
   - signals/announcement_car.py:51, governance_events.py:68,81, pead.py:139.
   - scoring/health_score.py:98.
   - sources/transcripts_pull.py:139-208 (finds transcript filings).
   - tools/build_event_calendar.py:52, event_study.py:120, sid_crosswalk.py:42-60.
5. Time columns:
   - `dt_tm` is the announcement time.
   - `submission_dt` is the filing time.
   - `dissem_dt` is the public dissemination time, the true available_at.
   - `time_diff` is the latency (TEXT 'HH:MM:SS').
   - `fetched_at` is the first seen (OR IGNORE).
   - PIT-safe: yes, on date(dt_tm).
   - `sid` is mutated later by the backfill (identity only).
6. TEXT columns. LENGTH() sampled on 20 rows at offset 500k and averaged over the latest 2,000 rows:

   | column | typical length |
   |---|---|
   | headline | avg 100, max 206 |
   | news_sub | avg 91, max 324; repeats company, scrip and headline |
   | nsurl | avg 82; derivable from scrip slug |
   | attachment | 40 (PDF GUID) |
   | news_id | 36 (UUID) |
   | company_name | about 23 (redundant with scrip_master.name) |
   | dt_tm / dissem_dt | about 22 each |
   | submission_dt, fetched_at | about 19 each |
   | category, subcategory | about 6-68 (repeated labels) |
   | time_diff | 8 |
   | announcement_type | 1 |
   | quarter_id | usually NULL |

   **No single large text column.** The 1.77 GB is about 500 B/row of repeated short strings, plus 4 indexes, two of them TEXT-keyed (the news_id autoindex and (category, subcategory)) × 2.6M rows.
7. Target: **Events**. Columns: type = category/subcategory, sid, event_time = dt_tm, available_at = dissem_dt, source = bse, payload JSON = {headline, attachment, critical, pdf/ppt/av flags, quarter_id}.
   - Drop nsurl, company_name and the news_sub duplication.
   - scrip_cd becomes a security_links key.
8. The raw `sid` covers about 53% of rows (sid_crosswalk.py:3-4; research 0003), because non-universe scrips stay NULL.

##### bulk_deals
1. NSE bulk and block deals (client, side, quantity, price).
2. Grain: one deal. PK `id AUTOINCREMENT`. `UNIQUE(symbol, client_name, deal_date, quantity)`.
3. Writers (all `insert_df`, OR IGNORE):
   - sources/nse_bulk.py:133, step `fetch_bulk_deals` (daily).
   - sources/nse_bulk.py:182 (local CSV import).
   - sources/nselib_pull.py:151 (manual `--source bulk` backfill).
4. Readers:
   - **Ranking path: yes.** pit.py:1487 `bulk` (the smart_money producer runs in the screener but is UNWEIGHTED; also eligibility `smart_money`).
   - signals/smart_money.py:63.
   - cockpit/api.py:215, app.py:213 and stock_detail.html:1050-1065.
5. Time columns: deal_date (event, published the same evening) and fetched_at. PIT-safe: yes.
6. TEXT columns: symbol, client_name, deal_type, buy_sell.
7. Target: **Events** (type=bulk_deal/block_deal, payload {client, side, qty, price}). Alternatively Ownership flows.
8. The UNIQUE key omits buy_sell, price and deal_type: a same-client, same-quantity buy and sell on one day, or bulk and block legs, collapse into one row.

##### corporate_actions
1. NSE corporate actions (dividend, split, bonus, rights, buyback) with the raw subject text.
2. Grain: one action. PK `id AUTOINCREMENT`. `UNIQUE(symbol, ex_date, subject)`.
3. `insert_df` at sources/nselib_pull.py:219. Step `fetch_corp_actions` (daily, months=2, config.py:272). Monthly `--months 24` backfill is manual.
4. Readers:
   - tools/compute_corporate_adjustments.py:123 (daily step → corporate_adjustments, which is in the ranking path).
   - Backtest: pit.py:1502 `corp_actions` (pead, not wired).
   - Cockpit: cockpit/api.py:1413. The multibagger REVIEW view **re-parses split/bonus itself** instead of reading corporate_adjustments.
   - validators/temporal_continuity.py:50,158.
   - tools/build_event_calendar.py:68, multibagger_cohort.py:110, multibagger_monitor.py:49.
5. Time columns:
   - ex_date is the event date (announced in advance).
   - fetched_at is the first seen.
   - No announce date is stored.
   - PIT-safe: yes for ex_date ≤ D; you cannot ask "known by D".
6. TEXT columns: ind (a label), `subject` (free text parsed by regex downstream), series.
7. Target: **Events** (type=corp_action/<ind>, payload {subject, face_value}).
8. None.

##### corporate_adjustments
1. Derived per-(sid, ex_date) price-adjustment factor for split, bonus and dividend.
2. Grain: (sid, ex_date). PK the same.
3. **DELETE + upsert_df full rebuild** in one transaction at tools/compute_corporate_adjustments.py:208-211. Step `compute_corporate_adjustments` (daily since 2026-09-27; before that hand-run and frozen since 04-30, per config.py:276-277).
4. Readers:
   - **Ranking path: yes.** pit.py:1484 `adjustments` applies to every price factor (pit.py:1397). Also scoring/segment.py:96 (splits/bonuses in market cap).
   - signals/_prices.py:71 and share_momentum.py:19.
5. Time columns:
   - ex_date: PIT-safe, because it is applied only when ex_date ≤ D.
   - fetched_at is the rebuild time.
6. TEXT columns: inds (comma-joined labels), subjects (truncated raw text).
7. Target: **Bars** (an adjustment factor alongside bars_daily), derived from Events(corp_action). Alternatively compute it on the fly. It is a cache, not a concept.
8. The dividend factor depends on stock_prices close_pre, so the rebuild is data-dependent.

##### earnings_calendar
1. NSE forthcoming board-meeting and results calendar (−3 to +30 days).
2. Grain: (symbol, date). PK `id AUTOINCREMENT`. `UNIQUE(symbol, date)`.
3. `_insert_or_ignore` at sources/nselib_pull.py:354 (via :82). This **bypasses** insert_df's future-date guard on purpose. Step `fetch_earnings_calendar` (daily, config.py:288).
4. Readers:
   - cockpit/api.py:250-263 `get_earnings_upcoming` (stock detail and a widget).
   - health.py:741.
   - Ranking path: no.
5. Time columns:
   - `date` is the scheduled event date.
   - `added_date` is the first seen, a usable available_at.
   - PIT-safe: yes, via added_date.
   - A rescheduled meeting leaves the old row behind.
6. TEXT columns: company, purpose, and `bm_desc` (a free-text sentence).
7. Target: **Events** (type=board_meeting_scheduled, event_time=date, available_at=added_date, payload {purpose, bm_desc}).
8. It overlaps bse_announcements (category 'Board Meeting') and analyst_consensus.next_earnings_date. There are three sources for the same concept.

##### event_calendar
1. Plan 0013 normalization of demerger events (from bse_announcements) and buyback events (from corporate_actions).
2. Grain: (sid, event_type, announce_date). PK the same. Buyback rows have NULL announce_date, so the PK does not dedupe them (build_event_calendar.py:20-26).
3. `insert_df` at tools/build_event_calendar.py:95. **Manual tool; ran once** (all loaded_at = 2026-07-11 21:20:11). No cron, no step.
4. Readers: **none.** Only a comment at nselib_pull.py:323 and a docstring at sid_crosswalk.py:6 mention it. tools/event_study.py reads bse_announcements directly.
5. Time columns: announce_date, record_date, loaded_at. It is a frozen snapshot.
6. TEXT columns: event_type, event_subtype, source.
7. Target: **DELETE.**
   - No scheduled writer and no reader.
   - It is derivable as a view over Events.
   - The plan 0013 legs came back NULL (memory `special_situations_inhouse_legs_null`).
8. Its PK cannot enforce uniqueness on the NULL key.

##### fii_dii_cash_flow
1. Market-wide FII/DII cash-segment buy, sell and net value per day.
2. Grain: (flow_date, category). PK the same. category is 'FII/FPI' or 'DII'.
3. `insert_df` at sources/nselib_pull.py:457. Cron forward, `--source daily_forward` (run.sh:50), today-only (no archive).
4. Readers: **no code reader.**
   - factors.py:1006-1017 `fii_dii_cash_net` is a PROPOSED library entry with no producer.
   - signals/sector_briefs.py:11 is a comment only.
   - Otherwise only the cockpit_ops inventory.
5. Time columns: flow_date (event) and fetched_at. PIT-safe: yes.
6. TEXT columns: category.
7. Target: **Series** (series_id = fii_net_cash / dii_net_cash, …).
8. Write-only today, but it accumulates data that is forward-only, so keep it.

##### fii_dii_positioning
1. NSE participant-wise F&O open-interest positioning (Client, DII, FII, Pro, TOTAL).
2. Grain: (trade_date, client_type). PK the same.
3. `insert_df` at sources/nselib_pull.py:418. Cron forward (days_back=3).
4. Readers: **no code reader.** factors.py:1019-1030 has a PROPOSED entry with no producer. config.py:274,290 lists it under `reads` for fetch_corp_actions and fetch_earnings_calendar, which is a **bogus dependency** (those functions never read it).
5. Time columns: trade_date and fetched_at. PIT-safe: yes.
6. TEXT columns: client_type.
7. Target: **Series** (one series per client_type × leg).
8. The false `reads` edges put a phantom DAG dependency on it.

##### insider_trades
1. SEBI PIT (insider) disclosures from NSE: person, category, buy or sell, shares, value.
2. Grain: one disclosed trade. PK `id AUTOINCREMENT`. `UNIQUE(sid, person_category, transaction_type, trade_date, shares)`.
3. `insert_df` at sources/nse_insider.py:194. Step `fetch_insider` (daily).
4. Readers:
   - signals/insider_signal.py:169-226 (step `signal_insider` → insider_signals).
   - Backtest: pit.py:1491 (insider_signal producer, not wired).
   - cockpit/api.py:181,1092.
   - tools/freshness_watchdog.py:170.
   - Ranking path: no.
5. Time columns:
   - trade_date is the transaction date.
   - The disclosure date is **not stored** (it is only embedded in `filing_id`, e.g. `…_20260910_…`).
   - fetched_at is the first seen.
   - PIT: **no**. pit.py:1377 filters on trade_date, but disclosure lags the trade by days.
6. TEXT columns: company_name, person, person_category, transaction_type, source, filing_id.
7. Target: **Events** (type=insider_trade, event_time=trade_date, available_at=filing date, payload {person, category, side, shares, value}). Alternatively Ownership.
8. The UNIQUE key omits `person` and `filing_id`, so two different insiders in the same category with the same share count on the same day collapse into one row.

##### short_selling_data
1. NSE reported short-sold quantity per stock per day (F&O names only).
2. Grain: (symbol, short_date). PK `id AUTOINCREMENT`. `UNIQUE(symbol, short_date)`.
3. `insert_df` at sources/nselib_pull.py:287. Cron forward (1-month window, T+1 posting).
4. Readers: backtest only, pit.py:1488 `short` (the short_selling producer, bench). Ranking path: no.
5. Time columns: short_date (event) and fetched_at. PIT-safe: yes, but NSE posts at T+1 and the filter is ≤ D.
6. TEXT columns: symbol.
7. Target: **Features** (raw per-sid daily value). Alternatively Series keyed by sid.
8. None.

##### surveillance_flags
1. Daily NSE ASM (LT/ST), GSM and F&O-ban list membership.
2. Grain: (sid, flag_type, flag_date). PK the same. A daily **snapshot**, so a stock under GSM for 90 days produces 90 rows.
3. `insert_df` at sources/nselib_pull.py:580,605,646. Cron forward.
4. Readers: **none** (only the cockpit_ops inventory at 1472 and the tables.py registry).
5. Time columns: flag_date (the as-of snapshot) and fetched_at. PIT-safe: yes.
6. TEXT columns: flag_type, stage, `reason` (free text).
7. Target: **Events** (type=surveillance_on/off with intervals, payload {stage, reason}). Alternatively Series (0/1).
8. Write-only, but forward-only data (research 0001 row 2), so keep it.

---
#### Slice summary
- **Target counts (31):**

  | target | tables | count |
  |---|---|---|
  | Reference | stocks, scrip_master | 2 |
  | Bars | stock_prices, fno_bhav, nse_index_history, corporate_adjustments | 4 |
  | Series | fii_dii_cash_flow, fii_dii_positioning, vix_history (fold into macro_history) | 3 |
  | Events | bse_announcements, bulk_deals, corporate_actions, earnings_calendar, insider_trades, surveillance_flags | 6 |
  | Fundamentals (versioned, long) | annual_balance_sheet, annual_cash_flow, quarterly_income, fundamentals_screener, banking_metrics | 5 |
  | Estimates | analyst_consensus, analyst_consensus_snapshots, forecast_history, broker_recommendations | 4 |
  | Ownership | shareholding | 1 |
  | Features | fno_iv_history, fno_pcr_history, short_selling_data | 3 |
  | Decisions | regime_state | 1 |
  | DESIGN QUESTION | universe_eligibility | 1 |
  | DELETE | event_calendar | 1 |

- **DELETE candidates:**
  - `event_calendar`: a manual one-shot (loaded_at 2026-07-11), with no writer on any schedule and zero readers.
  - `vix_history`: a pure mirror of macro_history `india_vix` (macro_yfinance.py:195-204). Repoint regime.py:43 and diff_engine.py:214.
  - 14 dead `stocks` columns:
    - 12 all-NULL fundamentals columns.
    - Frozen April seeds `market_cap_cr` (in rupees) and `adtv_6m_cr`.
  - The dead `forecast_history` rows where metric='price'.
- **DESIGN QUESTIONS:**
  - `universe_eligibility`: about 22K 0/1 rows per day that no one can reproduce. It should probably be run-scoped (Decisions) or computed on the fly.
  - `regime_state`: a single overwritten row, display-only; it should become a per-run attribute.
- **Top surprises:**
  1. `analyst_consensus.price_target`, `total_analysts` and `buy_pct` are overwritten **daily** by the Moneycontrol aggregate (moneycontrol_recos.py:347), while `pt_source` still says yfinance. Both CLAUDE.md and tickertape_analyst.py:88 say yfinance is the sole writer. Live: RELI shows total_analysts=2.
  2. `forecast_history` eps feeds the **wired** consensus_signal_combined (LARGE .28 / SMALL .16), but it is period-dated and overwritten on every monthly fetch. pit.py:1366 filters on the period date, which is the same float-then-freeze look-ahead risk as the pulled `price` metric (magnitude unverified).
  3. **Live tier bug:** classify_micro_tier.py:62-73 compares the rupee `market_cap_cr` to 500 crores, so the mcap leg is dead, and it prefers the frozen April `adtv_6m_cr` over the live 90-day ADTV.
  4. `stocks` has no INSERT path at all. It was seeded once on 2026-04-09. With FKs enforced, the universe cannot gain a listing or lose a delisting. `cap_tier` and `sector` are overwritten in place, and the backtest uses today's values for every past date (pit.py:1409).
  5. The pre-push hook (`tools/regression_fixtures.py`) writes to and deletes from the live `stock_prices`, and it wipes all of RELI's `trust_verdicts`.
  6. `insider_trades` has no disclosure date, so its PIT filter on trade_date looks ahead.
  7. `analyst_consensus_snapshots` rows are backdated: the 2026-05-01 snapshot was fetched on 05-22.
  8. Several natural keys are lossy:
     - insider_trades omits `person`.
     - bulk_deals omits buy_sell and deal_type.
     - broker_recommendations reco_date falls back to today when missing.
  9. `bse_announcements` has no single large text column. Its 1.77 GB is about 2.6M rows × about 500 B of repeated short strings, plus TEXT-keyed indexes.

## Appendix B — news, macro/sector, regulatory, MF, outputs


Method: DDL/indexes from live DB (`mode=ro`), writers found by scanning every repo .py/.sh/.html for the table name with a write keyword within ±3 lines (catches multi-line SQL, `insert_df/upsert_df`), plus the dynamic `f"{table}_quarantine"` path (validators/_verdicts.py:91) and PIPELINE_STEPS (config.py:229+). `.claude/worktrees/` and `_archive/` are excluded from "live" writers/readers but noted when relevant. Step → cron: every PIPELINE_STEPS step runs inside `run.sh morning` (cron 03:30 UTC) at its `frequency`; watchdog (15:00 UTC) can re-run any step (heal).

Ranking path = `scoring/screener.py:109-116` → `pit.raw_keys_for(producers)` → `pit.RAW_SQL`. For the 10 weighted factors this resolves (verified by running `pit.raw_keys_for`) to raw frames `adjustments, bs, bse_gov, bse_results, cf, fh, fno_iv, macro_hist, macro_sector, prices, qi, sh, stocks`. From this slice only **macro_history** (`macro_hist` → announcement_car benchmark) is read directly; **macro_sector_map** is read indirectly (→ `macro_sector_signals_pit.macro_score` built by tools/reconstruct_pit.py:289 → `sector_tilt`, weighted LARGE .22/SMALL .16).

---

#### News & Sentiment

##### news_article_stocks
1. Concept: article ↔ stock entity-match link (string match of names/tickers at ingest).
2. Grain: one (article, sid) match. PK (article_id, sid). FKs → news_articles, stocks. Idx sid.
3. Write: `insert_df` = INSERT OR IGNORE — sources/rss.py:205 (step `fetch_news`, daily). Refs scan listed 0 writers (missed). Never re-matched when the universe/matcher changes.
4. Readers: pit/backtest pit.py:1489-1490 (`news`, `news_text` raw frames → sentiment_7d / news_volume_7d, both bench PROPOSED, unweighted); live signals/sentiment.py:41 (step `signal_sentiment` → sentiment_scores, unweighted); cockpit cockpit/api.py:205 (stock page A5 news); tools tools/sector_narrative_fetcher.py:203. Ops: health.py:729, lineage.py:561/569, cockpit_ops/api.py:1460. Tests: tests/test_sources_door.py:2760+. **Not in ranking path.**
5. Time: none on the table; inherits news_articles.published_at. PIT: lag-rule only (via parent).
6. Text: match_location (label: title/summary).
7. Target: **Events** (fold into the news event's payload as `sids[]`, or a generic `event_entities` link) — it is the entity side of a news Event.
8. Surprise: no match timestamp/matcher version → can't tell whether a link existed at date D.

##### news_articles
1. Concept: raw RSS news article (8-11 publications).
2. Grain: one article. PK article_id (hash of title+source).
3. Write: `insert_df` INSERT OR IGNORE — sources/rss.py:201 (step `fetch_news`, daily; skips entries older than 7d, rss.py:135-172). Refs scan listed 0 writers (missed).
4. Readers: pit pit.py:1489-1490; live signals/sentiment.py:38 (unweighted); cockpit cockpit/api.py:204, :2162 (news feed); LLM consumers sources/news_classifier.py:248/284, sources/news_brief.py:78, sources/regulatory_classifier.py:103 (materialises articles into regulatory_events), tools/session_classify.py:393/410, tools/sector_narrative_fetcher.py:97/202. Ops: health.py:725, lineage.py:558/571, cockpit_ops/api.py:1398/1459/1729. Tests: tests/test_smoke.py:79, test_sources_door.py. **Not in ranking path.**
5. Time: published_at = event time (publisher; mixed `YYYY-MM-DD HH:MM:SS` and ISO `T` formats, no RFC-2822 seen); fetched_at = ingest time (DEFAULT now). Range 2024-04-23 → 2026-09-27. PIT: yes if you use fetched_at as available_at (append-only, never overwritten); pit.py uses SUBSTR(published_at,1,10) ≤ D (lag-rule only).
6. Text: title (~95 ch), summary (~240 ch, capped 500), url, source.
7. Target: **Events** (type=news, event_time=published_at, available_at=fetched_at, payload{title,summary,url,source}) — or Documents if bodies are ever stored. Short enough for Events payload.
8. Surprise: regulatory_classifier copies every article into regulatory_events (`news_<article_id>`, regulatory_classifier.py:237/265) — the same article lives in two tables.

##### news_briefs
1. Concept: daily LLM (Sonnet) news digest (BIG ONE / FIVE FAST / ONE TO WATCH / ZOOM OUT).
2. Grain: one brief per day. PK brief_date.
3. Write: INSERT OR REPLACE — sources/news_brief.py:151 (step `news_brief`, daily). Single producer, full row.
4. Readers: cockpit only — cockpit/api.py:2077/2079 (`/news` header). Not in ranking path.
5. Time: brief_date (as-of), generated_at (run time). Overwritten on rerun. Range 2026-05-24 → **2026-08-23 (stale ~5 wk)**.
6. Text: big_one, five_fast (JSON array), one_to_watch, zoom_out (~375-800 ch each).
7. Target: **Documents** (doc_type=news_brief, as_of, body JSON, run_id).
8. Stale since 2026-08-23 (LLM credit outage per news_classifier.py:295-300 comment) — verify with health report.

##### news_enriched
1. Concept: per-article LLM (Haiku) enrichment — topics, one-liner, why-it-matters, sentiment, keywords.
2. Grain: one row per article. PK article_id (FK news_articles). Idx classifier_status, primary_topic.
3. Write: INSERT OR REPLACE — sources/news_classifier.py:322 ('failed' stub, only 3 cols), :332 (full); UPDATE keywords :270 (`backfill_keywords`, manual); tools/session_classify.py:420 (INSERT OR REPLACE, manual/untracked file). Step `classify_news` (daily).
4. Readers: cockpit/api.py:2163 (news feed pool incl. `image_url`); sources/news_brief.py:79. Not in ranking path.
5. Time: classified_at (LLM run time). Rows replaced in place on reclassify (no history).
6. Text: topics (JSON), primary_topic, one_liner, why_it_matters, key_numbers (JSON), what_to_watch, confidence, sentiment (label), keywords (JSON), classifier_status, image_url.
7. Target: **Documents/annotations** — an LLM-derived annotation of a news Event (payload JSON keyed by event_id + model + run_id). Workflow status → Ops.
8. Surprises: (a) `image_url` has data (e.g. article e5296050c23c) and is read by cockpit/api.py:2162 but has **no writer in the main tree** — the writer `tools/fetch_news_images.py` exists only in `.claude/worktrees/agent-a573…`/`agent-ad32…`. (b) INSERT OR REPLACE at news_classifier.py:322/332 and session_classify.py:420 omits image_url → wipes it; the 'failed' stub (:322) also wipes every enrichment field of a previously 'done' row. Violates the CLAUDE.md "never OR REPLACE on snapshot/state tables" rule.

##### transcripts
1. Concept: earnings-call transcript / notes / PPT PDFs with full extracted text.
2. Grain: one document. PK (sid, source_url). Idx (sid, doc_date).
3. Write: INSERT OR IGNORE — sources/transcripts_pull.py:302; UPDATE bse_filing_date — :205. **Not a PIPELINE_STEPS step, not in run.sh/crontab** → manual only (max fetched_at 2026-06-07).
4. Readers: signals/nlp_scores.py:117 (manual; → nlp_scores, which refresh_pit_panel reads, unweighted per memory "NLP transcript factors don't validate"). Tests: tests/test_sources_door.py:366. Not in ranking path.
5. Time: doc_date (concall month → first biz day, coarse), announce_date (parsed from PDF p1), bse_filing_date (BSE filing = true availability), fetched_at. PIT: yes via bse_filing_date/available_date (nlp_scores.py:40 insists on it). Append-only.
6. Text: **raw_text — long (LIMIT 20 sample: 31k–74k chars, avg 49k)**; period_label, doc_type, source_url, pdf_url, sha256.
7. Target: **Documents** (the canonical long-text table; available_at = bse_filing_date).
8. Manual-only producer of a 2005→2026 corpus; no freshness owner.

---

#### Macro / sector

##### macro_history
1. Concept: long-format macro & market time series (~50 indicators: Nifty/sector indices, commodities, FX, rates via yfinance; IIP/CPI/core via MoSPI/OEA; FRED).
2. Grain: one (indicator, reference date). PK (indicator_id, date). Idx category, date.
3. Write: `upsert_df` (column-level) — sources/macro_yfinance.py:171, :259 (step `fetch_macro_market`, daily); sources/macro_gov.py:87 (FRED) and sources/macro_official.py:271-272 (MoSPI/OEA) (step `fetch_macro_gov`, weekly). Multiple producers, disjoint indicator_ids.
4. Readers: **RANKING** pit.py:1494 `macro_hist` → announcement_car (weighted LARGE .35/SMALL .14) benchmark; → tools/reconstruct_pit.py:285/289 `pit_macro_sector` (pit.py:1021) → macro_sector_signals_pit → sector_tilt (weighted). PIT also macro_betas/residual_momentum (pit.py:844/968). Live/other signals: signals/announcement_car.py:158, pead.py:130, residual_momentum.py:61, macro_betas.py:135, sector_momentum.py:125 (→ sector_briefs.horizon_*). Cockpit cockpit/api.py:1935. Tools tools/event_study.py:129. Ops health.py:746, lineage.py:590+, cockpit_ops/api.py:1465. Tests test_phase0_guards.py:23, test_sources_silent_failures.py:86.
5. Time: date = reference period (daily close for market series; month-start for official stats); fetched_at = first-insert time only (upsert doesn't refresh it). Official series are **revised in place** (macro_official.py:241 re-pulls trailing window; mom_change nulled) → history of revisions lost. PIT: lag-rule only; pit_macro_sector uses `date <= eval` with **no publication lag** — safe for the ranking path only because macro_sector_map maps exclusively daily yfinance series (verified by join), would be look-ahead for IIP/CPI.
6. Text: source, category, unit (catalog attributes repeated per row).
7. Target: **Series** (series_id, date, value, available_at) + catalog from macro_indicator_meta; index/commodity price series arguably **Bars** (overlap with nse_index_history/benchmark indices — unverified here).
8. Oddity (unverified cause): iip_general 2026-06-01 and 2026-07-01 both 124.8.

##### macro_indicator_meta
1. Concept: registry of macro indicators (name, source, frequency, unit).
2. Grain: one indicator. PK indicator_id.
3. Write: `upsert_df` — sources/macro_yfinance.py:82, :258; sources/macro_gov.py:142; sources/macro_official.py:277-278. Rewritten every daily run.
4. Readers: no ranking/PIT read; metadata only — factors.py:1165 (source_tables text), lineage.py:593, health.py:755, cockpit_ops/api.py:1466; FK target of macro_sector_map.
5. Time: none. State, overwritten.
6. Text: name, source, source_ref, category, frequency, unit, description.
7. Target: **Reference → catalog** (series catalog).
8. —

##### macro_indicators
1. Concept: per-indicator STRONG/IMPROVING/STABLE/DETERIORATING labels + macro_overall pulse from latest IIP/core YoY.
2. Grain: one (indicator, run date). PK (indicator, snapshot_date).
3. Write: `upsert_df` — sources/macro_official.py:288 (step `fetch_macro_gov`, weekly). tables.py:288-289 note says "v1-migration leftover, no v2 producer" is now stale — producer exists since 2026-09-27.
4. Readers: signals/macro.py:66 (step `signal_macro` → macro_sector_signals, live, not ranking). Ops cockpit_ops/api.py:1464/1737, health.py:752. Tests tests/test_macro_official.py.
5. Time: snapshot_date = run date (as-of); derived from macro_history. PIT: yes-ish (append per run date), but derivable.
6. Text: signal (label), detail (sentence).
7. Target: **Features** (derived label; value already numeric) or drop as a view over Series — it is a pure function of macro_history.
8. Rows 2026-04-09 (v1) then 2026-09-27; stale labels (e.g. GST, credit growth) survive in macro_sector_signals.macro_detail from older snapshots.

##### macro_sector_map
1. Concept: indicator → GICS sector → direction/weight rules (30 rows).
2. Grain: one (indicator, sector). PK (indicator_id, sector). FK → macro_indicator_meta.
3. Write: **none in repo** (no writer in main tree, _archive, or schema.sql seed) — v1-migrated static data.
4. Readers: **RANKING (indirect)** pit.py:1495 `macro_map` → tools/reconstruct_pit.py:289 → macro_sector_signals_pit.macro_score → sector_tilt. Cockpit cockpit/api.py:1931 (sector macro contributors). Checks checks/ranges.py:67; lineage.py:595; health.py:760; cockpit_ops/api.py:1467.
5. Time: none (config). Not versioned — a change silently rewrites all PIT history on next refresh.
6. Text: rationale, sector.
7. Target: **Reference → catalog** (or a config dict in code, per ADR 0004) — must be versioned (valid_from) since it feeds a weighted factor.
8. Surprises: (a) no writer, no seed in schema.sql → a fresh DB from schema.sql has an empty map and sector_tilt loses its macro leg silently. (b) Contains non-GICS "Financial Services" rows alongside "Financials". (c) A second, different indicator→sector map is hard-coded in signals/macro.py:32 `SECTOR_MAP` (industry-level keys, official-stat indicators) for the live macro_sector_signals — two maps for one concept.

##### macro_sector_signals
1. Concept: live per-sector macro score/label (+ regulatory summary text appended).
2. Grain: one (sector, run date). PK (sector, snapshot_date).
3. Write: `upsert_df` — signals/macro.py:111 (step `signal_macro`, daily); signals/regulatory.py:216 (step `signal_regulatory`, daily) — two producers on the same columns (regulatory re-writes macro_score/macro_signal/macro_detail it read back).
4. Readers: signals/sector_briefs.py:132 (→ sector_briefs); cockpit/api.py:1624 (sector pages). checks/ranges.py:68/71; health.py:764. **Not in ranking path** (sector_tilt reads the _pit twin).
5. Time: snapshot_date = run date. Overwritten on rerun. PIT: append-per-day but values depend on step order.
6. Text: macro_signal (label), macro_detail (free text, 500 cap).
7. Target: **Features** (entity=sector) — and fold with macro_sector_signals_pit (same concept, two computations).
8. Surprises: (a) the numeric regulatory score is **never persisted** — only as text "Regulatory: NEUTRAL (967 events…)" inside macro_detail (regulatory.py:196-205); (b) if `signal_regulatory` runs before `signal_macro`, it writes macro_score NULL/'UNKNOWN' and macro.py then overwrites macro_detail, erasing the regulatory text — latest rows show it present for Financials/IT but not Energy; (c) live (macro_indicators × SECTOR_MAP) and PIT (macro_history × macro_sector_map) use different formulas → live ≠ PIT, contrary to ADR 0052 "one compute function".

##### sector_analyst_breadth_pit
1. Concept: monthly sector net analyst PT-revision breadth (from analyst_consensus_snapshots MoM).
2. Grain: (sector, month-start). PK (sector, snapshot_date).
3. Write: `upsert_df` — signals/sector_breadth.py:95 (step `sector_analyst_breadth`, monthly).
4. Readers: **none** besides the producer (only config.py:372-373, tables.py, ADR 0040 text). Accumulator for a future backtest (ADR 0040:24).
5. Time: snapshot_date = later month's snapshot (as-of). PIT: yes (derived from monthly snapshots). Range 2026-06-01 → 2026-09-01.
6. Text: none.
7. Target: **Features** (entity=sector, feature_id=analyst_breadth) — or recompute on demand from Estimates snapshots.
8. Write-only table (intended accumulator).

##### sector_force_breakdown
1. Concept: per-sector × force (macro/regulation/tech/market) direction/magnitude/summary for the sectors page.
2. Grain: (sector, snapshot_date, force). PK same. CHECK force ∈ 4.
3. Write: INSERT OR REPLACE full row — signals/sector_forces.py:300 (step `compute_sector_forces`, daily). Single producer.
4. Readers: cockpit/api.py:1891 (/sectors); output/sector_dossier.py:146 (LLM prompt). Not ranking.
5. Time: snapshot_date = sector_briefs date; computed_at. Overwritten per date.
6. Text: direction, magnitude (labels), summary (~185 ch), detail (JSON ~330 ch).
7. Target: **Features** for the numeric part is weak — mostly labels/JSON → **Documents** (derived sector narrative inputs) or a view. DESIGN QUESTION-lite: it's presentation, derivable from Events + Series.
8. —

##### sector_metadata
1. Concept: LLM-generated (Sonnet + web search) structured sector/industry narrative (value chain, drivers, players).
2. Grain: one (key, source) where key is a **sector OR industry name** (views.py:340-343). PK (sector, source). 48 rows.
3. Write: INSERT … ON CONFLICT DO UPDATE — tools/sector_narrative_fetcher.py:400 (manual CLI; not a step, not cron; last run 2026-05-11).
4. Readers: signals/sector_forces.py:197/214 (tech force); output/sector_dossier.py; views.py:342 (`sector_narrative`, cockpit via cockpit/api.py:1670 `get_group_metadata`); cockpit/api.py:1583. Not ranking.
5. Time: generated_at (overwritten). No history.
6. Text: payload (JSON, ~15-19k chars), industry, notes.
7. Target: **Documents** (doc_type=sector_narrative, key, generated_at).
8. Column named `sector` holds industry names too (taxonomy overloading).

##### sector_narrative_runs
1. Concept: audit log of sector_narrative_fetcher runs.
2. Grain: one run. PK id AUTOINCREMENT.
3. Write: INSERT — tools/sector_narrative_fetcher.py:414 (manual).
4. Readers: none (tables.py:311 only).
5. Time: started_at/finished_at. Append-only. 4 rows, last 2026-05-11.
6. Text: status, detail (error text).
7. Target: **Ops** (step_runs / llm_usage) — or DELETE (no reader).
8. api_cost_usd never populated.

##### sector_policy_pit
1. Concept: monthly age-decayed net policy tailwind per sector from curated policy_events.
2. Grain: (sector, month-end). PK (sector, snapshot_date).
3. Write: `upsert_df` — signals/sector_policy.py:125 (step `sector_policy`, monthly); full backfill every run.
4. Readers: **none** besides producer (config.py:380-381, ADR 0040 text).
5. Time: snapshot_date month-end. **Not PIT-honest**: the whole 2020-05 → 2026-08 history is recomputed from a seed curated in 2026-06 (hindsight selection/magnitudes).
6. Text: none.
7. Target: **Features** (entity=sector) — or DELETE (write-only, hindsight-contaminated).
8. —

##### sector_sentiment_breadth_pit
1. Concept: monthly sector aggregate of stock 30d news sentiment breadth.
2. Grain: (sector, month). PK (sector, snapshot_date).
3. Write: `upsert_df` — signals/sector_breadth.py:144 (step `sector_sentiment_breadth`, monthly).
4. Readers: **none** besides producer.
5. Time: snapshot_date = last sentiment snapshot in month. PIT: lag-rule (derived from sentiment_scores). Range 2026-03-31 → 2026-08-31.
6. Text: none.
7. Target: **Features** (entity=sector).
8. Write-only accumulator.

---

#### Regulatory

##### policy_events
1. Concept: hand-curated major India policy events (budget, PLI, tariffs) with direction/magnitude.
2. Grain: one (date, sector, title). PK (event_date, sector, title).
3. Write: `upsert_df` of the in-code SEED — signals/sector_policy.py:76 (`seed()`, auto-called by step `sector_policy` when empty, :90-93). Source of truth is the Python list, not the table.
4. Readers: signals/sector_policy.py:87/89 only.
5. Time: event_date (announcement/effective). No available_at; seed dated 2026-06 ("curated_seed_2026-06"). 2020-05-13 → 2025-04-01.
6. Text: title, event_type, source.
7. Target: **Events** (type=policy, available_at = curation date) — tables.py DATASET_KIND_OVERRIDES already calls it "event".
8. Duplicates code; stops at 2025-04 (nothing appended since seed).

##### regulatory_batches
1. Concept: Anthropic Message-Batch job tracking for the regulatory classifier.
2. Grain: one batch. PK batch_id.
3. Write: INSERT OR REPLACE — sources/regulatory_classifier.py:786; UPDATE status — :796 (step `classify_regulatory`, daily).
4. Readers: sources/regulatory_classifier.py:643/646/664 (poll pending batches). No surface.
5. Time: submitted_at, ingested_at. State.
6. Text: stage, status.
7. Target: **Ops** (llm job state / llm_usage).
8. —

##### regulatory_events
1. Concept: regulatory/policy news items (Google News, RBI circulars, PIB, Wayback, plus every RSS article materialised as `news_<id>`) + classifier workflow status.
2. Grain: one event. PK event_id. Idx classifier_status, source, published_at.
3. Write: `insert_df` INSERT OR IGNORE — sources/regulatory_harvester.py:193/288/361/529/588 (step `fetch_regulatory`, daily = `harvest_incremental`; others manual); sources/regulatory_classifier.py:237/265 (copies news_articles); UPDATE classifier_status/processed_at/ministry/title_hash — regulatory_classifier.py:275/281/300/425/585/764/777 (step `classify_regulatory`); tools/session_classify.py:182/212 (manual, untracked).
4. Readers: live signals/regulatory.py:65 (→ macro_sector_signals text), signals/sector_briefs.py:188, signals/sector_forces.py:106/128; pit pit.py:1492 (→ macro_sector_signals_pit.regulatory_score, **unweighted — not in ranking path**); cockpit cockpit/api.py:243 (sector/stock regulatory blocks); checks/custom.py:459-475, checks/ranges.py:73; tools/compare_reg_models.py:81/86. Ops health.py:768, lineage.py:580, cockpit_ops.
5. Time: published_at = event time (**mixed ISO and RFC-2822 text**, e.g. `Thu, 28 Sep 2023 23:45:23 +0530`); fetched_at = ingest; classifier_processed_at = workflow. PIT: lag-rule only; classifier status overwritten in place.
6. Text: title, summary (≤2000, ~360 ch), full_text (RBI/PIB bodies, 3000 cap), source_url, ministry, classifier_status, title_hash.
7. Target: **Events** (type=regulatory, payload{title,summary,ministry}); full_text → **Documents**; classifier_status → Ops.
8. Surprises: (a) tools/reconstruct_pit.py:284 filters `published_at <= eval_str` as a **string** — every RFC-2822 row ('F','M','S','T','W' > digits) is always excluded from PIT regulatory_score, and same-day ISO rows are excluded; (b) MIN/MAX(published_at) are lexicographic garbage (MAX = "Wed, 31 May 2023"); db.py:734 has a slow-path workaround for freshness; (c) news articles duplicated here.

##### regulatory_signals
1. Concept: LLM (Haiku pre-filter + Sonnet) sector impact of a regulatory event.
2. Grain: one (event, sector). PK (event_id, sector). FK → regulatory_events.
3. Write: `insert_df` INSERT OR IGNORE — sources/regulatory_classifier.py:153 (copy verdict to title-hash duplicate), :330, :574, :757 (batch path) (step `classify_regulatory`); tools/session_classify.py:211 DELETE, :373/:384 UPDATE direction (manual reconcile/rollback).
4. Readers: signals/regulatory.py:64/91; signals/sector_briefs.py:187; signals/sector_forces.py:98-127; pit.py:1493 (`reg_signals`, unweighted); cockpit/api.py:220-244; checks/custom.py:436-454, ranges.py:76; tools/compare_reg_models.py:17. Not ranking.
5. Time: classified_at (LLM time, DEFAULT now; copies get a fresh now). PIT: **no** — pit.py joins signals with no classified_at filter; LLM classified old (2023) events in 2026 with hindsight; session_classify rewrites direction in place.
6. Text: ai_reasoning (~190 ch, max ~280), stage, magnitude, time_horizon, confidence (labels); direction/is_regulatory numeric.
7. Target: **Events** annotation (payload per sector, model, run_id) — or Documents-annotation like news_enriched.
8. tables.py:327 depth text ("5,687 signals… paused on budget cap") is stale vs current writers.

---

#### Mutual funds (extra (a) below)

##### mf_calendar_returns
1. Concept: per-scheme calendar-year return vs benchmark.
2. Grain: (scheme_code, year). PK same.
3. Write: `upsert_df` — signals/mf_metrics.py:668 (step `compute_mf_metrics`, monthly).
4. Readers: cockpit/mf.py:204 (MF detail bar chart).
5. Time: year; current year overwritten monthly. Derivable from fund_nav.
6. Text: none.
7. Target: **MF** (fund_metrics, metric=cal_return, period=year) — or view.
8. —

##### mf_category_stats
1. Concept: per-category medians/deciles of returns/Sharpe.
2. Grain: (category_norm, as_of_date). PK same.
3. Write: `upsert_df` — signals/mf_metrics.py:673 (compute_mf_metrics, monthly).
4. Readers: cockpit/mf.py:159-160 (heatmap).
5. Time: as_of_date snapshot (kept). 2026-05-26 → 2026-09-01.
6. Text: category_norm.
7. Target: **MF** (fund_metrics at category entity) or view.
8. —

##### mf_holdings
1. Concept: fund portfolio holdings (top equity positions) scraped from ETMoney.
2. Grain: (scheme_code, as_of_date, holding_rank). PK same. Idx sid, scheme.
3. Write: INSERT OR REPLACE full row — sources/mf_holdings_scrape.py:575 (step `scrape_mf_holdings`, monthly); sources/mf_holdings.py:109 (manual CSV). Quarantine mirror `mf_holdings_quarantine` via validators/_verdicts.py:91 (called from mf_holdings_scrape.py:515 on WRONG_ENTITY); trust_verdicts rows via record_verdict (:535).
4. Readers: cockpit/mf.py:287-303 (`get_mf_holdings`, MF detail page). Ops: scoring/health_score.py:185 (comment: trust_verdicts carries mf_holdings). **No stock-side reader.**
5. Time: as_of_date = **scrape date** (`as_of or datetime.now()`, mf_holdings_scrape.py:545), not the fund's disclosure date. PIT: no (disclosure lag unknown).
6. Text: instrument_name, instrument_type, sector (ETMoney taxonomy e.g. "Financial", not GICS), isin (always NULL from scrape).
7. Target: **MF** (fund_holdings) — the one table that could become **Ownership** (fund → sid) if a stock factor ever uses it.
8. sid is a best-effort name match (mf_holdings_scrape.py:474-475, 554); stale higher ranks are not deleted on re-scrape of the same date (only mf_sector_allocation is DELETEd, :571).

##### mf_metrics
1. Concept: per-scheme returns/risk/peer-rank/composite score snapshot.
2. Grain: (scheme_code, as_of_date). PK same.
3. Write: `upsert_df` — signals/mf_metrics.py:648 (compute_mf_metrics, monthly).
4. Readers: cockpit/mf.py (20-55, 199, 236, 266, 334); sources/mf_data_quality.py:186-205 (step classify_mf_quality); sources/mf_holdings_scrape.py:439 (target selection). Ops lineage.py:164-167 (unit contracts), tools/trust_backfill.py:395.
5. Time: as_of_date snapshot (monthly, kept); nav_date. 2026-05-28 → 2026-09-01.
6. Text: max_dd_start/max_dd_end (dates).
7. Target: **MF** (fund_metrics, long: metric_id,value).
8. Benchmark is "Nifty 50 proxy = AVG(close) of TODAY's top-50 LARGE stocks" over the full history (signals/mf_metrics.py:80-114) — survivorship/look-ahead benchmark; tools/trust_backfill.py:395 references a non-existent `snapshot_date` column for mf_metrics.

##### mf_nav_history
1. Concept: daily NAV per scheme.
2. Grain: (scheme_code, nav_date). PK same. ~8M rows (health.py:508).
3. Write: INSERT OR IGNORE — sources/mf_nav_daily.py:73, :139 (step `fetch_mf_nav_daily`, daily; `--from/--to` gap repair); sources/mf_nav_backfill.py:109 (manual mfapi.in bootstrap).
4. Readers: signals/mf_metrics.py:554/559; sources/mf_data_quality.py:146-153; cockpit/mf.py:48, 171, 225, 232. Ops scoring/health_score.py:95/633 (freshness), validators/temporal_continuity.py:27 (docstring example), cockpit_ops/api.py:1476. Test tests/test_schema.py:25.
5. Time: nav_date (event), fetched_at (ingest). Append-only; AMFI restatements ignored (first write wins). PIT: yes.
6. Text: none.
7. Target: **MF** (fund_nav) — structurally Bars/Series for a fund entity.
8. —

##### mf_rolling_returns
1. Concept: monthly-anchored rolling 3Y/5Y CAGR + beats-category flags.
2. Grain: (scheme_code, anchor_date). PK same.
3. Write: `upsert_df` — signals/mf_metrics.py:663 (monthly; recomputes all anchors).
4. Readers: cockpit/mf.py:247.
5. Time: anchor_date; recomputed/overwritten. Derivable.
6. Text: none.
7. Target: **MF** (fund_metrics) or view.
8. —

##### mf_scheme_master
1. Concept: AMFI MF universe (scheme code, ISINs, AMC, category, plan/option, active) + quality flag + ETMoney mapping.
2. Grain: one scheme. PK scheme_code.
3. Write: `upsert_df` — sources/mf_amfi_master.py:303 + UPDATE active=0 :309 (step `fetch_mf_master`, weekly); UPDATE data_quality — sources/mf_data_quality.py:261 (step `classify_mf_quality`, weekly); UPDATE etm_slug/etm_id — sources/mf_holdings_scrape.py:255 (+ runtime `ALTER TABLE` :78/:81); UPDATE — sources/mf_metadata_enrichment.py:109 (manual CSV, would `ALTER TABLE ADD fund_manager` :76 — not applied in DB).
4. Readers: cockpit/mf.py (18-69, 168-190, 257-267, 328-361); signals/mf_metrics.py:546/559; sources/mf_nav_backfill.py:78, mf_nav_daily (config reads); ops scoring/health_score.py:96/634.
5. Time: last_seen, fetched_at; overwritten state; soft-delete via active.
6. Text: scheme_name, amc, category_raw/norm, sub_category, plan/option_type, benchmark, data_quality, quality_reason, etm_slug, ISINs.
7. Target: **MF** (funds).
8. Four writers on disjoint columns (OK under upsert_df), but schema mutated at runtime by two sources modules (ALTER TABLE) — schema.sql drift risk.

##### mf_schemes
1. Concept: v0 compat table — backfilled-schemes marker (inception_date, has_full_history).
2. Grain: one scheme. PK scheme_code.
3. Write: INSERT … ON CONFLICT DO UPDATE — sources/mf_nav_backfill.py:114 (manual).
4. Readers: sources/mf_nav_backfill.py:75 (skip list); cockpit/mf.py:191, :329 (LEFT JOIN for inception_date/has_full_history). Test tests/test_schema.py:25.
5. Time: fetched_at. State.
6. Text: scheme_name, fund_house, scheme_type, direct_or_regular, growth_or_dividend.
7. Target: **MF** — merge 2 columns into funds; DELETE the table.
8. Sample row has direct_or_regular="Open Ended Schemes" (mis-mapped mfapi meta); duplicates mf_scheme_master.

##### mf_sector_allocation
1. Concept: fund sector-weight breakdown (ETMoney).
2. Grain: (scheme_code, as_of_date, sector). PK same.
3. Write: DELETE (scheme,date) + INSERT OR REPLACE — sources/mf_holdings_scrape.py:571/583 (scrape_mf_holdings, monthly, same txn as holdings); INSERT OR REPLACE sources/mf_holdings.py:129 (manual CSV). Quarantine mirror exists (tables.py:543).
4. Readers: cockpit/mf.py:294-296. Tests test_sources_door.py:1816+.
5. Time: as_of_date = scrape date. PIT: no.
6. Text: sector (ETMoney taxonomy).
7. Target: **MF** (fund_holdings at sector granularity, or fund_metrics).
8. —

---

#### Output

##### daily_changes
1. Concept: day-over-day diff events for the email/cockpit (ENTRY/EXIT/UPGRADE/DOWNGRADE/SIGNAL_FIRED/REGIME_CHANGE).
2. Grain: one change row. PK id AUTOINCREMENT (no natural key). Idx sid, change_date.
3. Write: DELETE today + `insert_df` — output/diff_engine.py:304/306 (step `diff_engine`, daily). Non-atomic (two connections). If a rerun yields 0 changes, old rows for today are kept (`if changes:` :298).
4. Readers: views.py:322-335 (`changes`, `change_counts`) → cockpit/api.py:646-648, output/email_sender.py:370; checks/ranges.py:91; health.py:837; cockpit_ops/api.py:1492. Not ranking.
5. Time: change_date = run date. Rewritten per day.
6. Text: headline, detail, color, severity, change_type.
7. Target: **Decisions** — derivable view over picks(t) vs picks(t-1); recommend replacing the table with a view (DELETE as table).
8. Presentation (color) stored in data.

##### daily_picks
1. Concept: the screener's ranked eligible universe per day with final_score, within-tier rank, coverage gates, integrity and UHS.
2. Grain: (sid, pick_date). **PK (sid, pick_date)**; FK sid→stocks; idx pick_date. No run_id, no git sha, no weights hash, no created_at/generated_at column at all.
3. Write: DELETE WHERE pick_date=today (scoring/screener.py:472-473) then `upsert_df` (:475) — **separate connections, not atomic**; then UPDATE uhs_* columns — scoring/confidence.py:228-233 (`batch_write_pick_uhs`, called from screener.py:484-485). Step `screener` (critical, daily). **Rerun same date = full replace**, previous run unrecoverable.
4. Readers: decision layer portfolio_construction.py (309-394, 496-603, 721); tools/compute_pick_outcomes.py:122 (→ pick_outcomes); scoring/confidence.py (UHS/calibration), scoring/health_score.py:515/523; output/snapshot.py, output/diff_engine.py, output/dossier.py:455, output/email_sender.py, signals/sector_briefs.py:112/146/159, validators/per_stock_integrity.py:474; views.py:125-242; cockpit/api.py (291, 465, 676-789, 1171, 1611-1720, 1977, 2416), cockpit/templates (explorer, stock_detail, model_*); cockpit_ops/api.py:2127-2155, 2398; checks/custom.py:169-380, 494, ranges.py:88-90; tools/rebalance_sim.py, pit_replay.py:97, sector_tilt_validation.py, rank_localization; mirror in DuckDB (tables.py `mirror`). Tests: tests/test_checks.py, test_graph.py, … It **is** the ranking output; nothing in the next day's ranking reads it back.
5. Time: pick_date = run date (as-of). PIT: yes per date (one snapshot/day), but reruns overwrite; UHS updated after insert.
6. Text: cap_tier, sector (denormalised), integrity_status, integrity_reasons, uhs_label, uhs_worst_dim, uhs_breakdown_json (~350 ch JSON).
7. Target: **Decisions** (runs + picks + pick_contributions; sector/cap_tier from security_tiers by date).
8. Surprises: nine legacy `*_adj` columns hard-coded to 0 (screener.py:448-456 "placeholder"); non-atomic DELETE+upsert; no provenance of which weights/code produced a row.

##### daily_snapshots
1. Concept: live per-stock signal values on the pick date (piotroski, accruals, EY, B/P, momentum, delivery, smart money, sentiment).
2. Grain: (sid, snapshot_date). PK same. Idx cap_tier, date.
3. Write: `upsert_df` (all columns → effectively full-row) — output/snapshot.py:111 (step `snapshot`, daily).
4. Readers: output/diff_engine.py:47/157/164; output/email_sender.py (SNAPSHOT_SIGNALS); output/sector_dossier.py (config reads); cockpit/api.py:292-294, 500-506, 759-769; views.py:152/165; scoring/health_score.py:66/86/624; checks/custom.py:186-327, ranges.py:80-82; cockpit_ops/api.py:629. (signals/momentum.py:102, earnings_yield.py:95, delivery_anomaly.py:12 are comments only.) Not read by ranking.
5. Time: snapshot_date = run date. Overwritten on rerun.
6. Text: cap_tier.
7. Target: **Features** (feature_values, run_id) — duplicates daily_snapshots_pit for the same concept (live vs PIT panel).
8. Parallel to daily_snapshots_pit with different computations for some columns (e.g. delivery_pct = 30d avg here, snapshot.py:79-83).

##### paper_nav_history
1. Concept: paper-portfolio daily NAV vs benchmark.
2. Grain: one date. PK nav_date.
3. Write: **none in main tree** — writer is `_archive/paper_portfolio.py` (archived). Last row 2026-07-03.
4. Readers: none (tables.py:467 only, `may_be_empty`).
5. Time: nav_date.
6. Text: none.
7. Target: **DELETE** (no writer, no reader; not in crontab/run.sh/PIPELINE_STEPS). Superseded conceptually by portfolio_weights/portfolio_outcomes (tools/portfolio_nav.py computes NAV on the fly).
8. tables.py says "not live yet" but the table holds May–Jul 2026 rows from the archived writer.

##### paper_positions
1. Concept: paper-portfolio positions (open/closed lots).
2. Grain: one position. PK position_id AUTOINCREMENT.
3. Write: none in main tree (`_archive/paper_portfolio.py`).
4. Readers: none (tables.py:468).
5. Time: entry_date/exit_date.
6. Text: status, sector, cap_tier.
7. Target: **DELETE** (same evidence as paper_nav_history).
8. —

##### paper_trades
1. Concept: paper-portfolio trade blotter.
2. Grain: one trade. PK trade_id AUTOINCREMENT. FK position_id.
3. Write: none in main tree (`_archive/paper_portfolio.py`); last trade 2026-06-29.
4. Readers: none live; tests/test_checks.py:120 only.
5. Time: trade_date, rebalance_date.
6. Text: side, reason.
7. Target: **DELETE** (or Decisions/book_weights if paper trading returns).
8. —

##### pick_outcomes
1. Concept: realised forward return (20/63/126 trading days) of every daily_picks row vs tier benchmark.
2. Grain: (sid, pick_date, window_days). PK same. Idx (cap_tier, pick_date), pick_date.
3. Write: `upsert_df` — tools/compute_pick_outcomes.py:199 (step `compute_pick_outcomes`, daily; recomputes all history).
4. Readers: scoring/confidence.py:241/253 (→ uhs_calibration_log, step update_uhs_calibration); cockpit/api.py:2398, 2477, 2504 (model outcomes page via cockpit/app.py:352/362); tools/rank_localization.py, tools/validate_rank_skill.py:66-82. DuckDB mirror. Not ranking.
5. Time: pick_date (decision), exit_date (realisation), computed_at. Rows restated in place when prices/adjustments change.
6. Text: bench_index.
7. Target: **Decisions → outcomes**.
8. Covers the whole ranked universe, not just top-N — it's a label table as much as a track record.

##### portfolio_outcomes
1. Concept: realised HRP-book vs equal-weight vs benchmark return per book date & window.
2. Grain: (asof_date, window_days). PK same.
3. Write: `upsert_df` — tools/portfolio_outcomes.py:145 (step `portfolio_outcomes`, daily).
4. Readers: only tools/portfolio_outcomes.py:152 (`report()`, CLI print). **No cockpit/email reader.**
5. Time: asof_date, computed_at; recomputed in place.
6. Text: none.
7. Target: **Decisions → outcomes** (book-level) — or view over pick_outcomes × book_weights.
8. Pipeline log shows the step logged twice per run (output/pipeline.log:113544-113551 START/DONE duplicated) — logging artefact, unverified cause.

##### portfolio_weights
1. Concept: advisory HRP risk-parity × alpha-tilt book per date.
2. Grain: (asof_date, sid). **PK (asof_date, sid)**; FK sid→stocks. No run_id / git sha / weights hash; created_at DEFAULT now (insert only — upsert doesn't refresh it).
3. Write: DELETE sids not in new book + `upsert_df` on the **same connection** (atomic) — portfolio_construction.py:715-717 (step `portfolio_construction`, daily; `--backfill` rebuilt history from 2026-04-09). Rerun same date = replace.
4. Readers: portfolio_construction.py:320/433-444 (prior book for carry/drift banding); cockpit/api.py:1195-1214 (`get_sized_book`); tools/portfolio_outcomes.py:105, tools/portfolio_nav.py:94, tools/expected_return.py:90-93 (monthly cron `expected_return`), tools/rebalance_sim.py. Not ranking.
5. Time: asof_date = daily_picks.pick_date. History before 2026-09 is a **backfill** (portfolio_construction.backfill), not what was live on that date.
6. Text: cap_tier, sector, name (denormalised).
7. Target: **Decisions → book_weights** (+ runs).
8. Denormalises name/sector/tier from stocks.

##### sector_briefs
1. Concept: per-sector daily digest (macro score, breadth, top picks, regulatory summary, bucket, momentum horizons).
2. Grain: (sector, snapshot_date). PK same. Idx (date, bucket), date.
3. Write: INSERT OR REPLACE — signals/sector_briefs.py:219 (step `compute_sector_briefs`, daily) writes 17 cols **omitting horizon_short/medium/long**; UPDATE horizon_* — signals/sector_momentum.py:235 (step `compute_sector_momentum`, daily).
4. Readers: cockpit/api.py:1777-1793 + templates/sectors.html; output/sector_dossier.py:126/272-295; signals/sector_forces.py:44-49/281 (snapshot date + macro force). Not ranking.
5. Time: snapshot_date = latest pick_date; computed_at. Overwritten per date.
6. Text: macro_signal, macro_drivers (JSON ~350 ch), top_picks (JSON), regulatory_summary (JSON), bucket, horizon_* (labels); fii/dii_net_30d always NULL ("RESERVED").
7. Target: DESIGN QUESTION — a presentation roll-up mixing Features (sector macro/breadth) with Decisions (top picks) and labels; best as a view/materialised doc, not a stored concept.
8. **OR REPLACE with two producers**: any rerun/heal of compute_sector_briefs after compute_sector_momentum NULLs the horizon_* columns (CLAUDE.md rule violation; comment at sector_briefs.py:211 even claims it's "per CLAUDE.md").

##### sector_dossiers
1. Concept: LLM sector thesis/bull/bear/watch-list with number-free validation.
2. Grain: (sector, snapshot_date). PK same.
3. Write: INSERT OR REPLACE full row — output/sector_dossier.py:248 (step `compute_sector_dossiers`, daily). Module also carries its own CREATE TABLE (:53-68).
4. Readers: cockpit/api.py:1810 (valid=1 only). Tests tests/test_graph.py:71/74.
5. Time: snapshot_date, generated_at; overwritten. Range 2026-05-31 → **2026-08-23 (stale)**.
6. Text: thesis (~300 ch), bull_case/bear_case/what_to_watch/tech_innovation_drivers (JSON lists, ~900 ch), conviction (label), validation_json, model.
7. Target: **Documents** (doc_type=sector_dossier, model, run_id, valid).
8. Stale since 2026-08-23 (same LLM outage as news_briefs).

---

#### Extras

**(a) MF boundary.** Stock-side (non-MF) code reading mf_* tables: only ops/metadata — scoring/health_score.py:95-96, 633-634 (freshness thresholds for mf_nav_history, mf_scheme_master), :185 (comment: trust_verdicts carries mf_holdings); lineage.py:163-167 (unit contracts mf_metrics); tools/trust_backfill.py:395 (mf_metrics PK spec, wrong column); health.py:508 (comment); cockpit_ops/api.py:1475-1476 (inventory text); validators/temporal_continuity.py:27 (docstring). **No ranking, PIT, signals/, scoring or stock cockpit page reads an mf_* table.** Reverse direction (MF reads stock tables): signals/mf_metrics.py:108-114 (stocks + stock_prices for the Nifty proxy benchmark), sources/mf_holdings_scrape.py:474 and sources/mf_holdings.py:91 (stocks name/isin → sid). **Nothing joins mf_holdings.sid to stocks in any reader** (cockpit/mf.py:285 just returns the sid column). → mf.db split is clean if the benchmark comes from a shared index Series and the sid matcher reads a securities export.

**(b) daily_picks / portfolio_weights.** daily_picks PK (sid, pick_date); rerun = DELETE date then upsert in a separate transaction (screener.py:472-475), then UHS UPDATE (confidence.py:228). portfolio_weights PK (asof_date, sid); rerun = DELETE-not-in + upsert in one transaction (portfolio_construction.py:714-717). Neither has run_id, git sha, weights hash or config hash (grep `run_id` over repo .py returns nothing outside worktrees/tests). daily_picks has no timestamp column at all.

**(c) Long text (LIMIT-20 samples).** transcripts.raw_text 31k–74k chars (avg 49k) — the only true Documents-scale column. Medium: sector_metadata.payload ~15-19k (JSON); regulatory_events.full_text ≤3000; sector_dossiers lists ~900; news_briefs.five_fast ~800. Short (<500): news_articles.title ~95 / summary ~240; news_enriched fields 50-130; regulatory_events.summary ~360; regulatory_signals.ai_reasoning ~190; daily_picks.uhs_breakdown_json ~350.

#### Slice summary
- Targets (40): Events 5 (news_articles, news_article_stocks, policy_events, regulatory_events, regulatory_signals) · Documents 5 (transcripts, news_briefs, news_enriched, sector_metadata, sector_dossiers) · Series 1 (macro_history) · Reference/catalog 2 (macro_indicator_meta, macro_sector_map) · Features 6 (macro_indicators, macro_sector_signals, sector_analyst_breadth_pit, sector_sentiment_breadth_pit, sector_force_breakdown, daily_snapshots) · MF 9 · Decisions 5 (daily_picks, portfolio_weights, pick_outcomes, portfolio_outcomes, daily_changes→view) · Ops 2 (regulatory_batches, sector_narrative_runs) · DELETE 4 (paper_* ×3, sector_policy_pit) · DESIGN QUESTION 1 (sector_briefs). (mf_schemes counted in MF 9 but is itself a merge-and-drop.)
- DELETE: paper_nav_history/paper_positions/paper_trades (only writer is `_archive/paper_portfolio.py`, no reader, not in crontab/run.sh/PIPELINE_STEPS, last rows Jun–Jul 2026); mf_schemes (fold 2 cols into funds); sector_policy_pit (no reader, hindsight-curated backfill). Soft: sector_narrative_runs, daily_changes (derivable view), sector_*_breadth_pit (write-only accumulators, no reader yet).
- Ranking path from this slice: macro_history (direct, announcement_car) and macro_sector_map (indirect via macro_sector_signals_pit → sector_tilt). macro_sector_map has **no writer and no schema.sql seed** — a rebuilt DB silently drops sector_tilt's macro leg.
- Two indicator→sector maps: table macro_sector_map (PIT) vs hard-coded signals/macro.py:32 SECTOR_MAP (live) → live macro_sector_signals ≠ PIT twin (violates ADR 0052 one-compute rule).
- OR REPLACE with multiple producers: sector_briefs (sector_briefs.py:219 wipes sector_momentum's horizon_*), news_enriched (news_classifier.py:322/332, session_classify.py:420 wipe image_url, whose writer exists only in a .claude worktree).
- regulatory_events.published_at mixes ISO and RFC-2822 → reconstruct_pit.py:284 string compare always drops RFC rows from PIT; MAX() is lexicographic garbage. regulatory_signals has no PIT guard (hindsight LLM labels).
- Regulatory score in live macro_sector_signals exists only as text in macro_detail; step order decides whether it survives.
- daily_picks: DELETE+upsert non-atomic, no run_id/sha/weights hash/timestamp; nine `*_adj` columns are constant 0.
- Stale LLM outputs: news_briefs and sector_dossiers stop at 2026-08-23. transcripts and sector_metadata have manual-only producers.

## Appendix C — per-factor signal tables


Auditor C. Read-only. DB = live `data/alpha_signal.db` (mode=ro), 2026-09-27 ~18:50 UTC. Code = HEAD 7996712.
Legend: KEY / FV = numeric feature value / NI = numeric intermediate (input or component) / LBL = text label or flag / NAR = narrative text / META.
Every table below is **history keyed by (sid, snapshot_date)** (except nlp_scores and insider_signals, where the PK differs). None is a single "latest" row per sid. `snapshot_date` = the producer's run date (`date.today()`), not a fiscal date.

#### 0. Shared facts (verified once, then used everywhere below)

- **Write mode.** Every writer uses `db.upsert_df` = `INSERT … ON CONFLICT(pk) DO UPDATE SET <only the df's columns>` (db.py:582-589). The one exception is nlp_scores, which uses `INSERT OR REPLACE` (signals/nlp_scores.py:139-141). No table in this slice uses DELETE-then-insert.
- **Live producers apply no filing lag.** They read everything in the DB on the run date (e.g. signals/piotroski.py:43-66). The PIT producers wrap the SAME `_compute*` on lagged slices (pit.py:107-150, 155, 1153, 1261; `_annual.pit_frame` signals/_annual.py:58). So a `*_scores` row at snapshot_date D is "as observed at D" (knowable at D, PIT-safe as an observation log). It is NOT the value `features_at(D)` returns, which applies the 75/60/21-day lags (pit.py:25-28).
- **Huge redundancy.** Each run re-stamps every sid even when nothing changed. Share of distinct (sid, value) among all rows: about 2-5% for every annual-ratio table and piotroski/forensic/sentiment; 26-43% for the within-tier percentile composites (accruals_signal, promoter_signal, consensus_signal, smart_money_score), which move with the cross-section. share_momentum is 72%, because it is price-driven. Filler rows are common: sentiment_7d is NULL in 337k/379k rows, consensus_signal in 185k/316k, smart_money_score in 55k/370k, and insider_signals has 212k/231k NEUTRAL rows.
- **Cockpit_ops catalog.** cockpit_ops/api.py:1478-1488 (`DATA_MODEL_GROUPS`) lists piotroski, forensic, accruals, consensus, promoter, smart_money, insider, sentiment, roic and fcf_yield tables for row-count/schema display only. It is metadata and never counts as a live reader.
- **Traced step `reads` are stale.** `config.PIPELINE_STEPS` "reads" are traced (db.py:56 `_trace_authorizer`). The live-screener path (features_at) landed TODAY in commit 4af1d6f (2026-09-27 06:31 UTC), after this morning's 03:30 run (pit_replay frozen_by_commit=bd7dc24). So the traced reads for `screener` (config.py:649) and `refresh_pit_panel` (config.py:808) predate it. I found no read of accruals/piotroski/promoter/forensic/smart_money/consensus tables in pit.py or tools/reconstruct_pit.py, so the refresh_pit_panel declared reads of those tables are stale (unverified at runtime).

#### 1. Annual-ratio tables (22) — one shape

Common to all 22 unless noted:
- **Grain / PK:** (sid, snapshot_date); PK = sid+snapshot_date.
- **Writer:** `signals/<m>.py compute()` → `_annual.save()` → signals/_annual.py:108 `upsert_df`.
- **Step:** `signal_<m>`, weekly (share_momentum is daily), config.py lines below.
- **Registry:** each backs exactly 1 FACTORS entry. All are **bench=LIBRARY, no weights**. The PIT twin is recomputed from `fundamentals_screener` by `pit.pit_<m>` into a daily_snapshots_pit column. The table itself is **not read by PIT or by the screener**.
- **Time:** snapshot_date = run date; `period_end` = fiscal year end of the latest annual row (NOT the knowable date).
- **Target:** Features (feature_values). The FV becomes the feature row. NIs become optional extra features, or are dropped because they are recomputable from fundamentals_screener. `period_end` becomes a provenance field on the value (or `source_period`), not a key.
- **Readers:** none live beyond those listed per row.

| table | step (config.py) | factor (factors.py) | rows / dates / sids | FV | NI | other readers |
|---|---|---|---|---|---|---|
| asset_tangibility_scores | signal_asset_tangibility :542 | asset_tangibility | 104,500 / 56 / 1,892 | asset_tangibility | — | none |
| capex_to_dep_scores | :527 | capex_to_dep | 76,240 / 56 / 1,418 | capex_to_dep | — | none |
| cash_conversion_cycle_scores | :454 | ccc | 74,168 / 56 / 1,326 | ccc | dso, dio, dpo | none |
| debt_structure_scores | :537 | debt_structure | 73,128 / 56 / 1,309 | debt_structure | — | none |
| dio_change_yoy_scores | :502 | dio_change_yoy | 93,992 / 56 / 1,713 | dio_change_yoy | — | none |
| dso_change_yoy_scores | :497 | dso_change_yoy | 100,468 / 56 / 1,831 | dso_change_yoy | — | none |
| fcf_margin_scores | :522 | fcf_margin | 74,880 / 56 / 1,400 | fcf_margin | — | none |
| fcf_yield_scores | :446 | fcf_yield | 82,034 / 68 / 1,249 | fcf_yield | fcf, market_cap_cr | cockpit_ops command-centre COUNT(DISTINCT sid) cockpit_ops/api.py:1250-1256,1332 |
| goodwill_to_assets_scores | :532 | goodwill_to_assets | 81,248 / 56 / 1,454 | goodwill_to_assets | — | none |
| gross_profitability_scores | :490 | gross_profitability | 64,422 / 45 / 1,470 | gross_profitability | gross_profit, total_assets | **signals/multibagger.py:319** (latest-per-sid) |
| interest_coverage_scores | :475 | interest_coverage | 91,184 / 56 / 1,688 | interest_coverage | — | none |
| inventory_turnover_scores | :558 | relative_turnover | 96,532 / 68 / 1,504 | relative_turnover | inventory_turnover, sector_p50 (a sector aggregate repeated per sid) | none |
| nwc_to_revenue_scores | :507 | nwc_to_revenue | 82,468 / 56 / 1,475 | nwc_to_revenue | — | none |
| operating_margin_trend_scores | :461 | margin_slope | 82,072 / 56 / 1,530 | margin_slope | margin_latest, margin_5y_avg | **signals/multibagger.py:320** |
| revenue_cv_scores | :552 | revenue_cv_5y | 108,803 / 68 / 1,713 | revenue_cv_5y | mean_growth, years_used (count/META); **no period_end** | none |
| roic_scores | :438 | roic | 103,346 / 68 / 1,623 | roic | nopat, invested_capital | **signals/multibagger.py:317**; cockpit_ops/api.py:1241-1247,1332 (count) |
| roiic_scores | :483 | roiic | 64,860 / 56 / 1,271 | roiic | delta_nopat, delta_ic | **signals/multibagger.py:318** |
| sales_growth_relative_scores | :564 | relative_growth | 114,383 / 68 / 1,757 | relative_growth | sales_growth, sector_median (sector aggregate) | none |
| sga_to_revenue_change_scores | :517 | sga_to_revenue_change | 99,266 / 56 / 1,786 | sga_to_revenue_change | — | none |
| share_momentum_scores | :570 (**daily**) | share_momentum | 207,588 / 140 / 1,512 | share_momentum | market_cap_cr, sector_share; **no period_end** | none |
| sloan_accruals_full_scores | :512 | sloan_accruals_full | 80,844 / 56 / 1,446 | sloan_accruals_full | — | none |
| working_capital_intensity_scores | :468 | wc_intensity | 74,168 / 56 / 1,326 | wc_intensity | — | none |

Surprises (annual group):
- **Not dead, but nearly consumer-less.** 17 of 22 tables have no reader except their own step's freshness tracking. Their numbers only reach research through daily_snapshots_pit, which is recomputed from raw. These are weekly writes of about 1.5k rows each that nothing reads. They are still produced by live cron steps, so they are not DELETE candidates by the "no writer" rule. The design point stands, though: the table is pure write-only history.
- **Multibagger consumes 4 of them live** (roic, roiic, gross_profitability, margin_slope) via `_latest()` = MAX(snapshot_date) per sid with no age cap (signals/multibagger.py:108-116). A sid that dropped out of scoring keeps its stale value forever.
- **sector_p50 / sector_median** are sector-level values stored per stock. In feature_values they would be entity=sector rows, or be dropped.
- **Duplicate sets.** cash_conversion_cycle_scores and working_capital_intensity_scores have identical row counts (74,168) and sid sets (1,326), because they share the same inputs. dso/dio are also computed inside CCC, and dso_change_yoy_scores/dio_change_yoy_scores are separate YoY deltas.

#### 2. The 13 non-annual tables

##### accruals_scores
1. Accruals quality. Backs **cf_accruals_ratio** (factors.py:170; **WIRED MID 0.22**, screener_col `accruals` ← replay_col `accruals_signal`), **bs_accruals_ratio** (:196, PROPOSED) and **earnings_persistence** (:210, PROPOSED). `accruals_signal` = PIT_EXTRA composite (factors.py:1781, within-tier percentile blend).
2. PK sid+snapshot_date; 193,392 rows; 79 dates (2026-04-09→09-27); 2,448 sids; full universe per date.
3. signals/accruals.py:316 upsert_df; step signal_accruals weekly (config.py:576).
4. Readers:
   - Screener: none since 4af1d6f (the old screener read accruals_signal directly: `git show bd7dc24:scoring/screener.py:112-114`); now pit.pit_accruals (pit.py:116).
   - Display: views._DISPLAY_SIGNAL_TABLES (views.py:200) → views.signals() → stock page (cockpit/api.py:792) + dossier prompt (output/dossier.py:240, :284 `accruals_signal`); output/snapshot.py:43 (cf/bs ratios → daily_snapshots); cockpit dominant-signal (cockpit/api.py:685).
   - Checks: checks/custom.py:396; health.py:782.
5. Columns: KEY sid, snapshot_date; FV cf_accruals_ratio, bs_accruals_ratio, earnings_persistence; FV(composite) accruals_signal. **All numeric.**
6. snapshot_date = run date, no lag. PIT-safe as an observation log.
7. **Features.**
8. The composite is a within-tier percentile, so it is cross-section-relative. That is why 32% of rows are distinct.

##### consensus_signals
1. Analyst consensus composite from `analyst_consensus` + prices.
   - Columns map loosely onto **pt_upside** (factors.py:1037, **BLOCKED**, screener_col pt_upside, replay_col None = display-only) and **eps_growth_yoy** (:298, VARIANT, screener_col eps_growth, replay_col None). But the eps_growth_yoy factor's PIT twin comes from quarterly_income (growth_fundamentals), a DIFFERENT quantity than consensus_signals.eps_growth (analyst forward growth).
   - `consensus_signal` has **no FACTORS entry**. The wired `consensus` weight (LARGE 0.28 / SMALL 0.16) is `consensus_signal_combined` = eps_revision_yoy from forecast_history (pit.py:494-511), not this column.
   - uhs_tables/freshness_table = consensus_signals for eps_growth_yoy and pt_upside (factors.py:310-311, 1051-1052).
2. PK sid+snapshot_date; 315,594 rows; 129 dates (2026-05-22→09-27); 2,448 sids.
3. signals/consensus.py:277 upsert_df, plus emit_lineage (signals/consensus.py:283 → signal_lineage); step signal_consensus daily (config.py:582).
4. Readers:
   - **Screener, still direct:** scoring/screener.py:123-127 (pt_upside, eps_growth, latest within 45d; unweighted display carried into pit_replay inputs_json). Also the integrity gate validate_picks (screener.py:449 → validators/per_stock_integrity.py:252-257, consensus_signal) can FAIL a pick.
   - UHS/health: scoring/health_score.py:69 (TIER_1 critical), :88 (freshness 1d), :626. trust_verdicts **source_table='consensus_signals' 111,204 rows**, written by sources/yfinance_analyst.py:315,323 and tools/trust_backfill.py:81-101,287-388. Also validators/cross_source.py:106, validators/plausibility.py:192, validators/unit_contract.py:39-45, lineage.py:112-120 (UNIT_CONTRACTS).
   - Display: views.py:200 → stock page + dossier (output/dossier.py:285-296: consensus_signal, pt_upside, eps_growth, revenue_growth); output/snapshot.py:47; cockpit dominant-signal cockpit/api.py:682.
   - Checks: checks/custom.py:150-159, 397, 514-536; health.py:788. Tools: tools/optimize_weights.py:63 (a comment/WIRED_KEYS list, not a read). Tests: tests/test_graph.py:17-18 (synthetic name only).
   - Quarantine mirror consensus_signals_quarantine (0 rows); tables.py:348 quarantine+mirror.
5. Columns: KEY sid, snapshot_date; FV pt_upside, eps_growth, revenue_growth, consensus_signal; NI pt_revision_1yr. All numeric.
6. Run date, no lag.
7. **Features**, plus a **DESIGN QUESTION**: trust_verdicts and signal_lineage key on the table NAME `consensus_signals`. In a long model they must key on feature_id, or on the upstream raw table `analyst_consensus`.
8. Surprises:
   - The **name collision "consensus"**: the cockpit "Consensus" badge, the dossier "Consensus Signal" and daily_snapshots.consensus_signal all show this table's PT/growth composite. The ranked "consensus" is eps_revision_yoy, a different quantity.
   - Until today the screener read consensus_signal into column `consensus`. pit_replay inputs_json for 2026-09-27 equals consensus_signals.consensus_signal in 992/992 rows.

##### financial_signal_scores
1. Banking/NBFC sub-model pillars. **financial_signal** (factors.py:1525, PROPOSED), **financial_quality** (:1538, LIBRARY), **financial_recovery** (:1550, PROPOSED). The PIT twin is computed from banking_metrics (pit.py:1445), not this table. Per CLAUDE.md/ADR 0048 it is dossier/display-only.
2. PK sid+snapshot_date; 17,202 rows; 122 dates (2026-05-29→09-27); 141 sids.
3. signals/financial_signal.py:418 upsert_df; step compute_financial_signal daily (config.py:642).
4. Readers:
   - Screener: no.
   - Display: cockpit/api.py:383-405 get_financial_management (stock_detail Management tab, cockpit/app.py:219; within-tier percentile over MAX(snapshot_date)).
   - Nothing else.
5. Columns:
   - KEY sid, snapshot_date.
   - Copies of `stocks` attributes: TEXT industry, cap_tier (META).
   - FV financial_signal, financial_quality, financial_recovery.
   - NI asset_quality_z, profitability_z, capital_z, funding_z, asset_quality_quality_z, asset_quality_recovery_z, gross_npa_pct, net_npa_pct, nii_margin_pct, np_margin_pct, cost_of_funds_pct (copies of banking_metrics), components_present (INT).
   - LBL score_basis, quality_basis, recovery_basis (enum AQ+P+F / P+F / AQ+P / INSUFFICIENT).
   - META computed_at.
6. Run date. PIT-safe as an observation.
7. **Features + label enum.** The basis labels are derivable from which components are non-null, so they can be dropped or coded as a small enum.
8. Surprises:
   - `financial_signal` ≡ `financial_quality` in all 17,202 rows (signals/financial_signal.py:373).
   - `score_basis` ≡ `quality_basis` ≡ `recovery_basis` in all rows. Two alias columns and two redundant labels.

##### forensic_scores
1. Beneish M + Altman Z″ distress. **m_score** (factors.py:449, PROPOSED) and **z_score** (:462, PROPOSED). `penalty` = PIT_EXTRA **forensic_penalty** (factors.py:1783), which is **live in ranking**: final_score = base + penalty (scoring/screener.py:259-261), now via pit.pit_forensic (pit.py:139).
2. PK sid+snapshot_date; 193,392 rows; 79 dates; 2,448 sids.
3. signals/forensic.py:387 upsert_df; step signal_forensic weekly (config.py:422).
4. Readers:
   - Screener: penalty via features_at (old screener read it directly, bd7dc24:134-136). **Integrity gate**: per_stock_integrity.py:280-284 (m_score) via screener.py:449.
   - Display: views.py:200 → stock page + dossier (output/dossier.py:305-311 m_score, m_score_flag, z_score, z_score_flag); cockpit/api.py:1167-1176 "forensic alerts" on top-20 picks (filters on flags); cockpit_ops/templates/sql_console.html:35 (canned query on flags).
   - Other: signals/multibagger.py:324 (m_score_flag → beneish gate); signals/management_quality.py:111-113 (penalty); checks/ranges.py:83-84; health.py:799. Tests: tests/test_checks.py:60,76.
5. Columns:
   - KEY sid, snapshot_date.
   - FV m_score, z_score, penalty (penalty = step fn of flags, 0/-0.1/-0.2/-0.3; signals/forensic.py:285-296).
   - **LBL m_score_flag** {CLEAN, POSSIBLE_MANIPULATOR, LIKELY_MANIPULATOR, NULL}.
   - **LBL z_score_flag** {SAFE, GREY_ZONE, DISTRESS, NULL}.
   - The flags are pure threshold functions of m_score / z_score (signals/forensic.py:263-283).
6. Run date.
7. **Features + label enum.** Two options: (a) store the flags as coded label features (0/1/2), or (b) derive them at read time from the catalog's thresholds. Readers of the text: cockpit alerts, the sql_console template, dossier, multibagger. The claim that "the TEXT can't collapse" is **refuted**: it collapses to an enum code with no information loss.
8. Surprises:
   - **Bug:** cockpit/api.py:1167-1176 joins forensic_scores with **no snapshot_date filter**. A flagged pick matches every one of its up to 79 historical rows, so the LIMIT 10 fills with duplicates of one stock, and flags from old snapshots leak in.
   - 17,179 rows with NULL m_score/z_score are filler.

##### insider_signals
1. Net-weighted insider buy/sell over 90 days. Backs **insider_signal** (factors.py:429, LIBRARY). The PIT twin `insider_score` is recomputed from insider_trades by pit.py:1153.
2. PK **sid+snapshot_date+signal_type**; 231,195 rows; 118 dates (2024-04-01→**2026-07-31**); 2,448 sids.
   - In practice there is exactly 1 row per (sid, date) (2,448 per date), so `signal_type` in the PK is vestigial.
   - History mixes monthly backfill rows (reconstruct_historical, signals/insider_signal.py:214-256, 1st of month) with daily live rows.
3. signals/insider_signal.py:207 (daily compute, writes all stocks with NEUTRAL filler) and :250 (manual backfill, non-neutral only); upsert_df. Step signal_insider daily (config.py:417).
4. Readers:
   - Screener: no.
   - Display: cockpit/api.py:190-197 get_insider_signal_batch (via views.latest_rows) → stock_detail.html:999-1007 (renders signal_type + description) and action_queue enrichment cockpit/app.py:176-184 (`insider_desc`, which I could not find rendered in action_queue.html → dead there); cockpit dominant-signal cockpit/api.py:686 (score_impact).
   - Checks: health.py:816. views.py:200 lists it, but views.signals() de-dupes by column name.
   - Tests: tests/test_views.py:111-112.
5. Columns:
   - KEY sid, snapshot_date.
   - FV score_impact.
   - LBL signal_type {STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL} and LBL strength {strong, moderate, weak}. Both are threshold functions of score_impact, and strength is fully determined by signal_type (signals/insider_signal.py:130-145).
   - **NAR description**: templated "Director sold ₹6051L; …" from insider_trades aggregates (:112-122). It contains numbers but is not LLM output.
6. Run date for live rows, eval date for backfill rows. PIT-safe.
7. **Features + label enum.** signal_type becomes an enum code (or is derived from score_impact). Drop `strength`. `description` is a rendering of insider_trades (event table); regenerate it at read time from insider_trades rather than storing it. The claim that "the TEXT can't collapse" is **partly true**: only `description` is text with content, and that content is reconstructible from events.
8. Surprises:
   - **Stale since 2026-07-31.** signal_insider FAILS daily with "0 insider trades in last 90d (latest 2026-05-02)" (pipeline_log 2026-09-27 05:18 and 15:30). insider_trades now holds 4,165 rows after 2026-05-02 (max trade_date 2026-09-25), inserted after 15:30 by the nse_insider fix. It should recover on the next run.
   - 92% of rows are NEUTRAL filler.

##### management_scores
1. Management-quality scorecard (3 pillars: capital allocation, alignment, credibility). **No FACTORS entry** (diagnostic).
2. PK sid+snapshot_date; 1,609 rows; **1 date (2026-06-06)**.
3. signals/management_quality.py:174 upsert_df. **No PIPELINE_STEPS entry, no cron, no run.sh case**: manual only (`python -m signals.management_quality`).
4. Readers:
   - Screener: no.
   - Display: cockpit/api.py:308 get_management_score → cockpit/app.py:217 → stock_detail.html:150-160 (grade, score, pillars).
   - Nothing else. signals/managerial_ability.py:41,104 mentions it in comments only (unverified as a read; grep shows docstring text).
5. Columns:
   - KEY sid, snapshot_date.
   - META cap_tier (copy of stocks).
   - FV mgmt_quality_score, mgmt_quality_z.
   - NI capital_allocation_z, alignment_z, credibility_z, and **copies** of other features: roic, roiic, fcf_margin, promoter_trend (already coded -1/0/+1 REAL), pledge_quality, promoter_signal, f_score, accruals_quality, forensic_penalty.
   - META n_pillars, computed_at.
   - **LBL grade** {A+, A, B, C, D}, a function of the score percentile.
6. snapshot_date = max(input table dates) (signals/management_quality.py:122). It mixes a daily_snapshots_pit anchor (pillar A: roic/roiic/fcf_margin read from **daily_snapshots_pit**, :90-98) with the latest live tables. The as-of date is mixed.
7. **Features + label enum** (grade derivable). Alternatively a **DESIGN QUESTION**: it is a frozen one-shot, so decide whether to schedule it or retire it. It is not DELETE-eligible, because it has a live cockpit reader.
8. Surprise: this is the only producer that already encodes promoter_trend TEXT→ordinal (:119-121). That is the pattern for label enums.

##### managerial_ability_scores
1. Demerjian-Lev-McVay managerial ability (DEA frontier + Tobit residual). **No FACTORS entry** (diagnostic only).
2. PK sid+snapshot_date; 1,736 rows; **1 date (2026-06-09)**.
3. signals/managerial_ability.py:422 upsert_df. **No step / cron**: manual only.
4. Readers: cockpit/api.py:354 get_managerial_ability → cockpit/app.py:218 → stock_detail.html:203-215. Nothing else.
5. Columns:
   - KEY sid, snapshot_date.
   - META cap_tier, sector (copies).
   - **LBL frontier_group** (industry/sector peer-group name; 3 rows empty).
   - META period_end.
   - FV ma_score, ma_residual, dea_efficiency.
   - **LBL grade**.
   - NI sales, cogs, employee_cost, net_block, intangibles, total_assets (copies of fundamentals).
   - META n_peers, computed_at.
6. Run date; period_end = fiscal.
7. **Features + label enum.** frontier_group is a peer-group dimension: store it as an entity attribute or group id, not as a feature. Same one-shot question as management_scores.
8. None beyond the one-shot status.

##### multibagger_scores
1. Multibagger funnel (gates → hurdles → pillar percentiles), with a regime gate. **No FACTORS entry.**
2. PK sid+snapshot_date; 31,878 rows; 19 dates (2026-06-03→09-27, weekly); 1,737 sids.
3. signals/multibagger.py:361 upsert_df; step signal_multibagger weekly (config.py:606).
4. Readers: cockpit/api.py:1497-1502 get_multibagger_overview (latest date only) → cockpit/app.py:387 → multibagger.html (gate_fail/hurdle_fail tallies, regime banner). Nothing in screener/PIT.
5. Columns:
   - KEY sid, snapshot_date.
   - META cap_tier, mcap_cr.
   - Flags (INT): survived, passed_gates, passed_hurdles, regime_favorable.
   - **LBL gate_fail** (comma-set over {beneish, pledge, debt}).
   - **LBL hurdle_fail** (comma-set over {mcap, roic, fscore, growth, promoter}).
   - NI (copies of other features): de_ratio, pat_cagr_3y, earnings_acceleration, ep_yield, peg, gross_profitability, roic, roiic, margin_slope, f_score, promoter_pct, pledge_pct, smart_money_score.
   - **LBL m_score_flag** (a copy of forensic's).
   - FV p_quality, p_growth, p_conviction, interaction, multibagger_score, rank_in_tier.
   - **LBL smallcap_regime** (market-level, repeated per row; values UPTREND or NULL seen).
6. Run date. The inputs are latest-per-sid with no age cap, so the as-of is fuzzy.
7. **Features + label enum.** gate_fail/hurdle_fail are sets of reasons. Encode them as one 0/1 feature per gate/hurdle, or as a bitmask. smallcap_regime belongs in a market-level (entity=market) series, not per stock. Drop the copied inputs; they are the other features. The claim that "the TEXT can't collapse" is **refuted**: it is all enumerable.
8. **BUG:**
   - p_conviction takes `_pctile(promoter_trend)` on the TEXT label (signals/multibagger.py:285, loaded at :323). pandas ranks strings lexicographically: ACCUMULATING=0.25 < MIXED=0.5 < REDUCING=0.75 < STABLE=1.0 (verified). So promoter **accumulation is scored as the worst conviction** and reduction beats it. The weekly score is live on the cockpit multibagger page.
   - multibagger_score is NULL in 31,541/31,878 rows (only survivors are scored).

##### nlp_scores
1. Loughran-McDonald tone/uncertainty/forward-looking per earnings-call transcript. Input to **earnings_call_tone_qoq** (factors.py:933), **forward_looking_intensity** and **uncertainty_word_density**, all LIBRARY. The factor math is in signals/nlp_factors.py via pit.pit_nlp_factors (pit.py:1001-1018).
2. PK **sid+doc_type+doc_date** (document grain, not sid-date); 15,031 rows; doc_type='transcript' only; doc_date 2005-08-01→2026-06-01; 906 sids; computed_at is a single value 2026-06-14.
3. signals/nlp_scores.py:139-141 **INSERT OR REPLACE**. **No step / cron**: manual `python -m signals.nlp_scores`. sources/transcripts_pull.py only mentions it.
4. Readers:
   - **PIT: pit.RAW_SQL["nlp"]** (pit.py:1505) → reconstruct_pit (refresh_pit_panel weekly, config.py:805) → daily_snapshots_pit (earnings_call_tone_qoq etc.). Also signals/nlp_factors.py.
   - Screener: no, because the nlp columns are not in PIT_TO_SCREENER_COLS.
   - Metadata: lineage.py:804-818.
5. Columns:
   - KEY sid, doc_type, doc_date.
   - META available_date (look-ahead-safe filing date, COALESCE(bse_filing_date, announce_date, doc_date), signals/nlp_scores.py:41), computed_at.
   - NI word_count, lm_positive, lm_negative (counts).
   - FV net_tone, uncertainty_density, forward_looking_intensity.
   - **All numeric; no TEXT content.**
6. available_date is the knowable date (good). But 96 rows have available_date more than 31 days before doc_date, including 3 before 2015 (BEML doc 2024-05 → available 1964-05-11). These are bad filing-date joins. Leakage is bounded by the FRESH_DAYS filter in compute_nlp_factors (unverified in detail).
7. **Features + Documents.** These are per-document measurements. Store them as feature rows on entity=document (transcript id), with available_date as the as-of, or as document attributes. The per-stock factor is then derived. The claim that nlp_scores "has TEXT that can't collapse" is **refuted**. The real issue is the **grain** (document vs sid-date), not text.
8. It is a frozen one-shot input to a weekly PIT step, so new transcripts never get scored unless someone runs it by hand.

##### piotroski_scores
1. Piotroski F-score. Backs **piotroski_f_score** (factors.py:144; **WIRED MID 0.18 / SMALL 0.06**; screener_col f_score ← replay_col piotroski_f). uhs_tables for earnings_yield, book_to_price, piotroski, cf_accruals (factors.py:92,116,159,185); freshness_table (:160).
2. PK sid+snapshot_date; 176,213 rows; 79 dates; 2,448 sids.
3. signals/piotroski.py:335 upsert_df, plus emit_lineage :341; step signal_piotroski weekly (config.py:428).
4. Readers:
   - Screener: via pit.pit_piotroski since 4af1d6f (old direct read bd7dc24:107-110). **Integrity gate** per_stock_integrity.py:271-276 (f_score range).
   - **Tier assignment:** tools/classify_micro_tier.py:55 `MAX(f_score) … GROUP BY sid` over ALL history (step classify_micro_tier daily, config.py:816).
   - UHS: scoring/health_score.py:70,89,627 (TIER_1 + freshness 30d); trust_verdicts source_table='piotroski_scores' 1,979 rows (validators/plausibility.py:55; tools/trust_backfill.py:88-113,392).
   - Display: views.py:200 → stock page + dossier (output/dossier.py:283); output/snapshot.py:39; cockpit dominant-signal cockpit/api.py:684.
   - Other: signals/multibagger.py:321; signals/management_quality.py:106-108; checks/custom.py:282-295,395; checks/ranges.py:79; health.py:777; lineage.py:153.
5. Columns: KEY sid, snapshot_date; FV f_score; NI 9 binary components (roa_positive, cfo_positive, roa_improving, accruals_quality, leverage_down, liquidity_up, no_dilution, gross_margin_up, asset_turnover_up; INTEGER 0/1). All numeric.
6. Run date.
7. **Features.** Components become 9 extra 0/1 features, or are dropped because they are recomputable. **DESIGN QUESTION**: trust_verdicts, signal_lineage and health_score key on the table name `piotroski_scores`.
8. Surprises:
   - classify_micro_tier uses the **best-ever** f_score, not the latest. It is a live tier gate that would read a whole feature's history in the long model.
   - The dominant-signal display (cockpit/api.py:708-718) sorts by |value| across mixed scales (f_score 0-9 vs 0-1 composites), so Piotroski almost always "dominates".

##### promoter_signals
1. Promoter holding change + pledge. Backs **promoter_qoq** (factors.py:378, VARIANT; weight_key promoter ← replay_col **promoter_signal** = PIT_EXTRA :1782, unweighted) and **pledge_quality** (:413, **WIRED SMALL 0.10**, PIT producer `pledge`). promoter_trend_4q (:402, PROPOSED) is computed inside the same module but **not stored** here (signals/promoter.py:98, dropped at :164).
2. PK sid+snapshot_date; 193,392 rows; 79 dates; 2,448 sids.
3. signals/promoter.py:189 upsert_df; step signal_promoter weekly (config.py:589).
4. Readers:
   - Screener: via pit (pit.py:129, 230) since 4af1d6f (old direct read bd7dc24:129-131).
   - Display: views.py:200 → stock page + dossier (output/dossier.py:297-304 promoter_qoq, promoter_trend TEXT, pledge_quality); output/snapshot.py:51; cockpit dominant-signal cockpit/api.py:683.
   - Other: signals/multibagger.py:323 (pledge_quality, **promoter_trend TEXT**); signals/management_quality.py:100-103 (maps TEXT→ordinal :119-121); checks/custom.py:398; health.py:794.
5. Columns:
   - KEY sid, snapshot_date.
   - FV promoter_qoq, pledge_quality, promoter_signal.
   - **LBL promoter_trend** {ACCUMULATING, STABLE, MIXED, REDUCING, NULL}, a threshold label over the unstored numeric promoter_trend_4q (signals/promoter.py:143-159).
6. Run date. Shareholding has a quarterly cadence, so values are re-stamped weekly.
7. **Features + label enum.** Store promoter_trend_4q numerically (it is already a PIT column) and derive or code the label. This table **should be added to the "TEXT" list**: its label is consumed numerically (and wrongly) by multibagger.
8. The multibagger lexicographic-rank bug (see multibagger_scores).

##### sentiment_scores
1. VADER news sentiment per stock. Maps loosely onto **sentiment_7d** (factors.py:1114, PROPOSED). But the PIT twin pit_sentiment_7d (pit.py:1121-1150) is a **separate VADER implementation**, not the same compute function as signals/sentiment.py. That violates the CLAUDE.md "one compute function" rule. Values agree only by construction of the same lexicon (unverified numerically).
2. PK sid+snapshot_date; 378,837 rows; 193 dates (2026-03-15→09-27); 2,448 sids.
3. signals/sentiment.py:134 upsert_df; step signal_sentiment daily (config.py:412).
4. Readers:
   - Screener: no.
   - **History reader:** signals/sector_breadth.py:104-106 (sentiment_30d, articles_30d, all dates → sector_sentiment_breadth_pit; step sector_sentiment_breadth monthly, config.py:375).
   - Display: views.py:200 → dossier (output/dossier.py:314-315 sentiment_7d, articles_7d); output/snapshot.py:59.
   - Checks: checks/ranges.py:85; health.py:811.
5. Columns: KEY sid, snapshot_date; FV sentiment_today, sentiment_7d, sentiment_30d, sentiment_momentum; NI articles_today, articles_7d, articles_30d (counts); **TEXT latest_headline**.
6. Run date. The windows are relative to `date.today()` (signals/sentiment.py:49).
7. **Features.** Drop latest_headline: it has no reader, and headlines already live in news_articles (documents).
8. **BUG:** `latest_headline` stores `str(latest.get("sentiment"))` (signals/sentiment.py:97), i.e. the latest article's compound SCORE as text ("0.6124"), not a headline. It is NULL/empty in 254,583 rows. It is not real text at all.

##### smart_money_scores
1. Bulk-deal + delivery accumulation composite (0-100). Backs **smart_money_score** (factors.py:493, VARIANT; weight_key smart_money, unweighted).
2. PK sid+snapshot_date; 369,648 rows; 151 dates (2026-04-09→09-27); 2,448 sids.
3. signals/smart_money.py:192 upsert_df; step signal_smart_money daily (config.py:594).
4. Readers:
   - Screener: via pit.pit_smart_money (pit.py:155) since 4af1d6f (old direct read bd7dc24:139-141).
   - Display: views.py:200 → dossier (output/dossier.py:312); output/snapshot.py:55.
   - Other: signals/multibagger.py:322; checks/custom.py:399-426 (the 50.0 default-leak check); health.py:805.
5. Columns: KEY sid, snapshot_date; FV smart_money_score; NI bulk_score, delivery_score (components), net_buy_qty, buy_deals, sell_deals, repeat_buyers (counts). All numeric.
6. Run date.
7. **Features.**
8. Scale mismatch: the screener divides by 100 (scoring/screener.py:139). The stored value is 0-100 while other composites are 0-1. The catalog must carry the unit.

#### Cross-cutting

**How the live screener gets each factor today.**
- **Ranking inputs.** `_load_signals` computes every factor as `pit.features_at(t, pit_cols)` (scoring/screener.py:107-118, pit.py:1574-1583):
  - pit_cols = factors.PIT_TO_SCREENER_COLS minus consensus_signal_combined.
  - features_at runs pit.PIT_PRODUCERS on **raw** frames from pit.RAW_SQL (pit.py:1477-1506): quarterly_income, annual_*, shareholding, stock_prices, bulk_deals, forecast_history, fno_iv_history, bse_announcements, macro_*, etc.
  - This covers piotroski_f, accruals_signal, promoter_signal, pledge_quality, smart_money_score and forensic_penalty (pit.py:107-155, 230). **No `*_scores` table is an input to features_at, except nlp_scores** (RAW_SQL["nlp"], which the screener doesn't request).
- **Direct `*_scores` reads that remain on the screener path:**
  - (a) consensus_signals: pt_upside and eps_growth display columns (scoring/screener.py:123-127, unweighted).
  - (b) validate_picks integrity gate (scoring/screener.py:449 → validators/per_stock_integrity.py:252-284) reads consensus_signals.consensus_signal, piotroski_scores.f_score and forensic_scores.m_score (latest date). It can FAIL a pick out of the action queue.
  - (c) Upstream of the screener: classify_micro_tier reads piotroski_scores MAX(f_score) over all history (tools/classify_micro_tier.py:55) to set tiers. compute_health_score and UHS read consensus_signals/piotroski_scores freshness and trust_verdicts keyed by those table names.
- **Timing caveat:** the features_at switch is commit 4af1d6f, 2026-09-27 06:31 UTC. **Every daily_picks row up to and including 2026-09-27 was produced by the old screener**, which read piotroski/accruals/consensus/promoter/forensic/smart_money `*_scores` directly (latest-per-sid within max age; `git show bd7dc24:scoring/screener.py:107-141`). Tomorrow's run is the first on features_at.

**reconstruct_pit write rule.**
- tools/reconstruct_pit.py:249-258 calls `reconstruct_one_date` and then `upsert_df(df, "daily_snapshots_pit")`.
- The rule lives in pit.py:1426-1438 (`cols_to_emit = [c for c in PIT_COLUMNS if c in base.columns]`: only the columns the requested producers produced, never NaN-padded). Combined with db.upsert_df's column-level ON CONFLICT DO UPDATE (db.py:582-589), an UPDATE touches only those columns.
- In long `feature_values(feature_id, date, entity_id, value, run_id)` the rule becomes **structural: confirmed**. A producer writes only rows for its own feature_ids, so "untouched columns" don't exist, and nothing can wipe another producer's values.
- One caveat replaces it: a re-run must **replace the whole (feature_id, date) slice**, via DELETE-then-insert or run_id versioning. Otherwise a sid that now evaluates to NaN keeps its stale old row. Today that case is handled by writing NULL into the wide column (reconstruct_pit.py:257, `astype(object).where(notna, None)`). Out-of-range values → NaN (`_validate_and_clean`) need the same treatment: write NULL or delete.

**"Value used for the pick on date D" — recoverable?**
- **Exact.** pit_replay_snapshots.inputs_json holds every screener input column per sid per date. It is written daily by pit_replay_freeze (tools/pit_replay.py:123-185, INSERT OR REPLACE), 131 dates 2024-09-02→2026-09-27, with historical dates backfilled from daily_snapshots_pit. It is JSON in one TEXT column, keyed by screener column name, and it is the only exact record after 4af1d6f.
- **Before 2026-09-28**, the wired inputs also exist in the `*_scores` history: f_score, accruals_signal, promoter_signal, pledge_quality, smart_money_score, penalty, consensus_signal/pt_upside/eps_growth. Because history is kept (upsert per snapshot_date, never overwritten across dates), the row with max snapshot_date ≤ D is what the old screener used. 992/992 consensus values reconcile with inputs_json on 2026-09-27.
- **From 2026-09-28**, `*_scores` rows are no longer what the screener used: features_at applies filing lags and recomputes from raw. Only pit_replay_snapshots holds the exact value. daily_snapshots_pit holds it only on monthly/Friday anchors, and even there it is recomputed, so a restated raw table silently changes it.
- The annual-ratio tables were never screener inputs.
- A feature_values table written by the live screener with run_id is the natural replacement for inputs_json.

**The "5 TEXT tables" claim.** Verified column-by-column:
- **insider_signals**: TRUE, but narrow. Only `description` is content-bearing text, and it is a template over insider_trades (regenerable). signal_type/strength are enums derived from score_impact.
- **forensic_scores**: FALSE as "can't collapse". The flags are threshold enums of m_score/z_score.
- **nlp_scores**: FALSE. It has no text columns at all. The problem is document grain, not text.
- **multibagger_scores**: FALSE as "can't collapse". gate_fail/hurdle_fail are reason SETS (→ 0/1 features), smallcap_regime is a market-level enum, and m_score_flag is a copy.
- **management_scores**: only `grade` (enum from the score); promoter_trend is already numeric.
- **Add:**
  - promoter_signals.promoter_trend: an enum, and the one actually mis-consumed (the multibagger bug).
  - financial_signal_scores: score_basis/quality_basis/recovery_basis enums (identical), plus industry/cap_tier copies.
  - managerial_ability_scores: grade, frontier_group (a peer-group dimension), sector/cap_tier copies.
  - sentiment_scores.latest_headline: a TEXT column that holds a number (a bug), with no reader.
- **Net: in this slice no column needs a documents store except insider_signals.description**, which should be regenerated from events rather than stored. Every other TEXT column is an enum label, derivable from a numeric feature, or a copied entity attribute.

#### Slice summary

- All 35 tables are history keyed by (sid, snapshot_date = run date), except nlp_scores (document grain) and insider_signals (vestigial signal_type in PK). Every writer upserts with no lag. About 97% of annual-ratio rows are re-stamps of unchanged values.
- **Live ranking reads none of them since today's commit 4af1d6f.** features_at recomputes from raw. Still on the live path: consensus_signals (display cols + integrity gate), piotroski_scores and forensic_scores (integrity gate), piotroski_scores MAX(f_score) (MICRO tier gate), and consensus/piotroski as table-name keys in trust_verdicts, signal_lineage and UHS (DESIGN QUESTION: re-key to feature_id).
- **Historical picks through 2026-09-27 came from the old screener reading 6 `*_scores` tables directly.** Keep that history for replay. pit_replay_snapshots.inputs_json is the only exact per-pick record going forward.
- **Targets:**
  - Features: all 22 annual-ratio tables, plus accruals, consensus, piotroski, smart_money and sentiment.
  - Features + label enum: forensic, promoter, insider, multibagger, financial_signal, management, managerial_ability.
  - Features + Documents (grain): nlp_scores.
  - DELETE: none. Every table has a live writer or a live cockpit reader. management, managerial_ability and nlp_scores are manual one-shots, so decide whether to schedule or retire them.
- **Bugs found:**
  1. multibagger ranks promoter_trend TEXT lexicographically (accumulation scored worst), signals/multibagger.py:285.
  2. cockpit forensic alerts have no snapshot_date filter (duplicates and stale flags), cockpit/api.py:1167.
  3. sentiment latest_headline stores the score, not a headline, signals/sentiment.py:97.
  4. insider_signals stale since 07-31 (feed now fixed).
  5. financial_signal ≡ financial_quality, and the three *_basis columns are identical.
  6. nlp available_date is bogus for 96 rows.
  7. pit_sentiment_7d is a second VADER implementation.
- The "5 TEXT tables" list is mostly wrong. Only insider_signals.description is real text, and it is regenerable. Add promoter_signals, financial_signal_scores and managerial_ability_scores as label-enum tables.
- Long feature_values makes the reconstruct_pit column rule structural. Its replacement rule is "a re-run replaces the whole (feature_id, date) slice".

## Appendix D — backtest panel, research, ops


Auditor D, read-only, 2026-09-27. DB read via `mode=ro`. "rowid≈" = MAX(rowid) (the lead has the exact row counts).
Crontab (verified `crontab -l`): morning 03:30 (`run.sh morning` → pipeline.py + duckdb_refresh), forward 14:00, watchdog 15:00, health 04:00, pt_snapshot 1st, **backtest 2nd 05:15 (`tools.backtest_pit`)**, expected_return 1st, screener_*, tickertape. Nothing else in my slice has its own cron line.

---

#### Backtest (PIT)

##### daily_snapshots_pit
1. Concept: wide PIT feature panel, one column per factor/sub-factor + the 20d forward-return label, per (stock, anchor date).
2. Grain: sid × anchor date (monthly first-biz-day since 2019-12-02 + Fridays; 202 distinct dates, max 2026-09-25). PK (sid, snapshot_date). rowid≈614k. Indexes idx_pit_date, idx_pit_tier.
3. Write: `upsert_df` (column-level upsert) at tools/reconstruct_pit.py:258; DDL generated from `factors.PIT_COLUMNS` at reconstruct_pit.py:27-37. Step `refresh_pit_panel` (config.py:804-810, weekly, runs inside `run.sh morning`); also watchdog heals + manual `python -m tools.reconstruct_pit`.
4. Readers:
   - Live ranking path: NONE. The screener takes features from `pit.features_at(today)` (scoring/screener.py:103-116), which computes from raw tables via `pit.load_raw` RAW_SQL (pit.py:1536-1550). pit.py mentions of the table (pit.py:7, 1456, 1468) are docstrings.
   - Semi-live display: signals/management_quality.py:92-97 (Pillar A = latest anchor with roic; manual CLI only, not in PIPELINE_STEPS; writes management_scores).
   - PIT/backtest: tools/backtest_pit.py:290 (`SELECT *` whole table → pandas); tools/promotion_gate.py:178 (`SELECT *`); tools/ic_decay.py:137 (`SELECT *`); tools/factor_decay.py:42 (one column + label per tier); tools/factor_marginal.py:181; tools/risk_decomp.py:59; tools/rank_localization.py:114,124; tools/factor_correlation.py:96 (per tier); tools/expected_return.py:128 (SQL aggregate, monthly cron); tools/pit_replay.py:126-136 (historical freeze mode).
   - Cockpit: cockpit/api.py:1745-1752 `get_group_factor_means` (`SELECT pit.*` for latest anchor, JOIN stocks; route cockpit/app.py:271); cockpit_ops/api.py:253-262 `_coverage` per column via **DuckDB** `read_sql_fast`; :345-354 date/sid counts (DuckDB); :613-657 `get_factor_health` per-column latest-date subqueries (SQLite); :1299 COUNT DISTINCT sid; :1496, :1696 static description lists (stale text: "7 monthly dates × 26 signals").
   - Health: generic typeof scan (health.py:~490-500 comment names this table).
   - Tests: tests/test_registry_renames.py:13-35 (rename migration, factors.RENAME_PANEL factors.py:2199).
5. Time: snapshot_date (as-of), reconstructed_at (write time). PIT-safe by construction for factor columns (filing lags 75/60/21d, pit.py:10-14); `fwd_return_20d` is a forward label (look-ahead by design, only for evaluation). Known survivorship bias: current sids only (tools/backtest_pit.py:25-35).
6. TEXT: only sid, snapshot_date, cap_tier, reconstructed_at. All values REAL/INTEGER → fits numeric long table perfectly.
7. Target: **Features** (`feature_values`, run_id = reconstruct run; history in Parquet/DuckDB). `fwd_return_20d` → Decisions/outcomes or a label feature; cap_tier → Reference `security_tiers` (valid_from/valid_to).
8. Surprises: (a) Every backtest tool loads the full ~614k×109 table into pandas via SQLite `read_sql`, not DuckDB (only cockpit_ops uses the replica). (b) Live and backtest share compute code, but NOT storage: live never writes today's feature row to the panel — the panel only gets today's values on the next weekly refresh.

##### daily_snapshots_pit_v1
1. Concept: frozen v1 PIT panel (13 signals + fwd_return_20d), the C13b evidence base.
2. Grain: sid × monthly anchor (35 dates, 2023-04-03 → 2026-02-02). PK (sid, snapshot_date). rowid≈60k.
3. Write: none live. Importer moved to _archive/tools/import_v1_pit.py (tables.py:502 still points to tools/import_v1_pit.py, which is gone).
4. Readers: tools/backtest_pit.py:289 (`SELECT *`, source 'v1_archive' for monthly factors — iter_panels :261-263); tools/promotion_gate.py:177; tools/ic_decay.py:136; tools/walk_forward.py:113 (v1 only); cockpit_ops/api.py:236,280 (coverage via DuckDB), :326 (DuckDB count), :345, :1497, :1697 (static lists).
5. Time: snapshot_date, imported_at. PIT as v1 built it.
6. TEXT: ticker, cap_tier, sector (denormalised identifiers) — drop in long form.
7. Target: **Features** with run_id='v1_archive' (or a Parquet archive + DuckDB view); readers switch to feature_values filtered by run. See Cross-cutting.
8. Surprises: uses `eps_cv` where v2 has `earnings_persistence` (factors pit_column_v1 map). Stores ticker/sector/price copies.

##### factor_horizon_gate
1. Concept: per-factor×tier net-of-cost evidence at natural horizon + verdict (PROMOTE/LIBRARY/REJECT).
2. Grain: signal × cap_tier. PK (signal, cap_tier). 245 rows.
3. Write: `upsert_df` tools/promotion_gate.py:320 (DDL :78). Manual only (`python -m tools.promotion_gate`) — no step, no cron. Single computed_at 2026-06-02 → ~4 months stale.
4. Readers: cockpit_ops/api.py:1081-1083 (command centre horizon-gate tile); factors.py:2200 (RENAME_EVIDENCE); tests/test_registry_renames.py:17.
5. Time: computed_at only (no as-of/run). Not PIT-relevant.
6. TEXT/JSON: ir_curve_json (horizon→IR dict), verdict, source, cadence.
7. Target: **Research** (`factor_tests`, test_kind='horizon_gate', curve in a JSON payload or child rows).
8. Surprise: stale evidence surface displayed as current on the cockpit.

##### historical_universe
1. Concept: true historical NSE listing (incl. delisted) per bhavcopy date, with the close/delivery on that day.
2. Grain: bhavcopy date × NSE symbol. PK (snapshot_date, symbol). rowid≈17.7k; 2018-04-02 → 2026-05-29.
3. Write: `INSERT OR REPLACE` tools/build_historical_universe.py:140. Manual only (network, not a step, not cron).
4. Readers: tools only — tools/multibagger_cohort.py:157-165; tools/survivorship_exposure.py:14-61. backtest_pit.py:34 is a docstring. No cockpit, no live.
5. Time: snapshot_date (actual bhavcopy day), requested_date (anchor). PIT-safe (observed that day).
6. TEXT: symbol, series (fine as attributes).
7. Target: **Reference** — `securities` (incl. dead ones, symbol history) + membership by date (`security_tiers`/universe valid_from/valid_to); close/delivery_pct belong in prices.
8. Surprise: sid NULL for delisted = the exact "security master for dead names" the reference layer lacks.

##### macro_sector_signals_pit
1. Concept: per-sector regulatory + macro score as of an anchor date.
2. Grain: sector × anchor date. PK (sector, snapshot_date). rowid≈891; 2022-08-01 → 2026-09-25.
3. Write: `upsert_df` tools/reconstruct_pit.py:311 (producer `sector_overlays`, factors.py:1879), same step `refresh_pit_panel` (config.py:809 writes, lagged_write).
4. Readers:
   - **Live ranking path**: pit.py:1496 RAW_SQL["macro_sector"] → pit.pit_sector_tilt (pit.py:736-760) → `sector_tilt` factor, WIRED (weights LARGE 0.22 / SMALL 0.16) → screener (config.py:649 reads). Also signals/sector_tilt.py:130-136 when called standalone.
   - Backtest: tools/sector_signal_lab.py:180-182, tools/sector_tilt_validation.py:73, tools/factor_correlation.py:81 (comment).
   - Cockpit: cockpit_ops/api.py:1469 (static list). lineage.py:616 (lineage map).
5. Time: snapshot_date, reconstructed_at. PIT safety depends on macro_history.date / regulatory published_at slicing (reconstruct_pit.py:289-290). Whether macro_history.date is a release date or a period date is **unverified** — potential look-ahead in macro_score.
6. TEXT: none besides sector.
7. Target: **Features** with entity = sector (feature_values.entity_id = sector id), or derived on read.
8. Surprise: a table in the "Backtest" domain is in fact a live input to a weighted factor, refreshed only weekly.

##### pit_ic_by_tier_v1
1. Concept: v1's IC/t-stat/verdict per signal×tier (frozen import).
2. Grain: signal × cap_tier. PK (signal, cap_tier). 30 rows, imported 2026-05-03.
3. Write: none (importer archived).
4. Readers: only cockpit_ops/api.py:1498 (static data-model list → PRAGMA table_info + count). No code reads its values. The same v1 evidence is also in pit_ic_by_tier_v2 source='v1_archive' (36 rows).
5. Time: imported_at.
6. TEXT: description, verdict.
7. Target: **DELETE** (no writer, no reader of values; duplicated by v2 v1_archive rows). Archive CSV if wanted.
8. —

##### pit_ic_by_tier_v2
1. Concept: backtest evidence — IC/ICIR/t/CI/verdict per signal × tier × source/cadence variant.
2. Grain: signal × cap_tier × source ('v1_archive', 'v2_recompute', 'v2_recompute:weekly+NW{3,4,13}'). PK (signal, cap_tier, source). rowid≈339.
3. Write: `upsert_df` tools/backtest_pit.py:331. Cron `run.sh backtest` (2nd of month 05:15).
4. Readers:
   - Cockpit: cockpit_ops/api.py:175-193 `best_ic_by_signal` (the one ranking rule) → roster :249, factor health :611, command centre :1264; :1389 factor library; templates cockpit_ops/templates/command.html:383, system.html:1010, cockpit/templates/model_variants.html:48 (text).
   - Tools: tools/optimize_weights.py:71-78 (→ `--variant` weights, cockpit variants page); tools/multiple_testing.py:47; tools/expected_return.py:100 (monthly cron); tools/verify_factor_library.py.
   - Registry: factors.py:2200 RENAME_EVIDENCE. Tests: tests/test_registry_renames.py:15,44,47; tests/test_schema.py:26.
5. Time: computed_at — **only set on first INSERT** (upsert_df never updates it; backtest_pit doesn't pass it). Max computed_at 2026-07-11 although the cron wrote 317 rows on each monthly run (output/backtest_refresh.log). No as-of / run id / sample window.
6. TEXT: verdict, source (source also encodes cadence+NW lag as a string).
7. Target: **Research** (`factor_tests`: factor_id, tier, test_kind, panel/run, window, n, ic, t, ci, verdict, computed_at).
8. Surprises: stale-looking timestamps; duplicate (signal,tier) hypotheses across sources — every reader re-implements "dedupe by max n_periods / prefer v2" (optimize_weights.py:68-75, multiple_testing.py:47-50, api.py:175).

##### pit_reconstruction_log
1. Concept: per-eval-date run log of reconstruct_pit.
2. Grain: one row per (invocation × eval date). PK id. rowid≈2,341 (SUCCESS 2,316 / FAILED 20 / RUNNING 5 orphaned).
3. Write: INSERT RUNNING (reconstruct_pit.py:218-222) then UPDATE to SUCCESS/FAILED (:233-238, :266-270). Step `refresh_pit_panel` + manual.
4. Readers: tools/reconstruct_pit.py:152-156 (`--skip-existing` only; refresh() doesn't use it); cockpit_ops/api.py:1500 (static list).
5. Time: eval_date, started_at, finished_at.
6. TEXT/JSON: signals_run (comma list), validation_summary (JSON per-column valid/nan/out_of_range/min/max), error_message.
7. Target: **Ops** — `step_runs` child (sub-run keyed by eval_date) + validation_summary → `check_results`.
8. Surprise: 5 RUNNING rows never closed (crashed runs, last 2026-07-05).

##### pit_replay_snapshots
1. Concept: frozen screener inputs+outputs per day, for regression replay.
2. Grain: snapshot_date × sid (~1,859 rows/day; 131 dates 2024-09-02 → 2026-09-27). PK (snapshot_date, sid). rowid≈253k.
3. Write: `INSERT OR REPLACE` tools/pit_replay.py:181-187. Step `pit_replay_freeze` (config.py:796, daily).
4. Readers: tools/pit_replay.py:188-195 (`replay`, manual only — not in cron/pipeline/pre-push); cockpit_ops/api.py:2308-2312 (freshness tile only). tests/test_factor_registry.py:12-53 (imports INPUT_COLS only).
5. Time: snapshot_date, frozen_at, frozen_by_commit. Historical freezes built from daily_snapshots_pit.
6. JSON: output_json (~150 B: *_adj, base_score, penalty), inputs_json (~650 B: every screener input incl. ticker/name/sector).
7. Target: **Decisions** — this is `runs` + `picks` + `pick_contributions` + the run's input `feature_values` (run_id = frozen_by_commit/run). Replay becomes "re-score run X's features".
8. Surprise: written daily, but the replay check is never run automatically.

#### Pipeline / ops

##### The 11 `*_quarantine` mirrors
analyst_consensus_quarantine, analyst_consensus_snapshots_quarantine, annual_balance_sheet_quarantine, annual_cash_flow_quarantine, banking_metrics_quarantine, broker_recommendations_quarantine, consensus_signals_quarantine, forecast_history_quarantine, mf_holdings_quarantine, mf_sector_allocation_quarantine, quarterly_income_quarantine.
1. Concept: rejected source rows (failed a Trust gate), kept schema-correct for forensics.
2. Grain: none — PK/CHECK/FK/UNIQUE stripped (db.py:216-240); duplicates allowed. Row counts: broker_recommendations 63 (all 2026-05-31), banking_metrics 16 (2026-06-01…08-01), **the other 9 are empty** (never written).
3. Write: created dynamically by `db._ensure_quarantine_tables` (db.py:157-196) from `tables.QUARANTINE_SOURCE_TABLES` (tables.py:722); rows appended by `validators/_verdicts._quarantine_insert` (_verdicts.py:83-96) when `write_verdict(..., quarantine=True)`: callers validators/identity_check.py:303-320 `quarantine_row` (used by sources/moneycontrol_recos.py:440, banking_metrics.py:397, mf_holdings_scrape.py:515, yfinance_analyst.py:89) and validators/plausibility.py:171-177 `route_on_plausibility` (banking_metrics.py:422, yfinance_analyst.py:309). Run inside those fetch steps.
4. Readers: cockpit_ops/api.py:2449-2465 (COUNT(*) per mirror → templates/system.html:174-183). checks/__init__.py:226-231 (empty mirror = OK). No code reads mirror rows back.
5. Time: `_q_quarantined_at` + the source's own date column.
6. TEXT: `_q_failed_gate`, `_q_reason` (+ whatever TEXT the source carries, e.g. rating_mix_history JSON in analyst_consensus).
7. Target: **Ops → `row_issues`** (DELETE the 11 mirrors).
8. Surprises: broker_recommendations rows carry gate `gate_1_identity_retroactive` — a string no current code emits (a since-removed backfill, `git log -S` shows only doc commits). consensus_signals has 320 QUARANTINED verdicts but 0 mirror rows (verdict-only path plausibility.py:190-202).

##### external_anchors
1. Concept: "anchor" truth values (today: NSE bhavcopy close/volume/delivery_pct) for gate 7 drift audit.
2. Grain: datum_class × sid_or_segment × anchor_source × anchor_date. PK same. rowid≈523k. Only anchor_source='nse_bhavcopy', 2026-05-29 → 2026-09-25.
3. Write: `upsert_df` tools/anchor_audit.py:95 (`promote_nse_bhavcopy_anchors` copies stock_prices rows). Step `anchor_audit` (config.py:709, daily). Also tools/regression_fixtures.py:190-224 (pre-push hook, see surprises).
4. Readers: tools/anchor_audit.py:127-133 (audit_drift); cockpit_ops/api.py:2468-2475 (source counts, trust overview).
5. Time: anchor_date, fetched_at.
6. TEXT: datum_class, anchor_source, notes (a long/EAV table already).
7. Target: **DELETE** (pure copy of stock_prices; gate 7 can compare against stock_prices directly or a second source table).
8. Surprise: gate 7 is structurally dead — stock_prices PK is (sid, date) (verified DDL), so a yfinance row and a bhavcopy row for the same sid/date can never coexist; audit_drift's inner join is always empty. `trust_verdicts.gate_7_anchor` is non-NULL on 0 rows. ~520k copied rows for nothing.

##### health_score
1. Concept: Unified Health Score (5 dims 0-20 + label) per entity (factor/table/system/pick) per day.
2. Grain: entity_kind × entity_id × snapshot_date. PK same. rowid≈213k: pick 210k (121 days), factor 1.8k, table 1.2k, system 151.
3. Write: `upsert_df` scoring/health_score.py:168 (`write_uhs`). Step `compute_health_score` (config.py:697, daily; lagged_writes).
4. Readers: live: scoring/health_score.py:457-470 `_latest_factor_uhs` → scoring/confidence.py:39/`batch_write_pick_uhs` → daily_picks.uhs_* (called from scoring/screener.py:483); cockpit: cockpit_ops/api.py:2385-2392 (system pulse), :2497-2505 (worst factors), cockpit/api.py:812 recomputes via rollup_pick_uhs (not a table read); health: tools/health_report.py:572-578 (system UHS < 60 alert). Tests: tests/test_graph.py:50-54, tests/test_factor_registry.py:13-54 (registry only).
5. Time: snapshot_date, computed_at.
6. TEXT/JSON: label, reasons_json (per-dim explanations), entity_kind/entity_id (polymorphic key, pick id = "sid|date").
7. Target: **Ops → `check_results`** (dataset/entity, check='uhs', dims, score, payload JSON). The pick rows are **Decisions** (`picks` quality column) — see surprise.
8. Surprise: pick UHS is stored twice — health_score entity_kind='pick' (~1.86k rows/day) AND daily_picks.uhs_score/uhs_label/uhs_breakdown_json (scoring/confidence.py:195-238), computed at different times.

##### llm_usage
1. Concept: LLM call/cost ledger.
2. Grain: one row per call or per aggregated batch. PK id. rowid≈5,852.
3. Write: `db.log_llm_usage` INSERT db.py:407-431 (DDL created on the fly, db.py:384). Callers: output/_llm.py:32 (dossiers, sector dossiers), sources/news_classifier.py:154,233, sources/news_brief.py:136, sources/regulatory_classifier.py:173,200,533,939,970, and **untracked tools/session_classify.py:201,431**.
4. Readers: none in code (hosts.py:99 and tools/compare_reg_models.py:18 are comments; .claude/commands/architecture-review.md:79 mentions it).
5. Time: called_at.
6. TEXT: step, model, mode.
7. Target: **Ops `llm_usage`** (keep; add run_id/step_run_id).
8. Surprises: session_classify.py wrote **8 rows with 0 input/0 output tokens, mode='session', model 'claude-sonnet-5'**: classify_regulatory_deep 7 rows / n_calls 15,570; classify_news 1 row / n_calls 1,099; est_cost 0.0 (2026-09-26 18:32-20:33). Any spend rollup must treat mode='session' as unpriced. Also: no API-billed LLM row since 2026-08-24 (dossier / sector dossier / news_brief / classify_news last 2026-08-23). Either those steps stopped calling the API or stopped logging (cause unverified).

##### pipeline_log
1. Concept: step run events (pipeline steps + watchdog heals + endpoint audits).
2. Grain: one row per status event. A step invocation writes a RUNNING row then a separate SUCCESS/FAILED row (pipeline.py:147, :160-170). PK id. rowid≈17.8k (RUNNING 8,341 / SUCCESS 8,413 / FAILED 820 / SKIPPED 203), since 2026-04-09.
3. Write: INSERT pipeline.py:79-95 `log_step`; tools/freshness_watchdog.py:59-67 (`watchdog_<table>_<action>`); tools/cockpit_endpoint_audit.py:133-137 (`endpoint_audit_<endpoint>`); tools/regression_fixtures.py:157-164 (insert+delete heartbeat, pre-push).
4. Readers: health: tools/health_report.py:136-150 (latest run_date failures), :160-185 (failure streaks), :316-330 (watchdog); db.py:1257-1262 (last run); views.py:410-424 (dedup per run_date/step); pipeline.py:285-289 `--status`; cockpit_ops/api.py:512-516 (rerun guard), :1877-1880 drilldown SQL, :2068-2080 endpoint audits; health.py:155 drill SQL text. Tests: tests/test_checks.py:165, tests/test_graph.py:64,81, tests/test_views.py:29,97.
5. Time: run_date, started_at, finished_at.
6. TEXT: step_name (overloaded namespace), status, error_message.
7. Target: **Ops `step_runs`**.
8. Surprises: no run id (see Cross-cutting). checks/ranges.py:94 allows `ABORTED` (not in the CHECK constraint) and omits COVERAGE_GAP/COVERAGE_SEVERE (in the CHECK) — the vocabularies don't match.

##### screener_pull_errors
1. Concept: per-stock Screener scrape failure log.
2. Grain: one row per failed attempt. PK id. rowid≈7.8k (fetch 6,197 / thin 1,223 / empty 347 / http 1; last 2026-09-15).
3. Write: `insert_df` sources/screener_pull.py:370-387 `log_error`, also called from sources/screener_schedules.py:177-192. Cron `run.sh screener_universe` (1st+15th) + screener steps.
4. Readers: none in code; cockpit_ops/api.py:1505 (static list), :1619 (hint text). Tests: tests/test_sources_door.py:2993,3005.
5. Time: attempted_at.
6. TEXT: error_type, error_message, ticker.
7. Target: **Ops `row_issues`** (dataset='fundamentals_screener', key {sid}, rule=error_type, payload {message,http_status}) or `step_runs` detail.
8. —

##### signal_lineage
1. Concept: per-stock record of which source rows/columns fed a factor value.
2. Grain: sid × snapshot_date × factor × source_table × source_key × contribution (PK all 6). rowid≈230k; 2026-05-25 → 2026-09-27; only top-300 sids (lineage.lineage_active_sids).
3. Write: `db.emit_lineage` DELETE+INSERT db.py:445-522; only 2 emitters: signals/piotroski.py:341, signals/consensus.py:283 (steps declare `writes` signal_lineage, config.py:432, :586).
4. Readers: live-ish: scoring/confidence.py:70-80 (gate 6 coverage → pick UHS → daily_picks); cockpit/api.py:844-848 per-stock lineage view.
5. Time: snapshot_date.
6. JSON: source_key, source_cols, column_sources; contribution TEXT.
7. Target: **Ops/Research provenance** — DESIGN QUESTION: fold into `feature_values` (add `source_ref JSON` per value) vs. keep as a separate `feature_provenance` table. Not numeric.
8. Surprise: only 2 of ~105 factors emit lineage, so gate 6 "coverage" measures emission for piotroski/consensus only.

##### trust_verdicts
1. Concept: per-source-row trust gate results (7 gate columns) + overall verdict.
2. Grain: sid × source_table × source_key(JSON PK) × datum_class × snapshot_date. rowid≈311k. ~99% are TRUSTED (pass records): analyst_consensus 175k, consensus_signals 111k, broker_recommendations 9.2k, stock_prices 2k, piotroski 2k, banking 1k, mf_holdings 322. QUARANTINED 361, PENDING_REVIEW 357. gate_6 and gate_7 are never populated.
3. Write: upsert validators/_verdicts.py:43-66 (ON CONFLICT, per-gate column). Callers: validators/identity_check.py:318,336; validators/plausibility.py:171-202; tools/trust_backfill.py:44-57 (manual); tools/anchor_audit.py:147-162 (step anchor_audit); tools/regression_fixtures.py (pre-push).
4. Readers: scoring/health_score.py:244-262 (`_gate_pass_rate`), :478-500 (`_sid_gate_counts` per pick) → UHS → daily_picks; checks/custom.py:672-692 (EXTERNAL_ANCHOR_DRIFT check, always 0/0); cockpit_ops/api.py:2420-2445 (per-gate pass rates). Tests: tests/test_verdicts.py, tests/test_identity_gate.py:197-245, tests/test_schema.py:27. No reader ever filters live data by verdict_overall (grep: QUARANTINED only in writers/tests).
5. Time: snapshot_date, computed_at.
6. JSON: source_key, reasons_json (json_patch-merged per gate).
7. Target: **Ops** — failures → `row_issues`; pass records → aggregate `check_results` (pass counts per dataset/rule/day). The per-row TRUSTED rows are the bulk and carry little information.
8. Surprise (**production data hazard**): the pre-push hook (.git/hooks/pre-push:20 → `tools.regression_fixtures verify_all`) runs the gate-7 fixture against the LIVE DB. It does `DELETE FROM trust_verdicts WHERE sid='RELI'`, `DELETE FROM external_anchors WHERE sid_or_segment='RELI'` and inserts/deletes a 1999 stock_prices row (tools/regression_fixtures.py:185-226). Verified: RELI has 0 trust_verdicts rows, while TCS has about 250. Every push wipes Reliance's verdicts.

##### uhs_calibration_log
1. Concept: pick outcome × UHS at pick time, for later validation of the UHS weighting.
2. Grain: sid × pick_date × window_days. PK same. 209,741 rows but rowid≈8.1M.
3. Write: `INSERT OR REPLACE` of the full join, row by row, every night: scoring/confidence.py:240-275. Step `update_uhs_calibration` (config.py:719, daily).
4. Readers: none (cockpit_ops/api.py:1999 is a comment; health freshness via tables.py:573).
5. Time: pick_date, window_days (forward outcome), written_at.
6. TEXT: uhs_label, uhs_worst_dim, cap_tier.
7. Target: **DELETE → view** over Decisions (`outcomes` ⋈ `picks`). It is a pure join of pick_outcomes × daily_picks.
8. Surprise: rewrites all ~210k rows daily (rowid 8.1M = ~40 full rewrites), for a table nobody reads.

---

#### Cross-cutting

##### daily_snapshots_pit — columns and how it is read
109 columns (PRAGMA verified). `factors.PIT_COLUMNS` has 108; the only DB column outside it is `reconstructed_at`. None are missing.
- **Identifiers/metadata (5):** sid, snapshot_date, cap_tier (tier at anchor), reconstructed_at, close_price (a base value, `PIT_EXTRA` factors.py:1779).
- **Label (1):** fwd_return_20d (`PIT_EXTRA`, the backtest response; `SIGNAL_COLUMN_MAP["_response"]` factors.py:2115).
- **Categorical factor (1):** industry_id (INTEGER 0-38; used as a risk-model dummy in tools/risk_decomp.py:59).
- **Factor values (~102):** one `pit_column(id)` per registered factor (factors.py:1992). They include sub-components and composites that are not their own FACTORS ids: piotroski_f, cf_accruals, bs_accruals, mom_6m, mom_12m, mom_composite, macd_bullish, insider_score, news_volume_7d, plus the screener composites accruals_signal, promoter_signal and forensic_penalty (`PIT_EXTRA`, stored for pit_replay). Types: INTEGER for piotroski_f and macd_bullish (factors.py:2084), REAL for the rest. There are no TEXT values, so the whole panel pivots cleanly to `feature_values(feature_id, date, entity_id=sid, value, run_id)`.
- **Read shapes:**
  - `pit.load_raw` / `pit.features_at` never read this table (pit.py:1536-1582 read raw source tables through RAW_SQL). The one PIT-table read is macro_sector_signals_pit (pit.py:1496).
  - tools/backtest_pit.py:289-290, promotion_gate.py:177-178 and ic_decay.py:136-137 load `SELECT *` of **both** v1 and v2 into pandas. That is the whole table, unfiltered, through SQLite.
  - The other tools do column projections filtered by tier or date (factor_decay, factor_marginal, risk_decomp, rank_localization, factor_correlation, expected_return).
  - Cockpit: cockpit/api.py:1745 reads the latest anchor with `SELECT pit.*`. cockpit_ops/api.py:253-262 and :326-354 run coverage and date aggregates.
- **DuckDB:** used only by cockpit_ops (`read_sql_fast`, db.py:295-314; callers cockpit_ops/api.py:257, 326, 354). The replica holds the `mirror: True` tables (tables.py:723), which include daily_snapshots_pit, daily_snapshots_pit_v1 and pit_ic_by_tier_v1. It is rebuilt at the end of `run.sh morning` (run.sh:45), and the file is about 175 MB. No backtest tool reads DuckDB, so moving history to Parquet and DuckDB would mainly help the backtest tools.

##### The _v1 tables
- daily_snapshots_pit_v1 has 4 code readers: tools/backtest_pit.py:289, promotion_gate.py:177, ic_decay.py:136 and walk_forward.py:113 (v1-only, a hard-coded factor list at :45). cockpit_ops/api.py:236/280/326/345 also reads it for coverage and roster stats, and :1497/:1697 are static labels. So there are 5 readers, 6 if you count the cockpit static lists.
- The readers use it for two things. First, the monthly 'v1_archive' IC source for 12 factors (`pit_column_v1`, backtest_pit.py:261-263). Second, walk_forward's training panel.
- Could they switch? Yes. The v2 panel covers 2019-12→ with all 12 columns (eps_cv maps to earnings_persistence), and memory backtest_v1_validates says v2 reproduces the v1 t-stats. Two options:
  - (a) Load v1 into `feature_values` with run_id='v1_archive'. Readers then filter by run, with the same shape as v2.
  - (b) Freeze v1 to Parquet and expose a DuckDB view `pit_panel_v1`.
  
  walk_forward needs a one-line source switch. backtest_pit, promotion_gate and ic_decay only need `iter_panels` to take a run filter.
- pit_ic_by_tier_v1 has no reader of its values (only the static schema list at cockpit_ops/api.py:1498), and pit_ic_by_tier_v2 source='v1_archive' already holds the same evidence. **DELETE**.

##### Quarantine
- **Path:** a source fetcher calls a validator (`verify_identity` or `verify_plausibility`). On WRONG_ENTITY or OUT_OF_RANGE_HARD it calls `quarantine_row` or `route_on_plausibility`, which call `write_verdict(..., quarantine=True)`. That writes the trust_verdicts gate=0 row and appends the raw row plus `_q_*` to `<source>_quarantine` in one transaction (validators/_verdicts.py:83-96, 135-158). The live write is then skipped.
- **Mirror columns:** the same columns as the source, with PK/CHECK/FK/UNIQUE stripped and NOT NULL kept (db.py:216-240). Three columns are appended: `_q_failed_gate`, `_q_reason` and `_q_quarantined_at`. They are built by introspection at startup (db.py:157-196), and rebuilt when the source DDL has a bad constraint (db.py:199-213).
- **Readers:** only COUNT(*) per mirror (cockpit_ops/api.py:2449-2465 → system.html:174) and the empty-is-OK policy (checks/__init__.py:226-231). No code reads mirror rows.
- **Release:** nothing ever releases a row. There are no DELETE, re-insert or reinstate paths for the mirrors (grep for release/reinstate finds none). The db.py:138 comment promises "re-instate-as-trusted workflows", but none was built.
- **Can `row_issues` replace all 11?** Yes, with no loss. Mapping: `dataset` = source table; `key` = PK JSON (already built by `_verdicts.source_key_for`); `rule` = gate; `severity` = FAIL/WARN (EXTREME→WARN covers PENDING_REVIEW); `detected_at` = `_q_quarantined_at`; `payload` = the rejected row as JSON plus reason; `resolved_at` = a release hook that doesn't exist today. Two things are lost:
  - (a) schema-typed columns for SQL forensics. `json_extract` covers these, and there are only 79 rows in total.
  - (b) the "LEFT JOIN <table>_quarantine" affordance. Nobody uses it.
  
  It also removes the dynamic DDL machinery (db.py:135-240), and it fixes the verdict/mirror drift: consensus_signals has 320 QUARANTINED verdicts and 0 mirror rows, and broker_recommendations has 8 verdicts against 63 mirror rows. A failing trust_verdicts gate row and a quarantine row are the same fact, so both collapse into `row_issues`.

##### pipeline_log vs step_runs
- **Columns:** id, run_date, step_name, status (RUNNING/SUCCESS/FAILED/SKIPPED/COVERAGE_GAP/COVERAGE_SEVERE), rows_affected, started_at, finished_at, duration_sec, error_message.
- **No run id.** A pipeline invocation is identified only by `run_date` (date('now')), and a step invocation by (step_name, started_at). RUNNING and terminal states are separate rows. The terminal row repeats `started` (pipeline.py:147/163), so they pair on (step_name, started_at).
- **step_name is overloaded** with `watchdog_<table>_<action>` (freshness_watchdog.py:63) and `endpoint_audit_<endpoint>` (cockpit_endpoint_audit.py:135). Readers pick them out with LIKE (health_report.py:321, cockpit_ops/api.py:2076).
- **How it is read:**
  - health_report.py:136-150: failures on MAX(run_date).
  - :160-185: ROW_NUMBER latest-status per step, then the failure streak over days.
  - :316-330: the watchdog summary.
  - views.py:410-424: collapses the RUNNING/terminal pair per (run_date, step), preferring SUCCESS.
  - db.py:1257: last terminal row.
  - cockpit_ops/api.py:512: rerun guard (latest RUNNING).
  
  All of these reconstruct "latest run of step X" with window functions because there is no run entity.
- **step_runs target:** `runs(run_id, job, started_at, finished_at, status, commit)` and `step_runs(run_id, step, started_at, finished_at, status, rows, error, kind ∈ {pipeline, watchdog_heal, endpoint_audit, pit_reconstruct})`, updated in place rather than written as 2 rows. pit_reconstruction_log folds in as step_runs children keyed by eval_date. Endpoint audits and COVERAGE_* statuses are really `check_results`.

##### llm_usage and session_classify
- MAX(rowid)=5,852, so the query was cheap. 8 rows have input_tokens=output_tokens=0, and all 8 come from tools/session_classify.py (mode='session', model 'claude-sonnet-5', est_cost 0.0, 2026-09-26): classify_regulatory_deep 7 rows / n_calls 15,570 and classify_news 1 row / n_calls 1,099. They inflate call counts but not cost. A spend report must exclude or separately price mode='session'.

#### Slice summary
- 28 tables. Proposed: 5 → **Features** (daily_snapshots_pit, _v1, macro_sector_signals_pit; pit_replay inputs); 2 → **Research** (pit_ic_by_tier_v2, factor_horizon_gate); pit_replay_snapshots → **Decisions**; pipeline_log + pit_reconstruction_log + screener_pull_errors + llm_usage + health_score + trust_verdicts + 11 quarantine mirrors → **Ops** (step_runs / row_issues / check_results / llm_usage); historical_universe → **Reference**; **DELETE**: pit_ic_by_tier_v1, external_anchors, uhs_calibration_log (→ view). signal_lineage = DESIGN QUESTION (provenance on feature_values vs its own table).
- daily_snapshots_pit is a 109-column all-numeric panel that pivots losslessly to feature_values. The live screener never reads it; only backtest tools and the cockpit do, mostly `SELECT *` into pandas through SQLite. Only cockpit_ops uses DuckDB.
- macro_sector_signals_pit, although filed as "Backtest", is a live input to the wired sector_tilt factor (pit.py:1496).
- One `row_issues` table can replace all 11 quarantine mirrors (9 are empty, 79 rows in total, only COUNT(*) readers, no release path) and also absorb the failing trust_verdicts rows.
- pipeline_log has no run id: RUNNING and terminal states are 2 rows, and step_name is overloaded with watchdog/endpoint_audit namespaces. Every reader rebuilds runs with window functions.
- **Hazards found:**
  - (1) The pre-push hook deletes RELI's trust_verdicts and external_anchors in the LIVE DB (verified: RELI has 0 verdicts).
  - (2) Gate 7 is structurally dead (stock_prices PK is sid,date), so external_anchors (~523k rows) is a useless copy.
  - (3) pit_ic_by_tier_v2.computed_at is never refreshed by upsert.
  - (4) uhs_calibration_log rewrites ~210k rows nightly with no reader.
  - (5) Pick UHS is stored twice (health_score and daily_picks).
  - (6) factor_horizon_gate has been stale since 2026-06-02 but is shown on the cockpit.
  - (7) No API-billed llm_usage rows since 2026-08-24.
  - (8) session_classify logged 16.7k zero-token calls.

