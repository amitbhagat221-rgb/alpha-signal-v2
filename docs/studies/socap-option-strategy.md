# SOCAP option strategy: rebuilt, backtested on our data, compared with ours (2026-11-07)

**Question (Amit):** "look at the socap strategy understand it and tell me how it compares vs our current strategy in terms of results". Then: "you are supposed to independently verify and backtest socap strategy on our data and report."

**Verdict: DROP** under the rules committed before any result ([pre-registration](socap-option-strategy-preregistration.md), commit 75f352d). The rule tested: sell near-the-money options on expiry day at 09:30 and hedge half the direction every 15 minutes.
- **It is a real edge on NIFTY.** It made money in all 6 years from 2021 to 2026: ₹561 a lot per expiry day, t 3.52. On SENSEX it is not reliable: ₹311 a lot, t 1.06, with losses in 2024 and 2026.
- **It makes about the same money as our live rule but swings three times as much.** On the same 235 NIFTY expiries:

  | | Average week, ₹/lot | Sharpe | Worst week, ₹/lot |
  |---|---|---|---|
  | Rebuilt SOCAP rule | 580 | 1.31 | −18,548 |
  | Our live rule | 530 | 4.16 | −10,050 |

  On SENSEX the rebuilt rule's Sharpe is 1.09 against our 3.34.
- **None of the 36 strike / hedge / timing combinations beats our rule.** The best is a fully hedged low-delta version: Sharpe 3.38 on NIFTY and 1.96 on SENSEX, still below ours (4.16 and 3.34).
- **Three things SOCAP reported, checked on our data:**

  | SOCAP reported | Our data | Verdict |
  |---|---|---|
  | Option prices expect more movement than the market delivers | True for NIFTY (80 % of expiry days); false for SENSEX (43 %) | Holds for NIFTY only |
  | 84 % of NIFTY and 76 % of SENSEX expiry days profitable in 2026 | The rebuilt rule wins 65 % and 55 % | Doesn't hold: SOCAP does much better than anything we can rebuild |
  | Lost money on 20-Jan, 3-Feb and 5-Nov | The rebuilt rule lost on 20-Jan and 5-Nov | Holds (2 of 3) |

  SOCAP's extra edge must come from things a one-lot rebuild cannot copy, such as filling inside the bid/ask, its timing and size, and positions held overnight.

**Recommendation:** no change to the live rule, and no SOCAP-style book. The rebuilt rule earns what ours earns with three times the swing, and it would need a second pot of margin on expiry day.

Tool: [`tools/socap_backtest.py`](../../tools/socap_backtest.py), read-only. A full run takes about 15 minutes: `python -m tools.socap_backtest --report out.md --csv days.csv`. Smoke test: `--smoke`.

## Plain words first

- **Delta (Δ).** Roughly, the chance an option ends in the money. Δ 0.40 is near the money and Δ 0.05 far out. On expiry morning, Δ 0.40 is only about 0.2 % from the index.
- **Hedge ratio h.** The share of the options' directional exposure that is cancelled with a synthetic future (buy a call and sell a put at the same strike). h = 0 is no hedge; h = 1 cancels all of it at each rebalance.
- **Implied vs realised volatility.** Implied is the movement the option price expects. Realised is the movement that actually happened, measured from 1-minute index changes between 09:30 and the close.
  - Our numbers annualise over trading minutes (375 a day, 252 days).
  - SOCAP's "25 %" looks like calendar time, which multiplies our figures by about 2.4. Our 2026 NIFTY 11.2 % implied and 10.6 % realised become about 26 % and 25 %, the same scale as SOCAP's 25 % and 21–22 %.
- **Sharpe.** Average week ÷ the week-to-week swing, × √50. It measures how smooth the income is.
- **Worst ÷ mean.** How many average weeks the worst week wipes out.
- **NW t.** A t-statistic for whether the average is above zero, corrected for weeks that run alike. Above 2 means unlikely to be luck.

## SOCAP's strategy (from SOCAP's fills, 2026 YTD)

This was rebuilt from SOCAP's own fills in a separate session on Amit's laptop. That data is not on this server.

- **What and when:**
  - NIFTY (expires Tue) and SENSEX (expires Thu), current-week contracts only.
  - The biggest selling window is 09:15–10:00 every day. About 60 % of selling is on expiry day, 19 % the day before, and 15–19 % four to seven days out. Selling continues until about 14:30.
