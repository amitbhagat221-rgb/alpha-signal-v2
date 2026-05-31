# 0035 — F&O IV/Greeks derived in-house from bhavcopy (Track 3.1b, §3.2.2 IV half)

**Status:** Accepted
**Date:** 2026-05-31

## Context
[ADR 0034](0034-fno-oi-data-model.md) marked the four IV factors (`iv_skew_25d`, `iv_term_structure`, `iv_realised_spread`, `iv_percentile_1y`) **forward-only and blocked** — the assumption was that IV comes only from the live option-chain (not backfillable) or a paid feed. That assumption was wrong. `fno_bhav` already stores, per option row, the **EOD settlement price + strike + expiry + CE/PE + spot**, with ~3 expiries × ~48 strikes per stock per day. Those are exactly the inputs to recover IV by **Black-76 inversion** — no external feed, fully historical, backfillable to the depth of `fno_bhav`.

Validated 2026-05-31: NIFTY ATM IV computed off our settle prices tracks **India VIX** (from our own `macro_history`) to within ~0.1–2 vol points and sits correctly just below it (VIX integrates the full smile + constant-30d). CE & PE IV match exactly at the ATM strike (put-call parity holds → the inversion is sound). Single-stock levels land in documented real-world ranges (RELIANCE 26%, web range 20–60%).

## Decision
1. **Derive the IV surface ourselves.** New `sources/fno_iv.py` inverts Black-76 on `fno_bhav` settle prices into `fno_iv_history` (one row per underlying per date: `atm_iv`, `iv_skew_25d`, `iv_term_structure`). Daily `compute_fno_iv` step, INSERT OR REPLACE, self-heals across a backfill — mirrors `compute_fno_pcr`. No paid source; Zerodha Kite is live-only (no historical greeks via API — confirmed).
2. **Implied forward via put-call parity** (removes the dividend-yield guess; r≈repo enters only via the small e^{-rT} factor). **OTM convention** per wing (call for K≥F, put for K<F). Skew interpolates IV over Black-76 forward delta to ±0.25Δ.
3. **`atm_iv` basis = expiry closest to ~30d** (VIX-comparable, stable across the monthly roll). The two atm_iv-derived factors (`iv_realised_spread` = atm_iv − 21d realised vol; `iv_percentile_1y` = rank within trailing ≤252d) live in `signals/fno_iv_factors.py`.
4. **Backfill `fno_bhav` to ~12 months** so `iv_percentile_1y`'s 1-year window actually fills.

## Consequences
- All 8 of §3.2.2 are now backtestable in-house — the IV half is no longer blocked or forward-only.
- **`iv_term_structure` has thin single-stock coverage (~20%)**: Indian stock options concentrate liquidity in the near month, so the next-month ATM IV is often unrecoverable. It is really an index-level signal; kept for completeness with the coverage caveat. Skew + the atm_iv-derived factors are ~99% covered.
- Far-OTM stale strikes are excluded (`fno_bhav` keeps oi>0∨vol>0; plus a below-intrinsic price reject in the inverter). High-vol days can truncate a wing before 25Δ → skew NaN that day (acceptable).
- The `fno_iv_snapshot` (live, forward-only) table sketched in ADR 0034 is **not needed** for these factors; live IV capture remains optional future work for intraday use.
