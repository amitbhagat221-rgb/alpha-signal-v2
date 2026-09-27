"""sources.macro_official — MoSPI/OEA parsing and the macro_indicators labels (offline)."""
from datetime import date

import pandas as pd

from sources import macro_official as mo


def test_core_sheet_reads_months_and_skips_fy_summaries():
    df = pd.DataFrame([
        ["Index: Overall", None, None, None],
        ["Months/Years", "Overall Index", "Coal", "Fertilizers"],
        ["Apr-23", 103.6, 98.6, 94.9],
        ["May-23", 108.3, 102.7, 110.5],
        ["2024-25(Apr-Mar)", 111.7, 117.2, 106.7],
    ])
    assert mo._core_sheet(df) == {
        "core_combined": {"2023-04-01": 103.6, "2023-05-01": 108.3},
        "core_coal": {"2023-04-01": 98.6, "2023-05-01": 102.7},
        "core_fertilizers": {"2023-04-01": 94.9, "2023-05-01": 110.5},
    }


def test_iip_names_map_to_the_ids_the_sector_map_uses():
    assert mo._iip_id("Mining & Quarrying") == "iip_mining"
    assert mo._iip_id("Electricity, Gas, Steam and Air Conditioning Supply") == "iip_electricity"
    assert mo._iip_id("Capital Goods") == "iip_capital_goods"
    assert mo._iip_id("Consumer Non-durables") == "iip_consumer_nondurables"


def test_labels_use_v1_thresholds_and_drop_stale_or_foreign_series():
    latest = {"core_cement": ("2026-08-01", 12.5), "core_steel": ("2026-08-01", 3.4),
              "iip_mining": ("2026-07-01", -0.9), "core_coal": ("2026-08-01", -3.8),
              "iip_general": ("2025-01-01", 9.0),          # stale → no label
              "cpi_general": ("2026-08-01", 4.8)}          # CPI is not labelled
    rows = {r["indicator"]: r for r in mo.build_labels(latest, date(2026, 9, 27))}
    assert {k: v["signal"] for k, v in rows.items() if k != "macro_overall"} == {
        "core_cement": "STRONG", "core_steel": "IMPROVING", "iip_mining": "STABLE",
        "core_coal": "DETERIORATING"}
    assert rows["macro_overall"]["value"] == 0.5 and rows["macro_overall"]["signal"] == "EXPANDING"
    assert rows["core_cement"]["detail"] == "core_cement: +12.5% YoY (Aug 2026)"
    assert all(r["snapshot_date"] == "2026-09-27" for r in rows.values())


def test_cpi_stops_at_the_first_unreleased_month(monkeypatch):
    calls = []

    def fake(sess, path, **p):
        calls.append((p["year"], p["month_code"]))
        if (p["year"], p["month_code"]) == ("2026", "9"):
            return {"data": []}
        return {"data": [{"division": "CPI (General)", "group": None, "index": "108.7", "inflation": "4.82"},
                         {"division": "Food and beverages", "group": "Food", "index": "110.7", "inflation": "5.9"}]}

    monkeypatch.setattr(mo, "_mospi", fake)
    monkeypatch.setattr(mo, "date", type("D", (date,), {"today": classmethod(lambda c: date(2026, 9, 27))}))
    rows = mo.fetch_cpi(None, (2026, 8))
    assert calls == [("2026", "8"), ("2026", "9")]
    assert [(r["indicator_id"], r["date"], r["yoy_change"]) for r in rows] == [("cpi_general", "2026-08-01", 4.82)]
