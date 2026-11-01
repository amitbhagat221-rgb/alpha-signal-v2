"""Plan 0030 stage 1 part 3: the four Decisions producers write the v3 tables themselves
(datamodel/decisions.py). Offline, on a DB built from schema.sql: a legacy-shaped frame written
to the legacy table and through the writer reads back identically through the compatibility
view (the parity gate passes, bit for bit), a rewrite replaces the run's rows, a superseded
outcome goes from both sides, a new sid gets its entity, and the sync leaves the writers'
tables alone."""
import json
import sqlite3
from datetime import date, timedelta

import pandas as pd
import pytest

import config
import db
from datamodel import compat, decisions, gate

D1 = (date.today() - timedelta(days=1)).isoformat()
D2 = date.today().isoformat()


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "d.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(config, "DB_PATH", path)
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA_PATH.read_text())
    c.executemany("INSERT INTO stocks (sid, ticker, name, sector, cap_tier) VALUES (?, ?, ?, 'Energy', ?)",
                  [("S1", "S1", "One", "LARGE"), ("S2", "S2", "Two", "LARGE"), ("S3", "S3", "Three", "SMALL")])
    c.commit()
    yield c
    c.close()


def _picks(d, sids=("S1", "S2", "S3")):
    rows = []
    for i, s in enumerate(sids):
        rows.append({"sid": s, "pick_date": d, "final_score": 0.9 - i / 7, "rank": i + 1 if s != "S3" else 1,
                     "base_score": 0.4452032108513916 - i / 13, "sentiment_adj": 0, "insider_adj": 0, "forensic_adj": -0.1 * i,
                     "macro_adj": 0, "piotroski_adj": 0, "accruals_adj": 0, "consensus_adj": 0, "promoter_adj": 0,
                     "smart_money_adj": 0, "cap_tier": "SMALL" if s == "S3" else "LARGE", "sector": "Energy",
                     "weight_coverage": 0.8, "price_rows": 900 + i, "fundamental_coverage": 1.0, "eligible_coverage": None,
                     "integrity_status": "PASS", "integrity_reasons": ""})
    return pd.DataFrame(rows).astype({"rank": "Int64"})


def _gate_ok(exact=True):
    out = gate.run("decisions", dates=3, exact=exact)
    bad = [r for r in out if r["legacy"] != r["view_rows"] or r["missing_in_view"] or r["extra_in_view"]]
    assert not bad, bad


def test_picks_written_both_sides_agree_and_a_rewrite_replaces_the_run(conn):
    frame = _picks(D1)
    db.upsert_df(frame, "daily_picks", conn=conn)
    assert decisions.write_picks(conn, D1, frame) == 3
    conn.commit()
    _gate_ok()
    view = pd.read_sql_query("SELECT * FROM v3_daily_picks ORDER BY sid", conn)
    assert view["base_score"].tolist()[0] == 0.4452032108513916             # Python JSON keeps the float exactly
    assert view["eligible_coverage"].isna().all() and (view["sentiment_adj"] == 0).all()
    sel = dict(conn.execute("SELECT e.key, p.selected FROM picks p JOIN entities e USING (entity_id)").fetchall())
    assert sel == {"S1": 1, "S2": 1, "S3": 1}                               # rank ≤ the tier's pick count
    rid = decisions.morning_run(conn, D1)
    assert conn.execute("SELECT git_sha IS NOT NULL, official FROM runs WHERE run_id=?", (rid,)).fetchone() == (1, 1)
    # a rerun the same day with one stock fewer leaves no stale row on either side
    again = frame[frame["sid"] != "S2"]
    conn.execute("DELETE FROM daily_picks WHERE pick_date=?", (D1,))
    db.upsert_df(again, "daily_picks", conn=conn)
    assert decisions.write_picks(conn, D1, again) == 2
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM picks").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM runs WHERE kind='morning'").fetchone()[0] == 1
    _gate_ok()


def test_a_new_sid_gets_an_entity_and_an_unknown_one_is_an_orphan(conn):
    frame = _picks(D1, sids=("S1", "NEW"))
    db.upsert_df(frame, "daily_picks", conn=conn)
    decisions.write_picks(conn, D1, frame)
    name, attrs = conn.execute("SELECT name, attrs FROM entities WHERE kind='security' AND key='NEW'").fetchone()
    assert name is None and json.loads(attrs)["orphan_from"] == "writer"
    assert conn.execute("SELECT name FROM entities WHERE key='S1'").fetchone() == ("One",)


