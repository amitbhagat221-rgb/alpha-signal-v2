# Pre-registration: T-1 tail rules and heavyweight results for the strangle (2026-11-04)

Written before the runs below (Amit 2026-11-04: "yes go ahead"). **Disclosure:** an exploratory z-rule table on the 0.05-delta book, using
the index close, was already seen on 2026-11-03: exit if z < 1.5 cut NIFTY's worst week and failed on SENSEX. Results at 2.5 sigma, on the
implied forward, by window, and everything in Part B have not been seen. Tool: `tools/option_tail_rules_study.py`, read-only.

## Common
- Data: `fno_bhav` settle, every weekly and monthly expiry: NIFTY from 2019, SENSEX from 2024. Costs: `option_book.leg_cost`, 1 % slippage a side.
- Entry at the T-2 settle. **Primary width: 2.5 sigma**, the live setting (`tools.option_sigma_study`'s definition). Secondary: 0.05 delta.
- Rupees: 20 lots at the lot size of each day.
- Windows: NIFTY before 2024 = selection. NIFTY 2024 onward and all of SENSEX = unseen.
- 2026-11-03 has no stored settlement. It is reported separately on the reported close of 23,810.85, marked unverified, and is in no pass test.

## Part A: T-1 tail rules
Decision at the T-1 settle, on the put-call parity forward F, not the index close. σ = ATM straddle / (0.8·F), at the strike nearest F.
z = distance to the nearer short strike in σ. Tail = F·exp(1.65·1.25·σ) − K for the call, mirrored for the put.

Fixed list, acting on the nearer short leg only: **hold** · **exit z<1** · **exit z<1.5** · **exit tail>₹2 L** (tail × units) · **wing z<1** · **wing z<1.5**.
Exit pays the T-1 settle plus costs. A wing buys the listed strike nearest 0.85 % of F beyond the short, at settle plus costs, held to expiry.

Also reported: actual finish in the money against normal, by z bucket, and each move's size in σ.

**Pass, against hold, in BOTH unseen windows:** worst week no worse than half of hold's, and yearly P&L at least 70 % of hold's. If hold's unseen worst
week is smaller than ₹50 K, the test on it reads as "does not make the worst week worse". Choice: on the selection window, the highest yearly P&L among
rules cutting the worst week by half. Pass = **candidate for a shadow forward test only**, never a live change.

## Part B: heavyweight results in the holding period
- Flag a trade when a **top-10 company by market cap at T-2** (`market_caps`) has its reaction session inside (T-2, expiry]. Sources: BSE `Result` filings with
  their timestamp, plus `earnings_calendar`. A filing at or after 15:30, or on a non-session, reacts next session. A calendar date with no time is treated as after hours.
- Placebo: the same flag for ranks 11–20. Sensitivity: top 5.
- Outcomes: move from F to settlement in entry σ, breach rate, mean P&L, worst week. Test: permutation, 10,000 shuffles, one-sided: flagged move is larger.

**Pass, on the 2.5-sigma book:** flagged move larger at p < 0.05 in BOTH NIFTY before 2024 and the unseen windows combined, and the top-10 effect
exceeds the placebo's. Then the action "skip flagged weeks" is reported against the Part A bar. Otherwise the warning stays a warning.

## Known limits, fixed now
- No index weights exist in the DB: full market cap is a proxy. LIC-type names rank above their index weight.
- The candidate list is today's top 80 by market cap, so merged names such as HDFC Ltd are missing.
- Settle is the nearest free proxy for a 15:00 look. Settle prices have no bid/ask.
- One crash-spring (2020) on NIFTY; none on SENSEX. Small counts near the strike. Multiple tests: 5 rules × 2 widths × 2 indices.
