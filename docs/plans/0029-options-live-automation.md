# Plan 0029 — Option premium, live on Kite: automation from shadow to real money

**Status:** proposed 2026-10-21 (Amit: "create a new plan for this please"). Stage 1 (shadow) may start on Amit's go; stages 2–4 place real orders and each needs his explicit approval.
**Why:** plan 0022's paper book trades the rule at one lot and end-of-day prices. Running it with ₹35 L means two trades a week at minute-level times (Friday and Tuesday entries, a Tuesday 15:10 buy-back), which nobody should do by hand, and a sizing / collateral / tail-risk setup decided in advance rather than in the moment.

## 1. The trade (unchanged from plan 0022, plus the rotation)

| | |
|---|---|
| Rule | Plan 0022: short strangle, ~0.05-delta call + put, entered at the close 2 sessions before expiry, **no stop-loss, no wings**, held to expiry |
| Underlyings | NIFTY (expires Tue, enter Fri ~15:15–15:29) · SENSEX (expires Thu, enter Tue ~15:17–15:29) |
| **Rotation (new)** | NIFTY is **bought back Tue 15:08–15:15**, freeing its margin for the SENSEX entry, so one pot of margin carries both at full size |
| Code | `option_book` picks strikes and costs — one implementation for backtest, paper book and live |

