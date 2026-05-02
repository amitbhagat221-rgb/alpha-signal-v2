---
Status: 
Created: 2026-04-10
Last updated: 2026-04-10
Owner: Amit Bhagat
Implementation: 
Related ADRs: 
---

# Macro Data Plan — From 22 Static Rows to a Historical Signal Engine

> The gap: our macro signal has no history. Can't backtest it, can't validate it,
> can't catch the next E20 regulation before it moves sugar stocks 40%.
>
> Created: 2026-04-10 | Owner: Amit Bhagat

---

## The Problem

Current state: 22 rows in `macro_indicators`, single snapshot date, no history.
The `macro_sector_signals` maps these to 18 sectors but it's static — yesterday's
score = today's score = tomorrow's score. Useless for signal validation.

What we need: **36 months of monthly macro data** across 50+ indicators, mapped to
sectors with directional weights, so we can backtest whether macro tilts actually
predict sector returns.

---

## The Three Data Tiers

### Tier 1: Market Proxies (yfinance — instant, daily, 3yr history)

These are the **fastest signals** — they move in real time, no publication lag.
Available right now with zero setup.

| Indicator | Ticker | Sector Impact | Signal Type |
|-----------|--------|--------------|-------------|
| **India VIX** | `^INDIAVIX` | All (regime) | Leading |
| **Nifty 50** | `^NSEI` | All (breadth) | Coincident |
| **Bank Nifty** | `^NSEBANK` | Financials | Coincident |
| **Nifty IT** | `^CNXIT` | IT | Coincident |
| **Nifty Metal** | `^CNXMETAL` | Materials, Mining | Coincident |
| **Nifty Realty** | `^CNXREALTY` | Real Estate, Construction | Coincident |
| **Nifty Pharma** | `^CNXPHARMA` | Health Care | Coincident |
| **Nifty Auto** | `^CNXAUTO` | Automobiles | Coincident |
| **Nifty FMCG** | `^CNXFMCG` | Consumer Staples | Coincident |
| **Nifty Energy** | `^CNXENERGY` | Energy, Oil & Gas | Coincident |
| **Nifty Infra** | `^CNXINFRA` | Industrials, Construction | Coincident |
| **Nifty PSU Bank** | `^CNXPSUBANK` | Banks (PSU) | Coincident |
| **Nifty Media** | `^CNXMEDIA` | Media | Coincident |
| **Brent Crude** | `BZ=F` | Energy (-), Chemicals (-) | Leading |
| **Gold** | `GC=F` | Materials, Safe haven | Leading |
| **Copper** | `HG=F` | Materials, Industrials | Leading |
| **Aluminium** | `ALI=F` | Materials | Leading |
| **Silver** | `SI=F` | Materials | Leading |
| **USD/INR** | `USDINR=X` | IT (+), Oil (-), Pharma (+) | Coincident |
| **US 10Y Yield** | `^TNX` | All (global liquidity) | Leading |

**Total: 20 tickers, ~750 daily rows each = ~15,000 rows for 3 years.**
Fetch time: ~30 seconds total.

---

### Tier 2: Government Statistics (data.gov.in — monthly, 3yr history)

These are **fundamental economic indicators** — slower but deeper signal.
User has API key. The `datagovindia` Python package is already installed.

| Dataset | Resource ID | Frequency | Lag | Sector Impact |
|---------|------------|-----------|-----|---------------|
| **IIP General + Sectoral** | `31d53713-46c6-48bd-951a-4d986272fd96` | Monthly | 6-8 weeks | Manufacturing, Capital Goods, Consumer |
| **CPI All India** (components) | `2a6edbfb-b416-48db-9183-645be023f757` | Monthly | 4-6 weeks | Consumer, FMCG, Food |
| **WPI** (commodity-wise) | `239ac3d0-f08d-40d0-b03c-9b7a426a62d5` | Monthly | 2-4 weeks | Materials, Chemicals, Energy |
| **Eight Core Industries** | `cc473f03-4db1-4c34-949e-481bdb3da490` | Monthly | 4-6 weeks | Steel, Cement, Coal, Oil, Power |
| **GST Monthly Collections** | `3c92ba18-8554-4967-aa8c-5c3afe0b7ba5` | Monthly | 1 week | All (consumption proxy) |
| **Crop Production** | Multiple | Seasonal | Variable | Agriculture, Sugar, Fertilizers |
| **Electricity Generation** | `2eddde2b-4b4d-46f0-915f-bb4ecd8edb27` | Monthly | 4 weeks | Utilities, Power |

**Key IIP sub-indices** (from the IIP dataset — each is a separate row):
- Mining (→ Materials, Mining)
- Manufacturing (→ Industrials, Auto, Consumer)
- Electricity (→ Utilities)
- Capital Goods (→ Capital Goods, Industrials)
- Consumer Durables (→ Consumer Discretionary)
- Consumer Non-Durables (→ FMCG, Consumer Staples)
- Infrastructure Goods (→ Construction, Real Estate)
- Intermediate Goods (→ Chemicals, Materials)

**Key CPI components** (each predicts different sectors):
- Food & Beverages (→ FMCG, Agriculture, Sugar)
- Fuel & Light (→ Energy, Utilities)
- Housing (→ Real Estate)
- Transport & Communication (→ Auto, Telecom)

---

### Tier 3: Central Bank & Trade Data (FRED — monthly, 5yr+ history)

Free, no API key needed. CSV download via direct URL.

