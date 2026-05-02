# Alpha Signal v2 — Project Context for Claude Code

> AI-Native Daily Stock Intelligence for the Indian Retail Investor
> Owner: Amit Bhagat | Bengaluru | Oracle Cloud Ubuntu VM
> Version 2.0 | March 2026

---

## Critical Rules — Read Before Every Task

1. **Always activate venv first:** `source ~/alpha-signal/venv/bin/activate`
2. **Never run two harvester scripts simultaneously** — doubles request rate, risks IP block
3. **Never call `build_universe()`** — broken (KeyError: 'stock'). Always use `--resume` to load existing `universe.csv`
4. **Tickertape SIDs ≠ NSE tickers** — e.g. REDY not DRRD, BJFN not BJFIN, HDBK not HDFCBANK. Always use universe.csv SIDs
5. **Smoke test with 3 stocks** before any full run
6. **Checkpoint every 200 stocks** in any harvester. Resume via harvest_log.json
7. **2-second delay** between API calls minimum
8. **Credentials live in `run_pipeline.sh`** as `export` statements — not in `~/.bashrc`, never in code
9. **Smart quotes from copy-paste break shell scripts** — always retype quotes manually
10. **CSV checkpoints** don't exist until the 200-stock milestone; sanity checks must wait for that point
11. **pip installs:** always use `--break-system-packages` flag

---

## v2 Philosophy — Core Principles

1. Use what we have built. Never rebuild from scratch.
2. Baby steps. One validated signal at a time. No Mt. Everest jumps.
3. Data pipeline first. Complete data foundation before signal work.
4. Validate before adding complexity. Backtester must confirm IC before any signal is trusted.
5. AI at every layer. Not just the dossier — signals, weights, discovery, and self-improvement.
6. India-specific always. Emerging market research over US-centric papers.
7. Cost discipline. Rs 450/month now. Never add paid sources without proven ROI.

---

## v2 Architecture — Four Layers

| Layer | What it does | Current state | v2 target |
|-------|-------------|---------------|-----------|
| Data Pipeline | Fetch, store, refresh all data sources | ~100% complete (A1-A5 done) | All sources harvested and refreshing |
| Signal Layer | Compute research-backed factors per stock | B1-B10 done, 5 new signals live | 10+ validated signals, t-stat >= 3.0 each |
| Model Layer | Combine signals into ranked predictions | Linear weighted scorecard, gut-feel weights | Fama-MacBeth → XGBoost → multi-agent AI |
| Output Layer | Deliver ranked picks with explanation | Email + Streamlit + AI dossier | SHAP-informed dossier, regime-aware ranking |

Each layer must be healthy before the next is added.

---

## Project Layout

```
~/alpha-signal/
├── scripts/                    # Numbered pipeline scripts (00–25+)
│   ├── 00-11                   # Core pipeline: fetch, screen, sentiment, AI classify, dossier, email
│   ├── 14_macro_pulse.py       # 22 macro indicators, 27 sector scores
│   ├── 17_forensic_guard.py    # Beneish M-Score + Altman Z-Score
│   ├── 22_data_harvester.py    # Income, balance sheet, cash flow, shareholding
│   ├── 23_slug_mapper.py       # SID → Tickertape URL slug mapping
│   ├── 24_backtester.py        # Built, waiting to run (Phase C)
│   ├── 25_analyst_harvester.py # Analyst consensus from __NEXT_DATA__
│   ├── tickertape_utils.py     # Reusable Tickertape client + all parsers
│   ├── page_methodology.py     # "How It Works" Streamlit page
│   ├── page_ai_assistant.py    # AI Assistant Streamlit page (chat UI, Haiku routing + Sonnet streaming)
│   ├── alpha_assistant_prompt.py # Full system prompt for AI Assistant (all scripts, signals, data files)
│   └── data_query_engine.py    # Data access functions: load_enriched, query_stock, query_top_n, etc.
├── data/
│   ├── harvester/              # universe.csv, quarterly_income.csv, annual_balancesheet.csv,
│   │                           # annual_cashflow.csv, slug_map.csv, shareholding.csv, errors.csv
│   ├── analyst/                # consensus.csv
│   ├── smart_money/            # bulk_30d.csv, delivery_30d.csv, smart_money_score.csv, raw/
│   ├── events/                 # earnings_calendar.csv
│   ├── snapshots/              # all_snapshots.csv, snapshot_YYYY-MM-DD.csv
│   └── signals/                # piotroski.csv, accruals.csv (Phase B outputs)
├── config/
│   └── settings.py             # Centralised config: EMAIL_CONFIG, FORENSIC_CONFIG, ZERODHA stubs
├── venv/                       # Python virtual environment
├── run_pipeline.sh             # Cron orchestrator (9AM IST daily) + all export credentials
├── CLAUDE.md                   # This file
└── .git/                       # Private repo: git@github.com:amitbhagat221-rgb/alpha-signal.git
```

---

## What's Already Built and LIVE

