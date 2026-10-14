# New listings (plan 0025 task 6.2) — 2026-10-14

**Question.** For its first 12 months, the live model scores a new listing's missing momentum as 0.5, so it barely sees stocks like ATHERENERG. Can a simple score rank stocks listed less than 12 months ago?

**Verdict (by the pre-registered rule): grade B → PROPOSE, not implemented.** The proposal: for stocks under 12 months old, the live model should stop scoring missing momentum as 0.5 and use this score instead. Amit decides. Nothing live has changed.

- Tool, with the pre-registration in its docstring: [`tools/new_listings.py`](../../tools/new_listings.py). It was written before any run, and the one pre-run change is logged there with its date.
- Outputs: `data/lh/v2/newlist_*`. The run log is `newlist_run.log`.

## What was tested
**The set.** At each monthly anchor (83 anchors, 2019-12 → 2026-10), a stock is in the set if all of these hold:
- it is less than 12 months past its first NSE close;
- its tier is SMALL or MID;
- its 20-session median traded value is at least ₹1 crore;
- it is not a trust or a Financial.

SMALL and MID form one set, because the set is too small to split by tier. The set holds 54.8 names on average (minimum 5 in 2020, maximum 114), and 508 different stocks pass through it. Twelve delisted listings from `stock_prices_unlisted` are included.

**The score.** An equal-weight average of the stock's percentile within the set on four inputs (a missing input counts as 0.5):
- return since the close on day 6 after listing, which skips the listing pop;
- price as a share of the high since listing;
- latest-quarter revenue growth, year on year;
- the sector's 6-month momentum.

## Results
**(a) Rank IC within the set** (informs only; t from non-overlapping subsamples):

| horizon | anchors | mean IC | t | share of anchors with IC > 0 |
|---|---|---|---|---|
| 63 sessions | 73 | 0.1231 | 3.09 | 75 % |
| 126 sessions | 70 | 0.1343 | 2.63 | 80 % |

Each input alone, at 126 sessions:

| input | mean IC | t |
|---|---|---|
| position vs the high since listing | 0.1555 | 3.34 |
| return since day 6 | 0.0653 | 1.43 |
| revenue growth (17 anchors only) | 0.1239 | 1.31 |
| sector momentum | 0.0405 | 0.81 |

Nearly all the signal comes from the position vs the high.

**(b) The book.** Top 10 by the score, monthly, each name held until its listing is 12 months old, then sold. It runs through `tools.lh_book`, with measured costs and Indian tax, against the NIFTY SMALLCAP 250. Results across 12 staggered starts (2019-12 … 2021-06):

| ADR 0073 test | value | B bar |
|---|---|---|
| median excess CAGR after costs and tax | **+20.3 %/yr** (lowest start +17.9 %) | — |
| median Newey-West t | 2.58 (1.83 after the 6-variant haircut, so not A) | ≥ 1.5 ✔ |
| starts beating the index | 12/12 | ≥ 10 ✔ |
| worst 12-month excess (worst start) | −12.1 % | ≥ −15 % ✔ |
| DSR / PBO (6-variant grid) | 0.986 / 0.686 | DSR ≥ 0.90 or PBO ≤ 0.30 ✔ |
| calendar years beating, 2021-25 | 4/5 (2023 −0.9 %) | ≥ 3 ✔ |

- Excess by calendar year, first start: 2020 +2.0 %, 2021 +11.6 %, 2022 +17.0 %, 2023 −0.9 %, 2024 +27.9 %, 2025 +14.2 %, 2026 so far +33.5 %.
- Against the NIFTY MIDCAP 150 (diagnostic): +19.1 %/yr, t 2.51.
- Turnover is 1.59×/yr, costs are 148 bps/yr, and the median hold is 8 months.
- **Grid, first start:** N 5 earns +22.7 % (hold to month 12) and +26.1 % (sell below rank 15). N 10 with sell-below-30 earns +13.6 %. **N 20 earns +7.9 % / +9.0 %, with t 1.09 / 1.20.** At ADR 0073's 20-name book shape, this rule would not grade B.

**Out of scope:** the hand-over to the normal tier rank after month 12. In the test, the position is simply sold.

## ATHERENERG (listed 2025-05-06): rank within the set
| | Jun 25 | Jul | Aug | Sep | Oct | Nov | Dec | Jan 26 | Feb | Mar | Apr | May |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rank | 19 | 32 | 26 | 9 | 2 | 1 | 3 | 1 | 1 | 1 | 13 | 17 |
| set size | 75 | 85 | 97 | 105 | 114 | 105 | 111 | 100 | 98 | 89 | 96 | 97 |

ATHERENERG enters the top 10 from September 2025.

## Caveats
- **Lottery-shaped.** Top-10 names beat the set median over 126 sessions by a median of only +4.7 % (mean +16.0 %, 55 % of cases positive).
  - Ten of the 225 names held (ORIA, HAPP, PRCE, KAYN, AFFL, …) supply 57 % of the summed excess.
  - Without the top 5 names, the mean is still +10.8 %.
- **High PBO, low N_eff.** The grade passes through DSR. PBO is 0.69 and N_eff is 2.04, so the in-sample best variant (N 5) does not hold its rank out of sample. The primary rule was fixed in advance, which limits the damage, but the edge shrinks fast as N grows.
- **One IPO cycle.** Everything falls in 2019-26, mostly the 2021 and 2023-24 IPO booms. The set was tiny in 2020 (9.4 names a month). With ADR 0073's halved planning return, plan for about +10 %/yr.
- **Listing date guards** were needed and are decided by data rules.
  - 327 BSE-only names were dropped, as was the 2026-04 bulk add.
  - 280 stocks whose BSE filings predate their first NSE close by more than 90 days were also dropped: BSE→NSE moves, BSE-SME migrants and renames.
  - NSE-Emerge SME debuts and demergers count as new listings.
  - The rules for delisted names rely on symbol patterns and a match on the bseindia URL slug. JUMPNET (from the 2019-08-19 batch of BSE companies moving to NSE) probably slipped through.
- **Revenue growth is close to empty before 2025.** Coverage is 0-2 % before 2025, then 49 % in 2025 and 89 % in 2026, because pre-listing quarters are not stored. In effect, the score before 2025 is three price inputs.
- **Survivorship.** Labels for universe stocks come from today's listed universe. Delisted names use the last traded close.
