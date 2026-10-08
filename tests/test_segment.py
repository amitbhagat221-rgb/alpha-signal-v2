"""scoring/segment.py — market-cap rank tiers from config.TIERS, with hysteresis
(plan 0015 D3). Pure assign() tests; no DB."""
import pandas as pd

import config
from scoring import segment


def _caps(n):
    # sid s1 is the largest; mcap strictly decreasing with the index
    return pd.DataFrame({"sid": [f"s{i}" for i in range(1, n + 1)],
                         "mcap_cr": [float(10 * n - i) for i in range(1, n + 1)]})


def test_rank_tiers_come_from_config():
    bands = segment._rank_tiers()
    assert [b[0] for b in bands] == [t for t, s in config.TIERS.items() if "rank_max" in s]
    assert bands[0][1:] == (0, 100) and bands[1][1:] == (100, 250) and bands[2][2] == float("inf")
    # the carve-out tier is not rank-assigned
    assert all(s.get("carve_from") for t, s in config.TIERS.items() if "rank_max" not in s)


def test_strict_assignment_without_hysteresis():
    caps = _caps(400)
    new = segment.assign(caps, {s: None for s in caps.sid}, h=0.0)
    assert (new[[f"s{i}" for i in range(1, 101)]] == "LARGE").all()
    assert (new[[f"s{i}" for i in range(101, 251)]] == "MID").all()
    assert (new[[f"s{i}" for i in range(251, 401)]] == "SMALL").all()


def test_hysteresis_band_keeps_incumbents_and_gates_entrants():
    caps = _caps(400)
    current = {s: None for s in caps.sid}
    current.update({"s105": "LARGE", "s112": "LARGE",    # LARGE incumbent inside / outside 110
                    "s95": "MID", "s89": "MID",          # MID incumbent inside / above the 90 bar
                    "s270": "MID", "s280": "MID",        # MID incumbent inside / outside 275
                    "s230": "SMALL", "s220": "SMALL"})   # SMALL entrant must clear 225
    new = segment.assign(caps, current, h=0.10)
    assert new["s105"] == "LARGE" and new["s112"] == "MID"
    assert new["s95"] == "MID" and new["s89"] == "LARGE"
    assert new["s270"] == "MID" and new["s280"] == "SMALL"
    assert new["s230"] == "SMALL" and new["s220"] == "MID"


def test_micro_is_a_small_incumbent_and_unknown_caps_keep_their_tier():
    caps = _caps(400)
    current = {s: None for s in caps.sid}
    current.update({"s300": "MICRO", "s200": "MICRO", "ghost": "MID"})
    new = segment.assign(caps, current, h=0.10)
    assert new["s300"] == "MICRO"          # stays carved (classify_micro_tier owns MICRO<->SMALL)
    assert new["s200"] == "MID"            # ranks into MID -> leaves MICRO
    assert new["ghost"] == "MID"           # no market cap: kept


def test_carve_needs_illiquid_and_small_or_short_history():
    tiers = pd.Series({"a": "SMALL", "b": "SMALL", "c": "SMALL", "d": "SMALL", "e": "MID"})
    ti = pd.DataFrame({"sid": list("abcde"),
                       "mcap_cr": [300.0, 300.0, 2000.0, 2000.0, 300.0],
                       "adtv_cr": [0.5, 3.0, 0.5, 0.5, 0.1],
                       "quarters": [8, 8, 8, 2, 8]})
    out = segment.carve(tiers, ti)
    assert out["a"] == "MICRO"             # illiquid and small
    assert out["b"] == "SMALL"             # small but liquid
    assert out["c"] == "SMALL"             # illiquid but large with history
    assert out["d"] == "MICRO"             # illiquid with too few statements
    assert out["e"] == "MID"               # only the carve-from tier is carved


def test_market_cap_is_close_times_shares_on_one_basis():
    """KDDL: both vendors carried 1,744 Cr shares for FY26 against 1.25 Cr the year before
    (no corporate action); the market cap must use the statement count, not 1,400x it."""
    from signals._fundamentals import market_caps
    bs = pd.DataFrame({"sid": ["K", "K"], "end_date": ["2025-03-31", "2026-03-31"],
                       "shares_outstanding": [0.1247, 174.4], "total_equity": [900.0, 1000.0]})
    fund = pd.DataFrame({"sid": ["K"] * 4, "period_end": ["2026-03-31"] * 4,
                         "line_item": ["Equity Share Capital", "Reserves", "Face value", "No. of Equity Shares"],
                         "value": [12.5, 990.0, 10.0, 12_470_000.0]})
    adj = pd.DataFrame(columns=["sid", "ex_date", "factor", "inds"])
    mc = market_caps(bs, fund, adj, pd.DataFrame({"sid": ["K"], "close_price": [4000.0]}), "2026-10-08")
    assert abs(mc.loc[0, "mcap_cr"] - 4000.0 * 12_470_000 / 1e7) < 1


def test_transitions_counts_moves():
    assert segment.transitions({"a": "MID", "b": "SMALL", "c": "LARGE"},
                               pd.Series({"a": "LARGE", "b": "SMALL", "c": "MID"})) == \
        {("MID", "LARGE"): 1, ("LARGE", "MID"): 1}
