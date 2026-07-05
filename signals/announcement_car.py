"""
Alpha Signal v2 — Announcement-window CAR (market-implied earnings surprise) — Plan 0002 §3.2.5.

`announcement_car` — the cumulative abnormal return in a tight event window AROUND
each earnings/result announcement, used as a MARKET-IMPLIED surprise proxy, then
tested for whether it predicts post-earnings-announcement drift (PEAD).

Why this and not a SUE: `signals/pead.py`'s seasonal-random-walk SUE and
`pead_drift_60d` both DROP even with real BSE announcement dates
(memory: pead_needs_announce_dates). The binding constraint was never the date —
it was the SURPRISE numerator (we have no PIT quarterly analyst-consensus EPS).
The market's own immediate price reaction to the print IS a real-time surprise
proxy that needs no consensus: a big positive CAR = the print beat the market's
priced-in expectation. PEAD says that beat keeps drifting for weeks.

Construction (per sid, as of eval_date):
  - Announcement dates: `bse_announcements`, category='Result', real `dt_tm`,
    sid-joined (the exact ~85%-coverage stream the PEAD work established). Only
    dt_tm ≤ eval_date is visible (look-ahead safe; reuses pead._announce_dates_by_sid).
  - Pick the MOST RECENT qualifying announcement: dt_tm within STALE_DAYS calendar
    days of eval_date AND whose event window has fully closed on/before eval_date.
    If the newest print's window hasn't closed yet, fall back to the prior one
    (which is then usually > STALE_DAYS old → NULL). NULL when no qualifying
    recent announcement — a missing print is "no reading", NOT a 0 (0 CAR would
    assert a specific neutral-surprise, which we don't know).
  - CAR = stock return − NIFTY-50 return over the [−1, +1] trading-day window:
    day0 = first trading day on/after the announcement date; buy at the close of
    day0−1 (last pre-print close), measure to the close of day0+1. Market-adjusted
    with NIFTY-50 (the same benchmark `signals/pead.py` uses, already in-DB), which
    is essential because each stock's window sits on its own idiosyncratic dates —
    NIFTY removes the common market move over that stock's specific 3 days.

Expected sign: POSITIVE (high announcement CAR → continued positive drift). The
backtest decides — record the observed sign, don't force it.

Staleness rule: STALE_DAYS = 90 (one reporting quarter). Earnings are quarterly,
so this always picks up the latest quarter's reaction and gives ~full reporter
coverage each monthly anchor; a print older than a quarter is superseded / the
stock simply hasn't reported recently → NULL. Drift is front-loaded in the first
~60 trading days, so a monthly anchor + 20d response samples the live-drift window
on average. (A tighter gate or an exponential decay weight would concentrate the
drift further — deferred; the hard 90d cutoff is the interpretable v1.)

Look-ahead-safe: only dt_tm ≤ eval_date announcements, only prices whose window
END date ≤ eval_date. Injectable frames so the live path and the PIT path
(tools/reconstruct_pit.py:pit_announcement_car) run identical logic. Uses
`adj_close` when present (PIT path passes split/bonus-adjusted closes; a split
inside the 3-day window would otherwise manufacture a fake CAR). Sector-agnostic
— every sector reports results incl. financials; tier segmentation is at backtest.

Reads:  bse_announcements (category='Result'), stock_prices (close),
        macro_history (nifty50)
Returns: DataFrame[sid, announcement_car]

Usage:
    python -m signals.announcement_car     # live compute + print stats
"""

from __future__ import annotations

import bisect
from datetime import date, timedelta

import numpy as np
import pandas as pd

from db import read_sql
from signals.pead import _announce_dates_by_sid

NIFTY_ID = "nifty50"
CAR_PRE = 1          # trading days BEFORE day0 → window opens at close of day0−1 (last pre-print close)
CAR_POST = 1         # trading days AFTER day0  → window closes at close of day0+1  ⇒ [−1,+1] 3-day event window
STALE_DAYS = 90      # announcement must be within this many CALENDAR days of eval (one reporting quarter)
CAR_CLIP = (-0.5, 0.5)   # a 3-day abnormal return beyond ±50% is almost always a data error


def _nifty_asof(n_dates, n_vals, d):
    """Latest NIFTY value on/before ISO date `d` (asof). None if before series start."""
    i = bisect.bisect_right(n_dates, d) - 1
    if i < 0:
        return None
    return float(n_vals[i])


