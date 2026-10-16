"""The multibagger desk's capacity cap and three forward paper books (plan 0026 phase 1d.8, research 0008 sections 3 and 6):
the cap arithmetic, a pond / top 30 / amit10 lifecycle on a temp database with 5 fake stocks over 14 months (including a
split), every kill rule firing on constructed data, and the report file the cockpit reads."""
import json
import sqlite3
from datetime import date, timedelta

import pytest

import config
from output import mb_capacity
from tools import mb_paper

ROOT = config.PROJECT_ROOT
SIDS = ["AAA", "BBB", "CCC", "DDD", "EEE"]


# ── capacity cap ────────────────────────────────────────────────────────────────────────────────

def _reader(rows):
    def read(sql, params=None):
        if "DISTINCT date" in sql:
            return [{"date": f"2026-10-{d:02d}"} for d in range(20, 0, -1)]
        return rows
    return read


def test_adv_is_the_median_with_missing_sessions_as_zero():
    # AAA traded on all 20 sessions (1 Cr each); BBB on 8 of 20 (1 Cr each): median of 8 trades + 12 zeros = 0
    rows = [{"sid": "AAA", "tv": 1e7}] * 20 + [{"sid": "BBB", "tv": 1e7}] * 8
    adv = mb_capacity.adv_inr(_reader(rows), ["AAA", "BBB"], "2026-10-20")
    assert adv == {"AAA": 1e7, "BBB": 0.0}


def test_max_position_is_five_percent_and_flags_the_per_name_amount():
    assert config.MB_THESIS["max_adv_share"] == 0.05 and config.MB_THESIS["book_inr"] == 3_000_000
    rows = [{"sid": "BIG", "tv": 4e6}] * 20 + [{"sid": "THIN", "tv": 1e6}] * 20           # Rs 40 lakh and Rs 10 lakh a day
    cap = mb_capacity.capacity(_reader(rows), ["BIG", "THIN"], max_names=30)
    assert cap["BIG"]["max_inr"] == pytest.approx(2e5) and cap["BIG"]["per_name_inr"] == pytest.approx(1e5)
    assert cap["BIG"]["too_big"] is False
    assert cap["THIN"]["max_inr"] == pytest.approx(5e4) and cap["THIN"]["too_big"] is True       # Rs 1 L > Rs 50 k
    assert cap["THIN"]["share"] == pytest.approx(0.1)
    held = mb_capacity.capacity(_reader(rows), ["BIG"], max_names=10)                              # 30 L / 10 = 3 L > 2 L max
    assert held["BIG"]["per_name_inr"] == pytest.approx(3e5) and held["BIG"]["too_big"] is True


def test_adv_ignores_other_sessions_and_empty_input():
    assert mb_capacity.adv_inr(_reader([]), []) == {}
    assert mb_capacity.inr_short(None) is None
    assert mb_capacity.inr_short(1.25e7) == "₹1.2 Cr" or mb_capacity.inr_short(1.25e7) == "₹1.3 Cr"
    assert mb_capacity.inr_short(420_000) == "₹4.2 L" and mb_capacity.inr_short(9_500) == "₹9,500"


# ── the books on a temp database ────────────────────────────────────────────────────────────────

