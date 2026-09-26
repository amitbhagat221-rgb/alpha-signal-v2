"""
schema.sql can rebuild the DB: db.init_db() on an empty file succeeds (twice —
idempotent) and yields every table the code registers. Before the 2026-09-26
regeneration, 20 live tables were missing from schema.sql and init_db() on an
empty DB raised "no such table".
"""
import sqlite3

import db


def test_init_db_on_empty_db(tmp_path, monkeypatch):
    path = tmp_path / "fresh.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    db.init_db()

    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in db.QUARANTINE_SOURCE_TABLES:
        assert t in tables and f"{t}_quarantine" in tables, t
    for t, col, _ in db._COLUMN_MIGRATIONS:
        assert col in {r[1] for r in conn.execute(f"PRAGMA table_info([{t}])")}, (t, col)
    # Tables that had no CREATE statement anywhere before the regeneration.
    for t in ("corporate_actions", "mf_schemes", "mf_nav_history", "surveillance_flags",
              "short_selling_data", "pit_ic_by_tier_v2", "nse_index_history",
              "fii_dii_cash_flow", "fii_dii_positioning", "trust_verdicts"):
        assert t in tables, t
    conn.close()
