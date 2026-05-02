# Changelog

Newest at the top. Skip typos and formatting; only log changes future-you would want to know.

---

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
