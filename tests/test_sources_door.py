"""Equivalence fixtures for the Host door (plan 0015 Phase 2).

Every harvester that used to bypass (or half-bypass) sources/_http.py is driven
here, fully offline, against a fixed synthetic payload:

  * HTTP is intercepted at requests.Session.request — the one funnel that
    requests.get, session.get and session.post all reach — so the log records the
    EFFECTIVE request (method, url, params, body, merged headers, timeout,
    redirects) whichever way a module issues it.
  * Library clients (yfinance, nselib, feedparser, kiteconnect, Bharat_sm_data)
    are replaced by fakes that stamp the virtual clock.
  * time.monotonic / time.sleep run on a virtual clock, so pacing is measured
    exactly and costs no wall time.

Each test snapshots (a) what was parsed / written and (b) the request log, and
asserts both equal SNAP[...] — captured from the pre-door code. Gap assertions
check the per-host minimum gap is never below what the old code kept.
"""
import contextlib
import gzip
import io
import json
import os
import re
import sys
import time
import types
from datetime import date as _real_date, datetime
from urllib.parse import urlsplit

import pandas as pd
import pytest
import requests
from requests.structures import CaseInsensitiveDict

from sources import _http

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


# ───────────────────────────── harness ─────────────────────────────

class Net:
    """Virtual clock + HTTP router + request/library-call log."""

    def __init__(self):
        self.now = 1_000_000.0
        self.sleeps = []
        self.log = []          # HTTP requests
        self.lib = []          # library-client calls: (t, host, name, args)
        self.routes = []       # (method, regex, response-or-callable)

    # clock
    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        if s > 0:
            self.now += s

    # routing
    def route(self, method, pattern, resp):
        self.routes.append((method.upper(), re.compile(pattern), resp))

    def _handle(self, session, method, url, **kw):
        headers = CaseInsensitiveDict(session.headers)
        headers.update(kw.get("headers") or {})
        merged = {k: v for k, v in headers.items() if v is not None}
        self.log.append({
            "t": self.now, "method": method.upper(), "url": url,
            "params": kw.get("params"), "data": kw.get("data"),
            "headers": dict(sorted(merged.items())),
            "timeout": kw.get("timeout"), "allow_redirects": kw.get("allow_redirects", True),
        })
        for m, rx, resp in self.routes:
            if m == method.upper() and rx.search(url):
                out = resp(url, kw) if callable(resp) else resp
                if isinstance(out, Exception):
                    raise out
                return out
        raise requests.ConnectionError(f"no route for {method} {url}")

    def call(self, host, name, *args):
        self.lib.append({"t": self.now, "host": host, "name": name, "args": list(args)})

    # views
    def requests_view(self):
        return [{k: v for k, v in r.items() if k != "t"} for r in self.log]

    def gaps(self, host):
        """Seconds between consecutive calls to `host` (HTTP + library)."""
        ts = sorted([r["t"] for r in self.log if urlsplit(r["url"]).netloc == host]
                    + [c["t"] for c in self.lib if c["host"] == host])
        return [b - a for a, b in zip(ts, ts[1:])]


def resp(status=200, body=b"", headers=None, url="https://x.test/"):
    r = requests.Response()
    r.status_code = status
    r._content = body.encode() if isinstance(body, str) else body
    r.headers.update(headers or {})
    r.url = url
    r.encoding = "utf-8"
    return r


def jresp(obj, status=200):
    return resp(status, json.dumps(obj), {"Content-Type": "application/json"})


@pytest.fixture
def net(monkeypatch):
    n = Net()
    monkeypatch.setattr(time, "monotonic", n.monotonic)
    monkeypatch.setattr(time, "sleep", n.sleep)
    monkeypatch.setattr(_http, "_LAST_CALL", {})
    monkeypatch.setattr(_http, "_SID_MAPS", {})

    def fake_request(self, method, url, **kw):
        return n._handle(self, method, url, **kw)

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)
    return n


class FakeConn:
    def __init__(self, sink):
        self.sink = sink
        self.total_changes = 0

    def execute(self, sql, params=()):
        self.sink.append(("execute", " ".join(sql.split()), list(params)))
        self.total_changes += 1
        return self

    def executemany(self, sql, rows):
        rows = [list(r) for r in rows]
        self.sink.append(("executemany", " ".join(sql.split()), rows))
        self.total_changes += len(rows)
        cur = types.SimpleNamespace(rowcount=len(rows))
        return cur

    def fetchall(self):
        return []


def fake_get_db(sink):
    @contextlib.contextmanager
    def get_db(*a, **k):
        yield FakeConn(sink)
    return get_db


def frozen_date(y, m, d):
    class _D(_real_date):
        @classmethod
        def today(cls):
            return cls(y, m, d)
    return _D


def records(df, drop=("fetched_at",)):
    if df is None:
        return None
    if isinstance(df, list):
        return [{k: v for k, v in r.items() if k not in drop} if isinstance(r, dict) else r
                for r in df]
    return json.loads(df.drop(columns=[c for c in drop if c in df.columns])
                      .to_json(orient="records", date_format="iso"))


def canon(obj):
    return json.loads(json.dumps(obj, sort_keys=True, default=str))


def check(name, obj):
    got = canon(obj)
    out = os.environ.get("DOOR_SNAP_OUT")   # capture mode: record, don't compare
    if out:
        data = json.loads(open(out).read()) if os.path.exists(out) else {}
        data[name] = got
        with open(out, "w") as f:
            json.dump(data, f, indent=1, sort_keys=True, ensure_ascii=False)
        return
    assert name in SNAP, f"no snapshot for {name}"
    assert got == SNAP[name], f"{name} differs from the pre-door snapshot"


def gap_note(net, host):
    """Capture mode: log the min gap the code kept per host (evidence for the
    'never lower' gate). The door's own gap guarantees are asserted separately."""
    out = os.environ.get("DOOR_GAPS_OUT")
    if out:
        g = net.gaps(host)
        test = os.environ.get("PYTEST_CURRENT_TEST", "").split(" ")[0].split("::")[-1]
        with open(out, "a") as f:
            f.write(f"{test}\t{host}\tcalls={len(g) + 1}\tmin_gap={min(g) if g else None}\n")


class _Verdict:
    status = "PASS"
    reason = ""


def _patch_identity(monkeypatch):
    import validators.identity_check as ic
    monkeypatch.setattr(ic, "verify_identity", lambda *a, **k: _Verdict())
    monkeypatch.setattr(ic, "record_verdict", lambda *a, **k: None)
    monkeypatch.setattr(ic, "quarantine_row", lambda *a, **k: None)


# ───────────────────────────── Screener.in ─────────────────────────────

def _screener_cookie(monkeypatch, tmp_path):
    from sources import screener_pull
    f = tmp_path / "cookie.json"
    f.write_text(json.dumps({"sessionid": "sess", "csrftoken": "csrf"}))
    monkeypatch.setattr(screener_pull, "COOKIE_FILE", f)


def _xlsx():
    rows = [
        ["PROFIT & LOSS", None, None],
        ["Report Date", datetime(2024, 3, 31), datetime(2025, 3, 31)],
        ["Sales", 100.0, 120.5],
        ["Net profit", 10.0, 12.25],
        [None, None, None],
        ["Quarters", None, None],
        ["Report Date", datetime(2025, 6, 30), datetime(2025, 9, 30)],
        ["Sales", 30.0, 32.0],
        [None, None, None],
        ["BALANCE SHEET", None, None],
        ["Report Date", datetime(2024, 3, 31), datetime(2025, 3, 31)],
        ["Borrowings", 5.0, None],
    ]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, sheet_name="Data Sheet", header=False, index=False,
                                engine="openpyxl")
    return buf.getvalue()


def test_screener_pull_main(net, monkeypatch, tmp_path):
    from sources import screener_pull as sp
    _screener_cookie(monkeypatch, tmp_path)
    page = '<form><button formaction="/user/company/export/42/">Export</button></form>'
    net.route("GET", r"/company/TCS/consolidated/$", resp(200, page))
    net.route("GET", r"/company/INFY/consolidated/$", resp(404, "nope"))
    net.route("GET", r"/company/INFY/$", resp(200, page))
    net.route("POST", r"/user/company/export/42/$", resp(200, _xlsx()))
    monkeypatch.setattr(sp, "read_sql", lambda q, params=None: pd.DataFrame(
        {"sid": ["TCS", "INFY"], "ticker": ["TCS", "INFY"]}))
    written, errors = [], []
    monkeypatch.setattr(sp, "upsert_df", lambda df, t: written.append((t, records(df))) or len(df))
    monkeypatch.setattr(sp, "insert_df", lambda df, t: errors.append((t, records(df, ("attempted_at",)))))
    monkeypatch.setattr(sys, "argv", ["screener_pull", "--tier", "LARGE"])
    assert sp.main() == 0
    check("screener_pull.written", written)
    check("screener_pull.errors", errors)
    check("screener_pull.requests", net.requests_view())
    gap_note(net, "www.screener.in")


def test_screener_schedules_main(net, monkeypatch, tmp_path):
    from sources import screener_schedules as ss
    _screener_cookie(monkeypatch, tmp_path)
    net.route("GET", r"/company/TCS/consolidated/$", resp(200, 'x data-url="/api/company/77/add/" y'))
    net.route("GET", r"/company/INFY/consolidated/$", resp(404))
    net.route("GET", r"/company/INFY/$", resp(200, '<a href="/api/company/88/chat/">c</a>'))
    net.route("GET", r"/api/company/\d+/schedules/", lambda url, kw: jresp(
        {f"{kw['params']['parent']} A": {"Mar 2024": "1,234", "Mar 2025": "-", "Dec 2025": 7},
         "junk": [1, 2]}))
    monkeypatch.setattr(ss, "read_sql", lambda q, params=None: pd.DataFrame(
        {"sid": ["TCS", "INFY"], "ticker": ["TCS", "INFY"]}))
    written = []
    monkeypatch.setattr(ss, "upsert_df", lambda df, t: written.append((t, records(df))) or len(df))
    monkeypatch.setattr(ss, "insert_df", lambda df, t: pytest.fail("no errors expected"))
    monkeypatch.setattr(sys, "argv", ["screener_schedules", "--tier", "LARGE"])
    assert ss.main() == 0
    check("screener_schedules.written", written)
    check("screener_schedules.requests", net.requests_view())
    gap_note(net, "www.screener.in")


_BANK_PAGE = """<html><h1>HDFC Bank Ltd</h1>
<section id="quarters"><table><thead><tr><th></th><th>Jun 2025</th><th>Sep 2025</th></tr></thead>
<tbody><tr><td>Revenue+</td><td>1,000</td><td>1,100</td></tr>
<tr><td>Interest</td><td>600</td><td>650</td></tr>
<tr><td>Gross NPA %</td><td>1.5%</td><td>1.4%</td></tr>
<tr><td>Net NPA %</td><td>0.4%</td><td>(0.1)</td></tr></tbody></table></section>
<section id="profit-loss"><table><thead><tr><th></th><th>Mar 2024</th><th>Mar 2025</th><th>TTM</th></tr></thead>
<tbody><tr><td>Revenue+</td><td>4,000</td><td>4,400</td><td>4,500</td></tr>
<tr><td>Interest</td><td>2,400</td><td>2,500</td><td>2,550</td></tr>
<tr><td>Net Profit+</td><td>900</td><td>1,000</td><td>1,050</td></tr></tbody></table></section>
<section id="balance-sheet"><table><thead><tr><th></th><th>Mar 2024</th><th>Mar 2025</th></tr></thead>
<tbody><tr><td>Equity Capital</td><td>100</td><td>100</td></tr>
<tr><td>Reserves</td><td>9,900</td><td>10,900</td></tr>
<tr><td>Deposits</td><td>40,000</td><td>44,000</td></tr>
<tr><td>Borrowing</td><td>10,000</td><td>11,000</td></tr></tbody></table></section></html>"""


