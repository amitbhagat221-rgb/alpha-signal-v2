# Data Playbook

> The institutional memory we keep losing. Every source, every reconstruction
> method that worked, every gotcha we've already hit. Read before fetching;
> update after every data-source incident.
>
> If a future session has to re-discover something already in this doc, the
> doc has failed. Be explicit, be specific, name the file and the column.

**Maintained by:** anyone touching data ingestion or PIT reconstruction.
**Updated:** with every new source, every reconstruction we ship, every issue we resolve.
**Last refresh:** 2026-09-26: absorbed the former `api-endpoints.md` (archived) and re-checked source statuses against the live DB. Row counts go stale fast, so for live depth run `SELECT COUNT(*), MIN(date_col), MAX(date_col)` on the table; the freshness view is `db.data_health()`.

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

## Endpoint quick reference (merged from `api-endpoints.md`, 2026-09-26)

Libraries: `pip install --break-system-packages nselib jugaad-data mftool`. nselib 2.5.1 wraps NSE's
date-range APIs and handles the cookie session; jugaad-data is an alternate NSE wrapper; mftool wraps mfapi.in.
Every entry below was probed from this VM (first audit 2026-05-03). Sources with their own section in the
catalog further down are not repeated here.

| Source | Call / endpoint | Depth · notes |
|---|---|---|
| NSE block deals | `capital_market.block_deals_data(from_date, to_date)` | Same range as bulk deals; counterparty data |
| NSE smart-beta indices | `capital_market.index_data(index="NIFTY ALPHA 50", …)` | ~10y older indices, 2–3y newer; cols `TIMESTAMP`, `CLOSE_INDEX_VAL` (not `OPEN`); `nse_index_history`. yfinance returns empty for these |
| NSE futures per symbol | `nselib.derivatives.future_price_volume_data(symbol, …)` | Multi-month per stock |
| NSE F&O full EOD | `derivatives.fno_bhav_copy(trade_date)` | Whole market in one call → `fno_bhav` (ADR 0034); IV derived in-house (ADR 0035) |
| NSE event calendar | `capital_market.event_calendar_for_equity(…)` | Board meetings / results dates, forward + recent past |
| NSE FII/DII cash flow | `GET nseindia.com/api/fiidiiTradeReact` (cookie warm) | Today only → forward-accumulated in `fii_dii_cash_flow` since 2026-04-30 |
| NSE ASM / GSM / F&O ban | `api/reportASM` (cookie warm); `derivatives.fno_security_in_ban_period` | Today only → `surveillance_flags` |
| NSE bulk deals (today) | `archives.nseindia.com/content/equities/bulk.csv` | Daily fresh hit; nselib does history |
| NSE corporate announcements | `api/corporate-announcements?index=equities` | Latest 20–50; BSE stream (below) is the deep source |
| AMFI NAVAll.txt | `GET amfiindia.com/spages/NAVAll.txt` | Today's NAV for all schemes, used by the daily MF step (see MF section) |
| World Bank India | `api.worldbank.org/v2/country/IND/indicator/{code}?format=json` | 9–20y annual/quarterly (GDP, FX, FDI, M2) |
| AMFI MF portfolio disclosure | monthly PDFs | ~5y but PDF-brittle; holdings come from the ETMoney scrape instead |
| Tier C (caveats) | AlphaVantage demo (25 calls/day), Twelve Data, SEBI SAST (HTML only), FMP (India patchy) | Not used |

Paid sources: ranked options and costs are in [plan 0014](../plans/0014-data-acquisition-roadmap.md).
The earlier ₹5K/mo playbook is archived at [paid-data-sources.md](../_archive/reference/paid-data-sources.md), with a summary in memory `paid_data_sources.md`.

**After a long gap, before trusting an endpoint:** hit a known-recent date first (the cookie can fail
intermittently) · compare the response shape to the schema, because NSE renames columns silently · use `DD-MM-YYYY` for nselib and ISO elsewhere ·
strip column whitespace on `KeyError: ' SYMBOL'` · treat 403 as a cookie problem, not a dead endpoint · on an empty result, chunk the date range smaller.

