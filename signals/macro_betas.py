"""
Alpha Signal v2 — Per-stock macro betas — Plan 0002 §3.2.7 (macro extensions).

Six cross-sectional macro-exposure factors: each stock's rolling sensitivity
(OLS beta) of daily returns to a macro factor's daily returns over a trailing
252-trading-day window.

  oil_beta      β(stock, Brent crude)            — energy / input-cost exposure
  metals_beta   β(stock, copper+aluminium blend) — industrial / capex / metals cycle
  inr_beta      β(stock, USD/INR)                 — FX / importer-vs-exporter tilt
  gold_beta     β(stock, gold)                    — safe-haven / gold-financier tilt
  rate_beta     β(stock, 10Y G-Sec gilt ETF)      — rate / duration exposure (§3.2.7)
  credit_beta   β(stock, AAA-PSU credit excess)   — credit-cycle exposure (§3.2.7)

WHY BETAS, NOT LEVELS.  The plan names §3.2.7 "macro extensions" (inr_carry_proxy,
india_credit_spread, commodity_beta_oil/metals). A raw macro *level* (a carry rate,
a credit spread) is identical for every stock on a given date → it has zero
cross-sectional dispersion and therefore zero cross-sectional IC by construction;
it can only act as a regime conditioner, not a ranking factor. The rankable form
of a macro factor is the per-stock *exposure* (beta) — the Barra-style macro
factor. So all six are realised as betas.

RATE + CREDIT (2026-06-07).  Previously DEFERRED for lack of a daily India rates /
credit series. Resolved by sourcing NSE-listed bond ETFs (the only free daily India-
rates feed reachable from this VM; FBIL/CCIL/RBI are walled, FRED monthly):
  rate_beta   ← `gsec10_etf` (SBI 10Y Gilt ETF). The ETF RISES when the 10Y yield
              FALLS, so a +rate_beta stock co-moves with bond rallies (duration-like:
              NBFCs, rate-sensitive growth). Sign is decided by the backtest.
  credit_beta ← `credit_excess_idx` (AAA-PSU Bharat Bond minus gilt, base-100 excess-
              return index). +credit_beta stocks rise when credit spreads TIGHTEN.
              CAVEAT: Bharat Bond is target-maturity → residual duration tilt;
              orthogonalise credit_beta vs rate_beta before any wiring (see
              sources/macro_yfinance._compute_credit_spread).

Injectable `prices` + `macro_hist` frames so the live path and the PIT path
(tools/reconstruct_pit.py:pit_macro_betas) run identical logic. Sign is decided
by the backtest. Needs ~1y of macro history before the first computable anchor;
macro_history now reaches back to 2015-06 (gilt ETF 2016, credit index 2019).

Reads:  stock_prices (close), macro_history
        (brent_crude/copper/aluminium/usdinr/gold/gsec10_etf/credit_excess_idx)
Returns: DataFrame[sid, oil_beta, metals_beta, inr_beta, gold_beta, rate_beta, credit_beta]

Usage:
    python -m signals.macro_betas            # compute live + print stats
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from db import read_sql

WINDOW = 252            # trailing trading days for the rolling beta
MIN_OBS = 120           # min overlapping return obs (else NULL — analyst-thin/recent IPO)
BETA_CLIP = (-5.0, 5.0)

# factor → macro_history indicator_id(s). A list = equal-weight blend of the
# members' daily returns (the metals "index").
SERIES = {
    "oil_beta":    ["brent_crude"],
    "metals_beta": ["copper", "aluminium"],
    "inr_beta":    ["usdinr"],
    "gold_beta":   ["gold"],
    "rate_beta":   ["gsec10_etf"],         # 10Y G-Sec gilt ETF (rises when yields fall)
    "credit_beta": ["credit_excess_idx"],  # AAA-PSU-over-gilt excess-return index
}
FACTORS = list(SERIES.keys())


def _macro_factor_returns(macro_hist: pd.DataFrame) -> pd.DataFrame:
    """Build a date-indexed frame of daily returns, one column per macro factor.

    Single-indicator factors are that series' pct-change; blend factors are the
    equal-weight mean of members' pct-changes on each date.
    """
    if macro_hist is None or macro_hist.empty:
        return pd.DataFrame()
    wide = (macro_hist.pivot_table(index="date", columns="indicator_id", values="value")
            .sort_index())
    rets = wide.pct_change(fill_method=None)
    out = {}
    for factor, members in SERIES.items():
        present = [m for m in members if m in rets.columns]
        if not present:
            continue
        out[factor] = rets[present].mean(axis=1)
    return pd.DataFrame(out)


def _beta(stock_ret: pd.Series, macro_ret: pd.Series) -> float:
    """OLS slope of stock returns on a macro factor's returns over aligned dates."""
    j = pd.concat([stock_ret, macro_ret], axis=1, join="inner").dropna()
    if len(j) < MIN_OBS:
        return np.nan
    x = j.iloc[:, 1].to_numpy(float)
    y = j.iloc[:, 0].to_numpy(float)
    var = x.var()
    if not np.isfinite(var) or var <= 0:
        return np.nan
    beta = np.cov(y, x, bias=True)[0, 1] / var
    return _clip(beta, *BETA_CLIP)


