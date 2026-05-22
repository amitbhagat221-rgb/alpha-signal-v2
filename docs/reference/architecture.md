# Architecture

How the system fits today. Update when reality changes.

## Five layers

```
                  ORCHESTRATION
        pipeline.py reads PIPELINE_STEPS from config.py
        24 steps; each logged to pipeline_log; --step to isolate

   SOURCES        →        SIGNALS        →        SCORING
   external → DB           DB → DB                 DB → DB + ranking
   ~10 source families     12 modules → 42         screener, quality_gate,
                           registered factors      regime
                                  ↓
                       SQLite (alpha_signal.db)
                       51 tables, WAL, single file
                                  ↓
                            OUTPUT
                       snapshot → dossier → email
```

## Project layout

```
config.py / db.py / pipeline.py / validate.py / health.py / schema.sql

sources/
  macro_yfinance · macro_gov · nse (bhavcopy) · nse_insider · nse_bulk
  regulatory_harvester · regulatory_classifier · rss
  tickertape · tickertape_analyst · tickertape_shareholding (monthly cron)
  screener_pull · screener_schedules (Track 3 xlsx + JSON ingest)

signals/
  piotroski · accruals · consensus · promoter · forensic
  smart_money · sentiment · momentum · earnings_yield
  insider_signal · macro · regulatory
  roic · fcf_yield (Track 3 Phase 3.2)

scoring/
  screener (tier-aware weighted scoring + forensic penalty)
  quality_gate (small-cap 3-tier: EXCLUDED/PENALISED/PASS)
  regime (VIX → allocation weights)

output/   snapshot · dossier (Claude API) · email_sender (Gmail SMTP)
tools/    reconstruct_pit · backtest_pit · compute_corporate_adjustments · freshness_watchdog
cockpit/  FastAPI ops console + read-mostly UI
```

## Pipeline steps (current)

| # | Stage | Step | Module |
|---|---|---|---|
| 1–4 | Fetch | macro_market, macro_gov, insider, bulk_deals | sources/* |
| 5–14 | Signals | sentiment, insider, forensic, piotroski, accruals, consensus, promoter, smart_money, macro, regulatory | signals/* |
| 15–17 | Score | quality_gate, regime_update, screener | scoring/* |
| 18–20 | Output | snapshot, dossier, email | output/* |

Steps defined in `config.PIPELINE_STEPS`. Change frequency/order there; orchestrator adapts.

## Database (51 tables, 6 groups)

| Group | Tables | Rows | Purpose |
|---|---|---|---|
| Raw data | 16 | ~1.4M | External, fetched |
| Computed signals | 9 | ~21K | Per-stock per-snapshot |
| Macro & regulatory | 5 | ~40K | Indicators + classified events |
| Fundamentals (Track 3) | ~6 | ~700K | Long-format Screener Premium ingest |
| Output | 2 | ~5K | Picks + snapshots |
| Pipeline / ops | 13 | grows | Logs, sector metadata, PIT archives, etc. |

Schema in `schema.sql`. Live source-of-truth: `db.TABLE_META`.

## Data flow (example: piotroski)

```
tickertape → quarterly_income, annual_balance_sheet, annual_cash_flow
           ↓
signals.piotroski → piotroski_scores  (per sid per snapshot_date)
           ↓
scoring.screener  → daily_picks  (with piotroski_adj contribution)
           ↓
output.email_sender → Gmail HTML email
```

Every signal follows this shape: read raw → compute → write to `*_scores` indexed by `(sid, snapshot_date)`.

## Tier-aware scoring

- LARGE (~100) · MID (~150) · SMALL (~2,200) by market cap
- Each tier has its own weight vector for the 12 signals (`config.WEIGHTS`)
- Percentile-rank within tier → weight → re-rank within tier → top 5–15 per tier
- See [ADR 0005](../decisions/0005-tier-aware-scoring.md) for why

## Run wrapper

`run_pipeline.sh` sets credentials (exports inherited from v1) and calls `python pipeline.py`. Cron entry at 03:30 IST.

## v1 relationship

v1 (`~/alpha-signal/`) kept for rollback only. v2 owns the cron slot since 2026-05-01. See [ADR 0007](../decisions/0007-fresh-rebuild-v2.md).
