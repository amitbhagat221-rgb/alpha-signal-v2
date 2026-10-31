<!-- generated 2026-10-31 by the stage-0 measurement (plan 0030); scripts in the session scratchpad, raw inventory.json / dbstat.json not committed -->
# Plan 0030 stage 0 — measurements (2026-10-31, read-only)

Raw data: `inventory.json`, `dbstat.json` next to this file. Nothing in the repo was modified.

## 1. Reader inventory

Mirrored legacy tables = the 120 non-RETIRED `datamodel_parity` subjects on 2026-10-31 (what `datamodel/reconcile.py` compares), expanded: `a+b` subjects split, `table.column` subjects collapsed to the table, `quarantine_mirrors(11)` = the 11 `*_quarantine` tables → **132 distinct legacy tables**. RETIRED (kept-as-is / dropped) tables excluded.

Files = production code files (`*.py *.html *.js *.sql run.sh`) naming the table as a whole word (`grep -rlw`); excluded `tests/ datamodel/ docs/ _archive/ .archify/ output/ data/ .git/ backups/ graphify-out/ .devlib/ .claude/worktrees/` (the worktrees hold full repo copies and inflated the first pass 25×). **311 distinct files** name at least one mirrored table.

| legacy table | v3 concept | v3 table | files naming it |
|---|---|---|---:|
| `stocks` | Reference | entities (+classifications tier, attrs) | 220 |
| `stock_prices` | Bars | bars_daily | 89 |
| `daily_snapshots_pit` | Features | feature_values | 59 |
| `fundamentals_screener` | Company facts | fundamentals | 54 |
| `shareholding` | Company facts | fundamentals | 37 |
| `corporate_adjustments` | Events | events | 36 |
| `quarterly_income` | Company facts | fundamentals | 36 |
| `bse_announcements` | Events | events | 30 |
| `daily_picks` | Decisions | picks + runs | 30 |
| `macro_history` | Series | series_values | 27 |
| `nse_index_history` | Bars | bars_daily | 27 |
| `analyst_consensus` | Company facts | estimates | 24 |
| `news_articles` | Events | events | 24 |
| `regulatory_events` | Events | events (+documents full_text) | 24 |
| `fno_bhav` | Bars | derivative_bars | 23 |
| `annual_balance_sheet` | Company facts | fundamentals | 21 |
| `corporate_actions` | Events | events | 21 |
| `pipeline_log` | Ops | step_runs | 21 |
| `insider_trades` | Events | events | 20 |
| `regulatory_signals` | Documents | documents | 20 |
| `nse_announcements` | Events | events | 19 |
| `bulk_deals` | Events | events | 18 |
| `forecast_history` | Company facts | estimates | 17 |
| `annual_cash_flow` | Company facts | fundamentals | 16 |
| `consensus_signals` | Features | feature_values | 15 |
| `forensic_scores` | Features | feature_values | 14 |
| `mf_nav_history` | mf.db | mf.fund_nav | 14 |
| `mf_scheme_master` | mf.db | mf.funds | 14 |
| `news_article_stocks` | Events | event_links | 14 |
| `banking_metrics` | Company facts | fundamentals | 13 |
| `macro_sector_signals_pit` | Features | feature_values | 13 |
| `mf_holdings` | mf.db | mf.fund_holdings | 13 |
| `piotroski_scores` | Features | feature_values | 13 |
| `portfolio_weights` | Decisions | book_weights | 13 |
| `scrip_master` | Reference | identifiers | 13 |
| `shareholding_categories` | Events | events | 13 |
| `analyst_consensus_snapshots` | Company facts | estimates | 12 |
| `earnings_calendar` | Events | events | 11 |
| `fno_iv_history` | Features | feature_values | 11 |
| `fno_pcr_history` | Features | feature_values | 11 |
| `macro_indicator_meta` | Reference | catalog (series spec) | 11 |
| `macro_sector_map` | Reference | catalog (series spec) | 11 |
| `macro_sector_signals` | Features | feature_values (+documents text) | 11 |
| `news_enriched` | Documents | documents | 11 |
| `nlp_scores` | Features | feature_values | 11 |
| `pick_outcomes` | Decisions | outcomes | 11 |
| `pit_ic_by_tier_v2` | Research | factor_tests | 11 |
| `shareholding_holders` | Events | events | 11 |
| `transcripts` | Documents | documents | 11 |
| `daily_snapshots` | Features | feature_values | 10 |
| `fii_dii_cash_flow` | Series | series_values | 10 |
| `macro_indicators` | Features | feature_values | 10 |
| `mf_metrics` | mf.db | mf.fund_metrics | 10 |
| `sector_briefs` | Features | feature_values (+documents text) | 10 |
| `sector_metadata` | Documents | documents | 10 |
| `multibagger_scores` | Features | feature_values | 9 |
| `news_briefs` | Documents | documents | 9 |
| `pit_replay_snapshots` | Decisions | documents(pit_replay) + pick_contributions | 9 |
| `surveillance_flags` | Events | events | 9 |
| `universe_eligibility` | Features | feature_values | 9 |
| `feed_checks` | Ops | check_results | 8 |
| `fii_dii_positioning` | Series | series_values | 8 |
| `insider_signals` | Features | feature_values (+documents text) | 8 |
| `promoter_signals` | Features | feature_values | 8 |
| `regime_state` | Features | feature_values | 8 |
| `sentiment_scores` | Features | feature_values (+documents text) | 8 |
| `short_selling_data` | Events | events | 8 |
| `analyst_estimates` | Company facts | estimates | 7 |
| `broker_recommendations` | Events | events | 7 |
| `daily_snapshots_pit_v1` | Features | feature_values | 7 |
| `management_scores` | Features | feature_values | 7 |
| `mf_sector_allocation` | mf.db | mf.fund_holdings | 7 |
| `smart_money_scores` | Features | feature_values | 7 |
| `trust_verdicts` | Ops | check_results + row_issues | 7 |
| `accruals_scores` | Features | feature_values | 6 |
| `historical_universe` | Reference | bars_daily + entities | 6 |
| `mf_schemes` | mf.db | mf.funds | 6 |
| `playbook_members` | Features | feature_values | 6 |
| `policy_events` | Events | events | 6 |
| `portfolio_outcomes` | Decisions | outcomes | 6 |
| `sector_dossiers` | Documents | documents | 6 |
| `factor_horizon_gate` | Research | factor_tests | 5 |
| `financial_signal_scores` | Features | feature_values | 5 |
| `gross_profitability_scores` | Features | feature_values | 5 |
| `managerial_ability_scores` | Features | feature_values | 5 |
| `market_events` | Events | events | 5 |
| `mf_calendar_returns` | mf.db | mf.fund_metrics | 5 |
| `mf_category_stats` | mf.db | mf.fund_metrics | 5 |
| `mf_rolling_returns` | mf.db | mf.fund_metrics | 5 |
| `operating_margin_trend_scores` | Features | feature_values | 5 |
| `roic_scores` | Features | feature_values | 5 |
| `roiic_scores` | Features | feature_values | 5 |
| `sector_force_breakdown` | Features | feature_values (+documents text) | 5 |
| `valuation_ranges` | Features | feature_values (+documents text) | 5 |
| `mb_research` | Documents | documents | 4 |
| `pit_reconstruction_log` | Ops | step_runs | 4 |
| `regulatory_batches` | Ops | step_runs | 4 |
| `screener_pull_errors` | Ops | row_issues | 4 |
| `sector_analyst_breadth_pit` | Features | feature_values | 4 |
| `sector_sentiment_breadth_pit` | Features | feature_values | 4 |
| `analyst_consensus_quarantine` | Ops | row_issues | 3 |
| `banking_metrics_quarantine` | Ops | row_issues | 3 |
| `broker_recommendations_quarantine` | Ops | row_issues | 3 |
| `consensus_signals_quarantine` | Ops | row_issues | 3 |
| `mb_dossiers` | Documents | documents | 3 |
| `mf_holdings_quarantine` | Ops | mf.row_issues | 3 |
| `sector_narrative_runs` | Ops | step_runs | 3 |
| `analyst_consensus_snapshots_quarantine` | Ops | row_issues | 2 |
| `annual_balance_sheet_quarantine` | Ops | row_issues | 2 |
| `annual_cash_flow_quarantine` | Ops | row_issues | 2 |
| `asset_tangibility_scores` | Features | feature_values | 2 |
| `capex_to_dep_scores` | Features | feature_values | 2 |
| `cash_conversion_cycle_scores` | Features | feature_values | 2 |
| `debt_structure_scores` | Features | feature_values | 2 |
| `dio_change_yoy_scores` | Features | feature_values | 2 |
| `dso_change_yoy_scores` | Features | feature_values | 2 |
| `fcf_margin_scores` | Features | feature_values | 2 |
| `fcf_yield_scores` | Features | feature_values | 2 |
| `forecast_history_quarantine` | Ops | row_issues | 2 |
| `goodwill_to_assets_scores` | Features | feature_values | 2 |
| `health_score` | Ops | check_results | 2 |
| `interest_coverage_scores` | Features | feature_values | 2 |
| `inventory_turnover_scores` | Features | feature_values | 2 |
| `mf_sector_allocation_quarantine` | Ops | mf.row_issues | 2 |
| `nwc_to_revenue_scores` | Features | feature_values | 2 |
| `quarterly_income_quarantine` | Ops | row_issues | 2 |
| `revenue_cv_scores` | Features | feature_values | 2 |
| `sales_growth_relative_scores` | Features | feature_values | 2 |
| `sga_to_revenue_change_scores` | Features | feature_values | 2 |
| `share_momentum_scores` | Features | feature_values | 2 |
| `sloan_accruals_full_scores` | Features | feature_values | 2 |
| `working_capital_intensity_scores` | Features | feature_values | 2 |

