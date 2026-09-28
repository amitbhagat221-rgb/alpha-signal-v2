"""
Alpha Signal v2 — Canaries: one tiny live probe per feed (plan 0018 §6, rung 2).

A canary asks the feed's primary route for ONE item and hands back what came over
the wire; tools/canary.py judges it (Gate 1 transport, Gate 2 content, shape
fingerprint vs the accepted baseline). A canary never writes a table.

Each canary reuses the feed module's own URL constants and fetch helpers, so a
URL change is fixed once and the harvester and its canary move together. Every
call goes through the host door (sources/_http: polite_get, or pace() around a
library client). The same function is the smoke test for a discovery candidate.

A canary returns a sample dict:
    expect     "json" | "csv" | "html" | "xml" | "text" | "frame"
    records    list[dict] | DataFrame | dict — what the fingerprint and row count read
    raw        bytes kept in data/raw/<feed>/ (last good + failures)
    http       status code (None for library clients that hide it)
    url        what was asked
    min_rows   Gate 2 floor (default 1)
    required   field names that must be present
    checks     [(name, ok, detail)] feed-specific content checks (a failure = class F)
    fields     optional explicit field list for the fingerprint (HTML canaries)
Plain functions (ADR 0004).
"""

import io
import json
import re
from datetime import date, timedelta

import pandas as pd

from sources import _http
from hosts import HOSTS
from db import scalar

REF_SLUG = "stocks/reliance-industries-RELI"   # Tickertape slug of feeds.REF
REF_TT_SID = "RELI"


def _resp(r, expect, records, **kw):
    return {"expect": expect, "records": records, "raw": r.content if r is not None else b"",
            "http": r.status_code if r is not None else 404, "url": getattr(r, "url", None),
            "content_type": r.headers.get("content-type") if r is not None else None, **kw}


def _frame(df, url, **kw):
    raw = df.head(200).to_csv(index=False).encode() if isinstance(df, pd.DataFrame) else b""
    return {"expect": "frame", "records": df, "raw": raw, "http": None, "url": url, **kw}


def _csv(r):
    if r is None or r.status_code != 200 or r.content[:1] == b"<":
        return None
    df = pd.read_csv(io.BytesIO(r.content))
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _latest(table, col):
    return scalar(f"SELECT MAX({col}) FROM {table}")


# ─────────────────────────────── Prices & market ───────────────────────────────

def nse_bhavcopy():
    from sources.nse import BHAVCOPY_URL
    d = pd.Timestamp(_latest("stock_prices", "date"))
    r = _http.polite_request("GET", BHAVCOPY_URL.format(date=d.strftime("%d%m%Y")),
                             check=False, retries=0, timeout=30)
    df = _csv(r)
    checks = []
    if df is not None and "CLOSE_PRICE" in df:
        close = pd.to_numeric(df["CLOSE_PRICE"], errors="coerce")
        checks.append(("close_positive", float((close > 0).mean()) >= 0.99, f"{(close > 0).mean():.3f} of rows"))
    return _resp(r, "csv", df, min_rows=1000, checks=checks,
                 required=["SYMBOL", "SERIES", "CLOSE_PRICE", "TTL_TRD_QNTY", "DELIV_PER"])


def yfinance_prices():
    import yfinance as yf
    with _http.pace("yahoo"):
        df = yf.Ticker("RELIANCE.NS").history(period="5d").reset_index()
    return _frame(df, "yf RELIANCE.NS 5d", required=["Open", "High", "Low", "Close", "Volume"])


def fno_bhav():
    from nselib import derivatives as dv
    d = pd.Timestamp(_latest("fno_bhav", "trade_date"))
    with _http.pace("nse"):
        df = dv.fno_bhav_copy(trade_date=d.strftime("%d-%m-%Y"))
    return _frame(df, f"nselib fno_bhav_copy {d.date()}", min_rows=5000)


def nse_indices():
    from nselib import capital_market as cm
    to = date.today()
    with _http.pace("nse"):
        df = cm.index_data(index="NIFTY 50", from_date=(to - timedelta(days=12)).strftime("%d-%m-%Y"),
                           to_date=to.strftime("%d-%m-%Y"))
    return _frame(df, "nselib index_data NIFTY 50 12d")


