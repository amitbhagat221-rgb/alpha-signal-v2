# Promotion review — October 2026

Review of every production weight on the corrected evidence (plan 0020, [factor-audit-2026-10.md](factor-audit-2026-10.md) §8). Run 2026-10-03. **A proposal for Amit: no weight was changed by this review.**

The evidence is the 20-day rank IC on the rebuilt panel: tier as of each date, entry the session after the signal, adjusted total-return label, 202 anchors. Rules applied are the standing ones (ADR 0049): |t| ≥ 1.5 on the tier with at least 20 anchors, sign matching the economic prior, one representative per family unless two members are nearly uncorrelated, a cap of 0.35 per factor, Σ|w| = 1 per tier. No weight is derived from a formula.

## 1. What goes, what stays

| Tier | Factor | Weight now | t | Recent t (since 2024-09) | Call |
|---|---|---|---|---|---|
| LARGE | announcement_car | 0.35 | 2.65 | −0.16 | keep |
| LARGE | consensus | 0.28 | 0.11 | — | **drop** |
| LARGE | sector_tilt | 0.22 | 0.54 | — | **drop** |
| LARGE | book_to_price | 0.15 | 1.26 | — | **drop** |
| MID | iv_skew_25d | 0.26 | 4.06 | 3.80 | keep |
| MID | accruals (cf) | −0.22 | −1.92 | −1.92 | keep, smaller |
| MID | book_to_price | 0.20 | 1.18 | — | **drop** |
| MID | piotroski | 0.18 | 3.63 | 3.63 | keep |
| MID | governance_resignation | −0.14 | −0.30 | — | **drop** |
| SMALL | delivery_anomaly_z | 0.26 | 5.52 | 5.33 | keep |
| SMALL | consensus | 0.16 | 1.39 | — | **drop** |
| SMALL | sector_tilt | 0.16 | 3.59 | 2.00 | keep |
| SMALL | announcement_car | 0.14 | 5.51 | 3.75 | keep, larger |
| SMALL | book_to_price | 0.12 | 0.71 | — | **drop** |
| SMALL | pledge_quality | 0.10 | 0.56 | — | **drop** |
| SMALL | piotroski | 0.06 | 4.26 | 4.26 | keep, larger |

## 2. Candidates from the library

Factors clearing the bar that are not weighted today, with what each adds when all are ranked together (25 monthly dates since 2024-09) and how it overlaps the others:

| Tier | Factor | t | Recent t | Adds on top of the rest (t) | Note |
|---|---|---|---|---|---|
| MID | residual_momentum_12_1 | 3.33 | 2.02 | 0.29 | 0.92 correlated with `mom_12m_adj` (4.00): one of the two |
| MID | consensus (reported EPS growth) | 2.31 | 3.48 | 3.26 | works in MID, not in LARGE or SMALL |
| MID | pcr_oi | 3.06 | 2.87 | 2.00 | second options factor (0.14 correlated with skew); held back: one per family |
| MID | announcement_car | 1.88 | 0.73 | 0.61 | passes the bar, weak recently |
| SMALL | residual_momentum_12_1 | 3.98 | 2.40 | 1.59 | |
| SMALL | avg_delivery_pct_30d | 3.67 | 3.10 | 2.56 | 0.06 correlated with `delivery_anomaly_z` (level vs surprise); 0.93 with `smart_money_score` |
| SMALL | earnings_persistence | −3.37 | −3.28 | −2.74 | steadier earnings do better; 28 anchors |
| SMALL | low_vol_252d | −2.96 | −2.66 | −2.23 | 0.46 correlated with `max_lottery_21d` (−3.48) |
| LARGE | iv_skew_25d | 1.86 | 1.46 | 0.80 | the only LARGE candidate with a positive recent window |
| LARGE | asset_growth_yoy | −2.37 | −0.97 | −0.58 | sign matches the prior (low asset growth does better) |
| LARGE | forward_looking_intensity | 2.18 | 0.31 | −0.02 | transcript language; weak recently |

