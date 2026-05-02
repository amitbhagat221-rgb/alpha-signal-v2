# Alpha Signal — Data Source Strategy

> Audit every source. Pick the best. Build once on correct foundations.
>
> Created: 2026-04-09 | Owner: Amit Bhagat

---

## Current Source Inventory

We use **7 external sources** across 14 harvester scripts. Here's what each gives us,
what's wrong with it, and what to do about it.

---

### SOURCE 1: yfinance (Yahoo Finance)

**Currently used for:**
| Data | Script | Frequency |
|------|--------|-----------|
| OHLCV prices (1yr, .NS suffix) | `02_fetch_price_data.py` | Weekly |
| Stock fundamentals (PE, PB, ROE, margins) | `02_fetch_price_data.py` | Weekly |
| India VIX (^INDIAVIX) | `33_regime_module.py` | Daily |
| Annual financial statements (for Beneish/Altman) | `17_forensic_guard.py` | Daily (7-day cache) |
| 3yr price history (backtest) | `24_backtester.py` / `38_signal_reconstructor.py` | Ad-hoc |

**What's good:**
- Free, no API key, no IP blocking
- Easy Python API
- Covers all Indian stocks with .NS suffix
- Reliable for large/mid caps

**What's wrong:**
- **OHLCV accuracy:** Yahoo adjusts prices retroactively (corporate actions, dividends). NSE bhavcopy is the authoritative source for Indian markets.
- **Fundamentals are incomplete:** Many Indian small caps return `None` for PE, PB, ROE. Fields vary across stocks. Not a structured API — it scrapes Yahoo Finance.
- **No delivery %:** This is a critical signal for us (informed accumulation). Only available from NSE bhavcopy.
- **No intraday volume breakdown:** Yahoo gives total volume. NSE bhavcopy splits traded vs delivered.
- **Financial statements unreliable:** Column names vary (`Total Revenue` vs `Revenue` vs `Operating Revenue`). The forensic guard script tries 6 aliases per field.
- **Rate limits:** Throttles after ~15 rapid requests. No official API guarantee — can break without notice.

**VERDICT: REPLACE for prices. KEEP for VIX only.**

---

### SOURCE 2: NSE Archives (archives.nseindia.com)

**Currently used for:**
| Data | Script | Frequency |
|------|--------|-----------|
| Bhavcopy (delivery %) | `16_smart_money.py` | Daily |
| Bulk deals | `16_smart_money.py` | Daily |
| Block deals | `16_smart_money.py` | Daily |
| Earnings calendar | `18_earnings_calendar.py` | Daily |

**URLs:**
```
Bhavcopy:  https://archives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv
Bulk:      https://archives.nseindia.com/content/equities/bulk.csv
Block:     https://archives.nseindia.com/content/equities/block.csv
Events:    https://archives.nseindia.com/event-calendar (via www.nseindia.com/api)
```

**What's good:**
- **Authoritative source.** NSE is the exchange. This is the actual trade data.
- **Bhavcopy has EVERYTHING:** Symbol, series, open, high, low, close, last, prev_close, total_traded_qty, total_traded_value, total_trades, delivered_qty, delivery_pct
- **Not blocked** from Oracle Cloud IPs (unlike www.nseindia.com main site)
- **Free, daily, reliable**
- Already proven to work in our pipeline (smart_money fetches it daily)

**What's wrong:**
- Only gives **one day at a time** — building history requires iterating over dates
- Needs User-Agent spoofing (browser headers)
- 2-second delay between requests required
- Weekend/holiday files don't exist (need fallback logic)

**VERDICT: PROMOTE to primary OHLCV source. Already works, already in our codebase.**

---

### SOURCE 3: Tickertape (tickertape.in)

**Currently used for:**
| Data | Script | Frequency |
|------|--------|-----------|
| Income statements (quarterly, 10Q) | `22_data_harvester.py` | Monthly |
| Balance sheets (annual, 10yr) | `22_data_harvester.py` | Monthly |
| Cash flow (annual, 10yr) | `22_data_harvester.py` | Monthly |
| Shareholding (quarterly, 6Q) | `22_data_harvester.py` | Monthly |
| Key ratios | `22_data_harvester.py` | Monthly |
| Analyst consensus (latest) | `25_analyst_harvester.py` | Monthly |
| Forecast history (PT, EPS, revenue) | `31_forecast_history_harvester.py` | Monthly |
| Slug discovery | `23_slug_mapper.py` | One-time |
| Universe building (screener) | `22_data_harvester.py` | One-time (broken) |

