# How many names per tier — 2026-10-10

Pre-registered (checklist, same day) and read-only. Tool: `python -m tools.names_per_tier --md PATH`.

## Verdict
- **LARGE: hold the index.** On out-of-sample scores, no number of names earns anything (net t between −0.5 and +0.3 over the full history; −0.8 to −2.7 since 2024-09). The live weights look good over the full history, but they were chosen on it, and since 2024-09 they are flat as well.
- **MID: more than 5 names.** On the live weights, the book's own holding rule gives top 10–30 net t 2.8–3.0 against 1.6 for the top 5, with lower turnover. Out-of-sample selection earns nothing, so most of that evidence was chosen with hindsight.
- **SMALL: costs decide, not the number of names.** Gross excess is the largest of any tier (1.2–1.9 %/month), but monthly turnover of 70–90% at the assumed 150 bps one-way turns every variant negative. Break-even cost is about 95–150 bps one-way. Below that, top 10–20 is net positive.

## Method
Walk-forward protocol of `tools/walk_forward.py`: monthly anchors from 2020-06, expanding training window, 1-anchor embargo. Scores:
- `oos`: factors with training |t| ≥ 2.5, sign-weighted, at most 6.
- `live`: today's `factors.SIGNAL_WEIGHTS`, including the MID change made the same day.

Holding: equal-weight top N for 20 sessions. Rules:
- `monthly`: rebuy the top N each month.
- `banded`: keep a name until it ranks below 1.6 × N, the book's 5 → 8 band.

Excess is over the tier's equal-weight average. Cost = 2 × turnover × `config.TIERS` one-way `cost_bps` (30 / 50 / 150). Break-even = gross / (2 × turnover).

## Caveats
- The benchmark is the tier's equal-weight average, not the cap-weighted index.
- Fundamentals history holds only today's universe.
- The real book trades daily with a 3-day debounce, not monthly.
- `oos` tests a mechanical selection rule, not the curated live set.
- The 150 bps SMALL cost is the ADR 0038 placeholder, not a measured cost. Zerodha delivery is about 11–12 bps a side in fees (STT, stamp duty, exchange charges), plus the spread. **Measuring real costs from the Kite fills is the next step.**

## Full history

