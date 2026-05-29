# 0032 — Tier direction-flip → split-signal methodology

**Status:** Accepted
**Date:** 2026-05-29

## Context
[signals/financial_signal.py](../../signals/financial_signal.py) Phase 2.2b shipped as a single composite (40% asset_quality + 30% profitability + 15% capital + 15% funding), all four sub-components encoded with a single fixed direction. The asset_quality leg was `direction='lower'` — low NPA = good — because the v1 banking reference + every textbook says so.

The Phase 2.2d backtest (148 PIT dates, 14.5K rows) returned `t = -0.75 / -1.30 / -0.34` across LARGE/MID/SMALL — well below the |t| ≥ 2.0 done gate. The composite was effectively noise.

Decomposition diagnostic surfaced the cause: **components have predictive power but the asset_quality leg flips sign by cap_tier**.

| Tier | Strongest NPA component | t-stat | Interpretation |
|---|---|---:|---|
| LARGE | `net_npa_pct` | **+2.39** | High NPA names mean-revert (distressed recovery) |
| MID | `net_npa_pct` | **+4.16** | Same mechanism stronger at MID |
| SMALL | `gross_npa_pct` | **-3.09** | Low NPA persists, quality compounds |

The composite's fixed `direction='lower'` was correctly aligned with SMALL but reversed against LARGE/MID. Averaging across tiers, the legs cancelled. The mechanism was visible per-tier, hidden in the composite.

Two paths were available:
1. **Per-tier sign flag** — keep one signal column, swap direction per cap_tier in `score_universe`.
2. **Split into two named signals** — `financial_quality` (direction='lower') and `financial_recovery` (direction='higher'), with each cap_tier consuming whichever matches its mechanism.

## Decision
**Path 2 — split into two named signals**. Whenever a factor's backtest IC flips sign across cap_tiers, ship two parallel signals — one per direction — with names that surface the *mechanism* (`quality`, `recovery`, `mean_reversion`, `momentum`, etc.). Do **not** apply per-tier sign on a single composite.

Implementation pattern (codified in [signals/financial_signal.py](../../signals/financial_signal.py)):
1. Compute the raw component once.
2. Z-score it twice — once per direction — into two columns: `<component>_<direction1>_z` and `<component>_<direction2>_z`.
3. Pass each variant z-score into the same `_compute_composite(df, aq_col=…, out_col=…, basis_col=…)` helper, producing two parallel composite columns.
4. Persist both columns + their basis strings in the signal scores table AND in `daily_snapshots_pit` via `_COLUMN_MIGRATIONS`.
5. Register each in [db.BACKTEST_SIGNALS](../../db.py) with its own row and tier-specific hypothesis text.
6. The original single-direction column is retained as a back-compat alias (`= quality variant` in this case) for older consumers; the backtest harness sees all three as distinct signals.
7. The screener's `SIGNAL_WEIGHTS[tier]` chooses which variant to consume per tier; bench-status variants are computed but not routed.

## Rationale (alternatives weighed)
- **Per-tier sign flag (Path 1)** — minimal schema change, single column, single name. But it obscures the mechanism: a downstream reader sees `financial_signal = 0.5` and has no way to tell whether that means "low NPA franchise" or "high-NPA recovery candidate" without checking the cap_tier. The single name conflates two trades with opposite economic semantics. Rejected.
- **Drop the asset_quality leg entirely** — would let the composite work uniformly with the remaining three components, but it discards 40% of the intended signal weight and the leg with the highest per-component t-stats (LARGE/MID +2.39/+4.16). Rejected.
- **Build a tier-specific composite from scratch** — clean but proliferates: every new factor with a tier-flip would spawn a new bespoke signal. The split pattern is reusable as a library of two variants. Rejected.
- **Wait for more PIT periods** — the direction-flip is visible at n=148 PIT dates and the signs are economically interpretable; this isn't a small-sample artifact. Rejected.

