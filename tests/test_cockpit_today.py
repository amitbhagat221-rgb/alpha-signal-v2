"""Cockpit v2 Today page: book diff -> buys/sells, latest-forensic filter, Financials skip Altman Z,
results due, the 'nothing to do' state. Offline: pure functions plus a temp SQLite DB."""
import sqlite3

import pytest

import db
import views
from cockpit import today

FIN = ["Financials"]


def b(sid, w=0.1, tier="MID"):
    return {"sid": sid, "ticker": sid, "weight": w, "cap_tier": tier, "rank": 1}


def test_book_diff_buys_and_sells():
    buys, sells, resizes = today.diff_books([b("A"), b("C"), b("D")], [b("A"), b("B")])
    assert [r["sid"] for r in buys] == ["C", "D"]
    assert [r["sid"] for r in sells] == ["B"]
    assert resizes == []


def test_book_diff_resize_only_above_threshold():
    _, _, rs = today.diff_books([b("A", 0.080), b("B", 0.0705)], [b("A", 0.070), b("B", 0.07)])
    assert [(r["sid"], r["prev_weight"]) for r in rs] == [("A", 0.070)]      # 1 pp moves, 0.05 pp does not


def test_no_previous_book_is_not_a_buy_everything_day():
    assert today.diff_books([b("A")], None) == ([], [], [])
    sentence, nothing = today.headline([], [], [], [], has_prev=False)
    assert "No earlier book" in sentence and not nothing


def test_headline_counts_and_nothing_to_do():
    s, nothing = today.headline([1, 2, 3], [1, 2], [], [1])
    assert s == "Today: 3 buys · 2 sells · 1 check" and not nothing
    s, nothing = today.headline([1], [], [], [])
    assert s == "Today: 1 buy"
    s, nothing = today.headline([], [], [], [])
    assert s.startswith("Nothing to do") and nothing


def test_financials_skip_altman_z_but_keep_beneish():
    meta = {"BANK": {"ticker": "BANK", "tier": "LARGE", "sector": "Financials", "source": "in book"},
            "STEEL": {"ticker": "STEEL", "tier": "MID", "sector": "Materials", "source": "in book"}}
    flags = {"BANK": {"as_of": "2026-10-04", "m_flag": None, "z_flag": "DISTRESS"},
             "STEEL": {"as_of": "2026-10-04", "m_flag": "LIKELY_MANIPULATOR", "z_flag": "DISTRESS"}}
    checks = today.build_checks(flags, {}, meta, FIN)
    assert [(c["ticker"], c["text"]) for c in checks] == [
        ("STEEL", "Reported profits look flattered"), ("STEEL", "Balance sheet in the distress zone")]
    bank_m = today.build_checks({"BANK": {"as_of": "x", "m_flag": "LIKELY_MANIPULATOR", "z_flag": None}}, {}, meta, FIN)
    assert len(bank_m) == 1


def test_checks_order_results_first_and_only_known_names():
    meta = {"A": {"ticker": "A", "tier": "MID", "sector": "X", "source": "top pick"},
            "B": {"ticker": "B", "tier": "MID", "sector": "X", "source": "in book"}}
    due = {"A": {"date": "2026-10-14", "days": 4, "purpose": "Financial Results"},
           "B": {"date": "2026-10-12", "days": 2, "purpose": "Financial Results"},
           "ZZ": {"date": "2026-10-12", "days": 2, "purpose": "Financial Results"}}
    flags = {"A": {"as_of": "d", "m_flag": "LIKELY_MANIPULATOR", "z_flag": None}}
    out = today.build_checks(flags, due, meta, FIN)
    assert [(c["ticker"], c["kind"]) for c in out] == [("B", "results"), ("A", "results"), ("A", "forensic")]
    assert out[0]["text"] == "Results in 2 days"


def test_rank_movers_only_big_moves_near_the_top():
    cur = [{"sid": "A", "ticker": "A", "cap_tier": "MID", "rank": 3, "final_score": .7},
           {"sid": "B", "ticker": "B", "cap_tier": "MID", "rank": 500, "final_score": .2},
           {"sid": "C", "ticker": "C", "cap_tier": "MID", "rank": 10, "final_score": .6},
           {"sid": "N", "ticker": "N", "cap_tier": "MID", "rank": 1, "final_score": .9}]
    prev = [{"sid": "A", "rank": 12}, {"sid": "B", "rank": 520}, {"sid": "C", "rank": 8}]
    out = today.rank_movers(cur, prev)
    assert list(out) == ["MID"] and [m["sid"] for m in out["MID"]] == ["A"]    # B far from top, C <5 places, N new


@pytest.fixture
def tmpdb(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE stocks (sid TEXT PRIMARY KEY, ticker TEXT, name TEXT);
        CREATE TABLE portfolio_weights (asof_date TEXT, sid TEXT, weight REAL, factor_score REAL,
            marginal_risk_contrib REAL, cap_tier TEXT, sector TEXT, name TEXT, rank INTEGER);
        CREATE TABLE forensic_scores (sid TEXT, snapshot_date TEXT, m_score REAL, m_score_flag TEXT,
            z_score REAL, z_score_flag TEXT, penalty REAL);
        CREATE TABLE earnings_calendar (id INTEGER PRIMARY KEY, date TEXT, symbol TEXT, sid TEXT,
            name TEXT, purpose TEXT, bm_desc TEXT);
        INSERT INTO stocks VALUES ('A','AAA','A Ltd'),('B','BBB','B Ltd');
        INSERT INTO portfolio_weights (asof_date, sid, weight, cap_tier, sector, rank) VALUES
            ('2026-10-02','A',.5,'MID','X',1),('2026-10-02','B',.5,'MID','X',2),
            ('2026-10-03','A',1.0,'MID','X',1);
        INSERT INTO forensic_scores VALUES ('A','2026-09-01',0,'LIKELY_MANIPULATOR',0,'DISTRESS',0),
            ('A','2026-10-01',0,'CLEAN',0,'SAFE',0),
            ('B','2026-09-01',0,'CLEAN',0,'SAFE',0),('B','2026-10-01',0,'LIKELY_MANIPULATOR',0,'GREY_ZONE',0);
        INSERT INTO earnings_calendar (date, sid, purpose) VALUES
            ('2026-10-12','A','Financial Results'),('2026-10-14','A','Financial Results'),
            ('2026-10-13','B','Dividend'),('2026-10-30','B','Financial Results');
    """)
    c.commit()
    c.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def test_book_history_newest_first(tmpdb):
    h = views.book_history(2)
    assert [x["asof"] for x in h] == ["2026-10-03", "2026-10-02"]
    buys, sells, _ = today.diff_books(h[0]["rows"], h[1]["rows"])
    assert buys == [] and [r["ticker"] for r in sells] == ["BBB"]


def test_forensic_flags_use_the_latest_row_only(tmpdb):
    f = views.forensic_flags(["A", "B"])
    assert list(f) == ["B"]                      # A's old flags are superseded by a clean newest row
    assert f["B"]["m_flag"] == "LIKELY_MANIPULATOR" and f["B"]["z_flag"] is None and f["B"]["as_of"] == "2026-10-01"


def test_results_due_next_result_within_window_only(tmpdb):
    d = views.results_due(["A", "B"], days=7, today="2026-10-10")
    assert d == {"A": {"date": "2026-10-12", "purpose": "Financial Results", "days": 2}}   # B: dividend / too far
    assert views.results_due([], today="2026-10-10") == {}
