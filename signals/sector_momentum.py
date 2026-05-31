"""
Alpha Signal v2 — Sector Momentum — Plan 0006 Phase E.

Per-sector relative strength vs the NIFTY 50 benchmark over three horizons:

  short  =  21 trading-day (≈1m) cap-weighted sector return − NIFTY 50 return
  medium =  63 trading-day (≈3m) "
  long   = 252 trading-day (≈12m) "

Each horizon is classified {strong, neutral, weak} by cross-sectional tercile
across the ~11 sectors (a sector is "strong" only relative to its peers today).
These drive the S/M/L horizon badges on the /sectors front door.

Why constituent-built, not NSE sector indices: the nifty_* sectoral indices in
macro_history don't map 1:1 to our GICS sectors (no clean Utilities / Comm /
Consumer-Discretionary index), and their constituents differ from ours. Building
the sector return from OUR constituents keeps the badge faithful to the same
universe the screener ranks, and makes the value naturally PIT-reconstructible
from stock_prices history (used by the backtest PIT helper).

Data flow (two consumers, one core):
  • compute_sector_momentum()  — sector-level RS + horizon categories. Written to
    sector_briefs.horizon_{short,medium,long} for the cockpit badges.
  • sector_momentum_for_stocks() — assigns each stock its sector's medium-horizon
    RS (z-scored across sectors). This is the per-stock factor the Track-3
    backtest scores; its PIT helper lives in tools/reconstruct_pit.py.

The core takes injectable price / nifty / stocks frames so the live path and the
PIT path run identical logic on different as-of data — never a second copy.

Reads:  stock_prices, stocks, macro_history (nifty50)
Writes: sector_briefs.horizon_{short,medium,long} (UPDATE on existing rows)

Usage:
    python -m signals.sector_momentum            # compute + write horizons
    python -m signals.sector_momentum --dry-run  # print, no DB write
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from db import get_db, read_sql

# Trading-day windows per horizon.
WINDOWS = {"short": 21, "medium": 63, "long": 252}
# A sector needs at least this many constituents with a valid window return
# before we trust its cap-weighted return (else horizon → None).
MIN_CONSTITUENTS = 3
NIFTY_ID = "nifty50"
# Per-constituent window-return winsorization before cap-weighting. Bounds the
# damage a single split/anomaly does to the sector aggregate (stock_prices.close
# is raw/unadjusted, so a constituent split shows a spurious ±80% return). Cheap
# split-defense that keeps the live and PIT paths identical (no adj_close
# dependency) — a real ±60%/+300% single-stock move is also rare and bounded.
RET_CLIP = (-0.6, 3.0)


def _window_return(values: np.ndarray, w: int):
    """Position-based simple return over the last `w` rows of a close series.

    Mirrors signals/momentum.py: index from the end so missing trading days
    just shorten the effective lookback rather than misaligning dates. Returns
    None if there isn't enough history or the base price is non-positive."""
    if values is None or len(values) < w + 1:
        return None
    p_now = values[-1]
    p_then = values[-w - 1]
    if p_then is None or p_then <= 0 or p_now is None or p_now <= 0:
        return None
    return float(p_now / p_then - 1.0)


def _classify(series: pd.Series) -> pd.Series:
    """Tercile classification across sectors → strong / neutral / weak.

    Rank-percentile so it's robust to outliers and always splits the field:
    top third strong, bottom third weak. NaN RS (too few constituents) → None.
    """
    pct = series.rank(pct=True, method="average")

    def _lab(p):
        if pd.isna(p):
            return None
        if p >= 2.0 / 3.0:
            return "strong"
        if p <= 1.0 / 3.0:
            return "weak"
        return "neutral"

    return pct.map(_lab)


