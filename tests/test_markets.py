"""Markets (cockpit v2): one verdict per sector ordered by sector_tilt, the theme note's
"since the note" logic, and news search."""
from cockpit import api

TILTS = [{"sector": "Health Care", "sector_tilt": 1.6, "z_mom6": 2.4, "z_macro": 0.9},
         {"sector": "Energy", "sector_tilt": -0.27, "z_mom6": 0.7, "z_macro": -1.3},
         {"sector": "Real Estate", "sector_tilt": -0.7, "z_mom6": -0.2, "z_macro": -1.2},
         {"sector": "Materials", "sector_tilt": 0.3, "z_mom6": 0.0, "z_macro": 0.6}]
WEEK = {"favour": [{"sector": "Energy", "reason": "oil high"}],
        "careful": [{"sector": "Health Care", "reason": "tariffs"}, {"sector": "Real Estate", "reason": "rates"}]}


def test_one_verdict_per_sector_ordered_by_tilt():
    rows = api.build_sector_call(TILTS, WEEK)
    assert [r["sector"] for r in rows] == ["Health Care", "Materials", "Energy", "Real Estate"]
    assert len({r["sector"] for r in rows}) == len(rows)
    by = {r["sector"]: r for r in rows}
    assert by["Health Care"]["verdict"] == "Lean in" and by["Health Care"]["news"] == "careful"
    assert by["Health Care"]["agree"] is False                       # model and news disagree: both kept
    assert by["Real Estate"]["verdict"] == "Lean away" and by["Real Estate"]["agree"] is True
    assert by["Energy"]["verdict"] == "No call" and by["Energy"]["agree"] is None   # below the lean threshold
    assert by["Materials"]["news"] is None


def test_sector_without_a_tilt_still_listed_last():
    rows = api.build_sector_call(TILTS[:1], WEEK)
    assert rows[0]["sector"] == "Health Care" and rows[-1]["tilt"] is None and rows[-1]["verdict"] == "No call"


def test_theme_is_out_of_date_only_when_a_newer_story_has_its_theme():
    today = {"day": "2026-10-10", "items": [{"headline": "A", "theme": "oil"}, {"headline": "B", "theme": "ai"}]}
    themes = [{"theme_id": "oil", "updated_at": "2026-10-05 21:00", "stands_now": "x"},
              {"theme_id": "ai", "updated_at": "2026-10-10 06:00", "stands_now": "x"},      # note is from today
              {"theme_id": "rates", "updated_at": "2026-10-05", "stands_now": "x"},        # no story
              {"theme_id": "new", "updated_at": None, "stands_now": ""}]
    out = {t["theme_id"]: t for t in api.annotate_themes(themes, today)}
    assert out["oil"]["stale"] and out["oil"]["since"] == [{"headline": "A", "n": 1}]
    assert not out["ai"]["stale"] and not out["rates"]["stale"] and not out["new"]["stale"]
    assert not any(t["stale"] for t in api.annotate_themes(themes, {}))


def test_search_filters_and_links_tickers(monkeypatch):
    cards = [{"id": "1", "headline": "RBI acts", "source_url": "u", "source_label": "Mint", "published_at": "2026-10-10T01:00",
              "age_label": "1h ago", "one_liner": None},
             {"id": "2", "headline": "Oil up", "source_url": "v", "source_label": "ET", "published_at": "2026-10-09T01:00",
              "age_label": "1d ago", "one_liner": None}]
    seen = {}

    def feed(**kw):
        seen.update(kw)
        c = [x for x in cards if not kw.get("source") or x["source_label"] == kw["source"]]
        return {"cards": c, "total": len(c), "page": 1, "total_pages": 1, "source_counts": {"Mint": 1, "ET": 1}, "theme_counts": {}}
    monkeypatch.setattr(api, "get_news_feed", feed)
    monkeypatch.setattr(api, "get_news_themes", lambda: [])
    monkeypatch.setattr(api, "_theme_members", lambda: {})
    monkeypatch.setattr(api, "_article_tickers", lambda ids: {"1": [{"ticker": "SBIN", "sid": "SBIN"}]})
    r = api.search_news(q="rbi", source="Mint", hours=72)
    assert seen["q"] == "rbi" and seen["source"] == "Mint" and seen["hours"] == 72 and seen["sort"] == "recent"
    assert [x["headline"] for x in r["rows"]] == ["RBI acts"] and r["rows"][0]["tickers"][0]["ticker"] == "SBIN"
    assert r["rows"][0]["day"] == "2026-10-10"
