# Alpha Signal v2 — Build Plan

> A clean rebuild. Same intelligence, proper engineering.
> v1 stays live until v2 is ready. Nothing breaks.
>
> Created: 2026-04-09 | Owner: Amit Bhagat

---

## The Design Philosophy

**v1 was scripts calling scripts.** Each script knew where its data lived,
how to fetch it, how to parse it, how to save it. Change one thing and you're
grep-ing through 20 files.

**v2 is layers.** Each layer has one job and talks to the others through
well-defined interfaces:

```
┌─────────────────────────────────────────────────┐
│                   CONFIG                         │
│  sources.yaml │ signals.yaml │ pipeline.yaml     │
│  "What to fetch, how to score, when to run"      │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│                    CORE                          │
│  database.py │ registry.py │ universe.py         │
│  "How to store, how to discover, who's in scope" │
└────────────────────┬────────────────────────────┘
                     │
         ┌───────────┼───────────┐
         ▼           ▼           ▼
┌──────────────┐ ┌────────┐ ┌────────┐
│   SOURCES    │ │SIGNALS │ │ OUTPUT │
│ One file per │ │One file│ │Screener│
│ data source  │ │per sig │ │Dossier │
│              │ │        │ │Email   │
│ All implement│ │All impl│ │        │
│ BaseSource   │ │BaseSig │ │        │
└──────────────┘ └────────┘ └────────┘
         │           │           │
         └───────────┼───────────┘
                     ▼
┌────────────────────────────────────────────────┐
│                   FLOWS                         │
│  Prefect orchestration                          │
│  daily.py │ weekly.py │ monthly.py              │
│  "When to run what, in what order"              │
└────────────────────────────────────────────────┘
```

**The key insight:** data sources are configuration, not code.
Every source implements the same interface. Swapping one for another
is changing a YAML line, not rewriting a script.

---

## Project Structure

```
~/alpha-signal-v2/
│
├── config/
│   ├── sources.yaml            # data source registry
│   ├── signals.yaml            # signal definitions + weights per tier
│   ├── pipeline.yaml           # schedules, thresholds, alert settings
│   ├── schema.sql              # SQLite table definitions
│   └── __init__.py
│
├── core/
│   ├── __init__.py
│   ├── database.py             # get_db(), read_table(), upsert()
│   ├── registry.py             # source/signal discovery from YAML
│   ├── models.py               # dataclasses for Stock, Signal, Pick
│   └── logging.py              # structured logging setup
│
├── sources/                    # one file per data source
│   ├── __init__.py
│   ├── base.py                 # BaseSource class (interface)
│   ├── nse_bhavcopy.py         # OHLCV + delivery %
│   ├── tickertape_fundamentals.py  # income, BS, CF, shareholding, ratios
│   ├── tickertape_analyst.py   # consensus + forecast history
│   ├── nse_insider.py          # insider trades (BSE/NSE/Trendlyne)
│   ├── nse_bulk_deals.py       # bulk/block deals
│   ├── rss_news.py             # financial news from RSS
│   ├── yfinance_vix.py         # India VIX only
│   ├── macro_gov.py            # government macro indicators
│   └── nse_events.py           # earnings calendar
│
├── signals/                    # one file per signal
│   ├── __init__.py
│   ├── base.py                 # BaseSignal class (interface)
│   ├── piotroski.py            # 9-factor F-Score
│   ├── accruals.py             # cash flow vs accrual quality
│   ├── consensus.py            # analyst revision momentum
│   ├── promoter.py             # promoter buying momentum
│   ├── sentiment.py            # VADER news sentiment
│   ├── smart_money.py          # bulk deals + delivery %
│   ├── forensic.py             # Beneish M-Score + Altman Z
│   ├── momentum.py             # 6M/12M price momentum
│   └── earnings_yield.py       # E/P signal
│
├── scoring/
│   ├── __init__.py
│   ├── screener.py             # tier-aware scoring engine
│   ├── quality_gate.py         # small-cap quality gate
│   ├── regime.py               # VIX regime → allocation weights
│   └── portfolio.py            # final portfolio construction
│
├── output/
│   ├── __init__.py
│   ├── dossier.py              # AI investment thesis (Claude)
│   ├── email_sender.py         # Gmail delivery
│   └── snapshot.py             # point-in-time archiver
│
├── flows/                      # Prefect orchestration
│   ├── __init__.py
│   ├── daily.py                # daily pipeline flow
│   ├── weekly.py               # weekend refresh flow
│   ├── monthly.py              # deep harvest flow
│   └── deploy.py               # register all deployments
│
├── tests/
│   ├── __init__.py
│   ├── test_smoke.py           # pre-pipeline sanity checks
│   ├── test_sources.py         # each source returns expected schema
│   ├── test_signals.py         # each signal produces valid output
│   ├── test_contracts.py       # DB schema enforcement
│   └── conftest.py             # shared fixtures
│
├── notebooks/                  # learning + diagnostics
│   ├── diagnostics.ipynb
│   └── signal_validation.ipynb
│
├── data/
│   └── alpha_signal.db         # THE database (created by schema.sql)
│
├── output/                     # logs, reports
│   └── pipeline.log
│
├── requirements.txt
├── pyproject.toml
├── CLAUDE.md                   # v2 project context
└── README.md
```

