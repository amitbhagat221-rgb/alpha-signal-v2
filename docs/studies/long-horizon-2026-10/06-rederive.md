# Long horizon, step 6 — independent re-derivation of the H1 / H2 / H3 headline numbers — 2026-10-12

Plan 0024. Read-only on the DB. Tool: `python -m tools.lh_verify_rederive build | h1 | h2 | h2_sens | h3` (new file, about 10 minutes in all). Results: `data/lh/rederive_results.json`, logs `data/lh/rederive_*.log`, my own out-of-sample scores `data/lh/rederive_oos_scores.parquet`, per-month H2 records `data/lh/rederive_h2_{tier}.csv`.

I wrote the code from the study notes' definitions, straight from the panel, `pit.forward_returns` and the price table. I did not import or read any `tools/lh_*.py` logic before I had my numbers. The one exception the task allows is the cost model `tools.lh_costs.one_way_cost_bps`, used in step 3. After my numbers were in, I read `tools/lh_book.py` and ran it once, only to find where the MID book differs.

Tolerance: IC within 0.01, t within 0.5, excess within 1 %/yr, turnover within 15 %.

## Verdict
**Confirmed, with two minor issues.** Every H1 and H2 headline reproduces exactly. The H3 best-variant books reproduce within tolerance in SMALL and LARGE. In MID my excess return comes out **1.6 points a year higher** than the claim, which is outside the 1-point tolerance. The cause is a one-session difference in month-end marks (below). It makes the claimed MID result more cautious than mine, and MID still fails by a wide margin. The study's overall conclusion (H1 and H2 pass in MID and SMALL; H3 fails in every tier) stands.

## 1. H1 — the strongest slow factors (126-session IC, Newey-West t with lag 6)
Monthly anchors from `tools.backtest_pit._is_month_start_anchor`: 83 of them, 2019-12-02 → 2026-10-01. Spearman IC within the panel's cap tier, at least 20 stocks.

| tier | factor | anchors | IC 126 mine / claim | t 126 mine / claim | IC 21 / t 21 (mine) | match |
|---|---|---|---|---|---|---|
| MID | z_score | 76 | −0.0952 / −0.0952 | −5.75 / −5.75 | −0.0284 / −1.91 | yes |
| MID | interest_coverage | 76 | −0.0845 / −0.0845 | −5.02 / −5.02 | −0.0228 / −1.63 | yes |
| MID | roic | 76 | −0.0675 / −0.0675 | −4.27 / −4.27 | −0.0135 / −1.04 | yes |
| MID | piotroski_f (thin) | 20 | +0.0954 / +0.0954 | +11.59 / +11.59 | +0.0438 / +3.03 | yes |
| SMALL | cons_beat_rate_4q | 77 | +0.0802 / +0.0802 | +6.43 / +6.43 | +0.0442 / +5.03 | yes |
| SMALL | value_composite | 77 | +0.0951 / +0.0951 | +5.69 / +5.69 | +0.0336 / +4.11 | yes |
| SMALL | sector_tilt | 77 | +0.0728 / +0.0728 | +4.92 / +4.92 | +0.0356 / +4.19 | yes |
| LARGE | metals_beta | 77 | +0.0988 / +0.0988 | +3.73 / +3.73 | +0.0412 / +2.19 | yes |
| SMALL | delivery_anomaly_z (fast) | 74 | +0.0197 | +2.41 / +2.41 | +0.0321 / +7.15 (claim +7.15) | yes |

I did not re-derive the multiple-testing counts (M = 1,094; 91 BY survivors) or the three-period sign checks.

## 2. H2 — out-of-sample `slow_select`, my own walk-forward
For each test month I train only on months whose 126-session label had fully ended by the test anchor, and that are at least 6 anchors earlier. In practice that is a 7-month embargo. Testing starts at the first month with 24 such training months. In each training window, every candidate column (`tools.walk_forward._columns()`, 100 columns) with at least 12 months and a training |t| ≥ 2.5 is eligible. The 8 strongest go in at equal weight with their training sign. The score is the within-tier percentile composite, with a missing value counting as 0.5.

