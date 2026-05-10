---
Status: active
Created: 2026-05-03
Last updated: 2026-05-10
Owner: Amit Bhagat
Implementation:
  A1 (Screener Premium xlsx scraper): universe-complete on 2026-05-10.
    2,119 / 2,448 stocks pulled, 681,256 rows in fundamentals_screener,
    329 fetch failures (almost all SMALL — delisted/newly-listed/templates).
    sources/screener_pull.py.
  A2 (Screener schedules JSON scraper): module landed 2026-05-10
    (sources/screener_schedules.py, commit 6bd5a38). Smoke-tested on RELI
    (276 rows / 23 new line items incl. Trade Payables, ST/LT Borrowings,
    Plant Machinery). Universe run kicked off 2026-05-10 12:17 UTC, ETA ~4 hrs.
  A3 (NSE F&O OI), A4 (Kite + transcripts): not started.
  Phase B factors shipped today: signals/roic.py (1,501 stocks scored),
    signals/fcf_yield.py (1,195 stocks scored). Both wired into pipeline.py
    via signal_roic / signal_fcf_yield steps. Neither in scoring weights yet
    (no validated t-stat — needs N months of forward returns).
Related ADRs: 0009-factor-track-parallel-to-d-track.md, 0011-long-format-for-new-fundamentals-tables.md
---

# 0005 — Double Factor Count to 100 + Factor Model Upgrade

> Today: 42 registered factors, 30 READY. That's top-quartile retail, mid-tier
> for a small systematic shop. This plan takes us to **100 factors** and then
> upgrades the scoring stack from `weight × signal` summation to a real factor
> model (orthogonalization, IC-stability weighting, covariance-based portfolio
> construction).
>
> **Order of operations is non-negotiable: data first, factors next, model last.**
> Most retail quant repos collapse because they skip step 1 and reverse step 3
> with step 2. Don't.

---

## What problem are we solving?

Factor count alone is vanity. The real gap between v2 today and a real systematic
process is in three places:

1. **Coverage** — entire factor categories are missing (options-implied,
   microstructure, NLP, event-time, working-capital quality). Each missing
   category leaves whole regimes where v2 has no edge.
2. **Independence** — the 30 READY factors include a lot of correlated quality
   and value signals. Their weighted sum double-counts.
3. **Risk awareness** — there's no covariance, no industry decomposition, no
   beta-neutralization. Two stocks with identical factor scores but opposite
   risk profiles get the same allocation.

This plan fixes all three. The result is a system where adding the 60th factor
*actually* helps, because the framework knows how to incorporate it without
double-counting or risking ruin.

---

## Sensibull vs Zerodha Kite — settled

| Question | Answer |
|---|---|
| Does Sensibull sell a retail API? | No. Their commercial offering is B2B; brokers embed their analytics into their own platforms. Zerodha is one of their integration partners (you see Sensibull *inside* Kite). |
| What does Kite give us for options? | Real-time LTP, OI, IV (exchange-computed), Greeks (delta/gamma/theta/vega), full option chain across all F&O contracts. WebSocket streaming. 5+ years historical OHLCV. |
| What is Sensibull adding on top? | Pre-built analytics: max pain, OI build-up classification, strategy P&L visualizer, IV percentile vs history, dispersion screens. **Every one of these we can compute ourselves from Kite raw data — and we'd want to, to keep our own PIT history.** |
| Verdict | **Skip Sensibull. Kite covers the data; we compute the derived analytics ourselves.** |

This means the paid stack is unchanged from the existing playbook:
- Zerodha Kite Connect — ₹500/mo
- Screener Premium — ₹420/mo
- Reserve — ₹4,080/mo (EODHD bursts, Trendlyne if needed)

---

## Phase A — Data First (4 acquisition streams)

**Goal:** stand up four new ingestion pipelines, each landing in a versioned
SQLite table with PIT discipline. Until all four streams have at least
**90 days of accumulated history**, do not move to Phase B factor builds —
because every factor needs ≥18 monthly periods of clean PIT data to backtest,
and starting factor work before data work is how you get fooled by 5-period
t-stats.

