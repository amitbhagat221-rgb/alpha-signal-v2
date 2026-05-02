# Alpha Signal v3 — Audit Notes

Living document. Findings logged as we trace the system.
Legend: ✅ understood | ⚠️ risk | 🔁 redundant | ⚡ inefficient | ❓ unknown | 🚧 tech debt

---

## Phase 0 — Ground Truth (in progress)

### 🚧 Backup files living in `scripts/` (~200K dead code)
Eight `.bak` / `_backup` files sit next to live code. Git already has history.
Risk: accidental import, confusion about which is canonical.

- `03_screener.py.v2.bak` (23K)
- `06_fetch_news_v1_backup.py` (11K)
- `08_integrate_sentiment.py.v2.bak` (35K)
- `16_smart_money.py.v2.bak` (24K)
- `24_backtester.py.c13.bak` (62K) ← largest file in scripts/
- `28_accruals.py.v2.bak` (19K)
- `29_consensus_signal.py.v2.bak` (15K)
- `30_promoter_signal.py.v2.bak` (12K)

**Decision:** keep for now — understand provenance before deleting.

---

## Phase 1 — Data Pipeline Map (harvesters)

### The 14 harvesters

| # | Script | Source | Output | Rows | Last refresh |
|---|--------|--------|--------|------|--------------|
| 01 | `01_fetch_universe.py` | NSE Indices CSV + Wikipedia + fallback | `data/nifty500_list.csv` | 501 | Apr 4 |
| 02 | `02_fetch_price_data.py` | yfinance | `data/stock_metadata.csv` + per-stock OHLCV | 501 | Apr 4 |
| 06 | `06_fetch_news.py` | MoneyControl, ET, LiveMint, BS RSS | `data/news/news_archive.csv` | 2,814 | Apr 8 ✅ |
| 09 | `09_insider_tracker.py` | BSE API + Trendlyne + NSE API | `data/insider/latest_insider_signals.csv` | 476 | Apr 8 ✅ |
| 12 | `12_google_trends.py` | Google Trends (pytrends) | `data/trends/latest_trends_signals.csv` | **0** ⚠️ | Apr 4 |
| 14 | `14_macro_pulse.py` | PIB, eaindustry, RBI DBIE, GST, fallback | `data/macro/macro_pulse.csv` (+ sector) | 23 | Apr 8 ✅ |
| 16 | `16_smart_money.py` | NSE bulk/block + bhavcopy | `data/smart_money/smart_money_score.csv` | 2,517 | Apr 8 ✅ |
| 18 | `18_earnings_calendar.py` | NSE event-calendar API | `data/events/earnings_calendar.csv` | 117 | Apr 8 ✅ |
| 22 | `22_data_harvester.py` | Tickertape sid API | `harvester/{quarterly_income, annual_balancesheet, annual_cashflow, shareholding, key_ratios}.csv` + universe | 21,572 / 19,197 / ? / 14,136 | **Mar 26–29** ⚠️ |
| 23 | `23_slug_mapper.py` | Tickertape redirect discovery | `data/harvester/slug_map.csv` | 2,501 | Mar 29 |
| 25 | `25_analyst_harvester.py` | Tickertape `__NEXT_DATA__` | `data/analyst/consensus.csv` | 2,440 | Mar 29 |
| 31 | `31_forecast_history_harvester.py` | Tickertape forecastsHistory arrays | `data/analyst/forecast_history.csv` | 29,014 | Mar 31 |
| 33 | `33_regime_module.py` | yfinance ^INDIAVIX | `data/reference/india_vix.csv` + `regime_state.json` | 736 | Apr 8 ✅ |
| 17 | `17_forensic_guard.py` | (compute-only — not a harvester) | `data/forensic/forensic_scores.csv` | — | — |

### Findings from the map

