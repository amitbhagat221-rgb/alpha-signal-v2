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


# ─────────────────────────────── BSE shareholding XBRL: named holders ───────────────────────────────

def _shp_ctx(key, when, q='"'):
    typed = f"<xbrldi:typedMember dimension={q}in-bse-shp:XAxis{q}><in-bse-shp:XDomain>{key}</in-bse-shp:XDomain></xbrldi:typedMember>"
    return (f"<xbrli:context id={q}D_{key}{q}><xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate>"
            f"<xbrli:endDate>{when}</xbrli:endDate></xbrli:period><xbrli:scenario>{typed}</xbrli:scenario></xbrli:context>"
            f"<xbrli:context id={q}{key}{q}><xbrli:period><xbrli:instant>{when}</xbrli:instant></xbrli:period>"
            f"<xbrli:scenario>{typed}</xbrli:scenario></xbrli:context>")


def test_bse_shp_parses_named_holders_from_xml_and_inline_xbrl():
    from sources.bse_shp import parse_holders
    # XBRL .xml, 2016 taxonomy: keys without "_Context"; a "Category" member is a sub-total, not a holder
    xml = (_shp_ctx("IndividualsOrHUF15", "2016-06-30") + _shp_ctx("OtherNonInstitutions16", "2016-06-30")
           + '<in-bse-shp:NameOfTheShareholder contextRef="D_IndividualsOrHUF15">Rajat  Agrawal</in-bse-shp:NameOfTheShareholder>'
           '<in-bse-shp:NumberOfShares contextRef="IndividualsOrHUF15" unitRef="shares" decimals="INF">32677725</in-bse-shp:NumberOfShares>'
           '<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="IndividualsOrHUF15" unitRef="pure">47.76</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>'
           '<in-bse-shp:NameOfTheShareholder contextRef="D_OtherNonInstitutions16">Clearing Members</in-bse-shp:NameOfTheShareholder>'
           '<in-bse-shp:WhetherACategoryOrMoreThan1PercentageOfShareHolding contextRef="D_OtherNonInstitutions16">Category</in-bse-shp:WhetherACategoryOrMoreThan1PercentageOfShareHolding>'
           '<in-bse-shp:NumberOfShares contextRef="OtherNonInstitutions16" unitRef="shares">500</in-bse-shp:NumberOfShares>')
    assert parse_holders(xml) == [{"end_date": "2016-06-30", "holder_category": "IndividualsOrHUF", "holder_seq": 15,
                                   "holder_name": "Rajat Agrawal", "promoter_type": None,
                                   "shares": 32677725.0, "pct": 47.76}]
    # inline XBRL .html, 2025 taxonomy: single quotes, scale='-2' on the percentage (printed text stays percent)
    key = "DetailsOfSharesHeldByInstitutionsForeignPortfolioInvestorOne_Context17"
    ix = (_shp_ctx(key, "2026-06-30", q="'") + _shp_ctx("IndividualsOrHUF_Context15", "2026-06-30", q="'")
          + f"<ix:nonNumeric name='in-bse-shp:NameOfTheShareholder' contextRef='D_{key}'>GOLDMAN SACHS &amp; CO</ix:nonNumeric>"
          f"<ix:nonFraction name='in-bse-shp:NumberOfShares' contextRef='{key}' decimals='INF' unitRef='shares'>9,07,886</ix:nonFraction>"
          f"<ix:nonFraction name='in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares' contextRef='{key}' unitRef='pure' scale='-2'>1.23</ix:nonFraction>"
          "<ix:nonNumeric name='in-bse-shp:NameOfTheShareholder' contextRef='D_IndividualsOrHUF_Context15'>RAJAT AGRAWAL</ix:nonNumeric>"
          "<ix:nonNumeric name='in-bse-shp:TypeOfPromoterShareholding' contextRef='D_IndividualsOrHUF_Context15'>Promoter</ix:nonNumeric>"
          "<ix:nonFraction name='in-bse-shp:NumberOfShares' contextRef='IndividualsOrHUF_Context15' unitRef='shares'>23899789</ix:nonFraction>")
    got = {h["holder_name"]: h for h in parse_holders(ix)}
    fpi, promoter = got["GOLDMAN SACHS & CO"], got["RAJAT AGRAWAL"]
    assert (fpi["holder_category"], fpi["holder_seq"], fpi["shares"], fpi["pct"]) == \
        ("InstitutionsForeignPortfolioInvestorOne", 17, 907886.0, 1.23)
    assert promoter["promoter_type"] == "Promoter" and promoter["pct"] is None and promoter["end_date"] == "2026-06-30"
    assert parse_holders("<html>blocked</html>") == []


def _shp_total(key, when, shares, pct=None, holders=None):
    out = _shp_ctx(key, when) + f'<in-bse-shp:NumberOfShares contextRef="{key}" unitRef="shares">{shares}</in-bse-shp:NumberOfShares>'
    if pct is not None:
        out += f'<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="{key}" unitRef="pure">{pct}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>'
    if holders is not None:
        out += f'<in-bse-shp:NumberOfShareholders contextRef="{key}" unitRef="shares">{holders}</in-bse-shp:NumberOfShareholders>'
    return out


