"""Macro force direction comes from the macro indicators, not the Regulatory event count."""
import json

import pandas as pd

from signals import sector_forces as sf


def _force(monkeypatch, drivers, score):
    df = pd.DataFrame([{"sector": "S", "macro_score": score, "macro_drivers": json.dumps(drivers)}])
    monkeypatch.setattr(sf, "read_sql", lambda *a, **k: df)
    return sf._macro_force("2026-10-10")["S"]


REG = {"driver": "Regulatory", "value": 1309.0, "unit": "", "direction": "+", "raw": "NEUTRAL (1309 events)"}


def test_regulatory_count_does_not_make_a_headwind_sector_positive(monkeypatch):
    d = [{"driver": "crude", "value": -3.6, "unit": "%", "direction": "-", "raw": "-3.6% YoY"},
         {"driver": "gas", "value": -4.9, "unit": "%", "direction": "-", "raw": "-4.9% YoY"},
         {"driver": "refinery", "value": 2.6, "unit": "%", "direction": "+", "raw": "+2.6% YoY"}, REG]
    assert _force(monkeypatch, d, 41.7)["direction"] == "-"


def test_only_regulatory_driver_is_neutral(monkeypatch):
    assert _force(monkeypatch, [REG], None)["direction"] == "neutral"
