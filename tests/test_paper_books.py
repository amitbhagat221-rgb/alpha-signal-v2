"""Paper books (Amit 2026-11-01): six strategies of ₹10 L each from June 2026. The engine is tested on a tiny
synthetic market (no DB, no parquet): a buy at the first anchor, a sell on a rank fall, the costs split out with
STT on its own, 20.8 % short-term tax only on a net gain, rotations counted from the second anchor. The page reads
ONE file through views.paper_books (missing = {}, old = stale) and the Book page keeps only Zerodha + Track record."""
import json
from datetime import date

import pandas as pd
import pytest

import views
from tools import paper_books as pb


def _market():
    """Three stocks, three anchors; AAA doubles, BBB halves, CCC flat. ADTV far above the ₹1 cr floor."""
    rows = []
    sessions = ["2026-06-01", "2026-07-01", "2026-08-03"]
    px = {"AAA": [100, 150, 200], "BBB": [100, 80, 50], "CCC": [100, 100, 100]}
    for sid, closes in px.items():
        for d, c in zip(sessions, closes):
            rows.append(dict(sid=sid, date=d, close=float(c), adj_close=float(c), adtv=5e8))
    df = pd.DataFrame(rows).set_index(["sid", "date"])
    bench = pd.Series({("IDX", d): v for d, v in zip(sessions, [100.0, 110.0, 120.0])})
    bench.index = pd.MultiIndex.from_tuples(bench.index, names=["index_symbol", "date"])
    meta = pd.DataFrame({"ticker": ["AAA", "BBB", "CCC"], "cap_tier": ["SMALL"] * 3}, index=["AAA", "BBB", "CCC"])
    return pb.Prices(df, sessions), meta, bench, sessions


@pytest.fixture
def toy(monkeypatch):
    monkeypatch.setitem(pb.BOOKS, "toy", dict(label="Toy", tier="SMALL", kind="fast", bench={"IDX": 1.0}, N=2, rule="", min_hold_m=0))
    return _market()


def test_buy_sell_rotation_costs_and_tax(toy):
    prices, meta, bench, sessions = toy
    # anchor 1: AAA, BBB top 2; anchor 2: BBB falls to rank 5 (> 2N = 4) → sold, CCC bought; anchor 3: no change
    ranks = {sessions[0]: [("SMALL", {"AAA": 1, "BBB": 2, "CCC": 3}, 2, 4)],
             sessions[1]: [("SMALL", {"AAA": 1, "CCC": 2, "BBB": 5}, 2, 4)],
             sessions[2]: [("SMALL", {"AAA": 1, "CCC": 2, "BBB": 5}, 2, 4)]}
    r, frozen = pb.simulate("toy", {}, ranks, prices, meta, set(), bench, sessions, sessions[-1], capital=100_000.0)
    sides = [(t["date"], t["side"], t["sid"]) for t in r["trades"]]
    assert sides[:2] == [(sessions[0], "BUY", "AAA"), (sessions[0], "BUY", "BBB")]
    assert (sessions[1], "SELL", "BBB") in sides and (sessions[1], "BUY", "CCC") in sides
    assert r["rotations"] == 1 and r["buys"] == 3 and r["sells"] == 1          # the June start is not a rotation
    buys_value = sum(t["value"] for t in r["trades"] if t["side"] == "BUY")
    assert 0.001 * buys_value < r["costs"]["stt"] < 0.001 * (buys_value + 1.02 * r["trades"][2]["value"])   # 0.1 % each way
    assert 0 < r["costs"]["stt"] < r["costs"]["total"]                            # STT is one part of the cost
    sell = next(t for t in r["trades"] if t["side"] == "SELL")
    assert sell["gain"] < 0 and sell["held_months"] == 1                          # BBB sold at a loss after a month
    assert r["tax_realised"] == 0                                                 # a realised loss: no tax due
    assert r["unrealised_gain"] > 0 and r["tax_if_sold"] == pytest.approx(max(r["realised_gain"] + r["unrealised_gain"], 0) * 0.208, abs=1)
    assert r["bench_ret"] == pytest.approx(0.2)
    assert len(r["history"]) == 4 and r["history"][-1]["date"] == sessions[-1]   # three anchors + the final mark
    assert {h["sid"] for h in r["holdings"]} == {"AAA", "CCC"}
    assert r["ret"] == pytest.approx(r["nav"] / 100_000 - 1, abs=1e-4)