def _weekdays(d0, d1):
    d = d0
    while d <= d1:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def _make_db(path):
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE stocks (sid TEXT PRIMARY KEY, ticker TEXT NOT NULL, name TEXT NOT NULL, sector TEXT, industry TEXT,
        cap_tier TEXT, market_cap_cr REAL, adtv_6m_cr REAL, pe_ratio REAL, pb_ratio REAL, roe REAL, revenue_growth REAL,
        updated_at TEXT DEFAULT (datetime('now')))""")
    c.executescript((ROOT / "schema.sql").read_text())
    for s in SIDS:
        c.execute("INSERT INTO stocks (sid, ticker, name, cap_tier) VALUES (?,?,?, 'SMALL')", (s, s, f"{s} Ltd"))
    # thesis run of 2025-09-30: all five in the pond, ranked AAA..EEE
    for i, s in enumerate(SIDS):
        c.execute("INSERT INTO multibagger_scores (sid, snapshot_date, thesis_pond, thesis_score, thesis_rank, thesis_stage) "
                  "VALUES (?, '2025-09-30', 1, ?, ?, 'top100')", (s, 1 - i / 10, i + 1))
    # prices: flat Rs 100 (AAA grows 1 %/month, EEE falls 2 %/month); CCC splits 1:2 on 2026-03-10 (close halves, factor 0.5)
    for d in _weekdays(date(2025, 9, 1), date(2026, 12, 4)):
        m = (d.year - 2025) * 12 + d.month - 9
        for s in SIDS:
            px = {"AAA": 100 * 1.01 ** m, "BBB": 100.0, "CCC": 100.0 * 1.005 ** m, "DDD": 100.0, "EEE": 100 * 0.98 ** m}[s]
            if s == "CCC" and d >= date(2026, 3, 10):
                px /= 2
            c.execute("INSERT INTO stock_prices (sid, date, close, volume, traded_value) VALUES (?,?,?,?,?)",
                      (s, d.isoformat(), px, 100_000, px * 100_000))            # Rs 1 Cr a day
        c.execute("INSERT INTO nse_index_history (index_symbol, trade_date, close) VALUES ('NIFTY SMALLCAP 250', ?, ?)",
                  (d.isoformat(), 15000 * 1.005 ** m))
    c.execute("INSERT INTO corporate_adjustments (sid, ex_date, factor, n_events, inds) VALUES ('CCC', '2026-03-10', 0.5, 1, 'SPLIT')")
    c.commit()
    c.close()


@pytest.fixture
def books(tmp_path, monkeypatch):
    path = tmp_path / "desk.db"
    _make_db(path)
    monkeypatch.setattr(mb_paper, "DB", path)
    monkeypatch.setattr(mb_paper, "STATE", tmp_path / "paper" / "mb_books.json")
    monkeypatch.setattr(mb_paper, "OUT", tmp_path / "out")
    monkeypatch.setattr(mb_paper, "cost_bps", lambda adv, price, trade, tier: 10.0)
    monkeypatch.setitem(config.MB_THESIS, "paper_top_n", 3)
    monkeypatch.setitem(config.MB_THESIS, "book_inr", 1_000_000)
    return path


def _hold(path, sid, on=True):
    c = sqlite3.connect(path)
    if on:
        c.execute("INSERT OR REPLACE INTO multibagger_book (sid, status, since, reason, updated_at) VALUES (?, 'held', '2026-01-01', 'r', 'now')", (sid,))
    else:
        c.execute("DELETE FROM multibagger_book WHERE sid = ?", (sid,))
    c.commit()
    c.close()


def test_start_buys_equal_weights_and_refuses_twice(books, capsys):
    rep = mb_paper.start("2025-10-01")
    st = json.loads(mb_paper.STATE.read_text())
    assert {k: len(b["positions"]) for k, b in st["books"].items()} == {"pond": 5, "top30": 3, "amit10": 0}
    for sid, p in st["books"]["pond"]["positions"].items():
        assert p["value"] == pytest.approx(1_000_000 / 5 * (1 - 0.001), rel=1e-6)          # 10 bps cost
    assert set(st["books"]["top30"]["positions"]) == {"AAA", "BBB", "CCC"}                  # best three ranks
    assert st["books"]["amit10"]["cash"] == 1_000_000
    amit = next(b for b in rep["books"] if b["key"] == "amit10")
    assert amit["n"] == 0 and amit["note"] == "in cash, no held names" and amit["ret_pct"] == 0.0
    with pytest.raises(SystemExit, match="already started"):
        mb_paper.start("2025-10-01")


def test_fourteen_months_split_follow_the_book_and_yearly_rebuild(books):
    mb_paper.start("2025-10-01")
    marks = [date(2025 + (9 + i) // 12, (9 + i) % 12 + 1, 1) for i in range(1, 14)]          # 2025-11-01 .. 2026-11-01
    for d in marks:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        if d == date(2026, 6, 1):
            _hold(books, "EEE")                                                              # Amit holds a loser
        if d == date(2026, 9, 1):
            _hold(books, "EEE", on=False)
            _hold(books, "AAA")
        rep = mb_paper.mark(d.isoformat())
        if d == date(2026, 3, 2):                                                            # before the split
            pre_split = json.loads(mb_paper.STATE.read_text())["books"]["pond"]["positions"]["CCC"]["value"]
        if d == date(2026, 4, 1):                                                            # after it: value kept, not halved
            post = json.loads(mb_paper.STATE.read_text())["books"]["pond"]["positions"]["CCC"]["value"]
            assert post == pytest.approx(pre_split * 1.005 ** 1, rel=0.02)
    st = json.loads(mb_paper.STATE.read_text())
    assert rep["months"] == 13 and len(st["history"]) == 14
    # amit10 bought EEE in June (a loser) and sold it in September, then held AAA
    assert [c["sid"] for c in st["books"]["amit10"]["closed"]] == ["EEE"] and st["books"]["amit10"]["closed"][0]["ret"] < 0
    assert set(st["books"]["amit10"]["positions"]) == {"AAA"}
    # the yearly rebuild ran at the first mark a full year on
    assert st["last_rebalance"] == {"pond": "2026-10-01", "top30": "2026-10-01"}
    assert any(t["why"] == "yearly rebuild" for t in st["trades"])
    # the books: top30 (AAA, BBB, CCC) beats the pond (which holds the falling EEE), both against the index
    by = {b["key"]: b for b in rep["books"]}
    assert by["top30"]["ret_pct"] > by["pond"]["ret_pct"]
    assert rep["bench_ret_pct"] == pytest.approx(((1.005 ** 13) - 1) * 100, abs=1.0)
    # before 24 months the judged kills say so
    kills = {k["key"]: k for k in rep["kills"]}
    assert kills["score"]["state"] == "early" and kills["score"]["state_text"] == "too early (13 months)"
    assert kills["human"]["state"] == "early" and kills["risk"]["state"] == "ok"
    # the 13-month rolling excess is nowhere near -35 %; amit10 holds one name = the whole Rs 10 L book = 8-9 % of its
    # Rs 1.2 Cr day: past the 5 % watch line, under the 10 % kill
    assert kills["risk"]["state"] == "ok" and kills["capacity"]["state"] == "warn" and rep["halted"] is False


def test_status_rewrites_the_report_without_trading(books):
    mb_paper.start("2025-10-01")
    mb_paper.mark("2025-11-03")
    before = json.loads(mb_paper.STATE.read_text())
    (mb_paper.OUT / "latest.json").unlink()
    mb_paper.status(None)
    assert json.loads(mb_paper.STATE.read_text()) == before
    rep = json.loads((mb_paper.OUT / "latest.json").read_text())
    assert rep["asof"] == "2025-11-03" and [b["key"] for b in rep["books"]] == ["pond", "top30", "amit10"]
    assert (mb_paper.OUT / "latest.md").read_text().startswith("# Multibagger paper books")


def test_mark_and_status_before_start_refuse(books):
    with pytest.raises(SystemExit, match="not started"):
        mb_paper.mark("2025-11-03")


def test_start_with_an_empty_pond_raises(books):
    c = sqlite3.connect(books)
    c.execute("UPDATE multibagger_scores SET thesis_pond = 0")
    c.commit()
    c.close()
    with pytest.raises(SystemExit, match="empty pond"):
        mb_paper.start("2025-10-01")
    assert not mb_paper.STATE.exists()


def test_halt_buys_sells_but_never_buys(books):
    mb_paper.start("2025-10-01")
    st = json.loads(mb_paper.STATE.read_text())
    ctx = mb_paper._context(st, {"DDD", "EEE"}, "2025-11-03")
    n_trades = len(st["trades"])
    mb_paper.rebalance_to(st, "top30", ["DDD", "EEE"], ctx, "2025-11-03", "t", halt_buys=True)
    assert set(st["books"]["top30"]["positions"]) == set()                       # all three sold, nothing bought
    assert all(t["side"] == "SELL" for t in st["trades"][n_trades:])
    assert st["books"]["top30"]["cash"] == pytest.approx(1_000_000 * 0.999 ** 2, rel=1e-3)


# ── the kill rules, on constructed histories ────────────────────────────────────────────────────

def _hist(n_months, nav, bench=None):
    """One row per month from 2024-01-02; nav = {book: f(i)} and bench f(i) as multiples of the start."""
    rows = []
    for i in range(n_months + 1):
        d = date(2024 + i // 12, i % 12 + 1, 2).isoformat()
        rows.append(dict(date=d, price_date=d, bench_date=d, bench=15000 * (bench(i) if bench else 1.0),
                         nav={k: 1_000_000 * f(i) for k, f in nav.items()}, n={}))
    return rows


def _state(positions=None, closed=None):
    pos = lambda v, r=0.0: dict(entry_date="2024-01-02", invested=v, proceeds=0.0, value=v * (1 + r), last_date="d", last_close=1)
    mk = lambda ps=None, cl=None: dict(cash=0.0, positions=ps or {}, closed=cl or [])
    return dict(start="2024-01-02", bench_start=15000, book_inr=1_000_000,
                books={"pond": mk(), "top30": mk(positions and positions.get("top30")), "amit10": mk(positions and positions.get("amit10"), closed)})


def _kill(kills, key):
    return next(k for k in kills if k["key"] == key)


def test_score_kill_fires_after_24_months_only():
    flat = lambda i: 1.0
    nav = {"pond": lambda i: 1 + 0.01 * i, "top30": lambda i: 1 + 0.01 * i - 0.06 * (i >= 12), "amit10": flat}
    st = _state()
    late = _kill(mb_paper.evaluate(st, _hist(24, nav), {}), "score")
    assert late["state"] == "kill" and late["value"] == pytest.approx(-6.0)
    early = _kill(mb_paper.evaluate(st, _hist(23, nav), {}), "score")
    assert early["state"] == "early" and early["state_text"] == "too early (23 months)"
    ok_nav = dict(nav, top30=lambda i: 1 + 0.01 * i - 0.02 * (i >= 1))
    assert _kill(mb_paper.evaluate(st, _hist(24, ok_nav), {}), "score")["state"] == "ok"
    warn_nav = dict(nav, top30=lambda i: 1 + 0.01 * i - 0.03 * (i >= 1))
    assert _kill(mb_paper.evaluate(st, _hist(24, warn_nav), {}), "score")["state"] == "warn"


def test_human_kill_on_points_and_on_hit_rate():
    nav = {"pond": lambda i: 1.0, "top30": lambda i: 1 + 0.01 * i, "amit10": lambda i: 1 + 0.01 * i - 0.12 * (i >= 12)}
    pos = lambda r: {"X": dict(entry_date="2024-01-02", invested=100.0, proceeds=0.0, value=100.0 * (1 + r), last_date="d", last_close=1)}
    st = _state(positions={"top30": pos(0.6), "amit10": pos(0.1)})
    assert _kill(mb_paper.evaluate(st, _hist(24, nav), {}), "human")["state"] == "kill"            # 12 points behind
    near = {"pond": lambda i: 1.0, "top30": lambda i: 1 + 0.01 * i, "amit10": lambda i: 1 + 0.01 * i}
    k = _kill(mb_paper.evaluate(st, _hist(24, near), {}), "human")
    assert k["state"] == "kill" and "below it is a kill" in k["detail"]                              # level on points, fewer names up 50 %
    st_ok = _state(positions={"top30": pos(0.6), "amit10": pos(0.7)})
    assert _kill(mb_paper.evaluate(st_ok, _hist(24, near), {}), "human")["state"] == "ok"
    assert _kill(mb_paper.evaluate(_state(), _hist(24, near), {}), "human")["state_text"] == "no names held yet"
    assert _kill(mb_paper.evaluate(st, _hist(12, near), {}), "human")["state"] == "early"


def test_risk_kill_halts_new_buying():
    nav = {"pond": lambda i: 1.0, "top30": lambda i: 1.0 if i < 12 else 0.6, "amit10": lambda i: 1.0}   # -40 % in a year, index flat
    k = mb_paper.evaluate(_state(), _hist(14, nav), {})
    assert _kill(k, "risk")["state"] == "kill" and _kill(k, "risk")["value"] < -35 and mb_paper.halted(k)
    assert _kill(mb_paper.evaluate(_state(), _hist(10, nav), {}), "risk")["value"] is None             # < 12 months of history
    mild = {"pond": lambda i: 1.0, "top30": lambda i: 1.0 if i < 12 else 0.8, "amit10": lambda i: 1.0}
    assert _kill(mb_paper.evaluate(_state(), _hist(14, mild), {}), "risk")["state"] == "warn"         # -20 %: past half of -35
    bear = {"pond": lambda i: 1.0, "top30": lambda i: 1.0 if i < 12 else 0.6, "amit10": lambda i: 1.0}
    # an index that falls just as far is not an excess loss
    k = mb_paper.evaluate(_state(), _hist(14, bear, bench=lambda i: 1.0 if i < 12 else 0.6), {})
    assert _kill(k, "risk")["state"] == "ok" and not mb_paper.halted(k)


def test_risk_kill_exempts_a_momentum_crash():
    """Research 0008 round 2: a junk rally (pond +60 %) in which the top 30 lags the index by 40 points is not a halt."""
    nav = {"pond": lambda i: 1.0 if i < 12 else 1.6, "top30": lambda i: 1.0 if i < 12 else 1.2, "amit10": lambda i: 1.0}
    k = mb_paper.evaluate(_state(), _hist(14, nav, bench=lambda i: 1.0 if i < 12 else 1.6), {})
    r = _kill(k, "risk")
    assert r["state"] == "ok" and not mb_paper.halted(k) and "momentum crash" in r["detail"]
    calm = {"pond": lambda i: 1.0 if i < 12 else 1.1, "top30": lambda i: 1.0 if i < 12 else 0.6, "amit10": lambda i: 1.0}
    assert _kill(mb_paper.evaluate(_state(), _hist(14, calm), {}), "risk")["state"] == "kill"     # pond +10 %: no exemption


def test_capacity_kill_on_share_of_adtv():
    pos = lambda v: {"X": dict(entry_date="d", invested=v, proceeds=0.0, value=v, last_date="d", last_close=1)}
    hist = _hist(3, {"pond": lambda i: 1.0, "top30": lambda i: 1.0, "amit10": lambda i: 1.0})
    adv = {"X": 1_000_000.0}
    ok = mb_paper.evaluate(_state(positions={"top30": pos(40_000.0)}), hist, adv)                 # 4 %
    warn = mb_paper.evaluate(_state(positions={"top30": pos(70_000.0)}), hist, adv)               # 7 %
    kill = mb_paper.evaluate(_state(positions={"amit10": pos(150_000.0)}), hist, adv)             # 15 %
    assert [_kill(x, "capacity")["state"] for x in (ok, warn, kill)] == ["ok", "warn", "kill"]
    assert _kill(kill, "capacity")["value"] == 15.0 and mb_paper.halted(kill) and not mb_paper.halted(warn)
    assert "no traded value" in _kill(mb_paper.evaluate(_state(positions={"top30": pos(1.0)}), hist, {}), "capacity")["detail"]
