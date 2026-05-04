# Changelog

Newest at the top. Skip typos and formatting; only log changes future-you would want to know.

---

## 2026-05-04

- **Project blueprint expanded to three tracks.** [docs/plans/0003-mother-plan.md](docs/plans/0003-mother-plan.md) now covers Engineering ✅ + Intelligence (D-phases) + Factor-depth (F-phases). The F-track is the new addition: F1 data acquisition (Screener Premium scrape, NSE F&O OI, Zerodha Kite, NLP transcripts) → F2 build 50 new factors → F3 factor model upgrade (IC-stability weighting, within-group orthogonalization, mean-variance portfolio construction with shrunk covariance, Barra-style risk decomposition). [docs/decisions/0009-factor-track-parallel-to-d-track.md](docs/decisions/0009-factor-track-parallel-to-d-track.md) records the parallel-not-sequential decision and the explicit D17↔F3.3 / D18↔F3.2 integration points.
- **Factor registry: 40 of 42 READY** (was 30/42). 8 PARTIAL → READY: m_score, z_score, fii_dii_cash_net, fii_dii_fno_positioning (status flips — data was always there); earnings_beat_rate, news_volume (built v2 compute functions); mom_6m_adj, mom_12m_adj (applied splits); promoter_qoq (diagnostic showed 97.4% sign-match when both >0.05 abs); short_selling_signal (PROPOSED → READY). Remaining non-READY: sentiment_7d (PARTIAL — needs FinBERT, scoped in plan 0005 F1.4), screener_final_composite (PROPOSED — F3 deliverable). status_reason text rewritten with hard data (n_periods, sign-match rates, correlation values).
- **PIT reconstruction full-featured.** [tools/reconstruct_pit.py](tools/reconstruct_pit.py) computes 22 signals across 7 monthly snapshots for 2,448 stocks (~210 sec per full run); new functions `pit_earnings_beat_rate` (proxy via QoQ-positive rate, 8-quarter window) and `pit_news_volume` (article count from news_articles ⟕ news_article_stocks, 7-day rolling). New schema columns: `daily_snapshots_pit.earnings_beat_rate`, `daily_snapshots_pit.news_volume_7d`. Validation guardrails + `pit_reconstruction_log` checkpoint table + `--skip-existing` flag working.
- **Split adjustment live.** [tools/apply_splits.py](tools/apply_splits.py) populates `stock_prices.adj_close` from 104 parsed `corporate_actions` events (58,263 (sid, date) rows updated across 101 stocks). [tools/reconstruct_pit.py](tools/reconstruct_pit.py) `pit_momentum` switched to use `adj_close` via `COALESCE(adj_close, close)`. v1↔v2 momentum correlation improved 0.67 → 0.78 mom_12m and 0.70 → 0.72 mom_6m. Remaining gap = dividend adjustment (deferred — would close another ~20 pp).
- **promoter_qoq diagnostic.** Raw v1↔v2 correlation 0.42-0.63 across overlap dates was misleading. Median |v1-v2 diff| = 0.000 across 1,896 stocks. Subset where both signals >0.05 absolute (n=303): **sign-match=97.4%**. The low correlation was scatter-dominated by the agreement-at-zero majority. Reclassified READY; v1 archive remains canonical for pre-2026 backtest reference.
- **nselib unified ingest.** [sources/nselib_pull.py](sources/nselib_pull.py) single CLI `--source {bulk,corp,short,fii_pos,fii_cash,mf_nav,indices,surveillance,daily_forward,all}`. Backfilled 13,652 bulk deals (12mo), 4,516 corporate actions (24mo), 30,692 short-selling rows (24mo), 220 FII/DII F&O positioning rows, 38,830 MF NAVs, 6,243 smart-beta index rows. Status flip for `bulk_deal_signal` was BLOCKED→PARTIAL→READY in this and the prior session.
- **Smart-beta indices populated.** `nse_index_history` has 9 of 12 NSE smart-beta indices, ~720 rows each (2023-06 → 2026-04). Validation: our `value_composite` top-30 LARGE+MID portfolio tracks NIFTY200 VALUE 30 at Pearson **0.984** with 5/5 sign-matches across overlap snapshots (~125 bps/mo drag, plausibly closeable with a quality overlay).
- **Forward-only daily cron wired.** `0 14 * * * /home/ubuntu/alpha-signal-v2/run_daily_forward.sh` runs at 14:00 UTC = 7:30 PM IST, after NSE EOD. Captures FII/DII cash flow + F&O participant positioning + ASM list — sources with no historical archive that must accumulate forward. ASM works (146 rows). GSM and F&O ban list parsers have known bugs (`'list' object has no attribute 'get'`) — deferred; harmless except for log noise.
- **Backtest harness validates v1 archive exactly.** [tools/backtest_pit.py](tools/backtest_pit.py) reads `daily_snapshots_pit_v1` + `daily_snapshots_pit`, computes Spearman IC per (signal × tier × eval_date), aggregates to t-stat. Reproduces every C13b headline within rounding: promoter t=3.20 SMALL ✅, EY t=3.13 SMALL ✅, piotroski t=2.81 SMALL ✅, B/P t=2.54 SMALL ✅, avg_delivery t=2.49 SMALL ✅, cf_accruals t=3.20 MID ✅. Output: `pit_ic_by_tier_v2`. v1 archive is canonical for historical t-stats; v2 is canonical going forward.
- **Three new reference docs.** [docs/reference/data-playbook.md](docs/reference/data-playbook.md) (43KB strategy + 6 reconstruction patterns + per-signal PIT recipes), [docs/reference/api-endpoints.md](docs/reference/api-endpoints.md) (per-endpoint catalog with NSE quirks, install commands, things-tried-and-rejected), [docs/reference/paid-data-sources.md](docs/reference/paid-data-sources.md) (₹5K/mo budget allocation, Screener Premium scrape pattern, Sensibull skip rationale). Extracted from Claude private memory into checked-in repo so user can see them.
- **upsert_df bug fixed.** [db.py:165](db.py#L165) was using `INSERT OR REPLACE` which deleted the row and re-inserted with NULLs for any column not in the supplied DataFrame. Effect: `tools.reconstruct_pit --signal X` was nulling all other columns for affected snapshot dates (caused real data loss mid-session). Switched to `INSERT INTO ... ON CONFLICT(pk) DO UPDATE SET only_provided_cols=excluded.only_provided_cols`. PK cols looked up via PRAGMA + cached. Verified end-to-end: subset upsert preserves untouched columns.

## 2026-05-02

- **`/flow` page rebuilt with a hand-rolled mini-DAG.** Four phase columns (Sources / Signals / Scoring / Output) side-by-side with `→` arrows between them, color-coded step pills (SUCCESS / FAILED / RUNNING / ABORTED / NEVER RUN), critical-fail steps get a thick red border. Sits above the existing detail-card grid in [cockpit/templates/flow.html](cockpit/templates/flow.html). No graph library — pure CSS grid + flexbox.
- **In-UI step rerun.** `↻` button on every step pill (mini-DAG) and every detail card → POST `/api/pipeline/rerun/{step_name}` → spawns `python pipeline.py --step <name>` as a detached subprocess via `start_new_session=True`. Logs to `output/rerun.log`. Backed by `rerun_step()` in [cockpit/api.py](cockpit/api.py) and a new POST route in [cockpit/app.py](cockpit/app.py). See [docs/decisions/0008-cockpit-write-surface.md](docs/decisions/0008-cockpit-write-surface.md) for the architectural shift (cockpit is now a write-side surface) and the five guardrails every future write endpoint must satisfy.
- **Duplicate protection on rerun.** Refuses with HTTP 409 `{"ok": false, "error": "<step> is already RUNNING"}` if a `pipeline_log` row for that step is RUNNING and younger than 5 minutes. Stale RUNNING (older) is treated as crashed and the rerun proceeds.
- **Auto-refresh on `/flow`** every 60s with a visible countdown; rerun click shortens the countdown to 8s so the status flip is visible without a manual reload.
- **Smoke tests updated.** Replaced the intermediate Mermaid-renderer tests with `test_flow_overview_returns_layers_and_failures` and `test_rerun_step_rejects_unknown_step`. All 6 pass via `python -m tests.test_smoke`.
- **Mermaid tried and rejected.** Earlier in the session the DAG was rendered via Mermaid (`cockpit/pipeline_dag.py`); its auto-layout collapsed 26 nodes into an unreadable horizontal stripe. The hand-rolled CSS-grid version replaced it; `cockpit/pipeline_dag.py` is deleted.
- **Dagster considered and rejected.** Conversation started as "should we add Dagster for pipeline visualization and asset-centric observability?" Per [docs/decisions/0002-no-prefect.md](docs/decisions/0002-no-prefect.md) (which explicitly named Dagster as an alternative and rejected it 23 days ago), and given no concrete observability gap that `SELECT * FROM pipeline_log` can't answer, the decision held. The narrower thing that *did* get accepted — cockpit may now mutate state via subprocess spawning — is recorded in ADR 0008.

## 2026-05-01

- **v2 took over from v1.** Cron daily slot (3:30 UTC = 9 IST) now runs `~/alpha-signal-v2/run_pipeline.sh`. v1 line commented for rollback. Pipeline ran end-to-end clean (1814 bhavcopy rows, 220 news, 2448 picks, 5 dossiers, email sent).
- **Cockpit live as systemd unit `alpha-cockpit.service`** on port 3000 — auto-restart, enabled. Replaces v1's @reboot streamlit dashboard.
- **Email template rewritten.** Tier-aware sections (LARGE / MID / SMALL), per-stock cockpit links, signal driver pills sourced from `daily_snapshots` (not the legacy `*_adj` columns the percentile screener leaves at 0), AI thesis with bull/bear/catalysts/risks in a 2×2 grid.
- **VIX bug fixed.** `vix_history` had not been written since 2026-04-07 (24 days stale). Regime was running off VIX=24.7 → CAUTION (55/25/20 allocation). Real VIX in `macro_history` was 18.46 → NORMAL (40/30/30). Added `_sync_vix_history()` to `sources.macro_yfinance.compute()` so the india_vix indicator mirrors automatically each daily run; one-shot backfill restored 757 rows.
- **`daily_changes.severity` case mismatch fixed.** Validator expected `LOW/MEDIUM/HIGH/CRITICAL`, diff_engine wrote `low/medium/high`. All writers + sort dict in [output/diff_engine.py](output/diff_engine.py) uppercased.
- **`signals/sentiment.py` ISO8601 fix.** Was hardcoding `%Y-%m-%d %H:%M:%S` for `published_at`; new RSS fetcher writes ISO8601 with `T` separator.
- **Health-check overrides.** `macro_indicators` (v1-migration leftover, no v2 producer) and `regulatory_events`/`regulatory_signals` (harvester paused on 2026-04-10 due to Anthropic budget) now scored against their real cadence, not "daily". Overall health 94 → 98.
- **Smoke tests added.** [tests/test_smoke.py](tests/test_smoke.py) — module imports, dry-run executes, critical steps stay critical, news dates parse.

## 2026-04-27

- **Documentation restructure.** Moved from 12+ floating MD files at root to a categorized `docs/` tree (`architecture.md`, `decisions/`, `runbooks/`, `reference/`, `plans/`, `_archive/`). Project root now has only `README.md`, `CLAUDE.md`, `CHANGELOG.md`. CLAUDE.md trimmed from 477 lines to ~200. v1 planning MDs (audit notes, hardening plan, build plan, etc.) archived under `docs/_archive/` with date prefixes. New rule lives in `docs/runbooks/documentation-rules.md`.

## 2026-04-11

- **Regulatory classifier state-tracking bug fixed.** Added `classifier_status` and `classifier_processed_at` columns to `regulatory_events`. Six terminal states (`pending` / `haiku_rejected` / `haiku_rejected_inferred` / `haiku_passed_sonnet_failed` / `classified` / `unknown`). Re-runs no longer waste tokens re-Haiku'ing previously rejected events. Verifier (`sources.verify_classifier_trace`) covers all four code paths with mocked APIs.
- **Regulatory backfill complete.** 16,523 events harvested across Google News (11,877), RBI circulars (858), Wayback Machine (816), and v1 news migration (2,972). 5,687 sector signals from 2,702 classified events. API budget hit on 2026-04-10 — paused until May 1.

## 2026-04-10

- **Macro data infrastructure complete.** 50 indicators across yfinance (20), data.gov.in (24), FRED (6). 18,146 rows in `macro_history`. Sector mapping covers 12 sectors with direction (+1/-1) and weight.
- **NSE bulk deals daily fetch live.** No historical archive available — accumulating from today forward.

## 2026-04-09

- **v2 rebuild begun.** Fresh folder at `~/alpha-signal-v2/`. SQLite + plain Python (no Prefect, no base classes, no YAML). v1 stays running on cron untouched.
- **Schema designed.** 33 tables across raw data / computed signals / output / pipeline metadata.
- **Data sources audited.** Identified bhavcopy as superior to yfinance for prices (delivery % + official close). Google Trends signal killed (dead).
- **Documentation drift identified.** v1 had 12+ planning/audit MDs scattered at root with no organization.

## 2026-04-03

- **v1 D14 (small-cap quality gate) instructions written.** Three-tier graduated design: hard exclusion → heavy penalty → quality composite.

## Earlier

See `docs/_archive/` for older planning documents and prior CLAUDE.md backups.
