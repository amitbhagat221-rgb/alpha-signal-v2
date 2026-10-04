# Factor audit — October 2026 (plan 0020)

Audit of all 105 factors, the backtest engine, cadence and the factor code, run 2026-10-03.
Four read-only auditors (fundamentals calcs, price/event calcs, backtest + cadence, code structure) plus the audit sheet `python -m tools.factor_audit`. Every finding below was reproduced with data unless marked *suspected*.

**In one paragraph.** The code computes what it says: 90 of 90 hand recomputes of the wired fundamentals factors match, the stored evidence reproduces exactly, and per-factor contributions add up to `final_score` for every pick. The problems are in what the code is fed and what the evidence was measured on: two Tickertape columns are mis-mapped, price and share count sit on different bases around splits, the "consensus" factor is realised EPS growth with look-ahead, the accruals weight is backed by evidence on a different column, the return label ignored splits, and the panel uses today's tiers and universe at every past date. After correcting for these, the honest evidence under the LARGE tier is thinner than recorded.

## 1. Fixed on 2026-10-03

None of these changes today's ranking. Tests: `tests/test_backtest_engine.py`; full suite green.

| # | What was wrong | Fix |
|---|---|---|
| F1 | `fwd_return_20d` used raw closes. A 5:1 split inside the window read as −80%; 54% of all labels below −40% (966 of 1,780) were corporate actions. | Label on fully adjusted closes, total return (`pit.pit_fwd_return_20d`); same in `tools/ic_decay.py`. |
| F2 | A bonus issue of preference shares or debentures was parsed as an equity bonus. TVSM's whole price history was cut to a fifth; SUND, SIYR, MUSI also. | `parse_bonus_factor` returns nothing for NCRPS / preference / debenture; `corporate_adjustments` recomputed (9,388 → 9,383 rows). |
| F3 | The `consensus` input (`forecast_history` EPS, dated at fiscal year-end, holding the reported figure) was treated as known on the year-end date. | 75-day annual filing lag in `pit._pit_input`. No value changes today (FY26 has long been filed); it changes April–June dates. |
| F4 | A verdict and a confidence interval were written for any sample size: t = 19.42 on 2 anchors labelled KEEP; intervals of −93 and 310 on 4 anchors. | No verdict and no interval below 12 anchors (`IC_MIN_PERIODS`, one constant). |
| F5 | The interval resampled anchors independently, then applied Newey-West: for weekly factors it was centred on the wrong t (t = 5.84 with interval 6.75–13.04). | Moving-block bootstrap of the mean IC, scaled by the series' own standard error. |
| F6 | `computed_at` kept the first insert date forever (rows rewritten on 10-02 showed May); 25 orphan rows no run overwrites. | `computed_at` written explicitly; rows a run no longer produces are deleted. |
| F7 | Four readers of the evidence table each picked "the" row differently and disagreed on 4 pairs. | One function, `tools.backtest_pit.evidence()`, used by the cockpit, MCP, `multiple_testing`, `optimize_weights`, `expected_return`, `factor_audit`. |
| F8 | The decay monitor took every anchor with a value, mixing weekly and monthly grids: "last 12 anchors" was the same nine weeks for every factor, and it judged accruals on the wrong column. Its three DECAYED flags were noise. | It now uses the backtest's anchors, one year of the factor's own cadence, and the column the screener ranks. Result: 0 of 16 decayed. |
| F9 | `promotion_gate` net t dropped the overlap correction and came out above gross (book-to-price SMALL 252d: gross 6.72, "net" 13.58; 23 of 37 PROMOTE verdicts affected). | Net t = gross t × share of IC left after cost. The gate table still needs a rerun. |

## 2. Confirmed, not yet fixed: these change the ranking

Each needs the panel rebuilt and the evidence re-run before and after. They go live together as one measured model change.

