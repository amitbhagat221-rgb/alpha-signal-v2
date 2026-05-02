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
# # 05 — Remaining Sources: VIX, Insider, News, Bulk Deals, Earnings, Macro
#
# **Tables to populate:**
# - `vix_history` — India VIX daily (736 rows)
# - `regime_state` — current VIX regime (1 row)
# - `insider_trades` — BSE/NSE insider trades (111,420 rows pre-dedup)
# - `news_articles` + `news_article_stocks` — RSS news (2,972 rows)
# - `bulk_deals` — NSE bulk/block deals (125 rows)
# - `earnings_calendar` — NSE events (130 rows)
# - `macro_indicators` — RBI/PIB/GST (22 rows)

# %%
import pandas as pd
import json
from pathlib import Path
import sys

V1 = Path.home() / "alpha-signal"
sys.path.insert(0, str(Path.home() / "alpha-signal-v2"))
from db import get_db, upsert_df, insert_df, read_table, read_sql, table_counts

stocks = read_table("stocks")
valid_sids = set(stocks['sid'])
ticker_to_sid = dict(zip(stocks['ticker'].str.strip(), stocks['sid']))
print(f"Universe: {len(valid_sids)} stocks loaded")

# %% [markdown]
# ## 1. VIX History + Regime State

# %%
# === VIX HISTORY ===
vix = pd.read_csv(V1 / "data/reference/india_vix.csv")
print(f"VIX: {vix.shape}, columns: {list(vix.columns)}")
print(f"Date range: {vix['date'].min()} to {vix['date'].max()}")
print(f"VIX range: {vix['vix'].min():.1f} to {vix['vix'].max():.1f}")
print(f"Nulls: {vix['vix'].isnull().sum()}")

rows = upsert_df(vix, "vix_history")
print(f"\nvix_history: {rows} rows inserted")

# === REGIME STATE ===
with open(V1 / "data/reference/regime_state.json") as f:
    regime = json.load(f)

print(f"\nRegime: {regime['regime']} since {regime['regime_since']}")
print(f"VIX: {regime['vix_close']}, Allocation: {regime['allocation']}")

regime_df = pd.DataFrame([{
    'id': 1,
    'regime': regime['regime'],
    'vix_latest': regime['vix_close'],
    'alloc_large': regime['allocation']['LARGE'],
    'alloc_mid': regime['allocation']['MID'],
    'alloc_small': regime['allocation']['SMALL'],
}])
rows = upsert_df(regime_df, "regime_state")
print(f"regime_state: {rows} row inserted")

# %% [markdown]
# ## 2. Insider Trades
#
# **WARNING:** CSV columns are misaligned. Actual mapping:
# - `transaction_type` column → actually contains **shares** (count)
# - `shares` column → actually contains **value** (rupees)  
# - `value_lakhs` column → actually contains **transaction_type** (Buy/Sell)

# %%
# === INSIDER TRADES ===
ins = pd.read_csv(V1 / "data/insider/insider_archive.csv")
print(f"Raw insider: {ins.shape}")

# Fix misaligned columns
# CSV header says: symbol, company_name, person, category_person, transaction_type, shares, value_lakhs, date, source, value, matched_symbol
# But actual data: symbol, company_name, person, category_person, SHARES, VALUE_RUPEES, BUY_SELL, date, source, value, matched_symbol
ins = ins.rename(columns={
    'transaction_type': 'shares_actual',
    'shares': 'value_actual', 
    'value_lakhs': 'transaction_type_actual',
})

# Convert value from rupees to lakhs
ins['shares'] = pd.to_numeric(ins['shares_actual'], errors='coerce')
ins['value_lakhs'] = pd.to_numeric(ins['value_actual'], errors='coerce') / 100000
ins['transaction_type'] = ins['transaction_type_actual']

# Map matched_symbol (ticker) to sid
ins['sid'] = ins['matched_symbol'].str.strip().map(ticker_to_sid)
print(f"Matched to universe: {ins['sid'].notna().sum()} of {len(ins)}")

# Filter to valid sids only
ins_clean = ins[ins['sid'].notna()].copy()

# Parse date: "15-Mar-2026 18:32" → "2026-03-15"
ins_clean['trade_date'] = pd.to_datetime(ins_clean['date'], format='mixed', dayfirst=True).dt.strftime('%Y-%m-%d')

print(f"\nSample (fixed columns):")
print(ins_clean[['sid', 'person', 'category_person', 'transaction_type', 
                  'shares', 'value_lakhs', 'trade_date', 'source']].head(5).to_string(index=False))

# %%
# Insert insider trades — UNIQUE constraint handles dedup
ins_insert = ins_clean[['sid', 'symbol', 'company_name', 'person', 'category_person',
                         'transaction_type', 'shares', 'value_lakhs', 'trade_date', 'source']].copy()
# Rename to match schema
ins_insert = ins_insert.rename(columns={'category_person': 'person_category'})

rows = insert_df(ins_insert, "insider_trades")
print(f"insider_trades: {rows} rows inserted (from {len(ins_insert)} — rest deduped by UNIQUE constraint)")

# Dedup stats
print(f"Dedup ratio: {(1 - rows/len(ins_insert))*100:.1f}% duplicates removed")

# %% [markdown]
# ## 3. News Articles

