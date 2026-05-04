# Data Playbook

> The institutional memory we keep losing. Every source, every reconstruction
> method that worked, every gotcha we've already hit. Read before fetching;
> update after every data-source incident.
>
> If a future session has to re-discover something already in this doc, the
> doc has failed. Be explicit, be specific, name the file and the column.

**Maintained by:** anyone touching data ingestion or PIT reconstruction.
**Updated:** with every new source, every reconstruction we ship, every issue we resolve.
**Last refresh:** 2026-05-03

---

## How to use this doc

1. **Before fetching a new data source** — search this doc for it. Most things have been tried before in v1 or v2.
2. **Before reconstructing history** — find the *Reconstruction patterns* section. The right pattern is almost always one of five.
3. **When you hit a weird issue** — search *Known issues*. If your issue isn't there, **add it** before moving on.
4. **When a source's coverage changes** — update its row in the source catalog. Stale depth/lag info is worse than no info.

---

## Three principles that override everything

1. **Live data ≠ PIT data.** A snapshot table that overwrites itself (`analyst_consensus`, `regime_state`, every `*_scores` table) cannot be backtested as a time series. If you need history, you need to *capture* history yourself, daily or monthly. There is no "restore from external source" for snapshots once they're overwritten.

2. **Filing lag is a hard rule, not a heuristic.** Annual = 75d, Quarterly = 60d, Shareholding = 21d, Price = 0d. Ignoring this introduces ~37% Piotroski divergence on the latest date alone (we measured this). Lag rules apply *every time* you build a PIT-anchored value.

3. **Reconstruct *and* archive.** The v1 lesson: we ran VADER over news to produce historical `sentiment_scores`, then in v2 we kept only the latest snapshot. The historical CSVs got dropped, the news depth wasn't fully preserved, and we can no longer fully re-derive. **Compute → store → version.** Never rely on re-derivation when the source is gappy.

---

## Source Catalog

For each source: **what it gives**, **endpoint**, **PIT/live access**, **historical access**, **depth available right now in v2**, **gotchas**, **rate limits**.

### NSE Bhavcopy — stock prices + delivery %

| Field | Value |
|---|---|
| **What** | Daily OHLCV + delivery quantity + delivery % per equity. The foundational price series. |
| **Endpoint** | `https://archives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv` (raw archive, the simplified format that started Apr 3 2026 — earlier dates need the `MMM/MMMYYYY` path) |
| **PIT access** | Today's file is published end-of-day. No intraday. Backfill 1 day at a time. |
| **Historical access** | NSE archive holds ~5 years. We have 3+ years (2022-07 → present). |
| **v2 depth** | 917 daily files, 1.3M rows in `stock_prices` |
| **Gotchas** | (1) **Column names have leading spaces** — `.str.strip()` everything before referencing. (2) Format changed Apr 3 2026 — earlier dates need `mmm/mmmYYYY/cmDDmmmYYYYbhav.csv.zip`, simplified after. (3) Filter `series == "EQ"` — bhavcopy includes BE, BL, etc. (4) Raw close is **NOT split-adjusted** — yfinance Adj Close gives different values, momentum signals diverge ~30%. |
| **Rate limit** | 2-second floor between requests; longer (5s) is safer. NSE will block for hours if you batch-blast. |
| **Used by** | `signals/momentum.py`, `signals/smart_money.py`, `tools/reconstruct_pit.py`, screener, every PIT response variable. |

### NSE PIT (Insider Trading)

| Field | Value |
|---|---|
| **What** | Promoter / KMP / director equity transactions disclosed to NSE under SEBI PIT regulations. |
| **Endpoint** | `https://www.nseindia.com/api/corporates-pit?...` (JSON) |
| **PIT access** | Discloses on transaction date — already PIT-clean. |
| **Historical access** | NSE archive goes back ~5 years. We have 2021-01 → 2026-11. |
| **v2 depth** | 26,741 transactions in `insider_trades`, 1,043 stocks |
| **Gotchas** | **`buyQuantity`/`sellquantity` are always 0** — the real values are in `secAcq` and `secVal`. v1 spent 3 weeks on this bug. |
| **Rate limit** | 2-second floor. Session cookies required (set User-Agent + first-hit Cookie). |
| **Used by** | `signals/insider_signal.py` |

### NSE Bulk Deals

