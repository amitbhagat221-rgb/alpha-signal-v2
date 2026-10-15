# Promotion review: `q_ebitda_chg` in SMALL (2026-10-15)

Asked by Amit ("yes promote the strong candidate") after plan 0025 task 5.1 ([quarterly-nse-2026-10.md](quarterly-nse-2026-10.md)).
Tool: `tools/small_promote_q_ebitda.py`, pre-registered and committed (8c22ac2) before any result. Output: `data/lh/v2/small_promote_q_ebitda.json` and `_books.csv`.

## What was built
- **`signals/quarterly_growth.py`**: one compute function for live and PIT.
  - NSE XBRL quarters for 2017-24: the first filing only, known strictly after its filing date.
  - Tickertape quarters for 2025 onward and live, at quarter end + 60 days.
  - A year-on-year comparison never mixes the two sources.
  - The latest quarter must end within 270 days of the date; Financials get no value.
  - Live today: 1,975 stocks.
- **Registered in `factors.FACTORS`** as LIBRARY (no weight). The PIT column was backfilled on all 205 panel dates (501,840 rows). SMALL coverage per anchor: about 190 stocks in 2019-20, 550-590 in 2021-23, 960 in 2024, 1,200-1,380 in 2025-26.

## Result (SMALL keeps the strict bar; ADR 0074's grade B is MID-only)

**Factor gate: PASS**

| | value |
|---|---|
| SMALL IC on the live label (fwd_return_20d), 82 monthly anchors | 0.042, **t 4.44** |
| halves | 0.048 / 0.036 (same sign) |
| since 2024-09 | t 2.56 |
| highest correlation with a wired SMALL factor | 0.36 (residual momentum), 0.31 (announcement CAR) |
| IC net of all six wired SMALL factors | t 2.25 |
| MID / LARGE | t 1.66 / 0.40 (not wired outside SMALL) |

**Whole-score test: FAIL.** The grade-A weight is 0.143, with the other SMALL weights ×6/7.

| SMALL score | rank IC 21 (t) | top − bottom tenth (t) | top-20 book, 12 starts 2022-06 … 2023-05: median excess · starts beating |
|---|---|---|---|
| current | 0.0736 (8.64) | 2.84 % (7.21) | **+9.1 %/yr** · 12/12 |
| + `q_ebitda_chg` | 0.0759 (8.34) | 2.92 % (6.77) | **+7.9 %/yr** · 12/12 |

- The new book is lower in 10 of the 12 starts, equal in one and higher in one.
- Turnover is lower (7.3× vs 8.2× a year).
- The pre-registered accept rule needs median excess ≥ old, starts beating ≥ old **and** rank IC t not falling. Two of the three fail → **not wired**.

## Reading
- The factor is genuine. It passes the strict SMALL bar on the live label, and its IC survives the six wired factors.
- But the current SMALL score already captures most of what it adds at the top of the ranking: profit growth overlaps with the results reaction and momentum. At a full weight it dilutes stronger signals.
- Searching for a smaller weight that passes would be fitting to this same history. That was not done.

## Where it stays
- `q_ebitda_chg` stays a **LIBRARY** factor with full PIT history. This changes no live pick.
- The paper sleeve's walk-forward selection (`fast_select`) and future reviews can pick it up out of sample.
- Revisit if the SMALL score is reworked, e.g. under a slow / 126-session label, where the 5.1 evidence was strongest (t 3.85).
