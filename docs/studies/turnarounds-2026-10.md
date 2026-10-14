# Turnarounds (plan 0025 task 7.2) — 2026-10-14

**Verdict: no turnaround sleeve.** SMALL fails the asymmetry bar and the book is grade C. MID is also C.

- Tool: [`tools/turnarounds.py`](../../tools/turnarounds.py). It was pre-registered in its docstring before any run, and nothing in it changed after the first run.
- Outputs: `data/lh/v2/turnaround_*`.
- Sibling of 7.1 ([asymmetric-sleeves-2026-10.md](asymmetric-sleeves-2026-10.md)): same labels, book machinery, asymmetry measure and grading.

## The screen (primary rule)
A stock passes the gate when **all four** of these hold:

1. **Deleveraging:** debt / assets fell two years running, on Screener annual statements known at fiscal year end + 150 days. Debt / assets two years earlier had to be at least 0.10.
2. **Turn:** **either** the latest quarter's profit before tax (before exceptional items) is above zero after a loss quarter in the prior year, **or** interest coverage has crossed 1.5. Quarters come from NSE XBRL filings, known from the filing time, for 2017-04 to 2024-12. From 2025 they come from Screener, known at quarter end + 60 days.
3. **Price confirmation:** 3-month return above zero.
4. **Universe:** non-Financial, not a trust, and median traded value of at least ₹1 crore.

**Ranking.** Passers are ranked by the equal-weight mean of three within-tier percentiles, and the top 20 are kept:
- the size of the deleveraging;
- the 3-month return;
- an acquirer flag: any BSE "Open Offer" or "Acquisition" filing in the last 12 months.

**Exit.** A stock is sold at the next monthly review once it fails the gate (as in 7.1).

## Asymmetry bar (top 20 per anchor, 2019-12 … 2025-09)
| tier | P(double) | base | lift | P(halve) | base | median excess | mean excess | bar |
|---|---|---|---|---|---|---|---|---|
| **SMALL** | 17.3 % | 11.4 % | **1.52×** | 3.0 % | 2.5 % | +2.8 % | +24.9 % | **fails** (lift < 2×, halves more than base) |
| SMALL 2019-22 | 22.7 % | 15.6 % | 1.45× | 2.4 % | 1.7 % | +9.6 % | | fails |
| SMALL 2023-25 | 12.2 % | 8.9 % | 1.37× | 3.5 % | 2.9 % | −1.5 % | | fails |
| MID | 19.2 % | 7.9 % | 2.43× | 1.6 % | 1.0 % | +17.7 % | | fails (halves more often); about 3 names per anchor |

- SMALL is measured on 937 stock-anchor outcomes, an average of 14 names per anchor.
- The SMALL profile is the two-sided lottery 7.3 found: a higher mean, a near-zero median, and more halvings than the base.

## Book grade (ADR 0073), primary variant (top 20, sell below 40, monthly)
| | SMALL | MID |
|---|---|---|
| excess CAGR vs index, after costs and tax (first start, 2019-12) | **−4.4 %** | −15.0 % |
| t (Newey-West) | −0.85 | −2.64 |
| DSR / PBO | 0.21 / 0.31* | 0.02 / 1.0* |
| starts beating the index | **0/12** (median −4.7 %, worst −11.5 %) | 0/12 (median −16.5 %) |
| calendar years beating, 2021-25 | 2/5 (2020 −11.0 %, 2021 +3.2 %, 2022 +8.7 %, 2023 −2.1 %, 2024 −11.1 %, 2025 −5.7 %) | 0/5 |
| worst 12-month excess | −36.9 % | −40.8 % |
| average cash share | 32 % | 85 % |
| turnover / median hold | 286 %/yr / 2.1 months | 45 %/yr / 3.0 months |
| **grade** | **C** | **C** |

\* The 6-variant grid is degenerate: there are rarely more than 20 passers, so the sell band never binds and all six books are almost identical (N_eff 1.0). PBO and the haircut therefore carry no information here.

The book holds about a third cash because too few names pass. Cash drag explains part of the shortfall, but not all of it: the after-tax CAGR is 17.9 % against the index's 22.9 % (medians over the starts).

## Passers per anchor (gated SMALL names)
- Over 83 anchors, the median is **16** and the mean is 17.7 (range 0–46). Three anchors had none, all in the COVID months of 2020.
- MID has a median of 1 name.
- The pre-registered book-shape check (at least 20 names, ADR 0073) also fails for SMALL.

## Diagnostics (decide nothing)
SMALL asymmetry, full span:

| gate variant | lift | P(halve) vs base 2.5 % | median excess |
|---|---|---|---|
| acquirer as an OR-leg | 1.26× | 2.9 % | −1.7 % |
| acquirer required (4 names per anchor) | 0.85× | 2.1 % | −5.7 % |
| no price confirmation | 1.51× | 2.8 % | +2.7 % |
| deleveraging alone (+ momentum) | 1.44× | 2.1 % | +3.6 % |
| turn alone (+ momentum) | 1.49× | 2.7 % | +1.0 % |

- The acquirer filing does not help in SMALL. It hurts when it is required.
- In MID, the gate with the acquirer as an OR-leg and the turn leg alone pass the bar on 6–9 names per anchor. This is a small-sample, post-hoc observation, not a finding.
- Today's gated top 20 is in `turnaround_latest.csv`.

## Caveats
- **Data window.** The test runs from 2019-12 to 2026-10, because the anchors in `labels.parquet` start there. Inputs exist from 2018: NSE quarterlies from 2017-04, BSE filings from 2018. Asymmetry outcomes run to 2025-09. That is one cycle, and the 2020 COVID crash sits at the very start.
- **Source change.** Quarterly sources switch from NSE to Screener at 2025-01, and the prior quarters of a 2025 quarter may be NSE quarters. Screener's PBT may include exceptional items.
- **Acquirer filings.** "Acquisition" filings are mostly the company buying something, not being bought. Flagged before the run.
- **Sector labels.** A vendor sector label let one lender, HUDCO (labelled Real Estate), into the universe.
- **Survivorship.** Labels cover today's listed universe only, which flatters SMALL by about 2.8 %/yr. Turnarounds that failed and delisted are missing, so the true result is likely worse.