| tier | scores | rule | holding | months | gross_%/mo | turnover_% | net_%/mo | net_%/yr | breakeven_bps | t_net | months_up_% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| LARGE | live | monthly | top 5 | 76 | 0.76 | 52 | 0.45 | 5.4 | 73 | 1.08 | 55 |
| LARGE | live | banded | top 5 | 76 | 0.76 | 44 | 0.5 | 5.9 | 87 | 1.31 | 59 |
| LARGE | live | monthly | top 10 | 76 | 0.61 | 47 | 0.32 | 3.9 | 65 | 1.06 | 53 |
| LARGE | live | banded | top 10 | 76 | 0.67 | 36 | 0.45 | 5.4 | 93 | 1.47 | 57 |
| LARGE | live | monthly | top 20 | 76 | 0.92 | 38 | 0.69 | 8.3 | 123 | 3.05 | 64 |
| LARGE | live | banded | top 20 | 76 | 0.83 | 27 | 0.66 | 7.9 | 155 | 2.89 | 64 |
| LARGE | live | monthly | top 30 | 76 | 0.61 | 33 | 0.41 | 4.9 | 93 | 2.57 | 61 |
| LARGE | live | banded | top 30 | 76 | 0.63 | 21 | 0.5 | 6.0 | 152 | 3.16 | 61 |
| LARGE | live | monthly | top fifth | 76 | 0.92 | 38 | 0.69 | 8.3 | 123 | 3.05 | 64 |
| LARGE | live | banded | top fifth | 76 | 0.83 | 27 | 0.66 | 7.9 | 155 | 2.89 | 64 |
| LARGE | oos | monthly | top 5 | 53 | 0.32 | 69 | -0.1 | -1.2 | 23 | -0.16 | 40 |
| LARGE | oos | banded | top 5 | 53 | 0.4 | 60 | 0.03 | 0.4 | 33 | 0.06 | 42 |
| LARGE | oos | monthly | top 10 | 53 | 0.4 | 61 | 0.03 | 0.3 | 33 | 0.07 | 43 |
| LARGE | oos | banded | top 10 | 53 | 0.4 | 56 | 0.06 | 0.7 | 36 | 0.17 | 47 |
| LARGE | oos | monthly | top 20 | 53 | 0.2 | 53 | -0.13 | -1.5 | 19 | -0.51 | 40 |
| LARGE | oos | banded | top 20 | 53 | 0.36 | 44 | 0.09 | 1.0 | 40 | 0.33 | 45 |
| LARGE | oos | monthly | top 30 | 53 | 0.07 | 49 | -0.23 | -2.7 | 7 | -1.17 | 42 |
| LARGE | oos | banded | top 30 | 53 | 0.25 | 34 | 0.04 | 0.5 | 37 | 0.18 | 51 |
| LARGE | oos | monthly | top fifth | 53 | 0.2 | 53 | -0.13 | -1.5 | 19 | -0.51 | 40 |
| LARGE | oos | banded | top fifth | 53 | 0.36 | 44 | 0.09 | 1.0 | 40 | 0.33 | 45 |
| MID | live | monthly | top 5 | 76 | 1.13 | 49 | 0.63 | 7.6 | 115 | 1.27 | 55 |
| MID | live | banded | top 5 | 76 | 1.32 | 41 | 0.91 | 10.9 | 163 | 1.62 | 59 |
| MID | live | monthly | top 10 | 76 | 1.24 | 43 | 0.8 | 9.7 | 145 | 2.13 | 62 |
| MID | live | banded | top 10 | 76 | 1.43 | 30 | 1.12 | 13.5 | 241 | 2.78 | 66 |
| MID | live | monthly | top 20 | 76 | 1.04 | 36 | 0.67 | 8.0 | 145 | 2.25 | 59 |
| MID | live | banded | top 20 | 76 | 1.17 | 22 | 0.93 | 11.2 | 260 | 2.9 | 71 |
| MID | live | monthly | top 30 | 76 | 1.02 | 31 | 0.7 | 8.4 | 163 | 2.7 | 64 |
| MID | live | banded | top 30 | 76 | 0.95 | 18 | 0.77 | 9.2 | 270 | 3.04 | 66 |
| MID | live | monthly | top fifth | 76 | 1.03 | 31 | 0.71 | 8.5 | 164 | 2.73 | 64 |
| MID | live | banded | top fifth | 76 | 0.93 | 18 | 0.74 | 8.9 | 263 | 2.93 | 66 |
| MID | oos | monthly | top 5 | 54 | 0.4 | 78 | -0.38 | -4.6 | 26 | -0.77 | 54 |
| MID | oos | banded | top 5 | 54 | 0.21 | 68 | -0.47 | -5.7 | 16 | -0.88 | 48 |
| MID | oos | monthly | top 10 | 54 | 0.53 | 73 | -0.2 | -2.4 | 37 | -0.51 | 54 |
| MID | oos | banded | top 10 | 54 | 0.66 | 67 | -0.02 | -0.3 | 49 | -0.07 | 52 |
| MID | oos | monthly | top 20 | 54 | 0.26 | 72 | -0.47 | -5.7 | 18 | -1.67 | 48 |
| MID | oos | banded | top 20 | 54 | 0.38 | 60 | -0.23 | -2.8 | 31 | -0.78 | 54 |
| MID | oos | monthly | top 30 | 54 | 0.28 | 67 | -0.39 | -4.7 | 21 | -1.72 | 37 |
| MID | oos | banded | top 30 | 54 | 0.31 | 53 | -0.22 | -2.7 | 29 | -1.02 | 46 |
| MID | oos | monthly | top fifth | 54 | 0.3 | 67 | -0.38 | -4.5 | 22 | -1.65 | 39 |
| MID | oos | banded | top fifth | 54 | 0.32 | 53 | -0.21 | -2.6 | 30 | -0.97 | 46 |
| SMALL | live | monthly | top 5 | 76 | 1.24 | 85 | -1.3 | -15.6 | 73 | -1.55 | 38 |
| SMALL | live | banded | top 5 | 76 | 1.2 | 82 | -1.26 | -15.1 | 73 | -1.5 | 39 |
| SMALL | live | monthly | top 10 | 76 | 1.49 | 82 | -0.96 | -11.6 | 91 | -1.52 | 37 |
| SMALL | live | banded | top 10 | 76 | 1.41 | 76 | -0.86 | -10.4 | 94 | -1.37 | 36 |
| SMALL | live | monthly | top 20 | 76 | 1.49 | 77 | -0.84 | -10.1 | 96 | -1.73 | 36 |
| SMALL | live | banded | top 20 | 76 | 1.63 | 71 | -0.51 | -6.1 | 115 | -1.01 | 42 |
| SMALL | live | monthly | top 30 | 76 | 1.32 | 76 | -0.96 | -11.5 | 87 | -2.53 | 33 |
| SMALL | live | banded | top 30 | 76 | 1.31 | 68 | -0.74 | -8.9 | 96 | -1.81 | 37 |
| SMALL | live | monthly | top fifth | 76 | 1.2 | 56 | -0.5 | -6.0 | 107 | -3.28 | 29 |
| SMALL | live | banded | top fifth | 76 | 1.21 | 41 | -0.04 | -0.5 | 148 | -0.26 | 43 |
| SMALL | oos | monthly | top 5 | 69 | 1.74 | 90 | -0.95 | -11.4 | 97 | -1.58 | 35 |
| SMALL | oos | banded | top 5 | 69 | 1.65 | 87 | -0.97 | -11.7 | 95 | -1.59 | 33 |
| SMALL | oos | monthly | top 10 | 69 | 1.49 | 88 | -1.15 | -13.8 | 85 | -1.98 | 32 |
| SMALL | oos | banded | top 10 | 69 | 1.85 | 82 | -0.61 | -7.3 | 113 | -1.0 | 35 |
| SMALL | oos | monthly | top 20 | 69 | 1.56 | 82 | -0.91 | -10.9 | 95 | -1.96 | 39 |
| SMALL | oos | banded | top 20 | 69 | 1.75 | 76 | -0.53 | -6.4 | 116 | -1.11 | 41 |
| SMALL | oos | monthly | top 30 | 69 | 1.37 | 79 | -1.0 | -12.0 | 87 | -2.52 | 33 |
| SMALL | oos | banded | top 30 | 69 | 1.25 | 72 | -0.91 | -11.0 | 87 | -2.3 | 38 |
| SMALL | oos | monthly | top fifth | 69 | 0.65 | 57 | -1.06 | -12.7 | 58 | -6.43 | 19 |
| SMALL | oos | banded | top fifth | 69 | 0.57 | 41 | -0.68 | -8.1 | 70 | -4.28 | 29 |

