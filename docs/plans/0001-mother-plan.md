---
Status: active
Created: 2026-05-03
Last updated: 2026-05-22
Owner: Amit Bhagat
Related ADRs: 0002-no-prefect.md, 0004-no-base-classes-no-yaml.md, 0009-factor-track-parallel-to-d-track.md, 0015-track-numbering-and-rename.md
---

# Mother Plan — v2 Roadmap

Three tracks running in parallel ([ADR 0015](../decisions/0015-track-numbering-and-rename.md) for naming + numbering convention):

| Track | Name | Status | Lives in |
|---|---|---|---|
| **Track 1** | **Foundation** — rebuild + research validation | ✅ Done 2026-05-01 | Archived |
| **Track 2** | **Portfolio** — segment models + portfolio construction | ⏳ ~40% (2.1 done, 2.2 next) | This plan |
| **Track 3** | **Factor model** — 42 → 100 factors + factor model upgrade | ⏳ Active | [0002-100-factors-and-model.md](0002-100-factors-and-model.md) |

Track 2 and Track 3 run concurrently with documented integration points ([ADR 0009](../decisions/0009-factor-track-parallel-to-d-track.md)): **2.4 ↔ 3.3c** and **2.5 ↔ 3.3b**. Track 2 phases don't block on Track 3 phases.

## Track 1 — Foundation ✅ done

- 1.1 v1 audit + rebuild plan
- 1.2 Tier infrastructure — `cap_tier` ∈ {LARGE, MID, SMALL} assigned before any ranking; within-segment ranking locked
- 1.3 Stratified backtest + VIX regime — per-tier IC + t-stats; `scoring/regime.py` allocation overlay
- 1.4 36-month PIT reconstruction — the validated signal map ([signal-weights.md](../reference/signal-weights.md)) and t-stat tiering rules anchor here. Known as **C13b** in code/comments (proper noun)
- 1.5 v2 cutover (2026-05-01)

## Track 2 — Portfolio ladder

### 2.1 — Small-cap quality gate ✅ done
Three-tier filter applied to small caps before scoring. Philosophy: *quality is a gate in small caps, a signal in large caps*.

| Tier | Behavior | Triggers |
|---|---|---|
| **HARD EXCLUSION** (~15%) | Removed from universe | No price data, 3yr consecutive loss, negative equity, Piotroski F≤1, Altman Z″<0.5 |
| **HEAVY PENALTY** | Stays, capped –0.60 penalty | Loss 2/3yr (–0.25), neg 3yr FCF (–0.20), pledge >50% (–0.25), F=2–3 (–0.15), Z=0.5–1.1 (–0.15), Beneish > –1.78 (–0.20) |
| **QUALITY COMPOSITE** | Positive signal contribution | Piotroski 25%, CFO/EBITDA 20%, Beneish 20%, Z 15%, Pledge 10%, FCF years 10% |

Lives in [scoring/quality_gate.py](../../scoring/quality_gate.py). Output: `gate_status` ∈ {EXCLUDED, PENALISED, PASS}.

### 2.2 — Financial sub-model ⏳ NEXT
Banks and NBFCs have no inventory/COGS/op margin — Piotroski/accruals/EBITDA are noise. Route Financials through a sector-specific model.

**Factor replacements:** P/E → P/B + P/PPOP · ROE → ROA · D/E → GNPA/NNPA/PCR/Slippage · op margin → NIM · banks: + CASA · NBFCs: + Cost of Funds.

**Keystone calc:** `adj_book = reported_book − GNPA × (1 − PCR/100)`. Regress `P/adj_book` on `ROA` → residual is alpha.

**Benchmarks (sector pass):** ROA ≥ 1%, NIM ≥ 3%, GNPA ≤ 3%, PCR ≥ 70%, CASA ≥ 40% (banks).

**Blocker:** banking metrics ingest. Source priority: Tickertape ratios first; RBI quarterly statements (PDF/Excel) as fallback. New `sources/banking_metrics.py` + `banking_metrics` table + `signals/financial_signal.py`.

**Done when:** ≥80% coverage on ~120 Financial Services stocks; financial_signal score per stock with ≥3/5 core ratios; backtest t-stat ≥ 2.0 within Financial Services subset.

**Why first:** Financials = ~12% of universe, ~25% of Nifty 500 weight. Highest leverage per unit of work.

Reference: v1's [docs/financial_model_reference.md](../../../alpha-signal/docs/financial_model_reference.md).

### 2.3 — Cyclical overlay ⏳
Metals, Oil & Gas, Chemicals, Cement trade on commodity cycles. Raw P/E misleading at peaks (bear trap) and troughs (buy signal). Normalize across 7-year cycle.

**Cycle-position detector per sector (4 indicators):** Steel (HRC vs 7yr range, capacity util, China exports, India demand) · Oil & Gas (Brent vs 7yr, inventory, refinery margins, OPEC) · Aluminium (LME, alumina-Al spread, power, China supply) · Cement (regional pricing, util, infra spend, input cost).

**Valuation logic:** trough → weight P/B + dividend yield · mid-cycle → blended P/E + EV/EBITDA · peak → normalized EV/EBITDA on 7yr median EBITDA.

**Data gap:** 7y prices for Brent (easy), LME aluminium/copper (easy), HRC + pet coke (hard — India-specific). Acceptable to overlay only sectors with full coverage; defer cement/steel.