| Field | Value |
|---|---|
| **What** | Same-day disclosure of large block trades > ₹10 Cr (or 0.5% of company's equity), client name + qty + price. |
| **Endpoint** | (1) `archives.nseindia.com/content/equities/bulk.csv` (today only). (2) **`nselib.capital_market.bulk_deal_data(from_date, to_date)`** — date-range, **history back to ≥ June 2023**, requires `pip install nselib`. v1's CLAUDE.md said `www.nseindia.com main is blocked` — that was missing-cookie issue, nselib handles it. |
| **PIT access** | Today's file or any past day via nselib. |
| **Historical access** | **2-3 years confirmed via nselib** (probed 2026-05-03). Jan 2024 returned 3,908 rows; June 2023 returned 1,472 rows. |
| **v2 depth** | 865 deals across 13 dates (legacy archives.nseindia.com fetch). **Backfillable to 3 years via nselib.** |
| **Gotchas** | (1) Date format `DD-MM-YYYY` (not ISO). (2) Symbol matching needs strip+upper. (3) Use 2-second floor between calls; chunk long ranges by month. |
| **Reconstruction** | **No longer BLOCKED** — switch to nselib for backfill. Plan: replace `sources/nse_bulk.py` fetcher's URL with `nselib.capital_market.bulk_deal_data` call. |
| **Used by** | `signals/smart_money.py` |

### Tickertape — Fundamentals (qi, bs, cf, shareholding)

| Field | Value |
|---|---|
| **What** | Quarterly income statement, annual balance sheet, annual cash flow, quarterly shareholding. **The fundamentals backbone.** |
| **Endpoint** | Two-tier API: (1) sid-based `from Fundamentals.TickerTape import Tickertape; tt.get_income_data(sid)` etc. (2) slug-based `__NEXT_DATA__` scrape from page HTML for fields the SDK doesn't expose. |
| **PIT access** | Latest filing per stock; refresh monthly via `run_tickertape_monthly.sh` cron. |
| **Historical access** | Up to ~10 years per stock for income/BS/CF; ~6 quarters for shareholding (window depends on fetch date — older quarters fall off). |
| **v2 depth** | qi: 21,955 rows / 46 quarters · bs: 19,227 rows / 44 years · cf: 19,185 rows · sh: 14,128 rows / 53 quarters |
| **Gotchas** | (1) **SIDs ≠ NSE tickers** — `REDY` not `DRRD`, `BJFN` not `BJFIN`. Always use universe `sid`. (2) `operating_profit` column is **100% NULL** — derive EBITDA = `pbt + interest + (annual_depreciation/4)`. (3) `consolidated` reporting is preferred when present; fall back to `standalone`. (4) **Curated subset** — no COGS, SGA, inventory, goodwill. Beneish reduced to 6-factor as a result. (5) Network blocks: `tickertape.in` and `analyze.api.tickertape.in` work; `get_ticker()` search is blocked, MoneyControl is blocked. |
| **Rate limit** | 2-second floor. Checkpoint every 200 stocks; resume via `harvest_log.json`. |
| **Used by** | `signals/piotroski.py`, `accruals.py`, `forensic.py`, `consensus.py`, plus screener inputs. |

### Tickertape — Analyst Consensus (snapshot)

| Field | Value |
|---|---|
| **What** | Total analysts, buy %, price target, forward EPS, EPS growth %, forward revenue, revenue growth %. |
| **Endpoint** | Slug-based `__NEXT_DATA__` scrape (`analyze.api.tickertape.in`) |
| **PIT access** | Latest snapshot only. Refresh monthly. |
| **Historical access** | **None.** `analyst_consensus` overwrites itself — no historical archive of buy %, PT, etc. |
| **v2 depth** | 2,439 rows (one per stock, current snapshot) |
| **Gotchas** | (1) `has_analyst_data=0` for ~25% of universe (small caps without coverage). (2) Reconstructing historical consensus is **partially feasible from `forecast_history`** (annual snapshots of price targets, EPS, revenue — see Reconstruction Patterns) but no monthly granularity. |
| **Used by** | `signals/consensus.py`, stock_detail Consensus tab |

### Tickertape — Forecast History (dated revisions)

| Field | Value |
|---|---|
| **What** | Time-stamped consensus forecast values: price targets, FY EPS, FY revenue. The closest thing to consensus history we have. |
| **Endpoint** | Slug-based `__NEXT_DATA__` (`forecastsHistory` path) |
| **PIT access** | Pulled at fetch time, dates back to 2015. |
| **Historical access** | 10+ years per metric per stock, but **annual granularity** — not monthly revisions. |
| **v2 depth** | price: 10,543 rows · revenue: 9,235 · eps: 9,235. 2,435 stocks covered. |
| **Gotchas** | (1) `change` column populated for `eps`/`revenue` but **empty for `price`** — compute PT YoY from value series directly. (2) `fetched_at` is the same for all rows (the date of last harvest); the *event* date is in the `date` column. (3) Annual cadence means a "monthly PIT consensus" reconstruction will have 12 dates per stock per year using forward-fill — coarser than v1's "proxy" t=3.52 implied. |
| **Reconstruction** | PROPOSED — see *Pattern 6: Annual-snapshot PIT* below. |
| **Used by** | Currently `signals/consensus.py` (forward EPS revision); intended consumer: `tools/reconstruct_consensus_pit.py`. |

### yfinance — VIX, Sector Indices, Commodities, FX

| Field | Value |
|---|---|
| **What** | India VIX (`^INDIAVIX`), Nifty sector indices (`^CNXIT`, `^CNXMETAL`, etc.), Brent (`BZ=F`), Gold (`GC=F`), USDINR (`USDINR=X`), US 10Y (`^TNX`). 20 tickers total. |
| **Endpoint** | `yfinance` Python lib (Yahoo Finance backend) |
| **PIT access** | Real-time during market hours; daily close after EOD. |
| **Historical access** | 3+ years of daily history available; longer for major tickers. |
| **v2 depth** | vix_history: 757 daily rows · macro_history: 18,284 rows for 50 indicators |
| **Gotchas** | (1) Indian sector index tickers are unstable — `^CNXMETAL` works, others have aliases. Verify before bulk-fetching. (2) Adj Close (split-adjusted) ≠ Close (raw) — for momentum/EY consistency, pick one and stay. (3) Bulk-fetch (yf.download list) is fastest but rate-limited around 50 tickers/request. |
| **Rate limit** | 1-second floor, but yfinance internally batches and caches. Heavy parallel calls get 429-throttled. |
| **Used by** | `signals/macro.py`, `scoring/regime.py`, `sources/macro_yfinance.py` |

### data.gov.in — IIP, CPI, WPI, Core Sector, GST

| Field | Value |
|---|---|
| **What** | Government statistics: IIP general + sectoral subindices, CPI all-India + components, WPI commodity-wise, Eight Core Industries, GST collections, electricity generation. |
| **Endpoint** | `https://api.data.gov.in/resource/{resource_id}` with API key (free tier). `datagovindia` Python package wraps it. |
| **PIT access** | Monthly, with 4-8 week publication lag. |
| **Historical access** | 3-7 years depending on indicator. |
| **v2 depth** | macro_history covers IIP, CPI, WPI, Core Sector since 2022-01 — 1,143 dates × ~50 indicators |
| **Gotchas** | (1) **API timeouts are common** — use 60s timeout + 3 retries. (2) Wide format (months as columns) — needs pivot to long format. (3) For Core Sector: use `ITEM_CODE` (e.g. `INDEX_COAL`) not `ITEM_NAME` (e.g. "Growth of Coal (%)"). (4) GST collections: 1-week lag, fastest of the lot. |
| **Rate limit** | Free tier: 100 calls/day shared across all `data.gov.in` resources. Plan accordingly. |
| **Used by** | `sources/macro_gov.py`, `signals/macro.py` |

### FRED — Cross-border / US macro

| Field | Value |
|---|---|
| **What** | Federal Reserve Economic Data — India CPI series, India money market rate, India trade flows, US 10Y yield, Brent (daily). |
| **Endpoint** | `https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}` (no API key needed for CSV). |
| **PIT access** | Same as data.gov.in — monthly with publication lag. |
| **Historical access** | Generous — most India series go back 5+ years, some 20+. |
| **v2 depth** | (Currently unused; wired for future macro expansion) |
| **Gotchas** | (1) Series codes change occasionally — pin them in config. (2) FRED returns blank rows for missing months — drop NA. |
| **Rate limit** | None for CSV scraping; 120 req/min if using API key. |

### RBI — Circulars + Quarterly Bank Statements

| Field | Value |
|---|---|
| **What** | Monetary policy circulars, banking regulations, bank-by-bank quarterly NIM/GNPA/PCR/CASA (the latter via `Quarterly Publications`). |
| **Endpoint** | (1) `rbi.org.in/Scripts/NotificationUser.aspx` for circulars. (2) `rbi.org.in/Scripts/QuarterlyPublications.aspx` for bank quarterly data (PDF/Excel — needs scraping). |
| **PIT access** | Daily for circulars; quarterly with ~6-week lag for bank data. |
| **Historical access** | Circulars go back 10+ years; bank quarterly data goes back ~5 years. |
| **v2 depth** | 5,687 regulatory_signals classified from regulatory_events; bank metrics not yet ingested |
| **Gotchas** | (1) **2-second delay between requests or RBI blocks**. (2) PDF parsing is brittle; some quarters have format changes. |
| **Used by** | `sources/regulatory_*` (planned), `sources/banking_metrics.py` (planned for D15) |

### SEBI — Circulars

| Field | Value |
|---|---|
| **What** | Market regulator circulars: MF rules, listing rules, disclosure norms. |
| **Endpoint** | `sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=2` |
| **PIT access** | Weekly. |
| **Historical access** | 5+ years on the site. |
| **v2 depth** | Subset captured in regulatory_events |
| **Gotchas** | HTML structure changes occasionally — selector-based scraping breaks. Cache aggressively. |
| **Used by** | `signals/regulatory.py` |

### PIB — Press Information Bureau

| Field | Value |
|---|---|
| **What** | Ministry-wise government press releases — earliest signal of policy changes (e.g. E20 mandate, PLI schemes). |
| **Endpoint** | `pib.gov.in/allRel.aspx` |
| **PIT access** | Daily; 5-20 releases per day. |
| **Historical access** | 10+ years on the site (we have 16,523 events back to 1993). |
| **v2 depth** | 16,523 regulatory_events ingested |
| **Gotchas** | **PIB scraper landmine: saves only at the END of all 110K iterations.** A crash mid-run loses everything. Add incremental save every 1000 events. |
| **Used by** | `signals/regulatory.py`, `regulatory_classifier` (Haiku + Sonnet) |

### nselib (Python lib — UNLOCKS multiple historical APIs)

| Field | Value |
|---|---|
| **What** | Python wrapper around NSE's date-range historical APIs that requires session cookies. v1's CLAUDE.md called these "blocked" — they're not, just need cookie warm-up. nselib handles it. |
| **Install** | `pip install --break-system-packages nselib` (v2.5.1 confirmed working 2026-05-03) |
| **Confirmed-working endpoints** | See [memory/nselib_apis.md](../../../.claude/projects/-home-ubuntu-alpha-signal-v2/memory/nselib_apis.md) for the full table. Highlights: bulk_deal_data + block_deals_data (≥2yr range), corporate_actions_for_equity (splits/divs), short_selling_data (Jan 2024+), bhav_copy_with_delivery, deliverable_position_data per symbol, participant_wise_open_interest (FII/DII positioning, Dec 2025+). |
| **Quirks** | DD-MM-YYYY date format; `xlrd` dep needed for `fii_derivatives_statistics`; some single-day endpoints return "no data available" for arbitrary recent dates. |
| **Rate limit** | Treat as 2-second floor (same NSE rule as bhavcopy). Chunk long ranges by month. |
| **Used by** | (None yet — pending integration as of 2026-05-03) |

### Short Selling — NEW signal class via nselib

| Field | Value |
|---|---|
| **What** | Daily reported short-selling activity per symbol. Quantity sold short. Probed Jan 2025: 675 rows; Jan 2024: 37 rows (data sparser earlier). |
| **Endpoint** | `nselib.capital_market.short_selling_data(from_date, to_date)` |
| **Historical access** | Back to Jan 2024 confirmed; sparse for older dates. |
| **Alpha use** | Short-interest spike = bearish positioning; short squeeze candidate when shorts cover. New signal class not in v1's roster. |
| **Status in v2** | Not yet ingested. PROPOSED for D17 work. |

### Corporate Actions — fixes the Adj-Close issue

| Field | Value |
|---|---|
| **What** | Splits, bonuses, rights, dividends, ex-dates per symbol. The data needed to reconstruct true split-adjusted prices. |
| **Endpoint** | `nselib.capital_market.corporate_actions_for_equity(from_date, to_date)`. Confirmed: 2,246 rows for 2025-2026. |
| **Why important** | Resolves the v1-vs-v2 mom_6m correlation 0.70 issue at the root. v1 used yfinance Adj Close (split-adjusted); v2 uses bhavcopy raw close. With corporate-actions data we can split-adjust the bhavcopy prices ourselves and the divergence disappears. |
| **Status in v2** | Not yet ingested. Single-session integration. |

### FII/DII Positioning (F&O segment) — derivatives flow signal

| Field | Value |
|---|---|
| **What** | Daily participant-wise (Client / DII / FII / Pro) Open Interest and trading volume in F&O. Tells you how each cohort is positioned in futures and options. |
| **Endpoint** | `nselib.derivatives.participant_wise_open_interest(trade_date)` and `participant_wise_trading_volume(trade_date)`. Single-day signature. |
| **Historical access** | **Dec 2025+ only** — must accumulate forward. ~5 months of history available as of 2026-05-03. |
| **Alpha use** | FII net long/short F&O positioning is one of the strongest macro tilts available. Cohort divergence (FII selling vs DII buying) is a regime signal. |
| **Status in v2** | Not yet ingested. Forward accumulation strategy. |

### MF NAV via mfapi.in — free JSON API

| Field | Value |
|---|---|
| **What** | Daily NAV for ~4,048 Indian MF schemes, going back ~13 years (2013-present). Free, no key. |
| **Endpoint** | `https://api.mfapi.in/mf/{scheme_code}` returns full NAV history; `/latest` for the most recent. |
| **Historical depth** | 13 years confirmed for Parag Parikh Flexi Cap (3,178 daily NAVs from 2013-05-28). |
| **Alpha use** | MF NAV trends as flow proxy; top-decile MFs' overweighted stocks as smart-money signal (combine with monthly portfolio disclosure). |
| **Limit** | NAV only — for actual stock holdings need AMFI portfolio disclosures (monthly, ~45-day lag). |
| **Status in v2** | Not yet ingested. Reference: [memory/mfapi_nav.md](../../../.claude/projects/-home-ubuntu-alpha-signal-v2/memory/mfapi_nav.md) |

### Google News RSS

| Field | Value |
|---|---|
| **What** | Financial news headlines + summaries from Indian publications. Used for sentiment + entity matching. |
| **Endpoint** | `https://news.google.com/rss/search?q=...` |
| **PIT access** | Daily polling. |
| **Historical access** | Date-filter queries `after:YYYY-MM-DD before:YYYY-MM-DD` work for 3+ years back. |
| **v2 depth** | **GAP IN HISTORY:** 3,514 articles, 53 dates. Continuous from 2026-03-01; one isolated date in 2024-04 then silence until 2026-02. |
| **Gotchas** | (1) Returns up to 100 items per query — paginate with shifted date windows. (2) Free, no API key. (3) **In v2 we never backfilled the 2024-05 → 2026-01 gap** — sentiment historical reconstruction therefore only feasible 2026-03+. |
| **Rate limit** | 1 req/sec safe. |
| **Used by** | `signals/sentiment.py`, `regulatory_classifier` (one input among many) |

---

## Cross-Cutting Principles

### Filing-lag rules (PIT discipline)

| Filing | Statutory deadline | Use this lag for PIT |
|---|---|---|
| Annual results (BS, CF, full-year P&L) | 75 days post-FY-end | **75d** |
| Quarterly results | 60 days post-Q-end (45 for results, +15 for full filing) | **60d** |
| Shareholding pattern | 21 days post-Q-end | **21d** |
| NSE PIT insider trade | 2 trading days post-trade | **0d** (already PIT) |
| Bulk deal | Same day | **0d** |
| Macro indicator | varies (1w GST, 6-8w IIP, 4-6w CPI) | per-indicator (in `macro_indicator_meta`) |
| News article | published_at field | **0d** |

For each PIT eval date, slice raw data by `record_date + lag <= eval_date`. Anything that's *fetched* but not yet *knowable* is look-ahead and corrupts t-stats.

### Survivorship bias

Universe (`stocks` table) is current names only. Stocks delisted before today are missing entirely. Empirical bias: **~4.4% per year**. For backtests over 3+ years this is material; for monthly t-stats over 6 months it's noise.

**Fix path:** scrape NSE delisted-companies archive, mark with `delisted_date`, include in PIT eval if `delisted_date > snapshot_date`. Substantial work — deferred per Plan 0004 §3.2.

### Look-ahead bias (the live-snapshot trap)

Live snapshot tables (`daily_snapshots`, all `*_scores`, `daily_picks`) include data that has been *fetched*, not just data that was *knowable* on the snapshot date. Empirical: 37% of Piotroski rows differ between live and PIT for 2026-05-01 alone.

**Rule:** for backtests, never read from live snapshot tables. Always read from `daily_snapshots_pit_v1` (canonical historical) or `daily_snapshots_pit` (v2 forward extension).

### Dedup strategies

| Pattern | Use for | SQL |
|---|---|---|
| Append-only | insider_trades, bulk_deals, news_articles | `INSERT OR IGNORE` with UNIQUE constraint |
| Snapshot-replace | analyst_consensus, regime_state, all `*_scores` | `INSERT OR REPLACE` on PRIMARY KEY |

UNIQUE constraints on append-only tables prevent the v1 disaster: insider_archive had 96.5% duplicates because dedup was app-level and broke. Now it's DB-level and unfixable.

### Validation guardrails (per-column range gates)

Every PIT signal column has a `(min_val, max_val)` rule in [`tools/reconstruct_pit.py VALIDATION_RANGES`](../../tools/reconstruct_pit.py). At write time:

1. Replace `±inf` with NaN.
2. Set values outside `[min_val, max_val]` to NaN (not raised — silently dropped to NaN with a count).
3. Track per-column: `n_valid`, `n_nan`, `n_out_of_range`, observed `min`/`max`. Stored as JSON in `pit_reconstruction_log.validation_summary`.
4. Flag any column where `out_of_range > 5%` of rows in the run-end summary.

Why this design: bad data corrupting a column silently is worse than crashing — but crashing on every NaN is too noisy (legitimate NaN is common). Setting outliers to NaN keeps the row but quarantines the bad value. The flag in the run-end output gives early warning.

**Current ranges** (extend as new signals land):

| Signal | Range | Why |
|---|---|---|
| close_price | (0.01, 1M) | Excludes negative prices, sanity-caps top |
| piotroski_f | (0, 9) | Definitionally 0-9 |
| earnings_yield | (-10, 10) | Caps absurd EPS/price ratios |
| book_to_price | (-100, 1000) | Allows negative-equity stocks; caps tail |
| mom_6m / mom_12m | (-100, 100) | Caps risk-adjusted momentum tail |
| mom_composite | (0, 1) | Within-tier rank |
| position_52w | (0, 1) | Within range bounds |
| pledge_quality | (0, 1) | 1 − pct |
| avg_delivery_pct_30d | (0, 100) | Pct |
| delivery_anomaly_z | (-5, 5) | Clip extreme z-scores |
| fwd_return_20d | (-1, 5) | -100% (zero) to 500% — caps takeover blowups |
| m_score | (-20, 20), z_score | (-50, 100) | Forensic outlier caps |

### Checkpoint & resume (no progress lost)

`tools/reconstruct_pit.py` writes a `pit_reconstruction_log` row before any work for an eval_date and updates it to SUCCESS / FAILED on completion. Each row:

```
id, eval_date, signals_run, rows_attempted, rows_written,
validation_summary (JSON), started_at, finished_at, duration_sec,
status (RUNNING/SUCCESS/FAILED/SKIPPED), error_message
```

**Three properties this gives us:**

1. **Crash recovery:** if reconstruction crashes mid-run, dates that completed have SUCCESS rows; the rest stay RUNNING/missing. Re-run with `--skip-existing` and only the unfinished dates re-execute.

2. **Audit trail:** every reconstruction is recorded with timestamps + rows + validation summary. Looking at `pit_reconstruction_log` ordered by `id` shows the full history of when/what was computed.

3. **Detect bad runs:** `validation_summary` JSON shows per-column out-of-range counts. A run that suddenly spikes `out_of_range` for any column is the early-warning signal of a data-source change (e.g. Tickertape schema flip).

**Usage:**

```bash
# First run (all dates)
python -m tools.reconstruct_pit --months 12

# Re-run only the dates that didn't complete (after a crash)
python -m tools.reconstruct_pit --months 12 --skip-existing

# Inspect history
sqlite3 data/alpha_signal.db \
  "SELECT eval_date, status, rows_written, ROUND(duration_sec,1)
   FROM pit_reconstruction_log ORDER BY id DESC LIMIT 20;"
```

**`--skip-existing` is keyed on the exact `signals_run` set.** Adding a new signal to the default set changes the key, and previously-done dates will re-run (correct — they need the new column populated). If you want to rerun only one signal across all dates, use `--signal X` and existing dates with that signal-set in the log will be skipped.

### Rate-limit floor

**2 seconds between any external API call.** Faster works for short bursts; sustained faster gets you blocked (NSE blocks for hours, Tickertape blocks for ~30 min, RBI hard-blocks the IP).

For batch operations: chunk + checkpoint every 200 items. Resume via a JSON state file. Never run two harvesters simultaneously.

---

## Reconstruction Patterns

The 6 patterns we've actually used. New reconstruction = pick the matching pattern; don't invent.

### Pattern 1 — PIT slicing of raw history

**Used for:** piotroski, accruals, earnings_yield, book_to_price, momentum, promoter_qoq, forensic.
**Recipe:**
1. Load full raw history once (qi, bs, cf, sh, prices).
2. For each eval_date, filter raw to `record_date + filing_lag <= eval_date`.
3. Run the existing signal `_compute_scores(stocks, qi, bs, cf, sh)` against the filtered data.
4. Store the result with `snapshot_date = eval_date`.

**Implementation:** [tools/reconstruct_pit.py](../../tools/reconstruct_pit.py).

**Critical:** never modify the live signal modules. Reuse their pure `_compute_scores()` function with pre-filtered DataFrames. Live behavior stays identical; PIT becomes a dataset variant, not a parallel codebase.

**When it works:** the raw source has historical depth (≥1 year per stock).
**When it doesn't:** the raw source overwrites itself (use Pattern 5 or 6 instead).

### Pattern 2 — Snapshot accumulation (capture forward)

**Used for:** insider_signals (29 monthly snapshots), daily_snapshots_pit (7 monthly + extending), regulatory_signals (one batch so far, will accumulate).
**Recipe:**
1. Compute the signal with current data.
2. Write a row tagged with today's date.
3. Run weekly/monthly via cron.
4. Time produces history.

**When it works:** signal can be computed today *and* you're willing to wait. New signals start with 0 history; in 12 months you have 12 monthly periods (enough for IC validation).
**When it doesn't:** you need the t-stat *now*. Use Pattern 1 if raw data exists.

### Pattern 3 — Event-time aggregation with decay

**Used for:** regulatory_sector_signal (planned), insider_signal (90-day window).
**Recipe:**
1. Each event has a `published_at` or `trade_date`.
2. For eval_date D, filter events with `published_at ≤ D`.
3. Aggregate per sector/stock with time decay: `sum(direction × magnitude × exp(-(D - published_at)/half_life))`.
4. Half-life: 30-90 days depending on signal class.

**When it works:** events are event-stamped (have a real published_at, not just a fetched_at).
**When it doesn't:** all events were classified in one batch (e.g. regulatory_signals at 2026-04-10 only). Workaround: use the underlying event's `published_at`, not the classification's `classified_at`.

### Pattern 4 — Window-rolling aggregation

**Used for:** sentiment_7d, avg_delivery_pct_30d, mom_6m/12m, smart_money 90-day window.
**Recipe:**
1. For eval_date D and window W, filter source rows with `date BETWEEN D - W AND D`.
2. Aggregate: mean, sum, std, count.
3. Some signals normalize (z-score) using a longer baseline window.

**When it works:** continuous source coverage over the window.
**When it doesn't:** source has gaps (e.g. news_articles 2024-05 → 2026-01). Mark NULL for windows touching the gap; document the limit.

### Pattern 5 — DON'T reconstruct (forward-only)

**Used for:** bulk_deal_signal, pt_upside (analyst_consensus snapshot).
**Recipe:**
1. Mark NULL for any pre-availability date in the PIT table.
2. Document the limit in this playbook + the signal's registry entry.
3. Wait for forward accumulation. Don't try heroics.

**When it applies:** raw source has no historical archive AND no third-party backfill is worth the cost.

### Pattern 6 — Annual-snapshot PIT (coarse but feasible)

**Used for:** consensus reconstruction (planned), forecast revisions.
**Recipe:**
1. Source has annual or quarterly snapshots, not monthly.
2. For each monthly eval_date D, find the most recent snapshot with `date ≤ D`.
3. Compute a YoY or QoQ change from snapshot vs prior snapshot.
4. Forward-fill within a year if no new snapshot was published.

**When it works:** annual cadence is acceptable for the signal (e.g. consensus revisions don't need to be daily).
**When it doesn't:** signal is genuinely about monthly revision velocity (e.g. momentum-style). Then mark unbuildable and move on.

---

## Known Issues — Running Log

The bugs and gotchas we've already paid for. Add to this list every time something bites.

| Issue | Source / Module | Resolution | First seen |
|---|---|---|---|
| Bhavcopy column names have leading spaces | NSE Bhavcopy / `signals/momentum.py` | Always `df.columns.str.strip()` immediately after CSV read | v1 |
| Bhavcopy format changed Apr 3 2026 | NSE Bhavcopy | Earlier dates need `mmm/MMMYYYY/cmDDmmmYYYYbhav.csv.zip`; simplified format after | 2026-04 |
| Tickertape SIDs ≠ NSE tickers | Tickertape / harvester | REDY ≠ DRRD, BJFN ≠ BJFIN. Always use `universe.csv` SIDs not free-text tickers | v1 |
| Tickertape `operating_profit` is 100% NULL | Tickertape | Use `pbt + interest + (annual_depreciation/4)` to derive EBITDA | v1 |
| Tickertape `get_ticker()` search is blocked | Tickertape | Skip search; resolve by SID. `tickertape.in` and `analyze.api.tickertape.in` work; the rest of the API surface is blocked | v1 |
| NSE PIT `buyQuantity`/`sellquantity` always 0 | NSE PIT | Real values in `secAcq` and `secVal`. Cost us 3 weeks in v1. | v1 |
| Shareholding sentinel dates 1899-12-31 | Tickertape shareholding | Filter `WHERE end_date > '2000-01-01'` | v1 |
| Insider archive 96.5% duplicates | NSE PIT | App-level dedup broke. v2 uses DB-level UNIQUE constraint | v1 |
| **PIB scraper saves only at end** | PIB scraper | A crash mid-run loses 110K iterations. Add incremental save every 1000 events. | v1 |
| RBI blocks if requests <2s apart | RBI | Hard 2-second floor; longer is safer | v1 |
| data.gov.in API timeouts common | data.gov.in | 60s timeout + 3 retries with exponential backoff | v1 |
| data.gov.in Core Sector wide format | data.gov.in | Pivot to long; use `ITEM_CODE` (`INDEX_COAL`) not `ITEM_NAME` (text shifts) | v1 |
| **bulk_deals — no historical archive** | NSE bulk deals | Today's file only. Forward-only. Backtest BLOCKED. | v1 |
| **analyst_consensus — no history** | Tickertape consensus | Snapshot table; no historical buy_pct / PT. Use `forecast_history` for revision-based reconstruction. | v1 |
| **news_articles 2024-05 → 2026-01 blackout** | Google News RSS | We fetched once in 2024-04, then nothing until 2026-02. Sentiment reconstruction starts at 2026-03. | 2026-05-03 |
| **v1 sentiment reconstruction lost** | Sentiment / migration | v1 had VADER scores back to ~2023; CSVs were dropped during v2 migration; news depth wasn't preserved either, so re-derivation impossible. **Lesson: archive the computed signal, not just the raw source.** | 2026-05-03 |
| Live snapshots ≠ PIT (37% Piotroski divergence) | daily_snapshots vs daily_snapshots_pit | Use `daily_snapshots_pit_v1` for backtests. Live is for daily ranking only. | 2026-05-03 |
| Adj Close vs Raw Close (mom corr 0.67) | yfinance vs NSE bhavcopy | v1 used yfinance Adj Close; v2 uses bhavcopy raw close. Pick one and stay. v1 canonical for historical. | 2026-05-03 |
| Smart quotes from copy-paste break shells | run_pipeline.sh | Always retype quotes manually; never paste from docs | v1 |
| Cap_tier drift across history | tools/reconstruct_pit.py | Currently uses *current* cap_tier for historical eval dates. Material for 36mo+ backtests; benign for 6mo. (Plan 0004 §3.1) | 2026-05-03 |
| Financial sector accidentally included in forensic | signals/forensic.py | The exclusion via `FINANCIAL_SECTORS` config doesn't fire when stock.sector strings vary. Live signal bug (will inherit fix automatically into PIT). | 2026-05-03 |

---

## Per-Signal PIT Recipes

For every signal in [`db.py BACKTEST_SIGNALS`](../../db.py), the exact computation procedure. When in doubt, read here, not the live signal module — live modules combine PIT logic with snapshot writes that you don't want to copy.

### Value group

**earnings_yield**
- Inputs: `quarterly_income.eps` (TTM = sum of last 4 quarters where `end_date + 60d ≤ eval_date`), `stock_prices.close` (latest where `date ≤ eval_date`).
- Formula: `TTM_EPS / close`.
- Pattern: 1 (PIT slicing).

**book_to_price**
- Inputs: latest `annual_balance_sheet` row where `end_date + 75d ≤ eval_date` (`total_equity`, `shares_outstanding`); `stock_prices.close` at eval_date.
- Formula: `(total_equity / shares_outstanding) / close`.
- Pattern: 1.

**position_52w** (PROPOSED)
- Inputs: `stock_prices.close` over trailing 252 trading days.
- Formula: `(close - 52w_low) / (52w_high - 52w_low)`. Higher value = closer to highs (less of a value play; invert if ranking).
- Pattern: 1.

### Quality group

**piotroski_f_score**
- Inputs: 8 quarters of `quarterly_income`, latest 2 `annual_balance_sheet`, latest `annual_cash_flow`, all gated by appropriate filing lag.
- Formula: 9 binary factors (ROA+, CFO+, ΔROA+, accruals quality, ΔLeverage−, ΔLiquidity+, no-dilution, ΔGrossMargin+, ΔAssetTurnover+).
- Pattern: 1. Reuse `signals.piotroski._compute_scores`.

**cf_accruals_ratio**
- Inputs: TTM net income from qi, latest annual operating CF from cf, latest annual total assets from bs (all PIT-lagged).
- Formula: `(NI − OperCF) / TotalAssets`. Negative = cash backs earnings (good).
- Pattern: 1. Reuse `signals.accruals._compute_scores`.

**bs_accruals_ratio**
- Inputs: latest 2 `annual_balance_sheet` for ΔWorkingCapital; latest `annual_cash_flow` for capex + depreciation.
- Formula: `(ΔWC − capex − dep) / TotalAssets`.
- Pattern: 1.

**earnings_persistence (eps_cv)**
- Inputs: 8 quarters of `quarterly_income.eps` (lagged 60d).
- Formula: `std(eps[-8:]) / |mean(eps[-8:])|`. Lower = more persistent.
- Pattern: 1.

**earnings_beat_rate** (PARTIAL)
- Inputs: 8 quarters of `quarterly_income.eps`.
- Formula (proxy): fraction of last N quarters where `eps[i] > eps[i-1]`. v1 used analyst-estimate beat rate; we don't have that historically.
- Pattern: 1.

**roe / roa / debt_to_equity / profit_margin / revenue_growth_yoy / eps_growth_yoy** (all READY as of 2026-05-03)
- Inputs: qi.{net_income, revenue, eps} + bs.{total_equity, total_assets, total_debt}, all PIT-lagged 75d annual + 60d quarterly.
- Formulas: TTM ratios for ROE/ROA/PM (sum 4 quarters of NI / latest annual denominator); revenue_growth/eps_growth = TTM(latest 4Q) vs prior TTM(quarters −8 to −4).
- Negative-equity stocks → ROE/D/E = NaN. Financial sector → D/E = NaN (D/E meaningless for banks).
- Pattern: 1. Implementation: `pit_quality_fundamentals()` + `pit_growth_fundamentals()` in `tools/reconstruct_pit.py`.

### Momentum group

**mom_6m_adj / mom_12m_adj**
- Inputs: trailing prices from `stock_prices`. 6M = 154 days, 12M = 252 days, plus 22-day skip window.
- Formula: `(price[-skip] / price[-skip-window]) − 1` divided by daily-return std over the window.
- Pattern: 1.

**macd_signal** (PROPOSED)
- Inputs: 252 days of `stock_prices.close`.
- Formula: 12-day EMA − 26-day EMA = MACD line; 9-day EMA of MACD = signal line; bullish if MACD > signal.
- Pattern: 1.

### Ownership group

**promoter_qoq**
- Inputs: latest 2 `shareholding.promoter_pct` rows where `end_date + 21d ≤ eval_date`.
- Formula: `latest − prior`. Asymmetric adjustment (selling counts less).
- Pattern: 1. v1 vs v2 disagree (corr 0.55) — investigation pending.

**promoter_trend_4q** (PROPOSED)
- Inputs: 5 quarters of shareholding.
- Formula: `latest − value_5_quarters_ago`.
- Pattern: 1.

**pledge_quality** (PARTIAL — v1 has it, v2 omits)
- Inputs: latest `shareholding.pledge_pct`.
- Formula: `1 − pledge_pct/100`.
- Pattern: 1.

**insider_signal** — already PIT-derived, lives in `insider_signals`. Pattern: 2.

### Forensic group

**m_score** (Beneish reduced 6-factor)
- Inputs: qi.revenue (current + prior year), bs.{receivables, current_assets, total_assets}, cf.depreciation.
- Formula: `−4.84 + 0.920·DSRI + 0.404·AQI + 0.892·SGI + 0.115·DEPI + 4.679·TATA − 0.327·LVGI`. Threshold −1.78 (with +0.50 conservative shift for missing GMI/SGAI).
- Pattern: 1.

**z_score** (Altman Z'' emerging market 4-factor)
- Inputs: bs.{current_assets − liabilities, retained_earnings, total_assets}, cf.operating_cash_flow.
- Formula: 4-factor weighted sum. Threshold 0.5 = distress.
- Pattern: 1.

### Smart Money group

**avg_delivery_pct_30d** (PARTIAL — v1 has, v2 omits)
- Inputs: trailing 30 trading days of `stock_prices.delivery_pct`.
- Formula: `mean(delivery_pct[-30:])`.
- Pattern: 4.

**delivery_anomaly_z** (PROPOSED)
- Inputs: trailing 90 days of `stock_prices.delivery_pct`.
- Formula: `(today − 90d_mean) / 90d_std`.
- Pattern: 4.

**bulk_deal_signal** — BLOCKED. Pattern: 5.

### Consensus group

**pt_revision_yoy / eps_revision_yoy / consensus_signal_combined** (all READY as of 2026-05-03)
- Inputs: `forecast_history.value` for `metric IN ('eps', 'price')`. Filter `date ≤ eval_date`.
- For each (sid, metric): latest snapshot with date ≤ D; pick prior-year snapshot (closest to D − 1 year, within 9–18 month window).
- yoy = `(latest_value / |prior_value|) − 1` (× 100 for percentage units).
- consensus_signal_combined = mean of pt_revision_yoy + eps_revision_yoy when both available; single value if only one.
- Pattern: 6 (annual-snapshot PIT). Implementation: `pit_consensus()` in `tools/reconstruct_pit.py`.
- **Caveat:** annual cadence (FY-end snapshots), not monthly revisions. v1's "consensus" t=3.52 LARGE was *proxy mode* (snapshot-anchored), not strict PIT. Re-deriving in v2 with strict PIT may produce a different t-stat — that's intentional, not a bug.

**pt_upside** (READY as of 2026-05-03)
- Inputs: forecast_history (metric='price', dated PT snapshots back to 2015) + close at eval_date.
- Recipe: latest knowable PT for sid (where forecast date ≤ eval_date) / close at eval_date − 1.
- Pattern: 6 (uses forecast_history annual snapshots, not analyst_consensus snapshot-only).
- Implementation: `pit_pt_upside()` in `tools/reconstruct_pit.py`. **Was BLOCKED** when we mistakenly anchored on `analyst_consensus.price_target` — switching to forecast_history unblocks it.

### Sentiment group

**sentiment_7d** — feasible 2026-03+ only. Pattern: 4 (rolling window). Inputs: `news_articles.{title, summary}` joined to `news_article_stocks` by sid; VADER score per article; mean over trailing 7 days per sid.

### Sector overlay group (regulatory + macro) — READY as of 2026-05-03

Both written to `macro_sector_signals_pit (sector, snapshot_date)` — per-sector per-eval-date, NOT in stock-level `daily_snapshots_pit`. Schema:

```sql
CREATE TABLE macro_sector_signals_pit (
    sector TEXT, snapshot_date TEXT,
    regulatory_score REAL,    -- weighted reg-event score with 90d half-life decay
    macro_score REAL,         -- weighted indicator change (latest vs 90d-prior)
    n_reg_events INTEGER,     -- count of classified events surviving the PIT filter
    n_macro_indicators INTEGER,
    reconstructed_at TEXT,
    PRIMARY KEY (sector, snapshot_date)
);
```

**regulatory_sector_signal recipe:**
- Pattern 3 (event-time aggregation with decay).
- Filter: `reg_events.published_at ≤ eval_date` joined to classified `regulatory_signals` (inner join — only classified events count).
- Weights: `direction × magnitude_w × confidence_w × decay`. magnitude_w = {minor:1, moderate:2, major:3}; confidence_w = {low:0.5, medium:0.75, high:1.0}; decay = 0.5^(age_days / 90d_half_life).
- Normalize: `Σ weighted / sqrt(n)` to keep small samples conservative.
- Implementation: `pit_regulatory_sector()` in `tools/reconstruct_pit.py`.
- **Caveat:** classified subset is 5,687 of 16,523 events (~34%). Older eval dates may have few classified-and-published events.
- **Caveat:** `regulatory_events.published_at` has mixed formats (ISO and HTTP-style). Only ISO-parseable rows survive — silent loss of older entries.

**macro_sector_signal recipe:**
- Pattern 3 + Pattern 4 (rolling change with directional weighting).
- For each indicator: latest knowable value (≤ eval_date) vs 60-120d-prior value → percentage change.
- Per sector: `mean of (pct_change × direction × weight)` across mapped indicators in `macro_sector_map` (30 mappings).
- Scaled to ±10 range.
- Implementation: `pit_macro_sector()`.

**Bulk_deal_signal recipe** (PARTIAL — formerly BLOCKED, now forward-only):
- Net buy value over trailing 30 days (BUY = +qty×price, SELL = −qty×price), normalized by 30d avg close.
- NaN where no bulk_deals data exists in the window — naturally sparse pre-2026-03 because NSE has no historical archive.
- Implementation: `pit_bulk_deal_signal()`.

---

## Cross-references

- **Per-endpoint catalog:** [api-endpoints.md](api-endpoints.md) — function signatures, install commands, probe dates, NSE quirks, things-tried-and-rejected
- **Paid data playbook:** [paid-data-sources.md](paid-data-sources.md) — ₹5K/mo budget, Screener scrape pattern, Sensibull skip rationale
- **Engineering:** [tools/reconstruct_pit.py](../../tools/reconstruct_pit.py) (the reconstruction driver), [tools/import_v1_pit.py](../../tools/import_v1_pit.py) (v1 archive importer)
- **Plans:** [0004-pit-reconstruction.md](../plans/0004-pit-reconstruction.md), [0005-100-factors-and-model.md](../plans/0005-100-factors-and-model.md)
- **Mother plan:** [docs/plans/0003-mother-plan.md](../plans/0003-mother-plan.md)
- **Registry of signals:** `db.py` → `BACKTEST_SIGNALS` (42 entries, all statuses)
- **Critical rules:** [CLAUDE.md](../../CLAUDE.md) (filing-lag rule, harvester-rate rule, dedup rule)
- **v1 backtest source-of-truth:** `daily_snapshots_pit_v1`, `pit_ic_by_tier_v1` (imported from v1 CSV, frozen)

---

## How to extend this doc

When you ingest a new source: add a section to *Source Catalog* with all 7 fields (What/Endpoint/PIT/Historical/Depth/Gotchas/Rate limit).

When you reconstruct a new signal: pick from the 6 patterns; if your case doesn't fit, add a new pattern with a recipe and at least one example signal.

When you hit a new bug: add a row to *Known issues* the same day. The cost of one line in this doc << the cost of re-paying the same debugging.

When a source's depth changes (e.g. you backfill news_articles): update its row in Source Catalog *and* its `status_reason` in `BACKTEST_SIGNALS`.
