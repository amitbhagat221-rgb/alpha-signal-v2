# HANDOFF
Updated: 2026-06-08 | Branch: master (1 unpushed after this) | HEAD: `7d86f74` feat(signals): wire sector_tilt SMALL-only (ADR 0041)

## Left off
Shipped the **BSE corporate-announcement event-stream harvester** ([sources/bse_announcements.py](sources/bse_announcements.py) + `bse_announcements` table) — the richest free data unlock found (timestamped, survivorship-complete to 2018, delisted included); full backfill running in background. Also this session: `rate_beta`/`credit_beta` built off a new daily India rates/credit series (both DROP → benched) and a build-not-buy data-source research trail ([ADR 0042](docs/decisions/0042-data-acquisition-build-not-buy.md) + 2 reference docs). Big realization: nearly everything the paid-vendor research priced "enterprise quote" is reachable free (BSE events, SEC-EDGAR ADR PIT fundamentals, TradingView 13k fields).

## Pick up here
1. **When the BSE backfill finishes** (`tail logs/bse_ann_backfill.log`; ~1.4M rows walking to 2018), build the static **BSE scrip-master ↔ ISIN ↔ ticker map** to fill `bse_announcements.sid` (NULL today) → then wire event-time PEAD dates ([signals/pead.py](signals/pead.py) ~line 44 uses `period_end+45d` proxy) + transcript look-ahead fix ([sources/transcripts_pull.py](sources/transcripts_pull.py) `doc_date` is a month proxy).
2. **Free quick wins** from [docs/reference/oss-quant-toolbox.md](docs/reference/oss-quant-toolbox.md): SEC-EDGAR ADR PIT pull (look-ahead audit, verified `data.sec.gov`), **Deflated Sharpe Ratio on `pit_ic_by_tier_v2`** (fixes the multiple-testing exposure), `pysentiment2` full LM → [signals/nlp_scores.py](signals/nlp_scores.py) (replace the ~270-word subset).
3. **Backfill `stock_prices` to 2018 via jugaad-data** (nselib floors at 2022) — the dependency behind credit_beta's backtest window + every deepened backtest (2018 floor approved by user).

## Watch out
- BSE API: endpoint is `AnnSubCategoryGetData` (NOT `AnnGetData`); the all-scrip firehose returns **one day per call** (multi-day → 0 rows); warm cookie + browser UA; **never run alongside `transcripts_pull`** (shared BSE IP-block).
- `bse_announcements.sid` is NULL until the scrip-master map exists (`stocks` has no ISIN).
- The macro full-history backfill ([sources/macro_yfinance.py](sources/macro_yfinance.py)) re-wrote `vix_history` (now 2015→) + the `macro_history` baseline → next pipeline run recomputes **regime + the live SMALL `sector_tilt` macro-z** off the deeper baseline; eyeball that daily_picks don't shift oddly.
- credit_beta is benched mostly because 2018 IL&FS credit stress predates the 2022 price panel — won't un-bench until `stock_prices` reaches 2018.
- Do **not** commit `amit_personal_docs/` or the `*.png` screenshots (dev artifacts, untracked).

## Active plan
docs/plans/0002-*.md §3.2 — §3.2.7 macro betas DONE (all 6 benched); §3.2.4 NLP next (`nlp_scores` shipped, 15,471 transcripts). New thread (no plan doc yet): BSE event stream → PEAD / credit-rating / pledge / governance factors.
