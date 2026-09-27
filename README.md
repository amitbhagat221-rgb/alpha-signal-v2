# Alpha Signal v2

Daily stock intelligence for Indian retail investors. It computes PIT-strict factors across the NSE/BSE universe (2,448 stocks, ETFs excluded), ranks them within market-cap tiers (LARGE/MID/SMALL; MICRO is classified but never picked), and emails the top picks with AI-written theses.

**Owner:** Amit Bhagat · **Stack:** Python + SQLite + FastAPI · **Status:** live since 2026-05-01 (research system, no live capital)

## How it works

```
03:30 UTC cron → pipeline.py runs config.PIPELINE_STEPS (fetch → signals → quality gate/regime
→ screener → snapshot/dossier/email → slow background jobs) → daily_picks + cockpit
```

- **One SQLite DB:** `data/alpha_signal.db` (multi-GB; for the table list run `sqlite3 … .tables`).
- **One step list:** `config.PIPELINE_STEPS` (85 steps; each has a `frequency`, so most days run a subset).
- **PIT-strict:** prices and fundamentals are adjusted at compute time, not at ingest ([ADR 0010](docs/decisions/0010-pit-strict-corporate-action-adjustment.md)).

The full cron, services, backups and recovery steps are in [OPERATOR.md](OPERATOR.md).

## Quick start

Set up the environment first (venv, credentials, v1 boundary); the steps are in [CLAUDE.md → Critical Rules](CLAUDE.md). Then:

```bash
python -c "from db import data_health; print(data_health().to_string())"   # health
python pipeline.py --dry-run                                                # pipeline
python -m tools.reconstruct_pit --date 2025-12-01                           # PIT replay
```

More: [docs/reference/commands.md](docs/reference/commands.md). The cockpit runs as systemd units on ports 3000/3001, so don't start a second copy on those ports.

## Layout

```
config.py · db.py · tables.py · pipeline.py · graph.py · schema.sql · lineage.py · health.py
pit.py        as-of datasets + factor computation at any date (live = backtest at t=today)
views.py      named read-models shared by the email/dossier (ADR 0052)
sources/      fetchers (NSE, BSE, Tickertape, yfinance, Screener, AMFI, Moneycontrol, RSS…)
signals/      one module per factor family → *_scores tables
scoring/      screener · regime · confidence · health_score
eligibility/  per-signal eligibility registry     validators/  trust-pipeline gates
output/       snapshot · dossier · email (plus generated reports, gitignored)
tools/        PIT panel writer, backtests, promotion gate, health/watchdog, studies
cockpit/      main FastAPI UI (:3000)             cockpit_ops/  ops console (:3001)
tests/        smoke + regression tests            _archive/     retired one-off code
docs/         see docs/README.md
```

## Where to look

| You want | Read |
|---|---|
| Current state | [HANDOFF.md](HANDOFF.md) |
| Rules for working here | [CLAUDE.md](CLAUDE.md) |
| Running / inheriting the system | [OPERATOR.md](OPERATOR.md) |
| Doc map | [docs/README.md](docs/README.md) |

v1 (`~/alpha-signal/`) is kept for rollback only ([ADR 0007](docs/decisions/0007-fresh-rebuild-v2.md)).