## Since 2024-09-01

| tier | scores | rule | holding | months | gross_%/mo | turnover_% | net_%/mo | net_%/yr | breakeven_bps | t_net | months_up_% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| LARGE | oos | monthly | top 5 | 25 | -1.06 | 64 | -1.45 | -17.4 | -82 | -2.51 | 24 |
| LARGE | oos | banded | top 5 | 25 | -1.0 | 51 | -1.31 | -15.7 | -98 | -2.66 | 28 |
| LARGE | oos | monthly | top 10 | 25 | -0.54 | 52 | -0.85 | -10.2 | -52 | -2.32 | 28 |
| LARGE | oos | banded | top 10 | 25 | -0.54 | 44 | -0.8 | -9.6 | -61 | -1.8 | 36 |
| LARGE | oos | monthly | top 20 | 25 | -0.47 | 42 | -0.72 | -8.7 | -55 | -2.43 | 32 |
| LARGE | oos | banded | top 20 | 25 | -0.26 | 31 | -0.44 | -5.3 | -43 | -1.17 | 36 |
| LARGE | oos | monthly | top 30 | 25 | -0.3 | 38 | -0.53 | -6.3 | -40 | -2.35 | 36 |
| LARGE | oos | banded | top 30 | 25 | -0.08 | 24 | -0.22 | -2.6 | -16 | -0.83 | 44 |
| LARGE | oos | monthly | top fifth | 25 | -0.47 | 42 | -0.72 | -8.7 | -55 | -2.43 | 32 |
| LARGE | oos | banded | top fifth | 25 | -0.26 | 31 | -0.44 | -5.3 | -43 | -1.17 | 36 |
| LARGE | live | monthly | top 5 | 25 | -0.18 | 70 | -0.6 | -7.2 | -13 | -1.31 | 40 |
| LARGE | live | banded | top 5 | 25 | -0.18 | 57 | -0.51 | -6.2 | -16 | -1.1 | 44 |
| LARGE | live | monthly | top 10 | 25 | -0.27 | 60 | -0.62 | -7.5 | -22 | -1.85 | 24 |
| LARGE | live | banded | top 10 | 25 | -0.12 | 43 | -0.37 | -4.4 | -14 | -0.93 | 44 |
| LARGE | live | monthly | top 20 | 25 | 0.4 | 45 | 0.13 | 1.5 | 44 | 0.45 | 52 |
| LARGE | live | banded | top 20 | 25 | 0.31 | 34 | 0.11 | 1.3 | 46 | 0.35 | 56 |
| LARGE | live | monthly | top 30 | 25 | 0.22 | 40 | -0.02 | -0.2 | 28 | -0.1 | 52 |
| LARGE | live | banded | top 30 | 25 | 0.14 | 23 | -0.01 | -0.1 | 29 | -0.02 | 44 |
| LARGE | live | monthly | top fifth | 25 | 0.4 | 45 | 0.13 | 1.5 | 44 | 0.45 | 52 |
| LARGE | live | banded | top fifth | 25 | 0.31 | 34 | 0.11 | 1.3 | 46 | 0.35 | 56 |
| MID | oos | monthly | top 5 | 25 | 0.78 | 63 | 0.14 | 1.7 | 62 | 0.19 | 60 |
| MID | oos | banded | top 5 | 25 | 0.7 | 50 | 0.2 | 2.5 | 70 | 0.25 | 56 |
| MID | oos | monthly | top 10 | 25 | 0.97 | 65 | 0.32 | 3.9 | 75 | 0.51 | 60 |
| MID | oos | banded | top 10 | 25 | 0.7 | 58 | 0.12 | 1.5 | 60 | 0.22 | 56 |
| MID | oos | monthly | top 20 | 25 | 0.29 | 67 | -0.39 | -4.6 | 21 | -0.91 | 44 |
| MID | oos | banded | top 20 | 25 | 0.38 | 53 | -0.15 | -1.8 | 36 | -0.31 | 52 |
| MID | oos | monthly | top 30 | 25 | 0.42 | 63 | -0.21 | -2.5 | 33 | -0.72 | 40 |
| MID | oos | banded | top 30 | 25 | 0.39 | 46 | -0.07 | -0.9 | 42 | -0.22 | 48 |
| MID | oos | monthly | top fifth | 25 | 0.45 | 63 | -0.18 | -2.2 | 36 | -0.61 | 44 |
| MID | oos | banded | top fifth | 25 | 0.41 | 46 | -0.05 | -0.6 | 45 | -0.15 | 48 |
| MID | live | monthly | top 5 | 25 | 1.15 | 58 | 0.55 | 6.6 | 98 | 0.82 | 52 |
| MID | live | banded | top 5 | 25 | 1.07 | 47 | 0.59 | 7.0 | 115 | 0.76 | 52 |
| MID | live | monthly | top 10 | 25 | 1.66 | 48 | 1.17 | 14.1 | 173 | 2.67 | 68 |
| MID | live | banded | top 10 | 25 | 1.64 | 32 | 1.3 | 15.6 | 255 | 2.06 | 68 |
| MID | live | monthly | top 20 | 25 | 1.23 | 40 | 0.82 | 9.9 | 154 | 2.52 | 64 |
| MID | live | banded | top 20 | 25 | 1.56 | 27 | 1.29 | 15.5 | 290 | 3.07 | 76 |
| MID | live | monthly | top 30 | 25 | 1.1 | 36 | 0.74 | 8.9 | 152 | 2.4 | 68 |
| MID | live | banded | top 30 | 25 | 1.19 | 21 | 0.98 | 11.7 | 289 | 3.37 | 76 |
| MID | live | monthly | top fifth | 25 | 1.12 | 36 | 0.76 | 9.1 | 155 | 2.46 | 68 |
| MID | live | banded | top fifth | 25 | 1.11 | 21 | 0.9 | 10.8 | 270 | 3.09 | 76 |
| SMALL | oos | monthly | top 5 | 25 | 3.16 | 92 | 0.37 | 4.5 | 171 | 0.34 | 48 |
| SMALL | oos | banded | top 5 | 25 | 3.2 | 91 | 0.46 | 5.6 | 176 | 0.41 | 48 |
| SMALL | oos | monthly | top 10 | 25 | 2.34 | 92 | -0.43 | -5.2 | 127 | -0.44 | 48 |
| SMALL | oos | banded | top 10 | 25 | 2.47 | 88 | -0.18 | -2.2 | 141 | -0.18 | 48 |
| SMALL | oos | monthly | top 20 | 25 | 2.11 | 89 | -0.57 | -6.8 | 119 | -0.71 | 48 |
| SMALL | oos | banded | top 20 | 25 | 2.24 | 84 | -0.29 | -3.5 | 134 | -0.35 | 48 |
| SMALL | oos | monthly | top 30 | 25 | 1.73 | 85 | -0.84 | -10.0 | 102 | -1.36 | 40 |
| SMALL | oos | banded | top 30 | 25 | 1.83 | 79 | -0.57 | -6.8 | 116 | -0.91 | 40 |
| SMALL | oos | monthly | top fifth | 25 | 0.55 | 59 | -1.26 | -15.1 | 46 | -5.97 | 16 |
| SMALL | oos | banded | top fifth | 25 | 0.6 | 43 | -0.72 | -8.7 | 70 | -3.29 | 24 |
| SMALL | live | monthly | top 5 | 25 | 0.77 | 89 | -1.92 | -23.0 | 43 | -1.46 | 32 |
| SMALL | live | banded | top 5 | 25 | 0.92 | 88 | -1.72 | -20.7 | 52 | -1.29 | 32 |
| SMALL | live | monthly | top 10 | 25 | 1.52 | 85 | -1.05 | -12.6 | 89 | -0.81 | 40 |
| SMALL | live | banded | top 10 | 25 | 0.84 | 82 | -1.62 | -19.4 | 52 | -1.35 | 32 |
| SMALL | live | monthly | top 20 | 25 | 1.12 | 83 | -1.37 | -16.4 | 68 | -1.51 | 32 |
| SMALL | live | banded | top 20 | 25 | 1.31 | 78 | -1.02 | -12.3 | 84 | -1.12 | 36 |
| SMALL | live | monthly | top 30 | 25 | 1.19 | 82 | -1.26 | -15.1 | 73 | -1.94 | 28 |
| SMALL | live | banded | top 30 | 25 | 1.19 | 75 | -1.05 | -12.6 | 80 | -1.63 | 32 |
| SMALL | live | monthly | top fifth | 25 | 0.89 | 57 | -0.83 | -9.9 | 78 | -4.07 | 12 |
| SMALL | live | banded | top fifth | 25 | 0.88 | 41 | -0.35 | -4.2 | 109 | -1.6 | 36 |

