"""
Alpha Signal v2 — Database Module

Single point of access for all database operations.
Every other module imports from here. Never open sqlite3 directly.

Usage:
    from db import get_db, read_table, get_universe, init_db
"""

import sqlite3
import pandas as pd
from pathlib import Path
from contextlib import contextmanager

# ── Paths ──
PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "alpha_signal.db"
SCHEMA_PATH = PROJECT_ROOT / "schema.sql"


@contextmanager
def get_db():
    """
    Get a database connection with sensible defaults.

    WAL mode:       allows concurrent readers
    foreign_keys:   enforces REFERENCES constraints (bad sid = error, not silent)
    busy_timeout:   waits 5s if another writer holds the lock

    Each call opens a new connection — no pooling needed for batch pipeline.

    Usage:
        with get_db() as conn:
            conn.execute("INSERT INTO ...")
            # auto-commits on exit, auto-rollbacks on exception
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """
    Create all tables from schema.sql. Safe to run multiple times
    (all statements use IF NOT EXISTS).
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text()
    with get_db() as conn:
        conn.executescript(schema_sql)
    print(f"Database initialized: {DB_PATH}")
    print(f"Size: {DB_PATH.stat().st_size / 1024:.1f} KB")


def table_counts():
    """Print row count for every table. Quick health check."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]

    with get_db() as conn:
        for t in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
            if count > 0:
                print(f"  {t:30s} {count:>8,} rows")
            else:
                print(f"  {t:30s}    empty")


# ── Read helpers ──

def read_table(table_name, where=None, params=None, limit=None):
    """
    Read a table into a DataFrame.

    Examples:
        read_table("stocks")
        read_table("stocks", where="cap_tier = ?", params=["LARGE"])
        read_table("stock_prices", where="sid = ?", params=["RELI"], limit=30)
    """
    query = f"SELECT * FROM [{table_name}]"
    if where:
        query += f" WHERE {where}"
    if limit:
        query += f" LIMIT {int(limit)}"
    with get_db() as conn:
        return pd.read_sql_query(query, conn, params=params)


def read_sql(query, params=None):
    """Run arbitrary SQL and return a DataFrame."""
    with get_db() as conn:
        return pd.read_sql_query(query, conn, params=params)


def get_universe(tier=None, sector=None):
    """
    Load the stock universe.

    get_universe()                    → all 2,500 stocks
    get_universe(tier="LARGE")        → 100 large caps
    get_universe(sector="IT")         → all IT stocks
    """
    conditions = []
    params = []
    if tier:
        conditions.append("cap_tier = ?")
        params.append(tier)
    if sector:
        conditions.append("sector = ?")
        params.append(sector)

    where = " AND ".join(conditions) if conditions else None
    return read_table("stocks", where=where, params=params or None)


def get_latest_date(table_name, date_column="snapshot_date"):
    """Get the most recent date in a signal/snapshot table."""
    with get_db() as conn:
        row = conn.execute(
            f"SELECT MAX([{date_column}]) FROM [{table_name}]"
        ).fetchone()
        return row[0] if row else None


# ── Write helpers ──

def insert_df(df, table_name, conn=None):
    """
    Insert DataFrame rows. Skips rows that violate UNIQUE/PRIMARY KEY
    constraints (idempotent — safe to re-run).

    Use for append-only tables: insider_trades, bulk_deals, news_articles.
    """
    if df.empty:
        return 0

    cols = ", ".join(f"[{c}]" for c in df.columns)
    placeholders = ", ".join(["?"] * len(df.columns))
    sql = f"INSERT OR IGNORE INTO [{table_name}] ({cols}) VALUES ({placeholders})"

    def _execute(connection):
        cursor = connection.executemany(sql, df.values.tolist())
        return cursor.rowcount

    if conn is not None:
        return _execute(conn)
    else:
        with get_db() as connection:
            return _execute(connection)


def upsert_df(df, table_name, conn=None):
    """
    Insert or replace DataFrame rows (overwrites on PK conflict).
    Use for tables where you want to UPDATE existing rows.

    Use for: analyst_consensus, stocks, regime_state, signal tables.

    WARNING: INSERT OR REPLACE internally DELETEs then INSERTs.
    Current schema has no ON DELETE CASCADE, so this is safe.
    If cascade deletes are ever added, switch to INSERT ... ON CONFLICT UPDATE.
    """
    if df.empty:
        return 0

    cols = ", ".join(f"[{c}]" for c in df.columns)
    placeholders = ", ".join(["?"] * len(df.columns))
    sql = f"INSERT OR REPLACE INTO [{table_name}] ({cols}) VALUES ({placeholders})"

    def _execute(connection):
        cursor = connection.executemany(sql, df.values.tolist())
        return cursor.rowcount

    if conn is not None:
        return _execute(conn)
    else:
        with get_db() as connection:
            return _execute(connection)


# ── Data Health ──

# Per-table metadata for the data inventory page.
# Each entry has four structured fields so the user can scan a row and answer:
#   - kind:        Is this RAW (fetched), COMPUTED (derived from other tables), or STATE (single-row config/log)?
#   - depth:       *Why* the time span looks the way it does (10 years history, snapshot only, growing daily, etc.)
#   - description: What the table actually stores
#   - consumed_by: Which downstream signals/pages/scripts read from this table
TABLE_META = {
    # ── Universe ──
    "stocks": {
        "kind": "RAW",
        "depth": "Snapshot only",
        "description": "Universe of investable stocks (2,448 NSE-listed, ETFs excluded). Tickers, company names, sectors, market cap tiers (LARGE/MID/SMALL), and yfinance fundamentals (P/E, ROE, D/E). Single source of truth — every other table joins on `sid`.",
        "consumed_by": "every other table (FK target on `sid`)",
    },

    # ── Prices & Market ──
    "stock_prices": {
        "kind": "RAW",
        "depth": "3+ years (922 daily files)",
        "description": "Daily OHLCV bhavcopy per stock — open, high, low, close, volume, traded value, delivery quantity, delivery %. Foundational price table for momentum, RSI, returns, 52-week highs.",
        "consumed_by": "signals.momentum, smart_money_scores, screener, stock_detail price chart",
    },
    "vix_history": {
        "kind": "RAW",
        "depth": "3 years daily",
        "description": "India VIX daily values from yfinance. Used by the regime classifier to determine CALM/NORMAL/CAUTION/CRISIS state and adjust LARGE/MID/SMALL portfolio allocation.",
        "consumed_by": "scoring.regime → regime_state",
    },
    "regime_state": {
        "kind": "STATE",
        "depth": "Single row (current state)",
        "description": "Current VIX regime (CALM/NORMAL/CAUTION/CRISIS) and the corresponding tier allocation weights (alloc_large, alloc_mid, alloc_small).",
        "consumed_by": "screener (allocation), morning_brief, portfolio page",
    },

    # ── Tickertape Fundamentals ──
    "quarterly_income": {
        "kind": "RAW",
        "depth": "10 quarters per stock",
        "description": "Quarterly income statement from Tickertape — revenue, EBITDA, operating profit, PBT, net income, EPS, interest. Powers TTM ratios, YoY growth, Piotroski profitability factors, accruals, forensic Beneish.",
        "consumed_by": "signals.piotroski, signals.accruals, signals.forensic, stock_detail Financials tab",
    },
    "annual_balance_sheet": {
        "kind": "RAW",
        "depth": "10 years per stock",
        "description": "Annual balance sheet from Tickertape — total assets, equity, debt, current assets/liabilities, shares outstanding, retained earnings, net PPE. Powers D/E, ROE, ROA, current ratio, book value, Altman Z, Piotroski leverage.",
        "consumed_by": "signals.piotroski (leverage), signals.forensic (Altman), stock_detail Financials tab",
    },
    "annual_cash_flow": {
        "kind": "RAW",
        "depth": "10 years per stock",
        "description": "Annual cash flow statement from Tickertape — operating CF, capex, free cash flow, financing CF, depreciation. Powers FCF yield, Piotroski CFO/accruals quality, capex ratio.",
        "consumed_by": "signals.piotroski (CFO), signals.accruals, stock_detail Financials tab",
    },
    "shareholding": {
        "kind": "RAW",
        "depth": "~6 quarters per stock (window varies by fetch date)",
        "description": "Quarterly shareholding pattern from Tickertape — promoter %, FII %, MF %, DII %, public %, pledge %, insurance %. Each stock has ~6 trailing quarters at the time it was last fetched, so the calendar span across the table looks much wider than the per-stock depth. Powers promoter signal (QoQ change).",
        "consumed_by": "signals.promoter, stock_detail Ownership tab",
    },
    "analyst_consensus": {
        "kind": "RAW",
        "depth": "Latest snapshot per stock",
        "description": "Latest analyst consensus snapshot from Tickertape — price target, total analysts, buy %, forward EPS/revenue, EPS/revenue growth %. One row per stock.",
        "consumed_by": "signals.consensus → consensus_signals, stock_detail Consensus tab",
    },
    "forecast_history": {
        "kind": "RAW",
        "depth": "Time series of revisions",
        "description": "Time series of analyst forecast revisions — price target, EPS, revenue forecasts over time. Used to compute pt_revision_1yr signal and the forecast revision chart.",
        "consumed_by": "signals.consensus (PT revision), stock_detail forecast chart",
    },

    # ── Trades ──
    "insider_trades": {
        "kind": "RAW",
        "depth": "2+ years history (NSE PIT)",
        "description": "Promoter/KMP/director trades from NSE PIT API — person, transaction type, shares (`secAcq`), value (`secVal`). 1,043 stocks covered.",
        "consumed_by": "signals.insider_signal → insider_signals, stock_detail Ownership timeline",
    },
    "insider_signals": {
        "kind": "COMPUTED",
        "depth": "25 months reconstructed",
        "description": "Computed monthly insider buying/selling signal per stock derived from `insider_trades`. 25 months of history reconstructed for backtesting + the current month.",
        "consumed_by": "scoring.screener (insider signal), backtester",
    },
    "bulk_deals": {
        "kind": "RAW",
        "depth": "Growing daily (no historical archive)",
        "description": "Daily bulk/block deals from NSE archives. NO HISTORICAL ARCHIVE — only today's file is fetchable, so this accumulates one day at a time.",
        "consumed_by": "signals.smart_money → smart_money_scores",
    },

    # ── News & Regulatory ──
    "news_articles": {
        "kind": "RAW",
        "depth": "Growing daily from RSS",
        "description": "RSS news articles from 8-11 financial publications (ET, Mint, BS, Moneycontrol, etc.). Title, summary, URL, publication date.",
        "consumed_by": "signals.sentiment, regulatory_classifier, stock_detail News card",
    },
    "news_article_stocks": {
        "kind": "COMPUTED",
        "depth": "Grows with news_articles",
        "description": "Entity matching: which news articles mention which stocks. Created by string matching company names + tickers against titles and summaries.",
        "consumed_by": "signals.sentiment (per stock), stock_detail News card",
    },
    "earnings_calendar": {
        "kind": "RAW",
        "depth": "Forward-looking events",
        "description": "Upcoming corporate event dates from NSE — earnings, dividends, board meetings. Sparse coverage (~50 stocks at any time).",
        "consumed_by": "morning_brief Upcoming Earnings, stock_detail Overview",
    },
    "regulatory_events": {
        "kind": "RAW",
        "depth": "3 years harvested",
        "description": "Regulatory events harvested from Google News + RBI circulars + Wayback Machine + PIB. 16,523 events spanning 2023-2026. Each event has a `classifier_status` column tracking whether the AI classifier has processed it (see CLAUDE.md rule #17).",
        "consumed_by": "regulatory_classifier → regulatory_signals",
    },
    "regulatory_signals": {
        "kind": "COMPUTED",
        "depth": "Partial — ~16% of regulatory_events classified (API budget locked)",
        "description": "AI-classified sector impacts from `regulatory_events`. Stage 1 Haiku pre-filter + Stage 2 Sonnet deep classify. Each event can produce 1-N sector signals (direction, magnitude, time_horizon, confidence, reasoning). Currently 5,687 signals from 2,702 of 16,523 events; the rest is paused on Anthropic budget cap.",
        "consumed_by": "signals.regulatory → macro_sector_signals",
    },

    # ── Macro ──
    "macro_history": {
        "kind": "RAW",
        "depth": "3+ years (50 indicators)",
        "description": "Time series of 50 macro indicators (Nifty sectors, commodities, FX, rates, IIP, CPI, Core Sector, GST). Sources: yfinance + data.gov.in + FRED. Daily and monthly frequencies.",
        "consumed_by": "signals.macro → macro_sector_signals",
    },
    "macro_indicators": {
        "kind": "RAW",
        "depth": "Static snapshot (legacy v1)",
        "description": "Static snapshot (22 rows) of macro indicators from RBI/PIB/MOSPI. Migrated from v1; replaced by `macro_history` for new work.",
        "consumed_by": "(legacy — superseded by macro_history)",
    },
    "macro_indicator_meta": {
        "kind": "RAW",
        "depth": "Registry (50 entries)",
        "description": "Registry of all 50 macro indicators with source, frequency, sector mapping, and units. Used by the macro signal generator to resolve indicator → sector.",
        "consumed_by": "signals.macro",
    },
    "macro_sector_map": {
        "kind": "RAW",
        "depth": "Configuration (30 rules)",
        "description": "Mapping table: macro indicator → affected sector → direction (+1/-1) → weight. Translates indicator changes into sector scores.",
        "consumed_by": "signals.macro",
    },
    "macro_sector_signals": {
        "kind": "COMPUTED",
        "depth": "Latest snapshot per sector",
        "description": "Sector-level macro and regulatory scores (one row per sector). Combines macro indicator changes + AI-classified regulatory events.",
        "consumed_by": "screener (sector tilt), morning_brief tailwinds/headwinds, sectors page",
    },

    # ── Computed Signals ──
    "piotroski_scores": {
        "kind": "COMPUTED",
        "depth": "Latest snapshot per stock",
        "description": "9-factor Piotroski F-Score per stock — profitability (3), leverage (3), efficiency (3). Range 0-9. Computed from quarterly_income + annual_balance_sheet + annual_cash_flow.",
        "consumed_by": "screener, quality_gate, stock_detail Forensic tab",
    },
    "accruals_scores": {
        "kind": "COMPUTED",
        "depth": "Latest snapshot per stock",
        "description": "Cash flow accruals + balance sheet accruals + earnings persistence per stock. Measures whether reported earnings are backed by cash. Powers the accruals signal.",
        "consumed_by": "screener, stock_detail Forensic tab",
    },
    "consensus_signals": {
        "kind": "COMPUTED",
        "depth": "Latest snapshot per stock",
        "description": "Computed consensus signal per stock — combines pt_upside, pt_revision_1yr, eps_growth, revenue_growth from analyst_consensus + forecast_history.",
        "consumed_by": "screener, stock_detail Overview signal cards",
    },
    "promoter_signals": {
        "kind": "COMPUTED",
        "depth": "Latest snapshot per stock",
        "description": "Computed promoter signal per stock — QoQ change in promoter holding, trend direction, pledge quality. From `shareholding`.",
        "consumed_by": "screener, stock_detail Ownership tab",
    },
    "forensic_scores": {
        "kind": "COMPUTED",
        "depth": "Latest snapshot per stock",
        "description": "Beneish M-Score (earnings manipulation detector, 6-factor) + Altman Z'' (bankruptcy predictor, emerging market variant) per stock. Used as a forensic penalty in the screener.",
        "consumed_by": "screener (forensic_adj), stock_detail Forensic tab",
    },
    "smart_money_scores": {
        "kind": "COMPUTED",
        "depth": "Latest snapshot per stock",
        "description": "Composite institutional accumulation signal — bulk deal activity (60%) + delivery percentage (40%). Range 0-100.",
        "consumed_by": "screener, stock_detail Overview",
    },
    "sentiment_scores": {
        "kind": "COMPUTED",
        "depth": "7-day rolling per stock",
        "description": "VADER sentiment scores from news articles, aggregated to per-stock 7-day windows.",
        "consumed_by": "screener (sentiment signal), stock_detail",
    },

    # ── Output ──
    "daily_picks": {
        "kind": "COMPUTED",
        "depth": "Latest pick_date snapshot",
        "description": "Daily output of the screener — every stock with its final_score, rank within tier, base_score, and forensic_adj. The ranked universe.",
        "consumed_by": "morning_brief, action_queue, signals page, sectors page",
    },
    "daily_snapshots": {
        "kind": "COMPUTED",
        "depth": "Growing daily (PIT archive)",
        "description": "Point-in-time archive of all signal values per stock. One row per stock per pick_date. Used for diff engine + signal time series + backtesting.",
        "consumed_by": "daily_changes (diff engine), backtester",
    },
    "daily_changes": {
        "kind": "COMPUTED",
        "depth": "Growing daily",
        "description": "Output of the diff engine — what changed today vs yesterday. ENTRY/EXIT/UPGRADE/DOWNGRADE/SIGNAL_FIRED/REGIME_CHANGE events.",
        "consumed_by": "morning_brief Today's Changes card",
    },

    # ── System ──
    "pipeline_log": {
        "kind": "LOG",
        "depth": "Per-step run history (append-only)",
        "description": "Append-only audit trail of every pipeline step run — start/end timestamps, status (RUNNING/SUCCESS/FAILED), rows affected, duration, error message. Each step writes a RUNNING row on start and a SUCCESS/FAILED row on completion.",
        "consumed_by": "system page Pipeline Log",
    },
    "sqlite_sequence": {
        "kind": "STATE",
        "depth": "Internal",
        "description": "Internal SQLite table tracking AUTOINCREMENT counters. Not user-facing.",
        "consumed_by": "(internal — SQLite engine)",
    },
}


def _date_span(latest_date_str, earliest_date_str):
    """Compute human-readable date span: '3.2 years' or '4 months' or '—'.

    Note: string MIN/MAX from SQLite can be unreliable when a column mixes
    ISO and RFC-2822 date formats — the lexicographic ordering doesn't
    correspond to chronological ordering. We parse both strings and use the
    actual timestamp delta.
    """
    if not latest_date_str or not earliest_date_str:
        return "—"
    try:
        latest = pd.to_datetime(latest_date_str, errors="coerce", utc=True, format="mixed")
        earliest = pd.to_datetime(earliest_date_str, errors="coerce", utc=True, format="mixed")
        if pd.isna(latest) or pd.isna(earliest):
            return "—"
        # Defensive: if string MIN/MAX swapped them due to mixed formats, fix here
        if earliest > latest:
            earliest, latest = latest, earliest
        days = (latest - earliest).days
        if days <= 1:
            return "1 day"
        if days < 60:
            return f"{days} days"
        months = days / 30.44
        if months < 24:
            return f"{months:.1f} months"
        return f"{days / 365.25:.1f} years"
    except Exception:
        return "—"


def _table_date_range(conn, tbl):
    """Find the earliest and latest dates in a table by scanning candidate date columns.

    Strategy:
      1. For each candidate column, get the row count and the SQL MIN/MAX.
      2. If both MIN and MAX parse cleanly AND parsed_max > parsed_min, trust them
         (this is the fast path for clean ISO/single-format columns).
      3. Otherwise (mixed formats — lexical SQL min/max can be wrong) read every
         distinct value, parse all of them, and take the true min/max.

    Returns (earliest_iso, latest_iso, span_str) or (None, None, '—').
    """
    # Ordered: business/event dates first, ingestion timestamps last. Tables like
    # insider_trades and bulk_deals carry both — we want the trade/deal date span,
    # not when v2 ingested the row (which is bounded by the v2 cutover).
    DATE_COLS = ["snapshot_date", "date", "end_date", "period", "pick_date",
                 "run_date", "published_at", "deal_date", "trade_date",
                 "classified_at", "fetched_at", "updated_at"]

    for col in DATE_COLS:
        try:
            sql_min, sql_max = conn.execute(
                f"SELECT MIN([{col}]), MAX([{col}]) FROM [{tbl}] WHERE [{col}] IS NOT NULL"
            ).fetchone()
        except Exception:
            continue

        if not sql_min or not sql_max:
            continue

        sql_min_ts = pd.to_datetime(sql_min, errors="coerce", utc=True, format="mixed")
        sql_max_ts = pd.to_datetime(sql_max, errors="coerce", utc=True, format="mixed")

        # NSE PIT occasionally returns filings with trade_date months in the future
        # (data-entry errors). Cap latest at today + 7d so the span/freshness
        # calculations don't get poisoned. Year >= 2000 catches stubs like 1899.
        upper_bound = pd.Timestamp.utcnow() + pd.Timedelta(days=7)

        # Fast path: both parse and chronologically consistent
        if (pd.notna(sql_min_ts) and pd.notna(sql_max_ts)
                and sql_max_ts >= sql_min_ts
                and sql_min_ts.year >= 2000
                and sql_max_ts <= upper_bound):
            earliest_iso = sql_min_ts.strftime("%Y-%m-%d")
            latest_iso = sql_max_ts.strftime("%Y-%m-%d")
            return earliest_iso, latest_iso, _date_span(latest_iso, earliest_iso)

        # Slow path: mixed-format column (e.g. regulatory_events.published_at)
        # OR sentinel/future dates polluting the range. Read every distinct value,
        # parse, take real min/max from parsed values that are sane.
        try:
            cur = conn.execute(
                f"SELECT DISTINCT [{col}] FROM [{tbl}] WHERE [{col}] IS NOT NULL"
            )
            vals = [r[0] for r in cur.fetchall() if r[0]]
            if not vals:
                continue
            parsed = pd.to_datetime(pd.Series(vals), errors="coerce", utc=True, format="mixed")
            parsed = parsed.dropna()
            # Filter sentinel stubs and rogue future-dated entries
            parsed = parsed[(parsed.dt.year >= 2000) & (parsed <= upper_bound)]
            if parsed.empty:
                continue
            earliest_iso = parsed.min().strftime("%Y-%m-%d")
            latest_iso = parsed.max().strftime("%Y-%m-%d")
            return earliest_iso, latest_iso, _date_span(latest_iso, earliest_iso)
        except Exception:
            continue

    return None, None, "—"


# ── Dynamic codebase scan for table lineage ──
#
# Replaces the hand-curated `consumed_by` field. Walks signals/, scoring/,
# output/, sources/, cockpit/ once and finds every file that reads or writes
# each table. Cached at module level — invalidated only on cockpit reload.
#
# Reads vs writes are inferred from the syntactic context:
#   - read_table("foo")        → read
#   - upsert_df(df, "foo")     → write
#   - insert_df(df, "foo")     → write
#   - FROM foo / JOIN foo      → read
#   - INSERT INTO foo / UPDATE → write
# Templates (.html) are scanned for table-name string literals only.

_DB_REFERENCES = None  # populated lazily by get_db_references()

# Directories to walk recursively for .py files
_SCAN_DIRS = ("signals", "scoring", "output", "sources", "cockpit")
# Top-level files to also scan (pipeline orchestrator etc.)
_SCAN_ROOT_FILES = ("pipeline.py", "validate.py")
# Files to never count (this file is the canonical TABLE_META — every table
# name appears here, which would otherwise pollute every "consumed_by" cell).
_SCAN_EXCLUDE = {"db.py"}  # only exclude this file (canonical TABLE_META)


def _scan_db_references():
    """Walk the codebase, return {table: {"reads": [files], "writes": [files]}}.

    Each entry is a sorted list of project-relative file paths. Empty lists
    are kept (so the caller can show '(unused)' or '(no producer)').

    Only .py files are scanned. Templates (.html) are deliberately excluded —
    sql_console.html embeds every table name in its example-query dropdown,
    which would create false positives in every row. Templates render data
    that the python layer prepares; the python file that prepares the data
    is the true consumer in the lineage sense.
    """
    import re

    project_root = Path(__file__).resolve().parent
    table_names = list(TABLE_META.keys())

    # Pre-compile one regex per table for both directions. \b ensures whole-word
    # matching so 'stocks' doesn't match 'stock_prices'.
    write_patterns = {}
    read_patterns = {}
    for tbl in table_names:
        e = re.escape(tbl)
        write_patterns[tbl] = re.compile(
            rf'(?:upsert_df\s*\([^,)]*,\s*["\']{e}["\']'
            rf'|insert_df\s*\([^,)]*,\s*["\']{e}["\']'
            rf'|INSERT\s+(?:OR\s+(?:IGNORE|REPLACE)\s+)?INTO\s+\[?{e}\b'
            rf'|UPDATE\s+\[?{e}\b'
            rf'|REPLACE\s+INTO\s+\[?{e}\b)',
            re.IGNORECASE,
        )
        read_patterns[tbl] = re.compile(
            rf'(?:read_table\s*\(\s*["\']{e}["\']'
            rf'|FROM\s+\[?{e}\b'
            rf'|JOIN\s+\[?{e}\b)',
            re.IGNORECASE,
        )

    refs = {tbl: {"reads": set(), "writes": set()} for tbl in table_names}

    # Build the file list: directory walk + named root files
    files_to_scan = []
    for d in _SCAN_DIRS:
        dir_path = project_root / d
        if not dir_path.exists():
            continue
        for f in dir_path.rglob("*.py"):
            if any(part.startswith((".", "__")) for part in f.relative_to(project_root).parts):
                continue
            files_to_scan.append(f)
    for fn in _SCAN_ROOT_FILES:
        f = project_root / fn
        if f.exists():
            files_to_scan.append(f)

    for f in files_to_scan:
        rel = str(f.relative_to(project_root))
        if rel in _SCAN_EXCLUDE:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for tbl in table_names:
            if write_patterns[tbl].search(text):
                refs[tbl]["writes"].add(rel)
            if read_patterns[tbl].search(text):
                refs[tbl]["reads"].add(rel)

    return {
        tbl: {"reads": sorted(v["reads"]), "writes": sorted(v["writes"])}
        for tbl, v in refs.items()
    }


def get_db_references():
    """Lazy-cached accessor for the codebase scan."""
    global _DB_REFERENCES
    if _DB_REFERENCES is None:
        _DB_REFERENCES = _scan_db_references()
    return _DB_REFERENCES


# ── Freshness benchmark ──
#
# Each refresh frequency has a tolerance window. If `latest_date` is within
# the window we call the table FRESH. 1-2x window → STALE. >2x → OUTDATED.
# Tables with no refresh schedule (configuration tables, single-row state)
# return N/A.

STALENESS_THRESHOLDS = {
    "daily": 3,        # allow long weekends
    "weekly": 10,
    "monthly": 40,
    "quarterly": 100,
    "annual": 400,
}


def _compute_freshness(latest_date_iso, refresh_freq):
    """Return (status, age_days, threshold_days). status ∈ FRESH/STALE/OUTDATED/N/A."""
    if not latest_date_iso or refresh_freq not in STALENESS_THRESHOLDS:
        return "N/A", None, None
    try:
        from datetime import datetime
        latest = datetime.strptime(latest_date_iso, "%Y-%m-%d").date()
        today = datetime.now().date()
        age = (today - latest).days
        threshold = STALENESS_THRESHOLDS[refresh_freq]
        if age <= threshold:
            return "FRESH", age, threshold
        if age <= threshold * 2:
            return "STALE", age, threshold
        return "OUTDATED", age, threshold
    except Exception:
        return "N/A", None, None


# Domain grouping for the cockpit's Data Inventory section.
# Add new tables here as they're introduced. Unmapped tables fall to "Other".
TABLE_DOMAIN = {
    # Universe & Prices
    "stocks": "Universe & Prices",
    "stock_prices": "Universe & Prices",
    "vix_history": "Universe & Prices",
    "regime_state": "Universe & Prices",
    # Fundamentals (Tickertape)
    "quarterly_income": "Fundamentals",
    "annual_balance_sheet": "Fundamentals",
    "annual_cash_flow": "Fundamentals",
    "shareholding": "Fundamentals",
    "analyst_consensus": "Fundamentals",
    "forecast_history": "Fundamentals",
    # Trades & corporate actions
    "insider_trades": "Trades & Corporate",
    "bulk_deals": "Trades & Corporate",
    "earnings_calendar": "Trades & Corporate",
    # News
    "news_articles": "News & Sentiment",
    "news_article_stocks": "News & Sentiment",
    # Macro
    "macro_history": "Macro",
    "macro_indicators": "Macro",
    "macro_indicator_meta": "Macro",
    "macro_sector_map": "Macro",
    "macro_sector_signals": "Macro",
    # Regulatory
    "regulatory_events": "Regulatory",
    "regulatory_signals": "Regulatory",
    # Per-stock computed signals
    "piotroski_scores": "Computed Signals",
    "accruals_scores": "Computed Signals",
    "consensus_signals": "Computed Signals",
    "promoter_signals": "Computed Signals",
    "forensic_scores": "Computed Signals",
    "smart_money_scores": "Computed Signals",
    "sentiment_scores": "Computed Signals",
    "insider_signals": "Computed Signals",
    # Daily output
    "daily_picks": "Output",
    "daily_snapshots": "Output",
    "daily_changes": "Output",
    # Pipeline / internal
    "pipeline_log": "Pipeline",
    "sqlite_sequence": "Pipeline",
}

# Display order for the domain sections.
DOMAIN_ORDER = [
    "Universe & Prices",
    "Fundamentals",
    "Trades & Corporate",
    "News & Sentiment",
    "Macro",
    "Regulatory",
    "Computed Signals",
    "Output",
    "Pipeline",
    "Other",
]


def data_health():
    """
    Comprehensive data health report. Merges DB row counts with pipeline-step
    metadata from config.PIPELINE_STEPS + config.RAW_TABLES, per-table
    descriptions, date spans, freshness benchmark, and dynamic lineage from
    scanning the codebase.

    Returns DataFrame with: table, rows, kind, depth, description, source,
    frequency, earliest_date, latest_date, date_span, freshness, age_days,
    threshold_days, produced_by, consumed_by, status.
    """
    from config import PIPELINE_STEPS, RAW_TABLES

    # Build lookup: table → registered metadata (source, refresh frequency)
    meta = {}
    for s in PIPELINE_STEPS:
        if s.get("table"):
            meta[s["table"]] = {
                "source": s["source"],
                "data_freq": s["data_freq"],
                "frequency": s["frequency"],
                "step_name": s["name"],
                "function": f"{s['module']}.{s['function']}",
            }
    for r in RAW_TABLES:
        if r["table"] not in meta:
            meta[r["table"]] = {
                "source": r["source"],
                "data_freq": r["data_freq"],
                "frequency": r["frequency"],
                "step_name": "—",
                "function": "—",
            }

    # Dynamic codebase lineage scan
    refs = get_db_references()

    # Walk every table in the DB (including sqlite_sequence — user wants it kept)
    with get_db() as conn:
        tables = [
            row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        ]

    # Universe size (for stock-coverage column on per-stock tables).
    try:
        with get_db() as conn:
            universe_size = conn.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
    except Exception:
        universe_size = 0

    rows = []
    for tbl in tables:
        with get_db() as conn:
            count = conn.execute(f"SELECT COUNT(*) FROM [{tbl}]").fetchone()[0]
            earliest, latest, date_span = _table_date_range(conn, tbl)
            # Stock coverage: only meaningful for tables with a sid column.
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info([{tbl}])").fetchall()]
            if "sid" in cols and universe_size > 0:
                stock_count = conn.execute(
                    f"SELECT COUNT(DISTINCT sid) FROM [{tbl}]"
                ).fetchone()[0] or 0
                stock_coverage_pct = round(100 * stock_count / universe_size, 1)
                stock_coverage = f"{stock_count:,} / {universe_size:,} ({stock_coverage_pct:g}%)"
            else:
                stock_count = None
                stock_coverage_pct = None
                stock_coverage = "—"

        m = meta.get(tbl, {})
        tm = TABLE_META.get(tbl, {})
        ref = refs.get(tbl, {"reads": [], "writes": []})

        # Lineage formatting — produced_by from scan, fall back to PIPELINE_STEPS function
        if ref["writes"]:
            produced_by = ", ".join(ref["writes"])
        elif m.get("function") and m["function"] != "—":
            produced_by = m["function"]
        else:
            produced_by = "—"

        if ref["reads"]:
            # Drop self-reads (a producer often reads its own table)
            consumers = [r for r in ref["reads"] if r not in ref["writes"]]
            consumed_by = ", ".join(consumers) if consumers else "(no external consumers)"
        else:
            consumed_by = "(no consumers found)"

        # Freshness benchmark
        freshness, age_days, threshold_days = _compute_freshness(latest, m.get("frequency"))

        status = "OK" if count > 0 else "EMPTY"

        # Consumer count for the inventory's "Used by" column.
        consumers_list = ref["reads"]
        if ref["writes"]:
            consumers_list = [r for r in consumers_list if r not in ref["writes"]]
        consumed_count = len(consumers_list)

        rows.append({
            "table": tbl,
            "domain": TABLE_DOMAIN.get(tbl, "Other"),
            "rows": count,
            "kind": tm.get("kind", "—"),
            "depth": tm.get("depth", "—"),
            "description": tm.get("description", "—"),
            "produced_by": produced_by,
            "consumed_by": consumed_by,
            "consumed_count": consumed_count,
            "source": m.get("source", "—"),
            "data_freq": m.get("data_freq", "—"),
            "frequency": m.get("frequency", "—"),
            "earliest_date": earliest,
            "latest_date": latest,
            "date_span": date_span,
            "freshness": freshness,
            "age_days": age_days,
            "threshold_days": threshold_days,
            "stock_count": stock_count,
            "stock_coverage_pct": stock_coverage_pct,
            "stock_coverage": stock_coverage,
            "status": status,
        })

    return pd.DataFrame(rows)


def db_summary():
    """High-level health verdict for the system page header.

    Returns a dict with totals, kind breakdown, freshness counts, last
    pipeline run, and a one-line written verdict.
    """
    df = data_health()
    db_size_mb = DB_PATH.stat().st_size / 1024 / 1024

    # Last successful pipeline run
    last_run = {"started_at": None, "run_date": None, "step_name": None, "status": None}
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT run_date, step_name, status, started_at FROM pipeline_log "
                "WHERE status IN ('SUCCESS','FAILED') ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            if row:
                last_run = {"run_date": row[0], "step_name": row[1], "status": row[2], "started_at": row[3]}
    except Exception:
        pass

    kind_counts = df["kind"].value_counts().to_dict()
    fresh_counts = df["freshness"].value_counts().to_dict()
    empty_count = int((df["status"] == "EMPTY").sum())
    total_rows = int(df["rows"].sum())

    # Written verdict — order from most-alarming to least
    outdated = fresh_counts.get("OUTDATED", 0)
    stale = fresh_counts.get("STALE", 0)
    fresh = fresh_counts.get("FRESH", 0)
    na = fresh_counts.get("N/A", 0)

    if outdated:
        verdict = f"NEEDS ATTENTION — {outdated} table(s) outdated past 2× their refresh window."
    elif stale:
        verdict = f"WATCH — {stale} table(s) past their refresh window but within 2×."
    elif empty_count > 1:  # daily_changes is allowed to be empty
        verdict = f"WATCH — {empty_count} table(s) empty."
    else:
        verdict = "HEALTHY — all refreshable tables are fresh."

    return {
        "total_tables": len(df),
        "total_rows": total_rows,
        "db_size_mb": round(db_size_mb, 1),
        "kind_counts": kind_counts,
        "fresh_counts": {"FRESH": fresh, "STALE": stale, "OUTDATED": outdated, "N/A": na},
        "empty_count": empty_count,
        "last_run": last_run,
        "verdict": verdict,
    }


# ── Read-only SQL query helper for the cockpit SQL console ──

# Statements explicitly forbidden in the SQL console — must be a whole word match
SQL_FORBIDDEN = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "REPLACE", "TRUNCATE", "ATTACH", "DETACH", "VACUUM", "REINDEX",
    "PRAGMA",
)


def safe_read_sql(query, max_rows=500):
    """
    Run a single read-only SQL statement and return (DataFrame, error_message).

    Used by the cockpit SQL console. Refuses any statement containing
    write keywords (INSERT/UPDATE/DELETE/etc) or multiple statements.
    Caps result rows to `max_rows`.

    Returns: (DataFrame or None, error_message or None)
    """
    if not query or not query.strip():
        return None, "Empty query"

    q = query.strip().rstrip(";")

    # Reject multiple statements
    if ";" in q:
        return None, "Only single statements allowed (no semicolons)"

    # Tokenize and check for forbidden keywords (whole-word match, case-insensitive)
    import re
    upper = q.upper()
    tokens = set(re.findall(r"\b[A-Z_]+\b", upper))
    bad = tokens & set(SQL_FORBIDDEN)
    if bad:
        return None, f"Forbidden keyword(s): {', '.join(sorted(bad))}. SQL console is read-only."

    # Must start with SELECT or WITH
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        return None, "Query must start with SELECT or WITH"

    # Add row cap if not already present
    if "LIMIT" not in upper:
        q += f" LIMIT {int(max_rows)}"

    try:
        with get_db() as conn:
            df = pd.read_sql_query(q, conn)
        return df, None
    except Exception as e:
        # pandas wraps sqlite errors as `DatabaseError: Execution failed on sql '...': <real msg>`.
        # Surface only the sqlite portion to keep the console message friendly.
        msg = str(e.__cause__) if e.__cause__ else str(e)
        return None, msg


# ── Quick self-test ──

if __name__ == "__main__":
    print("Initializing database...\n")
    init_db()
    print("\nTable inventory:")
    table_counts()
