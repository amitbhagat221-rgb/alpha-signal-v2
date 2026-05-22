# Alpha Signal v2 — Progress Checklist
_Last updated: 2026-05-22 (handoff — 4 Track-3 factors PIT-shipped + FACTOR_LIBRARY introduced) · Plans are truth, this is the view. Update via `/handoff`._
_Glyphs: ✅ done · ⏳ next/in-progress · 🚫 blocked · 💤 parked · ↔ cross-track integration point_
_Convention: see [ADR 0015](../decisions/0015-track-numbering-and-rename.md) (tracks) + [ADR 0016](../decisions/0016-plan-numbering-fresh-start.md) (plan numbers)._

## Next 3
1. ⏳ Retrofit `pit_roic` + `pit_fcf_yield` in [tools/reconstruct_pit.py](../../tools/reconstruct_pit.py) — flips both MISSING → READY in [db.BACKTEST_SIGNALS](../../db.py); template: `pit_cash_conversion_cycle`
2. ⏳ Ship `signals/roiic.py` + `pit_roiic` (ΔNOPAT / ΔInvested Capital, 5y) — next item in batch queue
3. ⏳ Decide share_momentum scoring weight (KEEP, |t|=3.21) — manual ~0.5× now, or wait for Track 3.3a IC-stability framework

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
   - ⏳ 3.1b NSE F&O OI  (next)
   - ⏳ 3.1c Kite Connect
   - ⏳ 3.1d PIB + earnings call NLP
- ⏳ 3.2 Factor build, 50 factors  (6/50 PIT-shipped)
   - ✅ roic (scoring only — PIT helper pending retrofit) · ✅ fcf_yield (scoring only — PIT helper pending retrofit)
   - ✅ cash_conversion_cycle (PARKED — WEAK LARGE t=+1.87, contrarian sign)
   - ✅ operating_margin_trend (library — best |t|=1.30 MID)
   - ✅ working_capital_intensity (library — best |t|=1.48 LARGE)
   - ✅ interest_coverage (PARKED — WEAK SMALL t=+2.41, intuitive sign, promote candidate)
   - ⏳ Retrofit `pit_roic` + `pit_fcf_yield` in [tools/reconstruct_pit.py](../../tools/reconstruct_pit.py)  ← **active** (unit-of-work rule)
      - ⏳ `pit_roic(stocks, fund_pit)` — NOPAT / IC, 3y median, template: `pit_cash_conversion_cycle`
      - ⏳ `pit_fcf_yield(stocks, fund_pit, prices_pit)` — needs PIT close for market_cap
      - ⏳ ALTER `daily_snapshots_pit` ADD COLUMN roic, fcf_yield + PIT_COLUMNS + VALIDATION_RANGES
      - ⏳ Surgical 7-date update + backtest → flips MISSING → READY in [db.BACKTEST_SIGNALS](../../db.py)
   - ⏳ Batch queue (same template, ship in this order): `roiic`, `debt_structure`, `asset_tangibility`
   - 💤 +42 remaining factors (see plan 0002 §3.2.1–3.2.7)
- 💤 3.3 Factor model upgrade (gated on 3.2 ≥ 25 factors):
   - 💤 3.3a IC stability weighting
   - 💤 3.3b Orthogonalization  **↔ 2.5**
   - 💤 3.3c Mean-variance portfolio  **↔ 2.4**
   - 💤 3.3d Risk decomposition (Barra-style)

## Side plans
- ⏳ [0007 Market-share momentum cluster](0003-market-share-momentum-factor.md) — 4 factors, ~7 hr, proposed
- ⏳ [0008 Consumer demand pulse](0004-consumer-demand-pulse.md) — research-gated, validation before port

## Open questions (pending roadmap decisions)
- 2.2 banking-metrics source: Tickertape-first or RBI-first?
- 2.3 commodity-data gaps: skip cement/steel until manual curation?
- 0008 paid pytrends fallback if free tier blocks?
- Insider / regulatory / macro signal weights: tertiary 0.2× for first two, zero for macro?

## Decisions changing roadmap
- [ADR 0009](../decisions/0009-factor-track-parallel-to-d-track.md) — Tracks 2 & 3 run parallel; integration points 2.4↔3.3c and 2.5↔3.3b
- [ADR 0013](../decisions/0013-industry-not-sector-as-drill-unit.md) — industry replaces GICS sector as drill unit
- [ADR 0015](../decisions/0015-track-numbering-and-rename.md) — Track 1/2/3 naming + numbering convention (this doc's vocabulary)
- [ADR 0016](../decisions/0016-plan-numbering-fresh-start.md) — active plans renumbered 0001–0004 chronologically; archived keep historical numbers
- [ADR 0017](../decisions/0017-factor-library-two-tier-registry.md) — explicit two-tier registry (`BACKTEST_SIGNALS` + `FACTOR_LIBRARY`) replaces the implicit "in/out of BACKTEST_SIGNALS" tier signal

## Recently archived
- 0001 regulatory signal — implemented
- 0002 macro data — implemented
- 0004 PIT reconstruction — shipped, captured in ADRs 0010 + 0012
- 0006 sector intelligence page — implemented, ADRs 0013 + 0014
