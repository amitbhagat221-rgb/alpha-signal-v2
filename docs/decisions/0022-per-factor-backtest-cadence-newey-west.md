# 0022 — Per-factor backtest cadence + Newey-West variance correction
**2026-05-24 · Accepted**

**Decision.** Each factor declares a `backtest_cadence` in [db.py BACKTEST_CADENCE](../../db.py): `monthly` (default, slow-moving fundamentals), `weekly` (behavioral / event-driven / news), `sector_portfolio` (sector-level signals — different framework), or `portfolio` (end-state composite — Track 2.4). [tools/backtest_pit.py](../../tools/backtest_pit.py) dispatches on this field, filters `daily_snapshots_pit` to cadence-appropriate dates, and applies Newey-West variance correction when the signal lookback window or forward-return horizon exceeds the eval gap. NW lag per signal: insider/delivery_anomaly_z=13 (90d window), delivery/bulk/short=4 (30d), sentiment/news_volume=3 (fwd_return overlap only).

**Why.** Pre-2026-05-24 the backtest framework was monthly-only — v1's C13b protocol used 35 monthly eval dates because that matched the quarterly-filing cadence of fundamentals. Behavioral signals (insider, sentiment_7d, bulk_deal, short_selling, delivery anomaly) update daily and have day-to-week alpha decay, so a monthly framework gives them ~24-36 observations vs the 250+ they should have at weekly cadence. The √n boost in t-stats was structurally biased against fast-decay signals — they showed DROP or INSUFFICIENT not because they lacked alpha but because the framework starved them of sample size. The 2026-05-24 audit confirmed this empirically: same data, monthly cadence → `bulk_deal_signal SMALL` t=0.66 (DROP, n=3), weekly cadence → t=2.56 (KEEP, n=70).

Newey-West is necessary because weekly observations of a 90d-window signal are ~93% overlapping. Treating them as independent observations inflates the √n boost to a fake degree (`insider_signal` would show t≈5 raw vs t≈1.8 NW-corrected). Without NW, the weekly framework would be biased *toward* false positives, which is worse than the original monthly bias. NW with the right lag levels the playing field — t-stats from different cadences become honestly comparable.

**Empirical impact (post-cadence-aware compute).** Three signals moved from "looks like noise" to "real alpha", two confirmed as real-noise:

| Signal × Tier | Monthly t (n) | Weekly+NW t (n) | Change |
|---|---|---|---|
| bulk_deal_signal SMALL | 0.66 (n=3, DROP) | **2.56 (n=70, KEEP)** | New finding |
| delivery_anomaly_z SMALL | 0.64 (n=5, DROP) | **4.11 (n=100, KEEP)** | New finding |
| sentiment_7d LARGE | INSUFFICIENT (n=1) | **-3.88 (n=4, KEEP)** | New — preliminary, tiny sample |
| avg_delivery_pct_30d SMALL | 4.20 (n=5, KEEP) | 4.21 (n=100, KEEP) | Stable, much higher confidence |
| short_selling all tiers | DROP (all) | DROP (NW-corrected) | Confirmed real-noise |
| insider_signal all tiers | DROP (all) | DROP (NW-corrected, SMALL near-WEAK at 1.85) | Confirmed |

**Storage.** `pit_ic_by_tier_v2` now carries dual rows per signal — old `source='v2_recompute'` row from monthly compute, new `source='v2_recompute:weekly+NW<lag>'` row from cadence-aware compute. PK is (signal, cap_tier, source) so they coexist. Readers MUST filter by source to avoid double-counting. Cockpit Factor Library reads only monthly rows for the validation badge (cadence is displayed separately so the user knows which sample size produced the verdict).

**Lag schedule (`_NW_LAG_WEEKLY` in backtest_pit.py).** Computed as `max(signal_window_in_weeks, fwd_horizon_in_weeks - 1)`. fwd_return_20d ≈ 4 weeks → adds floor lag 3 for return overlap. Signal-side lags: insider 90d → 13, delivery_anomaly_z 90d → 13, avg_delivery_30d → 4, bulk_deal aggregation 30d → 4, short_selling 30d → 4, sentiment_7d → 3 (signal window matches eval gap), news_volume_7d → 3. Bartlett kernel with linear weight decay; falls back to classical SE if NW estimator is non-positive (rare edge case).

**Cadence picker (`BACKTEST_CADENCE` in db.py).** Categorized 63 signals: 51 monthly (fundamentals + momentum + shareholding + analyst + composites), 9 weekly (insider, sentiment_7d, bulk_deal, short_selling, delivery × 2, news_volume, fii_dii × 2), 2 sector_portfolio (regulatory_sector_signal, macro_sector_signal), 1 portfolio (screener_final_composite). Default `get_backtest_cadence(unknown_id) → "monthly"` is safe for all current signals even if sub-optimal — monthly always works, just with weaker statistical power for fast-decay ones.

**Trade-offs considered.** (a) Could have run *all* signals at weekly cadence — rejected because fundamentals genuinely don't refresh weekly, so the extra observations would be pure autocorrelation that NW would have to entirely strip out, giving no real boost. Monthly is the natural rebalance frequency for fundamentals. (b) Could have used daily cadence for behavioral signals — rejected because the rolling-window overlap (e.g. 90d) is so large that NW lag would be ~90 days, eating most of the apparent boost. Weekly is the sweet spot for behavioral signals: enough cadence to grow n meaningfully (5x vs monthly), small enough autocorrelation that NW correction is bounded. (c) Could have done sector-portfolio test for regulatory/macro tilts here — deferred to a separate ADR; that framework is different (information ratio vs cross-sectional IC) and warrants its own design.

**What this is not.** Not a re-run of v1 C13b — those 35 monthly t-stats in `pit_ic_by_tier_v1` are the canonical baseline for cross-cadence comparison and remain authoritative for the 13 v1 signals. Not an automatic upgrade of every behavioral signal's verdict — the cadence change reveals which signals have real alpha vs which were genuinely noise (e.g. short_selling stayed DROP under both). Not a sector-portfolio test (different framework entirely — needed for regulatory_sector + macro_sector).

**Future work signaled.** (i) Sector-portfolio test framework for the 2 sector signals. (ii) When `news_articles` accumulates another ~6 months, re-run sentiment_7d weekly compute — the LARGE-tier t=-3.88 (n=4) is preliminary and could be regime-specific. (iii) IC stability weighting (Plan 0002 §3.3a) should consume cadence-native t-stats, not blanket-monthly — this ADR is a prerequisite.
