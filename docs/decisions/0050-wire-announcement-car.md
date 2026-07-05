# ADR 0050 — Wire announcement_car (PEAD-via-CAR) into LARGE + SMALL

Status: accepted 2026-07-05 · Builds on [ADR 0049](0049-honest-weight-rederivation.md) (honest reweight), [ADR 0047](0047-fwd-return-anchor-proximity-guard.md) (clean panel) · factor built commit `9dedead`

## Context
The honest reweight (ADR 0049) left LARGE structurally hollow — its best factor was `consensus`
at clean t=1.62. `announcement_car` (market-adjusted [−1,+1] CAR around the latest BSE `Result`
print, an earnings-surprise proxy needing no PIT consensus EPS) backtested on the clean panel
(78 anchors) at **LARGE +2.23 / SMALL +3.74 / MID +1.20, all positive** (the hypothesised drift
sign) — the first honest LARGE signal the rebuild produced, topping consensus. It was built
backtest-only (FACTOR_LIBRARY); wiring needed a live producer.

## Decision
1. **Producer:** no table — compute inline in `scoring/screener.py::_load_signals` via
   `compute_announcement_car()` (as-of today), exactly like `delivery_anomaly`/`sector_tilt`.
   PIT-safe by construction (dt_tm ≤ today, only closed windows, 90d staleness gate → NULL for
   names with no fresh print). Live coverage 1616/1872 non-MICRO (86%).
2. **Eligibility:** added `announcement_car` to `eligibility/registry.py` (has a Result print in
   trailing ~95d) so the 256 names without a fresh print are marked ineligible and
   `eligible_coverage` renormalizes — not penalised (the lesson from the Financials bug, ADR 0048).
3. **Weights:** orthogonality confirmed (max |ρ| ≈ 0.04 vs the SMALL cluster → genuinely new
   dimension, no redundancy shrink). LARGE — co-lead at **0.35** (its strongest factor):
   announcement_car .35 / consensus .28 / sector_tilt .22 / book_to_price .15. SMALL — diversifier
   at **0.14**: delivery .26 / consensus .16 / sector_tilt .16 / announcement_car .14 /
   book_to_price .12 / pledge .10 / piotroski .06. MID unchanged (CAR MID=1.20 DROP). Σ|w|=1.0.
4. Removed from `FACTOR_LIBRARY` (now wired — partition holds).

## Consequences
- Re-scored clean: 1695 picks, all tiers + Financials intact; CAR contributes (87/100 LARGE names
  carry a live value). LARGE is no longer hollow — its lead factor is now t=2.23, not 1.62.
- Still a diversifier-grade add, not robust-core: CAR fails BY-FDR (p_BY≈0.15), same band as the
  already-wired sector_tilt/consensus. Honest gain = a new orthogonal dimension + a real LARGE
  anchor, not a haircut-proof factor.
- Book (`portfolio_weights` 2026-07-05) rebuilt fresh (`--mode daily`, one-time after the model
  overhaul) so the advisory cockpit book reflects the new model rather than debounce-holding the
  pre-overhaul names; banded resumes tomorrow.
- Follow-ups: a [0,+2] window robustness variant (cheap); the next validated factors
  (eps_revision_yoy, value_composite) still need the same inline-producer treatment.