### Per-concept rollup

| concept | legacy tables | distinct files to move |
|---|---:|---:|
| Reference | 5 | 224 |
| Features | 51 | 123 |
| Company facts | 10 | 114 |
| Bars | 3 | 111 |
| Events | 17 | 96 |
| Decisions | 5 | 42 |
| Documents | 8 | 39 |
| Ops | 19 | 35 |
| Series | 3 | 31 |
| mf.db | 9 | 24 |
| Research | 2 | 13 |

Files overlap heavily across concepts (one module reads several tables), so the rollup does not sum to the 311 total.


## 2. Disk per v3 table

`backup_db.sh` does `VACUUM INTO` → `gzip -1` → rclone to Drive, then deletes the local `.gz`; the only local copy is the fallback `backups/alpha_signal_20260531.db.gz` (5 months stale) and there is never an uncompressed snapshot on disk. So the `.gz` was left alone and `dbstat` was run on the **live DB through `file:...?mode=ro`**, one b-tree at a time (`WHERE name = ?` walks only that b-tree), 300 s interrupt per object. v3 rows = table + its indexes; legacy rows = table b-tree only. Rows = leaf-page cell count from dbstat (exact, no COUNT(*)).

DB file: **24.44 GB** (26,241,613,824 bytes; page size 4096, 6,406,644 pages, 0 free pages = 0.00 GB freelist).