| | MID mine / claim | SMALL mine / claim | LARGE mine / claim |
|---|---|---|---|
| first test month · first training window | 2022-06-01 · 24 months 2019-12-02 → 2021-11-01 / same | same / same | same / same |
| test months · with a 126-session label | 53 · 47 / 53 · 47 | 53 · 47 / 53 · 47 | 53 · 47 / 53 · 47 |
| mean OOS IC 126 | 0.0873 / 0.0873 | 0.0725 / 0.0725 | −0.0040 / −0.0040 |
| **OOS IC 126, NW t (lag 6)** | **5.68 / 5.68** | **3.29 / 3.29** | −0.11 / −0.11 |
| non-overlapping t, median (lowest) of 6 offsets | 3.03 (2.55) / 3.03 (2.55) | 2.52 (2.30) / 2.52 (2.30) | 0.01 (−0.87) / — |
| top 15 minus tier average at 126 sessions | +0.67 % (t 0.31) / +0.67 % (t 0.31) | +4.86 % (t 2.71) / +4.86 % (t 2.71) | −0.97 % (t −0.66) / −0.97 % (t −0.66) |
| most-chosen factors | −z_score 96 %, −gross_profitability 91 %, +gold_beta 83 %, −inr_beta 83 % | cons_beat_rate_4q 100 %, value_composite 100 %, sector_tilt 83 % | — |

My score file matches `data/lh/oos_scores.parquet` (`slow_select`) **row for row**: 76,708 rows each, none missing on either side, largest absolute difference 0.0.

**Does the pass hold if the choices change?** (my own reruns, OOS IC 126 NW t):

| change | MID | SMALL |
|---|---|---|
| as claimed (12-month factor floor, 7-month embargo, 8 factors) | 5.68 | 3.29 |
| factor needs 24 training months, not 12 | 6.51 | 3.37 |
| embargo 12 anchors (testing starts 2022-11, 42 months with a label) | 6.35 | 6.49 |
| 4 factors, not 8 | 5.19 | 3.76 |

All of these clear 2.0. The non-overlapping medians stay between 2.49 and 4.38 in every rerun. The H2 pass in MID and SMALL is not a product of these three choices. It still shares every input with the claim: the same panel, the same label and today's factor registry as the candidate list (see "What this does not check").

## 3. H3 — the best variant per tier, my own simple simulator
No tier is claimed to pass H3. I still rebuilt each tier's best variant, because the "fail" verdict rests on those numbers.

My simulator works like this:
- Trades at the entry session after each anchor.
- Marks every holding by its adjusted close (dividends included) at the next anchor's entry session.
- Equal weight at entry, no trimming, cash earns 0 %.
- Buys only from the top N and sells only below rank k·N, after the minimum hold.
- Defers a gain sale that turns long-term within 42 days.
- Sells at once on a red flag (`forensic_penalty` ≤ −0.20).
- Band-tests a stock that changed tier against its percentile in the new tier.

Benchmark: the tier index plus the claimed dividend credit (MID: the tier equal-weight average for the first 12 months). There is no tax here, so the comparable claimed figures are the **pre-tax** ones in `book_variants.csv`. Turnover is the pre-tax run's.

| tier · rule | book CAGR mine / claim | benchmark CAGR mine / claim | **excess, pre-tax with costs** mine / claim | excess pre-cost (mine) | **turnover** mine / claim | median hold (Kaplan-Meier) mine / claim | match |
|---|---|---|---|---|---|---|---|
| SMALL · M · N10 · k3 · avg3 · hold 12 | 39.69 % / 39.50 % | 18.47 % / 18.47 % | **+21.22 % / +21.03 %** | +22.26 % | **91 % / 88 %** | 13.0 / 12.9 months | yes |
| MID · M · N15 · k3 · raw · hold 6 | 26.86 % / 25.21 % | 18.78 % / 18.71 % | **+8.09 % / +6.50 %** | +8.49 % | **69 % / 72 %** | 12.0 / 10.1 months | **excess no (Δ 1.6)**; turnover yes |
| LARGE · Q · N20 · k4 · raw · hold 6 | 16.77 % / 16.85 % | 8.90 % / 8.88 % | **+7.88 % / +7.96 %** | +8.00 % | **26 % / 26 %** | 27.0 / 27.0 months | yes |

