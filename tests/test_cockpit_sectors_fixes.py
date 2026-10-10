"""Sectors / Markets fixes (2026-10-10): one score-colour scale, whole-word news search, no pick that is also an avoid."""
import pandas as pd

import formatting
from cockpit import api


def test_score_bands_one_scale():
    assert formatting.score_band(0.58) == "hm-s4" and formatting.score_tone(0.58) == "score-green"
    assert formatting.score_band(0.66) == "hm-s5"
    assert formatting.score_band(0.45) == "hm-s3" and formatting.score_tone(0.45) == "score-amber"
    assert formatting.score_tone(0.2) == "score-red"
    assert formatting.score_band(None) == "hm-na" and formatting.score_tone(float("nan")) == ""


def _feed(monkeypatch, headlines):
    cards = [{"id": str(i), "headline": h, "summary": "", "one_liner": "", "why_it_matters": "", "hours_old": 1,
              "source_label": "S", "source_tier": 1, "source_tier_score": 1, "score": 1, "n_key_numbers": 0, "enriched": False}
             for i, h in enumerate(headlines)]
    monkeypatch.setattr(api, "_get_news_pool", lambda hours=720: cards)
    monkeypatch.setattr(api, "_theme_members", lambda: {})
    return lambda q: [c["headline"] for c in api.get_news_feed(q=q, page_size=50)["cards"]]


def test_news_search_matches_whole_words(monkeypatch):
    s = _feed(monkeypatch, ["RBI holds rates", "Carbide maker orbit turbines", "Repo rate: rbi's view", "Policy rate cut"])
    assert sorted(s("RBI")) == ["RBI holds rates", "Repo rate: rbi's view"]
    assert s("policy rate") == ["Policy rate cut"]
    assert s("rate") == ["RBI holds rates", "Repo rate: rbi's view", "Policy rate cut"] or len(s("rate")) == 3


def test_group_picks_never_lists_a_stock_twice(monkeypatch):
    df = pd.DataFrame({"sid": list("abc"), "ticker": list("ABC"), "name": list("xyz"),
                       "final_score": [0.6, 0.5, 0.4], "cap_tier": ["MID"] * 3})
    monkeypatch.setattr(api, "read_sql", lambda *a, **k: df)
    monkeypatch.setattr(api, "latest_pick_date", lambda: "2026-10-10")
    r = api.get_group_picks("industry", "REITs", top_n=10, bottom_n=5)
    assert len(r["top"]) == 3 and r["bottom"] == []
    r = api.get_group_picks("industry", "REITs", top_n=1, bottom_n=5)
    assert [x["sid"] for x in r["top"]] == ["a"] and [x["sid"] for x in r["bottom"]] == ["c", "b"]