- **Strikes:** calls and puts in equal numbers, median **Δ 0.34–0.44**. Only 10–12 % is below Δ 0.15.
- **Hedge:**
  - Same-strike call/put pairs near the money. It sells index exposure as the market falls and buys it as the market rises. The hedge ratio is not fixed.
  - One tag leans with the 09:15–10:00 move, with no forecasting skill after 10:00.
- **Exit:**
  - Days that aren't expiry days: buy back 38–62 % in the afternoon and carry the rest overnight.
  - Expiry day: hold to the 15:30 settlement.
- **Crash insurance:** Δ ≈ 0.01 options, −₹193 cr YTD.
- **Costs:** about 0.12 % of premium, through Citi's and Kotak's algos.
- **Reported results:** NIFTY +₹957 cr over 44 expiry days (84 % profitable), SENSEX +₹758 cr over 45 (76 %). Worst days: 20-Jan, 3-Feb, 3-Nov and 5-Nov.

## How it was rebuilt (rule P, fixed before any result)

1. **Data:**
   - 1-minute trade prices: NIFTY 259 expiry days (2021-05-27 → 2026-05-19), SENSEX 124 (2024-01-05 → 2026-11-05).
   - Sources: the Hugging Face archive, plus the Kite capture for SENSEX 5-Nov.
   - Settlement from `fno_bhav`.
   - Not in the data: NIFTY 3-Nov (never captured), the archive's last files after May 2026, and SENSEX 2023 (no settlement in `fno_bhav`).
2. **Entry:** at 09:30 on expiry day, sell 1 call and 1 put at |Δ| nearest 0.40. The forward comes from put-call parity at the strike nearest the index.
3. **Hedge:** every 15 minutes, cancel half the options' delta with a synthetic future. Each leg keeps its 09:30 implied vol.
4. **Exit:** hold everything to settlement at intrinsic value.
5. **Costs:**
   - Our Kite charges plus slippage of 0.25 % of the price per leg. That is about twice the bid/ask half-spread measured on our Kite quotes for near-the-money strikes.
   - Brokerage is spread over a 10-lot book, and our rule is charged the same way in the comparison.

## Results

### Rule P, ₹ per lot per expiry day

| | Days | Win % | Mean | Median | Sharpe | NW t | Worst | Worst ÷ mean | 1 day in 20 |
|---|---|---|---|---|---|---|---|---|---|
| NIFTY 2021–26 | 259 | 64 | 561 | 980 | 1.30 | 3.52 | −18,548 | 33 | −3,568 |
| SENSEX 2024–26 | 124 | 59 | 311 | 754 | 0.63 | 1.06 | −11,481 | 37 | −5,342 |

| Year | NIFTY total | NIFTY worst | SENSEX total | SENSEX worst |
|---|---|---|---|---|
| 2021 (from May) | +21,073 | −3,902 | | |
| 2022 | +16,093 | −9,739 | | |
| 2023 | +17,972 | −3,129 | | |
| 2024 | +13,785 | −7,195 | −2,024 | −6,653 |
| 2025 | +48,084 | −18,548 | +52,841 | −11,481 |
| 2026 (NIFTY to May) | +28,359 | −3,927 | −12,223 | −8,794 |

Where a NIFTY day's money comes from, in points per unit:
- Credit 76.8.
- Paid out at settlement −68.6.
- Hedge +3.5.
- Costs −1.7 (2.2 % of the credit; for our far-out options it is about 6 %).
- **Net +10.0.**

The edge is thin: the option seller keeps about 13 % of what it collects.

### Against our live rule, same expiries, ₹ per lot

| | Book | Weeks | Win % | Mean | Sharpe | Worst | Worst ÷ mean | Total |
|---|---|---|---|---|---|---|---|---|
| NIFTY | Rebuilt SOCAP | 235 | 64 | 580 | 1.31 | −18,548 | 32 | 1,36,214 |
| | **Ours** | 235 | 97 | 572 | **4.49** | −10,008 | 17.5 | 1,34,529 |
| | 50/50 | 235 | 72 | 576 | 2.39 | −8,758 | 15.2 | 1,35,372 |
| SENSEX | Rebuilt SOCAP | 107 | 64 | 529 | 1.09 | −11,162 | 21 | 56,608 |
| | **Ours** | 107 | 97 | 619 | **3.59** | −11,050 | 17.9 | 66,213 |
| | 50/50 | 107 | 68 | 574 | 2.20 | −5,696 | 9.9 | 61,410 |