def test_banking_metrics_compute_universe(net, monkeypatch, tmp_path):
    from sources import banking_metrics as bm
    import validators.plausibility as vp
    _screener_cookie(monkeypatch, tmp_path)
    _patch_identity(monkeypatch)
    monkeypatch.setattr(vp, "verify_plausibility",
                        lambda *a, **k: types.SimpleNamespace(status="OK"))
    net.route("GET", r"screener\.in/$", resp(200, "<a href='/logout/'>logout</a>"))
    net.route("GET", r"/company/HDBK/$", resp(200, _BANK_PAGE))
    net.route("GET", r"/company/ICBK/$", resp(404))
    net.route("GET", r"/company/ICBK/consolidated/$", resp(200, _BANK_PAGE))

    def fake_read_sql(q, params=None):
        if "No. of Equity Shares" in q:
            return pd.DataFrame({"value": [1e9]})
        if "SELECT name FROM stocks" in q:
            return pd.DataFrame({"name": ["HDFC Bank Ltd"]})
        return pd.DataFrame({"sid": ["HDBK", "ICBK"], "ticker": ["HDBK", "ICBK"],
                             "industry": ["Banks", "Banks"]})

    monkeypatch.setattr(bm, "read_sql", fake_read_sql)
    written = []
    monkeypatch.setattr(bm, "upsert_df", lambda df, t: written.append((t, records(df))) or len(df))
    assert bm.compute_universe() > 0
    check("banking_metrics.written", written)
    check("banking_metrics.requests", net.requests_view())
    gap_note(net, "www.screener.in")


_CONCALLS = """<html><div class="documents concalls"><ul>
<li><div>Apr 2026</div>
  <a href="https://www.bseindia.com/stock-share-price/AnnPdfOpen.aspx?Pname=aaa-111.pdf">Transcript</a>
  <a href="https://youtube.com/x">REC</a></li>
<li><div>Jan 2026</div>
  <a href="https://www.bseindia.com/xml-data/corpfiling/AttachLive/bbb-222.pdf">Transcript</a>
  <a href="https://www.bseindia.com/xml-data/corpfiling/AttachLive/ccc-333.pdf">PPT</a></li>
</ul></div>""" + "<!-- pad -->" * 300 + "</html>"


def test_transcripts_pull_main(net, monkeypatch, tmp_path):
    from sources import transcripts_pull as tp
    _screener_cookie(monkeypatch, tmp_path)
    net.route("GET", r"screener\.in/$", resp(200, "logout"))
    net.route("GET", r"/company/TCS/consolidated/$", resp(200, _CONCALLS))
    net.route("GET", r"/company/INFY/consolidated/$", resp(404))
    net.route("GET", r"/company/INFY/$", resp(200, _CONCALLS))
    net.route("GET", r"AttachLive/aaa-111\.pdf$", resp(404))
    net.route("GET", r"AttachHis/aaa-111\.pdf$", resp(200, b"%PDF-1.4 aaa"))
    net.route("GET", r"AttachLive/bbb-222\.pdf$", resp(200, b"%PDF-1.4 bbb"))
    monkeypatch.setattr(tp, "_extract_pdf_text", lambda b: (
        f"Earnings call held on April 27, 2026. {b.decode()}", 3))

    def fake_read_sql(q, params=None):
        if "FROM transcripts" in q:
            return pd.DataFrame({"source_url": []})
        if "FROM bse_announcements" in q:
            return pd.DataFrame({"attachment": ["aaa-111.pdf"], "d": ["2026-04-28"]})
        return pd.DataFrame({"sid": ["TCS", "INFY"], "ticker": ["TCS", "INFY"]})

    monkeypatch.setattr(tp, "read_sql", fake_read_sql)
    stored = []
    monkeypatch.setattr(tp, "_store_rows", lambda rows: stored.append(records(rows)) or len(rows))
    monkeypatch.setattr(sys, "argv", ["transcripts_pull", "--tier", "LARGE"])
    assert tp.main() == 0
    check("transcripts_pull.stored", stored)
    check("transcripts_pull.requests", net.requests_view())
    gap_note(net, "www.screener.in")
    gap_note(net, "www.bseindia.com")


# ───────────────────────────── BSE ─────────────────────────────

def test_bse_announcements_main(net, monkeypatch):
    from sources import bse_announcements as ba
    monkeypatch.setattr(ba, "date", frozen_date(2026, 9, 25))
    net.route("GET", r"corporates/ann\.html$", resp(200, "<html>warm</html>"))

    def page(url, kw):
        p = kw["params"]
        n = int(p["pageno"])
        rows = [{"NEWSID": f"{p['strPrevDate']}-{n}-{i}", "SCRIP_CD": 500000 + i,
                 "SLONGNAME": f" Co {i} ", "HEADLINE": "Result", "CRITICALNEWS": i % 2,
                 "DT_TM": f"{p['strPrevDate']}T10:0{i}", "PDFFLAG": "0"} for i in range(2)]
        return jresp({"Table": rows, "Table1": [{"ROWCNT": 60}]})

    net.route("GET", r"api\.bseindia\.com/BseIndiaAPI/api/AnnSubCategoryGetData/w$", page)
    stored = []
    monkeypatch.setattr(ba, "_store", lambda recs: stored.append(records(recs)) or len(recs))
    monkeypatch.setattr(sys, "argv", ["bse_announcements", "--days", "1"])
    assert ba.main() == 0
    check("bse_announcements.stored", stored)
    check("bse_announcements.requests", net.requests_view())
    gap_note(net, "api.bseindia.com")


# ───────────────────────────── ETMoney ─────────────────────────────

_ETM_HOLDINGS = """<html><p>Portfolio as on 31 Aug, 2026</p>
<table><thead><tr><th>Stocks</th><th>Sector</th><th>Value (Cr)</th><th>% of Total Holdings</th></tr></thead>
<tbody><tr><td><a href="/stocks/hdfc-bank/123">HDFC Bank Ltd.</a></td><td>Financial</td><td>1,234.5</td><td>9.5%</td></tr>
<tr><td>Infosys Ltd.</td><td>Technology</td><td>800</td><td>6.25%</td></tr>
<tr><td>ICICI Bank Ltd.</td><td>Financial</td><td>-</td><td>5%</td></tr></tbody></table>
""" + "<!-- pad -->" * 1000 + "</html>"


def test_mf_holdings_scrape(net, monkeypatch):
    from sources import mf_holdings_scrape as mh
    _patch_identity(monkeypatch)
    net.route("GET", r"mf-schemes-sitemap\.xml$", resp(200,
        "<loc>https://www.etmoney.com/mutual-funds/sbi-contra-direct-growth/111</loc>"))
    net.route("GET", r"mf-regular-schemes-sitemap\.xml$", resp(200,
        "<loc>https://www.etmoney.com/mutual-funds/hdfc-top-100-regular/222</loc>"
        "<loc>https://www.etmoney.com/mutual-funds/axis-bluechip/333</loc>"))
    net.route("GET", r"/portfolio-details/111$", resp(200, _ETM_HOLDINGS))
    net.route("GET", r"/portfolio-details/222$", resp(404))
    net.route("GET", r"/portfolio-details/333$", resp(200, _ETM_HOLDINGS))
    check("mf_holdings_scrape.sitemap", mh.fetch_etm_sitemap_urls())

    def fake_read_sql(q, params=None):
        if "FROM stocks" in q:
            return pd.DataFrame({"sid": ["HDBK", "INFY"], "name": ["HDFC Bank Ltd.", "Infosys Ltd."],
                                 "ticker": ["HDFCBANK", "INFY"]})
        return pd.DataFrame({"etm_id": [111, 222, 333], "sibling_codes": ["1001,1002", "2001", "3001"],
                             "etm_slug": ["sbi-contra-direct-growth", "hdfc-top-100-regular", "axis-bluechip"],
                             "scheme_name": ["SBI Contra", "HDFC Top 100", "Axis Bluechip"]})

    sink = []
    monkeypatch.setattr(mh, "read_sql", fake_read_sql)
    monkeypatch.setattr(mh, "get_db", fake_get_db(sink))
    assert mh.scrape() == 2
    check("mf_holdings_scrape.db", sink)
    check("mf_holdings_scrape.requests", net.requests_view())
    gap_note(net, "www.etmoney.com")


# ───────────────────────────── Moneycontrol ─────────────────────────────

_MC_PAGE = """<html><body>
<div class="brrs_bx"><div class="brstk_name"><h3>Motilal Oswal</h3></div>
<div class="br_date">12 Sep, 2026</div><button class="button_buy">Buy</button>
<table><tr><td>Reco Price <strong>1,000</strong></td><td>Target <strong>1,250.5</strong></td></tr></table>
<a href="https://x.test/r.pdf">pdf</a></div>
<div class="brrs_bx"><div class="brstk_name"><h3>Emkay</h3></div>
<div class="br_date">-</div><button class="button_buy">Hold</button>
<table><tr><td>Reco Price <strong>-</strong></td><td>Target <strong>990</strong></td></tr></table></div>
</body></html>"""


def test_moneycontrol_recos_compute(net, monkeypatch):
    from sources import moneycontrol_recos as mc
    monkeypatch.setattr(mc, "_date", frozen_date(2026, 9, 25))
    _patch_identity(monkeypatch)
    sug = [{"link_src": "https://www.moneycontrol.com/india/stockpricequote/banks/hdfcbank/HDF01",
            "pdt_dis_nm": "HDFC Bank&nbsp;<span>INE040A01034, HDFCBANK, 500180</span>"}]
    net.route("GET", r"autosuggestion_solr\.php$", jresp(sug))
    net.route("GET", r"/india/stockpricequote/", resp(200, _MC_PAGE))
    monkeypatch.setattr(mc, "_ensure_schema", lambda: None)
    monkeypatch.setattr(mc, "read_sql", lambda q, params=None: pd.DataFrame({
        "sid": ["RELI", "HDBK"], "ticker": ["RELIANCE", "HDFCBANK"], "name": ["Reliance", "HDFC Bank"],
        "mc_slug": ["/india/stockpricequote/refineries/relianceindustries/RI", ""]}))
    sink, written = [], []
    monkeypatch.setattr(mc, "get_db", fake_get_db(sink))
    monkeypatch.setattr(mc, "upsert_df", lambda df, t: written.append((t, records(df))) or len(df))
    monkeypatch.setattr(mc, "aggregate_consensus", lambda: 0)
    assert mc.compute(max_minutes=None) == 4
    check("moneycontrol_recos.written", written)
    check("moneycontrol_recos.db", [s for s in sink if "mc_checked_at" not in s[1]])
    check("moneycontrol_recos.requests", net.requests_view())
    gap_note(net, "www.moneycontrol.com")


# ───────────────────────────── Kite ─────────────────────────────

class _FakeKite:
    def __init__(self, net):
        self.net = net

    def historical_data(self, token, frm, to, interval):
        self.net.call("api.kite.trade", "historical_data", token, frm, to, interval)
        if token == 3:
            raise RuntimeError("Too many requests")
        return [{"date": datetime(2026, 9, 24, 9, 15 + i), "open": 10.0 + i, "high": 11.0,
                 "low": 9.5, "close": 10.5 + i, "volume": 100 * (i + 1)} for i in range(2)]


def test_kite_backfill_bars(net, monkeypatch):
    from sources import kite_pull as kp
    monkeypatch.setattr(kp, "date", frozen_date(2026, 9, 25))
    monkeypatch.setattr(kp, "_universe_tokens", lambda which: pd.DataFrame(
        {"sid": ["RELI", "TCS", "INFY"], "ticker": ["RELIANCE", "TCS", "INFY"],
         "instrument_token": [1, 2, 3]}))
    sink = []
    monkeypatch.setattr(kp, "get_db", fake_get_db(sink))
    assert kp.backfill_bars(days=5, kc=_FakeKite(net)) == 4
    check("kite_pull.db", sink)
    check("kite_pull.calls", [{k: v for k, v in c.items() if k != "t"} for c in net.lib])
    gap_note(net, "api.kite.trade")


