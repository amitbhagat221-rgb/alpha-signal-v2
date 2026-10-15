"""
Plan 0026 stage 4: the deep-dive builders (3 real names, skipped without the live DB), the mb_dossier
validator (no raw numbers), the brief size cap, and the queue kind's registry / ingest / undo.
"""
import json

import pytest

import db

REAL = ["CONCO", "MARK", "ASTR"]
GOOD = {"thesis_line": "A specialty fermentation maker whose margin recovery could compound for years.",
        "thesis": "Results turned up in Q1 FY27 after a weak H2.",
        "bull": ["Margins recovered"], "bear": ["Premium valuation versus peers"],
        "catalysts": ["New capacity in FY27"], "risks": ["Single-product concentration"],
        "what_would_break_it": ["Margins rolling over again"]}


def _live():
    try:
        return bool(db.DB_PATH.exists() and db.one("SELECT 1 AS x FROM quarterly_income WHERE sid = 'CONCO' LIMIT 1"))
    except Exception:
        return False


live = pytest.mark.skipif(not _live(), reason="live DB not available (set ALPHA_DB)")


@live
@pytest.mark.parametrize("sid", REAL)
def test_results_trend(sid):
    from output import mb_deepdive as mb
    t = mb.results_trend(sid)
    assert 4 <= len(t) <= 12 and [r["end_date"] for r in t] == sorted(r["end_date"] for r in t)
    assert all(r["source"] and r["end_date"] for r in t)
    assert any(r["revenue"] and r["ebitda_margin_pct"] is not None for r in t)
    assert any(r["rev_yoy_pct"] is not None for r in t)


@live
@pytest.mark.parametrize("sid", REAL)
def test_ownership_timeline(sid):
    from output import mb_deepdive as mb
    o = mb.ownership_timeline(sid)
    assert len(o) >= 8 and o[0]["end_date"] >= "2016"
    assert all(k in o[-1] for k in ("promoter_pct", "fii_pct", "dii_pct", "mf_pct", "retail_pct",
                                    "n_shareholders", "pledge_pct", "entered", "exited"))
    assert o[0]["entered"] == [] and o[0]["exited"] == []
    assert 0 <= o[-1]["promoter_pct"] <= 100


@live
@pytest.mark.parametrize("sid", REAL)
def test_peers(sid):
    from output import mb_deepdive as mb
    p = mb.peers(sid, k=8)
    assert p[0]["sid"] == sid and p[0]["is_self"] and 2 <= len(p) <= 9
    assert len({r["sid"] for r in p}) == len(p)
    assert all(r["as_of"] and "thesis_score" in r for r in p)     # thesis_score is None until the column exists
    assert p[0]["market_cap_cr"] and p[0]["pe"] is not None


@live
def test_brief_under_40kb_for_a_data_rich_name():
    from output import mb_dossier as md
    brief, as_of = md.build_brief("CONCO")
    assert len(brief.encode()) < md.MAX_BRIEF_BYTES and as_of >= "2026"
    assert "NO NUMBERS" in brief and "CONCORDBIO" in brief


def test_validator_rejects_numbers_and_accepts_calendar_tokens():
    from output import mb_dossier as md
    assert md.validate(GOOD)["validation"]["ok"]
    for bad in ("Order book worth ₹1,200 Cr was announced", "Margins rose 35% in a year"):
        with pytest.raises(ValueError, match="numbers are not allowed"):
            md.validate({**GOOD, "bull": [bad]})
    with pytest.raises(ValueError, match="numbers are not allowed"):
        md.validate({**GOOD, "thesis_line": "It could rise 5x"})
    with pytest.raises(ValueError, match="what_would_break_it"):
        md.validate({**GOOD, "what_would_break_it": []})
    with pytest.raises(ValueError, match="thesis_line"):
        md.validate({**GOOD, "thesis_line": ""})


def test_mb_dossier_registered_and_drains_after_dossier():
    from alpha_mcp import tasks
    spec = tasks.TASK_KINDS["mb_dossier"]
    assert spec["batch"] == 1 and set(spec["schema"]["required"]) == set(GOOD)
    order = tasks.DRAIN_ORDER
    assert order.index("mb_dossier") == order.index("dossier") + 1


def test_mb_dossier_ingest_and_undo(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "q.db")
    db.init_db()
    with db.get_db() as c:
        c.execute("INSERT INTO stocks (sid, ticker, name) VALUES ('X1', 'XONE', 'X One')")
    from alpha_mcp import tasks
    k = tasks.TASK_KINDS["mb_dossier"]
    payload = {"sid": "X1", "ticker": "XONE", "_as_of": "2026-06-30"}
    clean = k["validate"](GOOD, payload)
    rec = k["ingest"](clean, payload)
    row = db.one("SELECT * FROM mb_dossiers WHERE sid = 'X1'")
    assert row["as_of_date"] == "2026-06-30" and json.loads(row["bull"]) == GOOD["bull"]
    k["undo"](rec)
    assert not db.one("SELECT * FROM mb_dossiers WHERE sid = 'X1'")


def test_mb_dossier_export_raises_without_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "q.db")
    db.init_db()
    from alpha_mcp import tasks
    with pytest.raises(ValueError, match="multibagger_book"):
        tasks.TASK_KINDS["mb_dossier"]["export"]()
