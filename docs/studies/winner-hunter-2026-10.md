# Winner hunter, 2019-12 → 2026-10 (plan 0025 task 6.1)

Tool: `tools/winner_hunter.py` (pre-registered 2026-10-13; gate denominator amended 2026-10-14 before the first run, 5a92f57). Read-only. Outputs: `data/lh/v2/hunter_result.json`, `data/lh/v2/hunter_books.csv`, `data/lh/v2/hunter_scores.parquet`.

**Question:** can a score built for Netweb / SSWL-type runs catch big SMALL winners better than chance? It is the equal-weight percentiles of 6-month momentum, 52-week position, quarterly core-profit acceleration, revenue growth and margin change, gated on revenue growth > 0 and momentum > 0. And does its book earn after costs and tax?

**Data gate:** READY, 850 of 950 SMALL + MID non-Financial stocks listed by 2021-01 (89 %).

## Results
**T1, winner capture (the purpose): FAIL**
- 77 anchors.
- Top-20 hit rate 6.8 % (chance 5 %, bar 10 %); non-overlap t 0.90.
- Only 2.8 % of all top-5 % winners were in the top 20.

**T2, book (primary rule; 12 staggered starts 2019-12 → 2020-11): grade C**
- Median excess vs the Smallcap 250 after measured costs and tax: **+15.1 %/yr**, median t 2.03, **12 / 12 starts beating**.
- Grid of 8: DSR 0.985, but **PBO 0.66**. The best grid variant in-sample usually does not stay best.
- **Worst 12-month excess −21.1 %**, against the −15 % bar.
- Turnover about 2.3× per year.

**Cases (best rank reached; reported, not deciding)**
- NETWEB 55, SSWL 100, TIMETECHNO 72.
- ATHERENERG never passed the gate or the liquidity floor (listed 2025).

## Verdict (pre-registered rule)
T1 fails → **no hunter**; the verdict is recorded, with no sleeve and no watchlist.

## Reading
- The score does not find the big winners. They are too few and too idiosyncratic for a top 20 to catch at above chance.
- What the book earns comes from owning many good-not-spectacular growers with momentum. That is the same SMALL "quarterly growth level + momentum" edge that task 5.1 found ([quarterly-nse-2026-10.md](quarterly-nse-2026-10.md)).
- The −21 % worst year and the PBO of 0.66 say this book is not stable enough on its own. The edge is better used as a factor inside the existing SMALL score (5.1's promotion review) than as a separate sleeve.
- This reading is post-hoc and decides nothing.