**Two access methods:**
1. **Tier 1 (SID-based JSON API):** `Bharat_sm_data` package → income, BS, CF, shareholding, ratios
2. **Tier 2 (__NEXT_DATA__ scrape):** Parse hidden JSON in HTML pages → analyst data, forecast history

**What's good:**
- **Best source for Indian fundamentals.** Structured, clean, quarterly granularity
- **Covers 2,500+ stocks** including small caps
- **Shareholding data** (promoter %, FII %, MF %, pledge %) — not available elsewhere for free
- **Analyst consensus** — only free source for this
- **Forecast history** — time series of analyst revisions, unique dataset

**What's wrong:**
- **Screener endpoint blocked** from Oracle Cloud IPs (hence `build_universe()` is broken)
- **No official API** — both methods are reverse-engineered scrapes that can break
- **2s delay required** — harvesting 2,500 stocks takes hours
- **Tier 2 depends on slug mapping** — slug_mapper must run first
- **Analyst coverage sparse** for small caps (~1,000 of 2,500 have data)

**VERDICT: KEEP. Irreplaceable for Indian fundamentals. No free alternative exists.**

---

### SOURCE 4: BSE/NSE Insider APIs

**Currently used for:**
| Data | Script | Source |
|------|--------|--------|
| Insider trades | `09_insider_tracker.py` | BSE package, NSE API, Trendlyne, BSE scrape |

**What's good:**
- 4-source cascading fallback (if one fails, tries next)
- Captures promoter buying/selling, pledge events

**What's wrong:**
- **NSE main API blocked** from Oracle Cloud IPs
- **BSE package is flaky** — sometimes returns empty
- **Trendlyne scrape is fragile** — HTML structure changes break it
- **No trade size filtering** — ₹10,000 trade treated same as ₹10 crore
- **No deduplication** in archive (11MB of duplicates)

**VERDICT: KEEP but improve.** Add trade value thresholds. Fix dedup. Consider SEBI SAST filings as additional source (more reliable than scraping).

---

### SOURCE 5: RSS Feeds (News)

**Currently used for:**
| Data | Script | Sources |
|------|--------|---------|
| Financial news | `06_fetch_news.py` | MoneyControl, ET, LiveMint, BS (11 feeds) |

**What's good:**
- Free, no auth, reliable RSS protocol
- Good coverage of large/mid cap news
- 4 major Indian financial publications

**What's wrong:**
- **Only covers Nifty 500** (entity matching uses `nifty500_list.csv`)
- **No small cap coverage** — smaller companies rarely appear in major publications
- **RSS is headline-only** — no full article text (paywalled)
- **VADER sentiment is crude** — financial language nuance lost

**VERDICT: KEEP but expand universe matching to 2,500 stocks. Consider adding Pulse by Zerodha RSS or Finshots for broader coverage.**

---

### SOURCE 6: Government / Macro APIs

**Currently used for:**
| Data | Script | Sources |
|------|--------|---------|
| GST collections | `14_macro_pulse.py` | ClearTax + PIB |
| Core industries | `14_macro_pulse.py` | PIB + eaindustry.nic.in |
| IIP | `14_macro_pulse.py` | data.gov.in |
| Credit growth | `14_macro_pulse.py` | RBI DBIE |

**What's wrong:**
- All scraping-based — HTML changes break extraction
- Feb 2026 hardcoded fallback for everything
- Monthly data at best — not timely
- data.gov.in requires API key

**VERDICT: KEEP but low priority for improvement. Macro signals have limited predictive power at the individual stock level. The sector-level routing is useful but doesn't need real-time accuracy.**

---

### SOURCE 7: Google Trends (pytrends)

**Currently used for:** `12_google_trends.py`
**Status:** **DEAD.** Produces 0 rows. Rate-limited/blocked.

**VERDICT: DELETE. Google Trends is unreliable for systematic trading. The signal was never validated.**

---

## The Strategic Redesign

### What Changes

