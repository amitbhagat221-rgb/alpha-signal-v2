# Most-used commands

```bash
source ~/alpha-signal/venv/bin/activate
cd ~/alpha-signal-v2

# Database health
python db.py
python validate.py
python -c "from db import data_health; print(data_health().to_string())"
python -c "from db import table_counts; table_counts()"

# Pipeline
python pipeline.py --dry-run
python pipeline.py --status
python pipeline.py --step signal_piotroski

# Signals (smoke test individually)
python -m signals.piotroski --dry-run
python -m signals.insider_signal --dry-run
python -m signals.regulatory --dry-run

# Scoring
python -m scoring.screener --dry-run --top 10
python -m scoring.quality_gate
python -m scoring.regime --dry-run

# Data fetchers
python -m sources.macro_yfinance --days 7
python -m sources.nse_insider --months 1
python -m sources.nse_bulk
python -m sources.macro_gov

# SQL explorer
jupyter notebook notebooks/00_sql_explorer.ipynb
```

## Crons (crontab-only, invisible to git — check `crontab -l`)

Cron entries live only in the system crontab, never in this repo — `git log`/`grep`
will never show them. `crontab -l` is the only source of truth; back it up before
editing (`crontab -l > backup.txt`).

- **Monthly expected_return prediction snapshot** (plan 0012 B3, added 2026-07-11) —
  1st of month 05:00 UTC (after the 04:00 health email + 04:30 snapshots cron):
  ```
  0 5 1 * * cd /home/ubuntu/alpha-signal-v2 && eval "$(grep '^export ' /home/ubuntu/alpha-signal/run_pipeline.sh)" && /home/ubuntu/alpha-signal/venv/bin/python -m tools.expected_return >> logs/expected_return_cron.log 2>&1
  ```
  Appends one JSON line to `data/expected_return_predictions.jsonl` (E[1Y]
  decomposition — beta/alpha/cost/tax) so the prediction becomes a scoreable
  track record without anyone remembering to run it by hand. Log:
  `logs/expected_return_cron.log`.
