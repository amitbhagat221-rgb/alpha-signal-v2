# 0010 — PIT-strict corporate-action adjustment composes at signal-compute time
**2026-05-06 · Accepted**

**Decision.** Adjustments compose at signal-compute time, never at ingest.

1. Raw close in `stock_prices` stays raw. No `adj_close` column.
2. `corporate_adjustments` (PK `(sid, ex_date)`, columns: `factor`, `n_events`, `inds`, `subjects`) built from `corporate_actions` by [tools/compute_corporate_adjustments.py](../../tools/compute_corporate_adjustments.py). Same-day SPLIT+BONUS+DIVIDEND pre-multiplied into one factor.
3. At reconstruction, `apply_pit_adjustments(prices_pit, adjustments, eval_date)` materializes per-snapshot `adj_close` in memory — composes only events with `ex_date <= eval_date`. Vectorized via reverse cumprod + `np.searchsorted`.
4. Price signals read `prices_pit["adj_close"]` after the helper; get PIT correctness for free.

**Why.** v1 used yfinance `Adj Close` which forward-adjusts history every new event — embeds future events into past prices. v2 had quietly mirrored this with `tools/apply_splits.py` writing a static `adj_close` at ingest. Both leaky. Phase 3.2 (~50 new price-based factors) would inherit the leak.

**Switched in this ADR.** `pit_momentum`, `pit_position_52w`, `pit_macd_bullish`. `pit_fwd_return_20d` stays on raw close (it measures realized backtest returns from the perspective of a trader on `eval_date+20`, who actually receives dividends).

**Validation lift.** 12-date Pearson on existing stack: raw close 0.745 → PIT-adj 0.862 (+0.117).

**Trade-offs.** Reconstruction time 14.6s → 216s (acceptable). Anyone adding a price factor must remember to read `adj_close`, not `close` — convention only, not enforced.

**Removed.** `tools/apply_splits.py`, `tools/compute_splits.py`, `stock_prices.adj_close` column (commit `4e6cef1`).

**References.** [tools/reconstruct_pit.py:283-324](../../tools/reconstruct_pit.py#L283-L324) · related: [0003](0003-bhavcopy-over-yfinance.md)