| v3 table | table MB | index MB | total MB | rows | walk s |
|---|---:|---:|---:|---:|---:|
| `catalog` | 0.4 | 0.1 | 0.4 | 1,399 | 0 |
| `entities` | 3.8 | 0.7 | 4.5 | 20,337 | 0 |
| `classifications` | 1.7 | 0.9 | 2.6 | 27,200 | 0 |
| `identifiers` | 5.1 | 1.2 | 6.3 | 25,089 | 0 |
| `bars_daily` | 569.1 | 161.5 | 730.6 | 4,892,833 | 18 |
| `derivative_bars` | 1,515.4 | 692.9 | 2,208.3 | 13,447,228 | 31 |
| `series_values` | 23.4 | 0.0 | 23.4 | 278,708 | 0 |
| `events` | 3,608.5 | 1,161.4 | 4,769.9 | 4,660,974 | 98 |
| `event_links` | 0.5 | 0.0 | 0.5 | 26,437 | 0 |
| `documents` | 792.0 | 127.5 | 919.5 | 958,279 | 3 |
| `fundamentals` | 280.3 | 0.0 | 280.3 | 2,154,603 | 4 |
| `estimates` | 37.6 | 0.0 | 37.6 | 264,452 | 1 |
| `feature_values` | 1,802.6 | 1,260.3 | 3,062.9 | 57,071,117 | 38 |
| `runs` | 0.1 | 0.0 | 0.1 | 586 | 0 |
| `picks` | 360.5 | 0.0 | 360.5 | 278,773 | 2 |
| `pick_contributions` | 11.5 | 0.0 | 11.5 | 222,842 | 0 |
| `book_weights` | 0.6 | 0.0 | 0.6 | 2,570 | 0 |
| `outcomes` | 82.9 | 0.0 | 82.9 | 295,105 | 0 |
| `factor_tests` | 0.2 | 0.0 | 0.2 | 669 | 0 |
| `step_runs` | 11.6 | 0.6 | 12.1 | 16,690 | 0 |
| `check_results` | 256.5 | 40.0 | 296.6 | 546,954 | 13 |
| `row_issues` | 3.8 | 1.1 | 4.9 | 11,966 | 0 |
| `llm_usage` | 0.7 | 0.0 | 0.7 | 8,507 | 0 |
| `llm_tasks` | 58.8 | 3.1 | 61.9 | 35,187 | 0 |

