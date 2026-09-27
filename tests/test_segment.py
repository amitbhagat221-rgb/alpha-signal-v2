"""scoring/segment.py — market-cap rank tiers from config.TIERS, with hysteresis
(plan 0015 D3). Pure assign() tests; no DB."""
import pandas as pd

import config
from scoring import segment


def _caps(n, corroborated=True):
    # sid s1 is the largest; mcap strictly decreasing with the index
    return pd.DataFrame({"sid": [f"s{i}" for i in range(1, n + 1)],
                         "mcap_cr": [float(10 * n - i) for i in range(1, n + 1)],
                         "corroborated": corroborated})


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
    caps.loc[caps.sid == "s50", "corroborated"] = False            # unconfirmed share count
    current = {s: None for s in caps.sid}
    current.update({"s300": "MICRO", "s200": "MICRO", "s50": "SMALL", "ghost": "MID"})
    new = segment.assign(caps, current, h=0.10)
    assert new["s300"] == "MICRO"          # stays carved (classify_micro_tier owns MICRO<->SMALL)
    assert new["s200"] == "MID"            # ranks into MID -> leaves MICRO
    assert new["s50"] == "SMALL"           # uncorroborated: neither ranked nor moved
    assert new["ghost"] == "MID"           # no market cap: kept
    assert new["s49"] == "LARGE" and new["s51"] == "LARGE"


def test_transitions_counts_moves():
    assert segment.transitions({"a": "MID", "b": "SMALL", "c": "LARGE"},
                               pd.Series({"a": "LARGE", "b": "SMALL", "c": "MID"})) == \
        {("MID", "LARGE"): 1, ("LARGE", "MID"): 1}