| # | Finding | Wired exposure | Evidence | Proposed fix |
|---|---|---|---|---|
| R1 | `quarterly_income.interest` is **operating expenses** (`sources/tickertape.py:105`, `qIncOpe`). | Piotroski F8 (MID 0.18, SMALL 0.06); Altman Z in the forensic penalty on every score | Median interest ÷ revenue is 0.61–0.86 in every sector; RELI Jun-26 revenue 316,018, "interest" 261,951. The F8 bit disagrees with a true margin change for 45% of names. Altman: 35% of names clipped at the cap; about 46 names escape a penalty. | Rename the column; F8 on (revenue − opex) ÷ revenue; Altman EBIT from proper items. |
| R2 | `annual_cash_flow.depreciation` is **dividends paid** (`tickertape.py:224`, `cafTcdp`). | 35% of the MID accruals composite; Beneish DEPI | 3% of names agree with Screener depreciation; median ratio to Screener dividends 0.994. RELI 7,879 against 57,688. | Depreciation from `fundamentals_screener`. |
| R3 | Book-to-price and earnings yield divide restated shares / EPS by an unadjusted close. | Book-to-price in all three tiers | History: 5.6% of panel rows understated by the split factor (15–17% of 2022–23). Live: wrong in the other direction from ex-date to the next monthly refetch (TAA 0.72 stored, 0.14 true). | One share basis for price and shares (split and bonus factors only). |
| R4 | `consensus` is realised fiscal-year EPS growth, not analyst revisions. Wrong sign when the prior year is negative (57 of 92 kept cases); the range discards 11.9% of values, including the profit-to-loss names. | LARGE 0.28, SMALL 0.16 | With the filing lag (F3): LARGE t 1.74 → **1.05**, MID 0.40 → −0.04, SMALL 4.15 → **2.98**. Rank correlation with `eps_growth_yoy` 0.75. | Rename for what it is; (latest − prior) ÷ \|prior\|; winsorize instead of discard. LARGE weight to the promotion review: it no longer clears 1.5. |
| R5 | The MID accruals weight (+0.22) is justified on `cf_accruals` (t = −2.90) but the screener ranks `accruals_signal`, a four-part blend. The sign is right; the evidence is not for what is ranked. | MID 0.22 | `accruals_signal` MID: 8 monthly anchors, t = 0.59. Two of the four parts point the wrong way in MID; one is built on R2. | Rank −`cf_accruals` directly, or register and test the blend. Decision for Amit. |
| R6 | `total_equity` includes minority interest. | Book-to-price | Differs from Screener capital + reserves by more than 5% for 23.5% of LARGE (BJFS 1.81×, GRAS 1.64×). | Subtract non-controlling interest. |
| R7 | Bad `shares_outstanding` rows: 36 stocks jump more than 5× year on year (KDDL 1,744 Cr shares against 1.25 Cr). | Book-to-price; possibly tiering | KDDL book-to-price 0.00027 and sitting in LARGE. | Write contract on year-on-year share change; cross-check with Screener. |
| R8 | Five wired factors have no eligibility rule (`iv_skew_25d`, `delivery_anomaly_z`, `sector_tilt`, `governance_resignation`, `pledge_quality`), so every stock counts as eligible. | MID gate | 56 MID stocks without listed options count as "missing"; 10 of 31 MID Financials are gated out, three of them ranked 2, 3 and 5 before the gate. | Eligibility for every wired factor, enforced by a test; clip coverage at 1. |
| R9 | A missing factor's weight is spread over the present ones, so MID Financials are scored on three factors with book-to-price at an effective 33%, ranked against non-financials. | MID picks | Financials are 14% of MID but 31% of the MID top 20 over the last 50 days. | Design decision: rank book-to-price within Financials, or shrink a missing factor to 0.5. |
| R10 | Piotroski sums whatever components exist. | MID 0.18, SMALL 0.06 | 106 scored names have fewer than 9 components (mean score 3.6 against 5.6). | Require 8, or scale by 9 ÷ n. |
| R11 | Annual statements reach the DB 1–4 months after the modelled 75-day lag; the backtest sees them earlier than live did. | All fundamentals factors | FY26 balance sheets arrived 07-01 to 10-01; recomputing 2026-09-25 today changes 869 book-to-price values. | Gate on first-seen date as well; harvest annuals weekly June–September. |

Library and proposed factors with definition faults: `roic` drops loss-makers; `value_composite` rewards a high 52-week position; `ccc` ≡ 365 × `wc_intensity`; `earnings_beat_rate` is not a beat rate; promoter trends look back by row count over month-end rows; three Screener factors switched to half-year rows from 2025-12 to 2026-06; negative book equity ranks as most expensive.

