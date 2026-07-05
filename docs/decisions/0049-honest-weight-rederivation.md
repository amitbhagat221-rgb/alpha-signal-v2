# ADR 0049 — Honest weight re-derivation on clean data

Status: accepted 2026-07-05 · Builds on [ADR 0047](0047-fwd-return-anchor-proximity-guard.md) (clean panel), [ADR 0043](0043-multiple-testing-aware-factor-significance.md) (haircut), [ADR 0045](0045-pull-pt-upside-lookahead.md)

## Context
After the fwd_return re-baseline (ADR 0047), the wired weights were stale — derived on
contaminated t-stats, over-weighting deflated factors (promoter, MID consensus), double-counting
the Value group, and missing validated factors (consensus was unwired in SMALL, sector_tilt in
LARGE). A mechanical "wire the high t-stats" pass would have re-created the audit's failures: the
raw clean scorecard's top LARGE rows are `eps_growth` (t=4.58, **n=9** artifact), `kyle_lambda`
(t=4.22, **benched** cost-coupled), and wrong-sign factors (`roic −2.5`, `interest_coverage
−2.58`, `low_vol +1.99` — all "buy junk", bull-regime artifacts).

## Decision
Re-derive `SIGNAL_WEIGHTS` among the **screener-consumable signals** under five hard rules:
1. clean v2 |t| ≥ 1.5 on the tier (exclude v1_archive-only support);
2. n ≥ 20 anchors (drops eps_growth n=9);
3. **sign must match the economic prior** — every wrong-sign factor excluded;
4. one representative per orthogonal group (Value = `book_to_price` only, not +`earnings_yield`);
5. benched-for-cause stays benched (`kyle_lambda`).
Weights ∝ shrunk conviction, single-factor cap ~0.30, Σ|w|=1.0/tier.

**New scheme:**
- LARGE: consensus .42, sector_tilt .33, book_to_price .25 (**low conviction** — hollow tier)
- MID: iv_skew_25d .26, accruals .22, book_to_price .20, piotroski .18, governance −.14
- SMALL: delivery_anomaly_z .28, consensus .18, sector_tilt .18, book_to_price .14,
  pledge_quality .12, piotroski .10

## Consequences
- DROPPED as clean-data noise: `promoter` (was SMALL 0.19 / MID 0.04 — clean 0.47/1.14),
  `momentum` (1.34), MID `consensus` (−0.13), MID/LARGE `earnings_yield`, LARGE
  `accruals`/`piotroski`, SMALL `accruals`. ADDED: `consensus`→SMALL (t=3.74),
  `sector_tilt`→LARGE (t=1.58). `delivery_anomaly_z` boosted 0.12→0.28 (sole BY-FDR survivor).
- Re-scored: SMALL top-5 reshuffled (2 of 5 held); all tiers intact, Financials preserved
  (LARGE 27 / MID 19 / SMALL 127), 1695 picks, screener clean.
- **Scope B still open** — the newest validated factors (`eps_revision_yoy` SMALL 2.78,
  `value_composite`, announcement-window CAR) are NOT screener-consumable yet; wiring them needs
  `scoring/screener.py::_load_signals` extended. Tracked as the next factor-model step.
- LARGE remains structurally weak (best factor t=1.62); the real fix is a *new validated LARGE
  factor*, not re-weighting. Flagged low-conviction.
- This is evidence-derived, not a proven-live improvement — the honest gain is removing noise and
  contamination-era weights, not a demonstrated Sharpe lift. Revisit at the next promotion review.
