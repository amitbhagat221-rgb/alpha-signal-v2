# Plan 0025 — slow core and fast tactical: phases 1–3 results (2026-10-13)

**Verdict first.**
- **Slow core: no tier passes.** The new slow score (`slow_v2`) predicts better than plan 0024's on its own terms (SMALL non-overlap t 3.48 at 6 months), but its book does not clear the bar. SMALL made +7.9 %/yr over 2022-26 (t 1.19) and +10.3 %/yr over 2019-26 (t 1.95). Choosing among rules is luck (PBO 0.57–0.93).
- **Fast SMALL tactical book: closest to passing of anything tested.** This is the walk-forward (honest) fast score. All 12 variants beat the Smallcap 250 after costs and short-term tax; the best made +12.2 %/yr. It **passes both luck tests** (DSR 0.955, PBO 0.10) but its t is 1.64 (< 2.0). Its excess is uncorrelated with the slow books (ρ ≈ 0).
- **The forensic penalty fails** its pre-registered test on 2019-26 history. The Beneish flag shows no underperformance in MID/SMALL and flags 20 % of the fastest growers. **Accruals are the reverse of the Indian paper:** high accruals underperform, most in SMALL (t −2.7 at 6 months, −3.2 at 12).

Nothing here changes live weights or picks. Every tool is read-only and pre-registered in its docstring.

