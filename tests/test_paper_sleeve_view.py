"""The long-hold rank and the paper sleeve reach the cockpit through ONE reader (views.paper_sleeve):
a missing file reads as {}, a missed monthly refresh reads as stale, and only ranked (Small) stocks get
a long-hold rank (2026-10-14)."""
import json
from datetime import date

import views
from cockpit import today


def _write(tmp_path, monkeypatch, computed="2026-10-13"):
    f = tmp_path / "latest.json"
    f.write_text(json.dumps({
        "status": "ACTIVE", "next_review": "2026-11-02", "notional": 525000.0,
        "latest": {"date": computed, "price_date": computed, "combined": 1.0, "bench": 1.0, "relative": 1.0},
        "last_review": {"date": computed, "bought": 40, "sold": 0},
        "books": {"slow": {"positions": [{"sid": "AAA"}]}, "tactical": {"positions": [{"sid": "BBB"}]}},
        "long_hold": {"tier": "SMALL", "score_date": "2026-10-01", "computed": computed, "size": 3,
                      "ranks": {"AAA": 1, "BBB": 2, "CCC": 3}},
    }))
    monkeypatch.setattr(views, "SLEEVE_FILE", f)


def test_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(views, "SLEEVE_FILE", tmp_path / "nope.json")
    assert views.paper_sleeve() == {}
    assert views.long_hold("AAA") is None
    assert today.sleeve_review() is None


def test_rank_books_and_staleness(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch)
    fresh = views.paper_sleeve(today=date(2026, 10, 20))
    assert fresh["stale"] is False and fresh["age_days"] == 7
    lh = views.long_hold("AAA", fresh)
    assert lh == {"rank": 1, "size": 3, "score_date": "2026-10-01", "stale": False, "books": ["slow"]}
    assert views.long_hold("BBB", fresh)["books"] == ["tactical"]
    assert views.long_hold("ZZZ", fresh) is None                      # Mid / Large / unranked: no long-hold rank
    assert views.paper_sleeve(today=date(2026, 12, 1))["stale"] is True   # the November refresh was missed


def test_today_line_only_in_review_week(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch)
    assert today.sleeve_review(date(2026, 10, 15)) == {"date": "2026-10-13", "bought": 40, "sold": 0, "status": "ACTIVE"}
    assert today.sleeve_review(date(2026, 10, 25)) is None
