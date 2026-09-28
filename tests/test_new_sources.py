"""New sources onboarded 2026-09-28 (plan 0018): NSE event streams, Yahoo estimates,
Screener shareholder counts. Offline — no network, no live DB writes."""
import sqlite3

import pandas as pd
import pytest

from sources import nse_events as ne
from sources import yahoo_estimates as ye
from sources.screener_pull import parse_shareholders


# ─────────────────────────────── credit ratings ───────────────────────────────

@pytest.mark.parametrize("new,old,act,want", [
    ("Crisil A-/Stable", "Crisil A/Stable", "Other", "downgrade"),        # hidden under "Other"
    ("CARE AA; Stable", "CARE AA-; Positive", "Upgrade", "upgrade"),
    ("[ICRA]A+(Stable)", "[ICRA]A+(Stable)", "Reaffirm", "reaffirm"),
    ("CRISIL A1+", "CRISIL A1+", "", "reaffirm"),
    ("Crisil A2+", "Crisil A1", "Other", "downgrade"),                   # short-term scale
    ("CARE D", "CARE BB; Stable", "", "downgrade"),
    ("CRISIL AAA/Stable", None, "New", "new"),
    ("Withdrawn", "CARE A; Stable", "Withdrawal", "withdrawn"),
    ("IND AA/Stable", "CRISIL A1+", "Reaffirm", "reaffirm"),              # different scales → label
])
def test_rating_direction(new, old, act, want):
    assert ne.rating_direction(new, old, act) == want


def test_rating_rows_link_debt_isin_to_equity_by_issuer_prefix():
    raw = [{"AppID": "1", "Symbol": "NOTLISTED", "ISIN": "INE572J07123", "ISIN_ER": "",
            "NameOfCRAgency": "CARE", "CreditRating": "CARE A-; Stable", "CreditRatingEarlier": "CARE A; Stable",
            "RatingAction": "Other", "DateofCR": "13-06-2025", "BroadcastDateTime": "14-06-2025 10:05:00"}]
    rows = ne.rating_rows(raw, tick={}, isin_map={}, prefix={"INE572J": "SPANDANA"}, now="t")
    typ, sub, sid, when, avail, src, key, payload, fetched = rows[0]
    assert (typ, sub, sid) == ("credit_rating", "downgrade", "SPANDANA")
    assert when.startswith("2025-06-13") and avail.startswith("2025-06-14T10:05"), "available_at = broadcast (PIT)"
    assert '"notches": -1' in payload, "notches > 0 = upgrade, < 0 = downgrade"


def test_ipo_lockins_and_index_rows():
    l30, l90 = ne._lockins("2026-09-25T00:00:00")
    assert l30 == "2026-10-24" and l90 == "2026-12-23"        # allotment = 1 business day before listing
    frames = {"Nifty 50": pd.DataFrame({"Index Name": ["Nifty 50"], "Event Date": [pd.Timestamp("2020-07-31")],
                                        "Scrip Name": ["HDFC Life Insurance Company Ltd."],
                                        "Description": ["Inclusion into Index"]})}
    rows = ne.index_rows(frames, {ne._norm("HDFC Life Insurance Company Limited"): "HDFL"}, "t")
    assert rows[0][:3] == ["index_change", "inclusion", "HDFL"]


# ─────────────────────────────── Yahoo estimates ───────────────────────────────

def test_history_rows_pit_labels():
    ed = pd.DataFrame({"EPS Estimate": [16.3, 14.97], "Reported EPS": [float("nan"), 15.48], "Surprise(%)": [float("nan"), 3.38]},
                      index=pd.DatetimeIndex([pd.Timestamp("2099-10-16 09:00", tz="Asia/Kolkata"),
                                              pd.Timestamp("2026-07-17 09:00", tz="Asia/Kolkata")]))
    rows = ye.history_rows("RELI", ed, now="2026-09-28T12:00:00+00:00")
    by = {(r[1], r[2]): r for r in rows}
    up = by[("eps_estimate", "2099-10-16")]
    assert up[5] == "upcoming" and up[6] == "2026-09-28T12:00:00+00:00", "a future estimate is known NOW"
    past = by[("eps_estimate", "2026-07-17")]
    assert past[5] == "pit_unverified" and past[6].startswith("2026-07-17T03:30")
    assert ("eps_actual", "2099-10-16") not in by, "NaN actuals are not stored"


def test_write_versioned(monkeypatch, tmp_path):
    import db
    path = tmp_path / "e.db"
    s = db.SCHEMA_PATH.read_text()
    i = s.index("CREATE TABLE IF NOT EXISTS analyst_estimates")
    conn = sqlite3.connect(path)
    conn.executescript(s[i:s.index("CREATE INDEX IF NOT EXISTS idx_analyst_estimates_metric")])
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    row = ("RELI", "eps_trend_now", "yf:0q", "yahoo_trend", 16.3, None, "t0")
    assert ye.write_versioned([row]) == 1
    assert ye.write_versioned([row]) == 0, "unchanged → only last_seen_at moves"
    assert ye.write_versioned([(*row[:4], 16.9, None, "t1")]) == 1, "changed → a new version"
    n = sqlite3.connect(path).execute("SELECT COUNT(*) FROM analyst_estimates").fetchone()[0]
    assert n == 2


# ─────────────────────────────── Screener shareholder counts ───────────────────────────────

def test_parse_shareholders():
    html = ('<table class="data-table" id="quarterly-shp"><thead><tr><th></th><th>Sep 2023</th><th>Jun 2026</th></tr>'
            '</thead><tbody><tr><td>Promoters</td><td>50.1</td><td>49.9</td></tr><tr><td>No. of Shareholders</td>'
            '<td>36,98,648</td><td>46,51,863</td></tr></tbody></table>')
    assert parse_shareholders(html) == [("2023-09-30", 3698648), ("2026-06-30", 4651863)]
    wrapped = ('<div id="quarterly-shp" class="responsive-holder"><table class="data-table"><thead><tr><th></th>'
               '<th>Mar 2026</th></tr></thead><tbody><tr><td>No. of Shareholders</td><td>1,234</td></tr></tbody></table></div>')
    assert parse_shareholders(wrapped) == [("2026-03-31", 1234)], "real pages put the id on a wrapper"
    assert parse_shareholders("<html>no table</html>") == []
    assert parse_shareholders(None) == []
