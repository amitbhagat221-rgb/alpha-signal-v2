"""
Alpha Signal v2 — Event-time / PEAD factors — Plan 0002 §3.2.5.

Four of the six §3.2.5 factors are built here (the clean, data-supported ones);
the other two are deferred with reasons (see bottom):

  earnings_surprise_std    SUE — seasonal-random-walk standardised surprise   (core PEAD)
  pead_drift_60d           abnormal return since last earnings (drift-in-progress) (core PEAD)
  corporate_action_density count of corporate actions in trailing 1y          (event flag)
  buyback_announcement_30d 1 if a buyback action in the last 30d              (event flag)

PEAD = post-earnings-announcement drift: stocks that surprise keep drifting in the
surprise direction for weeks. Two complementary readings — the SURPRISE itself
(earnings_surprise_std) and the DRIFT already in progress (pead_drift_60d).

The drift window is anchored to the REAL result-announcement date — the earliest
`bse_announcements` row with category='Result' for that sid landing in
(quarter_end, quarter_end + MAX_ANNOUNCE_LAG_DAYS] (look-ahead-safe `dt_tm` event
time; 81,750 dated events across 2,179 universe names, sid-joined via scrip_master).
quarterly_income itself carries no announcement date, so names with no BSE match
(NSE-only / pre-2018 quarters / late filers) fall back to the period_end +
ANNOUNCE_LAG_DAYS (~45d) proxy — graceful degradation to the old behaviour.
SUE uses the seasonal random walk (EPS_t − EPS_{t-4}) standardised by the stdev of
trailing YoY EPS changes — no analyst-consensus dependency (robust + PIT-clean;
consensus EPS in forecast_history is annual/episodic).

Injectable frames so the live path and the PIT path
(tools/reconstruct_pit.py:pit_pead) run identical logic. Stock-agnostic; sign
decided by the backtest.

Reads:  quarterly_income, stock_prices, macro_history(nifty50), corporate_actions,
        bse_announcements (category='Result')
Returns: DataFrame[sid, earnings_surprise_std, pead_drift_60d,
                   corporate_action_density, buyback_announcement_30d]

Usage:
    python -m signals.pead            # compute live + print stats
"""

from __future__ import annotations

import bisect
import re
from datetime import date, timedelta

import numpy as np
import pandas as pd

from db import read_sql

ANNOUNCE_LAG_DAYS = 45        # period_end → announcement-date PROXY (fallback when no BSE match)
MAX_ANNOUNCE_LAG_DAYS = 80    # search window after quarter-end for the real BSE result filing.
                              # SEBI LODR caps results at 45d quarterly / 60d annual; 80 adds slack
                              # yet stays < ~91d next-quarter spacing → MIN-after-end never grabs Q+1.
DRIFT_WINDOW_DAYS = 90        # calendar days (~60 trading) post-announcement drift window
MIN_QUARTERS_SUE = 6          # need ≥6 quarters to form a YoY change + a stdev
SUE_CLIP = (-5.0, 5.0)
DENSITY_CLIP = (0, 20)
NIFTY_ID = "nifty50"
_BUYBACK_RE = re.compile(r"buy[\s-]?back", re.I)


def _sue_one(eps_series: np.ndarray) -> float:
    """Seasonal-random-walk SUE for the latest quarter.

    surprise = EPS_t − EPS_{t-4}; standardised by stdev of trailing YoY changes.
    eps_series is chronological (oldest→newest). NaN if too little history.
    """
    e = eps_series[~np.isnan(eps_series)]
    if len(e) < MIN_QUARTERS_SUE:
        return np.nan
    yoy = e[4:] - e[:-4]            # YoY changes (seasonal)
    if len(yoy) < 2:
        return np.nan
    sd = np.std(yoy[:-1], ddof=1) if len(yoy) > 2 else np.std(yoy, ddof=1)
    if not sd or sd <= 0:
        return np.nan
    return float(yoy[-1] / sd)


