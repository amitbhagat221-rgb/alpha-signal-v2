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
# # 01 — Universe Audit
#
# **Goal:** Understand what's in `universe.csv` before migrating to the `stocks` table.
#
# **Questions to answer:**
# 1. How many stocks per cap_tier?
# 2. What columns exist? Which map to the `stocks` schema?
# 3. Any duplicate sids? Missing required fields?
# 4. Sector distribution — any gaps?
# 5. How do nifty500_list.csv and slug_map.csv relate?

# %%
import pandas as pd
from pathlib import Path

V1 = Path.home() / "alpha-signal"

# Load the main universe file
uni = pd.read_csv(V1 / "data/harvester/universe.csv")
print(f"Shape: {uni.shape}")
print(f"\nColumns ({len(uni.columns)}):")
for c in uni.columns:
    print(f"  {c:25s}  {uni[c].dtype}  nulls={uni[c].isnull().sum()}")


# %%
# Tier distribution + duplicate check
print("=== Cap Tier Distribution ===")
print(uni['cap_tier'].value_counts().sort_index())
print(f"\n=== Duplicate SIDs: {uni['sid'].duplicated().sum()} ===")
print(f"=== Duplicate Tickers: {uni['ticker'].duplicated().sum()} ===")

# Sector distribution
print(f"\n=== Sectors ({uni['sector'].nunique()}) ===")
sec = uni['sector'].value_counts()
print(sec.to_string())
print(f"\nSectors with < 5 stocks: {(sec < 5).sum()}")

