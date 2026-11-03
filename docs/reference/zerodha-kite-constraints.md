# Zerodha / Kite Connect: the rules every live action checks

Catalogued 2026-11-03 after the expiry-day failure (a 06:19 IST login was flushed by Zerodha before the 09:16 close;
week −₹1.28 L, ≈ ₹55 K of it the delay). Sources: Kite Connect docs, Zerodha support, the Kite developer forum
(staff answers marked *staff*). Every rule names the control that enforces it. A new live action (step, cron
line, AMO path) is checked against every row before it is scheduled; `tests/test_kite_constraints.py` keeps this
file and `options_live.preflight` in step.

## 1. Sessions (the 2026-11-03 failure)

| Rule | Source | Control |
|---|---|---|
| Zerodha flushes every API session each morning. Docs say 6 AM; *staff*: "around 7:30 AM"; users see 06:00–07:30; *staff* advise taking the day's token **at or after 08:30 IST**. | [docs: user](https://kite.trade/docs/connect/v3/user/), [forum 4108](https://kite.trade/forum/discussion/4108/exact-time-of-my-access-token-expiry), [forum 7759](https://kite.trade/forum/discussion/7759/access-token-validity) | `kite_pull.SAFE_LOGIN_IST`; `login_info()["early"]`; the login page shows `kite=early`; precheck pushes "log in AGAIN after 08:30" |
| A cached token is NOT a session until Kite confirms it (a flushed token still looks valid locally). | this incident | `kite()` calls `profile()` on every cached token; a `TokenException` deletes the cache and raises `NoKiteSession` |
| A new `generate_session` on the same api_key invalidates the previous token. One app, one session. | [Zerodha FAQ](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs) | only the cockpit login mints a token; cron never logs in (`cached_only=True`) |
| A master logout from Kite web (and, per users, a fresh browser login) can end the API session. | docs: user; forum | precheck re-proves the session before each action window; preflight proves it again before orders |
| The exchange requires one manual login a day; automating login is discouraged by *staff*. | [forum 7773](https://kite.trade/forum/discussion/7773/kite-api-session-timeout-everyday) | the cockpit one-tap login; no TOTP automation on cron |
| Margins / RMS endpoints fail at night (`GetRmsLimitsResponse Fail`, 02:16 IST 2026-11-03). Nothing that reads margin runs between 00:00 and 08:30 IST. | this incident | the quote step is daytime cron only; preflight reads margin before orders |

## 2. Orders

| Rule | Source | Control |
|---|---|---|
| Rate limits: 10 orders/s, 400/min, 5,000/day per **account** (not per app); 25 modifications per order; quotes 1/s; other endpoints 10/s; 429 on breach. | [docs: exceptions](https://kite.trade/docs/connect/v3/exceptions/) | `_http.pace("kite")` ≥ 2 s between calls; `work_orders` re-prices every `reprice_every_s` ≥ 20 s (≤ 15 modifications a leg) |
| Freeze quantity per order (NIFTY 1,800 units in 2026): bigger orders are icebergs; each slice is its own exchange order with a child id. | NSE; 2026-10-30 incident | `slices()`, `_members` read every child; `freeze_qty` setting |
| Market orders are rejected on illiquid index/stock options; orders outside the execution range around the theoretical price are rejected ("place it around the theoretical price"); GTTs triggering outside the range are rejected too. | [support: theoretical price](https://support.zerodha.com/category/trading-and-markets/trading-faqs/f-otrading/articles/order-rejected-saying-place-around-the-theoretical-price), [Z-Connect: execution range](https://zerodha.com/z-connect/general/deciphering-nses-execution-range-circular) | every live order is LIMIT at the touch, re-priced; never a market order; a "final aggressive limit" stays near the touch |
| Some NIFTY / BANKNIFTY strikes are blocked for NRML (overnight) on market-wide OI limits; MIS allows all strikes. | [support: strike restrictions](https://support.zerodha.com/category/trading-and-markets/trading-faqs/f-otrading/articles/why-did-my-bank-nifty-option-order-get-rejected) | a rejected leg is recorded and the lone leg bought back (`test_a_rejected_leg_…`) |
| Stock options: no fresh OTM longs in the last two days before expiry (physical settlement). Index options are cash-settled. | [support](https://support.zerodha.com/category/trading-and-markets/trading-faqs/f-otrading/articles/why-am-i-unable-to-buy-stock-options-close-to-the-expiry) | the book trades index options only |

## 3. After-market orders (the path that would have survived the flush)

| Rule | Source | Control |
|---|---|---|
| F&O AMOs can be placed, modified and cancelled **15:45 → 09:11 IST** (current-month futures to 08:58). Blocked 09:10–15:45. | [support: AMO timings](https://support.zerodha.com/category/trading-and-markets/kite-web-and-mobile/articles/what-is-amo-and-when-can-we-place-it), [support: rejections](https://support.zerodha.com/category/trading-and-markets/alerts-and-nudges/kite-error-messages/articles/kite-order-rejections) | place-at-open path (planned): AMO placed the evening before or at the morning login |
| **Market-type AMOs on index options are rejected** (impact cost); use LIMIT. This is what Kite refused on 2026-11-03 at 01:30 when the order was switched to Market. | [support: index option AMO rejection](https://support.zerodha.com/category/trading-and-markets/charts-and-orders/order/articles/index-options-amo-rejection) | place-at-open uses LIMIT at a price that fills at any realistic open |
| API: `variety="amo"` (lower case); not for iceberg or cover orders; a pending AMO may still show variety `amo` after the exchange takes it, so cancel with `regular` if `amo` times out. | [forum 10912](https://kite.trade/forum/discussion/10912/not-able-to-place-amo-orders-using-kite-api), [forum 11742](https://kite.trade/forum/discussion/11742/error-in-cancelling-amo-orders) | place-at-open path; the order book is read back after placing |
| An accepted order lives on Zerodha's side: a later token flush cannot touch it. | docs | the reason the place-at-open path exists |

## 4. Alerts (the ping that never arrived)

| Rule | Source | Control |
|---|---|---|
| ntfy priority 5 ("urgent") is the loudest ntfy level; the server held the 09:16 message at priority 5, the phone never showed it. Android kills the ntfy background service under battery optimisation / doze; the fix is battery "unrestricted" + connection mode WebSocket + instant delivery. | [ntfy #1709](https://github.com/binwiederhier/ntfy/issues/1709), [#855](https://github.com/binwiederhier/ntfy/issues/855), [#1834](https://github.com/binwiederhier/ntfy/issues/1834) | Amit's phone settings (one-time); `send_ntfy` adds a loud tag and repeats an urgent push |
| A phone call needs a paid channel: ntfy Pro `X-Call` (Twilio-backed, verified number) or a self-hosted ntfy with a Twilio account. | [ntfy: publish](https://docs.ntfy.sh/publish/), [ntfy: config](https://docs.ntfy.sh/config/) | `ALERT_CALL_URL` in secrets.env (any GET webhook that rings the phone) is hit on every urgent push |

## 5. Before any new live action

1. Which session does it need, and at what time? If before 08:30 IST, it cannot rely on a login: it must be an AMO placed while a session is valid, or it waits.
2. Does the step prove the session, read margin, quote every leg and compare Kite with the ledger **before** the first order (`preflight`)? Which push does the user get if any of that fails, and how early?
3. Is every order a LIMIT inside the execution range, below the freeze quantity, within the rate limits?
4. Which one-shot setting or state does it consume, and is it consumed only after the action that needed it succeeded?
5. Has it run end to end on the fake broker (`tests/test_options_live.py`) and, where possible, in shadow on a real day?