# %%
# === NEWS ARTICLES ===
news = pd.read_csv(V1 / "data/news/news_archive.csv")
print(f"News: {news.shape}")
print(f"Columns: {list(news.columns)}")
print(f"Date range: {news['published_at'].min()} to {news['published_at'].max()}")
print(f"Sources: {news['source'].nunique()} unique")
print(news['source'].value_counts().head(10))

# Insert articles
news_articles = news[['article_id', 'title', 'summary', 'url', 'source', 
                       'published_at', 'fetched_at']].copy()
rows = insert_df(news_articles, "news_articles")
print(f"\nnews_articles: {rows} rows inserted")

# Parse symbols_str into junction table
# symbols_str contains comma-separated tickers like "BANKBARODA,HDFCLIFE"
junction_rows = []
for _, row in news.iterrows():
    if pd.isna(row['symbols_str']) or row['symbols_str'] == '':
        continue
    for ticker in str(row['symbols_str']).split(','):
        ticker = ticker.strip()
        sid = ticker_to_sid.get(ticker)
        if sid:
            junction_rows.append({
                'article_id': row['article_id'],
                'sid': sid,
            })

junction_df = pd.DataFrame(junction_rows)
print(f"\nJunction rows built: {len(junction_df)} (articles × matched stocks)")
rows = insert_df(junction_df, "news_article_stocks")
print(f"news_article_stocks: {rows} rows inserted")

# %% [markdown]
# ## 4. Bulk Deals, Earnings Calendar, Macro Indicators

# %%
# === BULK DEALS ===
bulk = pd.read_csv(V1 / "data/smart_money/bulk_30d.csv")
print(f"Bulk deals: {bulk.shape}")
print(f"Columns: {list(bulk.columns)}")

# Map symbol to sid
bulk['sid'] = bulk['symbol'].str.strip().map(ticker_to_sid)
bulk_clean = bulk[bulk['sid'].notna()].copy()
print(f"Matched to universe: {len(bulk_clean)} of {len(bulk)}")

# The bulk CSV has aggregated data (net_buy_qty, buy_deals, sell_deals etc.)
# Schema expects individual deals. This is already aggregated — insert as-is
# but we need to reshape to match schema
# Actually let's check what columns we have vs schema
print(f"\nBulk columns: {list(bulk.columns)}")
print(bulk.head(3).to_string(index=False))

# %%
# NOTE: bulk_30d.csv is AGGREGATED (one row per stock: net_buy_qty, buy_deals, etc.)
# The schema `bulk_deals` expects INDIVIDUAL deals (client_name, deal_date, quantity, price)
# The raw individual deals may be in smart_money/raw/bulk_*.csv files
# For now, let's check if raw bulk deal files exist

from glob import glob
raw_bulk = glob(str(V1 / "data/smart_money/raw/bulk_*.csv"))
print(f"Raw bulk deal files: {len(raw_bulk)}")
if raw_bulk:
    sample_bulk = pd.read_csv(raw_bulk[-1])
    print(f"Latest bulk file: {Path(raw_bulk[-1]).name}")
    print(f"Shape: {sample_bulk.shape}, Columns: {list(sample_bulk.columns)}")
    print(sample_bulk.head(3).to_string(index=False))

# %%
# === EARNINGS CALENDAR ===
earn = pd.read_csv(V1 / "data/events/earnings_calendar.csv")
print(f"Earnings calendar: {earn.shape}")
print(f"Columns: {list(earn.columns)}")
print(earn.head(3).to_string(index=False))

# Map sid — the CSV already has sid column
earn_clean = earn[earn['sid'].isin(valid_sids)].copy()
print(f"\nMatched to universe: {len(earn_clean)} of {len(earn)}")

earn_cols = ['date', 'symbol', 'sid', 'company', 'purpose', 'bm_desc', 'added_date']
# Only keep columns that exist in CSV
earn_cols_exist = [c for c in earn_cols if c in earn_clean.columns]
earn_insert = earn_clean[earn_cols_exist]

rows = insert_df(earn_insert, "earnings_calendar")
print(f"earnings_calendar: {rows} rows inserted")

# %%
# === MACRO INDICATORS ===
macro = pd.read_csv(V1 / "data/macro/macro_pulse.csv")
print(f"Macro indicators: {macro.shape}")
print(f"Columns: {list(macro.columns)}")
print(macro.head(5).to_string(index=False))

# Schema: indicator, signal, value, detail, snapshot_date
# CSV has: indicator, signal, value, detail, updated
macro_insert = macro.rename(columns={'updated': 'snapshot_date'})
macro_cols = ['indicator', 'signal', 'value', 'detail', 'snapshot_date']
macro_cols_exist = [c for c in macro_cols if c in macro_insert.columns]
macro_insert = macro_insert[macro_cols_exist]

rows = upsert_df(macro_insert, "macro_indicators")
print(f"\nmacro_indicators: {rows} rows inserted")

# %% [markdown]
# ## Final Verification

# %%
# === FINAL TABLE COUNTS ===
print("=" * 50)
print("ALL RAW DATA TABLES — FINAL STATUS")
print("=" * 50)
table_counts()

# Summary of what's populated vs empty
print("\n\nPhase 1 migration complete. Computed signal tables are intentionally empty —")
print("they will be recomputed from raw data in Phase 5.")
