# Alpha Signal v2

Daily stock intelligence for Indian retail investors. Computes 12 signals across 2,448 stocks, ranks them within market cap tiers, and emails the top picks with AI-generated investment theses.

**Owner:** Amit Bhagat | **Stack:** Python + SQLite + Jupyter | **Status:** In production (v2 took over from v1 on 2026-05-01)

---

## What this does

```
Daily 3:30 AM IST
    │
    ▼
fetch external data → compute signals → score within tier → email top picks
   (10 sources)         (12 signals)      (LARGE/MID/SMALL)    (top 5 + dossiers)
```

A single SQLite database (`data/alpha_signal.db`, 33 tables, ~236 MB) is the source of truth. Plain Python orchestrates 20 pipeline steps. No frameworks, no YAML, no surprises.

## Quick start

```bash
source ~/alpha-signal/venv/bin/activate
cd ~/alpha-signal-v2

# See what's in the database
python -c "from db import table_counts; table_counts()"
python -c "from db import data_health; print(data_health().to_string())"

# Run the pipeline (or one step)
python pipeline.py --dry-run
python pipeline.py
python pipeline.py --step signal_piotroski

# Open the SQL explorer notebook
jupyter notebook notebooks/00_sql_explorer.ipynb
```

## Project layout

```
~/alpha-signal-v2/
├── README.md           ← you are here
├── CLAUDE.md           ← AI context: critical rules + pointers
├── CHANGELOG.md        ← what changed, when
├── docs/               ← all other documentation (start at docs/README.md)
│
├── config.py           ← all weights, thresholds, paths, pipeline steps
├── db.py               ← database helpers + data_health()
├── schema.sql          ← 33 tables
├── pipeline.py         ← THE orchestrator
├── validate.py         ← shared validators
├── health.py           ← health diagnostics
│
├── sources/            ← data fetchers (one file per source family)
├── signals/            ← 12 signal computations
├── scoring/            ← screener, quality_gate, regime
├── output/             ← snapshot, dossier, email
├── notebooks/          ← exploration + validation
├── tests/
└── data/alpha_signal.db
```

## Where to learn more

| You want to... | Read |
|----------------|------|
| Understand how the system fits together | [docs/architecture.md](docs/architecture.md) |
| See every doc available | [docs/README.md](docs/README.md) |
| Understand a signal's formula | [docs/reference/signals.md](docs/reference/signals.md) |
| Add a new signal or source | [docs/runbooks/](docs/runbooks/) |
| Know why we chose SQLite/Python/etc. | [docs/decisions/](docs/decisions/) |

## Status (high level)

- ✅ Foundation, data migration, signals, scoring, output — **DONE**
- ✅ Data fetchers: bhavcopy + RSS + insider + bulk-deals + macro all on daily cron; Tickertape on monthly cron (`run_tickertape_monthly.sh`)
- ✅ Smoke tests — [tests/test_smoke.py](tests/test_smoke.py); 6 tests covering imports, dry-run, critical-step config, flow overview, rerun guardrails
- ✅ Parallel run + cutover — **2026-05-01**: v2 replaced v1 on the 03:30 UTC cron slot; v1 stays installed for rollback only

Open items (see [HANDOFF.md](HANDOFF.md) for the live list): distill the regulatory-signal and macro-data plans into reference docs, resume the regulatory harvester (paused 2026-04-10 on Anthropic budget), backtest the three new signals (insider / regulatory / macro sector), decide on v1 weekend-refresh decommission, add PIB scraper incremental-save.

## Relationship to v1

v1 (`~/alpha-signal/`) is the original pipeline. It is **still live on cron** and will keep running until v2 is fully validated. v2 was designed as a clean rebuild with proper engineering practices — see [decisions/0007-fresh-rebuild-v2.md](docs/decisions/0007-fresh-rebuild-v2.md) for context.

**Do not modify v1 from this folder.**
