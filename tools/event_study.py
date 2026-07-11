"""
Alpha Signal v2 — tools/event_study.py — generalized event-time CAR framework (WS4.2, plan 0013 A1).

Generalizes signals/announcement_car.py's wired [-1,+1] earnings-CAR machinery
(`_car_one` + `_nifty_asof`) to arbitrary (pre, post) trading-day windows over an
arbitrary event set (not just 'Result' announcements), plus a cross-sectional
aggregator with a t-stat and a multi-window drift curve. Read-only — event
studies produce EVIDENCE (drift curves + t-stats), not production signals; no
weight in `config.SIGNAL_WEIGHTS` is touched by this module or its callers.

`_nifty_asof` is imported directly from signals.announcement_car (identical
logic, no reason to duplicate). `_car_one`'s CAR math is mirrored here — not
imported — because that module hardcodes its window as CAR_PRE=1/CAR_POST=1
module constants; `_event_car_one` below is the same algorithm parameterized
on (pre, post) so callers can study any window.

Usage:
    from tools.event_study import event_car, car_summary, drift_curve
    python -m tools.event_study     # VERIFY: reproduces compute_announcement_car() at (1,1)
"""
from __future__ import annotations

import bisect
from datetime import date

import numpy as np
import pandas as pd

from signals.announcement_car import NIFTY_ID, _nifty_asof

CAR_CLIP = (-0.5, 0.5)   # a multi-day abnormal return beyond ±50% is almost always a data error


def _event_car_one(pdates, pcloses, n_dates, n_vals, event_iso, eval_iso, pre, post):
    """Market-adjusted [-pre,+post] CAR around one event. NaN if not measurable.

    day0 = first price row with date >= event_iso. Requires the window's END
    close to exist AND its date <= eval_iso (look-ahead guard). Mirrors
    signals.announcement_car._car_one exactly, parameterized on (pre, post).
    """
    i0 = bisect.bisect_left(pdates, event_iso)
    if i0 >= len(pdates):
        return np.nan
    start, end = i0 - pre, i0 + post
    if start < 0 or end >= len(pdates):
        return np.nan
    d_start, d_end = pdates[start], pdates[end]
    if d_end > eval_iso:                      # window not fully closed by eval → look-ahead guard
        return np.nan
    p0, p1 = pcloses[start], pcloses[end]
    if not (p0 > 0 and p1 > 0):
        return np.nan
    n0 = _nifty_asof(n_dates, n_vals, d_start)
    n1 = _nifty_asof(n_dates, n_vals, d_end)
    if n0 is None or n1 is None or n0 <= 0:
        return np.nan
    return float((p1 / p0 - 1.0) - (n1 / n0 - 1.0))


def event_car(events_df: pd.DataFrame, prices: pd.DataFrame, nifty: pd.DataFrame,
              pre: int, post: int, as_of: str | None = None) -> pd.DataFrame:
    """One market-adjusted CAR per (sid, event) over trading-day window [-pre,+post].

    events_df: DataFrame[sid, event_date]. prices: DataFrame[sid, date, close(+adj_close)]
    (uses adj_close when present — split/bonus-safe, same rule as announcement_car).
    nifty: DataFrame[date, value] for indicator nifty50. day0 = first price row
    with date >= event_date. NaN when the window isn't fully closed by `as_of`
    (the same look-ahead guard as signals.announcement_car).
    """
    cols = ["sid", "event_date", "car"]
    eval_iso = as_of or date.today().isoformat()
    if (events_df is None or len(events_df) == 0 or prices is None or len(prices) == 0
            or nifty is None or len(nifty) == 0):
        return pd.DataFrame(columns=cols)

    ev = events_df[["sid", "event_date"]].dropna().copy()
    ev["event_date"] = ev["event_date"].astype(str).str.slice(0, 10)
    ev = ev[ev["event_date"] <= eval_iso]
    if len(ev) == 0:
        return pd.DataFrame(columns=cols)

    nf = nifty.dropna(subset=["value"]).sort_values("date")
    n_dates = nf["date"].astype(str).to_numpy()
    n_vals = nf["value"].astype(float).to_numpy()
    price_col = "adj_close" if "adj_close" in prices.columns else "close"

    px_by_sid = {}
    for sid, g in prices.groupby("sid", sort=False):
        g = g.sort_values("date")
        px_by_sid[sid] = (g["date"].astype(str).to_numpy(), g[price_col].astype(float).to_numpy())

    rows = []
    for sid, event_date in ev[["sid", "event_date"]].itertuples(index=False):
        pd_arrs = px_by_sid.get(sid)
        if pd_arrs is None:
            continue
        pdates, pcloses = pd_arrs
        car = _event_car_one(pdates, pcloses, n_dates, n_vals, event_date, eval_iso, pre, post)
        if car is not None and not np.isnan(car):
            rows.append({"sid": sid, "event_date": event_date,
                         "car": round(float(np.clip(car, *CAR_CLIP)), 4)})
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


