# New LARGE-cap factors, 2026-10: verdict EMPTY (no candidate PROMISING)

Verdict: of 21 new candidates tested, none reaches the PROMISING bar on LARGE (|t| >= 2.5, >= 36 anchors,
halves same sign, |corr| < 0.5 with wired factors). Best new LARGE reading is `fip_id` t = -1.93 (WEAK,
below the bar and nowhere near the multiple-testing bar). The only new LARGE |t| >= 2.5 is `ann_car_ind`
(t = +2.97), the wired `announcement_car` re-expressed (corr 0.92), not new information. LARGE still has no
proven factor beyond what plan 0020 listed. Ownership-flow factors are BLOCKED by data depth (below), not refuted.

## Method
- Script: `tools/large_factor_study.py` (read-only; `ALPHA_DB=... python -m tools.large_factor_study --md PATH`).
- Labels and tiers from `daily_snapshots_pit`: `fwd_return_20d` (entry next session, 20 sessions, adjusted total
  return), `cap_tier` = point-in-time tier. Monthly first-business-day anchors only (82 anchors, 2019-12 to 2026-10).
- Evidence engine: `tools.backtest_pit._compute_ic` (Spearman per anchor, >= 20 stocks) and `_aggregate` (t = ICIR * sqrt(n)).
  Halves: anchors before 2023-01-01 vs after; "agree" needs the same sign in both halves and in the full mean, >= 6 anchors each.
- Correlation: mean per-anchor Spearman within LARGE against wired `announcement_car`, `iv_skew_25d`, `asset_growth_yoy`, `forward_looking_intensity`.
- As-of: returns/volume only through the anchor row (fully adjusted prices give the same returns as PIT-strict adj_close for any window ending at or before the anchor);
  shareholding via `pit.knowable_shareholding` (21-day lag); result filings only from >= 335 days before the anchor; industry = `stocks.industry` (38 groups, static label).
- Caveats: price history starts 2018-03 (backfill covers about 70% of sids pre-2023), so 12-1 momentum starts about 2019-03 and seasonality needs >= 3 prior same-month years
  (66 anchors on LARGE, effectively 2021+, so the 2020-22 half is thin). Only about 26 anchors carry option data and about 20 carry usable QoQ shareholding.

## Hypotheses counted
21 new candidates (x3 tiers = 63 cells): mom_12_1 (plain reference), fip_id, mom_cont, seas_same, seas_other, seas_diff, high52, high52_ind,
ivol60, ivol60_ind, st_rev_ind, d_fii, d_mf, d_dii, inst_breadth, abvol, abvol_signed, ann_car_ind, resmom_ind, beta252, ann_premium.
Plus 20 existing panel columns re-read (already inside the ~269 prior count). Running total about 290, so the Bonferroni bar stays near |t| 4.2:
|t| >= 2.5 would only have been necessary, not sufficient. Nothing new came close on LARGE.

Definitions: ID = sign(12-1 return) x (% negative days - % positive days) over sessions t-251..t-21; mom_cont = (within-tier pct rank of 12-1 return - 0.5) x (1 - within-tier pct rank of ID);
seasonality = mean return of the anchor's calendar month over the prior 5 years (>= 3), other = mean of the other months over the prior 60 (>= 36);
high52 = close / 252d max; ivol60 = residual std vs equal-weight market (60 sessions); abvol = log(5d mean volume / prior 50d mean), signed by the 5d return;
ann_premium = a result filing in the year-ago 30-day window (Frazzini-Lamont); *_ind = demeaned within `stocks.industry` at the anchor.
Item 8 (other documented effects, computable from existing tables): beta252 (betting against beta) and ann_premium.

## Results (printed by the script)

### NEW candidates