**Parallelizable with 2.2.** Smaller blast radius (~10% of universe).

Reference: v1's [docs/cyclical_overlay_reference.md](../../../alpha-signal/docs/cyclical_overlay_reference.md).

### 2.4 — Segment models + portfolio construction ⏳ ★ CAPSTONE
The phase that turns daily ranking into a daily portfolio.

**Per-segment weighted scoring** (3 scorers, one per tier; weights from C13b t-stats, recomputed at 2.4 launch):

LARGE (monthly rebal, ~30bps, ADTV ≥ ₹10 Cr): consensus 0.40 · EY 0.20 · cf_accruals 0.15 · B/P 0.10 · Piotroski 0.10 · mom_6m 0.05
MID (quarterly, ~50bps, ADTV ≥ ₹5 Cr): cf_accruals 0.30 · B/P 0.20 · Piotroski 0.20 · consensus 0.15 · EY 0.10 · promoter 0.05
SMALL (semi-annual, ~150bps, ADTV ≥ ₹1 Cr, **after 2.1 gate**): promoter_qoq 0.25 · EY 0.20 · Piotroski 0.15 · B/P 0.15 · delivery% 0.10 · cf_accruals 0.10 · mom_12m 0.05

**Portfolio construction:**
- Baseline allocation 40/30/30 (L/M/S); VIX overlay (>25 → 55/25/20, <13 → 30/35/35, >35 → 70/20/10)
- Top 10–15 per tier by composite
- ≤5% per stock, ≤5 stocks per sector (sector cap binds first)
- Rebalance: L monthly · M quarterly · S semi-annual

**State (new tables):** `portfolio_holdings (rebal_date, tier, sid, weight, entry_price, entry_score)` · `portfolio_rebalances` · `portfolio_drift_daily`.

**Open question:** paper or real portfolio? **Take:** paper-traded only. Real money invokes brokerage/tax/KYC outside this plan's scope.

**Integration with Track 3 (2.4 ↔ 3.3c):** mean-variance optimizer from 3.3c replaces equal-weight when ready. Whichever ships first owns `portfolio_holdings`.

**Done when:** 3 per-segment scorers in `scoring/`; `scoring/portfolio.py` assembles top-N + caps; rebalance cadence enforced in pipeline; `/portfolio` cockpit page; per-tier backtest IR ≥ 0.5 vs benchmark.

### 2.5 — XGBoost overlay ⏳ blocked
Non-linear ML overlay per tier that learns interaction effects. SHAP attribution → every prediction explainable.

**Blocked on data.** Needs ≥6 months of accumulated daily PIT snapshots; v2's snapshot accumulation started ~2026-05-01. Earliest start: late October 2026; realistically early 2027.

**Integration with Track 3 (2.5 ↔ 3.3b):** trains on the orthogonalized factor matrix from 3.3b if ready, raw otherwise.

Trains on snapshot row × forward 30-day return rank within tier. Output: `xgboost_score` merged into 2.4 composite at 0.10× initial, raise on OOS validation. Quarterly retrain.

**Done when:** per-tier walk-forward IC ≥ raw composite by ≥0.01; SHAP integrated into dossier.

## Open questions

1. **Insider / regulatory / macro signal weights** — these run in production but lack v2 t-stats. **Take:** tertiary 0.2× for insider + regulatory (face-valid, low downside); zero for macro (sector signal, belongs in tilt overlay).
2. **Recalibration cadence.** Master plan said weekly IC / quarterly weight tweaks / semi-annual structural. **Take:** weekly IC monitoring (cockpit auto), quarterly *manual* weight review (human in loop), semi-annual ADR for structural changes.
3. **2.2 banking-metrics source.** **Take:** Tickertape-first; promote RBI to primary only if Tickertape gaps cost real signal.
4. **2.3 commodity-data gap policy.** **Take:** partial coverage (oil/Al/Cu/gold) is better than blocking the phase; skip cement/steel until manual curation.

## Done when (plan-level)

Track 2:
1. Every Financial Services stock has financial_signal [2.2]
2. Every cyclical has cycle-position-adjusted valuation [2.3]
3. Daily output is a portfolio (40/30/30 + VIX, top 10–15 per tier, ≤5%/stock, ≤5 stocks/sector, rebalance cadence enforced) [2.4]
4. `/portfolio` page shows holdings + drift + last rebalance [2.4]
5. XGBoost overlay live with SHAP in dossier [2.5]
6. Per-tier backtest IR ≥ 0.5 vs benchmark
7. Recalibration cadence operating

Track 3 success criteria live in [0002-100-factors-and-model.md](0002-100-factors-and-model.md).

## Effort sizing

| Phase | Effort | Blocks |
|---|---|---|
| 2.2 Financial sub-model | 3–5 sessions | None — banking metrics ingest is the long pole |
| 2.3 Cyclical overlay | 3–4 sessions | None (parallel with 2.2) |
| **2.4** Segment + portfolio ★ | 5–8 sessions | 2.1 + 2.2 (2.3 nice-to-have) |
| 2.5 XGBoost overlay | 3–4 sessions | ≥6mo PIT data (~early 2027) |

Realistic Track 2 to 2.4: 3–6 months part-time. Track 2 output usable at each phase.
