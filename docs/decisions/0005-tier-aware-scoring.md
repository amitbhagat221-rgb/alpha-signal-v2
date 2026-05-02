# 0005 — Tier-aware scoring (within-segment ranking)

**Status:** Accepted
**Date:** 2026-04-09 (carried over from v1 C12/C13b finding)
**Decided by:** Amit (with Claude Code)

## Context

When we backtested signals across the full universe (universe-wide IC), some signals looked weak (consensus t=2.4, piotroski t=1.5). When we re-ran the backtest stratified by market cap tier (LARGE / MID / SMALL), the picture changed dramatically:

| Signal | LARGE | MID | SMALL |
|--------|-------|-----|-------|
| Consensus | **t=3.52** | t=2.20 | t=2.44 |
| CF Accruals | t=0.20 | **t=3.20** | t=2.10 |
| Promoter QoQ | t=0.04 | t=0.83 | **t=3.20** |
| Earnings Yield | t=1.57 | t=1.01 | **t=3.13** |
| Piotroski | t=0.51 | t=2.23 | **t=2.81** |

Same signals, very different predictive power across tiers. Universe-wide ranking averages all of these into a mediocre middle. Within-tier ranking lets each signal do its job in the segment where it actually works.

## Decision

The screener never ranks across the full universe. Every signal is percentile-ranked **within** its cap tier, then weighted by tier-specific weights from `config.WEIGHTS`, then re-ranked within tier. Output: top 5–15 picks per tier (LARGE / MID / SMALL).

`cap_tier` must be assigned to every stock before any ranking happens. There is no "all stocks" mode — that's a category error.

## Alternatives considered

- **Universe-wide ranking with sector/size factors.** Too much smoothing — the tier-specific signal patterns get washed out.
- **Top N from each tier with hard quotas.** Simpler than weighted scoring but loses signal-level nuance.
- **Single weight vector across tiers.** What v1's original screener did. Empirically worse — see the t-stats above.

## Consequences

**Easier:**
- Each signal has a clean home where it works
- Adding a tier-specific signal (e.g. "delivery %" only matters for SMALL) is one more entry in `WEIGHTS["SMALL"]`
- Backtests are stratified by default; signal validity is testable per tier

**Harder:**
- More code paths (3 tier-specific scoring runs vs one universal run)
- Weight tuning takes longer — every tier has its own knobs
- Tier reassignment is sensitive: a stock crossing from MID to SMALL is now scored on a totally different formula

**Will bite us if:**
- Tier boundaries get sloppy (mitigation: cap_tier is recomputed monthly; transition log surfaces stocks crossing boundaries)
- Someone accidentally calls `df.rank(pct=True)` without `groupby("cap_tier")` — the rule is in CLAUDE.md as critical rule #10

## References

- Screener: `scoring/screener.py`
- Weight config: `config.WEIGHTS`
- Backtest that produced these t-stats: [../_archive/2026-04-03-c13b-pit-reconstruction.md](../_archive/2026-04-03-c13b-pit-reconstruction.md)
- Signal reference: [../reference/signals.md](../reference/signals.md)