## 3. Backtest and cadence

**What is correct:** Spearman IC, the 20-stock minimum, the t-stat and the Newey-West formula. All 16 wired pairs reproduce exactly with independent code.

**What is biased:**
- **Today's tier and sector at every past date.** 2,369 of 2,448 stocks carry one tier across all 202 anchors. A rough reconstruction puts 17–23 of today's LARGE outside the top 100 at past anchors. "LARGE in 2021" is conditioned on having grown into LARGE. No historical tier table exists.
- **Today's universe at every past date.** Label coverage in SMALL rises from 50% (2020) to 95% (2026). An estimated 5–10 points of each past cross-section are dead names.
- **The stored panel is a mix of vintages and does not reproduce.** Re-running 2026-09-25 eight days later reproduced 19 of 104 columns: adjustments are rewritten daily, statements are upserted with no vintage, tiers move.
- **Factors are judged on different windows.** `announcement_car` from 2020 (80 anchors); piotroski, accruals and pledge from late 2024 (21–23 anchors, one regime). t-stats are not comparable across factors, and five of the 16 wired pairs rest on under two years.
- **Anchor grid:** one off-grid anchor (2025-12-15), one with no prices (2019-12-02), and anchors with partial labels that the refresh never refills.

**Wired weights against the bar** (before R1–R7 are corrected):

| Tier | Factor | Weight | t stored | t, adjusted label | Note |
|---|---|---|---|---|---|
| LARGE | announcement_car | 0.35 | 2.16 | 2.03 | |
| LARGE | consensus | 0.28 | 1.74 | 1.31 | 1.05 with the filing lag |
| LARGE | sector_tilt | 0.22 | 1.53 | 1.41 | one value per sector |
| LARGE | book_to_price | 0.15 | 0.82 | 0.92 | below the 1.5 floor |
| MID | iv_skew_25d | 0.26 | 2.82 | — | 2.49 at a longer lag; 15 months of history |
| MID | accruals | 0.22 | 0.59 on the ranked column | — | R5 |
| MID | book_to_price | 0.20 | 2.33 | 2.48 | |
| MID | piotroski | 0.18 | 2.85 | 2.96 | 23 anchors; R1, R10 |
| MID | governance_resignation | −0.14 | −1.71 | −1.74 | |
| SMALL | delivery_anomaly_z | 0.26 | 7.14 | — | the one factor that survives multiple testing |
| SMALL | consensus | 0.16 | 4.15 | 4.28 | 2.98 with the filing lag |
| SMALL | sector_tilt | 0.16 | 3.38 | 3.38 | |
| SMALL | announcement_car | 0.14 | 3.75 | 3.91 | |
| SMALL | book_to_price | 0.12 | 1.84 | 1.22 | 0.93 on liquid names |
| SMALL | pledge_quality | 0.10 | 2.28 | 2.16 | 83% of names share one value |
| SMALL | piotroski | 0.06 | 2.00 | 2.26 | |

Illiquidity does not drive the SMALL results, except book-to-price.

**Cadence.** Every factor is judged on a 20-day return and re-ranked daily, whatever its rhythm. The `cadence` field mixes three things: anchor spacing, test type and (implicitly) horizon.

| Factor | Information arrives | Tested at | Mismatch |
|---|---|---|---|
| book_to_price | annual statement + daily price | monthly, 20d | Rank autocorrelation 0.99; IC peaks at 60d+. Daily re-rank adds price noise only. |
| piotroski, accruals, pledge | 4 times a year | monthly, 20d | 23 monthly observations are about 8 independent states. |
| consensus | once a year (as built) | monthly, 20d | Not an analyst factor. |
| announcement_car | quarterly print, held 90 days | monthly, 20d | Signal age mixed 1–90 days; belongs in event time. |
| governance_resignation | event stream | monthly, 20d | Same. |
| sector_tilt | one value per sector | stock-level IC | A sector test, scored as a stock test. |
| delivery_anomaly_z | daily | weekly, 20d | IC is highest at 5 days (0.037 against 0.028). |
| iv_skew_25d | daily | weekly, 20d | Verdict depends on the overlap lag. |