def nse_market_daily():
    from sources.nselib_pull import NSE_HOME
    s = _http.warm_session(NSE_HOME)
    r = _http.polite_request("GET", "https://www.nseindia.com/api/fiidiiTradeReact", session=s,
                             check=False, retries=0, timeout=30)
    js = r.json() if r.status_code == 200 and r.content[:1] in (b"[", b"{") else None
    return _resp(r, "json", js, required=["category", "date", "buyValue", "sellValue", "netValue"])


# ─────────────────────────────── Fundamentals ───────────────────────────────

def _tickertape_client():
    from sources.tickertape import _get_client
    return _get_client()


def tickertape_fundamentals():
    client = _tickertape_client()
    with _http.pace("tickertape"):
        df = client.get_income_data(REF_TT_SID, time_horizon="interim", num_time_periods=2)
    return _frame(df if isinstance(df, pd.DataFrame) else pd.DataFrame(df), f"Tickertape income {REF_TT_SID}")


def screener():
    from sources.screener_pull import COMPANY_CONSOLIDATED_URL, make_session
    r = _http.polite_request("GET", COMPANY_CONSOLIDATED_URL.format(ticker="RELIANCE"),
                             session=make_session(), check=False, retries=0, timeout=30)
    t = r.text if r is not None else ""
    sections = sorted(set(re.findall(r'<section[^>]*\bid="([a-z0-9-]+)"', t)))
    checks = [("logged_in", "logout" in t.lower(), "Premium session cookie accepted"),
              ("export_form", bool(re.search(r'formaction=["\']/user/company/export/\d+/', t)), "Excel export button"),
              ("shareholding_table", 'id="quarterly-shp"' in t, "quarterly shareholding table")]
    return _resp(r, "html", [{"section": s} for s in sections], fields=sections, checks=checks,
                 required=["profit-loss", "balance-sheet", "cash-flow", "shareholding"])


# ─────────────────────────────── Ownership ───────────────────────────────

def tickertape_shareholding():
    client = _tickertape_client()
    with _http.pace("tickertape"):
        sh = client.get_share_holding_pattern(REF_SLUG)
    df = sh if isinstance(sh, pd.DataFrame) else pd.DataFrame(sh)
    return _frame(df, f"Tickertape shareholding {REF_SLUG}")


def nse_insider():
    from sources.nse_insider import NSE_HOME, NSE_PIT_LIST_URL, SESSION_HEADERS
    s = _http.warm_session(NSE_HOME, headers=SESSION_HEADERS)
    to = date.today()
    r = _http.polite_request("GET", NSE_PIT_LIST_URL, session=s, check=False, retries=0, timeout=60,
                             params={"index": "equities", "from_date": (to - timedelta(days=10)).strftime("%d-%m-%Y"),
                                     "to_date": to.strftime("%d-%m-%Y")})
    js = r.json() if r.status_code == 200 and r.content[:1] == b"{" else None
    rows = (js or {}).get("data") if isinstance(js, dict) else None
    return _resp(r, "json", rows, required=["symbol", "xmlFileName"])


def nse_bulk_deals():
    from sources.nse_bulk import BULK_URL
    r = _http.polite_request("GET", BULK_URL, check=False, retries=0, timeout=30)
    return _resp(r, "csv", _csv(r), required=["Date", "Symbol", "Client Name", "Buy/Sell", "Quantity Traded"])


# ─────────────────────────────── Estimates ───────────────────────────────

def tickertape_analyst():
    from sources.tickertape_analyst import _fetch_next_data
    data = _fetch_next_data(REF_SLUG) or {}
    pp = data.get("props", {}).get("pageProps", {})
    fc = (pp.get("securitySummary") or {}).get("forecast") or {}
    rec = {"pageProps." + k: 1 for k in pp} | {"forecast." + k: 1 for k in fc}
    checks = [("forecast_block", bool(fc), "securitySummary.forecast present"),
              ("forecasts_history", bool(pp.get("forecastsHistory")), "forecastsHistory present")]
    return {"expect": "json", "records": [rec] if rec else None, "raw": json.dumps(pp, default=str)[:200000].encode(),
            "http": 200 if data else 404, "url": f"https://tickertape.in/{REF_SLUG}", "checks": checks,
            "required": ["forecast.totalReco", "pageProps.forecastsHistory"]}