- 🔁 **None of the harvesters truly duplicate sources.** 25 (consensus snapshot) and 31 (forecast history) hit different `__NEXT_DATA__` keys. 06 vs 06_backup confirmed dead.
- ⚠️ **Universe schism:** `data/nifty500_list.csv` (501 rows, from `01`) vs `data/harvester/universe.csv` (2,500 rows, from `22`). Two different universes coexist. CLAUDE.md treats the 2,500 as canonical but `01` is still maintained.
- ⚠️ **Stale fundamentals:** `22_data_harvester.py` outputs last updated Mar 26–29. It's now Apr 8 — **13 days stale**. Either it's not on the daily cron, or it failed silently.
- ⚠️ **Google Trends signal is empty** (rate-limited or broken). Script runs but produces nothing. Dead pipeline node.
- ❓ **Cashflow file missing/not found** by the explorer (`annual_cashflow.csv`) — needs verification.
- ❓ `99_forecast_history_check.py` is a debug script, not production. Should it live in `scripts/` at all?

### 🚧 Numbering collision: two `33_` scripts
- `33_regime_module.py` (12K) — VIX regime + allocation
- `33_quality_gate.py` (26K) — small-cap quality gate (D14)

Both real on disk. CLAUDE.md flagged this. Needs renumbering eventually.

---

## Full System Map — Branch-by-Branch

Daily cron runs 20 steps at 9AM IST. Each branch below is one audit unit.
Pick a branch, trace it, mark it ✅ or flag issues.

### Execution Order (from `run_pipeline.sh`)

```
 1. 06_fetch_news.py
 2. 07_sentiment_scorer.py
 3. 09_insider_tracker.py
 4. 18_earnings_calendar.py
 5. 10_ai_news_classifier.py
 6. 17_forensic_guard.py
 7. 14_macro_pulse.py
 8. 16_smart_money.py
 8b.33_regime_module.py --refresh
 9. 03_screener.py
10. 27_piotroski.py
11. 28_accruals.py
12. 31_forecast_history_harvester.py --resume
13. 29_consensus_signal.py
14. 30_promoter_signal.py
15. 08_integrate_sentiment.py
16. 13_sector_analysis.py
17. 26_snapshot_archiver.py
18. 11_ai_dossier.py
19. 04_send_email.py
20. Git backup
```

### Branch A: News → Sentiment → AI Classification — DETAILED

