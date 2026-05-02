# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.1
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # 04 — Analyst Data Audit & Migration
#
# **Tables:** `analyst_consensus` (current snapshot per stock), `forecast_history` (time series)
#
# **Source:** `~/alpha-signal/data/analyst/consensus.csv` (2,439 rows), `forecast_history.csv` (29,013 rows)

# %%
import pandas as pd
from pathlib import Path
import sys

V1 = Path.home() / "alpha-signal"
sys.path.insert(0, str(Path.home() / "alpha-signal-v2"))
from db import get_db, upsert_df, insert_df, read_table, read_sql

# Load both CSVs
cons = pd.read_csv(V1 / "data/analyst/consensus.csv")
fh = pd.read_csv(V1 / "data/analyst/forecast_history.csv")

print(f"=== consensus.csv: {cons.shape} ===")
print(f"Columns: {list(cons.columns)}")
for c in cons.columns:
    null_pct = cons[c].isnull().sum() / len(cons) * 100
    print(f"  {c:25s}  {cons[c].dtype:10s}  {null_pct:5.1f}% null")

print(f"\n=== forecast_history.csv: {fh.shape} ===")
print(f"Columns: {list(fh.columns)}")
print(f"Unique sids: {fh['sid'].nunique()}")
print(f"Metrics: {fh['metric'].unique().tolist()}")
print(f"Date range: {fh['date'].min()} to {fh['date'].max()}")

# %%
# Coverage by tier
stocks = read_table("stocks")
valid_sids = set(stocks['sid'])

cons_in_universe = cons[cons['sid'].isin(valid_sids)]
print(f"=== Consensus: {len(cons_in_universe)} of {len(cons)} in universe ===")

# How many have actual analyst data?
has_data = cons_in_universe[cons_in_universe['has_analyst_data'] == True]
print(f"With analyst data: {len(has_data)}")

# Coverage by tier
merged = cons_in_universe.merge(stocks[['sid', 'cap_tier']], on='sid')
print(f"\n=== Analyst coverage by tier ===")
for tier in ['LARGE', 'MID', 'SMALL']:
    tier_total = len(stocks[stocks['cap_tier'] == tier])
    tier_covered = len(merged[(merged['cap_tier'] == tier) & (merged['has_analyst_data'] == True)])
    print(f"  {tier:6s}: {tier_covered}/{tier_total} ({tier_covered/tier_total*100:.0f}%)")

# Forecast history coverage
fh_in_universe = fh[fh['sid'].isin(valid_sids)]
print(f"\n=== Forecast history: {len(fh_in_universe)} of {len(fh)} in universe ===")
print(f"Orphan sids: {len(set(fh['sid']) - valid_sids)}")

# %%
# === MIGRATE ANALYST CONSENSUS ===
# Schema: sid (PK), total_analysts, buy_pct, price_target, forward_eps,
#         eps_growth_pct, forward_revenue, revenue_growth_pct, has_analyst_data, fetched_at

cons_clean = cons_in_universe.copy()
cons_clean['has_analyst_data'] = cons_clean['has_analyst_data'].astype(int)
cons_clean = cons_clean.rename(columns={'harvested_at': 'fetched_at'})

cons_cols = ['sid', 'total_analysts', 'buy_pct', 'price_target', 'forward_eps',
             'eps_growth_pct', 'forward_revenue', 'revenue_growth_pct', 
             'has_analyst_data', 'fetched_at']
cons_insert = cons_clean[cons_cols]

rows = upsert_df(cons_insert, "analyst_consensus")
print(f"analyst_consensus: {rows} rows inserted")

# === MIGRATE FORECAST HISTORY ===
# Schema: sid, metric, date, value, change, fetched_at

fh_clean = fh_in_universe.copy()
fh_clean = fh_clean.rename(columns={'harvested_at': 'fetched_at'})
fh_cols = ['sid', 'metric', 'date', 'value', 'change', 'fetched_at']
fh_insert = fh_clean[fh_cols]

rows = insert_df(fh_insert, "forecast_history")
print(f"forecast_history: {rows} rows inserted")

# Verify
from db import table_counts
table_counts()
