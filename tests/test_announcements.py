"""ADR 0082: one announcement reader (signals.announcements) — BSE history + NSE live in BSE's taxonomy — and the
fraud / default red-flag kinds. Temp DB only; the headlines are real filings (2018-2026), quoted as filed."""
import sqlite3

import pandas as pd
import pytest

import config
import db
from signals import announcements as A

FLAGS = config.MB_THESIS["red_flags"]


def _bse(c, news_id, sid, subcategory, dt, sub="", headline="h", category="Company Update"):
    c.execute("INSERT INTO bse_announcements (news_id, scrip_cd, sid, headline, news_sub, category, subcategory, dt_tm, "
              "fetched_at) VALUES (?, 1, ?, ?, ?, ?, ?, ?, 'now')", (news_id, sid, headline, sub, category, subcategory, dt))


def _nse(c, seq, sid, desc, subject, an_dt):
    c.execute("INSERT INTO nse_announcements (seq_id, symbol, sid, desc_category, category, subject, an_dt, fetched_at) "
              "VALUES (?, 'SYM', ?, ?, 'other', ?, ?, 'now')", (seq, sid, desc, subject, an_dt))


@pytest.fixture()
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "a.db")
    c.executescript(db.SCHEMA_PATH.read_text())
    yield c
    c.close()


def _mapped(c, desc, subject):
    _nse(c, "m", "S", desc, subject, "2026-10-15 10:00:00")
    r = c.execute(f"SELECT category, subcategory FROM ({A.nse_sql()}) m").fetchone()
    c.execute("DELETE FROM nse_announcements")
    return r


@pytest.mark.parametrize("desc,subject,expect", [
    ("Outcome of Board Meeting", "Canara Bank has submitted to the Exchange, the financial results for the period "
     "ended September 30, 2026.", ("Result", "Financial Results")),
    ("Outcome of Board Meeting", "Kronox Lab Sciences Limited has informed the Exchange regarding Outcome of Board "
     "Meeting held on October 14, 2026.", ("Board Meeting", "Outcome of Board Meeting")),
    ("Resignation", "GP Petroleums Limited has informed the Exchange regarding Resignation of Mr Arjun Verma as Chief "
     "Financial Officer of the company w.e.f. October 15, 2026.", ("Company Update", "Resignation of Chief Financial Officer (CFO)")),
    ("Resignation", "NIIT Limited has informed the Exchange regarding Resignation of Mr Pankaj Prabhakar Jathar as Chief "
     "Executive Officer of the company", ("Company Update", "Resignation of Chief Executive Officer (CEO)")),
    ("Resignation", "Modi Naturals Limited has informed the Exchange regarding Resignation of Mr. Rajan Kumar Singh as "
     "Company Secretary & Compliance Officer", ("Company Update", "Resignation of Company Secretary / Compliance Officer")),
    ("Resignation", "Meesho Limited has informed the Exchange regarding Resignation of Mr Surojit Chatterjee as Non- "
     "Executive Independent Director", ("Company Update", "Resignation of Director")),
    ("Resignation", "Nazara Technologies Limited informs the Exchange regarding Resignation of Mr Rohit Sharma from the "
     "office of Whole-time Director", ("Company Update", "Resignation of Director")),
    ("Cessation", "Jyoti Structures Limited has informed the Exchange regarding Cessation of Mr Abdul Hameed Khan as "
     "Chief Financial Officer", ("Company Update", "Cessation")),
    ("Resignation of Statutory Auditor", "SecUR Credentials Limited has informed the Exchange about Resignation of "
     "Statutory Auditor", ("Company Update", "Resignation of Statutory Auditors")),
    ("General Updates", "Intimation of resignation of the Statutory Auditor of the Company",
     ("Company Update", "Resignation of Statutory Auditors")),
    ("Corporate Insolvency Resolution Process", "CoC meeting",
     ("Company Update", "Updates - Corporate Insolvency Resolution Process  (CIRP)")),
    ("Credit Rating- Revision", "x", ("Company Update", "Credit Rating")),
    ("Frauds/Default by employees", "Servotech Renewable Power System Limited has informed the Exchange about update "
     "on Frauds/Default by employees", ("Company Update", "General")),
    # not mapped: no clear BSE equivalent, or mapping it would double-count
    ("Resignation of Director/KMP/SMP", "Meesho Limited has informed the Exchange about Resignation of Director/KMP/SMP",
     (None, None)),
    ("Resignation", "Mayur Uniquoters Ltd has informed the Exchange regarding Resignation of Mr Ashutosh Pandey as "
     "Senior Management Personnel", (None, None)),
    ("Resignation", "UltraTech Cement Limited has informed the Exchange regarding relinquishment of position as "
     "Non-Executive Vice Chairman of the Company", (None, None)),
    ("Change in Auditors", "Tata Elxsi Limited has informed the Exchange regarding Change in Auditors of the company.",
     (None, None)),
    ("Appointment", "appointment of a director", (None, None)),
])
def test_nse_rows_map_to_their_bse_equivalent(conn, desc, subject, expect):
    assert _mapped(conn, desc, subject) == expect