## 1.1 Luck tests on plan 0024's 48 variants
See [long-horizon-2026-10.md](long-horizon-2026-10.md#luck-tests-on-the-48-variants-plan-0025-task-11-2026-10-13).
- No tier passes.
- SMALL: DSR 0.93, PBO 0.47. The in-sample best beats the index out of sample in 90 % of splits; the median rule makes +8.5 %/yr. So the edge, if any, is in the score, not the rule.

## 1.2 / 1.3
- `fast_v1` frozen (plan 0025 notes).
- `slow_v2` pre-registered in [`tools/lh_slow_v2.py`](../../tools/lh_slow_v2.py): equal-weight percentile mean of `mom_6m`, quality × value (ROCE & book-to-price), and Piotroski-lite.
- It was selected after looking at 2019-26, so its own results are in-sample selection with no fitted weights.

## 2.1 slow_v2 horizon test (77 anchors at 126 sessions)
| tier | IC 126 | non-overlap t 126 | top-decile excess 126 | IC 2020-22 / 23-24 / 25-26 | bar |
|---|---|---|---|---|---|
| SMALL | 0.075 | **3.48** | +12.2 % | 0.051 / 0.101 / 0.094 | **pass** |
| MID | 0.066 | 1.85 | +10.4 % | 0.014 / 0.088 / 0.153 | fail (t; weak 2020-22) |
| LARGE | 0.013 | 0.31 | +7.0 % | 0.024 / 0.017 / −0.021 | fail |

- Rank correlation with plan 0024's `slow_select`: SMALL 0.27, MID 0.03. These are different scores.
- `fast_v1` (live weights on history) shows SMALL t 6.6. **This is in-sample:** the live weights were set on this period, so it is not evidence.

## 2.2 slow_v2 book (template: monthly · top 10 · sell below 30 · 3-month avg · 12-month hold)
| | window A 2022-06 → 2026-10 | window B 2019-12 → 2026-10 | grid (48, window A): median excess · DSR(N_eff) · PBO |
|---|---|---|---|
| SMALL | +7.9 %/yr, t 1.19 | +10.3 %/yr, t 1.95 | +7.2 % · 0.82 · 0.66 |
| MID | +4.1 %/yr, t 0.78 | +7.6 %/yr, t 1.22 | +9.2 % · 0.97 · 0.57 |
| LARGE | +12.0 %/yr, t 1.84 | +14.9 %/yr, t 1.81 | +9.8 % · 0.98 · 0.93 |

- Same template, window A, other scores: SMALL `slow_select` +18.3 % (t 1.81), `fast_v1` +9.5 % (t 1.32); MID `fast_v1` +9.5 % (t 1.81).
- **Fail in every tier.** The LARGE book result sits on an IC of ≈ 0 and PBO 0.93: noise, not skill.
- Better IC did not give a better top-10 book.
- Without the forensic forced sale, the books earned less (SMALL A 6.6 % vs 7.9 %, B 6.1 % vs 10.3 %). But that rests on only 1–3 forced sales plus a few blocked buys per book: too few to read.

## 2.3 Forensic flags, rebuilt from annual Screener 2016+ (77 anchors, non-Financials)
Calibration against the live scores on 2024-07+: M rank correlation 0.62, LIKELY rate 9.4 % (annual) vs 8.0 % (live); Z correlation 0.89.

| flag (penalty) | tier · 126 sessions | flagged − clean, per anchor | non-overlap t | beat-median rate |
|---|---|---|---|---|
| Beneish LIKELY (−0.20) | SMALL | +1.5 % | 0.20 | 47.6 % |
| Beneish LIKELY | MID | +0.2 % | 0.02 | 51.3 % |
| Beneish LIKELY | LARGE (1.5 names/anchor) | −11.1 % | −2.75 | 26.1 % |
| Beneish POSSIBLE (−0.10) | SMALL | −4.1 % | −1.80 | 45.7 % |
| Altman DISTRESS (−0.20) | SMALL | +1.0 % | 0.06 | 45.8 % |
| Altman GREY (−0.10) | SMALL | +6.8 % | 0.49 | 40.2 % |
| Altman GREY | MID (1.6 names/anchor) | −10.4 % (−25.9 % at 252, t −2.69) | −1.03 | 29.5 % |

- Share flagged LIKELY by revenue-growth quintile: 6.9 / 4.7 / 5.5 / 6.5 / **20.4 %**.
- Pre-registered rule: a −0.20 cut needs flagged-minus-clean t ≤ −2.0 at 126 in that tier. **No MID/SMALL flag qualifies.**
- Distressed small caps have a lower median but a fatter right tail, so the mean is unchanged.
- **Recommendation (D4):** replace both score cuts with review flags; keep the forced-sale rule only as a review trigger.

## 2.4 Accruals, long history (cf accruals = (NI − CFO) / assets; negative IC = high accruals lag)
| tier | IC 126 | NW t | non-overlap t | IC 252 | non-overlap t 252 | sign by period |
|---|---|---|---|---|---|---|
| SMALL | −0.044 | −3.71 | **−2.69** | −0.065 | **−3.15** | − / − / − |
| MID | −0.045 | −2.33 | −1.66 | −0.057 | −1.51 | − / − / − |
| LARGE | −0.049 | −2.04 | −1.43 | −0.068 | −1.36 | − / − / − |

- The live MID weight (−0.10) has the right sign but misses the pre-registered bar (−1.66 vs −2.0). Keep it, unchanged.
- In SMALL it is a slow signal that strengthens with horizon and is **not wired**. It is a candidate for a pre-registered `slow_v3`, counted in the multiple-testing family.
- This contradicts Sehgal et al. 2012 (BSE-500, 1997–2010), which found no accrual anomaly.

## 3 Fast SMALL tactical book ([`tools/tactical_book.py`](../../tools/tactical_book.py), 2022-06 → 2026-10)
Measured costs (30.5 bps one-way), STCG 20 % + cess, NIFTY SMALLCAP 250 + dividends, no tax deferral.

| score | best variant | excess/yr after costs + tax | t | turnover/yr | costs/yr | all variants beat index | DSR(N_eff) | PBO | verdict |
|---|---|---|---|---|---|---|---|---|---|
| `fast_select` (walk-forward, honest) | monthly · top 20 · sell below 40 | **+12.2 %** | 1.64 | 9.0× | 7.2 % | 12 / 12 (median +8.1 %) | **0.955** | **0.10** | fails t only |
| `live` (in-sample reference) | monthly · top 20 · sell below 40 | +9.1 % | 1.85 | 8.2× | 5.8 % | 12 / 12 | 0.91 | 0.56 | — |
| status quo, top 5 / below 8 | — | +8.1 % (`fast_select`) | 1.11 | 10.2× | 10.4 % | — | — | — | — |

- **3.1** (names-per-tier at measured cost + tax): top 20 beats top 10 in every band (+12.2 / +12.2 / +8.7 % vs +7.5 / +5.7 / +5.5 %).
- **3.3:** the correlation of monthly excess with the slow template books is 0.07 (`slow_select`) and −0.02 (`slow_v2`). The two books would diversify each other.
- The minimum hold of 0 vs 1 month is identical at monthly review, so the grid holds 6 distinct rules.
- A weekly review is not testable on monthly labels.
- **Time to prove:** t 1.64 in 52 months implies an IR of about 0.79. Reaching t 2.0 forward takes about **4 years** at the same strength (≈ (1.645 / IR)² years).

## What it means for the decisions (plan 0025 D1–D4)
- **D1 slow core:** fail → SMALL/MID stay the index for real money. `slow_select` remains the best slow book score (+18.3 %, t 1.81); `slow_v2` did not improve it.
- **D2 tactical SMALL:** the strongest candidate. It passes the luck tests but not the t. It is a case for a **pre-registered forward paper test** of one rule (`fast_select` · monthly · top 20 · sell below 40), with the bar fixed now, if Amit wants it. It still needs ~4 years to prove at this strength.
- **D4:** turn the Beneish and Altman score cuts into review flags (changes live picks → worktree branch, Amit's approval). Keep the MID accruals weight.

## 4.1 Thesis monitors on our own data ([`tools/monitor_events.py`](../../tools/monitor_events.py))
Each event is assigned to the next monthly review that would see it. Outcome = the forward return vs the tier median.
- **False alarm:** the share of flagged stocks that still beat their tier median (any stock: 50 %).
- **Grade (pre-registered):** EXIT needs a mean ≤ −5 % at 126 sessions with non-overlap t ≤ −2.0 and false alarms ≤ 40 %; REVIEW needs a mean < 0 with t ≤ −1.5.

MID + SMALL pooled, 126 sessions:

| event (source) | n | month before the review | median excess | false alarm | non-overlap t (mean) | grade |
|---|---|---|---|---|---|---|
| auditor resignation (BSE 2018+) | 143 | +2.5 % | −1.3 % | 47.6 % | 0.06 | noise |
| CFO resignation | 624 | +1.7 % | −1.6 % | 47.9 % | 1.62 | noise |
| CEO / MD resignation | 271 | +0.3 % | −3.2 % | 43.9 % | 0.50 | noise |
| — MID only | 40 | −0.4 % | **−6.9 %** | **37.5 %** | −0.76 | noise (n small) |
| director resignation | 1,717 | +1.9 % | −0.8 % | 48.2 % | 2.49 | noise |
| rating downgrade (headline) | 70 | −0.2 % | +4.1 % | 57.1 % | 0.84 | noise |
| rating upgrade (contrast) | 499 | +2.7 % | +2.0 % | 52.9 % | 1.84 | — |
| pledge up ≥ 2 pts q/q | 214 | +1.9 % | −0.2 % | 49.1 % | 0.04 | noise |
| promoter stake down ≥ 2 pts q/q | 413 | +3.2 % | −0.1 % | 49.9 % | 1.18 | noise |
| results reaction ≤ −8 % | 2,092 | −7.4 % | −1.8 % | 47.5 % | 1.80 | noise |
| last month in the tier's bottom 5 % (price crash) | 3,908 | −17.6 % | −2.0 % | 46.4 % | 2.74 (positive mean) | noise |
| delivery anomaly z ≤ −2 | 2,582 | +7.3 % | −0.7 % | 48.3 % | 2.78 (positive mean) | noise |

Read:
- **No warning sign separates future losers from winners** at the next monthly review: false-alarm rates are 44–57 % against 50 % by chance.
- Means are positive because tier returns are right-skewed (the mean stock beats the median). Read the median and the false-alarm rate.
- Consistent with research 0007: downgrades are priced before the news, and selling after a price crash loses (a mean rebound).
- **Not measurable here:** ASM/GSM entry (`surveillance_flags` starts 2026-05) and loan-default disclosures (headlines don't say nil vs default).
- **Survivorship understates every negative effect.** Firms that delisted after the event are missing from the labels.

**4.2 not run.** With no event above noise, replaying "review, not sell" would only measure noise. The design rule from research 0007 stands without it: alerts open a qualitative review, never an automatic exit.
- **Follow-up that could change this:** rerun 4.1 on the full market including delisted names (legacy bhavcopy, plan 0025 5.2), where auditor-resignation and default outcomes are most likely to show.

## 5. Tier-wise slow model v1, timing luck and midcap tactical (2026-10-13, after Amit's "good enough" steer)

### Tier-wise slow model v1 ([`tools/lh_tier_slow.py`](../../tools/lh_tier_slow.py), pre-registered, equal weights)
- **SMALL:** + mom_6m · + cons_beat_rate_4q · + quality×value · + sector_tilt · − accruals · + Piotroski-lite.
- **MID:** + mom_6m · + Piotroski-lite · + cons_beat_rate_4q · + quarterly margin change · − accruals.

**The strongest ranking scores built so far:**

| | IC 126 | non-overlap t 126 | top-decile excess 126 | IC by period 20-22 / 23-24 / 25-26 |
|---|---|---|---|---|
| SMALL | 0.106 | **5.18** | +14.3 % | 0.095 / 0.132 / 0.094 |
| MID | 0.084 | **3.12** | +8.1 % | 0.056 / 0.074 / 0.161 |
| MID + "avoid steady high ROCE" | 0.106 | 4.06 | +8.3 % | 0.076 / 0.107 / 0.174 |

**But the book results swing with the start month.** SMALL template (top 10, sell below 30):
- From 2022-06: +0.8 %/yr, t 0.19, grade C.
- From 2019-12: +18.4 %/yr, t 2.99, 7 of 7 years positive.
- Both runs cover the same 2022-26 years. That is what prompted the timing-luck test.

MID template: +5.3 %/yr, t 0.94, grade C.

### Timing luck ([`tools/lh_timing_luck.py`](../../tools/lh_timing_luck.py)): the same rule started in each of the 12 months 2022-06 … 2023-05, all to 2026-10, after costs and tax

| book | starts beating the index | median excess/yr | range | median t |
|---|---|---|---|---|
| SMALL tactical `fast_select` top 20 | **12/12** | +11.2 % | +10.6 … +12.2 % | 1.40 |
| SMALL `slow_v2` top 20 | **12/12** | +9.3 % | +6.0 … +15.8 % | 1.86 |
| SMALL `slow_v2` top 10 | 12/12 | +13.9 % | +0.3 … +25.9 % | 2.00 |
| SMALL `slow_select` top 20 | 11/12 | +8.1 % | −0.1 … +25.3 % | 1.47 |
| SMALL tier model v1 top 20 | 11/12 | +7.0 % | −1.8 … +12.1 % | 1.54 |
| SMALL tier model v1 top 10 | 8/12 | +0.6 % | −9.4 … +10.9 % | 0.19 |
| **SMALL `slow_select` top 20 + tactical, 50/50** | **12/12** | +8.1 % | +4.5 … +15.2 % | **2.04** |
| SMALL tier model v1 top 20 + tactical, 50/50 | 12/12 | +7.4 % | +4.1 … +10.1 % | 1.96 |
| MID `slow_v2` top 20 | 12/12 | +5.7 % | +2.3 … +10.6 % | 1.00 |
| MID tier model v1 top 20 | 11/12 | +4.2 % | −1.4 … +9.6 % | 1.10 |
| MID `slow_select` top 20 | 5/12 | −0.4 % | −5.8 … +5.9 % | 0.00 |
| MID tactical `fast_select` top 20 | 0/12 | −2.4 % | −4.0 … −1.2 % | −0.77 |

Read:
- **Single-start book tests are noisy.** Top-10 books swing by up to 30 points between start months. Top 20 is far more stable, so **hold 20, not 10**, and judge books across staggered starts.
- **SMALL is robust.** The tactical book and `slow_v2` beat the index from every start. The slow + tactical combination beats it from every start with a median t of 2.0.
- **A higher IC did not give a better top-20 book.** The tier model v1 ranks best by IC, but its book is no better than `slow_v2`. The extra factors improve the middle of the ranking, not the top.
- **MID:** `slow_v2` top 20 beats the Midcap 150 from every start, but by only +5.7 %/yr at t 1.0. It is consistent but small: grade C on t, though the most robust MID result so far.
- **MID tactical fails** (0/12 starts; 4 of 12 variants beat the index in the grid; DSR 0.50).
- MID `live` is in-sample (+18.2 %, t 4.8) and is not evidence.

### Feature engineering: fast → slow ([`tools/lh_fast2slow.py`](../../tools/lh_fast2slow.py), pre-registered; 14 fast factors × 4 transforms × 2 tiers = 112 tests)
- **Transforms**, each over the stock's own monthly series:
  - avg6 / avg12: the 6- or 12-month average;
  - persist6: the share of the last 6 months in the tier's top third;
  - trend6: the latest value minus the prior 6-month average.
- **"Converted"** needs all of: non-overlap t ≥ 2.0 at 126 sessions, IC at 126 ≥ IC at 21, the sign held in every period, and a larger IC than the raw factor.
- **15 conversions met that rule.** The credible ones have the full 2019–26 history:

| fast factor → slow feature (SMALL) | raw IC 21 → 126 | converted IC 21 → 126 → 252 | non-overlap t 126 | IC 20-22 / 23-24 / 25-26 | Bonferroni |
|---|---|---|---|---|---|
| **announcement CAR, 6-month persistence** (repeatedly good reactions to results) | 0.029 → 0.046 | 0.029 → **0.061** → 0.047 | **5.61** | 0.050 / 0.071 / 0.069 | yes |
| **announcement CAR, 6-month average** | | 0.028 → **0.066** → 0.051 | **5.10** | 0.049 / 0.086 / 0.073 | yes |
| **closing strength, 6-month average** (stocks that keep closing near the day's high) | 0.022 → 0.050 | 0.042 → 0.065 → 0.053 | 3.43 | 0.053 / 0.083 / 0.062 | yes |
| VWAP deviation, 6-month persistence | 0.007 → 0.024 | 0.026 → 0.041 → 0.040 | 2.97 | 0.020 / 0.071 / 0.040 | yes |
| short-term reversal, 6-month average | −0.006 → 0.025 | 0.014 → 0.057 → 0.051 | 2.41 | 0.051 / 0.082 / 0.035 | no |
| relative turnover, 6-month persistence (−: persistently heavy trading lags) | −0.007 → −0.023 | −0.015 → −0.041 → −0.057 | −2.19 | −0.054 / −0.027 / −0.038 | no |

- **Not credible:** MID `iv_skew_25d` avg / persist (IC 0.17–0.20, but only 2025-26 data, so the t is unreliable) and SMALL `short_selling_signal` (2025-26 only).
- **Stays fast** (no transform helps): delivery anomaly z, smart-money score, lottery, intraday range, bulk deals. `avg_delivery_pct_30d` is already slow raw (t 2.92) and smoothing adds nothing.
- **Read:** averaging the *reaction to results* over 6 months turns a short-window event signal into one of the strongest slow signals we have. It is "earnings momentum told by the market". Closing strength behaves the same way.
- **Caveat:** these were chosen out of 112 tries on 2019-26. Candidates for a pre-registered tier model v2, not wired.

## 6. Does a "good enough" factor bar help MID or LARGE? ([`tools/lh_relax_test.py`](../../tools/lh_relax_test.py) → [ADR 0074](../decisions/0074-good-enough-factor-admission-mid.md))
Setup:
- Walk-forward, factors chosen each month from past data only.
- **Strict** = ADR 0043 (|t| ≥ 2.5).
- **Relaxed** = strict plus grade-B factors (1.5 ≤ |t| < 2.5, same sign in both halves of training) at half weight.
- Books: top 20, 12 start months, after costs and tax.

| tier · model | strict: median excess · starts | relaxed | IC strict → relaxed | verdict (pre-registered) |
|---|---|---|---|---|
| MID fast | −2.2 % · 0/12 | **+3.3 % · 12/12** | 0.048 → 0.050 | **relax (MID)** |
| MID slow | +1.3 % · 9/12 | +0.9 % · 9/12 | 0.087 → 0.104 | keep |
| LARGE fast | +5.1 % · 11/12 | +4.8 % · 12/12 | 0.008 → 0.047 | keep |
| LARGE slow | +5.6 % · 12/12 | +5.3 % · 12/12 | −0.004 → 0.061 | keep |

- The relaxed MID fast model adds the momentum family at half weight (66–91 % of months).
- **Relaxing lifts IC everywhere, but books only in MID fast.**
- LARGE books beat the NIFTY 50 from 12/12 starts at ~+5 %/yr but t ≈ 0.9 (grade C): consistent, small, unproven.

## 7. Full market 2010 → 2026, delisted names included (plan 0025 5.2; [`tools/lh_price_history.py`](../../tools/lh_price_history.py), [`tools/monitor_events_full.py`](../../tools/monitor_events_full.py))

**Data.**
- Legacy NSE bhavcopy backfilled 2010-01 → 2018-02: 2,018 days, 0 bad days, +1.57 M universe rows.
- Corporate actions loaded back to 2010.
- Panel: 4,831 names (2,447 in today's universe), 183 monthly anchors 2011-02 → 2026-04 (~30 independent 6-month windows instead of 13).
- 2,161 split-like one-day jumps in unlisted names were neutralised.

**Groups.** Delisted names have no market cap, so groups are by liquidity rank: T1 = ranks 1–100, T2 = 101–250, T3 = 251–1000. Delisting returns are kept.

| signal | T3 (small proxy): IC 126 · non-overlap t · top-decile excess | IC 2011-14 / 15-19 / 20-22 / 23-26 | survivors-only t | T2 t | T1 t |
|---|---|---|---|---|---|
| **position in the 52-week range** | 0.152 · **6.33** · +10.4 % | 0.194 / 0.192 / 0.059 / 0.127 | 4.75 | **3.00** | 1.86 |
| **6-month momentum** | 0.117 · **6.04** · +11.8 % | 0.170 / 0.129 / 0.061 / 0.087 | 4.69 | 2.59 | 1.56 |
| 12-1 momentum | 0.106 · 4.68 · +10.8 % | 0.158 / 0.119 / 0.025 / 0.098 | 3.36 | 1.54 | 0.92 |
| low volatility | 0.096 · 3.12 · +3.0 % | 0.135 / 0.164 / 0.001 / 0.032 | 1.78 | 2.25 | 1.53 |
| short-term reversal (−21-day return) | −0.058 · −3.39 | all negative | −2.37 | −1.55 | −0.23 |

- **Momentum and the 52-week position pass the robustness bar in T3** (t ≥ 2, positive in 4/4 periods), and the 52-week position does in T2.
- **Survivorship had *understated* them.** Delisted names were mostly weak-momentum losers, which these signals avoid.
- In small caps last month's winners keep winning: there is no short-term reversal to trade.
- T1 (large): nothing reaches t 2 (pos_52w 1.86).

**Price crash, full market.** A last-month return in the group's bottom 5 %:
- T3: median −7.0 % over 126 sessions; false alarms 40.6 %; t −0.75.
- 3.5 % of these stopped trading, against 1.5 % for all names.
- Still a review flag, not an exit.

**Warning signs, full market.**
- BSE events mapped to NSE names through `scrip_master.nse_symbol`. 83 % of the non-universe events are BSE-only companies, out of scope.
- **Pooled over all names (the ex-ante view), every event is still noise:** false alarms 44–48 %, |t| ≤ 1.85.
- The subset that later left the universe shows large losses: director resignation median −25 %, false alarms 15 %, n 54. But membership of that subset is known only with hindsight, so it cannot grade the signal.

**Implication.** Momentum and the 52-week position are the most robust slow signals we have, over 15 years and with delisted names. They deserve more weight in the slow book. The next pre-registered slow score should be built around them (`slow_v2` carries only 6-month momentum, at one-third weight).

## 8. slow_v3 — momentum-centred slow score ([`tools/lh_slow_v3.py`](../../tools/lh_slow_v3.py), pre-registered; plan 0025 2.5)
`slow_v3` = equal-weight percentiles of the 52-week position, 6-month and 12-month momentum. `slow_v3q` adds quality × value. Template book: monthly · top 20 · sell below 60 · 12-month hold.

| test | slow_v3 median excess · starts beating · median t · worst 12 months | comparison |
|---|---|---|
| 15 years, T3 small proxy, vs the group's equal-weight average incl. delisted (pre-tax, after costs) | +7.7 %/yr · 12/12 · 1.99 · **−35.3 %** | 6-month momentum alone +7.2 % · t 1.90; 52-week position alone +5.0 % · t 1.58 |
| 15 years, T2 mid proxy | +8.7 %/yr · 12/12 · **2.67** · −23.0 % | 6-month momentum alone +4.4 % · t 1.50 |
| 2019+, SMALL vs NIFTY SMALLCAP 250 (measured costs, Indian tax) | **+11.6 %/yr** · 12/12 · 1.60 · −15.2 % | slow_v2 +9.3 % · t 1.86 · −16.9 %; slow_v3q +4.5 % · t 0.94 |
| 2019+, MID vs NIFTY MIDCAP 150 | **+8.4 %/yr** · 12/12 · 1.66 · −9.9 % | slow_v2 +5.7 % · t 1.00; slow_v3q +5.2 % |

**Pre-registered decision: keep slow_v2.** The 15-year small-proxy book fails the worst-12-month bar (−35 % against −15 %).
- The worst stretch for the 2011-02 start was −20.4 % in the 12 months to May 2016 (the 2015 momentum crash).
- Yearly excess for that start: +10.5 / +13.2 / +19.7 / +14.6 / **−9.0** (2015) / +7.9 / −1.4 / +21.0 / +1.5 / +11.5 / **+66.8** (2021) / **−12.2** (2022) / **−6.8** (2023) / +7.6 / −2.3 / +3.2 %.

Read:
- **slow_v3 earns more but crashes harder.** That is the classic momentum profile: big years (2021) paid for by sharp losing streaks (2015, 2022-23).
- Adding value / quality (`slow_v3q`) made it worse.
- MID `slow_v3` passes every recent bar (12/12, t 1.66, worst −9.9 %), but its 15-year mid proxy has a −23 % worst year. MID stays the index.
- **Pre-registered next idea, not run:** a 50/50 slow_v2 + slow_v3 blend, to keep the momentum edge with a smaller crash.

## 9. 50/50 blend of slow_v2 and slow_v3 ([`tools/lh_blend_v23.py`](../../tools/lh_blend_v23.py), pre-registered)
Template book, 12 starts per window, after measured costs and Indian tax, SMALL vs NIFTY SMALLCAP 250.
- **Window A** (starts 2022-06 … 2023-05):

| book | median excess | median t | worst 12 months |
|---|---|---|---|
| slow_v2 | +9.3 % | 1.86 | −16.9 % |
| blend | +9.6 % | 2.00 | −13.2 % |
| slow_v3 | +11.6 % | 1.60 | −15.2 % |
| two books 50/50 | +8.5 % | 1.87 | −11.8 % |

- **Window B** (starts 2019-12 … 2020-11, the crash test):

| book | median excess | median t | worst 12 months |
|---|---|---|---|
| slow_v2 | +14.2 % | 2.09 | −23.5 % |
| blend | +11.4 % | 1.91 | −21.3 % |
| slow_v3 | +9.6 % | 1.56 | −20.5 % |
| two books 50/50 | +9.4 % | 2.31 | −20.3 % |

- **Verdict (pre-registered): keep slow_v2.** The blend fails window B's −15 % bar.
- Caveat: the incumbent slow_v2 fails that bar too (−23.5 %). Every option crossed −15 % in the 2020-21 stretch, so the bar as written can only keep the incumbent.
- MID: blend +8.2 % (A) / +3.8 % (B); the two-book pair +6.1 % / +6.5 % with t 1.83 / 2.13.
