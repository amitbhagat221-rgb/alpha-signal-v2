# ADR 0020 — PT data model v2: sell-side only, LLM narrative-only, freshness via proxies

**Date:** 2026-05-23
**Status:** Accepted (supersedes parts of ADR 0018)

## Context

The 2026-05-22 HALC bug ("AI said 16.5% downside at ₹1038") was patched at the narrative-validator layer (ADR 0019 + dossier number-detector), but two deeper issues remained:

1. **LLM-generated `target_price` and `stop_loss` fields** in the dossier were never anchored to reality. The validator only checked `isinstance(int)`, not whether the number agreed with the sell-side aggregate. HALC's AI target ₹1320 (+19%) contradicted actual analyst consensus ₹1015 (−8.5%); user surfaced this 2026-05-23.

2. **`forecast_history.metric='price'` is contaminated** — confirmed 2026-05-23 that 100% of LARGE/MID and 95.5% of SMALL have the latest fh.value matching `stock_prices.close` exactly. The values are current-close masquerading as historical PT; Tickertape's `forecastsHistory.price` array contains historical year-end closes plus the latest entry (mislabeled with a recent year-end date) overwritten with today's lastPrice. Downstream: `pt_revision_yoy` factor was computing 1-year price return, not PT revision — contributing ~14% of every LARGE final_score (0.40 consensus × 0.35 pt_rev component).

Additionally, the 9-source probe (Tickertape, yfinance, Finnhub, Tijori, Trendlyne, StockEdge, MoneyControl, Screener Premium, EODHD) confirmed no free or hacky Indian PT source extends coverage beyond yfinance's ~900 stocks. The 1,500 SMALL caps without coverage genuinely have no sell-side analyst. Yahoo's `upgrades_downgrades` endpoint returns empty for Indian symbols, so per-analyst revision timestamps are not retrievable.

## Decision

**1. `analyst_consensus.price_target` (yfinance, daily refresh) is the only trusted sell-side PT source.**
- `forecast_history.metric='price'` is no longer consumed anywhere; `signals/consensus.py` and `tools/reconstruct_pit.py:pit_consensus()` both stopped reading it.
- `forecast_history.metric='eps'` and `'revenue'` remain trusted (verified plausible vs current actuals).

**2. `pt_revision_yoy` factor is DROPPED.**
- Production `signals/consensus.py`: `pt_rev` removed from WEIGHTS, redistributed proportionally to `pt_up=0.23, eps=0.54, rev=0.23` (was 0.15 / 0.35 / 0.15 with pt_rev=0.35).
- PIT `tools/reconstruct_pit.py:pit_consensus()`: hardcodes `pt_revision_yoy=NULL`; `consensus_signal_combined` now = `eps_revision_yoy` only.
- `db.py BACKTEST_SIGNALS`: `pt_revision_yoy` marked DROPPED, `consensus_signal_combined` marked DEGRADED.
- **Rebuild plan**: once `analyst_consensus_snapshots` accumulates ≥12mo (calendar: 2027-05+), recompute pt_revision from real monthly snapshot history.

**3. The LLM dossier no longer produces structured numbers.**
- `output/dossier.py` prompt: dropped `target_price`, `stop_loss`, `target_horizon_months` fields. New hard rule 6 in the prompt explicitly forbids these and references this ADR.
- Validator: any leaked `target_price`/`stop_loss` is now a violation (not a structured-ok flag).
- Rationale: LLM-generated targets hallucinated badly enough to contradict the actual consensus shown in the same view. The LLM's value-add is narrative reasoning; numbers belong in deterministic fields.

**4. Cockpit shows a single Sell-side PT card with honest provenance.**
- Headline: median PT (more robust than mean) + upside vs current price + `Median of N`.
- Range bar: low / current / median / high analyst estimates.
- Single-period rating mix (5 buckets) + qualitative recommendation_key.
- **Freshness proxies** (since yfinance doesn't expose per-analyst revision dates):
  - Next earnings date with days delta — analysts revise within ~10d of earnings
  - 4-period rating-mix mini-trend (3mo ago / 2mo / 1mo / now) with `Bullish: N% vs M% (-3m) ↑/↓` summary
  - Our own PT-change detection: when fetch-over-fetch PT moves >0.5%, store prior value + timestamp, show `PT moved +X% Nd ago` badge
- Source provenance: `YFINANCE · refreshed today ⓘ` with tooltip explaining yfinance doesn't expose per-analyst revision dates.
- For uncovered stocks: honest "No analyst price target available" notice (amber-bordered). No fake numbers.

**5. Sanity check strengthened.**
- `tools/data_sanity.py FORECAST_HISTORY_IS_PRICE_HISTORY` now cross-date JOINs (sid only). Fires CRITICAL on the 95.5% of stocks with contaminated values. Previously reported 0/0 clean because the JOIN required same-date match.

**6. Model PT (Option B) deferred to a separate session.**
- IC-based model target (`model_pt = price × (1 + IC × z(score) × σ(annual_returns))`) is the planned second column in the cockpit PT card. Calibration math + `model_targets` table + daily writer = 3-4 hours; out of scope for this ADR. Will be its own ship.

## Consequences

- **Production model meaningfully de-biased.** Re-running screener after the pt_rev drop reshuffled LARGE top-10 by 8/10 (HALC #1→#9, materials/PSU bias removed) and MID top-10 by 2/10. SMALL unchanged (no consensus weight in tier). The pre-fix model was systematically over-weighting 1-year price-return winners.
- **Backtests crossing 2026-05-23 must account for the discontinuity.** `pt_revision_yoy` and `consensus_signal_combined` change definition on this date; comparing pre- vs post-2026-05-23 t-stats is apples-to-oranges.
- **PT-change-detection badge is forward-only.** Won't populate until next genuine yfinance revision (typically 1-3 days for actively-covered stocks).
- **SMALL coverage stays at 30%** — no source materializes the missing 1,500. Honest "no coverage" notice is the long-term state for those.
- **Per-analyst revision dates remain unavailable.** Three freshness proxies are the honest substitute. If a paid source ever exposes per-broker timestamps (Trendlyne consumer-tier Excel Connect could be reverse-engineered on a non-cloud machine, ~₹5,900/yr), this decision is revisitable.

## References

- Memory: `pt_source_landscape_2026_05_23` (9-source probe results, dead-ends, paid options)
- Memory: `forecast_history_price_contaminated` (root cause + downstream impact + sanity-check fix)
- ADR 0018 (PT episodic cadence) — partially superseded: `forecast_history` is no longer in the "3 tables × 3 cadences" model for PT specifically
- ADR 0019 (observability sensor/surface/alert) — strengthened by the cross-date JOIN fix
- Commit: this session
