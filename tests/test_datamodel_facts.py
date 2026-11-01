"""Plan 0030 stage 2: the Company-facts views reproduce their legacy tables from fundamentals /
estimates (the latest version of each metric, pivoted back; period derived from the period end;
INTEGER columns cast), and the gate compares a table without a date column whole."""
import sqlite3

import pytest

import config
import db
from datamodel import compat, gate


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "f.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(config, "DB_PATH", path)
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA_PATH.read_text())
    c.executescript("""
        INSERT INTO stocks (sid, ticker, name, cap_tier) VALUES ('S1', 'S1', 'One', 'LARGE');
        INSERT INTO entities (entity_id, kind, market, key, name, created_at, updated_at) VALUES (1, 'security', 'IN', 'S1', 'One', 't', 't');
        INSERT INTO catalog (catalog_id, kind, name, first_seen) VALUES
            (1, 'metric', 'qi.revenue', 't'), (2, 'metric', 'qi.eps', 't'), (3, 'metric', 'sh.promoter_pct', 't'), (4, 'metric', 'sh.n_shareholders', 't'),
            (5, 'metric', 'ac.total_analysts', 't'), (6, 'metric', 'ac.price_target', 't'), (7, 'metric', 'ac.recommendation_key', 't'),
            (8, 'metric', 'screener.Sales', 't'), (9, 'metric', 'ac.has_analyst_data', 't');
        INSERT INTO quarterly_income (sid, period, end_date, reporting, revenue, eps, fetched_at) VALUES
            ('S1', 'JUN 2026', '2026-06-30', 'consolidated', 1200.5, 5.25, '2026-08-02 01:00:00'),
            ('S1', 'MAR 2026', '2026-03-31', 'consolidated', 1000.0, 4.0, '2026-08-02 01:00:00');
        -- revenue restated: two versions, the newer one wins; eps confirmed on the same fetch
        INSERT INTO fundamentals (entity_id, metric_id, period_end, period_type, basis, source, value, available_at, fetched_at, last_seen_at) VALUES
            (1, 1, '2026-06-30', 'Q', 'consolidated', 'quarterly_income', 1100.0, '2026-08-29', '2026-07-30 01:00:00', '2026-07-30 01:00:00'),
            (1, 1, '2026-06-30', 'Q', 'consolidated', 'quarterly_income', 1200.5, '2026-08-29', '2026-08-02 01:00:00', '2026-08-02 01:00:00'),
            (1, 2, '2026-06-30', 'Q', 'consolidated', 'quarterly_income', 5.25, '2026-08-29', '2026-07-30 01:00:00', '2026-08-02 01:00:00'),
            (1, 1, '2026-03-31', 'Q', 'consolidated', 'quarterly_income', 1000.0, '2026-05-30', '2026-08-02 01:00:00', '2026-08-02 01:00:00'),
            (1, 2, '2026-03-31', 'Q', 'consolidated', 'quarterly_income', 4.0, '2026-05-30', '2026-08-02 01:00:00', '2026-08-02 01:00:00');
        INSERT INTO shareholding (sid, end_date, promoter_pct, n_shareholders, fetched_at) VALUES ('S1', '2026-09-30', 51.2, 12345, '2026-10-20 00:00:00');
        INSERT INTO fundamentals (entity_id, metric_id, period_end, period_type, basis, source, value, available_at, fetched_at, last_seen_at) VALUES
            (1, 3, '2026-09-30', 'Q', 'default', 'shareholding', 51.2, '2026-10-21', '2026-10-20 00:00:00', '2026-10-20 00:00:00'),
            (1, 4, '2026-09-30', 'Q', 'default', 'shareholding', 12345.0, '2026-10-21', '2026-10-20 00:00:00', '2026-10-20 00:00:00');
        INSERT INTO fundamentals_screener (sid, period_end, period_type, line_item, value, filing_date, fetched_at) VALUES
            ('S1', '2026-09-30', 'quarterly', 'Sales', 300.0, NULL, '2026-10-25 00:00:00');
        INSERT INTO fundamentals (entity_id, metric_id, period_end, period_type, basis, source, value, available_at, fetched_at, last_seen_at) VALUES
            (1, 8, '2026-09-30', 'quarterly', 'default', 'fundamentals_screener', 300.0, '2026-11-29', '2026-10-25 00:00:00', '2026-10-25 00:00:00');
        INSERT INTO analyst_consensus (sid, total_analysts, price_target, recommendation_key, fetched_at) VALUES ('S1', 7, 1234.5, 'buy', '2026-11-01 08:00:00');
        INSERT INTO estimates (entity_id, metric_id, target_period, source, value, label, available_at, fetched_at, last_seen_at) VALUES
            (1, 5, '12M', 'analyst_consensus', 7.0, NULL, '2026-10-01', '2026-10-01 05:00:00', '2026-11-01 08:00:00'),
            (1, 6, '12M', 'analyst_consensus', 1234.5, NULL, '2026-10-01', '2026-10-01 05:00:00', '2026-11-01 08:00:00'),
            (1, 7, '12M', 'analyst_consensus', NULL, 'buy', '2026-10-01', '2026-10-01 05:00:00', '2026-11-01 08:00:00'),
            (1, 9, '12M', 'analyst_consensus', 1.0, NULL, '2026-10-01', '2026-10-01 05:00:00', '2026-11-01 08:00:00');   -- the legacy column's DEFAULT 1
    """)
    c.commit()
    yield c
    c.close()


