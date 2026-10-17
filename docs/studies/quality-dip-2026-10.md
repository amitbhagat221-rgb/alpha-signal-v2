# Quality dip: did the multibagger thesis miss good businesses that were beaten down? (2026-10-17)

**Verdict: FAIL, no "quality dip" lens.** The thesis is unchanged.
- Asked by Amit 2026-10-17 ("did we miss out on high quality beaten down stocks … agreed please run").
- Tool: `tools/mb_quality_dip.py`, read-only. The rules were fixed in its docstring before the run.
- Outputs: `data/lh/v2/mbqd_*`. Plan [0026](../plans/0026-multibagger-desk.md).

## The rule tested
The stock must be in the thesis pond (same safety gates, survivors) and meet all three tests:
- **quality:** 3-year average ROCE ≥ 15 %, debt/equity ≤ 0.5 and a profit in the latest year;
- **beaten down:** price at most 60 % of its 3-year high;
- **cheap:** P/B at or below its own 3-year median.

Qualifying names are ranked by ROCE, depth of the fall and book/price. Checked from Oct 2017 onwards, with labels to Oct 2026. The set ran to 1–36 names per October anchor.

## Results

| Test | Bar | Quality dip | Thesis top 30 (same anchors) |
|---|---|---|---|
| Odds of a 3x in 3 years vs the pond (5 Oct anchors with ≥ 10 names) | ≥ 1.3× | **1.00×** | 1.37× |
| Odds of halving in 3 years vs the pond | ≤ 1.0× | 0.44× (safe) | 0.13× |
| 30-name book vs the equal-weight pond, median of 12 starts, from 2018-10 | ≥ +3 pts/yr, t ≥ 1.5 | **−10.3 %/yr**, t −2.33, 0 of 12 starts | — |
| Same book vs NIFTY SMALLCAP 250 | — | 14.2 % a year, −4.4 %/yr, worst 12 months −45 % | — |

- **Survivorship check (passes).** For beaten-down stocks across the full market, including delisted ones, the halving lift is 1.76×; on survivors only it is 1.51×.
  - The rule for this check was that the full-market lift must not exceed 1.5× the survivors' lift; 1.76 is well under that.
  - Beaten-down names do disappear more often: 11.5 % stopped trading within 3 years, against 7.8 % for the pond.
- **By market regime (descriptive only).**
  - Anchors in a small-cap bear market: 3x lift 1.08×.
  - Other anchors: 0.78×.
  - The thesis top 30 beat it in both: 1.32× and 1.22×.

## What it means
- **Good businesses that are down a lot rarely blow up**, about half the pond's halving rate. But they also multibag no more often than an average pond stock.
- **As a book they lagged badly.** The worst year against the pond was −74 %, when junk-led rallies left them behind.
- **The thesis was not missing them.** On 2026-10-01, 59 names qualified, and 5 of them were already in the thesis top 100. The other 54 are in `data/lh/v2/mbqd_latest.csv`, for curiosity only, not as a list to act on.
- **This agrees with the earlier work:**
  - quality lowered the odds of a 10x in the 10-year study (ROCE ≥ 18 % gave 0.65×);
  - turnarounds failed (plan 0025 7.2);
  - dropping the thesis's price part nearly doubles the halving rate.

**Limits:**
- Fundamentals exist for survivors only, so the quality legs can't be run on delisted names; the beaten-down leg alone was checked across the full market.
- Only 5 October anchors had 10 or more names, so the 3x lift is noisy. The book result is not: it lost to the pond in every one of the 12 starts.
