# Day / night factors, filing timing and the ASM trigger — study 2026-10-16

**Status:** done, read-only, nothing registered or wired · **Tool:** `python -m tools.day_night_study --md FILE` (≈4 min) · **Pre-registration:** [research 0009](../research/0009-intraday-factor-menu.md) S1 S2 S3 F6, [research 0010](../research/0010-minute-bar-uses/0010-minute-bar-uses.md) P2 P3 G1. These are the candidates that need no minute bars.
**Sample:** 82 monthly anchors 2019-12 → 2026-09, point-in-time cap tier, panel label `fwd_return_20d`, the backtest's own IC engine. Survivorship check on everything that traded (5,332 symbols incl. delisted), split by 90-day traded value. Day return = ln(close/open); night return = adjusted close-to-close minus the day return.

## Verdicts

| Candidate | Pre-registered | Result | Verdict |
|---|---|---|---|
| `mom_intraday_12_1` (Σ day returns, months −12…−2) | + | SMALL t 3.76, MID 2.98, LARGE 1.28; halves agree. **Net of `mom_6m`, `residual_momentum_12_1` and total 12-1 momentum together: SMALL t 3.07, MID 1.05, LARGE 1.43.** Full market (incl. delisted) tradeable t 3.92 | **SMALL promotion candidate.** Clears 2.5 incrementally, not the 4.2 Bonferroni bar. MID/LARGE add nothing over existing momentum |
| `mom_overnight_12_1` (Σ night returns) | two-sided | t −1.47 / −0.27 / −1.35 (L/M/S); full-market tradeable −1.99 | DROP. The night half drags momentum down: total 12-1 scores SMALL t 2.78 vs the day half alone 3.76 |
| `tug_of_war_3m` | + | all tiers \|t\| ≤ 1.02 | DROP (only delisted thin names give t +2.81; not robust) |
| `overnight_ret_1m` | + (India prior) | SMALL t −1.86; full-market thin −4.24, tradeable −2.17 | **WRONG SIGN.** Short-run night gains reverse. The negative version is a post-hoc idea, not a pass |
| `day_night_beta_gap` (β day − β night, 252 sessions) | two-sided | SMALL t 1.59, MID 1.09, LARGE 0.39; full market +2.39 tradeable, +2.84 thin | WEAK. Retest with the minute-bar asynchronous beta |
| ASM up-flag (5-day return ≥ NIFTY 50 + 25 % in the last 5 sessions) | flagged underperform | SMALL +0.4 % over 20 days, t +0.49; inside the top lottery quintile also nothing | **DROP as a gate.** The price trigger alone does not mark losers |
| ASM down-flag (≤ NIFTY 50 − 25 %) | flagged underperform | Full-market tradeable −7.7 %, t −5.74 (34 anchors, ~7 names each), −8.0 % without Mar–May 2020; survivors only −5.2 %, t −2.46 (17 anchors). Median flagged return 0.0 % and 62 % are non-universe names, so many stop trading | **Suggestive crash-continuation gate, not passed.** Needs an event-level test (60-day horizon, suspended names handled) |
| Results filed in session vs outside: drift after the reaction day | two-sided | All tiers t 0.77 (SMALL 1.12) | DROP for P2 |

## Side findings (not pre-registered, descriptive only)

- **After-hours results are worse news.** Reaction-day return: in session +0.00 %, outside −0.68 % (difference t 4.78, 30,589 filings, 2019-12 →). This fits Indian evidence that big surprises are filed after hours. It is not tradeable before the filing.
- **Drift after the reaction follows the reaction mostly for after-hours filings** (drift × sign of reaction: SMALL outside +1.02 %, in session +0.55 %, difference t −1.99). This favours the minute-anchored `announcement_car` (research 0010 P1). Its daily version mixes pre-filing minutes into the day-0 return of in-session filings.

## What to do next

1. `mom_intraday_12_1` → register as LIBRARY (one compute function in `pit`, PIT column), then the SMALL promotion review with the whole-score test and the multiple-testing haircut. It writes a PIT column over all anchors, which is a long DB writer: do it on a worktree branch when no other long writer runs.
2. ASM down-flag → event study with 60-day horizon before any gate.
3. Beta gap → wait for the minute bars (asynchronous beta, research 0010 P3).

