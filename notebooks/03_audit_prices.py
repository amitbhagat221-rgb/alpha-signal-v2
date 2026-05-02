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
# # 03 — Price Data Audit & Migration
#
# **Goal:** Load 922 bhavcopy CSVs into `stock_prices` table. 
#
# **Source:** `~/alpha-signal/data/smart_money/raw/bhav_*.csv` (Jul 2022 – Apr 2026)
#
# **Key questions:**
# 1. What do bhavcopy columns look like? How do they map to schema?
# 2. How many stocks per day match our universe?
# 3. What's the delivery % distribution?
# 4. Any gaps in trading days?
# 5. Load everything into `stock_prices`

# %%
import pandas as pd
import numpy as np
from pathlib import Path
from glob import glob
import sys

V1 = Path.home() / "alpha-signal"
sys.path.insert(0, str(Path.home() / "alpha-signal-v2"))
from db import get_db, upsert_df, insert_df, read_table

# Load one bhavcopy to inspect structure
sample = pd.read_csv(V1 / "data/smart_money/raw/bhav_20260407.csv")
print(f"Shape: {sample.shape}")
print(f"\nColumns: {list(sample.columns)}")
print(f"\nSample (first 5 rows):")
sample.head()

# %%
# Column mapping: bhavcopy → stock_prices schema
# Load universe to map SYMBOL (ticker) → sid
stocks = read_table("stocks")
ticker_to_sid = dict(zip(stocks['ticker'].str.strip(), stocks['sid']))

print(f"Universe: {len(ticker_to_sid)} stocks")

# Map one day to see match rate
sample.columns = sample.columns.str.strip()
eq_only = sample[sample['SERIES'] == 'EQ'].copy()
eq_only['sid'] = eq_only['SYMBOL'].str.strip().map(ticker_to_sid)

matched = eq_only['sid'].notna().sum()
total = len(eq_only)
print(f"\nSingle day match: {matched} of {total} EQ rows matched to universe ({matched/total*100:.1f}%)")
print(f"Unmatched: {total - matched} (stocks not in our universe — fine)")

print(f"""\n=== Column Mapping ===
  Bhavcopy            →  stock_prices       Action
  ────────────────────────────────────────────────
  SYMBOL              →  (map to sid)       Via ticker_to_sid lookup
  DATE1               →  date               Parse DD-Mon-YYYY → YYYY-MM-DD
  OPEN_PRICE          →  open               Direct
  HIGH_PRICE          →  high               Direct
  LOW_PRICE           →  low                Direct
  CLOSE_PRICE         →  close              Direct
  PREV_CLOSE          →  prev_close         Direct
  TTL_TRD_QNTY        →  volume             Direct
  TURNOVER_LACS       →  traded_value       Convert lakhs → absolute? Or keep as lakhs
  NO_OF_TRADES        →  num_trades         Direct
  DELIV_QTY           →  delivered_qty      Direct
  DELIV_PER           →  delivery_pct       Direct
  SERIES              →  (filter EQ only)   Drop BE/BZ/etc
  AVG_PRICE           →  (drop)             Not in schema
  LAST_PRICE          →  (drop)             Not in schema
""")

# %%
# Delivery % distribution on a single day
print("=== Delivery % distribution (single day) ===")
print(eq_only[eq_only['sid'].notna()]['DELIV_PER'].describe())
null_deliv = eq_only[eq_only['sid'].notna()]['DELIV_PER'].isnull().sum()
print(f"\nNull delivery %: {null_deliv}")

# Check date format
print(f"\n=== Date format sample ===")
print(eq_only['DATE1'].head(3).tolist())


# %%
# === LOAD ALL 922 BHAVCOPY FILES ===
# Build a function to parse one file, then apply to all

def parse_bhavcopy(filepath, ticker_to_sid):
    """Parse one bhavcopy CSV into stock_prices format."""
    try:
        df = pd.read_csv(filepath)
        df.columns = df.columns.str.strip()
        
        # Filter EQ series only
        df = df[df['SERIES'].str.strip() == 'EQ'].copy()
        
        # Map ticker to sid
        df['sid'] = df['SYMBOL'].str.strip().map(ticker_to_sid)
        df = df[df['sid'].notna()]  # Drop unmatched
        
        if df.empty:
            return None
        
        # Parse date: "07-Apr-2026" → "2026-04-07"
        df['date'] = pd.to_datetime(df['DATE1'].str.strip(), format='%d-%b-%Y').dt.strftime('%Y-%m-%d')
        
        # Rename columns to match schema
        result = pd.DataFrame({
            'sid': df['sid'],
            'date': df['date'],
            'open': pd.to_numeric(df['OPEN_PRICE'], errors='coerce'),
            'high': pd.to_numeric(df['HIGH_PRICE'], errors='coerce'),
            'low': pd.to_numeric(df['LOW_PRICE'], errors='coerce'),
            'close': pd.to_numeric(df['CLOSE_PRICE'], errors='coerce'),
            'prev_close': pd.to_numeric(df['PREV_CLOSE'], errors='coerce'),
            'volume': pd.to_numeric(df['TTL_TRD_QNTY'], errors='coerce'),
            'traded_value': pd.to_numeric(df['TURNOVER_LACS'], errors='coerce'),
            'num_trades': pd.to_numeric(df['NO_OF_TRADES'], errors='coerce'),
            'delivered_qty': pd.to_numeric(df['DELIV_QTY'], errors='coerce'),
            'delivery_pct': pd.to_numeric(df['DELIV_PER'], errors='coerce'),
        })
        return result
    except Exception as e:
        print(f"  Error parsing {filepath.name}: {e}")
        return None

