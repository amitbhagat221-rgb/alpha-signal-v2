# HANDOFF
Updated: 2026-05-22 | Branch: master (1 unpushed + new work) | HEAD: `d1d4d33` docs: handoff — Track 3.1a verified, CCC ready as next factor

## Left off
Shipped 4 Track-3 factors end-to-end as signal+PIT-helper pairs (`ccc`, `operating_margin_trend`, `working_capital_intensity`, `interest_coverage`) and introduced `FACTOR_LIBRARY` in [db.py](db.py) so library-tier (sub-|t|=1.5) factors are explicitly registered. `BACKTEST_SIGNALS` grew 41→52; share_momentum hit KEEP (|t|=3.21, strongest Track-3 result), ccc + interest_coverage parked at WEAK pending sign verification, the rest dropped into library tier.

## Pick up here
1. Retrofit `pit_roic` + `pit_fcf_yield` in [tools/reconstruct_pit.py](tools/reconstruct_pit.py) — closes the unit-of-work rule violation; flips both from status MISSING → READY in `db.BACKTEST_SIGNALS`. Template: today's `pit_cash_conversion_cycle`.
2. Continue batch queue with `roiic` (ΔNOPAT / ΔInvested Capital, 5y). Same signal+PIT unit-of-work as ccc.
3. Decide share_momentum's scoring weight: hit KEEP at |t|=3.21 but stays out of `SCREEN.weight_tiers` per CLAUDE.md. Either weight-now (manual ~0.5×) or wait for Track 3.3a IC-stability framework.

## Watch out
- 4 new columns ALTER'd onto `daily_snapshots_pit` (ccc, margin_slope, wc_intensity, interest_coverage). `CREATE_TABLE_SQL` in [tools/reconstruct_pit.py](tools/reconstruct_pit.py) stops at `growth_composite` — pre-existing drift, but a fresh DB rebuild would miss 14+ columns.
- `FACTOR_LIBRARY` in [db.py](db.py) is hand-maintained. When a factor's t-stat crosses |t|≥1.5 it needs explicit removal. Not enforced by code — drift risk against `pit_ic_by_tier_v2`.
- Cockpit `import` test passed but the new "Track 3 — Library" group of 10 BACKTEST_SIGNALS entries hasn't been visually verified on a real page load.

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — Track 3 Phase 3.2 (6/50 factors PIT-shipped; next: roic/fcf_yield PIT retrofit → roiic)