## Full tables

### Factor ICs (panel, PIT tier, label fwd_return_20d)

| signal | group | n | stocks | mean_ic | t | ic_h1 | ic_h2 | halves | corr_mom_6m | max_corr | max_corr_with | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mom_intraday_12_1 | LARGE | 82 | 98 | +0.0231 | +1.2800 | +0.0440 | +0.0022 | True | +0.5440 | +0.6304 | residual_momentum_12_1 | DROP |
| mom_intraday_12_1 | MID | 82 | 146 | +0.0441 | +2.9800 | +0.0483 | +0.0399 | True | +0.6022 | +0.7091 | residual_momentum_12_1 | WEAK |
| mom_intraday_12_1 | SMALL | 82 | 892 | +0.0445 | +3.7600 | +0.0336 | +0.0554 | True | +0.4515 | +0.5392 | residual_momentum_12_1 | WEAK |
| mom_overnight_12_1 | LARGE | 82 | 98 | -0.0288 | -1.4700 | -0.0664 | +0.0088 | False | +0.1306 | +0.4668 | low_vol_252d | DROP |
| mom_overnight_12_1 | MID | 82 | 146 | -0.0040 | -0.2700 | -0.0125 | +0.0044 | False | +0.1580 | +0.3841 | low_vol_252d | DROP |
| mom_overnight_12_1 | SMALL | 82 | 892 | -0.0127 | -1.3500 | -0.0078 | -0.0176 | True | +0.1683 | +0.4491 | low_vol_252d | DROP |
| tug_of_war_3m | LARGE | 82 | 99 | -0.0142 | -1.0200 | -0.0359 | +0.0074 | False | -0.0272 | -0.1751 | pcr_volume | DROP |
| tug_of_war_3m | MID | 82 | 149 | -0.0038 | -0.3100 | -0.0139 | +0.0063 | False | -0.1018 | -0.1592 | st_reversal_21d | DROP |
| tug_of_war_3m | SMALL | 82 | 942 | -0.0039 | -0.5700 | -0.0002 | -0.0075 | True | -0.1864 | -0.1864 | mom_6m | DROP |
| overnight_ret_1m | LARGE | 82 | 99 | -0.0097 | -0.5400 | -0.0318 | +0.0123 | False | +0.0814 | +0.3179 | max_lottery_21d | DROP |
| overnight_ret_1m | MID | 82 | 149 | -0.0116 | -0.8000 | -0.0123 | -0.0109 | True | +0.0626 | +0.2328 | max_lottery_21d | DROP |
| overnight_ret_1m | SMALL | 82 | 953 | -0.0123 | -1.8600 | -0.0089 | -0.0156 | True | +0.0221 | +0.2647 | max_lottery_21d | WRONG SIGN |
| day_night_beta_gap | LARGE | 82 | 98 | +0.0058 | +0.3900 | +0.0005 | +0.0112 | True | +0.0326 | -0.2409 | avg_delivery_pct_30d | DROP |
| day_night_beta_gap | MID | 82 | 146 | +0.0153 | +1.0900 | +0.0094 | +0.0211 | True | -0.0315 | -0.2613 | avg_delivery_pct_30d | DROP |
| day_night_beta_gap | SMALL | 82 | 899 | +0.0101 | +1.5900 | +0.0102 | +0.0099 | True | +0.0260 | +0.1661 | value_composite | WEAK |

### Reference: total 12-1 momentum computed the same way

| signal | group | n | mean_ic | t |
|---|---|---|---|---|
| mom_total_12_1 | LARGE | 82 | +0.0049 | +0.2300 |
| mom_total_12_1 | MID | 82 | +0.0442 | +2.5300 |
| mom_total_12_1 | SMALL | 82 | +0.0394 | +2.7800 |

### mom_intraday_12_1 net of the momentum we already have (rank residual IC)