def test_frozen_record_is_not_retraded_when_the_scores_change(toy):
    """The first run freezes June–July; a later run with DIFFERENT June/July ranks keeps those trades and only
    trades the new anchor."""
    prices, meta, bench, sessions = toy
    first = {sessions[0]: [("SMALL", {"AAA": 1, "BBB": 2, "CCC": 3}, 2, 4)], sessions[1]: [("SMALL", {"AAA": 1, "BBB": 2, "CCC": 3}, 2, 4)]}
    r1, frozen = pb.simulate("toy", {}, first, prices, meta, set(), bench, sessions[:2], sessions[1], capital=100_000.0)
    assert frozen["last_anchor"] == sessions[1] and {h["sid"] for h in r1["holdings"]} == {"AAA", "BBB"}
    frozen = json.loads(json.dumps(frozen))                                       # as it comes back from the state file
    changed = {sessions[0]: [("SMALL", {"CCC": 1, "BBB": 2, "AAA": 9}, 2, 4)],      # a rebuilt panel re-ranks June
               sessions[1]: [("SMALL", {"CCC": 1, "BBB": 2, "AAA": 9}, 2, 4)],
               sessions[2]: [("SMALL", {"AAA": 1, "CCC": 2, "BBB": 9}, 2, 4)]}
    r2, frozen2 = pb.simulate("toy", {}, changed, prices, meta, set(), bench, sessions, sessions[2], capital=100_000.0, state=frozen)
    june = [t for t in r2["trades"] if t["date"] == sessions[0]]
    assert {t["sid"] for t in june} == {"AAA", "BBB"}                             # June stays as it was traded
    assert [t["sid"] for t in r2["trades"] if t["date"] == sessions[2] and t["side"] == "SELL"] == ["BBB"]
    assert frozen2["last_anchor"] == sessions[2] and len(frozen2["history"]) == 3


def test_slow_rule_never_sells_inside_twelve_months(toy, monkeypatch):
    prices, meta, bench, sessions = toy
    monkeypatch.setitem(pb.BOOKS, "toy", dict(label="Toy", tier="SMALL", kind="slow", bench={"IDX": 1.0}, N=2, rule="", min_hold_m=12))
    ranks = {d: [("SMALL", {"AAA": 1, "BBB": 2, "CCC": 3} if d == sessions[0] else {"AAA": 1, "CCC": 2, "BBB": 50}, 2, 6)]
             for d in sessions}
    r, _ = pb.simulate("toy", {}, ranks, prices, meta, set(), bench, sessions, sessions[-1], capital=100_000.0)
    assert r["sells"] == 0 and r["rotations"] == 0 and {h["sid"] for h in r["holdings"]} == {"AAA", "BBB"}


def test_trusts_and_illiquid_names_are_never_bought(toy):
    prices, meta, bench, sessions = toy
    ranks = {d: [("SMALL", {"AAA": 1, "BBB": 2, "CCC": 3}, 2, 4)] for d in sessions}
    r, _ = pb.simulate("toy", {}, ranks, prices, meta, {"AAA"}, bench, sessions, sessions[-1], capital=100_000.0)
    assert {h["sid"] for h in r["holdings"]} == {"BBB", "CCC"}                    # the trust is skipped, the next rank fills


def test_trade_cost_splits_stt_from_the_rest():
    c = pb.trade_cost(50_000.0, 5e8, 100.0, "SMALL", "buy")
    assert c["stt"] == pytest.approx(50.0)
    assert c["total"] == pytest.approx(c["stt"] + c["fees_other"] + c["spread_impact"])
    assert c["spread_impact"] > 0 and c["fees_other"] > 0
    assert pb.trade_cost(50_000.0, 5e8, 100.0, "MICRO", "sell")["total"] > 0      # MICRO prices on the SMALL curve


def test_months_between():
    assert pb.months_between("2026-06-01", "2026-07-01") == 1
    assert pb.months_between("2026-06-01", "2026-06-30") == 0
    assert pb.months_between("2025-10-13", "2026-10-13") == 12


def test_every_book_has_options_and_a_default_that_is_first():
    for k, b in pb.BOOKS.items():
        opts = pb.OPTIONS[b["kind"]]
        assert 3 <= len(opts) <= 4, k
        assert "default" in opts[0]["label"]
        assert k in pb.EVIDENCE


def test_views_reader(tmp_path, monkeypatch):
    monkeypatch.setattr(views, "PAPER_BOOKS_FILE", tmp_path / "nope.json")
    assert views.paper_books() == {}
    f = tmp_path / "latest.json"
    f.write_text(json.dumps({"asof": "2026-10-30", "computed": "2026-11-01", "start": "2026-06-01", "capital": 1e6, "books": {"x": {}}}))
    monkeypatch.setattr(views, "PAPER_BOOKS_FILE", f)
    d = views.paper_books(today=date(2026, 11, 2))
    assert d["age_days"] == 1 and not d["stale"]
    assert views.paper_books(today=date(2027, 1, 1))["stale"]


def test_book_page_keeps_only_zerodha_and_track_record():
    from cockpit import pages
    tabs = next(p["tabs"] for p in pages.PAGES if p["id"] == "book")
    assert [t for t, _ in tabs] == ["zerodha", "track-record"]
    src = (pages.__file__.rsplit("/", 1)[0] + "/templates/book.html")
    html = open(src, encoding="utf-8").read()
    for gone in ("tab === 'book'", "tab === 'sleeve'", "tab === 'methods'", "tab === 'risk'"):
        assert gone not in html
    assert "What this tab measures" in html and "/paper-books" in html


def test_ops_page_is_registered_and_listed():
    from cockpit_ops import pages
    p = next(p for p in pages.PAGES if p["id"] == "paper-books")
    assert p["path"] == "/paper-books" and p["section"] == "Fund"
    from config import FILE_OUTPUTS
    assert any(f["virtual_table"] == "_file_paper_books" for f in FILE_OUTPUTS)
