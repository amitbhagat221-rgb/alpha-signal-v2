"""
Alpha Signal v2 — Database Module

Single point of access for all database operations.
Every other module imports from here. Never open sqlite3 directly.

Usage:
    from db import get_db, read_table, read_sql, upsert_df
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

from config import PROJECT_ROOT, DB_PATH, SCHEMA_PATH
# Per-table registry (tables.TABLES) + the views derived from it, re-exported
# here under their historical names.
from tables import (TABLES, TABLE_META, TABLE_DOMAIN, STALENESS_OVERRIDES,
                    COVERAGE_THRESHOLDS, BEST_EFFORT_STALE, QUARANTINE_SOURCE_TABLES,
                    DUCKDB_MIRRORED_TABLES)

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
# IF NOT EXISTS" so we catch the duplicate-column error. When a new column is
# added to an existing table, add it to schema.sql AND append it here so live
# DBs pick it up; never edit existing entries (they're idempotent by design).
# 2026-09-26: schema.sql regenerated from the live DB — the 76 entries that
# lived here are all in it now, so the list restarts empty.
_COLUMN_MIGRATIONS = [
]


def _ensure_columns():
    with get_db() as conn:
        for tbl, col, typ in _COLUMN_MIGRATIONS:
            try:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
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
# The source tables are the TABLES entries flagged `quarantine`.


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
# Use for analytical reads on the tables in DUCKDB_MIRRORED_TABLES (TABLES entries
# flagged `mirror`). SQLite stays the source of truth for writes and for tables
# not in the mirror list.
DUCK_PATH = PROJECT_ROOT / "data" / "alpha_signal.duckdb"


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
# Per-table metadata (kind / domain / freshness / coverage / date column /
# inventory text) lives in tables.TABLES.


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
    """Find the earliest and latest dates in a table's date column.

    Strategy:
      1. The column is TABLES[tbl]["date_col"] (None → no date anchor). Tables
         not in the registry fall back to probing DATE_COLS in order: business/
         event dates first, ingestion timestamps last (insider_trades and
         bulk_deals carry both — we want the trade/deal span, not ingestion).
      2. If both SQL MIN and MAX parse cleanly AND parsed_max > parsed_min, trust
         them (this is the fast path for clean ISO/single-format columns).
      3. Otherwise (mixed formats — lexical SQL min/max can be wrong) read every
         distinct value, parse all of them, and take the true min/max.

    Returns (earliest_iso, latest_iso, span_str) or (None, None, '—').
    """
    if tbl in TABLES:
        date_col = TABLES[tbl]["date_col"]
        candidates = [date_col] if date_col else []
    else:
        candidates = DATE_COLS
    for col in candidates:
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
_SCAN_ROOT_FILES = ("pipeline.py",)
# Files to never count (every table name appears here, which would otherwise
# pollute every "consumed_by" cell). tables.py sits outside _SCAN_DIRS.
_SCAN_EXCLUDE = {"db.py"}


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
    table_names = [t for t, e in TABLES.items() if e["kind"] != "file"]

    # One regex per direction; the captured identifier is kept only if it is a
    # registered table (whole identifier, so 'stocks' doesn't match
    # 'stock_prices'). One pass per file instead of one per (file, table) — the
    # per-table form cost ~19s once every table was registered.
    write_pattern = re.compile(
        r'(?:upsert_df\s*\([^,)]*,\s*["\'](\w+)["\']'
        r'|insert_df\s*\([^,)]*,\s*["\'](\w+)["\']'
        r'|INSERT\s+(?:OR\s+(?:IGNORE|REPLACE)\s+)?INTO\s+\[?(\w+)'
        r'|UPDATE\s+\[?(\w+)'
        r'|REPLACE\s+INTO\s+\[?(\w+))',
        re.IGNORECASE,
    )
    read_pattern = re.compile(
        r'(?:read_table\s*\(\s*["\'](\w+)["\']'
        r'|FROM\s+\[?(\w+)'
        r'|JOIN\s+\[?(\w+))',
        re.IGNORECASE,
    )

    def _tables_in(pattern, text):
        found = set()
        for m in pattern.finditer(text):
            name = next(g for g in m.groups() if g).lower()
            if name in refs:
                found.add(name)
        return found

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
        for tbl in _tables_in(write_pattern, text):
            refs[tbl]["writes"].add(rel)
        for tbl in _tables_in(read_pattern, text):
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

# Per-table overrides (`stale_days`), best-effort sources and per-stock
# coverage gates (`coverage`) are TABLES fields — see tables.py for the
# reason behind each one.


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


# Domain grouping for the cockpit's Data Inventory section is TABLES[t]["domain"].




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
    # smart_money_score: behavioural by nature, but its PIT reconstruction only
    # produced MONTHLY anchors (bulk_deals ~1mo depth blocks weekly Friday replay),
    # so it's scored on the monthly panel. Revisit → weekly once bulk depth grows.
    "smart_money_score":        "monthly",
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
        "signal": "smart_money_score",
        "label": "Smart Money Composite",
        "group": "Smart Money",
        "description": "Composite of bulk-deal net-buy depth + delivery-% strength (signals.smart_money). Wired into SMALL screener weight; registered 2026-06-02 to close the never-backtested gap (HANDOFF 2026-06-02).",
        "source_tables": ["bulk_deals", "stock_prices"],
        "source_columns": ["bulk_deals.*", "stock_prices.delivery_pct"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "smart_money_score",
        "v1_verdict_summary": "(was unbacktested — PIT-thin: bulk_deals ~1mo depth → only 6 reconstructed anchors)",
        "status": "READY",
        "status_reason": "PIT helper pit_smart_money exists; thin history (n≈6) — verdict preliminary.",
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
        "signal": "sector_tilt",
        "label": "Sector Tilt (6m basket momentum + macro ensemble)",
        "group": "Momentum",
        "description": "Stock inherits its GICS sector's ensemble = mean of "
                       "z(trailing-6m median constituent return) and z(latest "
                       "macro_sector_signals_pit.macro_score), z-scored across "
                       "the 11 sectors. Validated additive to stock momentum "
                       "(Fama-MacBeth t+3.34 at 3m horizon, ADR 0041).",
        "source_tables": ["stock_prices", "stocks", "macro_sector_signals_pit"],
        "source_columns": ["stock_prices.close", "stocks.sector",
                           "macro_sector_signals_pit.macro_score"],
        "filing_lag": "0d (prices) / monthly (macro leg)",
        "pit_column_v1": None,
        "pit_column_v2": "sector_tilt",
        "v1_verdict_summary": "(new — ADR 0041, no v1 counterpart)",
        "status": "READY",
        "status_reason": "Shipped 2026-06-05 (ADR 0041). Distinct from the benched "
                         "sector_momentum cousin (63d cap-wtd RS): this is the 6m "
                         "absolute median basket + orthogonal macro engine. Backtest "
                         "on 34 monthly PIT anchors: SMALL t=+3.18 KEEP (IC +0.023, "
                         "ICIR 0.545, CI [1.14,5.88]) → WIRED SIGNAL_WEIGHTS[SMALL]=0.10. "
                         "LARGE t=+0.92 / MID t=+0.64 DROP — beats the cousin in every "
                         "tier but clears only SMALL; not wired LARGE/MID.",
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
                         "WIRED into SIGNAL_WEIGHTS[MID]=0.18 on 2026-05-31. Backtest "
                         "on the EXTENDED 48 weekly periods (~11mo, multi-regime): MID "
                         "t=+3.16 KEEP (IC +0.060, CI [2.13,7.15] strictly >0; held "
                         "from the 25-period t=4.61), LARGE t=1.37 / SMALL t=0.17 DROP "
                         "→ MID-only. Orthogonal to size/adtv/existing factors "
                         "(|ρ|<0.15) — adds genuinely new info. F&O-stock coverage.",
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
        "signal": "intraday_range_compression",
        "label": "Intraday Range Compression (ATR5/ATR20)",
        "group": "Microstructure",
        "description": "5-day ATR / 20-day ATR. <1 = recent daily ranges tighter "
                       "than the longer run (volatility compression). Daily OHLC.",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.{high,low,close}"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "intraday_range_compression",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.3, daily-derivable, no Kite)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (§3.2.3 daily half). Backtest 39 monthly periods: best |t|=0.92 LARGE — DROP all tiers. Bench (FACTOR_LIBRARY).",
    },
    {
        "signal": "closing_strength_1m",
        "label": "Closing Strength (1mo)",
        "group": "Microstructure",
        "description": "Mean (close−low)/(high−low) over ~21d — where in the daily "
                       "range the close lands. High = persistent late-day buying.",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.{high,low,close}"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "closing_strength_1m",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.3, daily-derivable, no Kite)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (§3.2.3 daily half). Backtest 39 monthly periods: best |t|=0.98 SMALL — DROP all tiers. Bench (FACTOR_LIBRARY).",
    },
    {
        "signal": "opening_gap_freq_1m",
        "label": "Opening Gap Frequency (1mo)",
        "group": "Microstructure",
        "description": "Fraction of last ~21d with a >1% overnight gap "
                       "(|open/prev_close − 1|). News/event sensitivity proxy.",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.{open,close}"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "opening_gap_freq_1m",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.3, daily-derivable, no Kite)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (§3.2.3 daily half). Backtest 39 monthly periods: MID t=1.31 weak hint, DROP all tiers. Bench (FACTOR_LIBRARY).",
    },
    {
        "signal": "vwap_deviation_5d",
        "label": "VWAP Deviation (5d, OHLC proxy)",
        "group": "Microstructure",
        "description": "Mean 5d (close − typical_price)/typical_price, TP=(H+L+C)/3 "
                       "(daily VWAP proxy — traded_value is ~17% NULL). Late-day strength.",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.{high,low,close}"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "vwap_deviation_5d",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.3, daily-derivable proxy, no Kite)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (§3.2.3 daily half). Backtest 39 monthly periods: best |t|=0.96 SMALL — DROP (OHLC typical-price proxy; true VWAP needs intraday). Bench (FACTOR_LIBRARY).",
    },
    {
        "signal": "bidask_spread_proxy",
        "label": "Bid-Ask Spread (Corwin-Schultz)",
        "group": "Microstructure",
        "description": "Corwin-Schultz 2-day high/low spread estimator, ~20d mean. "
                       "Illiquidity proxy (higher = wider effective spread). Daily H/L.",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.{high,low}"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "bidask_spread_proxy",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.3, daily-derivable proxy, no Kite)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (§3.2.3 daily half). Backtest 39 monthly periods: MID t=1.30 weak hint, DROP all tiers. Bench (FACTOR_LIBRARY).",
    },
    {
        "signal": "kyle_lambda",
        "label": "Kyle Lambda (Amihud illiquidity)",
        "group": "Microstructure",
        "description": "Amihud: mean |daily return| / turnover(₹cr) over ~21d. "
                       "Price impact per unit volume; higher = more illiquid.",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.{close,volume}"],
        "filing_lag": "0d",
        "pit_column_v1": None,
        "pit_column_v2": "kyle_lambda",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.3, daily-derivable proxy, no Kite)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (§3.2.3 daily half). Backtest 39 monthly periods: LARGE t=+4.24 KEEP + MID t=+4.14 KEEP (both CI strictly >0), SMALL t=+1.65 WEAK — the Amihud illiquidity premium (illiquid -> higher fwd returns). Strong + economically grounded. PROMOTION CANDIDATE but trading-cost-coupled (you pay the spread youre compensated for) + likely colinear with size/adtv -> needs factor_correlation + cost-aware review before wiring.",
    },
    {
        "signal": "earnings_surprise_std",
        "label": "Earnings Surprise (SUE)",
        "group": "Event/PEAD",
        "description": "Standardised unexpected earnings — seasonal random walk: "
                       "(EPS_t − EPS_{t-4}) / stdev(trailing YoY EPS changes). The "
                       "classic PEAD signal; no analyst-consensus dependency.",
        "source_tables": ["quarterly_income"],
        "source_columns": ["quarterly_income.eps"],
        "filing_lag": "~45d announcement approx (period_end + 45d)",
        "pit_column_v1": None,
        "pit_column_v2": "earnings_surprise_std",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.5, time-series SUE)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (§3.2.5). Backtest 13-16 monthly periods: all tiers DROP (best LARGE t=0.52). Time-series seasonal-RW SUE proxy too noisy without true earnings-announcement dates + analyst consensus (quarterly_income has neither) — PEAD did not replicate via this proxy. Bench (FACTOR_LIBRARY).",
    },
    {
        "signal": "pead_drift_60d",
        "label": "PEAD Drift (post-earnings, 60d)",
        "group": "Event/PEAD",
        "description": "Abnormal return (stock − NIFTY) since the most recent "
                       "earnings announcement (≈period_end+45d), if within a ~60-day "
                       "post-announcement window; else NULL. Drift-in-progress.",
        "source_tables": ["quarterly_income", "stock_prices", "macro_history"],
        "source_columns": ["quarterly_income.end_date", "stock_prices.close", "macro_history.nifty50"],
        "filing_lag": "~45d announcement approx",
        "pit_column_v1": None,
        "pit_column_v2": "pead_drift_60d",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.5)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (§3.2.5). Backtest 25 monthly periods: SMALL t=-1.54 WEAK (NEGATIVE — post-earnings drift reverses in small caps, opposite of classic PEAD; likely illiquid-reversal noise), LARGE/MID DROP. Active only post-earnings (~600-800/date). Bench.",
    },
    {
        "signal": "corporate_action_density",
        "label": "Corporate Action Density (1y)",
        "group": "Event/PEAD",
        "description": "Count of corporate actions (dividends/splits/bonus/etc.) in "
                       "the trailing 1 year. Higher = more capital-action activity.",
        "source_tables": ["corporate_actions"],
        "source_columns": ["corporate_actions.ex_date"],
        "filing_lag": "0d (ex_date anchor)",
        "pit_column_v1": None,
        "pit_column_v2": "corporate_action_density",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.5)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (§3.2.5). Backtest 20-21 monthly periods: LARGE t=-3.67 KEEP (CI [-5.99,-2.06]; more corp actions -> lower fwd returns), MID/SMALL DROP. NOT promoted — mechanism unclear (likely a maturity/value proxy), corporate_actions only 2yr deep (single regime); verify non-colinear with value factors before trusting. Bench (FACTOR_LIBRARY).",
    },
    {
        "signal": "buyback_announcement_30d",
        "label": "Buyback Announcement (30d)",
        "group": "Event/PEAD",
        "description": "1 if a buyback corporate action appears in the last 30 days "
                       "(subject ~ 'buy back'), else 0. Sparse binary event flag.",
        "source_tables": ["corporate_actions"],
        "source_columns": ["corporate_actions.{ex_date,subject}"],
        "filing_lag": "0d (ex_date anchor)",
        "pit_column_v1": None,
        "pit_column_v2": "buyback_announcement_30d",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.5)",
        "status": "READY",
        "status_reason": "Shipped 2026-05-31 (§3.2.5). Backtest: DROP all tiers (LARGE/MID only n=2 periods, SMALL t=-0.65) — too sparse (~9 buybacks/date) for power. Bench.",
    },
    {
        "signal": "announcement_car",
        "label": "Announcement-Window CAR (PEAD proxy)",
        "group": "Event/PEAD",
        "description": "Market-adjusted cumulative abnormal return in the [-1,+1] trading-day "
                       "window around the latest BSE 'Result' announcement (buy at the last "
                       "pre-print close, measure to +1, minus NIFTY-50 over the same dates). "
                       "The market's own immediate reaction = a real-time earnings-surprise proxy "
                       "needing no analyst consensus (which we lack PIT); PEAD hypothesis: a big "
                       "positive CAR keeps drifting → expected IC POSITIVE. Staleness gate 90d "
                       "(one reporting quarter); NULL when no qualifying recent print.",
        "source_tables": ["bse_announcements", "stock_prices", "macro_history"],
        "source_columns": ["bse_announcements.{sid,dt_tm,category=Result}", "stock_prices.close (adj)", "macro_history.nifty50"],
        "filing_lag": "0d (dt_tm event-time anchor; CAR window must close ≤ eval)",
        "pit_column_v1": None,
        "pit_column_v2": "announcement_car",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.5, PEAD-via-CAR; audit Factor-F3 sanctioned next candidate)",
        "status": "READY",
        "status_reason": "Shipped + backtested 2026-07-05 (PEAD-via-CAR, the sanctioned next step after "
                         "the SUE/pead_drift PEAD failed — memory pead_needs_announce_dates). 78 monthly "
                         "anchors on the CLEAN post-ADR-0047 panel (fwd_return anchor-proximity guard). "
                         "SMALL t=+3.74 KEEP (IC +0.0258, ICIR 0.424, CI [1.99,5.74]); LARGE t=+2.23 WEAK "
                         "(IC +0.0308, ICIR 0.253, CI [0.22,4.36]); MID t=+1.20 DROP (IC +0.0141, "
                         "CI [-0.73,3.20]). ALL THREE POSITIVE — the hypothesised sign (a big announcement "
                         "reaction keeps drifting). This is the FIRST honest thing the LARGE tier has gotten "
                         "from the rebuild: LARGE +2.23 tops the current best wired LARGE factor (consensus "
                         "+1.62 on the clean panel). Multiple-testing: SMALL fails BY-FDR (p_BY 0.153, "
                         "Bonferroni bar |t|≥4.09 not cleared) but sits in the SAME p_BY band as the already-"
                         "WIRED sector_tilt SMALL (3.69) and consensus SMALL (3.74) — a genuine promotion "
                         "candidate, not robust-core. NOT wired (human weight review). Benched in FACTOR_LIBRARY. "
                         "NOTE: a live daily producer is NOT yet built — wiring requires one (see status).",
    },
    {
        "signal": "governance_resignation",
        "label": "Governance Resignation Intensity (1y)",
        "group": "Event/Forensic",
        "description": "Weighted trailing-365d density of senior-officer + auditor "
                       "resignation/cessation events from the BSE announcement stream "
                       "(auditor 3.0 / CFO 2.5 / MD-CEO-Chairman 2.0 / director-CS-cessation 1.0). "
                       "Higher = more governance instability. Dual-use forensic red-flag.",
        "source_tables": ["bse_announcements"],
        "source_columns": ["bse_announcements.{sid,subcategory,dt_tm}"],
        "filing_lag": "0d (dt_tm event-time anchor)",
        "pit_column_v1": None,
        "pit_column_v2": "governance_resignation",
        "v1_verdict_summary": "(new — ADR 0042 BSE event stream)",
        "status": "READY",
        "status_reason": "Shipped 2026-06-13 (ADR 0042). Backtest 46 monthly periods (2018+ BSE depth): "
                         "MID t=-3.82 KEEP (IC -0.051, ICIR -0.56, CI [-6.57,-1.71]) — NEGATIVE sign as "
                         "hypothesised (senior/auditor resignations -> lower fwd returns); LARGE t=-1.61 / "
                         "SMALL t=-1.65 WEAK (same negative direction, not significant). Clear mechanism "
                         "(governance instability), 8yr deep — stronger than corporate_action_density. "
                         "Candidate for deliberate weight review (negative-weight penalty in MID) pending "
                         "orthogonality vs piotroski/forensic/pledge_quality. Dual-use forensic red-flag. NOT yet wired.",
    },
    {
        "signal": "earnings_call_tone_qoq",
        "label": "Earnings-Call Tone QoQ",
        "group": "NLP/Transcript",
        "description": "Δ net Loughran-McDonald tone (positive−negative word density) of the "
                       "latest earnings-call transcript vs the prior call. Tone momentum; "
                       "look-ahead-safe on the real BSE filing date (available_date, #1c).",
        "source_tables": ["nlp_scores", "transcripts"],
        "source_columns": ["nlp_scores.{net_tone,available_date,doc_date}"],
        "filing_lag": "0d (available_date = real BSE filing dt_tm)",
        "pit_column_v1": None,
        "pit_column_v2": "earnings_call_tone_qoq",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.4)",
        "status": "READY",
        "status_reason": "Shipped 2026-06-14 (§3.2.4). Backtest 46 monthly periods: DROP all tiers "
                         "(LARGE t=0.88 / MID -0.17 / SMALL 0.62) — tone-momentum didn't replicate. Bench (FACTOR_LIBRARY).",
    },
    {
        "signal": "forward_looking_intensity",
        "label": "Forward-Looking Intensity",
        "group": "NLP/Transcript",
        "description": "Forward-looking phrases per 1,000 words in the latest earnings-call "
                       "transcript (guidance/outlook/expansion language). Look-ahead-safe (#1c).",
        "source_tables": ["nlp_scores", "transcripts"],
        "source_columns": ["nlp_scores.{forward_looking_intensity,available_date,doc_date}"],
        "filing_lag": "0d (available_date = real BSE filing dt_tm)",
        "pit_column_v1": None,
        "pit_column_v2": "forward_looking_intensity",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.4)",
        "status": "READY",
        "status_reason": "Shipped 2026-06-14 (§3.2.4). Backtest 46 monthly periods: LARGE t=+1.67 / SMALL t=+1.94 "
                         "WEAK (positive — more guidance language → better fwd returns, sensible; CIs straddle 0), "
                         "MID t=0.99 DROP. Sub-2.5, not wired. Bench (FACTOR_LIBRARY); re-test as panel deepens.",
    },
    {
        "signal": "uncertainty_word_density",
        "label": "Uncertainty Word Density",
        "group": "NLP/Transcript",
        "description": "Loughran-McDonald uncertainty-word hits per 100 words in the latest "
                       "earnings-call transcript (hedged/evasive tone). Look-ahead-safe (#1c).",
        "source_tables": ["nlp_scores", "transcripts"],
        "source_columns": ["nlp_scores.{uncertainty_density,available_date,doc_date}"],
        "filing_lag": "0d (available_date = real BSE filing dt_tm)",
        "pit_column_v1": None,
        "pit_column_v2": "uncertainty_word_density",
        "v1_verdict_summary": "(new — Plan 0002 §3.2.4)",
        "status": "READY",
        "status_reason": "Shipped 2026-06-14 (§3.2.4). Backtest 46 monthly periods: LARGE t=+2.90 KEEP "
                         "(IC +0.049, ICIR 0.43, CI [1.00,5.24]) BUT the sign is CONTRARIAN — more hedging/"
                         "uncertainty → HIGHER fwd returns, backwards from LM-uncertainty theory; and LARGE-only "
                         "(the tier walk-forward flags ~zero OOS skill), one 2022-26 regime. MID/SMALL DROP. "
                         "NOT wired — PARKED pending sign/regime verification (FACTOR_LIBRARY), like ccc/nwc_to_revenue.",
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
        "signal": "gross_profitability",
        "label": "Gross Profitability (Novy-Marx)",
        "group": "Track 3 — Library",
        "description": "(Sales − COGS) / Total Assets, 3y median. COGS = Raw Material + Change in Inventory + Power & Fuel + Other Mfr. Exp. Anchor quality factor of the multibagger funnel.",
        "source_tables": ["fundamentals_screener"],
        "source_columns": ["{Sales, Raw Material Cost, Change in Inventory, Power and Fuel, Other Mfr. Exp, Total} (annual)"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "gross_profitability",
        "v1_verdict_summary": "v2-only — not yet backtested (built 2026-06-03 for multibagger funnel)",
        "status": "READY",
        "status_reason": "Multibagger funnel anchor (docs/reference/multibagger-research.md #1). Computed; awaiting first ic_decay/promotion_gate read.",
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

    # ═══════════════════════════════════════════════════════════════════
    # GROUP — INDUSTRY (§3.2.6) + MACRO BETAS (§3.2.7)
    # ═══════════════════════════════════════════════════════════════════
    {
        "signal": "industry_id",
        "label": "Industry Identity (categorical control)",
        "group": "Controls",
        "description": "Frozen integer code (1..38, 0=unknown) for the stock's industry. A NEUTRALISATION CONTROL, not a rankable alpha factor — no directional signal, Spearman IC of an arbitrary code is meaningless. Kept out of SIGNAL_COLUMN_MAP / the IC roster; exists for industry one-hot / neutralisation at model-fit time (Plan 0002 §3.2.6 'industry dummies (1)').",
        "source_tables": ["stocks"],
        "source_columns": ["stocks.industry"],
        "filing_lag": "0d (static attribute)",
        "pit_column_v1": None,
        "pit_column_v2": "industry_id",
        "v1_verdict_summary": "(control — not backtested for IC)",
        "status": "CONTROL",
        "status_reason": "Shipped 2026-06-02. Categorical control; not promotable, not IC-gated.",
    },
    {
        "signal": "oil_beta",
        "label": "Oil Beta (β vs Brent crude)",
        "group": "Macro Extensions",
        "description": "Rolling 252-trading-day OLS beta of daily stock returns on Brent crude daily returns. Energy / input-cost exposure (Plan 0002 §3.2.7). Per-stock exposure, NOT the macro level (a level is cross-sectionally constant → 0 IC).",
        "source_tables": ["stock_prices", "macro_history"],
        "source_columns": ["stock_prices.close", "macro_history.brent_crude"],
        "filing_lag": "0d (daily price + daily macro)",
        "pit_column_v1": None,
        "pit_column_v2": "oil_beta",
        "v1_verdict_summary": "(v2-only; macro_history starts 2023-03-13, NULL before ~1y lookback)",
        "status": "READY",
        "status_reason": "Shipped 2026-06-02; re-backtested 2026-06-07 on deepened macro_history (40 monthly periods, was 23). best |t|=0.87 LARGE → DROP, benched (FACTOR_LIBRARY).",
    },
    {
        "signal": "metals_beta",
        "label": "Metals Beta (β vs copper+aluminium)",
        "group": "Macro Extensions",
        "description": "Rolling 252-trading-day OLS beta of daily stock returns on an equal-weight copper+aluminium daily-return blend. Industrial / capex / metals-cycle exposure (Plan 0002 §3.2.7).",
        "source_tables": ["stock_prices", "macro_history"],
        "source_columns": ["stock_prices.close", "macro_history.copper", "macro_history.aluminium"],
        "filing_lag": "0d (daily price + daily macro)",
        "pit_column_v1": None,
        "pit_column_v2": "metals_beta",
        "v1_verdict_summary": "(v2-only; NULL before ~1y macro lookback)",
        "status": "READY",
        "status_reason": "Shipped 2026-06-02; re-backtested 2026-06-07 on deepened macro_history (40 monthly periods, was 23). LARGE t=+1.96 WEAK (CI [-0.10,3.92] straddles 0; firmed from +1.78), MID/SMALL DROP → benched.",
    },
    {
        "signal": "inr_beta",
        "label": "INR Beta (β vs USD/INR)",
        "group": "Macro Extensions",
        "description": "Rolling 252-trading-day OLS beta of daily stock returns on USD/INR daily returns. FX / importer-vs-exporter tilt (Plan 0002 §3.2.7). The rankable form of the plan's 'inr_carry_proxy' — a carry LEVEL is cross-sectionally constant, so the per-stock FX exposure is used instead.",
        "source_tables": ["stock_prices", "macro_history"],
        "source_columns": ["stock_prices.close", "macro_history.usdinr"],
        "filing_lag": "0d (daily price + daily macro)",
        "pit_column_v1": None,
        "pit_column_v2": "inr_beta",
        "v1_verdict_summary": "(v2-only; NULL before ~1y macro lookback)",
        "status": "READY",
        "status_reason": "Shipped 2026-06-02; re-backtested 2026-06-07 on deepened macro_history (40 monthly periods, was 23). best |t|=1.01 SMALL → DROP (FX exposure not cross-sectionally priced), benched.",
    },
    {
        "signal": "gold_beta",
        "label": "Gold Beta (β vs gold)",
        "group": "Macro Extensions",
        "description": "Rolling 252-trading-day OLS beta of daily stock returns on gold daily returns. Safe-haven / gold-financier tilt (Plan 0002 §3.2.7). Takes the 4th macro-extension slot in place of india_credit_spread, which is DATA-BLOCKED (no daily India G-Sec / credit series; india_money_rate is monthly + stale). Revisit a rate_beta when a daily G-Sec feed lands.",
        "source_tables": ["stock_prices", "macro_history"],
        "source_columns": ["stock_prices.close", "macro_history.gold"],
        "filing_lag": "0d (daily price + daily macro)",
        "pit_column_v1": None,
        "pit_column_v2": "gold_beta",
        "v1_verdict_summary": "(v2-only; NULL before ~1y macro lookback)",
        "status": "READY",
        "status_reason": "Shipped 2026-06-02; re-backtested 2026-06-07 on deepened macro_history (40 monthly periods, was 23). LARGE t=+1.89 WEAK (CI [-0.21,3.85] straddles 0; firmed from +1.58), MID/SMALL DROP → benched.",
    },
    {
        "signal": "rate_beta",
        "label": "Rate Beta (β vs 10Y G-Sec gilt ETF)",
        "group": "Macro Extensions",
        "description": "Rolling 252-trading-day OLS beta of daily stock returns on the SBI 10Y Gilt ETF (SETF10GILT) daily returns. Rate / duration exposure (Plan 0002 §3.2.7). The gilt ETF RISES when the 10Y yield FALLS, so +rate_beta = co-moves with bond rallies (duration-like: NBFCs, rate-sensitive growth). Resolves the previously DATA-BLOCKED india rate factor — NSE bond ETFs are the only free daily India-rates feed reachable (FBIL/CCIL/RBI walled, FRED monthly).",
        "source_tables": ["stock_prices", "macro_history"],
        "source_columns": ["stock_prices.close", "macro_history.gsec10_etf"],
        "filing_lag": "0d (daily price + daily macro)",
        "pit_column_v1": None,
        "pit_column_v2": "rate_beta",
        "v1_verdict_summary": "(v2-only; gsec10_etf daily from 2016)",
        "status": "READY",
        "status_reason": "Shipped + backtested 2026-06-07 (§3.2.7, 40 monthly periods). best |t|=0.77 LARGE → DROP, benched (FACTOR_LIBRARY). Rate-sensitivity not cross-sectionally priced in this sample.",
    },
    {
        "signal": "credit_beta",
        "label": "Credit Beta (β vs AAA-PSU credit excess)",
        "group": "Macro Extensions",
        "description": "Rolling 252-trading-day OLS beta of daily stock returns on credit_excess_idx — the AAA-PSU-over-gilt excess-return index (Bharat Bond EBBETF0430 minus SBI 10Y Gilt). Credit-cycle exposure (Plan 0002 §3.2.7); +credit_beta = rises when credit spreads tighten. CAVEAT: Bharat Bond is target-maturity → residual duration tilt; orthogonalise vs rate_beta before any wiring.",
        "source_tables": ["stock_prices", "macro_history"],
        "source_columns": ["stock_prices.close", "macro_history.credit_excess_idx"],
        "filing_lag": "0d (daily price + daily macro)",
        "pit_column_v1": None,
        "pit_column_v2": "credit_beta",
        "v1_verdict_summary": "(v2-only; credit_excess_idx daily from 2019)",
        "status": "READY",
        "status_reason": "Shipped + backtested 2026-06-07 (§3.2.7, 40 monthly periods). best |t|=0.68 SMALL → DROP, benched. Credit stress (2018 IL&FS / 2020 COVID) falls OUTSIDE the price-history window (2022+), so the test period sees credit in a calm regime — low power. Duration-tilt caveat moot (no signal either way).",
    },

    # ═══════════════════════════════════════════════════════════════════
    # GROUP — LARGE-TIER CANONICAL REBUILD (audit 2026-07-04 Factor-F3)
    # The three canonical factors the audit's gap map named as absent with
    # data already in-house. BUILD + EVIDENCE only — none wired.
    # ═══════════════════════════════════════════════════════════════════

    {
        "signal": "low_vol_252d",
        "label": "Low Volatility (252d annualized)",
        "group": "Risk",
        "description": "Annualized std of daily log returns over the trailing 252 trading "
                       "days (min 200 obs, split-adjusted closes). Canonical low-risk anomaly "
                       "(Ang 2006, Blitz-van Vliet 2007, BAB): LOW vol → HIGH forward return, "
                       "so the expected IC of the raw vol value is NEGATIVE.",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.close (adj, rolling 252d)"],
        "filing_lag": "0d (price)",
        "pit_column_v1": None,
        "pit_column_v2": "low_vol_252d",
        "v1_verdict_summary": "(new — audit Factor-F3 LARGE-tier rebuild candidate #1)",
        "status": "READY",
        "status_reason": "Shipped + backtested 2026-07-05 (audit Factor-F3 #1; 68 monthly anchors "
                         "2020-11→2026-06, incl. the new 2020 price-backfill anchors). LARGE t=+1.96 "
                         "WEAK (IC +0.057, CI [0.14,3.94]) but CONTRARIAN sign — HIGH vol won in the "
                         "mostly-bull 2021-26 sample, opposite the canonical low-vol anomaly; MID +1.26 "
                         "/ SMALL −1.04 DROP (SMALL carries the expected negative sign, insignificant). "
                         "Robust to the timely-anchor fwd_return check (LARGE +1.99). Contrarian-sign "
                         "WEAK on the walk-forward-weakest tier → NOT promotion-eligible; benched "
                         "(FACTOR_LIBRARY). Re-read once a drawdown regime enters the window.",
    },
    {
        "signal": "st_reversal_21d",
        "label": "Short-Term Reversal (21d return)",
        "group": "Momentum",
        "description": "Trailing 21-trading-day total return (min 15 obs, split-adjusted "
                       "closes). Canonical short-term reversal (Jegadeesh 1990): last month's "
                       "losers win next month — expected IC NEGATIVE. The horizon mom_6m/12m "
                       "deliberately skip (SKIP_DAYS=22) is exactly this factor.",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.close (adj, rolling 21d)"],
        "filing_lag": "0d (price)",
        "pit_column_v1": None,
        "pit_column_v2": "st_reversal_21d",
        "v1_verdict_summary": "(new — audit Factor-F3 LARGE-tier rebuild candidate #2)",
        "status": "READY",
        "status_reason": "Shipped + backtested 2026-07-05 (audit Factor-F3 #2; 77 monthly anchors "
                         "2020-02→2026-06). DROP all tiers: SMALL t=−1.50 (expected reversal sign), "
                         "MID −0.40, LARGE +0.04. On the timely-anchor robustness slice SMALL firms "
                         "to −1.93 — the reversal direction looks real in SMALL but stays sub-2.5. "
                         "Benched (FACTOR_LIBRARY); natural retest is weekly cadence (a 21d fast-decay "
                         "factor sampled monthly with a 20d response is structurally handicapped).",
    },
    {
        "signal": "asset_growth_yoy",
        "label": "Asset Growth YoY (CMA)",
        "group": "Growth",
        "description": "YoY % change in total assets between the two most recent knowable "
                       "annual balance sheets (75d filing lag, book_to_price convention; "
                       "non-financials, prior-year assets ≥ ₹50 cr). Canonical investment "
                       "factor (Cooper-Gulen-Schill 2008 / FF5 CMA): aggressive balance-sheet "
                       "expansion underperforms — expected IC NEGATIVE.",
        "source_tables": ["annual_balance_sheet"],
        "source_columns": ["bs.total_assets"],
        "filing_lag": "75d annual",
        "pit_column_v1": None,
        "pit_column_v2": "asset_growth_yoy",
        "v1_verdict_summary": "(new — audit Factor-F3 LARGE-tier rebuild candidate #3)",
        "status": "READY",
        "status_reason": "Shipped + backtested 2026-07-05 (audit Factor-F3 #3; 78 monthly anchors "
                         "2020-01→2026-06). Headline: MID t=+2.18 WEAK / LARGE +1.21 / SMALL −0.30. "
                         "The MID '+' is an ARTIFACT of late-anchored responses: pit_fwd_return_20d "
                         "anchors a sid with no prices near an old eval date at its FIRST later price "
                         "row (~40% of pairs at pre-2023 anchors), pairing 2019-era balance-sheet "
                         "growth with wrong-period returns. Restricting to pairs whose response "
                         "anchors within 10d of eval flips MID to −0.92 and gives the expected CMA "
                         "negative sign on ALL tiers (LARGE −0.87 / MID −0.92 / SMALL −0.70), "
                         "insignificant. NOT promotion-eligible; benched (FACTOR_LIBRARY).",
    },
    {
        "signal": "residual_momentum_12_1",
        "label": "Residual Momentum (12-1, NIFTY-beta-net)",
        "group": "Momentum",
        "description": "12-1 momentum (skip most recent ~21 trading days) residualized "
                       "against NIFTY-50 market beta over the same window (OLS, min 150 "
                       "paired daily-return obs). Jegadeesh-Titman 1993 / Blitz-Huij-Martens "
                       "2011 — removing the market-beta component strengthens raw momentum. "
                       "Designed retest of plain momentum (mom_6m_adj/mom_12m_adj), which "
                       "failed the clean bar at SMALL t=1.34. Expected IC POSITIVE.",
        "source_tables": ["stock_prices", "macro_history"],
        "source_columns": ["stock_prices.close (adj, 252-21d window)", "macro_history.nifty50"],
        "filing_lag": "0d (price)",
        "pit_column_v1": None,
        "pit_column_v2": "residual_momentum_12_1",
        "v1_verdict_summary": "(new — plan 0012 C3, WS2.6 momentum retest hypothesis 1 of 2)",
        "status": "READY",
        "status_reason": "Shipped + backtested 2026-07-11 (plan 0012 C3; 66 monthly anchors "
                         "2020-02→2026-07). SMALL t=+2.84 KEEP (IC +0.0319), correct hypothesised "
                         "sign; LARGE +1.33 / MID +1.11 both DROP (also correct sign, just weak). "
                         "Multiple-testing: SMALL p_BY=0.8832 — fails BY-FDR outright (naive KEEP "
                         "does not survive correction; likely a false discovery from the ~280-"
                         "hypothesis factor zoo, though sign is right). NOT promotion-eligible on "
                         "this evidence; benched (FACTOR_LIBRARY). Report: "
                         "docs/studies/new-factors-2026-07.md.",
    },
    {
        "signal": "max_lottery_21d",
        "label": "MAX Lottery Factor (21d)",
        "group": "Momentum",
        "description": "Mean of the 5 highest daily simple returns over the trailing 21 "
                       "trading days. Bali-Cakici-Whitelaw 2011: retail lottery preference "
                       "overprices extreme-daily-return names — expected IC NEGATIVE. "
                       "Long-only use is naturally exclusion/penalty-shaped (can't short "
                       "the names to avoid), like governance_resignation.",
        "source_tables": ["stock_prices"],
        "source_columns": ["stock_prices.close (adj, rolling 21d, top-5 daily returns)"],
        "filing_lag": "0d (price)",
        "pit_column_v1": None,
        "pit_column_v2": "max_lottery_21d",
        "v1_verdict_summary": "(new — plan 0012 C4, WS2.7 lottery retest hypothesis 2 of 2)",
        "status": "READY",
        "status_reason": "Shipped + backtested 2026-07-11 (plan 0012 C4; 77 monthly anchors "
                         "2020-02→2026-07). SMALL t=-3.47 KEEP (IC -0.0324), correct hypothesised "
                         "NEGATIVE sign — the strongest clean result of the plan 0012 factor batch. "
                         "LARGE t=+1.84 WEAK but CONTRARIAN (positive — opposite of the lottery-"
                         "penalty hypothesis); MID +0.70 DROP. Multiple-testing: SMALL p_BY=0.2193 "
                         "— fails the 0.05 BY-FDR bar but far less badly than the plan's other new "
                         "factors (closest to survival of the batch). NOT promotion-eligible on "
                         "this evidence; benched (FACTOR_LIBRARY). Report: "
                         "docs/studies/new-factors-2026-07.md.",
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
    "gross_profitability",  # Novy-Marx anchor (multibagger funnel). First backtest 2026-07-05
                             # (audit gap #5): SMALL t=-3.91 KEEP, MID t=-2.18 WEAK, LARGE t=-1.32
                             # DROP — all NEGATIVE sign (opposite of Novy-Marx). Contrarian-sign
                             # KEEP, not auto-promotion-eligible — parked pending sign/regime check.
    # Audit Factor-F3 (2026-07-05) — LARGE-tier canonical rebuild trio. None cleared
    # an honest bar; full evidence in BACKTEST_SIGNALS status_reason + signal-weights.md.
    "low_vol_252d",         # LARGE t=+1.96 WEAK but CONTRARIAN (high vol won, 2021-26 bull sample) — parked, not promotion-eligible
    "st_reversal_21d",      # DROP all; SMALL −1.50 (−1.93 on timely-anchor slice), expected reversal sign, sub-bar — weekly-cadence retest is the natural next test
    "asset_growth_yoy",     # MID +2.18 WEAK is a late-anchored-fwd_return ARTIFACT (timely-only −0.92); clean sign = CMA negative all tiers, insignificant
    # Plan 0012 C3 (2026-07-11) — momentum retest hypothesis (WS2.6).
    "residual_momentum_12_1",  # SMALL t=+2.84 KEEP, correct sign, but p_BY=0.8832 fails BY-FDR — not promotion-eligible
    # Plan 0012 C4 (2026-07-11) — lottery retest hypothesis (WS2.7).
    "max_lottery_21d",      # SMALL t=-3.47 KEEP, correct NEGATIVE sign, p_BY=0.2193 (closest-to-surviving of the batch); LARGE +1.84 WEAK but contrarian
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
    # Options/F&O IV factors (§3.2.2 IV half) — 25-48 weekly periods
    # NOTE: iv_skew_25d PROMOTED to SIGNAL_WEIGHTS[MID] 2026-05-31 — no longer bench.
    "iv_realised_spread",   # MID t=-1.95 WEAK (CI excludes 0)
    "iv_term_structure",    # MID t=-1.80 WEAK; SMALL KEEP is a thin-sample artifact
    "iv_percentile_1y",     # best |t|=1.18 LARGE — DROP (regime signal)
    # Microstructure factors (§3.2.3 daily-derivable) — 39 monthly periods
    "kyle_lambda",          # LARGE t=+4.24 + MID t=+4.14 KEEP — Amihud illiquidity premium; promotion candidate (cost-coupled)
    "bidask_spread_proxy",  # MID t=1.30 — DROP
    "opening_gap_freq_1m",  # MID t=1.31 — DROP
    "closing_strength_1m",  # best |t|=0.98 SMALL — DROP
    "vwap_deviation_5d",    # best |t|=0.96 SMALL — DROP
    "intraday_range_compression",  # best |t|=0.92 LARGE — DROP
    # Event-time / PEAD factors (§3.2.5) — earnings half didn't replicate
    # announcement_car WIRED 2026-07-05 (ADR 0050): LARGE 0.35 lead + SMALL 0.14 — moved
    # out of FACTOR_LIBRARY into SIGNAL_WEIGHTS (inline screener producer). Was: PEAD-via-CAR,
    # SMALL t=+3.74 / LARGE +2.23, all positive drift sign, orthogonal (max|ρ|≈0.04).
    "corporate_action_density",  # LARGE t=-3.67 KEEP but unclear mechanism (maturity/value proxy?) — NOT promoted
    "pead_drift_60d",            # SMALL t=-1.54 WEAK (reversal sign)
    "earnings_surprise_std",     # DROP — SUE proxy too noisy w/o announce dates + consensus
    "buyback_announcement_30d",  # DROP — too sparse
    # Macro betas (§3.2.7) — 23 monthly periods, per-stock rolling 252d β
    "metals_beta",          # LARGE t=+1.96 WEAK (40 periods; cyclical large-cap exposure; CI straddles 0)
    "gold_beta",            # LARGE t=+1.89 WEAK (40 periods; safe-haven/gold-financier tilt; CI straddles 0)
    "oil_beta",             # best |t|=0.87 LARGE — DROP (40 periods)
    "inr_beta",             # best |t|=1.01 SMALL — DROP (FX exposure not cross-sectionally priced)
    "rate_beta",            # §3.2.7 (2026-06-07, 40 periods) — best |t|=0.77 LARGE → DROP
    "credit_beta",          # §3.2.7 (2026-06-07, 40 periods) — best |t|=0.68 SMALL → DROP (credit stress pre-2022, out of window)
    # Earnings-call NLP factors (§3.2.4) — 46 monthly periods, look-ahead-safe (#1c)
    "uncertainty_word_density",  # LARGE t=+2.90 KEEP but CONTRARIAN sign (more hedging→higher returns, backwards from LM-uncertainty theory) + LARGE-only (OOS-weak tier) — PARKED for sign/regime verification, NOT wired
    "forward_looking_intensity", # LARGE t=+1.67 / SMALL t=+1.94 WEAK (sensible + sign, CIs straddle 0); MID DROP
    "earnings_call_tone_qoq",    # best |t|=0.88 LARGE — DROP all tiers (tone-momentum didn't replicate)
    # sector_tilt (ADR 0041) NOT here — backtest cleared SMALL t=3.18 KEEP → WIRED to
    # SIGNAL_WEIGHTS[SMALL]=0.10 (2026-06-05). LARGE/MID sub-1.5 but live only in SMALL.

    # 2026-07-05 (audit Factor-F2, ADR 0017 registry debt): sub-1.5 BACKTEST_SIGNALS
    # ids the audit named as limbo (computed + backtested, never registered here or
    # in FACTOR_STATUS) — added so tools/verify_factor_library.py's partition holds.
    "share_momentum",
    "debt_to_equity",
    "position_52w",
    "profit_margin",
    "financial_quality",
    "revenue_growth_yoy",
    "short_selling_signal",
    "earnings_beat_rate",
    # upstream feed frozen 2026-05-02 — see db.STALENESS_OVERRIDES["insider_trades"]
    "insider_signal",
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
    metadata from config.PIPELINE_STEPS + tables.TABLES, per-table
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


def table_step_meta():
    """table → {source, data_freq, frequency, step_name, function}.

    A PIPELINE_STEPS step with `table` wins; otherwise the TABLES entry's
    freq/source (tables fed by standalone crons or co-written by another step).
    """
    from config import PIPELINE_STEPS

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
    for t, e in TABLES.items():
        if e.get("freq") and t not in meta:
            meta[t] = {
                "source": e.get("source", "—"),
                "data_freq": e.get("data_freq", "—"),
                "frequency": e["freq"],
                "step_name": "—",
                "function": "—",
            }
    return meta


def _data_health_impl():
    meta = table_step_meta()

    # Dynamic codebase lineage scan
    refs = get_db_references()

    rows = []
    # One connection for the whole scan.
    with get_db() as conn:
        # Walk every table in the DB (including sqlite_sequence — user wants it kept)
        tables = [
            row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        ]
        # Universe size (for stock-coverage column on per-stock tables).
        try:
            universe_size = conn.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
        except Exception:
            universe_size = 0
        scanned = {}
        for tbl in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM [{tbl}]").fetchone()[0]
            earliest, latest, date_span = _table_date_range(conn, tbl)
            # Stock coverage: only meaningful for tables with a sid column.
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info([{tbl}])").fetchall()]
            stock_count = None
            if "sid" in cols and universe_size > 0:
                stock_count = conn.execute(
                    f"SELECT COUNT(DISTINCT sid) FROM [{tbl}]"
                ).fetchone()[0] or 0
            scanned[tbl] = (count, earliest, latest, date_span, stock_count)

    for tbl in tables:
        count, earliest, latest, date_span, stock_count = scanned[tbl]
        if stock_count is not None:
            stock_coverage_pct = round(100 * stock_count / universe_size, 1)
            stock_coverage = f"{stock_count:,} / {universe_size:,} ({stock_coverage_pct:g}%)"
        else:
            stock_coverage_pct = None
            stock_coverage = "—"

        m = meta.get(tbl, {})
        tm = TABLES.get(tbl, {})
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
            "domain": tm.get("domain", "Other"),
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
