# Rank-IC localization mini-study (plan 0012 A1)

Read-only study. Decides whether conviction sizing (WS1.4) is worth building: does realized edge concentrate at the top of the rank, or is it flat across the picked list?

## Lens 1 — pick_outcomes (realized), window_days=20

Bucket stats — n, mean/median excess_return_pct, hit rate:

| cap_tier | bucket | n | mean_excess | median_excess | hit_rate |
| --- | --- | --- | --- | --- | --- |
| LARGE | 1-5 | 215 | -0.5729 | -1.2921 | 0.4744 |
| LARGE | 6-10 | 215 | -2.2397 | -0.7356 | 0.4372 |
| LARGE | 11-20 | 430 | 0.733 | 1.1552 | 0.5651 |
| LARGE | 21-50 | 1290 | -0.6792 | -0.2742 | 0.4891 |
| MID | 1-5 | 215 | -1.2677 | -1.9471 | 0.4047 |
| MID | 6-10 | 215 | 1.5813 | 1.707 | 0.614 |
| MID | 11-20 | 430 | -0.1154 | -0.2255 | 0.4907 |
| MID | 21-50 | 1290 | 0.4046 | -0.8034 | 0.4519 |
| SMALL | 1-5 | 215 | 2.2948 | 1.2336 | 0.5256 |
| SMALL | 6-10 | 215 | 0.7747 | -3.2113 | 0.4 |
| SMALL | 11-20 | 421 | -3.3048 | -4.5042 | 0.2922 |
| SMALL | 21-50 | 1276 | -1.191 | -2.6568 | 0.4028 |


Two-sample t-test, bucket 1-5 vs 6-10 (Welch, unequal variance):

| cap_tier | n_1_5 | n_6_10 | t_stat | p_value |
| --- | --- | --- | --- | --- |
| LARGE | 215 | 215 | 1.78 | 0.0759 |
| MID | 215 | 215 | -3.398 | 0.0007 |
| SMALL | 215 | 215 | 1.208 | 0.2276 |


## Lens 2 — daily_snapshots_pit single-factor proxy (SMALL only)

Ranked by `delivery_anomaly_z` (sole robust SMALL factor), latest 24 anchors, quintile-1 (top) vs quintile-2 mean `fwd_return_20d`. **This is a single-factor proxy, not the model.**

| quintile | n | mean_fwd_return_20d |
| --- | --- | --- |
| Q1 (top delivery_anomaly_z) | 6117 | 0.0272 |
| Q2 | 6107 | 0.0268 |


Per-anchor detail:

| snapshot_date | n | q1_mean | q2_mean |
| --- | --- | --- | --- |
| 2026-01-23 | 1427 | 0.0569 | 0.0595 |
| 2026-01-30 | 1430 | -0.0075 | 0.0118 |
| 2026-02-02 | 1433 | -0.007 | -0.0052 |
| 2026-02-06 | 1433 | -0.0497 | -0.0599 |
| 2026-02-13 | 1437 | -0.0929 | -0.0922 |
| 2026-02-20 | 1445 | -0.0771 | -0.0926 |
| 2026-02-27 | 1442 | -0.1108 | -0.1013 |
| 2026-03-02 | 1444 | -0.1196 | -0.1215 |
| 2026-03-06 | 1441 | -0.0371 | -0.0375 |
| 2026-03-13 | 1450 | 0.0869 | 0.0849 |
| 2026-03-20 | 1452 | 0.1276 | 0.1351 |
| 2026-03-27 | 1458 | 0.1929 | 0.183 |
| 2026-04-01 | 1458 | 0.1862 | 0.1766 |
| 2026-04-03 | 1462 | 0.1512 | 0.1567 |
| 2026-04-10 | 1469 | 0.1047 | 0.1267 |
| 2026-04-17 | 1481 | 0.0177 | 0.0101 |
| 2026-04-24 | 1482 | 0.0254 | 0.0262 |
| 2026-05-01 | 1484 | 0.0256 | 0.0252 |
| 2026-05-08 | 1485 | -0.0125 | -0.0187 |
| 2026-05-15 | 1482 | 0.0438 | 0.0345 |
| 2026-05-22 | 1480 | 0.058 | 0.0557 |


## Verdict

**Localizes.** Bucket 1-5 beats 6-10 with t >= 1.5 in LARGE (pick_outcomes lens) — conviction sizing (WS1.4) has real evidence behind it and is worth prototyping, though the single-factor PIT proxy should be read as corroborating context, not proof, since it isolates one factor rather than the full model. A human should scope a conviction-weighting design before building.