### A1 — Screener Premium scraper (highest ROI, do first)

| Item | Spec |
|---|---|
| New file | `sources/screener_pull.py` |
| New table | `fundamentals_screener` |
| Schema | `(sid, period_end, period_type, line_item, value, filing_date, fetched_at)` long format — one row per (stock × period × line item) |
| Cadence | Full universe weekly (5,000 × 1 HTTP × 2s = ~3 hours), incremental daily for stocks with new filings |
| Auth | Cookie-jar reuse pattern from `paid_data_sources.md`. Save session cookie to `~/.cache/screener_cookie.json`. Re-login on 401. |
| Quotas | Premium = unlimited downloads. Self-impose 2s delay so we don't get banned. |
| Output sanity | Per-stock: must have at least 4 quarterly periods + 5 annual periods, else log to `screener_pull_errors`. |

**Data captured (delta vs Tickertape):**
- COGS, gross profit, gross margin
- SG&A, R&D (where reported)
- Receivables, inventory, payables (working capital triple)
- Goodwill, intangibles
- Treasury stock (buybacks)
- Standalone vs consolidated separately
- 10+ years quarterly (Tickertape only has 10 quarters)

### A2 — NSE F&O OI / Greeks (free, do second)

| Item | Spec |
|---|---|
| New file | `sources/fno_pull.py` |
| New tables | `fno_option_chain` (snapshot), `fno_oi_history` (EOD), `fno_pcr_history` (computed) |
| Source | nselib `option_chain_indices` and `option_chain_equities` — confirmed working. EOD bhavcopy at `https://archives.nseindia.com/content/historical/DERIVATIVES/` for backfill. |
| Cadence | EOD daily after 6 PM IST (existing 14:00 UTC cron). 6 months historical backfill on first run. |
| Schema (`fno_option_chain`) | `(sid, expiry, strike, opt_type, oi, oi_change, volume, ltp, iv, delta, gamma, theta, vega, snapshot_date)` |

**Data captured:**
- Per-stock option chain EOD: full strike grid × CE/PE × all expiries
- Implied volatility (exchange-published or Black-Scholes computed)
- Greeks (delta, gamma, theta, vega) — Kite gives these; nselib needs us to compute
- OI build-up / unwinding by strike

### A3 — Zerodha Kite Connect (do third — only if user has Zerodha account)

| Item | Spec |
|---|---|
| New file | `sources/kite_pull.py` |
| Auth | API key + access token + daily TOTP login flow. Static IP requirement met (Oracle VM). |
| New tables | `kite_intraday_bars` (1-min bars, last 60 days), `kite_tick_aggregates` (daily VWAP/twap/spread metrics derived from ticks) |
| Cadence | Intraday bars: post-close pull at 4 PM IST. Tick stream: optional, only if we go live. |
| Coverage | All 2,448 universe stocks + index F&O |

**Data captured:**
- 1-minute OHLCV (60 days rolling)
- Daily VWAP per stock (cleanest version of daily fair price)
- Bid-ask spread proxy from minute bars
- Properly split-adjusted historical (no Adj-Close vs raw issues)
- Live option chain feed (alternative to A2 nselib path; redundant for safety)

### A4 — PIB + Earnings Call NLP (free, do last)

| Item | Spec |
|---|---|
| New file | `sources/transcripts_pull.py` |
| Sources | (a) PIB press releases — already scraped, currently lost in non-incremental pipeline. (b) Earnings call transcripts from BSE/NSE corporate announcements + screener.in earnings call section. (c) Ratings agency releases. |
| New table | `transcripts (sid, doc_type, doc_date, source_url, raw_text, sha256, fetched_at)` — content-addressed, no dedup issues. |
| Scoring file | `signals/nlp_scores.py` — runs sentiment + tone analysis on raw_text |
| Scoring table | `nlp_scores (sid, doc_id, sentiment, hawkish_dovish, uncertainty, forward_looking, computed_at)` |

