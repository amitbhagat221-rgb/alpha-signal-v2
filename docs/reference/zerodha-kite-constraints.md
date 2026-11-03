# Zerodha / Kite Connect: the rules every live action checks

Catalogued 2026-11-03 after the expiry-day failure (a 06:19 IST login was flushed by Zerodha before the 09:16 close;
week −₹1.28 L, ≈ ₹55 K of it the delay). Sources: Kite Connect docs, Zerodha support, the Kite developer forum
(staff answers marked *staff*). Every rule names the control that enforces it. A new live action (step, cron
line, AMO path) is checked against every row before it is scheduled; `tests/test_kite_constraints.py` only checks that key names and values appear;
it does not prove each control works.

## 1. Sessions (the 2026-11-03 failure)

| Rule | Source | Control |
|---|---|---|
| Zerodha flushes every API session each morning. Docs say 6 AM; *staff*: "around 7:30 AM"; users see 06:00–07:30; *staff* advise taking the day's token **at or after 08:30 IST**. | [docs: user](https://kite.trade/docs/connect/v3/user/), [forum 4108](https://kite.trade/forum/discussion/4108/exact-time-of-my-access-token-expiry), [forum 7759](https://kite.trade/forum/discussion/7759/access-token-validity) | `kite_pull.SAFE_LOGIN_IST`; `login_info()["early"]`; the login page shows `kite=early`; precheck pushes "log in AGAIN after 08:30" |
| A cached token is NOT a session until Kite confirms it (a flushed token still looks valid locally). | this incident | `kite()` calls `profile()` on every cached token; a `TokenException` deletes the cache and raises `NoKiteSession` |
| A new `generate_session` on the same api_key invalidates the previous token. One app, one session. | [Zerodha FAQ](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs) | only the cockpit login mints a token; cron never logs in (`cached_only=True`) |
| A master logout from Kite web (and, per users, a fresh browser login) can end the API session. | docs: user; forum | precheck re-proves the session before each action window; preflight proves it again before orders |
| The exchange requires one manual login a day; automating login is discouraged by *staff*. | [forum 7773](https://kite.trade/forum/discussion/7773/kite-api-session-timeout-everyday) | the cockpit one-tap login; no TOTP automation on cron |
| **Forum only, cause not confirmed:** `Get Rms Limits Entity Response ... Request not registered` is attributed to the beginning-of-day process. No official page found. Exact string `GetRmsLimitsResponse` not found on any source. Our logs: 01:59 IST 2026-10-30 and 02:16 IST 2026-11-03; the app still showed margin at 01:23 IST on 11-03. | [forum 4247, 2018](https://kite.trade/forum/discussion/4247/get-rms-limits-entity-response-request-not-registered), [Trading Q&A, 2020](https://tradingqna.com/t/error-in-kite-mobile-app/83195) | preflight reads margin before orders; nothing stops a night-time quote step |

## 2. Orders

| Rule | Source | Control |
|---|---|---|
| Rate limits: 10 orders/s, 400/min, 5,000/day per **account** (not per app); 25 modifications per order; quotes 1/s; other endpoints 10/s; 429 on breach. | [docs: exceptions](https://kite.trade/docs/connect/v3/exceptions/) | `_http.pace("kite")` ≥ 2 s between calls; `work_orders` re-prices every `reprice_every_s` ≥ 20 s (≤ 15 modifications a leg) |
| Freeze quantity per order (NIFTY 1,800 units in 2026): bigger orders are icebergs; each slice is its own exchange order with a child id. | config.py, not re-checked against NSE; 2026-10-30 incident | `slices()`, `_members` read every child; `freeze_qty` setting |
| Market orders are rejected on illiquid index/stock options; orders outside the execution range around the theoretical price are rejected ("place it around the theoretical price"); GTTs triggering outside the range are rejected too. | [support: theoretical price](https://support.zerodha.com/category/trading-and-markets/trading-faqs/f-otrading/articles/order-rejected-saying-place-around-the-theoretical-price), [Z-Connect: execution range](https://zerodha.com/z-connect/general/deciphering-nses-execution-range-circular) | every live order is LIMIT at the touch, re-priced; never a market order; a "final aggressive limit" stays near the touch |
| Some NIFTY / BANKNIFTY strikes are blocked for NRML (overnight) on market-wide OI limits; MIS allows all strikes. | [support: strike restrictions](https://support.zerodha.com/category/trading-and-markets/trading-faqs/f-otrading/articles/why-did-my-bank-nifty-option-order-get-rejected) | a rejected leg is recorded and the lone leg bought back (`test_a_rejected_leg_…`) |
| Stock options: no fresh OTM longs in the last two days before expiry (physical settlement). Index options are cash-settled. | [support](https://support.zerodha.com/category/trading-and-markets/trading-faqs/f-otrading/articles/why-am-i-unable-to-buy-stock-options-close-to-the-expiry) | the book trades index options only |

## 3. After-market orders (the path that would have survived the flush)

| Rule | Source | Control |
|---|---|---|
| **Official:** F&O AMOs can be placed, modified and cancelled **15:45 to 09:11 IST**, sent to the exchange at 09:15 (current-month futures to 08:58). **Not between 01:00 and 05:30 IST: scheduled maintenance.** So the real windows are 15:45 to 01:00 and 05:30 to 09:11. The rejections page gives 09:10 as the F&O cut-off, so treat 09:10 as the safe end. Pages carry no date. | [support: AMO timings](https://support.zerodha.com/category/trading-and-markets/charts-and-orders/order/articles/auto-amo), [support: rejections](https://support.zerodha.com/category/trading-and-markets/alerts-and-nudges/kite-error-messages/articles/kite-order-rejections) | place-at-open path (planned): LIMIT AMO placed before 01:00 or after 05:30, never in between |
| **Official:** index option market AMOs are rejected (impact cost); use LIMIT, priced above the expected market for a buy. **Official:** in an AMO, orders with the GTT checkbox selected are not accepted. | [support: index option AMO rejection](https://support.zerodha.com/category/trading-and-markets/charts-and-orders/order/articles/index-options-amo-rejection), [support: AMO timings](https://support.zerodha.com/category/trading-and-markets/charts-and-orders/order/articles/auto-amo) | place-at-open uses LIMIT with no GTT flag |
| API: `variety="amo"` (lower case); not for iceberg or cover orders; a pending AMO may still show variety `amo` after the exchange takes it, so cancel with `regular` if `amo` times out. | [forum 10912](https://kite.trade/forum/discussion/10912/not-able-to-place-amo-orders-using-kite-api), [forum 11742](https://kite.trade/forum/discussion/11742/error-in-cancelling-amo-orders) | place-at-open path; the order book is read back after placing |
| **Unconfirmed, no source found:** an accepted AMO survives a later API token flush. It is our reasoning, and the reason the place-at-open path exists, so the one-lot real test must prove it. | none | place-at-open path |

### GTTs and overnight, what is and is not sourced

| Item | Status | Source |
|---|---|---|
| GTTs can be placed, cancelled or modified at any time; they trigger only in market hours, F&O contracts until 15:40 | **Official**, says nothing about maintenance | [support: GTT](https://support.zerodha.com/category/trading-and-markets/charts-and-orders/gtt/articles/what-is-the-good-till-triggered-gtt-feature) |
| Buy OCO GTTs only in F&O; index F&O OCO only NRML | **Official** | same page |
| F&O GTT validity: support says until the contract expires; the terms say pending GTTs are invalidated one day after expiry | **Official, the two pages differ** | [support: F&O GTT](https://support.zerodha.com/category/trading-and-markets/charts-and-orders/gtt/articles/gtt-fno), [GTT terms](https://zerodha.com/tos/gtt/) |
| An overnight block on GTTs | **Not found.** Conflicts with "at any time", yet Kite appeared to refuse one at about 01:30 IST on 2026-11-03; exact message not captured | none |
| Extra AMO or GTT limits on options expiring that day | **Not found** | none |
| The 01:00 to 05:30 block applies to the Kite Connect API | **Not found.** Kite Connect order and GTT docs mention no window or maintenance; do not assume either way | [docs: orders](https://kite.trade/docs/connect/v3/orders/), [docs: GTT](https://kite.trade/docs/connect/v3/gtt/) |
| Beginning-of-day process times | **Forum only, old and conflicting:** see the two threads | [forum 2524](https://kite.trade/forum/discussion/2524/trading-symbol-doesnt-exist), [forum 4655](https://kite.trade/forum/discussion/4655/can-not-login-to-https-kite-zerodha-com-for-two-days) |

## 4. Alerts (the ping that never arrived)

| Rule | Source | Control |
|---|---|---|
| ntfy priority 5 ("urgent") is the loudest ntfy level; the server held the 09:16 message at priority 5, the phone never showed it. Android kills the ntfy background service under battery optimisation / doze; the fix is battery "unrestricted" + connection mode WebSocket + instant delivery. | [ntfy #1709](https://github.com/binwiederhier/ntfy/issues/1709), [#855](https://github.com/binwiederhier/ntfy/issues/855), [#1834](https://github.com/binwiederhier/ntfy/issues/1834) | Amit's phone settings (one-time); `send_ntfy` adds a loud tag (no repeat is built) |
| A phone call needs a paid channel: ntfy Pro `X-Call` (Twilio-backed, verified number) or a self-hosted ntfy with a Twilio account. | [ntfy: publish](https://docs.ntfy.sh/publish/), [ntfy: config](https://docs.ntfy.sh/config/) | `ALERT_CALL_URL` in secrets.env (any GET webhook that rings the phone) is hit on every urgent push |

## 5. Before any new live action

1. Which session does it need, and at what time? If before 08:30 IST, it cannot rely on a login: it must be an AMO placed while a session is valid, or it waits.
2. Does the step prove the session, read margin, quote every leg and compare Kite with the ledger **before** the first order (`preflight`)? Which push does the user get if any of that fails, and how early?
3. Is every order a LIMIT inside the execution range, below the freeze quantity, within the rate limits?
4. Which one-shot setting or state does it consume, and is it consumed only after the action that needed it succeeded?
5. Has it run end to end on the fake broker (`tests/test_options_live.py`) and, where possible, in shadow on a real day?
