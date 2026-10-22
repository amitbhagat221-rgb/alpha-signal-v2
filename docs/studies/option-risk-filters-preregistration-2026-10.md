# Pre-registration: can any market factor avoid or shrink the option book's worst weeks? (2026-10-22)

Written before the search (Amit 2026-10-22: "I refuse to believe there was no factor that could have predicted the worst drawdown; we have a rich factor library"). Only a quick table of results by VIX band was seen beforehand: the 2 worst trades were at VIX > 30, but VIX > 30 weeks were also the most profitable (15 trades, +27.8 % total).

## Rule under test
The plan 0022 rule: NIFTY weekly short strangle, 0.05 delta, 2 sessions before expiry, held to expiry. Per-trade results come from `tools/option_premium_backtest --start 2019-02-01` (hold exp2, delta 0.05, strangle; 399 trades 2019-02 → 2026-10, real chain, end-of-day). SENSEX (2024 →) is a second out-of-sample check only. The 2015–2019 stress model (NIFTY + VIX history) is a third check for rules that use only NIFTY and VIX.

## Candidate predictors (each known at the entry close; point in time, no look-ahead)
- **Volatility:** India VIX level, its 5-day change, its 1-year percentile; NIFTY realized vol over 5 and 20 days; implied minus realized vol; ATM IV and 25-delta skew (`fno_iv`).
- **Trend / stretch:** NIFTY return over 1, 5 and 20 days; distance from the 20- and 50-day averages; drawdown from the 52-week high.
- **Positioning / flows:** put-call ratio (`fno_pcr_history`); FII index futures and options net positioning (`fii_dii_positioning`); FII cash flow over 5 days.
- **Global / overnight:** US VIX, S&P 500 1- and 5-day return, USDINR, Brent and US 10-year 5-day change (`macro_history`).
- **Calendar:** a scheduled event inside the holding window (RBI policy, Union Budget, election results, FOMC); a holiday inside the window.
- **Premium richness:** credit as % of margin; strike distance in VIX × √T units.
- **The house regime model** (`scoring/regime.py`) output at entry.

Any series without point-in-time history over 2019–2026 is listed as untested, not dropped silently.

## Actions tested per predictor
1. **Skip** the trade when the predictor is beyond a threshold.
2. **Half size** beyond the threshold.
3. **Risk-scaled size** (no threshold; fixed now): lots ∝ 1 / VIX, and separately lots ∝ 1 / 20-day realized vol, normalised so the average margin used equals the base book.

## Method
- **Choose on 2019-02 → 2022-12, test on 2023-01 → 2026-10:** thresholds for actions 1–2 are picked on the first window only, from the predictor's 70th / 80th / 90th / 95th percentile in that window, whichever gives the best ratio of P&L to max drawdown there. The pick is then frozen for the test window.
- **One combined model:** a walk-forward logistic model on all predictors (refit yearly, expanding window). It predicts a bad trade (bottom 5 % of returns in the training data) and halves size when the predicted probability is in its top decile.
- **Multiple testing:** about 30 predictors × 2 threshold actions. Report the count tried and apply the HLZ / Bonferroni haircut (`tools/multiple_testing.py`) to any "pass".
- **Power warning, stated up front:** only 4 trades lost more than 2 % of margin in 2019–2026, so no filter can be proven on tail events alone. Judge on whole-book P&L and drawdown.

## Reported per rule, on both windows
Trades kept, total and annual P&L (% of margin and ₹ at ₹35 L), worst trade, max drawdown, P&L ÷ max drawdown, which of the 4 worst trades it avoided or shrank, and P&L given up.

## Decision rule
A rule is **adopted** (proposed for plan 0022 / 0029) only if, on the 2023–26 test window **and** on SENSEX:
1. max drawdown falls by at least 30 % versus the base book at equal average margin, and
2. P&L ÷ max drawdown improves, and
3. at least 85 % of the base book's P&L is kept.

It must also survive the multiple-testing haircut. Risk-scaled sizing (action 3) has no threshold to fit, so it needs only conditions 1–3. If nothing passes, the answer is stated plainly with the near misses.
