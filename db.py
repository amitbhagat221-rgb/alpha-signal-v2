"""
Alpha Signal v2 — Database Module

Single point of access for all database operations.
Every other module imports from here. Never open sqlite3 directly.

Usage:
    from db import get_db, read_table, get_universe, init_db
"""

import glob
import json
import re
import sqlite3
import threading
import time as _time_module
import pandas as pd
from pathlib import Path
from contextlib import contextmanager

# ── Paths ──
PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "alpha_signal.db"
SCHEMA_PATH = PROJECT_ROOT / "schema.sql"

# Candidate business-date columns, checked by both _table_date_range (freshness
# scan) and the future-date ingestion guard below. Ordered: business/event dates
# first, ingestion timestamps last.
DATE_COLS = ["snapshot_date", "date", "end_date", "period", "pick_date",
             "asof_date", "as_of_date", "run_date", "published_at", "deal_date",
             "trade_date", "classified_at", "brief_date", "change_date",
             "fetched_at", "updated_at"]


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
    _ensure_columns()
    print(f"Database initialized: {DB_PATH}")
    print(f"Size: {DB_PATH.stat().st_size / 1024:.1f} KB")


# Columns added after a table was first created. SQLite has no "ADD COLUMN
# IF NOT EXISTS" so we catch the duplicate-column error. Append to this list
# whenever a new column is added to an existing table; never edit existing
# entries (they're idempotent by design).
_COLUMN_MIGRATIONS = [
    # 2026-06-14: Next-3 #1c — transcript look-ahead fix. bse_filing_date = the real
    # BSE filing dt_tm (matched by PDF GUID ↔ bse_announcements.attachment), the
    # look-ahead-safe availability date. nlp_scores.available_date carries the canonical
    # COALESCE(bse_filing_date, announce_date, doc_date) into the enriched layer so the
    # future NLP PIT helper filters on the real date, not the first-of-month doc_date
    # proxy (median +14d, p90 +27d look-ahead; 95% of rows proxy-earlier-than-filing).
    ("transcripts", "bse_filing_date", "TEXT"),
    ("nlp_scores",  "available_date",  "TEXT"),
    # 2026-06-01: fast-read keyword tags per article (LLM-generated, JSON array)
    ("news_enriched", "keywords", "TEXT"),
    ("daily_picks", "weight_coverage", "REAL"),
    ("daily_picks", "price_rows", "INTEGER"),
    ("daily_picks", "fundamental_coverage", "REAL"),
    # 2026-05-24: insider_signal and sentiment_7d now PIT-reconstructible.
    ("daily_snapshots_pit", "insider_score", "REAL"),
    ("daily_snapshots_pit", "sentiment_7d", "REAL"),
    # 2026-05-24 (session #3): plan 0005 Phase A — per-signal eligibility,
    # plus Phase B — per-stock integrity validator
    ("daily_picks", "eligible_coverage", "REAL"),
    ("daily_picks", "integrity_status", "TEXT"),
    ("daily_picks", "integrity_reasons", "TEXT"),
    # 2026-05-24 (session #4): plan 0005 Phase D.5 — bootstrap CIs on t-stat
    ("pit_ic_by_tier_v2", "t_stat_ci_lo", "REAL"),
    ("pit_ic_by_tier_v2", "t_stat_ci_hi", "REAL"),
    # 2026-05-26: MF research section (plan prfect-lets-add-a-zazzy-eich)
    ("mf_schemes", "category_norm",     "TEXT"),
    ("mf_schemes", "benchmark",         "TEXT"),
    ("mf_schemes", "inception_date",    "TEXT"),
    ("mf_schemes", "has_full_history",  "INTEGER DEFAULT 0"),
    # 2026-05-26: data-quality flag on master — keeps wound-up / segregated /
    # interval-fund / NAV-anomalous schemes out of the universe browser + scorer.
    # Values: TRUSTED (default) / WOUND_UP / SEGREGATED / INTERVAL / ANOMALOUS / BONUS
    ("mf_scheme_master", "data_quality",       "TEXT DEFAULT 'TRUSTED'"),
    ("mf_scheme_master", "quality_reason",     "TEXT"),
    # 2026-05-29: Track 2.2b — Financial sub-model PIT column. NULL for non-
    # financials (Banks + NBFCs scope per ADR 0030).
    ("daily_snapshots_pit", "financial_signal", "REAL"),
    # 2026-05-29 (session #2): Phase 2.2b-v2 — split into quality (SMALL) +
    # recovery (LARGE/MID) per the direction-flip backtest finding. Both
    # columns; screener picks one based on cap_tier. `financial_signal`
    # retained as alias for the quality variant for back-compat.
    ("daily_snapshots_pit", "financial_quality",  "REAL"),
    ("daily_snapshots_pit", "financial_recovery", "REAL"),
    ("financial_signal_scores", "financial_quality",  "REAL"),
    ("financial_signal_scores", "financial_recovery", "REAL"),
    ("financial_signal_scores", "quality_basis",      "TEXT"),
    ("financial_signal_scores", "recovery_basis",     "TEXT"),
    ("financial_signal_scores", "asset_quality_quality_z",  "REAL"),
    ("financial_signal_scores", "asset_quality_recovery_z", "REAL"),
    # ── Plan 0007 Phase 5: per-pick UHS columns ──
    # uhs_score is the 0-100 normalized score for THIS pick at pick_date.
    # uhs_breakdown_json keeps the 5 dim values + reasons for the explorer
    # Trust panel and the dossier prompt. uhs_label is the UHS band
    # (UNKNOWN/AVOID/REVIEW/PRELIMINARY/TRUSTED). uhs_worst_dim is the lowest-
    # scoring dim (drives the dossier's "weak dim" disclosure).
    ("daily_picks", "uhs_score",          "INTEGER"),
    ("daily_picks", "uhs_breakdown_json", "TEXT"),
    ("daily_picks", "uhs_label",          "TEXT"),
    ("daily_picks", "uhs_worst_dim",      "TEXT"),
    # 2026-05-31: Plan 0006 Phase E — per-sector S/M/L momentum horizon badges.
    # Categorical {strong/neutral/weak} written by signals.sector_momentum.
    ("sector_briefs", "horizon_short",  "TEXT"),
    ("sector_briefs", "horizon_medium", "TEXT"),
    ("sector_briefs", "horizon_long",   "TEXT"),
    # Per-stock sector-momentum factor PIT column (medium-horizon RS z-score).
    ("daily_snapshots_pit", "sector_momentum", "REAL"),
    # ADR 0041: per-stock sector-tilt factor PIT column (6m-mom + macro z-ensemble).
    ("daily_snapshots_pit", "sector_tilt", "REAL"),
    # 2026-05-31: Plan 0002 §3.2.2 — F&O open-interest factor PIT columns.
    ("daily_snapshots_pit", "pcr_oi",            "REAL"),
    ("daily_snapshots_pit", "pcr_volume",        "REAL"),
    ("daily_snapshots_pit", "max_pain_distance", "REAL"),
    ("daily_snapshots_pit", "oi_buildup_signal", "REAL"),
    # 2026-05-31: Plan 0002 §3.2.2 — F&O implied-volatility factor PIT columns.
    ("daily_snapshots_pit", "iv_skew_25d",        "REAL"),
    ("daily_snapshots_pit", "iv_term_structure",  "REAL"),
    ("daily_snapshots_pit", "iv_realised_spread", "REAL"),
    ("daily_snapshots_pit", "iv_percentile_1y",   "REAL"),
    # 2026-05-31: Plan 0002 §3.2.3 — daily-derivable microstructure PIT columns.
    ("daily_snapshots_pit", "intraday_range_compression", "REAL"),
    ("daily_snapshots_pit", "closing_strength_1m",        "REAL"),
    ("daily_snapshots_pit", "opening_gap_freq_1m",        "REAL"),
    ("daily_snapshots_pit", "vwap_deviation_5d",          "REAL"),
    ("daily_snapshots_pit", "bidask_spread_proxy",        "REAL"),
    ("daily_snapshots_pit", "kyle_lambda",                "REAL"),
    # 2026-05-31: Plan 0002 §3.2.5 — event-time / PEAD PIT columns.
    ("daily_snapshots_pit", "earnings_surprise_std",      "REAL"),
    ("daily_snapshots_pit", "pead_drift_60d",             "REAL"),
    ("daily_snapshots_pit", "corporate_action_density",   "REAL"),
    ("daily_snapshots_pit", "buyback_announcement_30d",   "REAL"),
    # 2026-07-05: §3.2.5 — announcement-window CAR (market-implied earnings surprise, PEAD-via-CAR).
    ("daily_snapshots_pit", "announcement_car",           "REAL"),
    # 2026-06-13: ADR 0042 — BSE governance/forensic resignation event factor.
    ("daily_snapshots_pit", "governance_resignation",     "REAL"),
    # 2026-06-14: Plan 0002 §3.2.4 — earnings-call NLP factors (off nlp_scores).
    ("daily_snapshots_pit", "earnings_call_tone_qoq",     "REAL"),
    ("daily_snapshots_pit", "forward_looking_intensity",  "REAL"),
    ("daily_snapshots_pit", "uncertainty_word_density",   "REAL"),
    # 2026-06-02: Plan 0002 §3.2.6 — industry identity (categorical control).
    ("daily_snapshots_pit", "industry_id",                "INTEGER"),
    # 2026-06-02: Plan 0002 §3.2.7 — per-stock macro betas.
    ("daily_snapshots_pit", "oil_beta",                   "REAL"),
    ("daily_snapshots_pit", "metals_beta",                "REAL"),
    ("daily_snapshots_pit", "inr_beta",                   "REAL"),
    ("daily_snapshots_pit", "gold_beta",                  "REAL"),
    # 2026-06-07: §3.2.7 rate + credit betas (daily India bond-ETF series now
    # available — gsec10_etf 2016, credit_excess_idx 2019; was DATA-BLOCKED).
    ("daily_snapshots_pit", "rate_beta",                  "REAL"),
    ("daily_snapshots_pit", "credit_beta",                "REAL"),
    # 2026-06-03: multibagger funnel — Novy-Marx anchor quality factor.
    ("daily_snapshots_pit", "gross_profitability",        "REAL"),
    # 2026-07-05: audit Factor-F3 — LARGE-tier canonical rebuild candidates.
    ("daily_snapshots_pit", "low_vol_252d",               "REAL"),
    ("daily_snapshots_pit", "st_reversal_21d",            "REAL"),
    ("daily_snapshots_pit", "asset_growth_yoy",           "REAL"),
    # 2026-07-11: plan 0012 C3 — momentum retest hypothesis (WS2.6).
    ("daily_snapshots_pit", "residual_momentum_12_1",     "REAL"),
    # 2026-07-11: plan 0012 C4 — lottery retest hypothesis (WS2.7).
    ("daily_snapshots_pit", "max_lottery_21d",            "REAL"),
    # 2026-06-04: multibagger Phase 2b+ — small-cap EMA regime gate. The screen
    # now selects regime-conditioned pillar weights (quality-heavy ↔ DOWNTREND,
    # growth-heavy ↔ UPTREND, balanced ↔ NEUTRAL), cohort-proven across 3 windows.
    # smallcap_regime stamps the regime at scoring time; regime_favorable=0 when
    # the screen historically underperforms (strong UPTREND / junk rally).
    ("multibagger_scores", "smallcap_regime",   "TEXT"),
    ("multibagger_scores", "regime_favorable",  "INTEGER"),
    # 2026-07-05: title-hash dedup before LLM classification (audit Eff-F2) —
    # same regulatory story arrives via Google News + RBI + PIB + Wayback and
    # was getting classified up to 3x. Lets the classifier reuse a prior
    # verdict for an identical normalized headline instead of re-calling Haiku/Sonnet.
    ("regulatory_events", "title_hash", "TEXT"),
]


