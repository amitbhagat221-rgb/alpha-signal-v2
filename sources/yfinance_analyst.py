"""
Alpha Signal v2 — Yahoo Finance Analyst Consensus

Replaces Tickertape's broken `forecastsHistory.price` feed (which mixed real
year-end snapshots with daily lastPrice contamination — see HANDOFF
2026-05-22). Two distinct writes:

  1. Daily (default): refresh `analyst_consensus` (latest aggregate per sid).
     Drives the cockpit "current PT" card. Idempotent.

  2. Monthly (--snapshot): append to `analyst_consensus_snapshots`. One row
     per stock per (snapshot_date, source). Drives backtest + pt_revision_*
     signals over proper windows.

PTs are episodic — sell-side analysts publish ~quarterly. Daily history was
phantom precision; monthly captures real material revisions while filtering
day-to-day noise.

Coverage (validated 2026-05-22 on top-50-per-tier):
    LARGE: 98%, MID: 92%, SMALL: 4%

Fields available per stock:
    targetMeanPrice         — consensus PT (mean)
    targetMedianPrice       — median (more robust to outliers)
    targetHighPrice / Low   — analyst dispersion
    numberOfAnalystOpinions — n analysts contributing
    recommendationKey       — strong_buy / buy / hold / sell / strong_sell / none
    recommendationMean      — 1=strong buy, 5=strong sell

Usage:
    python -m sources.yfinance_analyst                  # daily refresh
    python -m sources.yfinance_analyst --snapshot       # ALSO write to monthly history
    python -m sources.yfinance_analyst --ticker HALC    # smoke test one
    python -m sources.yfinance_analyst --limit 20       # smoke test
    python -m sources.yfinance_analyst --tier LARGE
"""

import argparse
import sys
import time
from datetime import date as _date, datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, upsert_df

DELAY = 0.3       # Yahoo accepts ~60 req/min; 300ms = safe
SOURCE = "yfinance"


def _first_business_day(d=None):
    """The snapshot anchor — 1st business day of the current month."""
    d = d or _date.today()
    first = d.replace(day=1)
    while first.weekday() >= 5:    # skip Sat / Sun
        first += timedelta(days=1)
    return first.isoformat()


def _fetch_one(ticker):
    """Return dict of analyst fields, or None if no coverage."""
    import yfinance as yf
    try:
        info = yf.Ticker(f"{ticker}.NS").info
    except Exception:
        return None
    if not info:
        return None
    tgt_mean = info.get("targetMeanPrice")
    if tgt_mean is None:
        return None
    return {
        "target_mean":         float(tgt_mean) if tgt_mean is not None else None,
        "target_median":       float(info["targetMedianPrice"]) if info.get("targetMedianPrice") is not None else None,
        "target_high":         float(info["targetHighPrice"])   if info.get("targetHighPrice") is not None else None,
        "target_low":          float(info["targetLowPrice"])    if info.get("targetLowPrice") is not None else None,
        "n_analysts":          int(info["numberOfAnalystOpinions"]) if info.get("numberOfAnalystOpinions") else None,
        "recommendation_key":  info.get("recommendationKey"),
        "recommendation_mean": float(info["recommendationMean"]) if info.get("recommendationMean") is not None else None,
    }


def compute(limit=None, ticker=None, tier=None, snapshot=False, dry_run=False):
    where = ["s.ticker IS NOT NULL"]
    params = []
    if ticker:
        where.append("s.ticker = ?");  params.append(ticker)
    if tier:
        where.append("s.cap_tier = ?"); params.append(tier)
    stocks = read_sql(
        f"SELECT sid, ticker, cap_tier FROM stocks s WHERE {' AND '.join(where)} ORDER BY cap_tier, ticker",
        params=params,
    )
    if limit:
        stocks = stocks.head(limit)

    mode = "daily refresh + MONTHLY SNAPSHOT" if snapshot else "daily refresh only"
    print(f"yfinance analyst pull ({mode}): {len(stocks)} stocks")
    if dry_run:
        return 0

    fetched_at  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    snapshot_dt = _first_business_day()

    consensus_rows = []   # writes to analyst_consensus (current)
    snapshot_rows  = []   # writes to analyst_consensus_snapshots (monthly history)
    n_with_data    = 0
    n_no_data      = 0
    n_real_spread  = 0

    # Latest close per sid for the spread-check sanity signal
    closes = read_sql(
        "SELECT sid, close FROM stock_prices WHERE (sid, date) IN "
        "(SELECT sid, MAX(date) FROM stock_prices GROUP BY sid)"
    )
    close_map = dict(zip(closes["sid"], closes["close"]))

    t_start = time.time()
    for i, (sid, t, cap_tier) in enumerate(stocks.itertuples(index=False), 1):
        data = _fetch_one(t)
        if data is None:
            n_no_data += 1
        else:
            n_with_data += 1
            close = close_map.get(sid)
            if close and data["target_mean"] and abs(data["target_mean"] - close) / close > 0.02:
                n_real_spread += 1

            # Narrow column set so upsert_df only updates these fields,
            # leaving Tickertape-sourced forward_eps / eps_growth_pct /
            # forward_revenue / revenue_growth_pct intact (those are real).
            consensus_rows.append({
                "sid":              sid,
                "total_analysts":   data["n_analysts"],
                "price_target":     data["target_mean"],
                "has_analyst_data": 1,
                "fetched_at":       fetched_at,
            })
            if snapshot:
                snapshot_rows.append({
                    "sid": sid,
                    "snapshot_date":       snapshot_dt,
                    "source":              SOURCE,
                    "target_mean":         data["target_mean"],
                    "target_median":       data["target_median"],
                    "target_high":         data["target_high"],
                    "target_low":          data["target_low"],
                    "n_analysts":          data["n_analysts"],
                    "recommendation_key":  data["recommendation_key"],
                    "recommendation_mean": data["recommendation_mean"],
                    "fetched_at":          fetched_at,
                })

        if i % 200 == 0:
            elapsed = time.time() - t_start
            rate = i / elapsed
            print(f"  [{i}/{len(stocks)}] coverage={n_with_data} no_data={n_no_data} "
                  f"spread={n_real_spread} | {rate:.1f}/s")
        time.sleep(DELAY)

    if consensus_rows:
        upsert_df(pd.DataFrame(consensus_rows), "analyst_consensus")
    if snapshot_rows:
        upsert_df(pd.DataFrame(snapshot_rows), "analyst_consensus_snapshots")

    pct_have    = 100 * n_with_data / len(stocks) if len(stocks) else 0
    pct_spread  = 100 * n_real_spread / n_with_data if n_with_data else 0
    elapsed     = time.time() - t_start
    print()
    print(f"Done in {elapsed:.0f}s. {n_with_data}/{len(stocks)} have analyst data ({pct_have:.1f}%).")
    print(f"  {n_real_spread} ({pct_spread:.1f}%) have PT >2% from current close (non-degenerate).")
    if snapshot:
        print(f"  Wrote {len(snapshot_rows)} rows to analyst_consensus_snapshots @ {snapshot_dt}")
    return n_with_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", help="One ticker (smoke test)")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--tier", choices=["LARGE", "MID", "SMALL"])
    parser.add_argument("--snapshot", action="store_true",
                        help="Also append a row to analyst_consensus_snapshots "
                             "(monthly history). Set this on the monthly cron only.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(limit=args.limit, ticker=args.ticker, tier=args.tier,
            snapshot=args.snapshot, dry_run=args.dry_run)