## 4. Code: redundancy and dead weight

- **Six TTM implementations**, seven copies of the consolidated-preference filter (two producers omit it), five within-tier composites, four abnormal-return routines, three market caps from two share sources, three labels. Several copies can disagree numerically.
- **24 one-file-per-factor fundamentals modules:** 2,227 lines, about 560 of them maths.
- **A second, unlagged compute path:** about 30 pipeline steps write `*_scores` tables with no filing lag. 17 of those tables have no reader. The stock page shows these values, not the ones that were ranked (piotroski differs for 349 of 1,602 stocks).
- **Up to five names per factor** (id, weight key, screener column, PIT column, replay column). Every place the names diverge is cosmetic or one of the bugs above (R4, R5).
- **Dead:** three signal modules nothing imports (807 lines), six functions with no caller, the v1 panel machinery, the two print-only weight schemes that force eight unwired columns to be computed daily, registry fields no code reads.
- **A wired factor can vanish silently:** optional inputs swallow read errors and the screener skips an absent column; only the health check notices afterwards.

## 5. Proposed design (for Amit)

**Feature layer.** One name per factor. `features/primitives.py` (ttm, latest knowable, per share, rank composite, abnormal return, event window) → pure functions grouped by family → one registry entry `{fn, inputs, range, cadence, eligibility, weights | bench}`. One `INPUTS` table owns every lag. One step writes `features_at(today)` for display, so the stock page shows what was ranked. Estimate: 3,500–4,000 of 14,500 lines removed, about 30 pipeline steps become one. Every refactor step is gated on "old code and new code give identical values on the same frozen inputs" (not on the stored panel, which does not reproduce).

**Backtest.** In order of value:
1. Historical tiers and a liquidity flag stored per anchor (PIT market cap with the `segment.py` rule). Removes the largest remaining look-ahead.
2. One label table (stock, anchor, horizon) at 5 / 20 / 60 / 120 days, adjusted, entry the day after the signal.
3. One evidence function: IC, overlap-corrected t with the lag derived from horizon ÷ spacing, rank autocorrelation, turnover, top-minus-bottom spread.
4. Cadence split into `update_freq`, `eval_horizon`, `level` (stock / sector), `test` (IC / event / sector). Sector factors tested on sector returns; event factors in event time (`tools/event_study.py` exists).
5. Every factor's t on the common window beside its full-history t.
6. Immutable panel: a run id per anchor, statements and adjustments versioned by fetch date, three golden anchors for drift tests.
7. Walk-forward on the v2 panel with an embargo equal to the horizon.
8. Dead names from bhavcopy for the price-only factors.

**Factor set.** Collapse duplicates (`consensus_signal_combined` ≡ `eps_revision_yoy` ≈ `eps_growth_yoy`; `ccc` ≡ `wc_intensity` ≈ `nwc_to_revenue`; `financial_signal` ≡ `financial_quality`; two beat rates; two balance-sheet accruals). Fix definitions before judging (R1–R7, `roic`, `value_composite`). Then re-test everything on the corrected panel.

## 6. Price, event and market factors

The five wired factors here (`announcement_car`, `sector_tilt`, `iv_skew_25d`, `governance_resignation`, `delivery_anomaly_z`) match a hand recompute on every stock tested, including an independent Black-76 inversion for the skew. The problems are again in the inputs and the panel.