| Component | Status |
|-----------|--------|
| Oracle Cloud VM — 4 OCPU ARM, 24GB RAM, Ubuntu 24.04 | LIVE |
| Pipeline scripts 00-11 (fetch, screen, sentiment, AI classify, dossier, email) | LIVE |
| Forensic Guard — Beneish M-Score + Altman Z-Score (script 17, DEBUG=False) | LIVE |
| Macro Pulse — 22 macro indicators, 27 sector scores (script 14) | LIVE |
| Entity-matched news (11 RSS feeds, curated aliases, blocklist) | LIVE |
| AI routing — Haiku (bulk) + Sonnet (dossier), ~Rs 15/day | LIVE |
| Streamlit dashboard — 8 pages with sidebar nav | LIVE |
| "How It Works" page (page_methodology.py) — updated March 2026 for all 8 pre-phase-C fixes | LIVE |
| AI Assistant page (page_ai_assistant.py) — chat UI, two-pass Haiku routing + Sonnet streaming answers | LIVE |
| GitHub private repo + auto-backup via run_pipeline.sh | LIVE |
| Cron automation — 9AM IST daily, 10:30AM Saturday refresh | LIVE |
| NSE Smart Money Accumulator — 16_smart_money.py, 4 signals, cron-fed daily | LIVE |
| Earnings Calendar — 18_earnings_calendar.py, NSE API, rolling calendar | LIVE |
| Snapshot Archiver — 26_snapshot_archiver.py, cumulative enriched CSV for backtesting | LIVE |
| Piotroski F-Score — 27_piotroski.py, 1,978 stocks, 9-factor, data/signals/piotroski.csv | LIVE |
| Accruals Quality + Persistence — 28_accruals.py, 2,426 stocks, 4-factor, data/signals/accruals.csv | LIVE |
| Analyst Consensus Signal — 29_consensus_signal.py, 2,398 stocks, 4 sub-signals, data/signals/consensus.csv | LIVE |
| Promoter Buying Momentum — 30_promoter_signal.py, 2,438 stocks (100%), data/signals/promoter.csv | LIVE |
| Business Group Risk Tagger — 31_group_tagger.py, 15 conglomerates, data/reference/business_groups.csv | LIVE |
| Signal Validation Backtester — 24_backtester.py, 3 modes (PIT/proxy/recon), --recon flag adds historical reconstruction with filing lags | LIVE |

---

## Data Inventory — Harvested CSVs

| File | Location | Rows | Content | Status |
|------|----------|------|---------|--------|
| universe.csv | data/harvester/ | 2,500 | sid, name, ticker, sector, in_nifty500 | COMPLETE |
| quarterly_income.csv | data/harvester/ | 21,571 | Revenue, EPS, profit — 10 quarters | COMPLETE |
| annual_balancesheet.csv | data/harvester/ | 19,196 | Assets, equity, debt — 10 years | COMPLETE |
| annual_cashflow.csv | data/harvester/ | 19,155 | OCF, capex, FCF — 10 years | COMPLETE |
| slug_map.csv | data/harvester/ | 2,500 | sid → Tickertape URL slug (97.6% mapped) | COMPLETE |
| shareholding.csv | data/harvester/ | 14,135 | Promoter%, FII%, MF%, DII% — 6 quarters | COMPLETE |
| consensus.csv | data/analyst/ | 2,439 | Price target, buy%, EPS, revenue forecasts | COMPLETE |
| errors.csv | data/harvester/ | ~60 | ETFs + micro-caps with no data | COMPLETE |
| bulk_30d.csv | data/smart_money/ | 38 (Day 1, grows daily) | Net bulk buy vol, repeat buyers, premium buy per stock | LIVE |
| delivery_30d.csv | data/smart_money/ | 2,448 | 30-day avg delivery% per stock | LIVE |
| smart_money_score.csv | data/smart_money/ | 2,464 | Combined smart money signal (bulk×0.6 + delivery×0.4) | LIVE |

Total disk: ~14 MB. All at ~/alpha-signal/data/

---

## Tickertape API — Two Tiers

**Tier 1: Bharat_sm_data library (sid-based)**
- `from Fundamentals.TickerTape import Tickertape`
- Functions: get_income_data(sid), get_balance_sheet_data(sid), get_cash_flow_data(sid), get_score_card(sid)

**Tier 2: __NEXT_DATA__ JSON scrape (slug-based)**
- Slug format: `stocks/reliance-industries-RELI` (no leading slash, sid appended)
- Slug discovery: GET `tickertape.in/stocks/{sid}` → follow HTTP redirect

**Confirmed __NEXT_DATA__ JSON paths (March 2026):**
| Data | Path | Notes |
|------|------|-------|
| Analyst consensus | props.pageProps.securitySummary.forecast | totalReco, percBuyReco |
| Price target history | props.pageProps.forecastsHistory.price | Array of {date, value} |
| EPS forecast | props.pageProps.forecastsHistory.eps | Array of {value, date, change} |
| Revenue forecast | props.pageProps.forecastsHistory.revenue | Array of {value, date, change} |
| Shareholding | props.pageProps.securitySummary.holdings.holdings | Quarterly entries |
| Key ratios | props.pageProps.securitySummary.keyRatios | Array of {backL, value} |
| Financial summary | props.pageProps.securitySummary.financialSummary | 5yr revenue/profit |
| Dividends | props.pageProps.securitySummary.dividends | past + upcoming arrays |
| Events | props.pageProps.securitySummary.events | Earnings, AGMs, announcements |
| AI summary | props.pageProps.securitySummary.aiSummary.summary | Text string |
| Ratings | props.pageProps.securitySummary.ratings | NULL without login session |

---

## Network — What Works vs Blocked (Oracle Cloud IP)

**Working:** tickertape.in, analyze.api.tickertape.in, archives.nseindia.com, yfinance (.NS)
**Blocked (403):** get_ticker() search, MoneyControl, www.nseindia.com main site

---

## Harvester Conventions

- Script naming: sequential numbers (`16_smart_money.py`, `17_forensic_guard.py`)
- CLI flags: `--resume`, `--refresh`, `--flag-only` (e.g. `--shareholding-only`)
- Checkpoint: save CSV every 200 stocks
- Resume: read `harvest_log.json` for last completed index
- Error handling: log failures to errors.csv, skip and continue

---

## Phase A — Data Pipeline (Sessions 1-5)

**Goal:** Complete data pipeline. All sources harvested and refreshing on schedule.