def _car_one(pdates, pcloses, n_dates, n_vals, ann_iso, eval_iso):
    """Market-adjusted [−CAR_PRE, +CAR_POST] CAR around one announcement. NaN if not measurable.

    day0 = first price row with date ≥ ann_iso. Requires the window's END close to
    exist AND its date ≤ eval_iso (look-ahead guard). Market leg = NIFTY over the
    same start/end dates.
    """
    i0 = bisect.bisect_left(pdates, ann_iso)
    if i0 >= len(pdates):
        return np.nan
    start, end = i0 - CAR_PRE, i0 + CAR_POST
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


def _car_latest(pdates, pcloses, n_dates, n_vals, ann_dates_sorted, eval_iso, lo_iso):
    """CAR of the most recent qualifying announcement (window closed, within staleness).

    ann_dates_sorted ascending → scan newest first; stop once older than lo_iso.
    Falls through to the prior print if the newest window hasn't closed by eval.
    """
    for ann in reversed(ann_dates_sorted):
        if ann < lo_iso:
            break
        if ann > eval_iso:
            continue
        c = _car_one(pdates, pcloses, n_dates, n_vals, ann, eval_iso)
        if c is not None and not np.isnan(c):
            return c
    return np.nan


def compute_announcement_car(
    prices: pd.DataFrame | None = None,
    nifty: pd.DataFrame | None = None,
    announcements: pd.DataFrame | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """Announcement-window market-adjusted CAR per sid, as of as_of_date.

    Frames injectable for PIT. `announcements` = [sid, ann_date] (or raw dt_tm);
    the look-ahead filter (≤ eval) is applied inside via pead._announce_dates_by_sid,
    so the full stream can be passed. `prices` = [sid, date, close(+adj_close)]
    already ≤ eval by the caller. `nifty` = [date, value] for indicator nifty50 ≤ eval.
    """
    cols = ["sid", "announcement_car"]
    eval_iso = as_of_date or date.today().isoformat()
    lo_iso = (date.fromisoformat(eval_iso) - timedelta(days=STALE_DAYS)).isoformat()

    if announcements is None:
        dc = f"AND date(dt_tm) <= '{as_of_date}'" if as_of_date else ""
        announcements = read_sql(
            f"SELECT sid, date(dt_tm) AS ann_date FROM bse_announcements "
            f"WHERE category='Result' AND sid IS NOT NULL AND dt_tm IS NOT NULL {dc} "
            f"ORDER BY sid, dt_tm")
    if prices is None:
        dc = f"AND date <= '{as_of_date}'" if as_of_date else ""
        prices = read_sql(
            f"SELECT sid, date, close FROM stock_prices WHERE close > 0 {dc} ORDER BY sid, date")
    if nifty is None:
        dc = f"AND date <= '{as_of_date}'" if as_of_date else ""
        nifty = read_sql(
            f"SELECT date, value FROM macro_history "
            f"WHERE indicator_id='{NIFTY_ID}' AND value > 0 {dc} ORDER BY date")

    if (announcements is None or len(announcements) == 0
            or prices is None or len(prices) == 0
            or nifty is None or len(nifty) == 0):
        return pd.DataFrame(columns=cols)

    ann_by_sid = _announce_dates_by_sid(announcements, eval_iso)   # sid → sorted ISO dates ≤ eval
    nf = nifty.dropna(subset=["value"]).sort_values("date")
    n_dates = nf["date"].astype(str).to_numpy()
    n_vals = nf["value"].astype(float).to_numpy()
    price_col = "adj_close" if "adj_close" in prices.columns else "close"

    rows = []
    for sid, g in prices.groupby("sid", sort=False):
        ann_dates = ann_by_sid.get(sid)
        if not ann_dates:
            continue
        g = g.sort_values("date")
        pdates = g["date"].astype(str).to_numpy()
        pcloses = g[price_col].astype(float).to_numpy()
        car = _car_latest(pdates, pcloses, n_dates, n_vals, ann_dates, eval_iso, lo_iso)
        if car is not None and not np.isnan(car):
            rows.append({"sid": sid, "announcement_car": round(float(np.clip(car, *CAR_CLIP)), 4)})
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


if __name__ == "__main__":
    res = compute_announcement_car()
    s = res["announcement_car"].dropna()
    print(f"announcement_car — {len(s):,} stocks with a qualifying Result announcement "
          f"in the trailing {STALE_DAYS}d (CAR window [−{CAR_PRE},+{CAR_POST}])")
    if len(s):
        print(f"  market-adj CAR: mean={s.mean():+.4f}  median={s.median():+.4f}  "
              f"p25={s.quantile(0.25):+.4f}  p75={s.quantile(0.75):+.4f}  "
              f"min={s.min():+.4f}  max={s.max():+.4f}")
