# Survivorship-exposure dead-name diagnostic (plan 0012 A3)

Read-only. `reconstruct_pit.py` builds its PIT panel from the current, survivors-only universe (`stocks`) and never references `historical_universe` (built for the multibagger study, reconstructed back to 2018 incl. delisted names). This quantifies the gap before anyone changes `reconstruct_pit.py` — and surfaces a deeper limitation than the audit assumed.

## (a) Dead-name count

`historical_universe` distinct symbols: 3,302. `stocks` (current): 2,448. Overlap: 1,921. **Dead names (in `historical_universe`, not in `stocks`): 1381.**

Adapted finding: `historical_universe.sid` is populated for exactly the 1,921 overlapping symbols and is NULL for all 1,381 dead ones — the crosswalk to a v2 internal sid only exists for currently-tracked stocks. `stock_prices` (sid-keyed) confirms zero rows outside the current `stocks` sids. **Dead names have no price linkage into any sid-keyed table** — only `historical_universe.close` itself carries any price data for them.

## (b) Per anchor-year panel-entry eligibility

Tested against `historical_universe`'s own snapshot dates (there is no other price source for dead names) for >= 6 hits/year within 7 calendar days — the ADR-0047 guard's bar.

| anchor_year | n_historical_universe_snapshots_that_year | n_dead_names_qualifying (>=6 needed) |
| --- | --- | --- |
| 2023 | 2 | 0 |
| 2024 | 1 | 0 |
| 2025 | 0 | 0 |
| 2026 | 1 | 0 |


**Adapted finding:** `historical_universe` has only **9 snapshot dates in total** across 2018-2026 (~annual cadence — see the count column above), so the **6-monthly-anchors-per-year bar is unsatisfiable for any symbol by construction**. This is reported honestly as 0 rather than loosened into a weaker proxy that would misrepresent the finding. The real conclusion is stronger than "the panel misses dead names": **the reconstructed universe itself lacks the temporal density to backtest delisted names at the live panel's monthly/20d-forward cadence at all.** Fixing Data-F1 (wiring `historical_universe` into `reconstruct_pit.py`) would need a full daily-price backfill project for ~1,381 delisted symbols, not just pointing the panel builder at a different universe table.

## (c) The amputated tail

Because (b) is 0 for every year, the specified 20d-forward-return computation has no eligible rows. Substitute measurement (**coarse, annual-granularity, NOT the specified 20d window** — the closest this table's actual density supports): return from each dead symbol's first to last available `historical_universe` close.

- Dead symbols with >= 2 close observations: 1008 (single-observation, unmeasurable: 373)
- Mean first-to-last close return across those dead names: 0.7031
- Survivor panel mean `fwd_return_20d` (all anchors, all tiers, for scale — **not a like-for-like comparison**, different horizon/units): 0.0087 (n=284787)


Note on the positive mean: `historical_universe` "dead" symbols include BOTH distress delistings (failures) and clean delistings (mergers/acquisitions/buyouts, often at a premium) — this table can't distinguish the two, and the mean nets them against each other. The worst decliners below are recognizable distress cases (Future Retail/Consumer, Reliance Capital, Sadbhav) — the tail this diagnostic is meant to surface.

Sample of dead-name coarse returns (first 15, most negative first):

| symbol | first_date | last_date | n_obs | first_to_last_return |
| --- | --- | --- | --- | --- |
| AKSHAR | 2022-08-01 | 2026-05-29 | 5 | -0.9958 |
| MKPL | 2023-10-03 | 2026-05-29 | 3 | -0.994 |
| FRETAIL | 2018-04-02 | 2022-08-01 | 5 | -0.9895 |
| FCONSUMER | 2018-04-02 | 2024-04-01 | 8 | -0.9856 |
| GODHA | 2021-04-01 | 2024-04-01 | 6 | -0.9847 |
| SPTL | 2018-04-02 | 2024-04-01 | 8 | -0.9831 |
| HDFCMFGETF | 2018-04-02 | 2023-04-03 | 6 | -0.9814 |
| GOYALALUM | 2023-04-03 | 2026-05-29 | 4 | -0.9805 |
| SADBHIN | 2018-04-02 | 2026-05-29 | 9 | -0.9791 |
| GOLDSHARE | 2018-04-02 | 2024-04-01 | 8 | -0.9787 |
| MTEDUCARE | 2018-04-02 | 2026-05-29 | 9 | -0.9775 |
| RELCAPITAL | 2018-04-02 | 2023-10-03 | 7 | -0.9769 |
| SADBHAV | 2018-04-02 | 2026-05-29 | 9 | -0.9753 |
| KAMOPAINTS | 2023-04-03 | 2026-05-29 | 4 | -0.9748 |
| DANGEE | 2021-04-01 | 2026-05-29 | 7 | -0.9743 |


## Per-factor risk note

Distress-loading factors are the ones most inflated by this gap: `pledge_quality` and `governance_resignation` are explicitly designed to fire on names heading toward distress/delisting — exactly the population this diagnostic shows the panel drops, and (per section b) cannot currently be recovered even from the 'true universe' reconstruction without a fresh price-history backfill. Any IC/t-stat computed for these factors on the current survivors-only panel should be read as an upper bound on their true (dead-name-inclusive) predictive value, not a point estimate.
