# 0010 — PIT-strict corporate-action adjustment composes at signal-compute time

**Status:** Accepted
**Date:** 2026-05-06
**Decided by:** Amit (with Claude Code)

## Context

Fundamentals in v2 are PIT-disciplined: `knowable_quarterly`, `knowable_annual`, and `knowable_shareholding` filter every signal input to "what was actually visible on `eval_date`." Prices were the asymmetric exception. v1 had used yfinance `Adj Close`, which forward-adjusts the entire price history every time a new corporate event lands — embedding future events into past prices, leaky for any historical snapshot. v2 quietly mirrored that with `tools/apply_splits.py` writing a static `adj_close` column at ingest time. The longer this stayed, the more new factors (F2 expansion: 50 new factors, several price-based) would inherit the leak.

The decision question: where do split / bonus / dividend adjustments get composed — at ingest, or at signal-compute time?

## Decision

**Adjustments compose at signal-compute time, never at ingest.**

Concretely:
1. Raw close prices in `stock_prices` stay raw. No `adj_close` column.
2. Corporate events live in `corporate_adjustments` (PK `(sid, ex_date)`, columns `factor`, `n_events`, `inds`, `subjects`), produced by [tools/compute_corporate_adjustments.py](../../tools/compute_corporate_adjustments.py) from the `corporate_actions` source table. Same-day SPLIT+BONUS+DIVIDEND events on a single `ex_date` are pre-multiplied into one combined factor.
3. At reconstruction time, `apply_pit_adjustments(prices_pit, adjustments, eval_date)` ([tools/reconstruct_pit.py:283-324](../../tools/reconstruct_pit.py#L283-L324)) materializes a per-snapshot `adj_close` column in memory, composing only events with `ex_date <= eval_date`. Vectorized per sid via reverse cumprod + `np.searchsorted`.
4. Price-based signals read `prices_pit["adj_close"]` after this helper has been called — they get PIT correctness for free without per-signal awareness.

Three signals switched from raw close to `adj_close` in this ADR's commit: `pit_momentum`, `pit_position_52w`, `pit_macd_bullish`. `pit_fwd_return_20d` deliberately stays on raw close (it measures realized backtest returns from the perspective of a trader on `eval_date+20`, not a signal input).

## Alternatives considered

- **Use yfinance `Adj Close` directly.** Rejected — leaky-by-construction (every new event rewrites history), asymmetric with the existing PIT-fundamentals discipline.
- **Pre-bake a static `adj_close` column at ingest** (the deleted `tools/apply_splits.py` path). Rejected — half-honest middle ground. Snapshots reconstructed against this column inherit a leak from any event after the snapshot.
- **Per-snapshot materialized adjusted prices** (write `adj_close_at_<eval_date>` for every reconstruction). Rejected — explosive storage (1.3M rows × N snapshots), modest performance benefit over the in-memory composition.
- **Forward-adjust `pit_fwd_return_20d` too.** Rejected for now — it's a realized-return measurement, not a signal input. A trader on `eval_date+20` actually receives dividends and trades the post-event price; raw close on the realized window is the closer model. Revisit if this assumption bites.

## Reversal cost

**Low.** The helper is one self-contained function (~40 LOC). The `corporate_adjustments` table can be ignored or dropped without affecting raw prices. Reverting to a static `adj_close` column would be a single ALTER + repopulate.

## Consequences

**Easier:**
- All future price-based factors (F2: ~50 new factors) inherit PIT correctness for free by reading `prices_pit["adj_close"]` after `apply_pit_adjustments`.
- Architectural symmetry — fundamentals and prices both compose-at-signal-time. One mental model.
- 12-date apples-to-apples Pearson lift on the existing factor stack: raw close 0.745 → PIT-adj 0.862 (+0.117). The structural fix is what matters; the lift number is confirmation.

**Harder:**
- Full reconstruction time grew from 14.6s (momentum-only) to 216s (all 23 signals) — same as the prior baseline before this ADR's experiments. Acceptable; harness is not the bottleneck.
- Anyone adding a price-based factor must remember to read `adj_close` (not `close`) from `prices_pit`. Convention only — not enforced. Risk mitigated by the three-signal precedent.
- Same-day combined events (e.g. SPLIT+DIVIDEND on 2025-06-16) are stored as a single multiplied factor. Recovering the per-event breakdown requires going back to `corporate_actions`.

**Will bite us if:**
- A future ingest path repopulates `stock_prices.adj_close` directly, bypassing the helper. Mitigation: the column itself is being dropped (separate commit) so there's no surface to write into.
- We add a price-based signal that wants the unadjusted close (e.g. a dividend-yield-realized factor). It can still read the raw `close` column — the helper adds `adj_close`, doesn't replace `close`.

## References

- Helper: `apply_pit_adjustments()` in [tools/reconstruct_pit.py:283-324](../../tools/reconstruct_pit.py#L283-L324)
- Adjustment table builder: [tools/compute_corporate_adjustments.py](../../tools/compute_corporate_adjustments.py)
- Plan: [docs/plans/0004-pit-reconstruction.md](../plans/0004-pit-reconstruction.md), Phase 3 (methodology corrections)
- Removed: `tools/apply_splits.py` and `tools/compute_splits.py` (deleted in commit `4e6cef1`)
- Related: [0003-bhavcopy-over-yfinance.md](0003-bhavcopy-over-yfinance.md) — why we don't trust yfinance's price layer in the first place
