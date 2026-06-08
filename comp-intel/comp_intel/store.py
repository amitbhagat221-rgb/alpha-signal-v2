"""comp-intel — own SQLite store (data/comp_intel.db). Self-contained; imports nothing
from the parent alpha-signal project."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "comp_intel.db"

SCHEMA = """
-- Live job postings (JobSpy) — POSTED salary RANGES (noisy, abundant).
CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,        -- source-prefixed stable id (dedup)
    source        TEXT,                    -- naukri | indeed | glassdoor | linkedin
    title         TEXT,
    company       TEXT,
    firm_tag      TEXT,                    -- matched config.FIRMS, else NULL
    location      TEXT,
    role_query    TEXT,                    -- which ROLE_QUERY surfaced it
    salary_min    REAL,
    salary_max    REAL,
    salary_period TEXT,                    -- yearly | monthly | hourly
    currency      TEXT,
    salary_inr_min REAL,                   -- normalised to INR/year (best-effort)
    salary_inr_max REAL,
    experience    TEXT,                    -- e.g. "5-8 Yrs" (Naukri)
    skills        TEXT,
    is_remote     INTEGER,
    date_posted   TEXT,
    url           TEXT,
    fetched_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_role ON jobs(role_query, location);
CREATE INDEX IF NOT EXISTS idx_jobs_firm ON jobs(firm_tag);

-- Total-comp records imported from CSV exports (levels.fyi / AmbitionBox / Blind).
-- These are the PRECISE, gated layer — base + bonus + stock by level.
CREATE TABLE IF NOT EXISTS comp_records (
    rec_id        TEXT PRIMARY KEY,        -- content hash (dedup)
    source        TEXT,                    -- levels.fyi | ambitionbox | blind | manual
    company       TEXT,
    firm_tag      TEXT,
    role          TEXT,
    level         TEXT,
    location      TEXT,
    years_exp     REAL,
    base          REAL,
    bonus         REAL,
    stock         REAL,
    total         REAL,
    currency      TEXT,
    total_inr     REAL,                    -- normalised to INR/year (best-effort)
    as_of         TEXT,
    raw           TEXT,
    imported_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_comp_role ON comp_records(role, location);
"""


@contextmanager
def get_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
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
    with get_db() as conn:
        conn.executescript(SCHEMA)
    return DB_PATH


def upsert(table, rows, pk):
    """INSERT OR IGNORE list-of-dicts into `table` keyed on pk. Returns rows written."""
    rows = [r for r in rows if r.get(pk)]
    if not rows:
        return 0
    cols = list(rows[0].keys())
    sql = (f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) "
           f"VALUES ({','.join('?' * len(cols))})")
    payload = [tuple(_coerce(r.get(c)) for c in cols) for r in rows]
    with get_db() as conn:
        before = conn.total_changes
        conn.executemany(sql, payload)
        return conn.total_changes - before


def _coerce(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    return v


def now():
    return datetime.now().isoformat(timespec="seconds")
