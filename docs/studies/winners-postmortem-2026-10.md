# Winners post-mortem — why NETWEB ranked at the bottom (2026-10-13)

Prompted by Amit: "NETWEB is up 90 % and rated very badly in our setup … we are missing something fundamental." Read-only; scripts in the session scratchpad (`winners.py`, `forensic_test.py`), labels from `data/lh/labels.parquet` (plan 0024).

## NETWEB

- SMALL rank ~2,158 of ~2,160 in April 2026, ~1,450 in June–July. Then +51 % over the next 126 sessions (from the 2026-04-01 anchor). It was a top-5 % 6-month winner at 5 anchors in 2025.
- **Cause 1, the forensic penalty (−0.2) from April to late August 2026.** Beneish M-score −0.55 → `LIKELY_MANIPULATOR` (`signals/forensic.py`, red line −1.28). The trigger was revenue +97 % to +174 % YoY: Beneish's sales-growth index flags fast growers. A −0.2 penalty on a 0–1 score sends a mid-ranked stock to the bottom of the tier. The flag cleared on 2026-09-06 (M −3.61).
- **Cause 2, nothing in the SMALL score rewards what it had.** At 2026-04-01 it was in the 96th percentile on revenue growth, 84th on EPS growth, 97th on 6-month momentum and 93rd on ROE. The SMALL weights are delivery-anomaly z, announcement CAR (missing → 0.5), Piotroski (5/9), residual momentum (0.14), sector tilt (IT is low) and 30-day delivery % (1st percentile: a heavily traded stock). Rebuilt with today's weights and no penalty, it sat at about the 61st percentile: middle, not top.

## SSWL and TIMETECHNO (added same day)

Percentiles are within SMALL, from the PIT panel at monthly anchors; the live score is rebuilt with today's weights.

- **SSWL (+119.6 % over 6 months).** No forensic penalty. Before the run (Jan–Apr 2026), live score at the 22nd–38th percentile, and nothing in our factors stood out (6-month momentum 0.20–0.61, revenue growth 0.17–0.33). The run began in June 2026 (₹196 on 1 June → ₹247 on 1 July → ₹391 on 1 October); the 15 July results confirmed it.
  - What changed was **quarterly acceleration and margin expansion**. PAT YoY went −23 % (Sep 25) → −2 % → +0 % → **+47 %** (Jun 26), and EBITDA margin went 9.3 → 9.7 → 10.2 → 10.9 %. There was also an acquisition on 9 April 2026 and an order award plus MoUs in Dec 2025–Feb 2026.
  - Our growth inputs are annual/TTM and polluted by a one-off: the Mar-2024 quarter's PAT of ₹516 cr makes `eps_growth` read −2.7 % today. The model's announcement CAR did pick up the reaction (85th percentile from August).
  - It still doubled despite two director resignations (March and June 2026) and a show-cause notice (June 2026), which the governance factor reads as negatives.
- **TIMETECHNO.** The run was April 2023 → January 2025 (+222 % over 252 sessions from April 2023). In the last year it is −20 %: FY26 FCF turned negative on capex of ₹370 cr, there was about 9 % dilution, and promoters are selling. So the model's middle rank today is defensible.
  - **During the run, the live score whipsawed month to month:** 27th → 70th → 4th → 41st → 72nd → 96th → 16th → 82nd percentile. About 46 % of SMALL weight is on fast signals (delivery-anomaly z 0.24, announcement CAR 0.22), which flipped between the 4th and 93rd percentiles.
  - What stayed high the whole way: 6-month momentum and 52-week position (70th–96th), residual momentum (68th–93rd), falling debt and rising FCF.
- **All three winners sit at the bottom on 30-day delivery %:** NETWEB 1st percentile, TIMETECHNO 3rd, SSWL 13th. Heavily traded, popular stocks get penalised by a factor whose 6-month evidence fell from t 4.00 to 1.75 on the full market.

Read across the three: there is no **acceleration engine** (quarterly YoY growth change, margin expansion, ex-one-offs). The score is **unstable** because of fast signals, and it **penalises attention** through delivery % and the M-score. Three anecdotes are not evidence; the test below decides.

## All winners, 2019-12 → 2026-04 (top 5 % of each tier by 126-session return)

