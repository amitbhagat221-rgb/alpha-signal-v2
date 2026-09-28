# Research 0005 — Source-gap sweep: free and "hacky-elegant" data unlocks

**Status:** research complete · **Written:** 2026-09-28 · **Parent:** [plan 0014](../plans/0014-data-acquisition-roadmap.md)
**Method:** 6 parallel web-research agents (ownership · fundamentals/estimates · events/credit · macro · prices/intraday · GitHub ecosystem). Research only: web search, GitHub source reads, read-only DB checks. **No NSE/BSE/Screener/Tickertape endpoint was called from the VM.**
**Onboarded 2026-09-28** (plan 0018 notes): NSE credit ratings, IPO master, index inclusion/exclusion → `market_events`; Yahoo earnings history + EPS trend → `analyst_estimates`; Screener shareholder counts → `shareholding.n_shareholders`; F&O 2024-07→2025-05 backfill. Declined for now: delisted panel (D3), BSE SHP XBRL, macro nowcasts, results XBRL (next), account/blocked/thin sources.
**Evidence labels:** **VERIFIED** = checked against our DB/code this session, or an agent read the live document. **SOURCED** = cited repo/doc, not run. **UNVERIFIED** = inferred. Every build still starts with the 3-item smoke test through `sources/_http`.

## Headline

1. **Pre-2023 survivorship-free prices are NOT gone.** This overturns plan 0014's "permanent gap" and D3's ~2023 floor. VERIFIED: `tools/build_historical_universe.py::_old_bhav` already reads the legacy NSE CM bhavcopy. Its 2018-04-02 snapshot has 1,623 rows, 651 with no sid, including delisted FRETAIL and RELCAPITAL. We fetched membership from it but never prices.
2. **Retail shareholder counts, named holders (MF/LIC/superinvestors) and FPI names all come from one PIT-safe source:** the exchange shareholding-pattern XBRL.
3. **Credit-rating downgrades are recoverable.** They sit in a text table on page 1 of the agency press release, not in scanned images. Since 2025-08 there is also a structured NSE feed.
4. **Intraday history can be free:** Fyers 1-min from 2017-07. Kite is reportedly ₹500/mo with history included, not ₹2,000.
5. **Free PIT consensus-revision history is still NO before 2026**, but Yahoo `earningsTrend` makes forward collection useful in ~3 months. **Smoke test:** Yahoo's earnings calendar carries per-quarter EPS estimate vs actual back to 2007 (L) / 2015 (S). That is surprise history, PIT unverified.

## Smoke-test verdicts (2026-09-28) — supersede the tables below where they differ

Probed from the VM, strictly sequentially, under the harvest lock, through `sources/_http`. Test set: RELIANCE / PERSISTENT / GRAVITA (L/M/S). No DB writes, no blocks seen. Script and raw JSON are session scratch, not kept.

