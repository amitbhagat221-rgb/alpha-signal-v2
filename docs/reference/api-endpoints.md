# API Endpoints — Working Catalog

Per-endpoint reference for every external data source v2 calls. Every entry was probed from this VM. Re-verify after long gaps. Strategy doc: [data-playbook.md](data-playbook.md). Last audit: **2026-05-03**.

Tiers: A = free + deep history · B = free + forward-only (must cron) · C = free with caveats · D = paid (see [paid-data-sources.md](paid-data-sources.md)).

## Library install

```bash
pip install --break-system-packages nselib jugaad-data mftool
```

| Library | Version | Use |
|---|---|---|
| `nselib` | 2.5.1 | NSE date-range historical APIs (handles cookie session) |
| `jugaad-data` | 0.33.1 | Alternate NSE wrapper |
| `mftool` | 3.3 | Mutual fund NAV (wraps mfapi.in) |

---

## Tier A — Free, deep history

### NSE bhavcopy (delivery %)
```python
from nselib import capital_market
df = capital_market.bhav_copy_with_delivery(trade_date="03-05-2026")
```
- Date format: `DD-MM-YYYY`
- Confirmed: 3+ years back. Format boundary in 2024 (older format may need separate parser).
- Use: raw price + delivery%

### NSE bulk deals
```python
df = capital_market.bulk_deal_data(from_date="01-06-2023", to_date="03-05-2026")
```
- **3+ years confirmed** (June 2023 → today).
- Unblocks `bulk_deal_signal` which v1 validated at t=2.49 SMALL.
- Status flip: PARTIAL → READY after this.

### NSE block deals
```python
df = capital_market.block_deals_data(from_date=..., to_date=...)
```
- Same range capability as bulk_deal_data. Counterparty data.

### NSE short selling
```python
df = capital_market.short_selling_data(from_date=..., to_date=...)
```
- **2+ years (Jan 2024+)** — brand new signal class, not in v1.

### NSE corporate actions
```python
df = capital_market.corporate_actions_for_equity(from_date=..., to_date=...)
```
- **2+ years (2,246 rows for 2025-2026 alone).**
- Splits, bonuses, dividends. Lets us compute true split-adjusted close ourselves.
- Fixes v1-Adj-Close vs v2-bhavcopy momentum corr 0.67-0.70 issue.

### NSE smart-beta indices (factor benchmarks)
```python
df = capital_market.index_data(index="NIFTY ALPHA 50", from_date=..., to_date=...)
```
- ~10 years for older indices (Alpha 50, NIFTY 50). 2-3y for newer (Value 30, LowVol 30).
- 9 of 12 targeted indices populated as of 2026-05-03 — see `nse_index_history` table.
- Column names matter: `TIMESTAMP`, `OPEN_INDEX_VAL`, `CLOSE_INDEX_VAL`, etc. (NOT `HistoricalDate`/`OPEN`).
- Use: pre-computed factor exposure benchmark. `value_composite` corr to NIFTY200 VALUE 30 = **0.984**.

### NSE futures history per symbol
```python
df = nselib.derivatives.future_price_volume_data(symbol="RELIANCE", ...)
```
- Multi-month history per stock.

### NSE event calendar
```python
df = capital_market.event_calendar_for_equity(...)
```
- Earnings dates, board meetings — forward-looking + recent past.

### Mutual fund NAV — mfapi.in
```
GET https://api.mfapi.in/mf                       → list of all 4,048 schemes
GET https://api.mfapi.in/mf/{scheme_code}         → full NAV history
GET https://api.mfapi.in/mf/{scheme_code}/latest  → latest NAV only
```
- **13 years daily NAV** per scheme (probed scheme 122639 = Parag Parikh Flexi Cap Direct: 3,178 NAV points 2013-05-28 → 2026-04-30).
- Free, no key, no documented rate limit (be polite ~2s).
- 4,048 schemes covers all major fund houses; defunct schemes drop off.

### AMFI NAVAll.txt
```
GET https://www.amfiindia.com/spages/NAVAll.txt
```
- Today's snapshot, all schemes. Accumulate forward for daily granularity.
- mfapi.in is cleaner — prefer that for backfill.

### Tickertape fundamentals
```python
from Fundamentals import TickerTape
```
- 10 years per stock. Quality/Value/Growth factor inputs.
- **Limit:** curated subset — no COGS, SGA, inventory, goodwill. `operating_profit` is 100% NULL.