| signal | net_of | tier | n | mean_ic | t |
|---|---|---|---|---|---|
| mom_intraday_12_1 | mom_6m | LARGE | 82 | +0.0305 | +1.8800 |
| mom_intraday_12_1 | mom_6m | MID | 82 | +0.0247 | +1.9400 |
| mom_intraday_12_1 | mom_6m | SMALL | 82 | +0.0306 | +3.1100 |
| mom_intraday_12_1 | residual_momentum_12_1 | LARGE | 82 | +0.0164 | +0.9900 |
| mom_intraday_12_1 | residual_momentum_12_1 | MID | 82 | +0.0099 | +0.7900 |
| mom_intraday_12_1 | residual_momentum_12_1 | SMALL | 82 | +0.0261 | +2.9600 |
| mom_intraday_12_1 | mom_total_12_1 | LARGE | 82 | +0.0234 | +1.4300 |
| mom_intraday_12_1 | mom_total_12_1 | MID | 82 | +0.0155 | +1.1500 |
| mom_intraday_12_1 | mom_total_12_1 | SMALL | 82 | +0.0264 | +2.8900 |
| mom_intraday_12_1 | mom_6m + residual_momentum_12_1 + mom_total_12_1 | LARGE | 82 | +0.0223 | +1.4300 |
| mom_intraday_12_1 | mom_6m + residual_momentum_12_1 + mom_total_12_1 | MID | 82 | +0.0125 | +1.0500 |
| mom_intraday_12_1 | mom_6m + residual_momentum_12_1 + mom_total_12_1 | SMALL | 82 | +0.0263 | +3.0700 |

### Survivorship check (own 20-session label; delisted names exit at last close)

| scope | signal | group | n | stocks | mean_ic | t |
|---|---|---|---|---|---|---|
| universe only | mom_intraday_12_1 | tradeable | 82 | 1135 | +0.0457 | +3.4100 |
| universe only | mom_intraday_12_1 | thin | 82 | 309 | +0.0328 | +2.7400 |
| universe only | mom_overnight_12_1 | tradeable | 82 | 1134 | -0.0189 | -1.5000 |
| universe only | mom_overnight_12_1 | thin | 82 | 309 | -0.0160 | -1.5100 |
| universe only | tug_of_war_3m | tradeable | 82 | 1189 | -0.0064 | -1.0000 |
| universe only | tug_of_war_3m | thin | 82 | 338 | -0.0184 | -1.7700 |
| universe only | overnight_ret_1m | tradeable | 82 | 1200 | -0.0141 | -1.6800 |
| universe only | overnight_ret_1m | thin | 82 | 343 | -0.0250 | -3.2500 |
| universe only | day_night_beta_gap | tradeable | 82 | 1142 | +0.0110 | +1.6800 |
| universe only | day_night_beta_gap | thin | 82 | 313 | +0.0067 | +1.0300 |
| everything that traded | mom_intraday_12_1 | tradeable | 82 | 1299 | +0.0495 | +3.9200 |
| everything that traded | mom_intraday_12_1 | thin | 82 | 801 | +0.0281 | +2.9600 |
| everything that traded | mom_overnight_12_1 | tradeable | 82 | 1299 | -0.0221 | -1.9900 |
| everything that traded | mom_overnight_12_1 | thin | 82 | 799 | -0.0069 | -0.7700 |
| everything that traded | tug_of_war_3m | tradeable | 82 | 1371 | +0.0024 | +0.4300 |
| everything that traded | tug_of_war_3m | thin | 82 | 883 | +0.0310 | +2.8100 |
| everything that traded | overnight_ret_1m | tradeable | 82 | 1389 | -0.0166 | -2.1700 |
| everything that traded | overnight_ret_1m | thin | 82 | 896 | -0.0359 | -4.2400 |
| everything that traded | day_night_beta_gap | tradeable | 82 | 1309 | +0.0156 | +2.3900 |
| everything that traded | day_night_beta_gap | thin | 82 | 818 | +0.0176 | +2.8400 |

### ASM price-trigger gate: flagged − unflagged 20-day return (panel tiers)

| flag | group | anchors | flagged_avg | diff_20d | t | hit |
|---|---|---|---|---|---|---|
| asm_up_flag | LARGE | 1 |  |  |  |  |
| asm_up_flag | MID | 9 | +4.7778 | +0.0137 | +0.4317 | +0.5556 |
| asm_up_flag | SMALL | 82 | 17.2 | +0.0036 | +0.4906 | +0.5610 |
| asm_down_flag | LARGE | 1 |  |  |  |  |
| asm_down_flag | MID | 1 |  |  |  |  |
| asm_down_flag | SMALL | 15 | +7.0000 | -0.0405 | -1.5559 | +0.6000 |

