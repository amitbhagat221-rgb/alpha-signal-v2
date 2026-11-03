# Study: a kill decision at the close of the day before expiry (T-1) — 2026-11-03

**Question (Amit, after the 2026-11-03 loss):** "had the same decision model been run around 3 PM yesterday we would
have killed the trade yesterday itself without this big of a loss — backtest a decision model just before EOD a
day before expiry."

**Verdict: DROP as a standing rule.** On every expiry since 2019 a T-1 kill rule lost money against holding, in
every form tried (distance to the strike, option price multiple, one leg or both, always). The 2026-11-02 situation
(a short strike within 0.5 % at the T-1 close) happened 8 times before on NIFTY; the leg expired worthless 7 of
those 8 times and the one breach cost ₹22 K. 2026-11-03 is the first of these weeks where a kill clearly pays; it is one
week, and the sample cannot say how often it recurs.

What the rule IS good for is a risk preference, not expected value: it caps a week at roughly the cost of the
threatened leg at T-1 (about ₹34 K at most in the near-strike weeks, at 16 lots), and gives up about 5–10 % of the yearly result for it. If ₹50 K is the
pain line, the honest answer is still size (fewer lots), not a T-1 exit.

## Method (read-only, `tools/option_t1_exit_study.py`)

- Every expiry with chain data: NIFTY 2019-01 → 2026-10 (364), SENSEX 2024-01 → 2026-10 (131). The live rule's trade
  is opened at the T-2 settle by `option_book.open_trade` (0.05-delta strikes, `fno_bhav` settle); the 2026-11-03
  expiry is not in the sample (no settlement in the DB yet); it is added by hand below.
- At the T-1 settle (15:30, the nearest free proxy for a 15:00 look) one decision: **hold**; **dist d** (buy back a
  short leg when the index is within d % of its strike); **prem k** (buy back a leg at ≥ k × its entry price);
  **both-dist d** (buy back both when either is within d %); **t1-close** (always buy back both at T-1).
- A buy-back pays the T-1 settle plus `option_book.leg_cost` (brokerage, charges, 1 % slippage); held legs settle at
  intrinsic on the expiry-day index. Rupees at this week's size: points × 16 lots × the lot size of the day.
- Whipsaw = the rule fired and the leg would have expired worthless.

## NIFTY, 364 expiries 2019–26, 16 lots of the lot size of each day

| Rule | Fired | Whipsaw | Mean / week | Median | Total | 5th pct | Worst |
|---|---|---|---|---|---|---|---|
| hold | 0 % | – | ₹9,589 | ₹8,914 | ₹35 L | +₹4,070 | −₹1.61 L |
| dist 0.5 % | 2 % | 88 % | ₹9,057 | ₹8,842 | ₹33 L | +₹2,872 | −₹1.61 L |
| dist 1 % | 10 % | 86 % | ₹8,836 | ₹8,696 | ₹32 L | −₹3,373 | −₹1.61 L |
| dist 1.5 % | 37 % | 95 % | ₹8,341 | ₹7,726 | ₹30 L | −₹3,536 | −₹1.21 L |
| prem 3× | 4 % | 69 % | ₹9,219 | ₹8,870 | ₹34 L | −₹2,377 | −₹1.61 L |
| t1-close (always) | 100 % | 96 % | ₹3,033 | ₹2,893 | ₹11 L | −₹7,644 | −₹39 K |

A first version of this table used 1,040 units for every year; these are the corrected figures.

### The 18 NIFTY weeks with a short strike within 0.75 % at the T-1 close

| Expiry | Leg | T-1 distance | Leg price | Next day | Points in the money at settle | Hold | Kill at T-1 |
|---|---|---|---|---|---|---|---|
| 2019-04-25 | CE 11,800 | 0.63 % | 3.5 → 8.1 | -0.72 % | 0 | +7.0 K | -3.1 K |
| 2021-03-04 | CE 15,300 | 0.36 % | 5.8 → 39.5 | -1.08 % | 0 | +13.9 K | -34.4 K |
| 2021-09-16 | CE 17,650 | 0.75 % | 2.5 → 3.8 | +0.63 % | 0 | +4.8 K | +1.4 K |
| 2021-12-09 | CE 17,600 | 0.75 % | 4.8 → 13.6 | +0.27 % | 0 | +7.9 K | -3.4 K |
| 2023-02-23 | PE 17,500 | 0.31 % | 3.9 → 29.8 | -0.25 % | 0 | +6.1 K | -18.4 K |
| 2023-06-08 | CE 18,850 | 0.66 % | 2.1 → 4.4 | -0.49 % | 0 | +4.2 K | +0.2 K |
| 2023-08-03 | PE 19,400 | 0.65 % | 3.6 → 16.3 | -0.74 % | 18 | -9.6 K | -8.5 K |
| 2023-11-30 | CE 20,150 | 0.27 % | 3.4 → 33.8 | +0.18 % | 0 | +5.4 K | -22.3 K |
| 2023-12-21 | PE 21,000 | 0.71 % | 5.5 → 27.6 | +0.50 % | 0 | +7.0 K | -15.8 K |
| 2024-01-18 | PE 21,500 | 0.33 % | 6.8 → 50.3 | -0.51 % | 38 | -22.1 K | -32.9 K |
| 2024-03-14 | PE 21,900 | 0.44 % | 5.8 → 49.8 | +0.68 % | 0 | +8.5 K | -32.1 K |
| 2024-11-14 | PE 23,400 | 0.68 % | 7.2 → 32.8 | -0.11 % | 0 | +4.9 K | -8.7 K |
| 2025-03-06 | CE 22,500 | 0.73 % | 6.0 → 19.3 | +0.93 % | 45 | -40.6 K | -10.8 K |
| 2025-10-07 | CE 25,200 | 0.49 % | 4.6 → 13.6 | +0.12 % | 0 | +11.8 K | -5.1 K |
| 2025-12-09 | PE 25,800 | 0.62 % | 5.9 → 14.1 | -0.47 % | 0 | +10.7 K | -6.7 K |
| 2025-12-23 | CE 26,300 | 0.49 % | 5.0 → 10.3 | +0.02 % | 0 | +11.7 K | -1.2 K |
| 2026-08-04 | CE 24,750 | -0.10 % | 4.2 → 11.0 | -0.64 % | 0 | +10.1 K | -1.8 K |
| 2026-09-29 | PE 22,650 | 0.57 % | 6.3 → 26.1 | -0.28 % | 0 | +11.2 K | -16.7 K |

