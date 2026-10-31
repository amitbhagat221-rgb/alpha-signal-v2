# Research 0019 — what can be predicted in Indian options markets to earn a small, repeatable edge?

Brief pasted by Amit on 2026-10-26 ("do a deep research below"). The brief is kept verbatim below the line. The Phase 0 data inventory follows it (2026-10-26). The brief says to stop after Phase 0 and present the inventory.

---

# Deep Research: What Can Be Predicted in Indian Options Markets to Earn a Small, Repeatable Edge?

## The question
If we can predict *something* with a measurable degree of confidence, can we earn a small amount of money on a repeatable basis from that prediction using options?

Do NOT assume the answer up front. Treat every candidate prediction as a hypothesis. That includes realized-vs-implied vol, which earlier discussion suggested as the leading candidate but which is unproven on our data. The goal is a **ranked map** of:
- what is predictable
- what the option price already embeds
- where the gap between the two is large enough, stable enough and cheap enough to monetise

## First principles to anchor the research
1. **An option chain is the market's forecast.** It encodes a full risk-neutral distribution of the underlying at each expiry: direction, magnitude, skew, tails and term structure.
2. **Edge comes only from probability vs price.** We profit only when our probability for some outcome differs from the market-implied probability, we are right about the difference often enough, and the gap exceeds costs.
3. **Confidence is not accuracy.** Every structure has a **break-even hit rate** set by its payoff asymmetry. A 70%-accurate prediction can lose money on a short strangle; a 35%-accurate one can make money on a long wing. The research must express everything as **(model probability, implied probability, break-even probability, payoff)**.
4. **Many apparent anomalies are the same risk in disguise**, usually short volatility or short tail risk. Distinguish true independent edges from repackaged risk premia.

## Constraints
- **Decision frequency:** daily/EOD with setups defined in advance.
  - Tick-level/intraday micro-analysis is excluded.
  - On-the-fly discretionary positions are excluded.
  - Market-making/spread capture is excluded.
  - Expiry-day effects are allowed only if they can be acted on from a decision made at a prior EOD or a fixed scheduled time.
- **Output feeds an AI agent** operating inside tight, mechanical boundaries.
- **Reuse:** the existing factor library (alpha-signal) and all datasets in our database should be leveraged. The web should be used for literature, regulation and any missing public data (NSE bhavcopy, participant-wise OI, F&O ban list, India VIX history, corporate actions, event calendars).

---

## Phase 0 — Data inventory (report, then pause)
1. Discover the database schema. Inventory everything relevant:
   - underlying OHLC (index and stocks)
   - futures
   - option chains (bid/ask/LTP/OI/volume/IV per strike and expiry)
   - India VIX
   - participant-wise OI (FII/DII/Pro/Client)
   - F&O ban list
   - corporate actions and earnings dates
   - macro/event calendars
   - global data (US VIX, GIFT Nifty, USDINR, crude)
   - the alpha-signal factor library
2. For each dataset, report:
   - coverage and frequency
   - gaps
   - point-in-time integrity
   - survivorship
   - whether bid/ask (not just LTP) exists
3. Identify which candidate predictions in Phase 2 are testable with current data, which need web data, and which are untestable.

**Stop and present this inventory before continuing.**

## Phase 1 — Global calibration scan: where is the market's implied distribution wrong?
This is the core, assumption-free step.

1. For each trading day, underlying (Nifty, Bank Nifty, Sensex, then liquid stocks) and expiry:
   - Extract the **risk-neutral distribution** from the option chain. Use Breeden–Litzenberger on a smoothed IV surface (e.g. SVI, or a spline in delta space). Document the smoothing method and its sensitivity.
2. For a grid of outcomes, compare the **implied probability** to the **realized frequency** across all history:
   - P(S_T > K) for strikes spanning about ±4σ
   - P(|move| > x)
   - P(stays within range)
   - P(touches level)
3. Produce **calibration curves / reliability diagrams**:
   - by moneyness bucket, tenor, day-of-week-to-expiry, VIX regime, event vs non-event periods, and pre/post each regulatory change
