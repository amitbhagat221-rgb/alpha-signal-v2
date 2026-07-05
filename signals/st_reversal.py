"""
Alpha Signal v2 — Short-Term Reversal (trailing 21d)

`st_reversal_21d` — trailing 21-trading-day total return. The canonical
short-term reversal factor (Jegadeesh 1990, Lehmann 1990): last month's losers
outperform last month's winners over the next month — liquidity-provision
premium plus overreaction correction. Deliberately the OPPOSITE horizon of the
wired momentum factors (mom_6m/mom_12m skip the most recent 22 days precisely
because this reversal effect lives there). Audit 2026-07-04 Factor-F3
LARGE-tier rebuild candidate #2.

Expected sign: NEGATIVE IC (high trailing 1-month return → low forward
return). The backtest decides — record the observed sign, don't force it.

Reads:  stock_prices (close)
Returns: DataFrame[sid, st_reversal_21d]

Look-ahead-safe: only closes with date ≤ as_of enter the window. Injectable
frame so the live path and the PIT path (tools/reconstruct_pit.py:
pit_st_reversal_21d) run identical logic. Uses `adj_close` when present — the
PIT path passes PIT-strict split/bonus-adjusted closes; a split inside the
window would otherwise read as a fake −50% month. Sector-agnostic.

Usage:
    python -m signals.st_reversal      # live compute + print stats
"""

from __future__ import annotations

import pandas as pd

from db import read_sql

WINDOW_DAYS = 21     # return horizon in trading days (22 closes = 21 intervals)
MIN_OBS = 15         # minimum return intervals in the window, else NULL
RET_CLIP = (-1.0, 5.0)  # 21d total return band (mirrors fwd_return_20d bounds)


def compute_st_reversal_21d(
    prices: pd.DataFrame | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """Trailing 21-trading-day total return per sid.

    `prices` is injectable for PIT — a frame with [sid, date, close] and
    optionally adj_close (preferred when present), already filtered ≤ as_of by
    the caller. The live path loads stock_prices ≤ as_of itself. A stock with
    fewer than MIN_OBS+1 closes in its trailing window (recent listing, long
    suspension) is left NULL; a slightly short window (≥15 intervals) still
    scores — the return is measured over the closes actually present.
    """
    cols = ["sid", "st_reversal_21d"]
    if prices is None:
        dc = f"AND date <= '{as_of_date}'" if as_of_date else ""
        prices = read_sql(
            f"SELECT sid, date, close FROM stock_prices WHERE close > 0 {dc} "
            f"ORDER BY sid, date"
        )
    if prices is None or len(prices) == 0:
        return pd.DataFrame(columns=cols)

    price_col = "adj_close" if "adj_close" in prices.columns else "close"
    rows = []
    for sid, g in prices.groupby("sid"):
        closes = g.sort_values("date")[price_col].tail(WINDOW_DAYS + 1).values.astype(float)
        if len(closes) < MIN_OBS + 1 or closes[0] <= 0 or closes[-1] <= 0:
            rows.append({"sid": sid})
            continue
        ret = closes[-1] / closes[0] - 1.0
        ret = min(max(ret, RET_CLIP[0]), RET_CLIP[1])
        rows.append({"sid": sid, "st_reversal_21d": round(float(ret), 4)})
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


if __name__ == "__main__":
    res = compute_st_reversal_21d()
    s = res["st_reversal_21d"].dropna()
    print(f"st_reversal_21d — {len(s):,} of {len(res):,} stocks scored "
          f"(≥{MIN_OBS} return obs in trailing {WINDOW_DAYS}d)")
    if len(s):
        print(f"  21d return: median={s.median():+.3f}  "
              f"p25={s.quantile(0.25):+.3f}  p75={s.quantile(0.75):+.3f}")
