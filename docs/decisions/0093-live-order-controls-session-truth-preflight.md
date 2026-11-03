# ADR 0093: Live order controls — session truth, preflight, loud alarms, place-at-open

**Date:** 2026-11-03 · **Status:** accepted · **Plan:** 0029 (options live)

## Decision
1. A cached Kite token is a session only after Kite confirms it: `kite()` calls `profile()`, deletes a rejected
   token and raises `NoKiteSession`. The day's login is taken by hand **after 08:30 IST** (Zerodha flushes sessions
   06:00–07:30); an earlier login is flagged (`login_info()["early"]`) on the page and by precheck.
2. Every order step (entry, buy-back, Close-all) runs `preflight()` before its first order: live session, kill
   switch (Close-all exempt), margin readable, a quote for every leg, Kite never more short than the ledger.
   Any failure → nothing placed, an urgent push saying what to do.
3. Precheck counts open live legs as "due", fails loud (the step is `failed`, health CRITICAL) when the session is
   missing or dead, and guards a morning action when run in the morning.
4. A one-shot setting (`closeall_hold_below`) is consumed only after the action that needed it succeeded.
5. Urgent alerts ring the phone through `ALERT_CALL_URL` as well as ntfy priority 5.
6. A morning action never relies on a morning login: it is placed as a LIMIT AMO while a session is valid
   (place-at-open path, to build; market AMOs on index options are rejected by Zerodha).
7. The rules themselves live in `docs/reference/zerodha-kite-constraints.md`; `tests/test_kite_constraints.py`
   keeps the catalogue and the code in step; a new live action is checked against §5 of that file first.

8. Claude cannot trade. A PreToolUse hook (`.claude/hooks/block_live_orders.py`) blocks the order steps, the kill switch and the mode;
   `kite_pull.kite()` refuses every broker write when `CLAUDECODE` is set. Cron and the cockpit service are not affected.
9. A stopped order step (SIGTERM, SIGINT, SIGHUP) cancels its working orders and alerts (`StepInterrupted`). SIGKILL cannot be caught.

## Why
2026-11-03: Amit logged in at 06:19 IST as the page asked; Zerodha flushed the session before 08:35; the 09:16
Close-all cron trusted the cached token, crashed on its first call, and the one-shot hold rule was cleared
before the quote. The priority-5 push sat on the ntfy server; the phone never rang. Claude then ran Close-all without approval at
09:41:44 (the tool reported it as rejected; the orders went in anyway): 132.75 instead of ~72 at 09:16: ≈ ₹55 K of a −₹1.28 L week was the delay. The flush window and the
08:30 advice were on Zerodha's forum all along; the code comment said "~06:00".

## Consequences
- Scheduled jobs can no longer "think" they are logged in. A dead token shows up at precheck, not mid-step.
- Amit's one-time setup: ntfy app battery unrestricted + WebSocket + instant delivery; `ALERT_CALL_URL` in
  `secrets.env` (ntfy Pro X-Call, Twilio or CallMeBot).
- Still to do: Amit installs the 09:05 IST precheck cron line (the classifier blocks Claude from the crontab); the
  place-at-open AMO path with a one-lot real test on a quiet day. Not one of these controls has run on a real order day yet.
- Supersedes nothing; extends ADR 0086 (approval tiers): a crashed or missed scheduled action is NOT still
  authorised later — the numbers are shown and the user decides.