| Session | Build | Output | Status |
|---------|-------|--------|--------|
| A1 | Cash flow harvester — 2,500 stocks, FCF/capex/CFO | annual_cashflow.csv (19,155 rows) | ✅ DONE |
| A2 | Slug mapper + shareholding harvester | slug_map.csv + shareholding.csv (14,135 rows) | ✅ DONE |
| A3 | Analyst consensus harvester | consensus.csv (2,439 rows) | ✅ DONE |
| A4 | NSE smart money accumulator + 16_smart_money.py | bulk_30d.csv (38 symbols), delivery_30d.csv (2,448 rows), smart_money_score.csv (2,464 rows) | ✅ DONE |
| A5 | Earnings calendar + snapshot archiver (18_earnings_calendar.py + 26_snapshot_archiver.py) | earnings_calendar.csv (65 events), snapshots/all_snapshots.csv (494 rows Day 1) | ✅ DONE |

### Session A4 — NSE Smart Money Accumulator ✅ DONE

**Data sources (confirmed working from Oracle VM):**
| URL | Content | Cadence |
|-----|---------|---------|
| archives.nseindia.com/content/equities/bulk.csv | Daily bulk deals — entity, stock, qty, price | Daily |
| archives.nseindia.com/content/equities/block.csv | Daily block deals | Daily |
| archives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv | Full bhavcopy incl. delivery% (dated URL — undated is stale 2019 data) | Daily |

**Output files (first day, builds to full 30-day window via cron):**
- `data/smart_money/bulk_30d.csv` — 30-day rolling bulk/block deals (38 symbols Day 1)
- `data/smart_money/delivery_30d.csv` — 30-day average delivery% per stock (2,448 rows)
- `data/smart_money/smart_money_score.csv` — combined smart money signal per stock (2,464 rows)
- `data/smart_money/raw/` — daily raw files: `bulk_YYYYMMDD.csv`, `bhav_YYYYMMDD.csv`

**Score formula:** `smart_money_score = bulk_score × 0.6 + delivery_score × 0.4`

**Key implementation notes:**
- NSE returns 503 to bare curl (Akamai). Use Python `requests.Session()` with browser User-Agent.
- Bhav URL must be dated (`sec_bhavdata_full_DDMMYYYY.csv`). 5-day fallback for weekends/holidays.
- No dated URL exists for bulk/block deals — daily-only, accumulate raw files via cron.
- `SERIES` column values have leading spaces in raw CSV — always `str.strip()` before `== "EQ"` filter.
- Skip-logic checks raw file existence independently (bulk vs bhav), not a shared harvest log.

### Session A5 — Earnings Calendar + Snapshot Archiver

**Two scripts:**
- `18_earnings_calendar.py` — fetches NSE event-calendar API daily, accumulates results events to `data/events/earnings_calendar.csv`. Deduplicates on (symbol, date). Maps NSE ticker → sid via universe.csv.
- `26_snapshot_archiver.py` — reads latest `enriched_YYYY-MM-DD.csv` from screener_output/, stamps `snapshot_date`, appends to `data/snapshots/all_snapshots.csv` (cumulative backtesting archive) and saves per-day copy.

**Data source (confirmed working):**
| URL | Content | Cadence |
|-----|---------|---------|
| www.nseindia.com/api/event-calendar | Board meetings + results events, ~2 weeks ahead, JSON | Daily |

**Output files:**
- `data/events/earnings_calendar.csv` — cumulative upcoming results (symbol, sid, date, company, purpose, bm_desc, added_date)
- `data/snapshots/all_snapshots.csv` — cumulative daily enriched data with snapshot_date column (grows ~500 rows/day)
- `data/snapshots/snapshot_YYYY-MM-DD.csv` — per-day copies for quick lookup

**Pipeline position:** Step 4/19 (earnings_calendar after insider, before AI classify); Step 16/19 (snapshot after sector analysis, before dossier)

---

## Phase B — Signal Build (Sessions 6-10)

**Goal:** Add 5 research-backed signals. Each validated before next is built. No signal enters model without t-stat >= 3.0.

| Session | Signal | Academic Basis | Data Needed | Script |
|---------|--------|---------------|-------------|--------|
| ~~6~~ | ~~Piotroski F-Score (0-9)~~ | Piotroski 2000, emerging markets validated | Balance sheet + income (HAVE) | 27_piotroski.py ✅ DONE — 1,978 stocks, 45 stocks at 9/9 |
| ~~7~~ | ~~Accruals quality + earnings persistence~~ | Sloan 1996 (most replicated anomaly) + ISB course | Cash flow + income (HAVE) | 28_accruals.py ✅ DONE — 2,426 stocks, data/signals/accruals.csv |
| ~~8~~ | ~~Smart money integration~~ | Institutional flow research | NSE accumulator (A4) | 08_integrate_sentiment.py v5 ✅ DONE — all three integrated as ±4 pt soft adjustments |
| ~~9~~ | ~~Analyst consensus + target price upside~~ | PEAD literature, strong in India | Analyst consensus (HAVE) | 29_consensus_signal.py ✅ DONE — 2,398 stocks, 4 sub-signals, data/signals/consensus.csv |
| ~~10~~ | ~~Promoter buying momentum~~ | Insider trading literature | Shareholding (HAVE) | 30_promoter_signal.py ✅ DONE — 2,438 stocks (100% coverage), data/signals/promoter.csv |

### Session B7 — Accruals Quality + Earnings Persistence ✅ DONE

**Four sub-signals (28_accruals.py):**
- `cf_accruals_ratio`: (LTM NI − annual OCF) / avg_assets — Sloan CF version. Lower = cash confirms earnings (quality).
- `bs_accruals_ratio`: Sloan (1996) balance-sheet accruals = (ΔCA − ΔCash) − (ΔCL − ΔShortTermDebt) − Depreciation, divided by avg_assets. Skipped for Financials sector.
- `eps_cv`: Coefficient of variation of last 8Q EPS (std / |mean|). Lower = more stable earnings.
- `earnings_beat_rate`: Fraction of last 4Q where NI > same Q prior year. Higher = consistent YoY growth.