```
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 1/20: 06_fetch_news.py  (daily, ~200-500 articles)           │
│                                                                     │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  11 RSS FEEDS (fetched via feedparser)                │           │
│  │  ├─ MoneyControl  (latest, business, markets)         │           │
│  │  ├─ Economic Times (markets, companies, economy)      │           │
│  │  ├─ Business Standard (markets, companies, economy)   │           │
│  │  └─ LiveMint (markets, companies)                     │           │
│  │  0.5s sleep between each feed                         │           │
│  └──────────────────────────────────────────────────────┘           │
│              │                                                      │
│              ▼                                                      │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  PARSE EACH ARTICLE                                   │           │
│  │  ├─ title (raw text)                                  │           │
│  │  ├─ summary (BeautifulSoup strips HTML, cap 500 char) │           │
│  │  ├─ url, source, published_at                         │           │
│  │  └─ article_id = MD5(title.lower()|source)[:12]       │           │
│  └──────────────────────────────────────────────────────┘           │
│              │                                                      │
│              ▼                                                      │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  ENTITY MATCHING (v2 — rewritten from v1)             │           │
│  │                                                       │           │
│  │  Universe: nifty500_list.csv (⚠️ 501 stocks,          │           │
│  │           NOT the 2,500 universe.csv)                  │           │
│  │                                                       │           │
│  │  Three match pools:                                   │           │
│  │  ├─ Pool 1: Exact NSE symbols (501 tickers)           │           │
│  │  ├─ Pool 2: CURATED_SHORT_NAMES (262 hand-verified    │           │
│  │  │          aliases: "Reliance"→RELI, "TCS"→TCS,      │           │
│  │  │          "HDFC Life"→HDFCLIFE, etc.)               │           │
│  │  └─ Pool 3: Multi-word company names from             │           │
│  │             stock_metadata.csv (if first word not      │           │
│  │             in 47-word SYMBOL_BLOCKLIST)               │           │
│  │                                                       │           │
│  │  Matching rules:                                      │           │
│  │  ├─ Title: all 3 pools, word-boundary regex (\b..\b)  │           │
│  │  ├─ Summary: Pool 1 + Pool 2 ONLY (no company names)  │           │
│  │  ├─ EXACT_MATCH_ONLY (16 tickers: OIL, HAL, BEL,     │           │
│  │  │   SAIL, IDEA etc.) → must appear as exact ticker   │           │
│  │  ├─ Min alias length: >2 chars (except "LT")         │           │
│  │  └─ 5+ matches → article rejected (too generic)       │           │
│  │                                                       │           │
│  │  SYMBOL_BLOCKLIST (47 words):                         │           │
│  │  OIL, BANK, TECH, POWER, ENERGY, INDIA, GLOBAL,      │           │
│  │  NATIONAL, CAPITAL, GOLD, SILVER, MAX, ACE, YES,      │           │
│  │  SHARE, STOCK, MARKET, APPLE, GOOGLE, TESLA etc.      │           │
│  └──────────────────────────────────────────────────────┘           │
│              │                                                      │
│              ▼                                                      │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  DEDUP & WRITE                                        │           │
│  │  ├─ Skip if article_id already in news_archive.csv    │           │
│  │  ├─ Today's file: data/news/news_YYYY-MM-DD.csv       │           │
│  │  └─ Archive: data/news/news_archive.csv               │           │
│  │      (concat + drop_duplicates on article_id)         │           │
│  │                                                       │           │
│  │  Schema: article_id, title, summary, url, source,     │           │
│  │          published_at, fetched_at, matched_symbols,    │           │
│  │          symbols_str, num_matches                      │           │
│  └──────────────────────────────────────────────────────┘           │
│                                                                     │
│  EVOLUTION: v1 → v2                                                 │
│  ├─ v1 used first-word aliasing ("Reliance" from                    │
│  │   "Reliance Industries") → caused ~90% false matches             │
│  ├─ v1 had no blocklist, no title/summary separation                │
│  ├─ v2 replaced with 262 hand-curated aliases + blocklist           │
│  └─ v1 backup still in scripts/ as 06_fetch_news_v1_backup.py      │
│                                                                     │
│  ⚠️ RISKS:                                                          │
│  ├─ Uses nifty500_list.csv (501 stocks), not universe.csv (2,500)   │
│  │   → 2,000 small/mid caps get ZERO news coverage                  │
│  ├─ No retry on feed failure (single attempt per feed)              │
│  ├─ No timeout enforcement (uses feedparser default ~30s)           │
│  └─ Insider archive has NO deduplication across runs                │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 2/20: 07_sentiment_scorer.py                                  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  INPUT: data/news/news_archive.csv                    │           │
│  │  (reads ALL articles, not just today's)               │           │
│  └──────────────────────────────────────────────────────┘           │
│              │                                                      │
│              ▼                                                      │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  SENTIMENT ENGINE: VADER (nltk) + custom lexicon      │           │
│  │                                                       │           │
│  │  127-term financial lexicon injected at runtime:       │           │
│  │  ├─ Bullish (+2.0 to +4.0): "beats" 3.0,             │           │
│  │  │   "crushes" 3.5, "surges" 3.0, "upgrade" 3.0,     │           │
│  │  │   "multibagger" 3.5, "contract win" 3.0,           │           │
│  │  │   "debt-free" 3.0, "promoter buying" 2.5           │           │
│  │  ├─ Bearish (-4.0 to -2.0): "fraud" -4.0,            │           │
│  │  │   "scam" -4.0, "bankruptcy" -4.0, "plunges" -3.5,  │           │
│  │  │   "default" -3.5, "sebi ban" -3.5,                 │           │
│  │  │   "downgrade" -3.0, "promoter selling" -2.5        │           │
│  │  ├─ Moderate (+/-): "steady" 1.0, "flat" -0.3,       │           │
│  │  │   "headwinds" -1.5, "slowdown" -1.5                │           │
│  │  └─ Policy: "rate cut" +1.5, "rate hike" -1.0,       │           │
│  │     "pli scheme" +2.0, "anti-dumping" +1.5            │           │
│  │                                                       │           │
│  │  Scoring:                                             │           │
│  │  ├─ compound = title_VADER × 0.7 + summary_VADER × 0.3│          │
│  │  ├─ Label: >0.1 "positive" | <-0.1 "negative" | else │           │
│  │  └─ If summary missing → treated as neutral (0)       │           │
│  └──────────────────────────────────────────────────────┘           │
│              │                                                      │
│              ▼                                                      │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  AGGREGATION: article → stock                         │           │
│  │                                                       │           │
│  │  Articles exploded by symbols_str (one row per stock) │           │
│  │  Per-stock, per-window arithmetic mean:               │           │
│  │  ├─ sentiment_today  (articles from today only)       │           │
│  │  ├─ sentiment_7d     (last 7 calendar days)           │           │
│  │  ├─ sentiment_30d    (last 30 calendar days)          │           │
│  │  └─ sentiment_momentum = 7d_avg − 30d_avg            │           │
│  │                                                       │           │
│  │  ⚠️ No time decay — article from 29 days ago          │           │
│  │     weighted same as yesterday's article              │           │
│  │  ⚠️ No source reliability weighting                   │           │
│  │  ⚠️ No article count minimum for averages             │           │
│  │     (1 article = full weight)                         │           │
│  └──────────────────────────────────────────────────────┘           │
│              │                                                      │
│              ▼                                                      │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  DIVERGENCE SIGNALS                                   │           │
│  │  (only fires if ≥2 articles in 7-day window)          │           │
│  │                                                       │           │
│  │  🟢 SENTIMENT SURGE: momentum > +0.15 AND 7d > +0.1   │           │
│  │  🔴 SENTIMENT DROP:  momentum < -0.15 AND 7d < -0.1   │           │
│  │  📰 HIGH COVERAGE:   articles_7d ≥ 5 (any sentiment)  │           │
│  └──────────────────────────────────────────────────────┘           │
│              │                                                      │
│              ▼                                                      │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  OUTPUT FILES (all in data/sentiment/)                 │           │
│  │                                                       │           │
│  │  1. article_scores_YYYY-MM-DD.csv                     │           │
│  │     All articles + compound, pos, neg, neu, label      │           │
│  │                                                       │           │
│  │  2. stock_sentiment_YYYY-MM-DD.csv                    │           │
│  │     Per-stock: sentiment_today, articles_today,        │           │
│  │     sentiment_7d, articles_7d, positive_7d,            │           │
│  │     negative_7d, sentiment_30d, articles_30d,          │           │
│  │     sentiment_momentum, total_articles,                │           │
│  │     latest_headline, latest_source                     │           │
│  │                                                       │           │
│  │  3. latest_stock_sentiment.csv ← COPY of #2           │           │
│  │     (this is what 03_screener reads)                   │           │
│  │                                                       │           │
│  │  4. latest_signals.csv                                │           │
│  │     (divergence signals only, if any triggered)        │           │
│  └──────────────────────────────────────────────────────┘           │
│                                                                     │
│  ⚠️ RISKS:                                                          │
│  ├─ No explicit error handling on CSV read/write                    │
│  ├─ Reads symbols from news articles, NOT from universe             │
│  │   → if 06 missed a stock, 07 can never score it                  │
│  └─ article_scores growing ~1.5MB/day (no cleanup)                  │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                      (feeds into 03_screener
                       and 08_integrate_sentiment)

═══════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────────┐
│  STEP 3/20: 09_insider_tracker.py                                   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  4 EXTERNAL SOURCES (cascading fallback)              │           │
│  │                                                       │           │
│  │  1. BSE Python package                                │           │
│  │     bse.announcements(category=INSIDER, page=1..5)    │           │
│  │     → ~100 announcements, 0.5s between pages          │           │
│  │                                                       │           │
│  │  2. NSE API                                           │           │
│  │     nseindia.com/api/corporates-pit?index=equities    │           │
│  │     &from_date=30_days_ago&to_date=today              │           │
│  │     → JSON with insider trades                        │           │
│  │                                                       │           │
│  │  3. Trendlyne scrape                                  │           │
│  │     trendlyne.com/equity/group-insider-trading-sast/  │           │
│  │     → HTML table parsed with BeautifulSoup            │           │
│  │                                                       │           │
│  │  4. BSE Direct scrape (LAST RESORT — only if 1-3 all  │           │
│  │     return empty)                                     │           │
│  │     bseindia.com/corporates/Insider_Trading_new.aspx  │           │
│  │     → first 50 rows from GridView table               │           │
│  │                                                       │           │
│  │  All sources: try/except → return empty on failure     │           │
│  │  All results: concat into single combined DataFrame    │           │
│  └──────────────────────────────────────────────────────┘           │
│              │                                                      │
│              ▼                                                      │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  CLASSIFY EACH TRADE                                  │           │
│  │                                                       │           │
│  │  Transaction type (keyword scan on ALL row text):      │           │
│  │  ├─ BUY: "acquisition", "buy", "purchase", "bought"   │           │
│  │  ├─ SELL: "disposal", "sell", "sold", "sale"           │           │
│  │  ├─ PLEDGE_CREATE: "pledge" without revoke/release     │           │
│  │  ├─ PLEDGE_RELEASE: "pledge" + "revoke"/"release"      │           │
│  │  ├─ PLEDGE_INVOKE: "pledge" + "invoke"                 │           │
│  │  └─ UNKNOWN: no keywords matched                       │           │
│  │                                                       │           │
│  │  Person category (keyword scan):                      │           │
│  │  ├─ PROMOTER: "promoter", "promoter group"            │           │
│  │  ├─ DIRECTOR: "director", "chairm"                    │           │
│  │  ├─ KMP: "kmp", "key managerial", "cfo", "ceo", "md" │           │
│  │  ├─ EMPLOYEE: exact "employee"                        │           │
│  │  └─ OTHER: fallback                                   │           │
│  └──────────────────────────────────────────────────────┘           │
│              │                                                      │
│              ▼                                                      │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  MATCH TO UNIVERSE                                    │           │
│  │                                                       │           │
│  │  Reads: data/stock_metadata.csv (symbol, name)        │           │
│  │  ⚠️ NOT universe.csv — same issue as 06_fetch_news     │           │
│  │                                                       │           │
│  │  Match strategy:                                      │           │
│  │  ├─ Direct symbol match (if "symbol" column exists)   │           │
│  │  ├─ Full company name match                           │           │
│  │  ├─ First significant word match (>4 chars,            │           │
│  │  │   excluding: LIMITED, INDIA, INDUSTRIES etc.)       │           │
│  │  └─ Fuzzy: key-in-name or name-in-key                 │           │
│  │                                                       │           │
│  │  ⚠️ No filtering by universe membership               │           │
│  │     ANY matched stock gets signals                     │           │
│  └──────────────────────────────────────────────────────┘           │
│              │                                                      │
│              ▼                                                      │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  SIGNAL GENERATION                                    │           │
│  │  (grouped by matched_symbol, counts by type/person)   │           │
│  │                                                       │           │
│  │  Signal              │ Trigger          │ score_impact │           │
│  │  ────────────────────┼──────────────────┼─────────────│           │
│  │  PROMOTER BUYING     │ any promoter buy │ +15          │           │
│  │  PROMOTER SELLING    │ any promoter sell│ -12          │           │
│  │  DIRECTOR/KMP BUYING │ dir/kmp buy,     │ +8           │           │
│  │                      │ no promoter buy  │              │           │
│  │  CLUSTER BUYING      │ ≥2 unique buyer  │ +20          │           │
│  │                      │ categories       │              │           │
│  │  PLEDGE CREATED      │ any pledge create│ -10          │           │
│  │  PLEDGE RELEASED     │ any pledge release│ +8          │           │
│  │                                                       │           │
│  │  ⚠️ No thresholds on trade SIZE or VALUE               │           │
│  │     A ₹10,000 promoter buy = same signal as ₹10 Cr    │           │
│  │  ⚠️ No time windowing — all 30 days of NSE data        │           │
│  │     treated equally                                   │           │
│  └──────────────────────────────────────────────────────┘           │
│              │                                                      │
│              ▼                                                      │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  OUTPUT FILES (data/insider/)                         │           │
│  │                                                       │           │
│  │  1. insider_raw_YYYY-MM-DD.csv                        │           │
│  │     Raw trades from all sources                        │           │
│  │                                                       │           │
│  │  2. insider_archive.csv (APPEND, no dedup!)            │           │
│  │     ⚠️ Same trade appears multiple times across runs   │           │
│  │     Already 10.9 MB — largest CSV in the project       │           │
│  │                                                       │           │
│  │  3. latest_insider_signals.csv (OVERWRITE daily)       │           │
│  │     symbol, signal_type, strength, description,        │           │
│  │     detail, score_impact                               │           │
│  │     → consumed by 08_integrate_sentiment               │           │
│  │                                                       │           │
│  │  If ALL 4 sources fail: writes empty CSV (graceful)    │           │
│  └──────────────────────────────────────────────────────┘           │
│                                                                     │
│  ⚠️ RISKS:                                                          │
│  ├─ insider_archive.csv has NO dedup — grows unbounded              │
│  ├─ No trade size/value threshold — noise from tiny trades          │
│  ├─ Uses stock_metadata.csv not universe.csv                        │
│  ├─ Fuzzy name matching can produce false positives                 │
│  └─ nifty500_list.csv loaded but never used (dead code)             │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                      (feeds into 08_integrate_sentiment)

### Branch C: Macro & VIX
```
[RBI, PIB, GST, data.gov.in] → 14_macro_pulse → data/macro/macro_sector_signals.csv
                                                        ↓
                                                    (feeds into 08)