- "Ours" here is charged brokerage on the same 10-lot basis. The pre-registered as-is replay gives Sharpe 4.16 and 3.34, worst ÷ mean 19 and 19; the verdict is the same either way.
- **The two books lose on different weeks.** Week-by-week correlation is 0.19 (NIFTY) and 0.04 (SENSEX).
  - Our worst NIFTY week, 2026-05-12, cost the rebuilt rule only −₹3,554.
  - The rebuilt rule's two worst days, 2025-04-17 (+2.4 % during the day) and 2025-05-15 (+1.9 %), were winning weeks for us (+₹989 and +₹1,310).
  - The Ukraine day, 2022-02-24, came as a gap before 09:30: the rebuilt rule lost −₹4,533 and our rule made +₹698.
- **Mixing the two halves the SENSEX worst week relative to income** (9.9 against 17.9). But the Sharpe falls below ours alone, and it needs a second pot of margin on expiry day, because our NIFTY position is open until Tuesday 15:08. Reported, not recommended.

### SOCAP's reports, checked on our data

| Check | Our data | Holds? |
|---|---|---|
| V1 implied > realised on expiry days | **NIFTY:** 9.7 % against 8.2 % (median gap 1.4 points), implied higher on 80 % of days; 2026: 11.2 % against 10.6 %, 85 % of days. **SENSEX:** 10.2 % against 10.5 %, 43 % of days; 2026: 27 % of days | NIFTY yes, SENSEX no |
| V2 2026 hit rate (SOCAP 84 % / 76 %) | Rule P: NIFTY 65 % (20 days to May), SENSEX 55 % (22 days) | No |
| V3 loses on SOCAP's stress days | 20-Jan −₹3,927 (lost); 5-Nov −₹341 (lost); 3-Feb +₹12,618 (won) | Yes, 2 of 3 |

On 3-Feb the +2.8 % gap had already happened at 09:15, and the index was back to 25,774 by 09:30, so a seller entering at 09:30 never saw it. SOCAP's loss that day must have come from options sold on earlier days and carried overnight, which is outside this test.

### Grid and variants (not deciding; about 41 tries)

- **Hedging more is what helps.** Fully hedged (h = 1) cells reach NIFTY Sharpe 2.4–3.4, against 0.6 with no hedge.
  - The best is Δ 0.15, h 1, every 5 minutes: ₹383 a lot, Sharpe 3.37, worst −₹5,335 (13.9 average weeks).
  - Its worst ÷ mean is smaller than ours (17.5), but the Sharpe is still below ours (4.49). SENSEX's best cell has Sharpe 1.96 against our 3.59.
  - An unhedged near-the-money sale loses up to −₹33,333 a lot in one NIFTY day.
- **Leaning with the morning move:** NIFTY mean ₹733 and Sharpe 1.70, but the worst day grows to −₹26,363, and SENSEX gets worse. This matches SOCAP's fills, which show no forecasting skill in the lean.
- **Crash insurance (Δ 0.01, 10 % of the credit)** removes most of the edge: NIFTY Sharpe 0.30, SENSEX negative. SOCAP's −₹193 cr insurance bill is consistent with this.
- **Selling in hourly batches to 14:30:** half the mean, the same Sharpe.
- **Slippage:** at 0.1 % NIFTY is ₹571 a lot; at 1 % it is ₹497. Costs are not what sinks it.

## What this means

1. **SOCAP's premise is real on NIFTY.** Near-the-money options on expiry morning are priced for more movement than usually comes, and selling them made money every year since 2021, even at one lot and our costs. On SENSEX the premise does not hold in our data.
2. **The money is thin and the swings are large.** The seller keeps about 13 % of the credit, and a 2 % move during the day costs about 33 average days of income. Our far-out sale keeps far more of its credit and loses only on 3 %+ moves.
3. **SOCAP wins much more often than our rebuild (84 % against 65 %).** What we cannot copy is probably the extra: filling inside the spread, size and timing, and the overnight book.
4. **Neither window has a crash** (2021–26 minute data). Our rule's 2019–26 daily test includes March 2020. The rebuilt rule takes on new risk each morning but avoids overnight gaps, so a crash that gaps before the open would hurt it less than it hurts us.

## Limits

- **Trade prices, not bid/ask.** Slippage is assumed (0.25 %, with 0.1 % and 1 % tested). The Kite quote capture since 2026-11 gives real spreads for a forward check.
- **Hedge modelling:** hedge deltas use each leg's 09:30 vol (sticky strike). The hedge is priced as a future on the index plus a basis that decays linearly. Hedge trades are rounded to whole lots of a 10-lot book.
- **Out of scope:** SOCAP's selling on the day before expiry and earlier (about 40 % of its selling), and its standing futures short.
- **SOCAP's own figures** come from the other session and were not reproduced here. This study only tests whether its reconstructed rules work on our data.
