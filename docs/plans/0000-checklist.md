# Alpha Signal v2 — Progress Checklist
_Last updated: 2026-05-29 (DuckDB read-replica + Plan 0006 A+B+C shipped + Track 2.2b-v2 financial_signal split + 2 bench factors wired) · Plans are truth, this is the view. Update via `/handoff`._
_Glyphs: ✅ done · ⏳ next/in-progress · 🚫 blocked · 💤 parked · ↔ cross-track integration point_
_Convention: [ADR 0015](../decisions/0015-track-numbering-and-rename.md) (tracks) + [ADR 0016](../decisions/0016-plan-numbering-fresh-start.md) (plans)._

## Next 3
1. ⏳ **Plan 0006 Phase D — LLM-narrated sector dossiers** — schema + prompt in [plan 0006 §Phase D](0006-sector-dossiers.md). New `sector_dossiers` table; 11 LLM calls/night (~₹3-5). Mirror `output/dossier.py` hygiene contract (no raw numbers in narrative).
2. ⏳ **Track 3.1b — NSE F&O OI probe** — unblocks `§3.2.2` options-implied (8 factors). Probe `nselib.derivatives` (option chain, OI history, participant-wise OI) for date-range support; new `fno_option_chain` + `fno_oi_history` schemas; fetcher with cookie-warm + 2s rate; PIPELINE entry + freshness watchdog. Independent of sector-dossier work.
3. ⏳ **`financial_recovery` accumulator gate** — re-run `python -m tools.reconstruct_pit --signal financial_recovery --months 36` after Q1 FY27 NBFC results land (~late Jul 2026); re-backtest via `tools.backtest_pit`. If MID t-stat moves toward 2.0 (currently +1.55 WEAK), route into `SIGNAL_WEIGHTS[MID]` at ~10% weight. If regresses, re-think direction-flip framing.
4. ⏳ **Variant promotion** + **Refresh `nse_index_history`** — queued; promotion gated on orthogonalization.

## Queued
- ⏳ **[Plan 0006 — Sector dossiers](0006-sector-dossiers.md)** — `/sectors` front door rebuild. MVP **A + B + C shipped 2026-05-29** (see Shipped today). Remaining:
   - ⏳ Phase D — LLM-narrated per-sector thesis. New `sector_dossiers` table; 11 LLM calls/night (~₹3-5). Mirror `output/dossier.py` hygiene contract.
   - ⏳ Phase E — per-sector horizon scores (short / medium / long badges). Needs new `signals/sector_momentum.py` factor.

