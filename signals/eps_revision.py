"""
Alpha Signal v2 — EPS revision YoY, live producer (plan 0012 C1; WS2.1a).

`eps_revision_yoy` validated on the clean re-baselined panel (SMALL t=2.78,
n=38) but had no live producer — the screener couldn't see it. This is a
computed, ZERO-WEIGHT signal (pending human promotion review); it does NOT
change `factors.SIGNAL_WEIGHTS`.

`eps_revision_yoy()` below IS what `pit.pit_consensus` calls,
evaluated as-of today instead of a historical anchor: YoY % change between the latest
`forecast_history` metric='eps' snapshot and the snapshot 9-18 months prior
(closest to exactly 12 months back). `metric='eps'` rows are genuine forward
analyst EPS estimates — `metric='price'` is PERMANENTLY CONTAMINATED look-ahead
(ADR 0045, `forecast_history_price_contaminated`) and must never be touched here.

NULL when a sid has <2 usable snapshots or no prior snapshot in the 9-18mo
window (absent row, not a 0 — a missing revision is "no reading"). |value| > 500
is DISCARDED (NaN), not clipped — the backtest's range rule (factors.VALIDATION_RANGES),
applied by the screener; the live producer used to clip to ±500 instead.

Reads:  forecast_history (metric='eps')
Returns: DataFrame[sid, eps_revision_yoy]

Usage:
    python -m signals.eps_revision     # live compute + print stats
"""

import pandas as pd

from db import read_sql


def _yoy(g):
    """YoY % change between a sid's latest snapshot and the one closest to a year
    earlier (9–18 months back). None if not measurable. `g` sorted by date."""
    if g is None or len(g) < 2:
        return None
    latest = g.iloc[-1]
    latest_dt = str(latest["date"])
    latest_year = int(latest_dt[:4])
    prior_candidates = g[
        (g["date"] >= f"{latest_year - 2}-01-01")
        & (g["date"] < f"{latest_year}-{latest_dt[5:]}")
    ]
    if prior_candidates.empty:
        return None
    # Pick the one closest to latest_dt − 1 year
    target_year = latest_year - 1
    prior = prior_candidates.iloc[
        (prior_candidates["date"].str[:4].astype(int) - target_year).abs().argmin()
    ]
    latest_v, prior_v = latest["value"], prior["value"]
    if pd.isna(latest_v) or pd.isna(prior_v) or abs(prior_v) < 1e-9:
        return None
    return round((float(latest_v) / abs(float(prior_v)) - 1) * 100, 2)


def eps_revision_yoy(fh):
    """Per-sid EPS revision YoY off forecast_history metric='eps' rows [sid, date, value]
    (non-null values, as-of filtered by the caller). Unclipped — out-of-range values are
    discarded by the caller's range rule (factors.VALIDATION_RANGES), as in the backtest.
    Shared with pit.py:pit_consensus. Returns DataFrame[sid, eps_revision_yoy]."""
    cols = ["sid", "eps_revision_yoy"]
    rows = []
    for sid, g in fh.groupby("sid", sort=False):
        yoy = _yoy(g.sort_values("date"))
        if yoy is not None:
            rows.append({"sid": sid, "eps_revision_yoy": yoy})
    return pd.DataFrame(rows, columns=cols)


def compute_eps_revision_yoy():
    fh = read_sql(
        "SELECT sid, date, value FROM forecast_history "
        "WHERE metric='eps' AND value IS NOT NULL ORDER BY sid, date"
    )
    return eps_revision_yoy(fh)


if __name__ == "__main__":
    res = compute_eps_revision_yoy()
    s = res["eps_revision_yoy"].dropna()
    print(f"eps_revision_yoy — {len(s):,} stocks with a usable YoY EPS revision reading")
    if len(s):
        print(f"  mean={s.mean():+.2f}  median={s.median():+.2f}  "
              f"p25={s.quantile(0.25):+.2f}  p75={s.quantile(0.75):+.2f}  "
              f"min={s.min():+.2f}  max={s.max():+.2f}")
