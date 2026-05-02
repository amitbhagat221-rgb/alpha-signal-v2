# Changelog

Newest at the top. Skip typos and formatting; only log changes future-you would want to know.

---

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