def compute_sector_momentum(
    prices: pd.DataFrame | None = None,
    nifty: pd.DataFrame | None = None,
    stocks: pd.DataFrame | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """Core: per-sector relative strength + horizon categories.

    Inputs are injectable so the PIT helper can pass as-of-frozen frames; when
    omitted they're loaded live (optionally bounded by as_of_date).

    Returns DataFrame indexed by sector with columns:
      rs_short, rs_medium, rs_long, horizon_short, horizon_medium, horizon_long
    """
    date_clause = f"AND date <= '{as_of_date}'" if as_of_date else ""

    if prices is None:
        prices = read_sql(
            f"SELECT sid, date, close FROM stock_prices "
            f"WHERE close > 0 {date_clause} ORDER BY sid, date"
        )
    if stocks is None:
        stocks = read_sql(
            "SELECT sid, sector, market_cap_cr FROM stocks "
            "WHERE sector IS NOT NULL AND market_cap_cr > 0"
        )
    if nifty is None:
        nifty = read_sql(
            f"SELECT date, value FROM macro_history "
            f"WHERE indicator_id = '{NIFTY_ID}' AND value > 0 {date_clause} "
            f"ORDER BY date"
        )

    # Benchmark window returns.
    nifty_vals = nifty["value"].to_numpy() if not nifty.empty else np.array([])
    nifty_ret = {h: _window_return(nifty_vals, w) for h, w in WINDOWS.items()}

    # Per-stock window returns.
    sector_of = dict(zip(stocks["sid"], stocks["sector"]))
    mcap_of = dict(zip(stocks["sid"], stocks["market_cap_cr"]))

    recs = []
    for sid, g in prices.groupby("sid", sort=False):
        sector = sector_of.get(sid)
        if sector is None:
            continue
        closes = g["close"].to_numpy()
        rec = {"sid": sid, "sector": sector, "mcap": mcap_of.get(sid, 0.0) or 0.0}
        for h, w in WINDOWS.items():
            rec[h] = _window_return(closes, w)
        recs.append(rec)

    rdf = pd.DataFrame(recs)
    if rdf.empty:
        return pd.DataFrame()

    # Cap-weighted sector return per horizon, then relative strength vs NIFTY.
    out = {}
    for sector, g in rdf.groupby("sector"):
        row = {}
        for h in WINDOWS:
            valid = g[["mcap", h]].dropna(subset=[h])
            valid = valid[valid["mcap"] > 0]
            if len(valid) < MIN_CONSTITUENTS or valid["mcap"].sum() <= 0:
                row[f"rs_{h}"] = np.nan
                continue
            rets = valid[h].clip(*RET_CLIP)
            sec_ret = float(np.average(rets, weights=valid["mcap"]))
            bench = nifty_ret.get(h)
            row[f"rs_{h}"] = sec_ret - bench if bench is not None else np.nan
        out[sector] = row

    res = pd.DataFrame.from_dict(out, orient="index")
    res.index.name = "sector"
    for h in WINDOWS:
        res[f"horizon_{h}"] = _classify(res[f"rs_{h}"])
    return res


def sector_momentum_for_stocks(
    as_of_date: str | None = None,
    sector_mom: pd.DataFrame | None = None,
    stocks: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Per-stock factor: each stock inherits its sector's MEDIUM-horizon relative
    strength, z-scored across sectors. This is the classic sector-momentum
    anomaly (stocks in winning sectors keep winning). Sector-constant by design.

    Returns DataFrame[sid, sector_momentum].
    """
    if sector_mom is None:
        sector_mom = compute_sector_momentum(as_of_date=as_of_date)
    if sector_mom.empty or "rs_medium" not in sector_mom:
        return pd.DataFrame(columns=["sid", "sector_momentum"])

    rs = sector_mom["rs_medium"].dropna()
    if rs.empty:
        return pd.DataFrame(columns=["sid", "sector_momentum"])
    mu, sd = rs.mean(), rs.std()
    if not sd or sd <= 0:
        z = {s: 0.0 for s in rs.index}
    else:
        z = {s: float(np.clip((v - mu) / sd, -3.0, 3.0)) for s, v in rs.items()}

    if stocks is None:
        stocks = read_sql(
            "SELECT sid, sector FROM stocks WHERE sector IS NOT NULL"
        )
    stocks = stocks.copy()
    stocks["sector_momentum"] = stocks["sector"].map(z)
    out = stocks.dropna(subset=["sector_momentum"])[["sid", "sector_momentum"]]
    out["sector_momentum"] = out["sector_momentum"].round(4)
    return out.reset_index(drop=True)


def write_horizons(snapshot_date: str | None = None, dry_run: bool = False) -> int:
    """Compute sector momentum and UPDATE sector_briefs.horizon_* for the row(s)
    on snapshot_date (latest sector_briefs date if None). Returns rows updated."""
    with get_db() as conn:
        if snapshot_date is None:
            row = conn.execute("SELECT MAX(snapshot_date) FROM sector_briefs").fetchone()
            if not row or not row[0]:
                raise RuntimeError("No sector_briefs rows — run compute_sector_briefs first")
            snapshot_date = row[0]

    res = compute_sector_momentum(as_of_date=snapshot_date)
    if res.empty:
        raise RuntimeError("sector_momentum produced no rows — check stock_prices / nifty50")

    if dry_run:
        print(res[["rs_short", "rs_medium", "rs_long",
                   "horizon_short", "horizon_medium", "horizon_long"]].to_string())
        return 0

    n = 0
    with get_db() as conn:
        for sector, r in res.iterrows():
            cur = conn.execute(
                "UPDATE sector_briefs SET horizon_short = ?, horizon_medium = ?, "
                "horizon_long = ? WHERE sector = ? AND snapshot_date = ?",
                (r["horizon_short"], r["horizon_medium"], r["horizon_long"],
                 sector, snapshot_date),
            )
            n += cur.rowcount
    return n


def compute(snapshot_date: str | None = None, dry_run: bool = False) -> int:
    """Pipeline entry point. Returns rows updated in sector_briefs."""
    return write_horizons(snapshot_date=snapshot_date, dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="snapshot_date (default: latest sector_briefs)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    n = compute(snapshot_date=args.date, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"sector_momentum: updated {n} sector_briefs rows")