| FRED Series | Description | Freq | Impact |
|-------------|------------|------|--------|
| `INDCPIALLMINMEI` | India CPI Index | Monthly | All (inflation) |
| `IRSTCI01INM156N` | India Money Market Rate | Monthly | Financials, Real Estate |
| `XTEXVA01INM667S` | India Exports Value | Monthly | IT, Pharma, Textiles |
| `XTIMVA01INM667S` | India Imports Value | Monthly | Oil, Gold, Electronics |
| `DCOILBRENTEU` | Brent Crude (daily) | Daily | Energy, Chemicals |
| `DEXINUS` | INR/USD (daily) | Daily | IT, Pharma, Oil |

---

## Database Schema

### New table: `macro_history`

Replaces the current flat `macro_indicators` table. Every data point is a time-series row.

```sql
CREATE TABLE IF NOT EXISTS macro_history (
    indicator_id    TEXT NOT NULL,       -- e.g. 'iip_manufacturing', 'cpi_food', 'brent_crude'
    date            TEXT NOT NULL,       -- YYYY-MM-DD (monthly: use 1st of month)
    value           REAL,               -- the actual value (index, %, price)
    yoy_change      REAL,               -- year-over-year % change (computed)
    mom_change      REAL,               -- month-over-month % change (computed)
    source          TEXT,               -- 'data.gov.in', 'yfinance', 'fred'
    category        TEXT,               -- 'leading', 'coincident', 'lagging'
    unit            TEXT,               -- 'index', 'percent', 'inr_cr', 'usd'
    fetched_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (indicator_id, date)
);

CREATE INDEX IF NOT EXISTS idx_macro_history_date ON macro_history(date);
CREATE INDEX IF NOT EXISTS idx_macro_history_category ON macro_history(category);
```

### New table: `macro_indicator_meta`

Registry of all indicators with sector mapping and signal direction.

```sql
CREATE TABLE IF NOT EXISTS macro_indicator_meta (
    indicator_id    TEXT PRIMARY KEY,
    name            TEXT NOT NULL,       -- 'IIP Manufacturing', 'CPI Food'
    source          TEXT NOT NULL,       -- 'data.gov.in', 'yfinance', 'fred'
    source_ref      TEXT,               -- resource_id, ticker, or FRED series
    category        TEXT,               -- 'leading', 'coincident', 'lagging'
    frequency       TEXT DEFAULT 'monthly',
    unit            TEXT,
    description     TEXT
);
```

### New table: `macro_sector_map`

Maps indicators to sectors with direction and weight.

```sql
CREATE TABLE IF NOT EXISTS macro_sector_map (
    indicator_id    TEXT NOT NULL REFERENCES macro_indicator_meta(indicator_id),
    sector          TEXT NOT NULL,
    direction       INTEGER NOT NULL,    -- +1 = bullish when rising, -1 = bearish when rising
    weight          REAL DEFAULT 1.0,    -- relative importance (1.0 = normal)
    rationale       TEXT,               -- why this indicator affects this sector
    PRIMARY KEY (indicator_id, sector)
);
```

---

## Indicator Registry (Full List — 55 indicators)

### A. Market Proxies (20 — yfinance, daily)

| indicator_id | name | ticker | category |
|-------------|------|--------|----------|
| `nifty50` | Nifty 50 | ^NSEI | coincident |
| `bank_nifty` | Bank Nifty | ^NSEBANK | coincident |
| `nifty_it` | Nifty IT | ^CNXIT | coincident |
| `nifty_metal` | Nifty Metal | ^CNXMETAL | coincident |
| `nifty_realty` | Nifty Realty | ^CNXREALTY | coincident |
| `nifty_pharma` | Nifty Pharma | ^CNXPHARMA | coincident |
| `nifty_auto` | Nifty Auto | ^CNXAUTO | coincident |
| `nifty_fmcg` | Nifty FMCG | ^CNXFMCG | coincident |
| `nifty_energy` | Nifty Energy | ^CNXENERGY | coincident |
| `nifty_infra` | Nifty Infra | ^CNXINFRA | coincident |
| `nifty_psubank` | Nifty PSU Bank | ^CNXPSUBANK | coincident |
| `nifty_media` | Nifty Media | ^CNXMEDIA | coincident |
| `india_vix` | India VIX | ^INDIAVIX | leading |
| `brent_crude` | Brent Crude | BZ=F | leading |
| `gold` | Gold | GC=F | leading |
| `copper` | Copper | HG=F | leading |
| `aluminium` | Aluminium | ALI=F | leading |
| `silver` | Silver | SI=F | leading |
| `usdinr` | USD/INR | USDINR=X | coincident |
| `us_10y` | US 10Y Yield | ^TNX | leading |

### B. Government Statistics (25 — data.gov.in, monthly)

| indicator_id | name | resource_id | category |
|-------------|------|------------|----------|
| `iip_general` | IIP General Index | 31d53713... | coincident |
| `iip_mining` | IIP Mining | (subset) | coincident |
| `iip_manufacturing` | IIP Manufacturing | (subset) | coincident |
| `iip_electricity` | IIP Electricity | (subset) | coincident |
| `iip_capital_goods` | IIP Capital Goods | (subset) | coincident |
| `iip_consumer_durables` | IIP Consumer Durables | (subset) | coincident |
| `iip_consumer_nondurables` | IIP Consumer Non-Durables | (subset) | coincident |
