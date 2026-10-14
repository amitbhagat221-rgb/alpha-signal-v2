"""MF holdings coverage fix 2026-10-10: strict AMFI ↔ ETMoney matching, the month-first
portfolio date, and a remap that quarantines holdings taken from another fund's page."""
import contextlib
import sqlite3

import pandas as pd

from sources import mf_holdings_scrape as mh

_SITEMAP = {mh._normalise_etm_slug(s): (s, i) for s, i in [
    ("canara-robeco-income-direct-growth", 1), ("canara-robeco-flexi-cap-fund-direct-growth", 2),
    ("kotak-flexicap-fund-direct-growth", 3), ("kotak-flexicap-fund", 4),
    ("lic-mf-nifty-50-index-fund-direct-growth", 5), ("sbi-long-term-fund", 6),
    ("uti-focused-fund-30-stocks-direct-growth", 7), ("dsp-india-tiger-fund", 8),
    ("axis-global-innovation-fof-direct-growth", 9),
    ("icici-prudential-large-cap-fund-direct-growth", 10),
]}
_INDEX = mh._etm_index(_SITEMAP)


def _slug(name, plan="DIRECT"):
    hit = mh._match(name, _INDEX, plan)
    return hit[0] if hit else None


def test_same_fund_only():
    assert _slug("Canara Robeco Flexi Cap Fund") == "canara-robeco-flexi-cap-fund-direct-growth"
    assert _slug("Canara Robeco Banking and Financial Services Fund") is None   # was → canara-robeco-income
    assert _slug("LIC MF Nifty Next 50 Index Fund") is None                     # was → the Nifty 50 fund
    assert _slug("SBI Long Term Advantage Fund - Series IV") is None            # closed-end series ≠ open fund


def test_spelling_variants_still_match():
    assert _slug("Kotak Flexi Cap Fund") == "kotak-flexicap-fund-direct-growth"      # flexi cap = flexicap
    assert _slug("Kotak Flexi Cap Fund", "REGULAR") == "kotak-flexicap-fund"         # plan picks the slug
    assert _slug("UTI Focused Fund (30 stocks)") == "uti-focused-fund-30-stocks-direct-growth"
    assert _slug("ICICI Prudential Large Cap Fund (erstwhile Bluechip Fund)") \
        == "icici-prudential-large-cap-fund-direct-growth"
    assert _slug("DSP India T.I.G.E.R. Fund", "REGULAR") == "dsp-india-tiger-fund"
    assert _slug("Axis Global Innovation Fund of Fund") == "axis-global-innovation-fof-direct-growth"


def test_portfolio_date_month_first_and_as_on_first():
    page = ('<script>{"about":"AUM as of March 31, 2026"}</script>'
            '<h2>Portfolio Overview</h2><span class="asset-dates">as on Sep 30, 2026</span>')
    assert mh._parse_holdings_page(page)[2] == "2026-09-30"
    assert mh._parse_holdings_page("<p>Portfolio as on 31 Aug, 2026</p>")[2] == "2026-08-31"