| signal | LARGE n | mean IC | t | H1 IC (20-22) | H2 IC (23-26) | halves | max abs corr wired | label | MID t | SMALL t |
|---|---|---|---|---|---|---|---|---|---|---|
| mom_12_1 | 82 | +0.0055 | +0.25 | +0.0156 | -0.0028 | split | 0.16 | DROP | 2.67 (n=82) | 2.70 (n=82) |
| fip_id | 82 | -0.0284 | -1.93 | -0.0278 | -0.0288 | agree | 0.10 | WEAK | 0.68 (n=82) | 1.64 (n=82) |
| mom_cont | 82 | +0.0133 | +0.66 | +0.0190 | +0.0086 | agree | 0.16 | DROP | 2.91 (n=82) | 3.09 (n=82) |
| seas_same | 66 | +0.0081 | +0.44 | +0.0165 | +0.0042 | agree | 0.09 | DROP | 0.36 (n=66) | 2.41 (n=66) |
| seas_other | 63 | -0.0038 | -0.14 | -0.0206 | +0.0029 | split | 0.31 | DROP | 0.40 (n=63) | -1.88 (n=63) |
| seas_diff | 63 | +0.0108 | +0.61 | +0.0220 | +0.0064 | agree | 0.05 | DROP | 0.35 (n=63) | 2.59 (n=63) |
| high52 | 82 | -0.0019 | -0.09 | +0.0008 | -0.0041 | split | 0.25 | DROP | 1.65 (n=82) | 3.31 (n=82) |
| high52_ind | 82 | +0.0158 | +0.90 | +0.0094 | +0.0210 | agree | 0.23 | DROP | 1.28 (n=82) | 2.78 (n=82) |
| ivol60 | 82 | -0.0025 | -0.12 | -0.0010 | -0.0037 | agree | 0.20 | DROP | -1.48 (n=82) | -5.07 (n=82) |
| ivol60_ind | 82 | -0.0228 | -1.47 | -0.0258 | -0.0203 | agree | 0.13 | DROP | -2.36 (n=82) | -5.90 (n=82) |
| st_rev_ind | 82 | -0.0165 | -1.23 | -0.0112 | -0.0209 | agree | 0.21 | DROP | -1.61 (n=82) | -1.72 (n=82) |
| d_fii | 20 | -0.0278 | -0.92 | +nan | -0.0278 | split | 0.08 | INSUFFICIENT (n<36) | -0.35 (n=20) | 1.35 (n=20) |
| d_mf | 20 | +0.0310 | +1.30 | +nan | +0.0310 | split | 0.06 | INSUFFICIENT (n<36) | 1.13 (n=20) | 3.37 (n=20) |
| d_dii | 20 | +0.0105 | +0.41 | +nan | +0.0105 | split | 0.10 | INSUFFICIENT (n<36) | 0.10 (n=20) | 2.22 (n=20) |
| inst_breadth | 20 | -0.0139 | -0.62 | +nan | -0.0139 | split | 0.04 | INSUFFICIENT (n<36) | -0.06 (n=20) | 4.27 (n=20) |
| abvol | 82 | -0.0202 | -1.28 | -0.0539 | +0.0075 | split | 0.03 | DROP | -0.02 (n=82) | 0.27 (n=82) |
| abvol_signed | 82 | -0.0007 | -0.06 | -0.0025 | +0.0009 | split | 0.05 | DROP | -0.87 (n=82) | -4.07 (n=82) |
| ann_car_ind | 82 | +0.0348 | +2.97 | +0.0529 | +0.0200 | agree | 0.92 | NOT NEW (corr>=0.5) | 1.23 (n=82) | 5.64 (n=82) |
| resmom_ind | 72 | +0.0184 | +1.13 | +0.0388 | +0.0062 | agree | 0.15 | DROP | 3.81 (n=72) | 3.56 (n=72) |
| beta252 | 82 | +0.0166 | +0.57 | +0.0048 | +0.0263 | agree | 0.30 | DROP | -0.18 (n=82) | -1.80 (n=82) |
| ann_premium | 53 | +0.0110 | +0.55 | -0.0027 | +0.0264 | split | 0.05 | DROP | -0.60 (n=60) | -1.78 (n=80) |

### Existing panel columns (re-read)

