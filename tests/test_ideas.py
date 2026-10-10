"""Ideas (/ideas): the screens table joins the model rank, strict compounders are the multibagger
gates, every screen has its backtest line. Offline: the data functions are stubbed."""
import pandas as pd
import pytest

from cockpit import playbooks as pb


def _stats(**o):
    s = {"months": 60, "first": "2020-10", "last": "2026-09", "net_ann": 7.6, "bench_ann": 23.7, "excess_ann": -13.8, "t_stat": -2.4}
    return {**s, **o}


def test_every_screen_has_a_sleeve_and_a_chip():
    assert [k for k, _ in pb.SCREENS] == ["insiders", "compounders", "investors", "breakouts", "deep"]
    assert set(pb.SCREEN_SLEEVE) == {k for k, _ in pb.SCREENS}
    import sleeves
    assert set(pb.SCREEN_SLEEVE.values()) <= set(sleeves.SLEEVES)


def test_backtest_line_verdicts():
    l = pb.backtest_line(_stats(), "Breakouts")
    assert (l["net"], l["tier"], l["t"], l["months"], l["verdict"]) == (7.6, 23.7, -2.4, 60, "did not beat its tier")
    assert pb.backtest_line(_stats(months=2), "X")["verdict"] == "too short to judge"
    assert pb.backtest_line(_stats(excess_ann=3, t_stat=2.5), "X")["verdict"] == "beat its tier"
    assert "not beyond chance" in pb.backtest_line(_stats(excess_ann=3, t_stat=0.5), "X")["verdict"]
    assert pb.backtest_line(None, "X") is None


def test_rank_join_marks_agreement_and_conflict(monkeypatch):
    ranks = {"as_of": "2026-10-09", "by_sid": {"A": {"rank": 5, "n": 100, "pct": 0.05, "tier": "MID"},
                                                "B": {"rank": 95, "n": 100, "pct": 0.95, "tier": "MID"},
                                                "C": {"rank": 50, "n": 100, "pct": 0.5, "tier": "MID"}}}
    monkeypatch.setattr(pb, "_flag_counts", lambda: {"B": 2})
    rows = pb.with_rank([{"sid": s} for s in "ABCD"], ranks)
    assert [(r["agrees"], r["conflicts"]) for r in rows] == [(True, False), (False, True), (False, False), (False, False)]
    assert rows[3]["rank"] is None and rows[1]["flags"] == 2 and rows[0]["flags"] == 0


def test_model_ranks_are_within_tier(monkeypatch):
    df = pd.DataFrame({"sid": ["a", "b", "c"], "rank": [1, 2, 1], "cap_tier": ["MID", "MID", "SMALL"]})
    monkeypatch.setattr(pb.views, "picks", lambda gated=True: df)
    monkeypatch.setattr(pb.views, "latest_pick_date", lambda: "2026-10-09")
    m = pb.model_ranks()["by_sid"]
    assert m["b"] == {"rank": 2, "n": 2, "pct": 1.0, "tier": "MID"} and m["c"]["n"] == 1


def _overview():
    return {"available": True, "snapshot_date": "2026-10-04", "funnel": {"universe": 1690, "passed_gates": 1012, "survived": 2},
            "conviction_counts": {"HOLD": 1, "REVIEW": 1}, "gate_fails": [{"reason": "x", "n": 1}] * 5, "market_guard_active": False,
            "survivors": [{"sid": "S1", "ticker": "AAA", "name": "A", "cap_tier": "SMALL", "conviction": "HOLD"},
                          {"sid": "S2", "ticker": None, "name": "B", "cap_tier": "MID", "conviction": "REVIEW"}]}