def _gate_ok(concept="facts"):
    bad = [r for r in gate.run(concept, dates=3) if r["legacy"] != r["view_rows"] or r["missing_in_view"] or r["extra_in_view"]]
    assert not bad, bad


def test_views_reproduce_the_legacy_tables_and_the_gate_agrees(conn):
    q = conn.execute("SELECT sid, period, end_date, reporting, revenue, eps, fetched_at FROM v3_quarterly_income ORDER BY end_date DESC").fetchall()
    assert q == [("S1", "JUN 2026", "2026-06-30", "consolidated", 1200.5, 5.25, "2026-08-02 01:00:00"),
                 ("S1", "MAR 2026", "2026-03-31", "consolidated", 1000.0, 4.0, "2026-08-02 01:00:00")]
    assert conn.execute("SELECT promoter_pct, n_shareholders, typeof(n_shareholders) FROM v3_shareholding").fetchall() == [(51.2, 12345, "integer")]
    assert conn.execute("SELECT line_item, value, filing_date FROM v3_fundamentals_screener").fetchall() == [("Sales", 300.0, None)]
    assert conn.execute("SELECT total_analysts, typeof(total_analysts), price_target, recommendation_key, fetched_at FROM v3_analyst_consensus").fetchall() == \
        [(7, "integer", 1234.5, "buy", "2026-11-01 08:00:00")]
    _gate_ok()
    # the gate notices a difference, and compares the dateless table whole
    conn.execute("UPDATE analyst_consensus SET price_target = 999")
    conn.commit()
    r = {x["table"]: x for x in gate.run("facts", dates=3)}
    assert r["analyst_consensus"]["dates"] is None and r["analyst_consensus"]["missing_in_view"] == 1


def test_the_flag_switches_the_readers(conn, monkeypatch):
    monkeypatch.setitem(config.DATA_MODEL, "facts", "new")
    assert compat.rewrite("SELECT revenue FROM quarterly_income WHERE sid = ?") == "SELECT revenue FROM v3_quarterly_income WHERE sid = ?"
    assert db.read_sql("SELECT period, revenue FROM quarterly_income ORDER BY end_date DESC LIMIT 1").iloc[0].tolist() == ["JUN 2026", 1200.5]
    assert compat.aliases("quarterly_income") == {"quarterly_income", "v3_quarterly_income", "fundamentals", "catalog", "entities"}
    monkeypatch.setitem(config.DATA_MODEL, "facts", "old")
    assert compat.rewrite("SELECT revenue FROM quarterly_income") == "SELECT revenue FROM quarterly_income"