**NLP approach:** Start with FinBERT (off-the-shelf finance-tuned sentiment),
add custom dictionary scoring for India-specific terms (RBI, monetary policy,
GST). Don't train custom models — we don't have labeled data and the
marginal IC gain from custom training is small at this scale.

### Phase A definition-of-done

- [ ] All 4 ingest pipelines run nightly, with logs and idempotent UNIQUE constraints
- [ ] Each table has ≥90 days of accumulated history (start clock the day A1 lands)
- [ ] Validation dashboard on cockpit `/data` page shows row counts and latest dates
- [ ] No script crashes for 30 consecutive nights
- [ ] Total disk: budget ~5 GB additional (Screener fundamentals dwarf the rest)

**Estimated time:** A1 = 2 days; A2 = 1 day; A3 = 2 days (Kite OAuth annoyance);
A4 = 3 days. Total ~8 dev-days. Plus 90-day clock for accumulation.

---

## Phase B — Factor Build (target +50 to bring total to 100)

Each factor follows the existing pattern: a function in `signals/`, registered
in `BACKTEST_SIGNALS` with `pit_column_v2` populated, computed by
`tools/reconstruct_pit.py` on every snapshot. No new framework.

### B1 — Forensic & capital allocation (12-15 factors, from A1)

| # | Factor | Formula | Group | Expected universe |
|---|---|---|---|---|
| 1 | `cash_conversion_cycle` | DSO + DIO − DPO | Forensic | All |
| 2 | `dso_change_yoy` | Δ DSO over 1y | Forensic | All |
| 3 | `dio_change_yoy` | Δ DIO over 1y | Forensic | All |
| 4 | `nwc_to_revenue` | NWC / TTM revenue | Forensic | All |
| 5 | `sloan_accruals_full` | (ΔNWC − D&A) / avg total assets | Forensic | All |
| 6 | `gross_margin` | (Revenue − COGS) / Revenue | Quality | All |
| 7 | `gross_margin_4q_change` | GM(t) − GM(t−4) | Quality | All |
| 8 | `sga_to_revenue_change` | Δ SG&A intensity | Quality | All |
| 9 | `roic` | NOPAT / invested capital | Quality | All |
| 10 | `roiic` | Δ NOPAT / Δ invested capital, 4Q rolling | Quality | All |
| 11 | `fcf_yield` | FCF (TTM) / market cap | Value | All |
| 12 | `fcf_margin` | FCF / Revenue | Quality | All |
| 13 | `capex_to_dep` | CapEx / Depreciation | Capital | All |
| 14 | `goodwill_to_assets` | Goodwill / Total assets | Forensic | All |
| 15 | `consol_standalone_gap` | Consol EPS − Standalone EPS | Forensic | All |

### B2 — Options-implied (6-8 factors, from A2/A3)

| # | Factor | Formula | Universe |
|---|---|---|---|
| 16 | `iv_skew_25d` | 25d-put IV − 25d-call IV (relative to ATM) | F&O stocks (~200) |
| 17 | `iv_term_structure` | (60d ATM IV − 30d ATM IV) / 30d ATM IV | F&O stocks |
| 18 | `iv_percentile_1y` | Current ATM IV percentile rank vs 1y history | F&O stocks |
| 19 | `pcr_oi` | Put OI / Call OI | F&O stocks |
| 20 | `pcr_volume` | Put volume / Call volume | F&O stocks |
| 21 | `oi_buildup_signal` | Long buildup vs short buildup classification | F&O stocks |
| 22 | `max_pain_distance` | (Spot − Max Pain) / Spot | F&O stocks |
| 23 | `iv_realised_spread` | ATM IV − 30d realised vol | F&O stocks |

### B3 — Microstructure (8-10 factors, from A3)

