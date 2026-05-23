# Alpha Signal v2 — Progress Checklist
_Last updated: 2026-05-23 (handoff — PT data model v2 shipped: sell-side only, pt_revision DROPPED, freshness proxies in cockpit, sidebar v1) · Plans are truth, this is the view. Update via `/handoff`._
_Glyphs: ✅ done · ⏳ next/in-progress · 🚫 blocked · 💤 parked · ↔ cross-track integration point_
_Convention: see [ADR 0015](../decisions/0015-track-numbering-and-rename.md) (tracks) + [ADR 0016](../decisions/0016-plan-numbering-fresh-start.md) (plan numbers)._

## Next 3
1. ⏳ **Phase 3.1b NSE F&O OI ingest** — `sources/fno_pull.py` + `fno_option_chain` / `fno_oi_history` tables. Unblocks §3.2.2 (8 options-implied factors). Plan: probe `nselib.derivatives` endpoints first, then daily-cron ingest.
2. ⏳ Decide weights for `share_momentum` (|t|=3.21 KEEP) + `dso_change_yoy` (|t|=-2.81 KEEP LARGE) in `SCREEN.weight_tiers` → [scoring/screener.py](../../scoring/screener.py) — manual ~0.5× now, or wait for Track 3.3a IC-stability framework.
3. ⏳ **Model PT (Option B Step 2)** — IC-based deterministic target `model_pt = price × (1 + IC × z(score) × σ(annual_returns))` per cap_tier (3-4 hr). New `model_targets` table + daily writer wired into pipeline + second column in cockpit Sell-side PT card. Per [ADR 0020](../decisions/0020-pt-data-model-v2-sell-side-only-llm-narrative-only.md).

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
- ⏳ 3.2 Factor build, 50 factors  (**19/50 PIT-shipped**)
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
- ⏳ [0007 Market-share momentum cluster](0003-market-share-momentum-factor.md) — 4 factors, ~7 hr, proposed
- ⏳ [0008 Consumer demand pulse](0004-consumer-demand-pulse.md) — research-gated, validation before port
- ✅ **PT data model v2** (this session) — sell-side from yfinance only, LLM narrative-only, freshness via 3 proxies. ADR 0020. Tickertape `forecast_history.price` confirmed contaminated and removed from all consumers. `pt_revision_yoy` factor killed (production de-biased by ~14% of LARGE final_score; reshuffled 8/10 LARGE top picks). 4 new `analyst_consensus` columns + 4 freshness columns + cockpit card v2 with range bar, rating-mix trend, next-earnings + PT-change badges. Memory: `pt_source_landscape_2026_05_23`, `forecast_history_price_contaminated`.
   - ⏳ Model PT (Option B Step 2) → see Next 3 #3
   - ⏳ Rebuild pt_revision from `analyst_consensus_snapshots` once ≥12mo (calendar 2027-05+)
- ⏳ **Drive-by — SMALL-cap missing current_price** (ANONDITA / TGVSL / BRRL / SUNSHIEL) — these top SMALL picks have NULL `close` in `stock_prices`; investigate why bhavcopy/yfinance ingest missed them. Blocks Model PT for these stocks too.
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

## Recently archived
- 0001 regulatory signal — implemented
- 0002 macro data — implemented
- 0004 PIT reconstruction — shipped, captured in ADRs 0010 + 0012
- 0006 sector intelligence page — implemented, ADRs 0013 + 0014
