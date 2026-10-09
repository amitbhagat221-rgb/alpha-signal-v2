# Ownership flows from the BSE filings, 2026-10: institutional flows DROP, retail holder growth KEEP (SMALL)

Verdict: on 82 monthly anchors (2019-12 → 2026-09), quarter-on-quarter changes in foreign-institution,
mutual-fund and domestic-institution holding (and how many of the three rose) carry no signal in any tier.
The 2026-10 LARGE study's SMALL readings on 20 anchors (`d_mf` t 3.37, `inst_breadth` t 4.27) did not survive
the longer history. **Growth in the number of small (≤ Rs 2 lakh) shareholders predicts LOWER returns in
SMALL: t −3.48**, the pre-registered sign, both halves negative, 7 of 8 years negative, unchanged after
controlling for reversal / lottery / momentum / low-vol / 52-week position (t −3.17), max correlation with a
wired SMALL factor 0.06. Below the multiple-testing bar (|t| ≈ 4.2), so a promotion candidate, not a weight.

## Data (new)
- `shareholding_categories`: one row per BSE shareholding filing (category totals + shareholder counts),
  parsed from the XBRL already archived for `shareholding_holders` (`python -m sources.bse_shp --reparse`,
  no network). 34,443 filings, 1,002 stocks, Jun-2016 → today; `filed_at` = BSE broadcast time (point in time).
- Second source: on 229 quarters that overlap Tickertape `shareholding`, promoter / FII / MF / DII agree to a
  median 0.003 pp (correlation 1.000). Promoter + public = 100% in the median filing.
- Coverage on the panel: LARGE 89%, MID 85%, SMALL 49% (the backfill runs largest first; the smaller half of
  SMALL arrives as `run.sh backfill` finishes). Survivors only: stocks in today's universe.
- `mf_holdings` (plan 0011 WS2.3, plan 0014 D5) cannot be backtested: one full snapshot (2026-05-28) and
  ~174 schemes a month since. The filings' mutual-fund category (`mf_qoq` below) is the deep version of the
  same question, and it is a DROP.

## Method
- Script: `tools/ownership_flow_study.py` (read-only). Compute: `pit.pit_ownership_flows` — a filing counts
  from its broadcast day; latest quarter ≤ 140 days old and the previous quarter 70–120 days before it.
- Evidence engine: `tools.backtest_pit._compute_ic` / `_aggregate` within point-in-time tier, label
  `fwd_return_20d` (entry next session), first-business-day anchors. Halves split at 2023-05-01.
- Pre-registered signs: institutional changes and breadth positive; retail holder growth negative.
- 5 new hypotheses × 3 tiers (the four institutional ones were already counted in the LARGE study).

## Results

| signal | tier | n | coverage | mean IC | t | IC H1 | IC H2 | halves | hit rate | max corr wired | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fii_qoq | LARGE | 81 | 89% | +0.0005 | +0.04 | -0.0093 | +0.0105 | split | 49% | -0.05 (iv_skew_25d) | DROP |
| fii_qoq | MID | 81 | 85% | -0.0056 | -0.49 | -0.0054 | -0.0058 | agree | 54% | +0.24 (residual_momentum_12_1) | DROP |
| fii_qoq | SMALL | 82 | 49% | +0.0109 | +1.33 | +0.0187 | +0.0032 | agree | 59% | +0.24 (residual_momentum_12_1) | DROP |
| mf_qoq | LARGE | 81 | 89% | +0.0026 | +0.22 | -0.0102 | +0.0158 | split | 53% | +0.05 (iv_skew_25d) | DROP |
| mf_qoq | MID | 81 | 85% | +0.0116 | +1.05 | +0.0017 | +0.0218 | agree | 53% | +0.05 (iv_skew_25d) | DROP |
| mf_qoq | SMALL | 82 | 49% | +0.0099 | +1.57 | +0.0099 | +0.0099 | agree | 54% | +0.05 (residual_momentum_12_1) | WEAK |
| dii_qoq | LARGE | 81 | 89% | -0.0057 | -0.50 | -0.0134 | +0.0022 | split | 48% | +0.08 (iv_skew_25d) | DROP |
| dii_qoq | MID | 81 | 85% | -0.0036 | -0.35 | +0.0033 | -0.0106 | split | 49% | -0.11 (residual_momentum_12_1) | DROP |
| dii_qoq | SMALL | 82 | 49% | +0.0079 | +1.18 | +0.0084 | +0.0074 | agree | 49% | +0.05 (residual_momentum_12_1) | DROP |
| inst_breadth | LARGE | 81 | 89% | -0.0121 | -0.93 | -0.0163 | -0.0078 | agree | 48% | -0.03 (forward_looking_intensity) | DROP |
| inst_breadth | MID | 81 | 85% | +0.0108 | +0.97 | +0.0087 | +0.0130 | agree | 57% | +0.06 (residual_momentum_12_1) | DROP |
| inst_breadth | SMALL | 82 | 49% | +0.0042 | +0.56 | +0.0143 | -0.0059 | split | 59% | +0.09 (residual_momentum_12_1) | DROP |
| retail_holders_qoq | LARGE | 81 | 89% | +0.0044 | +0.31 | -0.0109 | +0.0201 | split | 57% | +0.16 (asset_growth_yoy) | DROP |
| retail_holders_qoq | MID | 81 | 85% | +0.0056 | +0.47 | +0.0106 | +0.0004 | agree | 58% | +0.11 (consensus_signal_combined) | DROP |
| retail_holders_qoq | SMALL | 82 | 49% | -0.0251 | -3.48 | -0.0330 | -0.0173 | agree | 63% | -0.06 (avg_delivery_pct_30d) | KEEP |
| promoter_qoq | LARGE | 20 | 24% | +0.0295 | +1.42 | +nan | +0.0295 | split | 75% | - | reference |
| promoter_qoq | MID | 20 | 24% | +0.0091 | +0.42 | +nan | +0.0091 | split | 55% | - | reference |
| promoter_qoq | SMALL | 27 | 24% | +0.0137 | +0.66 | +nan | +0.0137 | split | 41% | - | reference |

`promoter_qoq` is the existing panel column (Tickertape), shown for reference only.

## retail_holders_qoq, SMALL — robustness
- Controls (per-anchor rank regression on st_reversal_21d, max_lottery_21d, mom_12m, low_vol_252d,
  position_52w): residual IC −0.0212, t −3.17 (81 anchors).
- Quintiles, mean 20-day return: fewest new retail holders 2.90% → most 2.31%; Q1 − Q5 = 0.60% per 20 days,
  t 2.19, positive in 65% of months.
- IC by year: 2019 −0.045 · 2020 −0.040 · 2021 −0.007 · 2022 −0.075 · 2023 +0.011 · 2024 −0.009 ·
  2025 −0.034 · 2026 −0.020. Median 448 stocks per anchor.

## Next
- Re-run when the SMALL backfill completes (coverage 49% → ~95%); the verdict should hold on the smaller half.
- Promotion review (Amit / CIO desk): register `retail_holders_qoq` (PIT producer `ownership_flows` on
  `shareholding_categories`), reconstruct the panel column, `backtest_pit`, then a weight decision. Panel
  registration waits for the plan 0017 parity week (a new panel column is mirrored to v3 on every date).