| Data Need | Current Source | New Source | Why |
|-----------|---------------|-----------|-----|
| **Daily OHLCV** | yfinance | **NSE Bhavcopy** | Authoritative, already fetched daily, includes delivery % |
| **Historical OHLCV (3yr)** | yfinance | **NSE Bhavcopy backfill** + yfinance fallback | Build history from daily bhavcopy going forward; use yfinance for pre-existing history |
| **Stock fundamentals (PE, PB, etc.)** | yfinance `ticker.info` | **Tickertape key ratios** | Already have this data in `22_data_harvester.py` — more complete, more reliable |
| **Financial statements (for forensic)** | yfinance annual statements | **Tickertape income/BS/CF** | Already harvested, structured, clean. No field name guessing. |
| **India VIX** | yfinance ^INDIAVIX | **Keep yfinance** | Works well, no alternative needed |
| **Delivery %** | NSE bhavcopy (via smart_money) | **NSE bhavcopy (promoted)** | Already have it — just need to also use it for price data |
| **Universe definition** | 3 files | **Single `stocks` table** | Built from Tickertape screener + NSE bhavcopy validation |
| **Google Trends** | pytrends | **DELETE** | Dead signal, never validated |

### What Stays the Same

| Data Need | Source | Reason |
|-----------|--------|--------|
| Quarterly income, BS, CF, shareholding | Tickertape | Irreplaceable for Indian markets |
| Analyst consensus + forecast history | Tickertape | Only free source |
| Insider trades | BSE/NSE/Trendlyne | 4-source cascade is robust enough |
| News | RSS feeds | Free, reliable, good coverage |
| Macro indicators | Government APIs | Low priority, adequate |

---

## The Bhavcopy Upgrade — Detailed Plan

This is the biggest change. NSE bhavcopy replaces yfinance as the primary price source.

### What bhavcopy gives us (that yfinance doesn't):

```
sec_bhavdata_full_{DDMMYYYY}.csv columns:
─────────────────────────────────────────
SYMBOL          NSE ticker
SERIES          EQ (equity), BE (book entry), etc.
OPEN            Opening price
HIGH            Day high
LOW             Day low
CLOSE           Closing price (official)
LAST            Last traded price
PREVCLOSE       Previous day close
TOTTRDQTY       Total traded quantity
TOTTRDVAL       Total traded value (₹)
TIMESTAMP       Trade date
TOTALTRADES     Number of trades
ISIN            ISIN code
DELIVQTY        Delivered quantity        ← NOT IN YFINANCE
DELIVPCT        Delivery %                ← NOT IN YFINANCE
```

### Migration plan:

**Step 1: Build bhavcopy backfill script**
```python
# tasks/fetch_bhavcopy.py
# Fetch bhavcopy for date range, write to stock_prices table
# Filter: SERIES = 'EQ' only (ignore derivatives)
# Map: SYMBOL → sid via stocks table
# Store: OHLCV + delivery_qty + delivery_pct
```

**Step 2: Backfill 3 years of history**
- ~750 trading days × 1 CSV per day
- Each CSV has ~2,000-3,000 rows (all traded stocks)
- Total: ~2M rows in `stock_prices` table
- At 2s/request: ~25 minutes for full backfill
- Can parallelize with 5 concurrent fetchers: ~5 minutes

**Step 3: Daily bhavcopy fetch (replaces yfinance)**
- Fetch today's bhavcopy in the daily pipeline
- Insert into `stock_prices` table
- Delivery % automatically available for all signals

**Step 4: Retire yfinance for OHLCV**
- Keep yfinance ONLY for India VIX
- Delete `02_fetch_price_data.py`
- Delete `data/price_data/*.csv` (501 individual files → single DB table)

**Step 5: Update stock_prices schema**
```sql
CREATE TABLE stock_prices (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    date            TEXT NOT NULL,
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL NOT NULL,
    prev_close      REAL,
    volume          INTEGER,                   -- total traded qty
    traded_value    REAL,                      -- total traded value ₹
    num_trades      INTEGER,                   -- number of trades
    delivered_qty   INTEGER,                   -- delivered quantity
    delivery_pct    REAL,                      -- delivery % (key signal)
    source          TEXT DEFAULT 'bhavcopy',   -- 'bhavcopy' or 'yfinance' (legacy)
    PRIMARY KEY (sid, date)
);
```

### What this enables:

1. **Delivery % available for ALL stocks, ALL days** — currently only 30-day window in smart_money
2. **Volume quality signal:** `delivery_pct > 50%` = informed accumulation
3. **No more yfinance price discrepancies** (adjusted vs unadjusted confusion)
4. **Single source of truth for prices** — one table, not 501 files
5. **Backtest accuracy:** NSE official close prices, not Yahoo approximations

---

## The Tickertape Consolidation

### Currently: 4 scripts hit Tickertape separately

```
22_data_harvester.py     → Tier 1 API (income, BS, CF, shareholding, ratios)
23_slug_mapper.py        → HTTP redirect discovery
25_analyst_harvester.py  → Tier 2 __NEXT_DATA__ (consensus)
31_forecast_history.py   → Tier 2 __NEXT_DATA__ (forecast arrays)
```

### Proposed: 1 unified harvester

```
tasks/harvest_tickertape.py
  ├─ Phase 1: Tier 1 API (fundamentals) — all 2,500 stocks
  │   ├─ quarterly_income
  │   ├─ annual_balance_sheet
  │   ├─ annual_cash_flow
  │   ├─ shareholding
  │   └─ key_ratios → merge into stocks table (PE, PB, ROE, etc.)
  │
  ├─ Phase 2: Slug discovery (only for stocks missing slugs)
  │
  └─ Phase 3: Tier 2 scrape (analyst data) — only stocks with slugs
      ├─ analyst_consensus
      └─ forecast_history
```

**Benefits:**
- Single checkpoint file, single resume logic
- Rate limiting coordinated (not 4 separate 2s delays hitting same server)
- Slug discovery happens inline, not as a separate script
- Can prioritize: large caps first (most analyst coverage), small caps last

---

## Implementation Order

```
Phase 0: Delete dead code                           ← NOW
  ├─ Delete 12_google_trends.py (dead signal)
  ├─ Move .bak files to scripts/legacy/
  └─ Delete 06_fetch_news_v1_backup.py

Phase 1: Build SQLite + bhavcopy foundation          ← WEEK 1
  ├─ Create schema.sql with all tables
  ├─ Create database.py helper
  ├─ Build bhavcopy backfill script (3yr history)
  ├─ Migrate existing CSVs to SQLite
  └─ Verify: row counts match, prices match yfinance ±0.5%

Phase 2: Wire Prefect flows                          ← WEEK 2
  ├─ Install Prefect, register with Cloud (free tier)
  ├─ Build daily_pipeline flow (tasks read/write DB)
  ├─ News → sentiment → classify (Branch A)
  ├─ Insiders, macro, smart money, VIX (Branches B-E)
  └─ Parallel test: CSV pipeline still running as backup

Phase 3: Signals + integration                       ← WEEK 3
  ├─ Piotroski, accruals, consensus, promoter → DB tasks
  ├─ Screener + integrate → daily_picks table
  ├─ Snapshot archiver → daily_snapshots table
  ├─ Dossier + email (keep mostly as-is)
  └─ Retire CSV pipeline, switch cron to Prefect

Phase 4: Consolidate Tickertape + weekend flow       ← WEEK 4
  ├─ Unified Tickertape harvester
  ├─ Weekend refresh flow (universe + metadata + prices)
  ├─ Monthly harvest flow (financials)
  └─ Retire old scripts to legacy/

Phase 5: Tests + monitoring                          ← WEEK 5
  ├─ Smoke tests, contract tests, regression tests
  ├─ Prefect Cloud notifications on failure
  └─ Data hygiene automation
```

---

## Decisions Confirmed

| Decision | Choice | Reason |
|----------|--------|--------|
| Prefect hosting | **Cloud Free tier** | UI hosted, no server to maintain, mobile alerts |
| Primary price source | **NSE Bhavcopy** | Authoritative, includes delivery %, already working |
| VIX source | **yfinance (keep)** | Works well, no alternative needed |
| Fundamentals source | **Tickertape (keep)** | Irreplaceable for Indian markets |
| Google Trends | **DELETE** | Dead, never validated |
| Legacy scripts | **Move to scripts/legacy/** | Keep for reference during migration |
| Parallel operation | **2-3 days** | Verify before switching |
| Migration to SQLite | **After data source audit** | Don't migrate wrong data |
