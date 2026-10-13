# ADR 0071 — Consensus beat rate wired in MID

**Status:** accepted 2026-10-10 (Amit: "ok wire that up", after the LARGE re-audit). Changes the MID row of [ADR 0063](0063-weights-on-corrected-evidence.md); its rules stand.
**Evidence:** [large-reaudit-2026-10-10.md](../studies/large-reaudit-2026-10-10.md).

## Decision

`cons_beat_rate_4q` is wired in MID at 0.15: the share of a stock's last 4 results (≥ 3, within 400 days) whose reported EPS beat the Yahoo consensus estimate. The other MID weights are scaled ×0.85 so Σ|w| = 1:

| MID | iv_skew_25d 0.20 · residual_momentum_12_1 0.17 · cons_beat_rate_4q 0.15 · piotroski 0.15 · consensus 0.14 · accruals −0.10 · announcement_car 0.09 |
|---|---|

The feed `yahoo_earnings_history` goes from probation to production (T1: daily canary, 14-day serve-stale). Not wired in SMALL (23% coverage) or LARGE (t 0.89).

## Why

- MID t 4.52 over 83 monthly anchors (`backtest_pit`), 2.98 since 2024-09; both halves positive; 2.39 after the six MID factors already wired. Family "Earnings surprise": 0.22 correlated with `consensus`, 0.11 with `announcement_car`.
- MID combined score on the same 82 anchors, current → new: rank IC t 3.48 → 4.18 (since 2024-09: 4.05 → 4.70); top-minus-bottom tenth 2.21% → 2.27% (t 3.16 → 3.73).
- Of the variants tried, scaling the others gave the best spread. Replacing `announcement_car` gave a higher IC but a lower spread; a 0.20 weight was worse on both.

## What this does not claim

- Top 5 on the history: 1.91% → 1.33% over the tier (paired difference −0.58%, t −1.09). That is noise, but there's no evidence the top of the ranking improves. Top 10 is flat (+0.05%).
- The weights were chosen on the history they are measured on.
- Yahoo's past estimates are `pit_unverified`: whether one was revised after its report is unchecked. So far 2 pre/post-report pairs both moved < 0.5%. **Re-check after the Oct–Nov 2026 results season**; if estimates turn out to have been revised after the fact, un-wire.

## Effect (panel anchor 2026-10-02)

MID rank correlation old vs new 0.957; 3 of the top 5 kept (Navin Fluorine and Coforge in; Hindustan Copper and Sterlite Tech, which have no analyst coverage, drop to 6th and 8th).
