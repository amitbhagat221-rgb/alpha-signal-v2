# Quarterly growth on NSE filings, 2019-12 → 2026-10 (plan 0025 task 5.1)

Tool: `tools/lh_quarterly_nse.py` (pre-registered and committed in 5a92f57 before the run). Read-only. Outputs: `data/lh/v2/qnse_features.parquet`, `data/lh/v2/qnse_tests.csv`.

## Why
`tools/lh_growth.py` found one fundamental lead: MID quarterly margin expansion (`q_margin_chg`, 126 sessions, non-overlap t 2.71, top decile +12.9 %). But its quarters came from Tickertape, which starts in 2023, so the result rested on about three independent six-month windows in one regime. The NSE XBRL harvest (`quarterly_results_nse`, 2017-06 → 2024-12) now covers 89 % of the SMALL + MID stocks listed by 2021-01.

## What was tested
- The same six quarterly features as `lh_growth`, with the same formulas.
- NSE quarters are known at the original filing's timestamp; later restatements are ignored. Tickertape quarters are known at quarter end + 60 days.
- A year-on-year change is computed only inside one source and one basis.
- 2019–2024 anchors use NSE quarters (96–100 %); 2026 anchors use Tickertape.
- Bar: at least 24 anchors, non-overlap |t| ≥ 2.0, Newey-West |t| ≥ 2.5, and the same sign in 2020-22, 2023-24 and 2025-26. Bonferroni over the 54 tests is reported (|t| bar ≈ 3.49).

**Source check:** where both sources hold the same quarter (2023-24), revenue growth correlates 0.91 (2,151 quarters) and margin change 0.69 (2,149).

## Results (126 sessions unless stated)

| Feature | Tier | IC | NW t | Non-overlap t | Top-decile excess | 2020-22 / 2023-24 / 2025-26 | Bar |
|---|---|---|---|---|---|---|---|
| `q_ebitda_chg` (profit growth YoY, scaled by revenue) | SMALL | 0.064 | 6.12 | 3.85 | +11.8 % | 0.067 / 0.078 / 0.037 | pass + Bonferroni |
| `q_margin_chg` | SMALL | 0.058 | 5.20 | 3.54 | +10.3 % | 0.063 / 0.069 / 0.028 | pass + Bonferroni |
| `q_rev_yoy` | SMALL | 0.055 | 4.66 | 2.93 | +15.6 % | 0.058 / 0.070 / 0.024 | pass + Bonferroni |
| `q_rev_accel` | SMALL | 0.029 | 2.47 | 1.74 | +13.7 % | | fail |
| `q_profit_accel` | SMALL | 0.025 | 2.01 | 1.68 | +10.9 % | | fail |
| `q_margin_chg` | MID | −0.005 | −0.19 | −0.12 | +9.1 % | −0.030 / 0.008 / 0.034 | fail |
| every feature | LARGE | | \|t\| < 1 | | | | fail |

- At 63 sessions, SMALL `q_ebitda_chg`, `q_margin_chg`, `q_rev_yoy` and `q_margin_streak` pass; `q_rev_accel` passes the bar but not Bonferroni.
- At 252 sessions, SMALL `q_ebitda_chg` (non-overlap t 2.08) and `q_margin_chg` (2.17) pass.
- No MID or LARGE feature passes at any horizon.

## Verdict (pre-registered rule)
1. **The MID margin-expansion lead does not hold.** On 2020-26 anchors it is zero (non-overlap t −0.12); the 2025-26 reading was one regime. Drop it as a forward-test candidate.
2. **In SMALL, the level of quarterly growth works; acceleration does not.** Profit growth, margin change and revenue growth pass in every period, at every horizon tested, and survive Bonferroni. Acceleration (the change in growth) does not pass.
3. By the pre-registered rule these are **FACTOR_LIBRARY candidates for SMALL and go to a promotion review** (ADR 0043 haircut, `signal-weights.md`). This tool sets no weights.

## Exploratory, not pre-registered
SMALL, 126 sessions, each anchor's feature rank residualised on `announcement_car`, `residual_momentum_12_1` and `mom_6m`, all from the PIT panel:
- The features correlate with those live signals at 0.20–0.34.
- What remains still predicts returns: `q_ebitda_chg` non-overlap t 2.14, `q_margin_chg` 2.22, `q_rev_yoy` 1.84.

So most of the edge is new information, not the results-day reaction or momentum seen again. This supports the promotion review but does not replace it.

## Caveats
- The universe is today's listed names (survivorship), as in `lh_growth` and plan 0024.
- The NSE profit proxy is PBT before exceptionals + finance costs + depreciation − other income; Tickertape reports its own EBITDA. They are never mixed inside one YoY.
- 2026 anchors rely on Tickertape only.
- Coverage: features exist for 70–78 % of tier rows.

## Next (needs Amit; changes live picks, so it goes to a worktree)
Register `q_ebitda_chg` (and/or `q_margin_chg`) in `factors.FACTORS` with one compute function shared by live and PIT, then run the promotion review for SMALL.
- The NSE endpoint stops at Dec-2024 (`feeds.py` note, 2026-09-28), so live values would come from Tickertape `quarterly_income`. The 2026 anchors here already use Tickertape only, and the 2025-26 period IC stays positive (`q_ebitda_chg` 0.037).
- The history would come from NSE. Since the two profit definitions differ, the compute function must keep each YoY inside one source, as this tool does.
