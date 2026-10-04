# ADR 0064 — A factor with no value counts as neutral; a result print is found wherever it is filed

**Status:** accepted 2026-10-04 (Amit: "close all open items"). Amends the scoring rule of ADR 0024 / 0048 (renormalise over the factors that apply); the eligibility table and `eligible_coverage` are unchanged.

## Decision

1. **Scoring.** A wired factor with no value for a stock contributes `config.MISSING_FACTOR_SCORE` = 0.5, the middle of the tier. Its weight is no longer spread over the factors that do have a value. `base_score = Σ |w| × percentile (0.5 where missing) ÷ Σ |w|`.
2. **Result filings.** A quarterly-result print is a `bse_announcements` row of category 'Result' **or** an 'Outcome of Board Meeting' whose headline says financial results (`factors.RESULT_FILING_SQL`, one rule for the earnings-window factor, PEAD and the eligibility SQL).
3. **Demergers** are price adjustments: the ex-day close over the close before, when below 0.8 (`tools/compute_corporate_adjustments.py`).
4. **The thin-tier check** compares ranked stocks with the tier's size (under 80% = thin), not with a flat 100.

## Why

- Spreading a missing factor's weight made a stock scored on fewer factors louder. Financials, which have no accruals, Piotroski or asset growth, were 31% of the MID top 20 against 14% of the tier (audit R9), 40% against 25% in LARGE on 2026-10-04.
- On the corrected history the neutral rule is as good or better in every tier:

| Tier | Rule | IC t | Top 15 over tier | Top tenth minus bottom tenth | Financials in top 20 / in tier |
|---|---|---|---|---|---|
| LARGE | spread | 4.18 | 0.89% | 1.42% | 15% / 16% |
| LARGE | neutral | 4.15 | 0.77% | 1.89% | 13% / 16% |
| MID | spread | 4.81 | 1.49% | 3.06% | 18% / 14% |
| MID | neutral | 4.84 | 1.77% | 3.31% | 15% / 14% |
| SMALL | spread | 9.50 | 1.49% | 2.66% | — |
| SMALL | neutral | 9.57 | 1.48% | 2.45% | — |

- The first run on the new weights (2026-10-04) ranked 96 LARGE stocks, under the check's flat 100, and raised a CRITICAL. Six of the seven missing were large banks and Coal India: their results are filed as board-meeting outcomes, so the earnings-window factor (0.35 of LARGE) had no value for them. With rule 2, coverage of that factor rises 0.87 → 0.92 in LARGE, 0.89 → 0.95 in MID, 0.83 → 0.87 in SMALL (91 stocks gained), and 101 of 103 LARGE stocks pass the coverage gates.
- Vedanta, Siemens, Tata Motors, HEG and others showed a 40–80% one-day "loss" on their demerger day in every price factor and in the return label.

## Consequences

- A stock with thin data is pulled towards the middle of its tier and reaches the top only on strong values for what it has. `pick_breakdown` shows a missing factor with a null percentile and its neutral contribution.
- The pick gates (`eligible_coverage`, `weight_coverage`) still decide who is published.
- The ranking of 2026-10-05 changes again, less than on 2026-10-04.
