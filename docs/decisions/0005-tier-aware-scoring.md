# 0005 — Tier-aware scoring (within-segment ranking)
**2026-04-09 · Accepted**

**Decision.** Never rank across the full universe. Every signal is percentile-ranked **within** its cap tier (LARGE/MID/SMALL), weighted by tier-specific `config.WEIGHTS`, then re-ranked within tier. `cap_tier` must be assigned before any ranking.

**Why.** Universe-wide IC averages out signal patterns that are strong in specific tiers. v1 C13b backtest showed dramatic stratification:

| Signal | LARGE | MID | SMALL |
|---|---|---|---|
| Consensus | **3.52** | 2.20 | 2.44 |
| CF Accruals | 0.20 | **3.20** | 2.10 |
| Promoter QoQ | 0.04 | 0.83 | **3.20** |
| Piotroski | 0.51 | 2.23 | **2.81** |

Same signals, very different power per tier. Within-tier lets each signal work where it actually works.

**Trade-offs.**
- 3 scoring runs instead of 1; tier-specific weight tuning
- Tier-boundary stocks (MID↔SMALL) get scored on different formulas — `cap_tier` recomputed monthly
- A `df.rank(pct=True)` without `groupby("cap_tier")` is a bug — guardrail in CLAUDE.md

**References.** `scoring/screener.py` · `config.WEIGHTS` · [reference/signal-weights.md](../reference/signal-weights.md)