| Verdict | Item | What the probe showed |
|---|---|---|
| ✅ WORKS | A1 legacy CM bhavcopy | 2010 and 2015 files fetched. 2015-01-05: 1,510 EQ/BE symbols, ~715 not in today's universe (e.g. 3IINFOTECH, ABGSHIP). **ISIN column from 2015, absent in 2010.** |
| ❌ DEAD | A1 `PREVCLOSE(t)/CLOSE(t-1)` adjustment trick | Legacy PREVCLOSE is **unadjusted**: factor 1.0 on BPCL 1:1 and HINDPETRO 1:2 bonus ex-date 2024-06-21. Adjust via `corporate_actions` or A1b. |
| ✅ WORKS | A1 `symbolchange.csv` | 1,065 renames, 2003 → 2025 |
| ✅ WORKS | A1b HF `tejhq/indian-markets` | 88 files / 1.1 GB, yearly NSE parquets 2010+. `metrics/` = ISIN, `adj_close`, returns, volume/turnover averages. BPCL correctly adjusted across the 2024 bonus (ret_1d −1.8% on ex-date; our raw `stock_prices` shows 626→307). 669 of 2,182 symbols on 2024-06-20 are outside our universe. Raw OHLC/delivery not in `metrics/`. |
| ✅ WORKS | A1c MTO delivery 2015 | Per-symbol delivery qty/% |
| ✅ WORKS | A2 BSE `Corp_Shareholding_ng` | Filing index to 2001 (RELIANCE), 2010 (PERSISTENT, GRAVITA). XBRL files from 2016 (GRAVITA 44 quarters). **Retail count parsed:** Jun-2016 GRAVITA `…UpToRsTwoLakh` = 8,323 of 8,841 total. The XBRL path is `https://www.bseindia.com` + `XBRLAttachment`. 2025+ files are iXBRL `.html` and need an `ix:` parser. |
| ✅ WORKS | A2 NSE `corporate-share-holdings-master` | Per-symbol only from **Sep-2021**. XBRL has per-category `NumberOfShareholders`. BSE is the deeper source. |
| ✅ WORKS | A2b Screener counts + investors API | 12 quarters (Sep-2023→Jun-2026) on the page we already fetch. `/api/3/{id}/investors/…` returns named holders. |
| ✅ WORKS | A3 NSE results | `corporates-financial-results`: metadata 2005+, XBRL (84 tags incl. revenue, PAT, EPS, board-meeting date) **only up to Dec-2024**. 2025+ is at **`/api/integrated-filing-results`** (found by probe; iXBRL). Two parsers needed. |
| ✅ WORKS (L/M) | A4 Yahoo trend/revisions | `eps_trend` 7/30/60/90d, `eps_revisions`, low/high/#analysts for RELIANCE and PERSISTENT. **GRAVITA (SMALL) all NaN.** |
| ✅ **BIG** | A4 Yahoo `get_earnings_dates` | EPS estimate vs actual per quarter: **RELIANCE 78 quarters to 2007, PERSISTENT 66 to 2010, GRAVITA 15 to 2015.** A free surprise history, and the missing input for PEAD. PIT UNVERIFIED (is the estimate frozen at report?). |
| ✅ WORKS | B1 NSE `corporate-credit-rating` | Takes `from_date/to_date`; **back to at least Jan-2025** (not Aug-2025). ~1,360 rows/quarter; 82% carry `CreditRatingEarlier`, so direction is computable even for "Other". Labelled downgrades stay rare (2 vs 62 upgrades in Q1-2025). |
| ✅ WORKS | B1 BSE rating PDFs | Live under **`AttachHis`** (AttachLive 404). 5 of 6 random 2025+ letters are text-extractable with direction words; 2 of 6 were downgrades, one under a neutral headline. CARE page-1 "Downgraded from CARE A" and CRISIL HTML verified; both carry the rating-history annexure. |
| ✅ WORKS | B3 legacy F&O bhav 2015 | 29k contracts; SETTLE_PR, OPEN_INT → IV backfill feasible |
| ✅ WORKS | B4 `IndexInclExcl.xls` | Nifty 50 events through 2020-07 (multi-sheet; parse every sheet) |
| ✅ WORKS | B5 NSE `public-past-issues` | 1,458 issues back to 2012, incl. SME |
| ✅ WORKS (TLS) | B6 VAHAN | python-requests gets a **connection reset**. A curl_cffi `chrome` session gets 200, **no captcha**, ViewState present. Declare the host with `impersonate`. |
| ✅ WORKS | B7 Robbie Andrew CSVs | 63 files (POSOCO, coal, aluminium, cement…) |
| ✅ WORKS | B8 FBIL / RBIH DBIE / PPAC | FBIL publication list; DBIE search finds "Sectoral Deployment of Non-Food Gross Bank Credit"; PPAC JSON with monthly figures |
| ✅ WORKS | C SLB | Bhavcopy and open positions 2021 + 2026; thin (36 → 180 traded rows/day). SLBM SQLite (76 MB) present. |
| ✅ WORKS | NSCCL `CMVOLT` | 4,952 symbols/day, exchange EWMA volatility |
| ✅ WORKS | NSE `daily-reports?key=SLBS` manifest; NextApi `GetQuoteApi` | Both 200 (quote includes the order book) |
| ⚠️ PARTIAL | PR zip `MCAP` | MCAP file only from 2023-01…2024-04 onward, so **no long PIT cap history from it**. Bc/bh/Pd files exist back to 2015. |
| ❌ DEAD | BSE `SastReg31/w`; NSE `corporate-sast-reg31`, `corporates-pledgedata` | HTML / 404 |
| ❌ DEAD | iShares INDA holdings JSON | Returns an HTML page |
| ⏸ NEEDS ACCOUNT | Fyers, Upstox, ICICI Breeze, Kite pricing | Not probed |
| — not probed | `charting.nseindia.com` chart backend | Request format not obtained |