def yfinance_analyst():
    import yfinance as yf
    with _http.pace("yahoo"):
        t = yf.Ticker("RELIANCE.NS").analyst_price_targets or {}
    return {"expect": "json", "records": [t] if t else None, "raw": json.dumps(t, default=str).encode(), "http": None,
            "url": "yf RELIANCE.NS analyst_price_targets", "required": ["current", "mean", "high", "low"]}


def moneycontrol_recos():
    from sources.moneycontrol_recos import QUOTE_URL_TEMPLATE
    slug = scalar("SELECT mc_slug FROM stocks WHERE ticker = 'RELIANCE'")
    r = _http.polite_request("GET", QUOTE_URL_TEMPLATE.format(slug=slug), check=False, retries=0, timeout=40)
    t = r.text if r is not None else ""
    blocks = len(re.findall(r'class="[^"]*brrs_bx', t))
    return _resp(r, "html", [{"brrs_bx": 1}] * blocks, fields=["brrs_bx"], required=["brrs_bx"],
                 checks=[("reco_blocks", blocks > 0, f"{blocks} broker-reco blocks")])


# ─────────────────────────────── Events ───────────────────────────────

def bse_announcements():
    from sources.bse_announcements import WARM_URL, _fetch_page
    s = _http.warm_session(WARM_URL, headers=HOSTS["bse_api"]["headers"])
    day = str(_latest("bse_announcements", "dt_tm"))[:10].replace("-", "")   # a day we know has filings
    rows, total = _fetch_page(s, day, day, 1)        # single day: the API returns 0 for date RANGES
    return {"expect": "json", "records": rows or None, "raw": json.dumps(rows[:20], default=str).encode(), "http": 200 if rows else None,
            "url": f"api.bseindia.com AnnSubCategoryGetData {day} page 1",
            "required": ["NEWSID", "SCRIP_CD", "NEWSSUB", "DT_TM", "ATTACHMENTNAME", "SUBCATNAME"],
            "checks": [("total_count", total > 0, f"ROWCNT={total}")]}


def corporate_actions():
    from nselib import capital_market as cm
    to = date.today()
    with _http.pace("nse"):
        df = cm.corporate_actions_for_equity(from_date=(to - timedelta(days=30)).strftime("%d-%m-%Y"),
                                             to_date=to.strftime("%d-%m-%Y"))
    return _frame(df, "nselib corporate_actions_for_equity 30d")


def earnings_calendar():
    from nselib import capital_market as cm
    to = date.today()
    with _http.pace("nse"):
        df = cm.event_calendar_for_equity(from_date=to.strftime("%d-%m-%Y"),
                                          to_date=(to + timedelta(days=30)).strftime("%d-%m-%Y"))
    return _frame(df, "nselib event_calendar_for_equity +30d")


# ─────────────────────────────── Macro ───────────────────────────────

def macro_market():
    import yfinance as yf
    with _http.pace("yahoo"):
        df = yf.Ticker("^NSEI").history(period="5d").reset_index()
    return _frame(df, "yf ^NSEI 5d", required=["Open", "High", "Low", "Close"])


def macro_official():
    from sources.macro_official import MOSPI, _mospi
    js = _mospi(_http.session(MOSPI), "/api/iip/getIipData", base_year="2022-23", frequency="Monthly",
                type="All", year=str(date.today().year), limit=50, page="1") or {}
    rows = js.get("data") if isinstance(js, dict) else None
    return {"expect": "json", "records": rows or None, "raw": json.dumps(js, default=str)[:200000].encode(),
            "http": 200 if js else None, "url": MOSPI + "/api/iip/getIipData",
            "required": ["category", "month", "year", "index"]}


# ─────────────────────────────── News ───────────────────────────────

def _rss(url):
    import feedparser
    r = _http.polite_request("GET", url, check=False, retries=0, timeout=30)
    if r is None or r.status_code != 200:
        return _resp(r, "xml", None)
    feed = feedparser.parse(r.content)
    recs = [{k: 1 for k in ("title", "link", "published", "summary") if e.get(k)} for e in feed.entries[:50]]
    return _resp(r, "xml", recs or None, required=["title", "link"])


