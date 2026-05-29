# Alpha Signal v2 — Progress Checklist
_Last updated: 2026-05-29 (CRITICAL fixes: dossier sentiment regex + watchdog CHECK widening + heartbeat) · Plans are truth, this is the view. Update via `/handoff`._
_Glyphs: ✅ done · ⏳ next/in-progress · 🚫 blocked · 💤 parked · ↔ cross-track integration point_
_Convention: [ADR 0015](../decisions/0015-track-numbering-and-rename.md) (tracks) + [ADR 0016](../decisions/0016-plan-numbering-fresh-start.md) (plans)._

## Next 3
1. ⏳ **Phase 2.2a-ii — `sources/banking_metrics.py`** — Screener.in bank-page parser → `banking_metrics` (28-col table just created). 158 SID backfill. After this lands, coverage report tells us whether to ship RBI fallback for CASA/PCR/CAR (Phase 2.2c) or proceed straight to signal (Phase 2.2b). ADR 0030 has the rationale.
2. ⏳ **Wire 2 non-colinear bench factors** — `pledge_quality` (SMALL t=5.9) + `delivery_anomaly_z` (SMALL t=4.76). Correlation diagnostic killed the other 5 proposed wirings as redundant.
3. ⏳ **Variant promotion decision** — `SIGNAL_WEIGHTS_RETURN`/`SHARPE` print-only today. Honest answer: gated on orthogonalization (3.3b) because variants weight a colinearity-confounded basis. Kill-switch 2026-06-28; promote-or-abandon. Schema cost if promoting via `variant` PK column: 1-2 day refactor touching 6+ cockpit endpoints + dossier + morning_brief + PIT anchors.
4. ⏳ **Refresh `nse_index_history`** — NIFTY 50 latest = 2026-04-30, blocks `pick_outcomes` bench columns for newer picks.

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
   - ⏳ Phase 2.2a-ii: `sources/banking_metrics.py` — Screener.in bank-page parser, 158-SID backfill
   - ⏳ Phase 2.2b: `signals/financial_signal.py` + routing in `scoring/screener.py`
   - ⏳ Phase 2.2c: RBI fallback for CASA/PCR/CAR — gated on 2.2a coverage report
   - ⏳ Phase 2.2d: cockpit financial sub-model page + backtest validation (t-stat ≥ 2.0 within Financial subset = Plan 0001 done gate)
- ⏳ 2.3 Cyclical overlay (parallel-able with 2.2)
- ⏳ 2.4 Segment models + portfolio (capstone) **↔ 3.3c**
- 🚫 2.5 XGBoost overlay **↔ 3.3b** — needs ≥6mo PIT, ETA early 2027

## Track 3 — Factor model  · [plan 0002](0002-100-factors-and-model.md)
**State**: 23/50 PIT-shipped; production screener uses 8 factors (LARGE 6, MID 6, SMALL 7); 9 more KEEPs on bench.

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

## Recently archived
- 0001 regulatory signal · 0002 macro data · 0004 PIT reconstruction · 0006 sector intelligence