[yfinance ^INDIAVIX] → 33_regime_module → data/reference/regime_state.json
                                                ↓
                                           (portfolio allocation weights)
```
**Audit status:** [ ]

### Branch D: Forensic Guard
```
[yfinance financials] → 17_forensic_guard → data/forensic/forensic_scores.csv
                                                   ↓
                                              (feeds into 08)
```
**Audit status:** [ ]

### Branch E: Smart Money
```
[NSE bulk/block + bhavcopy] → 16_smart_money → data/smart_money/smart_money_score.csv
                                                       ↓
                                                  (feeds into 08)
```
**Audit status:** [ ]

### Branch F: Base Screener
```
[stock_metadata.csv + price data + sentiment] → 03_screener → data/screener_output/screen_{date}.csv
                                                                       ↓
                                                                  (feeds into 08)
```
**Audit status:** [ ]

### Branch G: Fundamental Signals
```
[harvester CSVs + universe] → 27_piotroski → data/signals/piotroski.csv ──────→ (08)
                            → 28_accruals  → data/signals/accruals.csv  ──────→ (08)
                            → 30_promoter  → data/signals/promoter.csv  ──────→ (08)

[slug_map + universe] → 31_forecast_history → data/analyst/forecast_history.csv
                                                       ↓
                                              29_consensus → data/signals/consensus.csv → (08)