def test_union_keeps_bse_and_drops_only_nse_copies_of_bse_filings(conn):
    _bse(conn, "b1", "S1", "Resignation of Chief Financial Officer (CFO)", "2026-10-10T18:00:00", "BSE copy")
    _nse(conn, "n1", "S1", "Resignation", "Resignation of Mr X as Chief Financial Officer", "2026-10-12 09:00:00")  # 2 days: copy
    _nse(conn, "n2", "S1", "Resignation", "Resignation of Mr Y as Chief Financial Officer", "2026-10-14 09:00:00")  # 4 days: new
    _nse(conn, "n3", "S1", "Cessation", "Cessation of Mr X as Chief Financial Officer", "2026-10-11 09:00:00")   # other subcat
    _nse(conn, "n4", "S2", "Resignation", "Resignation of Mr Z as Chief Financial Officer", "2026-10-10 09:00:00")  # other sid
    _nse(conn, "n5", None, "Resignation", "Resignation of Mr Q as Chief Financial Officer", "2026-10-10 09:00:00")  # unmapped sid
    _nse(conn, "n6", "S1", "Shareholders meeting", "AGM", "2026-10-10 09:00:00")                                  # NULL subcat
    got = pd.read_sql_query(f"SELECT * FROM ({A.sql()}) a ORDER BY id", conn)
    assert list(got.columns) == A.COLUMNS
    assert got["id"].tolist() == ["b1", "n2", "n3", "n4", "n5", "n6"]
    b = got.iloc[0]
    assert (b.source, b.subcategory, b.filed_as, b.title) == ("bse_announcements", "Resignation of Chief Financial "
                                                             "Officer (CFO)", "Resignation of Chief Financial Officer (CFO)",
                                                             "BSE copy")
    assert got.set_index("id").loc["n6", "filed_as"] == "Shareholders meeting"


def test_history_before_nse_is_untouched(conn):
    """PIT parity: NSE rows exist only from 2026-10-09, so every reader's history is the BSE history it had."""
    from signals.governance_events import events_sql
    import factors
    _bse(conn, "b1", "S1", "Resignation of Director", "2025-03-01T10:00:00")
    _bse(conn, "b2", "S1", "Financial Results", "2025-05-01T10:00:00", category="Result")
    q_gov = events_sql("2026-10-01")
    q_res = f"SELECT sid, date(dt_tm) d FROM ({factors.ANNOUNCEMENTS_SQL}) a WHERE {factors.RESULT_FILING_SQL} AND date(dt_tm) <= '2026-10-01'"
    before = (conn.execute(q_gov).fetchall(), conn.execute(q_res).fetchall())
    _nse(conn, "n1", "S1", "Resignation", "Resignation of Mr X as Director", "2026-10-14 10:00:00")
    _nse(conn, "n2", "S1", "Outcome of Board Meeting", "S1 has submitted to the Exchange, the financial results for the "
         "period ended September 30, 2026.", "2026-10-15 10:00:00")
    assert (conn.execute(q_gov).fetchall(), conn.execute(q_res).fetchall()) == before
    assert len(conn.execute(events_sql("2026-10-19")).fetchall()) == 2      # ... and today sees the NSE filing
    q_today = q_res.replace("2026-10-01", "2026-10-19")
    assert ("S1", "2026-10-15") in conn.execute(q_today).fetchall()


# ───────────── fraud / default kinds: real headlines, both ways ─────────────

