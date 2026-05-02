# Alpha Signal v2

Daily stock intelligence for Indian retail investors. Computes 12 signals across 2,448 stocks, ranks them within market cap tiers, and emails the top picks with AI-generated investment theses.

**Owner:** Amit Bhagat | **Stack:** Python + SQLite + Jupyter | **Status:** Phase 7 of 9 complete

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

- ✅ Phase 0–7: foundation, data migration, signals, scoring, output — **DONE**
- 🔄 Phase D: data fetchers — Tickertape/RSS/bhavcopy modules pending
- ⏳ Phase 8: tests — not started
- ⏳ Phase 9: parallel run alongside v1 — not started

For full status see [CLAUDE.md](CLAUDE.md) and [CHANGELOG.md](CHANGELOG.md).

## Relationship to v1

v1 (`~/alpha-signal/`) is the original pipeline. It is **still live on cron** and will keep running until v2 is fully validated. v2 was designed as a clean rebuild with proper engineering practices — see [decisions/0007-fresh-rebuild-v2.md](docs/decisions/0007-fresh-rebuild-v2.md) for context.

**Do not modify v1 from this folder.**
