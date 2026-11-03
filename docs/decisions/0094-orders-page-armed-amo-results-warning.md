# ADR 0094: Orders by day, a close armed for the next login, results warning

**Date:** 2026-11-03 · **Status:** accepted · **Plan:** 0029

## Decision
1. `/options/orders` shows every order in Kite's order book by market day, AMOs and hand trades included: accepted, filled,
   rejected or cancelled (`option_kite_orders`). Days before 2026-11-03 show recorded fills only.
2. Amit arms a close on that page (short live legs only, his limit price). His next Kite login inside Zerodha's AMO window, or
   Place now, runs the `amo` step in its own process: LIMIT AMOs, then Kite's order book is read back for up to 2 minutes.
3. Marked `firing` before the first order and never retried by itself, so a crash cannot place it twice. A window that is shut or a
   failed preflight leaves it armed and alerts. `amocheck` alerts if it has not filled after the open (the 10:00 mark runs it).
4. The page warns about results of the 15 largest companies, and RBI / Fed / Budget days, in the next 7 days. Warning only.
5. Claude cannot arm or fire this (`.claude/hooks/block_live_orders.py`, the write lock in `kite_pull.kite()`).

## Why
2026-11-03: a hand limit AMO after 05:30 would have closed the call near the 60.85 open; the cron close failed and it closed at
132.75. RELI's results were on the 2026-10-30 entry day, listed in `earnings_calendar` since 10-28, unused by the live book; RELI
rose 11.6 % on 11-02, inside the hold.

## Consequences
- Untested on a real order. Unknown: whether an API AMO is accepted at 06:15, how high a limit Zerodha accepts, and whether an
  accepted AMO survives the token flush. A one-lot test decides these.
- Skipping results weeks is not supported: `docs/studies/option-tail-rules-2026-11.md` found no larger move in priced σ. The study's macro veto failed too.
- The RBI / Fed / Budget lists in `tools/option_premium_backtest.py` end 2026-10-28, so later macro dates do not show until extended.
- The page field and the login trigger need an ops cockpit restart. A 09:20 `run.sh options_live amocheck` cron line is Amit's to add.