## Ranked build queue

### Tier A — high value, low effort, build next

| # | Unlock | Route | Gives | Depth / PIT | Evidence | Effort |
|---|---|---|---|---|---|---|
| A1 | **Survivorship-free adjusted price panel** (D3) | Legacy `nsearchives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MMM}/cm{DD}{MMM}{YYYY}bhav.csv.zip` (to 2024-07-05), then UDiFF `/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip`. ~~Adjustments via `PREVCLOSE(t)/CLOSE(t-1)`~~ (❌ smoke test: PREVCLOSE is unadjusted). Renames via `/content/equities/symbolchange.csv`. Key by ISIN (~2010+). | OHLCV for every symbol that traded, dead ones included | 1994+ · PIT | VERIFIED (our DB). [nsefactor](https://github.com/AnoopIbrampur/nsefactor) built 2015→2026 with 933 delisted ISINs | M |
| A1b | Zero-NSE-request fast path / cross-check for A1 | HuggingFace [`tejhq/indian-markets`](https://huggingface.co/datasets/tejhq/indian-markets) parquet, nightly, MIT | Bhavcopy, corp actions, back-adjusted prices, ISIN↔symbol history, PIT top-500 | 2010+ · delisted kept · no delivery · demergers/rights not adjusted | SOURCED | S |
| A1c | Pre-2020 delivery % (extends `delivery_anomaly_z`, our strongest factor) | `nsearchives…/archives/equities/mto/MTO_{DDMMYYYY}.DAT` | Delivery qty/% incl. delisted | ~2002+ | UNVERIFIED depth | S |
| A2 | **Shareholding-pattern XBRL** (completes D1) | BSE `api.bseindia.com/BseIndiaAPI/api/Corp_Shareholding_ng/w?scripcode={code}&flag=0&indtype=` (**send Referer, never Origin** — Origin returns an 1814-byte error shell). NSE `api/corporate-share-holdings-master?index=equities&from_date=&to_date=` → `xbrl` link. | `NumberOfShareholders` per category (retail ≤₹2L), every named holder >1%, FPI names, locked-in shares | iXBRL ~2018+ (BSE index ~26y) · PIT via broadcast time · BSE covers delisted | SOURCED: [NseIndiaApi sample](https://github.com/BennyThadikaran/NseIndiaApi/blob/main/src/samples/shareholding.json), [BSE spec](https://github.com/satwikbasu/indian-market-data-endpoints/blob/main/endpoints/lodr-shareholding.md). **Read [EQATS](https://github.com/sparlit/EQATS) before building**: 4 taxonomy versions; category contexts hold per-bucket counts, and the wrong context gives a wrong company count | M |
| A2b | Smoke test for A2, zero extra requests | Parse the "No. of Shareholders" row from the Screener company page `fetch_export` already GETs and discards ([screener_pull.py:193](../../sources/screener_pull.py#L193)) | Total/retail counts, ~12 quarters | NOT PIT (quarter labels, revised in place): lag quarter-end + 21d | VERIFIED (page already fetched) | S |
| A3 | **Results on filing day** (fixes the up-to-a-month Tickertape lag) | NSE `api/corporates-financial-results?index=equities&period=Quarterly&from_date=&to_date=` → `nsearchives…/corporate/xbrl/*.xml`. `nselib.financial_results_for_equity()` parses ~93 tags. | First-reported P&L, EPS, segments, exact release timestamp | NSE 2018-05+, BSE 2017-04+ · PIT, unrestated. Integrated Filing schema from 2025-04 (second parser). | SOURCED ([nselib src](https://raw.githubusercontent.com/RuchiTanmay/nselib/main/nselib/capital_market/get_func.py)). `nse_insider.py` already parses nsearchives XBRL | S–M |
| A4 | **Estimate revisions and surprise, forward** | yfinance modules `eps_trend`, `eps_revisions`, `earnings_estimate`, `earnings_history`; plus `get_earnings_dates(limit=100)` | EPS now / 7 / 30 / 60 / 90 days ago; up/down counts; low/high (dispersion); 4 quarters of surprise now, possibly more | Collect-forward, but each snapshot carries 90 days of lookback | SOURCED. **.NS coverage UNVERIFIED**: 3-stock smoke test first | S |
| A5 | **Transcripts step** (repair, not new) | `sources/transcripts_pull.py` has no pipeline step or cron | Q1 FY27 concalls missing | Stale since 2026-06-07 | VERIFIED (DB) | S |

### Tier B — clear value, medium effort

| # | Unlock | Route | Notes | Evidence |
|---|---|---|---|---|
| B1 | **Credit-rating direction** (un-defers checklist 1e) | Forward: NSE `api/corporate-credit-rating` (`RatingAction`, `DateofCR`, ISIN). Backfill 2018+: page-1 "Rating Action" table in CARE PDFs (`careratings.com/upload/CompanyFiles/PR/…`), CRISIL HTML (`crisil.com/mnt/winshare/Ratings/RatingList/RatingDocs/…_RR_{id}.html`), ICRA (`icra.in/Rating/GetRationalReportFilePdf?id=`). URLs already in `bse_announcements`. Each release has a 3-year rating-history annexure. | Forward from 2025-08-02 only. Backfill is text extraction plus regex, not OCR. Small agencies (Acuité, Brickwork, Infomerics) not checked. | CARE page-1 text VERIFIED by agent; NSE feed SOURCED ([StockVeda #12](https://github.com/CRS5226/StockVeda/issues/12)) |
| B2 | **Intraday history** (unblocks 3.1c's 3 microstructure factors) | Fyers API v3: 1-min from 2017-07-03, 100k calls/day ≈ whole universe in one day, free account, daily OAuth. Upstox v3: 1-min from 2022-01. ICICI Breeze: 1-sec, 3 years, 5k calls/day. Kite: ~₹500/mo incl. history, up to 10y (our `kite_pull.py` is already built). | Every broker feed covers **listed names only**, so intraday factors stay survivors-only. **Amit's call:** free Fyers vs ₹500 Kite. | SOURCED |
| B3 | Pre-2025-05 F&O → IV backfill | Legacy `nsearchives…/content/historical/DERIVATIVES/{YYYY}/{MMM}/fo{DD}{MMM}{YYYY}bhav.csv.zip` (nselib has no legacy fallback) | Extends `fno_iv_history` years back | Start date UNVERIFIED |
| B4 | Index membership (research 0001 #3) | NSE `archives…/content/indices/IndexInclExcl.xls` (1996–2020, names not symbols) plus niftyindices press releases after that. Or TejHQ PIT top-500. | Better than parsing press releases alone | SOURCED |
| B5 | IPO / anchor lock-in (research 0001 #4) | NSE `api/public-past-issues` (NseIndiaApi `listPastIPO`). Lock-ins are deterministic: 30/90 days from allotment. | Chittorgarh JSON (`webnodejs.chittorgarh.com/cloud/report/data-read/156/…`) is richer but ToS-grey | SOURCED |
| B6 | VAHAN maker × month (plan 0003, autos) | Replay the dashboard's PrimeFaces AJAX calls ([RevTpark/vahan-scraper](https://github.com/RevTpark/vahan-scraper), plain httpx, no captcha code) | Maps to ~10 listed OEMs. Snapshot daily from day 1: late registrations revise counts upward. Needs a strict request budget. | SOURCED; captcha claim to be settled by the smoke test |
| B7 | Company-level industrial output | [Robbie Andrew CSVs](https://github.com/robbieandrew/robbieandrew.github.io) under `/india/data/` (POSOCO daily power 2013+, CIL/SCCL coal, Nalco/Hindalco/Vedanta aluminium, PPAC, cement, steel) | GitHub-hosted, so no government host is touched. Overwritten in place, so we must snapshot. | SOURCED (pushed 2026-09-27) |
| B8 | Macro fills | FBIL G-sec yield curve (`fbil.org.in/wasdm/gsec/fetchfiltered` → `downloadPublished?date=`) replaces the `gsec10_etf` proxy. RBI sector credit via the [RBIH DBIE mirror](https://github.com/Reserve-Bank-Innovation-Hub/dbie.rbihub.in) REST/CSV. PPAC fuel JSON. DGCA airline share (IndiGo). | Copy recipes from [psrohit19/india-macro-tracker](https://github.com/psrohit19/india-macro-tracker) (~45 fetchers with lag/revision notes). Don't depend on the repo itself. | SOURCED |

### Tier C — niche, grey, or skip

- **SLB short-interest proxy.** Thin market (~230 names/day, mostly F&O). Backfill 2021-07+ from the committed SQLite in [krtk-chmp/SLBM](https://github.com/krtk-chmp/SLBM) with zero NSE requests.
- **Event-level pledge.** BSE `SastReg31/w`; response shape UNVERIFIED. The quarterly NSE `corporate-pledgedata` duplicates Tickertape `pledge_pct`.
- **IBBI insolvency list; SEBI debarred list.** The debarred list is OpenSanctions `in_nse_debarred`, CC-BY-NC.
- **Order wins.** Parse ₹-crore amounts from `bse_announcements` headlines; structured XBRL only since 2025-07.
- **Google Trends.** Apply for the official Trends API alpha. The pytrends forks drive a logged-in browser (grey).
- **ToS-grey, avoid:**
  - Investing.com surprise history (Cloudflare, ToS bans scraping)
  - Chittorgarh API
  - RBI DBIE gateway (copies the site's client-side encryption)
- **Dead ends — don't re-probe:**
  - Wayback snapshots of estimate pages (1–2/year at best)
  - Trendlyne (405, no free API)
  - MCA charges (captcha/paid)
  - GST portal (JavaScript anti-bot; don't bypass)
  - Per-stock daily FPI for the whole universe (only the near-cap breach list exists)
  - Free multi-year MF holdings (only the >1% named holders in A2)
  - Pre-2026 consensus revision history (buy or wait)
  - PMI detail (licensed), rail freight, IPA port data (stops 2024-11)

## Technique catalogue — smaller hacks surfaced by the sweep (all UNVERIFIED unless marked)

**Piggyback: let someone else's scraper carry the IP risk**
- SLB history 2021+ from the SQLite committed in [krtk-chmp/SLBM](https://github.com/krtk-chmp/SLBM).
- Survivorship-free bhavcopy 2010+ from HuggingFace [`tejhq/indian-markets`](https://huggingface.co/datasets/tejhq/indian-markets).
- Power, coal and aluminium from [Robbie Andrew's CSVs](https://github.com/robbieandrew/robbieandrew.github.io).
- DBIE tables via the RBIH REST mirror.
- NSE debarred list via OpenSanctions `in_nse_debarred`.

**NSE files we don't use yet**
- `/api/daily-reports?key=SLBS` returns the day's file manifest, so URLs needn't be guessed. Other `key=` values probably exist.
- The PR zip `archives/equities/bhavcopy/pr/PR{DDMMYY}.zip` (~2010+) holds a daily `MCAP` file, giving **point-in-time market cap per stock**. That would fix census finding #1 (`stocks.cap_tier` overwritten in place, so backtests use today's tier). It also holds `Bh` (circuit/band hits, research 0001 #5) and `Bc` (corporate actions).
- NSCCL `CMVOLT`/`FOVOLT` (the exchange's own daily volatility), `mwpl_cli_*.xls` (position-limit usage) and SPAN risk arrays.
- `charting.nseindia.com/v1/charts/symbolHistoricalData` is NSE's own chart backend: intraday bars with no login. Depth unknown.
- NextApi replacements for the endpoints that broke on 2026-09-26/27: `GetQuoteApi?functionName=getSymbolData`, `marketWatchApi?functionName=getIndicesData`.

**Ownership**
- Screener `/api/3/{company_id}/investors/{promoters|foreign_institutions|domestic_institutions|public}/quarterly/` returns named holders per quarter. The yearly tab reportedly carries shareholder counts back to Mar-2017 (checked on TCS).
- Passive-FPI flow proxy: iShares INDA/SMIN holdings JSON with `asOfDate=` gives daily share counts per Indian stock held by the US India ETFs.

**Estimates**
- yfinance's `/v1/finance/visualization` endpoint (EPS estimate / actual / surprise %) "stopped updating Summer 2025", but may still serve pre-2025 history for .NS. Cheap to test alongside A4.

**Events**
- Rating PIT timing without a dissemination timestamp: annexure date + 7 working days (the SEBI publish deadline).
- One recent rating PDF's 3-year history annexure backfills the whole issuer.
- ICRA (`id` ~100000–143700) and India Ratings (`pressrelease/{int}` ~38000–78200) use sequential IDs, so they are enumerable.
- Anchor lock-in expiry needs no data source: allotment date + 30 / 90 days.

**Derivatives**
- Fyers history includes **expired F&O contracts** at 1-min from 2017, i.e. intraday options history.

**Government**
- DGCA reports sit in a public S3 bucket, and each December report carries all 12 months.
- PPAC has a hidden `AjaxController` POST that returns fuel consumption from FY1999.
- FBIL takes `authenticated=false` + Referer.
- VAHAN can be replayed as PrimeFaces AJAX, no browser.
- [india-macro-tracker](https://github.com/psrohit19/india-macro-tracker) fetcher docstrings map each series' lag and revision behaviour, including a GST PDF filename map.

## Risks and hygiene

- **NSE archive backfills share the NSE host budget.** Declare `nsearchives.nseindia.com` under the `nse`/`nse_archives` host, and never run them alongside the pipeline (harvest lock). `tools/build_historical_universe.py` still points at `archives.nseindia.com`.
- **NSE endpoint churn 26–27 Sep 2026:** `/api/quote-equity` 403, `/api/equity-stockIndices` 404, `/api/corporate-shareholding-pattern` 404 ([PR #15](https://github.com/rajemishra-svg/indian-equity-investor/pull/15)). Also one report of NSE refusing dated queries from cloud IPs. Our VM is Oracle Cloud, so smoke-test A1/A2/A3 early.
- **Library drift:**
  - jugaad-data: installed 0.33.1 vs 0.35.9 upstream (VERIFIED installed version); upgrade before any backfill.
  - Bharat_sm_data (our Tickertape layer): last release 2025-07, so rising break risk.
  - [NseIndiaApi](https://github.com/BennyThadikaran/NseIndiaApi) (`nse` 4.0.1, 2026-08-31) is more active than nselib 2.5.1 and covers corporate filings nselib lacks. Adopt alongside it, through `sources/_http`.
- **Revisions:** VAHAN, DGCA, PPAC, FADA and the RBI tables revise past values in place. Snapshot on ingest so backtests read first-release values.

## Docs this corrects

- Plan 0014: D3 "~2023 floor" and "Pre-2023 delisted prices — gone" → wrong (implementation note appended).
- `docs/reference/kite-setup.md`: pricing (₹500/mo incl. history since Feb 2025) and depth (up to 10y intraday, 60-day chunks). SOURCED from Zerodha support; confirm before editing.
