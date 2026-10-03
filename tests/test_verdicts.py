"""
Shared trust_verdicts writer (validators/_verdicts.py).

Regression for the 2026-09-26 audit bug: every gate wrote `INSERT OR REPLACE`
with only its own gate column, which deleted the other gates' verdicts on the
same key. Runs against a temp DB — never the live one.
"""
import json
import sqlite3

import pytest

import db
from validators._verdicts import write_verdict, write_verdicts


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    path = tmp_path / "verdicts.db"
    ddl = db.SCHEMA_PATH.read_text()
    start = ddl.index("CREATE TABLE IF NOT EXISTS trust_verdicts")
    conn = sqlite3.connect(path)
    conn.execute(ddl[start:ddl.index(";", start) + 1])
    # A source table whose PK is NOT (sid, period, end_date) — the hand-written
    # map used to guess that for quarterly_income.
    conn.execute("CREATE TABLE src_fin (sid TEXT, period TEXT, reporting TEXT, "
                 "revenue REAL, end_date TEXT, PRIMARY KEY (sid, period, reporting))")
    conn.execute("CREATE TABLE src_fin_quarantine (sid TEXT, period TEXT, reporting TEXT, "
                 "revenue REAL, end_date TEXT, _q_failed_gate TEXT, _q_reason TEXT, "
                 "_q_quarantined_at TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    db._PK_CACHE.pop("src_fin", None)
    yield path
    db._PK_CACHE.pop("src_fin", None)


def _rows(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    out = [dict(r) for r in conn.execute("SELECT * FROM trust_verdicts")]
    conn.close()
    return out


ROW = {"sid": "ABC", "period": "2026-06", "reporting": "consolidated",
       "revenue": 1.0, "end_date": "2026-06-30"}


def test_two_gates_on_same_key_both_survive(temp_db):
    assert write_verdict("gate_1_identity", "ABC", "src_fin", "revenue", 1,
                         {"reason": "id ok"}, row=ROW, snapshot_date="2026-09-26")
    assert write_verdict("gate_2_plausibility", "ABC", "src_fin", "revenue", 2,
                         {"reason": "extreme"}, row=ROW, snapshot_date="2026-09-26")
    rows = _rows(temp_db)
    assert len(rows) == 1
    r = rows[0]
    assert r["gate_1_identity"] == 1
    assert r["gate_2_plausibility"] == 2
    assert r["verdict_overall"] == "PENDING_REVIEW"
    reasons = json.loads(r["reasons_json"])
    assert set(reasons) == {"gate_1_identity", "gate_2_plausibility"}


def test_overall_is_worst_gate_and_recomputes_on_rewrite(temp_db):
    write_verdict("gate_1_identity", "ABC", "src_fin", "revenue", 1, {}, row=ROW,
                  snapshot_date="2026-09-26")
    write_verdict("gate_2_plausibility", "ABC", "src_fin", "revenue", 0, {}, row=ROW,
                  snapshot_date="2026-09-26")
    assert _rows(temp_db)[0]["verdict_overall"] == "QUARANTINED"
    # Gate 2 re-evaluated to PASS → overall recovers; gate 1 untouched.
    write_verdict("gate_2_plausibility", "ABC", "src_fin", "revenue", 1, {}, row=ROW,
                  snapshot_date="2026-09-26")
    r = _rows(temp_db)[0]
    assert (r["gate_1_identity"], r["gate_2_plausibility"], r["verdict_overall"]) == (1, 1, "TRUSTED")


def test_source_key_uses_real_pk(temp_db):
    write_verdict("gate_2_plausibility", "ABC", "src_fin", "revenue", 1, {}, row=ROW,
                  snapshot_date="2026-09-26")
    key = json.loads(_rows(temp_db)[0]["source_key"])
    assert key == {"sid": "ABC", "period": "2026-06", "reporting": "consolidated"}


def test_quarantine_flag_writes_mirror_row(temp_db):
    assert write_verdict("gate_2_plausibility", "ABC", "src_fin", "revenue", 0,
                         {"reason": "outside hard range"}, row=ROW,
                         snapshot_date="2026-09-26", quarantine=True)
    conn = sqlite3.connect(temp_db)
    q = conn.execute("SELECT sid, _q_failed_gate, _q_reason FROM src_fin_quarantine").fetchall()
    conn.close()
    assert q == [("ABC", "gate_2_plausibility", "outside hard range")]
    assert _rows(temp_db)[0]["verdict_overall"] == "QUARANTINED"


def test_batch_is_atomic_and_rejects_unknown_gate(temp_db):
    good = {"gate": "gate_1_identity", "sid": "ABC", "source_table": "src_fin",
            "datum_class": "revenue", "value": 1, "row": ROW, "snapshot_date": "2026-09-26"}
    assert write_verdicts([good, {**good, "gate": "gate_9_bogus"}]) == 0
    assert _rows(temp_db) == []
    assert write_verdicts([good, {**good, "sid": "XYZ", "row": {**ROW, "sid": "XYZ"}}]) == 2
    assert len(_rows(temp_db)) == 2


def test_identity_wrappers_route_through_shared_writer(temp_db):
    from validators.identity_check import IdentityVerdict, quarantine_row, record_verdict
    from validators.plausibility import record_pt_plausibility_fail

    record_verdict("ABC", "src_fin", json.dumps({"sid": "ABC"}), "revenue",
                   IdentityVerdict("PASS", "ABC", "ABC", "ok"), snapshot_date="2026-09-26")
    record_pt_plausibility_fail("ABC", "2026-09-26", "PT 5x close", source_table="src_fin")
    rows = _rows(temp_db)
    # Different datum_class → two keys; each keeps its own gate.
    assert {(r["datum_class"], r["gate_1_identity"], r["gate_2_plausibility"]) for r in rows} == {
        ("revenue", 1, None), ("pt_upside_pct", None, 0)}
    assert quarantine_row("src_fin", ROW, "ABC", "revenue",
                          IdentityVerdict("WRONG_ENTITY", "ABC", "XYZ", "bad slug"),
                          snapshot_date="2026-09-26")
