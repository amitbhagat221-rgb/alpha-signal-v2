"""Plan 0015 Phase 0 — guards that used to be conventions. Offline (no live DB)."""
import sqlite3

import pandas as pd
import pytest

import db
from config import PIPELINE_STEPS


def test_one_primary_producer_for_freshness_and_heal():
    """db.table_producer is the ONE answer: finest cadence wins, ties → first listed."""
    from tools.freshness_watchdog import _producer_for
    by_table = {}
    for s in PIPELINE_STEPS:
        if s.get("table"):
            by_table.setdefault(s["table"], []).append(s)
    meta = db.table_step_meta()
    for table in by_table:
        p = db.table_producer(table)
        assert meta[table]["step_name"] == p["name"] == _producer_for(table)[0]
    assert db.table_producer("analyst_consensus")["frequency"] == "weekly"   # not the monthly scrape
    assert db.table_producer("macro_history")["frequency"] == "daily"


def test_quarantine_mirrors_have_no_pk_or_check():
    """A quarantined row may duplicate a key or be out of range — the mirror must accept it."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(open(db.Path(db.__file__).parent / "schema.sql").read())
    for src in db.QUARANTINE_SOURCE_TABLES:
        ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (src,)).fetchone()[0]
        assert not db._QUARANTINE_BAD_CONSTRAINT.search(
            db._rewrite_ddl_for_quarantine(ddl, src, src + "_quarantine")), src
        mirror = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (src + "_quarantine",)).fetchone()
        assert mirror and not db._QUARANTINE_BAD_CONSTRAINT.search(mirror[0]), f"schema.sql {src}_quarantine"


def test_sql_console_cannot_write(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE t (x)")
    c.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(10)])
    c.commit(); c.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    df, err = db.safe_read_sql("SELECT x FROM t", max_rows=3)
    assert err is None and len(df) == 3
    assert "Forbidden" in db.safe_read_sql("DELETE FROM t")[1]
    # even if a write slipped past the keyword screen, the connection is read-only
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO t VALUES (1)")


def test_dossiers_cover_the_emailed_book(monkeypatch):
    """published_picks('book') = top picks_per_tier of EVERY tier, not the first tier's top 5."""
    import views
    from config import PORTFOLIO
    rows = [{"sid": f"{t}{i}", "cap_tier": t, "rank": i} for t in ("LARGE", "MID", "SMALL") for i in range(1, 9)]
    monkeypatch.setattr(views, "read_sql", lambda q: pd.DataFrame(rows))
    book = views.published_picks("book")
    assert book.groupby("cap_tier").size().to_dict() == dict(PORTFOLIO["picks_per_tier"])
    assert set(book[book.cap_tier == "MID"]["rank"]) == {1, 2, 3, 4, 5}


def test_health_tier_enum_follows_config():
    import health
    from config import TIERS
    checks = health.TABLE_PROFILES["stocks"]["validity_checks"]
    assert any(c.get("column") == "cap_tier" and set(c["in"]) == set(TIERS) for c in checks)