## Shipped today (2026-05-29, cont.)
- ✅ **Track 2.2b-v2 — financial_signal split by direction** ([ADR 0032 proposed](../decisions/0032-tier-direction-flip-split-signal.md), commit `0d8d8bd`). Single-direction Phase 2.2d composite FAILED the done gate (t = -0.75 / -1.30 / -0.34); the diagnostic surfaced opposing signs on NPA (LARGE/MID `net_npa_pct` t=+2.39/+4.16 mean-reverting, SMALL `gross_npa_pct` t=-3.09 quality compounds). Split into [signals/financial_signal.py](../../signals/financial_signal.py)'s `financial_quality` (direction='lower', for SMALL) and `financial_recovery` (direction='higher', for LARGE/MID), sharing profitability/capital/funding components. Schema migrated via `_COLUMN_MIGRATIONS` (financial_signal_scores + daily_snapshots_pit); `financial_signal` kept as back-compat alias = quality. BACKTEST_SIGNALS in `db.py` updated (financial_signal → SUPERSEDED; both new → READY). PIT helper in [tools/reconstruct_pit.py:pit_financial_signal()](../../tools/reconstruct_pit.py) writes all three. **Backtest on 30 monthly PIT anchors**: financial_recovery MID **t=+1.55 WEAK** (mechanism confirmed), SMALL **t=-1.88 WEAK** (confirms quality direction for SMALL); financial_quality MID **t=-0.48** + SMALL **t=+0.44** DROP. Neither clears |t|≥2.0; both stay on bench, NOT routed into screener. Will revisit ~Q1 FY27.
- ✅ **2 non-colinear bench factors wired into screener** (commit `0d8d8bd`). `pledge_quality` (SMALL t=5.90, KEEP) — added to existing `promoter_signals` SELECT in [scoring/screener.py:_load_signals()](../../scoring/screener.py). `delivery_anomaly_z` (SMALL t=4.76, KEEP) — new [signals/delivery_anomaly.py](../../signals/delivery_anomaly.py) mirrors `momentum.py` live-compute pattern (90d z-score of latest delivery_pct vs baseline, clip ±5, 1,999 stocks scored). Both added to `SIGNAL_COLS`. [tools/optimize_weights.py](../../tools/optimize_weights.py) gains `--filter-wired` flag (drops unwired + renormalises per tier, paste-ready). `config.SIGNAL_WEIGHTS_RETURN` + `SIGNAL_WEIGHTS_SHARPE` refreshed: **unwired share LARGE 0% / MID 0% / SMALL 0%**. Variant pick-gate excluded count 251 → **210** (-41) because new factors reduce analyst-coverage dependence in SMALL. `pledge_quality` t=5.90 SMALL + `delivery_anomaly_z` t=4.76 SMALL each get their natural ~12% weight in SMALL variants.
- ✅ **NBFC GNPA fallback probe** (Phase 2.2c, research only, parked). Confirmed gap is data-not-on-source — Screener.in has labels but empty cells for 33/81 NBFCs (REC, IRFC, BAJAJFINSV, JIOFIN sampled). Source survey: RBI XBRL public portal dead (`xbrl.rbi.org.in` HTTP 000); NSE corporate-filings XBRL has `ImpairmentOnFinancialInstruments` + `FinanicalAssets` but no GNPA% tag in NBFC_INDAS taxonomy; NSE quarterly results PDF is the highest-fidelity path (2-3 day build for PDF table extraction). **Parked**: backtest sample size is the rate-limiter, not the missing 33 NBFCs. `financial_recovery` MID at t=1.55 will cross 2.0 with ~6 more periods if the mechanism holds, regardless of NBFC coverage. Re-evaluate after Q4 FY26 data.
- ✅ **DuckDB read-replica + perf wins** ([ADR 0031](../decisions/0031-duckdb-read-replica.md)). New `tools/duckdb_refresh.py` rebuilds `data/alpha_signal.duckdb` (87 MB columnar) nightly after pipeline; `tools/bench_duckdb_vs_sqlite.py` records the win (11-57× on column-scan-heavy SELECTs). New `db.read_sql_fast()` helper routes mirrored-table reads to DuckDB, falls back to SQLite if file missing. SQLite stays the write-side source of truth. **Measured cockpit gains**: `/model` cold-render 5.6s → 1.6s (3.5×) via [cockpit_ops/api.py:get_backtest_roster](../../cockpit_ops/api.py); `/system` cold-render 33.9s → 13.1s (2.6×) via a SEPARATE [health.py:534](../../health.py) `factor_type_conformance` rewrite — consolidated N per-column scans into 1, sample tables >500K rows at 200K LIMIT (CPU-bound `typeof()` was the bottleneck; not a DuckDB candidate because the check is fundamentally about SQLite's dynamic-typing surprises). Also fixed pre-existing latent circular-import bug in [cockpit_ops/app.py](../../cockpit_ops/app.py) surfaced by the cockpit restart.
- ✅ **Plan 0006 Sector dossiers — Phases A + B + C** ([plan](0006-sector-dossiers.md)). Phase A: [signals/sector_briefs.py](../../signals/sector_briefs.py) + new `sector_briefs` table — rolls macro_sector_signals + daily_picks + regulatory_signals into one row per sector per date with a 4-bucket classifier {BOOMING/LIKELY/HEADWIND/QUIET}. Today: 0/4/1/6. Phase B: [signals/sector_forces.py](../../signals/sector_forces.py) + new `sector_force_breakdown` table — 33 rows/day across 3 forces (macro 10+/1−, regulation 7+/2−, tech 11+/0−; market reserved for v2 — v2 `fii_dii_cash_flow` is index-level only). Phase C: [cockpit/api.py:get_sector_digest()](../../cockpit/api.py) + Tab "Today" rewrite in [cockpit/templates/sectors.html](../../cockpit/templates/sectors.html). 47-card heatmap deleted (`grep -c "ind-card"` now 0). Conflicts-first ordering surfaces Energy ("model still picking here — RELIANCE, BPCL, IOC") at top. Drill-down `/sectors?sector=X#per-sector` unchanged.
- ✅ **Rank-skill gate** — [tools/validate_rank_skill.py](../../tools/validate_rank_skill.py). The go/no-go test before deploying own capital: per-tier top-vs-bottom decile spread on **non-overlapping** windows with a 95% band; never prints "PROVEN" under 6 independent periods. Current read: only **2 independent 20d windows** exist (2026-04-09, 2026-05-07) — LARGE −1.03pp, MID +0.12pp, SMALL +0.39pp, all UNPROVEN. **Do not deploy capital yet.** Re-run weekly as `pick_outcomes` accumulates; invest a tier only when its independent spread's 95% range clears 0 on ≥6 periods.

## Shipped today (2026-05-29)
- ✅ **Factor correlation diagnostic** — [tools/factor_correlation.py](../../tools/factor_correlation.py). Findings: 5 clusters per tier at |ρ|≥0.6, including a "is this a strong business" mega-cluster of 8-12 factors (roe / roa / roic / interest_coverage / debt_to_equity / fcf_margin / fcf_yield / profit_margin / z_score / quality_composite). Killed 5 of 7 proposed wirings as colinear. Output: `data/factor_correlation_{LARGE,MID,SMALL}.json` + `output/factor_correlation_report.txt`.
- ✅ **Live equity curve** — new `pick_outcomes` table + [tools/compute_pick_outcomes.py](../../tools/compute_pick_outcomes.py) + cockpit [/model/outcomes](../../cockpit/templates/model_outcomes.html). 76K outcome rows computed across 5/20d windows × 2,000 stocks × 50 dates. Headline: 20d top-10 baskets show LARGE +2.44% / +2.69pp vs NIFTY 50; MID +3.81% / +0.52pp; SMALL +4.11% / -0.41pp vs SMALLCAP 250. Rank-decile spreads tiny (LARGE +0.04pp · MID +1.69pp · SMALL +0.35pp) — model's rank ordering not yet validated as predictive at 9 dates per tier. Wired into PIPELINE_STEPS daily.
- ✅ **Health drive-by** — dossier sentiment regex tightened (M&M CRITICAL cleared); watchdog CHECK constraint widened + heartbeat row on clean scans (139h-stale WARN cleared). Commit `2a8f299`.
- ✅ **Cockpit restart + spot-check** — `/model` (was HTTP 500) now serves 313KB in 6.7ms warm; `/model/variants` divergent stars rendering; `/mutual-funds/122639` Holdings tab present.

## Track 1 — Foundation  ✅ done 2026-05-01
Audit + tier infra + stratified backtest + 36mo PIT + cutover. See ADRs 0009-0014.

## Track 2 — Portfolio  · [plan 0001](0001-mother-plan.md)
- ✅ 2.1 Small-cap quality gate
- ⏳ 2.2 Financial sub-model — **source decision flipped 2026-05-29: Screener.in, not Tickertape** ([ADR 0030](../decisions/0030-banking-metrics-screener-first.md)). Probe showed Tickertape carries no banking-specific ratios; Screener.in stock pages have GNPA/NNPA/NII/Interest/Deposits. Scope clarified to **158 Banks+NBFCs** (the 91 AMC+Insurance+Capital-Markets stay on main screener).
   - ✅ Phase 2.2a-i: probe + ADR + `banking_metrics` table (28 cols, schema in `schema.sql`)
   - ✅ Phase 2.2a-ii: `sources/banking_metrics.py` — Screener.in bank-page parser, 158-SID backfill **DONE 2026-05-29 (9.1 min)**. Coverage: **131/132 ex-MICRO (99.2%)** — Banks 41/41 (100%), NBFCs LARGE/MID/SMALL 80/81 (98.8%), NBFCs MICRO 20/36 (excluded anyway). 17 failures all 404'd both standalone+consolidated (delisted/micro-shells). 3,365 rows total. PIPELINE wired (`fetch_banking_metrics`, monthly).
   - ✅ Phase 2.2b: `signals/financial_signal.py` **DONE 2026-05-29**. 141 stocks scored, 105 with financial_signal ≠ NULL, 36 INSUFFICIENT (mostly NBFCs missing both GNPA + NII). Z-scored within (industry, cap_tier); renormalized over present components. Wired to PIPELINE_STEPS as `compute_financial_signal` (daily, non-critical, before screener). **Print-only** — `scoring/screener.py` routing deferred to Phase 2.2d after t-stat ≥ 2.0 backtest validation. Validation spot-checks (top scorers KTKM/ICBK/BMBK/BJFN match reputation; bottom scorers UTK/UNBK/PNBK/SRTR match known weak names). New `financial_signal_scores` table (17 cols). **TODO** (next session): add `financial_signal` to `daily_snapshots_pit` via `_COLUMN_MIGRATIONS` in db.py + BACKTEST_SIGNALS registry entry. Currently blocked by parallel-session uncommitted edits to db.py.
   - 💤 Phase 2.2c: NBFC GNPA fallback — **PROBED + PARKED 2026-05-29**. Gap confirmed data-not-on-source (33/81 NBFCs Screener-empty: REC/IRFC/BAJAJFINSV/JIOFIN). RBI XBRL portal dead; NSE corporate-filings XBRL lacks GNPA% tag (has stage-3 financial assets + ECL but not the ratio); NSE quarterly results PDF is best-fidelity (2-3 day PDF extraction build). Parked because backtest sample size dominates as the rate-limiter — `financial_recovery` MID at t=1.55 crosses 2.0 with ~6 more quarterly periods if mechanism holds.
   - ⚠ Phase 2.2d: PIT + backtest **DONE 2026-05-29**. Composite FAILED done gate (t = -0.75 / -1.30 / -0.34). Diagnostic surfaced direction-flip on NPA — see 2.2b-v2 below.
   - ✅ Phase 2.2b-v2: **DONE 2026-05-29** (commit `0d8d8bd`) — split into `financial_quality` (SMALL, direction='lower') + `financial_recovery` (LARGE/MID, direction='higher'), shared profitability/capital/funding components. Schema migrated; PIT helper writes both columns + back-compat `financial_signal` alias. Backtest on 30 monthly PIT anchors: `financial_recovery` MID **t=+1.55 WEAK** (mechanism confirmed), SMALL **t=-1.88 WEAK** (confirms SMALL quality direction). Neither clears |t|≥2.0; both stay on bench, NOT routed into screener. Re-test ~Q1 FY27. See [proposed ADR 0032](../decisions/0032-tier-direction-flip-split-signal.md) for the generalizable methodology.

   **Coverage report (latest-quarterly per stock, 2026-05-29):**
   - Banks: 41/41 stocks · GNPA 40/41 · NNPA 40/41 · NII 41/41 · BVPS 41/41 · Deposits 41/41 · COF 41/41 ✓
   - NBFCs: 100/100 stocks · GNPA 20/100 (big gap) · NNPA 19/100 · NII 70/100 · BVPS 95/100 · Borrowings 70/100 · COF 63/100 · Deposits 0/100 (expected — non-deposit-taking)
- ⏳ 2.3 Cyclical overlay (parallel-able with 2.2)
- ⏳ 2.4 Segment models + portfolio (capstone) **↔ 3.3c**
- 🚫 2.5 XGBoost overlay **↔ 3.3b** — needs ≥6mo PIT, ETA early 2027

## Track 3 — Factor model  · [plan 0002](0002-100-factors-and-model.md)
**State**: 23/50 PIT-shipped; production screener uses 8 factors (LARGE 6, MID 6, SMALL 7); MaxReturn/MaxSharpe variants now use 10 factors (pt_upside, eps_growth wired 2026-05-28 + pledge_quality, delivery_anomaly_z wired 2026-05-29 → `tools.optimize_weights --filter-wired` shows **WIRED_KEYS coverage 100/100/100% LARGE/MID/SMALL**); 7 more KEEPs still on bench (interest_coverage, ccc, nwc_to_revenue, goodwill_to_assets MID; roic, fcf_margin SMALL; eps_revision).

- 3.1 Data acquisition:
   - ✅ 3.1a Screener Premium (2,119/2,448 stocks, 681K rows)
   - ⏳ 3.1b NSE F&O OI ← **active** (unblocks §3.2.2) — probe `nselib.derivatives`, schema, fetcher, cron
   - ⏳ 3.1c Kite Connect
   - ⏳ 3.1d PIB + earnings call NLP
- 3.2 Factor build (target 50):
   - ✅ §3.2.1 forensic/capital-allocation — 11/15 shipped; `pt_revision_yoy` DROPPED 2026-05-23 (ADR 0020); rebuild from snapshots calendar 2027-05+
   - 🚫 §3.2.2 options-implied (8) — blocked on 3.1b
   - 🚫 §3.2.3 microstructure (9) — blocked on 3.1c
   - 🚫 §3.2.4 NLP/sentiment (7) — blocked on 3.1d
   - ⏳ §3.2.5 event-time/PEAD (6) — feasible now, deferred
   - ⏳ §3.2.6 industry dummies (1)
   - ⏳ §3.2.7 macro extensions (4) — needs INR forward / G-Sec / commodity beta sources
- 3.3 Model upgrade (gated on 3.2 ≥ 25 factors; informal advance 2026-05-28):
   - ⏳ 3.3a IC stability — `SIGNAL_WEIGHTS_SHARPE` $w_i ∝ ICIR$ shipped, not yet wired to `daily_picks` (Next 3 #3)
   - 💤 3.3b Orthogonalization **↔ 2.5**
   - 💤 3.3c Mean-variance portfolio **↔ 2.4**
   - ⏳ 3.3d MaxReturn — `SIGNAL_WEIGHTS_RETURN` $w_i ∝ |t|$ shipped, same promotion gate
   - 💤 3.3e Risk decomposition (Barra-style)

## Side plans
- ✅ [0005 Data confidence 75 → 95](0005-data-confidence-to-95.md) — Phases A–E shipped (~93/100). Phase F (per-stock lineage wave 1) done; wave 2 = roll across remaining ~31 signal modules.
- ✅ MF research section (plans 0001-MF + zazzy-eich) — Phases 1-4 shipped; investable-only default + ETMoney matcher + holdings auto-scrape complete.
- ✅ Ops cockpit split — Stage 1 (service-level :3001) + Stage 2 (code-level extraction).
- ✅ Cockpit cold-restart perf rewrite — `/system` 140×, `/news` 50×, `/portfolio` 100×.
- ✅ Health Center cockpit redesign (ADR 0023).
- ⏳ [0007 Market-share momentum cluster](0003-market-share-momentum-factor.md) — 4 factors, ~7 hr, proposed
- ⏳ [0008 Consumer demand pulse](0004-consumer-demand-pulse.md) — research-gated

## Open questions
- 2.2 banking-metrics source: Tickertape-first or RBI-first?
- 2.3 commodity-data gaps: skip cement/steel until manual curation?
- 0008 paid pytrends fallback if free tier blocks?
- Insider / regulatory / macro signal weights: tertiary 0.2× for first two, zero for macro?
- `pt_upside` |t|=7.20 LARGE after PT cleanup — real alpha or artifact? Re-test after ≥3 monthly snapshots (calendar 2026-08).

## Decisions changing roadmap
- [0009](../decisions/0009-factor-track-parallel-to-d-track.md) — Tracks 2 & 3 parallel; integration points 2.4↔3.3c, 2.5↔3.3b
- [0013](../decisions/0013-industry-not-sector-as-drill-unit.md) — industry replaces GICS sector as drill unit
- [0015](../decisions/0015-track-numbering-and-rename.md) — track naming convention
- [0016](../decisions/0016-plan-numbering-fresh-start.md) — plans renumbered 0001-0004
- [0017](../decisions/0017-factor-library-two-tier-registry.md) — explicit two-tier `BACKTEST_SIGNALS` + `FACTOR_LIBRARY`
- [0018](../decisions/0018-pt-data-model-episodic-cadence.md) → superseded in part by 0020
- [0019](../decisions/0019-observability-sensor-surface-alert.md) — sanity assertions + daily health + push alerts
- [0020](../decisions/0020-pt-data-model-v2-sell-side-only-llm-narrative-only.md) — `forecast_history.price` contaminated; sell-side PT = yfinance only; LLM narrative-only
- [0021](../decisions/0021-pick-eligibility-gate.md) — `daily_picks` requires weight ≥0.50 + price_rows ≥60 + fundamental_coverage ≥0.50
- [0022](../decisions/0022-per-factor-backtest-cadence-newey-west.md) — per-factor cadence + Newey-West; uncovered 3 KEEPs
- [0023](../decisions/0023-health-center-cockpit-as-single-window.md) — `/system` is single window; `get_health_overview()` aggregates 5 sources
- [0024](../decisions/0024-per-signal-eligibility-and-per-stock-integrity.md) — per-signal eligibility registry + per-stock integrity validator
- [0025](../decisions/0025-pit-replay-validator.md) — PIT replay gate on scoring/signals/sources/eligibility pushes
- [0026](../decisions/0026-micro-tier-carve-out.md) — MICRO 4th cap-tier carved out of SMALL
- [0027](../decisions/0027-per-stock-data-lineage.md) — `FACTOR_LINEAGE` + `TABLE_COLUMN_SOURCES` + `signal_lineage` table
- [0028](../decisions/0028-two-variant-factor-model.md) — RETURN + SHARPE weight variants, promotion deferred
- [0029](../decisions/0029-mf-investable-only-default.md) — MF universe defaults to investable cut
- [0030](../decisions/0030-banking-metrics-screener-first.md) — banking_metrics source = Screener.in (not Tickertape); 158-SID scope
- [0031](../decisions/0031-duckdb-read-replica.md) — DuckDB read-replica rebuilt nightly; `read_sql_fast` routes mirrored-table reads; SQLite remains write-side source of truth
- [0032](../decisions/0032-tier-direction-flip-split-signal.md) — when a factor's IC flips sign across cap_tiers, split into two named signals (`X_quality` / `X_recovery`); don't apply per-tier sign on the composite

## Recently archived
- 0001 regulatory signal · 0002 macro data · 0004 PIT reconstruction · 0006 sector intelligence