def test_kite_auto_request_token(net, monkeypatch):
    import pyotp
    from sources import kite_pull as kp
    for k, v in {"KITE_USER_ID": "AB1234", "KITE_PASSWORD": "pw", "KITE_TOTP_SECRET": "JBSWY3DPEHPK3PXP"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(pyotp.TOTP, "now", lambda self: "123456")
    net.route("POST", r"kite\.zerodha\.com/api/login$", jresp({"data": {"request_id": "rq1"}}))
    net.route("POST", r"kite\.zerodha\.com/api/twofa$", jresp({"status": "success"}))
    r = resp(200, "ok")
    r.url = "https://127.0.0.1/callback?request_token=tok789&action=login"
    net.route("GET", r"kite\.trade/connect/login", r)
    assert kp._auto_request_token("key1") == "tok789"
    check("kite_pull.login_requests", net.requests_view())


# ───────────────────────────── Yahoo ─────────────────────────────

def _yf_frame(symbols, dates, base=100.0):
    cols = pd.MultiIndex.from_product([symbols, ["Open", "High", "Low", "Close", "Volume"]])
    data = []
    for i, _ in enumerate(dates):
        row = []
        for j, _s in enumerate(symbols):
            close = base + i + j if not (i == 0 and j == 1) else float("nan")
            row += [close - 1, close + 1, close - 2, close, 1000 * (i + 1)]
        data.append(row)
    return pd.DataFrame(data, index=pd.DatetimeIndex(dates), columns=cols)


def test_macro_yfinance_fetch_all(net, monkeypatch):
    from sources import macro_yfinance as my

    def download(symbols, **kw):
        net.call("query2.finance.yahoo.com", "download", symbols, sorted(kw.items()))
        return _yf_frame(["^NSEI", "GC=F"], ["2026-09-23", "2026-09-24"])

    monkeypatch.setattr(my.yf, "download", download)
    out = my._fetch_all("2026-09-01", "2026-09-25")
    check("macro_yfinance.out", {k: records(v) for k, v in out.items()})
    check("macro_yfinance.calls", [{k: v for k, v in c.items() if k != "t"} for c in net.lib])


def test_yfinance_prices_compute(net, monkeypatch):
    import yfinance
    from sources import yfinance_prices as yp

    def download(symbols, **kw):
        net.call("query2.finance.yahoo.com", "download", symbols, sorted(kw.items()))
        hits = [s for s in symbols if s in ("AAA.NS", "BBB.BO", "CCC.BO")]
        return _yf_frame(hits, ["2026-09-23", "2026-09-24"]) if hits else pd.DataFrame()

    monkeypatch.setattr(yfinance, "download", download)
    monkeypatch.setattr(yp, "_missing_sids", lambda days=30: pd.DataFrame(
        {"sid": ["A", "B", "C", "D"], "ticker": ["AAA", "BBB", "CCC", "DDD"],
         "cap_tier": ["SMALL"] * 4}))
    written = []
    monkeypatch.setattr(yp, "insert_df", lambda df, t: written.append((t, records(df))) or len(df))
    assert yp.compute() == 5
    check("yfinance_prices.written", written)
    check("yfinance_prices.calls", [{k: v for k, v in c.items() if k != "t"} for c in net.lib])


# ───────────────────────────── Upstox / GitHub (scrip master) ─────────────────────────────

def test_scrip_master_build_rows(net, monkeypatch):
    from sources import scrip_master as sm
    upstox = [
        {"segment": "BSE_EQ", "isin": "INE002A01018", "trading_symbol": "RELIANCE",
         "exchange_token": "500325", "name": "RELIANCE INDUSTRIES"},
        {"segment": "BSE_EQ", "isin": "INE999Z01011", "trading_symbol": "BSEONLY",
         "exchange_token": "543210", "name": "BSE ONLY LTD"},
        {"segment": "NSE_EQ", "isin": "INE002A01018", "trading_symbol": "RELIANCE"},
        {"segment": "NSE_EQ", "isin": "INE467B01029", "trading_symbol": "TCS"},
        {"segment": "NSE_FO", "isin": None, "trading_symbol": "NIFTY"},
    ]
    net.route("GET", r"assets\.upstox\.com/", resp(200, gzip.compress(json.dumps(upstox).encode())))
    net.route("GET", r"raw\.githubusercontent\.com/", resp(200,
        "Security Code,ISIN No,Security Name,Status\n"
        "500325,INE002A01018,Reliance,Active\n111111,INE111A01011,Gone Ltd,Delisted\nabc,,x,y\n"))
    monkeypatch.setattr(sm, "read_sql", lambda q, params=None: pd.DataFrame(
        {"sid": ["RELI", "TCS", "BSEO"], "ticker": ["RELIANCE", "TCS", "BSEONLY"]}))
    monkeypatch.setattr(sm, "_now", lambda: "2026-09-25T00:00:00+00:00")
    check("scrip_master.rows", sm.build_rows())
    check("scrip_master.requests", net.requests_view())


# ───────────────────────────── RSS ─────────────────────────────

def test_rss_fetch_news(net, monkeypatch):
    from sources import rss
    monkeypatch.setattr(rss, "_STOCK_INDEX", None)

    def parse(url):
        net.call(urlsplit(url).netloc, "feedparser.parse", url)
        if "livemint.com/rss/companies" in url:
            raise ValueError("bad feed")
        return types.SimpleNamespace(entries=[
            {"title": f"Reliance Industries posts record profit ({url[-12:]})",
             "summary": "<p>Analysts cheer <b>TCS</b> too</p>", "link": "https://n.test/a",
             "published_parsed": (2099, 1, 2, 3, 4, 5, 0, 0, 0)},
            {"title": "short"},
            {"title": "Macro wrap: markets end flat on the week", "published": "Fri, 25 Sep 2099"},
        ])

    monkeypatch.setattr(rss.feedparser, "parse", parse)

    def fake_read_sql(q, params=None):
        if "news_articles" in q:
            return pd.DataFrame({"article_id": []})
        return pd.DataFrame({"sid": ["RELI", "TCS"], "ticker": ["RELIANCE", "TCS"],
                             "name": ["Reliance Industries Ltd", "Tata Consultancy Services"]})

    monkeypatch.setattr(rss, "read_sql", fake_read_sql)
    written = []
    # entity matches come out of a set → order by content (hash-seed independent)
    monkeypatch.setattr(rss, "insert_df", lambda df, t: written.append(
        (t, sorted(records(df), key=lambda r: json.dumps(r, sort_keys=True)))) or len(df))
    rss.fetch_news()
    check("rss.written", written)
    check("rss.calls", [c["args"] for c in net.lib])
    for host in ("economictimes.indiatimes.com", "www.livemint.com", "www.moneycontrol.com"):
        gap_note(net, host)


# ───────────────────────────── nselib (NSE) ─────────────────────────────

def _fake_nselib(monkeypatch, net, **fns):
    def wrap(name, fn):
        def inner(*a, **k):
            net.call("www.nseindia.com", name, *a, *sorted(k.items()))
            return fn(*a, **k)
        return inner
    ns = types.SimpleNamespace(**{n: wrap(n, f) for n, f in fns.items()})
    pkg = types.ModuleType("nselib")
    pkg.capital_market = ns
    pkg.derivatives = ns
    monkeypatch.setitem(sys.modules, "nselib", pkg)


def test_nselib_pull_backfills(net, monkeypatch):
    from sources import nselib_pull as nl
    monkeypatch.setattr(nl, "date", frozen_date(2026, 9, 25))
    monkeypatch.setattr(nl._http, "sid_map", lambda col="ticker": {"RELIANCE": "RELI", "TCS": "TCS"})

    def bulk(from_date, to_date):
        if from_date.startswith("01-08"):
            raise RuntimeError("NSE says no")
        return pd.DataFrame([{"Date": "25-SEP-2026", "Symbol": "RELIANCE", "SecurityName": "Rel",
                              "ClientName": "FUND", "Buy/Sell": "BUY", "QuantityTraded": "1,000",
                              "TradePrice/Wght.Avg.Price": "1,400.50", "Remarks": "-"}])

    def corp(from_date, to_date):
        return pd.DataFrame([{"symbol": "TCS", "series": "EQ", "subject": "Dividend - Rs 10",
                              "exDate": "15-Sep-2026", "faceVal": "1"},
                             {"symbol": "RELIANCE", "series": "EQ", "subject": "Bonus 1:1",
                              "exDate": "bad", "faceVal": "10"}])

    def short(from_date, to_date):
        return pd.DataFrame([{"Symbol": "TCS", "Date": "24-Sep-2026", "Quantity": "5,000"}])

    def poi(trade_date):
        if trade_date == "23-09-2026":
            raise RuntimeError("No data")
        return pd.DataFrame([{"Client Type": "FII", "Future Index Long": 10, "Total Long Contracts": 99}])

    def idx(index, from_date, to_date):
        return pd.DataFrame([{"TIMESTAMP": "24-Sep-2026", "OPEN_INDEX_VAL": "1", "HIGH_INDEX_VAL": "2",
                              "LOW_INDEX_VAL": "0.5", "CLOSE_INDEX_VAL": "1.5", "TRADED_QTY": "10",
                              "TURN_OVER": "x"}])

    _fake_nselib(monkeypatch, net, bulk_deal_data=bulk, corporate_actions_for_equity=corp,
                 short_selling_data=short, participant_wise_open_interest=poi, index_data=idx)
    monkeypatch.setattr(nl, "read_sql", lambda q, params=None: pd.DataFrame({"trade_date": ["2026-09-24"]}))
    monkeypatch.setattr(nl, "SMART_BETA_INDICES", ["NIFTY 50", "NIFTY ALPHA 50"])
    written = []
    monkeypatch.setattr(nl, "insert_df", lambda df, t: written.append((t, records(df))) or len(df))
    nl.pull_bulk_deals(months=2)
    nl.pull_corporate_actions(months=2)
    nl.pull_short_selling(months=1)
    nl.pull_fii_positioning(days_back=4)
    nl.pull_nse_indices(months=1)
    check("nselib_pull.written", written)
    check("nselib_pull.calls", [{k: v for k, v in c.items() if k != "t"} for c in net.lib])
    gap_note(net, "www.nseindia.com")


def test_nselib_pull_surveillance_and_cash(net, monkeypatch):
    from sources import nselib_pull as nl
    monkeypatch.setattr(nl, "date", frozen_date(2026, 9, 25))
    monkeypatch.setattr(nl._http, "sid_map", lambda col="ticker": {"AMBER": "AMBE"})
    net.route("GET", r"www\.nseindia\.com/?$", resp(200, "home"))
    net.route("GET", r"/api/reportASM$", jresp({"longterm": {"data": [
        {"symbol": "amber", "stage": "I", "longterm_indicator": "x"}]}, "shortterm": {"data": []}}))
    net.route("GET", r"/api/reportGSM$", jresp([{"symbol": "ZZZ", "gsmStage": "II", "survDesc": "d"}]))
    net.route("GET", r"/api/fiidiiTradeReact$", jresp([
        {"date": "24-Sep-2026", "category": "FII/FPI ", "buyValue": "100.5", "sellValue": "90",
         "netValue": "10.5"}, {"date": "junk"}]))
    _fake_nselib(monkeypatch, net, fno_security_in_ban_period=lambda trade_date: ["AMBER", "KAYNES"])
    written = []
    monkeypatch.setattr(nl, "insert_df", lambda df, t: written.append((t, records(df))) or len(df))
    nl.pull_surveillance_today()
    nl.pull_fii_cash_flow()
    check("nselib_pull.surv_written", written)
    check("nselib_pull.surv_requests", net.requests_view())
    check("nselib_pull.surv_calls", [{k: v for k, v in c.items() if k != "t"} for c in net.lib])
    gap_note(net, "www.nseindia.com")


# ───────────────────────────── F&O bhavcopy (nselib) ─────────────────────────────

def test_fno_pull_compute(net, monkeypatch):
    from sources import fno_pull as fp
    monkeypatch.setattr(fp, "date", frozen_date(2026, 9, 25))
    monkeypatch.setattr(fp._http, "sid_map", lambda col="ticker": {"RELIANCE": "RELI"})
    monkeypatch.setattr(fp, "_existing_trade_dates", lambda: {"2026-09-22"})
    grid = pd.DataFrame([
        {"FinInstrmTp": "STO", "TckrSymb": "RELIANCE", "XpryDt": "2026-09-30", "StrkPric": 1400,
         "OptnTp": "CE", "TradDt": "2026-09-24", "ClsPric": 10.5, "SttlmPric": 10.4,
         "UndrlygPric": 1390, "OpnIntrst": 100, "ChngInOpnIntrst": 5, "TtlTradgVol": 20,
         "TtlNbOfTxsExctd": 3},
        {"FinInstrmTp": "IDF", "TckrSymb": "NIFTY", "XpryDt": "2026-09-30", "StrkPric": None,
         "OptnTp": None, "TradDt": "2026-09-24", "ClsPric": 25000, "SttlmPric": 25001,
         "UndrlygPric": 24990, "OpnIntrst": 0, "ChngInOpnIntrst": 0, "TtlTradgVol": 7,
         "TtlNbOfTxsExctd": 1},
        {"FinInstrmTp": "STK", "TckrSymb": "TCS", "XpryDt": "", "StrkPric": 0, "OptnTp": "",
         "TradDt": "2026-09-24", "ClsPric": 1, "SttlmPric": 1, "UndrlygPric": 1, "OpnIntrst": 1,
         "ChngInOpnIntrst": 0, "TtlTradgVol": 1, "TtlNbOfTxsExctd": 1},
    ])

    def bhav(trade_date):
        if trade_date == "24-09-2026":
            return grid.copy()
        if trade_date == "25-09-2026":
            return pd.DataFrame()
        raise RuntimeError("no data")

    _fake_nselib(monkeypatch, net, fno_bhav_copy=bhav)
    written = []
    monkeypatch.setattr(fp, "insert_df", lambda df, t: written.append((t, records(df))) or len(df))
    assert fp.compute(lookback_days=5) == 2
    check("fno_pull.written", written)
    check("fno_pull.calls", [{k: v for k, v in c.items() if k != "t"} for c in net.lib])
    gap_note(net, "www.nseindia.com")


# ─────────────── modules that only swap config.API for the host entry ───────────────

def test_polite_get_callers_send_same_headers(net, monkeypatch):
    """nse, nse_bulk, nse_insider, mf_amfi_master, mf_nav_backfill,
    regulatory_harvester, tickertape_analyst: identical requests before/after."""
    from sources import (mf_amfi_master, mf_nav_backfill, nse, nse_bulk, nse_insider,
                         regulatory_harvester, tickertape_analyst)
    net.route("GET", r"archives\.nseindia\.com/", resp(200, "SYMBOL,SERIES\n"))
    net.route("GET", r"www\.nseindia\.com/?$", resp(200, "home"))
    net.route("GET", r"/api/corporates-pit$", jresp({"data": [{"symbol": "X"}]}))
    net.route("GET", r"amfiindia\.com/", resp(200, "NAV"))
    net.route("GET", r"api\.mfapi\.in/", jresp({"meta": {}, "data": []}))
    net.route("GET", r"news\.google\.com/", resp(200, "<rss></rss>"))
    net.route("GET", r"pib\.gov\.in/", resp(200, "short"))
    net.route("GET", r"tickertape\.in/", resp(200, '<script id="__NEXT_DATA__">{"a": 1}</script>'))
    nse._fetch_date(_real_date(2026, 9, 24))
    monkeypatch.setattr(nse_bulk, "insert_df", lambda df, t: 0)
    with contextlib.suppress(RuntimeError):
        nse_bulk.fetch_today()
    monkeypatch.setattr(nse_insider, "date", frozen_date(2026, 9, 25))
    monkeypatch.setattr(nse_insider, "_parse_records", lambda recs: pd.DataFrame())
    nse_insider.fetch_insider(months=1)
    mf_amfi_master.fetch_navall_text()
    mf_nav_backfill.fetch_scheme_history("100")
    regulatory_harvester._google_rss_items("rbi", "2026-09-01", "2026-09-02")
    monkeypatch.setattr(regulatory_harvester, "insert_df", lambda df, t: 0)
    monkeypatch.setattr(regulatory_harvester, "read_sql", lambda q, params=None: pd.DataFrame(
        {"event_id": []}))
    with contextlib.suppress(Exception):
        regulatory_harvester.harvest_pib(start_prid=1, end_prid=2)
    assert tickertape_analyst._fetch_next_data("stocks/x-X") == {"a": 1}
    check("polite_get_callers.requests", net.requests_view())


# ───────────────────────────── snapshots ─────────────────────────────

# Captured from the pre-door code (commit 8cfbf9d) — regenerate only for an
# intentional behaviour change, and say so in the commit.
SNAP = json.loads(r"""
{
 "banking_metrics.requests": [
  {
   "allow_redirects": false,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.screener.in/"
  },
  {
   "allow_redirects": false,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.screener.in/company/HDBK/"
  },
  {
   "allow_redirects": false,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.screener.in/company/ICBK/"
  },
  {
   "allow_redirects": false,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.screener.in/company/ICBK/consolidated/"
  }
 ],
 "banking_metrics.written": [
  [
   "banking_metrics",
   [
    {
     "adj_book_per_share": null,
     "advances": null,
     "book_value_per_share": null,
     "borrowings": null,
     "car_pct": null,
     "casa_pct": null,
     "cost_of_funds_pct": null,
     "crar_pct": null,
     "credit_cost_pct": null,
     "deposits": null,
     "gross_npa_pct": 1.5,
     "interest_earned": 1000.0,
     "interest_expended": 600.0,
     "net_interest_income": 400.0,
     "net_npa_pct": 0.4,
     "net_profit": null,
     "nim_pct": null,
     "other_income": null,
     "pcr_pct": null,
     "period_end": "2025-06-30",
     "period_type": "quarterly",
     "pre_provision_op_profit": null,
     "provisions": null,
     "roa_pct": null,
     "sid": "HDBK",
     "slippage_pct": null,
     "source": "screener_in"
    },
    {
     "adj_book_per_share": null,
     "advances": null,
     "book_value_per_share": null,
     "borrowings": null,
     "car_pct": null,
     "casa_pct": null,
     "cost_of_funds_pct": null,
     "crar_pct": null,
     "credit_cost_pct": null,
     "deposits": null,
     "gross_npa_pct": 1.4,
     "interest_earned": 1100.0,
     "interest_expended": 650.0,
     "net_interest_income": 450.0,
     "net_npa_pct": -0.1,
     "net_profit": null,
     "nim_pct": null,
     "other_income": null,
     "pcr_pct": null,
     "period_end": "2025-09-30",
     "period_type": "quarterly",
     "pre_provision_op_profit": null,
     "provisions": null,
     "roa_pct": null,
     "sid": "HDBK",
     "slippage_pct": null,
     "source": "screener_in"
    },
    {
     "adj_book_per_share": 100.0,
     "advances": null,
     "book_value_per_share": 100.0,
     "borrowings": 10000.0,
     "car_pct": null,
     "casa_pct": null,
     "cost_of_funds_pct": 4.8,
     "crar_pct": null,
     "credit_cost_pct": null,
     "deposits": 40000.0,
     "gross_npa_pct": null,
     "interest_earned": 4000.0,
     "interest_expended": 2400.0,
     "net_interest_income": 1600.0,
     "net_npa_pct": null,
     "net_profit": 900.0,
     "nim_pct": null,
     "other_income": null,
     "pcr_pct": null,
     "period_end": "2024-03-31",
     "period_type": "annual",
     "pre_provision_op_profit": null,
     "provisions": null,
     "roa_pct": null,
     "sid": "HDBK",
     "slippage_pct": null,
     "source": "screener_in"
    },
    {
     "adj_book_per_share": 110.0,
     "advances": null,
     "book_value_per_share": 110.0,
     "borrowings": 11000.0,
     "car_pct": null,
     "casa_pct": null,
     "cost_of_funds_pct": 4.545,
     "crar_pct": null,
     "credit_cost_pct": null,
     "deposits": 44000.0,
     "gross_npa_pct": null,
     "interest_earned": 4400.0,
     "interest_expended": 2500.0,
     "net_interest_income": 1900.0,
     "net_npa_pct": null,
     "net_profit": 1000.0,
     "nim_pct": null,
     "other_income": null,
     "pcr_pct": null,
     "period_end": "2025-03-31",
     "period_type": "annual",
     "pre_provision_op_profit": null,
     "provisions": null,
     "roa_pct": null,
     "sid": "HDBK",
     "slippage_pct": null,
     "source": "screener_in"
    }
   ]
  ],
  [
   "banking_metrics",
   [
    {
     "adj_book_per_share": null,
     "advances": null,
     "book_value_per_share": null,
     "borrowings": null,
     "car_pct": null,
     "casa_pct": null,
     "cost_of_funds_pct": null,
     "crar_pct": null,
     "credit_cost_pct": null,
     "deposits": null,
     "gross_npa_pct": 1.5,
     "interest_earned": 1000.0,
     "interest_expended": 600.0,
     "net_interest_income": 400.0,
     "net_npa_pct": 0.4,
     "net_profit": null,
     "nim_pct": null,
     "other_income": null,
     "pcr_pct": null,
     "period_end": "2025-06-30",
     "period_type": "quarterly",
     "pre_provision_op_profit": null,
     "provisions": null,
     "roa_pct": null,
     "sid": "ICBK",
     "slippage_pct": null,
     "source": "screener_in"
    },
    {
     "adj_book_per_share": null,
     "advances": null,
     "book_value_per_share": null,
     "borrowings": null,
     "car_pct": null,
     "casa_pct": null,
     "cost_of_funds_pct": null,
     "crar_pct": null,
     "credit_cost_pct": null,
     "deposits": null,
     "gross_npa_pct": 1.4,
     "interest_earned": 1100.0,
     "interest_expended": 650.0,
     "net_interest_income": 450.0,
     "net_npa_pct": -0.1,
     "net_profit": null,
     "nim_pct": null,
     "other_income": null,
     "pcr_pct": null,
     "period_end": "2025-09-30",
     "period_type": "quarterly",
     "pre_provision_op_profit": null,
     "provisions": null,
     "roa_pct": null,
     "sid": "ICBK",
     "slippage_pct": null,
     "source": "screener_in"
    },
    {
     "adj_book_per_share": 100.0,
     "advances": null,
     "book_value_per_share": 100.0,
     "borrowings": 10000.0,
     "car_pct": null,
     "casa_pct": null,
     "cost_of_funds_pct": 4.8,
     "crar_pct": null,
     "credit_cost_pct": null,
     "deposits": 40000.0,
     "gross_npa_pct": null,
     "interest_earned": 4000.0,
     "interest_expended": 2400.0,
     "net_interest_income": 1600.0,
     "net_npa_pct": null,
     "net_profit": 900.0,
     "nim_pct": null,
     "other_income": null,
     "pcr_pct": null,
     "period_end": "2024-03-31",
     "period_type": "annual",
     "pre_provision_op_profit": null,
     "provisions": null,
     "roa_pct": null,
     "sid": "ICBK",
     "slippage_pct": null,
     "source": "screener_in"
    },
    {
     "adj_book_per_share": 110.0,
     "advances": null,
     "book_value_per_share": 110.0,
     "borrowings": 11000.0,
     "car_pct": null,
     "casa_pct": null,
     "cost_of_funds_pct": 4.545,
     "crar_pct": null,
     "credit_cost_pct": null,
     "deposits": 44000.0,
     "gross_npa_pct": null,
     "interest_earned": 4400.0,
     "interest_expended": 2500.0,
     "net_interest_income": 1900.0,
     "net_npa_pct": null,
     "net_profit": 1000.0,
     "nim_pct": null,
     "other_income": null,
     "pcr_pct": null,
     "period_end": "2025-03-31",
     "period_type": "annual",
     "pre_provision_op_profit": null,
     "provisions": null,
     "roa_pct": null,
     "sid": "ICBK",
     "slippage_pct": null,
     "source": "screener_in"
    }
   ]
  ]
 ],
 "bse_announcements.requests": [
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.bseindia.com/corporates/ann.html"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": {
    "pageno": 1,
    "strCat": "-1",
    "strPrevDate": "20260925",
    "strSearch": "P",
    "strToDate": "20260925",
    "strType": "C",
    "strscrip": "",
    "subcategory": "-1"
   },
   "timeout": 30,
   "url": "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": {
    "pageno": 2,
    "strCat": "-1",
    "strPrevDate": "20260925",
    "strSearch": "P",
    "strToDate": "20260925",
    "strType": "C",
    "strscrip": "",
    "subcategory": "-1"
   },
   "timeout": 30,
   "url": "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": {
    "pageno": 1,
    "strCat": "-1",
    "strPrevDate": "20260924",
    "strSearch": "P",
    "strToDate": "20260924",
    "strType": "C",
    "strscrip": "",
    "subcategory": "-1"
   },
   "timeout": 30,
   "url": "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": {
    "pageno": 2,
    "strCat": "-1",
    "strPrevDate": "20260924",
    "strSearch": "P",
    "strToDate": "20260924",
    "strType": "C",
    "strscrip": "",
    "subcategory": "-1"
   },
   "timeout": 30,
   "url": "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
  }
 ],
 "bse_announcements.stored": [
  [
   {
    "announcement_type": null,
    "attachment": null,
    "category": null,
    "company_name": "Co 0",
    "critical_news": 0,
    "dissem_dt": null,
    "dt_tm": "20260925T10:00",
    "has_audio_video": 0,
    "has_investor_ppt": 0,
    "headline": "Result",
    "news_id": "20260925-1-0",
    "news_sub": null,
    "nsurl": null,
    "pdf_flag": 0,
    "quarter_id": null,
    "scrip_cd": 500000,
    "sid": null,
    "subcategory": null,
    "submission_dt": null,
    "time_diff": null
   },
   {
    "announcement_type": null,
    "attachment": null,
    "category": null,
    "company_name": "Co 1",
    "critical_news": 1,
    "dissem_dt": null,
    "dt_tm": "20260925T10:01",
    "has_audio_video": 0,
    "has_investor_ppt": 0,
    "headline": "Result",
    "news_id": "20260925-1-1",
    "news_sub": null,
    "nsurl": null,
    "pdf_flag": 0,
    "quarter_id": null,
    "scrip_cd": 500001,
    "sid": null,
    "subcategory": null,
    "submission_dt": null,
    "time_diff": null
   },
   {
    "announcement_type": null,
    "attachment": null,
    "category": null,
    "company_name": "Co 0",
    "critical_news": 0,
    "dissem_dt": null,
    "dt_tm": "20260925T10:00",
    "has_audio_video": 0,
    "has_investor_ppt": 0,
    "headline": "Result",
    "news_id": "20260925-2-0",
    "news_sub": null,
    "nsurl": null,
    "pdf_flag": 0,
    "quarter_id": null,
    "scrip_cd": 500000,
    "sid": null,
    "subcategory": null,
    "submission_dt": null,
    "time_diff": null
   },
   {
    "announcement_type": null,
    "attachment": null,
    "category": null,
    "company_name": "Co 1",
    "critical_news": 1,
    "dissem_dt": null,
    "dt_tm": "20260925T10:01",
    "has_audio_video": 0,
    "has_investor_ppt": 0,
    "headline": "Result",
    "news_id": "20260925-2-1",
    "news_sub": null,
    "nsurl": null,
    "pdf_flag": 0,
    "quarter_id": null,
    "scrip_cd": 500001,
    "sid": null,
    "subcategory": null,
    "submission_dt": null,
    "time_diff": null
   }
  ],
  [
   {
    "announcement_type": null,
    "attachment": null,
    "category": null,
    "company_name": "Co 0",
    "critical_news": 0,
    "dissem_dt": null,
    "dt_tm": "20260924T10:00",
    "has_audio_video": 0,
    "has_investor_ppt": 0,
    "headline": "Result",
    "news_id": "20260924-1-0",
    "news_sub": null,
    "nsurl": null,
    "pdf_flag": 0,
    "quarter_id": null,
    "scrip_cd": 500000,
    "sid": null,
    "subcategory": null,
    "submission_dt": null,
    "time_diff": null
   },
   {
    "announcement_type": null,
    "attachment": null,
    "category": null,
    "company_name": "Co 1",
    "critical_news": 1,
    "dissem_dt": null,
    "dt_tm": "20260924T10:01",
    "has_audio_video": 0,
    "has_investor_ppt": 0,
    "headline": "Result",
    "news_id": "20260924-1-1",
    "news_sub": null,
    "nsurl": null,
    "pdf_flag": 0,
    "quarter_id": null,
    "scrip_cd": 500001,
    "sid": null,
    "subcategory": null,
    "submission_dt": null,
    "time_diff": null
   },
   {
    "announcement_type": null,
    "attachment": null,
    "category": null,
    "company_name": "Co 0",
    "critical_news": 0,
    "dissem_dt": null,
    "dt_tm": "20260924T10:00",
    "has_audio_video": 0,
    "has_investor_ppt": 0,
    "headline": "Result",
    "news_id": "20260924-2-0",
    "news_sub": null,
    "nsurl": null,
    "pdf_flag": 0,
    "quarter_id": null,
    "scrip_cd": 500000,
    "sid": null,
    "subcategory": null,
    "submission_dt": null,
    "time_diff": null
   },
   {
    "announcement_type": null,
    "attachment": null,
    "category": null,
    "company_name": "Co 1",
    "critical_news": 1,
    "dissem_dt": null,
    "dt_tm": "20260924T10:01",
    "has_audio_video": 0,
    "has_investor_ppt": 0,
    "headline": "Result",
    "news_id": "20260924-2-1",
    "news_sub": null,
    "nsurl": null,
    "pdf_flag": 0,
    "quarter_id": null,
    "scrip_cd": 500001,
    "sid": null,
    "subcategory": null,
    "submission_dt": null,
    "time_diff": null
   }
  ]
 ],
 "fno_pull.calls": [
  {
   "args": [
    [
     "trade_date",
     "25-09-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "fno_bhav_copy"
  },
  {
   "args": [
    [
     "trade_date",
     "24-09-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "fno_bhav_copy"
  },
  {
   "args": [
    [
     "trade_date",
     "23-09-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "fno_bhav_copy"
  },
  {
   "args": [
    [
     "trade_date",
     "21-09-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "fno_bhav_copy"
  }
 ],
 "fno_pull.written": [
  [
   "fno_bhav",
   [
    {
     "chg_oi": 5,
     "close": 10.5,
     "expiry_date": "2026-09-30",
     "instrument_type": "STO",
     "num_trades": 3,
     "oi": 100,
     "option_type": "CE",
     "settle": 10.4,
     "sid": "RELI",
     "strike": 1400.0,
     "symbol": "RELIANCE",
     "trade_date": "2026-09-24",
     "underlying_price": 1390,
     "volume": 20
    },
    {
     "chg_oi": 0,
     "close": 25000.0,
     "expiry_date": "2026-09-30",
     "instrument_type": "IDF",
     "num_trades": 1,
     "oi": 0,
     "option_type": "XX",
     "settle": 25001.0,
     "sid": null,
     "strike": 0.0,
     "symbol": "NIFTY",
     "trade_date": "2026-09-24",
     "underlying_price": 24990,
     "volume": 7
    }
   ]
  ]
 ],
 "kite_pull.calls": [
  {
   "args": [
    1,
    "2026-09-20 09:00:00",
    "2026-09-25 16:00:00",
    "minute"
   ],
   "host": "api.kite.trade",
   "name": "historical_data"
  },
  {
   "args": [
    2,
    "2026-09-20 09:00:00",
    "2026-09-25 16:00:00",
    "minute"
   ],
   "host": "api.kite.trade",
   "name": "historical_data"
  },
  {
   "args": [
    3,
    "2026-09-20 09:00:00",
    "2026-09-25 16:00:00",
    "minute"
   ],
   "host": "api.kite.trade",
   "name": "historical_data"
  }
 ],
 "kite_pull.db": [
  [
   "execute",
   "CREATE TABLE IF NOT EXISTS kite_intraday_bars ( sid TEXT, instrument_token INTEGER, ts TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER, UNIQUE(instrument_token, ts))",
   []
  ],
  [
   "execute",
   "CREATE INDEX IF NOT EXISTS idx_kite_bars_sid_ts ON kite_intraday_bars(sid, ts)",
   []
  ],
  [
   "executemany",
   "INSERT OR IGNORE INTO kite_intraday_bars (sid,instrument_token,ts,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?,?)",
   [
    [
     "RELI",
     1,
     "2026-09-24T09:15:00",
     10.0,
     11.0,
     9.5,
     10.5,
     100
    ],
    [
     "RELI",
     1,
     "2026-09-24T09:16:00",
     11.0,
     11.0,
     9.5,
     11.5,
     200
    ]
   ]
  ],
  [
   "executemany",
   "INSERT OR IGNORE INTO kite_intraday_bars (sid,instrument_token,ts,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?,?)",
   [
    [
     "TCS",
     2,
     "2026-09-24T09:15:00",
     10.0,
     11.0,
     9.5,
     10.5,
     100
    ],
    [
     "TCS",
     2,
     "2026-09-24T09:16:00",
     11.0,
     11.0,
     9.5,
     11.5,
     200
    ]
   ]
  ]
 ],
 "kite_pull.login_requests": [
  {
   "allow_redirects": true,
   "data": {
    "password": "pw",
    "user_id": "AB1234"
   },
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "python-requests/2.32.5"
   },
   "method": "POST",
   "params": null,
   "timeout": null,
   "url": "https://kite.zerodha.com/api/login"
  },
  {
   "allow_redirects": true,
   "data": {
    "request_id": "rq1",
    "twofa_value": "123456",
    "user_id": "AB1234"
   },
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "python-requests/2.32.5"
   },
   "method": "POST",
   "params": null,
   "timeout": null,
   "url": "https://kite.zerodha.com/api/twofa"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "python-requests/2.32.5"
   },
   "method": "GET",
   "params": null,
   "timeout": null,
   "url": "https://kite.trade/connect/login?api_key=key1&v=3"
  }
 ],
 "macro_yfinance.calls": [
  {
   "args": [
    [
     "^NSEI",
     "^NSEBANK",
     "^CNXIT",
     "^CNXMETAL",
     "^CNXREALTY",
     "^CNXPHARMA",
     "^CNXAUTO",
     "^CNXFMCG",
     "^CNXENERGY",
     "^CNXINFRA",
     "^CNXPSUBANK",
     "^CNXMEDIA",
     "^INDIAVIX",
     "BZ=F",
     "GC=F",
     "HG=F",
     "ALI=F",
     "SI=F",
     "USDINR=X",
     "^TNX",
     "SETF10GILT.NS",
     "EBBETF0430.NS"
    ],
    [
     [
      "auto_adjust",
      true
     ],
     [
      "end",
      "2026-09-25"
     ],
     [
      "group_by",
      "ticker"
     ],
     [
      "progress",
      false
     ],
     [
      "start",
      "2026-09-01"
     ],
     [
      "threads",
      false
     ]
    ]
   ],
   "host": "query2.finance.yahoo.com",
   "name": "download"
  }
 ],
 "macro_yfinance.out": {
  "aaa_psu_etf": [],
  "aluminium": [],
  "bank_nifty": [],
  "brent_crude": [],
  "copper": [],
  "gold": [
   {
    "category": "leading",
    "date": "2026-09-24",
    "indicator_id": "gold",
    "source": "yfinance",
    "unit": "usd",
    "value": 102.0
   }
  ],
  "gsec10_etf": [],
  "india_vix": [],
  "nifty50": [
   {
    "category": "coincident",
    "date": "2026-09-23",
    "indicator_id": "nifty50",
    "source": "yfinance",
    "unit": "index",
    "value": 100.0
   },
   {
    "category": "coincident",
    "date": "2026-09-24",
    "indicator_id": "nifty50",
    "source": "yfinance",
    "unit": "index",
    "value": 101.0
   }
  ],
  "nifty_auto": [],
  "nifty_energy": [],
  "nifty_fmcg": [],
  "nifty_infra": [],
  "nifty_it": [],
  "nifty_media": [],
  "nifty_metal": [],
  "nifty_pharma": [],
  "nifty_psubank": [],
  "nifty_realty": [],
  "silver": [],
  "us_10y": [],
  "usdinr": []
 },
 "mf_holdings_scrape.db": [
  [
   "execute",
   "DELETE FROM mf_sector_allocation WHERE scheme_code=? AND as_of_date=?",
   [
    "1001",
    "2026-08-31"
   ]
  ],
  [
   "execute",
   "DELETE FROM mf_sector_allocation WHERE scheme_code=? AND as_of_date=?",
   [
    "1002",
    "2026-08-31"
   ]
  ],
  [
   "executemany",
   "INSERT OR REPLACE INTO mf_holdings (scheme_code, as_of_date, holding_rank, instrument_type, sid, isin, instrument_name, sector, pct_of_aum, market_value_cr) VALUES (?,?,?,?,?,?,?,?,?,?)",
   [
    [
     "1001",
     "2026-08-31",
     1,
     "EQUITY",
     "HDBK",
     null,
     "HDFC Bank Ltd.",
     "Financial",
     9.5,
     1234.5
    ],
    [
     "1001",
     "2026-08-31",
     2,
     "EQUITY",
     "INFY",
     null,
     "Infosys Ltd.",
     "Technology",
     6.25,
     800.0
    ],
    [
     "1001",
     "2026-08-31",
     3,
     "EQUITY",
     null,
     null,
     "ICICI Bank Ltd.",
     "Financial",
     5.0,
     null
    ],
    [
     "1002",
     "2026-08-31",
     1,
     "EQUITY",
     "HDBK",
     null,
     "HDFC Bank Ltd.",
     "Financial",
     9.5,
     1234.5
    ],
    [
     "1002",
     "2026-08-31",
     2,
     "EQUITY",
     "INFY",
     null,
     "Infosys Ltd.",
     "Technology",
     6.25,
     800.0
    ],
    [
     "1002",
     "2026-08-31",
     3,
     "EQUITY",
     null,
     null,
     "ICICI Bank Ltd.",
     "Financial",
     5.0,
     null
    ]
   ]
  ],
  [
   "executemany",
   "INSERT OR REPLACE INTO mf_sector_allocation (scheme_code, as_of_date, sector, pct_of_aum) VALUES (?,?,?,?)",
   [
    [
     "1001",
     "2026-08-31",
     "Financial",
     14.5
    ],
    [
     "1001",
     "2026-08-31",
     "Technology",
     6.25
    ],
    [
     "1002",
     "2026-08-31",
     "Financial",
     14.5
    ],
    [
     "1002",
     "2026-08-31",
     "Technology",
     6.25
    ]
   ]
  ],
  [
   "execute",
   "DELETE FROM mf_sector_allocation WHERE scheme_code=? AND as_of_date=?",
   [
    "3001",
    "2026-08-31"
   ]
  ],
  [
   "executemany",
   "INSERT OR REPLACE INTO mf_holdings (scheme_code, as_of_date, holding_rank, instrument_type, sid, isin, instrument_name, sector, pct_of_aum, market_value_cr) VALUES (?,?,?,?,?,?,?,?,?,?)",
   [
    [
     "3001",
     "2026-08-31",
     1,
     "EQUITY",
     "HDBK",
     null,
     "HDFC Bank Ltd.",
     "Financial",
     9.5,
     1234.5
    ],
    [
     "3001",
     "2026-08-31",
     2,
     "EQUITY",
     "INFY",
     null,
     "Infosys Ltd.",
     "Technology",
     6.25,
     800.0
    ],
    [
     "3001",
     "2026-08-31",
     3,
     "EQUITY",
     null,
     null,
     "ICICI Bank Ltd.",
     "Financial",
     5.0,
     null
    ]
   ]
  ],
  [
   "executemany",
   "INSERT OR REPLACE INTO mf_sector_allocation (scheme_code, as_of_date, sector, pct_of_aum) VALUES (?,?,?,?)",
   [
    [
     "3001",
     "2026-08-31",
     "Financial",
     14.5
    ],
    [
     "3001",
     "2026-08-31",
     "Technology",
     6.25
    ]
   ]
  ]
 ],
 "mf_holdings_scrape.requests": [
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 30,
   "url": "https://www.etmoney.com/mf-schemes-sitemap.xml"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 30,
   "url": "https://www.etmoney.com/mf-regular-schemes-sitemap.xml"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 20,
   "url": "https://www.etmoney.com/mutual-funds/sbi-contra-direct-growth/portfolio-details/111"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 20,
   "url": "https://www.etmoney.com/mutual-funds/hdfc-top-100-regular/portfolio-details/222"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 20,
   "url": "https://www.etmoney.com/mutual-funds/axis-bluechip/portfolio-details/333"
  }
 ],
 "mf_holdings_scrape.sitemap": {
  "axisbluechip": [
   "axis-bluechip",
   333
  ],
  "hdfctop100regular": [
   "hdfc-top-100-regular",
   222
  ],
  "sbicontradirectgrowth": [
   "sbi-contra-direct-growth",
   111
  ]
 },
 "moneycontrol_recos.db": [
  [
   "execute",
   "UPDATE stocks SET mc_slug = ? WHERE sid = ?",
   [
    "/india/stockpricequote/banks/hdfcbank/HDF01",
    "HDBK"
   ]
  ]
 ],
 "moneycontrol_recos.requests": [
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://www.moneycontrol.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.moneycontrol.com/india/stockpricequote/refineries/relianceindustries/RI"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://www.moneycontrol.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": {
    "format": "json",
    "query": "HDFCBANK",
    "type": 1
   },
   "timeout": 15,
   "url": "https://www.moneycontrol.com/mccode/common/autosuggestion_solr.php"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://www.moneycontrol.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.moneycontrol.com/india/stockpricequote/banks/hdfcbank/HDF01"
  }
 ],
 "moneycontrol_recos.written": [
  [
   "broker_recommendations",
   [
    {
     "broker": "Motilal Oswal",
     "reco_date": "2026-09-12",
     "reco_price": 1000.0,
     "reco_type": "BUY",
     "report_url": "https://x.test/r.pdf",
     "sid": "RELI",
     "target_price": 1250.5
    },
    {
     "broker": "Emkay",
     "reco_date": "2026-09-25",
     "reco_price": null,
     "reco_type": "HOLD",
     "report_url": null,
     "sid": "RELI",
     "target_price": 990.0
    },
    {
     "broker": "Motilal Oswal",
     "reco_date": "2026-09-12",
     "reco_price": 1000.0,
     "reco_type": "BUY",
     "report_url": "https://x.test/r.pdf",
     "sid": "HDBK",
     "target_price": 1250.5
    },
    {
     "broker": "Emkay",
     "reco_date": "2026-09-25",
     "reco_price": null,
     "reco_type": "HOLD",
     "report_url": null,
     "sid": "HDBK",
     "target_price": 990.0
    }
   ]
  ]
 ],
 "nselib_pull.calls": [
  {
   "args": [
    [
     "from_date",
     "01-08-2026"
    ],
    [
     "to_date",
     "31-08-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "bulk_deal_data"
  },
  {
   "args": [
    [
     "from_date",
     "01-09-2026"
    ],
    [
     "to_date",
     "25-09-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "bulk_deal_data"
  },
  {
   "args": [
    [
     "from_date",
     "01-08-2026"
    ],
    [
     "to_date",
     "31-08-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "corporate_actions_for_equity"
  },
  {
   "args": [
    [
     "from_date",
     "01-09-2026"
    ],
    [
     "to_date",
     "25-09-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "corporate_actions_for_equity"
  },
  {
   "args": [
    [
     "from_date",
     "01-09-2026"
    ],
    [
     "to_date",
     "25-09-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "short_selling_data"
  },
  {
   "args": [
    [
     "trade_date",
     "25-09-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "participant_wise_open_interest"
  },
  {
   "args": [
    [
     "trade_date",
     "23-09-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "participant_wise_open_interest"
  },
  {
   "args": [
    [
     "trade_date",
     "22-09-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "participant_wise_open_interest"
  },
  {
   "args": [
    [
     "from_date",
     "01-09-2026"
    ],
    [
     "index",
     "NIFTY 50"
    ],
    [
     "to_date",
     "25-09-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "index_data"
  },
  {
   "args": [
    [
     "from_date",
     "01-09-2026"
    ],
    [
     "index",
     "NIFTY ALPHA 50"
    ],
    [
     "to_date",
     "25-09-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "index_data"
  }
 ],
 "nselib_pull.surv_calls": [
  {
   "args": [
    [
     "trade_date",
     "25-09-2026"
    ]
   ],
   "host": "www.nseindia.com",
   "name": "fno_security_in_ban_period"
  }
 ],
 "nselib_pull.surv_requests": [
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.nseindia.com"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 20,
   "url": "https://www.nseindia.com/api/reportASM"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 20,
   "url": "https://www.nseindia.com/api/reportGSM"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.nseindia.com"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.nseindia.com/api/fiidiiTradeReact"
  }
 ],
 "nselib_pull.surv_written": [
  [
   "surveillance_flags",
   [
    {
     "flag_date": "2026-09-25",
     "flag_type": "ASM_LT",
     "reason": "x",
     "sid": "AMBE",
     "stage": "I",
     "symbol": "AMBER"
    }
   ]
  ],
  [
   "surveillance_flags",
   [
    {
     "flag_date": "2026-09-25",
     "flag_type": "GSM",
     "reason": "d",
     "sid": null,
     "stage": "II",
     "symbol": "ZZZ"
    }
   ]
  ],
  [
   "surveillance_flags",
   [
    {
     "flag_date": "2026-09-25",
     "flag_type": "FNO_BAN",
     "reason": "",
     "sid": "AMBE",
     "stage": "",
     "symbol": "AMBER"
    },
    {
     "flag_date": "2026-09-25",
     "flag_type": "FNO_BAN",
     "reason": "",
     "sid": null,
     "stage": "",
     "symbol": "KAYNES"
    }
   ]
  ],
  [
   "fii_dii_cash_flow",
   [
    {
     "buy_value_cr": 100.5,
     "category": "FII/FPI",
     "flow_date": "2026-09-24",
     "net_value_cr": 10.5,
     "sell_value_cr": 90.0
    }
   ]
  ]
 ],
 "nselib_pull.written": [
  [
   "bulk_deals",
   [
    {
     "buy_sell": "BUY",
     "client_name": "FUND",
     "deal_date": "2026-09-25",
     "deal_type": "bulk",
     "price": 1400.5,
     "quantity": 1000.0,
     "sid": "RELI",
     "symbol": "RELIANCE"
    }
   ]
  ],
  [
   "corporate_actions",
   [
    {
     "ex_date": "2026-09-15",
     "face_value": 1.0,
     "ind": "DIVIDEND",
     "series": "EQ",
     "sid": "TCS",
     "subject": "Dividend - Rs 10",
     "symbol": "TCS"
    }
   ]
  ],
  [
   "corporate_actions",
   [
    {
     "ex_date": "2026-09-15",
     "face_value": 1.0,
     "ind": "DIVIDEND",
     "series": "EQ",
     "sid": "TCS",
     "subject": "Dividend - Rs 10",
     "symbol": "TCS"
    }
   ]
  ],
  [
   "short_selling_data",
   [
    {
     "quantity": 5000.0,
     "short_date": "2026-09-24",
     "sid": "TCS",
     "symbol": "TCS"
    }
   ]
  ],
  [
   "fii_dii_positioning",
   [
    {
     "client_type": "FII",
     "future_index_long": 10,
     "total_long": 99,
     "trade_date": "2026-09-25"
    }
   ]
  ],
  [
   "fii_dii_positioning",
   [
    {
     "client_type": "FII",
     "future_index_long": 10,
     "total_long": 99,
     "trade_date": "2026-09-22"
    }
   ]
  ],
  [
   "nse_index_history",
   [
    {
     "close": 1.5,
     "high": 2,
     "index_symbol": "NIFTY 50",
     "low": 0.5,
     "open": 1,
     "trade_date": "2026-09-24",
     "traded_value": null,
     "volume": 10
    }
   ]
  ],
  [
   "nse_index_history",
   [
    {
     "close": 1.5,
     "high": 2,
     "index_symbol": "NIFTY ALPHA 50",
     "low": 0.5,
     "open": 1,
     "trade_date": "2026-09-24",
     "traded_value": null,
     "volume": 10
    }
   ]
  ]
 ],
 "polite_get_callers.requests": [
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 30,
   "url": "https://archives.nseindia.com/products/content/sec_bhavdata_full_24092026.csv"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://archives.nseindia.com/content/equities/bulk.csv"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://archives.nseindia.com/content/equities/block.csv"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.nseindia.com/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
   },
   "method": "GET",
   "params": {
    "from_date": "26-08-2026",
    "index": "equities",
    "to_date": "25-09-2026"
   },
   "timeout": 30,
   "url": "https://www.nseindia.com/api/corporates-pit"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 60,
   "url": "https://www.amfiindia.com/spages/NAVAll.txt"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://api.mfapi.in/mf/100"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://news.google.com/rss/search?q=rbi+after:2026-09-01+before:2026-09-02&hl=en-IN&gl=IN&ceid=IN:en"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "text/html",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 10,
   "url": "https://pib.gov.in/PressReleasePage.aspx?PRID=1"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://tickertape.in/stocks/x-X"
  }
 ],
 "rss.calls": [
  [
   "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"
  ],
  [
   "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms"
  ],
  [
   "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms"
  ],
  [
   "https://www.livemint.com/rss/markets"
  ],
  [
   "https://www.livemint.com/rss/companies"
  ],
  [
   "https://www.moneycontrol.com/rss/latestnews.xml"
  ],
  [
   "https://www.moneycontrol.com/rss/business.xml"
  ],
  [
   "https://www.moneycontrol.com/rss/marketreports.xml"
  ]
 ],
 "rss.written": [
  [
   "news_articles",
   [
    {
     "article_id": "4c9a32814681",
     "published_at": "2099-01-02T03:04:05",
     "source": "et_markets",
     "summary": "Analysts cheer TCS too",
     "title": "Reliance Industries posts record profit (77021501.cms)",
     "url": "https://n.test/a"
    },
    {
     "article_id": "a870d91ea021",
     "published_at": "Fri, 25 Sep 2099",
     "source": "et_markets",
     "summary": "",
     "title": "Macro wrap: markets end flat on the week",
     "url": ""
    }
   ]
  ],
  [
   "news_article_stocks",
   [
    {
     "article_id": "4c9a32814681",
     "match_location": "summary",
     "sid": "TCS"
    },
    {
     "article_id": "4c9a32814681",
     "match_location": "title",
     "sid": "RELI"
    }
   ]
  ],
  [
   "news_articles",
   [
    {
     "article_id": "afbb0c67f797",
     "published_at": "Fri, 25 Sep 2099",
     "source": "et_companies",
     "summary": "",
     "title": "Macro wrap: markets end flat on the week",
     "url": ""
    },
    {
     "article_id": "b7caa6449960",
     "published_at": "2099-01-02T03:04:05",
     "source": "et_companies",
     "summary": "Analysts cheer TCS too",
     "title": "Reliance Industries posts record profit (13352306.cms)",
     "url": "https://n.test/a"
    }
   ]
  ],
  [
   "news_article_stocks",
   [
    {
     "article_id": "b7caa6449960",
     "match_location": "summary",
     "sid": "TCS"
    },
    {
     "article_id": "b7caa6449960",
     "match_location": "title",
     "sid": "RELI"
    }
   ]
  ],
  [
   "news_articles",
   [
    {
     "article_id": "61ec20ddbb96",
     "published_at": "Fri, 25 Sep 2099",
     "source": "et_economy",
     "summary": "",
     "title": "Macro wrap: markets end flat on the week",
     "url": ""
    },
    {
     "article_id": "aaea7e748d1a",
     "published_at": "2099-01-02T03:04:05",
     "source": "et_economy",
     "summary": "Analysts cheer TCS too",
     "title": "Reliance Industries posts record profit (73380680.cms)",
     "url": "https://n.test/a"
    }
   ]
  ],
  [
   "news_article_stocks",
   [
    {
     "article_id": "aaea7e748d1a",
     "match_location": "summary",
     "sid": "TCS"
    },
    {
     "article_id": "aaea7e748d1a",
     "match_location": "title",
     "sid": "RELI"
    }
   ]
  ],
  [
   "news_articles",
   [
    {
     "article_id": "0c9452202e91",
     "published_at": "2099-01-02T03:04:05",
     "source": "livemint_markets",
     "summary": "Analysts cheer TCS too",
     "title": "Reliance Industries posts record profit (/rss/markets)",
     "url": "https://n.test/a"
    },
    {
     "article_id": "12e45b54e536",
     "published_at": "Fri, 25 Sep 2099",
     "source": "livemint_markets",
     "summary": "",
     "title": "Macro wrap: markets end flat on the week",
     "url": ""
    }
   ]
  ],
  [
   "news_article_stocks",
   [
    {
     "article_id": "0c9452202e91",
     "match_location": "summary",
     "sid": "TCS"
    },
    {
     "article_id": "0c9452202e91",
     "match_location": "title",
     "sid": "RELI"
    }
   ]
  ],
  [
   "news_articles",
   [
    {
     "article_id": "85cc91785d2a",
     "published_at": "2099-01-02T03:04:05",
     "source": "moneycontrol_latest",
     "summary": "Analysts cheer TCS too",
     "title": "Reliance Industries posts record profit (testnews.xml)",
     "url": "https://n.test/a"
    },
    {
     "article_id": "8c232d2ba3fb",
     "published_at": "Fri, 25 Sep 2099",
     "source": "moneycontrol_latest",
     "summary": "",
     "title": "Macro wrap: markets end flat on the week",
     "url": ""
    }
   ]
  ],
  [
   "news_article_stocks",
   [
    {
     "article_id": "85cc91785d2a",
     "match_location": "summary",
     "sid": "TCS"
    },
    {
     "article_id": "85cc91785d2a",
     "match_location": "title",
     "sid": "RELI"
    }
   ]
  ],
  [
   "news_articles",
   [
    {
     "article_id": "49a3dc021c4e",
     "published_at": "Fri, 25 Sep 2099",
     "source": "moneycontrol_business",
     "summary": "",
     "title": "Macro wrap: markets end flat on the week",
     "url": ""
    },
    {
     "article_id": "6192b3d8e6bc",
     "published_at": "2099-01-02T03:04:05",
     "source": "moneycontrol_business",
     "summary": "Analysts cheer TCS too",
     "title": "Reliance Industries posts record profit (business.xml)",
     "url": "https://n.test/a"
    }
   ]
  ],
  [
   "news_article_stocks",
   [
    {
     "article_id": "6192b3d8e6bc",
     "match_location": "summary",
     "sid": "TCS"
    },
    {
     "article_id": "6192b3d8e6bc",
     "match_location": "title",
     "sid": "RELI"
    }
   ]
  ],
  [
   "news_articles",
   [
    {
     "article_id": "24ec33983d9b",
     "published_at": "2099-01-02T03:04:05",
     "source": "moneycontrol_markets",
     "summary": "Analysts cheer TCS too",
     "title": "Reliance Industries posts record profit (treports.xml)",
     "url": "https://n.test/a"
    },
    {
     "article_id": "51ffaa8534e5",
     "published_at": "Fri, 25 Sep 2099",
     "source": "moneycontrol_markets",
     "summary": "",
     "title": "Macro wrap: markets end flat on the week",
     "url": ""
    }
   ]
  ],
  [
   "news_article_stocks",
   [
    {
     "article_id": "24ec33983d9b",
     "match_location": "summary",
     "sid": "TCS"
    },
    {
     "article_id": "24ec33983d9b",
     "match_location": "title",
     "sid": "RELI"
    }
   ]
  ]
 ],
 "screener_pull.errors": [
  [
   "screener_pull_errors",
   [
    {
     "error_message": "only 2 quarter periods / 2 annual periods",
     "error_type": "thin",
     "http_status": null,
     "sid": "TCS",
     "ticker": "TCS"
    }
   ]
  ],
  [
   "screener_pull_errors",
   [
    {
     "error_message": "only 2 quarter periods / 2 annual periods",
     "error_type": "thin",
     "http_status": null,
     "sid": "INFY",
     "ticker": "INFY"
    }
   ]
  ]
 ],
 "screener_pull.requests": [
  {
   "allow_redirects": false,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.screener.in/company/TCS/consolidated/"
  },
  {
   "allow_redirects": false,
   "data": {
    "csrfmiddlewaretoken": "csrf"
   },
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.screener.in/company/TCS/consolidated/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "POST",
   "params": null,
   "timeout": 30,
   "url": "https://www.screener.in/user/company/export/42/"
  },
  {
   "allow_redirects": false,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.screener.in/company/INFY/consolidated/"
  },
  {
   "allow_redirects": false,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.screener.in/company/INFY/"
  },
  {
   "allow_redirects": false,
   "data": {
    "csrfmiddlewaretoken": "csrf"
   },
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.screener.in/company/INFY/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "POST",
   "params": null,
   "timeout": 30,
   "url": "https://www.screener.in/user/company/export/42/"
  }
 ],
 "screener_pull.written": [
  [
   "fundamentals_screener",
   [
    {
     "filing_date": null,
     "line_item": "Sales",
     "period_end": "2024-03-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": 100.0
    },
    {
     "filing_date": null,
     "line_item": "Sales",
     "period_end": "2025-03-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": 120.5
    },
    {
     "filing_date": null,
     "line_item": "Net profit",
     "period_end": "2024-03-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": 10.0
    },
    {
     "filing_date": null,
     "line_item": "Net profit",
     "period_end": "2025-03-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": 12.25
    },
    {
     "filing_date": null,
     "line_item": "Sales",
     "period_end": "2025-06-30",
     "period_type": "quarterly",
     "sid": "TCS",
     "value": 30.0
    },
    {
     "filing_date": null,
     "line_item": "Sales",
     "period_end": "2025-09-30",
     "period_type": "quarterly",
     "sid": "TCS",
     "value": 32.0
    },
    {
     "filing_date": null,
     "line_item": "Borrowings",
     "period_end": "2024-03-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": 5.0
    }
   ]
  ],
  [
   "fundamentals_screener",
   [
    {
     "filing_date": null,
     "line_item": "Sales",
     "period_end": "2024-03-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": 100.0
    },
    {
     "filing_date": null,
     "line_item": "Sales",
     "period_end": "2025-03-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": 120.5
    },
    {
     "filing_date": null,
     "line_item": "Net profit",
     "period_end": "2024-03-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": 10.0
    },
    {
     "filing_date": null,
     "line_item": "Net profit",
     "period_end": "2025-03-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": 12.25
    },
    {
     "filing_date": null,
     "line_item": "Sales",
     "period_end": "2025-06-30",
     "period_type": "quarterly",
     "sid": "INFY",
     "value": 30.0
    },
    {
     "filing_date": null,
     "line_item": "Sales",
     "period_end": "2025-09-30",
     "period_type": "quarterly",
     "sid": "INFY",
     "value": 32.0
    },
    {
     "filing_date": null,
     "line_item": "Borrowings",
     "period_end": "2024-03-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": 5.0
    }
   ]
  ]
 ],
 "screener_schedules.requests": [
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 20,
   "url": "https://www.screener.in/company/TCS/consolidated/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest"
   },
   "method": "GET",
   "params": {
    "consolidated": "",
    "parent": "Other Liabilities",
    "section": "balance-sheet"
   },
   "timeout": 20,
   "url": "https://www.screener.in/api/company/77/schedules/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest"
   },
   "method": "GET",
   "params": {
    "consolidated": "",
    "parent": "Borrowings",
    "section": "balance-sheet"
   },
   "timeout": 20,
   "url": "https://www.screener.in/api/company/77/schedules/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest"
   },
   "method": "GET",
   "params": {
    "consolidated": "",
    "parent": "Other Assets",
    "section": "balance-sheet"
   },
   "timeout": 20,
   "url": "https://www.screener.in/api/company/77/schedules/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest"
   },
   "method": "GET",
   "params": {
    "consolidated": "",
    "parent": "Fixed Assets",
    "section": "balance-sheet"
   },
   "timeout": 20,
   "url": "https://www.screener.in/api/company/77/schedules/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 20,
   "url": "https://www.screener.in/company/INFY/consolidated/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 20,
   "url": "https://www.screener.in/company/INFY/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest"
   },
   "method": "GET",
   "params": {
    "parent": "Other Liabilities",
    "section": "balance-sheet"
   },
   "timeout": 20,
   "url": "https://www.screener.in/api/company/88/schedules/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest"
   },
   "method": "GET",
   "params": {
    "parent": "Borrowings",
    "section": "balance-sheet"
   },
   "timeout": 20,
   "url": "https://www.screener.in/api/company/88/schedules/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest"
   },
   "method": "GET",
   "params": {
    "parent": "Other Assets",
    "section": "balance-sheet"
   },
   "timeout": 20,
   "url": "https://www.screener.in/api/company/88/schedules/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest"
   },
   "method": "GET",
   "params": {
    "parent": "Fixed Assets",
    "section": "balance-sheet"
   },
   "timeout": 20,
   "url": "https://www.screener.in/api/company/88/schedules/"
  }
 ],
 "screener_schedules.written": [
  [
   "fundamentals_screener",
   [
    {
     "line_item": "Other Liabilities A",
     "period_end": "2024-03-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": 1234.0
    },
    {
     "line_item": "Other Liabilities A",
     "period_end": "2025-03-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": null
    },
    {
     "line_item": "Other Liabilities A",
     "period_end": "2025-12-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": 7.0
    },
    {
     "line_item": "Borrowings A",
     "period_end": "2024-03-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": 1234.0
    },
    {
     "line_item": "Borrowings A",
     "period_end": "2025-03-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": null
    },
    {
     "line_item": "Borrowings A",
     "period_end": "2025-12-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": 7.0
    },
    {
     "line_item": "Other Assets A",
     "period_end": "2024-03-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": 1234.0
    },
    {
     "line_item": "Other Assets A",
     "period_end": "2025-03-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": null
    },
    {
     "line_item": "Other Assets A",
     "period_end": "2025-12-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": 7.0
    },
    {
     "line_item": "Fixed Assets A",
     "period_end": "2024-03-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": 1234.0
    },
    {
     "line_item": "Fixed Assets A",
     "period_end": "2025-03-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": null
    },
    {
     "line_item": "Fixed Assets A",
     "period_end": "2025-12-31",
     "period_type": "annual",
     "sid": "TCS",
     "value": 7.0
    }
   ]
  ],
  [
   "fundamentals_screener",
   [
    {
     "line_item": "Other Liabilities A",
     "period_end": "2024-03-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": 1234.0
    },
    {
     "line_item": "Other Liabilities A",
     "period_end": "2025-03-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": null
    },
    {
     "line_item": "Other Liabilities A",
     "period_end": "2025-12-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": 7.0
    },
    {
     "line_item": "Borrowings A",
     "period_end": "2024-03-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": 1234.0
    },
    {
     "line_item": "Borrowings A",
     "period_end": "2025-03-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": null
    },
    {
     "line_item": "Borrowings A",
     "period_end": "2025-12-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": 7.0
    },
    {
     "line_item": "Other Assets A",
     "period_end": "2024-03-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": 1234.0
    },
    {
     "line_item": "Other Assets A",
     "period_end": "2025-03-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": null
    },
    {
     "line_item": "Other Assets A",
     "period_end": "2025-12-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": 7.0
    },
    {
     "line_item": "Fixed Assets A",
     "period_end": "2024-03-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": 1234.0
    },
    {
     "line_item": "Fixed Assets A",
     "period_end": "2025-03-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": null
    },
    {
     "line_item": "Fixed Assets A",
     "period_end": "2025-12-31",
     "period_type": "annual",
     "sid": "INFY",
     "value": 7.0
    }
   ]
  ]
 ],
 "scrip_master.requests": [
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "python-requests/2.32.5"
   },
   "method": "GET",
   "params": null,
   "timeout": 120,
   "url": "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "python-requests/2.32.5"
   },
   "method": "GET",
   "params": null,
   "timeout": 60,
   "url": "https://raw.githubusercontent.com/rohittihiro/BhavCopy_Equity_Database/main/ListOfScrips.csv"
  }
 ],
 "scrip_master.rows": [
  [
   500325,
   "INE002A01018",
   "RELIANCE",
   "RELI",
   "RELIANCE INDUSTRIES",
   "Active",
   "upstox",
   "2026-09-25T00:00:00+00:00"
  ],
  [
   543210,
   "INE999Z01011",
   null,
   "BSEO",
   "BSE ONLY LTD",
   "Active",
   "upstox",
   "2026-09-25T00:00:00+00:00"
  ],
  [
   111111,
   "INE111A01011",
   null,
   null,
   "Gone Ltd",
   "Delisted",
   "listofscrips",
   "2026-09-25T00:00:00+00:00"
  ]
 ],
 "transcripts_pull.requests": [
  {
   "allow_redirects": false,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 15,
   "url": "https://www.screener.in/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 25,
   "url": "https://www.screener.in/company/TCS/consolidated/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.bseindia.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 40,
   "url": "https://www.bseindia.com/xml-data/corpfiling/AttachLive/aaa-111.pdf"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.bseindia.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 40,
   "url": "https://www.bseindia.com/xml-data/corpfiling/AttachHis/aaa-111.pdf"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.bseindia.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 40,
   "url": "https://www.bseindia.com/xml-data/corpfiling/AttachLive/bbb-222.pdf"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 25,
   "url": "https://www.screener.in/company/INFY/consolidated/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 25,
   "url": "https://www.screener.in/company/INFY/"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.bseindia.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 40,
   "url": "https://www.bseindia.com/xml-data/corpfiling/AttachLive/aaa-111.pdf"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.bseindia.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 40,
   "url": "https://www.bseindia.com/xml-data/corpfiling/AttachHis/aaa-111.pdf"
  },
  {
   "allow_redirects": true,
   "data": null,
   "headers": {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.bseindia.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   },
   "method": "GET",
   "params": null,
   "timeout": 40,
   "url": "https://www.bseindia.com/xml-data/corpfiling/AttachLive/bbb-222.pdf"
  }
 ],
 "transcripts_pull.stored": [
  [
   {
    "announce_date": "2026-04-27",
    "bse_filing_date": "2026-04-28",
    "char_count": 50,
    "doc_date": "2026-04-01",
    "doc_type": "transcript",
    "n_pages": 3,
    "pdf_url": "https://www.bseindia.com/xml-data/corpfiling/AttachHis/aaa-111.pdf",
    "period_label": "Apr 2026",
    "raw_text": "Earnings call held on April 27, 2026. %PDF-1.4 aaa",
    "sha256": "ff95d17209c64d3ef4c3cda08d75315095460fb8e28a6f637932310be02f7fcf",
    "sid": "TCS",
    "source_url": "https://www.bseindia.com/stock-share-price/AnnPdfOpen.aspx?Pname=aaa-111.pdf"
   },
   {
    "announce_date": "2026-04-27",
    "bse_filing_date": null,
    "char_count": 50,
    "doc_date": "2026-01-01",
    "doc_type": "transcript",
    "n_pages": 3,
    "pdf_url": "https://www.bseindia.com/xml-data/corpfiling/AttachLive/bbb-222.pdf",
    "period_label": "Jan 2026",
    "raw_text": "Earnings call held on April 27, 2026. %PDF-1.4 bbb",
    "sha256": "dc039d8d712af558274299b0abb51557612ae5750961f7f55803df21522da8b4",
    "sid": "TCS",
    "source_url": "https://www.bseindia.com/xml-data/corpfiling/AttachLive/bbb-222.pdf"
   }
  ],
  [
   {
    "announce_date": "2026-04-27",
    "bse_filing_date": "2026-04-28",
    "char_count": 50,
    "doc_date": "2026-04-01",
    "doc_type": "transcript",
    "n_pages": 3,
    "pdf_url": "https://www.bseindia.com/xml-data/corpfiling/AttachHis/aaa-111.pdf",
    "period_label": "Apr 2026",
    "raw_text": "Earnings call held on April 27, 2026. %PDF-1.4 aaa",
    "sha256": "ff95d17209c64d3ef4c3cda08d75315095460fb8e28a6f637932310be02f7fcf",
    "sid": "INFY",
    "source_url": "https://www.bseindia.com/stock-share-price/AnnPdfOpen.aspx?Pname=aaa-111.pdf"
   },
   {
    "announce_date": "2026-04-27",
    "bse_filing_date": null,
    "char_count": 50,
    "doc_date": "2026-01-01",
    "doc_type": "transcript",
    "n_pages": 3,
    "pdf_url": "https://www.bseindia.com/xml-data/corpfiling/AttachLive/bbb-222.pdf",
    "period_label": "Jan 2026",
    "raw_text": "Earnings call held on April 27, 2026. %PDF-1.4 bbb",
    "sha256": "dc039d8d712af558274299b0abb51557612ae5750961f7f55803df21522da8b4",
    "sid": "INFY",
    "source_url": "https://www.bseindia.com/xml-data/corpfiling/AttachLive/bbb-222.pdf"
   }
  ]
 ],
 "yfinance_prices.calls": [
  {
   "args": [
    [
     "AAA.NS",
     "BBB.NS",
     "CCC.NS",
     "DDD.NS"
    ],
    [
     [
      "auto_adjust",
      false
     ],
     [
      "group_by",
      "ticker"
     ],
     [
      "period",
      "30d"
     ],
     [
      "progress",
      false
     ],
     [
      "threads",
      false
     ]
    ]
   ],
   "host": "query2.finance.yahoo.com",
   "name": "download"
  },
  {
   "args": [
    [
     "BBB.BO",
     "CCC.BO",
     "DDD.BO"
    ],
    [
     [
      "auto_adjust",
      false
     ],
     [
      "group_by",
      "ticker"
     ],
     [
      "period",
      "30d"
     ],
     [
      "progress",
      false
     ],
     [
      "threads",
      false
     ]
    ]
   ],
   "host": "query2.finance.yahoo.com",
   "name": "download"
  }
 ],
 "yfinance_prices.written": [
  [
   "stock_prices",
   [
    {
     "close": 100.0,
     "date": "2026-09-23",
     "high": 101.0,
     "low": 98.0,
     "open": 99.0,
     "sid": "A",
     "source": "yfinance.NS",
     "volume": 1000
    },
    {
     "close": 101.0,
     "date": "2026-09-24",
     "high": 102.0,
     "low": 99.0,
     "open": 100.0,
     "sid": "A",
     "source": "yfinance.NS",
     "volume": 2000
    },
    {
     "close": 100.0,
     "date": "2026-09-23",
     "high": 101.0,
     "low": 98.0,
     "open": 99.0,
     "sid": "B",
     "source": "yfinance.BO",
     "volume": 1000
    },
    {
     "close": 101.0,
     "date": "2026-09-24",
     "high": 102.0,
     "low": 99.0,
     "open": 100.0,
     "sid": "B",
     "source": "yfinance.BO",
     "volume": 2000
    },
    {
     "close": 102.0,
     "date": "2026-09-24",
     "high": 103.0,
     "low": 100.0,
     "open": 101.0,
     "sid": "C",
     "source": "yfinance.BO",
     "volume": 2000
    }
   ]
  ]
 ]
}
""")