**Tried and rejected (don't repeat):**

| Attempted | Result | Use instead |
|---|---|---|
| yfinance smart-beta indices | Only NIFTY 50/500/MIDCAP 150 work | `nselib…index_data` |
| SEBI insider-trade JSON | HTML only | NSE PIT API (now empty too, see Known issues) |
| AMFI portfolio-disclosure URL | 404 | ETMoney holdings scrape |
| BSE bulk-deals API | 0 entries | nselib bulk deals |
| EODHD demo for India | 403 | skip |
| Wayback Machine for NSE bulk.csv | 1 snapshot | nselib date-range |
| Sensibull | No retail API | compute from Kite/nselib raw |

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
| **Historical access** | NSE archive goes back ~5 years. `insider_trades` holds 2021-01 → 2026-05-02 (last row fetched 2026-05-24). |
| **⚠ Status (2026-09-26)** | **The API has returned empty data since ~2026-05.** `fetch_insider` and `signal_insider` now raise with that reason instead of logging SUCCESS/0 (commit 8700769). `insider_signal` is frozen at May 2026 until a replacement source is found (candidates: BSE announcement stream SAST/PIT categories, plan 0014). |
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
| **v2 depth** | `bulk_deals` backfilled via nselib: 2021-01 → present. |
| **Gotchas** | (1) Date format `DD-MM-YYYY` (not ISO). (2) Symbol matching needs strip+upper. (3) Use 2-second floor between calls; chunk long ranges by month. |
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

### Analyst consensus (`analyst_consensus`): yfinance PT + Tickertape EPS/revenue

| Field | Value |
|---|---|
| **What** | Total analysts, buy %, price target, forward EPS, EPS growth %, forward revenue, revenue growth %. **Field owners (ADR 0018/0020):** `price_target` + `total_analysts` come only from yfinance (`sources/yfinance_analyst.py`, daily). Tickertape writes only the EPS/revenue fields. The monthly `--snapshot` cron appends `analyst_consensus_snapshots`, which is the only honest PT history. |
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
| **v2 depth** | eps + revenue: ~11.7K rows each (monthly refresh); 8.1K legacy price rows frozen at 2026-05-11 (never read). |
| **Gotchas** | (1) `change` column populated for `eps`/`revenue` but **empty for `price`** — compute PT YoY from value series directly. (2) `fetched_at` is the same for all rows (the date of last harvest); the *event* date is in the `date` column. (3) Annual cadence means a "monthly PIT consensus" reconstruction will have 12 dates per stock per year using forward-fill — coarser than v1's "proxy" t=3.52 implied. |
| **Status (2026-09-26)** | **`metric='price'` rows are no longer ingested or served** (commit 8700769, ADR 0045). The 8K legacy price rows left in the table are look-ahead (see below) and must never be read. `eps`/`revenue` are still ingested monthly. |
| **Used by** | `signals/consensus.py` + `pit_consensus()` (EPS revision only). |

#### 2026-07-05 — forecastsHistory contamination MECHANISM (live-probe verdict; audit Factor-F1 follow-up)

**UPSTREAM defect, by design. Source permanently dead for PT/PIT purposes.** Live probe of 8 sids (6 fetched OK, 2 404'd) + DB forensics:

- `forecastsHistory.price` is **not a PT history — it never contains a PT at any point in its life.** Each year-end-dated entry (Dec-Y) is a live price tracker: it floats with lastPrice until ~Dec-26 of **Y+1**, then freezes and a new Dec-Y+1 entry spawns. Verified: live Dec-2024 entry = close(**2025-12-26**) to the paisa on 6/6 probed sids (HALC 872.9, BRTI 2105.4, ABOT 28905, BHEL 281.5, ACC 1735.3, ACEL 951.2); live Dec-2025 entry = close(2026-07-03) on 6/6, identical to the "today" entry. DB-side: 99.3% of 1,775 stored Dec-2025 rows (fetched 2026-07-01) match the **fetch-date** close within 2%; only 7.5% match the actual Dec-2025 close.
- **Ingest is faithful** — `_extract_forecast_rows` stores the API's own dates/values unchanged. Its ≤90d filter drops the "today"-dated twin but keeps the identically-live Dec-dated entry, and the monthly upsert (PK sid+metric+date) keeps re-floating that row until it freezes a year later at close(Dec-Y+1). Net: every stored Dec-Y price row embeds the year-AHEAD close — pure look-ahead, unfixable by any date filter.
- Stale vintages corroborate: CIGN (fetched 2026-05-19) Dec-2025 row = close(2026-05-14) 1260.3; NGFR (2026-06-01) = close(2026-05-28) 3.70 exactly. Both slugs now 404 (delisted) — rows frozen at last successful fetch, as the mechanism predicts.
- **Salvageable: nothing, for PT purposes.** eps/revenue arrays = realized FY actuals (long-decimal computed values we already hold in quarterly_income/annual tables) + ONE live forward consensus point dated at the FY-end being forecast — legitimate only as a current snapshot (analyst_consensus already captures it; Pattern 2 forward accumulation), never as a dated consensus archive.
- **Epitaph:** Tickertape's forecastsHistory.price is a chart-decoration price track masquerading as forecast history; its Dec-Y "forecasts" are the realized Dec-Y+1 closes by construction. Quarantine metric='price' from every PIT consumer (`pit_pt_upside`, `pit_consensus`/pt_revision_yoy); the only honest PT history is `analyst_consensus_snapshots` accumulated forward. Do not re-probe.

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
| **v2 depth** | Circulars feed `regulatory_events` → `regulatory_signals`. Bank metrics are **not** taken from RBI: `banking_metrics` comes from Screener.in bank pages (158 banks + NBFCs, monthly `fetch_banking_metrics`) and is display-only (ADR 0048). |
| **Gotchas** | (1) **2-second delay between requests or RBI blocks**. (2) PDF parsing is brittle; some quarters have format changes. |
| **Used by** | `sources/regulatory_harvester.py`, `sources/regulatory_classifier.py` |

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
| **Confirmed-working endpoints** | See memory `nselib_apis.md` (Claude auto-memory, outside the repo) for the full table. Highlights: bulk_deal_data + block_deals_data (≥2yr range), corporate_actions_for_equity (splits/divs), short_selling_data (Jan 2024+), bhav_copy_with_delivery, deliverable_position_data per symbol, participant_wise_open_interest (FII/DII positioning, Dec 2025+). |
| **Quirks** | DD-MM-YYYY date format; `xlrd` dep needed for `fii_derivatives_statistics`; some single-day endpoints return "no data available" for arbitrary recent dates. |
| **Rate limit** | Treat as 2-second floor (same NSE rule as bhavcopy). Chunk long ranges by month. |
| **Used by** | `sources/nselib_pull.py` (bulk, short selling, corporate actions, FII/DII positioning), `sources/fno_pull.py` (`fno_bhav`), `sources/historical_backfill.py` |

### Short Selling — NEW signal class via nselib

| Field | Value |
|---|---|
| **What** | Daily reported short-selling activity per symbol. Quantity sold short. Probed Jan 2025: 675 rows; Jan 2024: 37 rows (data sparser earlier). |
| **Endpoint** | `nselib.capital_market.short_selling_data(from_date, to_date)` |
| **Historical access** | Back to Jan 2024 confirmed; sparse for older dates. |
| **Alpha use** | Short-interest spike = bearish positioning; short squeeze candidate when shorts cover. New signal class not in v1's roster. |
| **Status in v2** | Ingested: `short_selling_data`, 2022-01 → present. |

### Corporate Actions — fixes the Adj-Close issue

| Field | Value |
|---|---|
| **What** | Splits, bonuses, rights, dividends, ex-dates per symbol. The data needed to reconstruct true split-adjusted prices. |
| **Endpoint** | `nselib.capital_market.corporate_actions_for_equity(from_date, to_date)`. Confirmed: 2,246 rows for 2025-2026. |
| **Why important** | Resolves the v1-vs-v2 mom_6m correlation 0.70 issue at the root. v1 used yfinance Adj Close (split-adjusted); v2 uses bhavcopy raw close. With corporate-actions data we can split-adjust the bhavcopy prices ourselves and the divergence disappears. |
| **Status in v2** | Ingested: `corporate_actions`, 2018-03 → present. PIT factors are pre-multiplied into `corporate_adjustments` by `tools/compute_corporate_adjustments.py` (ADR 0010). **That tool is not a pipeline step, so rebuild it by hand**: as of 2026-09-26 `corporate_adjustments` stops at ex_date 2026-04-30 while `corporate_actions` runs to 2026-09-25. |

### FII/DII Positioning (F&O segment) — derivatives flow signal

| Field | Value |
|---|---|
| **What** | Daily participant-wise (Client / DII / FII / Pro) Open Interest and trading volume in F&O. Tells you how each cohort is positioned in futures and options. |
| **Endpoint** | `nselib.derivatives.participant_wise_open_interest(trade_date)` and `participant_wise_trading_volume(trade_date)`. Single-day signature. |
| **Historical access** | The endpoint served ~Dec 2025+ at first probe; `fii_dii_positioning` now holds 2022-01 → present (backfilled). |
| **Alpha use** | FII net long/short F&O positioning is one of the strongest macro tilts available. Cohort divergence (FII selling vs DII buying) is a regime signal. |
| **Status in v2** | Ingested daily by `run_daily_forward.sh` (14:00 UTC). |

### Mutual-fund NAV: AMFI NAVAll.txt (daily) + mfapi.in (backfill)

| Field | Value |
|---|---|
| **What** | Daily NAV for ~4,048 Indian MF schemes, going back ~13 years (2013-present). Free, no key. |
| **Endpoint** | `https://api.mfapi.in/mf/{scheme_code}` returns full NAV history; `/latest` for the most recent. |
| **Historical depth** | 13 years confirmed for Parag Parikh Flexi Cap (3,178 daily NAVs from 2013-05-28). |
| **Alpha use** | MF NAV trends as flow proxy; top-decile MFs' overweighted stocks as smart-money signal (combine with monthly portfolio disclosure). |
| **Limit** | NAV only — for actual stock holdings need AMFI portfolio disclosures (monthly, ~45-day lag). |
| **Status in v2** | `mf_nav_history` (2006 → present). Daily: `fetch_mf_nav_daily` / `fetch_mf_master` parse AMFI `NAVAll.txt`. Backfill: `sources/mf_nav_backfill.py` (mfapi.in). **AMFI added `Plan;Option` columns ~2026-08-19** (6 → 8 cols), and the fixed-index parser silently read "Direct Plan" as the NAV, so NAVs stopped at 2026-08-18. The parser is now header-driven with a UTF-8 decode (commit 8700769); expect a gap from 2026-08-19 until the fix's first run. Holdings: ETMoney scrape (`sources/mf_holdings_scrape.py`). Memory: `mfapi_nav.md`. |

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

### Moneycontrol — broker recommendations

| Field | Value |
|---|---|
| **What** | Per-stock sell-side recommendations (broker, target, reco date) → `broker_recommendations` (bad slug matches go to `broker_recommendations_quarantine` via the identity gate, ADR 0033). |
| **Endpoint** | Moneycontrol HTML per `stocks.mc_slug` (slugs are company-name-derived, not tickers). |
| **Cadence** | **Daily with a 90-minute stalest-first budget** (`PIPELINE_BUDGET_MIN`, ordered by `stocks.mc_checked_at`; ~300 stocks/day, full cycle ~8–9 days). This replaced the ~18h Sunday full sweep, which held the harvest lock and starved `run_daily_forward.sh` (2026-09-26). It raises on 0 rows. |
| **Rate limit** | 12 s/request. |

### Screener.in — deep fundamentals + bank pages

| Field | Value |
|---|---|
| **What** | `fundamentals_screener` (long format, ADR 0011) and `banking_metrics` (bank pages). |
| **Access** | Logged-in session cookie at `~/.cache/screener_cookie.json`. A keep-alive cron runs every 8h and pushes to ntfy when auth dies (`sources.screener_pull --check-cookie`). Full refresh `--universe` runs on the 1st and 15th under the shared harvest `flock`. |
| **⚠ Status (2026-09-26)** | Last successful rows fetched 2026-07-15. The latest `--universe` run logged `failures: 2448/2448, total rows: 0`. Check the cookie before trusting Screener-derived factors. |

### BSE corporate-announcement EVENT STREAM ⭐ (the richest free unlock found, 2026-06-08)

| Field | Value |
|---|---|
| **What** | The full BSE corporate-disclosure feed — every announcement (Result, Board Meeting, Credit Rating, Pledge/SAST, Resignation, Buyback, Corp. Action, AGM/EGM, Company Update) with **exact timestamps**, category/subcategory, BSE's own `CRITICALNEWS` materiality flag, disclosure-latency (`TimeDiff`), `QUARTER_ID`, and attachment flags (PDF / Investor PPT / audio-video). A whole new *event-driven* data category. |
| **Endpoint** | `https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w` — **unofficial** (the public bseindia.com site's own backend). Params: `pageno, strCat=-1, subcategory=-1, strPrevDate=YYYYMMDD, strToDate=YYYYMMDD, strSearch=P, strscrip='', strType=C`. Response `{"Table":[rows], "Table1":[{"ROWCNT":<total>}]}`, 50 rows/page. |
| **PIT access** | `DT_TM` is the look-ahead-safe event time. The all-scrip/all-category "firehose" returns **ONE day per call** (multi-day ranges silently return 0) → harvest day-by-day. |
| **Historical access** | Confirmed back to **2018** incl. **delisted names** (scrip code persists post-delisting; e.g. DHFL 2018 returns 50 rows) → survivorship-complete by construction. |
| **v2 depth** | `bse_announcements` — backfilling 2018→present (~700/day × ~250 trading days/yr). `sid` column is NULL until the deferred BSE-scrip-master ↔ ISIN ↔ ticker map is built (`stocks` has no ISIN). |
| **Gotchas** | (1) **Endpoint is `AnnSubCategoryGetData`, NOT `AnnGetData`** (the latter returns "No Record Found"). (2) Single-day only for the firehose. (3) **Warm the cookie** — GET `bseindia.com/corporates/ann.html` first; browser UA + Referer/Origin required. (4) Same IP-block risk as the PDF harvester — ≥1.5s between pages, single-threaded. (5) Unofficial: BSE can rename params without notice (already did once). (6) **ToS:** fine for personal research; the *real-time feed* is what BSE licenses — get a licensed feed before any commercial redistribution. |
| **Rate limit** | ≥1.5s between pages; warmed session; never parallel with the transcript/PDF harvester (shares the BSE IP-block surface). |
| **Used by** | (planned) PEAD announce-dates, transcript look-ahead fix, credit-rating-change factor, promoter-pledge events, auditor/KMP-resignation forensic, governance signals (`critical_news` + `time_diff`), free forward earnings calendar (Board Meeting agenda). Harvester: `sources/bse_announcements.py`. |

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

**Fix path (plan 0011 WS2.8):** `historical_universe` (built by `tools/build_historical_universe.py` from bhavcopy, incl. delisted names back to 2018) exists but has only ~9 sparse snapshots. A full price backfill (~1,381 delisted symbols) must come first, and only then can `reconstruct_pit.py` intersect with it ([survivorship study](../studies/survivorship-exposure-2026-07.md)).

### Look-ahead bias (the live-snapshot trap)

Live snapshot tables (`daily_snapshots`, all `*_scores`, `daily_picks`) include data that has been *fetched*, not just data that was *knowable* on the snapshot date. Empirical: 37% of Piotroski rows differ between live and PIT for 2026-05-01 alone.

**Rule:** for backtests, never read from live snapshot tables. Always read from `daily_snapshots_pit_v1` (canonical historical) or `daily_snapshots_pit` (v2 forward extension).

### Dedup strategies

| Pattern | Use for | SQL |
|---|---|---|
| Append-only | insider_trades, bulk_deals, news_articles | `INSERT OR IGNORE` with UNIQUE constraint |
| Snapshot-replace | analyst_consensus, regime_state, all `*_scores` | `INSERT OR REPLACE` on PRIMARY KEY |

UNIQUE constraints on append-only tables prevent the v1 disaster: insider_archive had 96.5% duplicates because dedup was app-level and broke. Now it's DB-level and unfixable.

### Validation guardrails (one range per column, one check runner)

Plan 0015 Phase 4 (ADR 0052 Check block). Every legal-value rule is declared ONCE and every consumer reads it — before this, M-score alone had three ranges in three files.

| Rule | Declared in | Read by |
|---|---|---|
| Factor / PIT column range | `factors.FACTORS[...]["pit_range"]` → `factors.VALIDATION_RANGES` | `pit.py` and the live screener (`discard_out_of_range`: out of range → NaN, never clipped); stored columns of the same quantity via `{"factor": ...}` |
| Stored column range / enum | `checks/ranges.py COLUMNS[(table, column)]` — `factor` / `range` / `min` / `in`, optional `typical` review band | `health.factor_validity` (per-table score), the range verdicts of `checks.run()` (→ `tools/data_sanity`, health email, ops Health page), `validators/plausibility` (column datum classes via `DATUM_COLUMNS`), `validators/per_stock_integrity` |
| Tier / regime enums | `config.TIERS`, `EXCLUDED_FROM_PICKS`, `VIX_REGIMES` | `checks/ranges.py` |
| Per-stock coverage | `tables.TABLES[...]["coverage"]` | derived coverage checks + watchdog |
| Semantic checks (PT == close, rank duplicates, feed dark…) | `checks/custom.py CHECKS` | `checks.run()` |
| Segment priors for write-time quantities (pt_upside by tier, NAV day-change by fund type) | `validators/plausibility.PLAUSIBILITY_RANGES` | the write-time plausibility gate |

PIT write path (`pit._validate_and_clean`): `±inf` → NaN, out-of-range → NaN with a count, per-column `n_valid / n_nan / n_out_of_range / min / max` stored as JSON in `pit_reconstruction_log.validation_summary`; a column with > 5% out of range is flagged in the run summary. Setting outliers to NaN keeps the row but quarantines the bad value. Print the current factor ranges with `python -c "import factors; print(factors.VALIDATION_RANGES)"` — never copy them into a doc or another module.

**One runner, one verdict shape.** `checks.run()` returns `{check_id, target, severity, status, detail, …}` per check (PASS / FAIL / ERROR). Range-verdict severity is derived, not per-check: a column on the email's critical path is CRITICAL from 1% of rows violating, any other from 10%; WARN from 1%; INFO below. Custom checks keep their own `critical_pct` / `warn_pct`.

**Alert criticality is derived.** A failed step pages when it is `critical` or the email transitively needs its output (`checks.critical_steps()` = `critical` ∪ `graph.ancestors(steps, "email", needed_only=True)` ∪ email); an OUTDATED table pages when such a step writes it (`checks.critical_tables()`). Adding a step or a read edge updates both — there is no list to edit.

**Post-step check (invariant 4).** `checks.post_step(step)` fails a step when a table it declares writing (`graph.writes`, `file:*` and `best_effort` tables skipped) is OUTDATED by the freshness rule right after it ran. Zero rows into a still-fresh table is a no-op; zero rows into a stale one is a failure (the bhavcopy "returned 0, logged SUCCESS" class).

**Dataset kinds.** `tables.dataset_kinds()` infers one kind per table from its schema.sql PK (+ `DATASET_KIND_OVERRIDES`): `event` (surrogate / event-id key), `series` (fetched entity × date), `state` (entity → current value), `feature` (computed entity × date), `log`. **Vintage rule for series (documented, not yet enforced):** a series row is insert-only with `fetched_at` = first seen; a restatement is a new row, never an in-place UPDATE; `asof(series, t)` = per key the latest `fetched_at <= t` among rows whose business date + availability lag `<= t`. Until then a replay applies `end_date + lag` to today's restated values (plan 0015 Phase 3 finding).

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

**Used for:** pt_upside (`analyst_consensus_snapshots` only, since 2026-05; ADR 0045), FII/DII cash flow.
**Recipe:**
1. Mark NULL for any pre-availability date in the PIT table.
2. Document the limit in this playbook + the signal's registry entry.
3. Wait for forward accumulation. Don't try heroics.

**When it applies:** raw source has no historical archive AND no third-party backfill is worth the cost.

### Pattern 6 — Annual-snapshot PIT (coarse but feasible)

**Used for:** EPS revisions from `forecast_history` eps/revenue. **Never** apply it to `forecast_history` price, which is look-ahead by construction.
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
| bulk_deals "no historical archive" (v1 belief) | NSE bulk deals | Wrong: nselib `bulk_deal_data` backfills (done, 2021+) | v1 → 2026-05 |
| NSE `api/*` "blocked" | NSE | Missing cookies: GET `https://www.nseindia.com` in the same `requests.Session` (browser UA) first; nselib does this | v1 |
| Date formats mixed silently return empty | nselib | nselib wants `DD-MM-YYYY`, everything else ISO | 2026-05-03 |
| `fii_derivatives_statistics` needs `xlrd` | nselib | Skip it; `participant_wise_open_interest` gives the same data | 2026-05-03 |
| NSE PIT API returns empty data | NSE PIT | Since ~2026-05; producers now raise loudly. Needs a replacement source | 2026-09-26 |
| AMFI NAVAll.txt gained `Plan;Option` columns | AMFI | Header-driven parse + UTF-8 decode | 2026-09-26 |
| Moneycontrol full sweep ran ~18h, starved other jobs | Moneycontrol | Daily 90-min stalest-first budget | 2026-09-26 |
| `forecast_history` price = year-ahead close | Tickertape | Stop ingesting price rows; PT history = `analyst_consensus_snapshots` only | 2026-07-05 |
| **analyst_consensus — current only** | yfinance daily refresh | PK=sid, daily-refreshed for cockpit "current PT" card. Historical aggregates live in `analyst_consensus_snapshots` (monthly cadence, since 2026-05-22). | v2 |
| **news_articles 2024-05 → 2026-01 blackout** | Google News RSS | We fetched once in 2024-04, then nothing until 2026-02. Sentiment reconstruction starts at 2026-03. | 2026-05-03 |
| **v1 sentiment reconstruction lost** | Sentiment / migration | v1 had VADER scores back to ~2023; CSVs were dropped during v2 migration; news depth wasn't preserved either, so re-derivation impossible. **Lesson: archive the computed signal, not just the raw source.** | 2026-05-03 |
| Live snapshots ≠ PIT (37% Piotroski divergence) | daily_snapshots vs daily_snapshots_pit | Use `daily_snapshots_pit_v1` for backtests. Live is for daily ranking only. | 2026-05-03 |
| Adj Close vs Raw Close (mom corr 0.67) | yfinance vs NSE bhavcopy | v1 used yfinance Adj Close; v2 uses bhavcopy raw close. Pick one and stay. v1 canonical for historical. | 2026-05-03 |
| Smart quotes from copy-paste break shells | run_pipeline.sh | Always retype quotes manually; never paste from docs | v1 |
| Cap_tier drift across history | tools/reconstruct_pit.py | Currently uses *current* cap_tier for historical eval dates. Material for 36mo+ backtests; benign for 6mo. (archived [pit-reconstruction plan](../_archive/2026-05-22-plan-0004-pit-reconstruction.md) §3.1; the survivorship side is WS2.8 in plan 0011) | 2026-05-03 |
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

**eps_revision_yoy / consensus_signal_combined**
- Inputs: `forecast_history.value` for `metric='eps'`, filtered `date ≤ eval_date`; latest snapshot vs the one closest to D − 1 year (9–18 month window).
- yoy = `(latest / |prior|) − 1`. `consensus_signal_combined` = `eps_revision_yoy` only.
- `pt_revision_yoy` is **DROPPED** (ADR 0020). Rebuild it from `analyst_consensus_snapshots` once ≥12 months exist (~2027-05).
- Pattern: 6. Implementation: `pit_consensus()` in `tools/reconstruct_pit.py`.

**pt_upside** (pulled from `SIGNAL_WEIGHTS`, ADR 0045)
- Source: `analyst_consensus_snapshots` **only** (monthly yfinance aggregate, 2026-05+), NULL before the first snapshot, no fallback.
- Recipe: latest knowable PT (snapshot ≤ eval_date) / close at eval_date − 1.
- History: the |t|=16 (2026-05-03) and t=7–9 (2026-05→07) results were `forecast_history` look-ahead artifacts. Re-entry needs ≥12 clean monthly anchors and |t|≥1.5, ~2027-05.

**PT cadence** (CLAUDE.md "Data-cadence rule"): `analyst_consensus` is the live view, `analyst_consensus_snapshots` holds the monthly history, and a PT row is never written daily.

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

**Bulk_deal_signal recipe:**
- Net buy value over trailing 30 days (BUY = +qty×price, SELL = −qty×price), normalized by 30d avg close.
- NaN where no bulk_deals data exists in the window (table backfilled to 2021-01 via nselib).
- Implementation: `pit_bulk_deal_signal()`.

---

## Cross-references

- **Paid data / acquisition roadmap:** [plan 0014](../plans/0014-data-acquisition-roadmap.md) and [oss-quant-toolbox.md](oss-quant-toolbox.md). Archived research: [pit-data-sources-research.md](../_archive/reference/pit-data-sources-research.md), [api-endpoints.md](../_archive/reference/api-endpoints.md) (pre-merge).
- **Engineering:** [tools/reconstruct_pit.py](../../tools/reconstruct_pit.py) (reconstruction driver). The v1 archive importer is `_archive/tools/import_v1_pit.py` (one-shot, done).
- **Registry of signals:** `db.BACKTEST_SIGNALS` (live count lives there, not here); weights in [signal-weights.md](signal-weights.md).
- **Critical rules:** [CLAUDE.md](../../CLAUDE.md) (filing lag, harvester rate, dedup).
- **v1 backtest source-of-truth:** `daily_snapshots_pit_v1`, `pit_ic_by_tier_v1` (imported from v1 CSV, frozen).

---

## How to extend this doc

When you ingest a new source: add a section to *Source Catalog* with all 7 fields (What/Endpoint/PIT/Historical/Depth/Gotchas/Rate limit).

When you reconstruct a new signal: pick from the 6 patterns; if your case doesn't fit, add a new pattern with a recipe and at least one example signal.

When you hit a new bug: add a row to *Known issues* the same day. The cost of one line in this doc << the cost of re-paying the same debugging.

When a source's depth changes (e.g. you backfill news_articles): update its row in Source Catalog *and* its `status_reason` in `BACKTEST_SIGNALS`.