**Signal aggregation:** Percentile rank each component within universe → weighted avg (CF 35%, BS 35%, eps_cv 15%, beat_rate 15%). Missing components are excluded from denominator. Output: `accruals_signal` 0–1.

**Coverage:** 2,426/2,500 stocks with non-NaN signal. 1,977 "full" (all 4 components). Financials skip BS accruals (partial_3of4).

**Pipeline position:** Step 11/19 (after Piotroski, before consensus).

**Caution:** Very negative CF/BS accruals in distressed or loss-making companies can score high on "quality" despite being uninvestable. Piotroski and forensic scores will partially offset these at integration.

### Session B9 — Analyst Consensus Signal ✅ DONE

**Four sub-signals (29_consensus_signal.py):**
- `pt_upside`: (price_target / current_price − 1) × 100 — needs CMP from latest screen_*.csv. Only ~494 screener stocks have this; remaining 1,944 get NaN (excluded from their component weighting).
- `buy_pct`: % of analysts with buy recommendation (0–100).
- `eps_growth_pct`: forward EPS growth expectation — clipped to (−50%, +100%) before ranking.
- `revenue_growth_pct`: forward revenue growth expectation — clipped to (−30%, +80%).

**Signal aggregation:** Percentile rank each within universe → NaN-tolerant weighted avg (pt_upside 40%, buy_pct 30%, eps_growth 20%, rev_growth 10%). Output: `consensus_signal` 0–1.

**Coverage:** 2,398/2,438 non-NaN signal. 456 "full" (all 4 inc. pt_upside), 500 partial_3of4, 1,421 partial_2of4 (no price = only eps+rev growth), 61 insufficient.

**Integration (v6):** (consensus_signal − 0.5) × 8, capped ±4. First live run: 194 boosted / 278 penalised within 494-stock screener.

**Email tag:** `Cons=0.72`

**Note:** True earnings revision momentum (change in estimates over time) requires accumulating daily harvests. Current signal is analyst optimism proxy. Will become proper revision momentum once Phase C data work builds a time series.

### Session B10 — Promoter Buying Momentum ✅ DONE

**Three sub-signals (30_promoter_signal.py):**
- `promoter_qoq`: latest quarter promoter% − previous quarter promoter%. Positive = accumulation.
- `promoter_trend_4q`: latest quarter promoter% − 4 quarters ago promoter% (1-year view). Positive = sustained buying.
- `pledge_quality`: 1 − (promoter_pledged_pct / 100). Used directly (not percentile ranked). 0% pledge = 1.0, fully pledged = 0.0.

**Signal aggregation:** QoQ and trend_4q percentile-ranked within universe. Pledge used directly. Weights: QoQ 35%, trend_4q 35%, pledge_quality 30%. Output: `promoter_signal` 0–1.

**Coverage:** 2,438/2,438 stocks (100% — shareholding complete). 2,227 "full" (all 3 components), 207 partial_2of3 (stocks with < 5 quarters = no trend_4q), 4 minimal.

**Integration (v6):** (promoter_signal − 0.5) × 8, capped ±4. First live run: 348 boosted / 134 penalised.

**Email tag:** `Prom=0.73`

**Smoke test results:**
```
RELI  latest=50.01%  qoq=+0.899%  trend_4q=-0.129%  pledge=0.00%  signal=0.7340
TCS   latest=71.77%  qoq=+0.000%  trend_4q=+0.000%  pledge=0.00%  signal=0.6923
INFY  latest=14.52%  qoq=+1.468%  trend_4q=+0.087%  pledge=0.00%  signal=0.9316
```

### Session B8 — Piotroski + Accruals + Smart Money Integration ✅ DONE

**08_integrate_sentiment.py upgraded to v5 (B8), then v6 (B9+B10).** Five total new soft adjustments added (no hard filtering — missing data = 0 pts, neutral):

| Signal | Join path | Adjustment formula | Max impact |
|--------|-----------|-------------------|------------|
| Piotroski F-Score | screener.symbol → universe.ticker → universe.sid → piotroski.sid | (f_score − 4.5) × 0.8, capped ±4 | ±4 pts |
| Accruals signal | same sid join | (accruals_signal − 0.5) × 8, capped ±4 | ±4 pts |
| Smart money | direct symbol join (smart_money_score.csv has NSE symbol) | (score − 50) × 0.08, capped ±4 | ±4 pts |
| Consensus signal | same sid join via universe | (consensus_signal − 0.5) × 8, capped ±4 | ±4 pts |
| Promoter signal | same sid join via universe | (promoter_signal − 0.5) × 8, capped ±4 | ±4 pts |

**Coverage within 494-stock screener:** Piotroski 395/494 (99 missing = Financial sector), Accruals 494/494, Smart money 493/494, Consensus 472/494, Promoter 494/494.

**First live run (2026-03-30 v6):** Piotroski 311/84; Accruals 327/155; Smart money 121/314; Consensus 194/278; Promoter 348/134.

**Signal tags added to email:** `F=7/9`, `Acc=0.72`, `SM=63`, `Cons=0.72`, `Prom=0.73`

**Signals already live (awaiting backtester validation):**
Value (P/E, P/B, EV/EBITDA), Quality (ROE, ROA, D/E), Momentum (3M/6M/12M), Growth (revenue, EPS trend), Sentiment (VADER + custom), Insider buying (BSE promoter trades), AI event classification (Haiku), Forensic penalty (Beneish + Altman), Macro sector overlay, Piotroski F-Score, Accruals quality + persistence, Analyst consensus + PT upside, Promoter buying momentum

