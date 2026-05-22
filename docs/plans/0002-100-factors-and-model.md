---
Status: active
Created: 2026-05-03
Last updated: 2026-05-22
Owner: Amit Bhagat
Implementation:
  3.1a (Screener Premium xlsx): universe-complete 2026-05-10. 2,119/2,448 stocks, 681K rows in `fundamentals_screener`, 329 failures (mostly SMALL delisted/new). `sources/screener_pull.py`.
  3.1b/c/d (NSE F&O OI, Kite, NLP): not started.
  Schedules JSON scraper: module landed 2026-05-10 (`sources/screener_schedules.py`). RELI smoke test passed (276 rows / 23 new line items). Universe run kicked off.
  Phase 3.2 factors shipped: `signals/roic.py` (1,501 stocks), `signals/fcf_yield.py` (1,195 stocks). Both wired into pipeline. Not in scoring weights yet — need t-stat validation.
Related ADRs: 0009-factor-track-parallel-to-d-track.md, 0011-long-format-for-new-fundamentals-tables.md, 0015-track-numbering-and-rename.md
---

# 0005 — Double Factor Count to 100 + Factor Model Upgrade

This is the canonical spec for **Track 3 — Factor model**. Today: 42 registered factors, 30 READY. This plan takes us to **100 factors** then upgrades scoring from `weight × signal` summation to a real factor model (orthogonalization, IC-stability weighting, covariance-based portfolio construction).

**Order is non-negotiable: data first, factors next, model last.** Most retail quant repos collapse by reversing this. Don't.

## What we're fixing

1. **Coverage** — missing categories (options-implied, microstructure, NLP, event-time, working-capital quality)
2. **Independence** — current 30 READY factors include correlated quality + value signals; weighted sum double-counts
3. **Risk awareness** — no covariance, no industry decomposition, no beta-neutralization

## Sensibull vs Kite — settled

Sensibull has no retail API; it's B2B (Zerodha embeds them inside Kite). Their analytics (max pain, OI buildup, IV percentile, dispersion) are computable from raw Kite option chain data — and we'd want our own PIT history anyway. **Skip Sensibull.** Paid stack: Kite ₹500/mo + Screener ₹420/mo. Full reasoning in [paid-data-sources.md](../reference/paid-data-sources.md).

---

## Phase 3.1 — Data acquisition (4 fork streams)

Stand up four ingest pipelines with PIT discipline. Until each has ≥90 days of accumulated history, don't move to Phase 3.2 — every factor needs ≥18 monthly periods for clean backtest, and starting factor work too early produces 5-period t-stats and false confidence.

### 3.1a — Screener Premium scraper ✅ done

| Item | Spec |
|---|---|
| File | `sources/screener_pull.py` + `sources/screener_schedules.py` |
| Table | `fundamentals_screener` — long format `(sid, period_end, period_type, line_item, value, filing_date, fetched_at)` (see [ADR 0011](../decisions/0011-long-format-for-new-fundamentals-tables.md)) |
| Cadence | Full universe weekly (~3hr at 2s delay); incremental daily for new filings |
| Auth | Cookie-jar pattern from [paid-data-sources.md](../reference/paid-data-sources.md). Re-login on 401. |

**Captured (delta vs Tickertape):** COGS, gross profit, SG&A, R&D, working-capital triple (AR/inventory/AP), goodwill, intangibles, treasury stock, standalone+consolidated separately, 10+ years quarterly.

### 3.1b — NSE F&O OI / Greeks (free, ⏳ next)

| Item | Spec |
|---|---|
| File | `sources/fno_pull.py` |
| Tables | `fno_option_chain` (snapshot), `fno_oi_history` (EOD), `fno_pcr_history` (computed) |
| Source | nselib `option_chain_indices` + `option_chain_equities`; EOD bhavcopy at `archives.nseindia.com/content/historical/DERIVATIVES/` for backfill |
| Cadence | EOD after 6 PM IST; 6mo backfill on first run |

**Captured:** full strike grid × CE/PE × all expiries; IV (exchange or Black-Scholes); Greeks; OI build-up by strike.

### 3.1c — Zerodha Kite Connect (₹500/mo, ⏳ later)

| Item | Spec |
|---|---|
| File | `sources/kite_pull.py` |
| Auth | API key + token + daily TOTP. Static IP ✅ (Oracle VM). |
| Tables | `kite_intraday_bars` (1-min, 60d rolling), `kite_tick_aggregates` (daily VWAP/twap/spread from ticks) |