---

## The Pluggable Source Pattern

This is the core idea. Here's how it works:

### sources/base.py — The Interface

```python
"""
Every data source implements this interface.
Swap a source by changing config/sources.yaml.
The rest of the system never knows the difference.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import pandas as pd

@dataclass
class FetchResult:
    """Standard return type from any source."""
    data: pd.DataFrame
    rows_fetched: int
    source_name: str
    fetch_timestamp: str
    warnings: list[str]

class BaseSource(ABC):
    """Interface that every data source must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name (e.g. 'NSE Bhavcopy')."""

    @property
    @abstractmethod
    def table(self) -> str:
        """Target SQLite table name (e.g. 'stock_prices')."""

    @property
    @abstractmethod
    def frequency(self) -> str:
        """How often this runs: 'daily', 'weekly', 'monthly'."""

    @abstractmethod
    def fetch(self, **kwargs) -> FetchResult:
        """Fetch data from external source. Returns a FetchResult."""

    @abstractmethod
    def validate(self, df: pd.DataFrame) -> list[str]:
        """Validate fetched data. Returns list of errors (empty = valid)."""

    def save(self, result: FetchResult, conn):
        """Save to database. Default: upsert to self.table."""
        errors = self.validate(result.data)
        if errors:
            raise ValueError(f"{self.name} validation failed: {errors}")
        result.data.to_sql(self.table, conn, if_exists="append", index=False)
```

### Example: sources/nse_bhavcopy.py

```python
"""NSE Bhavcopy — authoritative OHLCV + delivery data for Indian equities."""

import pandas as pd
import requests
from datetime import date, timedelta
from .base import BaseSource, FetchResult

class NSEBhavcopy(BaseSource):
    name = "NSE Bhavcopy"
    table = "stock_prices"
    frequency = "daily"

    BASE_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv"
    HEADERS = {"User-Agent": "Mozilla/5.0 ..."}

    def fetch(self, target_date: date = None, **kwargs) -> FetchResult:
        target_date = target_date or date.today()
        url = self.BASE_URL.format(date=target_date.strftime("%d%m%Y"))

        resp = requests.get(url, headers=self.HEADERS, timeout=30)
        resp.raise_for_status()

        df = pd.read_csv(io.StringIO(resp.text))
        df = df[df[" SERIES"] == " EQ"]  # equity only

        # Normalize columns
        df = df.rename(columns={
            "SYMBOL": "symbol",
            " OPEN_PRICE": "open", " HIGH_PRICE": "high",
            " LOW_PRICE": "low", " CLOSE_PRICE": "close",
            " PREVCLOSE": "prev_close", " TTL_TRD_QNTY": "volume",
            " TTL_TRD_VAL": "traded_value", " NO_OF_TRADES": "num_trades",
            " DELIV_QTY": "delivered_qty", " DELIV_PER": "delivery_pct",
        })
        df["date"] = target_date.isoformat()

        return FetchResult(
            data=df, rows_fetched=len(df),
            source_name=self.name,
            fetch_timestamp=datetime.now().isoformat(),
            warnings=[]
        )

    def validate(self, df):
        errors = []
        if len(df) < 1000:
            errors.append(f"Too few rows: {len(df)} (expected 1500+)")
        if "close" not in df.columns:
            errors.append("Missing 'close' column")
        if df["close"].isna().any():
            errors.append(f"{df['close'].isna().sum()} null close prices")
        return errors
```

### Now here's the magic — switching sources:

```yaml
# config/sources.yaml

prices:
  provider: nse_bhavcopy          # ← THE source
  # provider: yfinance_prices     # ← swap in 1 line if bhavcopy breaks
  schedule: daily
  target_table: stock_prices

vix:
  provider: yfinance_vix
  schedule: daily
  target_table: vix_history

fundamentals:
  provider: tickertape_fundamentals
  schedule: monthly
  target_table: [quarterly_income, annual_balance_sheet, annual_cash_flow]

analyst:
  provider: tickertape_analyst
  schedule: monthly
  target_table: [analyst_consensus, forecast_history]

news:
  provider: rss_news
  schedule: daily
  target_table: news_articles

insiders:
  provider: nse_insider
  schedule: daily
  target_table: insider_trades

bulk_deals:
  provider: nse_bulk_deals
  schedule: daily
  target_table: bulk_deals

macro:
  provider: macro_gov
  schedule: daily
  target_table: macro_indicators

events:
  provider: nse_events
  schedule: daily
  target_table: earnings_calendar
```

### Same pattern for signals:

```yaml
# config/signals.yaml

signals:
  piotroski:
    module: signals.piotroski
    inputs: [quarterly_income, annual_balance_sheet, annual_cash_flow]
    output_table: piotroski_scores
    exclude_sectors: [Financial Services]
    schedule: daily

  accruals:
    module: signals.accruals
    inputs: [quarterly_income, annual_cash_flow, annual_balance_sheet]
    output_table: accruals_scores
    schedule: daily

  consensus:
    module: signals.consensus
    inputs: [analyst_consensus, forecast_history, stock_prices]
    output_table: consensus_signals
    schedule: daily

  promoter:
    module: signals.promoter
    inputs: [shareholding]
    output_table: promoter_signals
    schedule: daily

  sentiment:
    module: signals.sentiment
    inputs: [news_articles, news_article_stocks]
    output_table: sentiment_scores
    schedule: daily

  smart_money:
    module: signals.smart_money
    inputs: [bulk_deals, delivery_data]
    output_table: smart_money_scores
    schedule: daily

  forensic:
    module: signals.forensic
    inputs: [quarterly_income, annual_balance_sheet, annual_cash_flow]
    output_table: forensic_scores
    exclude_sectors: [Financial Services]
    schedule: daily

  momentum:
    module: signals.momentum
    inputs: [stock_prices]
    output_table: momentum_scores
    schedule: daily

  earnings_yield:
    module: signals.earnings_yield
    inputs: [quarterly_income, stock_prices, stocks]
    output_table: earnings_yield_scores
    schedule: daily

# Weight tiers per cap segment (from C13b validation)
weights:
  LARGE:
    consensus:      {weight: 0.40, t_stat: 3.52, tier: primary}
    earnings_yield: {weight: 0.20, t_stat: 1.57, tier: secondary}
    accruals:       {weight: 0.15, t_stat: 0.20, tier: tertiary}
    piotroski:      {weight: 0.10, t_stat: 0.51, tier: tertiary}
    momentum:       {weight: 0.05, t_stat: 0.00, tier: tertiary}

  MID:
    accruals:       {weight: 0.30, t_stat: 3.20, tier: primary}
    piotroski:      {weight: 0.20, t_stat: 2.23, tier: secondary}
    consensus:      {weight: 0.15, t_stat: 2.20, tier: secondary}
    earnings_yield: {weight: 0.10, t_stat: 1.01, tier: tertiary}
    promoter:       {weight: 0.05, t_stat: 0.83, tier: tertiary}

  SMALL:
    promoter:       {weight: 0.25, t_stat: 3.20, tier: primary}
    earnings_yield: {weight: 0.20, t_stat: 3.13, tier: primary}
    piotroski:      {weight: 0.15, t_stat: 2.81, tier: primary}
    accruals:       {weight: 0.10, t_stat: 2.10, tier: secondary}
    smart_money:    {weight: 0.10, t_stat: 2.49, tier: secondary}
    momentum:       {weight: 0.05, t_stat: 1.76, tier: secondary}
```

---

## Build Sessions — One at a Time

Each session is **one sitting**. We build one thing, test it, verify it,
understand it. Then stop. Next session builds the next thing.

### Session 1: The Foundation
**Build:** Project skeleton + SQLite database + core module
**Files created:**
- `alpha-signal-v2/` folder structure
- `config/schema.sql` — all 26 table definitions
- `core/database.py` — get_db(), read_table(), upsert(), init_db()
- `requirements.txt` — prefect, pandas, requests, nltk, etc.
- `CLAUDE.md` — v2 project context

**Test:** `python -c "from core.database import init_db; init_db()"` creates the DB.
**Verify:** `sqlite3 data/alpha_signal.db ".tables"` shows all 26 tables.
**You understand:** How the DB works. What each table is for. How to query it.

---

### Session 2: The Source Interface + First Source (Bhavcopy)
**Build:** BaseSource class + NSE Bhavcopy source
**Files created:**
- `sources/base.py` — BaseSource interface + FetchResult dataclass
- `sources/nse_bhavcopy.py` — fetch, validate, save
- `config/sources.yaml` — first entry

