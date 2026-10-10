"""Cockpit v2, group Stocks: the screener (filters, sort, URL state, the median-target basis), the news
name check, the stock-page chips and the monthly management refresh wiring."""
import pathlib
import re

import pytest

from cockpit import stocks

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _row(ticker, tier, score=None, rank=None, **kw):
    base = {"sid": ticker, "ticker": ticker, "name": f"{ticker} Ltd", "tier": tier, "sector": "Materials",
            "ranked": score is not None, "score": score, "rank": rank, "tier_size": 3 if score is not None else None,
            "change": None, "data": 100 if score is not None else None, "data_colour": "green", "book": False,
            "avoid": False, "forensic": [], "veto": False, "plays": [], "pt_up": None, "analysts": None, "flagged": False}
    return {**base, **kw}


@pytest.fixture
def uni(monkeypatch):
    rows = [_row("AAA", "LARGE", 70, 1, book=True, pt_up=12.0), _row("BBB", "LARGE", 60, 2, flagged=True, avoid=True),
            _row("CCC", "MID", 80, 1, sector="Energy", change=3), _row("DDD", "MID", 50, 2, change="new", pt_up=-5.0),
            _row("EEE", "SMALL", 40, 1, sector="Energy"), _row("MMM", "MICRO")]
    u = {"as_of": "2026-10-10", "prev_date": "2026-10-09", "rows": rows, "tiers": ["LARGE", "MID", "SMALL", "MICRO"],
         "unpickable": ["MICRO"], "sectors": ["Energy", "Materials"]}
    monkeypatch.setattr(stocks, "universe", lambda: u)
    return u


def tickers(params):
    return [r["ticker"] for r in stocks.screen(params)["rows"]]


def test_default_view_hides_micro_and_orders_tier_by_tier(uni):
    s = stocks.screen({})
    assert [r["ticker"] for r in s["rows"]] == ["AAA", "BBB", "CCC", "DDD", "EEE"]     # never one rank across tiers
    assert s["default_view"] and s["n_ranked"] == 5 and s["n_unranked"] == 1


def test_filters(uni):
    assert tickers({"tier": "MID"}) == ["CCC", "DDD"]
    assert tickers({"sector": "Energy"}) == ["CCC", "EEE"]
    assert tickers({"book": "1"}) == ["AAA"]
    assert tickers({"flagged": "1"}) == ["BBB"]
    assert tickers({"q": "dd"}) == ["DDD"]
    assert tickers({"micro": "1"})[-1] == "MMM"                                         # micro only when asked, shown last
    assert tickers({"tier": "MICRO"}) == ["MMM"]
    assert tickers({"tier": "MID", "sector": "Materials"}) == ["DDD"]
    assert stocks.screen({"q": "zzz"})["rows"] == [] and stocks.screen({"q": "zzz"})["total"] == 0


def test_sort_and_direction(uni):
    assert tickers({"sort": "score"}) == ["CCC", "AAA", "BBB", "DDD", "EEE"]            # default direction desc
    assert tickers({"sort": "score", "dir": "asc"}) == ["EEE", "DDD", "BBB", "AAA", "CCC"]
    assert tickers({"sort": "pt"})[:2] == ["AAA", "DDD"]                                # rows without a target sink
    assert tickers({"sort": "change"})[0] == "CCC"                                      # 'new' has no number to sort on
    assert tickers({"sort": "ticker", "dir": "desc"})[0] == "EEE"
    assert stocks.screen({"sort": "bogus"})["chosen"]["sort"] == "rank"


def test_url_state_round_trips(uni):
    s = stocks.screen({"tier": "MID", "sort": "score", "dir": "asc", "book": "1"})
    assert s["link"]() == "/stocks?tier=MID&book=1&sort=score&dir=asc"
    assert s["link"](sort="rank", dir="asc", tier="") == "/stocks?book=1"             # back to the default order and tier
    assert s["link"](page=2) == "/stocks?tier=MID&book=1&sort=score&dir=asc&page=2"
    assert stocks.screen({})["link"]() == "/stocks"


def test_paging(monkeypatch, uni):
    rows = [_row(f"S{i:03d}", "SMALL", 50, i) for i in range(1, 251)]
    monkeypatch.setattr(stocks, "universe", lambda: {**uni, "rows": rows})
    s = stocks.screen({"page": "3"})
    assert (s["pages"], s["page"], len(s["rows"]), s["total"]) == (3, 3, 50, 250)
    assert stocks.screen({"page": "99"})["page"] == 3 and stocks.screen({"page": "x"})["page"] == 1


def test_median_target_basis():
    assert stocks._median_upside(120, 100) == 20.0
    assert stocks._median_upside(None, 100) is None
    assert stocks._median_upside(400, 100) is None          # outside PT_CLOSE_RATIO: Yahoo garbage, not a target
    assert stocks._median_upside(20, 100) is None
    assert stocks._median_upside(120, None) is None