Lift is the winners' mean within-tier percentile minus 0.5, set against the same for the bottom-5 % losers. The non-overlapping t averages six every-6th-anchor subsamples.

- **Big winners are mostly volatility.** 252-day volatility, max daily return, opening-gap frequency and Kyle's λ put stocks in *both* tails (SMALL volatility: winners +0.10, losers +0.12). Picking for winners means buying volatility.
- **The live score is not blind to winners.** SMALL winner lift is +0.064 and loser lift −0.023, positive at 90 % of anchors (t 4.7). MID: +0.084 / −0.006 (t 2.9). But only 15 % of SMALL winners and 19 % of MID winners were in the live top 10 %; 42 % / 36 % were in the bottom half.
- **The most consistent trait of winners is momentum.** 6-month and 12-month momentum and 52-week position were positive at 80–87 % of anchors, with near-zero loser lift (MID mom_6m +0.093 / +0.005, t 3.1).
- **Growth looks like a winner trait, but its history is 8 anchors.** `revenue_growth_yoy`, `eps_growth_yoy` and `growth_composite` start in the PIT panel only in 2025-09; ROE, Piotroski and quality start in 2024-09. MID EPS growth: winners +0.13, losers +0.03, 8/8 anchors positive. Not testable yet, even though statements go back 10–11 years.
- **Quality and safety are not winner traits.** In SMALL, gross profitability, interest coverage, Altman Z and ROIC are *below* median for winners and losers alike: junk is volatile.

## The forensic penalty, tested (2025-09 → 2026-04: 8 anchors with M-score coverage, about 1.3 independent 6-month windows)

| SMALL, 126 sessions | per anchor | median excess vs tier | beat median | top-5 % rate | bottom-5 % rate |
|---|---|---|---|---|---|
| M CLEAN | 975 | +0.3 % | 50.5 % | 4.7 % | 4.6 % |
| M LIKELY (−0.2) | 96 | −2.4 % | 45.7 % | 6.0 % | 7.3 % |
| Z DISTRESS (−0.2) | 31 | −6.7 % | 39.4 % | 4.0 % | 8.4 % |
| Z GREY (−0.1) | 12 | −7.3 % | 38.3 % | 5.3 % | 9.6 % |

- The M-score flag lands on growth: 20.5 % of the top revenue-growth quintile is `LIKELY`, against about 3 % in the middle quintiles. In effect the penalty works as an unweighted anti-growth factor.
- In SMALL it widens both tails (more winners *and* more losers) with a small negative median. MID `LIKELY` looks worse (median −7.5 %, 28 % beat the median) on only 3.6 names per anchor. Altman distress/grey is the more consistent avoid signal.
- The penalty sits outside `factors.FACTORS`, so it never faced the evidence bar every weighted factor faces. Its size (−0.2) is not measured; it is a rule from 2026-05.

## Step 1 — growth, acceleration and long-history quality, tested (2026-10-13)

[`tools/lh_growth.py`](../../tools/lh_growth.py) (read-only; features pre-registered in its docstring). Features are built from the statements at every monthly anchor:
- **Annual:** Screener, knowable at period end + 150 days, 77 anchors from 2019-12.
- **Quarterly:** `quarterly_income`, knowable at period end + 60 days, but only 14–17 testable anchors from 2024-12, because quarterly history starts in 2023 in both sources.

Within-tier rank IC; Newey-West t at lag = horizon in months; non-overlap t = the mean of the every-k-th-anchor subsample t's. **With fewer than ~30 anchors the Newey-West t is not credible** (it over-rejects); read the non-overlap t. Family: 162 tests, Bonferroni |t| ≈ 3.8.

