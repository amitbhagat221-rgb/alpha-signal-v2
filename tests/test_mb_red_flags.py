"""Plan 0026 4b.1: the multibagger red-flag gate reads BSE and NSE announcements (signals.multibagger.red_flag_events),
and the event watch (signals.mb_watch) sees an NSE auditor resignation and NSE government orders. Temp DB only."""
import sqlite3

import pandas as pd
import pytest

import db
from signals import mb_watch
from signals import multibagger as mb

AS_OF = "2026-10-19"


def _bse(c, news_id, sid, subcategory, dt, sub="", headline="h"):
    c.execute("INSERT INTO bse_announcements (news_id, scrip_cd, sid, headline, news_sub, subcategory, dt_tm, fetched_at) "
              "VALUES (?, 1, ?, ?, ?, ?, ?, 'now')", (news_id, sid, headline, sub, subcategory, dt))


def _nse(c, seq, sid, desc, subject, an_dt, category="other", url=None):
    c.execute("INSERT INTO nse_announcements (seq_id, symbol, sid, desc_category, category, subject, an_dt, "
              "attachment_url, fetched_at) VALUES (?, 'SYM', ?, ?, ?, ?, ?, ?, 'now')",
              (seq, sid, desc, category, subject, an_dt, url))


@pytest.fixture()
def tmpdb(tmp_path, monkeypatch):
    path = tmp_path / "alpha_signal.db"
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA_PATH.read_text())
    # BSE history (the backtest-era source) — BSE's last row is 2026-10-12, as in production
    _bse(c, "b1", "OLDB", "Resignation of Statutory Auditors", "2026-03-01T10:00:00", "Resignation of auditor")
    _bse(c, "b2", "CIRB", "Updates - Corporate Insolvency Resolution Process  (CIRP)", "2026-10-12T19:28:03")
    _bse(c, "b3", "STALE", "Resignation of Statutory Auditors", "2025-09-01T10:00:00")       # > 365 days before AS_OF
    _bse(c, "b4", "ROTB", "Change in Auditors", "2026-10-01T10:00:00")                       # not a flag on BSE
    # the same filing on both exchanges, a day apart -> one event (BSE's)
    _bse(c, "b5", "BOTH", "Resignation of Statutory Auditors", "2026-10-10T18:00:00", "BSE copy")
    _nse(c, "n5", "BOTH", "Resignation of Statutory Auditor", "NSE copy", "2026-10-11 09:00:00")
    # same sid and kind but 9 days apart -> two events
    _nse(c, "n6", "CIRB", "Corporate Insolvency Resolution Process", "CoC meeting", "2026-10-21 10:00:00", "insolvency")
    _nse(c, "n7", "CIRB", "Corporate Insolvency Resolution Process", "CoC meeting", "2026-10-03 10:00:00", "insolvency")
    # NSE-only events after BSE went dark
    _nse(c, "n1", "NEWA", "Resignation of Statutory Auditor", "X has informed the Exchange about Resignation of "
         "Statutory Auditor", "2026-10-14 18:38:43")
    _nse(c, "n2", "NEWG", "General Updates", "Intimation of resignation of the Statutory Auditor of the Company",
         "2026-10-15 11:00:00")
    _nse(c, "n3", "NEWC", "Corporate Insolvency Resolution Process", "CIRP update", "2026-10-16 12:00:00", "insolvency")
    # PIT: filed after AS_OF
    _nse(c, "n4", "LATE", "Resignation of Statutory Auditor", "late", "2026-10-20 09:00:00")
    # NOT red flags: a rotation, an appointment, CIRP keywords in a generic desc (acquiring a firm out of CIRP),
    # an internal auditor, an unmapped stock
    _nse(c, "x1", "ROTN", "Change in Auditors", "informed regarding Change in Auditors", "2026-10-13 10:00:00",
         "auditor_resignation")
    _nse(c, "x2", "APPT", "Outcome of Board Meeting", "appointment of Statutory Auditors", "2026-10-13 10:00:00",
         "auditor_resignation")
    _nse(c, "x3", "ACQ", "General Updates", "Acquisition of shares in Y through CIRP vide NCLT order",
         "2026-10-12 10:00:00", "insolvency")
    _nse(c, "x4", "INTA", "Change in Management", "appointment of Internal Auditor", "2026-10-16 10:00:00",
         "management_change")
    _nse(c, "x5", None, "Resignation of Statutory Auditor", "unmapped", "2026-10-09 10:00:00")
    c.commit()
    c.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def test_both_sources_dedupe_and_point_in_time(tmpdb):
    ev = mb.red_flag_events(AS_OF)
    assert list(ev.columns) == mb.RED_FLAG_COLS
    got = {(r.sid, r.kind, str(r.date.date()), r.source) for r in ev.itertuples()}
    assert got == {
        ("OLDB", "auditor_resignation", "2026-03-01", "bse_announcements"),
        ("CIRB", "cirp", "2026-10-12", "bse_announcements"),
        ("CIRB", "cirp", "2026-10-03", "nse_announcements"),           # 9 days from BSE's: a separate event
        ("BOTH", "auditor_resignation", "2026-10-10", "bse_announcements"),
        ("NEWA", "auditor_resignation", "2026-10-14", "nse_announcements"),
        ("NEWG", "auditor_resignation", "2026-10-15", "nse_announcements"),
        ("NEWC", "cirp", "2026-10-16", "nse_announcements"),
    }
    assert ev["date"].is_monotonic_decreasing
    assert ev.loc[ev["sid"] == "BOTH", "headline"].tolist() == ["BSE copy"]


