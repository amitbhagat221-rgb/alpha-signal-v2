# Architecture

How the system fits together today. This doc names where each fact lives instead of copying counts that drift.

## Layers

```
                        ORCHESTRATION
   pipeline.py runs config.PIPELINE_STEPS in order (85 steps as of 2026-09-26)
   each step: {name, module, function, critical, table, source, data_freq, frequency}
   frequency gate: daily · weekly (Sunday) · monthly (1st); --step overrides
   critical=True (fetch_bhavcopy, quality_gate, screener) aborts the run
   every step → one pipeline_log row

 SOURCES  ────────→  SIGNALS  ────────→  SCORING  ────────→  OUTPUT
 sources/*           signals/*           scoring/*           output/*
 external → DB       DB → *_scores       quality_gate,       snapshot → dossier
 (+ run_daily_       (+ inline factors   regime, screener    (Claude API) → email
  forward.sh at      in screener         → daily_picks       (Gmail SMTP)
  14:00 UTC)         _load_signals)
                              ↓
               SQLite data/alpha_signal.db (WAL, single file)
               + DuckDB read replica for analytical scans (ADR 0031)
                              ↓
            TRUST & OBSERVABILITY: eligibility/ · validators/ (7 gates, UHS)
            · tools/data_sanity · health_report · freshness_watchdog · lineage.py
                              ↓
            cockpit/ (:3000) · cockpit_ops/ (:3001 Health Center, /flow, /sql)
```

Heavy or slow steps (news enrichment, regulatory classification, broker recos with a 90-minute daily budget, banking metrics) come **after** the email in `PIPELINE_STEPS`, so they can't delay the digest.

## Where the truth lives

| Fact | Source of truth |
|---|---|
| Steps, order, cadence | `config.PIPELINE_STEPS` (`python pipeline.py --dry-run` lists what runs today) |
| Tables + descriptions | `schema.sql`, `tables.TABLES`; live: `sqlite3 data/alpha_signal.db .tables` |
| Factor registry | `db.BACKTEST_SIGNALS` (all), `db.FACTOR_LIBRARY` (sub-bar), `db.BACKTEST_CADENCE` |
| Production weights | `config.SIGNAL_WEIGHTS` → [signal-weights.md](signal-weights.md) for the rationale |
| Tiers + liquidity floors | `stocks.cap_tier`, `config.PORTFOLIO["min_adtv_inr"]`, `tools/classify_micro_tier.py`, `config.EXCLUDED_FROM_PICKS` |
| Per-signal eligibility | `eligibility/registry.py` → `universe_eligibility` |
| Factor lineage | `lineage.FACTOR_LINEAGE` (ADR 0027) |
| File outputs watched for freshness | `config.FILE_OUTPUTS` |
| Cron | `crontab -l` (table in [OPERATOR.md](../../OPERATOR.md)) |

## Data flow (example: piotroski)

```
tickertape → quarterly_income, annual_balance_sheet, annual_cash_flow
           ↓
signals.piotroski → piotroski_scores  (per sid per snapshot_date)
           ↓
scoring.screener  → daily_picks  (full ranked, eligible universe per date)
           ↓
output.dossier → output.email_sender
```

Every signal has the same shape: read raw data, compute, and write a `*_scores` table keyed by `(sid, snapshot_date)`. The PIT twin of each signal lives in `tools/reconstruct_pit.py` and writes `daily_snapshots_pit` (ship them together, per CLAUDE.md).

## Tier-aware scoring

- `stocks.cap_tier` is assigned before any ranking: LARGE (top 100), MID (101–250), SMALL (rest), MICRO (carved out of SMALL, never picked; ADR 0026).
- Each tier has its own weight vector in `config.SIGNAL_WEIGHTS`. Signals are percentile-ranked **within tier**, weighted, and re-ranked within tier (ADR 0005).
- Pick gate: `eligible_coverage` plus weight-coverage and price-row floors (ADR 0021 → 0024). Financials use the generic weights (ADR 0048).
- The advisory sized book is HRP with banded rebalancing (ADRs 0044/0046; `portfolio_construction.py`).

## Run wrapper

`run_pipeline.sh` takes the shared harvest `flock`, imports the credentials read-only from v1's `run_pipeline.sh` and runs `python pipeline.py`. The cron fires it at **03:30 UTC** (09:00 IST).
