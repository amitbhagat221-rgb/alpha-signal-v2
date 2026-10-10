# Plan 0023 — Dynamic option setups: does reacting to the market beat the static rule?

**Status:** DONE 2026-10-10, negative: **all six hypotheses FAIL**; no combination test (no survivors); [ADR 0068](../decisions/0068-no-dynamic-filters-on-option-strangle.md) proposed. The static plan-0022 rule stands. Pre-registration below was written before any result was computed.
**Asked for (Amit, 2026-10-10):** "we dont want to be static but a little dynamic and reactive to market moves and decide on setup as per the macros, technicals etc."
**Baseline:** the static rule of plan 0022 (0.05-delta strangle, sold 2 sessions before the weekly expiry, held to expiry). It keeps running on paper unchanged, so any winner here is also compared forward.

## 1. Method

1. **Setup table.** For every entry day (2 sessions before the front weekly expiry) the engine (`option_book.py`) prices each leg at call/put delta 0.03, 0.05 and 0.07, held to expiry, after costs. A setup is a sum of legs × size. A policy picks one setup per week from what the table already holds, so every policy is judged on the same trades.
2. **Market reading.** Computed with only what was known at the entry close, by one function used both in the backtest and live (`option_state.py`). US-hours and next-morning data (USD/INR, Brent from yfinance) use the previous day's value.
3. **Thresholds.** Percentiles come from an expanding window of data before that date: no look-ahead, no tuning.
4. **Windows.**
   - **TRAIN:** NIFTY entries 2019-02-11 → 2024-11-19.
   - **TEST:** NIFTY entries 2024-11-20 → latest (the one-weekly-expiry regime), run once.
   - **Second check:** SENSEX 2024-01 → latest.
5. **Unit.** Returns are a % of the standard strangle's margin (12% of the forward): the capital the static rule uses.

## 2. Setups

| Setup | Call delta | Put delta | Size |
|---|---|---|---|
| STD (baseline) | 0.05 | 0.05 | 1 |
| SKIP | — | — | 0 |
| HALF | 0.05 | 0.05 | 0.5 |
| PUT_FAR (put further out, call closer) | 0.07 | 0.03 | 1 |
| CALL_FAR (call further out, put closer) | 0.03 | 0.07 | 1 |

## 3. Hypotheses (pre-registered 2026-10-10)

| # | Idea | Reading at the entry close | Rule |
|---|---|---|---|
| H1 | Premium rich or cheap | VRP = NIFTY ATM IV (≈30-day, `fno_iv_history.atm_iv`) − 20-day realised vol (NIFTY closes, annualised) | VRP ≤ 0 → SKIP, else STD |
| H2 | Trend tilt | 5-session NIFTY return, expanding percentile from 2015 | ≤ 20th → PUT_FAR (after a fall, more room below); ≥ 80th → CALL_FAR; else STD |
| H3 | Skew | `iv_skew_25d` (put IV − call IV), expanding percentile (≥ 120 days of history, else STD) | ≥ 80th (puts rich) → CALL_FAR (sell the rich put closer); ≤ 20th → PUT_FAR; else STD |
| H4 | Stress | `iv_term_structure` (near ATM IV − next expiry ATM IV) | > 0 (inverted) → SKIP, else STD |
| H5 | Crowded positioning | NIFTY put/call OI ratio (`fno_pcr_history.pcr_oi`), expanding percentile (≥ 120 days) | below 10th or above 90th → HALF, else STD |
| H6 | Macro shock | 5-day % change of USD/INR and of Brent (previous day), expanding percentile of the absolute change from 2015 | either above 90th → HALF, else STD |

## 4. Pass bar (fixed now)

For each hypothesis, the weekly difference = policy return − STD return. A hypothesis **passes** only if all of these hold:
- **TEST:** t of the mean difference ≥ **2.4** (one-sided 5% after a Bonferroni haircut for 6 hypotheses).
- **TRAIN:** mean difference > 0.
- **TEST:** the worst trade and the max drawdown are no worse than STD's.
- **SENSEX:** mean difference > 0 (same sign).
- **Shuffle test:** the TEST difference is beaten in < 5% of 1,000 shuffles of the reading across TEST weeks.

Also reported, not gating: results by bucket of the reading (they should move in the expected direction), and by year.

**Combination:** only survivors, with the precedence SKIP > HALF > tilt. It is judged once on TEST against the same bar, as a 7th test.

## 5. Not testable here

- **Reacting during the day** (stops, adjustments): no historical intraday prices. Kite minute data collected forward would make it testable later.
- **The agent's news judgement:** no point-in-time news archive. It is logged forward from plan 0022 Phase 2 and earns a role only on its forward record.

## Implementation notes
- 2026-10-10 inputs:
  - **IV rollup fix.** `sources/fno_iv.py` fell back to nothing when the ~30-day expiry was a thin weekly: 495 NIFTY days were missing, mostly 2019–21. It now takes the next-closest expiry that inverts; existing rows are unchanged. NIFTY IV now covers all 1,913 days; SENSEX lacks 25 thin early-2024 days.
  - **SENSEX PCR** filled 2024-07 → (553 days).
- 2026-10-10 result (`python -m tools.option_dynamic_study`). STD check: NIFTY 397 entries, 24.3%/yr of margin, Sharpe 2.92, matching the study.

| Rule | TRAIN diff/trade | TEST diff/trade (t) | SENSEX diff | Verdict |
|---|---|---|---|---|
| H1 premium (skip when IV ≤ realised) | −0.10% | −0.16% (−5.9) | −0.10% | FAIL, worse every year |
| H2 trend tilt | +0.03% | −0.02% (−0.8) | −0.02% | FAIL (helped in 2020 only) |
| H3 skew tilt | −0.02% | +0.00% (+0.7) | +0.02% | FAIL (no effect) |
| H4 stress (skip when inverted) | −0.22% | −0.19% (−5.0) | −0.09% | FAIL, worse every year |
| H5 positioning (half when crowded) | −0.06% | −0.04% (−4.4) | −0.01% | FAIL |
| H6 macro shock (half) | −0.07% | −0.07% (−4.0) | −0.04% | FAIL |

**Why: the static rule is already reactive, and the "scary" states pay the most.**
- A 0.05-delta strike moves further out when implied volatility rises, so stress is priced into the strike automatically.
- The static rule's return per trade by quintile (2019 →) is highest in the top quintile of: premium over realised (0.73%), skew (0.73%), inverted term structure (0.70%), rupee moves (0.71%) and oil moves (0.73%). After the sharpest 5-day falls it is 0.89%.
- Rules that skip or halve in those states give up the best weeks without removing the tail (worst trade unchanged in TEST).
- "Size up when premium is rich" is the opposite idea. It is NOT tested here; it would need its own pre-registration and a forward test, since it adds tail risk.