| # | Finding | Exposure | Evidence | Proposed fix | State |
|---|---|---|---|---|---|
| P1 | `sector_tilt` in the panel uses a months-stale macro leg: the rebuild loads the macro table once, before the rows for the dates it is rebuilding exist. | LARGE 0.22, SMALL 0.16 (evidence); live reads a snapshot up to a refresh old | Anchors 06-05 to 09-25 all carry the 2026-05-01 macro snapshot exactly. Sector rank correlation with the correct value: 0.07 at 07-03. | Compute the macro score inside the producer from macro history up to the date. Rebuild, re-test. | staged (changes ranks) |
| P2 | 44 phantom trading days in `stock_prices`: on market holidays the harvester stored a copy of the previous day (2026-10-02, 01-26, 12-25 …; 15 since 2025-10). | Every price factor; the 2026-10-03 picks used the copied 10-02 row as "today" | 100% of 2,139 rows on 2026-10-02 equal 10-01 in close and volume. 3.8% of earnings windows touch a phantom day. Five panel anchors are phantom days. | Delete those dates, refuse such a file in the harvester, add a health check. | staged (deletes raw rows) |
| P3 | Missing adjustments: demergers are not handled (Vedanta 2026-04-30 −65%, Siemens 2025-04-07 −43%); 48 unexplained one-day moves beyond −40% / +67%. | Momentum-type factors, the label | 21 stocks have such a jump inside their trailing year. | Demerger handling or an override list; a check for an adjusted one-day move beyond 40% with no event. | open |
| P4 | Panel anchors 2026-05-29 → 09-25 were written while the adjustments table was frozen. | Evidence for every price factor | `mom_6m` differs on 753 stocks at 09-25; `announcement_car` on 25. | One explicit rebuild of every anchor since 2026-04-30, after P1–P3. | needs the panel rebuild |
| P5 | `bulk_deal_signal` signed every deal as a sale (compared with "B"; the table holds BUY / SELL). | Proposed factor, not wired | All 267 values negative at 09-25. | `startswith("B")`. | **fixed** (panel column needs the rebuild) |
| P6 | The label enters at the same close the factors read. Delivery data and 69% of resignation filings arrive after that close. | Evidence | Entry a day later: `delivery_anomaly_z` SMALL t 9.42 → 8.19 (about 12% of its IC is not tradeable); LARGE consensus 1.74 → 1.14. | Label from the next day's close (backtest redesign item 2). | open |
| P7 | Raw close passed where adjusted is meant, at five call sites (`sector_tilt`, `sector_momentum`, `iv_realised_spread`, macro betas, `pead_drift_60d`). | `sector_tilt` (small: two adjacent sector swaps) | Max 0.08 z difference. | Pass `adj_close`. | staged |
| P8 | Stale derivative rows are scored: IV allows 45 days, OI has no limit. | `iv_skew_25d` MID 0.26 | SAIL ranked on 10-03 with a skew from 09-11 on an expired contract; 60 of 270 OI values older than a week. | Require a row within 5 trading days. | staged |
| P9 | `announcement_car` takes the latest "Result" filing in the window, which can be a corrigendum; no guard on the span of the three-day window. | LARGE 0.35, SMALL 0.14 | 16 of 1,919 stocks at 09-25. | First filing of a cluster; span ≤ 7 calendar days. | staged |
| P10 | `governance_resignation` double-counts 39 duplicate filings; "Cessation" (26% of events) includes routine end of tenure. | MID −0.14 | — | Dedupe; review the subcategory weights. | staged |

Library items: `short_selling_signal` is not a short-interest ratio; `smart_money_score` min-max scaling lets one deal rescale a tier; `mom_6m` spans 8.4 months; `buyback_announcement_30d` is keyed on ex-date; `macro_score` is half sector momentum again (three overlapping sector-momentum computations exist).

## 7. Fixed on 2026-10-03, second pass (ADR 0062)

After Amit's go-ahead ("fix all and institute the new checks"), as one model change:

| Finding | What changed |
|---|---|
| R1, R2 | Columns renamed to what they hold (`operating_expenses`, `dividends_paid`); stored EBITDA corrected; Piotroski margin test, Altman EBIT, Beneish DEPI and balance-sheet accruals read real figures (Screener). Distress / grey flags 31 / 11 → 54 / 29. |
| R3, R6, R7 | Book-to-price on one share basis with owners' equity (`shares_and_book`). RELI across its 2024 bonus: 0.23 → 0.51 before, 0.40 → 0.44 now. KDDL 0.0003 → 0.22. |
| R4 | Filing lag, change over \|base\|, winsorised. Description says what it is. LARGE weight left for the promotion review. |
| R5 | MID accruals: −0.22 on `cf_accruals`, the column with the evidence. |
| R8 | Eligibility for all wired factors, enforced by a test; coverage clipped at 1. |
| R10 | Piotroski scaled to 9 points, at least 6 components. |
| P1, P7 | Sector tilt: macro leg as of the date, adjusted prices. |
| P2 | Harvester refuses a file dated another day; 44 copied days deleted (saved in `output/`). |
| P8, P9, P10 | Options older than 7 days unused; first filing of a result, real 3-day window; duplicate filings counted once. |
| Guards | Reconcile compares every statement column factors read (`FUND_FIELDS`); checks `PRICE_DAY_COPIED`, `PRICE_JUMP_UNEXPLAINED` with drills. |