def test_full_remap_clears_wrong_page_and_quarantines_its_holdings(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE mf_scheme_master (scheme_code TEXT, scheme_name TEXT, plan_type TEXT, active INT,
            data_quality TEXT, etm_slug TEXT, etm_id INT, etm_checked_at TEXT);
        CREATE TABLE mf_holdings (scheme_code TEXT, as_of_date TEXT, holding_rank INT, instrument_type TEXT,
            sid TEXT, isin TEXT, instrument_name TEXT, sector TEXT, pct_of_aum REAL, market_value_cr REAL);
        CREATE TABLE mf_holdings_quarantine AS SELECT *, '' _q_failed_gate, '' _q_reason, '' _q_quarantined_at
            FROM mf_holdings WHERE 0;
        CREATE TABLE mf_sector_allocation (scheme_code TEXT, as_of_date TEXT, sector TEXT, pct_of_aum REAL);
        CREATE TABLE mf_sector_allocation_quarantine AS SELECT *, '' _q_failed_gate, '' _q_reason,
            '' _q_quarantined_at FROM mf_sector_allocation WHERE 0;
        INSERT INTO mf_scheme_master VALUES
            ('A', 'Canara Robeco Banking and Financial Services Fund', 'DIRECT', 1, 'TRUSTED',
             'canara-robeco-income-direct-growth', 1, '2026-05-28'),
            ('B', 'Kotak Flexi Cap Fund', 'DIRECT', 1, 'TRUSTED', 'kotak-flexicap-fund-direct-growth', 3, '2026-05-28'),
            ('C', 'Canara Robeco Flexi Cap Fund', 'DIRECT', 1, 'TRUSTED', NULL, NULL, NULL);
        INSERT INTO mf_holdings VALUES ('A', '2026-05-28', 1, 'EQUITY', NULL, NULL, 'Some Bond', NULL, 9.0, NULL),
                                       ('B', '2026-05-28', 1, 'EQUITY', NULL, NULL, 'HDFC Bank', NULL, 8.0, NULL);
        INSERT INTO mf_sector_allocation VALUES ('A', '2026-05-28', 'Debt', 9.0);
    """)

    @contextlib.contextmanager
    def get_db(*a, **k):
        yield conn
        conn.commit()

    monkeypatch.setattr(mh, "get_db", get_db)
    monkeypatch.setattr(mh, "read_sql", lambda q, params=None: pd.read_sql(q, conn, params=params))
    monkeypatch.setattr(mh, "fetch_etm_sitemap_urls", lambda: _SITEMAP)

    mh.build_mapping()
    rows = dict(conn.execute("SELECT scheme_code, etm_slug FROM mf_scheme_master").fetchall())
    assert rows == {"A": None, "B": "kotak-flexicap-fund-direct-growth",
                    "C": "canara-robeco-flexi-cap-fund-direct-growth"}
    assert conn.execute("SELECT scheme_code FROM mf_holdings").fetchall() == [("B",)]   # B kept: same page
    assert conn.execute("SELECT scheme_code, _q_failed_gate FROM mf_holdings_quarantine").fetchall() \
        == [("A", "etm_mapping")]
    assert conn.execute("SELECT COUNT(*) FROM mf_sector_allocation").fetchone() == (0,)
    assert conn.execute("SELECT etm_checked_at FROM mf_scheme_master WHERE scheme_code='B'").fetchone() \
        == ("2026-05-28",)   # untouched mapping keeps its place in the rotation


# ── Groww route (primary, 2026-10-10) ──────────────────────────────────────────────

import json as _json
import types

from sources import mf_holdings_groww as mg


def _page(code="151917", isin="INF0J8L01156", holdings=None, **extra):
    data = {"scheme_code": code, "direct_scheme_code": code, "isin": isin, **extra, "holdings": holdings if holdings is not None else [
        {"company_name": "Torrent Pharmaceuticals Ltd", "nature_name": "EQUITY", "sector_name": "Healthcare",
         "instrument_name": "Equity", "market_value": 142.6, "corpus_per": 5.5, "portfolio_date": "2026-09-29T18:30:00.000Z"},
        {"company_name": "GOI 91 DAYS TBILL", "nature_name": "DEBT", "sector_name": "Financial",
         "instrument_name": "Treasury Bills", "market_value": 6.0, "corpus_per": 0.2, "portfolio_date": "2026-09-29T18:30:00.000Z"},
        {"company_name": "HDFC Bank Ltd", "nature_name": "EQUITY", "sector_name": "Financial",
         "instrument_name": "Equity", "market_value": 200.0, "corpus_per": 7.8, "portfolio_date": "2026-09-29T18:30:00.000Z"},
    ]}
    nd = {"props": {"pageProps": {"mfServerSideData": data}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{_json.dumps(nd)}</script></html>'


def test_groww_page_parse():
    codes, isin, holdings, sectors, as_of, status = mg.parse_page(_page())
    assert codes == {"151917"} and isin == "INF0J8L01156"
    assert status == {"lumpsum_open": None, "sip_open": None, "closed_reason": None}   # page silent → unknown
    assert as_of == "2026-09-30"                                   # IST midnight, not the UTC date
    assert [h["instrument_name"] for h in holdings] == ["HDFC Bank Ltd", "Torrent Pharmaceuticals Ltd", "GOI 91 DAYS TBILL"]
    tbill = holdings[2]
    assert tbill["instrument_type"] == "DEBT" and tbill["sector"] == "Treasury Bills"   # not Groww's "Financial"
    assert sectors == [{"sector": "Financial", "pct_of_aum": 7.8}, {"sector": "Healthcare", "pct_of_aum": 5.5}]


def test_groww_subscription_status():
    """HDFC Developed World FoF's page (2026-10-14): new money stopped at the fund level."""
    stopped = mg.parse_page(_page(available_for_investment=False, lumpsum_allowed=False, sip_allowed=False,
                                  blocked_reason="New investments have been stopped for this fund. "
                                                 "You can explore similar funds below."))[5]
    assert stopped == {"lumpsum_open": 0, "sip_open": 0,
                       "closed_reason": "New investments have been stopped for this fund."}
    assert mg.parse_page(_page(available_for_investment=True, lumpsum_allowed=True, sip_allowed=True))[5] == \
        {"lumpsum_open": 1, "sip_open": 1, "closed_reason": None}
    sip_only = mg.parse_page(_page(available_for_investment=True, lumpsum_allowed=False, sip_allowed=True))[5]
    assert (sip_only["lumpsum_open"], sip_only["sip_open"]) == (0, 1)
    # The fund-level switch overrides per-route flags.
    assert mg.parse_page(_page(available_for_investment=False, lumpsum_allowed=True, sip_allowed=True))[5][
        "lumpsum_open"] == 0


def test_groww_slug_guess():
    assert mg._guess_slug("SBI Long Term Advantage Fund - Series IV") == "sbi-long-term-advantage-fund-series-iv-direct-growth"
    assert mg._guess_slug("Kotak Large & Mid Cap Fund") == "kotak-large-and-mid-cap-fund-direct-growth"


def test_groww_writes_only_the_fund_the_page_is(monkeypatch):
    fund = lambda name, codes, isins, slug: {"amc": "X", "scheme_name": name, "codes": codes, "isins": isins,
                                             "slug": slug, "never_checked": True, "last_checked": None,
                                             "has_holdings": False, "score": None}
    monkeypatch.setattr(mg, "_ensure_columns", lambda: None)
    monkeypatch.setattr(mg, "funds", lambda scheme=None: pd.DataFrame([
        fund("NJ Flexi Cap Fund", ["151917", "151918"], {"INF0J8L01156"}, "nj-flexi"),   # the right page
        fund("Wrong Guess Fund", ["999001"], {"INF999"}, "wrong-guess"),                 # page is NJ's
        fund("Gone Fund", ["999002"], set(), "gone"),                                     # 404
    ]))
    monkeypatch.setattr(mg, "read_sql", lambda q, params=None: pd.DataFrame({"sid": ["TORP"], "name": ["Torrent Pharmaceuticals Ltd."]}))
    pages = {"nj-flexi": (200, _page()), "wrong-guess": (200, _page()), "gone": (404, "")}
    monkeypatch.setattr(mg._http, "polite_request", lambda m, url, **k: types.SimpleNamespace(
        status_code=pages[url.rsplit("/", 1)[1]][0], text=pages[url.rsplit("/", 1)[1]][1]))
    monkeypatch.setattr(mg.runlog, "note", lambda *a, **k: None)
    written, marks, statuses = [], [], []
    monkeypatch.setattr(mg, "write_portfolio", lambda codes, as_of, h, s, n2s, **k: written.append((codes, as_of, len(h))) or (len(h), len(s)))
    monkeypatch.setattr(mg, "_mark", lambda codes, slug=None: marks.append((tuple(codes), slug)))
    monkeypatch.setattr(mg, "_write_status", lambda codes, status: statuses.append(tuple(codes)))

    assert mg.scrape() == 1
    assert written == [(["151917", "151918"], "2026-09-30", 3)]
    assert (("999001",), mg.NO_PAGE) in marks and (("999002",), mg.NO_PAGE) in marks
    assert (("151917", "151918"), None) in marks
    assert statuses == [("151917", "151918")]                 # only the page that is the fund


def test_expected_portfolio_month():
    from datetime import date
    assert mg.expected_portfolio(date(2026, 10, 10)) == "2026-08-31"   # September's file may not be out yet
    assert mg.expected_portfolio(date(2026, 10, 11)) == "2026-09-30"
    assert mg.expected_portfolio(date(2026, 1, 5)) == "2025-11-30"


def test_discover_links_renamed_fund_by_code(monkeypatch, tmp_path):
    monkeypatch.setattr(mg, "UNCLAIMED_FILE", tmp_path / "unclaimed.json")
    master = pd.DataFrame({"scheme_code": ["151917", "151918", "200001"],
                           "amc": ["NJ", "NJ", "Y"], "scheme_name": ["NJ Flexi Cap Fund", "NJ Flexi Cap Fund", "Y Fund"],
                           "groww_slug": [mg.NO_PAGE, mg.NO_PAGE, "y-fund-direct-growth"]})
    def fake_sql(q, params=None):
        if "DISTINCT groww_slug" in q:
            return pd.DataFrame({"groww_slug": ["y-fund-direct-growth"]})
        return master
    monkeypatch.setattr(mg, "read_sql", fake_sql)
    pages = {"nj-old-name-fund-direct-growth": _page(),                       # renamed: code 151917
             "y-second-page-direct-growth": _page(code="200001", isin="X"),   # fund already has a page
             "unknown-fund-direct-growth": _page(code="999999", isin="Z")}    # not in the master
    monkeypatch.setattr(mg._http, "polite_request", lambda m, url, **k: types.SimpleNamespace(
        status_code=200, text=pages[url.rsplit("/", 1)[1]]))
    written, marks, statuses = [], [], []
    monkeypatch.setattr(mg, "write_portfolio", lambda codes, as_of, h, s, n2s, **k: written.append(codes) or (0, 0))
    monkeypatch.setattr(mg, "_mark", lambda codes, slug=None: marks.append((tuple(codes), slug)))
    monkeypatch.setattr(mg, "_write_status", lambda codes, status: statuses.append(tuple(codes)))

    assert mg.discover(list(pages) + ["y-fund-direct-growth"], name_to_sid={}) == 1
    assert written == [["151917", "151918"]]
    assert marks == [(("151917", "151918"), "nj-old-name-fund-direct-growth")]
    left = _json.loads((tmp_path / "unclaimed.json").read_text())
    assert set(left) == {"y-second-page-direct-growth", "unknown-fund-direct-growth"}


def test_funds_with_half_its_plans_checked(monkeypatch):
    """The 2026-10-11 morning run died here: min() over check times mixed with NaN."""
    rows = pd.DataFrame({"scheme_code": ["1", "2", "3"], "amc": ["A", "A", "B"],
                         "scheme_name": ["F", "F", "G"], "isin_growth": ["I1", "I2", None], "isin_div": [None] * 3,
                         "groww_slug": ["f-direct-growth"] * 2 + [None],
                         "groww_checked_at": ["2026-10-10 20:15:00", None, None],
                         "has_holdings": [1, 0, 0], "last_portfolio": ["2026-09-30", None, None], "score": [0.5, None, None]})
    monkeypatch.setattr(mg, "read_sql", lambda q, params=None: rows)
    f = mg.funds().set_index("scheme_name")
    assert f.loc["F", "never_checked"] and f.loc["F", "last_checked"] == "2026-10-10 20:15:00"
    assert f.loc["F", "last_portfolio"] is None and f.loc["G", "last_checked"] is None
