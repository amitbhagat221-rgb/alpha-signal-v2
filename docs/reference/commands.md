# Most-used commands

Set up the venv and credentials first; the steps are in [CLAUDE.md → Critical Rules](../../CLAUDE.md). Run everything from the repo root.

```bash
# Database health
python db.py
python -m tools.data_sanity          # semantic sanity checks (validate.py retired 2026-09-26)
python -c "from db import data_health; print(data_health().to_string())"
python -c "from db import table_counts; table_counts()"
python -m tools.health_report                 # same report as the 04:00 UTC email

# Pipeline
python pipeline.py --dry-run                  # steps due today (frequency-gated)
python pipeline.py --status                   # recent pipeline_log
python pipeline.py --step signal_piotroski    # one step, any day

# Signals (smoke test individually)
python -m signals.piotroski --dry-run
python -m signals.insider_signal --dry-run    # raises while the NSE PIT API is empty (since ~2026-05)
python -m signals.regulatory --dry-run

# Scoring
python -m scoring.screener --dry-run --top 10
python -m scoring.quality_gate
python -m scoring.regime --dry-run

# Data fetchers (one harvester at a time; 3-stock smoke test first)
python -m sources.macro_yfinance --days 7
python -m sources.nse_bulk
python -m sources.macro_gov

# PIT / backtest
python -m tools.reconstruct_pit --date 2025-12-01
python -m tools.backtest_pit
python -m tools.promotion_gate

# SQL explorer
jupyter notebook notebooks/00_sql_explorer.ipynb
```

The v1-port validation notebooks (01–14) are retired to `_archive/notebooks/`.

## Crons

Cron entries live only in the system crontab, never in this repo. `crontab -l` is the source of truth; the annotated table is in [OPERATOR.md §2](../../OPERATOR.md). Back up before editing: `crontab -l > ~/crontab.bak`.
