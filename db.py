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
    "monthly": 50,     # Tickertape monthly pulls land day-1 of month → 31d when cron runs day-2; 50d tolerates a skipped month
    "quarterly": 100,
    "annual": 400,
}

# Per-table overrides for tables whose upstream has known publishing lag.
# Listed by table name; takes precedence over the frequency-based default.
STALENESS_OVERRIDES = {
    # NSE PIT filings post with delay AND many stocks have weeks-long quiet
    # stretches. Bumped 14→30 (2026-05-25) after producer ran daily but
    # MAX(trade_date) stayed flat because no fresh insider trades were filed.
    "insider_trades": 30,
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
    # ── Forward-return-window-bound table ──
    # 2026-05-30: pick_outcomes producer runs daily, but `latest_date` =
    # MAX(pick_date) only advances once a pick has a COMPLETED forward
    # return. The table's max is governed by its shortest window (5 trading
    # days ≈ 7-10 calendar with weekends/holidays), so the daily(3) default
    # flagged STALE every single day and the watchdog heal step FAILED daily
    # trying to "fix" a structural lag. 14 tolerates the 5d-window lag + a
    # holiday cluster, yet still flags a genuinely stalled producer in <2wk.
    "pick_outcomes":          14,
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
    """Return (status, age_days, threshold_days). status ∈ FRESH/STALE/OUTDATED/N/A."""
    if not latest_date_iso or refresh_freq not in STALENESS_THRESHOLDS:
        return "N/A", None, None
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
# Signal-level view of the backtest universe. Cross-referenced against v1's
# full factor inventory (scripts/03_screener.py + signal_validation_by_tier.csv +
# reconstructed_signals.csv) so even DROP-verdict signals stay in the registry —
# economic regimes shift; today's noise can be tomorrow's alpha. We compute and
# store everything; we just don't *weight* the dropped ones.
#
# `status` taxonomy (5 levels, in order of readiness):
#   READY    — signal values are in a PIT table; backtest can run today
#   PARTIAL  — in PIT but with known caveat (data divergence, sparse coverage,
#              missing in one source — usable with documented limit)
#   MISSING  — signal NOT in any PIT table, but raw data exists; reconstruction
#              is additive engineering effort (no data gap blocks it)
#   PROPOSED — factor exists in v1's inventory; raw data exists in v2 to compute
#              it but no v2 module has been written yet (clear next deliverable)
#   BLOCKED  — raw data fundamentally insufficient (e.g. NSE bulk_deals has no
#              historical archive). Forward-only or wontfix without new source.
#
# IC / t-stat / verdict come from pit_ic_by_tier_v1 at runtime — no hardcoding.

# ─────────────────────────────────────────────────────────────────────────
# Backtest cadence per signal — 2026-05-24.
#
# Pre-2026-05-24: ALL signals were backtested at v1's monthly cadence (35 dates).
# That handicapped fast-decay signals (sentiment_7d, insider_signal, etc.) which
# would have hundreds of weekly observations but only ~24 monthly ones, giving
# misleadingly weak t-stats.
#
# Cadence taxonomy:
#   "monthly"          — slow-moving fundamentals/momentum/shareholding/analyst.
#                        Matches v1 C13b framework. ~42 v1+v2 monthly dates.
#                        Forward return: fwd_return_20d. No Newey-West.
#   "weekly"           — behavioral, event-driven, news, daily-published.
#                        Eval each Friday. Forward return: fwd_return_5d (or 20d).
#                        Newey-West required if signal-window > eval-gap.
#   "sector_portfolio" — sector-level signals (regulatory_sector, macro_sector).
#                        Not per-stock; need sector-tilt portfolio test, not IC.
#   "portfolio"        — end-state composite (screener_final). Track 2.4
#                        portfolio backtest, not factor IC.
#
# Use get_backtest_cadence(signal_id) — falls back to "monthly" for unknown ids.
BACKTEST_CADENCE = {
    # ── Weekly: behavioral / event-driven / news ──
    "insider_signal":           "weekly",
    "avg_delivery_pct_30d":     "weekly",
    "delivery_anomaly_z":       "weekly",
    "bulk_deal_signal":         "weekly",
    "short_selling_signal":     "weekly",
    "sentiment_7d":             "weekly",
    "news_volume":              "weekly",
    "fii_dii_cash_net":         "weekly",
    "fii_dii_fno_positioning":  "weekly",
    # ── Weekly: options/F&O OI factors (§3.2.2) — daily-flow, fast-decay ──
    "pcr_oi":                   "weekly",
    "pcr_volume":               "weekly",
    "max_pain_distance":        "weekly",
    "oi_buildup_signal":        "weekly",
    "iv_skew_25d":              "weekly",
    "iv_term_structure":        "weekly",
    "iv_realised_spread":       "weekly",
    "iv_percentile_1y":         "weekly",
    # ── Sector-portfolio: sector-level signals (not per-stock IC) ──
    "regulatory_sector_signal": "sector_portfolio",
    "macro_sector_signal":      "sector_portfolio",
    # ── Portfolio: end-state composite (backtest via Track 2.4) ──
    "screener_final_composite": "portfolio",
    # All other signals default to "monthly" — see get_backtest_cadence().
}


def get_backtest_cadence(signal_id):
    """Return cadence label for a signal. Defaults to 'monthly' for unknown ids
    (the safe default — monthly cadence works for all current signals even if
    sub-optimal for fast-decay ones)."""
    return BACKTEST_CADENCE.get(signal_id, "monthly")


BACKTEST_SIGNALS = [

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 1 — VALUE
    # ═══════════════════════════════════════════════════════════════════

    {
        "signal": "earnings_yield",
        "label": "Earnings Yield (TTM E/P)",
        "group": "Value",
        "description": "Trailing 12-month EPS / current price",
        "source_tables": ["quarterly_income", "stock_prices"],
        "source_columns": ["qi.eps", "stock_prices.close"],
        "filing_lag": "60d quarterly + 0d price",
        "pit_column_v1": "earnings_yield",
        "pit_column_v2": "earnings_yield",
        "v1_verdict_summary": "DROP / DROP / KEEP (t=3.13 SMALL)",
        "status": "READY",
        "status_reason": "",
    },
    {
        "signal": "book_to_price",
        "label": "Book-to-Price",
        "group": "Value",
        "description": "Per-share book equity / price",
        "source_tables": ["annual_balance_sheet", "stock_prices"],
        "source_columns": ["bs.total_equity", "bs.shares_outstanding", "stock_prices.close"],
        "filing_lag": "75d annual + 0d price",
        "pit_column_v1": "book_to_price",
        "pit_column_v2": "book_to_price",
        "v1_verdict_summary": "DROP / WEAK / KEEP (t=2.54 SMALL)",
        "status": "READY",
        "status_reason": "",
    },
    {
        "signal": "position_52w",
        "label": "52-Week Range Position",
        "group": "Value",
        "description": "(close − 52w_low) / (52w_high − 52w_low) — proximity to lows is value-positive",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.close (rolling 252d high/low)"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "position_52w",
        "v1_verdict_summary": "(used as 25% of value composite, not separately validated)",
        "status": "READY",
        "status_reason": "",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 2 — QUALITY (profitability + leverage + efficiency)
    # ═══════════════════════════════════════════════════════════════════

    {
        "signal": "piotroski_f_score",
        "label": "Piotroski F-Score",
        "group": "Quality",
        "description": "9-factor profitability + leverage + efficiency score (0-9)",
        "source_tables": ["quarterly_income", "annual_balance_sheet", "annual_cash_flow"],
        "source_columns": ["qi.{eps,net_income,revenue}", "bs.{total_assets,equity,debt,shares_outstanding}", "cf.operating_cash_flow"],
        "filing_lag": "75d annual + 60d quarterly",
        "pit_column_v1": "piotroski_f",
        "pit_column_v2": "piotroski_f",
        "v1_verdict_summary": "DROP / WEAK / KEEP (t=2.81 SMALL)",
        "status": "READY",
        "status_reason": "",
    },
    {
        "signal": "cf_accruals_ratio",
        "label": "CF Accruals (Sloan)",
        "group": "Quality",
        "description": "(Net income − operating CF) / total assets — earnings backed by cash",
        "source_tables": ["quarterly_income", "annual_cash_flow", "annual_balance_sheet"],
        "source_columns": ["qi.net_income", "cf.operating_cash_flow", "bs.total_assets"],
        "filing_lag": "75d annual + 60d quarterly",
        "pit_column_v1": "cf_accruals",
        "pit_column_v2": "cf_accruals",
        "v1_verdict_summary": "DROP / KEEP / WEAK (t=3.20 MID)",
        "status": "READY",
        "status_reason": "",
    },
    {
        "signal": "bs_accruals_ratio",
        "label": "BS Accruals",
        "group": "Quality",
        "description": "ΔWorking capital − capex − depreciation, scaled by assets",
        "source_tables": ["annual_balance_sheet", "annual_cash_flow"],
        "source_columns": ["bs.{current_assets,liabilities,cash}", "cf.{capex,depreciation}"],
        "filing_lag": "75d annual",
        "pit_column_v1": "bs_accruals",
        "pit_column_v2": "bs_accruals",
        "v1_verdict_summary": "DROP / DROP / DROP",
        "status": "READY",
        "status_reason": "Kept despite DROP — regimes change",
    },
    {
        "signal": "earnings_persistence",
        "label": "Earnings Persistence (EPS CV)",
        "group": "Quality",
        "description": "Coefficient of variation of trailing-8-quarter EPS — lower = more persistent",
        "source_tables": ["quarterly_income"],
        "source_columns": ["qi.eps"],
        "filing_lag": "60d quarterly",
        "pit_column_v1": "eps_cv",
        "pit_column_v2": "earnings_persistence",
        "v1_verdict_summary": "(diagnostic, sparse coverage)",
        "status": "READY",
        "status_reason": "",
    },
    {
        "signal": "earnings_beat_rate",
        "label": "Earnings Beat Rate",
        "group": "Quality",
        "description": "Fraction of last-N quarters where actual EPS beat consensus (proxy: vs prev-quarter run-rate)",
        "source_tables": ["quarterly_income"],
        "source_columns": ["qi.eps"],
        "filing_lag": "60d quarterly",
        "pit_column_v1": "earnings_beat_rate",
        "pit_column_v2": "earnings_beat_rate",
        "v1_verdict_summary": "(diagnostic, used inside accruals composite)",
        "status": "READY",
        "status_reason": "v2 reconstruction now writes column. Proxy: fraction of last 8 quarters with positive QoQ EPS growth (v1 used vs-consensus; we lack consensus per quarter). 2,161-2,221 stocks populated across all 7 snapshot dates.",
    },
    {
        "signal": "roe",
        "label": "Return on Equity",
        "group": "Quality",
        "description": "Net income / total equity (TTM)",
        "source_tables": ["quarterly_income", "annual_balance_sheet"],
        "source_columns": ["qi.net_income (TTM)", "bs.total_equity"],
        "filing_lag": "75d annual + 60d quarterly",
        "pit_column_v1": None,
        "pit_column_v2": "roe",
        "v1_verdict_summary": "(45% of quality composite — quality_recon: DROP all tiers)",
        "status": "READY",
        "status_reason": "Negative-equity stocks → NaN (D/E meaningless there).",
    },
    {
        "signal": "roa",
        "label": "Return on Assets",
        "group": "Quality",
        "description": "Net income / total assets (TTM)",
        "source_tables": ["quarterly_income", "annual_balance_sheet"],
        "source_columns": ["qi.net_income (TTM)", "bs.total_assets"],
        "filing_lag": "75d annual + 60d quarterly",
        "pit_column_v1": None,
        "pit_column_v2": "roa",
        "v1_verdict_summary": "(component of Track 2.2 financial sub-model; not in main C13b)",
        "status": "READY",
        "status_reason": "",
    },
    {
        "signal": "debt_to_equity",
        "label": "Debt-to-Equity",
        "group": "Quality",
        "description": "Total debt / total equity (lower better; financial sector excluded)",
        "source_tables": ["annual_balance_sheet"],
        "source_columns": ["bs.total_debt", "bs.total_equity"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "debt_to_equity",
        "v1_verdict_summary": "(30% of quality composite)",
        "status": "READY",
        "status_reason": "Financial sector NaN'd (D/E meaningless for banks).",
    },
    {
        "signal": "profit_margin",
        "label": "Profit Margin",
        "group": "Quality",
        "description": "Net income / revenue (TTM)",
        "source_tables": ["quarterly_income"],
        "source_columns": ["qi.net_income", "qi.revenue"],
        "filing_lag": "60d quarterly",
        "pit_column_v1": None,
        "pit_column_v2": "profit_margin",
        "v1_verdict_summary": "(25% of quality composite)",
        "status": "READY",
        "status_reason": "",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 3 — GROWTH
    # ═══════════════════════════════════════════════════════════════════

    {
        "signal": "revenue_growth_yoy",
        "label": "Revenue YoY Growth",
        "group": "Growth",
        "description": "Trailing 4Q revenue / prior 4Q revenue − 1",
        "source_tables": ["quarterly_income"],
        "source_columns": ["qi.revenue (8 quarters)"],
        "filing_lag": "60d quarterly",
        "pit_column_v1": None,
        "pit_column_v2": "revenue_growth_yoy",
        "v1_verdict_summary": "growth_recon: DROP all tiers (n=16)",
        "status": "READY",
        "status_reason": "Kept despite v1 DROP — regimes change.",
    },
    {
        "signal": "eps_growth_yoy",
        "label": "EPS YoY Growth",
        "group": "Growth",
        "description": "Trailing 4Q EPS / prior 4Q EPS − 1",
        "source_tables": ["quarterly_income"],
        "source_columns": ["qi.eps (8 quarters)"],
        "filing_lag": "60d quarterly",
        "pit_column_v1": None,
        "pit_column_v2": "eps_growth_yoy",
        "v1_verdict_summary": "growth_recon: DROP all tiers",
        "status": "READY",
        "status_reason": "Kept despite v1 DROP. Tiny base EPS produces high noise — clipped to ±1000% range.",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 4 — MOMENTUM
    # ═══════════════════════════════════════════════════════════════════

    {
        "signal": "mom_6m_adj",
        "label": "Risk-Adj 6M Momentum",
        "group": "Momentum",
        "description": "6-month return / 6-month daily-return std, with 22-day skip window",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.close"],
        "filing_lag": "0d",
        "pit_column_v1": "mom_6m",
        "pit_column_v2": "mom_6m",
        "v1_verdict_summary": "DROP / DROP / WEAK (t=1.32 SMALL)",
        "status": "READY",
        "status_reason": "v2 uses PIT-strict corporate-action-adjusted close: corporate_adjustments table holds 3,036 (sid, ex_date) factors covering SPLIT+BONUS+DIVIDEND; tools.reconstruct_pit.apply_pit_adjustments composes only events with ex_date <= snapshot_date. Apples-to-apples 12-date diagnostic: raw close 0.745 → PIT-adj 0.862 mean Pearson vs v1 archive (+0.117 lift). v1 is forward-adjusted via yfinance (mildly leaky); v2 is non-leaky and canonical going forward.",
    },
    {
        "signal": "mom_12m_adj",
        "label": "Risk-Adj 12M Momentum",
        "group": "Momentum",
        "description": "12-month return / 12-month daily-return std, with 22-day skip",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.close"],
        "filing_lag": "0d",
        "pit_column_v1": "mom_12m",
        "pit_column_v2": "mom_12m",
        "v1_verdict_summary": "WEAK / DROP / WEAK (t=−1.64 LARGE, 1.76 SMALL)",
        "status": "READY",
        "status_reason": "Same PIT-strict adjustment as mom_6m_adj. 12-date apples-to-apples Pearson lift +0.116; pooled v1↔v2 Pearson 0.71 / Spearman 0.87 (essentially identical to forward-adjusted-splits-only — leakage in v1 is small in practice; correctness benefit is architectural).",
    },
    {
        "signal": "macd_signal",
        "label": "MACD Bullish Crossover",
        "group": "Momentum",
        "description": "12/26 EMA crossover state — binary signal from price",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.close (252d)"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "macd_bullish",
        "v1_verdict_summary": "(technical — used in v1 screener but not in C13b validation)",
        "status": "READY",
        "status_reason": "",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 5 — OWNERSHIP / INSIDER
    # ═══════════════════════════════════════════════════════════════════

    {
        "signal": "promoter_qoq",
        "label": "Promoter QoQ Change",
        "group": "Ownership",
        "description": "Quarter-over-quarter change in promoter holding %",
        "source_tables": ["shareholding"],
        "source_columns": ["shareholding.promoter_pct"],
        "filing_lag": "21d",
        "pit_column_v1": "promoter_qoq",
        "pit_column_v2": "promoter_qoq",
        "v1_verdict_summary": "DROP / DROP / KEEP (t=3.20 SMALL)",
        "status": "READY",
        "status_reason": "Diagnostic 2026-05-04: median |v1-v2 diff|=0.000 across 1,896 overlap stocks; when both >0.05 abs, **sign-match=97.4%**. The 0.55 raw correlation was scatter-dominated (most stocks have 0 change, agree trivially); for ranking purposes the signal is directionally sound. Backtest reproduces v1's t=3.20 SMALL exactly (validated 2026-05-03).",
    },
    {
        "signal": "promoter_trend_4q",
        "label": "Promoter 1-Year Trend",
        "group": "Ownership",
        "description": "Latest promoter % minus value 5 quarters ago",
        "source_tables": ["shareholding"],
        "source_columns": ["shareholding.promoter_pct (5 quarters)"],
        "filing_lag": "21d",
        "pit_column_v1": None,
        "pit_column_v2": "promoter_trend_4q",
        "v1_verdict_summary": "(35% of promoter composite, not separately validated)",
        "status": "READY",
        "status_reason": "",
    },
    {
        "signal": "pledge_quality",
        "label": "Pledge Quality",
        "group": "Ownership",
        "description": "1 − (promoter pledge %) — higher better",
        "source_tables": ["shareholding"],
        "source_columns": ["shareholding.pledge_pct"],
        "filing_lag": "21d",
        "pit_column_v1": "pledge_quality",
        "pit_column_v2": "pledge_quality",
        "v1_verdict_summary": "DROP all tiers",
        "status": "READY",
        "status_reason": "Now in both v1 archive and v2 recompute. Kept despite DROP — regimes change.",
    },
    {
        "signal": "insider_signal",
        "label": "Insider Trading Signal",
        "group": "Ownership",
        "description": "Promoter/KMP buy-vs-sell over trailing 90 days",
        "source_tables": ["insider_trades"],
        "source_columns": ["insider_trades.{person_category, transaction_type, value_lakhs, trade_date}"],
        "filing_lag": "0d (NSE PIT discloses on transaction)",
        "pit_column_v1": None,
        "pit_column_v2": "insider_score",  # PIT helper added 2026-05-24
        "external_table": "insider_signals",
        "v1_verdict_summary": "(not in C13b; new in v2)",
        "status": "READY",
        "status_reason": "Lives in insider_signals table — 29 monthly snapshots. Join on (sid, snapshot_date).",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 6 — FORENSIC
    # ═══════════════════════════════════════════════════════════════════

    {
        "signal": "m_score",
        "label": "Beneish M-Score",
        "group": "Forensic",
        "description": "Earnings manipulation detector (6-factor reduced model)",
        "source_tables": ["quarterly_income", "annual_balance_sheet", "annual_cash_flow"],
        "source_columns": ["qi.revenue", "bs.{receivables,current_assets,total_assets}", "cf.depreciation"],
        "filing_lag": "75d annual + 60d quarterly",
        "pit_column_v1": None,
        "pit_column_v2": "m_score",
        "v1_verdict_summary": "(not in C13b; new in v2)",
        "status": "READY",
        "status_reason": "Computed forward-only (n=7 months, 13,922 rows in daily_snapshots_pit). Backtest n grows monthly with cron. Signal is correct; only the C13b-grade t-stat needs n≥18.",
    },
    {
        "signal": "z_score",
        "label": "Altman Z'' (emerging market)",
        "group": "Forensic",
        "description": "Bankruptcy predictor, 4-factor emerging-market variant",
        "source_tables": ["annual_balance_sheet", "annual_cash_flow"],
        "source_columns": ["bs.{current_assets,liabilities,retained_earnings,total_assets}", "cf.operating_cash_flow"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "z_score",
        "v1_verdict_summary": "(not in C13b; new in v2)",
        "status": "READY",
        "status_reason": "Computed forward-only (n=7 months, 15,504 rows). Backtest n grows monthly. Signal is correct; only C13b-grade t-stat needs n≥18.",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 7 — SMART MONEY
    # ═══════════════════════════════════════════════════════════════════

    {
        "signal": "avg_delivery_pct_30d",
        "label": "30-Day Avg Delivery %",
        "group": "Smart Money",
        "description": "Mean delivery percentage over trailing 30 days",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.delivery_pct"],
        "filing_lag": "0d",
        "pit_column_v1": "avg_delivery_pct_30d",
        "pit_column_v2": "avg_delivery_pct_30d",
        "v1_verdict_summary": "DROP / DROP / WEAK (t=2.49 SMALL)",
        "status": "READY",
        "status_reason": "Now in both archives.",
    },
    {
        "signal": "delivery_anomaly_z",
        "label": "Delivery % Anomaly (z-score)",
        "group": "Smart Money",
        "description": "Today's delivery % vs 90-day mean, normalized",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.delivery_pct (rolling 90d)"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "delivery_anomaly_z",
        "v1_verdict_summary": "(component of v1 smart_money_score)",
        "status": "READY",
        "status_reason": "",
    },
    {
        "signal": "sector_momentum",
        "label": "Sector Momentum (relative strength vs NIFTY)",
        "group": "Momentum",
        "description": "Stock inherits its GICS sector's medium-horizon (≈3m) "
                       "constituent cap-weighted return minus NIFTY 50, z-scored "
                       "across sectors. Classic sector-momentum anomaly.",
        "source_tables": ["stock_prices", "stocks", "macro_history"],
        "source_columns": ["stock_prices.close", "stocks.{sector,market_cap_cr}",
                           "macro_history.nifty50"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "sector_momentum",
        "v1_verdict_summary": "(new — Plan 0006 Phase E, no v1 counterpart)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (Plan 0006 Phase E). Backtest on 29 "
                         "monthly PIT periods: SMALL t=1.88 WEAK (IC +0.016), "
                         "MID t=0.33 DROP, LARGE t=-0.60 DROP. Stays on bench — "
                         "below the 2.0 screener-promotion gate; not wired to "
                         "SIGNAL_WEIGHTS. Also powers the /sectors S/M/L horizon "
                         "badges. Re-test as PIT panel deepens.",
    },
    {
        "signal": "pcr_oi",
        "label": "Put-Call Ratio (Open Interest)",
        "group": "Options/F&O",
        "description": "Nearest-expiry total put OI / total call OI for the F&O "
                       "underlying. High = put-heavy positioning (bearish, or "
                       "contrarian-bullish on excess fear). Sign decided by backtest.",
        "source_tables": ["fno_pcr_history"],
        "source_columns": ["fno_pcr_history.pcr_oi"],
        "filing_lag": "0d (EOD F&O bhavcopy)",
        "pit_column_v1": None,
        "pit_column_v2": "pcr_oi",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 OI half, no v1 counterpart)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2). Backtest on 22 "
                         "weekly PIT periods (NW3): best |t|=0.36 LARGE — DROP all "
                         "tiers. On the bench (FACTOR_LIBRARY). Re-test as the 6mo "
                         "fno_pcr_history window deepens past one regime.",
    },
    {
        "signal": "pcr_volume",
        "label": "Put-Call Ratio (Volume)",
        "group": "Options/F&O",
        "description": "Nearest-expiry total put volume / total call volume — the "
                       "same-day flow analogue of PCR(OI). Sign decided by backtest.",
        "source_tables": ["fno_pcr_history"],
        "source_columns": ["fno_pcr_history.pcr_volume"],
        "filing_lag": "0d (EOD F&O bhavcopy)",
        "pit_column_v1": None,
        "pit_column_v2": "pcr_volume",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 OI half, no v1 counterpart)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2). Backtest on 22 "
                         "weekly PIT periods (NW3): SMALL t=-1.69 WEAK (high put-vol "
                         "→ mild underperformance, sensible sign; CI straddles 0), "
                         "LARGE/MID DROP. Below 2.0 gate — on the bench "
                         "(FACTOR_LIBRARY). Re-test as window deepens.",
    },
    {
        "signal": "max_pain_distance",
        "label": "Max-Pain Distance",
        "group": "Options/F&O",
        "description": "(spot − max_pain_strike) / spot, where max-pain is the "
                       "argmin total-writer-payout strike on the nearest expiry. "
                       "Tests the 'price drifts toward max-pain into expiry' lore.",
        "source_tables": ["fno_pcr_history"],
        "source_columns": ["fno_pcr_history.max_pain_distance"],
        "filing_lag": "0d (EOD F&O bhavcopy)",
        "pit_column_v1": None,
        "pit_column_v2": "max_pain_distance",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 OI half, no v1 counterpart)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2). Backtest on 22 "
                         "weekly PIT periods (NW3): MID t=-1.68 WEAK (spot above "
                         "max-pain → drifts back, sensible mean-reversion sign; CI "
                         "straddles 0), LARGE/SMALL DROP. Below 2.0 gate — on the "
                         "bench (FACTOR_LIBRARY). Re-test as window deepens.",
    },
    {
        "signal": "oi_buildup_signal",
        "label": "OI Buildup Regime",
        "group": "Options/F&O",
        "description": "Four-state score from the same-expiry day-over-day change "
                       "in total OI vs underlying price: long buildup +1 / short "
                       "covering +0.5 / long unwinding −0.5 / short buildup −1. "
                       "Δ taken only within one expiry series (roll-safe).",
        "source_tables": ["fno_pcr_history"],
        "source_columns": ["fno_pcr_history.{total_call_oi,total_put_oi,underlying_price,expiry_date}"],
        "filing_lag": "0d (EOD F&O bhavcopy)",
        "pit_column_v1": None,
        "pit_column_v2": "oi_buildup_signal",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 OI half, no v1 counterpart)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2). Backtest on 22 "
                         "weekly PIT periods (NW3): best |t|=0.45 MID — DROP all "
                         "tiers (4-state Δ is noisy at weekly cadence). On the bench "
                         "(FACTOR_LIBRARY). Re-test as window deepens.",
    },
    {
        "signal": "iv_skew_25d",
        "label": "IV Skew (25Δ put − call)",
        "group": "Options/F&O",
        "description": "iv(25-delta put) − iv(25-delta call) on the ~30d expiry, from "
                       "Black-76 inversion of fno_bhav settle prices. Positive = "
                       "downside protection bid up (fear). Sign decided by backtest.",
        "source_tables": ["fno_iv_history"],
        "source_columns": ["fno_iv_history.iv_skew_25d"],
        "filing_lag": "0d (EOD F&O bhavcopy)",
        "pit_column_v1": None,
        "pit_column_v2": "iv_skew_25d",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 IV half, no v1 counterpart)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2 IV half, ADR 0035). "
                         "Backtest 25 weekly periods (NW3): MID t=+4.61 KEEP (IC "
                         "+0.096, bootstrap CI [2.28, 9.84] strictly >0 — the standout "
                         "F&O factor; high put-skew → MID outperformance), LARGE/SMALL "
                         "DROP. ~97% coverage. CANDIDATE for deliberate promotion "
                         "(signal-weights.md) — not yet wired; single ~6mo regime, "
                         "wants walk-forward OOS first.",
    },
    {
        "signal": "iv_term_structure",
        "label": "IV Term Structure (near − far)",
        "group": "Options/F&O",
        "description": "ATM IV(nearest ≥5d expiry) − ATM IV(next month). Positive = "
                       "inverted/backwardated curve (near-term stress). NOTE: thin "
                       "single-stock coverage (~20%) — next-month stock options are "
                       "illiquid; really an index-level signal.",
        "source_tables": ["fno_iv_history"],
        "source_columns": ["fno_iv_history.iv_term_structure"],
        "filing_lag": "0d (EOD F&O bhavcopy)",
        "pit_column_v1": None,
        "pit_column_v2": "iv_term_structure",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 IV half, no v1 counterpart)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2 IV half, ADR 0035). "
                         "Backtest (NW3): MID t=-1.80 WEAK (17 periods). SMALL 'KEEP' "
                         "t=-4.94 is a 7-period/23-stock SMALL-SAMPLE ARTIFACT (CI "
                         "[-32.7,-3.1]) — NOT trusted, NOT promoted. ~20% stock "
                         "coverage (far-month liquidity gap; index-level signal at "
                         "heart). Bench (FACTOR_LIBRARY).",
    },
    {
        "signal": "iv_realised_spread",
        "label": "IV − Realised Vol Spread",
        "group": "Options/F&O",
        "description": "ATM IV − 21d annualised realised vol — the variance risk "
                       "premium. Positive = options pricing more vol than has been "
                       "realised (rich). Sign decided by backtest.",
        "source_tables": ["fno_iv_history", "stock_prices"],
        "source_columns": ["fno_iv_history.atm_iv", "stock_prices.close (21d)"],
        "filing_lag": "0d (EOD F&O bhavcopy + 0d price)",
        "pit_column_v1": None,
        "pit_column_v2": "iv_realised_spread",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 IV half, no v1 counterpart)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2 IV half, ADR 0035). "
                         "Backtest 25 weekly periods (NW3): MID t=-1.95 WEAK (CI "
                         "[-5.94,-0.31] excludes 0; rich variance premium → MID "
                         "underperformance, sensible sign), LARGE/SMALL DROP. ~99% "
                         "coverage. Bench (FACTOR_LIBRARY).",
    },
    {
        "signal": "iv_percentile_1y",
        "label": "IV Percentile (trailing ≤1y)",
        "group": "Options/F&O",
        "description": "Percentile rank of today's ATM IV within its own trailing "
                       "≤252-day history. High = vol is expensive vs its own recent "
                       "range (mean-reversion / regime). Sign decided by backtest.",
        "source_tables": ["fno_iv_history"],
        "source_columns": ["fno_iv_history.atm_iv (trailing series)"],
        "filing_lag": "0d (EOD F&O bhavcopy)",
        "pit_column_v1": None,
        "pit_column_v2": "iv_percentile_1y",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.2 IV half, no v1 counterpart)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (Track 3.1b → §3.2.2 IV half, ADR 0035). "
                         "Backtest 25 weekly periods (NW3): best LARGE t=1.18 — DROP "
                         "all tiers (IV percentile is a regime/timing read, not a "
                         "cross-sectional stock-picker). fno_bhav backfilled to ~1yr "
                         "so the trailing-1y window is full. Bench (FACTOR_LIBRARY).",
    },
    {
        "signal": "bulk_deal_signal",
        "label": "Bulk/Block Deal Activity",
        "group": "Smart Money",
        "description": "Net bulk-deal value over trailing 30 days, normalized by avg close",
        "source_tables": ["bulk_deals", "stock_prices"],
        "source_columns": ["bulk_deals.{quantity, price, buy_sell, deal_date}"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "bulk_deal_signal",
        "v1_verdict_summary": "(60% weight in v1 smart_money_score)",
        "status": "READY",
        "status_reason": "Backfilled to 12 months via nselib (2025-06 → present, 13,652 deals). Was BLOCKED → PARTIAL → READY after discovering nselib.capital_market.bulk_deal_data with date-range support.",
    },
    {
        "signal": "short_selling_signal",
        "label": "Short-Selling Activity",
        "group": "Smart Money",
        "description": "Reported short-sold quantity over trailing 30 days, normalized by 30d avg volume",
        "source_tables": ["short_selling_data", "stock_prices"],
        "source_columns": ["short_selling_data.{quantity, short_date}"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "short_selling_signal",
        "v1_verdict_summary": "(NEW signal class — not in v1 roster)",
        "status": "READY",
        "status_reason": "PIT signal compute function shipped (pit_short_selling_signal). 432-714 stocks/snapshot populated across 7 dates from 2025-11. Coverage limited to F&O-eligible names (only those have reported short-selling). Backtest n=5 monthly periods so far; will mature with cron.",
    },
    {
        "signal": "fii_dii_cash_net",
        "label": "FII/DII Cash Segment Net Flow",
        "group": "Macro",
        "description": "Daily net institutional buying in cash market (FII + DII separately)",
        "source_tables": ["fii_dii_cash_flow"],
        "source_columns": ["fii_dii_cash_flow.{net_value_cr, category}"],
        "filing_lag": "0d (next-day publication)",
        "pit_column_v1": None,
        "pit_column_v2": None,
        "v1_verdict_summary": "(NEW signal class — sector-agnostic macro tilt)",
        "status": "READY",
        "status_reason": "Macro-level signal (one row per date per category, not per-stock). Consumed by regime/macro overlay, not daily_snapshots_pit. Daily cron at 14:00 UTC accumulating from 2026-05-03 forward. ~22 trading days of history; will be backtest-grade by 2026-08.",
    },
    {
        "signal": "fii_dii_fno_positioning",
        "label": "FII/DII F&O Positioning",
        "group": "Macro",
        "description": "Participant-wise (Client/DII/FII/Pro) Future + Option long/short positioning",
        "source_tables": ["fii_dii_positioning"],
        "source_columns": ["fii_dii_positioning.{future_*, option_*, total_*, client_type}"],
        "filing_lag": "0d (next-day publication)",
        "pit_column_v1": None,
        "pit_column_v2": None,
        "v1_verdict_summary": "(NEW signal class)",
        "status": "READY",
        "status_reason": "Macro-level signal (5 rows/day across Client/DII/FII/Pro/TOTAL). Consumed by regime overlay. 220 rows backfilled (Feb-Apr 2026); accumulating forward via daily cron.",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 8 — CONSENSUS / FORECAST
    # ═══════════════════════════════════════════════════════════════════

    {
        "signal": "pt_upside",
        "label": "Price Target Upside",
        "group": "Consensus",
        "description": "(Latest analyst PT − current price) / current price",
        "source_tables": ["forecast_history", "stock_prices"],
        "source_columns": ["forecast_history.value WHERE metric='price'", "stock_prices.close"],
        "filing_lag": "0d (use forecast.date for knowability)",
        "pit_column_v1": None,
        "pit_column_v2": "pt_upside",
        "v1_verdict_summary": "(component of v1 consensus signal)",
        "status": "READY",
        "status_reason": "Sourced from forecast_history (annual PT snapshots back to 2015), NOT from analyst_consensus (which is snapshot-only).",
    },
    {
        "signal": "pt_revision_yoy",
        "label": "PT Revision YoY",
        "group": "Consensus",
        "description": "(Latest PT / prior-year PT) − 1, from forecast_history.price snapshots",
        "source_tables": ["forecast_history"],
        "source_columns": ["forecast_history.value WHERE metric='price'"],
        "filing_lag": "0d (use forecast.date as knowability)",
        "pit_column_v1": None,
        "pit_column_v2": "pt_revision_yoy",
        "v1_verdict_summary": "(component of v1 consensus signal)",
        "status": "DROPPED",
        "status_reason": "Data contaminated (2026-05-23). forecast_history.metric='price' is current-close masquerading as PT, so YoY computation = 1-year price return, not PT revision. Both production (signals/consensus.py) and PIT (tools/reconstruct_pit.py) now hardcode this to NULL. Rebuild planned from analyst_consensus_snapshots monthly history once ≥12mo accumulate (2027-05).",
    },
    {
        "signal": "eps_revision_yoy",
        "label": "EPS Forecast Revision YoY",
        "group": "Consensus",
        "description": "Year-over-year change in consensus FY EPS estimate",
        "source_tables": ["forecast_history"],
        "source_columns": ["forecast_history.{value, change} WHERE metric='eps'"],
        "filing_lag": "0d (use forecast.date as knowability)",
        "pit_column_v1": None,
        "pit_column_v2": "eps_revision_yoy",
        "v1_verdict_summary": "(component of v1 consensus signal)",
        "status": "READY",
        "status_reason": "Pattern 6. Small-base-EPS stocks produce noise; combined signal mitigates.",
    },
    {
        "signal": "consensus_signal_combined",
        "label": "Consensus (PT + EPS revision)",
        "group": "Consensus",
        "description": "v1's headline consensus signal — was mean of pt_revision_yoy + eps_revision_yoy; now eps_revision_yoy only after pt source contaminated 2026-05-23",
        "source_tables": ["forecast_history"],
        "source_columns": ["forecast_history.{value} WHERE metric='eps'"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "consensus_signal_combined",
        "v1_verdict_summary": "KEEP / WEAK / WEAK (t=3.52 LARGE — proxy validation in v1, included pt component)",
        "status": "DEGRADED",
        "status_reason": "Originally combined pt_revision_yoy + eps_revision_yoy; pt component dropped 2026-05-23 due to data contamination. Now eps_revision_yoy only — t-stat will differ from v1's 3.52 (which had the pt boost). Re-backtest before relying. Restored when pt source rebuilt from analyst_consensus_snapshots (2027-05+).",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 9 — SENTIMENT
    # ═══════════════════════════════════════════════════════════════════

    {
        "signal": "sentiment_7d",
        "label": "News Sentiment (VADER 7d)",
        "group": "Sentiment",
        "description": "Rolling 7-day mean VADER sentiment across articles tagged for the stock",
        "source_tables": ["news_articles", "news_article_stocks"],
        "source_columns": ["news_articles.{title, summary, published_at}", "news_article_stocks.sid"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "sentiment_7d",  # PIT helper added 2026-05-24 (NaN pre-2024-04 — news data starts 2024-04-23)
        "v1_verdict_summary": "(used as adjustment in v1 screener, not in C13b)",
        "status": "READY",
        "status_reason": "PIT helper added 2026-05-24 — VADER on PIT-filtered article text. Output empty for eval dates before news_articles begins (2024-04-23).",
    },
    {
        "signal": "news_volume",
        "label": "News Article Volume (7d)",
        "group": "Sentiment",
        "description": "Count of articles in trailing 7 days — attention proxy",
        "source_tables": ["news_articles", "news_article_stocks"],
        "source_columns": ["news_article_stocks.sid (count)"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "news_volume_7d",
        "v1_verdict_summary": "(diagnostic)",
        "status": "READY",
        "status_reason": "v2 column populated from news_articles ⟕ news_article_stocks. 0 rows for snapshots before news data starts (2024-04 single-day, then continuous from 2026-03). 10-118 stocks/date for 2026-03+. Forward-only — sentiment analysis (sentiment_7d) blocked on FinBERT setup, see plan 0002 Phase A4.",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 10 — SECTOR OVERLAYS (regulatory + macro — sector-level, not stock-level)
    # ═══════════════════════════════════════════════════════════════════

    {
        "signal": "regulatory_sector_signal",
        "label": "Regulatory Sector Tilt",
        "group": "Regulatory",
        "description": "Per-sector aggregate of AI-classified regulatory events with 90-day half-life decay",
        "source_tables": ["regulatory_events", "regulatory_signals"],
        "source_columns": ["regulatory_events.published_at", "regulatory_signals.{direction, magnitude, confidence}"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "macro_sector_signals_pit.regulatory_score",
        "v1_verdict_summary": "(post-v1; Plan 0001)",
        "status": "READY",
        "status_reason": "Sector-level (not stock-level) — written to macro_sector_signals_pit. 11 sectors × 7 dates. Coverage limited by classified subset (5,687 of 16,523 events) — older dates have fewer events surviving the published_at filter.",
    },
    {
        "signal": "macro_sector_signal",
        "label": "Macro Sector Tilt",
        "group": "Macro",
        "description": "Per-sector aggregate of macro indicator changes (latest vs 90d-prior, weighted by direction)",
        "source_tables": ["macro_history", "macro_indicator_meta", "macro_sector_map"],
        "source_columns": ["macro_history.{value, date}", "macro_sector_map.{sector, direction, weight}"],
        "filing_lag": "varies (1w to 8w by indicator)",
        "pit_column_v1": None,
        "pit_column_v2": "macro_sector_signals_pit.macro_score",
        "v1_verdict_summary": "(post-v1; Plan 0002)",
        "status": "READY",
        "status_reason": "Sector-level — written to macro_sector_signals_pit. 11 sectors × 7 dates. Uses 30-row macro_sector_map for indicator→sector weighting.",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 11 — TRACK 3 FACTOR LIBRARY
    # ═══════════════════════════════════════════════════════════════════
    # All sourced from fundamentals_screener (Screener Premium scrape).
    # Filing lag 75d annual. Validated tier = |t|≥1.5 on some cap-tier in
    # the most recent backtest; library tier = below that bar but kept
    # computed for re-test as PIT history extends. The FACTOR_LIBRARY list
    # below carries the library-tier signal ids.

    {
        "signal": "roic",
        "label": "Return on Invested Capital",
        "group": "Track 3 — Library",
        "description": "NOPAT / Invested Capital, 3-yr median. NOPAT = (PBT + Interest) × (1 − Tax/PBT)",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{PBT, Interest, Tax, Equity Share Capital, Reserves, Borrowings}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "roic",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=0.75 LARGE)",
        "status": "READY",
        "status_reason": "Library tier — sub-|t|=1.5 on every tier in the 6-period backtest. Kept computed for re-test as PIT history extends.",
    },
    {
        "signal": "roiic",
        "label": "Return on Incremental Invested Capital",
        "group": "Track 3 — Library",
        "description": "(NOPAT_t − NOPAT_{t-5}) / (IC_t − IC_{t-5}). Marginal-ROIC over trailing 5y; sister of ROIC. ΔIC ≥ ₹50 cr filter, capped ±5.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{PBT, Tax, Interest, Equity Share Capital, Reserves, Borrowings} (annual, 6 yrs)"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "roiic",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=0.91 MID, intuitive sign)",
        "status": "READY",
        "status_reason": "Library tier — sub-|t|=1.5 in the 6-period backtest but signs are intuitive (positive marginal ROIC → positive return). Retest as PIT extends.",
    },
    {
        "signal": "fcf_yield",
        "label": "Free Cash Flow Yield",
        "group": "Track 3 — Library",
        "description": "3-yr median FCF / PIT market_cap. FCF = OCF − (max(Δ(Net Block + CWIP), 0) + Depreciation). PIT market cap uses close × No. of Equity Shares.",
        "source_tables": ["fundamentals_screener", "stock_prices"],
        "source_columns": ["{OCF, Net Block, CWIP, Depreciation, No. of Equity Shares}", "stock_prices.close (PIT)"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "fcf_yield",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.08 SMALL)",
        "status": "READY",
        "status_reason": "Library tier — sub-|t|=1.5 on every tier in the 6-period backtest. Kept computed for re-test as PIT history extends.",
    },
    {
        "signal": "ccc",
        "label": "Cash Conversion Cycle",
        "group": "Track 3 — Library",
        "description": "DSO + DIO − DPO, 3-yr median. Sales used as denominator (no clean COGS line in Screener).",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Sales, Receivables, Inventory, Trade Payables}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "ccc",
        "v1_verdict_summary": "v2-only — LARGE WEAK (t=+1.87, n=5, contrarian sign), MID/SMALL DROP",
        "status": "READY",
        "status_reason": "PARKED — passes |t|≥1.5 bar on LARGE but with contrarian sign (higher CCC predicts higher return). Likely 5-month regime artifact (small-cap rotation period); awaiting more periods before promoting to scoring weights.",
    },
    {
        "signal": "margin_slope",
        "label": "Operating Margin Trend (5y slope)",
        "group": "Track 3 — Library",
        "description": "OLS slope of last 5y EBIT/Sales in percentage-points/year. EBIT = PBT + Interest.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Sales, PBT, Interest}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "margin_slope",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.30 MID)",
        "status": "READY",
        "status_reason": "Library tier — signs negative across LARGE/MID, suggesting declining-margin stocks outperformed in the 5-period window. Kept computed for re-test as PIT extends.",
    },
    {
        "signal": "wc_intensity",
        "label": "Working Capital Intensity",
        "group": "Track 3 — Library",
        "description": "(Receivables + Inventory − Trade Payables) / Sales, 3-yr median. Sibling of CCC in ratio form.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Sales, Receivables, Inventory, Trade Payables}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "wc_intensity",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.48 LARGE)",
        "status": "READY",
        "status_reason": "Library tier — borderline (t=1.48 just under bar); same regime pattern as CCC. Kept computed.",
    },
    {
        "signal": "dso_change_yoy",
        "label": "DSO YoY Change",
        "group": "Track 3 — Library",
        "description": "Receivables/(Sales/365) − prior year. Rising DSO = receivables outpacing sales (forensic yellow flag). Days.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Sales, Receivables}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "dso_change_yoy",
        "v1_verdict_summary": "v2-only — LARGE KEEP (t=-2.81), MID WEAK (t=-1.71), SMALL DROP (t=+1.49)",
        "status": "READY",
        "status_reason": "PARKED — strongest factor in 2026-05 forensic batch. Intuitive sign on LARGE+MID (higher Δ DSO → lower return). Promote candidate after one more month of fwd_return matures.",
    },
    {
        "signal": "dio_change_yoy",
        "label": "DIO YoY Change",
        "group": "Track 3 — Library",
        "description": "Inventory/(Sales/365) − prior year. Rising DIO = inventory accumulating faster than sales. Days.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Sales, Inventory}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "dio_change_yoy",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=0.97 MID)",
        "status": "READY",
        "status_reason": "Library tier — no edge in the 6-period backtest. Cousin of dso_change_yoy but inventory dynamics are noisier (production decisions).",
    },
    {
        "signal": "nwc_to_revenue",
        "label": "NWC / Revenue (latest)",
        "group": "Track 3 — Library",
        "description": "(Receivables + Inventory − Trade Payables) / Sales, latest annual. Spot sibling of wc_intensity (which is 3y median).",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Sales, Receivables, Inventory, Trade Payables}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "nwc_to_revenue",
        "v1_verdict_summary": "v2-only — LARGE WEAK (t=+1.68), SMALL WEAK (t=+1.92), MID DROP (t=+1.29)",
        "status": "READY",
        "status_reason": "PARKED — passes |t|≥1.5 bar on LARGE+SMALL but with contrarian sign (higher NWC predicts higher return). Likely 6-period regime artifact (same pattern as wc_intensity / ccc); awaiting more periods.",
    },
    {
        "signal": "sloan_accruals_full",
        "label": "Sloan Accruals (full BS formula)",
        "group": "Track 3 — Library",
        "description": "(ΔNWC − Depreciation) / avg(Total assets). The original Sloan (1996) measure. Lower = cash-rich earnings.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Receivables, Inventory, Trade Payables, Depreciation, Total}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "sloan_accruals_full",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.43 SMALL)",
        "status": "READY",
        "status_reason": "Library tier — sub-|t|=1.5 across tiers. Sibling of cf_accruals/bs_accruals from v1 forensic suite; redundancy possible.",
    },
    {
        "signal": "sga_to_revenue_change",
        "label": "Δ SG&A Intensity",
        "group": "Track 3 — Library",
        "description": "Selling and admin / Sales − prior year. Rising intensity = operating discipline slipping.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Sales, Selling and admin}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "sga_to_revenue_change",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=0.69 MID)",
        "status": "READY",
        "status_reason": "Library tier — no edge in the 6-period backtest. Screener's 'Selling and admin' may miss R&D and other overheads broken out separately.",
    },
    {
        "signal": "fcf_margin",
        "label": "FCF Margin",
        "group": "Track 3 — Library",
        "description": "3y median (OCF − Capex) / Sales. Fundamental sibling of fcf_yield (no valuation input).",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Sales, OCF, Net Block, CWIP, Depreciation}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "fcf_margin",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.28 LARGE)",
        "status": "READY",
        "status_reason": "Library tier — sub-|t|=1.5. Likely correlated with fcf_yield and quality_composite.",
    },
    {
        "signal": "capex_to_dep",
        "label": "CapEx / Depreciation",
        "group": "Track 3 — Library",
        "description": "3y median (max(Δ(Net Block + CWIP), 0) + Depreciation) / Depreciation. >1 = growing, <1 = harvesting.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Net Block, CWIP, Depreciation}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "capex_to_dep",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=0.94 SMALL)",
        "status": "READY",
        "status_reason": "Library tier — capital-cycle descriptor more than a return predictor in this regime.",
    },
    {
        "signal": "goodwill_to_assets",
        "label": "Intangibles / Total Assets",
        "group": "Track 3 — Library",
        "description": "Intangible Assets / Total. Goodwill proxy — Screener doesn't separate goodwill from other intangibles.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Intangible Assets, Total}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "goodwill_to_assets",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=0.89 MID)",
        "status": "READY",
        "status_reason": "Library tier — no edge in 6 periods. Median ratio is 0.6% so the cross-section is thin; mostly a tag for acquisition-driven names.",
    },
    {
        "signal": "debt_structure",
        "label": "LT Borrowings Share",
        "group": "Track 3 — Library",
        "description": "Long term Borrowings / Borrowings, latest annual. Higher = safer debt maturity profile.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Long term Borrowings, Borrowings}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "debt_structure",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.15 LARGE)",
        "status": "READY",
        "status_reason": "Library tier — debt maturity profile descriptor. Median 27% LT (Indian companies skew short-term); cross-section may need finer maturity buckets to find signal.",
    },
    {
        "signal": "asset_tangibility",
        "label": "Asset Tangibility (Net Block / Total)",
        "group": "Track 3 — Library",
        "description": "Net Block / Total assets, latest annual. Higher = capex-heavy / asset-rich business model.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Net Block, Total}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "asset_tangibility",
        "v1_verdict_summary": "v2-only — MID WEAK (t=+2.06), LARGE/SMALL DROP",
        "status": "READY",
        "status_reason": "PARKED — WEAK MID with positive sign (capex-heavy mid-caps outperformed in the 6-period window). Likely regime-dependent (industrials/cement rotation); awaiting more periods.",
    },
    {
        "signal": "interest_coverage",
        "label": "Interest Coverage Ratio",
        "group": "Track 3 — Library",
        "description": "(PBT + Interest) / Interest, 3-yr median, capped ±200. Stocks with Interest<₹1cr excluded.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{PBT, Interest}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "interest_coverage",
        "v1_verdict_summary": "v2-only — SMALL WEAK (t=+2.41, n=5, intuitive sign), LARGE/MID DROP",
        "status": "READY",
        "status_reason": "PARKED — strongest result of the 2026-05-22 batch; intuitively-signed (higher coverage → higher return) on SMALL. Promote candidate after one more month of fwd_return matures.",
    },
    {
        "signal": "revenue_cv_5y",
        "label": "Revenue CV (5y stability)",
        "group": "Track 3 — Library",
        "description": "Stdev/|mean| of last 5 YoY Sales growth rates. Lower = more stable top line.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["Sales (annual, 6 yrs)"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "revenue_cv_5y",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.28)",
        "status": "READY",
        "status_reason": "Library tier (plan 0007 cluster).",
    },
    {
        "signal": "relative_turnover",
        "label": "Inventory Turnover vs Sector",
        "group": "Track 3 — Library",
        "description": "Sales/Inventory 3-yr median, divided by sector p50. IT/Comm/Utilities + financials excluded.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Sales, Inventory}"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "relative_turnover",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.07)",
        "status": "READY",
        "status_reason": "Library tier (plan 0007 cluster).",
    },
    {
        "signal": "relative_growth",
        "label": "Sales Growth vs Sector Median",
        "group": "Track 3 — Library",
        "description": "3-yr median YoY Sales growth minus sector median. Financials excluded.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["Sales (annual)"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "relative_growth",
        "v1_verdict_summary": "v2-only — DROP all tiers (best |t|=1.19)",
        "status": "READY",
        "status_reason": "Library tier (plan 0007 cluster).",
    },
    {
        "signal": "share_momentum",
        "label": "Market-Cap Share Momentum",
        "group": "Track 3 — Library",
        "description": "Δ market_cap_share within sector over trailing 90 calendar days. Financials excluded.",
        "source_tables": ["stock_prices", "fundamentals_screener"],
        "source_columns": ["close (PIT-adjusted)", "No. of Equity Shares"],
        "filing_lag": "0d price + 75d shares",
        "pit_column_v1": None,
        "pit_column_v2": "share_momentum",
        "v1_verdict_summary": "v2-only — KEEP on at least one tier (best |t|=3.21)",
        "status": "READY",
        "status_reason": "VALIDATED — strongest Track-3 signal to date. Eligible for scoring weights pending Track 3.3a weighting work (per CLAUDE.md, don't edit SCREEN.weight_tiers mechanically).",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP 12 — FACTOR COMPOSITES (v1 screener inputs)
    # ═══════════════════════════════════════════════════════════════════

    {
        "signal": "value_composite",
        "label": "Value Composite",
        "group": "Composite",
        "description": "v1 screener: 40% earnings_yield + 35% book_to_price + 25% position_52w (within-tier rank)",
        "source_tables": ["—"],
        "source_columns": ["earnings_yield + book_to_price + position_52w"],
        "filing_lag": "max of components (75d annual)",
        "pit_column_v1": None,
        "pit_column_v2": "value_composite",
        "v1_verdict_summary": "value_recon: DROP / DROP / KEEP (t=3.17 SMALL)",
        "status": "READY",
        "status_reason": "Within-tier rank, NaN-tolerant weighted average.",
    },
    {
        "signal": "quality_composite",
        "label": "Quality Composite",
        "group": "Composite",
        "description": "v1 screener: 45% roe + 30% inverse-debt_to_equity + 25% profit_margin (financials' D/E excluded)",
        "source_tables": ["—"],
        "source_columns": ["roe + debt_to_equity + profit_margin"],
        "filing_lag": "75d annual + 60d quarterly",
        "pit_column_v1": None,
        "pit_column_v2": "quality_composite",
        "v1_verdict_summary": "quality_recon: DROP all tiers",
        "status": "READY",
        "status_reason": "Within-tier rank. Kept despite v1 DROP.",
    },
    {
        "signal": "growth_composite",
        "label": "Growth Composite",
        "group": "Composite",
        "description": "v1 screener: 50% revenue_growth_yoy + 50% eps_growth_yoy (within-tier rank)",
        "source_tables": ["—"],
        "source_columns": ["revenue_growth_yoy + eps_growth_yoy"],
        "filing_lag": "60d quarterly",
        "pit_column_v1": None,
        "pit_column_v2": "growth_composite",
        "v1_verdict_summary": "growth_recon: DROP all tiers (n=16)",
        "status": "READY",
        "status_reason": "Kept despite v1 DROP.",
    },
    {
        "signal": "momentum_composite",
        "label": "Momentum Composite",
        "group": "Composite",
        "description": "v1 screener: 50% mom_6m + 50% mom_12m",
        "source_tables": ["—"],
        "source_columns": ["mom_6m + mom_12m"],
        "filing_lag": "—",
        "pit_column_v1": None,
        "pit_column_v2": "mom_composite",
        "v1_verdict_summary": "momentum_recon: DROP all tiers",
        "status": "READY",
        "status_reason": "Equal-weight composite of mom_6m + mom_12m, ranked within cap_tier.",
    },
    {
        "signal": "screener_final_composite",
        "label": "Final Screener Composite",
        "group": "Composite",
        "description": "Full screener output incl. all sub-signals + adjustments (forensic, sentiment, insider, macro)",
        "source_tables": ["—"],
        "source_columns": ["all of the above"],
        "filing_lag": "—",
        "pit_column_v1": None,
        "pit_column_v2": None,
        "v1_verdict_summary": "(insufficient PIT data — n=0 in v1)",
        "status": "PROPOSED",
        "status_reason": "End-state composite — built only after all sub-signals are PIT-ready. Tracks Track 2.4 portfolio construction work.",
    },
    {
        "signal": "financial_signal",
        "label": "Financial Sub-Model (Banks + NBFCs) — legacy single-direction",
        "group": "Track 2 — Portfolio",
        "description": "Per-stock composite for Banks + NBFCs only: 40% asset_quality (GNPA/NNPA, direction=lower) + 30% profitability + 15% capital + 15% funding. SUPERSEDED 2026-05-29 by financial_quality + financial_recovery split after backtest showed AQ direction flips by tier. Kept here as the alias column (= financial_quality) so historical PIT and the existing optimizer entry survive.",
        "source_tables": ["banking_metrics"],
        "source_columns": ["gross_npa_pct, net_npa_pct, interest_earned, net_interest_income, net_profit, cost_of_funds_pct"],
        "filing_lag": "60d quarterly + 75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "financial_signal",
        "v1_verdict_summary": "Phase 2.2d backtest FAILED done gate (t = -0.75 / -1.30 / -0.34 LARGE/MID/SMALL) — direction-flip diagnostic surfaced. Split into financial_quality + financial_recovery 2026-05-29 session #2.",
        "status": "SUPERSEDED",
        "status_reason": "Single-direction composite invalid by backtest. Use financial_quality (SMALL) + financial_recovery (LARGE/MID) instead.",
    },
    {
        "signal": "financial_quality",
        "label": "Financial Quality — SMALL banks/NBFCs (low NPA = strong franchise)",
        "group": "Track 2 — Portfolio",
        "description": "Quality direction of Phase 2.2b composite — asset_quality z-scored as direction='lower' (low NPA good). Other 3 components shared with financial_recovery: profitability (NII/NP margin), capital (NULL pre-2.2c), funding (cost_of_funds). Composite renormalised over present components. Backtest hypothesis: SMALL banks' gross_npa_pct t=-3.09 (low NPA persists, quality compounds).",
        "source_tables": ["banking_metrics"],
        "source_columns": ["gross_npa_pct, net_npa_pct, interest_earned, net_interest_income, net_profit, cost_of_funds_pct"],
        "filing_lag": "60d quarterly + 75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "financial_quality",
        "v1_verdict_summary": "(v2-only; SMALL-tier validation pending Phase 2.2d-v2 backtest run)",
        "status": "READY",
        "status_reason": "Phase 2.2b-v2 (split) shipped 2026-05-29. PIT helper writes both columns; screener will read this one for SMALL tier post-validation.",
    },
    {
        "signal": "financial_recovery",
        "label": "Financial Recovery — LARGE/MID banks/NBFCs (high NPA = mean-reversion)",
        "group": "Track 2 — Portfolio",
        "description": "Recovery direction of Phase 2.2b composite — asset_quality z-scored as direction='higher' (high NPA = distressed-recovery opportunity). Other 3 components shared with financial_quality. Backtest hypothesis: LARGE net_npa_pct t=+2.39, MID t=+4.16 (NPA-stressed names mean-revert).",
        "source_tables": ["banking_metrics"],
        "source_columns": ["gross_npa_pct, net_npa_pct, interest_earned, net_interest_income, net_profit, cost_of_funds_pct"],
        "filing_lag": "60d quarterly + 75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "financial_recovery",
        "v1_verdict_summary": "(v2-only; LARGE/MID-tier validation pending Phase 2.2d-v2 backtest run)",
        "status": "READY",
        "status_reason": "Phase 2.2b-v2 (split) shipped 2026-05-29. PIT helper writes both columns; screener will read this one for LARGE/MID tiers post-validation.",
    },
]


# ─────────────────────────────────────────────────────────────────────────
# FACTOR_LIBRARY — signal ids that are computed and PIT-reconstructable but
# do NOT (yet) clear the |t|≥1.5 promotion bar. Kept in BACKTEST_SIGNALS so
# the cockpit can render their cards, but listed here so downstream tools
# can filter "validated tier" from "library tier" cleanly.
#
# A signal moves from FACTOR_LIBRARY → validated tier by:
#   1. Hitting |t|≥1.5 on some cap-tier in pit_ic_by_tier_v2, AND
#   2. Being added to SCREEN.weight_tiers via the deliberate process
#      documented in docs/reference/signal-weights.md (NOT mechanically).
#
# Membership changes when t-stats change — keep in sync with the most recent
# `python -m tools.backtest_pit` output. The two PARKED entries (ccc,
# interest_coverage) are listed here because they pass the |t| bar but await
# sign/regime verification before promotion.
FACTOR_LIBRARY = [
    # PARKED — passes |t|≥1.5, sign/regime verification pending
    "dso_change_yoy",       # KEEP LARGE (t=-2.81) — strongest candidate, intuitive sign
    "interest_coverage",    # intuitive sign on SMALL (t=+2.41)
    "asset_tangibility",    # WEAK MID (t=+2.06), regime-dependent positive sign
    "ccc",                  # contrarian sign on LARGE (t=+1.87)
    "nwc_to_revenue",       # contrarian sign on LARGE+SMALL (t=+1.68/+1.92)
    # Sub-threshold — kept computed, awaiting more periods
    "margin_slope",
    "wc_intensity",
    "revenue_cv_5y",
    "relative_turnover",
    "relative_growth",
    "roic",                 # best |t|=0.75 LARGE
    "fcf_yield",            # best |t|=1.08 SMALL
    "roiic",                # best |t|=0.91 MID, intuitive sign
    "dio_change_yoy",       # best |t|=0.97 MID
    "sloan_accruals_full",  # best |t|=1.43 SMALL
    "sga_to_revenue_change",  # best |t|=0.69 MID
    "fcf_margin",           # best |t|=1.28 LARGE
    "capex_to_dep",         # best |t|=0.94 SMALL
    "goodwill_to_assets",   # best |t|=0.89 MID
    "debt_structure",       # best |t|=1.15 LARGE
    # Options/F&O OI factors (§3.2.2) — 22 weekly periods, single 6mo regime
    "pcr_volume",           # SMALL t=-1.69 WEAK (sensible bearish sign)
    "max_pain_distance",    # MID t=-1.68 WEAK (mean-reversion to max-pain)
    "pcr_oi",               # best |t|=0.36 LARGE
    "oi_buildup_signal",    # best |t|=0.45 MID
    # Options/F&O IV factors (§3.2.2 IV half) — 25 weekly periods
    "iv_skew_25d",          # MID t=+4.61 KEEP — strong candidate for promotion (not yet wired)
    "iv_realised_spread",   # MID t=-1.95 WEAK (CI excludes 0)
    "iv_term_structure",    # MID t=-1.80 WEAK; SMALL KEEP is a thin-sample artifact
    "iv_percentile_1y",     # best |t|=1.18 LARGE — DROP (regime signal)
]


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
    """
    pattern = str(PROJECT_ROOT / fo["glob"])
    files = sorted(glob.glob(pattern), reverse=True)
    freshness_field = fo.get("freshness_field")
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
