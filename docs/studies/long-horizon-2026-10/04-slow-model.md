# Long horizon, step 2 — does a slow model work on months it has not seen? (H2) — 2026-10-12

Plan 0024, H2. Read-only on the DB. Tool: `python -m tools.lh_slow_model` (about 10 minutes; `--reuse` re-summarises the saved records). Machine-readable: `data/lh/slow_model.json`, `data/lh/slow_model_summary.csv`, one row per (tier, method, month) in `data/lh/slow_model_records.csv`, every month's chosen factors and weights in `data/lh/slow_model_choices.csv`. The out-of-sample scores for the book simulator are in `data/lh/oos_scores.parquet` (381,240 rows).

## Verdict
**H2 passes in MID and SMALL and fails in LARGE.** The plan's bar is an out-of-sample rank IC t ≥ 2.0 at 126 sessions in MID or SMALL. Both slow methods clear it in both tiers:

| tier | slow_select | slow_icw | blend (slow + fast) | fast_select (control) | live (control, **not** out of sample) | H2 |
|---|---|---|---|---|---|---|
| LARGE | −0.11 | 0.77 | −0.04 | 0.16 | 2.79 | **fail** |
| MID | **5.68** | **2.81** | 3.97 | 2.81 | 7.74 | **pass** |
| SMALL | **3.29** | **3.63** | 5.60 | 5.43 | 9.37 | **pass** |

*Out-of-sample 126-session rank IC, Newey-West t (lag 6), 47 months with a 126-session label, 2022-06 → 2026-04 anchors.*

A pass here only says the slow model **ranks** stocks well over 6 months. It does not yet say a long-only book of its top names earns money. Four things to keep in mind before H3:

1. **MID's skill is not at the top.** The MID slow model's top 15 beat the MID average by only **+0.67 %** over 126 sessions (t 0.31); `slow_icw`'s top 15 by +1.52 % (t 0.64). The IC comes from the weak end: the bottom four tenths lag the tier. The factors it keeps choosing are the H1 "weak firms did better" set, all chosen with a **negative** sign: `z_score` (in 96 % of months), `gross_profitability` (91 %), `roic` (74 %), `interest_coverage` (68 %), plus `inr_beta` (−, 83 %) and `gold_beta` (+, 83 %). The fundamentals panel holds only today's listed companies, so weak firms in it are the ones that survived. That bias would produce exactly this pattern. **A long-only MID book is unlikely to earn from this model.** The live MID weights' top 15 did +8.11 % (t 5.78), but those were chosen on this same history.
2. **SMALL's skill does reach the top.** Top 15 over the SMALL average: `slow_select` +4.86 % at 126 sessions (t 2.71) and +7.37 % at 252 (t 4.20); `slow_icw` +9.93 % (t 2.91) and +18.06 % (t 2.19). These are before costs and tax.
3. **The Newey-West t is generous with long overlaps.** A check that uses only non-overlapping months (every 6th month, 8 months per starting offset, plain t, median over the 6 offsets) gives: MID `slow_select` 3.03 (lowest offset 2.55), MID `slow_icw` 2.28 (1.66), SMALL `slow_select` 2.52 (2.30), SMALL `slow_icw` 3.13 (2.57). The medians still clear 2.0, but with only 8 months each they are thin. The 252-session t's (MID `slow_select` 13.94, SMALL live 17.40) are not to be trusted: the non-overlapping version has 3 months per offset.
4. **SMALL is weaker recently.** In the 16 months from 2025, SMALL's 126-session IC was 0.0584 (t 1.99) for `slow_select` and 0.0634 (t 2.04) for `slow_icw`, against 0.0894 and 0.1607 in 2023-24.

**Do fast signals add anything?** Not to the ranking at 6 months, and they cost stability. In SMALL, `blend` has the same 126-session IC as `slow_select` (0.0734 vs 0.0725). Its t is higher (5.60 vs 3.29) because it is steadier month to month. But its top 15 earn less (+3.35 % vs +4.86 % at 126 sessions) and its top 20 churn more (48 % still in the top 60 a month later, against 67 %). In MID, `blend` IC 0.0914 against 0.0873 for `slow_select`. This supports the plan's rule: fast signals at most as a timing overlay, never deciding membership.

**How much hindsight is in the live weights?** The live weights beat every out-of-sample method in every tier, but they were picked on this history. In LARGE, live has t 2.79 while every honest method is near zero: LARGE's live edge is hindsight. This supports LARGE as the index.

## Stability — what drives turnover
Share of the top 20 at one month still in the top 60 the next month (stocks that left the tier are not counted; 3–7 % of the top 20 leave the tier each month):

