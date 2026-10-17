"""Industry taxonomy and the reviewed corrections (2026-10-17: textiles had no industry and were filed as
paper, chemicals and retail). Offline: the taxonomy and the review list, plus a temp DB for apply()."""
import sqlite3

import pytest

import db
import signals.industry_id as iid
from tools import industry_audit as audit
from tools import industry_review as rev
from tools.classify_industries import ALL_INDUSTRIES, INDUSTRIES_BY_SECTOR
from tools.sector_narrative_fetcher import INDUSTRY_LIST


def test_one_taxonomy_everywhere():
    assert "Textiles & Apparel" in INDUSTRIES_BY_SECTOR["Consumer Discretionary"]
    assert set(INDUSTRY_LIST) == set(ALL_INDUSTRIES) == set(iid.INDUSTRIES)


def test_industry_codes_never_move():
    """industry_id is frozen: a new industry may only take the next code (it sorts last)."""
    assert iid.INDUSTRY_CODES["Telecom"] == 38 and iid.INDUSTRY_CODES["Textiles & Apparel"] == 39
    assert iid.INDUSTRY_CODES["Asset Management"] == 1


def test_every_reviewed_industry_is_in_the_taxonomy_and_has_a_reason():
    for t, (ind, why) in rev.REVIEWED.items():
        assert ind in ALL_INDUSTRIES, t
        assert why and len(why) > 3, t


def test_slug_identity_rejects_look_alikes():
    assert not audit.slug_matches("Trident Ltd", "trent")
    assert not audit.slug_matches("Ashoka Buildcon Ltd", "ashokleyland")
    assert audit.slug_matches("Swaraj Suiting Ltd", "swarajsuiting")
    assert audit.slug_matches("Tata Power Company Ltd", "thetatapowercompany")
    assert audit.slug_matches("Indian Railway Catering and Tourism Corporation Ltd", "irctc-indianrailwaycateringtourismcorp")


def test_every_textile_category_votes_textiles():
    tex = [c for c in audit.MC_ACCEPTS if c.startswith("textile") and c != "textiles-machinery"]
    assert len(tex) >= 15 and all(audit.MC_ACCEPTS[c] == ("Textiles & Apparel",) for c in tex)
    assert audit.MC_ACCEPTS["textiles-machinery"] == ("Capital Goods & Industrial Machinery",)


@pytest.fixture
def stocks_db(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE stocks (sid TEXT PRIMARY KEY, ticker TEXT, name TEXT, sector TEXT, industry TEXT)")
        c.executemany("INSERT INTO stocks VALUES (?,?,?,?,?)", [
            ("SWARA", "SWARAJ", "Swaraj Suiting Ltd", "Materials", "Paper, Wood & Forest Products"),
            ("KPRM", "KPRMILL", "KPR Mill Ltd", "Consumer Discretionary", None),
            ("INFY", "INFY", "Infosys Ltd", "Information Technology", "IT Services & ITeS")])
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(rev, "REVIEWED", {"SWARAJ": ("Textiles & Apparel", "suiting fabric"),
                                          "KPRMILL": ("Textiles & Apparel", "yarn and garments")})
    return path


def test_apply_moves_industry_and_sector_and_is_idempotent(stocks_db):
    assert len(rev.apply(dry_run=True)) == 2
    with sqlite3.connect(stocks_db) as c:
        assert c.execute("SELECT industry FROM stocks WHERE sid='SWARA'").fetchone()[0] == "Paper, Wood & Forest Products"
    assert len(rev.apply()) == 2
    with sqlite3.connect(stocks_db) as c:
        rows = dict((s, (i, sec)) for s, sec, i in c.execute("SELECT sid, sector, industry FROM stocks"))
    assert rows["SWARA"] == ("Textiles & Apparel", "Consumer Discretionary")
    assert rows["KPRM"] == ("Textiles & Apparel", "Consumer Discretionary")
    assert rows["INFY"] == ("IT Services & ITeS", "Information Technology")             # untouched
    assert rev.apply() == []                                                             # nothing left to do


def test_an_unknown_ticker_is_refused(stocks_db, monkeypatch):
    monkeypatch.setitem(rev.REVIEWED, "NOPE", ("Textiles & Apparel", "x"))
    with pytest.raises(ValueError, match="NOPE"):
        rev.plan()
