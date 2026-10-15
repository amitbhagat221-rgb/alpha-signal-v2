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
    sync.real_sync_contributions = sync.sync_contributions
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


def test_backfills_rewrites_and_removals_reach_the_mirror(v3):
    """The changes a date window cannot see (2026-10-03..08 parity FAILs): a backfilled old price date, a deleted
    price row, a PIT column rewritten in place on an old date, a nulled analyst target, a dropped IC row, and an
    overwritten state row whose history only v3 keeps."""
    path, sync = v3
    c = sqlite3.connect(path)
    c.executescript("""
        INSERT INTO daily_snapshots_pit (sid, snapshot_date, cap_tier, close_price, reconstructed_at)
            VALUES ('AAA', '2025-01-01', 'LARGE', 10, '2025-01-02 00:00:00');
        INSERT INTO analyst_consensus (sid, total_analysts, price_target, fetched_at) VALUES ('AAA', 5, 120, '2026-08-01 00:00:00');
        INSERT INTO pit_ic_by_tier_v2 (signal, cap_tier, n_periods, t_stat, source) VALUES ('roic', 'LARGE', 40, 2.1, 'v2_recompute');
        INSERT INTO regime_state (regime, vix_latest, updated_at) VALUES ('NORMAL', 14, datetime('now', '-40 day'));
    """)
    c.commit()
    assert sync.main([]) == 0                                    # first run: full
    c.executescript("""
        INSERT INTO stock_prices (sid, date, close, source) VALUES ('AAA', '2019-06-03', 10, 'legacy_bhavcopy');
        DELETE FROM stock_prices WHERE sid = 'BBB';
        UPDATE daily_snapshots_pit SET roe = 0.3 WHERE sid = 'AAA';
        UPDATE analyst_consensus SET price_target = NULL WHERE sid = 'AAA';
        DELETE FROM pit_ic_by_tier_v2;
        UPDATE regime_state SET vix_latest = 15, updated_at = datetime('now', '-39 day');
    """)
    c.commit()
    c.close()
    assert sync.main([]) == 0                                    # incremental
    assert _q(path, "SELECT date FROM bars_daily ORDER BY date") == [("2019-06-03",), (_q(path, "SELECT date('now','-1 day')")[0][0],)]
    roe = _q(path, "SELECT f.date, f.value FROM feature_values f JOIN catalog k ON k.catalog_id=f.feature_id WHERE k.name='roe'")
    assert roe == [("2025-01-01", 0.3)]
    pt = _q(path, "SELECT e.value FROM estimates e JOIN catalog k ON k.catalog_id=e.metric_id WHERE k.name='ac.price_target' ORDER BY e.fetched_at")
    assert pt == [(120.0,), (None,)]                             # the removal is a NULL version; 120 stays in history
    assert _q(path, "SELECT attrs ->> '$.retired_at' IS NOT NULL FROM factor_tests") == [(1,)]
    vix = _q(path, "SELECT f.value FROM feature_values f JOIN catalog k ON k.catalog_id=f.feature_id "
                   "WHERE k.name='regime_state.vix_latest' ORDER BY f.date")
    assert vix == [(14.0,), (15.0,)]                             # v3 keeps the day the legacy row overwrote

    assert sync.main([]) == 0                                    # settled: a third run changes nothing
    from datamodel import reconcile
    fails = [r for r in reconcile.run(write=False) if r[1] == "FAIL"]
    assert not fails, fails


def test_stops_before_the_disk_fills(v3, monkeypatch):
    """2026-10-08: a catch-up rewrite grew the WAL to 32 GB and filled the disk. Low free space stops the sync
    cleanly, before it starts and between commits (the open transaction rolls back, no 'cannot rollback')."""
    path, sync = v3
    monkeypatch.setattr(sync, "MIN_FREE_BYTES", 1 << 62)
    with pytest.raises(SystemExit, match="not started"):
        sync.main([])
    c = sync.connect()
    with pytest.raises(RuntimeError, match="stopped before the disk fills"):
        with sync.tx(c):
            sync.breathe(c)
    assert not c.in_transaction


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



def test_contributions_skip_replay_day_without_daily_picks(v3, monkeypatch):
    """Regression (datamodel_sync failed 2026-10-10..15): a pit_replay day with no daily_picks row reads back an
    object-dtype base_score_stored; np.isclose raised TypeError. It must count as match 0.0 and skip the day."""
    import json

    from scoring import screener
    path, sync = v3
    monkeypatch.setattr(screener, "score_universe",
                        lambda df, as_of=None: df.assign(base_score=0.5))
    c = sqlite3.connect(path)
    c.execute("INSERT INTO pit_replay_snapshots (sid, snapshot_date, inputs_json, output_json, frozen_at) VALUES (?,?,?,?,?)",
              ("AAA", "2024-09-02", json.dumps({"cap_tier": "LARGE", "sid": "AAA"}), "{}", "2024-09-02"))
    c.execute("INSERT INTO runs (kind, as_of_date, started_at, status) VALUES ('morning', '2024-09-02', '2024-09-02 00:00:00', 'ok')")
    c.commit()
    c.commit()
    c.close()
    c = sync.connect()
    assert sync.real_sync_contributions(c, True) is not None
    assert c.execute("SELECT COUNT(*) FROM pick_contributions").fetchone()[0] == 0
    c.close()


def test_late_loaded_derivative_rows_of_a_mirrored_date_are_picked_up(v3):
    """Regression (reconcile fno_bhav FAIL from 2026-10-09): BSE SENSEX/BANKEX rows loaded later for dates already
    mirrored sit outside the 15-day window and date presence alone saw no drift; per-date key counts do."""
    path, sync = v3
    c = sqlite3.connect(path)
    ins = ("INSERT INTO fno_bhav (symbol, instrument_type, expiry_date, strike, option_type, trade_date, close) "
           "VALUES (?, 'IDO', '2024-08-01', ?, 'CE', '2024-07-15', 1.0)")
    c.execute(ins, ("NIFTY", 100.0))
    c.commit()
    assert sync.main([]) == 0
    c.execute(ins, ("SENSEX", 200.0))                     # arrives after that date was mirrored
    c.commit()
    assert sync.main([]) == 0
    assert _q(path, "SELECT COUNT(*) FROM derivative_bars WHERE date='2024-07-15'") == [(2,)]
    c.close()