**Effect on the ranking** (2026-10-03 inputs, code before vs after): score rank correlation LARGE 0.94 / MID 0.93 / SMALL 0.92; top-10 kept 7 / 7 / 3; top-30 kept 25 / 24 / 15. The largest mover is sector tilt (its macro leg was 8 days stale), then Piotroski and book-to-price.

**Still open:** R9 (Financials in MID), R11 (late-arriving statements), P3 (demergers), P6 (label entry a day later), the backtest redesign and the code refactor in §5, and the corrected evidence table (the rebuild of all 202 anchors was started 2026-10-03 11:55 UTC; log `output/factor_audit_rebuild.log`).

## 8. Corrected evidence (2026-10-03, after the rebuild)

All 202 anchors rebuilt with the fixes of §1, §7 and three more changes to how factors are judged:
- **Tier as of each date** (`pit.tiers_at`): market cap of that day with the `segment.py` rank rule, MICRO carved on that day's liquidity. Of the true top 100 in June 2021, 39 are not LARGE today.
- **Entry the session after the signal**: the label starts at the next session's close.
- **Renamed stocks have their earlier prices** (`sources.nse.link_renames`): 127 stocks, 92k rows.

Wired weights on the corrected panel (20-day rank IC; `python -m tools.factor_audit --wired`):

| Tier | Factor | Weight | t before the audit | t corrected | Anchors | Reading |
|---|---|---|---|---|---|---|
| LARGE | announcement_car | 0.35 | 2.16 | **2.31** | 81 | holds |
| LARGE | consensus | 0.28 | 1.74 | **0.11** | 40 | gone |
| LARGE | sector_tilt | 0.22 | 1.53 | **0.44** | 75 | gone |
| LARGE | book_to_price | 0.15 | 0.82 | 1.33 | 82 | below the 1.5 bar |
| MID | iv_skew_25d | 0.26 | 2.82 | **4.06** | 111 | stronger |
| MID | accruals (cf) | −0.22 | −2.90 | −1.92 | 26 | weaker, right sign |
| MID | book_to_price | 0.20 | 2.33 | **1.22** | 82 | below the bar |
| MID | piotroski | 0.18 | 2.85 | **3.63** | 26 | stronger (short history) |
| MID | governance_resignation | −0.14 | −1.71 | **−0.30** | 82 | gone |
| SMALL | delivery_anomaly_z | 0.26 | 7.14 | **6.07** | 126 | holds |
| SMALL | consensus | 0.16 | 4.15 | **1.39** | 40 | below the bar |
| SMALL | sector_tilt | 0.16 | 3.38 | **3.98** | 75 | holds |
| SMALL | announcement_car | 0.14 | 3.75 | **4.84** | 81 | stronger |
| SMALL | book_to_price | 0.12 | 1.84 | **0.67** | 82 | gone |
| SMALL | pledge_quality | 0.10 | 2.28 | **0.56** | 29 | gone |
| SMALL | piotroski | 0.06 | 2.00 | **4.26** | 26 | stronger (short history) |

