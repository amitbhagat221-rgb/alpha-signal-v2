# Alpha Signal v2

Daily stock intelligence for Indian retail investors. 42 PIT-strict factors across 2,448 stocks, ranked within market-cap tiers (LARGE/MID/SMALL), emailed with AI-generated theses.

**Owner:** Amit Bhagat · **Stack:** Python + SQLite + FastAPI · **Status:** Live since 2026-05-01

## How it works

```
Daily 03:30 IST → fetch (10+ sources) → compute factors → rank within tier → email top picks
```

One SQLite DB (`data/alpha_signal.db`, 51 tables, ~320 MB). Plain Python orchestrates 24 pipeline steps. PIT-strict: prices and fundamentals adjusted at compute time, not ingest ([ADR 0010](docs/decisions/0010-pit-strict-corporate-action-adjustment.md)).

## Quick start

```bash
source ~/alpha-signal/venv/bin/activate
cd ~/alpha-signal-v2

python -c "from db import data_health; print(data_health().to_string())"   # health
python pipeline.py --dry-run                                                # pipeline
python -m tools.reconstruct_pit --date 2025-12-01                           # PIT replay
uvicorn cockpit.app:app --host 0.0.0.0 --port 3000                          # cockpit
```

More commands: [docs/reference/commands.md](docs/reference/commands.md)

## Layout

```
config.py / db.py / pipeline.py / validate.py / health.py / schema.sql
sources/   data fetchers
signals/   12 modules → 42 factors
scoring/   screener · quality_gate · regime
output/    snapshot · dossier · email
tools/     PIT reconstruction · backtest · corporate-action adjustment
cockpit/   FastAPI ops console (read + step rerun)
docs/      see docs/README.md for the map
```

## Where to look

| You want | Read |
|---|---|
| Current state | [HANDOFF.md](HANDOFF.md) |
| Rules for working here | [CLAUDE.md](CLAUDE.md) |
| Doc map | [docs/README.md](docs/README.md) |
| Architecture · data · schema · commands | [docs/reference/](docs/reference/) |
| Why we chose X | [docs/decisions/](docs/decisions/) |
| What's planned | [docs/plans/](docs/plans/) |

## v1 relationship

v1 (`~/alpha-signal/`) is kept for rollback only. v2 owns the 03:30 UTC cron since 2026-05-01. Don't modify v1 from this folder. See [ADR 0007](docs/decisions/0007-fresh-rebuild-v2.md).