def test_strict_compounders_are_the_multibagger_survivors(monkeypatch):
    from cockpit import api
    monkeypatch.setattr(api, "get_multibagger_overview", lambda: _overview())
    monkeypatch.setattr(pb, "model_ranks", lambda: {"as_of": None, "by_sid": {}})
    monkeypatch.setattr(pb, "_backtest", lambda: None)
    monkeypatch.setattr(pb, "_flag_counts", lambda: {})
    d = pb.screen("compounders", strict=True)
    assert d["key"] == "strict" and [r["sid"] for r in d["rows"]] == ["S1", "S2"]
    assert d["rows"][1]["ticker"] == "S2" and d["strict"]["funnel"]["survived"] == 2 and d["line"] is None
    monkeypatch.setattr(api, "get_multibagger_overview", lambda: {"available": False})
    assert pb.screen("compounders", strict=True)["rows"] == []


def test_each_screen_carries_its_backtest_line(monkeypatch):
    bt = {"sleeves": [{"key": k, "stats": _stats()} for k in pb.SCREEN_SLEEVE.values()], "flagged": {"stats": _stats(t_stat=0.45)}}
    monkeypatch.setattr(pb, "_backtest", lambda: bt)
    monkeypatch.setattr(pb, "model_ranks", lambda: {"as_of": None, "by_sid": {}})
    monkeypatch.setattr(pb, "_flag_counts", lambda: {})
    row = {"sid": "S", "ticker": "T", "name": "N", "tier": "MID"}
    payload = {"rows": [row], "as_of": "2026-10-09"}
    for fn in ("insider_buying", "compounders", "breakouts", "deep_value"):
        monkeypatch.setattr(pb, fn, lambda payload=payload: payload)
    holder = {"who": "X", "pct": 1.5, "change": "new", "delta": None}
    monkeypatch.setattr(pb, "_investor_stock_rows", lambda: ([{**row, "holders": [holder], "n_buying": 1, "followed": True}],
                                                             {"as_of": "x", "followed": [1], "investors": [], "n_with_prior": 1, "n_stocks": 1}))
    for key, label in pb.SCREENS:
        d = pb.screen(key)
        assert d["line"]["label"] == label and d["line"]["verdict"] == "did not beat its tier" and len(d["rows"]) == 1, key
    monkeypatch.setattr(pb, "avoid_list", lambda: {"rows": [], "counts": [], "n_any": 0, "as_of": None})
    assert pb.avoid()["line"]["t"] == 0.45


def test_investor_screen_lists_only_new_or_added(monkeypatch):
    base = {"ticker": "T", "name": "N", "tier": "MID", "sector": None}
    monkeypatch.setattr(pb, "superinvestors", lambda: {
        "followed": [{"name": "F", "holdings": [{**base, "sid": "A", "pct": 2.0, "change": "up", "delta": 0.4},
                                                {**base, "sid": "B", "pct": 1.1, "change": "same", "delta": 0.0}]}],
        "investors": [], "as_of": "x", "n_stocks": 2, "n_with_prior": 2})
    rows, _ = pb._investor_stock_rows()
    assert [(r["sid"], r["n_buying"]) for r in rows] == [("A", 1), ("B", 0)]


def test_stock_chips_shape(monkeypatch):
    monkeypatch.setattr(pb, "category_of", lambda sid: ("fast", "Fast growers"))
    monkeypatch.setattr(pb, "read_sql", lambda q, params=None: pd.DataFrame({"sleeve": ["breakouts", "flagged"]}))
    from output import say_do
    monkeypatch.setattr(say_do, "load", lambda: [{"sid": "S", "verdict": "mixed", "summary": "s"}])
    c = pb.stock_chips("S")
    assert c["lynch"]["label"] == "Fast growers" and c["say_do"]["label"] == "Mixed record"
    assert c["playbooks"] == ["Breakouts", "Red-flag set"]


def test_pages_render_and_old_urls_redirect(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import webauth
    from cockpit.app import app
    monkeypatch.setattr(webauth, "AUTH_FILE", tmp_path / "auth.json")
    webauth.set_password("correct horse battery")
    c = TestClient(app, cookies={webauth.COOKIE: webauth.make_token()}, follow_redirects=False)
    assert c.get("/ideas").status_code == 200
    assert c.get("/partial/ideas/screen/nope").status_code == 404
    assert c.get("/playbooks").headers["location"] == "/ideas"
    assert c.get("/multibagger").headers["location"] == "/ideas"
