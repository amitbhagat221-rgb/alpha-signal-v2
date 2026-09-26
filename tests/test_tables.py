"""
tables.TABLES is the one per-table registry. Checked against a DB built from
schema.sql so a table added to one but not the other fails here, not silently
as a table with no freshness / lineage / domain.
"""
import sqlite3

import pytest

import db
from tables import TABLES

KINDS = {"RAW", "COMPUTED", "STATE", "LOG", "QUARANTINE", "file"}


@pytest.fixture(scope="module")
def schema_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("tables") / "fresh.db"
    conn = sqlite3.connect(path)
    conn.executescript(db.SCHEMA_PATH.read_text())
    yield conn
    conn.close()


def test_every_table_registered_both_ways(schema_db):
    live = {r[0] for r in schema_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    live.add("sqlite_sequence")   # created by the first AUTOINCREMENT insert
    registered = {t for t, e in TABLES.items() if e["kind"] != "file"}
    assert live - registered == set(), "tables missing from tables.TABLES"
    assert registered - live == set(), "tables.TABLES entries missing from schema.sql"


def test_entries_are_well_formed(schema_db):
    for t, e in TABLES.items():
        assert e["kind"] in KINDS, t
        assert e["domain"] in db.DOMAIN_ORDER, t
        assert "date_col" in e, t
        if e.get("freq"):
            assert e["freq"] in db.STALENESS_THRESHOLDS, t
        if e["kind"] == "file" or t == "sqlite_sequence" or not e["date_col"]:
            continue
        cols = {r[1] for r in schema_db.execute(f"PRAGMA table_info([{t}])")}
        assert e["date_col"] in cols, (t, e["date_col"])


def test_derived_views():
    assert db.BEST_EFFORT_STALE == {"insider_trades"}
    assert "stock_prices" in db.DUCKDB_MIRRORED_TABLES
    assert db.STALENESS_OVERRIDES["_file_duckdb_replica"] == 2
    assert all(f"{t}_quarantine" in TABLES for t in db.QUARANTINE_SOURCE_TABLES)