**After the final pass** (price factors recomputed with the renamed stocks' earlier prices, 18:30 UTC) the readings are the same; the values that moved: `announcement_car` LARGE 2.65 and SMALL 5.51, `delivery_anomaly_z` SMALL 5.52, `sector_tilt` LARGE 0.54 and SMALL 3.59, `book_to_price` 1.26 / 1.18 / 0.71. Unwired: `mom_12m_adj` MID 4.00 and SMALL 4.03, `residual_momentum_12_1` SMALL 3.98. The live table is `python -m tools.factor_audit --wired`.

Eight of the sixteen weights are now below the 1.5 wiring bar. By weight: LARGE 0.65 of 1.00 rests on factors with no evidence, MID 0.34, SMALL 0.38. The decay monitor flags none: the factors did not decay, their original evidence was inflated by today's tiers, the unadjusted label and (consensus) the look-ahead.

Unwired factors that clear |t| ≥ 2.5 with 20+ anchors on the corrected panel:
- **MID:** `mom_12m_adj` 3.92, `residual_momentum_12_1` 3.39, `momentum_composite` 3.39, `pcr_volume` 3.11, `pcr_oi` 3.06.
- **SMALL:** `smart_money_score` 3.92, `avg_delivery_pct_30d` 3.83, `max_lottery_21d` −3.43, `residual_momentum_12_1` 3.41, `earnings_persistence` −3.37, `momentum_composite` 3.34, `mom_12m_adj` 3.25, `closing_strength_1m` 3.07, `low_vol_252d` −3.01.
- **LARGE:** none. The strongest are `asset_growth_yoy` −2.37, `gross_profitability` −2.36, `announcement_car` 2.31, `forward_looking_intensity` 2.18.

After the multiple-testing haircut, `delivery_anomaly_z` SMALL and `announcement_car` SMALL are the clear survivors; `sector_tilt` SMALL, `iv_skew_25d` MID and `piotroski` SMALL sit just outside (p ≈ 0.055).

**Final pass (2026-10-03 18:30 UTC, price factors re-run after 127 renamed stocks got their earlier prices).** No reading changed; the same eight weights are below the bar. Moves: `announcement_car` LARGE 2.31 → 2.65 and SMALL 4.84 → 5.51; `delivery_anomaly_z` SMALL 6.07 → 5.52; `sector_tilt` SMALL 3.98 → 3.59 and LARGE 0.44 → 0.54; `book_to_price` 1.26 / 1.18 / 0.71. The current table is always `python -m tools.factor_audit --wired`.

## 9. Survivorship: price history for every symbol that traded

- `stock_prices_unlisted`: the rows of each daily NSE file for symbols not in `stocks`, 2020-01 → today (1.32 M rows, 2,212 symbols: 538 delisted or merged, about 1,400 listed outside the universe). Kept daily from now on. One source day is unreadable (2022-08-08).
- `symbol_changes`: NSE's rename list; earlier-name rows are copied to the stock's sid daily.
- Study [survivorship-price-factors-2026-10.md](survivorship-price-factors-2026-10.md) (`tools/survivorship_study.py`, 76 monthly anchors, five price factors, liquid names): adding the missing names leaves `delivery_anomaly_z` unchanged (t 6.47 → 6.59) and strengthens momentum (2.58 → 2.98), low volatility (−2.19 → −3.00) and the lottery factor (−2.58 → −3.34). The missing names crash more often (1.3% of 20-day returns below −30% against 0.4%) but do not change which factors work.
- Not done: dead names in the panel itself. They have no market cap before NSE's daily MCAP file starts (present in 2026, absent in 2020 and 2022) and no sid; the panel's key references `stocks`. A proposal is owed, tied to the data-model redesign's `entities`.

## 10. The weekly audit (so this does not take another six months to find)

`tools/dq_probes.py` runs the audit's five methods every week and `dq-auditor` (a desk seat, Sunday) judges the findings; see [org.md](../reference/org.md). First run of the probes, 2026-10-03: one new mislabelled column (`quarterly_income.total_other_income` holds the same values as Screener 'Tax' for 76% of stocks; no factor reads it), 4 unexplained price jumps in 60 days, the 8 weights below the bar. The drill caught 7 of 7 planted faults (its first run caught 4 of 5 and exposed a gap: a column that stops matching the item its name promises was not reported; fixed).

## 11. Close-out, 2026-10-04

First run on the new weights and what it showed: [ADR 0064](../decisions/0064-missing-factor-is-neutral.md). Closed: R9 (a missing factor is neutral), P3 (demergers), the third mislabelled column, the two unrecorded splits, the thin-tier check. Open: R11, dead names in the panel ([plan 0020 §7](../plans/0020-factor-audit.md)), the code refactor and the remaining backtest redesign (§5), LARGE (unproven).