| tier | slow_select | slow_icw | blend | fast_select | live |
|---|---|---|---|---|---|
| LARGE | 0.936 | 1.000 | 0.893 | 0.868 | 0.916 |
| MID | 0.982 | 0.989 | 0.819 | 0.646 | 0.954 |
| SMALL | **0.666** | **0.864** | 0.482 | 0.346 | 0.403 |

SMALL is where turnover lives today. The slow models hold their top names far better than the live weights: 67 % (`slow_select`) and 86 % (`slow_icw`) against 40 % for live and 35 % for fast. `slow_icw` spreads its weight over about 59 factors, so a month's change in one factor moves the score little.

How often the chosen set changed from one month to the next (any factor in or out, or a sign flip): `slow_select` 62 % / 42 % / 67 % of months (LARGE / MID / SMALL), but the average overlap with the previous month's set (Jaccard) was 0.83 / 0.90 / 0.83. Most changes swap one factor at the tail of the eight. SMALL `slow_select` chose `cons_beat_rate_4q` and `value_composite` in every month and `sector_tilt` in 83 % of months.

## Full table (out of sample, 53 monthly anchors 2022-06-01 → 2026-10-01)
IC at each horizon with its Newey-West t (lag = horizon in months), and the top tenth / top 15 minus the tier average in %. n = months with that label: 52 at 21 sessions, 50 at 63, 47 at 126, 40 at 252 (fewer for `fast_select` in LARGE and MID, which had no factor clearing its bar in some months: 39 and 47 months scored).

| tier | method | factors (avg) | IC63 (t) | IC126 (t) | IC252 (t) | top10 126 % (t) | top15 126 % (t) | top15 252 % (t) |
|---|---|---|---|---|---|---|---|---|
| LARGE | slow_select | 6.1 | 0.0026 (0.10) | −0.0040 (−0.11) | 0.0120 (0.33) | −1.56 (−1.08) | −0.97 (−0.66) | −1.43 (−0.65) |
| LARGE | slow_icw | 57.8 | 0.0481 (1.01) | 0.0511 (0.77) | 0.0646 (1.11) | −0.92 (−0.35) | −0.88 (−0.40) | −1.00 (−0.37) |
| LARGE | blend | 7.6 | 0.0119 (0.36) | −0.0016 (−0.04) | 0.0008 (0.02) | −0.31 (−0.19) | −0.13 (−0.08) | 0.47 (0.16) |
| LARGE | fast_select | 2.0 | 0.0243 (0.60) | 0.0064 (0.16) | −0.0069 (−0.31) | 1.66 (0.72) | 2.60 (1.46) | 2.74 (2.12) |
| LARGE | live | 4.0 | 0.0890 (3.00) | 0.0995 (2.79) | 0.1452 (2.24) | 3.91 (1.67) | 3.94 (2.17) | 8.91 (2.84) |
| MID | slow_select | 7.9 | 0.0524 (3.79) | 0.0873 (5.68) | 0.1185 (13.94) | 0.67 (0.31) | 0.67 (0.31) | 0.46 (0.13) |
| MID | slow_icw | 57.8 | 0.0741 (2.85) | 0.1137 (2.81) | 0.1349 (2.99) | 1.52 (0.64) | 1.52 (0.64) | 3.58 (0.94) |
| MID | blend | 10.7 | 0.0626 (4.69) | 0.0914 (3.97) | 0.1027 (6.34) | 0.53 (0.37) | 0.53 (0.37) | 0.33 (0.22) |
| MID | fast_select | 3.1 | 0.0528 (4.53) | 0.0629 (2.81) | 0.0525 (2.64) | 1.20 (0.59) | 1.23 (0.60) | 0.43 (0.12) |
| MID | live | 7.0 | 0.1132 (7.84) | 0.1421 (7.74) | 0.1151 (5.37) | 8.11 (5.78) | 8.11 (5.78) | 8.80 (2.39) |
| SMALL | slow_select | 8.0 | 0.0557 (3.48) | 0.0725 (3.29) | 0.0868 (4.13) | 4.38 (4.16) | 4.86 (2.71) | 7.37 (4.20) |
| SMALL | slow_icw | 59.3 | 0.0828 (4.12) | 0.1154 (3.63) | 0.1366 (3.02) | 7.54 (2.71) | 9.93 (2.91) | 18.06 (2.19) |
| SMALL | blend | 13.8 | 0.0626 (5.26) | 0.0734 (5.60) | 0.0804 (8.57) | 3.78 (3.61) | 3.35 (2.40) | 6.05 (2.04) |
| SMALL | fast_select | 5.8 | 0.0505 (5.48) | 0.0546 (5.43) | 0.0540 (4.49) | 1.38 (1.47) | 0.75 (0.46) | 1.41 (0.41) |
| SMALL | live | 6.0 | 0.0776 (8.83) | 0.0904 (9.37) | 0.0917 (17.40) | 5.07 (4.39) | 7.87 (2.28) | 14.77 (2.43) |