def car_summary(car_df: pd.DataFrame) -> dict:
    """n, mean CAR, std, t-stat (mean/(std/sqrt(n))), median, hit-rate(>0)."""
    s = car_df["car"].dropna() if car_df is not None and len(car_df) else pd.Series(dtype=float)
    n = len(s)
    if n == 0:
        return {"n": 0, "mean": np.nan, "std": np.nan, "t": np.nan,
                "median": np.nan, "hit_rate": np.nan}
    mean = float(s.mean())
    std = float(s.std(ddof=1)) if n > 1 else 0.0
    t = float(mean / (std / np.sqrt(n))) if std > 0 else np.nan
    return {"n": n, "mean": mean, "std": std, "t": t,
            "median": float(s.median()), "hit_rate": float((s > 0).mean())}


def drift_curve(events_df: pd.DataFrame, prices: pd.DataFrame, nifty: pd.DataFrame,
                 windows: list[tuple[int, int]], as_of: str | None = None) -> pd.DataFrame:
    """One car_summary row per (pre, post) window in `windows`."""
    rows = []
    for pre, post in windows:
        car_df = event_car(events_df, prices, nifty, pre, post, as_of=as_of)
        rows.append({"pre": pre, "post": post, **car_summary(car_df)})
    return pd.DataFrame(rows)


def _verify_against_announcement_car(n_check: int = 20) -> bool:
    """DECIDED acceptance test (plan 0013 A1): event_car at (1,1) over the
    category='Result' announcement set must reproduce compute_announcement_car()'s
    values for sids with a non-NaN reading today. Prints PASS/FAIL count."""
    from db import read_sql
    from signals.announcement_car import compute_announcement_car

    eval_iso = date.today().isoformat()
    ref = compute_announcement_car(as_of_date=eval_iso)
    if len(ref) == 0:
        print("VERIFY: no announcement_car readings today — cannot check. SKIP.")
        return True
    check_sids = ref["sid"].tolist()[:n_check]

    announcements = read_sql(
        "SELECT sid, date(dt_tm) AS event_date FROM bse_announcements "
        "WHERE category='Result' AND sid IS NOT NULL AND dt_tm IS NOT NULL "
        f"AND sid IN ({','.join('?' * len(check_sids))}) ORDER BY sid, dt_tm",
        tuple(check_sids))
    prices = read_sql(
        "SELECT sid, date, close FROM stock_prices WHERE close > 0 "
        f"AND sid IN ({','.join('?' * len(check_sids))}) ORDER BY sid, date",
        tuple(check_sids))
    nifty = read_sql(
        f"SELECT date, value FROM macro_history WHERE indicator_id='{NIFTY_ID}' AND value > 0 "
        "ORDER BY date")

    car_df = event_car(announcements, prices, nifty, pre=1, post=1, as_of=eval_iso)
    latest = car_df.sort_values("event_date").groupby("sid", as_index=False).last()
    latest_by_sid = dict(zip(latest["sid"], latest["car"]))

    ok, misses = 0, []
    for sid, ref_val in zip(ref["sid"].tolist()[:n_check], ref["announcement_car"].tolist()[:n_check]):
        got = latest_by_sid.get(sid)
        if got is not None and abs(got - ref_val) < 1e-6:
            ok += 1
        else:
            misses.append((sid, ref_val, got))
    print(f"VERIFY event_car(1,1) vs compute_announcement_car(): {ok}/{len(check_sids)} PASS")
    for sid, ref_val, got in misses:
        print(f"  MISS sid={sid} ref={ref_val} got={got}")
    return ok == len(check_sids)


if __name__ == "__main__":
    _verify_against_announcement_car()