def _kinds(conn, rows):
    """rows: [(source, subcategory_or_desc, title)] -> {title: set(kinds)}"""
    for i, (src, sub, title) in enumerate(rows):
        if src == "bse":
            _bse(conn, f"b{i}", "S", sub, "2026-06-01T10:00:00", title)
        else:
            _nse(conn, f"n{i}", "S", sub, title, "2026-10-15 10:00:00")
    ev = A.events({k: FLAGS[k] for k in ("fraud", "default")}, conn)
    return {t: set(ev.loc[ev["headline"] == t, "kind"]) for _, _, t in rows}


FRAUD_YES = [
    ("nse", "Frauds/Default by employees",
     "Servotech Renewable Power System Limited has informed the Exchange about update on Frauds/Default by employees"),
    ("nse", "Fraud/Default/Arrest", "Mangalam Drugs And Organics Limited has informed the Exchange about Fraud/Default/Arrest"),
    ("bse", "General", "Metro Brands Ltd - 543426 - Intimation Of Fraud By Two Employees Of The Company"),
    ("bse", "General", "Uflex Ltd - 500148 - Disclosures Under Regulation 30 Of The SEBI (Listing Obligations And "
                       "Disclosure Requirements) Regulations, 2015 - Reporting Of Fraud By Director Of Subsidiary Company."),
    ("bse", "General", "Gail (India) Ltd - 532155 - Shri E S Ranganathan, Director (Marketing) (DIN- 07417640) Named And "
                       "Arrested In Connection With Bribery Case"),
]
FRAUD_NO = [
    ("bse", "General", "Astron Paper & Board Mill Ltd - 540824 -  Intimation Regarding - Account Not Classified As Fraud"),
    ("bse", "General", "Sangam Finserv Ltd - 538714 - KIND ATTENTION TO GENERAL PUBLIC - CAUTION FOR FRAUD"),
    ("bse", "General", "Lancer Container Lines Ltd - 539841 - Intimation Under Regulation 30 Of SEBI (Listing Obligations "
                       "And Disclosure Requirements) Regulations, 2015 - Reporting Of Cyber Fraud"),
    ("bse", "General", "Karnataka Bank Ltd - 532652 - Reporting Of Fraud To The RBI."),
    ("bse", "General", "Punjab & Sind Bank - 533295 - Reporting Of Borrowal Fraud Of Bank''s Exposure In M/S IL & FS "
                       "Tamil Nadu Power Company Limited"),
    ("bse", "General", "RBZ Jewellers Ltd - 544060 - Receipt Of Insurance Claim Amount In Relation To Earlier Reported Fraud."),
    ("bse", "General", "Muthoot Finance Ltd - 533398 - Clarification On Newspaper Reports Regarding Fraud Committed By Employees"),
    ("bse", "General", "Integra Essentia Ltd - 535958 - Intimation Regarding Fraudulent Activities On Telegram In The Name "
                       "Of Integra Essentia Limited"),
    ("bse", "General", "Indian Renewable Energy Development Agency Ltd - 544026 - Declaration Of Fraud To M/S Gensol "
                       "Engineering Limited"),
    ("bse", "Press Release / Media Release", "Company X - Press release on fraud detection product"),   # not General
    ("nse", "Awarding of order(s)/contract(s)", "A new Deal for the deployment of its HyperSense Fraud Management solutions"),
]
DEFAULT_YES = [
    ("bse", "Disclosures by listed entities of defaults on payment of interest/ repayment of principal amount for loans "
            "including revolving facilities like cash credit from banks / financial institutions.",
     "Kisan Mouldings Ltd - 530145 - Disclosures By Listed Entities Of Defaults On Payment Of Interest/ Repayment Of "
     "Principal Amount For Loans"),
    ("bse", "General", "Mahanagar Telephone Nigam Ltd - 500108 - Intimation Of Default In The Payment Of Principal "
                       "(Instalment) & Interest Of Banks By MTNL Dtd 05.09.2024"),
    ("bse", "General", "HLV Ltd - 500193 - Intimation Under Regulation 51(2) The SEBI (Listing Obligations And Disclosure "
                       "Requirements) Regulations, 2015 Regarding Default In Payment Of Quarterly Interest On Debentures"),
    ("nse", "General Updates", "INTIMATION OF DEFAULT IN THE PAYMENT OF PRINCIPAL (INSTALMENT) & INTEREST OF BANKS BY "
                               "MTNL AS ON30.09.2026"),
    ("nse", "Fraud/Default/Arrest", "SECUREKLOUD TECHNOLOGIES LIMITED has informed the Exchange about Default"),
]
DEFAULT_NO = [
    ("bse", "Quarterly Disclosures by listed entities of defaults on payment of interest/ repayment of principal amount "
            "on loans from banks / financial institutions and unlisted debt securities.",
     "Gail (India) Ltd - 532155 - Quarterly Disclosures By Listed Entities Of Defaults On Payment Of Interest"),
    ("bse", "General", "Bajaj Hindusthan Sugar Ltd - 500032 - Corrigendum To Disclosure Dated May 01, 2020 - No Defaults "
                       "On Payment Of Principal / Interest Amount On Loans From Banks"),
    ("bse", "General", "Cholamandalam Investment and Finance Company Ltd - 511243 - NIL Defaults On Payments - "
                       "Clarification From Company"),
    ("bse", "General", "Peninsula Land Ltd - 503031 - Clarification On Disclosure Of Defaults On Payment Of Interest/ "
                       "Repayment Of Principal Amount On Loans"),
    ("bse", "General", "Gayatri Projects Ltd - 532767 - Quarterly Disclosure Of Defaults On Payment Of Interest/Repayment "
                       "Of Principal Amount On Loans From Banks/Financial Institutions"),
    ("bse", "General", "Olympic Cards Ltd - 534190 - Announcement Under Regulation 30 (LODR)-Updates. Default Loan EMI "
                       "Amount Has Been Made Good In Respect Of Loan Lender"),
    ("bse", "General", "Shashijit Infraprojects Ltd - 540147 - Announcement Under Regulation 30 (LODR) - Intimation Of "
                       "Repayment Of Interest/ Repayment Of Principal Amount On Loans"),
    ("nse", "General Updates", "BGR Energy Systems Limited has informed the Exchange regarding -Disclosures by listed "
                               "company of defaults on payment of interest for the quarter ended on 30th September 2026"),
    ("nse", "Delay/default in the payment of fines/penalties/dues etc. to authority",
     "Arvee Laboratories (India) Limited has informed the Exchange about Delay/default in the payment of fines"),
]


