"""
Alpha Signal v2 — Low Volatility (trailing 252d)

`low_vol_252d` — annualized standard deviation of daily log returns over the
trailing 252 trading days. The canonical low-risk anomaly (Haugen-Baker 1991,
Ang-Hodrick-Xing-Zhang 2006, Blitz-van Vliet 2007, Frazzini-Pedersen BAB 2014):
LOW volatility names earn higher risk-adjusted — and often raw — forward
returns, strongest among large liquid names. Audit 2026-07-04 Factor-F3 named
low-vol the biggest absent canonical factor; LARGE-tier rebuild candidate #1.

Expected sign: NEGATIVE IC of raw vol vs forward return (low vol → high fwd
return). The backtest decides — record the observed sign, don't force it.

Reads:  stock_prices (close)
Returns: DataFrame[sid, low_vol_252d]

Look-ahead-safe: only closes with date ≤ as_of enter the window. Injectable
frame so the live path and the PIT path (tools/reconstruct_pit.py:
pit_low_vol_252d) run identical logic. Uses `adj_close` when present — the PIT
path passes PIT-strict split/bonus-adjusted closes; a split inside the window
would otherwise manufacture a fake vol spike (live standalone run uses raw
close, same caveat as signals/microstructure.py). Sector-agnostic — vol is
defined for financials too; tier segmentation happens at backtest time.

Usage:
    python -m signals.low_vol      # live compute + print stats
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from signals._prices import load_prices

WINDOW_DAYS = 252    # trailing trading-day window
MIN_OBS = 200        # minimum daily log-return observations, else NULL
VOL_CLIP = (0.0, 5.0)  # annualized-vol band; >500% is data error


def compute_low_vol_252d(
    prices: pd.DataFrame | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """Annualized std of daily log returns, trailing 252 trading days per sid.

    `prices` is injectable for PIT — a frame with [sid, date, close] and
    optionally adj_close (preferred when present), already filtered ≤ as_of by
    the caller. The live path loads stock_prices ≤ as_of itself. Stocks with
    fewer than MIN_OBS return observations are left NULL (recent listings,
    long suspensions).
    """
    cols = ["sid", "low_vol_252d"]
    if prices is None:
        prices = load_prices(as_of_date)   # split/bonus-adjusted, as the PIT path passes
    if prices is None or len(prices) == 0:
        return pd.DataFrame(columns=cols)

    price_col = "adj_close" if "adj_close" in prices.columns else "close"
    rows = []
    for sid, g in prices.groupby("sid"):
        closes = g.sort_values("date")[price_col].tail(WINDOW_DAYS).values.astype(float)
        closes = closes[closes > 0]
        if len(closes) < MIN_OBS + 1:   # N closes → N−1 return obs
            rows.append({"sid": sid})
            continue
        rets = np.diff(np.log(closes))
        vol = float(np.std(rets, ddof=1) * np.sqrt(252.0))
        rows.append({"sid": sid, "low_vol_252d": round(float(np.clip(vol, *VOL_CLIP)), 4)})
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


if __name__ == "__main__":
    res = compute_low_vol_252d()
    s = res["low_vol_252d"].dropna()
    print(f"low_vol_252d — {len(s):,} of {len(res):,} stocks scored "
          f"(≥{MIN_OBS} daily obs in trailing {WINDOW_DAYS}d)")
    if len(s):
        print(f"  annualized vol: median={s.median():.3f}  "
              f"p25={s.quantile(0.25):.3f}  p75={s.quantile(0.75):.3f}  max={s.max():.3f}")