**Captured:** 1-min OHLCV, daily VWAP (cleanest fair-price), bid-ask spread proxy, properly split-adjusted history, live option chain (redundant with 3.1b for safety).

### 3.1d — PIB + Earnings Call NLP (free, ⏳ last)

| Item | Spec |
|---|---|
| File | `sources/transcripts_pull.py` |
| Sources | PIB press releases (already scraped) · earnings transcripts from BSE/NSE + screener.in · ratings agency releases |
| Table | `transcripts (sid, doc_type, doc_date, source_url, raw_text, sha256, fetched_at)` — content-addressed |
| Scoring | `signals/nlp_scores.py` → `nlp_scores (sid, doc_id, sentiment, hawkish_dovish, uncertainty, forward_looking)` |

**NLP approach:** Start with FinBERT off-the-shelf + India dictionary (RBI, GST, monetary policy). Don't train custom — not enough labeled data; marginal IC gain small.

### Phase 3.1 done when

- All 4 ingests run nightly with logs + idempotent UNIQUE constraints
- Each table has ≥90 days of accumulated history
- Validation dashboard on cockpit `/data` shows row counts + latest dates
- No crashes for 30 consecutive nights
- Disk budget ~5 GB additional (Screener dwarfs the rest)

**Effort:** 3.1a=2d, 3.1b=1d, 3.1c=2d (Kite OAuth), 3.1d=3d. Total ~8 dev-days + 90-day accumulation clock.

---

## Phase 3.2 — Factor build (+50 to bring total to ~100)

Each factor: function in `signals/`, registered in `BACKTEST_SIGNALS` with `pit_column_v2`, computed by `tools/reconstruct_pit.py`. No new framework.

### 3.2.1 — Forensic + capital allocation (from 3.1a)

| # | Factor | Formula | Group |
|---|---|---|---|
| 1 | `cash_conversion_cycle` | DSO + DIO − DPO | Forensic |
| 2 | `dso_change_yoy` | Δ DSO over 1y | Forensic |
| 3 | `dio_change_yoy` | Δ DIO over 1y | Forensic |
| 4 | `nwc_to_revenue` | NWC / TTM revenue | Forensic |
| 5 | `sloan_accruals_full` | (ΔNWC − D&A) / avg total assets | Forensic |
| 6 | `gross_margin` | (Revenue − COGS) / Revenue | Quality |
| 7 | `gross_margin_4q_change` | GM(t) − GM(t−4) | Quality |
| 8 | `sga_to_revenue_change` | Δ SG&A intensity | Quality |
| 9 | `roic` ✅ | NOPAT / invested capital | Quality |
| 10 | `roiic` | Δ NOPAT / Δ invested capital, 4Q | Quality |
| 11 | `fcf_yield` ✅ | FCF(TTM) / market cap | Value |
| 12 | `fcf_margin` | FCF / Revenue | Quality |
| 13 | `capex_to_dep` | CapEx / Depreciation | Capital |
| 14 | `goodwill_to_assets` | Goodwill / Total assets | Forensic |
| 15 | `consol_standalone_gap` | Consol EPS − Standalone EPS | Forensic |

### 3.2.2 — Options-implied (from 3.1b/3.1c, F&O stocks ~200)

| # | Factor | Formula |
|---|---|---|
| 16 | `iv_skew_25d` | 25d-put IV − 25d-call IV vs ATM |
| 17 | `iv_term_structure` | (60d ATM IV − 30d ATM IV) / 30d ATM IV |
| 18 | `iv_percentile_1y` | Current ATM IV percentile vs 1y |
| 19 | `pcr_oi` | Put OI / Call OI |
| 20 | `pcr_volume` | Put volume / Call volume |
| 21 | `oi_buildup_signal` | Long vs short buildup classification |
| 22 | `max_pain_distance` | (Spot − Max Pain) / Spot |
| 23 | `iv_realised_spread` | ATM IV − 30d realised vol |

### 3.2.3 — Microstructure (from 3.1c)

| # | Factor | Formula |
|---|---|---|
| 24 | `vwap_deviation_5d` | (Close − VWAP) / VWAP, 5d avg |
| 25 | `intraday_range_compression` | 5d ATR / 20d ATR |
| 26 | `closing_strength_1m` | Avg(close−low)/(high−low), 1mo |
| 27 | `opening_gap_freq_1m` | Frequency of >1% overnight gaps |
| 28 | `bidask_spread_proxy` | Median minute (high−low)/mid |
| 29 | `volume_clock_concentration` | % daily volume in last 30min |
| 30 | `kyle_lambda` | (Δprice / signed volume) slope |
| 31 | `tick_imbalance_5d` | (up_ticks − down_ticks) / total |
| 32 | `intraday_momentum_persistence` | Spearman(morning, afternoon return) |

