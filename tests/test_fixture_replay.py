"""Replay saved REAL upstream responses through the real parsers — offline (plan 0018
test ladder rung 1). Fixtures in tests/fixtures/feeds/ are minimal, scrubbed slices
of canary captures (`python -m tools.canary --save-fixtures`; MANIFEST.json says
when). When an upstream changes shape: fix the parser, --accept the canary, refresh
the fixtures — these tests then pin the new shape.

Also here: the write-contract gate, the volume band and the Gate-3 verdict rules.
"""
import gzip
import json
import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import db

FIX = Path(__file__).resolve().parent / "fixtures" / "feeds"


def _text(name):
    return gzip.decompress((FIX / name).read_bytes()).decode("utf-8")


class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.content = text, status, text.encode()
        self.headers = {"content-type": "text/csv"}


# ─────────────────────────────── replays ───────────────────────────────

def test_bhavcopy_replays_through_the_real_fetch(monkeypatch):
    from sources import nse
    monkeypatch.setattr(nse._http, "polite_get", lambda url, **kw: _Resp(_text("nse_bhavcopy.csv.gz")))
    df, errs = nse._fetch_date(date(2026, 9, 25))
    assert df is not None, errs
    assert len(df) >= nse.MIN_ROWS and {"sid", "date", "close", "volume", "delivery_pct"} <= set(df.columns)
    assert db.check_contract(df, "stock_prices") == []                     # real rows pass the write gate


def test_bulk_deals_replay_and_contract():
    from sources import nse_bulk
    df = nse_bulk._parse_deals(_text("nse_bulk_deals.csv.gz"), "bulk")
    assert len(df) >= 20 and (df["price"] > 0).mean() > 0.95
    assert db.check_contract(df, "bulk_deals") == []
    broken = df.assign(price=0.0)                          # the 2026-05 bug, replayed
    assert db.check_contract(broken, "bulk_deals") == ["price: all %d values zero/empty" % len(df)]


def test_amfi_navall_replay():
    from sources.mf_amfi_master import parse_navall
    rows = parse_navall(_text("amfi_nav.txt.gz"))
    assert len(rows) >= 100 and all(r["scheme_code"] and r["nav"] is not None for r in rows[:50])


def test_screener_page_replay():
    from sources.screener_pull import parse_shareholders
    html = _text("screener.html.gz")
    shp = parse_shareholders(html)
    assert len(shp) == 12 and shp[0][0] == "2023-09-30" and all(n > 0 for _, n in shp)
    assert re.search(r'formaction=["\'](/user/company/export/\d+/)["\']', html), "export button shape"


def test_rss_replay():
    import feedparser
    from sources import rss
    feed = feedparser.parse(_text("rss_news.xml.gz"))
    assert len(feed.entries) >= 10 and all(e.get("title") and e.get("link") for e in feed.entries[:10])
    assert rss._parse_date(feed.entries[0]) is not None


def test_etmoney_sitemap_replay():
    """The portfolio sitemap still lists /{slug}/portfolio-details/{id} — the URL shape
    mf_holdings_scrape builds (sources/mf_holdings_scrape.py fetch URL)."""
    hits = re.findall(r"<loc>https://www\.etmoney\.com/mutual-funds/([^/<]+)/portfolio-details/(\d+)</loc>",
                      _text("mf_holdings.xml.gz"))
    assert len(hits) >= 100


def test_nse_json_replays():
    ins = json.loads(_text("nse_insider.json.gz"))["data"]
    assert ins and {"symbol", "xmlFileName"} <= set(ins[0])
    flows = json.loads(_text("nse_market_daily.json.gz"))
    assert flows and {"category", "date", "buyValue", "sellValue", "netValue"} <= set(flows[0])


def test_manifest_covers_every_fixture():
    man = json.loads((FIX / "MANIFEST.json").read_text())
    assert {v["file"] for v in man.values()} == {p.name for p in FIX.glob("*.gz")}


# ─────────────────────────────── write contract gate ───────────────────────────────

def test_contract_blocks_before_write(monkeypatch, tmp_path):
    import sqlite3
    path = tmp_path / "c.db"
    sqlite3.connect(path).execute("CREATE TABLE bulk_deals (symbol TEXT, price REAL, quantity REAL)").connection.commit()
    monkeypatch.setattr(db, "DB_PATH", path)
    bad = pd.DataFrame({"symbol": ["X"] * 25, "price": [0.0] * 25, "quantity": [10.0] * 25})
    with pytest.raises(db.ContractViolation, match="price: all 25 values zero"):
        db.insert_df(bad, "bulk_deals")
    assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM bulk_deals").fetchone()[0] == 0, "nothing written"
    assert db.insert_df(bad.head(5), "bulk_deals") == 5, "small batches are not judged"
    ok = bad.assign(price=100.0)
    assert db.insert_df(ok, "bulk_deals") == 25
    assert db.check_contract(pd.DataFrame({"sid": ["a"] * 30}), "shareholding") == [], "absent columns pass"


