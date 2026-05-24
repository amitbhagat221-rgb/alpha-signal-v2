# Alpha Signal v2 — Progress Checklist
_Last updated: 2026-05-24 (handoff #3 of day — Health Center cockpit redesign + 2 CRITICAL fixes) · Plans are truth, this is the view. Update via `/handoff`._
_Glyphs: ✅ done · ⏳ next/in-progress · 🚫 blocked · 💤 parked · ↔ cross-track integration point_
_Convention: see [ADR 0015](../decisions/0015-track-numbering-and-rename.md) (tracks) + [ADR 0016](../decisions/0016-plan-numbering-fresh-start.md) (plan numbers)._

## Next 3
1. ⏳ **Fix `insider_timeline` cockpit endpoint** — only remaining CRITICAL after today's audit. Endpoint audit shows 48/90 (53.3%) sids return empty (sample: ADEL). Likely sid/ticker mismatch in [cockpit/api.py](../../cockpit/api.py) get_insider_timeline. ~30-60min.
2. ⏳ **Extend historical_backfill to FII/DII Cash Segment** — different SEBI source than the F&O positioning shipped 2026-05-24. Add `backfill_fii_cash()` paralleling `backfill_fii_fno()` in [sources/historical_backfill.py](../../sources/historical_backfill.py); endpoint `https://www.nseindia.com/api/historical/foreignActivity`. ~1hr code + ~30min pull.
3. ⏳ **Price source fallback layer** — `sources/bse.py` (BSE bhavcopy) + `sources/yfinance_prices.py` registered in [config.py:PIPELINE_STEPS](../../config.py#L218) after `fetch_bhavcopy`, each filling only sids the prior source missed. Covers the 339 still-missing stocks (mostly InvITs, BSE-only, recent IPOs).

## Track 1 — Foundation  ✅ done 2026-05-01
- 1.1 ✅ v1 audit + rebuild plan
- 1.2 ✅ Tier infrastructure (was C12)
- 1.3 ✅ Stratified backtest + VIX regime (was C13)
- 1.4 ✅ 36-month PIT reconstruction (was C13b)
- 1.5 ✅ v2 cutover (2026-05-01)

## Track 2 — Portfolio  · [plan 0001](0001-mother-plan.md)
- ✅ 2.1 Small-cap quality gate
- ⏳ 2.2 Financial sub-model  (next)
   - ⏳ `sources/banking_metrics.py`
   - ⏳ `banking_metrics` table + migration
   - ⏳ `signals/financial_signal.py`
- ⏳ 2.3 Cyclical overlay (parallel-able with 2.2)
- ⏳ 2.4 Segment models + portfolio (capstone)  **↔ 3.3c**
- 🚫 2.5 XGBoost overlay  **↔ 3.3b**  (blocked: needs ≥6mo PIT, ETA early 2027)

## Track 3 — Factor model  · [plan 0002](0002-100-factors-and-model.md)
- ⏳ 3.1 Data acquisition (forks ship independently):
   - ✅ 3.1a Screener Premium  (2,119 / 2,448 stocks, 681K rows in `fundamentals_screener`)
   - ⏳ 3.1b NSE F&O OI  ← **active** (unblocks §3.2.2)
      - ⏳ Probe `nselib.derivatives` endpoints (option chain, OI history, participant-wise OI) for date-range support
      - ⏳ Schema: `fno_option_chain` (per-strike snapshot) + `fno_oi_history` (time series)
      - ⏳ Fetcher `sources/fno_pull.py` with cookie-warm + rate limit
      - ⏳ Cron entry + freshness watchdog registration
   - ⏳ 3.1c Kite Connect
   - ⏳ 3.1d PIB + earnings call NLP
- ⏳ 3.2 Factor build, 50 factors  (**21/50 PIT-shipped** — +insider_signal + sentiment_7d 2026-05-24 cadence-aware backtest framework; **3 NEW KEEPs** uncovered by weekly+NW: bulk_deal SMALL t=2.56, delivery_anomaly_z SMALL t=4.11, sentiment_7d LARGE preliminary t=-3.88)
   - ✅ §3.2.1 forensic/capital allocation: **11/15 done** — roic, fcf_yield, ccc, operating_margin_trend, working_capital_intensity, interest_coverage, roiic, dso_change_yoy, dio_change_yoy, nwc_to_revenue, sloan_accruals_full, sga_to_revenue_change, fcf_margin, capex_to_dep, goodwill_to_assets, debt_structure, asset_tangibility — see [db.BACKTEST_SIGNALS](../../db.py) for per-factor verdicts. **NEW KEEP**: dso_change_yoy LARGE (|t|=-2.81, intuitive sign). 4 skipped: gross_margin (no clean COGS), gross_margin_4q_change (same), consol_standalone_gap (schema gap), sloan_accruals_full library tier.
   - ⚠ `pt_revision_yoy` DROPPED 2026-05-23 (contaminated data — see ADR 0020). `consensus_signal_combined` DEGRADED (eps-only). Rebuild from `analyst_consensus_snapshots` at 2027-05+.
   - 🚫 §3.2.2 options-implied (8 factors) — blocked on 3.1b
   - 🚫 §3.2.3 microstructure (9 factors) — blocked on 3.1c
   - 🚫 §3.2.4 NLP/sentiment (7 factors) — blocked on 3.1d
   - ⏳ §3.2.5 event-time/PEAD (6 factors) — feasible now from existing data, deferred
   - ⏳ §3.2.6 industry dummies (1) — structural
   - ⏳ §3.2.7 macro extensions (4 factors) — needs INR forward / G-Sec / commodity beta sources
- 💤 3.3 Factor model upgrade (gated on 3.2 ≥ 25 factors):
   - 💤 3.3a IC stability weighting
   - 💤 3.3b Orthogonalization  **↔ 2.5**
   - 💤 3.3c Mean-variance portfolio  **↔ 2.4**
   - 💤 3.3d Risk decomposition (Barra-style)

## Side plans
- ✅ **Health Center cockpit redesign + 2 CRITICAL fixes** (this session, 2026-05-24 #3) — institutional-grade observability folded into cockpit's `/system` (nav renamed: System → Health Center):
   1. **Fixed CRITICAL: `fetch_shareholding` CHECK constraint regression** — [sources/tickertape_shareholding.py](../../sources/tickertape_shareholding.py) `_normalise()` clamp widened from 1e-6 to 0.05pp (covers all empirical rounding drift) and now drops the column (not the row) for genuinely out-of-range values, logging to `_OUT_OF_RANGE_LOG` with sid+col+date so contamination is surfaced not silent. Also fixed [tools/health_report.py](../../tools/health_report.py) streak query — it was flagging steps as "currently failing N consecutive days" even when the most-recent run had succeeded. Now uses a CTE that requires the latest run for that step to also be FAILED before counting it as broken.
   2. **Fixed CRITICAL: `ANALYST_CONSENSUS_GROWTH_WITHOUT_ANALYSTS`** — gated [signals/consensus.py](../../signals/consensus.py) SELECT on `(total_analysts IS NOT NULL OR price_target IS NOT NULL)` — Tickertape forecast-only rows (model projection, no analyst attribution) never fire `consensus_signal`. Reframed sanity check in [tools/data_sanity.py](../../tools/data_sanity.py) into a forward-looking gate validator `CONSENSUS_SIGNAL_WITHOUT_ANALYST_ATTRIBUTION` (joins `consensus_signals` × `analyst_consensus` for the latest snapshot; provably 0 when the gate holds). Added companion INFO check `ANALYST_ATTRIBUTION_COVERAGE` that tracks yfinance coverage gap (not a leak).
   3. **New: `get_health_overview()` API** — [cockpit/api.py](../../cockpit/api.py) folds 5 sources (`tools.health_report.gather()` + `tools.data_sanity.run()` + `pipeline_log endpoint_audit_*` + failed_streaks + dossier validator) into one ranked feed. Each issue: severity / source / category / code / message / table+col / sample / volume / drilldown URL. Sorted CRITICAL→WARN→INFO. Also exposes `/api/health/overview` JSON for future automation.
   4. **New: Health Center Overview tab** — [cockpit/templates/system.html](../../cockpit/templates/system.html). Verdict banner (with severity-coloured chips for CRITICAL/WARN/INFO counts), 4 pillar tiles (Data/Factors/Pipeline/Dossiers, each with letter grade A/B/C/D/F via simple critical+warn heuristic), and **Live Issues Inbox** — sortable table with severity radio (All/Actionable/CRITICAL only), source dropdown, category dropdown, text search. Each row has severity badge, code, message, table.column, sample, volume (n_bad/n_total + pct), and a drill button (`/sql?q=…` or `/explorer/{sid}` based on issue type).
   5. **Filter toolbars on all existing tabs** — Data tab (radio: All/Failing/Warning/Passing/Has-issues + search), Factors tab (radio: Status × Validation × Track + search), Pipeline tab (radio: status + search + new "Currently broken steps" panel separated from historical noise). Inventory tab untouched (already has per-domain accordions + sortable grids).
   6. **Nav renamed**: "System" → "Health Center" in [cockpit/templates/base.html](../../cockpit/templates/base.html); subtitle "Issues · data · factors · pipeline".
   7. **End state**: morning health report went `⚠ 2 CRITICAL, 12 warn` → `⚠ 1 CRITICAL, 12 warn`. The 1 remaining CRITICAL is a real `insider_timeline` endpoint gap (53.3% empty), now surfaced in cockpit Overview (Next 3 #1).
- ⏳ [0007 Market-share momentum cluster](0003-market-share-momentum-factor.md) — 4 factors, ~7 hr, proposed
- ⏳ [0008 Consumer demand pulse](0004-consumer-demand-pulse.md) — research-gated, validation before port
- ✅ **PT data model v2** (this session) — sell-side from yfinance only, LLM narrative-only, freshness via 3 proxies. ADR 0020. Tickertape `forecast_history.price` confirmed contaminated and removed from all consumers. `pt_revision_yoy` factor killed (production de-biased by ~14% of LARGE final_score; reshuffled 8/10 LARGE top picks). 4 new `analyst_consensus` columns + 4 freshness columns + cockpit card v2 with range bar, rating-mix trend, next-earnings + PT-change badges. Memory: `pt_source_landscape_2026_05_23`, `forecast_history_price_contaminated`.
   - ⏳ Model PT (Option B Step 2) → see Next 3 #3
   - ⏳ Rebuild pt_revision from `analyst_consensus_snapshots` once ≥12mo (calendar 2027-05+)
- ✅ **Drive-by — SMALL-cap missing current_price** (ANONDITA / TGVSL / BRRL / SUNSHIEL) — root cause: `sources/nse.py` filtered to `SERIES=='EQ'` only, dropping 175 universe stocks listed on SM/BE/ST/IV/RR/BZ (SME, trade-for-trade, REIT/InvIT). 359 remaining are BSE-only / delisted, now surfaced via new `COVERAGE_GAP` watchdog status. Fixed 2026-05-23.
- ✅ **Drive-by — Watchdog + scoring gaps surfaced by ANO=#1 SMALL** (2026-05-23 → 2026-05-24) — ANO ranked #1 with zero price rows and only 1-2 real signals (most defaulted). Six fixes + observability rewrite shipped:
   1. NSE harvester now accepts SM/BE/ST/IV/RR/BZ series → +175 stocks (see prior entry).
   2. `_minmax_by_tier` in [signals/smart_money.py](../../signals/smart_money.py) seeded missing stocks at default 50.0 → "no data" looked like "neutral". Fixed: NaN propagates; bulk fillna(0) only (no-deals is a real 0 observation, no-prices is missing).
   3. [scoring/screener.py](../../scoring/screener.py) `weight_sums` renormalization let data-sparse stocks score on just the signals they had. Added `weight_coverage` column; `_pick_eligible()` two-part gate at `MIN_WEIGHT_COVERAGE = 0.5` AND `MIN_PRICE_ROWS = 60` — see [ADR 0021](../decisions/0021-pick-eligibility-gate.md). ANO went rank #1 → #247; `daily_picks` dropped 2,448 → 2,020 rows.
   4. Watchdog only saw table-level `MAX(date)`; per-sid coverage holes were invisible. Added `COVERAGE_THRESHOLDS` in [db.py](../../db.py) + new `coverage_status` column in `data_health()`; `tools/freshness_watchdog._report_coverage()` logs `COVERAGE_GAP`/`COVERAGE_SEVERE` to `pipeline_log`.
   5. `tools/data_sanity.py` had no output-layer checks. Added 6: DAILY_PICK_NO_PRICES (CRITICAL), DAILY_PICK_THIN_SIGNAL_COVERAGE, SCORE_TABLE_DEFAULT_PROLIFERATION, UNIVERSE_PRICE_COVERAGE_LOW, REGULATORY_SECTOR_TAXONOMY_MISMATCH, REGULATORY_FEED_DARK + a generic `_generic_coverage_checks()` that auto-emits per-table coverage checks from `COVERAGE_THRESHOLDS` (no more manual check-per-table).
   6. Gillette dossier showed 2023 regulatory articles in 2026 view: [cockpit/api.py](../../cockpit/api.py) `get_regulatory_for_sector` was string-sorting RFC-2822 `published_at` ("Wed, 27 Sep 2023" lexicographically > "Sun, 14 Sep 2025"). Fixed: `julianday()` sort + 90d cutoff + sector-alias map ("Financial Services"→"Financials", "IT"→"Information Technology"). Also stricter `regulatory_events` staleness override (50d → 14d).
   7. New `tools/cockpit_endpoint_audit.py` proactively scans every per-stock cockpit endpoint against a stratified sample, logs `endpoint_audit_*` rows to pipeline_log. Surfaces "table is FRESH but cockpit returns empty for X% of stocks" gaps. Wired into `freshness_watchdog` cron. Caught: `insider_timeline` returns empty for 53% of stocks (LARGE caps included).
- ✅ **Backfilled 365d NSE prices** — `python -m sources.nse --backfill 365` after series-filter fix. +106,750 new rows. ANO went 0 → 165 price rows.
- ✅ **NaN-rate audit + gate hardening** (2026-05-24, this session) — six fixes shipped after a random-SMALL gap probe surfaced ABSM (ANO 2.0: rank #164 SMALL with zero quarterly_income, scoring on growth-only consensus + percentile-tied promoter):
   1. [signals/forensic.py](../../signals/forensic.py) M-Score floor tightened 4-of-6 → 5-of-6. Pre-fix, partial-data stocks substituted 1.0 (neutral ratio) for up-to-2 missing Beneish components, understating manipulation flags. M-Score non-NULL: 1799 → 1756 stocks (−43, the partial-data tail).
   2. [signals/promoter.py](../../signals/promoter.py) `_holding_modifier(NaN)` returns `None` (was `0.9`); caller emits raw signal without dampening when stake is unknown. Defensive — no live impact today since all 398 stocks in the audit's 0.60 cluster have known stakes (354 in 65-75, 34 in 25-40); cluster is a real percentile-tie artifact, not a leak.
   3. [scoring/screener.py](../../scoring/screener.py) `daily_picks` now persists `weight_coverage` + `price_rows` + new `fundamental_coverage` columns (output-side + input-side gates). HANDOFF 2026-05-23 claimed the first two were added; PRAGMA showed they weren't.
   4. [scoring/screener.py](../../scoring/screener.py) **new** `MIN_FUNDAMENTAL_COVERAGE = 0.50` gate — ≥4 of 8 quarterly_income rows required. Catches ABSM-class (signal modules emit non-NULL OUTPUT from partial INPUT). Drops 218 SMALL stocks (all of fundamental gating happens in SMALL).
   5. [config.py](../../config.py) `SCREEN.trust_exclusion_patterns` + [scoring/screener.py](../../scoring/screener.py) drop InvIT/REIT/business-trust instruments from screener universe (22 excluded). Distribution-yield vehicles don't share equity ranking semantics. SHREI was the canary (40 of 65 trading days in last 90d, ranked SMALL).
   6. [tools/data_sanity.py](../../tools/data_sanity.py) new `ANALYST_CONSENSUS_GROWTH_WITHOUT_ANALYSTS` check — fires CRITICAL at 59.3% (see Next 3 #2). Mixed-provenance row: growth from one source, PT/count from another.
   7. [db.py](../../db.py) `_ensure_columns()` idempotent ALTER TABLE migration helper — applied to live DB; new daily_picks columns landed. [schema.sql](../../schema.sql) also updated for fresh installs.
   8. **Track-3 sweep clean** — `grep -nE 'fillna|pd.isna|else <N>'` across all 20 Track-3 factor files found zero default-substitution patterns. Modern factors propagate NaN by construction.
   9. [output/dossier.py](../../output/dossier.py) dossier prompt now suppresses N/A signal rows + skips Piotroski / Forensic for Financial-sector stocks (sub-model territory). Validator extended with `_SIGNAL_KEYWORD_MAP` — flags soft hallucination where narrative references a signal name (Piotroski, Accruals, Consensus, Smart Money, Promoter, M-Score, Z-Score, Sentiment) when the corresponding context value is None. Caught today: MUTT + BJAT (both Financials) had "solid Piotroski score" in narrative despite f_score=None. Regenerated 5 LARGE dossiers — all clean, Piotroski no longer mentioned for MUTT/BJAT.
   10. [sources/yfinance_analyst.py](../../sources/yfinance_analyst.py) `n_analysts` falls back to `sum(n_strong_buy..n_strong_sell)` when yfinance's `numberOfAnalystOpinions` is NULL despite per-rating counts being populated. Caught KALYA 2026-05-24 (NULL total_analysts but n_buy=9, recommendation_key='strong_buy'). Scope: 1 of 2,440 stocks today — edge case but real. Takes effect next yfinance refresh.
   11. [output/dossier.py](../../output/dossier.py) `_clip_growth()` caps eps_growth / revenue_growth at ±300% before showing to the LLM. 184 daily_picks stocks have |growth|>200% (turnaround / near-zero-base artifacts — VSKI rank #1 SMALL with eps_growth=2941%, JSTL #12 LARGE with 696%). consensus.py clips internally, but raw values flowed into the LLM prompt which is fragile. Clip display shows "300+" / "-300+" — explicit, not silent.
   12. [tools/data_sanity.py](../../tools/data_sanity.py) new `EXTREME_GROWTH_PCT_IN_TOP_PICKS` check — fires WARN when top-100 picks have |growth_pct|>300%. Currently fires at WARN level today.
   13. [signals/insider_signal.py](../../signals/insider_signal.py) two fixes — (a) `"KMP"` in `CATEGORY_WEIGHTS` never matched `"Key Managerial Personnel"` (substring fail on acronym); 92 KMP trades / 90d / 26 stocks silently skipped. Now uses full name. (b) Description "No insider activity in last 90d" was misleading when trades existed but only from non-tracked categories (Employees, Other). Now reports "N trade(s) from non-tracked categories" — caught WIPR 2026-05-24 (6 Employee trades).
   14. **Forecast_history contamination purged** — 2,028 rows where `forecast_history.value` matched same-stock latest `stock_prices.close` (Tickertape pre-fix contamination). Producer fix from 2026-05-23 stopped future contamination; this is the one-time cleanup. `FORECAST_HISTORY_IS_PRICE_HISTORY` sanity check now reads 0/1696.
   15. **Regulatory taxonomy mismatch fixed at source + backfill** — [sources/regulatory_classifier.py](../../sources/regulatory_classifier.py) prompt now uses canonical `stocks.sector` taxonomy ("Financials" not "Financial Services", "Information Technology" not "IT"). Renamed 1,482 existing rows in regulatory_signals (937 Financials + 545 IT) after deleting 156 dupe rows that already had canonical names for same event_id.
   16. **Regulatory + Broker harvesters wired into [config.py PIPELINE_STEPS](../../config.py#L222)** — `fetch_regulatory` (weekly), `classify_regulatory` (daily), `fetch_broker_recos` (weekly). Previously these ran ad-hoc only — caused `REGULATORY_FEED_DARK` 43-day silent gap. Broker source confirmed alive: HINDALCO returned 6 named-broker reports today (Motilal Oswal, Prabhudas Lilladher, Emkay Global). One-time `python -m sources.moneycontrol_recos --discover-only` needed to populate `stocks.mc_slug` (currently 1/2,448).
   17. [sources/yfinance_analyst.py](../../sources/yfinance_analyst.py) `n_analysts` fallback (also entry #10) — re-noted: applies on next yfinance refresh.
   18. **Cockpit Factor Library screen split into Data Health vs Validation** — [cockpit/api.py:2300](../../cockpit/api.py#L2300) + [cockpit/templates/system.html:213](../../cockpit/templates/system.html#L213). The pre-2026-05-24 composite mixed 5 things (coverage + freshness + backtest + PIT + model) into one "F" grade, making DROP-verdict factors look like broken data. Now: **Data Health** = 65% coverage + 25% freshness + 10% PIT (data-side only). **Validation** = KEEP/WEAK/DROP based purely on |t-stat|. Empirical post-fix: 19 factors were previously F-shadowed despite healthy data (e.g. Book-to-Price data=A val=DROP). True data-F count = 15.
   19. **PIT helpers shipped for insider_signal + sentiment_7d** — [tools/reconstruct_pit.py](../../tools/reconstruct_pit.py) + [db.py BACKTEST_SIGNALS](../../db.py) + [schema migration](../../db.py#L80) for `daily_snapshots_pit.insider_score` + `sentiment_7d`. Reconstructed across 7 v2 PIT dates: insider has 363-535 stocks/date (4.5yr depth from insider_trades), sentiment is sparse pre-2024-04 (news_articles cutoff) and 10-118 stocks/date post-2024-04.
   20. **Removed 6 false F-grades — TRACK3_EXTRAS dedupe** — [cockpit/api.py](../../cockpit/api.py) `TRACK3_EXTRAS = []`. Track 3 factors (roic, fcf_yield, revenue_cv_5y, relative_turnover, relative_growth, share_momentum) were registered in BOTH BACKTEST_SIGNALS and TRACK3_EXTRAS, double-counting each one. The duplicate via TRACK3_EXTRAS showed F because the lookup path silently returned coverage=0. F-grade count: 14 → 8.
   21. **Honest F-grade reason labels** — [cockpit/api.py:2311](../../cockpit/api.py#L2311). Each remaining F now shows a specific reason: "sparse by nature — X% of universe has the underlying event" (bulk deals, news, sentiment), "sector-level signal — per-stock coverage not applicable" (regulatory/macro tilt), "data depth limited — needs NSE archive backfill" (FII/DII), "composite output — backtest via portfolio (Track 2.4), not as factor" (Final Composite). No more bland "many stocks unscored" implying a bug.
   22. **Pipeline + cockpit manually triggered** — `sudo systemctl restart alpha-cockpit` after factor-screen + PIT helper changes. Pipeline run + mc_slug discovery launched in background.
   23. **Full v1 window PIT extension for insider + sentiment** — `tools/reconstruct_pit --months 36` populated `daily_snapshots_pit.insider_score` for 36 monthly dates (2023-06 → 2026-05). Coverage ramps from 2/2448 stocks in mid-2023 to 300-400/2448 from mid-2024 onward (reflects insider_trades real depth). Sentiment populated only for dates after news_articles cutoff (2024-04+, max 118 stocks/date). Enables backtest IC compute for both new factors on full v1 history. 88,128 rows written in 80 seconds.
   24. **Moneycontrol discovery silent-mode bug fixed** — [sources/moneycontrol_recos.py:322-339](../../sources/moneycontrol_recos.py#L322). Heartbeat print was placed AFTER `if discover_only: continue` → discovery ran 30+ minutes with zero log output (CLAUDE.md violation: "silent failures are the enemy"). Now prints `[i/N] mode=discovery · slugs_found=K · no_slug=M` every 50 stocks regardless of mode. Verified working — discovery currently at 509/2448 mc_slug populated.
   25. **Historical backfill harvester** — new [sources/historical_backfill.py](../../sources/historical_backfill.py) wraps nselib functions (`bulk_deal_data`, `short_selling_data`, `participant_wise_open_interest`) with date chunking, idempotent INSERT OR IGNORE, 2.5s rate limit, and loud progress prints. Smoke-tested all 3 source types. Full backfill launched in background sequentially (CLAUDE.md: no two harvesters simultaneously): bulk 2021+ · short 2022+ · fii_fno 2022+. Estimated ~1.5hr runtime. Output: `output/backfill_2026-05-24.log`.
   26. **Installed `xlrd`** in venv (`~/alpha-signal/venv/bin/pip install xlrd`) — required by `nselib.derivatives.fii_derivatives_statistics` which serves XLS format. Without it the FII F&O backfill would silently skip every date.
   27. **Per-factor backtest cadence + Newey-West** — three new pieces of infrastructure shipped together:
       - `BACKTEST_CADENCE` registry in [db.py:884](../../db.py#L884) — maps each signal to monthly / weekly / sector_portfolio / portfolio. 9 behavioral signals tagged weekly, 51 fundamentals stay monthly. Helper `get_backtest_cadence(signal_id)` with safe monthly default.
       - `generate_weekly_eval_dates()` + `--cadence weekly` flag in [tools/reconstruct_pit.py](../../tools/reconstruct_pit.py) — generates every-Friday eval dates (default 104 weeks). Reconstructed 6 behavioral signals (insider, sentiment, bulk, short, delivery, news_volume) + fwd_return_20d across 107 Friday dates → 254K + 254K = 508K new rows in `daily_snapshots_pit`.
       - Newey-West variance estimator + cadence-aware dispatch in [tools/backtest_pit.py](../../tools/backtest_pit.py). NW lag per signal: insider/delivery_anomaly_z=13 (90d window), delivery/bulk/short=4 (30d), sentiment/news_volume=3 (fwd_return overlap only). Reports source as `v2_recompute:weekly+NW<lag>` so cadence is visible in the IC table.
       - **3 new KEEP-verdict findings** the monthly framework had hidden:
         - `bulk_deal_signal SMALL`: monthly t=0.66 (DROP, n=3) → weekly+NW t=2.56 (KEEP, n=70)
         - `delivery_anomaly_z SMALL`: monthly t=0.64 (DROP, n=5) → weekly+NW t=4.11 (KEEP, n=100)
         - `sentiment_7d LARGE`: monthly INSUFFICIENT (n=1) → weekly+NW t=-3.88 (KEEP, n=4 — preliminary, needs more data)
       - `avg_delivery_pct_30d SMALL` confirmed at higher n (KEEP at both cadences, t≈4.2).
       - `short_selling` and `insider` (most tiers) confirmed DROP under both frameworks — real noise.
   28. **v1 archive importer** — new [sources/v1_archive_import.py](../../sources/v1_archive_import.py) reads (read-only per CLAUDE.md) from `/home/ubuntu/alpha-signal/data/`. Imported:
       - **insider_archive.csv** (123K rows / Feb-May 2026) → +2,890 net new insider_trades (87K were dupes — v2's NSE PIT bulk harvester already had them). insider_trades: 26,741 → 29,631.
       - **46× article_scores_YYYY-MM-DD.csv** (Mar 15 → May 10) → +9,189 sentiment_scores rows. sentiment_scores: 25 dates → 67 dates, 2026-03-15 → 2026-05-24.
       - Other v1 archives (delivery_30d, bulk_30d, classified_news, all_snapshots) skipped — either same-source-as-v2 or schema-mismatched.
   Pick gate now: 554 excluded today (108 weight + 418 prices + 218 fundamentals; overlap counted once). `daily_picks` 2020 → 1872 rows.
- ✅ **/graphify on whole repo** (this session) — 1,792 nodes / 2,801 edges / 196 communities. AST extraction free (1,133 nodes); semantic extraction via 18 parallel subagents (~890K tokens). 80× per-query token reduction vs raw corpus. graph.html + GRAPH_REPORT.md + graph.json in `graphify-out/` (gitignored). Top god nodes: `read_sql()` (213 edges), `upsert_df()` (110), `get_db()` (74). Post-commit + post-checkout git hooks installed to auto-rebuild. MCP server registered in `~/.claude.json` for project — `query_graph` / `god_nodes` / `shortest_path` etc. available in next CC session.
- ✅ **Cockpit sidebar v1** (this session) — widened rail 64→232px, 3 sections (Daily/Analysis/Ops), labels + subtitles per item.
- ✅ **Observability drive-bys** (this session):
   - ✅ `daily_picks` rank tie-break — secondary sort by `sid`, `method="first"`
   - ✅ `fetch_shareholding` CHECK constraint — float-epsilon clamp in `_normalise`
   - ✅ `freshness_watchdog` cron — missing `cd` into v2 dir prevented module import
   - ✅ `tools/data_sanity.py FORECAST_HISTORY_IS_PRICE_HISTORY` strengthened — cross-date JOIN now fires CRITICAL on 95.5% contaminated stocks

## Open questions (pending roadmap decisions)
- 2.2 banking-metrics source: Tickertape-first or RBI-first?
- 2.3 commodity-data gaps: skip cement/steel until manual curation?
- 0008 paid pytrends fallback if free tier blocks?
- Insider / regulatory / macro signal weights: tertiary 0.2× for first two, zero for macro?
- `pt_upside` |t|=7.20 LARGE after PT cleanup — is the price-anchor mechanism real alpha or artifact? Re-test after ≥3 monthly snapshots accumulate (calendar: 2026-08).

## Decisions changing roadmap
- [ADR 0009](../decisions/0009-factor-track-parallel-to-d-track.md) — Tracks 2 & 3 run parallel; integration points 2.4↔3.3c and 2.5↔3.3b
- [ADR 0013](../decisions/0013-industry-not-sector-as-drill-unit.md) — industry replaces GICS sector as drill unit
- [ADR 0015](../decisions/0015-track-numbering-and-rename.md) — Track 1/2/3 naming + numbering convention (this doc's vocabulary)
- [ADR 0016](../decisions/0016-plan-numbering-fresh-start.md) — active plans renumbered 0001–0004 chronologically; archived keep historical numbers
- [ADR 0017](../decisions/0017-factor-library-two-tier-registry.md) — explicit two-tier registry (`BACKTEST_SIGNALS` + `FACTOR_LIBRARY`) replaces the implicit "in/out of BACKTEST_SIGNALS" tier signal
- [ADR 0018](../decisions/0018-pt-data-model-episodic-cadence.md) — analyst PT is episodic, not continuous; 3 tables × 3 cadences (`analyst_consensus` daily, `analyst_consensus_snapshots` monthly, `forecast_history` annual)
- [ADR 0019](../decisions/0019-observability-sensor-surface-alert.md) — sanity assertions + daily health report + push alerts as the layer that catches silent-output bugs that freshness checks miss
- [ADR 0020](../decisions/0020-pt-data-model-v2-sell-side-only-llm-narrative-only.md) — supersedes parts of ADR 0018: `forecast_history.price` is contaminated and removed from all consumers; sell-side PT is yfinance-only; LLM never produces structured numbers; freshness surfaced via 3 proxies (next earnings, rating-mix trend, our PT-change detection)
- [ADR 0021](../decisions/0021-pick-eligibility-gate.md) — `daily_picks` requires `weight_coverage ≥ 0.50` AND `price_rows ≥ 60` (extended 2026-05-24 to also require `fundamental_coverage ≥ 0.50`); data-blank stocks no longer get ranked
- [ADR 0022](../decisions/0022-per-factor-backtest-cadence-newey-west.md) — each factor declares a `backtest_cadence` (monthly/weekly/sector_portfolio/portfolio); behavioral signals now backtested at weekly cadence with Newey-West variance correction; uncovered 3 new KEEP-verdict signals the monthly framework had hidden
- [ADR 0023](../decisions/0023-health-center-cockpit-as-single-window.md) — cockpit `/system` (renamed Health Center) is the single window into system health; `get_health_overview()` aggregates findings from `health_report` + `data_sanity` + `endpoint_audit` + dossier validator into one Live Issues Inbox; sub-tabs are slices, not separate sources of truth

## Recently archived
- 0001 regulatory signal — implemented
- 0002 macro data — implemented
- 0004 PIT reconstruction — shipped, captured in ADRs 0010 + 0012
- 0006 sector intelligence page — implemented, ADRs 0013 + 0014