def test_bse_shp_parses_category_totals_in_both_taxonomies():
    from sources.bse_shp import parse_categories, parse_holders
    # 2016 taxonomy, keys "<Category>I": one Institutions total with the FPIs inside it; no
    # insurance line (= 0); a holder with shares but no percentage gets shares / total
    d = "2017-09-30"
    old = (_shp_total("ShareholdingPatternI", d, 1000, 100, 5000) + _shp_total("ShareholdingOfPromoterAndPromoterGroupI", d, 600, 60)
           + _shp_total("PublicShareholdingI", d, 400, 40, 4990) + _shp_total("InstitutionsI", d, 150, 15)
           + _shp_total("InstitutionsForeignPortfolioInvestorI", d, 100, 10) + _shp_total("MutualFundsOrUtiI", d, 50, 5)
           + _shp_total("IndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakhI", d, 200, 20, 4900)
           + _shp_ctx("PAC_Public15", d)
           + '<in-bse-shp:NameOfTheShareholder contextRef="D_PAC_Public15">Acting Together Pvt Ltd</in-bse-shp:NameOfTheShareholder>'
           '<in-bse-shp:NumberOfShares contextRef="PAC_Public15" unitRef="shares">25</in-bse-shp:NumberOfShares>')
    assert parse_categories(old) == {
        "end_date": d, "promoter_pct": 60.0, "public_pct": 40.0, "foreign_inst_pct": 10.0, "domestic_inst_pct": 5.0,
        "mf_pct": 5.0, "insurance_pct": 0.0, "retail_pct": 20.0, "hni_pct": None, "n_shareholders": 5000.0,
        "n_retail": 4900.0, "total_shares": 1000.0}
    assert parse_holders(old)[0]["pct"] == 2.5
    # 2022 taxonomy, keys "<Category>_ContextI": foreign and domestic institutions filed apart;
    # a category total without a percentage is shares / total too
    d = "2025-06-30"
    new = (_shp_total("ShareholdingPattern_ContextI", d, 2000, 100, 9000) + _shp_total("PublicShareholding_ContextI", d, 2000, 100)
           + _shp_total("InstitutionsForeign_ContextI", d, 300, 15) + _shp_total("InstitutionsDomestic_ContextI", d, 500)
           + _shp_total("MutualFundsOrUTI_ContextI", d, 400, 20) + _shp_total("InsuranceCompanies_ContextI", d, 100, 5))
    got = parse_categories(new)
    assert (got["promoter_pct"], got["foreign_inst_pct"], got["domestic_inst_pct"], got["mf_pct"], got["insurance_pct"]) == \
        (0.0, 15.0, 25.0, 20.0, 5.0)
    assert got["retail_pct"] is None and got["n_retail"] is None
    assert parse_categories("<html>blocked</html>") is None


def test_bse_shp_latest_quarter_end():
    from datetime import date
    from sources.bse_shp import latest_quarter_end
    assert latest_quarter_end(date(2026, 10, 4)) == "2026-09-30"
    assert latest_quarter_end(date(2026, 9, 30)) == "2026-06-30"
    assert latest_quarter_end(date(2026, 2, 1)) == "2025-12-31"


# ─────────────────────────────── NSE legacy bhavcopy (pre-2020) ───────────────────────────────

def test_legacy_bhavcopy_maps_to_the_current_shape(monkeypatch):
    import io
    import zipfile
    from datetime import date
    from sources import nse
    lines = ["SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,"]
    lines += [f"SYM{i},EQ,10,12,9,11,11,10,1000,11000,05-JAN-2015,50,INE{i:09d}," for i in range(1100)]
    lines += ["GSEC1,GS,100,100,100,100,100,100,5,500,05-JAN-2015,1,IN0000000001,"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("cm05JAN2015bhav.csv", "\n".join(lines))
    monkeypatch.setattr(nse._http, "sid_map", lambda col="ticker": {"SYM0": "S0", "SYM1": "S1"})

    df, errs = nse._clean(nse.parse_legacy(buf.getvalue()), date(2015, 1, 5), source=nse.LEGACY_SOURCE)
    assert errs == [] and sorted(df["sid"]) == ["S0", "S1"]
    row = df.iloc[0]
    assert (row["date"], row["close"], row["prev_close"], row["volume"], row["num_trades"], row["source"]) == \
        ("2015-01-05", 11, 10, 1000, 50, "legacy_bhavcopy")
    assert pd.isna(row["delivery_pct"]) and pd.isna(row["traded_value"]), "the legacy file has no delivery; value is not carried"
    outside = nse._UNLISTED.pop(date(2015, 1, 5))
    assert len(outside) == 1098 and "GSEC1" not in set(outside["symbol"]), "non-equity series are dropped"
    # a file served for another day (holiday → previous session) is refused
    df2, errs2 = nse._clean(nse.parse_legacy(buf.getvalue()), date(2015, 1, 6), source=nse.LEGACY_SOURCE)
    assert df2 is None and "holiday" in errs2[0]