# Test with one file
test = parse_bhavcopy(V1 / "data/smart_money/raw/bhav_20260407.csv", ticker_to_sid)
print(f"Test parse: {len(test)} rows")
print(test.head(3).to_string(index=False))

# %%
# === BULK LOAD ALL 922 FILES ===
import time

bhav_files = sorted(glob(str(V1 / "data/smart_money/raw/bhav_*.csv")))
print(f"Found {len(bhav_files)} bhavcopy files")
print(f"Date range: {Path(bhav_files[0]).stem} to {Path(bhav_files[-1]).stem}")

all_dfs = []
errors = 0
for i, f in enumerate(bhav_files):
    df = parse_bhavcopy(Path(f), ticker_to_sid)
    if df is not None:
        all_dfs.append(df)
    else:
        errors += 1
    if (i + 1) % 200 == 0:
        print(f"  Parsed {i+1}/{len(bhav_files)} files...")

prices = pd.concat(all_dfs, ignore_index=True)
print(f"\nTotal rows: {len(prices):,}")
print(f"Unique dates: {prices['date'].nunique()}")
print(f"Unique sids: {prices['sid'].nunique()}")
print(f"Parse errors: {errors}")
print(f"Date range: {prices['date'].min()} to {prices['date'].max()}")

# %%
# === DATA QUALITY CHECKS ===
print("=== Delivery % distribution (all data) ===")
print(prices['delivery_pct'].describe())
print(f"\nNull delivery_pct: {prices['delivery_pct'].isnull().sum():,} ({prices['delivery_pct'].isnull().mean()*100:.1f}%)")

print(f"\n=== Negative or >100 delivery_pct ===")
bad_deliv = prices[~prices['delivery_pct'].between(0, 100, inclusive='both') & prices['delivery_pct'].notna()]
print(f"Rows: {len(bad_deliv)}")

print(f"\n=== Zero close prices ===")
print(f"Rows with close=0: {(prices['close'] == 0).sum()}")
print(f"Rows with close<0: {(prices['close'] < 0).sum()}")

print(f"\n=== Stocks per day (recent 10 days) ===")
print(prices.groupby('date').size().tail(10))

# %%
# === INSERT INTO stock_prices ===
# Clip delivery_pct to 0-100 (same floating point noise fix as shareholding)
prices['delivery_pct'] = prices['delivery_pct'].clip(lower=0, upper=100)

# Insert in chunks to avoid memory issues
CHUNK = 50_000
total_inserted = 0
for i in range(0, len(prices), CHUNK):
    chunk = prices.iloc[i:i+CHUNK]
    rows = insert_df(chunk, "stock_prices")
    total_inserted += rows
    print(f"  Chunk {i//CHUNK + 1}: {rows} rows inserted")

print(f"\nTotal inserted: {total_inserted:,}")

# Verify
from db import table_counts
table_counts()

# %%
# === QUICK SANITY: RELI price history ===
from db import read_sql

reli = read_sql("SELECT date, close, delivery_pct FROM stock_prices WHERE sid='RELI' ORDER BY date DESC LIMIT 10")
print("=== RELI last 10 trading days ===")
print(reli.to_string(index=False))

# Coverage by tier
coverage = read_sql("""
    SELECT s.cap_tier, 
           COUNT(DISTINCT p.sid) as stocks_with_prices,
           COUNT(DISTINCT s.sid) as total_stocks
    FROM stocks s
    LEFT JOIN stock_prices p ON s.sid = p.sid
    GROUP BY s.cap_tier
    ORDER BY s.cap_tier
""")
coverage['pct'] = (coverage['stocks_with_prices'] / coverage['total_stocks'] * 100).round(1)
print(f"\n=== Price coverage by tier ===")
print(coverage.to_string(index=False))
