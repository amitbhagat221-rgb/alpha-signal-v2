"""Cockpit v2 phase 3: one wording and one source across the main pages (rank format and denominator,
display tier order, the 'unproven' marker, the backtest evidence line, the Stocks default view, compare links)."""
import pytest

import formatting
import preview
import views
from cockpit import model, playbooks, stocks


def test_rank_text_is_one_format():
    assert formatting.rank_text(1, 100, "LARGE") == "#1 of 100 in Large"
    assert formatting.rank_text(99, 100) == "#99 of 100"
    assert formatting.rank_text(3) == "#3"
    assert formatting.rank_text(None, 100) == "not ranked"
    assert formatting.rank_text(5, 1579, "SMALL") == "#5 of 1,579 in Small"


def test_tier_sizes_count_only_ranked_rows(monkeypatch):
    seen = {}

    def fake(sql, params=()):
        seen["sql"] = sql
        return [{"cap_tier": "LARGE", "n": 100}, {"cap_tier": "MID", "n": 140}]
    monkeypatch.setattr(views, "native_rows", fake)
    assert views.tier_sizes("2026-10-10") == {"LARGE": 100, "MID": 140}
    assert "daily_picks" in seen["sql"]            # the ranking itself, not the replay frame that includes unranked names


def test_display_tiers_put_the_unproven_last():
    assert views.display_tiers() == ["MID", "SMALL", "LARGE"]
    assert views.unproven_tiers() == {"LARGE": views.NO_OOS_SKILL["LARGE"]}
    assert views.is_unproven("LARGE") and not views.is_unproven("MID")


def test_unproven_has_one_source(monkeypatch):
    assert model.NO_OOS_SKILL is views.NO_OOS_SKILL
    monkeypatch.setitem(views.NO_OOS_SKILL, "SMALL", "x")
    assert views.display_tiers() == ["MID", "LARGE", "SMALL"]
    assert "Small gets" in model.allocation_flag("SMALL", 0.3, "NORMAL", {"n_proven": 0, "best_t": 1.0})


def _bt(excess=-5.0, t=-1.0, veto_t=0.45):
    st = lambda ex, tt: {"net_ann": 5.0, "bench_ann": 5.0 - ex, "excess_ann": ex, "t_stat": tt, "months": 40, "last": "2026-09"}
    return {"last_month": "2026-09", "generated_at": "2026-10-04T10:00:00",
            "sleeves": [{"key": "insiders", "label": "Insider buying", "rule": "r", "stats": st(excess, t)}],
            "flagged": {"label": "Avoid", "rule": "r", "stats": st(1.6, veto_t)}, "combined": {"label": "c", "stats": None}}


def test_evidence_comes_from_the_backtest_file(monkeypatch):
    monkeypatch.setattr(playbooks, "_backtest", lambda: _bt())
    ev = playbooks.evidence()
    assert ev["available"] and ev["beat"] == []
    assert "no screen has beaten its tier" in ev["sentence"] and "Sep 2026" in ev["sentence"]
    assert "has not shown an edge" in ev["veto_sentence"] and "+0.45" in ev["veto_sentence"]
    monkeypatch.setattr(playbooks, "_backtest", lambda: _bt(excess=6.0, t=2.5))
    assert playbooks.evidence()["beat"] == ["Insider buying"]


def test_evidence_without_the_file_says_so_in_words(monkeypatch):
    monkeypatch.setattr(playbooks, "_backtest", lambda: None)
    ev = playbooks.evidence()
    assert not ev["available"] and "backtest not available" in ev["sentence"]
    assert "python" not in ev["sentence"] + ev["veto_sentence"]


def _row(t, tier, ranked, **kw):
    return {"sid": t, "ticker": t, "name": t, "tier": tier, "sector": "X", "ranked": ranked, "score": 50 if ranked else None,
            "rank": 1 if ranked else None, "tier_size": 1, "change": None, "data": 100, "data_colour": "green", "book": False,
            "avoid": False, "forensic": [], "veto": False, "plays": [], "pt_up": None, "analysts": None, "flagged": False, **kw}


def test_stocks_default_lists_exactly_the_ranked(monkeypatch):
    rows = [_row("A", "SMALL", True), _row("B", "SMALL", False), _row("M", "MICRO", False), _row("L", "LARGE", True)]
    monkeypatch.setattr(stocks, "universe", lambda: {"as_of": "2026-10-10", "prev_date": None, "rows": rows,
                        "tiers": ["MID", "SMALL", "LARGE", "MICRO"], "unpickable": ["MICRO"], "sectors": ["X"]})
    s = stocks.screen({})
    assert s["total"] == s["n_ranked"] == 2 and [r["ticker"] for r in s["rows"]] == ["A", "L"]     # SMALL before LARGE
    s = stocks.screen({"unranked": "1"})
    assert s["total"] == 4 and s["n_gate"] == 1 and s["n_micro"] == 1
    assert "unranked=1" in s["link"]() and stocks.screen({"micro": "1"})["total"] == 4          # the old URL still works
    assert stocks.screen({"tier": "SMALL"})["total"] == 1


def test_compare_links_for_model_tabs_and_strict():
    tabs = preview.compare_target("main", "/model")[1]
    assert tabs["#evidence"] == "/model#backtests" and tabs["#rules"] == "/model#gate"
    assert preview.compare_links("main", "/ideas", "strict=1")["url"].endswith("/multibagger")
    assert preview.compare_links("main", "/ideas")["url"].endswith("/playbooks")
