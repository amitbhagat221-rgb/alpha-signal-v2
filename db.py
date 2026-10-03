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


# ── Read tracing (plan 0015 Phase 1a) ──
# pipeline.run_step records which tables each step actually reads/writes through
# get_db(), so a step's declared `reads` can be checked against real runs. SQLite
# calls the authorizer when it compiles a statement, not per row — negligible cost.
_TRACE = None


def trace_start():
    global _TRACE
    _TRACE = {"reads": set(), "writes": set()}


def trace_stop():
    """End tracing; return {"reads": set, "writes": set} (tables, sqlite_* excluded)."""
    global _TRACE
    out, _TRACE = _TRACE, None
    return out or {"reads": set(), "writes": set()}


def _trace_authorizer(action, a1, a2, dbname, source):
    t = _TRACE
    if t is not None and a1 and not a1.startswith("sqlite_"):
        if action == sqlite3.SQLITE_READ:
            t["reads"].add(a1)
        elif action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
            t["writes"].add(a1)
    return sqlite3.SQLITE_OK


@contextmanager
def get_db():
    """
    Get a database connection with sensible defaults.

    WAL mode:       allows concurrent readers
    foreign_keys:   enforces REFERENCES constraints (bad sid = error, not silent)
    busy_timeout:   waits 30s if another writer holds the lock

    Each call opens a new connection — no pooling needed for batch pipeline.

    Usage:
        with get_db() as conn:
            conn.execute("INSERT INTO ...")
            # auto-commits on exit, auto-rollbacks on exception
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    if _TRACE is not None:
        conn.set_authorizer(_trace_authorizer)
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
    # XBRL filing the trade came from — nse_insider skips filings already stored (2026-09-27)
    ("insider_trades", "filing_id", "TEXT"),
    # total shareholder count per quarter (Screener page, plan 0018) — crowding signal
    ("shareholding", "n_shareholders", "INTEGER"),
    # 1 = Moneycontrol gave no call date; reco_date is the fetch date (plan 0018)
    ("broker_recommendations", "reco_date_imputed", "INTEGER"),
]


def _ensure_columns():
    """Apply _COLUMN_MIGRATIONS — to the table AND its quarantine mirror, if it has
    one: a column the source rows carry but the mirror lacks makes every quarantine
    write fail (found 2026-09-28: banking_metrics' helper column did exactly that)."""
    with get_db() as conn:
        mirrors = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%\\_quarantine' ESCAPE '\\'")}
        for tbl, col, typ in _COLUMN_MIGRATIONS:
            for target in (tbl, f"{tbl}_quarantine"):
                if target != tbl and target not in mirrors:
                    continue
                try:
                    conn.execute(f"ALTER TABLE {target} ADD COLUMN {col} {typ}")
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


_QUARANTINE_META_COLS = [
    ("_q_failed_gate", "TEXT"),
    ("_q_reason", "TEXT"),
    ("_q_quarantined_at", "TEXT DEFAULT (datetime('now'))"),
]


def _ensure_quarantine_tables():
    """Ensure `<table>_quarantine` exists for every QUARANTINE_SOURCE_TABLES entry."""
    import re
    with get_db() as conn:
        for source in QUARANTINE_SOURCE_TABLES:
            mirror = f"{source}_quarantine"
            # Already exists?
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (mirror,)
            ).fetchone()
            if row and not _QUARANTINE_BAD_CONSTRAINT.search(row[0]):
                continue
            if row:
                # Legacy mirror still carries an inline PK / CHECK (the old regex only
                # stripped table-level PKs): a sid could be quarantined once, and a row
                # failing a range gate could not be quarantined at all. Rebuild it.
                _rebuild_quarantine_mirror(conn, source, mirror)
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
            for col, typ in _QUARANTINE_META_COLS:
                try:
                    conn.execute(f"ALTER TABLE {mirror} ADD COLUMN {col} {typ}")
                except sqlite3.OperationalError:
                    pass


# An inline `PRIMARY KEY` or any `CHECK(...)` has no place in a quarantine mirror.
_QUARANTINE_BAD_CONSTRAINT = re.compile(r"PRIMARY\s+KEY|\bCHECK\s*\(", re.IGNORECASE)
_CHECK_CLAUSE = re.compile(r"\s*(?:CONSTRAINT\s+\w+\s+)?CHECK\s*\((?:[^()]|\([^()]*\))*\)", re.IGNORECASE)


