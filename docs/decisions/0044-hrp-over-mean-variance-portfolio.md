# ADR 0044 — HRP over mean-variance for portfolio construction

**Status:** accepted · 2026-06-14
**Context:** Track 3.3c (plan 0002 §3.3c); ↔ Track 2.4; supersedes the §3.3c spec's Markowitz text. Builds on `tools/hrp_prototype.py` (2026-06-09).

## Context

§3.3c as written specifies Markowitz mean-variance: `argmax (factor_score·w) − λ(w'Σw)` with a Ledoit-Wolf-shrunk
covariance. In practice our book is ~15 names sized from a covariance estimated on a few hundred noisy daily
returns over raw/unadjusted closes. Markowitz on inputs that thin is an "error-maximiser" — it concentrates
weight wherever the (mis)estimated covariance and the expected-return vector happen to align, and is acutely
sensitive to both. We have no reliable per-stock expected-return vector at all (analyst PT covers ~½ the book,
small-caps uncovered), so the µ input would be largely fabricated.

## Decision

Build the sized book with **Hierarchical Risk Parity** (López de Prado 2016), not mean-variance.
`portfolio_construction.py` → `portfolio_weights`:

1. **No µ input.** HRP allocates *risk* via a correlation-cluster hierarchy (quasi-diagonalise → recursive
   bisection). Dodges Markowitz instability; needs only the covariance.
2. **Alpha enters as a tilt, not an optimiser objective:** `w · exp(λ·z(final_score))`, λ=0.6 — a bounded
   nudge toward higher-ranked names, never the dominant term.
3. **Covariance** is still **Ledoit-Wolf-shrunk** (the one piece of the §3.3c spec we keep), and daily returns
   are winsorized to ±0.5 as a split-defense (raw closes — same rationale as `signals/sector_momentum.py`).
4. **Caps** (config `PORTFOLIO["hrp"]`): per-stock 12%, per-sector 35%, ₹1cr/day ADTV liquidity floor.
   Per-stock 12% (not the top-level 5%) because 15 names × 5% = 75% < 100% is infeasible; 1/15≈6.7%.
5. **Marginal risk contribution** persisted per name (percent of portfolio variance, Σ=1).

Mean-variance / cvxpy stays available for a later A/B once we have a defensible µ and ≥24mo PIT — HRP is the
default, not a permanent rejection of MV.

## Status / scope

**ADVISORY ONLY.** No capital is deployed until `tools/validate_rank_skill.py` clears (<6 independent 20d
windows as of 2026-06; 63d outcomes mature ~2026-07-06). This increment ships the table + sizing module; the
cockpit `/portfolio` sized view and any cron wiring are the next increment. The §3.3c "≥1.5% annualized
risk-adjusted over 18–24mo" hard gate is unchanged and still ~17mo out.

## Consequences

- The book is robust and explainable (cluster hierarchy + named tilts) rather than a black-box optimiser.
- Weights are deliberately diversified (effective-N ~11/15 on the 2026-06-14 book), not return-chasing.
- Cost: HRP ignores expected returns by design, so it will under-weight a genuinely high-Sharpe name relative
  to MV — accepted, because our µ estimates aren't trustworthy enough to earn that concentration.
