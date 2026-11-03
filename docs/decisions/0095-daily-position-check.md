# ADR 0095: The daily position check

**Date:** 2026-11-04 · **Status:** accepted · **Plan:** 0029

## Decision
Every open short is checked at 10:00, 15:01 and 15:45 IST, riding on the mark and record steps, and by Check now on `/options/orders`.
`options_live.position_math` is the one calculation. It reads Kite and places nothing. It reports:
1. **Where the market is:** the put-call parity forward, not the index close, and the move priced to expiry (ATM straddle / 0.8F).
2. **What it costs to close now:** asks × units, and what is left on those legs after closing.
3. **What a bad day costs:** P&L at 1, 2 and 3σ either way, and at 2.06σ against `position_limit_rs` (₹2 L, editable).
4. **Events before expiry:** `events_ahead`.
5. **The choices:** hold, close now, add wings, or arm a close for the next open, with the AMO window's state.

Verdicts: **over** if the bad-day loss exceeds the limit (urgent alert), **watch** if the nearer strike is under 1σ away, else **ok**. An alert after 15:40 summarises every day.

## It is facts, not a signal
`option-tail-rules-2026-11` found that exit rules cost income and do not reliably cut the worst week across both indices. So the check never closes anything and never says "close". It shows the price of each choice against Amit's limit, and he decides.

## Why
On 2026-11-02 the close decision came from a chat, under pressure, with some wrong numbers. Replayed on that evening's real settle prices: forward 23,329, σ 0.81 %, 23500 CE z 0.89, ₹24,544 to close, ₹15,392 kept if flat, ₹2.18 L lost on a bad day: **over** at ₹2 L. It would have shown the decision at 15:01 and 15:45, with the AMO window open.

## Consequences
- Not yet run on a live chain with a live position. Its first real run needs a Kite login.
- On days with an open short and no login, the 10:00 run alerts urgently, so a login before 10:00 is now part of holding a position.
- Bid and ask stand in for what could fill. After the close they are the last quotes.
