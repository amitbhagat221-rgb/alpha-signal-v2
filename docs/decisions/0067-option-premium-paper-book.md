# ADR 0067 — Option premium: a forward paper book on one rule, shared code with the backtest, manual Kite logins

**Status:** proposed 2026-10-10 (plan 0022, approved "sure"). Evidence: [option-premium-feasibility-2026-10](../studies/option-premium-feasibility-2026-10.md).

## Decision

1. **One rule, forward-tested on paper before any money.** Sell a 0.05-delta strangle on NIFTY and SENSEX at the close 2 trading sessions before the weekly expiry, held to expiry, 1 lot each. It is fixed for the test.
   - The pass bar (plan 0022 §3) is read after 25 settled trades: mean > 0, no trade worse than the backtest's worst, median live slippage ≤ 1%.
   - The rule was picked from a 32-cell grid after the data was seen, which is why only new days can test it.
2. **No agent veto in the rule.** The pre-registered event veto (Budget, elections, RBI, FOMC) and the VIX > 25 veto both failed: event trades did better, and the VIX veto had no same-direction effect out of sample. The agent's role is operator (prepare, check, ask), not selector.
3. **One implementation.** `option_book.py` holds the strike picker, the costs and the lot sizes. `tools/option_premium_backtest.py` imports them; a re-run gave an identical grid.
4. **BSE beside NSE in `fno_bhav`.** SENSEX/BANKEX rows from BSE's UDiFF file use the same columns and units: volume in lots, OI in units, and on expiry day `settle` = index settlement. SENSEX does not exist on NSE, so `symbol` keeps the rows apart. The legacy NSE F&O archive (2019-01 → 2024-07-12) was loaded for index underlyings only; stock options were left out (~30M rows, disk at 80%).
5. **Kite logins are manual.** The daily session comes from Amit's one-tap login (`/kite/login` on the ops cockpit → `/kite/callback`). Scheduled jobs run `kite(cached_only=True)` and fail loudly without it. No password or TOTP seed is stored: Zerodha does not allow automated logins for trading, and the login doubles as the daily permission. Every order passes the registered static IP 140.245.248.166.

## Why

- **The candidate the morning model chose failed.** On 2019–2024 real prices, the 1-session-before version reached Sharpe 0.6 and lost 28–39% of margin on 2020-03-11.
- **The 2-session 0.05-delta version held up** on three separate samples:
  - NIFTY 2019–2026: Sharpe 2.9, t 7.9, positive every year;
  - SENSEX 2024–2026: Sharpe 3.7;
  - March 2020 was a near miss, by 90 points.
- **Kite's measured strangle margin (11.8% / 10.7% of notional) confirms the 12% assumption**, so returns on margin stand.
- **One code path** keeps the forward record and the backtest from drifting (the same principle as ADR 0052 for factors).