---

## Phase C — Validation (Sessions 11-13)

**Goal:** Know what actually works. Derive empirical weights. Add regime awareness.

| Session | Build | Success Criteria | Output |
|---------|-------|-----------------|--------|
| ~~11~~ | ~~Run backtester — IC per signal, t-stat, decay rate~~ | ~~>=3 signals with t-stat >= 3.0~~ | 24_backtester.py ✅ DONE |
| 12 | Fama-MacBeth regression — derive empirical weights | Weights replace gut-feel 22/22/20/20/16 split | weights_config.json |
| 13 | Regime flag — VIX overlay, momentum crash protection | Momentum downweighted in high VIX regime | regime_module.py |

**Key insight:** Current scorecard ≠ factor model. Weights are gut-feel. Fama-MacBeth + IC tracking is deferred to Phase C by design.

### Session C11 — Signal Validation Backtester ✅ DONE (updated 2026-04-03)

**Script:** `24_backtester.py`

**Three IC modes:**
- **PIT** (point-in-time): uses historical enriched snapshots. Core signals have ~3 weeks = 6 IC periods. Need 6+ months for reliable t-stats.
- **Proxy**: current quarterly signal values projected back over 3yr price history. Appropriate for slow-moving fundamentals (Piotroski, accruals, consensus, promoter). Mild look-ahead bias.
- **Recon** (`--recon` flag): rebuilds signals from raw `quarterly_income.csv` + `annual_balancesheet.csv` + 3yr prices with proper 60/75-day filing lags. No look-ahead bias. 28-35 IC periods.

**Results — Proxy mode (N=35 monthly periods, Apr 2023 – Mar 2026):**

| Signal | Mean IC | ICIR | t-stat | L/S Net% | Verdict |
|--------|---------|------|--------|----------|---------|
| consensus | +0.062 | 0.586 | **3.47** | +1.33% | **KEEP** ✓ |
| piotroski | +0.006 | 0.056 | 0.33 | -0.34% | DROP (wider universe vs C11 original) |
| accruals | -0.039 | -0.441 | -2.61 | -1.97% | DROP (inverted — confirmed) |
| promoter | -0.002 | -0.025 | -0.15 | -0.21% | DROP |

**Results — Recon mode (N=28-30 periods, reconstructed from fundamentals):**

| Signal | Mean IC | ICIR | t-stat | L/S Net% | Verdict |
|--------|---------|------|--------|----------|---------|
| value_recon | +0.055 | 0.498 | **2.64** | +0.56% | **KEEP** ✓ (earnings yield + book-to-price, 60/75d lag) |
| composite_recon | +0.036 | 0.346 | 1.83 | +0.07% | DROP (equal-wt 4 signals) |
| momentum_recon | +0.018 | 0.139 | 0.74 | -0.30% | DROP |
| quality_recon | -0.007 | -0.095 | -0.50 | -0.86% | DROP |
| growth_recon | +0.006 | 0.085 | 0.34 | -0.80% | DROP (only 16 periods) |

**Key findings:**
1. **Value (earnings yield + book-to-price) is empirically validated** — first recon signal with t>2.5. Pure fundamental, no look-ahead bias.
2. **Consensus (analyst estimate revisions) is the strongest proxy signal** — t=3.47 holds across 3 years.
3. **Accruals is consistently inverted** — confirmed again. Action already taken (downweighted in 08_integrate_sentiment.py).
4. **Piotroski result context:** C11 original showed t=3.37 on a 2yr, 490-stock Nifty-500 universe. New 3yr result (t=0.33) covers a wider universe. Piotroski may be universe-dependent. Still KEEP as a qualitative screen.
5. **Growth signal weak** — only 16 periods due to YoY lag. YoY requires 5 quarters filed = 18+ months of data. Needs more history.

**Run commands:**
```bash
python scripts/24_backtester.py --no-download    # use cache, skip download
python scripts/24_backtester.py --recon           # 3yr download + reconstruction
python scripts/24_backtester.py --smoke --no-download  # quick syntax/flow check
```

**Outputs:**
- `data/backtest/signal_validation_report.csv` — per-signal IC/ICIR/t-stat
- `data/backtest/ic_decay_curves.csv` — IC at 5/10/20/40/60 day horizons
- `data/backtest/factor_correlation_matrix.csv` — pairwise Spearman
- `data/backtest/backtest_report.html` — formatted HTML report

**Survivorship bias note:** Universe is current listings only. Kohli et al. estimate 4.4% annual inflation for Indian value portfolios. All IC stats are upper bounds.

**Ticker prioritization fix (2026-04-03):** Enriched-file stocks are now always prioritised in the price download (regardless of alphabetical position) so proxy IC has correct overlap with fwd_proxy.

---

## Phase D — Model Upgrade (Sessions 14-17)

**Goal:** Replace linear scorecard with XGBoost. Add SHAP to dossier. Build PEAD.

| Session | Build | Success Criteria | Output |
|---------|-------|-----------------|--------|
| 14 | XGBoost model — train on validated signals, predict 20-day quintile | Out-of-sample accuracy > linear baseline | 31_xgboost_model.py |
| 15 | SHAP integration — per-stock explanations into dossier | Dossier explains top 3 signal drivers | 11_ai_dossier v2 |
| 16 | PEAD signal — post earnings drift detection | Fires within 2 days of earnings beat | 32_pead_signal.py |
| 17 | Multi-agent AI scaffold — 5 specialist agents | Agent outputs coherent per stock | 33_multi_agent.py |

