# ADR 0065 — Live tiers, display and inputs use the backtest's own computations; price factors carry a full-market reading

**Status:** proposed 2026-10-08 (plan 0020 close-out; Amit: "complete … anything pending from plan 0020"). Takes effect on approval: it moves 232 stocks between SMALL and MICRO. Builds on ADR 0026 (MICRO carve-out), 0052 (one compute per factor), 0064.

## Decision

1. **One market cap.** `signals._fundamentals.market_caps` (close × the share count on that close's basis) is the market cap of the live tiers (`scoring.segment`), the backtest tiers (`pit.tiers_at`), the MICRO carve-out, `fcf_yield` and `stocks.market_cap_cr`, which now holds ₹ crore and is written daily (work order 1).
2. **Live tiers are the backtest's tiers.** `pit.tier_inputs` (market cap, 90-day traded value, knowable quarters on one reporting basis) feeds both; the MICRO rule is `scoring.segment.carve`: illiquid (< ₹1 Cr a day) AND (market cap < ₹500 Cr OR < 4 quarters). The live-only Piotroski ≤ 3 leg is dropped.
3. **Display shows what was ranked.** `output/snapshot.py` takes every value from `pit.features_at(today)` and fills `stocks.pe_ratio / pb_ratio / roe / debt_to_equity`.
4. **A wired factor's input is never optional.** `pit.load_raw` raises when a frame a wired producer reads is empty or unreadable.
5. **Price factors carry two readings.** `daily_snapshots_pit_unlisted` holds the price-only factors of every delisted and never-listed NSE symbol; `tools/backtest_pit` stores a `v2_full_market` t beside the universe t. A weight on a price factor needs the full-market t to have the same sign and clear the same bar.

## Why

- The live two-source market cap passed KDDL at 1,744 Cr shares as "corroborated" (both vendors carried the bad row) and ranked a ₹5,000 Cr company 31st in LARGE on 2026-10-08. The backtest's share-count rule rejects that row.
- The live carve-out compared rupees with crore, so its size leg fired only for missing values, and it carried a Piotroski leg read from the unlagged `piotroski_scores` table. Neither was in the tier definition the SMALL evidence was measured on (ADR 0063).
- The stock page and email showed values computed by a second, unlagged path (Piotroski differed for 349 of 1,602 stocks); the valuation columns were empty for every stock (data-quality auditor, 2026-10-04).
- An unreadable `bse_results` would have scored `announcement_car` (weight 0.35 in LARGE, 0.10 in MID, 0.22 in SMALL) as neutral for every stock without an error.
- Survivorship: the universe drops 538 dead names; the price factors' evidence should not depend on that.

## Measured effect (dry runs, 2026-10-08)

| Change | Effect |
|---|---|
| Segment on the one market cap | 8 rank-tier moves; KDDL LARGE → SMALL |
| MICRO rule = backtest rule | 146 MICRO → SMALL, 86 SMALL → MICRO; MICRO 560 → 500 |
| Backtest tiers (quarters counted once) | 1–2 stocks per anchor SMALL → MICRO |

## Consequences

- SMALL ranks about 60 more stocks; the backtest's SMALL evidence now describes the live SMALL.
- `stocks.market_cap_cr` readers no longer divide by 1e7; the email shows market cap in crore for the first time.
- `tools/factor_audit --wired` shows `t_full_market`; the promotion review reads it for price factors.
