# Architecture

How the system fits together, **as it stands today**. Update this file when reality changes.

For *why* we made each design choice, see [decisions/](decisions/). For *what* each table or signal looks like in detail, see [reference/](reference/). For *how to do* a specific task, see [runbooks/](runbooks/).

---

## The five layers

```
┌─────────────────────────────────────────────────────────────────┐
│                          ORCHESTRATION                          │
│  pipeline.py reads PIPELINE_STEPS from config.py                │
│  20 steps; each logged to pipeline_log table; --step to isolate │
└────────────────────────────────────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│   SOURCES    │       │   SIGNALS    │       │   SCORING    │
│              │       │              │       │              │
│ External data│       │ DB → DB      │       │ DB → DB      │
│  → DB tables │       │ computations │       │ + ranking    │
│              │       │              │       │              │
│ One file per │       │ 12 signals   │       │ screener,    │
│ source family│       │ + macro      │       │ quality_gate,│
│              │       │ + regulatory │       │ regime       │
└──────┬───────┘       └──────┬───────┘       └──────┬───────┘
       │                      │                      │
       └──────────────────────┼──────────────────────┘
                              ▼
                   ┌──────────────────────┐
                   │   SQLite database    │
                   │  data/alpha_signal.db│
                   │  33 tables, 6 groups │
                   │  WAL, single file    │
                   └──────────┬───────────┘
                              │
                   ┌──────────▼───────────┐
                   │       OUTPUT         │
                   │ snapshot, dossier,   │
                   │ email                │
                   └──────────────────────┘
```

## Project layout

```
~/alpha-signal-v2/
├── config.py              # ALL config: weights, thresholds, paths, PIPELINE_STEPS, RAW_TABLES
├── db.py                  # Database helpers + data_health()
├── schema.sql             # 33 tables, 6 groups
├── validate.py            # Shared validation functions
├── pipeline.py            # THE orchestrator
├── health.py              # Health diagnostics
│
├── sources/               # Data fetchers (one file per source family)
│   ├── macro_yfinance.py
│   ├── macro_gov.py
│   ├── nse.py                   # bhavcopy → stock_prices
│   ├── nse_insider.py
│   ├── nse_bulk.py
│   ├── regulatory_harvester.py
│   ├── regulatory_classifier.py
│   ├── tickertape.py            # manual run only (~4hr); not in cron
│   └── rss.py
│
├── signals/               # 12 signal modules
│   ├── piotroski.py       # 9-factor F-Score
│   ├── accruals.py        # CF/BS accruals + earnings persistence
│   ├── consensus.py       # PT revision + EPS/revenue growth
│   ├── promoter.py        # QoQ + pledge quality + holding modifier
│   ├── forensic.py        # Beneish 6-factor + Altman Z''
│   ├── smart_money.py     # Bulk deals + delivery %
│   ├── sentiment.py       # VADER on news articles
│   ├── momentum.py        # Risk-adjusted 6M/12M (inline, no DB table)
│   ├── earnings_yield.py  # E/P (inline, no DB table)
│   ├── insider_signal.py  # Promoter/KMP/Director trades + pledge penalty
│   ├── macro.py           # Macro indicators → sector scores
│   └── regulatory.py      # AI-classified policy events → sector scores
│
├── scoring/
│   ├── screener.py        # Tier-aware weighted scoring + forensic penalty
│   ├── quality_gate.py    # Small-cap 3-tier gate (EXCLUDED/PENALISED/PASS)
│   └── regime.py          # VIX regime → allocation weights
│
├── output/
│   ├── snapshot.py
│   ├── dossier.py         # Claude API
│   └── email_sender.py
│
├── data/alpha_signal.db   # 236 MB. Back it up daily.
├── notebooks/             # 15 exploration + validation notebooks
└── docs/                  # all documentation
```

## The 23 pipeline steps

