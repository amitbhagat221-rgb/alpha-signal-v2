"""
Data model v3 shadow sync (ADR 0054): on a DB built from schema.sql with a few legacy
rows, a sync fills the new tables, a second sync changes nothing, a restated value
becomes a new version (the old one is kept), a re-tier closes the old tier row, and
the parity check passes.
"""
import sqlite3

import pytest

import db


@pytest.fixture()
def v3(tmp_path, monkeypatch):
    path = tmp_path / "alpha_signal.db"
    conn = sqlite3.connect(path)
    conn.executescript(db.SCHEMA_PATH.read_text())
    conn.executescript("""
        INSERT INTO stocks (sid, ticker, name, sector, industry, cap_tier) VALUES
            ('AAA', 'AAA', 'Alpha', 'IT', 'Software', 'LARGE'), ('BBB', 'BBB', 'Beta', 'Banks', 'Bank', 'SMALL');
        INSERT INTO stock_prices (sid, date, close, source) VALUES ('AAA', date('now','-1 day'), 100, 'nse'), ('BBB', date('now','-1 day'), 50, 'nse');
        INSERT INTO quarterly_income (sid, period, end_date, reporting, revenue, eps, fetched_at)
            VALUES ('AAA', 'JUN 2026', '2026-06-30', 'consolidated', 1000, 5, '2026-08-01 00:00:00');
        INSERT INTO bulk_deals (sid, symbol, client_name, buy_sell, quantity, price, deal_date, fetched_at)
            VALUES ('BBB', 'BBB', 'X Fund', 'BUY', 1000, 49.5, date('now','-2 day'), datetime('now'));
        INSERT INTO roic_scores (sid, snapshot_date, period_end, roic) VALUES ('AAA', date('now','-1 day'), '2026-03-31', 0.21);
        INSERT INTO daily_picks (sid, pick_date, final_score, rank, base_score, cap_tier, sector)
            VALUES ('AAA', date('now','-1 day'), 0.8, 1, 0.8, 'LARGE', 'IT');
    """)
    conn.commit()
    conn.close()
    from datamodel import sync
    monkeypatch.setattr(sync, "DB_PATH", path)
    monkeypatch.setattr(sync, "MF_DB", tmp_path / "mf.db")
    monkeypatch.setattr(sync, "sync_contributions", lambda c, full: 0)   # needs a pit_replay freeze; covered live
    return path, sync


def _q(path, sql):
    c = sqlite3.connect(path)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


def test_sync_fills_idempotent_and_versions(v3):
    path, sync = v3
    assert sync.main([]) == 0
    assert _q(path, "SELECT COUNT(*) FROM entities WHERE kind='security'")[0][0] == 2
    assert _q(path, "SELECT COUNT(*) FROM bars_daily")[0][0] == 2
    assert _q(path, "SELECT COUNT(*) FROM events")[0][0] == 1
    assert _q(path, "SELECT COUNT(*) FROM picks")[0][0] == 1
    fv = _q(path, "SELECT f.value FROM feature_values f JOIN catalog k ON k.catalog_id=f.feature_id WHERE k.name='roic_scores.roic'")
    assert fv == [(0.21,)]
    counts = {t: _q(path, f"SELECT COUNT(*) FROM {t}")[0][0]
              for t in ("fundamentals", "events", "feature_values", "classifications", "bars_daily", "picks")}

    assert sync.main([]) == 0                                    # idempotent
    assert counts == {t: _q(path, f"SELECT COUNT(*) FROM {t}")[0][0] for t in counts}

    c = sqlite3.connect(path)                                    # a restatement + a re-tier upstream
    c.execute("UPDATE quarterly_income SET revenue=1100, fetched_at='2026-09-01 00:00:00' WHERE sid='AAA'")
    c.execute("UPDATE stocks SET cap_tier='MID' WHERE sid='AAA'")
    c.commit()
    c.close()
    assert sync.main([]) == 0
    rev = _q(path, """SELECT f.value FROM fundamentals f JOIN catalog k ON k.catalog_id=f.metric_id
                      WHERE k.name='qi.revenue' ORDER BY f.fetched_at""")
    assert rev == [(1000.0,), (1100.0,)]                         # the old version is kept
    open_tier = _q(path, """SELECT k.value FROM classifications k JOIN entities e USING (entity_id)
                           WHERE e.key='AAA' AND k.scheme='tier' AND k.valid_to IS NULL""")
    assert open_tier == [("MID",)]


def test_reconcile_passes(v3):
    path, sync = v3
    sync.main([])
    from datamodel import reconcile
    rows = reconcile.run(write=True)
    fails = [r for r in rows if r[1] == "FAIL"]
    assert not fails, fails


def test_seed_from_snapshot(v3, tmp_path):
    path, sync = v3
    sync.main([])                                                # history starts today (no daily_picks row for BBB)
    snap = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute(f"VACUUM INTO '{snap}'")
    c.close()
    o = sqlite3.connect(snap)                                    # the old snapshot: BBB was MICRO, AAA unchanged
    o.execute("UPDATE stocks SET cap_tier='MICRO' WHERE sid='BBB'")
    o.commit()
    o.close()
    assert sync.main(["--seed-from", str(snap), "--seed-date", "2020-01-01"]) == 0
    rows = _q(path, """SELECT e.key, k.value, k.valid_from, k.valid_to FROM classifications k JOIN entities e USING (entity_id)
                       WHERE k.scheme='tier' AND e.key='BBB' ORDER BY k.valid_from""")
    assert rows[0][1:] == ("MICRO", "2020-01-01", rows[1][2]) and rows[1][1] == "SMALL" and rows[1][3] is None