Other figures from my runs, with costs:
- **SMALL:** 48 positions, 20 tax deferrals (claim 21), costs ₹78,455 in the pre-tax run, monthly-excess NW t 1.83 pre-tax (the claimed after-tax t is 1.81). Against the tier equal-weight average: +18.0 %/yr.
- **MID:** NW t 1.92 pre-tax.
- **LARGE:** NW t 1.26.

None of these comes near the raw t of about 3.5 that 48 variants need for a haircut t of 2.0. So the H3 "fail" holds in my numbers too.

**Why MID differs.** My MID book and the claimed pre-tax book (`tools.lh_book.simulate` with tax off, run once for this check) agree to four decimals every month until 2024-05. They split in the month from 2024-05-01 to 2024-06-03 (mine −4.23 %, theirs −3.78 %), and again in 2024-09 and 2025-01. The cause is the price table:
- It holds a Saturday special session on **2024-05-18** for only 1,411 of about 1,660 stocks.
- `pit.forward_returns` (and the `fwd_next_anchor` mark built the same way) counts the exit as "entry + h rows" in each stock's own price series. For the roughly 250 stocks without the 2024-05-18 row, the exit therefore lands one session late: **2024-06-05 instead of 2024-06-04**, the election-result day.
- The proximity guard (±7 days) lets this through. So in that month, part of the claimed book is marked a day later than the rest and than the index.

My marks use one date for every stock. After that month the two books hold slightly different names, and the gap grows to 1.6 points a year. The claimed MID number is therefore **too low, not too high**. MID still fails (t 1.92 before tax, far from 3.5), so the verdict does not change.

## Issues found
1. **(minor) MID H3 excess is outside tolerance by 0.6 points**: +8.09 % mine against +6.50 % claimed, pre-tax with costs. The cause is the one-session mark misalignment above. It does not change the fail verdict, but the MID row of `05-book.md` understates MID by about 1.6 %/yr pre-tax.
2. **(minor) `pit.forward_returns` counts sessions in each stock's own rows, so a partial market session shifts exits by a day.** Two sessions in the table cause this:
   - **2024-05-18** (DR-drill Saturday, 1,411 stocks). It affects every 21/63/126/252-session label whose window crosses that date, for about 15 % of stocks.
   - **2026-09-14**, a single stray row: `RST`, source `yfinance.BO`, zero volume, on an NSE holiday. It adds one fake session to the market calendar.

   On an ordinary exit day a one-day shift is noise. On 2024-06-04 it is not. The fix belongs in the shared label: count sessions on the market calendar, or require the exit date to equal the target. That fix is outside this read-only study.
3. **(minor, mine) My first H3 run had two errors I found and fixed:**
   - It gave no score to a held stock that had changed tier, so the stock was sold at once.
   - It added the dividend credit to MID's equal-weight months, which already carry dividends.

   The numbers above are after both fixes.

## What this does not check
- **Same definitions, same inputs.** My code uses the definitions written in the notes: candidate set, top 8, |t| ≥ 2.5, 12-month floor, composite formula, label. That is why the match is exact. It shows those definitions were implemented correctly. It does not show they are the right ones. My reruns above cover three of the choices.
- **The candidate list is today's registry.** Factors that were added because they worked on this history are offered to the 2022 training windows. That is a mild hindsight effect, not measured here.
- **Survivorship** (fundamentals hold today's listed firms only) affects my numbers exactly as it affects the claimed ones. My SMALL excess against the equal-weight tier average, which shares that bias, is +18.0 %/yr pre-tax.
- **Not re-derived:** tax, the 48-variant grid, the haircut and deflated Sharpe, the multiple-testing counts, and the cost calibration itself.