def test_fraud_kind_matches_real_frauds_and_skips_victims_and_clarifications(conn):
    got = _kinds(conn, FRAUD_YES + FRAUD_NO)
    assert {t: k for (_, _, t), k in zip(FRAUD_YES, [got[r[2]] for r in FRAUD_YES]) if "fraud" not in k} == {}
    assert {t: got[t] for _, _, t in FRAUD_NO if got[t]} == {}


def test_default_kind_matches_defaults_and_skips_no_default_filings(conn):
    got = _kinds(conn, DEFAULT_YES + DEFAULT_NO)
    assert {t: got[t] for _, _, t in DEFAULT_YES if "default" not in got[t]} == {}
    assert {t: got[t] for _, _, t in DEFAULT_NO if got[t]} == {}


def test_kind_dedupe_and_window(conn):
    _bse(conn, "b1", "S", "Updates - Corporate Insolvency Resolution Process  (CIRP)", "2026-10-11T10:00:00")
    _nse(conn, "n1", "S", "Corporate Insolvency Resolution Process", "x", "2026-10-12 10:00:00")   # copy: same kind, 1 day
    _bse(conn, "b2", "T", "Initiation of Corporate Insolvency Resolution Process (CIRP) by Financial Creditors",
         "2026-10-11T10:00:00")
    _nse(conn, "n2", "T", "Corporate Insolvency Resolution Process", "x", "2026-10-12 10:00:00")   # other subcat, same kind
    ev = A.events({"cirp": FLAGS["cirp"]}, conn, since="2026-10-10", until="2026-10-19")
    assert sorted(zip(ev["sid"], ev["source"])) == [("S", "bse_announcements"), ("T", "bse_announcements")]
    assert A.events({"cirp": FLAGS["cirp"]}, conn, since="2026-10-11").empty      # since is exclusive


def test_kind_spec_rejects_unknown_columns():
    with pytest.raises(ValueError):
        A.kind_sql({"match": [{"desc_category": ["x"]}]})
