"""
Alpha Signal v2 — Residual Momentum 12-1 (plan 0012 C3; WS2.6, hypothesis 1 of 2).

`residual_momentum_12_1` — 12-1 momentum (skip the most recent month) residualized
against NIFTY-50 market beta. The designed retest of plain momentum, which
failed the clean bar at SMALL t=1.34 (mom_6m_adj/mom_12m_adj — see
docs/studies/registry-limbo-2026-07.md). Jegadeesh-Titman 1993 (12-1 momentum
horizon) / Blitz-Huij-Martens 2011 (residualizing against market beta
strengthens momentum by removing the part that's just beta exposure, not
stock-specific persistence).

Construction (per sid, as of eval_date D):
  - Window: trading days [D-252, D-21] — skip the most recent ~21 trading days
    (reversal contamination, same convention as mom_6m/mom_12m's SKIP_DAYS=22).
  - Daily log returns for the stock and for NIFTY-50 (macro_history,
    indicator nifty50) over the SAME dates (inner-joined).
  - OLS beta of stock log returns on NIFTY log returns over the window
    (min MIN_OBS paired observations, else NULL — no shrinkage).
  - residual_momentum_12_1 = sum(stock_log_ret) - beta * sum(nifty_log_ret)
    over the window. No sector residualization (v1 of this factor — simple).

Expected sign: POSITIVE (winners persist even after removing market beta).

Reads:  stock_prices (close), macro_history (nifty50)
Returns: DataFrame[sid, residual_momentum_12_1]

Look-ahead-safe: injectable frames so the live path and the PIT path
(tools/reconstruct_pit.py:pit_residual_momentum_12_1) run identical logic.
Uses `adj_close` when present (a split inside the 252d window would otherwise
manufacture a fake momentum spike).

Usage:
    python -m signals.residual_momentum     # live compute + print stats
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from db import read_sql
from signals._prices import load_prices

NIFTY_ID = "nifty50"
WINDOW_START = 252    # trading days back from eval
WINDOW_END = 21        # skip this many most-recent trading days (reversal contamination)
MIN_OBS = 150          # minimum paired daily-return observations for the OLS beta


def compute_residual_momentum_12_1(
    prices: pd.DataFrame | None = None,
    nifty: pd.DataFrame | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    cols = ["sid", "residual_momentum_12_1"]
    if prices is None:
        prices = load_prices(as_of_date)   # split/bonus-adjusted, as the PIT path passes
    if nifty is None:
        dc = f"AND date <= '{as_of_date}'" if as_of_date else ""
        nifty = read_sql(
            f"SELECT date, value FROM macro_history WHERE indicator_id='{NIFTY_ID}' "
            f"AND value > 0 {dc} ORDER BY date"
        )

    if prices is None or len(prices) == 0 or nifty is None or len(nifty) == 0:
        return pd.DataFrame(columns=cols)

    nf = nifty.dropna(subset=["value"]).sort_values("date")
    n_dates = nf["date"].astype(str).to_numpy()
    n_closes = nf["value"].astype(float).to_numpy()
    if len(n_closes) < 2:
        return pd.DataFrame(columns=cols)
    n_log_ret = pd.Series(np.log(n_closes[1:] / n_closes[:-1]), index=n_dates[1:])

    price_col = "adj_close" if "adj_close" in prices.columns else "close"
    rows = []
    for sid, g in prices.groupby("sid", sort=False):
        g = g.sort_values("date")
        closes = g[price_col].to_numpy(dtype=float)
        dates = g["date"].astype(str).to_numpy()
        if len(closes) < WINDOW_START + 1:
            rows.append({"sid": sid})
            continue

        win_closes = closes[-(WINDOW_START + 1):]
        win_dates = dates[-(WINDOW_START + 1):]
        if WINDOW_END > 0:
            win_closes = win_closes[:-WINDOW_END]
            win_dates = win_dates[:-WINDOW_END]
        if len(win_closes) < 2 or (win_closes <= 0).any():
            rows.append({"sid": sid})
            continue

        stock_log_ret = np.log(win_closes[1:] / win_closes[:-1])
        s = pd.Series(stock_log_ret, index=win_dates[1:])
        paired = pd.concat([s.rename("stock"), n_log_ret.rename("nifty")], axis=1, join="inner").dropna()
        if len(paired) < MIN_OBS:
            rows.append({"sid": sid})
            continue

        x = paired["nifty"].to_numpy()
        y = paired["stock"].to_numpy()
        x_mean, y_mean = x.mean(), y.mean()
        denom = float(((x - x_mean) ** 2).sum())
        if denom <= 0:
            rows.append({"sid": sid})
            continue
        beta = float(((x - x_mean) * (y - y_mean)).sum() / denom)

        resid_mom = float(y.sum() - beta * x.sum())
        rows.append({"sid": sid, "residual_momentum_12_1": round(resid_mom, 4)})

    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


if __name__ == "__main__":
    res = compute_residual_momentum_12_1()
    s = res["residual_momentum_12_1"].dropna()
    print(f"residual_momentum_12_1 — {len(s):,} of {len(res):,} stocks scored "
          f"(min {MIN_OBS} paired daily-return obs)")
    if len(s):
        print(f"  mean={s.mean():+.4f}  median={s.median():+.4f}  "
              f"p25={s.quantile(0.25):+.4f}  p75={s.quantile(0.75):+.4f}")