def _rebuild_quarantine_mirror(conn, source, mirror):
    """Recreate `mirror` from the source DDL, keeping its rows (shared columns)."""
    src_ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (source,)
    ).fetchone()[0]
    old = f"{mirror}__old"
    conn.execute(f"ALTER TABLE {mirror} RENAME TO {old}")
    conn.execute(_rewrite_ddl_for_quarantine(src_ddl, source, mirror))
    for col, typ in _QUARANTINE_META_COLS:
        conn.execute(f"ALTER TABLE {mirror} ADD COLUMN {col} {typ}")
    new_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({mirror})")}
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({old})") if r[1] in new_cols]
    col_sql = ", ".join(cols)
    conn.execute(f"INSERT INTO {mirror} ({col_sql}) SELECT {col_sql} FROM {old}")
    conn.execute(f"DROP TABLE {old}")


def _rewrite_ddl_for_quarantine(source_ddl: str, source_name: str, mirror_name: str) -> str:
    """Source CREATE TABLE → quarantine CREATE TABLE. Strips PK, FK, UNIQUE, CHECK."""
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
    # …and inline column PKs (`sid TEXT PRIMARY KEY [AUTOINCREMENT]`).
    ddl = re.sub(r"\s+PRIMARY\s+KEY(\s+AUTOINCREMENT)?", "", ddl, flags=re.IGNORECASE)
    # CHECK constraints: a row that failed a range gate must still be storable here.
    ddl = _CHECK_CLAUSE.sub("", ddl)
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
DUCK_PATH = DB_PATH.with_suffix(".duckdb")   # follows ALPHA_DB


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


CONTRACT_MIN_ROWS = 20


class ContractViolation(ValueError):
    """A batch broke its table's write contract (tables.TABLES `contract`). Raised
    BEFORE the write: a harvest whose output is garbage fails loudly instead of
    storing it (plan 0018 — the 12.8K price-0 bulk_deals rows would have stopped here)."""


def check_contract(df, table_name):
    """[] or the list of violations of `table_name`'s write contract for this batch.
    Only columns present in the batch are checked (column-level upserts write
    subsets); batches under CONTRACT_MIN_ROWS rows are too small to judge."""
    c = TABLES.get(table_name, {}).get("contract")
    if not c or df is None or len(df) < CONTRACT_MIN_ROWS:
        return []
    bad = []
    for col, share in (c.get("max_null") or {}).items():
        if col in df.columns:
            frac = float(df[col].isna().mean())
            if frac > share:
                bad.append(f"{col}: {frac:.0%} null (max {share:.0%})")
    for col in c.get("not_all_zero") or []:
        if col in df.columns:
            v = pd.to_numeric(df[col], errors="coerce").fillna(0)
            if (v == 0).all():
                bad.append(f"{col}: all {len(df)} values zero/empty")
    return bad


def _enforce_contract(df, table_name):
    bad = check_contract(df, table_name)
    if bad:
        try:
            import runlog
            runlog.note(f"write contract violated on {table_name}: {'; '.join(bad)}", "ERROR",
                        table=table_name, rows=len(df), violations=bad)
        except Exception:                               # noqa: BLE001
            pass
        raise ContractViolation(f"{table_name} write blocked ({len(df)} rows): {'; '.join(bad)}")


def _count_write(table, n):
    """Rows written per table for the run log's run_end (best-effort)."""
    try:
        import runlog
        runlog.count_write(table, n)
    except Exception:                                   # noqa: BLE001
        pass


def insert_df(df, table_name, conn=None, lock_retries=0):
    """
    Insert DataFrame rows. Skips rows that violate UNIQUE/PRIMARY KEY
    constraints (idempotent — safe to re-run). Returns rows actually inserted.

    Use for append-only tables: insider_trades, bulk_deals, news_articles.

    lock_retries > 0 retries `database is locked` with a linear 2 s, 4 s, … backoff.
    busy_timeout does not cover *write-write* contention (the nightly backup's
    VACUUM, the pipeline, a DuckDB refresh raise SQLITE_BUSY at once for deadlock
    avoidance), so multi-hour harvests pass lock_retries to never lose a batch.
    """
    if df.empty:
        return 0

    df = _drop_future_dated_rows(df, table_name)
    if df.empty:
        return 0
    _enforce_contract(df, table_name)

    cols = ", ".join(f"[{c}]" for c in df.columns)
    placeholders = ", ".join(["?"] * len(df.columns))
    sql = f"INSERT OR IGNORE INTO [{table_name}] ({cols}) VALUES ({placeholders})"

    def _execute(connection):
        cursor = connection.executemany(sql, df.values.tolist())
        _count_write(table_name, cursor.rowcount)
        return cursor.rowcount

    if conn is not None:
        return _execute(conn)
    for attempt in range(lock_retries + 1):
        try:
            with get_db() as connection:
                return _execute(connection)
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or attempt == lock_retries:
                raise
            _time_module.sleep(2.0 * (attempt + 1))
    return 0


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
    _enforce_contract(df, table_name)     # plan 0018 write gate (tables.TABLES `contract`)

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
        _count_write(table_name, cursor.rowcount)
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
_SCAN_ROOT_FILES = ("pipeline.py", "views.py")
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
        if table_name in TABLES and "date_col" in TABLES[table_name] and TABLES[table_name]["date_col"] is None:
            return "N/A", None, None  # declared timeless (meta, per-year tables): not a blind spot
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
    per cold load (get_data_freshness + checks.system.table_facts). Keep it 0
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


