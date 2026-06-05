# 0041 — Daily sector tilt: backtest-gated, wired SMALL-only

**Status:** Accepted
**Date:** 2026-06-05

## Context
The daily **sector tilt** — per stock, its GICS sector's ensemble `mean( z(trailing-6m basket momentum), z(latest macro_sector_signals_pit.macro_score) )` z-scored across the 11 sectors — was validated 2026-06-04 ([tools/sector_tilt_validation.py](../../tools/sector_tilt_validation.py)) as **additive, not redundant** to the stock momentum already in the model: Fama-MacBeth slope **+0.84%/σ, t+3.34** controlling for stock momentum (slope *grows* under the control), double-sort orthogonal within every stock-momentum tercile. It was then parked ("optimise later") and is now being wired.

Two facts forced a careful path rather than wiring on the FM result alone:
1. A **close cousin is already benched** — `sector_momentum` (63d cap-weighted relative-strength vs NIFTY, [signals/sector_momentum.py](../../signals/sector_momentum.py)) backtested **WEAK/DROP within-tier** (LARGE −0.60 / MID +0.33 / SMALL +1.88) and sits unwired. The sector-momentum family had already failed the model's own lens once.
2. The FM t+3.34 was measured at a **3-month, pooled-across-tiers** horizon — not the **within-tier rank-IC** lens `daily_picks` actually ranks on.

## Decision
1. **Build it as a first-class backtestable factor `sector_tilt`**, not a post-rank overlay — [signals/sector_tilt.py](../../signals/sector_tilt.py) (one injectable core) + `pit_sector_tilt` twin in [reconstruct_pit.py](../../tools/reconstruct_pit.py), registered everywhere the cousin is (PIT column + `SIGNAL_COLUMN_MAP` + `BACKTEST_SIGNALS` + `FACTOR_LINEAGE`). A multiplicative tilt was rejected — inconsistent with the percentile engine and un-backtestable in-frame.
2. **Gate the production weight on a within-tier backtest.** Reconstructed 48 monthly anchors → `backtest_pit`: **SMALL t=+3.18 KEEP** (IC +0.023, ICIR 0.545, CI [1.14, 5.88], 34 periods), **LARGE +0.92 / MID +0.64 DROP**. The ensemble beats the cousin in *every* tier but clears only SMALL — the 3-month edge survives the within-tier lens there and nowhere else.
3. **Wire SMALL-only at 0.10** ([config.py](../../config.py) `SIGNAL_WEIGHTS[SMALL]`), funded by an even −0.01 haircut across the existing ten (ordering preserved, Σ=1.0). 0.10 sits alongside the other orthogonal non-fundamental SMALL signals (`delivery_anomaly_z` 0.10); the orthogonality (a genuinely new sector/macro dimension) earns weight beyond the raw t. LARGE/MID get **zero** weight — same SMALL-only shape as the cousin's only non-negative tier.

## Consequences
- SMALL `daily_picks` now tilt toward tailwind sectors as a **moderate nudge, not an override**: top-50 mean `sector_tilt` +0.49 vs +0.07 universe; tailwind sectors (Materials/Utilities/Industrials) overweighted, headwinds (IT/Consumer-Disc/Real-Estate) thinned — but a high-tilt sector with weak fundamentals (Health Care) still doesn't dominate, because the tilt is only 0.10 of the tier.
- The signal is **sector-constant** (11 distinct values → ties within a sector). Intended: it's a tilt, not a stock-selector; the backtest t=3.18 is on exactly this tie-heavy percentile structure.
- Computed **inline** in the screener (no table, like momentum/EY/delivery); the macro leg reads the monthly-cadence `macro_sector_signals_pit` (live=latest, PIT=latest ≤ eval_date), so before 2022-08 it falls back to the momentum z alone.
- Distinct from and supersedes the case for the benched `sector_momentum`; the cousin stays unwired (this is the better-specified version of the same idea).
- Re-judge LARGE/MID as the monthly panel deepens; revisit the SMALL weight if it drifts (never mechanical).