# ─────────────────────────────── volume band ───────────────────────────────

def test_volume_band_self_calibrates(monkeypatch):
    import checks.feeds as CF
    stable = [2000] * 30 + [900]                          # a stable step suddenly at 45 %
    noisy = [100, 5, 300, 20, 1, 250, 8, 400, 30, 2] * 3 + [3]
    hist = pd.DataFrame([("fetch_bhavcopy", i, r) for i, r in enumerate(stable)] +
                        [("fetch_corp_actions", 100 + i, r) for i, r in enumerate(noisy)],
                        columns=["step", "ord", "rows"])
    monkeypatch.setattr("db.read_sql", lambda q, params=None: hist if "pipeline_log" in q else pd.DataFrame(columns=hist.columns))
    b = CF.volume_bands(["fetch_bhavcopy", "fetch_corp_actions"])
    assert b["fetch_bhavcopy"]["stable"] and round(b["fetch_bhavcopy"]["ratio"], 2) == 0.45
    assert not b["fetch_corp_actions"]["stable"], "noisy steps are never judged"


def _row(tier="T1", volume=None, reconcile=None):
    return {"feed": "f", "tier": tier, "status": "production", "canary": None, "canary_last": None,
            "canary_prev": None, "canary_gates": [], "schedule": ["step:x"], "resilience": "fallback",
            "serve_stale_days": 1, "fallback_plan": None, "notes": None, "volume": volume or {}, "reconcile": reconcile}


def _sev(row, code):
    from checks.feeds import feed_verdicts
    return [v["severity"] for v in feed_verdicts([row]) if v["code"] == code]


def test_volume_and_reconcile_verdicts(monkeypatch):
    # hermetic: run.sh backfill writes output/backfill_active, which turns a spike into INFO (91f317b);
    # the test must not depend on whether a backfill window is open on this machine
    monkeypatch.setattr("checks.feeds.backfill_active", lambda *a, **k: False)
    band = lambda ratio, stable=True: {"x": {"last": 1, "median": 1.0, "ratio": ratio, "stable": stable, "n": 30}}
    assert _sev(_row(volume=band(0.45)), "FEED_VOLUME_DROP") == ["WARN"]
    assert _sev(_row(volume=band(0.10)), "FEED_VOLUME_DROP") == ["CRITICAL"]
    assert _sev(_row(tier="T2", volume=band(0.10)), "FEED_VOLUME_DROP") == ["WARN"]
    assert _sev(_row(volume=band(0.10, stable=False)), "FEED_VOLUME_DROP") == []
    assert _sev(_row(volume=band(4.0)), "FEED_VOLUME_SPIKE") == ["WARN"]
    monkeypatch.setattr("checks.feeds.backfill_active", lambda *a, **k: True)
    assert _sev(_row(volume=band(4.0)), "FEED_VOLUME_SPIKE") == ["INFO"]      # a declared backfill: expected
    assert _sev(_row(volume=band(0.10)), "FEED_VOLUME_DROP") == ["CRITICAL"]  # a drop still alarms
    monkeypatch.setattr("checks.feeds.backfill_active", lambda *a, **k: False)
    assert _sev(_row(reconcile={"status": "FAIL", "detail": "{}"}), "FEED_RECONCILE_FAIL") == ["CRITICAL"]
    assert _sev(_row(tier="T2", reconcile={"status": "FAIL", "detail": "{}"}), "FEED_RECONCILE_FAIL") == ["WARN"]
    assert _sev(_row(reconcile={"status": "PASS", "detail": "{}"}), "FEED_RECONCILE_FAIL") == []


def test_reconcile_agreement_rules():
    from tools.reconcile import agreement, verdict_of
    n, share, worst = agreement([("A", 100.0, 100.2), ("B", 50.0, 50.0), ("C", 10.0, 20.0)], 0.005)
    assert n == 3 and round(share, 2) == 0.67 and worst[0][0] == "C"
    assert verdict_of(0.95, 20, 0.9, 0.7) == "PASS" and verdict_of(0.75, 20, 0.9, 0.7) == "WARN"
    assert verdict_of(0.5, 20, 0.9, 0.7) == "FAIL" and verdict_of(1.0, 3, 0.9, 0.7) == "WARN", "too few to vouch"
