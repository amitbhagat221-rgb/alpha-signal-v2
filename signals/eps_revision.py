"""
Alpha Signal v2 — EPS revision YoY, live producer (plan 0012 C1; WS2.1a).

`eps_revision_yoy` validated on the clean re-baselined panel (SMALL t=2.78,
n=38) but had no live producer — the screener couldn't see it. This is a
computed, ZERO-WEIGHT signal (pending human promotion review); it does NOT
change `config.SIGNAL_WEIGHTS`.

Mirrors `tools.reconstruct_pit.pit_consensus`'s `_yoy` helper exactly, evaluated
as-of today instead of a historical anchor: YoY % change between the latest
`forecast_history` metric='eps' snapshot and the snapshot 9-18 months prior
(closest to exactly 12 months back). `metric='eps'` rows are genuine forward
analyst EPS estimates — `metric='price'` is PERMANENTLY CONTAMINATED look-ahead
(ADR 0045, `forecast_history_price_contaminated`) and must never be touched here.

NULL when a sid has <2 usable snapshots or no prior snapshot in the 9-18mo
window (absent row, not a 0 — a missing revision is "no reading"). Clipped to
+/-500 (matches the PIT range guard in tools/reconstruct_pit.py).

Reads:  forecast_history (metric='eps')
Returns: DataFrame[sid, eps_revision_yoy]

Usage:
    python -m signals.eps_revision     # live compute + print stats
"""

import numpy as np
import pandas as pd

from db import read_sql

EPS_YOY_CLIP = (-500, 500)


def compute_eps_revision_yoy():
    fh = read_sql(
        "SELECT sid, date, value FROM forecast_history WHERE metric='eps' "
        "ORDER BY sid, date"
    )
    cols = ["sid", "eps_revision_yoy"]
    if fh.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for sid, g in fh.groupby("sid", sort=False):
        g = g.sort_values("date")
        if len(g) < 2:
            continue
        latest = g.iloc[-1]
        latest_dt = str(latest["date"])
        latest_year = int(latest_dt[:4])
        prior_candidates = g[
            (g["date"] >= f"{latest_year - 2}-01-01")
            & (g["date"] < f"{latest_year}-{latest_dt[5:]}")
        ]
        if prior_candidates.empty:
            continue
        target_year = latest_year - 1
        prior = prior_candidates.iloc[
            (prior_candidates["date"].str[:4].astype(int) - target_year).abs().argmin()
        ]
        latest_v, prior_v = latest["value"], prior["value"]
        if pd.isna(latest_v) or pd.isna(prior_v) or abs(prior_v) < 1e-9:
            continue
        yoy = (float(latest_v) / abs(float(prior_v)) - 1.0) * 100.0
        rows.append({"sid": sid, "eps_revision_yoy": round(float(np.clip(yoy, *EPS_YOY_CLIP)), 2)})

    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


if __name__ == "__main__":
    res = compute_eps_revision_yoy()
    s = res["eps_revision_yoy"].dropna()
    print(f"eps_revision_yoy — {len(s):,} stocks with a usable YoY EPS revision reading")
    if len(s):
        print(f"  mean={s.mean():+.2f}  median={s.median():+.2f}  "
              f"p25={s.quantile(0.25):+.2f}  p75={s.quantile(0.75):+.2f}  "
              f"min={s.min():+.2f}  max={s.max():+.2f}")
