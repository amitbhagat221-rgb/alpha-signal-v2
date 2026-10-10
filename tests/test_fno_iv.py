"""IV rollup (sources.fno_iv): a thin expiry at the 30-day target must not drop the day."""

from datetime import date

import pandas as pd

from sources import fno_iv

DAY = "2020-07-22"
F, SIG = 11100.0, 0.22


def _chain(expiry, strikes):
    T = (date.fromisoformat(expiry) - date.fromisoformat(DAY)).days / 365.0
    rows = []
    for K in strikes:
        for cp, ot in (("C", "CE"), ("P", "PE")):
            rows.append({"sid": None, "symbol": "NIFTY", "expiry_date": expiry, "strike": float(K),
                         "option_type": ot, "underlying_price": F,
                         "settle": round(fno_iv._black76(F, K, T, SIG, cp), 2)})
    return rows


def test_thin_target_expiry_falls_back_to_the_next_closest():
    thin = _chain("2020-08-20", [10500])                                       # 29 days, one strike
    liquid = _chain("2020-08-27", range(10600, 11700, 100))                    # 36 days, liquid
    near = _chain("2020-07-30", range(10600, 11700, 100))                      # 8 days (term structure)
    roll = fno_iv._rollup_iv_one(pd.DataFrame(thin + liquid + near), DAY)
    assert roll is not None and roll["target_expiry"] == "2020-08-27"
    assert abs(roll["atm_iv"] - SIG) < 0.01


def test_no_invertible_expiry_still_gives_none():
    assert fno_iv._rollup_iv_one(pd.DataFrame(_chain("2020-08-20", [10500])), DAY) is None