4. Answer specifically:
   - Is the centre (ATM) systematically over/under-priced? This is the VRP.
   - Are the wings (tails) systematically over/under-priced, and on which side?
   - Is skew rich or cheap relative to realized downside asymmetry?
   - Are near-expiry OTM options overpriced (lottery demand)?
   - Is there a directional bias in the implied forward vs realized drift?
5. Convert each miscalibration into rupee terms: **expected P&L per lot after costs** for the simplest structure that isolates it.

This phase tells us *where* to look. Everything after builds on it.

## Phase 2 — Candidate prediction universe
For each candidate, define:
- the exact prediction
- what market price embeds it
- the cleanest structure to monetise it
- data needed
- a cheap first test

**A. Distributional (properties of the underlying's move)**
1. Magnitude: realized vol over the option's life vs IV
2. Change in IV (vega bet), independent of realized vol
3. Skew: downside vs upside asymmetry vs put/call skew
4. Tails: frequency of large moves vs wing pricing
5. Term structure: front vs back IV mean reversion
6. Direction (as a control). Compare monetising via options vs futures.
7. Range: probability of staying inside a band vs condor pricing
8. Overnight/weekend vs intraday vol split. Check whether theta over weekends/holidays is mispriced relative to realized gap risk.

**B. Event-driven**
1. Earnings: implied event move vs realized event move, per stock and per sector
2. Macro events: Union Budget, RBI policy, elections, US Fed/CPI, US market closures
3. F&O ban list entry/exit and its effect on IV and realized vol
4. Index rebalances, dividends, corporate actions
5. Pre-holiday / long-weekend effects

**C. Positioning and flow (observable at EOD)**
1. Open-interest concentration and **expiry pinning**: does price gravitate to high-OI strikes into expiry?
2. Dealer gamma exposure estimated from OI: does estimated positive/negative gamma predict next-day/next-week realized vol?
3. Participant-wise OI (FII long/short ratios in index futures and options) as a predictor of direction or vol
4. Put-call ratio (OI and volume), OI build-up/unwind patterns
5. Retail-heavy expiry-day dynamics, observable via scheduled-time decisions

**D. Relative value (prices inconsistent with each other)**
1. Nifty vs Sensex IV for overlapping exposures
2. Nifty vs Bank Nifty IV ratio vs realized vol ratio
3. Index IV vs constituent IVs (implied correlation / dispersion), feasibility permitting
4. Put-call parity and futures basis deviations at EOD. Check whether they are exploitable after costs or just stale prints.
5. Calendar and butterfly arbitrage violations on the surface

**E. Cross-asset / lead-lag predictors**
- US VIX moves, GIFT Nifty, USDINR implied/realized vol and crude as next-day predictors of Indian IV or realized vol

**F. Repurposed factor library**
- Test every alpha-signal factor as a predictor of **magnitude, IV change, skew change and event move**, not just direction.

Add any further candidates found in Phase 3's literature review.

## Phase 3 — Literature and market-structure review (web)
1. Survey the documented option-market anomalies and their evidence/decay:
   - variance risk premium
   - overpricing of OTM puts/calls and lottery demand
   - earnings IV crush
   - weekend effect in options
   - expiry pinning
   - dealer gamma effects
   - dispersion / implied correlation premium
   - term-structure and skew predictability
   - momentum/reversal in IV
2. India-specific evidence on Nifty, Bank Nifty, India VIX and SEBI studies on individual F&O trader P&L, including which strategy types lost money.
3. Regulatory and cost regime. Verify each item from SEBI/NSE/BSE primary sources with effective dates:
   - weekly expiry rationalisation and expiry-day changes
   - contract/lot size revisions
   - upfront premium collection
   - expiry-day extra ELM
   - calendar-spread margin changes
   - STT on options (sale and exercise)
   - exchange charges, SEBI fees, stamp duty, GST
   - SPAN + exposure margin methodology
4. Build a **dated regime-break table**. Every backtest result must be shown pre/post relevant breaks.

## Phase 4 — Screening (cheap, uniform test for every candidate)
For each candidate in Phase 2, run the same screen:
1. **Predictability:** out-of-sample, walk-forward, point-in-time only.
   - For continuous targets: R², QLIKE/MSE, Diebold–Mariano vs naive.
   - For probabilistic targets: hit rate, Brier score, log loss and calibration.
2. **Does the market already know it?** Encompassing test against the market's own forecast (IV, implied move, implied probability). If the market's price already encompasses our forecast, the candidate is dead.
3. **Break-even confidence:**
   - Compute the break-even hit rate for the simplest structure that monetises it.
   - Compare the model's calibrated probability to that break-even.
4. **Rupee edge per lot, gross and net.** Use bid/ask fills, slippage, statutory costs by date, lot size by date and liquidity filters.
5. **Tail profile:** worst trade, worst week, P&L skew, and the number of average winning periods wiped out by the worst loss.
6. **Stability:** consistency across years, regimes and regulatory breaks; parameter sensitivity.
7. **Independence:** regress the candidate's P&L on a plain short-ATM-straddle (VRP) factor and on Nifty returns. Report the residual alpha.
8. **Capacity:** liquidity at the strikes/tenors needed relative to intended size.

Output a **single ranked scorecard table**. Columns:
- candidate
- prediction
- predictability metric
- market-encompassed (Y/N)
- break-even vs model probability
- net ₹ edge per lot
- Sharpe
- worst-loss multiple
- residual alpha vs VRP
- stability
- capacity
- data feasibility
- verdict

Keep the dead candidates in the table with the reason they died.

## Phase 5 — Deep dive on the top 3–5 survivors
For each survivor:
1. Refine the model (feature engineering, regime conditioning, probability calibration).
2. Design a fully mechanical rule:
   - entry condition and threshold on (model probability − implied probability)
   - structure choice and strikes/wings
   - tenor
   - exit/adjustment rules (EOD only)
3. Full backtest with execution realism and sizing. Sizing must cap the loss from a 3–4σ move and from the worst historical gap at a chosen % of capital; show results for several caps. Track margin.
4. Robustness:
   - threshold sweeps and stability heatmaps
   - sub-period and regime splits
   - results excluding the best year
   - count of all variants tried, with a deflated Sharpe or equivalent multiple-testing correction
5. Kill-switches: VIX spike, gap threshold, drawdown limit, event blackouts, liquidity deterioration.

## Phase 6 — Combination
1. Correlation matrix of survivor P&Ls, including in stress periods (Mar 2020, Jun 2022, election results days, any major gap days).
2. Test whether combining edges improves risk-adjusted return or just stacks the same short-vol risk.
3. Propose a portfolio allocation and a total risk budget.

---

## Deliverables
1. **Report**
   - 5-line executive verdict: is there a small repeatable edge, from what prediction, how big after costs, and what kills it
   - the Phase 1 calibration findings with charts
   - the full Phase 4 scorecard
   - Phase 5 deep dives and Phase 6 combination
   - explicit sections for **evidence for** and **evidence against**
2. **Code**
   - data extraction
   - IV-surface and risk-neutral-density builder
   - calibration scanner
   - candidate screen harness (one uniform interface per candidate, so new ideas can be plugged in later)
   - backtester and cost/margin model
   - all reproducible from a single entry script
3. **Agent spec** for each strategy that survives:
   - inputs
   - exact conditions
   - structure selection
   - sizing formula
   - kill-switches
   - daily EOD checklist
4. **Open questions** that only paper trading can answer.

## Standards
- Build every number step by step. Show the arithmetic for at least one worked example per candidate:
  - expected move
  - fair premium
  - implied probability
  - break-even hit rate
  - edge in ₹ per lot
- Flag any figure that is estimated, inconsistent, or sourced from memory rather than data or a primary source. Cite web sources with links; prefer SEBI/NSE circulars and peer-reviewed work.
- Be balanced:
  - An edge that exists only gross of costs is a negative finding.
  - So is one that exists only in calm regimes.
  - So is one that disappears after a regulatory change.
  - So is one that is just the VRP repackaged.
  - Report all of these as such.
- If the evidence says no small repeatable edge is available under these constraints, say so clearly. Do not keep expanding scope to find a variant that "works".

---

# Phase 0 — data inventory (2026-10-26)

All queries were read-only against `data/alpha_signal.db`, with data up to 2026-10-23.

## Option and futures prices

| Dataset | Coverage | Notes |
|---|---|---|
| `fno_bhav` (same rows in v3 `derivative_bars`) | 2019-01-01 → 2026-10-23, 1,927 trading days, EOD | close, settle, underlying_price, OI, chg_OI, volume, trades per contract. **No bid/ask, no open/high/low.** |
| NIFTY options / futures | 2019-01 → , 1,922 days, 1.87 M option rows | 60–81 expiries a year (weeklies throughout) |
| BANKNIFTY | 2019-01 → , 1,922 days, 1.18 M rows | weeklies end Nov 2024 (24 expiries in 2025, 15 in 2026) |
| SENSEX / BANKEX | 2024-01-05 → , 689 days | BSE history starts 2024-01 |
| FINNIFTY / MIDCPNIFTY / NIFTYNXT50 | 2021-01 / 2022-01 / 2024-07 → | weeklies discontinued Nov 2024 |
| Stock options (STO) / futures (STF) | **2024-07-15 → only** (corrected 2026-10-26: the first count took the table-wide minimum date), 280 underlyings, 9.5 M option rows | monthly only, about 27 months. Exits are included (survivorship-safe). Stock lot sizes are **not stored**. |
| `options_1m` (Hugging Face, Parquet) | NIFTY 2021-05-27 → 2026-08-04 · SENSEX 2023-08-11 → 2026-07-30, 415 expiry files, 111.6 M bars + 1-min spot | trade OHLC + volume per minute. **Not quotes**; some expiries missing; CC BY-NC research licence |
| `option_live_quotes` (Kite) | 2026-10-13 → , 4 days, 950 rows | **The only bid/ask we have**: NIFTY/SENSEX, strikes near the strangle |

**Point-in-time and quality.** The bhavcopy is published after the close.
- For a traded contract, `close` is the exchange's 15:00–15:30 VWAP (per the option-stops-wings study).
- For an untraded contract (volume = 0), `close` is the **last traded price carried forward**, which can be stale. `settle` is a theoretical price.
- 15–25 % of index option rows are untraded (NIFTY 53 % in 2019).
- So every surface fit must use traded strikes only, and a "decide at EOD" rule cannot fill at the close it reads. The earlier studies used a fill at the 15:20–15:29 one-minute average.
- BSE expiry-day closes had a bug (43,361 rows fixed, check `OPTION_PRICE_IMPOSSIBLE`).

## Derived option series
- `fno_iv_history`: 287 symbols, 2019 → . Per symbol per day: ATM IV, 25-delta skew, term slope and forward, inverted from EOD prices. Useful as a quick check; Phase 1 will rebuild the surface from the raw chain.
- `fno_pcr_history`: 288 symbols, 2019 → . PCR by OI and by volume, max pain and its distance, nearest expiry only.

## Underlyings
- **NIFTY 50**: `nse_index_history` OHLC 2019 → , plus `macro_history.nifty50` (yfinance close) 2015 → .
- **BANKNIFTY**: the NSE OHLC **stops 2024-07-12**. The gap is covered by `macro_history.bank_nifty` (yfinance, 2015 → ) and by the bhavcopy `underlying_price`.
- **SENSEX**: the bhavcopy `underlying_price` from 2024-01, plus a 1-min index file from 2023-08. **No daily OHLC table.**
- **Stocks**: `bars_daily` OHLC with adjustment factors (`corporate_adjustments`). The Kite minute archive covers 1,974 stocks with 1.26 bn bars.

## Volatility, positioning, flags

| Dataset | Coverage | Gap |
|---|---|---|
| India VIX (`vix_history`, `macro_history.india_vix`) | 2015-06-25 → , 2,778 days | close only (no OHLC) |
| Participant OI (`fii_dii_positioning`) | 2022-01-03 → , 1,186 days, Client/DII/FII/Pro | **2019–2021 missing** (on NSE archives) |
| F&O ban (`surveillance_flags` FNO_BAN) | 2026-06-03 → only, 80 days | **history missing** (NSE fo_secban archive) |
| Short selling, bulk deals | present | — |

## Events and calendars
- **Earnings**: `bse_announcements` category Result, 208,501 rows for 2,188 stocks, 2018-01 → . Each row has its dissemination timestamp, which separates in-session from after-hours releases and is look-ahead-safe. `earnings_calendar` is forward-only (2026-04 → ).
- **Corporate actions**: 2010 → . 20,930 dividends, 580 splits, 591 bonuses. `event_calendar` holds buybacks and demergers.
- **Index changes**: `market_events` index_change runs 1996 → **2020-09 only**.
- **Macro event dates** (RBI, Budget, Fed, CPI, election results): **no table**. Earlier studies used hand lists. A dated calendar is needed from the web.
- `market_holidays`: 2026 only. Past holidays are inferred from trading days.

## Global
- USDINR 2015 → , Brent 2015 → , US 10-year 2015 → , gold and silver (yfinance; FRED copies from 2022).
- **Missing**: US VIX, S&P 500 and GIFT/SGX Nifty. US VIX and S&P 500 are an easy fetch via yfinance. GIFT Nifty history is hard to get: SGX Nifty ran before July 2023, GIFT Nifty after.

## Factor library
`factors.FACTORS` holds 107 factors (102 READY). Each has a point-in-time twin via `pit.features_at`, on monthly anchors. That fits direction and event-move tests on stocks; it is too coarse for daily volatility targets.

## Costs and lots
`option_book` holds Zerodha + exchange charges by date and STT 0.0625 % → 0.1 % from 2024-10-01. It also has the NIFTY/SENSEX lot history, with contract-level exceptions, and the 2 % expiry-day ELM. BANKNIFTY and stock lot histories are missing.

## Prior studies (already answered, do not re-test as new)
- **option-premium-feasibility**: exp2 0.05-delta strangle, Sharpe 2.9.
- **option-risk-filters**: no veto rule survives.
- **option-stops-wings**: all stops and wings DROP.
- **Research 0017**: short-horizon strategies.
- **Research 0018** (branch `option-lottery`): all 20 buy-side variants DROP, including PCR, IV<RV, event straddles and the expiry straddle. Its `literature.md` already covers the SEBI trader studies, the Oct 2024 framework, the Jane Street order and costs.

## Testability of the Phase 2 candidates

| Candidate | Status |
|---|---|
| A1 RV vs IV, A2 ΔIV, A3 skew, A4 tails, A5 term, A6 direction, A7 range, A8 overnight/weekend | **testable now** on index chains. Stock chains are monthly and sparse, so they get a coarse test only |
| B1 earnings implied vs realized move | testable **2024-07 → only** (monthly stock chains + BSE result timestamps). Noisy: the event move has to be separated from the remaining days |
| B2 macro events | **needs web dates** |
| B3 F&O ban | **needs web ban history** |
| B4 index rebalances | partial: index changes after 2020-09 need the web. Dividends: testable |
| B5 pre-holiday | testable (holidays inferred from trading days) |
| C1 pinning, C2 dealer gamma, C4 PCR/OI | **testable now**. The dealer-gamma sign is an assumption (customer side unknown) |
| C3 participant OI | testable 2022 → ; 2019–21 needs the web |
| C5 expiry-day scheduled-time | testable from the 1-min archive (NIFTY 2021-05 → , SENSEX 2023-08 → ) |
| D1 NIFTY vs SENSEX | testable 2024-01 → only (~2.8 yrs) |
| D2 NIFTY vs BANKNIFTY | testable |
| D3 dispersion | weak: monthly stock chains, no weights history |
| D4 parity/basis | **cannot be tested as an edge without bid/ask**. Can only flag stale prints |
| D5 surface arbitrage | same problem: EOD close/settle mixes |
| E cross-asset | USDINR/crude testable; **US VIX/S&P need a fetch; GIFT Nifty is mostly untestable** |
| F factor library | testable on stocks at monthly frequency, **2024-07 → only** (~24 months) |
| **All execution realism** | **No historical bid/ask.** Every spread is modelled (max(₹0.05, 1 %) slippage today). That is the main limit on every net figure |
