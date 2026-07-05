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
