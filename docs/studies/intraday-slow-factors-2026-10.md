# Slow factors from the minute archive at a 90-day horizon — 2026-10 study

_Run 2026-10-16 · `python -m tools.intraday_slow_study study` · read-only on the DB (the `intraday_files` rows for the daily summary are the only writes)._

**Sample:** 80 monthly anchors 2019-12-02 → 2026-07-01 (halves split at 2023-04-03), point-in-time cap tier from `daily_snapshots_pit`, 1932 stocks with a complete 90-day label. Daily summary: 1974 stocks, 3,714,568 stock-sessions, 2015-02-02 → 2026-10-15, from the Kite 1-minute archive (ADR 0072) resampled to 10-minute candles.

**Label:** `fwd_return_90d` = return from the first close after the anchor to the last close within 90 calendar days (built here from adjusted closes; the panel's `fwd_return_20d` beside it). Monthly anchors overlap a 90-day label three times, so t uses Newey–West lag 2; the 20-day t is classical.

**Survivorship caveat:** Kite serves listed stocks only, so the archive and every IC here are survivors-only. The day/night study showed the daily-data analogue of one factor survives delisted names; nothing here has that check yet.

## Pre-registered candidates

| factor | definition | sign |
|---|---|---|
| `rvol_60d` | √Σ rv over 60 sessions, rv = Σ 10-min log-return² | − |
| `rskew_60d` | realized skewness of the 10-min returns, 60 sessions | − |
| `jump_share_60d` | Σ(rv − π/2 · bipower)⁺ / Σ rv, 60 sessions | − |
| `ofi_60d` | tick-rule signed 1-min volume / volume, 60 sessions | + |
| `late_vol_share_60d` | volume 15:00–15:29 / volume, 60 sessions | two-sided (0009 S4) |
| `vwap_dev_60d` | ln(last close / 60-session VWAP) | two-sided |
| `smart_money_12_1` | Σ (last-30-min return − first-30-min return), sessions t−252 … t−22 | + |
| `vol_of_vol_60d` | std / mean of daily √rv, 60 sessions (uncertainty about risk: Baltussen, van Bekkum, van der Grient 2018) | − |
| `amihud_10m_60d` | mean √rv / ₹ Cr traded, 60 sessions | + |

Verdict: |t| ≥ 2.5 at 90 days, both halves agree in sign, max |ρ| with a wired factor < 0.5 (Bonferroni 4.2 for the 269+ hypotheses tested so far).

**Relation to research 0009:** `late_vol_share_60d` is its S4; `rskew`, `ofi` (tick rule, not BVC), `vwap_dev` and `amihud` are its fast candidates F1 / F3 / F5 / T1 tested here at the slow horizon; `smart_money_12_1` is S1's minute-bar version (last half hour minus first). 0009 left realized volatility and jump share off its menu on purpose (duplicate of the failed `low_vol_252d`; a size proxy): they run here as controls, not as new hypotheses. S5 (semibeta) needs the synthetic market series and is not here.

## Verdicts

**KEEP at 90 days:** `rskew_60d` SMALL (t -5.27), `vwap_dev_60d` SMALL (t 3.43), `vol_of_vol_60d` MID (t -2.70), `vol_of_vol_60d` SMALL (t -9.24)

**Slow, not fast (|t| ≥ 2.5 at 90 days, < 2.5 at 20 days):** `vwap_dev_60d` SMALL (t 90d 3.43 vs 20d 1.24)

## IC table (panel, PIT tier, label fwd_return_90d; 20-day beside it)

| signal | tier | n | stocks | ic_90d | t_90d | ic_h1 | ic_h2 | halves | ic_20d | t_20d | max_corr_wired | with | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rvol_60d | LARGE | 80 | 99 | -0.0063 | -0.1700 | -0.0247 | +0.0122 | False | +0.0004 | +0.0200 | +0.2852 | forward_looking_intensity | DROP |
| rvol_60d | MID | 80 | 146 | -0.0075 | -0.3300 | -0.0161 | +0.0011 | False | -0.0161 | -1.0500 | +0.3213 | residual_momentum_12_1 | DROP |
| rvol_60d | SMALL | 80 | 888 | -0.0101 | -0.5800 | -0.0089 | -0.0113 | True | -0.0350 | -3.0700 | +0.2722 | residual_momentum_12_1 | DROP |
| rskew_60d | LARGE | 80 | 99 | -0.0042 | -0.2800 | -0.0047 | -0.0037 | True | -0.0029 | -0.2400 | +0.1808 | announcement_car | DROP |
| rskew_60d | MID | 80 | 146 | -0.0197 | -1.5400 | -0.0063 | -0.0331 | True | -0.0277 | -2.7100 | +0.1760 | announcement_car | WEAK |
| rskew_60d | SMALL | 80 | 888 | -0.0428 | -5.2700 | -0.0429 | -0.0427 | True | -0.0344 | -5.7200 | -0.2139 | avg_delivery_pct_30d | KEEP (clears Bonferroni) |
| jump_share_60d | LARGE | 80 | 99 | -0.0067 | -0.4100 | -0.0358 | +0.0225 | False | -0.0123 | -1.0000 | -0.1140 | iv_skew_25d | DROP |
| jump_share_60d | MID | 80 | 146 | -0.0201 | -1.3500 | -0.0063 | -0.0339 | True | -0.0169 | -1.3500 | -0.1785 | value_composite | DROP |
| jump_share_60d | SMALL | 80 | 888 | +0.0024 | +0.2600 | -0.0063 | +0.0111 | False | -0.0094 | -1.3800 | +0.2598 | avg_delivery_pct_30d | DROP |
| ofi_60d | LARGE | 80 | 99 | +0.0058 | +0.4500 | +0.0216 | -0.0099 | False | +0.0013 | +0.1000 | +0.1748 | announcement_car | DROP |
| ofi_60d | MID | 80 | 146 | +0.0007 | +0.0600 | +0.0248 | -0.0234 | False | -0.0093 | -0.8600 | +0.1499 | residual_momentum_12_1 | DROP |
| ofi_60d | SMALL | 80 | 888 | +0.0053 | +0.5400 | +0.0010 | +0.0097 | True | -0.0088 | -1.1300 | +0.1851 | residual_momentum_12_1 | DROP |
| late_vol_share_60d | LARGE | 80 | 99 | -0.0025 | -0.0900 | -0.0153 | +0.0103 | False | -0.0083 | -0.4100 | -0.1839 | forward_looking_intensity | DROP |
| late_vol_share_60d | MID | 80 | 146 | +0.0065 | +0.3100 | +0.0260 | -0.0130 | False | -0.0019 | -0.1300 | +0.1290 | piotroski_f | DROP |
| late_vol_share_60d | SMALL | 80 | 888 | +0.0130 | +1.1200 | +0.0097 | +0.0163 | True | +0.0195 | +2.5700 | -0.1050 | residual_momentum_12_1 | DROP |
| vwap_dev_60d | LARGE | 80 | 99 | -0.0074 | -0.3300 | +0.0118 | -0.0266 | False | -0.0185 | -0.9700 | +0.3176 | announcement_car | DROP |
| vwap_dev_60d | MID | 80 | 146 | +0.0130 | +0.7400 | +0.0430 | -0.0170 | False | -0.0022 | -0.1300 | +0.2837 | announcement_car | DROP |
| vwap_dev_60d | SMALL | 80 | 888 | +0.0396 | +3.4300 | +0.0517 | +0.0275 | True | +0.0133 | +1.2400 | +0.2871 | announcement_car | KEEP — two-sided |
| smart_money_12_1 | LARGE | 80 | 98 | -0.0344 | -1.9800 | -0.0378 | -0.0310 | True | -0.0198 | -1.2000 | +0.0684 | asset_growth_yoy | WRONG SIGN |
| smart_money_12_1 | MID | 80 | 143 | -0.0186 | -1.5000 | +0.0055 | -0.0427 | False | -0.0052 | -0.4500 | -0.1831 | residual_momentum_12_1 | WRONG SIGN |
| smart_money_12_1 | SMALL | 80 | 843 | -0.0138 | -1.6200 | +0.0073 | -0.0349 | False | -0.0049 | -0.9100 | +0.2093 | avg_delivery_pct_30d | WRONG SIGN |
| vol_of_vol_60d | LARGE | 80 | 99 | -0.0045 | -0.1800 | -0.0257 | +0.0168 | False | -0.0022 | -0.1400 | +0.1445 | forward_looking_intensity | DROP |
| vol_of_vol_60d | MID | 80 | 146 | -0.0474 | -2.7000 | -0.0051 | -0.0897 | True | -0.0442 | -3.5200 | +0.1274 | residual_momentum_12_1 | KEEP |
| vol_of_vol_60d | SMALL | 80 | 888 | -0.0635 | -9.2400 | -0.0748 | -0.0522 | True | -0.0478 | -9.3200 | -0.0797 | avg_delivery_pct_30d | KEEP (clears Bonferroni) |
| amihud_10m_60d | LARGE | 80 | 99 | -0.0096 | -0.5300 | -0.0429 | +0.0238 | False | -0.0151 | -1.2400 | -0.2000 | iv_skew_25d | DROP |
| amihud_10m_60d | MID | 80 | 146 | -0.0209 | -1.2500 | +0.0116 | -0.0533 | False | -0.0199 | -1.4700 | -0.1556 | value_composite | DROP |
| amihud_10m_60d | SMALL | 80 | 888 | +0.0140 | +1.1600 | +0.0406 | -0.0126 | False | -0.0066 | -0.8500 | +0.4809 | avg_delivery_pct_30d | DROP |

## SMALL names trading ≥ ₹1 Cr a day (label fwd_return_90d)

| signal | slice | n | stocks | ic_90d | t_90d | ic_h1 | ic_h2 | halves |
|---|---|---|---|---|---|---|---|---|
| rvol_60d | SMALL_1CR | 80 | 849 | -0.0112 | -0.6300 | -0.0093 | -0.0131 | True |
| rskew_60d | SMALL_1CR | 80 | 849 | -0.0443 | -5.4000 | -0.0426 | -0.0460 | True |
| jump_share_60d | SMALL_1CR | 80 | 849 | +0.0011 | +0.1300 | -0.0059 | +0.0082 | False |
| ofi_60d | SMALL_1CR | 80 | 849 | +0.0051 | +0.5100 | +0.0019 | +0.0083 | True |
| late_vol_share_60d | SMALL_1CR | 80 | 849 | +0.0133 | +1.1400 | +0.0098 | +0.0167 | True |
| vwap_dev_60d | SMALL_1CR | 80 | 849 | +0.0412 | +3.6000 | +0.0528 | +0.0296 | True |
| smart_money_12_1 | SMALL_1CR | 80 | 808 | -0.0137 | -1.6300 | +0.0074 | -0.0348 | False |
| vol_of_vol_60d | SMALL_1CR | 80 | 849 | -0.0655 | -9.7000 | -0.0754 | -0.0556 | True |
| amihud_10m_60d | SMALL_1CR | 80 | 849 | +0.0106 | +0.8500 | +0.0393 | -0.0181 | False |

## What the strong rows add (|t| ≥ 2.5): IC net of liquidity, realized vol, the tier's wired factors

| signal | tier | net_of | n | mean_ic | t |
|---|---|---|---|---|---|
| rskew_60d | SMALL | ln_adtv_60d | 80 | -0.0405 | -5.0300 |
| rskew_60d | SMALL | rvol_60d | 80 | -0.0409 | -5.1100 |
| rskew_60d | SMALL | wired SMALL | 80 | -0.0321 | -4.3500 |
| rskew_60d | SMALL | all | 80 | -0.0270 | -3.8300 |
| vwap_dev_60d | SMALL | ln_adtv_60d | 80 | +0.0428 | +3.6600 |
| vwap_dev_60d | SMALL | rvol_60d | 80 | +0.0391 | +3.1300 |
| vwap_dev_60d | SMALL | wired SMALL | 80 | +0.0273 | +2.3700 |
| vwap_dev_60d | SMALL | all | 80 | +0.0307 | +2.5600 |
| vol_of_vol_60d | MID | ln_adtv_60d | 80 | -0.0451 | -2.8100 |
| vol_of_vol_60d | MID | rvol_60d | 80 | -0.0489 | -2.9800 |
| vol_of_vol_60d | MID | wired MID | 80 | -0.0462 | -2.7800 |
| vol_of_vol_60d | MID | all | 80 | -0.0358 | -2.7700 |
| vol_of_vol_60d | SMALL | ln_adtv_60d | 80 | -0.0607 | -9.3500 |
| vol_of_vol_60d | SMALL | rvol_60d | 80 | -0.0595 | -7.6800 |
| vol_of_vol_60d | SMALL | wired SMALL | 80 | -0.0594 | -8.3100 |
| vol_of_vol_60d | SMALL | all | 80 | -0.0490 | -6.4500 |

## The strong rows net of their nearest relatives (benched `max_lottery_21d`, `low_vol_252d`; wired `mom_6m`)

| signal | tier | net_of | n | mean_ic | t |
|---|---|---|---|---|---|
| rskew_60d | SMALL | max_lottery_21d | 80 | -0.0399 | -5.0300 |
| rskew_60d | SMALL | low_vol_252d | 80 | -0.0385 | -4.5900 |
| rskew_60d | SMALL | mom_6m | 80 | -0.0410 | -5.0500 |
| vwap_dev_60d | SMALL | max_lottery_21d | 80 | +0.0548 | +3.9600 |
| vwap_dev_60d | SMALL | low_vol_252d | 80 | +0.0406 | +3.7300 |
| vwap_dev_60d | SMALL | mom_6m | 80 | +0.0274 | +2.2700 |
| vol_of_vol_60d | MID | max_lottery_21d | 80 | -0.0421 | -2.5100 |
| vol_of_vol_60d | MID | low_vol_252d | 80 | -0.0477 | -2.9600 |
| vol_of_vol_60d | MID | mom_6m | 80 | -0.0486 | -2.8200 |
| vol_of_vol_60d | SMALL | max_lottery_21d | 80 | -0.0608 | -8.5300 |
| vol_of_vol_60d | SMALL | low_vol_252d | 80 | -0.0561 | -7.4000 |
| vol_of_vol_60d | SMALL | mom_6m | 80 | -0.0609 | -8.2300 |

## Decile shape of the strong rows (mean 90-day return in %, decile 1 = lowest factor value)

| signal | tier | d1 | d2 | d3 | d4 | d5 | d6 | d7 | d8 | d9 | d10 | spread_10_1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rskew_60d | SMALL | +6.9 | +7.8 | +7.8 | +7.9 | +7.3 | +6.7 | +6.1 | +6.1 | +5.1 | +5.2 | -1.7 |
| vwap_dev_60d | SMALL | +5.1 | +5.6 | +5.9 | +6.0 | +6.3 | +6.4 | +7.4 | +7.1 | +8.2 | +8.9 | +3.7 |
| vol_of_vol_60d | MID | +5.6 | +5.2 | +4.4 | +5.3 | +5.4 | +5.0 | +5.9 | +5.6 | +4.8 | +2.8 | -2.8 |
| vol_of_vol_60d | SMALL | +8.2 | +7.6 | +7.0 | +7.0 | +7.0 | +6.7 | +6.3 | +5.6 | +5.4 | +5.9 | -2.4 |

## Are the strong rows trading structure in disguise? (mean per-anchor Spearman with descriptors)

| signal | tier | bars_per_day | thin_days | flat_at_low | sessions | ln_adtv_60d | rvol_60d |
|---|---|---|---|---|---|---|---|
| rskew_60d | SMALL | -0.01 | -0.05 | -0.05 | -0.02 | +0.04 | +0.13 |
| vwap_dev_60d | SMALL | -0.01 | +0.03 | -0.02 | -0.01 | +0.10 | +0.13 |
| vol_of_vol_60d | MID | -0.24 | +0.03 | +0.14 | -0.13 | -0.11 | +0.42 |
| vol_of_vol_60d | SMALL | -0.02 | +0.09 | +0.12 | -0.10 | +0.07 | +0.26 |

## Reading it

- `t_90d` is the Newey–West t of the mean monthly rank IC against the 90-day label; `t_20d` the classical t against the 20-day label on the same anchors.
- `halves` = both halves of the sample carry the sign of the whole.
- `max_corr_wired` = the strongest mean per-anchor Spearman correlation with a factor already wired in that tier (`with`); ≥ 0.5 means the information is already in the model.
- WRONG SIGN = the pre-registered sign failed with |t| ≥ 1.5; WEAK = 1.5 ≤ |t| < 2.5; DROP otherwise.

## Next

- A KEEP goes to a promotion review (registration in `factors.FACTORS` as LIBRARY with a PIT twin from the daily summary, then `tools/multiple_testing.py`); never a weight from this table.
- The survivorship check needs delisted minute history, which Kite does not have: the fallback is the daily-data analogue on `stock_prices_unlisted` where one exists.
- The daily summary (`data/intraday/daily_1m/`) is the `intraday_daily` deliverable of ADR 0072; the weekly forward fetch must append to it.

## Interpretation (2026-10-16, written by hand after the run above)

- **The one slow-specific result is momentum in disguise.** `vwap_dev_60d` SMALL is the only candidate strong at 90 days (t 3.43) and weak at 20 (t 1.24), but it is the price's distance from its own 60-session VWAP, so it carries 3-month momentum: net of `mom_6m` t 2.27, net of the tier's wired set (incl. `residual_momentum_12_1`) t 2.37, net of everything 2.56. A sliver above the raw bar, well under Bonferroni, and nothing the model does not already have.
- **Two factors are real but horizon-agnostic, not slow.** `vol_of_vol_60d` SMALL (t −9.24 at 90 d, −9.32 at 20 d) and `rskew_60d` SMALL (−5.27 / −5.72) clear Bonferroni at both horizons, hold in both halves, in the ≥ ₹1 Cr slice, and net of liquidity, realized vol, the wired set, `max_lottery_21d`, `low_vol_252d` and `mom_6m`. Neither is thin trading or circuit locks in disguise (|ρ| ≤ 0.12 with bars per day, thin days, flat-at-low minutes). The spread is modest and steady, not a tail: deciles 1–5 earn 7–8 % per 90 days, deciles 8–10 earn 5–6 %, so a 10−1 spread of −2.4 pp (vol-of-vol) and −1.7 pp (skew), roughly 7–10 pp a year gross before costs. The t of 9 is consistency (IC −0.06 nearly every month), not a large effect. Both match the literature's sign (uncertainty about risk: Baltussen, van Bekkum, van der Grient 2018; realized skew: Amaya et al. 2015), and the skew result is research 0009's F1 confirmed at the slow horizon too. `vol_of_vol_60d` MID (t −2.70) is weaker and rides on realized vol (ρ 0.42).
- **Everything else fails:** order-flow imbalance, late-volume share (0009's S4), jump share, intraday Amihud, realized vol (as 0009 predicted). `smart_money_12_1` comes out with the WRONG SIGN in all three tiers (the last half hour minus the first half hour predicts the opposite of Lou–Polk–Skouras here, |t| ≤ 2).
- **Caveats that stand:** survivors only (Kite has no delisted names; the daily-data analogue check is not possible for minute measures); 80 overlapping anchors with Newey–West lag 2; 27 new rows join the multiple-testing ledger; costs not applied (these are monthly-rebalance signals in SMALL, where the real cost is 31 bps).
- **What to do with it:** register `vol_of_vol_60d` and `rskew_60d` as LIBRARY factors with a PIT twin that reads `data/intraday/daily_1m/` (one compute function, `factors.FACTORS`, `PIT_COLUMNS`), then the promotion review with `tools/multiple_testing.py` — SMALL only, negative sign. Not a weight from this table. Close the file on the other seven at the slow horizon.