### ASM gate on everything that traded (own label)

| flag | group | anchors | flagged_avg | diff_20d | t | hit |
|---|---|---|---|---|---|---|
| asm_up_flag | tradeable | 82 | 23.8 | +0.0030 | +0.4029 | +0.5000 |
| asm_up_flag | thin | 82 | 31.3 | -0.0038 | -0.3754 | +0.6463 |
| asm_down_flag | tradeable | 34 | +6.9706 | -0.0767 | -5.7375 | +0.8824 |
| asm_down_flag | thin | 47 | +7.8298 | -0.0024 | -0.1096 | +0.5319 |

### ASM down-flag robustness

| flag | group | anchors | flagged_avg | diff_20d | t | hit | sample |
|---|---|---|---|---|---|---|---|
| asm_down_flag | tradeable | 34 | +6.9706 | -0.0767 | -5.7375 | +0.8824 | everything |
| asm_down_flag | thin | 47 | +7.8298 | -0.0024 | -0.1096 | +0.5319 | everything |
| asm_down_flag | tradeable | 17 | +7.5882 | -0.0515 | -2.4617 | +0.7647 | universe only |
| asm_down_flag | thin | 7 | +9.0000 | -0.1362 | -3.0412 | +0.8571 | universe only |
| asm_down_flag | tradeable | 33 | +5.4242 | -0.0798 | -5.9591 | +0.9091 | everything, excl. 2020-03…2020-05 |
| asm_down_flag | thin | 44 | +5.5227 | -0.0154 | -0.6908 | +0.5682 | everything, excl. 2020-03…2020-05 |

{'n': 693, 'outside_share': 0.6204906204906205, 'median': 0.0, 'mean': 0.06276985392522773, 'median_unflagged': -0.0001612903225807205}

### ASM up-flag inside the top max_lottery quintile

| flag | group | anchors | flagged_avg | diff_20d | t | hit |
|---|---|---|---|---|---|---|
| asm_up_flag | LARGE | 0 |  |  |  |  |
| asm_up_flag | MID | 9 | +4.1111 | +0.0383 | +1.4614 | +0.3333 |
| asm_up_flag | SMALL | 82 | 15.5 | +0.0026 | +0.3270 | +0.5610 |

### Results filed in session vs outside (in − out, month-clustered t)

| tier | measure | events | in_session_share | mean_in | mean_out | months | diff | t |
|---|---|---|---|---|---|---|---|---|
| LARGE | drift (tier-adjusted) | 2626 | +0.3618 | +0.0014 | -0.0010 | 57 | -0.0010 | -0.1019 |
| LARGE | drift × sign(reaction) | 2626 | +0.3618 | +0.0031 | +0.0053 | 57 | -0.0052 | -0.7609 |
| LARGE | reaction day | 2626 | +0.3618 | +0.0013 | -0.0020 | 57 | +0.0049 | +2.8667 |
| MID | drift (tier-adjusted) | 3922 | +0.3440 | -0.0027 | -0.0002 | 59 | -0.0022 | -0.6246 |
| MID | drift × sign(reaction) | 3922 | +0.3440 | +0.0060 | +0.0080 | 59 | -0.0048 | -0.7615 |
| MID | reaction day | 3922 | +0.3440 | +0.0022 | -0.0018 | 59 | +0.0068 | +3.5052 |
| SMALL | drift (tier-adjusted) | 24041 | +0.3257 | -0.0061 | -0.0047 | 75 | +0.0084 | +1.1232 |
| SMALL | drift × sign(reaction) | 24041 | +0.3257 | +0.0055 | +0.0102 | 75 | -0.0135 | -1.9876 |
| SMALL | reaction day | 24041 | +0.3257 | -0.0005 | -0.0081 | 75 | +0.0082 | +4.6807 |
| ALL | drift (tier-adjusted) | 30589 | +0.3312 | -0.0049 | -0.0038 | 77 | +0.0058 | +0.7741 |
| ALL | drift × sign(reaction) | 30589 | +0.3312 | +0.0053 | +0.0095 | 77 | -0.0129 | -1.7464 |
| ALL | reaction day | 30589 | +0.3312 | +0.0000 | -0.0068 | 77 | +0.0074 | +4.7812 |