## Realistic costs (LARGE 15 / MID 25 / SMALL 50 bps one-way; `--cost`)

With those costs: SMALL top 10–20 on out-of-sample scores nets about 1.0%/month (t 1.7–2.1); at 80 bps about 0.5%/month (t 0.9–1.1). MID live top 10–20 nets 1.05–1.27%/month (t 3.2–3.3; in-sample weights); out-of-sample selection 0.1–0.3%/month. LARGE out of sample 0.1–0.2%/month (t < 0.9), negative since 2024-09.

## Full history

| tier | scores | rule | holding | months | gross_%/mo | turnover_% | net_%/mo | net_%/yr | breakeven_bps | t_net | months_up_% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| LARGE | live | monthly | top 5 | 76 | 0.76 | 52 | 0.6 | 7.3 | 73 | 1.47 | 57 |
| LARGE | live | banded | top 5 | 76 | 0.76 | 44 | 0.63 | 7.6 | 87 | 1.67 | 59 |
| LARGE | live | monthly | top 10 | 76 | 0.61 | 47 | 0.46 | 5.6 | 65 | 1.54 | 57 |
| LARGE | live | banded | top 10 | 76 | 0.67 | 36 | 0.56 | 6.7 | 93 | 1.83 | 57 |
| LARGE | live | monthly | top 20 | 76 | 0.92 | 38 | 0.81 | 9.7 | 123 | 3.56 | 72 |
| LARGE | live | banded | top 20 | 76 | 0.83 | 27 | 0.75 | 8.9 | 155 | 3.27 | 64 |
| LARGE | live | monthly | top 30 | 76 | 0.61 | 33 | 0.51 | 6.1 | 93 | 3.22 | 61 |
| LARGE | live | banded | top 30 | 76 | 0.63 | 21 | 0.57 | 6.8 | 152 | 3.57 | 62 |
| LARGE | live | monthly | top fifth | 76 | 0.92 | 38 | 0.81 | 9.7 | 123 | 3.56 | 72 |
| LARGE | live | banded | top fifth | 76 | 0.83 | 27 | 0.75 | 8.9 | 155 | 3.27 | 64 |
| LARGE | oos | monthly | top 5 | 53 | 0.32 | 69 | 0.11 | 1.3 | 23 | 0.18 | 43 |
| LARGE | oos | banded | top 5 | 53 | 0.4 | 60 | 0.22 | 2.6 | 33 | 0.36 | 45 |
| LARGE | oos | monthly | top 10 | 53 | 0.4 | 61 | 0.21 | 2.5 | 33 | 0.58 | 43 |
| LARGE | oos | banded | top 10 | 53 | 0.4 | 56 | 0.23 | 2.8 | 36 | 0.63 | 49 |
| LARGE | oos | monthly | top 20 | 53 | 0.2 | 53 | 0.04 | 0.5 | 19 | 0.15 | 45 |
| LARGE | oos | banded | top 20 | 53 | 0.36 | 44 | 0.22 | 2.6 | 40 | 0.83 | 49 |
| LARGE | oos | monthly | top 30 | 53 | 0.07 | 49 | -0.08 | -0.9 | 7 | -0.4 | 43 |
| LARGE | oos | banded | top 30 | 53 | 0.25 | 34 | 0.14 | 1.7 | 37 | 0.66 | 53 |
| LARGE | oos | monthly | top fifth | 53 | 0.2 | 53 | 0.04 | 0.5 | 19 | 0.15 | 45 |
| LARGE | oos | banded | top fifth | 53 | 0.36 | 44 | 0.22 | 2.6 | 40 | 0.83 | 49 |
| MID | live | monthly | top 5 | 76 | 1.13 | 49 | 0.88 | 10.6 | 115 | 1.78 | 59 |
| MID | live | banded | top 5 | 76 | 1.32 | 41 | 1.11 | 13.4 | 163 | 2.0 | 61 |
| MID | live | monthly | top 10 | 76 | 1.24 | 43 | 1.02 | 12.2 | 145 | 2.71 | 63 |
| MID | live | banded | top 10 | 76 | 1.43 | 30 | 1.27 | 15.3 | 241 | 3.18 | 67 |
| MID | live | monthly | top 20 | 76 | 1.04 | 36 | 0.85 | 10.2 | 145 | 2.87 | 64 |
| MID | live | banded | top 20 | 76 | 1.17 | 22 | 1.05 | 12.6 | 260 | 3.26 | 72 |
| MID | live | monthly | top 30 | 76 | 1.02 | 31 | 0.86 | 10.4 | 163 | 3.34 | 64 |
| MID | live | banded | top 30 | 76 | 0.95 | 18 | 0.86 | 10.3 | 270 | 3.42 | 68 |
| MID | live | monthly | top fifth | 76 | 1.03 | 31 | 0.87 | 10.4 | 164 | 3.36 | 64 |
| MID | live | banded | top fifth | 76 | 0.93 | 18 | 0.83 | 10.0 | 263 | 3.32 | 68 |
| MID | oos | monthly | top 5 | 54 | 0.4 | 78 | 0.01 | 0.1 | 26 | 0.01 | 56 |
| MID | oos | banded | top 5 | 54 | 0.21 | 68 | -0.13 | -1.6 | 16 | -0.24 | 54 |
| MID | oos | monthly | top 10 | 54 | 0.53 | 73 | 0.17 | 2.0 | 37 | 0.42 | 61 |
| MID | oos | banded | top 10 | 54 | 0.66 | 67 | 0.32 | 3.8 | 49 | 0.91 | 59 |
| MID | oos | monthly | top 20 | 54 | 0.26 | 72 | -0.11 | -1.3 | 18 | -0.38 | 52 |
| MID | oos | banded | top 20 | 54 | 0.38 | 60 | 0.07 | 0.9 | 31 | 0.24 | 59 |
| MID | oos | monthly | top 30 | 54 | 0.28 | 67 | -0.05 | -0.7 | 21 | -0.24 | 54 |
| MID | oos | banded | top 30 | 54 | 0.31 | 53 | 0.04 | 0.5 | 29 | 0.19 | 50 |
| MID | oos | monthly | top fifth | 54 | 0.3 | 67 | -0.04 | -0.5 | 22 | -0.18 | 54 |
| MID | oos | banded | top fifth | 54 | 0.32 | 53 | 0.05 | 0.6 | 30 | 0.24 | 50 |
| SMALL | live | monthly | top 5 | 76 | 1.24 | 85 | 0.39 | 4.7 | 73 | 0.47 | 53 |
| SMALL | live | banded | top 5 | 76 | 1.2 | 82 | 0.38 | 4.6 | 73 | 0.45 | 54 |
| SMALL | live | monthly | top 10 | 76 | 1.49 | 82 | 0.67 | 8.1 | 91 | 1.07 | 55 |
| SMALL | live | banded | top 10 | 76 | 1.41 | 76 | 0.66 | 7.9 | 94 | 1.06 | 55 |
| SMALL | live | monthly | top 20 | 76 | 1.49 | 77 | 0.71 | 8.6 | 96 | 1.47 | 55 |
| SMALL | live | banded | top 20 | 76 | 1.63 | 71 | 0.92 | 11.0 | 115 | 1.83 | 57 |
| SMALL | live | monthly | top 30 | 76 | 1.32 | 76 | 0.56 | 6.7 | 87 | 1.5 | 58 |
| SMALL | live | banded | top 30 | 76 | 1.31 | 68 | 0.62 | 7.5 | 96 | 1.52 | 57 |
| SMALL | live | monthly | top fifth | 76 | 1.2 | 56 | 0.63 | 7.6 | 107 | 4.06 | 62 |
| SMALL | live | banded | top fifth | 76 | 1.21 | 41 | 0.79 | 9.5 | 148 | 4.75 | 71 |
| SMALL | oos | monthly | top 5 | 69 | 1.74 | 90 | 0.84 | 10.1 | 97 | 1.4 | 52 |
| SMALL | oos | banded | top 5 | 69 | 1.65 | 87 | 0.78 | 9.3 | 95 | 1.27 | 51 |
| SMALL | oos | monthly | top 10 | 69 | 1.49 | 88 | 0.61 | 7.3 | 85 | 1.04 | 49 |
| SMALL | oos | banded | top 10 | 69 | 1.85 | 82 | 1.03 | 12.4 | 113 | 1.69 | 54 |
| SMALL | oos | monthly | top 20 | 69 | 1.56 | 82 | 0.74 | 8.8 | 95 | 1.59 | 52 |
| SMALL | oos | banded | top 20 | 69 | 1.75 | 76 | 0.99 | 11.9 | 116 | 2.08 | 55 |
| SMALL | oos | monthly | top 30 | 69 | 1.37 | 79 | 0.58 | 6.9 | 87 | 1.47 | 54 |
| SMALL | oos | banded | top 30 | 69 | 1.25 | 72 | 0.53 | 6.3 | 87 | 1.33 | 55 |
| SMALL | oos | monthly | top fifth | 69 | 0.65 | 57 | 0.08 | 1.0 | 58 | 0.5 | 54 |
| SMALL | oos | banded | top fifth | 69 | 0.57 | 41 | 0.16 | 1.9 | 70 | 1.0 | 55 |