Evidence:
- [stops / wings study](../studies/option-stops-wings-2026-10.md): all 7 pre-registered variants DROP; no stop level holds out of sample. The rule stays naked.
- Rotation cost, measured 2026-10-21 on 257 NIFTY expiries (minute data): buying back at 15:10–15:15 costs a median of ₹0.31 a unit (mean ₹0.54) more than holding to expiry, ~₹0.35 L a year at 20 lots.
- Rough ₹35 L figures (2021–26 minute data, today's lots and margins, before interest and tax): NIFTY alone ~₹6.45 L/yr; rotated NIFTY + SENSEX ~₹12.6 L/yr (2024–26 only); worst month about −₹1.3 L; max drawdown about −₹2.4 L. The window has no crash. The 2019–26 daily test, which includes March 2020, had a worst trade of −8.9 % of margin.

## 2. Decisions for Amit

- **D1 Go-live gate.** Real orders (stage 2+) only after plan 0022's pass bar (25 settled paper trades) **and** a clean shadow stage. Proposed: yes.
- **D2 Size.** Lots per index and a margin cap. Proposed start: 1–2 lots (stage 3), then 18 NIFTY + 19 SENSEX (stage 4). The 18 leaves room for the expiry-day margin add-on.
- **D3 Collateral.** Margin ₹35 L needs ~₹17.5 L cash-like (~₹19.5 L of liquid fund or liquid ETF after the haircut), ~₹23 L of pledged shares, and ~₹2 L cash for losses. Options:
  - (a) move ~₹15 L into a liquid fund;
  - (b) keep the shares and pay the shortfall interest (~₹1–1.5 L a year, to confirm);
  - (c) deploy less (₹9 L runs on today's ₹5 L of liquid fund).
- **D4 Weekly loss limit.** New entries pause after a week's realised loss above it. Proposed: ₹2 L.
- **D5 Crash tolerance.** The amount one gap week may cost; it sets the lot cap. A 20-lot book lost ~₹3 L in the 2020 crash on daily data, and a larger gap is possible.

## 3. Components

```
cron (IST times)  →  run.sh options_live <step>          step = entry | buyback | settle | watch
                       ├─ guards: kill switch · Kite session · caps · weekly loss · no duplicate
                       ├─ option_book: live chain → 0.05-delta strikes, costs
                       ├─ Kite Connect: margins API, place/modify/cancel orders (tagged), positions, order book
                       ├─ DB: option_live_trades (schema.sql + tables.TABLES), run_events
                       └─ notify: ntfy push + ops cockpit /options (live panel, Stop / Close-all buttons, settings)
health_report: step failed · broker positions ≠ ledger · retired/disabled step ran · loss limit hit
```

- **Settings** (cockpit, stored in the DB): mode (off / shadow / approve / auto), lots per index, margin cap, weekly loss limit, margin buffer.
- **Orders:**
  - Each leg is a limit order, re-priced every ~20 s toward the mid. At 15:14 the buy-back gets a final aggressive limit. No market orders.
  - Above the exchange freeze limit (NIFTY 1,800 units today; read from instrument data), the order goes as an iceberg, and every slice must fill.
  - Every order carries our tag. The job never touches untagged positions or holdings.
- **Rotation gate:** SENSEX enters only if the NIFTY legs are flat and the margins API shows the margin freed.

## 4. Stages

- [ ] **0 Prerequisites (Amit + build).**
  - Kite Connect app order permission.
  - Static-IP registration if Zerodha requires it for API orders (SEBI 2025 retail-algo rules; confirm).
  - Collateral per D3.
  - The `option_live_trades` table.
  - Settings and the kill switch on the cockpit.
  - Order-placement code behind a mode flag, with unit tests on a fake Kite client (fills, partial fills, rejects, re-pricing, iceberg, rotation gate).
- [ ] **1 Shadow (2–3 weeks; no orders; starts on Amit's go).** The full weekly flow on the live chain. Orders are simulated at the live bid/ask, recorded and pushed marked "shadow". It must show:
  1. every step on time;
  2. the rotation gate working;
  3. the real expiry-day margin on Tuesday morning;
  4. simulated fills within the backtest's slippage;
  5. the ledger matching what the broker reported.
- [ ] **2 Approve.** The job prepares the orders and pushes a link. Orders are sent only if Amit taps Approve before the cut-off. Small size.
- [ ] **3 Auto, 1–2 lots per index, ≥ 4 weeks.** No manual fixes needed; reconciliation clean every day.
- [ ] **4 Auto at the D2 size.** Step up in two moves: half size, then full.

## 5. Failure handling (each one tested in stage 0 and drilled in shadow)

| Case | Behaviour |
|---|---|
| No Kite login | No orders. Alerts at 14:45 and 15:10. On Tuesday NIFTY expires and settles normally; SENSEX is skipped |
| Leg unfilled by 15:29 | Cancel. If one leg filled alone, close it if possible, else alert for a manual close |
| Buy-back incomplete or margin not freed | SENSEX skipped; NIFTY expires normally |
| Kite / API / network down | Logged; alert; no retry after 15:29 |
| Weekly loss limit hit | Entries pause until re-enabled on the cockpit |
| Crash or re-run | Order book and tags checked first: never a double entry |
| Broker ≠ ledger | Red health check, alert, trading paused until reconciled |
| Amit: Stop / Close-all | No new entries / buy back all tagged legs now |

## 6. Done when

Stage 4 has run 8 weeks at full size, with:
- no manual intervention;
- daily reconciliation clean;
- realised fills within the backtest's cost assumptions;
- P&L reported weekly on the cockpit and in the health email.

## 7. Considered and rejected

- **Stop-losses** (premium 1.5–10×, index-distance): they lose to gaps and whipsaw out of sample.
- **Wings / iron condor:** they cost 19–31 % of the credit and never paid out in 2021–26; kept only as a possible crash-insurance choice for D5.
- **Splitting ₹35 L into two halves:** half the profit for the same work; the rotation is cheaper.
- **Market orders:** restricted on options and unsafe on far-OTM strikes.
- **Automating the 2FA login:** not allowed; Amit logs in on Fri and Tue.

## 8. Open questions

- The expiry-day extra margin on Tuesday morning: measured in shadow week 1.
- Zerodha's cash-shortfall interest rate and how it is counted.
- Static-IP / algo-ID requirements for retail API orders.
- Whether `kite_quotes`' 15:20 snapshot moves into this job.

## Implementation notes