def test_as_of_cuts_later_filings_and_the_window(tmpdb):
    ev = mb.red_flag_events("2026-10-13")                  # before every NSE-only event
    assert set(ev["sid"]) == {"OLDB", "CIRB", "BOTH"}
    ev = mb.red_flag_events("2026-10-21")                  # LATE and the second CIRB filing now count
    assert {"LATE", "CIRB"} <= set(ev["sid"])
    assert (ev["sid"] == "CIRB").sum() == 3
    assert "STALE" in set(mb.red_flag_events("2026-08-01")["sid"])
    assert "STALE" not in set(mb.red_flag_events(AS_OF)["sid"])


def test_red_flags_gate_set_and_newest_dates(tmpdb):
    flagged, newest = mb._red_flags(AS_OF)
    assert flagged == {"OLDB", "CIRB", "BOTH", "NEWA", "NEWG", "NEWC"}
    assert newest == {"bse": "2026-10-12", "nse": "2026-10-21"}


def test_explicit_connection_reads_the_same(tmpdb):
    c = sqlite3.connect(f"file:{tmpdb}?mode=ro", uri=True)
    try:
        assert mb.red_flag_events(AS_OF, conn=c).equals(mb.red_flag_events(AS_OF))
    finally:
        c.close()


def test_empty_tables_give_an_empty_frame(tmp_path, monkeypatch):
    path = tmp_path / "empty.db"
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA_PATH.read_text())
    c.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    ev = mb.red_flag_events(AS_OF)
    assert ev.empty and list(ev.columns) == mb.RED_FLAG_COLS


# ───────────── the event watch ─────────────

def test_watch_sees_an_nse_auditor_resignation_stored_as_other(tmpdb):
    c = sqlite3.connect(f"file:{tmpdb}?mode=ro", uri=True)
    try:
        t = mb_watch.timeline("NEWA", conn=c)
        assert t["category"].tolist() == ["auditor_resignation"] and t["severity"].tolist() == ["high"]
        n = mb_watch.new_since(["NEWA"], "2026-10-13", conn=c)
        assert n["sid"].tolist() == ["NEWA"]
        # the timeline keeps its same-day dedupe: copies a day apart are both shown (the gate counts one)
        both = mb_watch.timeline("BOTH", conn=c)
        assert set(both["source"]) == {"bse_announcements", "nse_announcements"}
        assert set(both["category"]) == {"auditor_resignation"}
    finally:
        c.close()


def test_govt_links_reads_nse_orders(tmp_path):
    path = tmp_path / "g.db"
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA_PATH.read_text())
    _bse(c, "o1", "GOV", "Award of Order / Receipt of Order", "2026-10-05T10:00:00", "Order from Ministry of Defence")
    _nse(c, "o2", "GOV", "Bagging/Receiving of orders/contracts", "Order from Ministry of Defence",
         "2026-10-06 10:00:00", "order_win", "u2")                                  # BSE's copy -> dropped
    _nse(c, "o3", "GOV", "Bagging/Receiving of orders/contracts", "Order received from NTPC Limited",
         "2026-10-15 10:00:00", "order_win", "u3")
    _nse(c, "o4", "GOV", "Agreements", "MoU with the Government of Odisha", "2026-10-16 10:00:00", "other", "u4")
    _nse(c, "o5", "GOV", "Bagging/Receiving of orders/contracts", "Order from a private buyer",
         "2026-10-17 10:00:00", "order_win")
    _nse(c, "o6", "GOV", "Press Release", "Ministry of Corporate Affairs approves name change", "2026-10-17 10:00:00")
    c.commit()
    g = mb_watch.govt_links("GOV", conn=c)
    c.close()
    assert [(o["date"], o["url"]) for o in g["govt_orders"]] == [
        ("2026-10-16", "u4"), ("2026-10-15", "u3"), ("2026-10-05", None)]
    assert g["n_govt_orders"] == 3
    assert g["govt_orders"][1]["matched"] == ["NTPC"]
