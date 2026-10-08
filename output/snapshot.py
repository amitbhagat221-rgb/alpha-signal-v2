"""
Alpha Signal v2 — Daily display snapshot.

One row per stock per day in daily_snapshots (what the email, the diff engine and the
cockpit show), and today's valuation figures on `stocks` (market cap is written by the
MICRO step; P/E, P/B, ROE, debt/equity here).

Every value comes from pit.features_at(today) — the computation the ranking and the
backtest use, filing lags included. Until 2026-10 this step recomputed earnings yield,
book-to-price and momentum by its own unlagged path and copied the rest from the
*_scores tables, so the stock page could show a value that was not the one ranked
(piotroski differed for 349 of 1,602 stocks; plan 0020 audit §4), and the four
`stocks` valuation columns were empty for every stock.

Usage:
    python -m output.snapshot
    python -m output.snapshot --dry-run
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from db import get_db, upsert_df

# daily_snapshots column ← the PIT column it shows
COLUMNS = {
    "piotroski_f": "piotroski_f", "cf_accruals": "cf_accruals", "bs_accruals": "bs_accruals",
    "earnings_yield": "earnings_yield", "book_to_price": "book_to_price",
    "consensus_signal": "consensus_signal_combined", "promoter_qoq": "promoter_qoq",
    "delivery_pct": "avg_delivery_pct_30d", "mom_6m": "mom_6m", "mom_12m": "mom_12m",
    "smart_money": "smart_money_score", "sentiment_7d": "sentiment_7d",
}
VALUATION = ("roe", "debt_to_equity")       # PIT columns written to `stocks` as they are


def _features(today):
    import pit
    from scoring.screener import LAST_SCORED
    cols = [*COLUMNS.values(), *VALUATION]
    producers = pit.producers_for(cols)
    raw = pit.load_raw(pit.raw_keys_for(producers) - {"prices"})
    prices = LAST_SCORED.get("prices") if LAST_SCORED.get("date") == today.isoformat() else None
    raw["prices"] = (prices[["sid", "date", "close", "delivery_pct", "volume"]] if prices is not None
                     and "volume" in prices else pit.load_raw({"prices"})["prices"])
    return pit.features_at(today, cols, raw=raw)


def valuation(f):
    """[sid, pe_ratio, pb_ratio, roe, debt_to_equity]: P/E = 1 / earnings yield and
    P/B = 1 / book-to-price where positive (a loss or negative book has no ratio)."""
    inv = lambda s: pd.Series(np.where(s > 0, 1.0 / s, np.nan), index=s.index).round(2)
    return pd.DataFrame({"sid": f["sid"], "pe_ratio": inv(f["earnings_yield"]), "pb_ratio": inv(f["book_to_price"]),
                         "roe": f["roe"], "debt_to_equity": f["debt_to_equity"]})


def compute(dry_run=False):
    """Write today's display snapshot and the `stocks` valuation figures."""
    today = date.today()
    f = _features(today)
    out = f[["sid", "cap_tier", "close_price"]].assign(snapshot_date=today.isoformat())
    for col, src in COLUMNS.items():
        out[col] = f[src] if src in f else None
    out = out[["sid", "snapshot_date", "cap_tier", "close_price", *COLUMNS]]
    val = valuation(f)

    print(f"Snapshot: {len(out)} stocks, date={today}")
    for col in COLUMNS:
        print(f"  {col}: {out[col].notna().sum()}")
    print(f"  stocks valuation: P/E {val['pe_ratio'].notna().sum()}, P/B {val['pb_ratio'].notna().sum()}, "
          f"ROE {val['roe'].notna().sum()}, D/E {val['debt_to_equity'].notna().sum()}")
    if dry_run:
        print("\nDry run — not saving.")
        return len(out)

    rows = upsert_df(out, "daily_snapshots")
    with get_db() as conn:
        conn.executemany(
            "UPDATE stocks SET pe_ratio = ?, pb_ratio = ?, roe = ?, debt_to_equity = ? WHERE sid = ?",
            [tuple(None if pd.isna(v) else float(v) for v in r[1:]) + (r[0],)
             for r in val[["sid", "pe_ratio", "pb_ratio", "roe", "debt_to_equity"]].itertuples(index=False)])
    print(f"Saved {rows} rows to daily_snapshots; valuation for {len(val)} stocks")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
