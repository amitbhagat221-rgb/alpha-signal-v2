"""Plan 0026 1d.8 on the cockpit: the Candidates and Held rows carry the capacity cap and its flag, and the Held tab opens with
the Paper books panel — an empty state without output/mb_paper/latest.json, three rows and the kill pills with it."""
import json
import sqlite3

import views
from tests.test_cockpit_multibagger import _assert_clean, empty, seeded  # noqa: F401  (fixtures)


def _volume(path, tv):
    c = sqlite3.connect(path)
    c.execute("UPDATE stock_prices SET traded_value = ?, volume = 1000", (tv,))
    c.commit()
    c.close()


def _book(client):
    client.post("/api/multibagger/promote", json={"sid": "AAA", "thesis_line": "x", "reason": "y"})
    client.post("/api/multibagger/hold", json={"sid": "AAA", "reason": "y", "entry_price": "100"})


def _report(**over):
    kills = [dict(key="score", label="Score", value=None, threshold=-5.0, state="early", state_text="too early (3 months)", detail="d1"),
             dict(key="human", label="Human", value=None, threshold=-10.0, state="early", state_text="no names held yet", detail="d2"),
             dict(key="risk", label="Risk", value=-40.0, threshold=-35.0, state="kill", state_text="KILL", detail="d3"),
             dict(key="capacity", label="Capacity", value=3.0, threshold=10.0, state="ok", state_text="ok", detail="d4")]
    book = lambda k, label, r: dict(key=k, label=label, rule="rule " + k, nav=1e6, nav_text="₹10.0 L", cash=0.0, ret_pct=r,
                                    vs_bench_pts=r - 2.0, n=3, note=None, positions=[])
    d = dict(asof="2026-10-02", start="2026-07-02", months=3, price_date="2026-10-01", score_date="2026-10-01", book_inr=3000000,
             book_text="₹30.0 L", bench="NIFTY SMALLCAP 250", bench_ret_pct=2.0,
             books=[book("pond", "Pond", 4.5), book("top30", "Top 30", 6.0), dict(book("amit10", "Amit 10", 0.0), n=0, note="in cash, no held names")],
             kills=kills, halted=True, history=[])
    d.update(over)
    return d


def test_held_tab_shows_the_empty_state_without_the_file(seeded, tmp_path, monkeypatch):
    monkeypatch.setattr(views, "MB_PAPER_FILE", tmp_path / "nope.json")
    html = seeded.get("/partial/multibagger/held").text
    assert "Paper books not started" in html and "run.sh mb_paper start" in html
    assert html.index("Paper books") < html.index("Nothing held yet")             # the panel sits at the top
    _assert_clean(html, "held (no file)")


def test_held_tab_shows_three_books_and_the_kill_pills(seeded, tmp_path, monkeypatch):
    f = tmp_path / "latest.json"
    f.write_text(json.dumps(_report()))
    monkeypatch.setattr(views, "MB_PAPER_FILE", f)
    _book(seeded)
    html = seeded.get("/partial/multibagger/held").text
    for label in ("Pond", "Top 30", "Amit 10"):
        assert label in html
    assert "+4.5%" in html and "+6.0%" in html and "in cash, no held names" in html
    assert "Score: too early (3 months)" in html and "Human: no names held yet" in html
    assert "Risk: KILL" in html and "pill-red" in html and "Capacity: ok" in html
    assert "New buying is halted" in html
    assert "Paper books not started" not in html
    _assert_clean(html, "held (file)")


def test_a_stale_file_says_so(seeded, tmp_path, monkeypatch):
    f = tmp_path / "latest.json"
    f.write_text(json.dumps(_report(asof="2020-01-02")))
    monkeypatch.setattr(views, "MB_PAPER_FILE", f)
    assert "monthly refresh missed" in seeded.get("/partial/multibagger/held").text


def test_rows_carry_the_cap_and_flag_a_book_too_big_for_the_stock(seeded):
    _volume(seeded.dbpath, 4e6)                                  # Rs 40 lakh a day -> max Rs 2 L at 5 %
    _book(seeded)
    cand = seeded.get("/partial/multibagger/candidates").text
    held = seeded.get("/partial/multibagger/held").text
    assert "max ₹2.0 L" in cand and "of a day" in cand
    assert "Too big" in cand and "Too big" in held                # held: Rs 30 L / 10 = Rs 3 L > Rs 2 L (a held row counts at /10)
    assert "max ₹2.0 L" in held and "Capacity" in held
    _volume(seeded.dbpath, 4e7)                                   # Rs 4 Cr a day -> max Rs 20 L
    from cockpit import multibagger as mb
    mb.clear_caches()
    assert "Too big" not in seeded.get("/partial/multibagger/held").text
    _assert_clean(held, "held")
    _assert_clean(cand, "candidates")


def test_candidate_rows_split_the_book_over_thirty(seeded):
    _volume(seeded.dbpath, 1e6)                                   # max Rs 50 k; a candidate gets Rs 30 L / 30 = Rs 1 L
    seeded.post("/api/multibagger/promote", json={"sid": "AAA", "thesis_line": "x", "reason": "y"})
    html = seeded.get("/partial/multibagger/candidates").text
    assert "max ₹50,000" in html and "Too big" in html
