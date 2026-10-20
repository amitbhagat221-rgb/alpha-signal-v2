"""signals/macro.py (the live Sectors macro read) is pit.pit_macro_sector in display form.

Regression for 2026-09-28 → 10-20: Financials, Information Technology and Communication
Services had macro_signal UNKNOWN with a NULL score. The live step was a second model
(monthly official labels via a hard-coded map) whose only inputs for those sectors were
GST and credit growth, which have no feed; the PIT twin, from macro_sector_map, still
scored them.
"""
from datetime import date

import pandas as pd
import pytest

from pit import pit_macro_sector
from signals import macro

AS_OF = date(2026, 10, 20)
SECTORS = ["Communication Services", "Financials", "Information Technology", "Utilities"]


def _hist():
    rows = []
    for ind, prior, latest in [("bank_nifty", 100.0, 104.0), ("us_10y", 4.0, 4.4),
                               ("nifty_it", 100.0, 103.0), ("nifty_media", 100.0, 98.0)]:
        rows += [{"indicator_id": ind, "date": "2026-07-20", "value": prior},     # ~90 days back
                 {"indicator_id": ind, "date": "2026-10-19", "value": latest},
                 {"indicator_id": ind, "date": "2026-10-25", "value": 1.0}]       # after as_of: never read
    return pd.DataFrame(rows)


MAP = pd.DataFrame([
    {"indicator_id": "bank_nifty", "sector": "Financials", "direction": 1, "weight": 1.0},
    {"indicator_id": "us_10y", "sector": "Financials", "direction": -1, "weight": 1.5},
    {"indicator_id": "us_10y", "sector": "Information Technology", "direction": -1, "weight": 1.5},
    {"indicator_id": "nifty_it", "sector": "Information Technology", "direction": 1, "weight": 1.0},
    {"indicator_id": "nifty_media", "sector": "Communication Services", "direction": 1, "weight": 1.0},
    {"indicator_id": "india_vix", "sector": "Utilities", "direction": 1, "weight": 0.5},   # no history
])


def test_live_read_is_the_pit_engine():
    live = macro.sector_reads(_hist(), MAP, SECTORS, AS_OF).set_index("sector")
    pit = {r["sector"]: r["macro_score"] for r in pit_macro_sector(_hist(), MAP, SECTORS, AS_OF)}
    for s in ["Communication Services", "Financials", "Information Technology"]:
        assert live.loc[s, "macro_score"] == macro.display_score(pit[s])
        assert live.loc[s, "macro_signal"] == macro._sector_signal(live.loc[s, "macro_score"])
        assert live.loc[s, "macro_signal"] != "UNKNOWN"
    # Financials: bank_nifty +4% (×1) and us_10y +10% (×−1.5) → mean −5.5 → −0.55 → 44.5
    assert pit["Financials"] == -0.55
    assert live.loc["Financials", "macro_score"] == 44.5
    assert live.loc["Financials", "macro_signal"] == "HEADWIND"
    # the drivers say the raw move and what it means for the sector, largest effect first
    assert live.loc["Financials", "macro_detail"] == \
        "us_10y: +10.0% in 90d (headwind) | bank_nifty: +4.0% in 90d (tailwind)"


def test_sector_without_a_move_is_left_out_and_reported(monkeypatch):
    monkeypatch.setattr(macro, "read_sql", lambda q, *a, **k: (
        pd.DataFrame({"sector": SECTORS}) if "FROM stocks" in q
        else MAP if "macro_sector_map" in q else _hist()))
    failed = []
    monkeypatch.setattr(macro.runlog, "item_failed", lambda label, item, msg, **k: failed.append(item))
    written = {}

    def upsert(df, table, **k):
        written[table] = df
        return len(df)
    monkeypatch.setattr(macro, "upsert_df", upsert)
    assert macro.compute(as_of=AS_OF) == 3
    assert failed == ["Utilities"]
    df = written["macro_sector_signals"]
    assert set(df["sector"]) == {"Communication Services", "Financials", "Information Technology"}
    assert (df["snapshot_date"] == "2026-10-20").all() and df["macro_score"].notna().all()


def test_no_sector_scored_raises(monkeypatch):
    monkeypatch.setattr(macro, "read_sql", lambda q, *a, **k: (
        pd.DataFrame({"sector": SECTORS}) if "FROM stocks" in q
        else MAP if "macro_sector_map" in q else _hist().iloc[0:0]))
    with pytest.raises(RuntimeError, match="no sector scored"):
        macro.compute(dry_run=True, as_of=AS_OF)


def test_display_scale_is_clipped():
    assert macro.display_score(0) == 50.0
    assert macro.display_score(0.5) == 55.0 and macro._sector_signal(55.0) == "FAVORABLE"
    assert macro.display_score(9) == 100.0 and macro.display_score(-9) == 0.0