def _ensure_columns():
    with get_db() as conn:
        for tbl, col, typ in _COLUMN_MIGRATIONS:
            try:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
    _ensure_pipeline_log_status_check()
    _ensure_quarantine_tables()


# ── Plan 0007 Phase 1: quarantine mirror tables ──
# Each source-fetching table gets a sibling `<table>_quarantine`. The Trust
# Pipeline's gate failures route rejected rows here instead of the live table,
# so forensics + re-instate-as-trusted workflows have schema-correct storage
# (not a JSON blob).
#
# Phase 2+ will write here from each fetcher. Phase 1 just creates the mirrors
# so consumers can `LEFT JOIN <table>_quarantine` from day 1.
#
# Mirror creation by introspection: read source DDL from sqlite_master, rewrite
# the name, drop PK + FK clauses (quarantined rows can duplicate and may have
# invalid SIDs by definition), then ALTER to append 3 forensic-metadata columns.
QUARANTINE_SOURCE_TABLES = [
    "broker_recommendations",
    "forecast_history",
    "analyst_consensus",
    "analyst_consensus_snapshots",
    "consensus_signals",
    "quarterly_income",
    "annual_balance_sheet",
    "annual_cash_flow",
    "banking_metrics",
    "mf_holdings",
    "mf_sector_allocation",
]