def _abnormal_drift(px_sid, nifty, announce_iso, eval_iso):
    """Stock return − NIFTY return from the announcement to eval_date.

    px_sid: DataFrame[date, close] for one sid (sorted). nifty: DataFrame[date,value].
    Uses the first available price on/after announce. NaN if no bracketing prices.
    """
    a = px_sid[px_sid["date"] >= announce_iso]
    b = px_sid[px_sid["date"] <= eval_iso]
    if a.empty or b.empty:
        return np.nan
    p0, p1 = a.iloc[0]["close"], b.iloc[-1]["close"]
    if not (p0 and p1 and p0 > 0):
        return np.nan
    na = nifty[nifty["date"] >= announce_iso]
    nb = nifty[nifty["date"] <= eval_iso]
    if na.empty or nb.empty:
        return np.nan
    n0, n1 = na.iloc[0]["value"], nb.iloc[-1]["value"]
    if not (n0 and n1 and n0 > 0):
        return np.nan
    return float((p1 / p0 - 1.0) - (n1 / n0 - 1.0))


def compute_pead(
    qi: pd.DataFrame | None = None,
    prices: pd.DataFrame | None = None,
    nifty: pd.DataFrame | None = None,
    corp_actions: pd.DataFrame | None = None,
    announcements: pd.DataFrame | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """Core: 4 event-time factors as of as_of_date (default today).

    Frames injectable for PIT. `qi` should already be PIT-knowable-filtered by the
    caller (the live path loads all; the PIT path passes knowable_quarterly output).
    """
    cols = ["sid", "earnings_surprise_std", "pead_drift_60d",
            "corporate_action_density", "buyback_announcement_30d"]
    eval_iso = as_of_date or date.today().isoformat()

    if qi is None:
        dc = f"AND end_date <= '{as_of_date}'" if as_of_date else ""
        qi = read_sql(f"SELECT sid, end_date, eps FROM quarterly_income "
                      f"WHERE end_date IS NOT NULL AND eps IS NOT NULL {dc} ORDER BY sid, end_date")
    if prices is None:
        dc = f"AND date <= '{as_of_date}'" if as_of_date else ""
        prices = read_sql(f"SELECT sid, date, close FROM stock_prices WHERE close>0 {dc} ORDER BY sid, date")
    if nifty is None:
        dc = f"AND date <= '{as_of_date}'" if as_of_date else ""
        nifty = read_sql(f"SELECT date, value FROM macro_history "
                         f"WHERE indicator_id='{NIFTY_ID}' AND value>0 {dc} ORDER BY date")
    if corp_actions is None:
        dc = f"AND ex_date <= '{as_of_date}'" if as_of_date else ""
        corp_actions = read_sql(f"SELECT sid, ex_date, subject FROM corporate_actions "
                                f"WHERE ex_date IS NOT NULL {dc}")
    if announcements is None:
        dc = f"AND date(dt_tm) <= '{as_of_date}'" if as_of_date else ""
        announcements = read_sql(
            f"SELECT sid, date(dt_tm) AS ann_date FROM bse_announcements "
            f"WHERE category='Result' AND sid IS NOT NULL AND dt_tm IS NOT NULL {dc} "
            f"ORDER BY sid, dt_tm")

    if qi is None or qi.empty:
        return pd.DataFrame(columns=cols)

    # ── Earnings factors per sid ──
    qi = qi.sort_values(["sid", "end_date"])
    px_by_sid = {s: g for s, g in prices.sort_values(["sid", "date"]).groupby("sid", sort=False)} \
        if prices is not None and not prices.empty else {}
    drift_lo = (date.fromisoformat(eval_iso) - timedelta(days=DRIFT_WINDOW_DAYS)).isoformat()
    ann_by_sid = _announce_dates_by_sid(announcements, eval_iso)

    rows = []
    for sid, g in qi.groupby("sid", sort=False):
        eps = g["eps"].to_numpy(float)
        sue = _sue_one(eps)

        # drift: anchor to the REAL result-announcement date for the latest quarter
        # (earliest BSE 'Result' filing in (end, end+MAX_ANNOUNCE_LAG_DAYS]); fall back
        # to end_date + ANNOUNCE_LAG_DAYS when no BSE match. Only compute if the
        # announcement falls inside the trailing drift window (post-earnings).
        last_end = g["end_date"].iloc[-1]
        announce = _match_announce(last_end, ann_by_sid.get(sid))
        if announce is None:
            announce = (date.fromisoformat(last_end) + timedelta(days=ANNOUNCE_LAG_DAYS)).isoformat()
        drift = np.nan
        if drift_lo <= announce <= eval_iso and sid in px_by_sid:
            drift = _abnormal_drift(px_by_sid[sid], nifty, announce, eval_iso)

        rows.append({"sid": sid,
                     "earnings_surprise_std": _clip(sue, *SUE_CLIP),
                     "pead_drift_60d": _clip(drift, -1.0, 1.0)})

    out = pd.DataFrame(rows)

    # ── Corporate-action factors (count in 1y; buyback flag in 30d) ──
    if corp_actions is not None and not corp_actions.empty:
        ca = corp_actions.copy()
        yr_lo = (date.fromisoformat(eval_iso) - timedelta(days=365)).isoformat()
        d30 = (date.fromisoformat(eval_iso) - timedelta(days=30)).isoformat()
        recent = ca[(ca["ex_date"] > yr_lo) & (ca["ex_date"] <= eval_iso)]
        density = recent.groupby("sid").size().rename("corporate_action_density")
        bb = ca[(ca["ex_date"] > d30) & (ca["ex_date"] <= eval_iso)]
        bb = bb[bb["subject"].fillna("").str.contains(_BUYBACK_RE)]
        buyback = bb.groupby("sid").size().gt(0).astype(int).rename("buyback_announcement_30d")
        out = out.merge(density, on="sid", how="left").merge(buyback, on="sid", how="left")
        out["corporate_action_density"] = out["corporate_action_density"].fillna(0).clip(*DENSITY_CLIP)
        out["buyback_announcement_30d"] = out["buyback_announcement_30d"].fillna(0)
    else:
        out["corporate_action_density"] = np.nan
        out["buyback_announcement_30d"] = np.nan

    for c in ("earnings_surprise_std", "pead_drift_60d"):
        out[c] = out[c].round(4)
    return out[cols].reset_index(drop=True)


def _announce_dates_by_sid(announcements, eval_iso):
    """sid → sorted list of result-announcement ISO dates (≤ eval, look-ahead safe).

    Accepts a frame with either `ann_date` (ISO date) or raw `dt_tm` (timestamp);
    normalises to the date and drops anything after eval so PIT can pass the full
    frame and rely on this filter for look-ahead safety.
    """
    if announcements is None or len(announcements) == 0:
        return {}
    col = "ann_date" if "ann_date" in announcements.columns else "dt_tm"
    a = announcements[["sid", col]].dropna()
    a = a.assign(ann_date=a[col].astype(str).str.slice(0, 10))
    a = a[a["ann_date"] <= eval_iso]
    return {s: sorted(g["ann_date"].tolist()) for s, g in a.groupby("sid", sort=False)}


def _match_announce(end_iso, dates_sorted):
    """Earliest result-announcement strictly after quarter-end, within the lag window.

    Returns the real announcement ISO date, or None if no BSE 'Result' filing landed
    in (end_iso, end_iso + MAX_ANNOUNCE_LAG_DAYS] → caller falls back to the proxy.
    Taking the MIN strictly after quarter-end (not just any in-window match) means a
    later restatement/revision can't displace the genuine first announcement.
    """
    if not dates_sorted:
        return None
    hi = (date.fromisoformat(end_iso) + timedelta(days=MAX_ANNOUNCE_LAG_DAYS)).isoformat()
    i = bisect.bisect_right(dates_sorted, end_iso)
    if i < len(dates_sorted) and dates_sorted[i] <= hi:
        return dates_sorted[i]
    return None


def _clip(v, lo, hi):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    return float(min(max(v, lo), hi))


# ── Deferred §3.2.5 factors (not built — reasons) ──
# dividend_change_signal: needs Rs-amount parsed from corporate_actions.subject
#   free text (brittle) + a clean prior-period dividend baseline. Low signal / high
#   parse-fragility — revisit if a structured dividend feed appears.
# index_inclusion_proximity: needs HISTORICAL market cap (close×shares per date) to
#   rank distance from the NIFTY-500 cutoff PIT-correctly; stocks.market_cap_cr is a
#   current snapshot → using it in PIT is look-ahead. Build the historical-mcap
#   series first.


if __name__ == "__main__":
    out = compute_pead()
    print(f"Computed PEAD/event factors for {len(out):,} stocks")
    for c in ("earnings_surprise_std", "pead_drift_60d",
              "corporate_action_density", "buyback_announcement_30d"):
        s = out[c].dropna()
        if len(s):
            print(f"  {c:26s} n={len(s):4d}  mean={s.mean():+.4f}  "
                  f"min={s.min():+.4f}  max={s.max():+.4f}  nonzero={int((s!=0).sum())}")
