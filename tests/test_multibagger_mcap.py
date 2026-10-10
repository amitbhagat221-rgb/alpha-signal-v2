"""The multibagger market-cap gate reads the one market cap, not the stocks column."""
import pandas as pd

from signals import multibagger as mb


def test_universe_mcap_comes_from_market_caps(monkeypatch):
    stocks = pd.DataFrame({"sid": ["A", "B", "C"], "name": "n", "sector": "s", "cap_tier": "SMALL",
                           "market_cap_cr": [1.0, 1.0, 1.0]})
    monkeypatch.setattr(mb, "read_sql", lambda *a, **k: stocks[["sid", "name", "sector", "cap_tier"]])
    monkeypatch.setattr(mb, "market_caps", lambda: pd.DataFrame({"sid": ["A", "B"], "mcap_cr": [19328.0, 4787.0]}))
    u = mb._load_universe().set_index("sid")
    assert u.loc["A", "mcap_cr"] == 19328.0 and pd.isna(u.loc["C", "mcap_cr"])


def test_too_few_market_caps_raises(monkeypatch):
    stocks = pd.DataFrame({"sid": list("ABCD"), "name": "n", "sector": "s", "cap_tier": "SMALL"})
    monkeypatch.setattr(mb, "read_sql", lambda *a, **k: stocks)
    monkeypatch.setattr(mb, "market_caps", lambda: pd.DataFrame({"sid": ["A"], "mcap_cr": [1.0]}))
    try:
        mb._load_universe()
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError")