**v3 total (measured tables + indexes): 12.58 GB = 51.5% of the 24.44 GB file.**

### Largest legacy tables (table b-tree only, no indexes)

| legacy table | MB | rows | walk s |
|---|---:|---:|---:|
| `bse_announcements` | 1,698.3 | 2,614,024 | 2 |
| `fno_bhav` | 1,431.9 | 13,824,293 | 29 |
| `transcripts` | 769.4 | 16,252 | 0 |
| `stock_prices` | 457.6 | 4,999,297 | 0 |
| `shareholding_holders` | 326.8 | 1,562,864 | 6 |
| `daily_snapshots_pit` | 325.4 | 506,736 | 0 |
| `stock_prices_unlisted` | 287.2 | 3,114,811 | 5 |
| `pit_replay_snapshots` | 237.2 | 310,627 | 2 |
| `fundamentals_screener` | 85.6 | 1,201,808 | 0 |
| `daily_snapshots_pit_unlisted` | 63.9 | 307,749 | 6 |
| `news_articles` | 21.7 | 34,426 | 0 |
| `news_enriched` | 14.8 | 28,821 | 0 |
| `fno_iv_history` | 11.4 | 120,756 | 0 |
| `quarterly_results_nse` | 8.8 | 31,608 | 0 |
| `daily_snapshots_pit_v1` | 8.2 | 60,168 | 0 |
| `macro_history` | 6.4 | 66,629 | 0 |
| `insider_trades` | 5.0 | 34,755 | 0 |
| `nse_announcements` | 4.0 | 10,412 | 0 |
| `quarterly_income` | 3.4 | 26,450 | 0 |
| `nse_index_history` | 1.7 | 17,069 | 0 |
| `historical_universe` | 1.0 | 17,691 | 0 |
| `option_live_quotes` | 0.2 | 1,424 | 0 |

Measured legacy table b-trees: 5.63 GB (indexes excluded; the rest of the file is the other ~150 tables, their indexes and the freelist).