## Constraints / known limits
- **Both new signals stayed WEAK at first backtest** — `financial_recovery` MID t=+1.55 and SMALL t=-1.88 are directionally right but below the |t|≥2.0 routing gate. The split was the right call but doesn't itself promote anything to live picks. Routing decision deferred until ~Q1 FY27 when 6 more quarterly periods accumulate.
- **Schema churn is real** — every direction-flip factor doubles its column count in `financial_signal_scores` + `daily_snapshots_pit`. Not painful at the current 1-2 cases per quarter; revisit if 10+ factors split this way.
- **The back-compat alias is a footgun** — `financial_signal` continues to equal `financial_quality` by default. A future caller that wants "the live composite for MID" will read the alias and silently get the wrong-direction value. Mitigated by the BACKTEST_SIGNALS registry entry marking `financial_signal` as `SUPERSEDED` and by code comments at the merge point. Will remove the alias once the screener is fully migrated to tier-aware reads.
- **`tools/optimize_weights.py` doesn't yet know about the split** — when a tier's optimal weight scheme picks `financial_recovery`, the optimizer needs to know it can only weight that variant for LARGE/MID. Currently the optimizer treats each as a tier-agnostic factor; honourable practice is to add a `tier_eligibility` field per signal in BACKTEST_SIGNALS. Deferred to next iteration.
- **The decomposition only worked because each component is scored independently before the composite** — a black-box composite (e.g. an XGBoost over raw inputs) wouldn't have given us the per-leg t-stat readout that surfaced the direction flip. Worth remembering for Track 2.5 / 3.3b.

## Consequences
- The Phase 2.2b-v2 split shipped in commit `0d8d8bd`. `financial_quality` + `financial_recovery` are now first-class signals in BACKTEST_SIGNALS, both visible in `daily_snapshots_pit` and in cockpit `/model` factor health, with bench status.
- Re-running `tools.reconstruct_pit --signal financial_recovery` after each quarterly NBFC results cycle becomes a recurring action — added to checklist Next-3.
- The pattern generalises: when adding any future factor where the t-stat decomposition shows opposing signs by tier (e.g. `mom_12m` LARGE positive / SMALL negative is a candidate to re-examine), reach for the split rather than per-tier sign. Future readers can look up this ADR.
- The composite-level methodology of [ADR 0028 (two-variant factor model)](0028-two-variant-factor-model.md) is unaffected — that's about weight-scheme selection, not direction. ADR 0028's `SIGNAL_WEIGHTS_RETURN` / `SIGNAL_WEIGHTS_SHARPE` continue to operate at the per-tier composite level; ADR 0032 operates at the per-factor input level.

## Files
- [signals/financial_signal.py](../../signals/financial_signal.py) — `_compute_composite(df, aq_col, out_col, basis_col)` refactored; `compute()` + `compute_pit()` produce both `financial_quality` + `financial_recovery`.
- [db.py:_COLUMN_MIGRATIONS](../../db.py) — `financial_quality`, `financial_recovery`, `quality_basis`, `recovery_basis`, `asset_quality_quality_z`, `asset_quality_recovery_z` on `financial_signal_scores`; first two also on `daily_snapshots_pit`.
- [db.py:BACKTEST_SIGNALS](../../db.py) — `financial_signal` → SUPERSEDED; `financial_quality` + `financial_recovery` → READY.
- [tools/reconstruct_pit.py:pit_financial_signal()](../../tools/reconstruct_pit.py) — returns `[sid, financial_signal, financial_quality, financial_recovery]`; dispatch trigger matches any of the three signal names; `PIT_COLUMNS` extended.
- [tools/backtest_pit.py:SIGNAL_COLUMN_MAP](../../tools/backtest_pit.py) — both new signal IDs registered.
- [docs/plans/0001-mother-plan.md §2.2](../plans/0001-mother-plan.md) — Phase 2.2d status reflects the diagnostic finding; Phase 2.2b-v2 ships per this ADR.

## Trigger to revisit
A factor's IC backtest produces opposing signs across cap_tiers (e.g. SMALL t < -1.5 while LARGE t > +1.5, OR mirror) → look at this ADR before applying a per-tier sign flag. If the underlying economic mechanism is interpretably different per tier (quality vs recovery, momentum vs reversal), split into two named signals.