def _clip(v, lo, hi):
    if v is None or not np.isfinite(v):
        return np.nan
    return float(min(max(v, lo), hi))


def compute_macro_betas(
    prices: pd.DataFrame | None = None,
    macro_hist: pd.DataFrame | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """Core: 4 macro-exposure betas per stock.

    Both `prices` (sid,date,close) and `macro_hist` (indicator_id,date,value) are
    injectable; the PIT path passes as-of-frozen frames. When None they're loaded
    live, bounded by as_of_date.

    Returns DataFrame[sid, oil_beta, metals_beta, inr_beta, gold_beta].
    """
    cols = ["sid", *FACTORS]
    if prices is None:
        date_clause = f"AND date <= '{as_of_date}'" if as_of_date else ""
        prices = read_sql(
            f"SELECT sid, date, close FROM stock_prices WHERE close > 0 {date_clause} "
            "ORDER BY sid, date"
        )
    if macro_hist is None:
        date_clause = f"AND date <= '{as_of_date}'" if as_of_date else ""
        macro_hist = read_sql(
            "SELECT indicator_id, date, value FROM macro_history "
            f"WHERE value IS NOT NULL {date_clause} ORDER BY indicator_id, date"
        )
    if prices is None or prices.empty:
        return pd.DataFrame(columns=cols)

    mret = _macro_factor_returns(macro_hist)
    if mret.empty:
        return pd.DataFrame(columns=cols)

    prices = prices.sort_values(["sid", "date"])
    rows = []
    for sid, g in prices.groupby("sid", sort=False):
        g = g.tail(WINDOW + 1)
        if len(g) < MIN_OBS + 1:
            continue
        sret = pd.Series(g["close"].pct_change(fill_method=None).to_numpy(), index=g["date"].to_numpy())
        rec = {"sid": sid}
        any_beta = False
        for factor in FACTORS:
            if factor not in mret.columns:
                rec[factor] = np.nan
                continue
            b = _beta(sret, mret[factor])
            rec[factor] = b
            any_beta = any_beta or np.isfinite(b) if b is not None else any_beta
        if any_beta:
            rows.append(rec)
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=cols)
    for f in FACTORS:
        out[f] = out[f].round(4)
    return out[cols].reset_index(drop=True)


if __name__ == "__main__":
    out = compute_macro_betas()
    print(f"Computed macro betas for {len(out):,} stocks")
    for c in FACTORS:
        s = out[c].dropna() if c in out else pd.Series(dtype=float)
        if len(s):
            print(f"  {c:14s} n={len(s):4d}  mean={s.mean():+.4f}  "
                  f"min={s.min():+.4f}  max={s.max():+.4f}  std={s.std():.4f}")
