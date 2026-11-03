# T-1 tail rules and heavyweight results for the strangle (2026-11-04)

**Verdict: both DROP under the [pre-registered](option-tail-rules-preregistration-2026-11.md) bar. No live change.**
- **Tail rules:** no rule passes on both indices. At 2.5 sigma they rarely fire and make the worst week worse. At 0.05 delta, exit z<1.5 and exit tail>₹2 L pass on NIFTY and fail on SENSEX.
- **Heavyweight results:** weeks when a top-10 company reports moved no more, in the σ the options priced, than other weeks.
- **What did cut the worst week:** the strike width. 2.5 sigma had a far smaller worst week than 0.05 delta, for 15 to 47 % less yearly income. These windows contain no gap through a 2.5-sigma strike, so this is not a bound on the loss.

Tool: `tools/option_tail_rules_study.py`, read-only. Settle prices, 1 % slippage, 20 lots at the lot size of each day. Rupees below use those lots, so older weeks are not at today's size.

## Part A, 2.5 sigma (live width)
| Window | Rule | Fired | Yearly | Worst week |
|---|---|---|---|---|
| NIFTY before 2024, 225 weeks | hold | 0 | ₹4.28 L | +₹2,452 |
| | exit z<1.5 | 7 | ₹3.80 L | −₹21,169 |
| | wing z<1.5 | 7 | ₹3.84 L | +₹78 |
| NIFTY 2024 on, 139 weeks | hold | 0 | ₹4.94 L | −₹29,622 |
| | exit z<1.5 | 4 | ₹4.73 L | −₹43,169 |
| | wing z<1.5 | 4 | ₹4.85 L | −₹42,017 |
| SENSEX, 131 weeks | hold | 0 | ₹3.31 L | +₹1,398 |
| | exit z<1.5 | 8 | ₹1.22 L | −₹2.86 L |
| | wing z<1.5 | 8 | ₹2.09 L | −₹2.28 L |

Short strikes were breached in 0.5 % of NIFTY weeks and 0 of 131 SENSEX weeks.

## Part A, 0.05 delta
| Window | Rule | Fired | Yearly | Worst week |
|---|---|---|---|---|
| NIFTY before 2024 | hold | 0 | ₹5.02 L | −₹1.51 L |
| | exit z<1.5 | 42 | ₹4.46 L | −₹42,964 |
| NIFTY 2024 on | hold | 0 | ₹6.76 L | −₹2.01 L |
| | exit z<1.5 | 25 | ₹6.22 L | −₹41,171 |
| | exit tail>₹2 L | 16 | ₹6.48 L | −₹41,171 |
| SENSEX | hold | 0 | ₹6.24 L | −₹52,076 |
| | exit z<1.5 | 30 | −₹0.21 L | −₹4.15 L |
| | exit tail>₹2 L | 16 | ₹0.35 L | −₹4.15 L |

Why SENSEX fails: the rule buys back at a high T-1 price in weeks the index then reverses. 2.3 years of SENSEX is short, but a rule the two indices disagree on is not adopted.

## Fat tails: not supported at these distances
T-1 to settlement in the market's σ, against normal: NIFTY over 1.65σ 7.4 % against 9.9 %, over 2.5σ 1.1 % against 1.2 %, over 3σ 0.5 % against 0.3 %.
SENSEX 11.5 %, 1.5 %, 0.0 %. One bucket runs hot: NIFTY 0.05 delta at z 0.5 to 1 finished in the money 31 % against 20 %, on 16 weeks.

## 2026-11-03, reported close 23,810.85, unverified, in no pass test
Forward at the T-1 settle 23,329, σ 0.81 %, a 2.51σ day. At 20 lots: 0.05 delta 22400/23500, z 0.89, hold −₹3.86 L, exit −₹9,728. 2.5 sigma 22300/23750, z 2.19, hold −₹69,228, exit +₹5,763.
So exit z<1 would have fired at 0.05 delta and not at 2.5 sigma. The index close was about 110 points above the forward options implied on 11-02; the cause is not established.

## Part B, heavyweight results, 2.5 sigma
| Window | Group | Flagged | Move in σ, flagged vs other | p | Mean ₹, flagged vs other |
|---|---|---|---|---|---|
| NIFTY before 2024 | top 10 | 50 of 225 | 0.78 vs 0.71 | 0.233 | 7,335 vs 9,913 |
| | placebo 11–20 | 68 | 0.74 vs 0.72 | 0.430 | 7,153 vs 10,287 |
| Unseen combined | top 10 | 53 of 270 | 0.66 vs 0.77 | 0.915 | 9,522 vs 8,347 |
| | placebo 11–20 | 53 | 0.68 vs 0.76 | 0.844 | 7,917 vs 8,739 |

The top-10 effect is no larger than the placebo's. Move is in entry σ, so this says the options priced these weeks, not that the index moved little. Reliance's 2026-11-02 move was inside the hold but is one week.

## Limits
Market cap, not index weight. Candidates are today's top 80, so HDFC Ltd and other merged names are missing. Settle stands in for a 15:00 look. SENSEX has no crash window, and NIFTY's crash is one spring. These trades enter once a week, so a gap landing in the hold has rarely been sampled: the earlier every-day model's worst day was about −40 % of margin at 2.5 sigma. Multiple tests were run. The rule was chosen after an exploratory table on 0.05 delta, disclosed in the pre-registration.