**Test:** Fetch today's bhavcopy → validate → save to `stock_prices` table.
**Verify:** `SELECT COUNT(*), date FROM stock_prices GROUP BY date` — one day of data.
**You understand:** How a source works. The fetch → validate → save pipeline.

---

### Session 3: Bhavcopy Backfill (3 years)
**Build:** Backfill script that fetches 750 trading days of bhavcopy
**Files created:**
- `sources/nse_bhavcopy.py` gets a `backfill(start_date, end_date)` method

**Test:** Backfill last 30 days first (fast). Verify prices match v1's yfinance data ±1%.
**Verify:** `SELECT COUNT(DISTINCT date) FROM stock_prices` — 30 days.
Then: full 3-year backfill (~25 min at 2s/request).
**You understand:** How historical data accumulates. Price accuracy vs yfinance.

---

### Session 4: The Universe (stocks table)
**Build:** Populate the `stocks` table — THE single source of truth
**Source:** Migrate from v1's `universe.csv` (2,500 stocks with cap_tier, adtv)
**Enrich:** Add `in_nifty500` flag from `nifty500_list.csv`, slugs from `slug_map.csv`
**Files created:**
- `core/universe.py` — load_universe(), get_tier(), refresh helpers

**Test:** `SELECT cap_tier, COUNT(*) FROM stocks GROUP BY cap_tier`
→ LARGE=100, MID=150, SMALL=2250
**Verify:** Every sid in `stock_prices` has a matching row in `stocks`.
**You understand:** Why ONE universe table matters. How tiers work.

---

### Session 5: Second Source (Tickertape Fundamentals)
**Build:** Tickertape fundamental harvester — income, BS, CF, shareholding
**Files created:**
- `sources/tickertape_fundamentals.py` — implements BaseSource
- Reuses `tickertape_utils.py` from v1 (copy + clean up)

**Test:** Fetch fundamentals for 3 stocks (smoke test). Validate schema. Save to DB.
**Verify:** `SELECT sid, COUNT(*) FROM quarterly_income GROUP BY sid LIMIT 5`
Then: migrate all existing v1 CSV data into SQLite tables.
**You understand:** Tickertape's two-tier API. SID vs slug. Checkpoint/resume logic.

---

### Session 6: Third Source (RSS News)
**Build:** News fetcher + article-stock linking
**Files created:**
- `sources/rss_news.py` — fetch RSS, entity matching, save to news_articles + news_article_stocks
- Entity matching uses `stocks` table (2,500 stocks, not nifty500!)

**Test:** Fetch today's news. Check entity matching against 2,500 stock universe.
**Verify:** Compare matched articles vs v1. More matches (broader universe)?
**You understand:** Entity matching rules. Why v1 missed 2,000 stocks.

---

### Session 7: First Signal (Sentiment)
**Build:** VADER sentiment scorer reading from DB
**Files created:**
- `signals/base.py` — BaseSignal interface
- `signals/sentiment.py` — reads news_articles, writes sentiment_scores
- `config/signals.yaml` — first entry

**Test:** Score sentiment for today's articles. Save to DB.
**Verify:** `SELECT sid, sentiment_7d, articles_7d FROM sentiment_scores LIMIT 10`
**You understand:** How signals read from DB and write to DB. The signal interface.

---

### Session 8: Remaining Sources (Insiders, VIX, Macro, Events, Bulk Deals)
**Build:** All remaining data sources
**Files created:**
- `sources/nse_insider.py` — with dedup via UNIQUE constraint
- `sources/yfinance_vix.py` — VIX only
- `sources/macro_gov.py` — government indicators
- `sources/nse_events.py` — earnings calendar
- `sources/nse_bulk_deals.py` — bulk/block deals + delivery data

**Test:** Each source fetches, validates, saves. One at a time.
**Verify:** Row counts in DB match expectations.
**You understand:** Each external dependency. What breaks if it's down.

---

### Session 9: Remaining Signals (Piotroski, Accruals, Consensus, Promoter, Forensic, Smart Money, Momentum, EY)
**Build:** All 8 remaining signals
**Files created:**
- `signals/piotroski.py`, `accruals.py`, `consensus.py`, `promoter.py`
- `signals/forensic.py`, `smart_money.py`, `momentum.py`, `earnings_yield.py`

**Test:** Each signal computes from DB data, validates, saves. One at a time.
**Verify:** Cross-check key values against v1 output (e.g. Piotroski scores should match).
**You understand:** Every signal formula. What inputs it needs. What it produces.

---

