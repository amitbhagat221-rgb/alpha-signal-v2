# 0034 — F&O OI data model (Track 3.1b)

**Status:** Accepted
**Date:** 2026-05-31

## Context
Plan 0002 §3.1b speced the NSE F&O ingest around `option_chain_equities` *per stock* (~200 calls/night) writing three tables (`fno_option_chain`/`fno_oi_history`/`fno_pcr_history`). A 2026-05-31 probe of nselib 2.5.1 found those function names don't exist, but `derivatives.fno_bhav_copy(trade_date)` returns the **entire EOD F&O market in one call** — ~35K rows (every strike × CE/PE × expiry × 211 stock + 5 index underlyings), with OI, ΔOI, volume, settle, and `UndrlygPric` (spot). It is also **archive-backfillable** (verified ≥6 months, consistent shape). The live option-chain API (the only IV/Greeks source) returned an empty payload — markets were closed (Sunday) — so IV feasibility is unverified.

## Decision
1. **One call, not a per-symbol loop.** A 6-month backfill is ~130 calls, not ~26,000. `sources/fno_pull.py` is built entirely on `fno_bhav_copy`.
2. **Two cadences, split by what's backfillable:**
   - **OI/price grid** (`fno_bhav`, backfillable) → feeds `pcr_oi`, `pcr_volume`, `oi_buildup_signal`, `max_pain_distance`. These factors are **NOT gated on the 90-day accumulation clock** — backfill gives 6mo of real history immediately.
   - **IV/Greeks** (forward-only, future `fno_iv_snapshot`) → feeds `iv_skew_25d`, `iv_term_structure`, `iv_percentile_1y`, `iv_realised_spread`. Stays clock-gated and pending a weekday verify that NSE exposes IV at all.
3. **Store the full strike grid, filtered to `oi>0 OR volume>0`** (16.3K of 35.6K rows/day). Max-pain and OI-buildup need every live strike; dead far-OTM strikes carry zero signal and ~halve storage. A future factor needing the *complete* grid must re-fetch raw.
4. **`fno_pcr_history` is a computed nearest-expiry rollup** (PCR + max-pain), INSERT OR REPLACE; `compute_fno_pcr` must run *after* `fetch_fno_bhav` in `PIPELINE_STEPS`.

## Consequences
- 4 of the 8 §3.2.2 options factors become backtestable now off a 6mo panel — unusually un-blocked factor work.
- Index underlyings carry `sid=NULL` (symbol-keyed); stock-only factor work filters `instrument_type='STO'` / `sid IS NOT NULL`.
- DB grew ~0.74 GB (2.83M rows). `STALENESS_OVERRIDE`=6 absorbs weekend+holiday `trade_date` gaps.
- The plan's `fno_option_chain` table name is dropped; `fno_bhav` + `fno_pcr_history` supersede the 3-table sketch.