### Tickertape forecast_history (consensus)
- Annual snapshots, 10 years. Consensus PT, EPS revisions.

### data.gov.in macro
- IIP, CPI, WPI, Core Sector, GST. 3-7 years.
- Use `ITEM_CODE` (e.g. `INDEX_COAL`) not `ITEM_NAME`. Wide format → pivot to long.

### yfinance — VIX, sector indices, commodities, FX
- Reliable for indices (NIFTY 50/500/MIDCAP), commodities (crude, gold), FX (INR pairs).
- **Smart-beta indices fail on yfinance** — alpha/quality/value-named return empty. Use NSE direct.

### FRED — cross-border / US macro
- 5+ years series for India CPI, money market rates, US Treasury yields.

### World Bank India
```
GET https://api.worldbank.org/v2/country/IND/indicator/{code}?format=json
```
- 9-20 years per indicator (GDP, FX, FDI, M2). Annual/quarterly granularity.

### NSE PIT (insider trades)
- 5+ years via NSE archives.
- **Critical:** `secAcq`/`secVal` are real values; `buyQuantity`/`sellquantity` are always 0 (don't use those).

### Regulatory events (PIB + RBI + SEBI + News)
- PIB: 30+ years scrapeable but classifier-gated. RBI: needs 2s delay or blocks.
- See `regulatory_events.classifier_status` for terminal-state tracking.

---

## Tier B — Free, forward-only (no historical archive)

**These all need cron NOW** so future-you has the data. The "v1 sentiment lost"
lesson — daily forward cron at 14:00 UTC = 7:30 PM IST is wired in
[run_daily_forward.sh](../../run_daily_forward.sh).

### NSE FII/DII cash flow
```
GET https://www.nseindia.com/api/fiidiiTradeReact  (needs cookie warm-up)
```
- Daily FII + DII buy/sell/net in ₹Cr. Strongest macro tilt signal.
- Today's row only — must accumulate.

### NSE FII/DII F&O positioning
```python
df = nselib.derivatives.participant_wise_open_interest(trade_date="03-05-2026")
```
- **Dec 2025+ only** (~2 months back). 5 rows/day (Client/DII/FII/Pro categories).
- Future + option long/short OI per category.

### NSE FII/DII F&O volume
```python
df = nselib.derivatives.participant_wise_trading_volume(trade_date=...)
```
- Same shape as above, volume instead of OI.

### NSE ASM / GSM / F&O ban lists
```
ASM: GET https://www.nseindia.com/api/reportASM  (cookie warm)
GSM: similar endpoint
F&O ban: nselib.derivatives.fno_security_in_ban_period
```
- ~250 ASM stocks today; varies daily. Distress / manipulation flag.
- F&O ban size = market stress / vol regime indicator.
- **Known parser bugs** in `pull_surveillance_today()` for GSM and F&O ban
  (`'list' object has no attribute 'get'`). ASM works (146 rows). Fix pending.

### NSE bulk deals — live snapshot
```
GET https://archives.nseindia.com/content/equities/bulk.csv
```
- Today's deals only. nselib backfills history; this is the daily fresh hit.

### NSE corporate announcements
```
GET https://www.nseindia.com/api/corporate-announcements?index=equities
```
- Latest 20-50 announcements. Earlier than RSS news.

### AMFI MF portfolio holdings
- Monthly disclosure PDF. ~5 years history scrapeable but PDF-brittle.
- TBD: stable scraper path.

### VIX term structure
- yfinance + nselib. Vol curve for regime detection.

---

## Tier C — Free with caveats

| Source | Access | Caveat |
|---|---|---|
| AlphaVantage demo | `alphavantage.co/query` | 25 calls/day free. Indian symbols partial. |
| Twelve Data | `api.twelvedata.com` | Limited free tier. Some Indian coverage. |
| SEBI SAST | `sebi.gov.in/sebiweb/...` | HTML scrape only. No clean API. |
| BSE bulk deals | `api.bseindia.com/BseIndiaAPI/...` | Returned 0 entries on probe — may need POST or specific params. Defer. |
| Wayback Machine | `web.archive.org/cdx/search/cdx` | Only 1 snapshot of NSE bulk.csv found. Not useful for backfill. |
| EODHD demo | `eodhd.com/api/eod/{sym}?api_token=demo` | US works (AAPL ✅), Indian symbols 403. |
| Financial Modeling Prep | `financialmodelingprep.com` | Strong on US, India patchy. |

---

## Tier D — Paid (deferred or evaluated)

See [paid-data-sources.md](paid-data-sources.md) for full ranked playbook.

| Source | Cost | Status |
|---|---|---|
| Zerodha Kite Connect | ₹500/mo | Recommended (Phase 3.1c of plan 0002) |
| Screener.in Premium | ₹420/mo | Recommended (Phase 3.1a of plan 0002). NO official API — login + Excel export pattern. |
| EODHD India Fundamentals | $20-60/mo | One-month bursts when extending PIT past 2023 |
| Trendlyne | ~₹500/mo | Backup for nselib data |
| TrueData | ₹500-2000/mo | Tick data + IV surface — only if HFT/options |
| Sensibull | n/a | **Skip** — no retail API; analytics layer over Kite raw data we'd compute ourselves |

---

## NSE quirks (the most common failure modes)

### 1. Cookie-warm trick (the "blocked" myth)

For ANY direct hit to `www.nseindia.com/api/*`, NSE rejects without warmed cookies:

```python
import requests
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
s.get("https://www.nseindia.com", timeout=15)  # warms _abck, bm_sz, etc.
r = s.get("https://www.nseindia.com/api/<endpoint>", timeout=15)
```

This is what v1's CLAUDE.md called "blocked" — it isn't. nselib does this internally.

### 2. Date format mismatches
- nselib functions: `DD-MM-YYYY`
- ISO most other places: `YYYY-MM-DD`
- Mixing them silently returns empty results, not errors.

### 3. Bhavcopy column whitespace
- Columns have leading spaces. **Always** `df.columns = df.columns.str.strip()`.
- Format changed Apr 3, 2026 (simplified). Fetch raw from archives for older.

### 4. PIT API field misuse
- `buyQuantity` / `sellquantity` are **always 0**. Real values: `secAcq`, `secVal`.

### 5. Sentinel dates
- Shareholding has `1899-12-31` rows. Filter out.

### 6. xlrd dependency
- `fii_derivatives_statistics` returns old XLS → needs `xlrd` package.
- Skip; `participant_wise_open_interest` gives equivalent data without xlrd.

### 7. Rate-limit floor
- 2-second delay minimum between any external API calls.
- For long ranges, chunk by month and concatenate — single large requests timeout.
- For very large date windows nselib chunks internally — slow but works.

### 8. Tickertape SID ≠ NSE ticker
- Tickertape uses curated SIDs (e.g. REDY, not DRRD). Always use universe SIDs.

### 9. data.gov.in timeouts
- API sometimes times out. Use `timeout=60` + 3 retries.

### 10. RBI rate-limiting
- 2s delay required between RBI page hits or it blocks.

---

## Things tried and rejected (don't repeat)

| Attempted | Result | Replacement |
|---|---|---|
| yfinance for full smart-beta indices | Only NIFTY 50/500/MIDCAP 150 work; alpha/quality/value-named return empty | NSE direct via `nselib.capital_market.index_data` |
| SEBI direct insider-trade JSON | Page only renders HTML; no JSON endpoint | NSE PIT API |
| AMFI portfolio disclosure direct URL | Old URL 404s | TBD — current page exists but PDF-brittle |
| BSE bulk deals API probe | 0 entries returned | NSE bulk via nselib |
| Bharat-SM-Data | Not investigated; assumed Tickertape-equivalent | — |
| EODHD demo for India | 403 on Indian symbols | Use paid tier or skip |
| Wayback Machine for NSE bulk.csv backfill | 1 snapshot found, useless | nselib date-range backfill |
| Sensibull standalone subscription | No retail API | Compute analytics ourselves from Kite/nselib raw |

---

## After a long gap, before trusting an endpoint

- Hit a known-recent date first (cookie can intermittently fail)
- Check response shape vs schema — NSE silently changes column names
- Verify date format: `DD-MM-YYYY` for nselib, ISO elsewhere
- Strip column whitespace if `KeyError: ' SYMBOL'`
- 403/blocked → cookie warm-up issue, not the endpoint
- Empty result → chunk the date range smaller

## Update protocol

Add/update entries with **probe date**. If an endpoint unblocks a registered signal, flip its status in `db.BACKTEST_SIGNALS`. Promote/demote tier based on actual reliability, not first impression.
