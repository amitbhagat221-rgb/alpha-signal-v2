# HANDOFF
Updated: 2026-05-23 | Branch: master (0 unpushed, all session work uncommitted) | HEAD: `8c89ad1` feat(data): yfinance PT source + observability stack + 13 Track-3 factors

## Left off
Shipped PT data model v2 (ADR 0020) — killed contaminated `forecast_history.price` from every consumer, dropped `pt_revision_yoy` factor (was 14% of LARGE final_score driving 1-yr return mislabeled as PT revision), and built a Sell-side PT card with three freshness proxies (next earnings, rating-mix trend, our own PT-change detection) because yfinance doesn't expose per-analyst revision dates for Indian equities. Also shipped sidebar v1 (rail widened 64→232px, 3 named sections) and the 3 CRITICAL observability fixes from morning health report.

## Pick up here
1. Phase 3.1b NSE F&O OI ingest → start by probing `nselib.derivatives` endpoints (option_chain, oi_history, participant_wise) for date-range support; then `sources/fno_pull.py` + `fno_option_chain` / `fno_oi_history` schema. Unblocks 8 options-implied factors in §3.2.2.
2. Decide weights for `share_momentum` (|t|=3.21 KEEP) + `dso_change_yoy` (|t|=-2.81 KEEP LARGE) in `SIGNAL_WEIGHTS` at [config.py:42](config.py#L42) — manual ~0.5× now or wait for Track 3.3a IC-stability framework.
3. Model PT (Option B Step 2) — IC-based `model_pt = price × (1 + IC × z(score) × σ(annual_returns))` per cap_tier. New `model_targets` table + daily writer + second column in [cockpit/templates/stock_detail.html](cockpit/templates/stock_detail.html) Sell-side PT card. 3-4 hr. Spec in [ADR 0020](docs/decisions/0020-pt-data-model-v2-sell-side-only-llm-narrative-only.md).

## Watch out
- **`pt_revision_yoy` is now NULL in production.** Any backtest comparing pre/post 2026-05-23 t-stats is apples-to-oranges. `consensus_signal_combined` similarly DEGRADED (eps-only). Real rebuild waits for `analyst_consensus_snapshots` to accumulate ≥12mo (2027-05+).
- **PT-change-detection badge is forward-only.** Cockpit will show "PT moved +X% Nd ago" badges starting 1-3 days from now as yfinance aggregates naturally revise; today's view shows the badge for zero stocks because we have no prior-fetch baseline yet.
- **SMALL caps ANO / SREER / BRR / SUNSH have NULL `close` in `stock_prices`** — they show "No analyst coverage" cleanly but also have no current price in the stock_detail header. Bhavcopy/yfinance ingest is missing them. Separate drive-by, not blocking.
- **LLM dossier schema changed.** Old dossier JSON files (`output/dossiers_*.json`) still carry `target_price`/`stop_loss` fields; the cockpit ignores them. New dossiers won't have those keys. Validator now treats their presence as a violation.

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — Track 3 Phase 3.1b (NSE F&O OI ingest, active) → unblocks §3.2.2 options-implied factors. Phase 3.2.1 forensic 11/15 done; 19/50 factors PIT-shipped.