### Session 10: Scoring Engine + Quality Gate
**Build:** Tier-aware scoring using weights from signals.yaml
**Files created:**
- `scoring/screener.py` — reads signals.yaml weights, ranks within tier
- `scoring/quality_gate.py` — small-cap filter (EXCLUDE/PENALIZE/PASS)
- `scoring/regime.py` — VIX regime → allocation weights
- `scoring/portfolio.py` — final portfolio: 40/30/30 + regime overlay

**Test:** Run screener on full universe. Compare top 15 picks to v1.
**Verify:** Rankings are within-tier. Quality gate excludes ~15% of small caps.
**You understand:** How signals combine. Why within-tier ranking matters.

---

### Session 11: Output Layer (Dossier + Email + Snapshot)
**Build:** AI dossier, email sender, daily snapshot archiver
**Files created:**
- `output/dossier.py` — Claude API for investment thesis
- `output/email_sender.py` — Gmail delivery
- `output/snapshot.py` — daily_snapshots table (PIT archive)

**Test:** Generate dossier for top 3 picks. Send test email.
**Verify:** Snapshot row count = number of stocks in universe.
**You understand:** The full pipeline end-to-end.

---

### Session 12: Prefect Flows
**Build:** Wire everything into Prefect flows
**Files created:**
- `flows/daily.py` — daily pipeline (harvest → signals → score → output)
- `flows/weekly.py` — weekend refresh (universe + prices + metadata)
- `flows/monthly.py` — deep harvest (Tickertape fundamentals)
- `flows/deploy.py` — register deployments with Prefect Cloud

**Test:** Run daily flow manually via Prefect. Watch it in the UI.
**Verify:** All tasks green. Output matches v1.
**You understand:** How Prefect orchestrates. How to re-run failed tasks.

---

### Session 13: Tests
**Build:** Test suite from the ground up
**Files created:**
- `tests/test_smoke.py` — DB exists, tables populated, files accessible
- `tests/test_sources.py` — each source returns expected schema
- `tests/test_signals.py` — each signal produces valid ranges
- `tests/test_contracts.py` — DB constraints hold
- `tests/conftest.py` — shared test fixtures

**Test:** `pytest tests/ -v` — all green.
**You understand:** What each test catches. What breaks if you change a schema.

---

### Session 14: Parallel Run + Validation
**Build:** Run v2 alongside v1 for 2-3 days
**Compare:**
- Daily picks: do v1 and v2 produce similar top 15?
- Signal values: are Piotroski, consensus, etc. within tolerance?
- Price data: does bhavcopy match yfinance close prices?
- Timing: is v2 faster/slower?

**Decision point:** If v2 matches v1 within acceptable tolerance → switch.
If discrepancies found → investigate and fix before switching.

---

### Session 15: Switchover
**Actions:**
- Point cron to v2 Prefect deployment
- Stop v1 cron
- Monitor v2 for 1 week
- Archive v1 folder (don't delete — it's history)

---

## What Makes v2 Different (Summary)

| Aspect | v1 | v2 |
|--------|----|----|
| Universe | 3 files, scripts pick whichever | 1 `stocks` table, everyone reads it |
| Data storage | 80+ CSV files | 1 SQLite database, 26 tables |
| Configuration | Hardcoded in 20 scripts | 3 YAML files (sources, signals, pipeline) |
| Source switching | Rewrite a script | Change 1 line in sources.yaml |
| Signal weights | Hardcoded in screener | signals.yaml with t-stat justification |
| Orchestration | bash script, no error handling | Prefect with UI, retries, alerting |
| Testing | Zero tests | Smoke + contract + regression tests |
| Monitoring | Manual dashboard check | Prefect Cloud dashboard + failure alerts |
| Adding a signal | Write a new script, edit 3 others | Write one file implementing BaseSignal, add to YAML |
| Data lineage | Unknown | Every table has fetch_timestamp, source tracking |
| Deduplication | Broken (insider archive 11MB dupes) | UNIQUE constraints at DB level |
| Error handling | Script crashes, pipeline continues | Prefect retries, alerts on failure, stops if critical |

---

## Rules for the Rebuild

1. **One session at a time.** No rushing. No "let me also quickly add..."
2. **Test before moving on.** If it doesn't work, we fix it now.
3. **You explain it back to me.** If you can't explain what a session built, we review.
4. **No copy-paste without understanding.** Every function adapted from v1 gets read first.
5. **Config over code.** If a value might change, it goes in YAML.
6. **DB constraints are your friend.** Let SQLite enforce what code forgets.
7. **v1 stays running.** We don't touch it. It's our safety net.

---

## Ready?

Session 1 is: create the folder, set up the database schema, build core/database.py.
Say "go" and we start.