| # | Factor | Formula | Universe |
|---|---|---|---|
| 24 | `vwap_deviation_5d` | (Close − VWAP) / VWAP, avg over 5d | All |
| 25 | `intraday_range_compression` | 5d ATR / 20d ATR (squeeze flag) | All |
| 26 | `closing_strength_1m` | Avg(close − low) / (high − low), 1mo | All |
| 27 | `opening_gap_freq_1m` | Frequency of >1% overnight gaps | All |
| 28 | `bidask_spread_proxy` | Median minute-bar (high − low) / mid | All |
| 29 | `volume_clock_concentration` | % daily volume in last 30min, 1mo avg | All |
| 30 | `kyle_lambda` | (Δprice / signed volume) regression slope | F&O stocks |
| 31 | `tick_imbalance_5d` | (up_ticks − down_ticks) / total ticks | F&O stocks (need ticks) |
| 32 | `intraday_momentum_persistence` | Spearman corr(morning return, afternoon return), 1mo | All |

### B4 — NLP/sentiment (5-8 factors, from A4)

| # | Factor | Formula | Universe |
|---|---|---|---|
| 33 | `news_sentiment_30d` | Mean FinBERT sentiment of news, 30d, exponentially decayed | All |
| 34 | `earnings_call_tone_qoq` | Sentiment delta latest call vs prior call | Stocks with calls |
| 35 | `regulatory_sentiment_90d` | Mean sentiment of regulatory mentions, 90d | All |
| 36 | `forward_looking_intensity` | Count of forward-looking phrases / total words, latest call | Stocks with calls |
| 37 | `uncertainty_word_density` | Loughran-McDonald uncertainty dictionary hit rate, latest filing | All |
| 38 | `pib_mention_velocity` | Δ in PIB mention count, 30d vs 90d trailing | All |
| 39 | `analyst_text_dispersion` | Stdev of analyst note sentiments | Covered stocks |

### B5 — Event-time / PEAD (5-8 factors, free)

| # | Factor | Formula | Universe |
|---|---|---|---|
| 40 | `pead_drift_60d` | Stock return − sector return, 60d post earnings beat | All with earnings |
| 41 | `earnings_surprise_std` | (actual − consensus) / std of consensus | Covered stocks |
| 42 | `buyback_announcement_30d` | 1 if buyback announced in last 30d | All |
| 43 | `dividend_change_signal` | Δ dividend rate vs prior period | Dividend payers |
| 44 | `index_inclusion_proximity` | Distance from NIFTY 500 cut-off rank | Borderline stocks |
| 45 | `corporate_action_density` | Count of corp actions, 1y | All |

### B6 — Industry / sector dummies (1 factor, but it's structural)

| # | Factor | Formula | Universe |
|---|---|---|---|
| 46 | `industry_id` | One-hot encoding of GICS-like industry (22 industries for India) | All |

This isn't really one factor — it's a 22-column one-hot block that becomes
input to the risk model in Phase C. Counts as 1 in the registry.

### B7 — Macro extensions (3 factors, from existing data + new)

| # | Factor | Formula | Universe |
|---|---|---|---|
| 47 | `inr_carry_proxy` | INR forward premium 6m | All |
| 48 | `india_credit_spread` | AAA corp yield − G-Sec yield | All |
| 49 | `commodity_beta_oil` | Stock beta to crude oil, 252d rolling | Oil-exposed sectors |
| 50 | `commodity_beta_metals` | Stock beta to LME metals, 252d rolling | Metal stocks |

**Phase B total: 50 new factors. Combined with existing 42 (post pruning of dups)
→ approximately 90-100 factors registered.**

### Phase B definition-of-done

- [ ] All 50 factors have entries in `BACKTEST_SIGNALS`
- [ ] All compute via `tools/reconstruct_pit.py`
- [ ] At least 6 monthly snapshots populated for each (n=6 for sanity, not statistical KEEP)
- [ ] No factor has >50% NaN rate within its expected universe
- [ ] Each factor's group/family classification is in registry
- [ ] Documentation: `docs/reference/factor-catalog.md` lists all 100 with formulas

**Estimated time:** B1 = 4 days; B2 = 3 days; B3 = 3 days; B4 = 5 days
(NLP setup); B5 = 3 days; B6/B7 = 2 days. Total ~20 dev-days, gated on Phase A
data accumulation.

---