| signal | LARGE n | mean IC | t | H1 IC (20-22) | H2 IC (23-26) | halves | max abs corr wired | label | MID t | SMALL t |
|---|---|---|---|---|---|---|---|---|---|---|
| announcement_car | 82 | +0.0358 | +2.69 | +0.0487 | +0.0252 | agree | - | reference | 1.71 (n=82) | 5.75 (n=82) |
| asset_growth_yoy | 81 | -0.0377 | -2.33 | -0.0323 | -0.0420 | agree | - | reference | 0.42 (n=81) | 0.55 (n=81) |
| delivery_anomaly_z | 79 | +0.0138 | +0.99 | +0.0363 | -0.0031 | split | - | reference | 2.90 (n=79) | 6.27 (n=79) |
| forward_looking_intensity | 81 | +0.0411 | +2.18 | +0.0141 | +0.0626 | agree | - | reference | 1.01 (n=81) | 0.82 (n=81) |
| gross_profitability | 81 | -0.0507 | -2.29 | -0.0647 | -0.0396 | agree | - | reference | -1.45 (n=81) | 0.62 (n=81) |
| iv_percentile_1y | 25 | +0.0205 | +0.71 | +nan | +0.0205 | split | - | reference | -0.79 (n=25) | -0.06 (n=25) |
| iv_realised_spread | 26 | -0.0104 | -0.53 | +nan | -0.0104 | split | - | reference | 1.11 (n=26) | 0.19 (n=26) |
| iv_skew_25d | 26 | +0.0447 | +1.42 | +nan | +0.0447 | split | - | reference | 1.93 (n=26) | 0.18 (n=26) |
| iv_term_structure | 19 | +0.0320 | +0.67 | +nan | +0.0320 | split | - | reference | 0.54 (n=7) | - (n=0) |
| low_vol_252d | 75 | -0.0053 | -0.19 | -0.0162 | +0.0020 | split | - | reference | -0.70 (n=75) | -3.38 (n=75) |
| max_lottery_21d | 82 | -0.0022 | -0.12 | -0.0093 | +0.0035 | split | - | reference | -0.93 (n=82) | -3.66 (n=82) |
| mom_12m | 71 | +0.0178 | +0.87 | +0.0638 | -0.0088 | split | - | reference | 4.62 (n=71) | 4.43 (n=71) |
| mom_6m | 76 | +0.0107 | +0.52 | +0.0327 | -0.0045 | split | - | reference | 2.58 (n=76) | 3.12 (n=76) |
| pcr_oi | 26 | -0.0005 | -0.02 | +nan | -0.0005 | split | - | reference | 2.51 (n=26) | 1.34 (n=26) |
| pcr_volume | 26 | +0.0134 | +0.55 | +nan | +0.0134 | split | - | reference | 2.17 (n=26) | 1.53 (n=26) |
| position_52w | 82 | -0.0062 | -0.30 | -0.0006 | -0.0108 | agree | - | reference | 1.68 (n=82) | 2.98 (n=82) |
| promoter_qoq | 20 | +0.0292 | +1.41 | +nan | +0.0292 | split | - | reference | 0.41 (n=20) | 0.67 (n=27) |
| promoter_trend_4q | 11 | -0.0024 | -0.07 | +nan | -0.0024 | split | - | reference | -0.13 (n=11) | 1.63 (n=13) |
| residual_momentum_12_1 | 72 | +0.0275 | +1.33 | +0.0707 | +0.0015 | agree | - | reference | 3.97 (n=72) | 4.40 (n=72) |
| st_reversal_21d | 82 | -0.0124 | -0.75 | -0.0149 | -0.0104 | agree | - | reference | -0.53 (n=82) | -0.29 (n=82) |

Correlation with wired LARGE factors:

```
              announcement_car  asset_growth_yoy  forward_looking_intensity  iv_skew_25d  max_abs
abvol                     0.00             -0.01                      -0.03        -0.02     0.03
abvol_signed              0.05             -0.00                      -0.02        -0.00     0.05
ann_car_ind               0.92             -0.01                       0.02         0.05     0.92
ann_premium               0.04              0.03                       0.05        -0.00     0.05
beta252                   0.04              0.11                       0.30         0.03     0.30
d_dii                    -0.02              0.10                      -0.08         0.05     0.10
d_fii                     0.03             -0.08                       0.03        -0.03     0.08
d_mf                      0.00              0.06                      -0.04         0.06     0.06
fip_id                   -0.05             -0.03                      -0.10         0.03     0.10
high52                    0.25             -0.08                      -0.02         0.01     0.25
high52_ind                0.23             -0.06                      -0.03         0.07     0.23
inst_breadth             -0.02              0.03                       0.04         0.03     0.04
ivol60                    0.11              0.14                       0.20        -0.05     0.20
ivol60_ind                0.09              0.13                       0.01        -0.04     0.13
mom_12_1                  0.13              0.00                       0.16        -0.00     0.16
mom_cont                  0.12              0.01                       0.16         0.01     0.16
resmom_ind                0.15             -0.00                      -0.02         0.04     0.15
seas_diff                 0.02              0.02                      -0.01         0.05     0.05
seas_other                0.06              0.24                       0.31        -0.06     0.31
seas_same                 0.03              0.09                       0.09         0.04     0.09
st_rev_ind                0.21              0.00                      -0.01        -0.00     0.21
```

## Verdict per candidate (LARGE)
- DROP: mom_12_1, mom_cont (momentum works on MID t=+2.9 and SMALL t=+3.1, not LARGE t=+0.7; H1 only), seas_same, seas_diff, seas_other, high52, high52_ind, ivol60, ivol60_ind, st_rev_ind, abvol, abvol_signed, resmom_ind (H1-only, like residual_momentum_12_1), beta252, ann_premium.
- WEAK: fip_id t = -1.93 (halves agree, corr 0.10). Negative sign (higher discreteness, lower return) in both halves. Below the bar; re-test as anchors accrue, not a registry entry.
- NOT NEW: ann_car_ind (corr 0.92 with announcement_car).
- INSUFFICIENT / BLOCKED (data): d_fii, d_mf, d_dii, inst_breadth, 20 anchors only. `shareholding` is dense (about 2,000 sids) only from 2024-09; before that it holds 1 to 17 rows per quarter. Cannot reach the 36-anchor bar until a deep quarterly history exists (BSE SHP holders feed is the route; not touched here). Same for iv_* / pcr_* (about 26 anchors).
- Existing columns on LARGE: none reaches 2.5 (position_52w, st_reversal_21d, low_vol_252d, max_lottery_21d, mom_*, residual_momentum_12_1 all |t| < 1.4). Known readings reproduce (announcement_car 2.69, asset_growth_yoy -2.33, gross_profitability -2.29, forward_looking_intensity 2.18).
- Side observations (other tiers, not tested for promotion, same haircut applies): ivol60 SMALL t = -5.07, ivol60_ind SMALL -5.90, momentum variants MID/SMALL t = 2.7 to 4.6.

## What would falsify / change this
- fip_id: a LARGE t beyond -2.5 on further anchors with both halves negative would justify a promotion review; today it is -1.93 on 82 anchors.
- Ownership flows: re-run after shareholding history is backfilled to 2019 (about 80 anchors).

## If a candidate is ever registered (nothing proposed now; template for fip_id)
- Producer: `compute_information_discreteness(prices)` in a new `signals/information_discreteness.py`, PIT wrapper `pit_information_discreteness`.
- Inputs: `stock_prices` adj_close (PIT-strict adjustments), 253 sessions, >= 150 valid returns in the 12-1 window.
- Filing lag: none (price-only, knowable at the anchor close). Range [-1, 1]; monthly; no `weights`; bench until it clears the bar.

## Files and tests
- `tools/large_factor_study.py`, `docs/studies/large-factors-2026-10.md`. No DB writes, no registry or weights changes.
- `pytest tests/test_factor_registry.py tests/test_invariant_ratchets.py`: 19 passed.