Hold +₹53 K in total, kill −₹2.20 L. The leg finished in the money 3 of 18 times, for 18–45 points. Larger breaches
exist, but from further away at T-1: 2020-04-30 (110 pts, 2.06 %), 2020-05-28 (90, 0.91 %), 2022-07-28 (80, 1.25 %),
2026-05-12 (170, 1.12 %). 2026-11-03 is not in the sample: no settlement was stored when this was written.

### Adding the day's move (the reasoning used on 2026-11-02)

Kill the nearer leg when it is close AND the T-1 day moved toward it. These were chosen after seeing this week, so
they are in-sample, and each fired only a handful of times.

| Rule | Fired | Whipsaw | Mean / week | Total | Worst |
|---|---|---|---|---|---|
| hold | 0 | – | ₹9,589 | ₹34.9 L | −₹1.61 L |
| within 0.5 % and day > 1 % | 6 | 5 | ₹9,139 | ₹33.3 L | −₹1.61 L |
| within 1 % and day > 1.5 % | 8 | 6 | ₹9,333 | ₹34.0 L | −₹1.61 L |
| any distance and day > 1.5 % | 26 | 22 | ₹8,761 | ₹31.9 L | −₹1.61 L |

## SENSEX, 131 expiries 2024–26, 16 lots of 20

| Rule | Fired | Whipsaw | Mean / week | Total | Loss > ₹50 K | Worst |
|---|---|---|---|---|---|---|
| hold | 0 % | – | ₹10,660 | ₹14 L | 0 % | −₹42 K |
| dist 0.25 % | 5 % | 83 % | ₹2,787 | ₹4 L | 3 % | −₹3.3 L |
| dist 0.5 % | 7 % | 89 % | ₹1,794 | ₹2 L | 4 % | −₹3.3 L |
| prem 3× | 12 % | 88 % | ₹800 | ₹1 L | 4 % | −₹3.3 L |
| t1-close (always) | 100 % | 98 % | −₹5,288 | −₹7 L | 4 % | −₹3.3 L |

SENSEX is worse for a T-1 kill: the near-strike weeks there include the April 2025 crash and the May 2025 rally,
where the strike was already through at T-1 and the index came back by settlement (2025-05-13: close 82,430 vs
the 81,500 call, settled 81,148; the call expired worthless and the kill would have paid ₹1,103 a unit).

## What I had to interpret

- The decision is taken on the T-1 **settle** (15:30); a 15:00 look would differ by half an hour of drift. The
  1-minute option archive can refine this; it will not turn 1 breach in 18 into a rule.
- Buy-back cost = settle + 1 % slippage + charges; no bid/ask on EOD data. The live book pays the ask, so the real
  kill costs are a little higher than shown.
- Monthly and quarterly expiries get a 2-day trade each like a weekly; a few weeks therefore appear twice.
- Rupees are at 16 lots of today's lot size (65 / 20) so they read as this week; the early years traded 75-unit lots.

## Reading for the book

- The strangle's losses are gaps, not drifts. A T-1 look sees the drift (the strike getting close) and cannot see
  the gap; it pays the T-1 premium on the 85–95 % of near-strike weeks that then expire worthless.
- Last night's "close at the open" call was a tail choice, not an expected-value one, and the backtest here agrees
  with the expiry-day backtest in `option-stops-wings-2026-10.md`: nothing after entry shrinks the worst week except
  wings and size.
- If a cut to the worst week is wanted anyway: **dist 1.5 % on NIFTY** took the worst seen week from −₹1.61 L to −₹1.21 L and
  gave up 13 % of the mean, firing on 37 % of weeks. That is a lower worst seen, not a cap: a gap from further away is not caught.
