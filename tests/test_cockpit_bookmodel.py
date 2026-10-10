"""/book and /model (cockpit v2): the tier verdict rule, weekday-only outcomes, |w| bars,
one count wording, the "left top picks" flag, the do-this-week lines."""
from datetime import date

import factors
from cockpit import book, model


def _cell(window, avg, n_dates, scope="all"):
    return {"window_days": window, "avg_fwd": avg, "n_dates": n_dates, "scope": scope}


def test_tier_verdict_beat_lagged_mixed_early_none():
    v = book.tier_verdict("SMALL", _cell(63, 10.5, 52), _cell(63, 5.4, 52), _cell(20, 3.2, 95), _cell(20, 1.4, 95))
    assert v["verdict"] == "beat" and v["spread_pp"] == 5.1 and v["n_dates"] == 52 and "beat the tier" in v["text"]
    v = book.tier_verdict("MID", _cell(63, 0.8, 52), _cell(63, 3.0, 52), _cell(20, 0.0, 95), _cell(20, 0.3, 95))
    assert v["verdict"] == "lagged"
    # 63-day says lagged but the 20-day says the opposite: not a verdict
    v = book.tier_verdict("LARGE", _cell(63, -2.1, 52), _cell(63, -0.3, 52), _cell(20, -0.6, 95), _cell(20, -0.7, 95))
    assert v["verdict"] == "mixed" and "20 trading days" in v["text"]
    # inside the +-1 point bar is no difference
    assert book.tier_verdict("MID", _cell(63, 3.5, 52), _cell(63, 3.0, 52))["verdict"] == "mixed"
    v = book.tier_verdict("SMALL", _cell(126, 14.0, 1), _cell(126, 16.0, 1))
    assert v["verdict"] == "early" and "1 pick days" in v["text"]
    assert book.tier_verdict("SMALL", None, None)["verdict"] == "none"


def test_outcomes_use_weekday_pick_dates_only():
    from cockpit import api
    s = api.get_pick_outcomes_summary.__wrapped__(top_n=10)
    days = {r["pick_date"] for r in s["time_series"]}
    assert days and all(date.fromisoformat(d).weekday() < 5 for d in days)
    assert "NOT IN (0, 6)" in api._OUTCOME_WEEKDAYS


def test_weight_bars_use_absolute_weight_and_negative_is_inverted():
    ws = [0.35, 0.25, -0.2, 0.2]
    bars = [model.bar_width(w, ws) for w in ws]
    assert all(0 <= b <= 100 for b in bars) and abs(sum(bars) - 100) < 0.5
    assert model.bar_width(-0.2, ws) == model.bar_width(0.2, ws)
    rows, _ = model.evidence_rows()
    assert all(r["inverted"] == (r["weight"] < 0) for r in rows)
    assert len(rows) == sum(len(tw) for tw in factors.weights().values())


def test_t_verdict_against_the_two_bars():
    assert model.t_verdict(5.0, 0.2)[0] == "proven"
    assert model.t_verdict(-4.5, -0.2)[0] == "proven"          # negative weight, negative t: right way round
    assert model.t_verdict(3.0, 0.2)[0] == "passes"
    assert model.t_verdict(1.0, 0.2)[0] == "weak"
    assert model.t_verdict(-3.0, 0.2)[0] == "wrong"
    assert model.t_verdict(None, 0.2)[0] == "none"


def test_one_count_wording():
    n_w = sum(len(tw) for tw in factors.weights().values())
    assert model.factor_count_text() == f"{len(factors.wired_signal_ids())} factors / {n_w} weights"


def test_left_top_picks_flag():
    info = {"ranked_today": True, "in_top_today": False, "last_top": "2026-10-09", "dates": ["2026-10-09", "2026-10-10"]}
    assert book.left_flag(info, "2026-10-10") == "left top picks 10 Oct"
    assert book.left_flag({**info, "in_top_today": True}, "2026-10-10") is None
    assert book.left_flag({**info, "last_top": None}, "2026-10-10") == "not in the top picks for 60 days"
    assert book.left_flag({**info, "ranked_today": False}, "2026-10-10") == "not ranked today"
    assert book.left_flag(None, "2026-10-10") == "not ranked today"


def test_allocation_flag_only_when_no_factor_clears_the_bar():
    none = {"n_proven": 0, "best_t": 2.8}
    assert "LARGE gets 40%" in model.allocation_flag("LARGE", 0.4, "NORMAL", none)
    assert "out-of-sample" in model.allocation_flag("LARGE", 0.4, "NORMAL", none)
    assert model.allocation_flag("SMALL", 0.3, "NORMAL", {"n_proven": 4, "best_t": 5.8}) is None


def test_do_this_week_is_capped_and_derived():
    decayed = [{"label": f"F{i}", "tier": "LARGE", "ic_recent": -0.01, "ic_all": 0.03} for i in range(5)]
    cov = {"n": 15, "n_low": 1, "threshold": 80, "low": [{"ticker": "ABC", "missing": ["IV Skew"]}]}
    tiers = [{"tier": "LARGE", "flag": "LARGE gets 40% ...", "verdict": {"verdict": "lagged", "spread_pp": -2.0, "window": 63}}]
    out = model.do_this_week(decayed, 6, cov, tiers)
    assert len(out) == model.MAX_ACTIONS and out[0]["kind"] == "review" and "7 days running" in out[0]["text"]
    out = model.do_this_week([], 0, cov, tiers)
    assert [a["kind"] for a in out] == ["data", "decide", "decide"] and "ABC is missing IV Skew" in out[0]["text"]
    assert model.do_this_week([], 0, {**cov, "n_low": 0}, [{**tiers[0], "flag": None, "verdict": {"verdict": "beat"}}]) == []


def test_library_covers_the_registry_wired_first_notes_from_registry():
    from cockpit_ops.api import get_validation_evidence
    rows = model.library_rows(get_validation_evidence()["rows"])
    assert len(rows) == len(factors.FACTORS)
    states = [r["state"] for r in rows]
    assert states[: len(factors.wired_signal_ids())] == ["WIRED"] * len(factors.wired_signal_ids())
    assert all("NOT wired" not in r["note"] for r in rows)
    assert all("Weights:" in r["note"] for r in rows if r["state"] == "WIRED")
