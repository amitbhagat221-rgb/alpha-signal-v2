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
