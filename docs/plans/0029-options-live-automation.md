# Plan 0029 — Option premium, live on Kite: automation from shadow to real money

**Status:** active — stage 0 build done 2026-10-23 on branch worktree-agent-a03ad53592e21a261 (Amit 2026-10-23: "ok build the automated framework, we are going to go live next Tuesday"). Proposed 2026-10-21 (Amit: "create a new plan for this please"). Stage 1 (shadow) may start on Amit's go; stages 2–4 place real orders and each needs his explicit approval.
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
  - [x] The `option_live_trades` table (+ `option_live_orders`, `option_live_settings`). 2026-10-23
  - [x] Settings and the kill switch on the cockpit. 2026-10-23
  - [x] Order-placement code behind a mode flag, with unit tests on a fake Kite client (fills, partial fills, rejects, re-pricing, iceberg, rotation gate). 2026-10-23
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
- 2026-10-29 **Sizing choices card** (Amit: "revamp the page to include the 4 options"): `sizing_quote` (read-only Kite: per-lot basket margin naked and with wings at `wing_pct`, or 1.75 % when off; expiry-day extra; credit at the bid, wing cost at the ask, entry charges; expected week = credit × backtest share kept (NIFTY 0.853, SENSEX 0.823) − charges; crash loss at a −13.9 % gap) runs in every mark while logged in and as step `quote`; `sizing_choices` → A naked at the caps · B naked within a 30 % crash budget · C winged at the caps · D winged at the margin limit (15 % spare), each ≤ `lots_hard_max`; Apply sets `wing_pct` + `lots_cap`. Step texts now print -₹ / +₹ (`_rs`).
- 2026-10-28 **Protective wings** (Amit: "yes please", after the −6 % calm-start analysis): setting `wing_pct` (% of spot beyond each short strike, 0 = off; 1.75 planned). `build_plan` picks the offered strike nearest that distance (`wing_strikes`) and sizes on Kite's 4-leg basket margin; `entry` BUYS the wings first (`wing_buy_s` 60 s, final aggressive limit in the last third), then sells the strangle on the lots both wings filled (no wing fill → no sale, a lone wing sold back). Long wings are never bought back or closed: the rotation gate and buy-back look at short legs only, `peak_available` credits legs leaving first unless a leaving long may hedge a short on the same index that stays, `settle` takes STT on an exercised wing's intrinsic (in `net_rs`). Kite 2026-10-28 (read-only, NIFTY 3 Nov, VIX ~16, ₹68 L assumed free): 28 lots naked (₹1.47 L + ₹0.59 L ELM a lot) → 40 with wings (₹0.85 L + ₹0.59 L; 41 without the 40 hard max), worst week ₹25.2 K a lot. Zerodha: the expiry-day 2 % ELM is charged "even if your position is hedged". Put wing alone gives no margin relief.
- 2026-10-26 **Sizing: two margin checks** (Amit: "do the code change, we need to be correct about this"): Kite takes only the entry margin when the order goes in, so lots = min(cap, ⌊(free now − buffer) ÷ entry margin⌋, ⌊(free on expiry day − buffer) ÷ (entry + expiry-day extra)⌋). Free on expiry day = free now + the margin of positions that expire first (basket margin of all open option legs − of those still open then), less their settlement at today's index and the expiry-day extra of legs that expire with ours (`peak_available`). No credit when a position is not a NIFTY/SENSEX option or an expiring leg is long. Matters when untagged NIFTY legs are still open at the Tuesday SENSEX entry.
- 2026-10-26 **Sizing covers the expiry-day margin** (Amit: "exchange also have extreme value margin on last day"): lots = what fits entry margin + `option_book.expiry_day_extra` (2 % of index × units per short leg, both legs) inside available − buffer. 15 SENSEX lots at 73,124: ₹21.3 L at entry, ≈ ₹30.1 L on expiry day. With Amit's 5 manual NIFTY lots still open at the Tue 15:17 entry (≈ ₹10.6 L with their own expiry-day add-on) about 12 lots fit, unless the 15:08 buy-back closes them (`adopt_manual_nifty`).
- 2026-10-25 **VIX guard** (Amit: "vix > 30 halt and vix >27<30 halve the position"): `options_live.india_vix` (Kite `NSE:INDIA VIX` live, else `macro_history` close ≤ `vix_max_age_days` 3, else unknown) → `vix_guard`: VIX ≥ `vix_halt` 30 or unknown = no entry (urgent push), > `vix_halve` 27 = half the lots (at least 1). Both thresholds editable on /options Settings. Insurance, not a validated rule: the option-risk-filters study (2026-10-22) found VIX ≥ 26.7 flagged both 2020 worst weeks in-sample, cost ~18 % of P&L, untested since 2023.
- 2026-10-25 Amit's size call: **15 SENSEX lots from Tue 2026-10-27** (skips stage 3's 1–2 lots and the D1 25-paper-trade gate; 4 settled). Margin ~₹21 L at entry (~₹1.42 L/lot, Fri quote), ~₹26 L on Thursday's expiry day, of ₹37 L cash after his ₹10 L pay-in; backtest-worst SENSEX trade (−7.6 % of margin) ≈ −₹1.6 L. /options Live panel now shows Kite margin used / free / total (`snapshot_margin` at mark + record).
- 2026-10-23 stage 0 built (`options_live.py`, one module, plain functions; tests `tests/test_options_live.py`, 32 on a fake Kite):
  - **Steps:** `run.sh options_live <step> [NIFTY|SENSEX]`, one `pipeline_log` name per step (`cron_options_live_entry_nifty`, `…_entry_sensex`, `…_buyback`, `…_closeall`, `…_record`, `…_mark`, `…_settle`, `…_reconcile`, `…_precheck`, `…_weekly`), a per-step `flock`, no harvest lock. `python -m options_live plan -u NIFTY` prints what `entry` would trade now, read-only.
  - **Modes and settings:** `config.OPTIONS_LIVE` holds the defaults (mode `shadow`, caps 1 + 1, buffer ₹50,000, weekly loss limit ₹2 L, tag `as0029`, all IST times); a row in `option_live_settings` overrides a key (cockpit or `python -m options_live set <key> <json>`). Real orders only in `approve` / `auto`.
  - **Strikes:** `sources/kite_quotes.py` was split into `live_chain` / `pick` / `touch`, shared by the 15:20 snapshot and this job; `pick` is `option_book.slice_deltas` + `nearest` on the live mids. Chain band ±8% of spot.
  - **Sizing:** `lots = min(cap, floor((Kite net margin − buffer) / Kite basket margin per lot))`, re-checked at size with a second basket query (steps down while it does not fit). Shadow records at least 1 lot and says "margin short" when a live mode would have skipped.
  - **Orders** (deviation from "re-price toward the mid"): a SELL goes at the **bid** and is re-pegged to the live bid every 20 s, never below half its first mid; a BUY at the ask, never above 3× its first ask until the final aggressive limit (ask × 1.25 + 4 ticks). Resting at the mid risks no fill by 15:29 on a far-OTM strike; the backtest already pays 1% slippage. Leftovers cancelled at the cut-off; a lone filled leg is bought back at once, else a push asks for a manual close.
  - **Iceberg:** above the freeze quantity (Kite instruments carry none, checked 2026-10-23, so config `freeze_qty` NIFTY 1,800 / SENSEX 1,000 units — confirm both before stage 4) an order goes as `variety=iceberg`, 2–10 legs, each a whole number of lots. Not reached at 1–2 lots; iceberg fill tracking is proven on the fake only.
  - **Ledger:** `option_live_orders` is the append-only event log (proposed, ticket, approved, expired, place, modify, cancel, status / partial, reject, error, fill, shadow_fill, seed); `option_live_trades` (one row per leg × source `shadow` / `live` / `manual`) is rebuilt from the fills. An order's own summary fill (`order:<id>`) stands until `record` reads its real Kite trades. `record` also adopts Amit's manual NIFTY/SENSEX option positions (source `manual`), but never absorbs a difference on a contract the system holds: that is `reconcile`'s mismatch.
  - **Costs:** `option_book.charges_pts` factored out of `leg_cost` (bit-identical on 100k random cases); live P&L = fills − charges (brokerage per order, exchange + GST, STT on sells, stamp on buys); settlement = `option_book.intrinsic` on the fno_bhav expiry-day index, as in the paper book.
  - **Shadow** touches only shadow legs (buy-back included) and never reaches a broker write: `call()` refuses place / modify / cancel outside the order loop. Only Close-all, pressed by hand, closes real tagged legs in any mode.
  - **Rotation gate:** SENSEX enters only when no NIFTY leg of the trading family expiring today is open and the buy-back's `rotation:<date>` state (flat in positions + margin freed ≥ 50% of the NIFTY entry margin) is not a failure; no NIFTY position = pass.
  - **Health:** `OPTIONS_LIVE` (checks/custom.py, catalog 29 of 30): broker ≠ ledger CRITICAL; a step failed in the last 3 days and not since recovered WARN in shadow, CRITICAL in approve / auto. Step failures also show as `PIPELINE_STEP` (WARN; not on the picks path).
  - **Cockpit:** `/options#live` panel above the paper book. Controls are POSTs needing the session cookie and a confirm word (typed for Close all and for mode auto); Resume is refused while the last reconcile is a mismatch.
  - **Smoke 2026-10-23 13:50 IST** on the real session, read-only (`plan`): NIFTY 27-Oct 23300 CE (Δ 0.046) + 21900 PE (Δ 0.054), ₹1,55,474 a lot; SENSEX 29-Oct 75900 CE + 70100 PE, ₹1,41,982 a lot; available ₹16.98 L. Account profile lists NFO + BFO, NRML, LIMIT. No order was placed during the build.
  - **Not done / open:** no real order has been placed by this code (approve / auto are proven on the fake only — the first real order is the first test of Kite's order permission, `tag`, modify and iceberg behaviour); `record` / `reconcile` / live `mark` need that day's Kite login (Amit logs in only on trading days); the 15:20 `kite_quotes` snapshot stays separate (§8); no daily-email line yet (push + page are the surfaces).

## Runbook

**Before Tuesday 2026-10-27 (once):**
1. Merge the branch. The tables appear on the first `options_live` step (or `python -c "import db; db.init_db()"`).
2. Kite order permission: the developers.kite.trade app must be a Connect app that may place orders (not a read-only one), and the account needs F&O on NFO and BFO (the profile lists both). Static IP: registered. The first real order is the real test: make it in `approve` mode at 1 lot.
3. `NTFY_TOPIC` in `~/.config/alpha-signal/secrets.env` and the ntfy phone app subscribed, or the pushes go nowhere (the panel still shows everything).
4. Add the crontab lines below (`crontab -e`), then copy the v2 lines into `ops/crontab.txt` (`tests/test_ops_files.py` compares them).

**Crontab (server UTC = IST − 5:30).** Entry and buy-back lines run every weekday and do nothing unless today is that underlying's entry day (2 sessions before its expiry, NSE holiday list) or a NIFTY expiry with open legs, so a holiday-shifted week needs no edit.
```
15 9 * * 1-5  /home/ubuntu/alpha-signal-v2/run.sh options_live precheck >> /home/ubuntu/alpha-signal-v2/output/options_live.log 2>&1        # 14:45 IST login reminder
30 9 * * 1-5  /home/ubuntu/alpha-signal-v2/run.sh options_live precheck >> /home/ubuntu/alpha-signal-v2/output/options_live.log 2>&1        # 15:00 IST second reminder
38 9 * * 1-5  /home/ubuntu/alpha-signal-v2/run.sh options_live buyback NIFTY >> /home/ubuntu/alpha-signal-v2/output/options_live.log 2>&1   # 15:08 IST (Tue)
42 9 * * 1-5  /home/ubuntu/alpha-signal-v2/run.sh options_live entry NIFTY >> /home/ubuntu/alpha-signal-v2/output/options_live.log 2>&1     # 15:12 IST (Fri)
47 9 * * 1-5  /home/ubuntu/alpha-signal-v2/run.sh options_live entry SENSEX >> /home/ubuntu/alpha-signal-v2/output/options_live.log 2>&1    # 15:17 IST (Tue)
15 10 * * 1-5 /home/ubuntu/alpha-signal-v2/run.sh options_live record >> /home/ubuntu/alpha-signal-v2/output/options_live.log 2>&1          # 15:45 IST
20 10 * * 1-5 /home/ubuntu/alpha-signal-v2/run.sh options_live reconcile >> /home/ubuntu/alpha-signal-v2/output/options_live.log 2>&1       # 15:50 IST
30 4 * * 1-5  /home/ubuntu/alpha-signal-v2/run.sh options_live mark >> /home/ubuntu/alpha-signal-v2/output/options_live.log 2>&1            # 10:00 IST (expiry-day margin)
30 9 * * 1-5  /home/ubuntu/alpha-signal-v2/run.sh options_live mark >> /home/ubuntu/alpha-signal-v2/output/options_live.log 2>&1            # 15:00 IST
0 6 * * 1-5   /home/ubuntu/alpha-signal-v2/run.sh options_live settle >> /home/ubuntu/alpha-signal-v2/output/options_live.log 2>&1          # 11:30 IST, after the morning fno_bhav load (~05:33 UTC)
10 6 * * 5    /home/ubuntu/alpha-signal-v2/run.sh options_live weekly >> /home/ubuntu/alpha-signal-v2/output/options_live.log 2>&1          # Fri 11:40 IST, after Thursday's SENSEX settles
```
In mode `shadow` (the default) every line is safe: nothing reaches the broker.

**Each trading day (Fri and Tue):** log in at `/kite/login` on the ops cockpit before 15:05 IST. Without it the 14:45 / 15:00 push says "log in to Kite", the entry fails (red step + push), and on Tuesday the buy-back cannot run: NIFTY then expires normally and SENSEX is skipped.

**Modes:** `/options#live` → Settings → Mode: `shadow` → `approve` (stage 2) → `auto` (stages 3–4; typing AUTO is required). Caps: Settings → NIFTY / SENSEX lots (hard maximum 40).

**Approve (mode approve):** at 15:12 (NIFTY) / 15:17 (SENSEX) a push "Approve NIFTY …: sell … × N lot(s)" links to `/options#live`. Tap **Approve** before **15:25 IST**; the waiting job places the orders within 10 s and works them until 15:29. Not approved by 15:25 = "ticket expired unapproved — nothing was placed".

**Stop:** **Stop** = no new entries; buy-backs and Close-all still run. **Resume** undoes it (refused while the last reconcile is a mismatch). The job stops itself on the weekly loss limit and on a reconcile mismatch.

**Close all** (type CLOSE ALL): Stop + buy back every open tagged leg now, limit at the ask, re-priced for 4 minutes, then the final aggressive limit for the last minute. Log: `output/options_live_closeall.log`; a push reports done / still open. Amit's own (untagged) legs are never touched.

**Broker ≠ ledger:** fix the position in Kite (or have a session fix the ledger), run `run.sh options_live reconcile`, then Resume.

**What each push means** (prefix `Options SHADOW:` / `APPROVE:` / `LIVE:`):

| Push | Meaning | Do |
|---|---|---|
| "log in to Kite before 15:05 IST — today has the …" | precheck: work due, no session | log in at `/kite/login` |
| "log in to Kite: … entry … is skipped" / "… buy-back has not run" | the step found no session | log in, re-run the step (`run.sh options_live entry NIFTY`) before the cut-off |
| "Approve NIFTY …" | a ticket is waiting | Approve before 15:25 |
| "NIFTY … sold: … = ₹X credit, margin ₹Y" | entry filled (shadow: simulated at the bid) | nothing |
| "entry unbalanced …" / "… still open without the other leg" | one leg filled; the excess was bought back, or could not be | close by hand in Kite, or keep to expiry |
| "nothing filled by 15:29" | orders cancelled, no position | nothing (no retry after 15:29) |
| "NIFTY buy-back done … SENSEX can enter" | rotation OK | nothing |
| "buy-back incomplete … SENSEX entry will be skipped" | NIFTY still open or margin not freed | nothing: NIFTY expires normally |
| "SENSEX entry skipped — rotation gate failed" | NIFTY not flat / margin not freed | nothing |
| "not enough margin" | available − buffer < one lot | add collateral or lower the buffer |
| "this week's realised loss … is over the limit" | D4 limit hit; entries paused | review, then Resume |
| "Kite positions do not match the ledger" | reconcile mismatch; entries stopped | see Broker ≠ ledger |
| "… settled at …" / "weekly P&L — …" | settlement / Friday summary | nothing |
