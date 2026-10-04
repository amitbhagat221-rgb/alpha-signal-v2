# ADR 0063 — Production weights re-set on the corrected evidence

**Status:** accepted 2026-10-03 (Amit approved both proposals of the promotion review). Supersedes the weight table of ADR 0049 / 0050; the rules of ADR 0049 stand.
**Evidence:** [promotion-review-2026-10.md](../studies/promotion-review-2026-10.md), on the panel rebuilt by [ADR 0062](0062-factor-audit-fixes-one-model-change.md) (tier as of each date, next-session entry, adjusted label).

## Decision

| Tier | Weights |
|---|---|
| LARGE | announcement_car 0.35 · iv_skew_25d 0.25 · asset_growth_yoy −0.20 · forward_looking_intensity 0.20 |
| MID | iv_skew_25d 0.24 · residual_momentum_12_1 0.20 · piotroski 0.18 · consensus 0.16 · accruals −0.12 · announcement_car 0.10 |
| SMALL | delivery_anomaly_z 0.24 · announcement_car 0.22 · sector_tilt 0.14 · piotroski 0.14 · residual_momentum_12_1 0.14 · avg_delivery_pct_30d 0.12 |

- **Un-wired** (below |t| 1.5 on the corrected panel): `book_to_price` in all three tiers, `consensus` in LARGE and SMALL, `sector_tilt` in LARGE, `governance_resignation` in MID, `pledge_quality` in SMALL. They stay computed and tested.
- **Wired for the first time:** `residual_momentum_12_1` (MID, SMALL), `avg_delivery_pct_30d` (SMALL), `asset_growth_yoy` and `forward_looking_intensity` (LARGE), `consensus` and `announcement_car` in MID, `iv_skew_25d` in LARGE. Each has an eligibility rule.
- Every weight now clears the 1.5 bar with at least 20 anchors and a sign that matches its prior.

## Why

Eight of the sixteen old weights had lost their evidence once the test stopped using today's tiers, the unadjusted label and (consensus) results known before they were published. On the same history the combined score improves in MID on every measure (top tenth minus bottom tenth over 20 days: 1.49% → 3.06%) and in SMALL as a ranking (1.86% → 2.66%).

## What this does not claim

- **LARGE is still unproven.** No LARGE factor survives the multiple-testing haircut, and neither the old nor the new set shows anything over the last 25 months. The new set is the one the rules allow; it is not evidence that LARGE picks work.
- In SMALL the top-5 and top-15 returns on the history are not better than under the old weights; the gain is in the ranking as a whole.
- The weights were chosen on the history they are measured on. The honest test is the months from here: `pick_outcomes` and `python -m tools.factor_audit --wired`.
- Financials in LARGE are scored on three of four factors (asset growth does not apply): 40% of the top 20 against 25% of the tier on 2026-10-03 (audit R9, open).

## Held for the next review

`pcr_oi` MID (adds on top of skew), `earnings_persistence` and `low_vol_252d` SMALL, `max_lottery_21d` SMALL (turnover first), `governance_resignation` SMALL (t = −2.33).

## Effect on the ranking (2026-10-03 inputs, old weights vs new)

Rank correlation LARGE 0.42, MID 0.60, SMALL 0.81; top 10 kept 2, 2 and 2. Stocks passing the coverage gates: LARGE 96 (was 103), MID 140 (140), SMALL 1,565 (1,609).
