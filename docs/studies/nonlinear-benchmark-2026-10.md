# Non-linear models on the factor library — 2026-10-10

**Verdict: no non-linear model beats a linear model on the same inputs, in any tier.** The largest gain, depth-3 boosted trees in MID, is +0.020 mean IC over ridge (paired t 1.99) with no gain in the top tenth (t 0.96), and it is the best of 7 pre-registered models, so it is below any multiple-testing bar. Nothing changes in production. Don't re-run this with tuning; see "What would change the verdict".

Tool: `python -m tools.nonlinear_benchmark` (read-only; per-anchor records in `output/nonlinear_benchmark.pkl`). Protocol = `tools/walk_forward.py`: 82 monthly anchors of `daily_snapshots_pit` (2019-12 → 2026-09), adjusted 20-day label, one-anchor embargo, expanding window, ≥12 training anchors → 69 test months (2021-01 → 2026-09). Inputs: 98 factors as within-tier percentiles; target: the within-tier percentile of the 20-day return. One fixed configuration per model, chosen before any result; the only fitting on data is RidgeCV's penalty, on the training window.

## Out-of-sample rank IC (69 months)

| tier | model | mean IC | t | top tenth vs tier, % / 20d | top-tenth turnover | paired t vs ridge |
|---|---|---|---|---|---|---|
| LARGE | live weights (hindsight) | 0.063 | 4.76 | 0.68 | 0.47 | 1.41 |
| LARGE | ridge, all factors | 0.033 | 2.01 | 0.15 | 0.55 | — |
| LARGE | splines (gam) | 0.034 | 2.17 | 0.42 | 0.54 | 0.08 |
| LARGE | boosted depth 3 | 0.028 | 1.58 | 0.19 | 0.66 | −0.42 |
| LARGE | select (walk-forward) | 0.006 | 0.37 | 0.20 | — | −1.17 |
| MID | boosted depth 3 | 0.066 | 5.09 | 0.73 | 0.64 | **1.99** |
| MID | live weights (hindsight) | 0.060 | 4.25 | 1.74 | 0.40 | 0.73 |
| MID | splines (gam) | 0.056 | 3.85 | 0.37 | 0.59 | 1.28 |
| MID | boosted stumps | 0.054 | 3.62 | 0.45 | 0.58 | 0.83 |
| MID | ridge, all factors | 0.047 | 3.03 | 0.40 | 0.56 | — |
| MID | select (walk-forward) | 0.026 | 1.95 | 0.12 | — | −0.93 |
| SMALL | random forest | 0.085 | 9.13 | 0.98 | 0.56 | 1.55 |
| SMALL | splines (gam) | 0.082 | 10.38 | 0.95 | 0.57 | 1.20 |
| SMALL | boosted stumps | 0.081 | 9.90 | 0.75 | 0.58 | 0.64 |
| SMALL | ridge, all factors | 0.078 | 8.54 | 0.72 | 0.55 | — |
| SMALL | boosted depth 3 | 0.076 | 9.79 | 0.80 | 0.64 | −0.42 |
| SMALL | live weights (hindsight) | 0.074 | 10.29 | 1.28 | 0.65 | −0.65 |
| SMALL | select (walk-forward) | 0.051 | 6.73 | 0.78 | — | −3.41 |

Per-tier fits (`ridge_tier`, `gbm_d3_tier`) were no better than pooled ones in any tier, except `ridge_tier` in SMALL (t 2.05 vs pooled ridge). Full table and IC by year: `output/nonlinear_benchmark.log`.

## What the numbers say

1. **Shape and interactions add nothing you can bank.** Interactions (depth 3 − stumps): LARGE +0.005 (t 0.52), MID +0.012 (t 1.48), SMALL −0.005 (t −1.35). Shape (gam − ridge): t 0.08 / 1.28 / 1.20. SHAP on the depth-3 model shows near-monotone main effects (delivery %, sector tilt, announcement CAR, residual momentum). The one kink is low volatility, where only the most volatile fifth is penalised. Interaction terms are spread thin across many pairs: the largest, forward-looking intensity × low volatility, is a fifth of a top main effect.
2. **No out-of-sample model buys a better top tenth than the live weights.** The live weights have the best top-tenth spread in every tier (SMALL 1.28% vs 0.72–1.08%), even though they were chosen on this history. The ML gains are in the broad rank IC, not at the top that we buy.
3. **LARGE stays empty.** Every model is ≤ 0.03 IC from 2025 onward, consistent with [the October LARGE study](large-factors-2026-10.md).
4. **Side result: "all factors, shrunk" beats "pick the 6 strongest" out of sample** (ridge − select, SMALL +0.028 IC, t 3.41). It does not carry to the top tenth (t −0.28), so the selection rule costs breadth, not picks.

## What would change the verdict

- Much longer history: the pre-2020 bhavcopy panel (price/liquidity factors to the 1990s, research 0005). The literature's ML gains need decades of data.
- Daily or weekly anchors with a short label for the price and liquidity factors, where trees have found interactions in other markets.
- A cost-aware objective trained on the top tenth, not the full ranking.
