# Research-Backed Changes to Alpha Signal Pipeline
## For Claude Code — Apply These Changes to Existing Scripts

**Context:** Deep research completed across 7 domains covering Indian equity factor investing. These are specific, evidence-backed changes to scripts already built in Phase A and Phase B. Read CLAUDE.md first for full project context.

**Priority:** Apply in order listed. Each change is independent — commit after each section.

---

## CHANGE 1: Script 27 — Piotroski F-Score Modifications

**File:** `~/alpha-signal/scripts/27_piotroski.py`

### 1A. Exclude financials entirely

Add a sector filter at the top of the scoring function. Banks, NBFCs, and insurance companies have balance sheet structures that make leverage and liquidity components unreliable.

```
EXCLUDED_SECTORS = ['Banks', 'Finance', 'Insurance', 'Financial Services', 
                     'NBFC', 'Banking', 'Financial Institution']
```

Before computing F-Score for any stock, check if its sector (from `universe.csv`) is in `EXCLUDED_SECTORS`. If yes, set F-Score to `NaN` (not zero — zero implies bad fundamentals, NaN implies not-applicable). Log how many stocks are excluded.

**Evidence:** Walkshäusl (2020, Journal of Asset Management) — academic consensus across all F-Score studies excludes financials.

### 1B. Add sector-relative mode for capital-intensive sectors

For sectors like Infrastructure, Real Estate, Metals, Utilities, Power — the ΔLEVER and ΔLIQUID components are structurally noisy. Add a flag `--sector-relative` that:
- Computes raw F-Score for all non-financial stocks
- For capital-intensive sectors (define list: `CAPITAL_INTENSIVE = ['Infrastructure', 'Real Estate', 'Metals', 'Power', 'Utilities', 'Construction']`), compute percentile rank of F-Score within that sector instead of using the absolute 0-9 score
- Store both `f_score_raw` (0-9) and `f_score_pctile` (0-100) in output

**Evidence:** Piotroski (2000) designed the score for broad market; sector-relative ranking handles structural differences.

### 1C. Update thresholds in integration

