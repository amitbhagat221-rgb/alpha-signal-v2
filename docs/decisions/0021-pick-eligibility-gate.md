# 0021 — Pick eligibility gate: weight coverage + price-rows requirement
**2026-05-24 · Accepted**

**Decision.** A stock qualifies for `daily_picks` only if it satisfies both gates ([scoring/screener.py:`_pick_eligible`](../../scoring/screener.py)):

- `weight_coverage ≥ 0.50` — at least half the tier's signal weight backed by real (non-NaN) data
- `price_rows ≥ 60` — at least ~3 months of `stock_prices` history

`weight_coverage` is a new column on the scored DataFrame: `sum(weights of signals that are non-NaN for this sid) / sum(weights in this tier's SIGNAL_WEIGHTS)`. `price_rows` is `COUNT(*) FROM stock_prices WHERE sid=? AND close>0`. Stocks failing either gate are not written to `daily_picks`; rank is re-densified 1..N within the eligible set so saved ranks have no gaps.

**Why.** On 2026-05-23, ANO (Anondita Medicare, SMALL) ranked #1 with `final_score=0.901` despite having zero price rows and only 2 of 7 SMALL signals (`promoter=0.9715`, `smart_money=50` — itself a default from a separate bug). The screener's `np.where(weight_sums > 0, scores / weight_sums, NaN)` renormalized over only the signals that existed, so a data-blank stock with one high signal scored above fully-covered peers. 15 of 20 top SMALL picks that morning had zero price rows.

Gating instead of penalizing has a specific reason: SMALL caps legitimately lack `consensus` (no sell-side coverage) and that shouldn't disqualify them. The fix is "you need enough breadth to be ranked at all" rather than "missing signals count as zero" — the latter would mechanically punish every SMALL for not having analyst coverage. 50% weight + 60d prices is the breadth threshold for *actionability*: enough breadth that the score reflects multiple independent reads, plus enough price history to chart and to compute momentum / EY / B-P.

**Numbers from the cutover (2026-05-23).** `daily_picks` dropped from 2,448 → 2,020 rows: 108 below 50% coverage (mostly BSE-only stocks with no momentum/EY/B-P) + 425 below 60d prices (overlap 105). ANO went from rank #1 → #247. SMALL top 10 changed entirely; LARGE/MID unchanged (already coverage-saturated).

**Threshold trade-offs.** `MIN_WEIGHT_COVERAGE = 0.50` is conservative — leaves room for stocks legitimately missing consensus + accruals (combined weight 0.25 on SMALL) and still passing. Raising to 0.65 would force most SMALLs to have piotroski too. `MIN_PRICE_ROWS = 60` is the dossier-chart minimum (1M view needs ≥21 trading days; 60d is comfortable). Tighter prices threshold (e.g. 252d for momentum) would gate out anything <1yr listed — too aggressive for a universe with frequent IPOs.

**Detection.** [tools/data_sanity.py](../../tools/data_sanity.py) sanity check `DAILY_PICK_NO_PRICES` (CRITICAL) and `DAILY_PICK_THIN_SIGNAL_COVERAGE` (WARN ≥10%, CRITICAL ≥25%) enforce the gate post-hoc — if a bug ever weakens the gate, these fire.

**What this is not.** Not a quality filter on the *score* — the screener still computes scores for the full universe so they're available for diagnostic queries. It's a gate on what we *recommend*. A blank-data stock can have a `final_score` that's queryable in the DataFrame; it just won't show up in `daily_picks` or anywhere downstream that reads from `daily_picks`.

**Downstream consumers checked.** [output/email_sender.py](../../output/email_sender.py) and [cockpit/api.py](../../cockpit/api.py) both iterate rank order, not full-universe assumption, so neither breaks when a sid is missing. Future writers should query `daily_picks` as authoritative for "eligible-and-ranked" — not for "every universe stock."
