# ADR 0046 — Banded/hysteresis rebalancing is the default for the advisory HRP book

**Status:** accepted · 2026-07-05
**Context:** [docs/audit-2026-07-04-report.md](../audit-2026-07-04-report.md) Port-F1 (HIGH): 18.5%/day one-way turnover on the daily-rebuilt advisory book (~2.7/15 names/day) — cost-fatal vs the measured gross edge. (Same estimator re-run 2026-07-05, `tools/portfolio_nav`: 14.6%/day — the number drifts as books accrue; the conclusion doesn't.)

## Decision
`PORTFOLIO["hrp"]["rebalance"] = {"mode": "banded", "rank_exit": 8, "drift_pp": 2.0}` — DEFAULT.
Enter at top-5; sell only below within-tier rank 8 (missing from picks = below 8) or on the
existing history/ADTV screen; buy only to refill a sold slot (5/tier); sell-and-rebuy washes
cancel to "held". Unchanged name set + all weights ≤2pp drifted from target (drift measured from
the LAST ACTUAL RE-SIZE, not yesterday's carried copy) → carry the stored targets forward; else
re-run HRP+tilt+caps. `"mode": "daily"` restores old behavior; `--backfill` stays fresh-build.

## Evidence — `tools/rebalance_sim.py` replay, 2026-04-09 → 2026-07-04 (61 trading days)
| mode | 1-way turnover | names trd/day | gross Sharpe | net Sharpe | cost drag/yr |
|---|---|---|---|---|---|
| daily (stored books) | 14.6%/day | 10.3 | 1.45 | −1.23 | 53.1% |
| banded 8/2pp (SHIPPED) | 12.0%/day | 9.6 | 1.66 | −0.84 | 45.6% |
| banded 20/2pp (sensitivity) | 9.3%/day | 9.2 | 1.94 | −0.51 | 41.0% |
| banded 40/2pp (sensitivity) | 7.2%/day | 8.5 | 1.01 | −0.76 | 33.2% |

**HONEST MISS: the <5%/day acceptance target FAILS at the decided top-8/2pp band** (1.2×, not
~10×), and no band width fixes it (2.0× at rank_exit=40). The binding constraint is rank
instability, not the band: a top-5 name has an 11.5%/day hazard of falling below rank 8 next day
(SMALL 22%) → 41/65 days re-size, each moving ~7.4pp one-way in the UNCHANGED names alone
(~4.7pp/day of the 12.0); the 2pp drift band never binds (0 triggers). Getting under 5%/day needs
upstream score smoothing, partial re-size, or a weekly trade calendar — bands were NOT tweaked.

## Consequences
- **REGIME CHANGE 2026-07-05 in `portfolio_weights`**: books ≤2026-07-04 are daily rebuilds,
  later books are banded. The HRP-vs-EQW evidence stream (`portfolio_nav`, `portfolio_outcomes`,
  HANDOFF headlines) is NOT comparable across that date; the stream now measures the deployable
  strategy. Turnover remains an open finding (net Sharpe still negative at 12%/day).

## Iteration 2 (2026-07-05) — attack the two isolated causes

Iter-1 isolated two turnover drivers: rank instability (~2 name-swaps/day) and full-HRP jitter
(~4.7pp/day moving in UNCHANGED names on every trigger). Three new levers, added to the
`rebalance` block: `debounce_days` (sell only after N consecutive days below rank_exit),
`resize` ("partial" = survivors keep their drifted weights, the sold names' vacated mass funds
the incoming buys, no HRP re-run | "full" = re-run the whole machinery), `full_resize_weekday`
(weekly full HRP re-run, None = trigger-only). `tools/rebalance_sim.py --matrix` — 3×2×2 grid,
same 61-day window/cost model (fast in-memory price IO; the d1/full/trig cell reproduces iter-1):

| cell (debounce / resize / calendar) | turnover | trade-days | gross Sharpe | net Sharpe | cost/yr |
|---|---|---|---|---|---|
| daily (baseline) | 14.6%/day | 95% | 1.45 | −1.23 | 53.1% |
| d1/full/trig (=iter-1) | 12.0%/day | 93% | 1.66 | −0.84 | 45.6% |
| d1/partial/trig | 8.9%/day | 93% | 1.44 | −0.48 | 32.2% |
| d2/full/trig | 9.9%/day | 95% | 1.70 | −0.50 | 38.9% |
| d2/partial/trig | 7.2%/day | 95% | 1.75 | 0.00 | 27.1% |
| d3/full/trig | 8.8%/day | 93% | 1.98 | −0.13 | 35.3% |
| **d3/partial/trig (WINNER, SHIPPED)** | **6.2%/day** | 93% | 1.67 | **+0.11** | 24.5% |
| d3/partial/weekly | 8.0%/day | 93% | 1.92 | −0.01 | 31.7% |

(weekly-calendar and d1/d2 rows omitted for space; all monotone.) **Winner = d3/partial/trigger
(net Sharpe, tiebreak lower turnover).** Debounce is the turnover lever (1.73→0.68 name-exits/day
from d1→d3); partial re-size is the net-Sharpe lever (removes the HRP jitter cost — every full→
partial column flips net Sharpe up); the weekly calendar HURTS (re-injects the jitter partial
avoids). New defaults: `debounce_days=3, resize="partial", full_resize_weekday=None`.

**HONEST: still MISSES <5%/day (6.2%), but flips net Sharpe −0.84 → +0.11 — cost-fatal to
marginally cost-positive.** Residual binding constraint is SMALL-tier rank churn: even with 3-day
debounce, 13.4% of top-5 SMALL names sit below rank-8 for 3 straight days (vs 2.8% LARGE / 4.7%
MID) → 0.68 name-swaps/day × ~6.7% book weight ≈ 4.6pp/day of the 6.2 is irreducible name churn,
the rest partial-resize renorm. The next lever is **EMA-smoothing `final_score` before ranking**
(directly damps the 13.4% SMALL flip rate) — that touches the screener/scoring, out of scope here.

- **SECOND REGIME CHANGE 2026-07-05**: books built from today are iteration-2 banded (debounce-3
  partial). Same non-comparability caveat as above applies within the banded era at this date.