### 3.2.4 — NLP / sentiment (from 3.1d)

| # | Factor | Formula |
|---|---|---|
| 33 | `news_sentiment_30d` | Mean FinBERT, 30d, exp-decayed |
| 34 | `earnings_call_tone_qoq` | Sentiment Δ vs prior call |
| 35 | `regulatory_sentiment_90d` | Mean sentiment of regulatory mentions, 90d |
| 36 | `forward_looking_intensity` | Count fwd-looking phrases / total words |
| 37 | `uncertainty_word_density` | Loughran-McDonald uncertainty hits |
| 38 | `pib_mention_velocity` | Δ PIB mentions, 30d vs 90d |
| 39 | `analyst_text_dispersion` | Stdev of analyst note sentiments |

### 3.2.5 — Event-time / PEAD (existing data)

| # | Factor | Formula |
|---|---|---|
| 40 | `pead_drift_60d` | Stock return − sector return, 60d post earnings beat |
| 41 | `earnings_surprise_std` | (actual − consensus) / std of consensus |
| 42 | `buyback_announcement_30d` | 1 if buyback announced last 30d |
| 43 | `dividend_change_signal` | Δ dividend rate vs prior period |
| 44 | `index_inclusion_proximity` | Distance from NIFTY 500 cut-off |
| 45 | `corporate_action_density` | Count corp actions, 1y |

### 3.2.6 — Industry dummies (structural)

| # | Factor | Formula |
|---|---|---|
| 46 | `industry_id` | 22-column one-hot for India industries — risk-model input |

### 3.2.7 — Macro extensions

| # | Factor | Formula |
|---|---|---|
| 47 | `inr_carry_proxy` | INR forward premium 6m |
| 48 | `india_credit_spread` | AAA corp yield − G-Sec yield |
| 49 | `commodity_beta_oil` | Stock beta to crude, 252d |
| 50 | `commodity_beta_metals` | Stock beta to LME metals, 252d |

### Phase 3.2 done when

- All 50 entered in `BACKTEST_SIGNALS`
- All compute via `tools/reconstruct_pit.py`
- ≥6 monthly snapshots populated (n=6 sanity, not statistical KEEP)
- No factor has >50% NaN rate within expected universe
- Group/family classified in registry
- `docs/reference/factor-catalog.md` lists all 100 with formulas

**Effort:** 3.2.1=4d, 3.2.2=3d, 3.2.3=3d, 3.2.4=5d (NLP setup), 3.2.5=3d, 3.2.6/3.2.7=2d. Total ~20 dev-days, gated on 3.1's 90-day accumulation clock.

---

## Phase 3.3 — Factor model upgrade (the real edge)

Four sub-phases, in order.

### 3.3a — IC stability weighting

Replace C13b's fixed verdict tiers (`|t|≥2.5 → 1.0×`) with dynamic weights from rolling-window IC stability.

```python
# tools/factor_weights.py
# For each (factor, cap_tier):
#   Compute rolling IC over 24 months
#   weight = mean(IC) / std(IC), clipped to [0, 1]
#   Decay older periods exponentially (half-life 12 months)
# Write to factor_weights_v2 (signal, cap_tier, weight, asof_date)
```

Cockpit `/factor-weights` shows current weights + evolution.

### 3.3b — Orthogonalization  (↔ 2.5)

ROE, ROA, profit_margin, ROIC are correlated. So are forensic accruals factors. So are value factors. Current weighted sum double-counts.

**Approach (start simple):**

| | Method | Pros | Cons |
|---|---|---|---|
| 3.3b-1 | Sequential regression — order factors by t-stat, take residuals | Interpretable, preserves labels | Order-dependent |
| 3.3b-2 | PCA on factor returns | Removes all correlation | Loses factor identity → can't explain dossier |
| **3.3b-3** | Hybrid: orthogonalize **within group** (Quality vs Quality), keep cross-group raw | **Best of both** | Most code |

**Decision:** start with sequential regression for transparency; migrate to the hybrid after Phase 3.2 is fully populated. Skip PCA — opacity is too costly for a tool that must explain itself.

**Integration:** Track 2.5 (XGBoost) trains on this orthogonalized matrix when ready.

