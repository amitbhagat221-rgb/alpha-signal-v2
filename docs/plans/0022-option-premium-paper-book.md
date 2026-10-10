# Plan 0022 — Option-premium paper book (forward test before any money)

**Status:** approved 2026-10-10 (Amit: "sure"). Phases 1 + 2 BUILT 2026-10-10; first paper trade NIFTY 2026-10-13 expiry (entered 2026-10-09 close). Recording forward.
**Why:** the feasibility study ([option-premium-feasibility-2026-10](../studies/option-premium-feasibility-2026-10.md)) found one rule that holds up on 2019–2026 real prices. It was picked from a grid after seeing the data, so its only honest test is days it has never seen.

## 1. The rule (pre-registered 2026-10-10, before the first forward trade)

Fixed for the whole test. Do not change it on what the record shows.

| | |
|---|---|
| Underlyings | NIFTY (NSE weekly, Tuesday) · SENSEX (BSE weekly, Thursday) |
| Structure | short strangle: sell one call + one put, no wings |
| Strikes | the out-of-the-money call and put whose Black-76 delta is nearest 0.05, among strikes that traded that day |
| Entry | at the close, **2 trading sessions before the expiry** (NSE F&O holiday list decides the sessions) |
| Exit | none: held to expiry, cash-settled at intrinsic value on the index settlement |
| Size | 1 lot each (NIFTY 65, SENSEX 20) |
| Costs | the backtest's: ₹20/order + GST, exchange charge, STT on the sell side, stamp, slippage max(0.05, 1% of price) per leg |
| Margin | Kite's basket margin where the live snapshot has it; else 12% of notional (Kite measured 11.8% / 10.7% on 2026-10-10) |

Code: `option_book.py` (shared with `tools/option_premium_backtest.py`, so the paper record and the backtest run one implementation).

## 2. Phases

1. **Paper record (end of day).** `option_book.py --record` in the morning run:
   - writes the trade for every entry day whose close is loaded;
   - settles every trade whose expiry is loaded, into `option_paper_trades`.
   - Page `/options` on the ops cockpit (HTTPS, phone).
2. **Live-quote shadow.** `sources/kite_quotes.py` at 15:20 IST (09:50 UTC) on entry days:
   - picks the strikes from live Kite quotes and records bid/ask/last and Kite's basket margin into `option_live_quotes`;
   - compares live bid with the settle the paper record uses: **that difference is the real slippage**;
   - needs Amit's one-tap Kite login that day (`/kite/login` on the ops cockpit).
3. **Live, 1 lot, with approval.**
   - The agent prepares the ticket and checks margin and data. Amit taps approve, then the order is placed.
   - Hard limits in code: an allow-list of NIFTY/SENSEX options only, max lots, a loss stop, a kill switch, a morning reconcile with Kite.
   - Not started until Phase 1 + 2 pass.
4. **Automatic within the limits.** Only after Phase 3 has a clean record.

## 3. Pass bar for Phases 1–2 (fixed now)

After **≥25 settled trades** (about 3 months, NIFTY + SENSEX together), all of these must hold:
- the mean net return per trade on margin is > 0;
- no single trade loses more than the backtest's worst (NIFTY −8.9%, SENSEX −7.6% of margin);
- the median live-quote slippage (settle − bid, as a share of the premium) is ≤ the 1% the backtest assumes. If it's higher, re-run the backtest at the measured slippage before Phase 3.

A miss on any one means stop and review, not tune.

## 4. Done when

Phase 1 + 2 have run 25 trades and the pass bar is read in a memo. Then Amit decides on Phase 3.

## Implementation notes
- 2026-10-10: NSE holiday list fetched from NSE `holiday-master` (Equity Derivatives) into `market_holidays`. BSE follows the same exchange-holiday calendar for index derivatives.
- 2026-10-10 built:
  - **Paper record:** `option_book.py` (also the backtest's core, so the two can't drift; grid re-run identical).
  - **Feeds:** `sources/nse_holidays.py` → `market_holidays`; `sources/kite_quotes.py` → `option_live_quotes` (feeds `nse_holidays`, `kite_option_quotes` on probation). `bse_fo_bhav` promoted to probation and fetched daily in `run.sh morning`.
  - **Schedules:** `run.sh morning` runs `cron_bse_fo` → `cron_nse_holidays` → `cron_option_book`; `run.sh kite_quotes` runs at 09:50 UTC on weekdays (crontab + ops/crontab.txt).
  - **Ops cockpit:** `/options` page, `/kite/login` → `/kite/callback`, which caches the session for the 15:20 job.
  - **Kite:** the app's redirect URL must be `https://alpha.rendezvous-app.duckdns.org/kite/callback`. Secrets come from `~/.config/alpha-signal/secrets.env` (`kite_pull._env` falls back to the file for the cockpit service).
  - **Dry run** on 2026-10-09 quotes picked the same strikes as the paper record. Kite basket margin: NIFTY ₹1,72,308, SENSEX ₹1,55,415.
  - **Not done:** the daily-email line (the page is the surface for now).