def rss_news():
    from sources.rss import FEEDS as RSS
    return _rss(RSS["et_markets"])


def regulatory_news():
    return _rss("https://news.google.com/rss/search?q=RBI+circular&hl=en-IN&gl=IN&ceid=IN:en")


# ─────────────────────────────── Reference + funds ───────────────────────────────

def scrip_master():
    import gzip
    import json
    from sources.scrip_master import LISTOFSCRIPS_URL, UPSTOX_URL
    r = _http.polite_request("GET", UPSTOX_URL, check=False, retries=0, timeout=120)
    rows = json.load(gzip.open(io.BytesIO(r.content))) if r.status_code == 200 else None
    segs = {x.get("segment") for x in rows or []}
    fb = _http.polite_request("HEAD", LISTOFSCRIPS_URL, check=False, retries=0, timeout=30)
    return _resp(r, "json", rows, min_rows=10000, raw_head=True,
                 required=["segment", "isin", "trading_symbol", "exchange_token", "name"],
                 checks=[("segments", {"BSE_EQ", "NSE_EQ"} <= segs, "BSE_EQ + NSE_EQ present"),
                         ("fallback_route", fb is not None and fb.status_code == 200,
                          f"ListOfScrips mirror HEAD {getattr(fb, 'status_code', None)}", "B", "WARN")])


def amfi_nav():
    from sources.mf_amfi_master import NAVALL_URL, parse_navall
    r = _http.polite_request("GET", NAVALL_URL, check=False, retries=0, timeout=60)
    rows = parse_navall(r.text) if r.status_code == 200 and r.content[:1] != b"<" else None
    return _resp(r, "text", rows, min_rows=10000, required=["scheme_code", "nav"])


def mf_holdings():
    from sources.mf_holdings_scrape import PORTFOLIO_SITEMAP
    r = _http.polite_request("GET", PORTFOLIO_SITEMAP, check=False, retries=0, timeout=40)
    locs = re.findall(r"<loc>([^<]+)</loc>", r.text) if r is not None else []
    return _resp(r, "xml", [{"loc": 1}] * len(locs) or None, fields=["loc"], min_rows=100)


def nse_credit_ratings():
    from sources.nse_events import RATING_API, RATING_REFERER, _rows_json, _session
    to = date.today()
    r = _http.polite_request("GET", RATING_API, session=_session(RATING_REFERER), check=False, retries=0,
                             timeout=60, params={"index": "equities", "from_date": (to - timedelta(days=10)).strftime("%d-%m-%Y"),
                                                 "to_date": to.strftime("%d-%m-%Y")})
    return _resp(r, "json", _rows_json(r) or None,
                 required=["CreditRating", "CreditRatingEarlier", "RatingAction", "DateofCR", "ISIN", "BroadcastDateTime"])


def yahoo_estimates():
    import yfinance as yf
    with _http.pace("yahoo"):
        ed = yf.Ticker("RELIANCE.NS").get_earnings_dates(limit=12)
    df = ed.reset_index() if ed is not None else None
    return _frame(df, "yf RELIANCE.NS earnings_dates", min_rows=4, required=["EPS Estimate", "Reported EPS"])


CANARIES = {
    "nse_bhavcopy": nse_bhavcopy, "yfinance_prices": yfinance_prices, "fno_bhav": fno_bhav,
    "nse_indices": nse_indices, "nse_market_daily": nse_market_daily,
    "tickertape_fundamentals": tickertape_fundamentals, "screener": screener,
    "tickertape_shareholding": tickertape_shareholding, "nse_insider": nse_insider,
    "nse_bulk_deals": nse_bulk_deals, "tickertape_analyst": tickertape_analyst,
    "yfinance_analyst": yfinance_analyst, "moneycontrol_recos": moneycontrol_recos,
    "bse_announcements": bse_announcements, "corporate_actions": corporate_actions,
    "earnings_calendar": earnings_calendar, "macro_market": macro_market,
    "macro_official": macro_official, "rss_news": rss_news, "regulatory_news": regulatory_news,
    "scrip_master": scrip_master, "amfi_nav": amfi_nav, "mf_holdings": mf_holdings,
    "nse_credit_ratings": nse_credit_ratings, "yahoo_estimates": yahoo_estimates,
}