**Multi-agent design (MarketSenseAI-inspired):**
- News agent: 30-day progressive narrative per stock from RSS feeds
- Fundamentals agent: extracts signals from quarterly filings, flags QoQ changes
- Macro agent: maps RBI/PIB/MOSPI releases to sector and stock impact
- Smart money agent: interprets bulk/block deal context and patterns
- Signal agent: synthesizes all four into conviction score and rationale

Key difference: current AI layer is descriptive (writes dossier after scoring). Multi-agent layer is generative — it produces signals, not just narratives.

---

## Phase E — Scale and Polish (Sessions 18-22+)

| Session | Build | Notes |
|---------|-------|-------|
| 18 | Expand to 2,500 stocks — multibagger scoring profile | Different weights for small/mid cap |
| 19 | AI signal discovery engine — Claude reads papers, proposes signals | Weekly paper batch, auto-backtest |
| 20 | Continuous alpha learning — IC decay monitoring, auto-retire signals | Monthly retraining trigger |
| 21 | RAG on Indian filings — vector DB of annual reports, con-calls | Query filing changes in real time |
| 22+ | Zerodha Kite Connect — portfolio tracking + real-time alerts | Rs 500/month, only in Phase E |

---

## Advanced Signals — Phase C/D (After Backtesting)

| Signal | What it is | Prerequisite |
|--------|-----------|-------------|
| PEAD | Stock drifts after earnings beat for 20-40 days | Earnings dates + analyst consensus |
| Asset growth anomaly | Aggressive asset growers tend to underperform | Balance sheet time series (HAVE) |
| Net stock issuance | Heavy equity issuers underperform | Balance sheet shares outstanding (HAVE) |
| Capex acceleration | Rising capex + capacity expansion = future revenue | Cash flow (HAVE) + news context |
| MF convergence | 3+ quality MFs adding same stock = early smart money | MF holdings (slug-based, untested) |

---

## Complete Data Source Inventory

### Price & Market Data
| Data | Source | Status |
|------|--------|--------|
| OHLCV 1yr — 500 stocks | yfinance | LIVE |
| OHLCV 1yr — 2500 stocks | yfinance | PENDING (weekly) |
| 52-week high/low, volume | yfinance | LIVE |
| NSE bhavcopy (delivery%) | NSE archives | LIVE |
| Index levels (Nifty 50, 500) | yfinance | LIVE |
| Nifty VIX | yfinance | PENDING |

### Macro & Government Data (LIVE via Macro Pulse)
GST collections (GST portal), IIP (MOSPI eSankhyiki), Core Industries Index (eaindustry.nic.in), RBI credit growth (RBI DBIE), Policy announcements (pib.gov.in), RBI monetary policy (rbi.org.in)

### Corporate Event Data
| Data | Source | Status |
|------|--------|--------|
| BSE insider/promoter trades | BSE filings | LIVE (script 09) |
| Earnings dates calendar | NSE event-calendar API (script 18) | LIVE |
| Dividend, bonus, split announcements | NSE corporate actions | PARTIAL |
| MCA director changes, charge creation | mca.gov.in | PLANNED (Phase D) |
| SEBI orders | sebi.gov.in | PLANNED (Phase D) |

### Explicitly Deferred (Phase D/E)
Satellite imagery (Planet Labs), Zauba import/export, LinkedIn/Naukri job postings, Twitter/X, Reddit (IndianStreetBets), Google Trends (script 12 exists, weekly), FADA auto sales, TRAI telecom data

---

## Cost Plan

| Phase | Monthly | Key additions |
|-------|---------|--------------|
| Now (A-B) | Rs 450 | Claude API only — all data free |
| Phase C-D | Rs 450-700 | Possible Screener.in Pro if yfinance gaps |
| Phase E | Rs 950-1,200 | Zerodha Kite Rs 500/mo |

Philosophy: Free tier exhausted before any paid subscription is added.

---

## AI Vision — Long-Term Moat

**Research basis:**
- MarketSenseAI 2.0 (Feb 2025): 5 specialist LLM agents → 125.9% returns vs 73.5% index. ~15% residual alpha unexplained by traditional factors.
- AlphaAgent (2025): LLM-driven alpha mining — generates signal hypotheses, codes them, backtests automatically, retains winners.

**India-specific advantages:**
- Indian market less efficient → anomalies persist longer → more signal in language data
- Indian regulatory filings (MCA, BSE, SEBI, PIB) in English and scrapeable → RAG advantage
- Earnings call transcripts public and English → Sonnet extracts guidance, tone, commitment
- Hindi-English code-switched news is untapped signal source
- Retail-dominated market → behavioral biases (PEAD, momentum) stronger
- Institutional quants mostly run US-centric models → India-native signals underexplored

---

## Success Metrics

**After Phase A-B:** Complete data pipeline, 10+ signals with documented t-stats, empirical weights, backtester report
**After Phase C-D:** XGBoost beating linear baseline, SHAP dossier per stock, PEAD signal, multi-agent scaffold
**After Phase E:** 2,500 stocks, AI signal discovery, self-improving monthly, Zerodha integration

**Realistic target:** Top 20-30 picks contain 2-3 stocks that 3x+ over 3 years (10% hit rate). Consistently top 30%, avoid bottom 30%. Compound at 20-25% vs market 12-15%. Over 10 years: 6x vs 4x.

---

## Pre-Phase-C Fixes Applied (2026-03-31)

All 8 fixes applied before running backtester. Changes below are live in production.