```
DATA FETCHERS (parallel-safe, but currently serial):
  1. fetch_macro_market     → sources.macro_yfinance     (daily)
  2. fetch_macro_gov        → sources.macro_gov           (weekly)
  3. fetch_insider          → sources.nse_insider          (daily)
  4. fetch_bulk_deals       → sources.nse_bulk             (daily)

SIGNALS (depend on raw data above):
  5. signal_sentiment       → signals.sentiment
  6. signal_insider         → signals.insider_signal
  7. signal_forensic        → signals.forensic
  8. signal_piotroski       → signals.piotroski
  9. signal_accruals        → signals.accruals
 10. signal_consensus       → signals.consensus
 11. signal_promoter        → signals.promoter
 12. signal_smart_money     → signals.smart_money
 13. signal_macro           → signals.macro
 14. signal_regulatory      → signals.regulatory

SCORING (depends on signals):
 15. quality_gate           → scoring.quality_gate        (CRITICAL)
 16. regime_update          → scoring.regime
 17. screener               → scoring.screener            (CRITICAL)

OUTPUT:
 18. snapshot               → output.snapshot
 19. dossier                → output.dossier              (Anthropic API)
 20. email                  → output.email_sender         (Gmail SMTP)
```

Steps are defined in `config.PIPELINE_STEPS` — change frequency or order there, the orchestrator adapts. See [reference/pipeline-steps.md](reference/pipeline-steps.md) for full details.

## The database (33 tables, 6 groups)

| Group | Tables | Total rows | Purpose |
|-------|--------|------------|---------|
| **Raw data** | 16 | ~1.4M | External data, fetched and stored |
| **Computed signals** | 9 | ~21K | Per-stock signals, daily |
| **Macro & regulatory** | 5 | ~40K | Macro indicators + AI-classified events |
| **Output** | 2 | ~5K | Daily picks + snapshots |
| **Pipeline** | 1 | grows | Step execution log |

See [reference/schema.md](reference/schema.md) for table-by-table detail.

## Data flow (one example: piotroski)

```
sources.tickertape             →  quarterly_income, annual_balance_sheet, annual_cash_flow
                                                       │
                                                       ▼
signals.piotroski              →  piotroski_scores  (one row per stock per snapshot_date)
                                                       │
                                                       ▼
scoring.screener               →  daily_picks  (with piotroski_adj contribution)
                                                       │
                                                       ▼
output.email_sender            →  Gmail HTML email with top picks
```

Every signal follows this same shape: read raw tables, compute, write to a `*_scores` or `*_signals` table indexed by `(sid, snapshot_date)`.

## Tier-aware scoring

The screener never ranks across the full universe. Instead:

- LARGE (top 100 by market cap)
- MID (next 150)
- SMALL (rest, ~2,200)

Each tier has its own weight vector for the 12 signals (see `config.WEIGHTS`). Stocks are percentile-ranked **within** their tier, then weighted by the tier-appropriate weights, then re-ranked. Top 5–15 picks per tier.

This matters because the same signal has very different predictive power across tiers. Consensus (analyst revisions) has t=3.52 in LARGE but only t=2.44 in SMALL. Promoter QoQ is the opposite (t=0.04 LARGE, t=3.20 SMALL). See [decisions/0005-tier-aware-scoring.md](decisions/0005-tier-aware-scoring.md).

## What's not built yet

| Module | What it does | Why missing |
|--------|--------------|-------------|
| Parallel run | v1 vs v2 for 2–3 days, then disable v1 cron | Pending — v2 ran end-to-end clean on 2026-05-01 |

## Relationship to v1

v1 (`~/alpha-signal/`) is the original pipeline, **still live on cron**. v2 was a clean rebuild after the v1 system became fragile (universe split across 3 files, 80+ scattered CSVs, no contracts between scripts, zero tests). v1 keeps running until v2 is fully validated. See [decisions/0007-fresh-rebuild-v2.md](decisions/0007-fresh-rebuild-v2.md).

## Run wrapper

`run_pipeline.sh` at the project root sets credentials and calls `python pipeline.py`. Mirror of v1's wrapper but pointed at v2. Cron entry point.