| Finding | Tier · horizon | IC | NW t | non-overlap t | top-decile excess | IC by period 20-22 / 23-24 / 25-26 |
|---|---|---|---|---|---|---|
| **Annual growth does not predict**; it is slightly negative (priced in) | SMALL · 252 `a_sales_g1` | −0.053 | −2.75 | −1.94 | +9.9 % | −0.077 / −0.045 / +0.022 |
| Same for acceleration, EBIT change, 3-yr CAGR, growth consistency | all | ≈ 0 or < 0 | — | — | — | — |
| **Persistent high ROCE underperformed in MID** (Coffee-Can-style quality) | MID · 126 `a_roce_min5` | −0.106 | −6.48 | −4.39 | +0.2 % | −0.100 / −0.117 / −0.099 |
| | MID · 252 | −0.135 | −7.16 | −5.53 | +0.6 % | −0.124 / −0.139 / −0.162 |
| **6-month momentum is the most robust slow signal** | SMALL · 126 `mom_6m` | 0.085 | 3.97 | 3.04 | +15.4 % | 0.067 / 0.125 / 0.067 |
| | MID · 126 | 0.088 | 3.16 | 2.39 | +8.3 % | 0.061 / 0.108 / 0.119 |
| **Value × quality works in SMALL** (ROCE & book-to-price) | SMALL · 252 `x_quality_value` | 0.046 | 3.01 | 2.02 | +21.2 % | 0.059 / 0.026 / 0.048 |
| **Quarterly margin expansion: promising, 1.5 years only** | MID · 126 `q_margin_chg` | 0.048 | 5.68 | 2.71 | +12.9 % | — / — / 0.045 |
| Quarterly profit / revenue acceleration | SMALL · 126 `q_profit_accel` / `q_rev_accel` | 0.030 / 0.029 | 6.40 / 2.97 | 1.02 / 0.62 | +8.1 % / +7.9 % | 2025-26 only |
| Growth × momentum, margin × momentum | MID · 126 | 0.054 / 0.063 | 2.57 / 2.60 | 1.81 / 1.94 | +6.0 / +6.7 % | ≈ 0 in 2020-22: adds nothing over momentum alone |
| Piotroski-lite on 2019+ annual data (live `piotroski_f` starts 2024-09) | MID / SMALL · 126 | 0.000 / 0.028 | 0.03 / 2.34 | −0.01 / 1.90 | +7.4 / +9.5 % | MID −0.040 / 0.015 / 0.071 |
| LARGE: nothing passes | — | — | — | — | — | — |

Read:
1. **Growth was not the missing factor.** Past growth, annual or accelerating, is priced in, and in SMALL it is mildly contrarian.
2. **What the winners shared that the data rewards is momentum.** The market's reaction to improving fundamentals predicts better than the fundamentals themselves. Our SMALL score puts 0.14 on residual momentum and 0.36 on delivery measures.
3. **Quarterly margin expansion is the one fundamental lead.** MID non-overlap t is 2.71 and top-decile excess +12.9 %, but it rests on about 3 independent 6-month windows in one regime. It is a pre-registered forward-test candidate, not a weight. Netweb would not have scored on it (flat ~15 % margin); SSWL would have.
4. **Consistent-high-ROCE quality lost in MID in every period since 2020.** This is a warning for Coffee-Can/QGLP-style books, consistent with Coffee Can's negative 5-year alpha (research 0007 leads). Value × quality, not quality alone, is the version that worked (SMALL), matching Kaur et al. 2024.
5. **Piotroski's live strength is recent.** The long-history lite version is ≈ 0 in MID 2020-22. Its current t's come from 2024-26.
6. A longer quarterly history (BSE/NSE XBRL results, 2018+) is the data that would settle point 3.

## What this means

The model is built to **avoid losers** (forensic penalty, accruals, Piotroski, delivery). That matches plan 0024: MID's skill sits in the bottom deciles. It has **no growth engine**, and the one growth-adjacent input, the M-score penalty, points the wrong way. Whether growth or acceleration would help out of sample is **unknown**, because the PIT growth factors have 8 months of history.

Next (needs Amit's go; the first two change picks):
1. Backfill the PIT history of growth, ROE and Piotroski from the 10–11 years of statements (2016+), then test growth, acceleration and growth × momentum within tier at 63–252 sessions. Include **quarterly** acceleration (latest-quarter YoY minus prior-quarter YoY, on EBITDA/PBT to dodge one-offs like SSWL's Mar-2024 gain) and YoY margin change, not just annual growth.
2. Re-test the Beneish and Altman penalties on that longer history. Size the penalty from evidence, cap it, or turn M-score into a review alert (thesis monitor) instead of a score cut. A worktree branch until approved.
3. Test raising momentum's weight in the slow score (most consistent winner trait, near-zero loser lift).
