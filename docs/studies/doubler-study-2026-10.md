# Why the doublers doubled, why we missed them, and what could catch them (2026-10-13)

Amit: "analyse these and figure out why our model did not catch it (it might be prudent also to not catch it) … what other asymmetric return model could have caught it … sentiment, Adani political connections, regulatory lobbying …".

Inputs:
- [`tools/doubler_study.py`](../../tools/doubler_study.py): every (stock, month) 2019-12 → 2025-10 in LARGE / MID / SMALL, 77,423 rows; outcome = next-12-month adjusted return.
- A web-research pass on the 40 largest runs: [doubler-drivers-top40.md](doubler-drivers-top40.md).
- The list: [missed-winners-2019-2025.md](missed-winners-2019-2025.md).

## 1. What a doubler looked like beforehand
Base rate: **11.1 %** of stock-months doubled within 12 months; **2.1 %** halved (today's listed names only, so halving is understated).

| profile | P(double) | P(halve) | median excess vs tier |
|---|---|---|---|
| starting in 2020 / 2023 | 32 % / 20.5 % | 0.3 % / 0.2 % | 0 (everything rose) |
| **Defence & aerospace** | **26 %** | **0 %** | **+39 %** |
| Adani group | 28 % | **8.1 % (3.9×)** | +19 % |
| power generation / power T&D | 21 % / 17 % | 3.5 % / 2.7 % | +8 % / +13 % |
| mining · capital goods · iron & steel | 20 / 17 / 16 % | ≈ base | +14 / +14 / +9 % |
| penny (< ₹50) | 21 % | 4.3 % (2.1×) | 0 |
| cheapest fifth on book-to-price | 13 % | **1.3 % (0.6×)** | +4 % |
| top fifth of the sector policy score | 14.5 % | ≈ base | +6.5 % |
| 6-month momentum, top fifth | 13.7 % | 2.8 % | +2.6 % |
| forensic-flagged | 14 % | **4.2 % (2.0×)** | **−4.4 %** |

## 2. What drove the 40 biggest runs (web research; details and sources in the appendix)
| driver | count | our model: caught / middle / missed | later trouble |
|---|---|---|---|
| structural growth with results acceleration | 10 | 2 / 4 / 4 | several −50 % falls |
| **policy-capex theme** (T&D, defence, renewables, rail) | 9 | **0 / 6 / 3** | IRFC −53 %, TARIL −56 %, Cochin |
| **turnaround** (deleveraging, first profit, new owner) | 4 | **0 / 0 / 4** | Jai Balaji −45-60 % from peak |
| group / connections (all Adani) | 4 | 1 / 1 / 2 | all four: Hindenburg (−46 to −79 %), DOJ |
| speculation / retail mania (Brightcom, TTML, RattanIndia) | 3 | — | all three: SEBI order or > −50 % |
| corporate event (acquirer / open offer) | 3 | all missed | Poonawalla SEBI order (revoked) |
| Covid-demand shock | 3 | — | mostly > −50 % later |
| commodity cycle | 1 | — | — |
| not found | 3 | — | — |

- 31 of 40 had a public systematic signal at some point: 17 at the start (order book, policy scheme, deal filing, results jump), 14 during the run.
- **9 had none beyond price momentum, and every one of those later hit trouble.**
- **Data note:** AURUM's "×24" is a label artifact. A ₹974 special dividend (factor 0.012, 2020-12-23) was reinvested at the post-dividend stub. It is the only pure-dividend adjustment that extreme; 7 are below 0.8.

## 3. Was missing them prudent?
- **On average, no.** In the 12 months after their run, doublers had a median of another **+19.6 %**; 65 % kept rising; 2.3 % gave back half.
- **For specific kinds, yes.** Speculation and connection runs (Brightcom, TTML, RattanIndia, the four Adani names) had no fundamental signal and all ended in a SEBI action, a fraud allegation or a crash of more than 50 %. Forensic-flagged names double nearly as often but halve twice as often, with a negative median.
- So the flag has value as a *risk* warning, which is how it is now used (a review prompt, not a score cut).

## 4. A generic "doubler model" — tested and rejected (pre-registered in the tool)
Logistic regression on 26 features, fitted on 2019-12 … 2022-12 and tested on 2023-01 … 2025-10. SMALL top 20 per month:

| | P(double) | P(halve) | mean excess | median excess |
|---|---|---|---|---|
| doubler model | 16.4 % (1.8× base) | **6.5 %** | +19 % | **+0.3 %** |
| live model | 16.4 % | 3.5 % | **+28 %** | **+8.1 %** |

- The model learned *small, cheap, volatile, business-group, policy sector*: a lottery ticket. It worked in 2023-24 and failed in 2025 (P(double) 2.8 % against a 3.8 % base; median −12 %).
- **Fails the bar.** A generic multibagger model is not worth building.

## 5. Where the gold is
- **Doubling is mostly beta and themes.** Two market-wide rallies (2020, 2023) plus a handful of policy-capex themes made most doublers. A stock-ranking model cannot catch beta; only tier allocation can.
- **Three specific, systematic patterns are worth a pre-registered test each** (plan 0025 phase 7):
  1. **Policy-capex theme momentum.** The strongest asymmetric profile: defence 26 % double / 0 % halve. Our model sits in the middle on all 9 theme winners.
     - Inputs we hold: sector policy score (2020+), industry momentum, **order-win intensity** (BSE "Award of Order / Receipt of Order": 9,454 filings, 742 companies, 2018+), position in the 52-week range.
     - Needs an exit rule: the themes crashed later (IRFC, TARIL, Cochin).
  2. **Turnarounds**, missed 4 out of 4. The quality factors and the old forensic cut mark down exactly the loss-making, levered names that re-rate.
     - Inputs: debt falling, first profit or interest coverage turning, a credible acquirer (BSE "Open Offer" / "Acquisition" filings).
     - Needs the quarterly history now harvesting.
  3. **A mania exclusion screen**, the "prudent not to catch" part: price momentum with no fundamental change in penny or low-float names, preferential-warrant issuers (BSE "Preferential Issue", 1,656 filings), and forensic flags. It works as an avoid list for every book.
- **Political / lobbying connections cannot be measured honestly** with our data. The business-group proxy shows Adani's two-sided profile (P(double) 2.6×, P(halve) 3.9×). That is risk, not edge.