```
**Audit status:** [ ]

### Branch H: Integration → Output
```
ALL branches above
        ↓
08_integrate_sentiment → data/screener_output/enriched_{date}.csv
                       → data/latest_picks.csv
                              ↓
                    13_sector_analysis → data/sector_summary.csv
                    26_snapshot_archiver → data/snapshots/all_snapshots.csv
                    11_ai_dossier → data/ai/latest_dossiers.json
                    04_send_email → Gmail delivery
```
**Audit status:** [ ]

### Branch Z: Offline / Not in Daily Cron
```
01_fetch_universe.py          ← builds nifty500_list (run manually?)
02_fetch_price_data.py        ← fetches OHLCV + metadata (run manually?)
22_data_harvester.py          ← fundamentals harvest (run manually, --resume)
23_slug_mapper.py             ← slug discovery (run manually)
25_analyst_harvester.py       ← consensus snapshot (run manually)
32_tier_assignment.py         ← cap_tier + ADTV (run manually)
12_google_trends.py           ← broken/empty output
24_backtester.py              ← backtest engine (run ad-hoc)
38_signal_reconstructor.py    ← PIT reconstruction (run ad-hoc)
33_quality_gate.py            ← D14 (not yet wired in)
```
**Audit status:** [ ]

---

## How to Use This Map

1. Pick a branch (A through Z)
2. Read the scripts in order
3. For each script, answer: do I understand why this exists?
4. Log findings back here under that branch's audit status
5. Mark [ ] → [✅] when understood, or flag issues
