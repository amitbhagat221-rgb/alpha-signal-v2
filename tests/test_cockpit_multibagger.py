"""Multibagger desk pages (plan 0026 phase 5): every route renders on a database with empty desk tables (the
production state until the first approved run), renders the seeded rows on a temp database, the promote / hold /
drop endpoints write the book and its log and show the book's refusals, and no page prints nan / None."""
import contextlib
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

import config
import db
import webauth
from cockpit import _shared, multibagger as mb

ROOT = config.PROJECT_ROOT
SNAP = "2026-10-11"


def _make_db(path, seeded):
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE stocks (sid TEXT PRIMARY KEY, ticker TEXT NOT NULL, name TEXT NOT NULL, sector TEXT, industry TEXT,
        cap_tier TEXT, market_cap_cr REAL, adtv_6m_cr REAL, pe_ratio REAL, pb_ratio REAL, roe REAL, revenue_growth REAL,
        updated_at TEXT DEFAULT (datetime('now')))""")
    c.executescript((ROOT / "schema.sql").read_text())
    c.executemany("INSERT INTO stocks (sid, ticker, name, sector, industry, cap_tier, market_cap_cr, pe_ratio, pb_ratio) VALUES (?,?,?,?,?,?,?,?,?)", [
        ("AAA", "AAA", "Alpha Castings", "Industrials", "Castings", "SMALL", 900.0, 14.0, 1.2),
        ("BBB", "BBB", "Beta Foods", "Staples", "Packaged Food", "SMALL", 1500.0, 20.0, 2.0),
        ("CCC", "CCC", "Gamma Pumps", "Industrials", "Castings", "MID", 4100.0, 25.0, 3.1)])
    if seeded:
        rows = [("AAA", 1, "", .9, .8, .7, .6, .5, .70, 1.0, "top100", 1.4, 900.0),
                ("BBB", 1, "", .5, .6, .4, .3, .2, .40, 2.0, "top100", 0.9, 1500.0),
                ("CCC", 0, "mcap,adtv", None, None, None, None, None, None, None, None, 0.1, 4100.0)]
        for sid, pond, gf, a, b, cc, d, e, score, rank, stage, adtv, mcap in rows:
            c.execute("INSERT INTO multibagger_scores (sid, snapshot_date, thesis_pond, thesis_gate_fail, p_smallness, p_cheapness, "
                      "p_price, p_business, p_tailwind, thesis_score, thesis_rank, thesis_stage, adtv_cr, mcap_cr, cap_tier) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'SMALL')", (sid, SNAP, pond, gf, a, b, cc, d, e, score, rank, stage, adtv, mcap))
        for m, lo, mid, hi in [("pe_band", 80, 100, 130), ("pb_band", 90, 110, 150), ("dcf", 60, 140, 400), ("range_52w", 70, 95, 120)]:
            c.execute("INSERT INTO valuation_ranges VALUES ('AAA','2026-10-14',?,?,?,?,?,100,NULL)", (m, lo, mid, hi, f"{m} basis text"))
        c.execute("INSERT INTO valuation_ranges VALUES ('AAA','2026-10-14','analyst',NULL,NULL,NULL,'no analysts cover it',100,NULL)")
        c.execute("INSERT INTO valuation_ranges VALUES ('AAA','2026-10-14','reverse_dcf',NULL,NULL,NULL,'growth that equates',100,0.142)")
        c.execute("INSERT INTO mb_dossiers (sid, as_of_date, thesis_line, thesis, bull, bear, catalysts, risks, what_would_break_it) "
                  "VALUES ('AAA','2026-06-30','A castings maker turning the corner.','Results recovered.',?,?,?,?,?)",
                  tuple('["%s"]' % w for w in ("Margins up", "Premium to peers", "New plant", "Single customer", "Margins roll over")))
        import json as _json
        c.execute("INSERT INTO mb_research (sid, as_of_date, verdict, verdict_reason, multibagger_case, case_reason, n_red_flags, "
                  "n_high_flags, fields, report, model, created_at) VALUES ('AAA','2026-10-16','flag','Large sales to a promoter firm.',"
                  "'plausible','Capacity doubles by FY28.',1,0,?,?,'test','2026-10-16')",
                  (_json.dumps({"red_flags": [{"area": "related_party", "severity": "medium", "finding": "Sales to a promoter firm",
                                               "date": "2026-08-01", "source_url": "https://example.com/ar.pdf"}],
                                "red_flag_checks": {"auditor": "not_found"}, "catalysts_12m": ["New plant"],
                                "what_would_break_it": ["Customer loss"], "unknowns": ["Order book size"],
                                "sources": [{"n": 1, "url": "https://example.com/ar.pdf", "title": "Annual report FY26"}]}),
                   "Full research report text."))
        for i, (end, rev, pat) in enumerate([("2025-06-30", 100, 8), ("2025-09-30", 110, 9), ("2025-12-31", 120, 10), ("2026-03-31", 125, 11),
                                              ("2026-06-30", 140, 15)]):
            c.execute("INSERT INTO quarterly_income (sid, period, end_date, reporting, revenue, ebitda, net_income) VALUES "
                      "('AAA',?,?,'consolidated',?,?,?)", (end[:7], end, rev, rev * 0.2, pat))
        c.execute("INSERT INTO bse_announcements (news_id, scrip_cd, sid, headline, news_sub, category, subcategory, dt_tm, fetched_at) VALUES "
                  "('n1', 1, 'AAA', 'Order received', 'Order worth Rs 50 crore from Indian Railways', 'Company Update', "
                  "'Award of Order / Receipt of Order', datetime('now', '-5 days'), datetime('now'))")
        for d, px in [("2026-10-01", 98.0), ("2026-10-14", 112.0)]:
            c.execute("INSERT INTO stock_prices (sid, date, close) VALUES ('AAA', ?, ?)", (d, px))
        for d, px in [("2026-10-01", 15000.0), ("2026-10-14", 15300.0)]:
            c.execute("INSERT INTO nse_index_history (index_symbol, trade_date, close) VALUES ('NIFTY SMALLCAP 250', ?, ?)", (d, px))
    c.commit()
    c.close()


@contextlib.contextmanager
def _rw_get_db():
    """db.get_db on the temp DB. Written here because importing alpha_mcp (test_views does) swaps db.get_db for a
    read-only twin for the rest of the process."""
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _client(tmp_path, monkeypatch, seeded):
    path = tmp_path / "desk.db"
    _make_db(path, seeded)
    for mod in (db, config):
        monkeypatch.setattr(mod, "DB_PATH", path)
    from output import mb_book
    monkeypatch.setattr(db, "get_db", _rw_get_db)
    monkeypatch.setattr(mb_book, "get_db", _rw_get_db)
    monkeypatch.setattr(_shared, "_PERSISTED_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(webauth, "AUTH_FILE", tmp_path / "auth.json")
    monkeypatch.delenv("COCKPIT_PREVIEW", raising=False)
    webauth.set_password("correct horse battery")
    mb.clear_caches()
    from cockpit.app import app
    return TestClient(app, cookies={webauth.COOKIE: webauth.make_token()}), path


@pytest.fixture
def empty(tmp_path, monkeypatch):
    c, path = _client(tmp_path, monkeypatch, seeded=False)
    yield c
    mb.clear_caches()


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    c, path = _client(tmp_path, monkeypatch, seeded=True)
    c.dbpath = path
    yield c
    mb.clear_caches()


PAGES = ["/multibagger", "/partial/multibagger/funnel", "/partial/multibagger/candidates", "/partial/multibagger/held",
         "/partial/multibagger/watch", "/multibagger/valuation", "/multibagger/stock/AAA"]


def _visible(html):
    """The page text a reader sees (scripts and styles dropped)."""
    html = re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


def _assert_clean(html, where):
    text = _visible(html)
    bad = re.findall(r".{0,30}\b(?:nan|NaN|None|undefined|inf|Infinity)\b.{0,20}", text)
    assert not bad, (where, bad[:3])


def test_redirect_is_gone_and_page_is_in_the_rail(empty):
    r = empty.get("/multibagger", follow_redirects=False)
    assert r.status_code == 200 and "Multibagger" in r.text
    assert 'href="/multibagger"' in r.text


def test_every_route_renders_with_empty_tables(empty):
    for url in PAGES:
        r = empty.get(url)
        assert r.status_code == 200, url
        _assert_clean(r.text, url)
    assert "No thesis run yet" in empty.get("/partial/multibagger/funnel").text
    assert "No candidates yet" in empty.get("/partial/multibagger/candidates").text
    assert "Nothing held yet" in empty.get("/partial/multibagger/held").text
    assert "No names to watch yet" in empty.get("/partial/multibagger/watch").text
    assert "No candidates yet" in empty.get("/multibagger/valuation").text
    d = empty.get("/multibagger/stock/AAA").text
    assert "Valuation not computed yet" in d and "No note yet" in d and "Not in the book" in d
    assert "not loaded" in d                                         # the electoral-bond flag


def test_unknown_stock_and_tab(empty):
    assert empty.get("/multibagger/stock/NOPE").status_code == 404
    assert empty.get("/partial/multibagger/nope").status_code == 404
    assert empty.post("/api/multibagger/nope", json={}).status_code == 404


def test_every_route_renders_seeded(seeded):
    for url in PAGES:
        r = seeded.get(url)
        assert r.status_code == 200, url
        _assert_clean(r.text, url)
    f = seeded.get("/partial/multibagger/funnel").text
    assert "Grade C" in f and "ADR 0075" in f
    assert "Alpha Castings" in f and "Beta Foods" in f and "Gamma Pumps" not in f      # CCC missed the pond
    assert "Promote to candidates" in f
    assert "Market cap over" in f and "Daily turnover under" in f                                    # the gate-fail tally
    assert f.index("Alpha Castings") < f.index("Beta Foods")                             # thesis_rank order
    assert seeded.get("/multibagger").text.count("Candidates 0/30") == 1                 # tab label carries the list size


def test_book_actions_write_book_and_log(seeded):
    ok = seeded.post("/api/multibagger/promote", json={"sid": "AAA", "thesis_line": "Castings recovery", "reason": "Passed my read"})
    assert ok.status_code == 200 and ok.json()["ok"], ok.text
    c = sqlite3.connect(seeded.dbpath)
    assert c.execute("SELECT status, thesis_line FROM multibagger_book WHERE sid='AAA'").fetchone() == ("candidate", "Castings recovery")
    assert c.execute("SELECT action, actor FROM multibagger_book_log WHERE sid='AAA'").fetchall() == [("add_candidate", "cockpit")]

    html = seeded.get("/partial/multibagger/candidates").text
    assert "Alpha Castings" in html and "Castings recovery" in html and "Hold" in html and "Drop" in html
    _assert_clean(html, "candidates")
    assert "Candidate" in seeded.get("/partial/multibagger/funnel").text                  # the card shows its status, no button
    val = seeded.get("/multibagger/valuation").text
    assert "Alpha Castings" in val and "mb-ff-bar" in val and "reverse DCF" in val and "14.2%" in val

    assert seeded.post("/api/multibagger/hold", json={"sid": "AAA", "reason": "Conviction", "entry_price": "100"}).status_code == 200
    assert c.execute("SELECT status, entry_price FROM multibagger_book WHERE sid='AAA'").fetchone() == ("held", 100.0)
    held = seeded.get("/partial/multibagger/held").text
    assert "Alpha Castings" in held and "+12.0%" in held and "NIFTY SMALLCAP 250" in held       # 112 vs 100; index +2.0%
    assert "Conviction monitor, not an exit rule" in held
    assert "Indian Railways" in seeded.get("/partial/multibagger/watch").text

    assert seeded.post("/api/multibagger/drop", json={"sid": "AAA", "reason": "Thesis broke"}).status_code == 200
    assert [r[0] for r in c.execute("SELECT action FROM multibagger_book_log ORDER BY id")] == ["add_candidate", "hold", "drop"]
    assert "Nothing held yet" in seeded.get("/partial/multibagger/held").text
    c.close()


def test_refusals_come_back_inline(seeded):
    r = seeded.post("/api/multibagger/promote", json={"sid": "AAA", "thesis_line": "x", "reason": ""})
    assert r.status_code == 400 and "reason is required" in r.json()["error"]
    r = seeded.post("/api/multibagger/promote", json={"sid": "ZZZ", "thesis_line": "x", "reason": "y"})
    assert r.status_code == 400 and "not in the universe" in r.json()["error"]
    r = seeded.post("/api/multibagger/hold", json={"sid": "AAA", "reason": "y"})
    assert r.status_code == 400 and "only a candidate can be held" in r.json()["error"]
    seeded.post("/api/multibagger/promote", json={"sid": "AAA", "thesis_line": "x", "reason": "y"})
    assert "already candidate" in seeded.post("/api/multibagger/promote", json={"sid": "AAA", "thesis_line": "x", "reason": "y"}).json()["error"]
    assert "number" in seeded.post("/api/multibagger/hold", json={"sid": "AAA", "reason": "y", "entry_price": "abc"}).json()["error"]
    assert seeded.post("/api/multibagger/promote", content=b"not json", headers={"Content-Type": "application/json"}).status_code == 400
    assert seeded.post("/api/multibagger/promote", json={"thesis_line": "x", "reason": "y"}).status_code == 400


def test_the_caps_are_enforced_by_the_book_not_the_page(seeded, monkeypatch):
    monkeypatch.setitem(config.MB_THESIS, "max_book", 1)
    assert seeded.post("/api/multibagger/promote", json={"sid": "AAA", "thesis_line": "x", "reason": "y"}).status_code == 200
    r = seeded.post("/api/multibagger/promote", json={"sid": "BBB", "thesis_line": "x", "reason": "y"})
    assert r.status_code == 400 and "book is full" in r.json()["error"]
    assert "Candidates 1/1" in seeded.get("/multibagger").text


def test_writes_need_a_login_and_are_refused_in_preview(seeded, monkeypatch):
    anon = TestClient(seeded.app)
    assert anon.post("/api/multibagger/drop", json={"sid": "AAA", "reason": "x"}).status_code == 401
    monkeypatch.setenv("COCKPIT_PREVIEW", "1")
    r = seeded.post("/api/multibagger/promote", json={"sid": "AAA", "thesis_line": "x", "reason": "y"})
    assert r.status_code == 403 and "read-only" in r.json()["error"]


def test_deep_dive_sections_in_order(seeded):
    seeded.post("/api/multibagger/promote", json={"sid": "AAA", "thesis_line": "Castings recovery", "reason": "r"})
    html = seeded.get("/multibagger/stock/AAA").text
    heads = ["1. Valuation football field", "2. The note", "3. Results", "4. Ownership", "5. Event timeline",
             "6. Government and political links", "7. Peers", "8. Book status and log"]
    pos = [html.index(h) for h in heads]
    assert pos == sorted(pos)
    assert "A castings maker turning the corner." in html and "Margins roll over" in html and "Single customer" in html
    assert "Indian Railways" in html and 'href="/stocks/AAA"' in html and "not loaded" in html
    assert "Castings recovery" in html and "add candidate" in html
    assert "No shareholding filings on record" in html


def test_football_geometry():
    rows = [{"sid": "X", "as_of": "2026-10-14", "price": 100.0, "implied_growth_10y": None, "basis": "b", "method": m,
             "low": lo, "mid": mid, "high": hi}
            for m, lo, mid, hi in [("pe_band", 80, 100, 120), ("dcf", 50, 150, 900), ("analyst", None, None, None)]]
    f = mb._field("X", rows)
    ax = f["axis"]
    assert ax["hi"] <= 100 * 3 and ax["lo"] < 50
    pe = next(m for m in f["methods"] if m["key"] == "pe_band")
    assert 0 <= pe["left"] < pe["mid_at"] < pe["left"] + pe["width"] <= 100 and not pe["clipped"]
    assert next(m for m in f["methods"] if m["key"] == "dcf")["clipped"]                  # the bull case runs off the axis
    assert not next(m for m in f["methods"] if m["key"] == "analyst")["ok"]
    assert f["discount_pct"] == -20.0 and f["median_mid"] == 125.0                        # mids 100 and 150 -> median 125
    assert 0 < ax["price_at"] < 100 and f["n_methods"] == 2


def test_discount_sort_puts_the_cheapest_first(monkeypatch):
    fields = {"A": {"axis": {"lo": 0}, "discount_pct": -10.0, "as_of": "d"}, "B": {"axis": {"lo": 0}, "discount_pct": -30.0, "as_of": "d"},
              "C": {"axis": {"lo": 0}, "discount_pct": None, "as_of": "d"}}
    monkeypatch.setattr(mb, "book_rows", lambda status=None: [{"sid": s, "status": "candidate"} for s in "ABC"])
    monkeypatch.setattr(mb, "valuation_fields", lambda sids: fields)
    assert [i["sid"] for i in mb.valuation_page()["rows"]] == ["B", "A", "C"]


def test_tab_counts_never_blank_and_fields_print_their_axis(seeded):
    seeded.post("/api/multibagger/promote", json={"sid": "AAA", "thesis_line": "x", "reason": "y"})
    seeded.post("/api/multibagger/hold", json={"sid": "AAA", "reason": "y"})
    for tab in ("candidates", "held"):
        html = seeded.get(f"/partial/multibagger/{tab}").text
        assert 'data-max-book="30"' in html and 'data-n-book="1"' in html, tab
    val = seeded.get("/multibagger/valuation").text
    assert "mb-ff-axisv" in val and "₹80 &ndash;" not in val             # axis line; no mixed precision
    assert seeded.get("/multibagger/stock/AAA").text.count("Grade C") == 0
    assert seeded.get("/partial/multibagger/funnel").text.count("Grade C") == 1


def test_exit_flags_fire_on_process_events(monkeypatch):
    """ADR 0076: auditor resignation / GSM / overdue results -> exit; pledge > 50 % / promoter -5 pts -> review."""
    from datetime import date, timedelta
    import config
    d = (date.today() - timedelta(days=10)).isoformat()
    ev = [{"category": "auditor_resignation", "date": d, "source": "bse_announcements"}]
    monkeypatch.setattr(mb, "_events", lambda sid, days=365: ev)

    def one(sql, params=None):
        if "surveillance_flags" in sql:
            return {"d": d}
        if "quarterly_income" in sql:
            return {"d": (date.today() - timedelta(days=400)).isoformat()}
        if "corporate_adjustments" in sql:
            return {"d": d}
        if "total_shares" in sql:
            return {"end_date": d, "total_shares": 2.0e9}
        if "m.mcap_cr" in sql:
            return {"mcap_cr": 400.0, "close": 40.0}          # filing says 2e9 x 40 / 1e7 = 8,000 Cr: 20x
        return {}

    def rows(sql, params=None):
        if "surveillance_flags" in sql:
            return [{"flag_type": "GSM"}]
        if "shareholding_categories" in sql:
            return [{"end_date": d, "promoter_pct": 40.0}, {"end_date": d, "promoter_pct": 44.0}, {"end_date": d, "promoter_pct": 47.0}]
        return []
    monkeypatch.setattr(mb, "_one", one)
    monkeypatch.setattr(mb, "_surveillance_date", lambda: {"d": d})
    monkeypatch.setattr(mb, "_rows", rows)
    f = mb.exit_flags("X", {"pledge": {"pledge_pct": 62.0, "end_date": d}})
    kinds = {x["text"].split(":")[0]: x["kind"] for x in f}
    texts = " | ".join(x["text"] for x in f)
    assert "auditor resigned" in texts and "GSM" in texts and "results overdue" in texts, texts
    assert "pledge 62 %" in texts and "promoter down 7.0 pts" in texts and "demerged" in texts, texts
    assert "share count off 20.0x" in texts, texts
    assert kinds == {"Exit": "exit", "Review": "review"}
    assert config.MB_EXITS["pledge_review_pct"] == 50.0


def test_research_verdict_on_funnel_and_stock_page(seeded):
    """Plan 0026 stage 4b: the loaded research verdict shows as a chip on the funnel card and a section on the stock page."""
    funnel = seeded.get("/partial/multibagger/funnel").text
    assert "Research: flagged" in funnel and "5x plausible" in funnel
    page = seeded.get("/multibagger/stock/AAA").text
    assert "Deep research" in page and "Sales to a promoter firm" in page and "Full research report text." in page
    assert "Capacity doubles by FY28." in page and "Annual report FY26" in page
    assert "Not researched yet" in seeded.get("/multibagger/stock/BBB").text