| Fix | File | Change |
|-----|------|--------|
| 1 | 03_screener.py | Sector z-scores (MAD-based robust z → norm.cdf → 0-100) for value + quality |
| 2 | 03_screener.py | D/E score neutralised (=50) for Financial Services — debt is their product |
| 3 | 03_screener.py | P/E replaced with earnings yield (E/P = 1/PE) — negative EPS now penalised |
| 4 | 03_screener.py | 3M/6M/12M momentum skip-month: returns computed ending 1M ago (Jegadeesh-Titman) |
| 5 | 03_screener.py | Momentum neutralised for stocks with avg daily turnover < ₹25L (micro-cap noise) |
| 6 | 24_backtester.py | Filing lag: 45 → 60 days (prevents look-ahead bias in fundamental data) |
| 7 | 08_integrate_sentiment.py | B-phase signal total capped at ±12 pts (was uncapped, max possible was ±20) |
| 8 | 29_consensus_signal.py | buy_pct removed (mean 80%, near-constant, noise); weight redistributed to pt_upside (30%) and eps_growth (30%) |

### Implementation details

**FIX 1 — Sector z-scores:** `z = (value − sector_median) / (1.4826 × MAD)` → `score = norm.cdf(clip(z, -4, 4)) × 100`. Sectors < 10 stocks fall back to universe-wide z-score. Affected: pe (now earnings_yield), pb, roe, debt_to_equity, profit_margin.

**FIX 3 — Earnings yield:** `earnings_yield = 1 / pe_ratio` (skipped if |pe| < 0.1). Loss-making stocks (EPS < 0) get negative E/P → correctly ranked as bad value. Previously P/E = -50 would rank as "cheap".

**FIX 4 — Skip-month momentum:**
- `ret_3m` = `close[-22] / close[-88] − 1` (needs 110 bars)
- `ret_6m` = `close[-22] / close[-154] − 1` (needs 176 bars)
- `ret_1y` = `close[-22] / close[0] − 1` (skip most recent month)
- `ret_1m` unchanged (it IS the short-term signal)

**FIX 7 — Signal cap:** All 5 B-phase adjustments (Piotroski, Accruals, SmartMoney, Consensus, Promoter) computed individually then summed and capped at ±12 before applying to `final_score`. Pre-cap score saved as `pre_signal_score` for clean application.

**Smoke test results (5 stocks, 2026-03-31):**
| Stock | Sector | Val | Qual | Mom | Final score |
|-------|--------|-----|------|-----|-------------|
| SBIN | Financial Services | 64 | 46 | 56 | 50.6 |
| SUNPHARMA | Healthcare | 41 | 63 | 77 | 75.8 |
| RELIANCE | Energy | 35 | 52 | 44 | 58.4 |
| TCS | Technology | 59 | 60 | 34 | 53.7 |
| INFY | Technology | 62 | 57 | 45 | 75.6 |

RELIANCE Val=35 correctly reflects expensive vs energy sector (PE 21.9 vs sector median 13.3). INFY Val=62 correctly cheap vs IT sector (PE 17.5 vs IT median 26.7).

---

## Research-Backed Changes Applied (2026-04-02)

9 changes from deep research (40+ academic papers). Applied in order, committed separately.

| # | Signal | Change | Evidence |
|---|--------|--------|----------|
| 1 | Piotroski (27) | Expand FINANCIAL_SECTORS; sector-relative percentile for capital-intensive; threshold-based integration (F≥7:boost, F≤2:penalty, F=3-6:neutral) | Walkshäusl (2020, J Asset Mgmt) |
| 2 | Accruals (28) | Skip CF accruals for Financials; asymmetric integration (-4/+2); beneish_overlap flag | Bansal & Ali (2021, IIM Kashipur); Hribar & Collins (2002) |
| 3 | Earnings persistence (28) | Q4 (Jan-Mar) surprises down-weighted 0.6x; loss-year base effect dampener 0.5x; TODO for standalone earnings | Balachandran et al. (2023); IndAS kitchen-sink Q4 |
| 4 | Momentum (03) | Risk-adjusted: return/vol (Sharpe-like) for 6M + 12M; India VIX regime flag | Chui et al. (2023, Pacific-Basin Finance); Daniel & Moskowitz (2016, JFE) |
| 5 | Consensus (29) | pt_upside 30%→15%; pt_revision 25%→35%; eps_growth 30%→35%; analyst count confidence weighting | Indian analyst study (2024, Cogent Econ & Finance) |
| 6 | Promoter (30) | Asymmetric: buying full strength, selling dampened 30-50%; holding level modifier (>75%:0.7x, 40-65%:1.0x, <25%:0.8x) | Brochet et al. (2017, NYU Stern); Selarka (2006) |
| 7 | Integration (08) | Liquidity tier (HIGH/MED/LOW by ADTV); sector concentration cap (≤5/sector in top-20) | Chui et al. (2023); Indian market structure |
| 8 | Group tagger (31) | NEW script — maps 15 major conglomerates, propagates risk flags | Hindenburg-Adani; DHFL, Zee, ADAG episodes |
| 9 | CLAUDE.md | Research-backed parameters documented (this section) | — |

### Research-Backed Parameter Reference

**Piotroski F-Score:**
- Boost threshold: F ≥ 7 (not ≥ 6). Penalty threshold: F ≤ 2 (not ≤ 3)
- Formula: F=7:+2, F=8:+4, F=9:+4 (capped); F=2:-2, F=1:-4, F=0:-4; F=3-6: 0
- FINANCIAL_SECTORS now includes all variants ("Financials", "Financial Services", "Banks", etc.)
- `f_score_pctile` column added; `--sector-relative` flag uses sector percentile for capital-intensive

**Accruals Signal:**
- Financial stocks fully excluded from CF and BS accruals (RBI provisioning norms ≠ operating discretion)
- Integration asymmetric: penalty -4 max (well-supported in India), boost +2 max (halved)
- Q4 (Jan-Mar) quarter weight = 0.6x in earnings_beat_rate (kitchen-sink charges)
- Loss-year filter: any EPS < 0.50 in 8Q lookback → eps_cv and beat_rate multiplied by 0.5
- beneish_overlap column: flags double-counting with Beneish M-Score TATA component

