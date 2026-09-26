"""
Alpha Signal v2 — MAX Lottery Factor, 21d (plan 0012 C4; WS2.7, hypothesis 2 of 2).

`max_lottery_21d` — Bali, Cakici & Whitelaw (2011): retail investors overpay for
lottery-like upside (a few huge daily gains), overpricing high-MAX names and
depressing their forward returns. Mean of the 5 highest daily simple returns
over the trailing 21 trading days.

Construction (per sid, as of eval_date D):
  - Window: trading days [D-21, D-1].
  - Simple (not log) daily returns over that window.
  - MAX = mean of the 5 highest daily returns in the window (min 15 obs, else NULL).

Expected sign: NEGATIVE (high MAX -> low forward return — the lottery premium
is a cost to holders, not a reward). Cadence: monthly.

Note (long-only use): like `governance_resignation`, this is naturally
EXCLUSION/PENALTY-shaped rather than a ranking tilt — a long-only book can't
short the lottery names it wants to avoid, so the practical use (if ever
promoted) would be a screen-out/penalty on high-MAX names, not a symmetric
long tilt. Recorded here for the backtest; wiring shape is a human decision.

Reads:  stock_prices (close)
Returns: DataFrame[sid, max_lottery_21d]

Look-ahead-safe: injectable frame so the live path and the PIT path
(tools/reconstruct_pit.py:pit_max_lottery_21d) run identical logic. Uses
`adj_close` when present (a split inside the 21d window would otherwise
manufacture a fake outsized daily return).

Usage:
    python -m signals.max_lottery     # live compute + print stats
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from signals._prices import load_prices

WINDOW_DAYS = 21   # trading days
MIN_OBS = 15       # minimum daily-return observations in the window, else NULL
TOP_K = 5          # highest daily returns averaged


def compute_max_lottery_21d(
    prices: pd.DataFrame | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    cols = ["sid", "max_lottery_21d"]
    if prices is None:
        prices = load_prices(as_of_date)   # split/bonus-adjusted, as the PIT path passes
    if prices is None or len(prices) == 0:
        return pd.DataFrame(columns=cols)

    price_col = "adj_close" if "adj_close" in prices.columns else "close"
    rows = []
    for sid, g in prices.groupby("sid", sort=False):
        closes = g.sort_values("date")[price_col].tail(WINDOW_DAYS + 1).to_numpy(dtype=float)
        if len(closes) < MIN_OBS + 1 or (closes <= 0).any():
            rows.append({"sid": sid})
            continue
        daily_ret = closes[1:] / closes[:-1] - 1.0
        if len(daily_ret) < MIN_OBS:
            rows.append({"sid": sid})
            continue
        top_k = np.sort(daily_ret)[-TOP_K:]
        rows.append({"sid": sid, "max_lottery_21d": round(float(top_k.mean()), 4)})

    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


if __name__ == "__main__":
    res = compute_max_lottery_21d()
    s = res["max_lottery_21d"].dropna()
    print(f"max_lottery_21d — {len(s):,} of {len(res):,} stocks scored "
          f"(min {MIN_OBS} obs, top {TOP_K} of trailing {WINDOW_DAYS}d)")
    if len(s):
        print(f"  mean={s.mean():+.4f}  median={s.median():+.4f}  "
              f"p25={s.quantile(0.25):+.4f}  p75={s.quantile(0.75):+.4f}")
