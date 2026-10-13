# Long horizon, step 1 — which factors are slow? (H1) — 2026-10-12

Plan 0024, H1. Pre-registered the same day, before any result. Read-only on the DB. Tools: `python -m tools.lh_labels` (labels), `python -m tools.lh_horizon` (this note's numbers). Machine-readable: `data/lh/horizon.json`, every test in `data/lh/horizon_tests.csv`.

## Verdict
**H1 passes in all three tiers on the plan's rule, but only MID and SMALL pass with something worth building on.**

The plan defines "slow" (6-month |t| ≥ 2.5, and the 6-month IC at least as large as the 1-month IC with the same sign), the multiple-testing haircut and the three-period sign check, but it does not write a single pass line per tier. I read H1 as **passing for a tier when at least one factor is slow, keeps its sign in 2020-22, 2023-24 and 2025-26, and survives the Benjamini-Yekutieli (BY) false-discovery haircut**. The orchestrator should confirm this reading.

| tier | slow | slow + same sign in all 3 periods | slow + survives BY | **all three** | slow + survives Bonferroni | fast |
|---|---|---|---|---|---|---|
| LARGE | 10 | 5 | 2 | **1** | 0 | 0 |
| MID | 21 | 11 | 9 | **6** | 3 | 1 |
| SMALL | 29 | 23 | 11 | **10** | 5 | 3 |

- **SMALL: a clear pass.** 10 factors pass all three tests. 4 of them also clear Bonferroni with the full history: `cons_beat_rate_4q` (6-month t +6.43), `value_composite` (+5.69), `sector_tilt` (+4.92) and `closing_strength_1m` (+4.47). The others are `position_52w`, `announcement_car`, `avg_delivery_pct_30d`, `mom_6m`, `rate_beta` (negative) and `accruals_signal`. Three of these are already in the live SMALL weights: `sector_tilt`, `announcement_car` and `avg_delivery_pct_30d`.
- **MID: a pass, but read it with care.** The 6 factors that pass all three are `z_score`, `interest_coverage`, `roic` and `gross_profitability`, all **negative** (weaker balance sheets and lower profitability did better over 6–12 months), plus `debt_structure` and `gold_beta`, both positive. This is a "junk did better" pattern. Survivorship can produce exactly that: the fundamentals panel holds only today's listed companies, so the weak firms in it are the ones that survived. Treat these as a risk exposure until H2 shows otherwise. The live MID factors `piotroski_f` (6-month t +11.59) and `iv_skew_25d` (+4.00) are slow, but their history starts in 2024, so they cannot pass the three-period check.
- **LARGE: a pass on paper only.** The one factor that passes all three is `metals_beta` (6-month IC +0.099, t +3.73): a bet on metal prices, not stock selection. Nothing in LARGE clears Bonferroni. This supports the existing view that LARGE should be the index.
- **The fast list is short: `delivery_anomaly_z`** (MID, and SMALL's largest live weight, 0.24), `low_vol_252d` and `max_lottery_21d` (both SMALL, negative). As the plan expected, SMALL's largest live weight is a one-month signal. Its t falls from +7.15 at 21 sessions to +2.41 at 126 and +1.14 at 252.

## How it was measured
- **Labels** (`data/lh/labels.parquet`, 203,184 rows = 83 monthly anchors × 2,448 sids, 2019-12-02 → 2026-10-01). The labels are `pit.forward_returns` at 21, 63, 126 and 252 sessions. Entry is the first session after the anchor, prices are adjusted closes, and the entry and exit proximity guards apply. The file also holds `fwd_next_anchor`, the return from the session after one anchor to the session after the next (16–23 sessions, median 21), for the book simulator. The panel's stored `fwd_return_20d` is recomputed exactly: on 127,440 pairs, correlation 1.0, median absolute difference 0, 100% equal. `fwd_21` against the stored 20-session label: correlation 0.9817 (Spearman 0.9744), median absolute difference 0.0132 over 127,399 pairs. `fwd_next_anchor` against `fwd_21`: correlation 0.9771, median absolute difference 0.0083.
- **IC**: for each monthly anchor, the Spearman rank IC within the panel's cap tier (at least 20 stocks), for 103 numeric factor columns of `daily_snapshots_pit`. ID and price columns are left out (`industry_id`, `close_price`).
- **t-stat**: Newey-West (Bartlett) with lag = horizon in months (1 / 3 / 6 / 12), using the `tools/backtest_pit` helpers. The same is computed by anchor period: 2019-12…2022-12, 2023-01…2024-12 and 2025-01…2026-10.
- **Classes** (fixed before the run). *Slow*: at least 12 anchors at 126, |t126| ≥ 2.5, |IC126| ≥ |IC21|, same sign. *Fast*: |t21| ≥ 2.5 and the 21-session |IC| is the largest of the horizons measured, with at least 12 anchors at 21, 63 and 126. *Same sign in all 3 periods*: IC126 has the full-sample sign in each period. A period with no data counts as a fail, because the sign cannot be shown to hold there.
- **Multiple testing**: every full-sample (factor, tier, horizon) test with at least 12 anchors is one hypothesis. p is two-sided with df = n − 1, as in `tools/multiple_testing`, and BY and Bonferroni are applied at 5%.

## Multiple testing
M = **1,094** tests (103 factors × 3 tiers × 4 horizons, less the thin ones). 239 have |t| ≥ 2.5 before any haircut. **91 survive BY** (smallest surviving |t| 3.65) and **48 survive Bonferroni** (smallest surviving |t| 4.37; the implied Bonferroni bar at the median df is |t| ≥ 4.35).

| tier | BY survivors at 21 / 63 / 126 / 252 | Bonferroni survivors at 21 / 63 / 126 / 252 |
|---|---|---|
| LARGE | 0 / 0 / 2 / 7 | 0 / 0 / 0 / 2 |
| MID | 1 / 2 / 9 / 18 | 0 / 0 / 3 / 13 |
| SMALL | 9 / 11 / 11 / 21 | 4 / 5 / 5 / 16 |

The 252-session column is the least trustworthy. With 12-month labels on monthly anchors, about 70 overlapping windows hold only around 6 independent years. The Newey-West t and the df = n − 1 p-value both overstate the evidence there. That is also why some thin factors show 252-session t-stats of 10–30 (for example `piotroski_f` SMALL +30.17 on 13 anchors).

## Slow factors, per tier
Bold = passes all three tests (slow, same sign in all 3 periods, survives BY). "·" = no data in that period. Live weight = `factors.SIGNAL_WEIGHTS` for that tier today. IC and t are the full-sample values.

### LARGE

| factor | live weight | IC 21 | IC 63 | IC 126 | IC 252 | t 21 | t 63 | t 126 | t 252 | anchors (126) | 126 sign 20-22 / 23-24 / 25-26 | BY | Bonf | passes all three |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **metals_beta** |  | +0.041 | +0.073 | +0.099 | +0.127 | +2.19 | +2.87 | +3.73 | +3.17 | 77 | + / + / + | yes | no | yes |
| cf_accruals |  | -0.025 | -0.018 | -0.092 | -0.052 | -0.69 | -0.39 | -4.19 | -1.86 | 20 | · / − / − | yes | no | no |
| promoter_qoq |  | +0.027 | +0.039 | +0.080 | +0.109 | +1.57 | +1.79 | +3.78 | +7.72 | 15 | · / · / + | no | no | no |
| debt_to_equity |  | +0.056 | +0.074 | +0.140 | +0.176 | +1.99 | +1.80 | +3.25 | +3.24 | 20 | · / + / + | no | no | no |
| z_score |  | -0.043 | -0.080 | -0.120 | -0.148 | -2.17 | -2.63 | -3.07 | -3.93 | 76 | − / − / − | no | no | no |
| promoter_signal |  | +0.019 | +0.061 | +0.102 | +0.117 | +1.00 | +2.75 | +2.95 | +6.64 | 18 | · / + / + | no | no | no |
| iv_skew_25d | 0.25 | +0.033 | +0.079 | +0.063 | +0.116 | +1.10 | +3.54 | +2.83 | +14.20 | 21 | · / + / + | no | no | no |
| debt_structure |  | +0.048 | +0.080 | +0.119 | +0.130 | +2.12 | +2.31 | +2.79 | +2.63 | 76 | + / + / + | no | no | no |
| governance_resignation |  | +0.001 | +0.023 | +0.043 | +0.055 | +0.10 | +1.43 | +2.68 | +3.05 | 76 | + / + / + | no | no | no |
| interest_coverage |  | -0.054 | -0.078 | -0.106 | -0.131 | -2.88 | -2.53 | -2.64 | -2.51 | 76 | − / − / − | no | no | no |

### MID

| factor | live weight | IC 21 | IC 63 | IC 126 | IC 252 | t 21 | t 63 | t 126 | t 252 | anchors (126) | 126 sign 20-22 / 23-24 / 25-26 | BY | Bonf | passes all three |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **z_score** |  | -0.028 | -0.058 | -0.095 | -0.142 | -1.91 | -3.10 | -5.75 | -8.56 | 76 | − / − / − | yes | yes | yes |
| **interest_coverage** |  | -0.023 | -0.052 | -0.085 | -0.118 | -1.63 | -2.78 | -5.02 | -10.01 | 76 | − / − / − | yes | yes | yes |
| **roic** |  | -0.013 | -0.037 | -0.068 | -0.108 | -1.04 | -2.32 | -4.27 | -8.98 | 76 | − / − / − | yes | no | yes |
| **debt_structure** |  | +0.027 | +0.047 | +0.078 | +0.122 | +2.18 | +2.60 | +3.97 | +7.86 | 76 | + / + / + | yes | no | yes |
| **gold_beta** |  | +0.021 | +0.034 | +0.062 | +0.063 | +2.00 | +3.35 | +3.82 | +3.01 | 77 | + / + / + | yes | no | yes |
| **gross_profitability** |  | -0.022 | -0.046 | -0.083 | -0.131 | -1.39 | -2.28 | -3.73 | -5.91 | 76 | − / − / − | yes | no | yes |
| piotroski_f | 0.15 | +0.044 | +0.078 | +0.095 | +0.116 | +3.03 | +4.68 | +11.59 | +10.11 | 20 | · / + / + | yes | yes | no |
| pcr_volume |  | +0.053 | +0.082 | +0.070 | +0.101 | +2.43 | +3.39 | +5.05 | +6.48 | 21 | · / + / + | yes | no | no |
| earnings_surprise_std |  | +0.037 | +0.061 | +0.078 | +0.098 | +1.96 | +2.93 | +4.69 | +29.07 | 14 | · / · / + | yes | no | no |
| cf_accruals | -0.1 | -0.025 | -0.071 | -0.094 | -0.115 | -1.72 | -3.55 | -4.13 | -11.23 | 20 | · / − / − | no | no | no |
| iv_skew_25d | 0.2 | +0.043 | +0.096 | +0.098 | +0.134 | +1.64 | +4.87 | +4.00 | +6.49 | 21 | · / + / + | no | no | no |
| earnings_beat_rate |  | +0.034 | +0.053 | +0.085 | +0.054 | +1.65 | +2.30 | +3.93 | +3.98 | 17 | · / + / + | no | no | no |
| position_52w |  | +0.029 | +0.053 | +0.079 | +0.068 | +1.58 | +2.77 | +3.54 | +2.81 | 77 | + / + / + | no | no | no |
| mom_6m |  | +0.042 | +0.060 | +0.088 | +0.057 | +2.51 | +3.05 | +3.16 | +1.77 | 77 | + / + / + | no | no | no |
| mom_composite |  | +0.048 | +0.069 | +0.083 | +0.055 | +2.85 | +3.38 | +3.01 | +1.65 | 77 | + / + / + | no | no | no |
| debt_to_equity |  | +0.010 | +0.037 | +0.074 | +0.053 | +0.43 | +1.68 | +2.98 | +2.27 | 20 | · / + / + | no | no | no |
| financial_signal |  | -0.199 | -0.258 | -0.267 | -0.240 | -3.13 | -3.57 | -2.97 | -3.93 | 15 | · / − / − | no | no | no |
| financial_quality |  | -0.199 | -0.258 | -0.267 | -0.240 | -3.13 | -3.57 | -2.97 | -3.93 | 15 | · / − / − | no | no | no |
| sga_to_revenue_change |  | +0.018 | +0.037 | +0.044 | +0.030 | +1.71 | +3.09 | +2.84 | +2.20 | 76 | + / + / + | no | no | no |
| financial_recovery |  | +0.010 | +0.144 | +0.203 | +0.223 | +0.27 | +3.14 | +2.82 | +4.99 | 15 | · / + / + | no | no | no |
| residual_momentum_12_1 | 0.17 | +0.048 | +0.070 | +0.074 | +0.041 | +2.76 | +3.23 | +2.59 | +1.21 | 77 | + / + / + | no | no | no |

### SMALL

| factor | live weight | IC 21 | IC 63 | IC 126 | IC 252 | t 21 | t 63 | t 126 | t 252 | anchors (126) | 126 sign 20-22 / 23-24 / 25-26 | BY | Bonf | passes all three |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **cons_beat_rate_4q** |  | +0.044 | +0.065 | +0.080 | +0.061 | +5.03 | +5.42 | +6.43 | +3.25 | 77 | + / + / + | yes | yes | yes |
| **value_composite** |  | +0.034 | +0.064 | +0.095 | +0.127 | +4.11 | +5.02 | +5.69 | +6.10 | 77 | + / + / + | yes | yes | yes |
| **sector_tilt** | 0.14 | +0.036 | +0.057 | +0.073 | +0.076 | +4.19 | +4.97 | +4.92 | +4.46 | 77 | + / + / + | yes | yes | yes |
| **closing_strength_1m** |  | +0.022 | +0.041 | +0.050 | +0.050 | +2.44 | +3.65 | +4.47 | +4.81 | 77 | + / + / + | yes | yes | yes |
| **position_52w** |  | +0.039 | +0.068 | +0.088 | +0.085 | +2.90 | +4.06 | +4.30 | +4.43 | 77 | + / + / + | yes | no | yes |
| **announcement_car** | 0.22 | +0.033 | +0.034 | +0.046 | +0.053 | +5.36 | +3.87 | +4.23 | +3.67 | 77 | + / + / + | yes | no | yes |
| **avg_delivery_pct_30d** | 0.12 | +0.042 | +0.052 | +0.056 | +0.049 | +4.92 | +4.69 | +4.00 | +2.95 | 76 | + / + / + | yes | no | yes |
| **mom_6m** |  | +0.036 | +0.059 | +0.085 | +0.058 | +2.82 | +3.18 | +3.97 | +2.56 | 77 | + / + / + | yes | no | yes |
| **rate_beta** |  | -0.001 | -0.014 | -0.026 | -0.027 | -0.21 | -2.14 | -3.97 | -6.69 | 77 | − / − / − | yes | no | yes |
| **accruals_signal** |  | +0.015 | +0.028 | +0.037 | +0.042 | +2.32 | +3.16 | +3.82 | +3.17 | 76 | + / + / + | yes | no | yes |
| piotroski_f | 0.14 | +0.030 | +0.046 | +0.069 | +0.089 | +4.26 | +6.45 | +13.23 | +30.17 | 20 | · / + / + | yes | yes | no |
| quality_composite |  | +0.029 | +0.033 | +0.046 | +0.061 | +2.74 | +2.55 | +3.75 | +9.16 | 20 | · / + / + | no | no | no |
| book_to_price |  | +0.011 | +0.028 | +0.050 | +0.087 | +1.05 | +1.90 | +3.55 | +4.97 | 77 | + / + / + | no | no | no |
| bs_accruals |  | -0.012 | -0.022 | -0.031 | -0.038 | -1.80 | -2.60 | -3.44 | -2.72 | 76 | − / − / − | no | no | no |
| smart_money_score |  | +0.033 | +0.044 | +0.050 | +0.043 | +3.94 | +3.89 | +3.41 | +2.56 | 64 | + / + / + | no | no | no |
| margin_slope |  | -0.004 | -0.015 | -0.026 | -0.034 | -0.69 | -1.82 | -3.38 | -4.27 | 70 | − / − / − | no | no | no |
| mom_composite |  | +0.039 | +0.060 | +0.077 | +0.049 | +3.01 | +3.12 | +3.29 | +1.96 | 77 | + / + / + | no | no | no |
| vwap_deviation_5d |  | +0.007 | +0.020 | +0.024 | +0.026 | +1.06 | +2.58 | +3.29 | +3.09 | 77 | + / + / + | no | no | no |
| earnings_persistence |  | -0.034 | -0.051 | -0.058 | -0.064 | -3.08 | -3.39 | -3.22 | -6.30 | 20 | · / − / − | no | no | no |
| roe |  | +0.025 | +0.028 | +0.033 | +0.035 | +2.46 | +2.43 | +3.18 | +18.99 | 20 | · / + / + | no | no | no |
| corporate_action_density |  | +0.022 | +0.034 | +0.048 | +0.056 | +2.32 | +2.38 | +3.11 | +6.17 | 29 | · / + / + | no | no | no |
| oil_beta |  | +0.015 | +0.023 | +0.025 | +0.035 | +2.61 | +3.67 | +3.10 | +3.49 | 77 | + / + / + | no | no | no |
| forward_looking_intensity |  | +0.010 | +0.031 | +0.054 | +0.080 | +1.05 | +2.58 | +3.09 | +3.55 | 77 | + / + / + | no | no | no |
| earnings_yield |  | +0.017 | +0.019 | +0.029 | +0.048 | +1.51 | +1.59 | +2.78 | +9.31 | 20 | · / + / + | no | no | no |
| metals_beta |  | +0.004 | +0.011 | +0.018 | +0.022 | +0.67 | +1.66 | +2.72 | +4.34 | 77 | + / + / + | no | no | no |
| residual_momentum_12_1 | 0.14 | +0.041 | +0.057 | +0.066 | +0.035 | +3.07 | +2.86 | +2.71 | +1.39 | 77 | + / + / + | no | no | no |
| share_momentum |  | +0.008 | +0.027 | +0.054 | +0.061 | +0.70 | +1.66 | +2.67 | +2.55 | 77 | + / + / + | no | no | no |
| fcf_yield |  | +0.013 | +0.020 | +0.029 | +0.043 | +2.28 | +2.26 | +2.52 | +2.77 | 77 | + / + / + | no | no | no |
| nwc_to_revenue |  | +0.015 | +0.026 | +0.033 | +0.043 | +2.31 | +2.57 | +2.51 | +3.43 | 76 | + / + / + | no | no | no |


**Thin history.** Several factors carry only 14–29 anchors at 126 sessions, because their inputs in the panel start in 2024-09 or later. These include `piotroski_f`, `cf_accruals`, `roe`, `earnings_yield`, `quality_composite`, `debt_to_equity`, `iv_skew_25d`, `pcr_volume`, `promoter_qoq`, `earnings_surprise_std`, `earnings_beat_rate` and the `financial_*` columns. Twenty overlapping 6-month windows from 2024-09 to 2026-04 cover roughly one market phase. Their 6-month t-stats (for example `piotroski_f` +11.59 MID, +13.23 SMALL) are real in that window but say little about another one. The three-period check rules them out by construction. `financial_signal` and `financial_quality` carry identical values in the panel.

**Sign flips.** One factor turns from one sign to the other between 21 and 126 sessions with |t126| ≥ 2.5: `earnings_surprise_std` SMALL (IC21 −0.0134, t −0.61 → IC126 +0.0472, t +3.12, 25 anchors at 21). It is not counted as slow.

## Fast factors (peak at 21 sessions, then decay)


| tier | factor | live weight | IC 21 | IC 63 | IC 126 | IC 252 | t 21 | t 63 | t 126 | t 252 |
|---|---|---|---|---|---|---|---|---|---|---|
| MID | delivery_anomaly_z |  | +0.031 | +0.017 | +0.014 | +0.001 | +3.05 | +2.09 | +1.44 | +0.10 |
| SMALL | delivery_anomaly_z | 0.24 | +0.032 | +0.025 | +0.020 | +0.008 | +7.15 | +3.65 | +2.41 | +1.14 |
| SMALL | low_vol_252d |  | -0.040 | -0.027 | -0.013 | -0.011 | -2.57 | -1.14 | -0.42 | -0.29 |
| SMALL | max_lottery_21d |  | -0.032 | -0.015 | +0.003 | +0.012 | -3.68 | -1.19 | +0.17 | +0.51 |


## Live wired factors at the long horizon


| tier | factor | live weight | IC 21 | IC 126 | t 21 | t 126 | anchors (126) | class |
|---|---|---|---|---|---|---|---|---|
| MID | piotroski_f | 0.15 | +0.044 | +0.095 | +3.03 | +11.59 | 20 | slow |
| SMALL | piotroski_f | 0.14 | +0.030 | +0.069 | +4.26 | +13.23 | 20 | slow |
| MID | cf_accruals | -0.1 | -0.025 | -0.094 | -1.72 | -4.13 | 20 | slow |
| SMALL | avg_delivery_pct_30d | 0.12 | +0.042 | +0.056 | +4.92 | +4.00 | 76 | slow, passes all three |
| SMALL | delivery_anomaly_z | 0.24 | +0.032 | +0.020 | +7.15 | +2.41 | 74 | fast |
| MID | consensus_signal_combined | 0.14 | +0.038 | +0.070 | +2.30 | +2.31 | 34 | neither |
| LARGE | iv_skew_25d | 0.25 | +0.033 | +0.063 | +1.10 | +2.83 | 21 | slow |
| MID | iv_skew_25d | 0.2 | +0.043 | +0.098 | +1.64 | +4.00 | 21 | slow |
| SMALL | sector_tilt | 0.14 | +0.036 | +0.073 | +4.19 | +4.92 | 77 | slow, passes all three |
| LARGE | forward_looking_intensity | 0.2 | +0.048 | +0.090 | +2.34 | +2.32 | 77 | neither |
| LARGE | asset_growth_yoy | -0.2 | -0.036 | -0.047 | -2.03 | -1.33 | 76 | neither |
| LARGE | announcement_car | 0.35 | +0.041 | +0.050 | +3.07 | +2.40 | 77 | neither |
| MID | announcement_car | 0.09 | +0.016 | +0.034 | +1.73 | +2.02 | 77 | neither |
| SMALL | announcement_car | 0.22 | +0.033 | +0.046 | +5.36 | +4.23 | 77 | slow, passes all three |
| MID | residual_momentum_12_1 | 0.17 | +0.048 | +0.074 | +2.76 | +2.59 | 77 | slow |
| SMALL | residual_momentum_12_1 | 0.14 | +0.041 | +0.066 | +3.07 | +2.71 | 77 | slow |
| MID | cons_beat_rate_4q | 0.15 | +0.044 | +0.059 | +4.17 | +2.45 | 77 | neither |


Of the 17 live (tier, factor) weights:
- **3 pass all three tests**: SMALL `avg_delivery_pct_30d`, `sector_tilt` and `announcement_car`.
- **7 are slow but miss a test.** Five miss the three-period check because their history starts in 2024: `piotroski_f` MID and SMALL, `cf_accruals` MID, and `iv_skew_25d` LARGE and MID. Two keep their sign in every period but fail BY: `residual_momentum_12_1` MID and SMALL.
- **1 is fast**: SMALL `delivery_anomaly_z`, the largest SMALL weight.
- **6 are neither**: LARGE `announcement_car`, `forward_looking_intensity` and `asset_growth_yoy`; MID `consensus_signal_combined` and `announcement_car`; and MID `cons_beat_rate_4q`. That last one has a 6-month t of +2.45, just under the bar, while it passes everything in SMALL.

## What this means for H2 and H3
- **Candidates for the slow composite** (to be chosen inside each training window, not from this table): SMALL has 10 factors with history back to 2019-12 that keep their sign in every period. MID has 6, but 4 are negative-quality exposures. LARGE has one macro beta.
- **H2 must test the MID negative-quality group with care.** It should be checked against the tier index and against a simple size and leverage tilt. Survivorship is a likely source: the panel holds only today's 2,448 listed stocks, so a firm that went bust is missing and weak firms look better than they were. The plan asks for price-only factors to be rerun on `daily_snapshots_pit_unlisted`. That was not done in this step. It applies to `closing_strength_1m`, `position_52w`, `mom_6m`, `sector_tilt` and the macro betas, not to the fundamental ones.
- The live 21-session weights lean on `delivery_anomaly_z` (fast) in SMALL. A slow SMALL composite has plenty to draw on without it.

## Caveats
- **Survivorship**: covered above. The likely effect is that weak-balance-sheet and distressed factors look better than they are.
- **Coverage before 2023**: only about 1,160–1,450 of the 2,448 sids have a 21-session label at anchors in 2019-12 → 2022-12 (the 2020-22 backfill is partial). The panel's tier at each anchor was used as stored.
- **Overlap**: 126- and 252-session labels overlap 6 and 12 months. Newey-West corrects the standard error, but with 77 anchors the 6-month estimate rests on about 13 non-overlapping windows. A t of 2.5–3 at 126 is modest evidence.
- **Pass reading**: the "all three" pass line per tier is my reading of the plan (see the Verdict). The per-test numbers in `data/lh/horizon_tests.csv` allow any other reading to be recomputed.

## Files
- `tools/lh_labels.py` → `data/lh/labels.parquet` (sid, snapshot_date, cap_tier, fwd_21, fwd_63, fwd_126, fwd_252, fwd_20 [check only], fwd_next_anchor, h_next_anchor)
- `tools/lh_horizon.py` → `data/lh/horizon.json` (verdict, multiple-testing summary, one record per factor × tier), `data/lh/horizon_tests.csv` (every test with period splits and p / p_BY / p_Bonf), `data/lh/horizon_raw.csv` (the ICs before the haircut; `--reuse` reclassifies from it)