**Momentum:**
- Risk-adjusted composite: mom_6m = ret_6m / vol_6m; mom_12m = ret_1y / vol_12m (daily std)
- India VIX regime: EXIT (>35), CAUTION (>25), NORMAL (≤25). Future: apply multiplier in 08.
- Scoring weights: ret1m 20%, mom_6m_adj 25%, mom_12m_adj 30%, RSI 15%, DMA 10%

**Consensus Signal:**
- pt_upside: 30% → 15% (63% hit rate in India; analyst optimism bias)
- pt_revision: 25% → 35% (direction-of-change has stronger predictive power)
- eps_growth: 30% → 35%; rev_growth: 15% (unchanged)
- Analyst confidence: ≥5 analysts = 1.0x; 3-4 = 0.6x; 1-2 = 0.3x; unknown = 0.3x

**Promoter Signal:**
- Selling dampened: >2% drop → 30% of raw, small selling → 50% of raw
- Holding modifier: >75% = 0.7x (low float risk), 40-65% = 1.0x (sweet spot), <25% = 0.8x

**Integration (08):**
- Liquidity tier: ADTV ≥ 10Cr = HIGH, 1-10Cr = MED, <1Cr = LOW (column in output CSV)
- Sector cap: max 5 stocks from any single sector in top-20 picks

### Known Constraints (Phase C prep)

- **Accruals anomaly structurally weak in India** — use as negative screen only (Pincus, Rajgopal & Venkatachalam 2007)
- **Earnings persistence should use standalone earnings** — data is consolidated-only (Tickertape). TODO flag added.
- **Momentum needs liquidity tier gating** — currently neutralised for <₹25L ADTV; liquidity_tier column now in output
- **Target price upside unreliable** — switched to revision-based (63% hit rate in India). pt_upside de-weighted to 15%.
- **t-stat threshold**: use ≥ 2.5 for known factors in new markets (not 3.0 — these aren't novel discoveries)
- **Survivorship bias**: ~4.4% annually in universe.csv. Bhavcopy backfill critical before Phase C backtesting.
- **Transaction costs**: 15-25 bps large-cap, 25-50 bps mid-cap, 50-200+ bps small-cap. Apply in backtester.
- **Fama-MacBeth**: rank-transform all factors, 6 Newey-West lags, ₹500 Cr minimum market cap filter
- **IC benchmarks**: 0.05-0.10 = good single factor; ICIR > 0.4 = reliable

### Future items flagged by research

- India VIX daily fetch + momentum crash protection applied in 08_integrate_sentiment.py
- Promoter pledge data harvest (SEBI mandates real-time disclosure since 2019)
- Standalone vs consolidated earnings flag per stock (Balachandran 2023 — parent earnings weight 1.55 vs 0.46)
- Business group risk integration into 08_integrate_sentiment.py (currently separate script 31)
- Backtester filing lag: 60 days (already fixed in 24_backtester.py)

---

## Known Issues

| Issue | Fix |
|-------|-----|
| build_universe() broken (KeyError: 'stock') | Always use --resume |
| Venv not activated → ModuleNotFoundError | source ~/alpha-signal/venv/bin/activate |
| Smart quotes from paste | Retype quotes manually |
| Tickertape SIDs ≠ NSE tickers | Use universe.csv SIDs |
| Cache blocking harvest | Add --refresh with --resume |
| Parallel harvesting risks IP block | Never run two scrapers at once |
| run_pipeline.sh has plaintext credentials | Move to .env file (TODO) |
| data.gov.in API key not obtained | Not urgent, fallbacks working |
| ~~Script 10: empty DataFrame writes~~ | ✅ Fixed — pd.DataFrame(columns=[...]).to_csv() |
| ~~NSE SERIES column has leading spaces~~ | ✅ Fixed — df["SERIES"].str.strip() before == "EQ" filter |
| ~~Smart money fetch log poisoning by smoke test~~ | ✅ Fixed — skip-logic checks raw file existence, not shared log |
| ~~pandas FutureWarning on fillna object dtype~~ | ✅ Fixed — .fillna(val).infer_objects(copy=False) |
| ~~No daily snapshot archiver yet~~ | ✅ Fixed — 26_snapshot_archiver.py, appends to data/snapshots/all_snapshots.csv |

---

## config/settings.py — Centralised Config Keys

| Config block | Key settings |
|-------------|-------------|
| `EMAIL_CONFIG` | SMTP credentials, recipient, subject prefix |
| `FORENSIC_CONFIG` | `m_score_grey_threshold` (-2.22), `m_score_red_threshold` (-1.78), `z_score_distress_threshold` (1.10), `z_score_grey_threshold` (2.60), `cache_max_age_days` (7), `skip_financial_sector` (True) |
| `ZERODHA` | Stub — Phase E only |

Scripts should import thresholds from `FORENSIC_CONFIG` rather than hardcoding them.

---

## yfinance Gotchas for Indian .NS Stocks

- Field names differ from docs: "Accounts Receivable" not "Net Receivables"
- Typo in yfinance: "Investmentin Financial Assets" (no space)
- Beneish/Altman scores must be computed from raw financials (not freely available pre-calculated)

---

## Validation Guardrails

- t-stat >= 3.0 required for any signal to enter the model
- Walk-forward splits (no look-ahead bias)
- 30-day paper trading before live inclusion
- 3+ orthogonal signals for conviction
- Monthly Fama-MacBeth recalibration of weights

---

## Test Commands

```bash
source ~/alpha-signal/venv/bin/activate
python -c "import pandas; print(pandas.__version__)"
wc -l data/harvester/universe.csv data/harvester/shareholding.csv data/analyst/consensus.csv
curl -I "https://archives.nseindia.com/content/equities/bulk.csv"
```