_CADENCE_RANK = {"daily": 0, "weekly": 1, "monthly": 2, "quarterly": 3}


def table_producer(table_name):
    """The ONE primary producer step of a table (plan 0015 Phase 0).

    Several steps can write the same table (macro_history, analyst_consensus, …).
    Freshness is judged on — and the watchdog heals via — the same step: the one
    with the finest `frequency`; ties go to the first listed. Before this, freshness
    took the LAST writer and the watchdog the FIRST, so e.g. analyst_consensus was
    judged on the weekly yfinance cadence but healed by the monthly Tickertape step.
    """
    from config import PIPELINE_STEPS
    from graph import writes

    # Every DECLARED write counts (review F12: only the legacy single `table` field did,
    # so a multi-output step's other tables had no producer and could never go stale).
    steps = [s for s in PIPELINE_STEPS if table_name in writes(s)]
    if not steps:
        return None
    return min(steps, key=lambda s: _CADENCE_RANK.get(s["frequency"], 9))  # min() is stable


def table_step_meta():
    """table → {source, data_freq, frequency, step_name, function}.

    The table's primary producer (`table_producer`) wins; otherwise the TABLES
    entry's freq/source (tables fed by standalone crons).
    """
    from config import PIPELINE_STEPS
    from graph import writes

    meta = {}
    for t in dict.fromkeys(t for s in PIPELINE_STEPS for t in writes(s)):
        s = table_producer(t)
        if s:
            meta[t] = {
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


SQL_CONSOLE_TIMEOUT_S = 20


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

    # Execute on a connection that CANNOT write (plan 0015 D6): read-only URI +
    # query_only, a wall-clock limit, and at most max_rows fetched. The keyword
    # screen above stays as a friendlier first error, not as the guarantee.
    deadline = _time_module.monotonic() + SQL_CONSOLE_TIMEOUT_S
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.set_progress_handler(lambda: _time_module.monotonic() > deadline, 10_000)
        cur = conn.execute(q)
        cols = [d[0] for d in cur.description or []]
        df = pd.DataFrame(cur.fetchmany(int(max_rows)), columns=cols)
        return df, None
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e).lower():
            return None, f"Query exceeded {SQL_CONSOLE_TIMEOUT_S}s and was stopped"
        return None, str(e)
    except Exception as e:
        # pandas wraps sqlite errors as `DatabaseError: Execution failed on sql '...': <real msg>`.
        # Surface only the sqlite portion to keep the console message friendly.
        msg = str(e.__cause__) if e.__cause__ else str(e)
        return None, msg
    finally:
        conn.close()


# ── Quick self-test ──

if __name__ == "__main__":
    print("Initializing database...\n")
    init_db()
    print("\nTable inventory:")
    table_counts()


# ── Read shorthands for the cockpit's query sites ──
# Kept at the very end of the module on purpose (other work edits the body).
# rows()/one() go through read_sql so column dtypes match the pandas paths they
# replace; scalar() reads one cell straight off sqlite3.

def rows(sql, params=None):
    """Run SQL → list[dict]. NaN/±Inf become None (the same coercion as
    cockpit._shared.safe_json_records), so the result is JSON- and Jinja-safe.
    Replaces `df.to_dict("records") if not df.empty else []` and the
    hand-written `df.astype(object).where(df.notna(), None)` dance."""
    import math
    out = read_sql(sql, params=params).to_dict("records")
    for rec in out:
        for k, v in rec.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                rec[k] = None
    return out


def one(sql, params=None):
    """First row of rows() as a dict, or {} when the query returns nothing."""
    r = rows(sql, params)
    return r[0] if r else {}


def scalar(sql, params=None, default=None):
    """First column of the first row, or `default` when there is no row or the
    value is NULL. Replaces `read_sql(...).iloc[0]["x"] if not df.empty else d`."""
    with get_db() as conn:
        row = conn.execute(sql, params or []).fetchone()
    return default if row is None or row[0] is None else row[0]