126-session IC by period (t, months): see `slow_model_summary.csv` columns `ic126_2022` / `_2023-24` / `_2025-26`. LARGE `slow_select` was −0.1518 in 2022 (7 months), 0.002 in 2023-24 and 0.0517 in 2025-26. MID `slow_select` was positive in all three (0.0844 / 0.0774 / 0.1032), as was SMALL `slow_select` (0.0468 / 0.0894 / 0.0584).

## How it was done
- **Clock.** The 83 monthly anchors of `daily_snapshots_pit` (`tools.backtest_pit._is_month_start_anchor`), 2019-12-02 → 2026-10-01. Labels: `data/lh/labels.parquet` (step 1, `pit.forward_returns`).
- **Training window (expanding).** For test month k, a training month j counts only if its 126-session label was fully known by k's close: at least 127 sessions from j's entry to k's entry, and at least 6 months apart. In practice that is 7 months of embargo. The first test month is the first with 24 such training months: **2022-06-01**, trained on 2019-12-02 … 2021-11-01. All five methods are scored on the same 53 months.
- **Candidate factors.** The 100 IC-rankable registry columns of `tools.walk_forward._columns()` that the panel carries, including benched factors and the macro betas (`gold_beta`, `inr_beta`, `metals_beta`, …). Nothing is hand-picked.
- **Methods, each chosen from the training window only:**
  - `slow_select`: factors with at least 12 training months and |Newey-West t (lag 6) of the training IC126| ≥ 2.5. The 8 strongest, equal weight, training sign.
  - `slow_icw`: every factor with at least 24 training months; weight = its training mean IC126.
  - `blend`: the average of the `slow_select` and `fast_select` scores (each 0–1). If one has no factor that month, the other alone.
  - `fast_select`: `tools.walk_forward`'s `select`, on the panel's 20-session label with a one-month embargo (≥ 12 months, |t| ≥ 2.5, 6 strongest).
  - `live`: today's `factors.SIGNAL_WEIGHTS`, fixed. A control. It was chosen on this history, so it is **not** out of sample.
- **Score.** `tools.walk_forward.composite`, the screener's formula: within-tier percentile over every tier member at the anchor, a negative weight inverts it, a missing factor counts as 0.5 (`config.MISSING_FACTOR_SCORE`).
- **Records.** Rank IC against `fwd_21/63/126/252` over stocks with that label (at least 20). The top tenth and top 15 are picked by score from all tier members, not knowing which will keep a price. Their mean label minus the tier mean among stocks with a label. t-stats are Newey-West with lag = horizon in months, as in step 1.
- **Check.** Re-computing the 126-session IC from the saved `oos_scores.parquet` and `labels.parquet` reproduces MID `slow_select` 0.0873 (t 5.68), SMALL `slow_icw` 0.1154 (t 3.63) and SMALL `slow_select` 0.0725 (t 3.29).

## Caveats
- **Short-history factors enter late.** `slow_select` lets in a factor once it has 12 matured 6-month labels (the floor `walk_forward` uses). By 2026 that admits factors whose history starts in 2024: at the last anchor SMALL's set includes `piotroski_f` and `quality_composite`, MID's includes `piotroski_f`, `earnings_surprise_std` and `pcr_volume`, LARGE's `promoter_qoq`. Twelve overlapping 6-month labels are about two independent observations. The 12-month floor is my choice, not the plan's. A rerun with 24 would be a fair robustness check.
- **Survivorship.** The fundamentals hold today's universe only. That biases toward weak-firm factors looking good (see MID above). It does not touch prices-only factors as much.
- **One window.** Out of sample covers 2022-06 → 2026-10 (4 years). The 2020 crash is in the training data only, never in a test month.
- **The H2 pass is two methods per tier.** Taking either `slow_select` or `slow_icw` slightly raises the chance of a lucky pass. Here both pass in MID and SMALL, so the verdict does not depend on that choice.
- **For H3.** `oos_scores.parquet` holds `sid, snapshot_date, cap_tier, method, score, pct_rank, oos` for all 53 anchors and all five methods (`oos = False` only for `live`). Higher is better. LARGE and MID `fast_select` have no rows in months where no factor cleared its bar.