## Phase C — Factor Model Upgrade (the real edge)

This is where v2 stops being a "factor zoo with weighted sum" and becomes a
factor model. Three orthogonal pieces, build in order.

### C1 — IC stability weighting

**Replace:** the current C13b verdict tiers (`|t|≥2.5 → 1.0×`, etc.) which are
fixed and don't adapt as new data arrives.

**With:** dynamic factor weights derived from rolling-window IC stability.

Implementation:
```python
# tools/factor_weights.py
# For each (factor, cap_tier):
#   Compute rolling IC over 24 months
#   weight = mean(IC) / std(IC) clipped to [0, 1]
#   Decay older periods exponentially (half-life 12 months)
# Write to factor_weights_v2 (signal, cap_tier, weight, asof_date)
```

Cockpit page `/factor-weights` shows current weights and how they've evolved.

### C2 — Orthogonalization

**Problem:** ROE, ROA, profit_margin, ROIC are all correlated. So are the
forensic accruals factors. So are the value factors. The current weighted sum
double-counts.

**Approach (start simple, escalate if needed):**

| Step | Method | Pros | Cons |
|---|---|---|---|
| C2a | **Sequential regression**: rank factors by historical t-stat. Take residuals at each step. | Interpretable; preserves signal labels. | Order-dependent. |
| C2b | **PCA on factor returns**: find principal components, weight by IC of each PC. | Removes all correlation. | Loses factor identity → can't explain dossier. |
| C2c | **Hybrid**: orthogonalize within group (Quality vs Quality), keep cross-group factors raw. | Best of both. | Most code. |

**Decision:** start with C2a for transparency, migrate to C2c once Phase B
is fully populated. Skip C2b — opacity is too costly for a retail tool that
must explain itself.

### C3 — Covariance matrix + portfolio construction

**Problem:** Two stocks with score 8.5 may have wildly different correlations
to existing holdings. Equal-weighting them concentrates risk.

**Implementation:**
```
1. Estimate per-stock daily return covariance, 252d window
2. Shrink toward diagonal (Ledoit-Wolf shrinkage) to handle 2,448-stock matrix
3. Construct portfolio = argmax (factor_score × w) − λ × (w' Σ w)
   subject to: per-stock cap, per-sector cap, turnover limit
4. Output: weighted portfolio, not just ranked list
```

**New table:** `portfolio_weights (asof_date, sid, weight, factor_score, marginal_risk_contrib)`.

**Cockpit page:** `/portfolio` shows actual weights, sector concentration,
expected vol, top risk contributors.

### C4 — Risk model decomposition (Barra-style)

**Goal:** split each stock's expected return into:
- Factor exposure (style factors: size, value, quality, momentum, vol)
- Industry exposure (22 industries)
- Stock-specific (residual)

**Why bother:** lets you say "this dossier earned +X% from value factor,
+Y% from momentum, −Z% from being in chemicals sector." Real-fund-grade
attribution.

**Implementation plan:**
- Cross-sectional regression each day: stock_return ~ style_factors + industry_dummies
- Residuals = stock-specific return
- Backtest factor returns themselves (not just IC) — this is what AQR/Barra publish

**Defer until C1-C3 are fully working.** This is the most valuable, the most
fragile, and most easily over-engineered.

### Phase C definition-of-done

- [ ] `factor_weights_v2` table populated, refreshed monthly
- [ ] Orthogonalization runs in scoring pipeline before screener output
- [ ] Portfolio construction outputs weighted positions (not just ranks)
- [ ] Risk decomposition reports for top-20 portfolio holdings
- [ ] Backtest comparison: factor-model portfolio vs old screener portfolio over 18-24 months. **Must beat by ≥1.5% annualized risk-adjusted, else don't ship.**

**Estimated time:** C1 = 3 days; C2a = 4 days; C2c = 5 days; C3 = 5 days; C4 = 7
days. Total ~24 dev-days.

---

## Open questions