Not eligible although |t| ≥ 1.5: `gross_profitability` and `interest_coverage` in LARGE (the sign is opposite to the prior), the macro betas (an exposure, not a selection signal), `news_volume` (21 anchors, 57% coverage).

## 3. Variants tested

Combined score per tier on monthly anchors: rank IC, and the 20-day return of the top names over the tier average. The weights were chosen on this same history, so every "proposed" figure is optimistic.

| Tier | Weights | Dates | IC t | Top 5 over tier | Top 15 over tier | Top minus bottom tenth | (t) |
|---|---|---|---|---|---|---|---|
| LARGE | current | 80 | 2.76 | 0.71% | 0.58% | 1.29% | 2.4 |
| LARGE | proposed | 80 | 4.18 | 0.73% | 0.89% | 1.42% | 2.6 |
| LARGE | current, since 2024-09 | 25 | −0.98 | 0.23% | 0.22% | 0.28% | 0.5 |
| LARGE | proposed, since 2024-09 | 25 | 0.96 | −0.01% | 0.16% | −0.37% | −0.6 |
| MID | current | 26 | 3.31 | 1.20% | 0.70% | 1.49% | 2.1 |
| MID | drop the unproven only | 25 | 3.94 | 0.90% | 0.14% | 1.39% | 1.9 |
| MID | proposed | 26 | 4.81 | 2.43% | 1.49% | 3.06% | 3.7 |
| SMALL | current | 79 | 9.15 | 2.49% | 1.84% | 1.86% | 6.3 |
| SMALL | drop the unproven only | 79 | 10.32 | 0.54% | 1.40% | 1.72% | 5.4 |
| SMALL | proposed (+ momentum, delivery level) | 79 | 9.50 | 0.88% | 1.49% | 2.66% | 7.9 |
| SMALL | + earnings stability, low volatility | 79 | 9.51 | 2.42% | 1.11% | 2.33% | 7.1 |

Reading:
- **MID:** the proposed set is better on every measure.
- **SMALL:** the tenth-against-tenth spread, the steadiest measure, improves from 1.86% to 2.66%. The top-5 and top-15 figures are noisy (five names out of about 1,600) and do not agree with each other; on those the current weights are not worse. The gain is in the ranking as a whole, not proven at the very top.
- **LARGE:** better on the full history, nothing on the last 25 months under either set. No LARGE factor survives the multiple-testing haircut. This tier is unproven whatever the weights.

## 4. Proposed weights

| Tier | Proposed |
|---|---|
| LARGE | announcement_car 0.35 · iv_skew_25d 0.25 · asset_growth_yoy −0.20 · forward_looking_intensity 0.20 |
| MID | iv_skew_25d 0.24 · residual_momentum_12_1 0.20 · piotroski 0.18 · consensus 0.16 · accruals −0.12 · announcement_car 0.10 |
| SMALL | delivery_anomaly_z 0.24 · announcement_car 0.22 · sector_tilt 0.14 · piotroski 0.14 · residual_momentum_12_1 0.14 · avg_delivery_pct_30d 0.12 |

Held for the next review, not proposed now: `pcr_oi` MID, `earnings_persistence` and `low_vol_252d` SMALL (each adds on its own; added together they did not improve the top of the SMALL ranking), `max_lottery_21d` SMALL (fast-moving: turnover cost first).

## 5. What the review cannot say

- The history still holds only today's universe for the fundamentals factors; the price factors were checked against the full market and held (survivorship study).
- Piotroski, accruals and the MID combined score rest on 26 anchors from one period.
- Costs are not in these figures. Momentum and delivery level are slow (rank autocorrelation 0.90 and 0.98), so the proposed sets should not raise turnover; this was not simulated.
- Financials in MID are still ranked on fewer factors than the rest (audit R9).
