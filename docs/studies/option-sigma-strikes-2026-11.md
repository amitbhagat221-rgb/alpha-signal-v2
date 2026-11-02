# Selling the NIFTY weekly strangle at 3 sigma instead of 2 (2026-11-02)

**Question (Amit):** "we did a 2 sigma study, can you do a 3 sigma study on the option strategy and tell me what's the outcome."
**Answer:** at 3 sigma the strangle has had **no losing week on the real chain (100 of 100 since Nov 2024)**, but it earns **about half the premium** (₹407 a lot a week against ₹953 at 2 sigma) and costs eat 12 % of it. In the 2015–2026 model it **does not remove the crash day**: the worst day still costs 33 % of margin (45 % at 2 sigma), which is four years of income at either width. 3 sigma trades a smaller, rarer tail for a smaller income; the tail-to-income ratio is unchanged.

Tool: [`tools/option_sigma_study.py`](../../tools/option_sigma_study.py), read-only, 25 s. It reuses the pre-registered backtest ([`tools/option_premium_backtest.py`](../../tools/option_premium_backtest.py), [feasibility study](option-premium-feasibility-2026-10.md)) and only swaps the strike picker.

## Plain words first

- **Sigma (σ).** The market's own guess of a one-standard-deviation move for the week, taken from the at-the-money implied volatility on the entry day: σ·√T. With NIFTY at 25,000, weekly IV 12 % and two sessions to expiry, one sigma ≈ 0.9 %, so 2 sigma ≈ 1.8 % and 3 sigma ≈ 2.7 % from the forward. If the market's guess is right, the index stays inside 2 sigma about 95 % of the time and inside 3 sigma 99.7 % of the time.
- **The live rule** sells the strikes whose delta is 0.05, two sessions before expiry, held to expiry (`exp2`). Measured on the chain, those strikes sit at 2.0 sigma. The 2-sigma row below is the live rule (19.3 %/yr, worst −3.7 %, vs the delta study's 19.5 % / −5.3 %).
- **% of margin.** Every return is net profit over the assumed margin (12 % of the forward, about ₹1.95 L a lot today). 0.39 % of margin ≈ ₹757 a lot.
- **exp1 / exp2 / exp3.** Enter 1, 2 or 3 sessions before the weekly expiry, hold to expiry.

## Real chain, entries 2024-11-20 → 2026-10 (100 weeks, hold to expiry)

| Width | Credit pts | Credit ₹/lot | Cost / credit | Win % | Mean ₹/lot | Ann % margin | Sharpe | Worst week ₹/lot | Worst % |
|---|---|---|---|---|---|---|---|---|---|
| exp2 1.5σ | 28.0 | 1,768 | 3.8 % | 91 | 879 | 22.9 | 1.8 | −18,807 | −10.0 |
| **exp2 2.0σ (≈ live)** | 15.7 | 953 | 5.9 % | 96 | 757 | 19.3 | 4.1 | −6,999 | −3.7 |
| exp2 2.5σ | 10.0 | 578 | 8.7 % | 100 | 627 | 15.7 | 11.6 | +105 | +0.1 |
| **exp2 3.0σ** | 7.2 | 407 | 11.9 % | 100 | 438 | 10.9 | 8.5 | +54 | +0.1 |
| exp1 3.0σ | 6.5 | 390 | 13.1 % | 100 | 383 | 9.6 | 12.6 | +18 | 0.0 |
| exp3 3.0σ | 7.5 | 452 | 11.4 % | 100 | 459 | 11.4 | 12.4 | +29 | 0.0 |

- Median 3σ strikes sit 3.3 % above and 3.1 % below the forward (2σ: 2.1 % each side). Both strikes traded on 98 of 100 weeks.
- The four losing 2σ weeks (2026-05-08, 2025-08-25, 2026-02-26, 2025-04-15, moves of 2–3.5 %) all stayed inside 3σ. **This window has no crash day**, so "100 % win" is what a calm two-year window looks like, not a property of the rule.
- Costs matter more as the strikes move out: 6 % of the credit at 2σ, 12 % at 3σ, because a 7-point option pays the same brokerage and slippage as a 16-point one.

## Model, 2015-06 → 2024-11 (NIFTY + VIX history, every entry day, out of sample)

Calibrated as in the feasibility study: strike distance and credit in units of VIX·√T, taken from the chain trades, replayed on every day of the index history. It sees the 2015 China devaluation, Feb 2016, Oct 2018, the Sept 2019 tax-cut rally and the March 2020 crash.

| Width (exp2) | Win % | Ann % margin | 1-in-100 day | Losing days of 2,301 | ≤ −10 % | ≤ −30 % | Worst day | Worst eats |
|---|---|---|---|---|---|---|---|---|
| 2.0σ | 95.5 | 11.1 | −7.6 % | 104 (4.5 %) | 15 | 2 | −45 % (2019-09-19, +8.4 %) | 4.1 years |
| 2.5σ | 98.0 | 9.9 | −3.5 % | 45 (2.0 %) | 11 | 3 ≤ −20 % | −40 % (2019-09-19) | 4.0 years |
| 3.0σ | 99.1 | 8.2 | +0.1 % | 20 (0.9 %) | 5 | 1 | −34 % (2019-09-19) | 4.1 years |

- The worst days are the same days: the +8.4 % tax-cut rally (2019-09-19 → 23), 2015-08-20 (−6.7 %), 2020-03-05 and 03-09 (−7 to −8 %), 2016-02-29 (+5.5 %), 2018-10-03 (−5 %). A 3σ strike is 3 % away; a 7 % day goes through it as surely as through a 2σ strike, only with 1 % less intrinsic loss and half the premium banked beforehand.
- **Worst-day loss divided by yearly income is 4.0–4.1 years at every width from 1.5σ to 3σ.** Moving the strikes out buys fewer small losses, not a better ratio of tail to income. That is the efficient-market result the predictability study (research 0019) found from the other direction.
- By year the ordering holds: 3σ earns 2–8 %/yr less than 2σ in every year but 2016 and 2020, and its worst year-day is always 5–10 points milder.

## And 2.5 sigma? (Amit, same day)

On the chain 2.5σ looks like the sweet spot: 100 of 100 weeks won, ₹578 credit a lot, mean ₹627 a lot after costs (83 % of 2σ's ₹757, because 2σ's four losing weeks cost it ₹34 K a lot), strikes 2.7 % out, worst mark-to-market −0.45 %. In the model it is simply the midpoint: 9.9 %/yr (2σ 11.1, 3σ 8.2), 45 losing days of 2,301 (2σ 104, 3σ 20), 11 days under −10 % (15 / 5), worst day −40 % (−45 / −34), and the worst day still eats 4.0 years of income. For 16 lots: ≈ ₹9 K a week credit, ≈ ₹10 K expected after costs, a −3.5 % week ≈ 0, a March-2020 day ≈ −₹6 L. It is a fair middle, not a free lunch: the chain's 100 % is the same calm window, and the crash-day arithmetic is unchanged.

## What it means for the live book (16 lots, lot 65, ₹56 L)

| | 2σ (live) | 3σ |
|---|---|---|
| Premium a week | ≈ ₹15 K | ≈ ₹6.5 K |
| Expected after losses and costs | ≈ ₹12 K | ≈ ₹7 K |
| Worst week seen since Nov 2024 | −₹1.1 L | +₹0.9 K |
| A 2026-05-08-type week (−3.5 %) | −₹1.1 L | about 0 |
| A March-2020-type day (−8 %), model | ≈ −₹9 L | ≈ −₹3.4 L |
| The worst modelled day (Sept 2019, +8.4 %) | ≈ −₹14 L | ≈ −₹10.5 L |
| Years of income one worst day eats | 4.1 | 4.1 |

- 3σ turns the ordinary bad week (a 2–3.5 % move, four of them in two years) into a non-event. It does not change what a 7–8 % gap does: with no wings, both widths lose several years of income in one day. The protection against that day is still wings or the crash budget ([combined-book study](combined-book-2026-10.md)), not strike width.
- Per rupee of margin, 2σ earns 1.8× what 3σ earns and has the same tail ratio, so on the numbers 2σ plus wings and a lot cap beats 3σ naked. 3σ makes sense only if the goal is **never to see a weekly loss on a normal week**, and the price of that is roughly half the income.
- A 3σ strike at ₹7 pays ₹20 brokerage a leg plus GST and slippage: at 16 lots the fixed costs are small, at 1–2 lots they take a third of the credit. Below ~5 lots 3σ is not worth trading.

## Margin per lot by width, 32 lots (Amit, same day)

Kite had no login on 2026-11-02, so only the live strikes have a Kite number (2026-10-30 quote, NIFTY 23500 CE / 22400 PE for 11-03, forward 23,021, lot 65): **₹1,61,596 a lot naked**, ₹84,743 winged at 1.75 %, expiry-day extra ₹59,854 (SEBI's 2 % per short leg). Of the naked figure ₹59,854 is the exposure margin (2 % of notional per short leg, the same at every strike) and ₹1,01,741 is SPAN. The 2.5σ and 3σ numbers are an estimate: the exchange's 16-scenario SPAN method priced on that day's live quotes, calibrated so the live strikes reproduce Kite's SPAN, with NSE's short-option minimum of 3 % of notional per short leg (₹89,782 a strangle) as the floor. **Check with `options_live quote` on the next login day.**

| Width (strikes on 10-30) | Credit ₹/lot at bid | SPAN ₹/lot | Margin ₹/lot | Expiry-day peak ₹/lot | 32 lots entry | 32 lots peak | 32 lots credit / week |
|---|---|---|---|---|---|---|---|
| 2σ, live 23500 / 22400 (Kite) | 991 | 1,01,741 | 1,61,596 | 2,21,450 | ₹51.7 L | ₹70.9 L | ₹31.7 K |
| 2.5σ, 23750 / 22300 (est.) | 552 | 86,471 → floor 89,782 | ≈ 1,49,600 | ≈ 2,09,500 | ≈ ₹47.9 L | ≈ ₹67.0 L | ₹17.7 K |
| 3σ, 23900 / 22150 (est.) | 383 | 76,995 → floor 89,782 | ≈ 1,49,600 | ≈ 2,09,500 | ≈ ₹47.9 L | ≈ ₹67.0 L | ₹12.3 K |

- Moving the strikes out saves little margin, about ₹12 K a lot (7 %), because the SPAN part hits the short-option minimum and the exposure margin and expiry-day extra do not move with the strike. Margin per lot is the same at 32 lots as at 1 (no hedge credit on a naked strangle).
- On ₹56.2 L with the ₹2 L buffer, 32 naked lots do not fit at any width on expiry day (peak ₹67–71 L): 25 lots is the most at every width. Winged at 1.75 % (Kite ₹84,743 a lot, peak ₹1,44,597) fits 37.
- Margin per rupee of credit: 2σ earns ₹991 on ₹1.62 L (0.61 % a week), 2.5σ ₹552 on ₹1.50 L (0.37 %), 3σ ₹383 on ₹1.50 L (0.26 %). The margin saving does not pay for the lost premium.

## Limits

- No bid/ask: slippage is assumed max(₹0.05, 1 %) a leg. At ₹4–7 a far strike's real spread can be ₹0.10–0.20, which would push the 3σ cost share to 15–20 %.
- Margin is 12 % of the forward at every width. Kite's SPAN on a 3σ short is a little lower than on a 2σ short, which would flatter 3σ's % of margin slightly.
- The model is a strike-distance-and-credit replay on daily closes: no intraday mark-to-market, no changes in skew on crash days (puts would be dearer in a real March 2020, which helps the seller's entry but hurts the exit), and the VIX stands in for weekly IV.
- The chain window has no crash day; the "100 % win" rows describe 2024-11 → 2026-10 only.
