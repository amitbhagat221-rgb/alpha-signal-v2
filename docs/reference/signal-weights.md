# Validated Signal Map

From v1 C13b — 36 monthly periods, reproduced by `tools/backtest_pit.py` in v2.

| Signal | LARGE | MID | SMALL |
|--------|-------|-----|-------|
| Consensus | t=3.52 | t=2.20 | t=2.44 |
| CF Accruals | t=0.20 | t=3.20 | t=2.10 |
| Promoter QoQ | t=0.04 | t=0.83 | t=3.20 |
| Earnings Yield | t=1.57 | t=1.01 | t=3.13 |
| Piotroski | t=0.51 | t=2.23 | t=2.81 |
| Book-to-Price | t=0.79 | t=2.33 | t=2.54 |

## Weight tiers

| t-stat | Weight |
|---|---|
| ≥ 2.5 | 1.0× |
| 1.5 – 2.5 | 0.5× |
| 0.5 – 1.5 | 0.2× |
| < 0.5 | 0× |

## Promoted beyond the v1 C13b set

| Signal | Tier | t-stat | Periods | Weight | Notes |
|--------|------|--------|---------|--------|-------|
| pt_upside | LARGE/MID/SMALL | 7.15/8.40/9.14 | v2 PIT | wired 2026-05-28 | analyst PT upside |
| eps_growth | LARGE/SMALL | 5.31/3.23 | v2 PIT | wired 2026-05-28 | |
| pledge_quality | SMALL | 5.90 | v2 PIT | wired 2026-05-29 | promoter-pledge stress |
| delivery_anomaly_z | SMALL | 4.76 | v2 PIT | wired 2026-05-29 | |
| **iv_skew_25d** | **MID** | **+3.16** | **48 weekly (~11mo)** | **0.18** | wired 2026-05-31 (ADR 0035). In-house IV-surface skew; orthogonal to size/adtv/existing (\|ρ\|<0.15); F&O-stock coverage. LARGE t=1.37 / SMALL t=0.17 DROP → MID-only. Conservative 0.18 (vs t-tier's 1.0×) given single-derivative-class novelty + ~11mo vs 36mo history. |

## On the bench (validated, NOT wired)

- **kyle_lambda** (LARGE t=+4.24 / MID t=+4.14 KEEP, 39mo) — Amihud illiquidity premium, but ρ(kyle, ln_ADTV)=−0.73: largely a cost-coupled liquidity tilt, semi-captured by the eligibility gate, MID IC decaying. Held as diagnostic, not alpha.
- F&O OI four + iv_realised_spread / iv_term_structure / iv_percentile_1y — see `FACTOR_LIBRARY`.

## Pending backtesting

- Insider (2yr reconstructed)
- Regulatory (3yr events)
- Macro sector (3yr indicators)
- Track 3 Phase 3.2 factors (plan 0002)
