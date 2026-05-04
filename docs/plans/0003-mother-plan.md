---
Status: active
Created: 2026-05-03
Last updated: 2026-05-04
Owner: Amit Bhagat
Implementation:
Related ADRs: 0002-no-prefect.md, 0004-no-base-classes-no-yaml.md
---

# Mother Plan — Alpha Signal v2 Project Blueprint

> **The single source of truth for what v2 is building.** Tracks every C and D
> phase from the original v1 master plan, plus the F-phase factor-depth track
> added 2026-05-04 to scale from 42 to ~100 factors and upgrade scoring from
> weighted-sum to a real factor model.
>
> Created: 2026-05-03 | Last updated: 2026-05-04 | Owner: Amit Bhagat

---

## What problem are we solving?

v2's switchover (2026-05-01) closed out the **engineering rebuild**. The original master plan in [v1's CLAUDE.md](../../../alpha-signal/CLAUDE.md#L196-L211) was a two-track plan; auditing v2 against peer quant funds in 2026-05-04 revealed a third track is also load-bearing. So v2 is now a **three-track plan**:

1. **Engineering track** — rewrite v1 scripts as a clean SQLite + Python codebase. *Done.*
2. **Intelligence track (D-phases)** — graduate from a per-tier ranked list into a real portfolio with sector sub-models, cyclical overlays, segment weights, regime overlay, and per-stock/per-sector position discipline. *Half done.*
3. **Factor-depth track (F-phases, NEW)** — scale from 42 factors to ~100, then upgrade scoring from weighted-sum to a real factor model with IC-stability weighting, orthogonalization, mean-variance portfolio construction, and Barra-style risk decomposition. *Not started.*

This plan is the canonical roadmap for all three. It supersedes [V2_BUILD_PLAN.md](../../../alpha-signal/V2_BUILD_PLAN.md) (engineering, consumed) and consolidates the phase ladder from [v1 CLAUDE.md](../../../alpha-signal/CLAUDE.md), [C13b_definitive_instructions.md](../../../alpha-signal/C13b_definitive_instructions.md), [D14_claude_code_instructions.md](../../../alpha-signal/D14_claude_code_instructions.md), and the F-phase plan [0005-100-factors-and-model.md](0005-100-factors-and-model.md) into one v2-native document.

---

## Where we are (as of 2026-05-04)

```
ENGINEERING TRACK ─────────────────────────────────────────── ✅ DONE
  V2_BUILD_PLAN sessions 1–15: schema → sources → signals →
  scoring → output → tests → parallel run → switchover

INTELLIGENCE TRACK (D-phases) ──────────────────────────── ⏳ ~40% done

  C-phases (research / validation)
    C12  Tier infrastructure ............................. ✅
    C13  Stratified backtest + VIX regime ................ ✅
    C13b 36-month PIT signal reconstruction .............. ✅
                                                              ↓
  D-phases (production deployment of validated signals)
    D14  Small-cap quality gate .......................... ✅
    D15  Financial sub-model ............................. ⏳ NEXT
    D16  Cyclical overlay ................................ ⏳
    D17  Segment models + portfolio construction ......... ⏳ ★ capstone
    D18  XGBoost per segment + SHAP ...................... ⏳ blocked on data

FACTOR-DEPTH TRACK (F-phases, runs PARALLEL to D-phases) ─ ⏳ not started
  Today: 42 factors registered, 40 READY (top quartile retail; small-shop tier)

  F1  Data acquisition ─ 4 streams ....................... ⏳ NEXT (week 1-6)
       Screener Premium scrape + NSE F&O OI + Kite + NLP
  F2  Factor build ─ 50 new factors → ~100 total ......... ⏳ (week 7-12)
       Forensic, options-implied, microstructure, NLP, event-time
  F3  Factor model upgrade ★ ............................. ⏳ (month 4-6)
       IC weighting → orthogonalization → portfolio construction
       → Barra-style risk decomposition
```

Today the daily output is a **per-tier ranked list** from `scoring/screener.py`, gated by `scoring/quality_gate.py` and contextualized by `scoring/regime.py`. That is **not a portfolio.** D15–D17 turn it into one. F1–F3 deepen the factor input and replace the weighted-sum core with a proper factor model.

---

## What does the solution look like?

### The full v2 stack, when D14–D18 *and* F1–F3 are all live

```
Universe (2,448 stocks, ETFs excluded)
    │
    ├── Tier assignment ─────────────────────── C12 ✅
    │     LARGE 1-100 | MID 101-250 | SMALL 251+
    │
    ├── Sector routing ──────────────── (D15/D16 add the branches)
    │     Financial Services      → D15 financial sub-model
    │     Metals/Oil/Chem/Cement  → D16 cyclical overlay (pre-process)
    │     Everything else         → main segment model
    │
    ├── Signal computation (~100 factors when F2 ships)
    │     Existing 40: piotroski, accruals, consensus, promoter, EY,
    │                  B/P, momentum, smart_money, forensic, insider,
    │                  regulatory, macro
    │     F2 adds 50:  forensic + capital-allocation (CCC, FCF yield,
    │                  ROIC, ROIIC, gross margin trend) ← from Screener
    │                  options-implied (IV skew, PCR, max pain) ← F&O OI
    │                  microstructure (VWAP dev, Kyle's λ) ← Kite
    │                  NLP (FinBERT sentiment, call tone) ← transcripts
    │                  event-time (PEAD, buyback, dividend changes)
    │
    ├── Quality gate (small caps only) ──────── D14 ✅
    │     EXCLUDED / PENALISED / PASS
    │
    ├── ── ── ── ── ── F3 inserts the FACTOR MODEL here ── ── ── ──
    │
    ├── Factor weighting ────────────────────── F3 ⏳
    │     IC-stability based dynamic weights (replaces fixed t-tier weights
    │     from C13b verdict scheme). Refresh monthly.
    │
    ├── Orthogonalization ───────────────────── F3 ⏳
    │     Within-group sequential regression (Quality vs Quality,
    │     Value vs Value, etc.) so the 100 factors don't double-count.
    │
    ├── Per-segment weighted scoring ────────── D17 ⏳
    │     Per-tier composite over orthogonalized + IC-weighted factors.
    │     LARGE / MID / SMALL each have their own weight vector.
    │
    ├── Per-segment ML overlay ──────────────── D18 ⏳
    │     XGBoost per tier with SHAP attribution.
    │
    ├── Portfolio construction ──────────────── D17 + F3 ⏳
    │     Mean-variance optimization with Ledoit-Wolf shrunk covariance.
    │     Baseline 40% L / 30% M / 30% S, VIX regime overlay.
    │     Top 10–15 per tier, ≤5% per stock, ≤5 per sector.
    │     Rebalance: L monthly / M quarterly / S semi-annual.
    │
    └── Risk attribution ────────────────────── F3 ⏳
          Barra-style: stock return = style_factors + industry_dummies + specific.
          Every dossier explains "+X% from value, -Y% from chemicals sector."
```

---

## Phase-by-phase detail

Each phase below answers: **what it is, where it is, what's left, why it matters, what success looks like.**

---

### C12 — Tier Infrastructure ✅

**What it is.** Assigns `cap_tier` ∈ {LARGE, MID, SMALL} to every stock in the universe before any ranking happens. Locks in within-segment ranking as the only allowed ranking.

**Where it landed in v2.**
- `cap_tier` column on the universe table.
- All signals and the screener `groupby('cap_tier').rank(pct=True)`.
- Critical rule in [CLAUDE.md](../../CLAUDE.md): *never rank across tiers*.

**Why it mattered.** v1 originally ranked all 2,500 stocks together — small-cap noise drowned out large-cap signal and vice versa. C13b confirmed signals work *within their natural habitat*; cross-tier ranking was destroying alpha.

**Definition of done (already met).** Universe has cap_tier; every ranking call is within-tier; no signal output crosses tiers.

---

### C13 — Stratified Backtest + VIX Regime ✅

**What it is.** Per-tier IC and t-stats for every signal. VIX regime detector → defensive / neutral / risk-on bucket → tier allocation overlay.

**Where it landed in v2.**
- Backtester produces per-tier IC, t-stat, hit rate.
- `scoring/regime.py` — VIX regime classifier; persists `regime_state` rows.
- Allocation overlay: VIX > 25 → 55/25/20, VIX < 13 → 30/35/35, VIX > 35 → 70/20/10.

**Why it mattered.** Without per-tier validation, every weight is hand-waved. C13 is what produced the t-stat tiering rule (≥2.5 → 1.0x, 1.5–2.5 → 0.5x, 0.5–1.5 → 0.2x, <0.5 → 0x).

**Definition of done (already met).** All signals have per-tier t-stats; regime module runs daily and feeds allocation.

---

### C13b — 36-Month PIT Reconstruction ✅

**What it is.** Reconstructs every signal value at the actual point-in-time it would have been knowable (with proper filing lag), monthly, for 36 months. The validation that anchors the entire weight scheme.

**Where it landed in v2.**
- `signals/` modules each emit a snapshot row daily; PIT accumulation table grows over time.
- The validated signal map (CLAUDE.md):

  | Signal | LARGE | MID | SMALL |
  |--------|-------|-----|-------|
  | Consensus | **t=3.52** | t=2.20 | t=2.44 |
  | CF Accruals | t=0.20 | **t=3.20** | t=2.10 |
  | Promoter QoQ | t=0.04 | t=0.83 | **t=3.20** |
  | Earnings Yield | t=1.57 | t=1.01 | **t=3.13** |
  | Piotroski | t=0.51 | t=2.23 | **t=2.81** |
  | Book-to-Price | t=0.79 | t=2.33 | **t=2.54** |

**Open thread (not blocking).** Three signals are validated by C13b but **pending fresh backtest** in v2: insider (2yr reconstructed), regulatory (3yr events), macro sector (3yr indicators). They run in production but their weights are placeholders until per-tier t-stats land. Plan to address this inside D17 (segment models pull weights from t-stats; if a signal lacks a t-stat, its weight is 0 by the tiering rule).

---

### D14 — Small-Cap Quality Gate ✅

**What it is.** A three-tier graduated filter applied to small caps before scoring. Reflects the philosophy *"Quality is a gate in small caps, a signal in large caps."*

| Tier | Behavior | Triggers |
|------|----------|----------|
| **HARD EXCLUSION** (~15%) | Removed from universe entirely | No price data, 3yr consecutive loss, negative equity, Piotroski F≤1, Altman Z″<0.5 |
| **HEAVY PENALTY** | Stays in universe, capped –0.60 score penalty | Loss 2/3yr (–0.25), neg 3yr FCF (–0.20), pledge >50% (–0.25), F=2–3 (–0.15), Z=0.5–1.1 (–0.15), Beneish > –1.78 (–0.20) |
| **QUALITY COMPOSITE** | Positive signal contribution | Piotroski 25%, CFO/EBITDA 20%, Beneish 20%, Z-Score 15%, Pledge 10%, FCF years 10% |

**Where it landed in v2.** [scoring/quality_gate.py](../../scoring/quality_gate.py). Output: `gate_status` ∈ {EXCLUDED, PENALISED, PASS}, `quality_penalty`, `quality_composite`.

**Open thread.** The full D14 spec referenced SEBI GSM list and shell-company list for HARD EXCLUSION. Confirm whether v2's quality_gate consumes these or relies only on the financial triggers — if missing, file as a small follow-up plan rather than blocking D15.

---

### D15 — Financial Sub-Model ⏳ NEXT

**What it is.** Banks and NBFCs do not have inventory, COGS, or operating margin in any meaningful sense. Running them through Piotroski / accruals / EBITDA-based signals produces noise. D15 routes every Financial Services stock through a sector-specific model that uses the right ratios.

**Factor replacements (vs main model):**

| Main signal | Financial replacement |
|-------------|----------------------|
| P/E | **P/B + P/PPOP** |
| ROE | **ROA** |
| D/E ratio | **GNPA% / NNPA% / PCR / Slippage Ratio** |
| Operating margin | **NIM** |
| (banks only) | **CASA ratio** |
| (NBFCs only) | **Cost of Funds** |

**Adjusted Book Value (the keystone calc):**
```
adj_book = reported_book_value − (GNPA × (1 − PCR/100))
```
Then: regress `P/adj_book` on `ROA`. The **residual** is the alpha — banks trading at a P/B lower than their ROA justifies are mispriced.

**Benchmarks (sector pass thresholds):** ROA ≥ 1%, NIM ≥ 3%, GNPA ≤ 3%, PCR ≥ 70%, CASA ≥ 40% (banks).

**Data gap (the actual blocker).** v2 does not yet have banking metrics: NIM, GNPA, NNPA, PCR, CASA, ROA at quarterly granularity. Source candidates:
- **Tickertape** — has some bank ratios via the ratios endpoint; coverage gaps for smaller NBFCs.
- **RBI** — Quarterly Financial Statements of Scheduled Commercial Banks (rbi.org.in/Scripts/QuarterlyPublications.aspx). Authoritative but PDF/Excel — needs scraping.
- **Annual reports** — last resort.

**v2 implementation sketch:**
- New source module: `sources/banking_metrics.py` (Tickertape-first, RBI fallback).
- New table: `banking_metrics` (sid, period, nim, gnpa, nnpa, pcr, casa, roa, cost_of_funds, fetched_at).
- New signal module: `signals/financial_signal.py` — implements adjusted-book regression, emits `financial_signal_score`.
- Routing: `scoring/screener.py` skips Financial Services rows; results are merged in via `financial_signal` instead.

**Definition of done.**
1. Banking metrics table has ≥4 quarters of coverage for the ~120 Financial Services stocks in the universe (≥80% coverage by name; smaller NBFCs may stay sparse).
2. `financial_signal` score available for every Financial Services stock with ≥3 of the 5 core ratios present.
3. Backtest: financial sub-model produces a per-tier t-stat for residual alpha. Target ≥2.0 within Financial Services subset (this is a sector-restricted backtest, not universe-wide).
4. `/flow` cockpit page surfaces D15 as a step with green status.

**Why first among the pending phases.** Financial Services is ~12% of the universe and ~25% of Nifty 500 weight. Today every one of those names is silently mis-scored or routed-around. Highest leverage per unit of work.

**Reference.** [docs/financial_model_reference.md](../../../alpha-signal/docs/financial_model_reference.md) (in v1 dir) has the detailed factor specs. Migrate the relevant parts to v2's `docs/reference/` when D15 ships.

---

### D16 — Cyclical Overlay ⏳

**What it is.** Metals, Oil & Gas, Chemicals, Cement trade on commodity cycles, not on quarterly earnings. Raw P/E is misleading at both ends of the cycle (low P/E at peak earnings = bear trap; high P/E at trough = buy signal). D16 normalizes valuations across a 7-year cycle.

**Cycle-position detector (4 indicators per sector):**
- Steel: HRC price vs 7yr range, capacity utilization, China steel exports, India bhavan demand proxy.
- Oil & Gas: Brent vs 7yr range, inventory levels, refinery margins, OPEC stance flag.
- Aluminium: LME price vs 7yr range, alumina-aluminium spread, power costs, China supply.
- Cement: regional pricing, capacity utilization, infra spend (gov capex), input cost (coal, pet coke).

**Valuation logic by cycle position:**
- **Trough** → weight P/B and dividend yield (earnings are depressed/negative; book value is the floor).
- **Mid-cycle** → weight blended P/E and EV/EBITDA.
- **Peak** → weight **normalized EV/EBITDA** (using 7yr median EBITDA, not trailing).

**Data gap.** 7yr commodity prices for Brent, HRC, LME aluminium, LME copper, coking coal, pet coke. Brent + LME metals are available on yfinance / FRED. HRC and pet coke are harder — Indian-specific; may need MCX or trade-publication sources.

**v2 implementation sketch:**
- New source: `sources/commodities.py` (yfinance + FRED for the easy ones; flag the gaps for manual curation).
- New table: `commodity_history` (commodity_id, date, price, source).
- New module: `scoring/cyclical_overlay.py` — computes cycle position per sector, applies as a pre-processor that *adjusts* the valuation signals (`earnings_yield`, `book_to_price`) for cyclical sectors before they enter the screener.
- Universe tag: add `is_cyclical` flag to stocks (Metals/Oil/Chem/Cement → True).

**Definition of done.**
1. 7yr history for ≥4 of the 6 target commodities (Brent, LME aluminium, LME copper, gold are easy; HRC and pet coke OK if sparse).
2. Cycle-position label per sector per month for the last 24 months (validation: does it match obvious calls — e.g. steel was at a peak in 2022, oil at a trough in 2020?).
3. Cyclical-overlay-adjusted earnings_yield / book_to_price flow into the screener for tagged stocks.
4. Backtest: cyclical-adjusted vs raw signals on cyclical subset only — target IC improvement ≥0.02.

**Reference.** [docs/cyclical_overlay_reference.md](../../../alpha-signal/docs/cyclical_overlay_reference.md) (v1 dir).

**Why second.** Cyclical sectors are ~10% of the universe. Smaller blast radius than D15, and D17 doesn't strictly depend on D16 — D17 can ship with cyclical stocks scored by raw signals if D16 slips. Treat D16 as pipelinable in parallel with D15 if bandwidth allows.

---

### D17 — Segment Models + Portfolio Construction ⏳ ★ CAPSTONE

**What it is.** The phase that turns Alpha Signal from a daily ranking into a daily portfolio. Replaces today's `scoring/screener.py` with three segment-specific scoring engines, then assembles the output into an actual portfolio with allocation, position sizing, sector caps, and rebalance discipline.

#### Part 1 — Per-segment weighted scoring

Each tier gets its own weight vector, anchored in C13b t-stats. Weights below are the master-plan starting point; D17 will recompute from latest backtest results before going live.

**Large cap** (rebalance monthly, ~30bps cost, ADTV ≥ ₹10 Cr):
```
consensus       0.40   (t=3.52, primary)
earnings_yield  0.20   (t=1.57, secondary)
cf_accruals     0.15   (t=0.20, tertiary)  ← stays in for diversification
book_to_price   0.10   (t=0.79, tertiary)
piotroski       0.10   (t=0.51, tertiary)
mom_6m          0.05   (t=0.00, tertiary)
```

**Mid cap** (rebalance quarterly, ~50bps cost, ADTV ≥ ₹5 Cr):
```
cf_accruals     0.30   (t=3.20, primary)
book_to_price   0.20   (t=2.33, secondary)
piotroski       0.20   (t=2.23, secondary)
consensus       0.15   (t=2.20, secondary)
earnings_yield  0.10   (t=1.01, tertiary)
promoter        0.05   (t=0.83, tertiary)
```

**Small cap** (rebalance semi-annual, ~150bps cost, ADTV ≥ ₹1 Cr; **after D14 quality gate**):
```
promoter_qoq    0.25   (t=3.20, primary)
earnings_yield  0.20   (t=3.13, primary)
piotroski       0.15   (t=2.81, primary)
book_to_price   0.15   (t=2.54, primary)
delivery%       0.10   (t=2.49, secondary)
cf_accruals     0.10   (t=2.10, secondary)
mom_12m         0.05   (t=1.76, secondary)
```

All percentile ranks are within-segment. Segments combine independently — no cross-tier composite score.

#### Part 2 — Portfolio construction layer

**Baseline allocation:** 40% Large / 30% Mid / 30% Small.

**VIX regime overlay** (already implemented in `scoring/regime.py` — D17 wires it to allocation):
- VIX > 25 → 55/25/20 (defensive)
- VIX 13–25 → 40/30/30 (neutral)
- VIX < 13 → 30/35/35 (risk-on)
- VIX > 35 → 70/20/10 (panic — extreme defensive)

**Selection per tier:** top 10–15 names ranked by per-segment composite score.

**Position discipline:**
- ≤5% allocation per individual stock
- ≤5 stocks per sector (any one sector cap)
- Sector cap binds before stock cap (drop the lowest-ranked over-cap names first)

**Rebalance cadences:**
- Large cap: monthly (last business day)
- Mid cap: quarterly (calendar quarter end)
- Small cap: semi-annual (June/December last business day)

**Drift handling:** between rebalances, positions drift with the market. Re-entries during a rebalance are *additions*, not full reshuffles — turnover discipline matters per the transaction-cost rule.

#### Part 3 — Portfolio state in SQLite (open question)

Today's pipeline is stateless — it produces today's ranking and the previous day's row is overwritten. A portfolio implies *state* across days:

- `portfolio_holdings` (rebalance_date, tier, sid, weight, entry_price, entry_score)
- `portfolio_rebalances` (rebalance_date, tier, additions [json], removals [json], turnover_pct, transaction_cost_estimate_bps)
- `portfolio_drift_daily` (date, tier, sid, current_weight_pct, current_drift_from_target)

**Open question 1.** Is this a *single* portfolio (one canonical book) or a *backtest portfolio* (paper-traded, performance-measured but not real)? The master plan is silent. My read: ship as paper-traded — close-loop performance measurement is the whole point of having a portfolio surface, and committing to a real book has implications (taxes, brokerage, KYC) outside this plan's scope.

**Open question 2.** What happens to a name that's removed at rebalance — does the cockpit *show* exit signals, or only show the current portfolio? Suggest: an `/portfolio` cockpit page that shows current holdings + last rebalance diff + drift heatmap.

#### Definition of done

1. Three per-segment scorers in `scoring/` (`segment_large.py`, `segment_mid.py`, `segment_small.py`) each consuming the validated weight vectors.
2. New module: `scoring/portfolio.py` — assembles top-N per tier, applies sector + position caps, writes `portfolio_holdings` row set per rebalance.
3. Rebalance cadence enforced by pipeline: `pipeline.py --step portfolio_rebalance_large` runs only on month-end; mid on quarter-end; small on semi-annual end.
4. New cockpit page `/portfolio` showing current holdings, last rebalance diff, sector exposure, and drift.
5. Backtest: per-tier portfolio-vs-benchmark — Large vs Nifty 100, Mid vs Nifty Midcap 150, Small vs Nifty Smallcap 250 — over the longest available reconstructed PIT history. Target IR ≥ 0.5 per tier.
6. `screener.py` deprecated (still callable for diagnostic; no longer the primary output).

**Reference.** [v1 CLAUDE.md lines 241-249](../../../alpha-signal/CLAUDE.md#L241-L249) for the headline weights; [V2_BUILD_PLAN.md sessions 10–11](../../../alpha-signal/V2_BUILD_PLAN.md#L532-L555) for the original output-layer design.

**Why third.** D17 is the capstone — the deliverable that finishes the master plan. Everything before this serves it. Everything after (D18) layers on top of it.

---

### D18 — XGBoost Per Segment + SHAP ⏳ BLOCKED ON DATA

**What it is.** A non-linear ML overlay per tier that consumes the same signal inputs as the segment models but learns interaction effects (e.g. "high promoter buying matters *only when* leverage is low and earnings are accelerating"). SHAP attribution makes every prediction explainable.

**Why this is blocked.** XGBoost on 2,448 stocks with 12 signals needs **several hundred to a few thousand training rows per tier** to avoid overfitting. We need ≥6 months of accumulated daily PIT signal snapshots before training is meaningful. v2's `signal_snapshots` table started accumulating around switchover (2026-05-01), so D18 cannot start before **late October 2026** at earliest, more honestly **early 2027**.

**v2 implementation sketch (when unblocked):**
- New module: `signals/xgboost_segment.py` — three models, one per tier.
- Trained on: snapshot row × forward 30-day return. Features = all live signal scores. Target = within-tier forward return rank.
- SHAP integration: every dossier gets a "why this stock" section with top-5 contributing features and their direction.
- Output: `xgboost_score` per stock per day, merged into D17's segment composite as an additional weight (start at 0.10x, raise on validation).

**Definition of done.**
1. ≥6 months of PIT snapshot accumulation (~120 trading days × 2,448 stocks ≈ 300K rows).
2. Per-tier OOS validation: walk-forward IC ≥ raw composite score by ≥0.01.
3. SHAP summary integrated into dossier output.
4. Recalibration cadence: quarterly retrain.

**Why last.** Genuinely waits on data. There's no parallel work that helps.

---

## Factor-Depth Track (F-phases) — added 2026-05-04

Phases F1–F3 run **parallel** to the D-phases. The full detailed plan lives in
[0005-100-factors-and-model.md](0005-100-factors-and-model.md); the summary
below is the blueprint reference. F-phases do not block D-phases — D15 and F1
can ship in parallel; D17's segment models will consume whatever factors are
READY when D17 lands.

---

### F1 — Data Acquisition (4 streams) ⏳ NEXT

**What it is.** Stand up four new ingestion pipelines, each landing in a
versioned SQLite table with PIT discipline. F1 must accumulate ≥90 days of
clean history before F2 factor computation is meaningful.

**Streams (in priority order):**

| # | Stream | New file | New table | Cost | Effort |
|---|---|---|---|---|---|
| F1.1 | Screener Premium scrape | `sources/screener_pull.py` | `fundamentals_screener` | ₹420/mo | 2 days |
| F1.2 | NSE F&O OI / Greeks | `sources/fno_pull.py` | `fno_option_chain`, `fno_oi_history` | free (nselib) | 1 day |
| F1.3 | Zerodha Kite Connect | `sources/kite_pull.py` | `kite_intraday_bars`, `kite_tick_aggregates` | ₹500/mo | 2 days |
| F1.4 | PIB + Earnings Call NLP | `sources/transcripts_pull.py` | `transcripts`, `nlp_scores` | free | 3 days |

**Sensibull skip rationale.** No retail API; their analytics layer is
computable from Kite raw data directly. Documented in
[paid-data-sources.md](../reference/paid-data-sources.md).

**Definition of done.**
- All 4 ingest pipelines run nightly with logs and idempotent UNIQUE constraints
- Each table has ≥90 days of accumulated history
- Validation dashboard on cockpit `/data` page shows row counts and latest dates
- No script crashes for 30 consecutive nights
- Total disk: ~5 GB additional

**Why first among F-phases.** Factor work is gated on data accumulation —
starting F2 before F1 produces 5-period t-stats and false-confidence factors
(this is what the *v1 sentiment lost* lesson reinforces).

---

### F2 — Factor Build ⏳ (target: 50 new factors → ~100 total)

**What it is.** Each new factor follows the existing v2 pattern: a function in
`signals/`, registered in `BACKTEST_SIGNALS` with `pit_column_v2` populated,
computed by `tools/reconstruct_pit.py` on every snapshot. No new framework.

**Factor groups (full list in plan 0005):**

| Group | Count | Source | Examples |
|---|---|---|---|
| Forensic + capital allocation | 15 | F1.1 Screener | CCC, FCF yield, ROIC, ROIIC, gross margin trend, Sloan accruals |
| Options-implied | 8 | F1.2/F1.3 | IV skew, IV percentile, PCR, max pain distance, IV-realised spread |
| Microstructure | 9 | F1.3 Kite | VWAP deviation, Kyle's λ, closing strength, opening gap freq |
| NLP / sentiment | 7 | F1.4 | FinBERT sentiment, earnings call tone, uncertainty density |
| Event-time / PEAD | 6 | (existing data) | PEAD drift, earnings surprise, buyback announcements, index inclusion |
| Industry one-hot | 1 | (structural) | 22-industry block — risk-model input |
| Macro extensions | 4 | (existing + new) | INR carry proxy, India credit spread, oil/metals betas |

**Definition of done.**
- All 50 factors entered in `BACKTEST_SIGNALS`
- All compute via `tools/reconstruct_pit.py`
- ≥6 monthly snapshots populated for each (n=6 sanity, not statistical KEEP)
- No factor has >50% NaN rate within its expected universe
- `docs/reference/factor-catalog.md` lists all 100 with formulas

**Why second.** Gated on F1 data accumulation. Once F1 has 90 days, F2 can
sprint through the factor builds in 2-3 weeks.

---

### F3 — Factor Model Upgrade ⏳ ★ THE REAL EDGE

**What it is.** Stops being a "factor zoo with weighted sum" and becomes a
factor model. Three orthogonal pieces, build in order. **Most retail quant
projects skip this and stay forever in factor-collecting mode; F3 is what
separates v2 from a hobby project.**

#### F3.1 — IC stability weighting (replaces C13b fixed tiers)

```python
# tools/factor_weights.py
# For each (factor, cap_tier):
#   Compute rolling IC over 24 months
#   weight = mean(IC) / std(IC), clipped to [0, 1]
#   Decay older periods exponentially (half-life 12 months)
# Write to factor_weights_v2 (signal, cap_tier, weight, asof_date)
```

Cockpit page `/factor-weights` shows current weights and how they evolve.

#### F3.2 — Orthogonalization

Approach: **sequential regression** within group (Quality vs Quality,
Forensic vs Forensic, etc.). Order factors by historical t-stat, take
residuals at each step. Cross-group factors stay raw. Preserves factor
identity for the dossier — the "why this stock" narrative would die under
PCA.

#### F3.3 — Mean-variance portfolio construction

Replaces D17's equal-weight-per-decile with a proper optimizer:

```
1. Estimate per-stock daily return covariance, 252d window
2. Shrink toward diagonal (Ledoit-Wolf) to handle 2,448-stock matrix
3. Construct portfolio = argmax (factor_score × w) − λ × (w' Σ w)
   subject to per-stock cap, per-sector cap, turnover limit
4. Output: weighted portfolio with marginal risk contributions
```

New table: `portfolio_weights (asof_date, sid, weight, factor_score, marginal_risk_contrib)`.

#### F3.4 — Risk model decomposition (Barra-style, defer until 3.1-3.3 work)

Cross-sectional regression each day:
`stock_return ~ style_factors + industry_dummies + residual`

Produces factor returns themselves (not just IC) — fund-grade attribution.
Every dossier gets "+X% from value, -Y% from chemicals sector, +Z% specific."

**Definition of done.**
1. `factor_weights_v2` table populated, refreshed monthly
2. Orthogonalization runs in scoring pipeline before screener output
3. Portfolio construction outputs weighted positions (replaces D17 ranks)
4. Risk decomposition reports for top-20 portfolio holdings
5. **Hard gate:** factor-model portfolio must beat current screener portfolio
   by ≥1.5% annualized risk-adjusted over 18-24 months. Else don't ship.

**Why last in F-track.** Gated on F2 (need ≥80 factors before
orthogonalization is meaningful) and on enough monthly history to compute
rolling IC stability. The 18-month head-to-head (point 5 above) needs ~24
monthly periods to be trusted; can't run that until ~2027-10.

---

## How F-phases relate to D-phases

The two tracks are **complementary, not sequential**:

| D-track ships | F-track effect | Notes |
|---|---|---|
| D15 financial sub-model | Adds banking factors to F2's universe | F2 factor list grows when D15 lands |
| D16 cyclical overlay | Adjusts cyclical-sector factor inputs | F3 orthogonalization respects cyclical adjustment |
| D17 segment models + portfolio | F3.3 mean-variance optimizer **replaces** D17's equal-weight portfolio | If F3 ships first, D17 inherits MVO; if D17 ships first, F3 swaps it in |
| D18 XGBoost overlay | Trains on the orthogonalized factors from F3.2, not raw | F3.2 *should* ship before D18 to avoid training on correlated features |

**Hard rule:** D-phases must not block on F-phases. If F1 is taking longer
than expected, D15 still ships using the existing 40 READY factors. The
factor-model upgrade is value-additive, not gating.

---

## What are the open questions?

These are decisions that need to be made before/during implementation:

1. **Portfolio = paper or real?** (D17, Part 3). My recommendation: paper-traded only. Real money invokes brokerage/tax/KYC concerns out of scope.

2. **Recalibration cadence and authority.** Master plan said: weekly IC dashboard, quarterly weight adjustments (±0.05 max), semi-annual architecture review, ±0.10 max per recalibration, signal promotion/demotion needs 2 consecutive quarters confirming. Should v2 honor all four cadences or simplify? Suggest: weekly IC monitoring (cockpit auto), quarterly *manual* weight review (no auto-adjust — human in the loop), semi-annual ADR for structural changes.

3. **D15 banking-metrics source priority.** Tickertape-first is fastest; RBI is most authoritative. Suggest: ship Tickertape-only for v1 of D15; promote RBI to primary when Tickertape coverage gaps cost real signal (measure first).

4. **D16 commodity-data gap policy.** HRC and pet coke are genuinely hard to source automated. Acceptable to cyclical-overlay only the sectors where we have full commodity coverage (oil/aluminium/copper/gold) and skip cement/steel until manual curation? Suggest: yes, partial coverage is better than blocking D16.

5. **Insider / regulatory / macro signal weights.** These run in production but lack C13b t-stats. Until backfilled, what weight do they carry in D17? Three options:
   - **Zero weight** (strict tiering rule) — they're informational only.
   - **Tertiary weight (0.2x)** — token contribution, capped low.
   - **Quarantine** — only affect dossier narrative, never composite score.

   Suggest: tertiary 0.2x for insider and regulatory (face-valid, low downside); zero for macro (sector signal not stock signal — belongs in tilt overlay, not stock score).

6. **Cockpit /portfolio page scope.** Just current state + last rebalance, or also historical performance, attribution, drawdown chart? Suggest: ship lean (state + last rebalance + sector exposure), iterate based on what you actually look at daily.

---

## What does success look like?

**Phase-level success** is in each phase's *Definition of done*. **Plan-level success** — i.e. the mother plan is finished — is when:

**Intelligence track (D-phases):**
1. Every Financial Services stock has a financial_signal score that respects sector-specific ratios. [D15]
2. Every cyclical stock has its valuation adjusted for cycle position before entering the screener. [D16]
3. The daily output is **a portfolio**: 40/30/30 (or VIX-adjusted), top 10–15 per tier, ≤5% per stock, ≤5 stocks per sector, with rebalance cadence enforced. [D17]
4. The cockpit's `/portfolio` page shows current holdings, drift, and last rebalance diff. [D17]
5. XGBoost overlay live with SHAP attribution in the dossier. [D18]
6. Per-tier portfolio backtest IR ≥ 0.5 vs tier benchmark.
7. Recalibration cadence operating: weekly IC monitoring, quarterly weight review, semi-annual structural review.

**Factor-depth track (F-phases):**
8. ≥100 factors registered, ≥80 READY (versus 42/40 today). [F2]
9. All 4 F1 data streams in production with ≥90 days of accumulated history. [F1]
10. Factor weights are dynamic (rolling-IC-stability based), not fixed C13b tiers. [F3.1]
11. Factor scores entering the segment models are orthogonalized within group. [F3.2]
12. Portfolio is mean-variance optimized with shrunk covariance, not equal-weighted. [F3.3]
13. Every dossier shows risk attribution by style factor + industry + specific. [F3.4]
14. Factor-model portfolio beats the original screener by ≥1.5% annualized risk-adjusted over 18-24 months. [F3 hard gate]

When all 14 hold, this plan is archived to `_archive/`, with permanent learnings distilled into `architecture.md` and `reference/` per the plan lifecycle in [docs/plans/README.md](README.md).

---

## What did we consider and reject?

- **Skipping D15 / D16 and going straight to D17.** Would produce a portfolio that systematically mis-prices ~22% of the universe (financials + cyclicals). Rejected — the engineering cost of D15 and D16 is small relative to the alpha they unlock and the embarrassment they prevent.

- **Universal scoring across tiers (revert C12).** Tempting because it simplifies code. Rejected — C13b proves signals work in their natural habitat only; cross-tier ranking destroyed alpha in v1. This is locked in CLAUDE.md as a critical rule.

- **Adding XGBoost (D18) before sufficient PIT data accumulates.** Rejected — overfit risk on 60-day data is severe; would produce a lookback-data artifact, not a signal. Wait.

- **Treating macro and regulatory as stock-level signals.** Considered. Rejected — both are sector-level by construction. They belong in a *tilt overlay* on top of the stock model, not as features inside per-stock segment composite. Defer the tilt-overlay design to a follow-up plan after D17 ships.

- **Adding a Prefect-style orchestration layer to manage rebalance cadences.** Considered. Rejected per [ADR 0002](../decisions/0002-no-prefect.md). The existing `pipeline.py --step <name>` + cron + cockpit `/flow` page is sufficient; rebalance cadence is just a date check inside `pipeline.py`.

- **Building the financial sub-model as a generic "sector model" framework.** Tempting (could later add tech-services, pharma sub-models). Rejected — premature abstraction per [ADR 0004](../decisions/0004-no-base-classes-no-yaml.md). Build D15 as a single concrete module; if D19/D20 later need sector models, refactor *then*.

- **Adding F-phase as another sequential block after D18.** Considered. Rejected — F-track doesn't depend on D-track for any of its intermediate value, and waiting until D18 (which is data-blocked until 2027) means losing 12+ months of factor-depth progress. Better to run them parallel and let whichever phase finishes first take precedence at the integration points (F3.3 vs D17 portfolio construction; F3.2 orthogonalization vs D18 XGBoost feature prep).

- **Sensibull subscription.** Evaluated 2026-05-04. No retail API; analytics layer is computable from Kite raw data. Skip. See [paid-data-sources.md](../reference/paid-data-sources.md).

- **Going to 200+ factors before fixing the model.** Tempting — every alt-data source promises "more alpha." Rejected — without F3 orthogonalization, the 60th factor adds noise, not signal. F2 caps at ~100; the 100→200 expansion is deferred until F3 orthogonalization proves the marginal-IC gate works in production.

---

## Implementation order and rough sizing

| Phase | Status | Effort | Blocks | Notes |
|-------|--------|--------|--------|-------|
| C12, C13, C13b | ✅ done | — | — | Validated foundation |
| D14 | ✅ done | — | — | Quality gate live |
| **D15** Financial sub-model | ⏳ next | ~3-5 sessions | None | Banking metrics ingest is the long pole |
| **D16** Cyclical overlay | ⏳ | ~3-4 sessions | None (parallelizable with D15) | Commodity data gap may force partial coverage |
| **D17** Segment models + portfolio | ⏳ ★ | ~5-8 sessions | D15 + D14 (D16 nice-to-have) | The capstone for D-track |
| **D18** XGBoost overlay | ⏳ blocked | ~3-4 sessions | ≥6mo PIT data (~early 2027) | Wait |
| | | | | |
| **F1** Data acquisition (4 streams) | ⏳ next | ~8 dev-days | None | + 90-day accumulation clock |
| **F2** Factor build (50 new) | ⏳ | ~20 dev-days | F1 | Sprintable once F1 has 90 days |
| **F3** Factor model upgrade ★ | ⏳ | ~24 dev-days | F2 | The capstone for F-track |

**Realistic calendar:**
- D-track to D17 completion (excluding D18): 3-6 months part-time
- F-track to F3 completion: 6 months dev + 18 months data accumulation for the hard-gate validation

The two tracks run in parallel. D-track output is usable at every step; F-track has a long-tail validation gate but its intermediate phases (F1, F2, F3.1) ship value as they land.

---

## Cross-references

**Sub-plans (the F-phases live here in detail):**
- [0005-100-factors-and-model.md](0005-100-factors-and-model.md) — full F1/F2/F3 specification with per-factor formulas, code sketches, hard gates
- [0004-pit-reconstruction.md](0004-pit-reconstruction.md) — PIT reconstruction work that powers C13b's monthly snapshots and F-track's backtest harness
- [0001-regulatory-signal.md](0001-regulatory-signal.md), [0002-macro-data.md](0002-macro-data.md) — early sub-plans, both implemented

**Reference catalogs:**
- [docs/reference/data-playbook.md](../reference/data-playbook.md) — sources by use case + reconstruction patterns
- [docs/reference/api-endpoints.md](../reference/api-endpoints.md) — per-endpoint catalog with quirks
- [docs/reference/paid-data-sources.md](../reference/paid-data-sources.md) — ₹5K/mo budget allocation

**v1 historical (immutable):**
- [V2_BUILD_PLAN.md](../../../alpha-signal/V2_BUILD_PLAN.md) — engineering plan, consumed
- [v1 CLAUDE.md](../../../alpha-signal/CLAUDE.md) — original master ladder
- [C13b_definitive_instructions.md](../../../alpha-signal/C13b_definitive_instructions.md), [D14_claude_code_instructions.md](../../../alpha-signal/D14_claude_code_instructions.md), [docs/financial_model_reference.md](../../../alpha-signal/docs/financial_model_reference.md), [docs/cyclical_overlay_reference.md](../../../alpha-signal/docs/cyclical_overlay_reference.md)

**Architectural constraints:**
- [ADR 0002 no-prefect](../decisions/0002-no-prefect.md), [ADR 0004 no-base-classes-no-yaml](../decisions/0004-no-base-classes-no-yaml.md)

**Registry of factors:** [db.py BACKTEST_SIGNALS](../../db.py) — 42 factors today, target ~100 after F2.