## Since 2024-09-01

| tier | scores | rule | holding | months | gross_%/mo | turnover_% | net_%/mo | net_%/yr | breakeven_bps | t_net | months_up_% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| LARGE | oos | monthly | top 5 | 25 | -1.06 | 64 | -1.25 | -15.1 | -82 | -2.17 | 28 |
| LARGE | oos | banded | top 5 | 25 | -1.0 | 51 | -1.16 | -13.9 | -98 | -2.34 | 28 |
| LARGE | oos | monthly | top 10 | 25 | -0.54 | 52 | -0.69 | -8.3 | -52 | -1.89 | 28 |
| LARGE | oos | banded | top 10 | 25 | -0.54 | 44 | -0.67 | -8.1 | -61 | -1.49 | 36 |
| LARGE | oos | monthly | top 20 | 25 | -0.47 | 42 | -0.6 | -7.2 | -55 | -1.99 | 36 |
| LARGE | oos | banded | top 20 | 25 | -0.26 | 31 | -0.35 | -4.2 | -43 | -0.92 | 36 |
| LARGE | oos | monthly | top 30 | 25 | -0.3 | 38 | -0.41 | -4.9 | -40 | -1.81 | 40 |
| LARGE | oos | banded | top 30 | 25 | -0.08 | 24 | -0.15 | -1.8 | -16 | -0.55 | 48 |
| LARGE | oos | monthly | top fifth | 25 | -0.47 | 42 | -0.6 | -7.2 | -55 | -1.99 | 36 |
| LARGE | oos | banded | top fifth | 25 | -0.26 | 31 | -0.35 | -4.2 | -43 | -0.92 | 36 |
| LARGE | live | monthly | top 5 | 25 | -0.18 | 70 | -0.39 | -4.7 | -13 | -0.86 | 40 |
| LARGE | live | banded | top 5 | 25 | -0.18 | 57 | -0.35 | -4.2 | -16 | -0.75 | 44 |
| LARGE | live | monthly | top 10 | 25 | -0.27 | 60 | -0.44 | -5.3 | -22 | -1.31 | 32 |
| LARGE | live | banded | top 10 | 25 | -0.12 | 43 | -0.24 | -2.9 | -14 | -0.61 | 44 |
| LARGE | live | monthly | top 20 | 25 | 0.4 | 45 | 0.26 | 3.2 | 44 | 0.91 | 64 |
| LARGE | live | banded | top 20 | 25 | 0.31 | 34 | 0.21 | 2.5 | 46 | 0.69 | 56 |
| LARGE | live | monthly | top 30 | 25 | 0.22 | 40 | 0.1 | 1.2 | 28 | 0.54 | 52 |
| LARGE | live | banded | top 30 | 25 | 0.14 | 23 | 0.07 | 0.8 | 29 | 0.28 | 44 |
| LARGE | live | monthly | top fifth | 25 | 0.4 | 45 | 0.26 | 3.2 | 44 | 0.91 | 64 |
| LARGE | live | banded | top fifth | 25 | 0.31 | 34 | 0.21 | 2.5 | 46 | 0.69 | 56 |
| MID | oos | monthly | top 5 | 25 | 0.78 | 63 | 0.46 | 5.6 | 62 | 0.62 | 60 |
| MID | oos | banded | top 5 | 25 | 0.7 | 50 | 0.45 | 5.4 | 70 | 0.56 | 60 |
| MID | oos | monthly | top 10 | 25 | 0.97 | 65 | 0.65 | 7.8 | 75 | 1.02 | 64 |
| MID | oos | banded | top 10 | 25 | 0.7 | 58 | 0.41 | 5.0 | 60 | 0.74 | 64 |
| MID | oos | monthly | top 20 | 25 | 0.29 | 67 | -0.05 | -0.6 | 21 | -0.12 | 48 |
| MID | oos | banded | top 20 | 25 | 0.38 | 53 | 0.11 | 1.3 | 36 | 0.23 | 52 |
| MID | oos | monthly | top 30 | 25 | 0.42 | 63 | 0.1 | 1.3 | 33 | 0.36 | 56 |
| MID | oos | banded | top 30 | 25 | 0.39 | 46 | 0.16 | 1.9 | 42 | 0.47 | 48 |
| MID | oos | monthly | top fifth | 25 | 0.45 | 63 | 0.13 | 1.6 | 36 | 0.45 | 56 |
| MID | oos | banded | top fifth | 25 | 0.41 | 46 | 0.18 | 2.2 | 45 | 0.53 | 48 |
| MID | live | monthly | top 5 | 25 | 1.15 | 58 | 0.85 | 10.2 | 98 | 1.29 | 56 |
| MID | live | banded | top 5 | 25 | 1.07 | 47 | 0.83 | 10.0 | 115 | 1.09 | 56 |
| MID | live | monthly | top 10 | 25 | 1.66 | 48 | 1.42 | 17.0 | 173 | 3.24 | 68 |
| MID | live | banded | top 10 | 25 | 1.64 | 32 | 1.47 | 17.7 | 255 | 2.35 | 68 |
| MID | live | monthly | top 20 | 25 | 1.23 | 40 | 1.03 | 12.3 | 154 | 3.13 | 72 |
| MID | live | banded | top 20 | 25 | 1.56 | 27 | 1.42 | 17.1 | 290 | 3.4 | 80 |
| MID | live | monthly | top 30 | 25 | 1.1 | 36 | 0.92 | 11.1 | 152 | 2.99 | 68 |
| MID | live | banded | top 30 | 25 | 1.19 | 21 | 1.08 | 13.0 | 289 | 3.74 | 76 |
| MID | live | monthly | top fifth | 25 | 1.12 | 36 | 0.94 | 11.3 | 155 | 3.05 | 68 |
| MID | live | banded | top fifth | 25 | 1.11 | 21 | 1.01 | 12.1 | 270 | 3.45 | 76 |
| SMALL | oos | monthly | top 5 | 25 | 3.16 | 92 | 2.23 | 26.7 | 171 | 2.04 | 68 |
| SMALL | oos | banded | top 5 | 25 | 3.2 | 91 | 2.29 | 27.5 | 176 | 2.06 | 68 |
| SMALL | oos | monthly | top 10 | 25 | 2.34 | 92 | 1.41 | 17.0 | 127 | 1.46 | 68 |
| SMALL | oos | banded | top 10 | 25 | 2.47 | 88 | 1.59 | 19.1 | 141 | 1.62 | 68 |
| SMALL | oos | monthly | top 20 | 25 | 2.11 | 89 | 1.22 | 14.6 | 119 | 1.5 | 60 |
| SMALL | oos | banded | top 20 | 25 | 2.24 | 84 | 1.4 | 16.8 | 134 | 1.7 | 60 |
| SMALL | oos | monthly | top 30 | 25 | 1.73 | 85 | 0.87 | 10.5 | 102 | 1.41 | 60 |
| SMALL | oos | banded | top 30 | 25 | 1.83 | 79 | 1.03 | 12.4 | 116 | 1.66 | 68 |
| SMALL | oos | monthly | top fifth | 25 | 0.55 | 59 | -0.05 | -0.6 | 46 | -0.25 | 48 |
| SMALL | oos | banded | top fifth | 25 | 0.6 | 43 | 0.16 | 1.9 | 70 | 0.74 | 56 |
| SMALL | live | monthly | top 5 | 25 | 0.77 | 89 | -0.13 | -1.5 | 43 | -0.1 | 52 |
| SMALL | live | banded | top 5 | 25 | 0.92 | 88 | 0.04 | 0.4 | 52 | 0.03 | 56 |
| SMALL | live | monthly | top 10 | 25 | 1.52 | 85 | 0.66 | 8.0 | 89 | 0.52 | 56 |
| SMALL | live | banded | top 10 | 25 | 0.84 | 82 | 0.02 | 0.3 | 52 | 0.02 | 52 |
| SMALL | live | monthly | top 20 | 25 | 1.12 | 83 | 0.29 | 3.5 | 68 | 0.33 | 52 |
| SMALL | live | banded | top 20 | 25 | 1.31 | 78 | 0.53 | 6.4 | 84 | 0.59 | 52 |
| SMALL | live | monthly | top 30 | 25 | 1.19 | 82 | 0.37 | 4.5 | 73 | 0.58 | 60 |
| SMALL | live | banded | top 30 | 25 | 1.19 | 75 | 0.44 | 5.3 | 80 | 0.7 | 60 |
| SMALL | live | monthly | top fifth | 25 | 0.89 | 57 | 0.32 | 3.8 | 78 | 1.57 | 60 |
| SMALL | live | banded | top fifth | 25 | 0.88 | 41 | 0.47 | 5.7 | 109 | 2.18 | 68 |
