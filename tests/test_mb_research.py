"""
Plan 0026 stage 4b: the deep-research pack (3 real names, skipped without the live DB), the verdict validator,
and the loader's round trip into mb_research.
"""
import json

import pytest

import db

REAL = ["CONCO", "MARK", "ASTR"]


def _live():
    try:
        return bool(db.DB_PATH.exists() and db.one("SELECT 1 AS x FROM quarterly_income WHERE sid = 'CONCO' LIMIT 1"))
    except Exception:
        return False


live = pytest.mark.skipif(not _live(), reason="live DB not available (set ALPHA_DB)")


def good(sid="X1"):
    from output import mb_research as r
    return {"sid": sid, "ticker": "XONE", "as_of": "2026-10-16", "model": "test",
            "verdict": "flag", "verdict_reason": "Large related-party sales.",
            "multibagger_case": "plausible", "case_reason": "Capacity doubles by FY28.",
            "red_flags": [{"area": "related_party", "severity": "medium", "finding": "Sales to a promoter firm",
                           "date": "2026-08-01", "source_url": "https://example.com/ar.pdf"}],
            "red_flag_checks": {c: "not_found" for c in r.CHECKS},
            "business": {"what_it_does": "Makes widgets"}, "growth_drivers": [], "management": {},
            "govt_political_links": [], "funding_dilution": [], "catalysts_12m": [], "what_would_break_it": [],
            "unknowns": [], "sources": [{"n": i, "url": f"https://example.com/{i}"} for i in range(6)]}


REPORT = "word " * 700


def test_validate_accepts_a_good_verdict():
    from output import mb_research as r
    assert r.validate(good(), REPORT) == []


@pytest.mark.parametrize("change, problem", [
    (lambda v: v.update(verdict="maybe"), "verdict must be"),
    (lambda v: v.update(multibagger_case="huge"), "multibagger_case"),
    (lambda v: v.update(verdict="reject"), "reject needs"),
    (lambda v: v.update(verdict="clean", red_flags=[{**v["red_flags"][0], "severity": "high"}]), "means reject"),
    (lambda v: v.update(red_flags=[{**v["red_flags"][0], "severity": "high"}]), "means reject"),
    (lambda v: v["red_flags"][0].pop("source_url"), "source_url required"),
    (lambda v: v["red_flag_checks"].pop("auditor"), "red_flag_checks"),
    (lambda v: v.update(sources=v["sources"][:3]), "web sources"),
    (lambda v: v.pop("unknowns"), "unknowns"),
])
def test_validate_rejects(change, problem):
    from output import mb_research as r
    v = good()
    change(v)
    assert any(problem in p for p in r.validate(v, REPORT)), r.validate(v, REPORT)


def test_validate_short_report():
    from output import mb_research as r
    assert any("600 words" in p for p in r.validate(good(), "too short"))


def test_load_round_trip(tmp_path, monkeypatch):
    from output import mb_research as r
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "q.db")
    db.init_db()
    with db.get_db() as c:
        c.execute("INSERT INTO stocks (sid, ticker, name) VALUES ('X1', 'XONE', 'X One')")
    tmp_path = tmp_path / "res"
    monkeypatch.setattr(r, "ROOT", tmp_path)
    (tmp_path / "X1").mkdir(parents=True)
    (tmp_path / "X1" / "verdict.json").write_text(json.dumps(good()))
    (tmp_path / "X1" / "report.md").write_text(REPORT)
    (tmp_path / "X2").mkdir()
    (tmp_path / "X2" / "verdict.json").write_text(json.dumps(good("X1")))     # sid does not match its folder
    (tmp_path / "X2" / "report.md").write_text(REPORT)
    res = r.load()
    assert res["X1"] == [] and any("does not match" in p for p in res["X2"])
    got = r.latest("X1")
    assert got["verdict"] == "flag" and got["n_red_flags"] == 1 and got["n_high_flags"] == 0
    assert got["fields"]["business"]["what_it_does"] == "Makes widgets" and got["report"] == REPORT


@live
@pytest.mark.parametrize("sid", REAL)
def test_pack_real(sid):
    from output import mb_research as r
    p = r.pack(sid)
    assert len(p.encode()) <= r.MAX_PACK_BYTES
    for h in ("## 0. Data warnings", "## 2. Annual financials", "## 5. Ownership", "## 10. Filings on file",
              "## 12. Gaps"):
        assert h in p, h
    assert "AttachLive" not in p.split("## 7.")[0]          # filing links use the archive path that serves all


def test_points_weigh_integrity_double_and_cap():
    """Overlay: medium integrity 0.015, medium business 0.008, low 0.005 / 0.003; capped; 5x case adds points."""
    from output import mb_research as r
    from config import MB_THESIS
    f = {"multibagger_case": "plausible", "red_flags": [
        {"area": "related_party", "severity": "medium"}, {"area": "business", "severity": "medium"},
        {"area": "audit", "severity": "low"}, {"area": "liquidity_debt", "severity": "low"}]}
    pen, bon, n = r.points(f)
    assert pen == round(0.015 + 0.008 + 0.005 + 0.003, 4) and bon == 0.04
    assert n["integrity"] == {"medium": 1, "low": 1} and n["business"] == {"medium": 1, "low": 1}
    many = {"multibagger_case": "weak", "red_flags": [{"area": "governance", "severity": "medium"}] * 50}
    assert r.points(many)[0] == MB_THESIS["research_overlay"]["max_penalty"] and r.points(many)[1] == 0.0