def test_rank_change_is_within_tier():
    import pandas as pd
    today = pd.DataFrame({"sid": ["A", "B", "C"], "cap_tier": ["MID", "MID", "SMALL"], "rank": [1, 2, 1]})
    yday = pd.DataFrame({"sid": ["A", "B", "C"], "cap_tier": ["MID", "SMALL", "SMALL"], "rank": [4, 1, 3]})
    assert stocks._rank_changes(today, yday) == {"A": 3, "B": "new", "C": 2}


def test_news_must_name_the_company():
    from cockpit.api import _names_company as named
    assert not named("Top 2 stocks to buy by Chandan Taparia - check stop-loss", "Chandan Healthcare Ltd", "CHANDAN")
    assert named("Chandan Healthcare opens a new lab", "Chandan Healthcare Ltd", "CHANDAN")
    assert named("Indian Bank to enter life insurance", "Indian Bank", "INDIANB")
    assert named("Kovai Medical expands", "Kovai Medical Center and Hospital Ltd", "KOVAI")      # first two words of a long name
    assert named("LODHA shares jump", "Lodha Developers Ltd", "LODHA")                         # ticker in capitals
    assert not named("House of Abhinandan Lodha ties up", "Lodha Developers Ltd", "LODHA")


def test_say_do_and_chips(monkeypatch):
    from output import say_do as sd
    monkeypatch.setattr(sd, "load", lambda: [{"sid": "X", "verdict": "mixed", "summary": "s", "latest_call": "2026-07-30",
                                              "earlier_call": "2026-01-28", "generated_at": "2026-10-08T12:00:00",
                                              "promises": [{"said": "a", "outcome": "missed", "evidence": "e"}]}])
    d = stocks.say_do_for("X")
    assert d["label"] == "Mixed record" and d["tone"] == "amber" and d["promises"][0]["label"] == "Missed"
    assert d["generated_at"] == "2026-10-08" and stocks.say_do_for("Y") is None
    from cockpit import playbooks
    monkeypatch.setattr(playbooks, "avoid_list", lambda: {"rows": [{"sid": "X", "n_flags": 3, "flags": [{"label": "Heavy pledging", "detail": "40% pledged"}]}]})
    monkeypatch.setattr(playbooks, "categories", lambda: {"categories": [{"key": "fast", "label": "Fast growers", "rule": "r"}], "by_sid": {"X": "fast"}})
    monkeypatch.setattr(stocks.views, "native_rows", lambda *a, **k: [{"sleeve": "quality"}, {"sleeve": "flagged"}])
    c = stocks.stock_chips("X")
    assert [f["tone"] for f in c["flags"]] == ["red", "amber"] and "Heavy pledging" in c["flags"][0]["tip"]
    assert [p["label"] for p in c["plays"]] == ["Compounders"] and c["category"]["label"] == "Fast growers"


def test_data_wording_is_the_neutral_fifty_rule():
    import views
    d = views.pick_data({"eligible_coverage": 0.6})
    assert "counts as the middle of its tier (50)" in d["meaning"] and "left out" not in d["meaning"]


# ── the monthly management refresh ──

def test_management_refresh_is_wired():
    run_sh = (ROOT / "run.sh").read_text()
    body = run_sh.split("    management)")[1].split(";;")[0]
    for step in ("signals.management_quality", "signals.managerial_ability", "output.say_do --enqueue", "harvest_lock"):
        assert step in body
    cron = (ROOT / "ops/crontab.txt").read_text()
    assert re.search(r"^\d+ \d+ \d+ \* \* /home/ubuntu/alpha-signal-v2/run\.sh management >> ", cron, re.M)   # monthly, via run.sh
    from tables import TABLES
    for t in ("management_scores", "managerial_ability_scores"):
        assert TABLES[t]["freq"] == "monthly" and TABLES[t]["stale_days"] == 35, t


def test_management_tables_are_judged_monthly():
    import db
    stale = db._compute_freshness("2026-06-06", "monthly", "management_scores")
    assert stale[0] == "OUTDATED" and stale[2] == 35


def test_stock_pages_render(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import webauth
    from cockpit.app import app
    monkeypatch.setattr(webauth, "AUTH_FILE", tmp_path / "auth.json")
    webauth.set_password("correct horse battery")
    client = TestClient(app, cookies={webauth.COOKIE: webauth.make_token()})
    r = client.get("/stocks?tier=MID&sort=score")
    assert r.status_code == 200 and "Score /100" in r.text and "explorer" not in r.text.lower().replace("preview", "")
    r = client.get("/stocks?q=zzzzzz-no-such")
    assert r.status_code == 200 and "No stock matches these filters" in r.text
    first = re.search(r'class="st-tk" href="/stocks/([^"]+)"', client.get("/stocks").text).group(1)
    page = client.get(f"/stocks/{first}").text
    for tab in ("Overview", "Financials", "Ownership", "Analysts", "Forensic", "Price &amp; technicals", "Industry", "Management"):
        assert f">{tab}</button>" in page, tab
    assert "CONVICTION" not in page and "Consensus</button>" not in page and ">Data</button>" not in page
