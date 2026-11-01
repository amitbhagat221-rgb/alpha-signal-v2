"""Plan 0032 stage 2: a data_quarantine row masks a stored row from the screener's raw inputs in
memory, and the pick diff of a re-rank against the stored picks is the fault's measured impact."""
import json
import sqlite3
from datetime import date

import pandas as pd
import pytest

import config
import db
from tools import quarantine as q

TODAY = date.today().isoformat()


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "q.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(config, "DB_PATH", path)
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA_PATH.read_text())
    c.executemany("INSERT INTO stocks (sid, ticker, name, sector, cap_tier) VALUES (?, ?, ?, 'Energy', 'LARGE')",
                  [(s, s, s) for s in ("S1", "S2", "S3")])
    c.commit()
    yield c
    c.close()


def test_mask_drops_a_sid_or_one_keyed_row_and_maps_raw_keys_to_tables():
    df = pd.DataFrame({"sid": ["S1", "S1", "S2", "S3"], "end_date": ["2026-03-31", "2026-06-30", "2026-06-30", "2026-06-30"], "v": [1, 2, 3, 4]})
    assert q.mask_frame(df, {"S1": [None]})["sid"].tolist() == ["S2", "S3"]
    assert q.mask_frame(df, {"S1": [{"end_date": "2026-06-30"}]})["v"].tolist() == [1, 3, 4]
    assert q.mask_frame(df, {"ZZ": [None]}).equals(df)
    assert q.tables_of("qi") == {"quarterly_income"} and "stock_prices" in q.tables_of("prices") and q.tables_of("nope") == set()
    q.ACTIVE = {"quarterly_income": {"S2": [None]}}
    try:
        out = q.mask_raw({"qi": df, "prices": df})
    finally:
        q.ACTIVE = None
    assert out["qi"]["sid"].tolist() == ["S1", "S1", "S3"] and out["prices"].equals(df)   # prices read another table
    assert q.mask_raw({"qi": df})["qi"].equals(df)                                        # nothing active, nothing applied


def test_sids_from_a_findings_sample():
    known = {"TEMB", "SIGM", "ELI"}
    assert q.sids_from_sample("TEMB 2026-10-03; SIGM demerged 2026-01-02, annual to 2025-03-31; ELI; TEMB", known) == ["TEMB", "SIGM", "ELI"]
    assert q.sids_from_sample(None, known) == [] and q.sids_from_sample("nothing here", known) == []


def test_register_add_release_and_the_measured_impact(conn):
    from tests.v3seed import seed
    ids = q.add("quarterly_income", ["S2", "S1"], rule="0027 #4", reason="revenue 6x Screener", order_number=7, conn=conn)
    assert ids == [1, 2] and q.add("quarterly_income", ["S1"], rule="0027 #4", conn=conn) == [1]     # no duplicate (ids follow sorted sids)
    conn.commit()
    assert q.as_mask(q.open_rows(conn)) == {"quarterly_income": {"S1": [None], "S2": [None]}}
    seed(conn, "daily_picks", [{"sid": s, "pick_date": TODAY, "cap_tier": "LARGE", "final_score": sc, "rank": r, "integrity_status": "PASS"}
                               for s, sc, r in (("S1", 0.9, 1), ("S2", 0.8, 2), ("S3", 0.7, 3))])
    conn.commit()
    after = pd.DataFrame({"sid": ["S3", "S1", "S2"], "cap_tier": "LARGE", "rank": [1, 2, 3], "final_score": [0.9, 0.85, 0.5]})
    seen = {}
    imp = q.impact(rerank_fn=lambda mask: (seen.setdefault("mask", mask), after)[1], top_n=2)
    assert seen["mask"] == {"quarantine_income".replace("quarantine", "quarterly"): {"S1": [None], "S2": [None]}}
    assert imp["quarantined"] == 2 and imp["moved"] == 2 and imp["top_changes"] == 1 and imp["pick_date"] == TODAY   # S2 left the top 2
    assert {m["sid"]: (m["rank_before"], m["rank_after"]) for m in imp["moves"]} == {"S1": (1, 2), "S2": (2, 3)}
    assert imp["tiers"]["LARGE"]["jaccard"] == pytest.approx(1 / 3, abs=1e-4) and imp["verdict"] == "FAIL"
    assert "2 stocks masked" in q.summary(imp)
    assert q.release([1], conn=conn) == 1
    conn.commit()
    assert [r["sid"] for r in q.open_rows(conn)] == ["S2"]
    assert q.impact(mask={}, rerank_fn=lambda m: after)["quarantined"] == 0


def test_the_drafted_fix_order_carries_the_measured_diff_and_registers_the_rows(conn, monkeypatch):
    import org
    from alpha_mcp import org_kinds
    calls = {}
    monkeypatch.setattr(org_kinds, "IMPACT", lambda mask: (calls.setdefault("mask", mask), {
        "verdict": "WARN", "top_n": 30, "quarantined": 2, "moved": 1, "top_changes": 0, "measured_at": "t",
        "tiers": {"LARGE": {"jaccard": 0.95, "max_rank_shift": 1, "max_score_diff_pct": 0.5}},
        "moves": [{"sid": "S1", "tier": "LARGE", "rank_before": 4, "rank_after": 9, "in_top": {"before": True, "after": True}},
                  {"sid": "S2", "tier": "LARGE", "rank_before": 40, "rank_after": 40, "in_top": {"before": False, "after": False}}]})[1])
    payload = {"as_of": TODAY, "facts": {"findings": [
        {"finding_id": "F1", "subject": "quarterly_income.revenue (0027 #4)", "probe": "forensic", "claim": "revenue 1.5x off", "n_bad": 2,
         "n_total": 100, "sample": "S1 6458x; S2 2x", "known": None},
        {"finding_id": "F2", "subject": "stocks.pe_ratio", "probe": "impossible", "claim": "all empty", "n_bad": 1, "n_total": 3, "sample": None}]}}
    clean = {"findings": [{"finding_id": "F1", "disposition": "real", "impact": "picks", "owner": "data-engineer", "proposed_fix": "the parser"},
                          {"finding_id": "F2", "disposition": "real", "impact": "picks"}], "top_action": "fix the parser"}
    did = org_kinds._draft_fix_order(conn, clean, payload, memo_id=None)
    conn.commit()
    assert did and calls["mask"] == {"quarterly_income": {"S1": [None], "S2": [None]}}
    w = org.work_order(1)
    assert "1 changed rank" in w["summary"] and "S1 rank 4 → 9" in w["items"][0]["what"]
    assert "names no stock ids" in w["items"][1]["what"]
    rows = q.open_rows(conn)
    assert [(r["table_name"], r["sid"], r["finding_id"], r["order_number"]) for r in rows] == \
        [("quarterly_income", "S1", "F1", 1), ("quarterly_income", "S2", "F1", 1)]
    assert json.loads(rows[0]["impact_json"])["rank_after"] == 9