def test_book_weights_keep_created_at_and_outcomes_drop_superseded_rows_on_both_sides(conn, tmp_path, monkeypatch):
    frame = _picks(D1)
    db.upsert_df(frame, "daily_picks", conn=conn)
    decisions.write_picks(conn, D1, frame)
    book = pd.DataFrame([{"asof_date": D1, "sid": "S1", "weight": 0.6, "factor_score": 0.9, "marginal_risk_contrib": 0.5,
                          "cap_tier": "LARGE", "sector": "Energy", "name": "One", "rank": 1},
                         {"asof_date": D1, "sid": "S2", "weight": 0.4, "factor_score": 0.8, "marginal_risk_contrib": 0.5,
                          "cap_tier": "LARGE", "sector": "Energy", "name": "Two", "rank": 2}])
    db.upsert_df(book, "portfolio_weights", conn=conn)
    stored = pd.read_sql_query("SELECT * FROM portfolio_weights WHERE asof_date=?", conn, params=[D1])
    assert stored["created_at"].notna().all()                              # the legacy default, carried into attrs
    assert decisions.write_book_weights(conn, D1, stored) == 2
    outc = pd.DataFrame([{"sid": s, "pick_date": D1, "window_days": w, "cap_tier": "LARGE", "rank_at_pick": 1, "final_score": 0.9,
                          "entry_price": 100.0, "exit_date": D2, "exit_price": 104.0, "fwd_return_pct": 4.0, "bench_index": "NIFTY 50",
                          "bench_return_pct": 1.0, "excess_return_pct": 3.0, "computed_at": "2026-11-01T04:00:00"}
                         for s in ("S1", "S2") for w in (20, 63)])
    db.upsert_df(outc, "pick_outcomes", conn=conn)
    assert decisions.write_pick_outcomes(conn, outc)[0] == 4
    bo = pd.DataFrame([{"asof_date": D1, "window_days": 20, "hrp_return_pct": -5.7586, "eqw_return_pct": -6.0306, "bench_return_pct": -3.2345,
                        "hrp_vs_eqw_pct": 0.272, "hrp_excess_pct": -2.5242, "n_names": 15, "n_matured": 15, "computed_at": "2026-11-01T04:09:55"}])
    db.upsert_df(bo, "portfolio_outcomes", conn=conn)
    assert decisions.write_portfolio_outcomes(conn, bo) == 1
    conn.commit()
    _gate_ok()
    # the next run recomputes only the 20-day rows: the 63-day ones are superseded on both sides
    later = outc[outc["window_days"] == 20].assign(computed_at="2026-11-02T04:00:00")
    db.upsert_df(later, "pick_outcomes", conn=conn)
    conn.execute("DELETE FROM pick_outcomes WHERE computed_at < ?", ("2026-11-02T00:00:00",))
    n, gone = decisions.write_pick_outcomes(conn, later, superseded_before="2026-11-02T00:00:00")
    conn.commit()
    assert (n, gone) == (2, 2)
    assert conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0] == 3     # 2 stock rows + the book row
    _gate_ok()
    from datamodel import reconcile, sync
    monkeypatch.setattr(sync, "DB_PATH", db.DB_PATH)
    monkeypatch.setattr(sync, "MF_DB", tmp_path / "mf.db")
    monkeypatch.setattr(sync, "sync_contributions", lambda c, full: 0)
    assert sync.main([]) == 0                                                   # fills the catalog the parity record keys on
    fails = [r for r in reconcile.run(write=False) if r[1] == "FAIL"]
    assert not fails, fails
    _gate_ok()                                                                  # the sync changed nothing the writers own


def test_the_sync_leaves_the_writers_tables_alone(conn, tmp_path, monkeypatch):
    frame = _picks(D1)
    db.upsert_df(frame, "daily_picks", conn=conn)                           # legacy only: nothing mirrors it any more
    conn.commit()
    from datamodel import sync
    monkeypatch.setattr(sync, "DB_PATH", db.DB_PATH)
    monkeypatch.setattr(sync, "MF_DB", tmp_path / "mf.db")
    monkeypatch.setattr(sync, "sync_contributions", lambda c, full: 0)
    assert sync.main(["--only", "entities,decisions"]) == 0
    assert conn.execute("SELECT COUNT(*) FROM picks").fetchone()[0] == 0
    assert compat.aliases("daily_picks") == {"daily_picks", "v3_daily_picks", "runs", "picks", "entities"}
