"""
Alpha Signal v2 — Consensus beat rate, last 4 reports (LARGE re-audit 2026-10-10).

`cons_beat_rate_4q` — the share of a stock's last four quarterly results whose reported
EPS beat the analyst consensus estimate (Yahoo estimate-vs-actual history). Companies that
keep beating keep drifting up: a persistent-surprise / PEAD reading that needs the
consensus numerator the time-series SUE never had (memory pead_needs_announce_dates).

Construction (per sid, as of eval_date D):
  - Reports with both an EPS estimate and a reported EPS, report date strictly before D
    and within the last WINDOW_DAYS (one stale-coverage gate: a stock Yahoo stopped
    covering drops out instead of carrying a year-old record).
  - The latest LAST_N of them; at least MIN_REPORTS, else NULL.
  - Beat = reported EPS > estimate. Value = beats / reports (0..1).

Expected sign: POSITIVE. Evidence (docs/studies/large-reaudit-2026-10-10.md, 82 monthly
anchors): MID t 4.00 (since 2024-09: 2.98), 2.39 after the MID wired factors; LARGE 0.89.

Reads:  analyst_estimates (source yahoo_calendar: eps_actual, eps_estimate)
Returns: DataFrame[sid, cons_beat_rate_4q]

PIT: the report date is the knowable time. Yahoo's stored estimate for a past report is
labelled pit_unverified (whether it was revised after the report is unchecked); a
version written later than the report is used as-is until capture-time history exists.
The live path and pit.py:pit_cons_beat_rate_4q run this same function.

Usage:
    python -m signals.consensus_beat     # live compute + print stats (input via pit.load_raw)
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

WINDOW_DAYS = 400   # reports older than this do not count (≈ 4 quarters + filing slack)
LAST_N = 4          # latest reports averaged
MIN_REPORTS = 3     # fewer than this in the window → NULL
SOURCE = "yahoo_calendar"
ESTIMATES_SQL = (f"SELECT sid, metric, target_period, value, fetched_at FROM analyst_estimates "
                 f"WHERE source = '{SOURCE}' AND metric IN ('eps_actual', 'eps_estimate') "
                 f"AND value IS NOT NULL")


def compute_cons_beat_rate_4q(
    estimates: pd.DataFrame,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """`estimates` = rows of ESTIMATES_SQL (pit.RAW_SQL['yahoo_eps']); signals/ never reads the DB."""
    cols = ["sid", "cons_beat_rate_4q"]
    if estimates is None or estimates.empty:
        return pd.DataFrame(columns=cols)
    as_of = as_of_date or date.today().isoformat()
    start = (date.fromisoformat(as_of) - timedelta(days=WINDOW_DAYS)).isoformat()

    e = estimates[(estimates["target_period"] < as_of) & (estimates["target_period"] >= start)]
    e = (e.sort_values("fetched_at")
          .drop_duplicates(["sid", "metric", "target_period"], keep="last"))   # latest version
    w = (e.pivot(index=["sid", "target_period"], columns="metric", values="value")
          .dropna(subset=["eps_actual", "eps_estimate"]) if not e.empty else pd.DataFrame())
    if w.empty or "eps_actual" not in w or "eps_estimate" not in w:
        return pd.DataFrame(columns=cols)
    w = w.reset_index().sort_values(["sid", "target_period"])
    last = w.groupby("sid").tail(LAST_N)
    last = last.assign(beat=(last["eps_actual"] > last["eps_estimate"]).astype(float))
    g = last.groupby("sid")["beat"].agg(["mean", "size"])
    g = g[g["size"] >= MIN_REPORTS]
    return pd.DataFrame({"sid": g.index, "cons_beat_rate_4q": g["mean"].round(4).values}, columns=cols)


if __name__ == "__main__":
    import pit
    res = compute_cons_beat_rate_4q(pit.load_raw(["yahoo_eps"])["yahoo_eps"])
    s = res["cons_beat_rate_4q"].dropna()
    print(f"cons_beat_rate_4q — {len(s):,} stocks with ≥{MIN_REPORTS} of the last {LAST_N} "
          f"reports in {WINDOW_DAYS}d")
    if len(s):
        print("  distribution:", s.value_counts().sort_index().to_dict())
