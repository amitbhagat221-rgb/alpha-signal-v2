"""factors.RENAMES + apply_renames: a factor rename is one registry entry plus one
idempotent migration (plan 0015 §4 change locality)."""
import sqlite3

import config
import factors


def _db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(open(config.SCHEMA_PATH).read())
    conn.execute("INSERT INTO stocks (sid, ticker, name) VALUES ('S1', 'T1', 'One')")
    conn.execute("INSERT INTO daily_snapshots_pit (sid, snapshot_date, mom_6m) VALUES ('S1', '2026-01-01', 0.5)")
    for sig in ("mom_6m_adj", "keep_me"):
        conn.execute("INSERT INTO pit_ic_by_tier_v2 (signal, cap_tier, source, n_periods) "
                     "VALUES (?, 'SMALL', 'v2', 10)", (sig,))
        conn.execute("INSERT INTO factor_horizon_gate (signal, cap_tier) VALUES (?, 'SMALL')", (sig,))
    return conn


def test_renames_registry_is_consistent():
    pit_cols = set(factors.PIT_COLUMNS)
    for old, new in factors.RENAMES.items():
        assert old not in factors.FACTORS and old not in pit_cols, old     # code already renamed
        assert new in factors.FACTORS or new in pit_cols, new


def test_apply_renames_migrates_panel_and_evidence_idempotently():
    conn = _db()
    renames = {"mom_6m": "mom_6m_renamed", "mom_6m_adj": "mom_6m_adj_renamed"}
    done = factors.apply_renames(conn, renames)
    assert ("column", "daily_snapshots_pit", "mom_6m", "mom_6m_renamed", 1) in done
    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_snapshots_pit)")}
    assert "mom_6m_renamed" in cols and "mom_6m" not in cols
    assert conn.execute("SELECT mom_6m_renamed FROM daily_snapshots_pit").fetchone() == (0.5,)
    for table in factors.RENAME_EVIDENCE:
        sigs = {r[0] for r in conn.execute(f"SELECT signal FROM {table}")}
        assert sigs == {"mom_6m_adj_renamed", "keep_me"}, table
    assert factors.apply_renames(conn, renames) == []                     # idempotent


def test_apply_renames_newer_row_wins_and_both_columns_refused():
    conn = _db()
    conn.execute("INSERT INTO pit_ic_by_tier_v2 (signal, cap_tier, source, n_periods) "
                 "VALUES ('new_id', 'SMALL', 'v2', 99)")
    factors.apply_renames(conn, {"mom_6m_adj": "new_id"})
    rows = conn.execute("SELECT signal, n_periods FROM pit_ic_by_tier_v2 WHERE cap_tier='SMALL' "
                        "AND signal IN ('new_id', 'mom_6m_adj')").fetchall()
    assert rows == [("new_id", 99)]
    try:
        factors.apply_renames(conn, {"mom_6m": "mom_12m"})
        assert False, "must refuse to rename onto an existing column"
    except ValueError:
        pass


def test_default_renames_is_a_noop():
    conn = _db()
    assert factors.apply_renames(conn) == []