### 3.3c — Mean-variance portfolio construction  (↔ 2.4)

```
1. Estimate per-stock daily return covariance, 252d window
2. Shrink toward diagonal (Ledoit-Wolf) for 2,448-stock matrix
3. Construct portfolio = argmax (factor_score × w) − λ × (w' Σ w)
   subject to: per-stock cap, per-sector cap, turnover limit
4. Output: weighted portfolio, not just ranked list
```

New table: `portfolio_weights (asof_date, sid, weight, factor_score, marginal_risk_contrib)`.

Cockpit `/portfolio`: actual weights, sector concentration, expected vol, top risk contributors. **Integrates with Track 2.4** ([0003 mother plan](0001-mother-plan.md)) — whichever ships first owns `portfolio_holdings`.

### 3.3d — Risk decomposition (Barra-style, defer until 3.3a–c work)

Cross-sectional regression each day: `stock_return ~ style_factors + industry_dummies + residual`. Lets every dossier say "+X% from value, −Y% from chemicals, +Z% specific." Real-fund-grade attribution.

### Phase 3.3 done when

- `factor_weights_v2` populated, refreshed monthly
- Orthogonalization runs in pipeline before screener output
- Portfolio construction outputs weighted positions
- Risk decomposition reports for top-20 holdings
- **Hard gate:** factor-model portfolio beats current screener portfolio by **≥1.5% annualized risk-adjusted over 18–24 months**. Else don't ship.

**Effort:** 3.3a=3d, 3.3b (sequential)=4d, 3.3b (hybrid)=5d, 3.3c=5d, 3.3d=7d. Total ~24 dev-days.

---

## Open questions

1. **Cap on factor count.** Is 100 the right number? Decision rule: a new factor must add positive marginal IC after orthogonalization. Rule kicks in after 3.3b.
2. **Lite path?** Top-30 factors for daily ranking, full path for monthly rebal? Saves ~80% compute, loses <5% IC. Prefer lite + full split.
3. **AI fits where?** This plan is classical quant. LLM-summarized dossier text, semantic news clustering, anomaly detection — track separately.
4. **Backtest length.** Phase 3.3's 1.5% gate needs 24+ months of PIT. We have 7. Clock to validation: ~17 months (2027-10). All 3.3 work is on faith until then; accept.

## Success — by the numbers

| Metric | Today | After |
|---|---|---|
| Registered factors | 42 (30 READY) | 100 (≥80 READY) |
| Categories covered | 9 | 13 |
| Independence | Raw weighted sum | Orthogonalized within group |
| Position sizing | Equal weight in deciles | Mean-variance with risk caps |
| Risk attribution | None | Style + industry + specific |
| Weight schedule | Per-tier t-stat tiers | Rolling IC + ICIR dynamic |

## Considered & rejected

- **EODHD over Screener.** Cleaner filing-date PIT but $20–60/mo vs ₹420/mo, 90% overlap for our universe. Use EODHD only for one-month bursts extending PIT past 2023.
- **Refinitiv / Bloomberg for risk factors.** Out of budget. Compute factor returns from cross-sectional regression — noisier but free + PIT-clean.
- **Custom-train FinBERT.** Not enough labeled data; off-the-shelf + India dictionary is good enough.
- **Tick-level microstructure storage.** ~50GB/year. Skip; rely on minute-bar aggregates.
- **Sensibull subscription.** No retail API. Settled above.

## Execution order

1. **Week 1:** 3.1a (Screener) — unlocks most factors fastest ✅
2. **Week 2:** 3.1b (F&O OI) — free, fast
3. **Week 3–4:** 3.1c (Kite) — OAuth + intraday accumulation
4. **Week 5–6:** 3.1d (NLP) — gives 3.1a–c time to accumulate
5. **Week 7–8:** 3.2.1, 3.2.2 (forensic + options factors)
6. **Week 9–10:** 3.2.3, 3.2.5, 3.2.7 (microstructure, event-time, macro)
7. **Week 11–12:** 3.2.4 (NLP factors — cleanest data is last)
8. **Week 13–15:** 3.3a (IC weighting) — immediate value, low risk
9. **Week 16–19:** 3.3b (orthogonalization)
10. **Week 20–24:** 3.3c (portfolio construction)
11. **Month 7+:** 3.3d (risk model)

Total: ~6 months evening/weekend with concurrent 3-month accumulation clock. By 2026-11: 100 factors + orthogonalization + IC weighting. By 2027-04: full risk model. By 2027-10: 18-month head-to-head verdict.
