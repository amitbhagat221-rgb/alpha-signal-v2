"""NSE corporate announcements (plan 0026 task 4.0): category map covers the probed descs,
rows map to the right columns, the feed is registered, and the table is declared."""
import config
import feeds
import tables
from sources import nse_announcements as na

# Top descs of the 2026-10-13..14 probe (1,058 rows) plus the 2018-01 probe: every one must be a decision.
PROBE_DESCS = [
    "Certificate under SEBI (Depositories and Participants) Regulations, 2018", "General Updates",
    "Analysts/Institutional Investor Meet/Con. Call Updates", "Updates", "Copy of Newspaper Publication",
    "Outcome of Board Meeting", "Press Release", "Resignation of Director/KMP/SMP", "Shareholders meeting",
    "Resignation", "Appointment", "Investor Presentation", "Acquisition", "Credit Rating", "Spurt in Volume",
    "Bagging/Receiving of orders/contracts", "Action(s) taken or orders passed", "ESOP/ESOS/ESPS",
    "Corporate Insolvency Resolution Process", "Change in Management", "Price movement",
    "Allotment of Securities", "Pendency of Litigation(s)/dispute(s) or the outcome impacting the Company",
    "Cessation", "Structural Digital Database", "Record Date", "Change in Director(s)", "Dividend",
    "News Verification", "Trading Window", "Credit Rating- Revision", "Issue of Securities",
    "Credit Rating- New", "Monitoring Agency Report", "Others", "Corrigendum",
    "Change in Company Secretary/Compliance Officer", "Rumour Verification - Regulation 30(11)",
    "Sale or disposal", "Preferential issue", "Raising of Funds", "Change in Auditors", "Open Offer",
]


def _decided(desc):
    d = desc.lower()
    return (d in config.NSE_ANNOUNCEMENT_CATEGORIES or d in config.NSE_ANNOUNCEMENT_OTHER_DESCS
            or d in config.NSE_ANNOUNCEMENT_GENERIC_DESCS)


def test_every_probed_desc_has_a_decision():
    assert [d for d in PROBE_DESCS if not _decided(d)] == []


def test_categories_are_the_watch_set():
    allowed = {"results", "order_win", "acquisition", "funding", "credit_rating", "management_change",
               "auditor_resignation", "insolvency", "shareholding_sast", "pledge", "clarification", "other"}
    assert set(config.NSE_ANNOUNCEMENT_CATEGORIES.values()) <= allowed
    assert {c for _, c in config.NSE_ANNOUNCEMENT_TEXT_RULES} <= allowed


def test_categorize_by_desc_and_by_text():
    assert na.categorize("Bagging/Receiving of orders/contracts", "") == "order_win"
    assert na.categorize("Credit Rating- Revision", "") == "credit_rating"
    assert na.categorize("Certificate under SEBI (Depositories and Participants) Regulations, 2018", "x") == "other"
    assert na.categorize("Updates", "X has received an order worth Rs 50 crore") == "order_win"
    assert na.categorize("Updates", "Allotment of equity shares on exercise of warrants") == "funding"
    assert na.categorize("General Updates", "Reconstitution of committees") == "other"
    assert na.categorize("Brand New Desc", "has received an order") == "other"   # unknown desc never guessed


def test_to_records_maps_columns_and_sid():
    raw = [{"seq_id": "1", "symbol": "acme", "sm_isin": "INE1", "desc": "Acquisition", "attchmntText": " t ",
            "an_dt": "14-Oct-2026 23:40:23", "exchdisstime": "14-Oct-2026 23:40:24", "attchmntFile": "u"},
           {"seq_id": "2", "symbol": "ZZZ", "sm_isin": "INE9", "desc": "Updates", "attchmntText": None,
            "an_dt": "03-Jan-2018 23:05:00", "exchdisstime": "-", "attchmntFile": None},
           {"seq_id": "", "an_dt": "14-Oct-2026 23:40:23"}]          # no id -> dropped
    r = na.to_records(raw, {"INE1": "SID1"}, {"ZZZ": "SID2"}, "now")
    assert [x["seq_id"] for x in r] == ["1", "2"]
    assert r[0]["sid"] == "SID1" and r[0]["category"] == "acquisition" and r[0]["an_dt"] == "2026-10-14 23:40:23"
    assert r[0]["dissem_dt"] == "2026-10-14 23:40:24" and r[0]["subject"] == "t"
    assert r[1]["sid"] == "SID2" and r[1]["dissem_dt"] is None and r[1]["attachment_url"] is None
    assert set(r[0]) == set(na.COLS)


def test_chunks_cover_range_newest_first():
    from datetime import date
    w = list(na._chunks(date(2026, 10, 1), date(2026, 10, 7), 3))
    assert w == [(date(2026, 10, 5), date(2026, 10, 7)), (date(2026, 10, 2), date(2026, 10, 4)),
                 (date(2026, 10, 1), date(2026, 10, 1))]


def test_registered_feed_and_table():
    f = feeds.FEEDS["nse_announcements"]
    assert f["writes"] == ["nse_announcements"] and f["modules"] == ["sources.nse_announcements"]
    assert tables.TABLES["nse_announcements"]["kind"] == "RAW"
    assert "bse_announcements" not in f["writes"]
    schema = open(config.PROJECT_ROOT / "schema.sql").read() if hasattr(config, "PROJECT_ROOT") else None
    if schema:
        assert "CREATE TABLE IF NOT EXISTS nse_announcements" in schema
