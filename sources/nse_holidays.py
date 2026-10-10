"""
Alpha Signal v2 — NSE trading-holiday list (plan 0022).

The option paper book places its entry day "2 trading sessions before expiry", which
needs the exchange's holiday list ahead of time (a bhavcopy 404 only says so after).
NSE publishes the current year's list per segment at /api/holiday-master?type=trading
(read through nselib, paced by the host door). BSE index derivatives close on the same
exchange holidays.

Writes market_holidays (segment, holiday_date, description) — INSERT OR IGNORE, so past
years accumulate. Raises when the list comes back without F&O rows.

Usage:
    python -m sources.nse_holidays
"""

import pandas as pd

from db import insert_df
from sources import _http

SEGMENTS = {"Equity Derivatives": "FO", "Equities": "CM"}


def fetch():
    from nselib.libutil import trading_holiday_calendar
    with _http.pace("nse"):
        df = trading_holiday_calendar()
    df = df[df["Product"].isin(SEGMENTS)]
    out = pd.DataFrame({
        "segment": df["Product"].map(SEGMENTS),
        "holiday_date": pd.to_datetime(df["tradingDate"], format="%d-%b-%Y").dt.date.astype(str),
        "description": df["description"].astype(str).str.strip(),
    })
    if (out["segment"] == "FO").sum() == 0:
        raise RuntimeError("NSE holiday list has no Equity Derivatives rows — endpoint changed?")
    return out


def main():
    out = fetch()
    n = insert_df(out, "market_holidays")
    print(f"market_holidays: {len(out)} rows fetched ({(out.segment == 'FO').sum()} F&O), {n} new")


if __name__ == "__main__":
    main()