def _ensure_quarantine_tables():
    """Ensure `<table>_quarantine` exists for every QUARANTINE_SOURCE_TABLES entry."""
    import re
    with get_db() as conn:
        for source in QUARANTINE_SOURCE_TABLES:
            mirror = f"{source}_quarantine"
            # Already exists?
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (mirror,)
            ).fetchone()
            if row:
                continue
            # Read source DDL
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (source,)
            ).fetchone()
            if not row:
                # Source table doesn't exist yet (e.g. legacy code path). Skip.
                continue
            source_ddl = row[0]
            mirror_ddl = _rewrite_ddl_for_quarantine(source_ddl, source, mirror)
            conn.execute(mirror_ddl)
            # Append 3 forensic-metadata columns (always at the end so source-row
            # offsets stay aligned for blob-copy code paths).
            for col, typ in [
                ("_q_failed_gate", "TEXT"),
                ("_q_reason", "TEXT"),
                ("_q_quarantined_at", "TEXT DEFAULT (datetime('now'))"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE {mirror} ADD COLUMN {col} {typ}")
                except sqlite3.OperationalError:
                    pass


def _rewrite_ddl_for_quarantine(source_ddl: str, source_name: str, mirror_name: str) -> str:
    """Source CREATE TABLE → quarantine CREATE TABLE. Strips PK + FK clauses."""
    import re
    ddl = source_ddl
    # Replace table name (first occurrence after CREATE TABLE)
    ddl = re.sub(
        rf"CREATE TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{re.escape(source_name)}",
        f"CREATE TABLE IF NOT EXISTS {mirror_name}",
        ddl, count=1, flags=re.IGNORECASE,
    )
    # Strip standalone PRIMARY KEY (...) constraints — quarantined rows can
    # duplicate (e.g. same sid quarantined for two different gates same day).
    ddl = re.sub(r",\s*PRIMARY\s+KEY\s*\([^)]+\)", "", ddl, flags=re.IGNORECASE)
    # Strip REFERENCES clauses — quarantined data may include invalid SIDs by
    # definition (a misidentified stock has no FK match in stocks).
    ddl = re.sub(r"\s+REFERENCES\s+\w+\s*\([^)]*\)(\s+ON\s+\w+\s+\w+)*", "", ddl, flags=re.IGNORECASE)
    # Strip per-column UNIQUE constraints for the same reason.
    ddl = re.sub(r"\s+UNIQUE", "", ddl, flags=re.IGNORECASE)
    # Strip NOT NULL on potentially-null fields the quarantine can receive
    # (we don't know which gate filled which columns). Leave only TYPE.
    # Simpler: keep NOT NULL — the writer must populate everything.
    return ddl


def _ensure_pipeline_log_status_check():
    """Widen pipeline_log.status CHECK to include COVERAGE_GAP/COVERAGE_SEVERE.

    Added 2026-05-29: HANDOFF 2026-05-24 #4 introduced these statuses in
    tools/freshness_watchdog._report_coverage() without widening the schema
    constraint, so every daily watchdog run since has crashed with
    `CHECK constraint failed: status IN (...)`. Idempotent — checks the
    live table's CHECK string and only recreates if missing.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='pipeline_log'"
        ).fetchone()
        if not row:
            return
        if "COVERAGE_GAP" in row[0]:
            return
        conn.executescript(
            """
            BEGIN;
            CREATE TABLE pipeline_log__new (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date        TEXT NOT NULL DEFAULT (date('now')),
                step_name       TEXT NOT NULL,
                status          TEXT CHECK(status IN ('RUNNING', 'SUCCESS', 'FAILED', 'SKIPPED', 'COVERAGE_GAP', 'COVERAGE_SEVERE')),
                rows_affected   INTEGER,
                started_at      TEXT DEFAULT (datetime('now')),
                finished_at     TEXT,
                duration_sec    REAL,
                error_message   TEXT
            );
            INSERT INTO pipeline_log__new
                SELECT id, run_date, step_name, status, rows_affected,
                       started_at, finished_at, duration_sec, error_message
                FROM pipeline_log;
            DROP TABLE pipeline_log;
            ALTER TABLE pipeline_log__new RENAME TO pipeline_log;
            CREATE INDEX IF NOT EXISTS idx_pipeline_log_date ON pipeline_log(run_date);
            COMMIT;
            """
        )


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


# ── DuckDB read-replica ──
# Columnar replica at data/alpha_signal.duckdb, rebuilt by tools.duckdb_refresh.
# Use for analytical reads on the tables in DUCKDB_MIRRORED_TABLES. SQLite stays
# the source of truth for writes and for tables not in the mirror list.
DUCK_PATH = PROJECT_ROOT / "data" / "alpha_signal.duckdb"
DUCKDB_MIRRORED_TABLES = frozenset({
    "daily_snapshots_pit",
    "daily_snapshots_pit_v1",
    "pit_ic_by_tier_v1",
    "stock_prices",
    "daily_picks",
    "pick_outcomes",
    "consensus_signals",
})


def read_sql_fast(query, params=None):
    """Drop-in for read_sql() that uses DuckDB when the replica is present.

    Falls back to SQLite if the replica file is missing — keeps callers safe
    during the first run after install / after manual deletion of the file.

    Caller must use DuckDB-compatible SQL: double-quoted identifiers ("col"),
    not SQLite's bracket-quoting ([col]). Caller is responsible for only
    referencing tables in DUCKDB_MIRRORED_TABLES.
    """
    if DUCK_PATH.exists():
        import duckdb
        con = duckdb.connect(str(DUCK_PATH), read_only=True)
        try:
            if params:
                return con.execute(query, params).fetchdf()
            return con.execute(query).fetchdf()
        finally:
            con.close()
    return read_sql(query, params)


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

def _drop_future_dated_rows(df, table_name):
    """Drop rows whose date column parses to a date > today + 2 days.

    +2d (not +7d) tolerates weekend/T+1 NAV publishing lag. The +7d read-side
    tolerance in _table_date_range is unaffected — this only guards writes.
    Checks the first matching DATE_COLS column found on the frame; drop-and-log,
    never raise (audit Data-F9 — future-dated NAV rows broke freshness math).
    """
    date_col = next((c for c in DATE_COLS if c in df.columns), None)
    if date_col is None:
        return df

    parsed = pd.to_datetime(df[date_col], errors="coerce", utc=True, format="mixed")
    upper_bound = pd.Timestamp.utcnow() + pd.Timedelta(days=2)
    future_mask = parsed.notna() & (parsed > upper_bound)
    n = int(future_mask.sum())
    if n > 0:
        print(f"[future-date guard] {table_name}: dropped {n} rows")
        df = df.loc[~future_mask]
    return df


def insert_df(df, table_name, conn=None):
    """
    Insert DataFrame rows. Skips rows that violate UNIQUE/PRIMARY KEY
    constraints (idempotent — safe to re-run).

    Use for append-only tables: insider_trades, bulk_deals, news_articles.
    """
    if df.empty:
        return 0

    df = _drop_future_dated_rows(df, table_name)
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


# ── LLM cost ledger ──
# Every Anthropic call site logs its response.usage here (audit 2026-07-04
# "no LLM spend visibility" gap; prereq for the plan-0014 D2 cost ledger).
# Tokens are the source of truth; est_cost_usd is a convenience estimate from
# the price table below — update prices there when Anthropic changes them.

_LLM_PRICES_PER_MTOK = {
    # model-id prefix → (input $/MTok, output $/MTok), sync list price
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-5":   (3.00, 15.00),
    "claude-haiku-4-5":  (1.00, 5.00),
    "claude-opus":       (5.00, 25.00),
}

_LLM_USAGE_DDL = """
CREATE TABLE IF NOT EXISTS llm_usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    called_at     TEXT NOT NULL DEFAULT (datetime('now')),
    step          TEXT NOT NULL,
    model         TEXT NOT NULL,
    mode          TEXT NOT NULL DEFAULT 'sync',
    n_calls       INTEGER NOT NULL DEFAULT 1,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    est_cost_usd  REAL
)
"""


def _llm_est_cost(model, mode, input_tokens, output_tokens):
    for prefix, (p_in, p_out) in _LLM_PRICES_PER_MTOK.items():
        if str(model).startswith(prefix):
            mult = 0.5 if mode == "batch" else 1.0
            return mult * (input_tokens * p_in + output_tokens * p_out) / 1e6
    return None


def log_llm_usage(step, model, usage, mode="sync", n_calls=1):
    """Record one (or an aggregate of) Anthropic API call(s) in llm_usage.

    `usage` is the SDK response.usage object or any object/dict with
    input_tokens/output_tokens. Telemetry only — never raises, so a ledger
    hiccup can't take down a producer (producers still fail loudly on their
    own output; that rule is untouched).
    """
    try:
        if isinstance(usage, dict):
            inp = int(usage.get("input_tokens", 0) or 0)
            out = int(usage.get("output_tokens", 0) or 0)
        else:
            inp = int(getattr(usage, "input_tokens", 0) or 0)
            out = int(getattr(usage, "output_tokens", 0) or 0)
        with get_db() as conn:
            conn.execute(_LLM_USAGE_DDL)
            conn.execute(
                "INSERT INTO llm_usage (step, model, mode, n_calls, input_tokens, "
                "output_tokens, est_cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (step, str(model), mode, int(n_calls), inp, out,
                 _llm_est_cost(model, mode, inp, out)),
            )
    except Exception as e:
        print(f"  [llm_usage] WARN ledger write failed ({e}) — call not recorded")


_PK_CACHE = {}


def _table_pk(table_name, connection):
    """Return list of PK column names for a table. Cached."""
    if table_name in _PK_CACHE:
        return _PK_CACHE[table_name]
    rows = connection.execute(f"PRAGMA table_info([{table_name}])").fetchall()
    pks = [r[1] for r in rows if r[5] > 0]  # PRAGMA returns (cid, name, type, notnull, dflt, pk)
    _PK_CACHE[table_name] = pks
    return pks


def emit_lineage(records, snapshot_date=None, replace_factor=True):
    """Write per-stock lineage rows to `signal_lineage`.

    Args:
      records:        list of dicts, each with keys:
                        sid (str), factor (str), source_table (str),
                        source_key (dict — serialized to JSON),
                        source_cols (list — optional, serialized to JSON),
                        column_sources (dict — optional, for mixed-source tables),
                        contribution (str — optional)
      snapshot_date:  ISO date; defaults to today
      replace_factor: if True, deletes existing rows for the (factor, snapshot_date)
                      tuple before inserting. Idempotent re-runs.

    Each signal module that participates in lineage calls this once per compute()
    with the records it emitted alongside its own *_signals upsert.

    Records are SKIPPED (not raised on) if `lineage.lineage_active_sids()` is set
    and the record's sid is not in the active universe. That keeps the
    `signal_lineage` table at a manageable size (top-300 SIDs by default).
    """
    if not records:
        return 0

    from datetime import date as _date
    import json as _json
    snapshot = snapshot_date or _date.today().isoformat()

    # Gate by active SID set (default: top-300 from daily_picks)
    try:
        from lineage import lineage_active_sids
        active = lineage_active_sids()
    except Exception:
        active = None
    if active is not None:
        records = [r for r in records if r.get("sid") in active]
        if not records:
            return 0

    rows = []
    factors_seen = set()
    for r in records:
        sid = r.get("sid")
        factor = r.get("factor")
        if not sid or not factor:
            continue
        factors_seen.add(factor)
        key_obj = r.get("source_key") or {}
        cols_obj = r.get("source_cols")
        colsrc_obj = r.get("column_sources")
        rows.append((
            sid, snapshot, factor,
            r.get("source_table"),
            _json.dumps(key_obj, sort_keys=True, separators=(",", ":")),
            _json.dumps(cols_obj, separators=(",", ":")) if cols_obj else None,
            _json.dumps(colsrc_obj, separators=(",", ":")) if colsrc_obj else None,
            r.get("contribution") or "",
        ))

    if not rows:
        return 0

    with get_db() as conn:
        if replace_factor:
            # Wipe prior (factor, snapshot_date) rows for the active SIDs only.
            # Re-running the same signal on the same day rewrites cleanly.
            sids_in_batch = list({row[0] for row in rows})
            placeholders = ",".join("?" * len(sids_in_batch))
            for f in factors_seen:
                conn.execute(
                    f"DELETE FROM signal_lineage WHERE factor=? AND snapshot_date=? "
                    f"AND sid IN ({placeholders})",
                    [f, snapshot] + sids_in_batch,
                )
        cursor = conn.executemany(
            "INSERT OR IGNORE INTO signal_lineage "
            "(sid, snapshot_date, factor, source_table, source_key, "
            "source_cols, column_sources, contribution) "
            "VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        return cursor.rowcount


def _check_frame_units(df, table_name: str, declared_units: dict) -> None:
    """Plan 0007 Phase 4 — heuristic unit-contract assertion at producer boundary.

    For each declared (col, unit) on this table, inspect the frame's value
    range and raise UnitMismatchError if it disagrees with the unit class.
    Heuristic only — many fields legitimately span a wide range — but catches
    the obvious flips (a `pct_100` column populated with 0..1 values, or vice
    versa).
    """
    from validators.unit_contract import UnitMismatchError

    for col, unit in declared_units.items():
        if col not in df.columns:
            continue
        # Drop NaNs for range inspection
        try:
            non_null = df[col].dropna()
        except Exception:
            continue
        if len(non_null) < 5:
            continue   # too few rows for a heuristic
        try:
            mn = float(non_null.min())
            mx = float(non_null.max())
        except (TypeError, ValueError):
            continue   # non-numeric column with a declared numeric unit — skip
        # Heuristics by unit
        if unit == "pct_100":
            # If 95%+ of values are in [-1.5, 1.5], it's almost-certainly ratio_1
            in_ratio = ((non_null >= -1.5) & (non_null <= 1.5)).mean()
            if in_ratio > 0.95 and abs(mx) < 5 and len(non_null) >= 20:
                raise UnitMismatchError(
                    f"{table_name}.{col}: declared 'pct_100' but {in_ratio*100:.0f}% of "
                    f"{len(non_null)} non-null values are in [-1.5, 1.5] (range {mn:.4f}..{mx:.4f}) "
                    f"— looks like ratio_1. Producer using wrong scale?"
                )
        elif unit == "ratio_1":
            # If any value is >5 or <-5, it's almost-certainly pct_100
            if (mx > 5 or mn < -5) and len(non_null) >= 5:
                # Allow up to 5% outliers (sloppy_ratio_1 columns sometimes carry log/z)
                out_of_band = ((non_null > 5) | (non_null < -5)).mean()
                if out_of_band > 0.05:
                    raise UnitMismatchError(
                        f"{table_name}.{col}: declared 'ratio_1' but {out_of_band*100:.0f}% of "
                        f"values are outside [-5, +5] (range {mn:.2f}..{mx:.2f}) — "
                        f"looks like pct_100 or unbounded. Producer using wrong scale?"
                    )
        # Other units (inr_*, days, timestamp_*) — no automatic heuristic;
        # rely on consumer-side assert_unit at read_typed boundaries.


def upsert_df(df, table_name, conn=None):
    """
    Upsert DataFrame rows: INSERT, or UPDATE only the provided columns on PK conflict.

    Uses SQLite's INSERT ... ON CONFLICT(pk) DO UPDATE SET col=excluded.col ...
    so columns NOT in `df` are preserved (unlike INSERT OR REPLACE which nulls them).

    Use for: analyst_consensus, stocks, regime_state, daily_snapshots_pit, signal tables.

    For tables without a declared primary key, falls back to INSERT OR REPLACE
    with a warning — those callers should be migrated.

    Plan 0007 Phase 4 — Gate 5 unit contract assertion. Before write, asserts
    every (table_name, col) registered in lineage.UNIT_CONTRACTS still matches
    the declared unit on the frame's value range. Catches the producer-side
    %-vs-fraction class. Undeclared columns pass through silently; declared
    columns whose value distribution looks wrong raise UnitMismatchError.
    """
    if df.empty:
        return 0

    df = _drop_future_dated_rows(df, table_name)
    if df.empty:
        return 0

    # Gate 5: producer-side unit-contract check
    try:
        from validators.unit_contract import units_for_table, UnitMismatchError
        declared = units_for_table(table_name)
        if declared:
            _check_frame_units(df, table_name, declared)
    except UnitMismatchError:
        raise
    except Exception:
        pass  # Never let unit-check failure break writes for unrelated reasons

    df_cols = list(df.columns)
    cols = ", ".join(f"[{c}]" for c in df_cols)
    placeholders = ", ".join(["?"] * len(df_cols))

    def _execute(connection):
        pk_cols = _table_pk(table_name, connection)
        if not pk_cols:
            # No PK declared — fall back to OR REPLACE (legacy behavior, all-cols expected)
            sql = f"INSERT OR REPLACE INTO [{table_name}] ({cols}) VALUES ({placeholders})"
        else:
            # ON CONFLICT UPDATE clause for non-PK columns present in df
            update_cols = [c for c in df_cols if c not in pk_cols]
            if update_cols:
                set_clause = ", ".join(f"[{c}]=excluded.[{c}]" for c in update_cols)
                conflict_cols = ", ".join(f"[{c}]" for c in pk_cols)
                sql = (
                    f"INSERT INTO [{table_name}] ({cols}) VALUES ({placeholders}) "
                    f"ON CONFLICT({conflict_cols}) DO UPDATE SET {set_clause}"
                )
            else:
                # df contains only PK cols — INSERT OR IGNORE (no-op on conflict)
                sql = f"INSERT OR IGNORE INTO [{table_name}] ({cols}) VALUES ({placeholders})"
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

    # ── Mutual Fund universe (research-only; standalone from stock model) ──
    "mf_scheme_master": {
        "kind": "RAW",
        "depth": "~14,364 active Indian MF schemes (refreshed weekly from AMFI NAVAll.txt)",
        "description": "Authoritative MF universe from AMFI. One row per scheme: code, ISINs, name, AMC, raw + normalised category, plan_type (Direct/Regular), option_type (Growth/IDCW), last_seen, active flag.",
        "consumed_by": "/mutual-funds cockpit page, mf_nav_backfill (selects active+Growth subset)",
    },
    "mf_nav_history": {
        "kind": "RAW",
        "depth": "~13y daily NAV per scheme (mfapi.in backfill) + ongoing daily (AMFI)",
        "description": "Per-scheme NAV time series. PK (scheme_code, nav_date). Bootstrap fills via mfapi.in; daily incremental via AMFI NAVAll.txt.",
        "consumed_by": "mf_metrics, mf_rolling_returns compute; cockpit /mutual-funds/{code} NAV chart",
    },
    "mf_schemes": {
        "kind": "RAW",
        "depth": "Subset of mf_scheme_master with full backfilled history",
        "description": "Compat table from v0 — tracks scheme metadata (inception_date, has_full_history) for schemes we've backfilled via mfapi.in. Functionally a join key with mf_scheme_master.",
        "consumed_by": "mf_nav_backfill (skip already-done), /mutual-funds/{code} detail",
    },
    "mf_metrics": {
        "kind": "COMPUTED",
        "depth": "One row per (scheme_code, as_of_date); recomputed monthly",
        "description": "Per-scheme returns + risk snapshot. 1Y/3Y/5Y/10Y CAGR, Sharpe, Sortino, max drawdown, peer rank, plus composite_score (0-100 within category) with 4-way breakdown (3Y CAGR / Sharpe 3Y / max DD / rolling consistency).",
        "consumed_by": "/mutual-funds universe browser (Score column, sort key), /mutual-funds/{code} detail page",
    },
    "mf_calendar_returns": {
        "kind": "COMPUTED",
        "depth": "Per-scheme per-calendar-year",
        "description": "Yearly returns table for the bar chart on the detail page. PK (scheme_code, year).",
        "consumed_by": "/mutual-funds/{code} Performance tab calendar chart",
    },
    "mf_rolling_returns": {
        "kind": "COMPUTED",
        "depth": "Monthly anchors (~60 per scheme), 3Y + 5Y rolling CAGR each",
        "description": "Rolling 3Y and 5Y CAGR sampled on the first business day of each month, plus a flag for whether the rolling window beat category median. Drives the rolling-returns charts + the consistency component of composite_score.",
        "consumed_by": "/mutual-funds/{code} Performance tab rolling charts; mf_metrics scorer",
    },
    "mf_category_stats": {
        "kind": "COMPUTED",
        "depth": "One row per (category_norm, as_of_date)",
        "description": "Category aggregates — median 1Y/3Y/5Y returns, median Sharpe, top/bottom decile cuts. Powers the heatmap on /mutual-funds and peer-rank comparisons.",
        "consumed_by": "/mutual-funds heatmap, mf_metrics peer ranking",
    },

    # ── Output ──
    "daily_picks": {
        "kind": "COMPUTED",
        "depth": "Latest pick_date snapshot",
        "description": "Daily output of the screener — every stock with its final_score, rank within tier, base_score, and forensic_adj. The ranked universe.",
        "consumed_by": "morning_brief, action_queue, signals page, sectors page",
    },
    "portfolio_weights": {
        "kind": "COMPUTED",
        "depth": "Snapshot per build date (asof_date)",
        "description": "Track 3.3c sized book — HRP risk-parity weights × alpha tilt over the top picks_per_tier names, under per-stock / per-sector / ₹-ADTV liquidity caps. Carries marginal_risk_contrib (percent of portfolio variance per name). ADVISORY only (no capital deployed until rank-skill validates). Built daily after the screener (PIPELINE_STEPS) + backfilled across daily_picks history.",
        "consumed_by": "cockpit /portfolio sized view + portfolio_outcomes (realized-return head-to-head)",
    },
    "portfolio_outcomes": {
        "kind": "COMPUTED",
        "depth": "Per (asof_date, window) — grows as books mature",
        "description": "Track 3.3c realized-return head-to-head: each HRP book's close-to-close return at 20/63/126 trading-day windows under HRP weights vs equal-weight on the same names (the weighting edge) vs a tier-blended NIFTY benchmark. Evidence accumulating toward the §3.3c hard gate (HRP beats current portfolio by ≥1.5% risk-adjusted over 18-24mo). ADVISORY. Reuses tools/compute_pick_outcomes price logic.",
        "consumed_by": "tools/portfolio_outcomes.report() (CLI head-to-head)",
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

    # ── Backtest (PIT) ──
    "daily_snapshots_pit_v1": {
        "kind": "RAW",
        "depth": "35 monthly dates (Apr 2023 → Feb 2026)",
        "description": "Frozen v1 PIT reconstruction — 1,978 stocks × 35 monthly eval dates × 13 signals + precomputed fwd_return_20d. The canonical historical backtest dataset. Source for the C13b t-stats baked into config.SIGNAL_WEIGHTS. Imported via tools/import_v1_pit.py from /home/ubuntu/alpha-signal/data/backtest/reconstructed_signals.csv.",
        "consumed_by": "/model Backtest Roster, future tools/backtest_pit.py",
    },
    "daily_snapshots_pit": {
        "kind": "COMPUTED",
        "depth": "Forward extension (currently 7 monthly dates Nov 2025 → May 2026)",
        "description": "v2 PIT reconstruction extending forward of the v1 archive. Computed by tools/reconstruct_pit.py with proper filing-lag discipline (75d annual / 60d quarterly / 21d shareholding). Adds m_score and z_score (forensic) which v1 lacks. Use for backtests in dates after 2026-02 where v1 stops.",
        "consumed_by": "/model Backtest Roster, future tools/backtest_pit.py",
    },
    "pit_ic_by_tier_v1": {
        "kind": "RAW",
        "depth": "30 rows (10 signals × 3 tiers)",
        "description": "Canonical IC / t-stat / verdict per signal × cap_tier from v1's 36-period validation. Source-of-truth for every weight in config.SIGNAL_WEIGHTS. Read-only; new t-stats from v2 reconstruction will land in a separate pit_ic_by_tier_v2 table.",
        "consumed_by": "/model Validation table, /model Backtest Roster",
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
    "monthly": 50,     # Tickertape monthly pulls land day-1 of month → 31d when cron runs day-2; 50d tolerates a skipped month
    "quarterly": 100,
    "annual": 400,
}

# Per-table overrides for tables whose upstream has known publishing lag.
# Listed by table name; takes precedence over the frequency-based default.
# BEST_EFFORT_STALE — tables whose UPSTREAM SOURCE can legitimately carry no fresh
# data, so persistent staleness is a WARN, never a heal-streak CRITICAL. Re-running
# the producer can't heal them (nothing to fetch), so the freshness watchdog skips the
# heal-rerun and health_report exempts their `watchdog_<table>_heal` step from the
# "failed N consecutive days → CRITICAL" escalation.
#   insider_trades: NSE's corporates-pit endpoint STOPPED serving recent PIT disclosures
#   ~2026-05 (verified 2026-06-22: returns 200 + data for Apr [392 rows] but ~0 for
#   May-onward; the wide Mar-Jun window still has 2452 rows, so it's a recent-data cliff,
#   not a 403/block). The producer runs clean but lands nothing → table frozen at
#   trade_date 2026-05-02. insider_score is NOT wired into SIGNAL_WEIGHTS (zero pick
#   impact). Revisit when a working PIT endpoint is found (NSE site archaeology).
BEST_EFFORT_STALE = {"insider_trades"}

STALENESS_OVERRIDES = {
    # NSE PIT insider disclosures lag the trade by WEEKS (by-trade_date is structurally
    # sparse near today). UPDATE 2026-06-22: beyond the lag, the corporates-pit endpoint
    # itself went stale for recent data (~May 2026 cliff) — insider_trades is now in
    # BEST_EFFORT_STALE so the watchdog won't escalate its unhealable staleness to
    # CRITICAL. 14→30 (2026-05-25), 30→45 (2026-06-04) as the real lag was measured.
    "insider_trades": 45,
    # earnings_calendar is a FORWARD-dated board-meeting calendar; a daily nselib
    # pull keeps near-future events present so MAX(date) sits ahead of today during
    # health. Was a one-off v1-CSV import with no producer (→ 6d stale, cockpit
    # upcoming-events widget empty); wired daily 2026-06-04. 10 flags a genuinely
    # stalled fetcher once the forward buffer drains, without month-edge noise.
    "earnings_calendar": 10,
    # 2026-05-23: regulatory_events was registered as "monthly" (50d) and
    # silently went stale for 43d before being noticed (Gillette dossier
    # showing 2023 articles). News/PIB are weekly cadence at worst; if the
    # harvester stops, we want a yellow flag in <2 weeks, not 50 days.
    "regulatory_events": 14,
    "regulatory_signals": 14,
    # ── Filing-cycle-bound tables (data only moves when companies file) ──
    # Producer runs daily, but `latest_date` is the most recent end_date,
    # which only advances after a fresh filing wave. Threshold is set so
    # the alarm fires only when the EXPECTED next wave has been missed
    # (= a real harvester problem), not on the natural lag inside a wave.
    # 2026-05-25: bumped these from monthly(50)/quarterly(100) defaults
    # after they flagged STALE 55d when the data is healthy.
    "quarterly_income":      120,  # quarterly filings; ~90d max gap, 120 tolerates a delayed wave
    "annual_balance_sheet":  220,  # annual filings; ~12mo max gap, 220 catches a missed cycle in ~7mo
    "annual_cash_flow":      220,
    "forecast_history":      220,  # Tickertape stores PT only at FY year-end → annual cadence
    # 2026-06-01: index history is trading-days only; a Fri close read on Mon
    # is ~3d old, plus nselib's T+1 posting lag → 6 tolerates a long weekend.
    # (Was untracked entirely until fetch_nse_indices became a pipeline step.)
    "nse_index_history":       6,
    # ── Forward-return-window-bound table ──
    # 2026-05-30: pick_outcomes producer runs daily, but `latest_date` =
    # MAX(pick_date) only advances once a pick has a COMPLETED forward
    # return. The table's max is governed by its SHORTEST window.
    # 2026-06-01: dropped the 5d window (noise) → shortest is now 20 trading
    # days ≈ 28 calendar with weekends/holidays, so the prior 14 would flag
    # STALE every day. 35 tolerates the 20d-window lag + a holiday cluster,
    # yet still flags a genuinely stalled producer in ~5wk.
    "pick_outcomes":          35,
    # portfolio_outcomes (Track 3.3c) is governed by the SAME 20d shortest window
    # as pick_outcomes — its MAX(asof_date) is the most recent book that has matured
    # at 20 trading days, so it structurally trails today by ~28-30 calendar days.
    # Mirror the 35 so the daily producer is flagged only when genuinely stalled.
    "portfolio_outcomes":     35,
    # corporate_actions producer runs daily but the freshness anchor is
    # fetched_at (ex_date isn't a _table_date_range candidate), which only
    # advances on a day with a NEW ex-date row. NSE announces something most
    # trading days, but holiday clusters (Diwali, year-end) can go several
    # quiet days. 10d tolerates that yet flags a genuinely stalled fetcher.
    "corporate_actions":      10,
    # F&O EOD grid + its rollup advance only on trading days, fetched the next
    # morning. MAX(trade_date) sits at Friday's session across a weekend (≈3d),
    # and a holiday adjacent to the weekend stretches it to ≈5-6d. 6 tolerates
    # that cluster yet still flags a genuinely stalled fetcher inside a week.
    "fno_bhav":               6,
    "fno_pcr_history":        6,
    "fno_iv_history":         6,
    # ── Standalone-cron tables (registered in RAW_TABLES 2026-06-03) ──
    # analyst_consensus_snapshots: written 1st business day of each month, so age
    # oscillates 0→~33d across a normal month (first-biz-day drift). 40 sits above
    # that ceiling (no month-end false alarm) yet flags a MISSED month by ~day 40
    # (≈1 week into the next month). This is the gap that hid the June 1 cron crash.
    "analyst_consensus_snapshots": 40,
    # FII/DII F&O positioning reports yesterday's settled OI (inherent +1d) and is
    # pulled days_back=3; over a weekend the freshest row is ~3-4d old. 6 tolerates
    # a long weekend + the settlement lag, still flags a stalled run_daily_forward.sh.
    "fii_dii_positioning":     6,
    # FII/DII cash + surveillance snapshots are trading-day rows published EOD; a
    # Friday read on Monday is ~3d, +T+1 publish lag. 5 tolerates that, flags a stall.
    "fii_dii_cash_flow":       5,
    "surveillance_flags":      5,
    # short_selling_data: NSE posts T+1 with occasional multi-day gaps (low-activity
    # days). Wired into run_daily_forward.sh 2026-06-03. 7 tolerates weekend + posting
    # lag + a quiet gap; provisional — tighten after observing the first cron runs.
    "short_selling_data":      7,
    # multibagger_scores: weekly (Sunday) fundamental screen. snapshot_date only
    # advances on the weekly run, so mid-week it's up to ~6d old; 10 tolerates a
    # normal week + a holiday-shifted Sunday, flags a genuinely missed weekly run.
    "multibagger_scores":     10,
    # ── BSE event stream + crosswalk (wired into run_daily_forward.sh 2026-06-13) ──
    # bse_announcements has no business-date column in _table_date_range's candidate
    # list (dt_tm isn't one) → freshness anchors on fetched_at, which advances on any
    # day the --days 7 refresh inserts a NEW filing. The whole-BSE firehose files most
    # calendar days, but a weekend + adjacent holiday can go quiet; 5 tolerates that,
    # still flags a genuinely stalled cron within a few days (the 7d window self-heals
    # a single missed run). scrip_master rebuilds the full map every run (updated_at=now
    # for every row) so its anchor advances daily regardless; 5 tolerates a skipped run.
    "bse_announcements":       5,
    "scrip_master":            5,
    # fundamentals_screener: manual Screener.in Premium pull, roughly fortnightly.
    # 21d gives one missed cycle before alarm. Auth broken 2026-07-01 — the alarm
    # firing daily until Amit repairs it is intended (audit Data-F2).
    "fundamentals_screener":  21,
    # uhs_calibration_log rows mature on a 20d forward window (pick_outcomes join),
    # so MAX(date) is structurally ~1 month old even when the producer is healthy.
    # 45d tolerates that lag and only alarms on true death (audit Data-F5).
    "uhs_calibration_log":    45,
    # DuckDB replica rebuilds nightly via run_pipeline.sh's cron tail (non-fatal
    # on failure). 2d catches a failed/stale rebuild quickly without false-alarming
    # on same-day timing drift (audit Data-F10).
    "_file_duckdb_replica":    2,
}

# Per-stock coverage gates. A table that should have a row per universe stock
# (or close to it) flips to COVERAGE_GAP / COVERAGE_SEVERE when too many sids
# are missing. The freshness watchdog logs these — they're typically structural
# (harvester filter dropping a series, source doesn't cover SME, etc), not
# something the next cron tick will fix. Pre-2026-05-23 the entire 22% gap on
# stock_prices was invisible because `MAX(date)` stayed FRESH for the 78% that
# did exist; that's the gap this is closing.
COVERAGE_THRESHOLDS = {
    # table:          (gap_below_pct, severe_below_pct)
    "stock_prices":   (95.0, 80.0),
    "analyst_consensus": (60.0, 30.0),  # sell-side doesn't cover every SMALL
    # Source (Screener.in) doesn't cover all SME-board smallcaps. Verified
    # 2026-05-25: 100% LARGE + 100% MID; 14.8% of SMALL universe (mostly
    # SME-board) is structurally absent — not a harvester defect. Lowered
    # 90→85 to match reality; severe at 70 still catches a real regression.
    "fundamentals_screener": (85.0, 70.0),
    "annual_balance_sheet":  (85.0, 70.0),
    "quarterly_income":      (85.0, 70.0),
    "promoter_signals":      (90.0, 70.0),
    "piotroski_scores":      (85.0, 70.0),
    "smart_money_scores":    (95.0, 80.0),
}


def _compute_coverage_status(table_name, stock_coverage_pct):
    """Return COVERAGE_OK / COVERAGE_GAP / COVERAGE_SEVERE / None.

    None means the table is not coverage-gated (no per-sid expectation, or no
    entry in COVERAGE_THRESHOLDS). Watchdog ignores None.
    """
    gate = COVERAGE_THRESHOLDS.get(table_name)
    if gate is None or stock_coverage_pct is None:
        return None
    gap_below, severe_below = gate
    if stock_coverage_pct < severe_below:
        return "COVERAGE_SEVERE"
    if stock_coverage_pct < gap_below:
        return "COVERAGE_GAP"
    return "COVERAGE_OK"


def _compute_freshness(latest_date_iso, refresh_freq, table_name=None):
    """Return (status, age_days, threshold_days). status ∈ FRESH/STALE/OUTDATED/NO_DATE_ANCHOR/N/A.

    NO_DATE_ANCHOR (WARN severity, not CRITICAL): the table has a registered
    refresh frequency (so it IS expected to be freshness-tracked) but none of
    DATE_COLS matched a column on it — a blind spot, not a data problem.
    """
    if refresh_freq not in STALENESS_THRESHOLDS:
        return "N/A", None, None
    if not latest_date_iso:
        return "NO_DATE_ANCHOR", None, None
    try:
        from datetime import datetime
        latest = datetime.strptime(latest_date_iso, "%Y-%m-%d").date()
        today = datetime.now().date()
        age = (today - latest).days
        threshold = STALENESS_OVERRIDES.get(table_name) or STALENESS_THRESHOLDS[refresh_freq]
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
    "portfolio_weights": "Output",
    "portfolio_outcomes": "Output",
    "daily_snapshots": "Output",
    "daily_changes": "Output",
    # Backtest (PIT reconstruction)
    "daily_snapshots_pit": "Backtest (PIT)",
    "daily_snapshots_pit_v1": "Backtest (PIT)",
    "pit_ic_by_tier_v1": "Backtest (PIT)",
    # Pipeline / internal
    "pipeline_log": "Pipeline",
    "sqlite_sequence": "Pipeline",
}




# ── Backtest Signal Registry ──
#
# Moved to factors.py (the one factor registry): every factor is one FACTORS
# entry there, and BACKTEST_SIGNALS / BACKTEST_CADENCE / FACTOR_LIBRARY are
# derived views of it. Re-exported here so `from db import BACKTEST_SIGNALS`
# (cockpit_ops, lineage, factor_correlation, …) keeps working.
from factors import (  # noqa: E402,F401  (re-exports)
    BACKTEST_CADENCE,
    BACKTEST_SIGNALS,
    FACTOR_LIBRARY,
    get_backtest_cadence,
)


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
    "Backtest (PIT)",
    "Pipeline",
    "Other",
]


_data_health_lock = threading.Lock()
_data_health_memo = {"value": None, "ts": 0.0}


def data_health(cache_ttl=0):
    """
    Comprehensive data health report. Merges DB row counts with pipeline-step
    metadata from config.PIPELINE_STEPS + config.RAW_TABLES, per-table
    descriptions, date spans, freshness benchmark, and dynamic lineage from
    scanning the codebase.

    Returns DataFrame with: table, rows, kind, depth, description, source,
    frequency, earliest_date, latest_date, date_span, freshness, age_days,
    threshold_days, produced_by, consumed_by, status.

    cache_ttl > 0 returns an in-process memoized result if the last full scan
    was within `cache_ttl` seconds — shared across callers, lock-guarded so
    concurrent callers compute it exactly once. Default 0 = always recompute.
    The /system page sets cache_ttl so the freshness scan (~7s) isn't run twice
    per cold load (get_data_freshness + health_report._gather_tables). Keep it 0
    for freshness_watchdog's compute→heal→re-verify loop, which needs live counts.
    """
    if cache_ttl and cache_ttl > 0:
        now = _time_module.time()
        with _data_health_lock:
            m = _data_health_memo
            if m["value"] is not None and (now - m["ts"]) < cache_ttl:
                return m["value"]
            df = _data_health_impl()
            m["value"], m["ts"] = df, now
            return df
    return _data_health_impl()


def _data_health_impl():
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
        freshness, age_days, threshold_days = _compute_freshness(latest, m.get("frequency"), tbl)

        # Per-sid coverage gate (independent of freshness). MAX(date) stays
        # fresh as long as any one stock pushed a row today — coverage_status
        # catches the case where 20% of the universe is silently missing.
        coverage_status = _compute_coverage_status(tbl, stock_coverage_pct)

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
            "coverage_status": coverage_status,
            "status": status,
        })

    # ── File-based outputs (virtual tables) ────────────────────────────────
    # Brings dossier JSONs and similar disk artifacts under the same
    # freshness lens as DB tables. The freshness watchdog reads this row
    # set directly, so file outputs get monitored "for free".
    try:
        from config import FILE_OUTPUTS
    except ImportError:
        FILE_OUTPUTS = []
    for fo in FILE_OUTPUTS:
        latest_iso, rows_count = _file_output_state(fo)
        freshness, age_days, threshold_days = _compute_freshness(
            latest_iso, fo.get("frequency"), fo["virtual_table"]
        )
        status = "OK" if rows_count > 0 else "EMPTY"
        rows.append({
            "table":             fo["virtual_table"],
            "domain":            "Output",
            "rows":              rows_count,
            "kind":              "file",
            "depth":             "—",
            "description":       fo.get("source", "—"),
            "produced_by":       fo.get("producer", "—"),
            "consumed_by":       "(cockpit UI)",
            "consumed_count":    1,
            "source":            fo.get("source", "—"),
            "data_freq":         fo.get("data_freq", "—"),
            "frequency":         fo.get("frequency", "—"),
            "earliest_date":     None,
            "latest_date":       latest_iso,
            "date_span":         None,
            "freshness":         freshness,
            "age_days":          age_days,
            "threshold_days":    threshold_days,
            "stock_count":       None,
            "stock_coverage_pct": None,
            "stock_coverage":    "—",
            "coverage_status":   None,
            "status":            status,
        })

    return pd.DataFrame(rows)


def _file_output_state(fo):
    """Return (latest_iso, n_records_with_freshness_field) for a file output.

    The freshness anchor is the newest file matching the glob *that contains*
    at least one record whose freshness_field is present. A file full of
    placeholders (status: no_api_key) doesn't count — that's the whole point.

    Entries with no freshness_field are non-JSON binary outputs (e.g. the
    DuckDB replica) — anchor on the newest file's mtime instead of parsing it.
    """
    pattern = str(PROJECT_ROOT / fo["glob"])
    files = sorted(glob.glob(pattern), reverse=True)
    freshness_field = fo.get("freshness_field")
    if freshness_field is None:
        if not files:
            return None, 0
        f = files[0]
        from datetime import datetime as _dt
        ts = _dt.fromtimestamp(Path(f).stat().st_mtime).date()
        return ts.isoformat(), (1 if Path(f).stat().st_size > 0 else 0)
    for f in files:
        try:
            with open(f) as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, IOError):
            continue
        if not isinstance(data, list):
            data = [data]
        if freshness_field:
            real = [d for d in data if isinstance(d, dict) and d.get(freshness_field)]
            if not real:
                continue
            n = len(real)
        else:
            n = len(data)
        # Date from filename if it follows the dossiers_YYYY-MM-DD.json pattern,
        # else fall back to mtime.
        from datetime import datetime as _dt
        m = re.search(r"(\d{4}-\d{2}-\d{2})", Path(f).name)
        if m:
            return m.group(1), n
        ts = _dt.fromtimestamp(Path(f).stat().st_mtime).date()
        return ts.isoformat(), n
    return None, 0


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
