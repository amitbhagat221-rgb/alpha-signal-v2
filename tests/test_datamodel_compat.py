"""Plan 0030 read switch: a compatibility view reproduces its legacy table column for
column, the read helpers follow the per-concept flag, and the parity gate reports a
difference. Offline: a temp DB from schema.sql."""
import sqlite3

import pytest

import config
import db
import views
from datamodel import compat, gate

PICK = {"sid": "S1", "pick_date": "2026-10-30", "final_score": 0.71, "rank": 3, "base_score": 0.7, "sentiment_adj": 0.0,
        "insider_adj": 0.01, "forensic_adj": 0.0, "macro_adj": 0.0, "piotroski_adj": 0.0, "accruals_adj": 0.0,
        "consensus_adj": 0.0, "promoter_adj": 0.0, "smart_money_adj": 0.0, "cap_tier": "LARGE", "sector": "Energy",
        "weight_coverage": 0.8, "price_rows": 900, "fundamental_coverage": 1.0, "eligible_coverage": 0.9,
        "integrity_status": "PASS", "integrity_reasons": "", "uhs_score": None, "uhs_breakdown_json": None,
        "uhs_label": None, "uhs_worst_dim": None}
ATTRS = {k: PICK[k] for k in PICK if k not in ("sid", "pick_date", "final_score", "rank", "cap_tier", "integrity_status", "uhs_score")}


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "v3.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(config, "DB_PATH", path)
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA_PATH.read_text())          # the views come with the schema
    c.execute("INSERT INTO stocks (sid, ticker, name, sector, cap_tier) VALUES ('S1', 'S1', 'One', 'Energy', 'LARGE')")
    c.execute("INSERT INTO entities (entity_id, kind, market, key, name, created_at, updated_at) VALUES (1, 'security', 'IN', 'S1', 'One', 't', 't')")
    c.execute("INSERT INTO entities (entity_id, kind, market, key, name, created_at, updated_at) VALUES (2, 'portfolio', 'IN', 'book', 'book', 't', 't')")
    c.execute("INSERT INTO runs (run_id, kind, as_of_date, started_at, status, official) VALUES (7, 'morning', '2026-10-30', 'x', 'ok', 1)")
    cols = ", ".join(PICK)
    c.execute(f"INSERT INTO daily_picks ({cols}) VALUES ({', '.join('?' * len(PICK))})", list(PICK.values()))
    import json
    c.execute("INSERT INTO picks (run_id, entity_id, tier, rank, score, selected, gate, uhs, attrs) VALUES (7, 1, 'LARGE', 3, 0.71, 1, 'PASS', NULL, ?)",
              (json.dumps(ATTRS),))
    c.execute("INSERT INTO pick_outcomes (sid, pick_date, window_days, cap_tier, rank_at_pick, final_score, entry_price, exit_date, "
              "exit_price, fwd_return_pct, bench_index, bench_return_pct, excess_return_pct, computed_at) VALUES "
              "('S1', '2026-10-30', 20, 'LARGE', 3, 0.71, 100.0, '2026-11-27', 104.0, 4.0, 'NIFTY 50', 1.0, 3.0, '2026-11-28 01:00:00')")
    c.execute("INSERT INTO outcomes (run_id, entity_id, horizon_days, start_date, end_date, ret, bench_ret, excess, attrs, computed_at) VALUES "
              "(7, 1, 20, '2026-10-30', '2026-11-27', 4.0, 1.0, 3.0, ?, '2026-11-28 01:00:00')",
              (json.dumps({"cap_tier": "LARGE", "rank_at_pick": 3, "final_score": 0.71, "entry_price": 100.0, "exit_price": 104.0,
                           "bench_index": "NIFTY 50"}),))
    c.commit()
    yield c
    c.close()


def _rows(c, sql):
    return c.execute(sql).fetchall()


def test_the_view_reproduces_the_legacy_table(conn):
    cols = ", ".join(PICK)
    assert _rows(conn, f"SELECT {cols} FROM daily_picks") == _rows(conn, f"SELECT {cols} FROM v3_daily_picks")
    assert _rows(conn, "SELECT * FROM pick_outcomes") == _rows(conn, "SELECT * FROM v3_pick_outcomes")
    # the gate agrees, and notices a difference
    ok = gate.run("decisions", dates=3)
    assert all(r["legacy"] == r["view_rows"] and not r["missing_in_view"] and not r["extra_in_view"] for r in ok)
    conn.execute("UPDATE picks SET score = 0.5"); conn.commit()
    bad = [r for r in gate.run("decisions", dates=3) if r["table"] == "daily_picks"][0]
    assert bad["missing_in_view"] == 1 and bad["extra_in_view"] == 1 and "legacy-only" in bad["sample"]


def test_readers_follow_the_flag(conn, monkeypatch):
    monkeypatch.setitem(config.DATA_MODEL, "decisions", "old")
    assert compat.rewrite("SELECT * FROM daily_picks") == "SELECT * FROM daily_picks"
    conn.execute("UPDATE daily_picks SET final_score = 0.99"); conn.commit()      # legacy and view now differ
    assert db.scalar("SELECT final_score FROM daily_picks") == 0.99
    assert views.latest_pick_date() == "2026-10-30"
    monkeypatch.setitem(config.DATA_MODEL, "decisions", "new")
    assert compat.rewrite("SELECT dp.sid FROM daily_picks dp JOIN pick_outcomes po USING (sid)") == \
        "SELECT dp.sid FROM v3_daily_picks dp JOIN v3_pick_outcomes po USING (sid)"
    assert compat.rewrite("INSERT INTO daily_picks (sid) VALUES ('x')").startswith("INSERT INTO daily_picks")   # writes untouched
    assert compat.rewrite("PRAGMA table_info(daily_picks)") == "PRAGMA table_info(daily_picks)"
    assert compat.rewrite("SELECT 'daily_picks' AS t, my_daily_picks FROM x") == "SELECT 'daily_picks' AS t, my_daily_picks FROM x"
    assert db.scalar("SELECT final_score FROM daily_picks") == 0.71                 # read from the view
    assert db.one("SELECT sid, rank FROM daily_picks")["rank"] == 3
    assert views.native_rows("SELECT COUNT(*) AS n FROM daily_picks")[0]["n"] == 1
    assert compat.resolve("daily_picks") == "v3_daily_picks" and compat.resolve("stocks") == "stocks"


def test_every_view_lists_exactly_the_legacy_columns(conn):
    for table, (view, _d) in compat.VIEWS["decisions"].items():
        legacy = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        mirror = [r[1] for r in conn.execute(f"PRAGMA table_info({view})")]
        assert mirror == legacy, (table, mirror, legacy)