1. **Cap on factor count.** Is 100 the right number? Could go to 200 with more
   alt-data, but every factor adds storage + compute + risk of overfitting.
   Decision rule: a new factor must add positive marginal IC after orthogonalization
   against the existing set. If it doesn't, drop it. **This rule kicks in after C2.**
2. **Should we run all 100 factors all the time?** Or have a "lite" path that
   uses only the top-30 factors for daily ranking, full path for monthly
   rebalance? Prefer lite + full split — saves ~80% compute, loses <5% IC.
3. **Where does AI fit?** This plan is classical quant. The "AI-native" promise
   in v2's mission needs a separate companion plan: LLM-summarized dossier text,
   semantic news clustering, anomaly detection. Track in 0006.
4. **Backtest extension.** Phase C's "must beat by 1.5% annualized" check needs
   24+ months of PIT history. We have 7. The clock to run this comparison is
   ~17 months from today (2027-10). Until then, all C work is on faith. Accept
   this; do not pause C work waiting for backtest length.

---

## What does success look like?

When this plan is fully shipped:

| Metric | Today | After |
|---|---|---|
| Registered factors | 42 (30 READY) | 100 (≥80 READY) |
| Factor categories covered | 9 | 13 |
| Factor independence | Raw weighted sum | Orthogonalized within group |
| Position sizing | Equal weight in deciles | Mean-variance optimized with risk caps |
| Risk attribution | None | Style + industry + specific |
| Backtest IC stability | Per-tier t-stat | Rolling IC + ICIR weighted dynamically |
| Smart-beta tracking | Discovered we track NIFTY200 VALUE 30 at 0.984 corr but lag 125 bps/mo | Should match or beat V30 after quality overlay |
| Performance bench | None | Live paper-trade 6mo before any real capital |

---

## What did we consider and reject?

- **EODHD instead of Screener Premium.** Cleaner filing-date PIT, but $20-60/mo
  vs ₹420/mo and 90% overlap with what Screener gives for our universe. Use
  EODHD for one-month bursts when we want to extend PIT past 2023 into 2010-2020.
- **Refinitiv / Bloomberg for risk model factor returns.** Way out of budget.
  We'll compute our own factor returns from cross-sectional regression — slightly
  noisier but free and fully PIT-clean.
- **Custom-train FinBERT on Indian filings.** Not enough labeled data; off-the-shelf
  FinBERT + India dictionary augmentation is good enough for v1 of NLP factors.
- **Tick-level microstructure.** Kite gives ticks but storing them is ~50GB/year.
  Skip; rely on minute-bar aggregates for now. Revisit only if microstructure
  factors clearly KEEP.
- **Sensibull standalone subscription.** No retail API. Their value-add is
  analytics on top of raw NSE/exchange data we can compute ourselves once we
  have F&O OI and Greeks via A2/A3.

---

## Suggested execution order (the actual play)

1. **Week 1:** A1 (Screener scraper). This unlocks the most factors, fastest.
2. **Week 2:** A2 (NSE F&O OI). Free, fast, separately useful.
3. **Week 3-4:** A3 (Kite). OAuth + intraday accumulation start.
4. **Week 5-6:** A4 (NLP). Gives time for A1-A3 data to accumulate.
5. **Week 7-8:** B1, B2 (forensic + options factors compute on accumulated data).
6. **Week 9-10:** B3, B5, B7 (microstructure, event-time, macro).
7. **Week 11-12:** B4 (NLP factors — last because the cleanest data depends on
   the longest-running scraper).
8. **Week 13-15:** C1 (IC weighting). Immediate value, low risk.
9. **Week 16-19:** C2 (orthogonalization). Real engineering.
10. **Week 20-24:** C3 (portfolio construction).
11. **Month 7+:** C4 (risk model). Wait until enough factor returns exist.

Total: roughly 6 months of evening/weekend work for one developer, with the
~3 month accumulation clock running concurrently.

If this rolls out cleanly, by 2026-11 v2 has 100 factors with orthogonalization
and IC weighting; by 2027-04, full risk model and portfolio construction;
by 2027-10, 18-month head-to-head against the original screener will tell us
whether all this work moved the needle.
