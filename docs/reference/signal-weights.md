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

## Pending backtesting

- Insider (2yr reconstructed)
- Regulatory (3yr events)
- Macro sector (3yr indicators)
- Track 3 Phase 3.2 factors (plan 0002)
