# Missed winners 2019 → 2025 (2026-10-13)

Amit, after ATHERENERG: "give a list of all such stocks over the past number of years".

- Full list: [missed-winners-2019-2025.csv](missed-winners-2019-2025.csv), one row per stock, from [`tools/missed_winners.py`](../../tools/missed_winners.py) (read-only, definitions in its docstring).
- **Doubler** = a stock whose next-12-month return from a monthly anchor was ≥ +100 % (2019-12 → 2025-10 anchors; LARGE / MID / SMALL).
- **Rank** = the live model as configured until 2026-10-13 (today's weights + the forensic penalty, rebuilt on the PIT panel), percentile within tier at the first anchor of the stock's first run.

## Result
**1,056 stocks doubled at least once.** At the start of the run:

| verdict | stocks | by chance |
|---|---|---|
| CAUGHT (top tenth) | 100 (9.5 %) | 10 % |
| MIDDLE | 427 (40 %) | 40 % |
| MISSED (bottom half) | 529 (50 %) | 50 % |

The model sees doublers at about chance, which matches the winner-capture test in [slow-core-tactical-2026-10.md](slow-core-tactical-2026-10.md).

| | CAUGHT | MIDDLE | MISSED |
|---|---|---|---|
| LARGE | 3 | 22 | 26 |
| MID | 6 | 41 | 69 |
| SMALL | 91 | 364 | 434 |
| run started 2020 | 35 | 176 | 254 |

## Why the 529 were missed
| reason | share of the 529 |
|---|---|
| forensic penalty at the anchor (now off) | 9 % |
| listed < 12 months earlier | 13 % |
| no 12-month momentum data | 13 % |
| already in the top 30 % on 6-month momentum | **only 14 %** |

**Most doublers start from a flat or falling price.** They are turnarounds and rebounds (2020 alone: 465 run starts). No momentum, quality or value-plus-quality signal sees the start of such a run; momentum sees the second half (as with Ather from Aug 2026).

## Largest runs (best 12-month return)
- BCG ×39 (later a SEBI fraud case) — middle.
- TTML ×35 — missed, penalised.
- AURUM ×25 — missed.
- JAIBALAJI ×21 — missed, penalised; in the tactical paper book now.
- TANLA ×17 — middle.
- ATGL ×13 — middle.
- COOLCAPS ×12 — new listing.
- INTELLECT ×12 — missed.
- POONAWALLA ×11 — missed.
- ADANIENT ×10 — missed (slow_v2 97th percentile).
- TARIL, COCHINSHIP — middle. CUPID — caught. SKYGOLD — new listing. ADANIGREEN, SAREGAMA, TRIDENT — caught. CGPOWER, GPIL, IRFC — missed. MAZDOCK, KPIGREEN, PRINCEPIPE — new listings.

Several of the largest doublers later had governance trouble (BCG, parts of the 2020-22 Adani run). A doubling is not the same as a good holding.

## What it means
- **The model is a 20-name edge over the index, not a multibagger finder.** That holds for every score we have.
- **Two structural blind spots:** (1) new listings, the first 12 months (Ather, Mazagon Dock, Sky Gold); (2) turnarounds from depressed prices.
- **Tests for both are pre-registered:**
  - plan 0025 6.2 (new listings);
  - 6.1 (the winner hunter: momentum + acceleration, which sees run *continuations*, not starts).
- A turnaround detector has no test yet.
