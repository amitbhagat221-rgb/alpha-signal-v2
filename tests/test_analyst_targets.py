"""
Analyst targets: one read rule for every surface (2026-10-23) — a target set before a split,
consolidation or demerger is rebased (views.target_basis), and an upside is shown only when the
target is plausible, current and backed by PT_MIN_ANALYSTS houses (validators.plausibility.pt_status).
Offline: temp DB from schema.sql.
"""
import sqlite3
from datetime import date, timedelta

import pytest

import db
import views
from validators.plausibility import PT_MIN_ANALYSTS, pt_status, rebase_targets

TODAY = date.today().isoformat()


def _day(n):
    return (date.today() - timedelta(days=n)).isoformat()


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "targets.db"
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA_PATH.read_text())
    monkeypatch.setattr(db, "DB_PATH", path)
    yield c
    c.close()


def test_status_order_implausible_stale_thin_ok():
    assert pt_status(400, 100, 10) == "implausible"
    assert pt_status(120, 100, 10, close_at_set=60) == "stale"        # +67 % since it was set
    assert pt_status(120, 100, 10, close_at_set=220) == "stale"       # -55 %
    assert pt_status(120, 100, PT_MIN_ANALYSTS - 1, close_at_set=90) == "thin"
    assert pt_status(120, 100, PT_MIN_ANALYSTS, close_at_set=90) == "ok"
    assert pt_status(120, 100, PT_MIN_ANALYSTS) == "ok"               # undated: no staleness test
    assert pt_status(None, 100, 10) == "none"


def test_rebase_scales_every_target_field():
    r = {"price_target": 20.0, "price_target_median": 21.0, "price_target_low": None, "total_analysts": 1}
    out = rebase_targets(r, 10)
    assert (out["price_target"], out["price_target_median"], out["price_target_low"], out["total_analysts"]) == (200, 210, None, 1)
    assert rebase_targets(r, 1.0) is r


def test_basis_rebases_only_share_changes_after_the_target_was_set(conn):
    conn.executemany("INSERT INTO stock_prices (sid, date, close) VALUES (?, ?, ?)",
                     [("X", _day(60), 14.0), ("X", TODAY, 130.0), ("Y", _day(60), 100.0), ("Y", TODAY, 100.0)])
    conn.executemany("INSERT INTO analyst_consensus (sid, price_target, price_target_changed_at, has_analyst_data, "
                     "fetched_at) VALUES (?, ?, ?, 1, ?)", [("X", 20.0, _day(30), TODAY), ("Y", 110.0, None, TODAY)])
    # X's 20 was already in the monthly snapshot 60 days ago: set by then, not 30 days ago
    conn.executemany("INSERT INTO analyst_consensus_snapshots (sid, snapshot_date, source, target_mean) VALUES (?, ?, ?, ?)",
                     [("X", _day(90), "yfinance", 26.0), ("X", _day(60), "yfinance", 20.0), ("X", _day(30), "yfinance", 20.0)])
    conn.executemany("INSERT INTO corporate_adjustments (sid, ex_date, factor, n_events, inds) VALUES (?, ?, ?, 1, ?)",
                     [("X", _day(100), 0.5, "BONUS"),        # before the target: already in its basis
                      ("X", _day(10), 10.0, "SPLIT"),        # the consolidation after it
                      ("X", _day(5), 0.99, "DIVIDEND"),      # analysts do not rebase for dividends
                      ("X", _day(-5), 2.0, "SPLIT")])        # announced, not yet ex
    conn.commit()
    b = views.target_basis()
    assert b["X"]["set_by"] == _day(60) and b["X"]["factor"] == 10.0
    assert b["X"]["close_at_set"] == pytest.approx(140.0)               # 14 then, on today's basis
    assert b["Y"] == {"set_by": None, "factor": 1.0, "close_at_set": None}
    assert set(views.target_basis(["Y"])) == {"Y"}


def test_cockpit_shows_upside_only_for_an_ok_target():
    from cockpit.api import _enrich_consensus

    def up(row, basis=None):
        return _enrich_consensus({"price_target_median": row["price_target"], **row}, 100.0, basis)

    ok = up({"price_target": 12.0, "total_analysts": 5}, {"set_by": _day(30), "factor": 10.0, "close_at_set": 95.0})
    assert (ok["pt_status"], ok["pt_upside_median_pct"], ok["pt_rebased_factor"]) == ("ok", 20.0, 10.0)
    assert "rebased" in ok["pt_note"]
    thin = up({"price_target": 120.0, "total_analysts": 1})
    assert thin["pt_status"] == "thin" and thin["price_target"] == 120.0 and "pt_upside_median_pct" not in thin
    assert "1 analyst" in thin["pt_note"]
    stale = up({"price_target": 120.0, "total_analysts": 5}, {"set_by": _day(90), "factor": 1.0, "close_at_set": 50.0})
    assert stale["pt_status"] == "stale" and "pt_upside_pct" not in stale and "+100%" in stale["pt_note"]
    bad = up({"price_target": 400.0, "total_analysts": 5})
    assert bad["pt_status"] == "implausible" and bad["price_target"] is None