In `08_integrate_sentiment.py`, wherever F-Score feeds in:
- Boost signal: F-Score ≥ 7 (not ≥ 6)
- Penalty signal: F-Score ≤ 2 (not ≤ 3)
- For excluded financial stocks: no F-Score adjustment (skip, don't penalize)

**Evidence:** Walkshäusl (2020) — ≥7 and ≤2 are the validated long/short thresholds with 10% annual spread in emerging markets.

---

## CHANGE 2: Script 28 — Accruals Quality Fixes

**File:** `~/alpha-signal/scripts/28_accruals.py`

### 2A. Switch to cash flow approach with average total assets

The formula should be:

```python
accruals = (net_income - operating_cash_flow) / average_total_assets
# where average_total_assets = (total_assets_current + total_assets_prior) / 2
```

If currently using beginning-of-period total assets or just current total assets as denominator, change to average. This is the Hribar & Collins (2002) recommendation — cleaner than the balance sheet approach, especially post-IndAS.

**Evidence:** Hribar & Collins (2002, The Accounting Review); Sloan (1996) original used balance sheet approach but cash flow approach is now standard.

### 2B. Use as negative screen only — not a positive signal

The accruals anomaly is structurally weak in India. Pincus, Rajgopal & Venkatachalam (2007, The Accounting Review) specifically flagged India as an exception where the anomaly coefficient was not statistically significant.

Change the integration logic in `08_integrate_sentiment.py`:
- **KEEP** the penalty for high accruals (top decile) — this still works as a manipulation/quality flag
- **REMOVE or halve** the boost for low accruals (bottom decile) — the positive side is not well-supported in India
- Specifically: if current code gives ±4 points for accruals, change to -4 / +2 (asymmetric)

**Evidence:** Bansal & Ali (2021, IIM Kashipur) — asymmetric pricing in Indian markets; negative side stronger than positive side.

### 2C. Exclude banks/NBFCs from accruals calculation

Same exclusion list as F-Score. Bank accruals are driven by RBI provisioning norms (regulatory), not operating discretion. Computing accruals for banks produces meaningless numbers.

```python
# Skip accruals for financial sector stocks
if sector in FINANCIAL_SECTORS:
    accruals_score = np.nan
```

### 2D. Add overlap check with Beneish M-Score

Log a warning when a stock is flagged by BOTH accruals (top decile) AND Beneish M-Score > -1.78 (from script 17). These signals share the TATA component — we may be double-counting. For now, log the overlap count; in Phase C we'll check correlation empirically.

Add to the output CSV: a column `beneish_overlap` (True/False) by cross-referencing `data/forensic/forensic_scores.csv`.

---

## CHANGE 3: Script 28 — Earnings Persistence Fixes

**File:** `~/alpha-signal/scripts/28_accruals.py` (if persistence is in the same script) or wherever earnings persistence is computed.

### 3A. Switch to standalone earnings

This is the single most impactful change from the research. Balachandran et al. (2023, Columbia/ISB) found the Indian market weights standalone parent earnings (coefficient 1.55) far more than subsidiary earnings (0.46). Parent earnings persistence is 68.3% vs 53.9% for subsidiaries.

Check which earnings field the persistence calculation uses from `quarterly_income.csv`. If it's using consolidated figures (which Tickertape may default to), switch to standalone.

**How to check:** Look at `22_data_harvester.py` — what does `get_income_data(sid)` return? If Tickertape returns consolidated by default, we may need to add a parameter or filter. If standalone isn't available separately, document this as a data gap to address.

**For now:** Add a TODO comment flagging this. If data is consolidated-only, the persistence signal is still directionally correct but weaker than it could be.

### 3B. Down-weight Q4 earnings surprises

Indian companies cluster write-offs in Q4 (January-March). In the persistence/surprise calculation, add:

```python
# Q4 (Jan-Mar quarter) results are noisier due to kitchen-sink write-offs
# Down-weight Q4 surprises by 0.6x
quarter = determine_quarter(result_date)  # 1=Apr-Jun, 2=Jul-Sep, 3=Oct-Dec, 4=Jan-Mar
q4_weight = 0.6 if quarter == 4 else 1.0
surprise = surprise * q4_weight
```

If we're only counting consecutive quarters of growth (binary yes/no), this doesn't apply directly. In that case, add: if Q4 shows negative growth but Q1-Q3 were positive, check whether Q4 had exceptional items > 10% of PBT. If yes, treat Q4 as "neutral" (neither breaking nor continuing the streak).

**Evidence:** IndAS 1 prohibits "extraordinary items" label but companies still dump exceptional charges in Q4. Practitioner consensus on down-weighting.

### 3C. Add loss-year base effect filter

A company recovering from a loss year shows consecutive "growth" that's really mean reversion. Add:

```python
# If any quarter in the lookback had EPS < 0.50 (or price < 10), 
# cap persistence score at 0.5 (half credit)
if any(eps < 0.50 for eps in lookback_eps) or any(price < 10 for price in lookback_prices):
    persistence_score *= 0.5
```

**Evidence:** Harshita, Singh & Yadav (2018) trimming approach for PEAD; Kumar et al. (2023) on mean reversion in Indian markets.

---

## CHANGE 4: Script 03 — Momentum Signal Upgrade

**File:** `~/alpha-signal/scripts/03_screener.py`

### 4A. Switch to risk-adjusted composite momentum

Replace raw 12-1 month return with the NSE Nifty200 Momentum 30 formula:

```python
# Current (likely): momentum = 12M_return (skipping last month)
# New: risk-adjusted composite
mom_6m = returns_6m / volatility_6m  # 6-month return / 6-month daily return std dev
mom_12m = returns_12m / volatility_12m  # 12-month return / 12-month daily return std dev
momentum_score = 0.5 * mom_6m + 0.5 * mom_12m
```

Volatility should be computed from daily returns over the same period. This naturally down-weights high-volatility stocks that happen to have high returns (speculative momentum) vs steady compounders.

**Evidence:** NSE's own methodology for Nifty200 Momentum 30 index; Chui et al. (2023) — raw momentum fails for illiquid stocks; risk-adjustment fixes this.

### 4B. Add anti-speculation filter

Before computing momentum, exclude stocks where daily turnover ratio (volume / shares outstanding) is > 3 standard deviations above the sector median. These are typically speculative micro-caps where "momentum" is noise.

```python
# Compute sector median turnover ratio
sector_median_turnover = df.groupby('sector')['turnover_ratio'].transform('median')
sector_std_turnover = df.groupby('sector')['turnover_ratio'].transform('std')
is_speculative = df['turnover_ratio'] > (sector_median_turnover + 3 * sector_std_turnover)
# Set momentum score to NaN for speculative stocks
df.loc[is_speculative, 'momentum_score'] = np.nan
```

**Evidence:** BacktestIndia 18.5-year backtest — this filter alone added +4% CAGR and reduced max drawdown by 8 percentage points.

### 4C. Add VIX-based crash protection flag

This doesn't change the momentum calculation but adds a regime column that `08_integrate_sentiment.py` can use:

```python
# Fetch India VIX (^INDIAVIX on yfinance or from NSE bhavcopy)
# If not available in current data, add to daily pipeline
vix = get_india_vix()  # current value
if vix > 35:
    momentum_regime = 'EXIT'      # zero out momentum weight
elif vix > 25:
    momentum_regime = 'CAUTION'   # halve momentum weight  
else:
    momentum_regime = 'NORMAL'    # full momentum weight
```

In `08_integrate_sentiment.py`, when applying momentum boost/penalty:
```python
if momentum_regime == 'EXIT':
    momentum_adjustment = 0
elif momentum_regime == 'CAUTION':
    momentum_adjustment = base_momentum_adjustment * 0.5
else:
    momentum_adjustment = base_momentum_adjustment
```

**Evidence:** Daniel & Moskowitz (2016, JFE); Singh, Walia, Panda & Gupta (2022, FIIB Business Review) — risk-managed momentum doubles Sharpe ratio on BSE stocks.

---

## CHANGE 5: Script 29 — Consensus Signal Refinements

**File:** `~/alpha-signal/scripts/29_consensus_signal.py`

### 5A. Change target price from absolute upside to revision-based

Current implementation likely uses `pt_upside` (consensus target vs CMP) as a bullish signal. Research shows this reflects analyst optimism bias, not genuine undervaluation (only 63% hit rate in India, decreasing with increasing optimism).

Change:
- **Remove or heavily down-weight** absolute `pt_upside` as a positive signal
- **Add** `pt_revision` = change in consensus target price from previous harvest vs current harvest
- If consensus.csv has historical snapshots (from snapshot archiver), compute: `(current_target - prior_target) / prior_target`
- If only current snapshot exists, flag this as needing the archiver data and keep absolute upside at reduced weight (10% instead of current 40%)

New composite weights:
```python
# Old: pt_upside (40%), buy_pct (30%), eps_growth_pct (20%), rev_growth_pct (10%)
# New: pt_revision (30%), buy_pct (30%), eps_growth_pct (25%), rev_growth_pct (15%)
# pt_upside removed or kept at 0% until we can validate independently
```

**Evidence:** Indian analyst study (2024, Cogent Economics & Finance) — 63% target price achievement; ScienceDirect (2021) — contrarian target price strategies work better.

### 5B. Add minimum analyst threshold

Currently 2,398/2,438 stocks get a consensus score. Many of these have only 1-2 analysts. Add confidence weighting:

```python
n_analysts = row.get('analyst_count', 1)
if n_analysts >= 5:
    confidence = 1.0       # full weight
elif n_analysts >= 3:
    confidence = 0.6       # reduced
elif n_analysts >= 1:
    confidence = 0.3       # directional only
else:
    confidence = 0.0       # no signal

consensus_score = raw_consensus_score * confidence
```

If `analyst_count` isn't in the current data, check whether `__NEXT_DATA__` JSON from Tickertape contains this. If not, use `buy_pct` as a proxy — if buy_pct is based on < 3 analysts, coverage is thin.

**Evidence:** Global practice (Linnainmaa & Zhang); consensus of 2 analysts is unreliable.

---

## CHANGE 6: Script 30 — Promoter Signal Enhancements

**File:** `~/alpha-signal/scripts/30_promoter_signal.py`

### 6A. Make buying vs selling asymmetric

Current implementation likely treats buying and selling symmetrically. Research strongly shows promoter buying is informative but selling is not (promoters sell for personal reasons — tax, diversification, family).

```python
# Asymmetric treatment
if promoter_change > 0:  # buying
    direction_score = 1.0   # strong positive
elif promoter_change < -2.0:  # significant selling (>2% drop)
    direction_score = -0.3  # mild negative only
else:
    direction_score = 0.0   # noise
```

**Evidence:** Brochet, Lee & Srinivasan (2017, NYU Stern) — promoter purchases significantly predict returns (β=0.073, p<0.001); non-promoter and sales coefficients are insignificant.

### 6B. Add promoter pledge penalty

This is a new sub-signal. If `shareholding.csv` contains pledge data (check if Tickertape's `get_share_holding_pattern` returns pledge percentage):

```python
pledge_pct = row.get('promoter_pledge_pct', 0)
if pledge_pct > 50:
    pledge_score = -1.0    # HARD PENALTY — exclude from top picks
elif pledge_pct > 20:
    pledge_score = -0.5    # significant penalty
elif pledge_pct > 10:
    pledge_score = -0.2    # minor caution
else:
    pledge_score = 0.0     # clean
```

If pledge data is not available in current harvested data, add a TODO to harvest it. SEBI mandates pledge disclosure — it should be in BSE/NSE filings. Check Tickertape's shareholding data for pledge fields.

**Evidence:** Multiple Indian market blow-ups (DHFL, Satyam, Zee); SEBI mandates real-time pledge disclosure since 2019.

### 6C. Add promoter holding level context

Very high promoter holding (>75%) can signal poor governance and low float, not just conviction:

```python
promoter_holding = row.get('promoter_pct', 50)
if promoter_holding > 75:
    # Too concentrated — low float, governance risk
    holding_modifier = 0.7  # dampen the signal
elif 40 <= promoter_holding <= 65:
    # Sweet spot — good skin in game, adequate float
    holding_modifier = 1.0
elif promoter_holding < 25:
    # Very low — professional management or dispersed
    holding_modifier = 0.8  # slightly dampened
else:
    holding_modifier = 0.9

# Apply to final promoter score
promoter_score = raw_promoter_score * holding_modifier
```

**Evidence:** Selarka (2006); Rastogi et al. (2021) — nonlinear inverted-U relationship between promoter ownership and performance in India.

---

## CHANGE 7: Script 08 — Integration Layer Updates

**File:** `~/alpha-signal/scripts/08_integrate_sentiment.py`

### 7A. Add liquidity tier system

All signals should be weighted based on stock liquidity. Momentum especially is unreliable for illiquid stocks.

Add at the beginning of integration:

```python
# Compute liquidity tier from price data
# Need average daily turnover value (ADTV) — price * volume, 20-day average
if adtv >= 10_00_00_000:   # >= 10 crore
    liquidity_tier = 'HIGH'
    momentum_weight = 1.0
elif adtv >= 1_00_00_000:  # >= 1 crore  
    liquidity_tier = 'MED'
    momentum_weight = 0.7
else:
    liquidity_tier = 'LOW'
    momentum_weight = 0.3
```

Apply `momentum_weight` as a multiplier to the momentum adjustment only. Other signals (F-Score, promoter, forensic) are not liquidity-dependent.

Also add `liquidity_tier` as a column in the output CSV — useful for Phase C backtesting.

**Evidence:** Chui, Ranganathan, Rohit & Veeraraghavan (2023, Pacific-Basin Finance Journal) — momentum works in liquid Indian stocks but reverses in illiquid ones. Amihud illiquidity for India is 3.25× that of the US.

### 7B. Add sector concentration cap

Add a post-integration check: no more than 25% of top-20 picks should come from a single sector. If BFSI dominates (common in Indian markets), cap at 5 stocks per sector in the top 20.

```python
# After ranking stocks by final_score
top_picks = ranked_df.head(20)
sector_counts = top_picks['sector'].value_counts()
while sector_counts.max() > 5:
    # Remove lowest-ranked stock from the over-represented sector
    over_sector = sector_counts.idxmax()
    drop_idx = top_picks[top_picks['sector'] == over_sector].tail(1).index
    top_picks = top_picks.drop(drop_idx)
    # Add next best stock from a different sector
    next_candidate = ranked_df[~ranked_df.index.isin(top_picks.index) & 
                               (ranked_df['sector'] != over_sector)].head(1)
    top_picks = pd.concat([top_picks, next_candidate])
    sector_counts = top_picks['sector'].value_counts()
```

**Evidence:** Portfolio construction best practice; Indian market is heavily weighted toward financials.

---

## CHANGE 8: New Script — Business Group Tagger

**File:** `~/alpha-signal/scripts/31_group_tagger.py` (NEW)

Create a simple CSV mapping stocks to their business group (Tata, Adani, Reliance, Birla, Mahindra, Bajaj, Vedanta, Godrej, L&T, etc.). This enables group-level risk monitoring.

```python
# data/reference/business_groups.csv
# Format: sid, group_name
# Example:
# TCS, Tata
# TAMO, Tata  
# TITN, Tata
# APSE, Adani
# ADEL, Adani
# RELI, Reliance
# ...
```

The script should:
1. Load the group mapping
2. For each group, compute: average promoter pledge across group stocks, count of forensic flags, aggregate FII/DII sentiment
3. If any stock in a group has M-Score > -1.78 OR pledge > 50%, flag ALL stocks in that group with a `group_risk` column
4. Output: `data/reference/group_risk_scores.csv`

This feeds into `08_integrate_sentiment.py` as an additional penalty layer.

**Evidence:** Hindenburg-Adani episode — contagion across all group stocks simultaneously. Business group dynamics are India-unique and a significant risk factor.

**Implementation note:** The initial group mapping (50-100 major groups) can be hardcoded as a CSV file. It's a one-time manual effort — Claude Code can help generate the initial list from universe.csv by clustering stocks with similar names/promoters.

---

## CHANGE 9: CLAUDE.md Updates

After applying all changes, update `~/alpha-signal/CLAUDE.md` with:

1. **New section: Research-Backed Parameters** — document the evidence basis for each parameter choice (F-Score thresholds, accruals asymmetry, momentum VIX cutoffs, etc.)

2. **Updated signal descriptions** reflecting the changes (asymmetric promoter scoring, risk-adjusted momentum, etc.)

3. **New known constraints:**
   - Accruals anomaly is structurally weak in India — use as negative screen only
   - Earnings persistence should use standalone earnings (flag if data is consolidated)
   - Momentum needs liquidity tier gating
   - Target price upside is unreliable — switch to revision-based

4. **Phase C prep notes:**
   - Backtester must use 60-day lag for quarterly data (SEBI reporting deadlines)
   - Survivorship bias in universe.csv is ~4.4% annually — bhavcopy backfill is critical
   - Transaction costs: 15-25 bps large-cap, 25-50 bps mid-cap, 50-200+ bps small-cap
   - Fama-MacBeth: rank-transform all factors, 6 Newey-West lags, ₹500 crore minimum market cap filter
   - IC benchmarks: 0.05-0.10 = good single factor; ICIR > 0.4 = reliable
   - t-stat threshold: ≥ 2.5 for known factors in new market (not 3.0 since these aren't novel discoveries)

5. **New future items:**
   - India VIX daily fetch (for momentum crash protection)
   - Promoter pledge data harvest
   - Standalone vs consolidated earnings flag per stock
   - Business group risk aggregation

---

## VERIFICATION CHECKLIST

After applying all changes, run the full pipeline once and verify:

- [ ] F-Score: financial sector stocks show NaN, not 0
- [ ] F-Score: ≥7 threshold for boost, ≤2 for penalty
- [ ] Accruals: using average total assets as denominator
- [ ] Accruals: penalty is stronger than boost (asymmetric)
- [ ] Accruals: banks/NBFCs excluded
- [ ] Momentum: risk-adjusted (return/vol) not raw return
- [ ] Momentum: VIX regime flag present in output
- [ ] Consensus: target price upside de-weighted or replaced with revision
- [ ] Consensus: analyst count confidence weighting applied
- [ ] Promoter: buying/selling asymmetric (1.0 / -0.3)
- [ ] Promoter: holding level modifier applied
- [ ] Integration: liquidity tier column present
- [ ] Integration: sector cap enforced in top picks
- [ ] Pipeline completes without errors
- [ ] Email still sends correctly
- [ ] Commit and push to GitHub

---

*Generated from deep research — April 2026*
*Evidence sources: 40+ academic papers, NSE/BSE studies, practitioner backtests*
*See full research report for complete citations and parameter justification*
