# ADR 0087 — Live book controls after the 2026-10-30 incident: read every iceberg slice, size on the broker, cap the wing price, cancel on kill or crash, flag a silent day

**Status:** accepted 2026-10-31 (Amit: "what all controls are now in place so such stupid mistakes dont happen" → "and what about all controls are those in place"). Extends plan 0029 stage 0; the wing cap amends the wing rule of 2026-10-28 (checklist: protective wings).

## Decision
- **Every Kite order is read through its slices.** `_members` / `_combined` fold an iceberg parent and its children (`parent_order_id`) into one filled quantity; a status, fill or cancel decision never reads the parent row alone.
- **The sale is sized on the broker, not on the plan.** After the wings, `entry` reads Kite's positions and sells the strangle on the lots both wings actually hold; a mismatch between legs is flattened and `_entry_check` sets the kill switch.
- **Wings cost at most `wing_max_share_pct` (30 %) of the credit** (both wing asks over both short bids, at plan time). The dearer wing is stepped out one listed strike at a time, up to `wing_max_pct` (3.5 % of spot) beyond its short; past that `WingsTooDear` skips the entry with an urgent push. `sizing_quote` prices the uncapped wings.
- **The kill switch is re-read before the first order and at every 20-second re-price.** On: working slices cancelled, filled wings sold back, nothing sold; mid-sale the filled shorts pass `_entry_check` and the step stops. A crash inside the order loop cancels every working slice before it raises.
- **Each mark compares Kite's free margin with the safety buffer and the expiry-day extra** of the open shorts; short → urgent push.
- **A silent entry day is CRITICAL.** The OPTIONS_LIVE check wants `step:entry:<index>`, `step:record:ALL`, `step:reconcile:ALL` dated the last session with a due entry (today after 15:55 IST), in approve / auto only.
- **`_write` retries a locked DB** (30 / 60 / 120 s); the run.sh lock is per step and index.

## Why
- 2026-10-30 15:12: the NIFTY wings for 32 lots went as two iceberg slices of 1,040; the code read the parent's 1,040, took the wings as half filled and sold 16 lots against 32 lots of wings. Settle then died on a locked DB and only printed. Both were silent for three hours.
- The wing cap: with the VIX guard, the 2019–26 backtest has 0 of 530 weeks past a wing and 18 past a short; paying 37 % (NIFTY on the day) or 63 % (SENSEX week-ahead quote) of the credit insures an event the data does not show. 30 % keeps most of the credit; the step-out trades a wider worst week (Friday: ₹25.4 K → ₹41.6 K a lot) for a cheaper wing, and the skip keeps a dear chain out of the book.
- A kill switch that is only read at the start of an entry is not a kill switch.

## Consequences
- `config.OPTIONS_LIVE["wing_max_share_pct"]`, `["wing_max_pct"]`; the cap is editable on /options → Live (5–100). Plan detail shows "X % of the credit, limit Y %".
- The realised wing cost can still exceed the cap by the final aggressive BUY limit (ask × 1.25 + 4 ticks); the cap is a plan-time check. Push failures are logged, not retried.
- Tests: `tests/test_options_live.py` (75), incl. the kill-mid-entry, crash-in-loop, margin-watch, silent-day and wing-cap cases. Explainer: `docs/research/0020-option-chain-liquidity.html`.
