"""
Alpha Signal v2 — Dead and never-listed names in the backtest (plan 0020 §7).

The panel (daily_snapshots_pit) holds only today's 2,448 stocks, so every past
cross-section misses the names that later delisted, merged or were never in the
universe. This writes their price-only factors to a second panel,
daily_snapshots_pit_unlisted (key: NSE symbol, anchor), so the backtest can measure a
price factor on the full market as well as on the universe.

  prices    stock_prices_unlisted (every NSE equity symbol outside `stocks`, 2020 →),
            adjusted for splits / bonuses parsed from corporate_actions by symbol
  factors   pit.reconstruct_one_date — the code that builds the panel — for every
            producer that reads prices only (PRODUCERS, derived from the registry)
  label     forward 20 sessions from the session after the anchor; a symbol that stops
            trading inside the window and never trades again exits at its last close
            (a delisting is a return, not a missing value)
  tier      a dead name has no share count, so no market cap: MICRO when its 90-day
            traded value is under the MICRO bar, else the tier most common among the
            20 listed stocks nearest to it in traded value that day (tier_estimated = 1)

No row in `stocks`, no sid: the live universe is unchanged. tools/backtest_pit adds a
"full market" row for each price factor (source v2_full_market) beside the universe row.

Usage:
    python -m tools.unlisted_panel                     # every panel anchor
    python -m tools.unlisted_panel --date 2024-06-03   # one anchor
    python -m tools.unlisted_panel --dry-run
"""
import argparse
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import factors
import pit
from db import get_db, read_sql, upsert_df
from scoring import segment
from signals._prices import apply_adjustments

TABLE = "daily_snapshots_pit_unlisted"
PRICE_INPUTS = {"px", "prices_ohlc", "eval_date", "macro_hist"}
PRODUCERS = [p for p, s in factors.PIT_PRODUCERS.items()
             if s.get("fn") and set(s.get("inputs", ())) | set(s.get("needs", ())) <= PRICE_INPUTS]
COLUMNS = [c for p in PRODUCERS for c in factors.PIT_COLUMNS_BY_PRODUCER.get(p, ())]
SERIES = ("EQ", "BE", "BZ", "SM", "ST")
NEIGHBOURS = 20
RANK_TIERS = [t for t, *_ in segment._rank_tiers()]


def unlisted_raw():
    """The raw frames reconstruct_one_date needs, for unlisted symbols keyed '~SYMBOL'."""
    from tools.compute_corporate_adjustments import parse_bonus_factor, parse_split_factor
    px = read_sql("SELECT '~' || symbol AS sid, date, open, high, low, close, volume, delivery_pct "
                  f"FROM stock_prices_unlisted WHERE close > 0 AND series IN ({','.join('?' * len(SERIES))}) "
                  "ORDER BY symbol, date", params=list(SERIES)).drop_duplicates(["sid", "date"])
    ca = read_sql("SELECT '~' || symbol AS sid, ex_date, ind, subject FROM corporate_actions "
                  "WHERE sid IS NULL AND ind IN ('SPLIT', 'BONUS') AND ex_date IS NOT NULL")
    ca["factor"] = [parse_split_factor(s) if i == "SPLIT" else parse_bonus_factor(s) for i, s in zip(ca["ind"], ca["subject"])]
    adj = ca.dropna(subset=["factor"]).groupby(["sid", "ex_date", "ind"], as_index=False)["factor"].prod()
    adj = adj.rename(columns={"ind": "inds"})
    raw = pit.load_raw({"macro_hist"})
    raw.update(stocks=pd.DataFrame({"sid": px["sid"].unique(), "cap_tier": None, "sector": None,
                                    "industry": None, "market_cap_cr": None}),
               prices=px[["sid", "date", "close", "delivery_pct", "volume"]],
               prices_ohlc=px[["sid", "date", "open", "high", "low", "close", "volume"]],
               adjustments=adj)
    return raw


def adtv(prices, d):
    """90-day average traded value (₹ crore / day) per sid as of d."""
    p = prices[(prices["date"] <= d.isoformat()) & (prices["date"] > (d - timedelta(days=90)).isoformat())]
    return ((p["close"] * p["volume"]).groupby(p["sid"]).mean() / 1e7).rename("adtv_cr")


def estimate_tiers(adtv_unlisted, listed):
    """Tier per unlisted sid from traded value: MICRO under segment.MICRO_ADTV_CR, else
    the most common rank tier among the NEIGHBOURS listed stocks nearest in log traded value.
    `listed` = DataFrame[cap_tier, adtv_cr] (that anchor's point-in-time tiers)."""
    micro = next(t for t, s in config.TIERS.items() if s.get("carve_from"))
    ref = listed[listed["cap_tier"].isin(RANK_TIERS) & (listed["adtv_cr"] > 0)].sort_values("adtv_cr")
    x, tiers = np.log(ref["adtv_cr"].to_numpy()), ref["cap_tier"].to_numpy()
    out = {}
    for sid, a in adtv_unlisted.items():
        if not a > 0 or a < segment.MICRO_ADTV_CR or len(x) == 0:
            out[sid] = micro
            continue
        i = int(np.searchsorted(x, np.log(a)))
        lo, hi = max(0, i - NEIGHBOURS), min(len(x), i + NEIGHBOURS)
        near = np.argsort(np.abs(x[lo:hi] - np.log(a)))[:NEIGHBOURS] + lo
        out[sid] = Counter(tiers[near]).most_common(1)[0][0]
    return pd.Series(out, name="cap_tier")


def labels(anchor, adjusted, lab_px):
    """fwd_return_20d (pit.forward_returns on `lab_px` = adjusted closes); a symbol whose
    trading ends inside the window and never resumes exits at its last close."""
    lab = pit.forward_returns(anchor, lab_px)
    lab = lab.set_index("sid").reindex(columns=["fwd_return_20d"])
    a, horizon_end = anchor.isoformat(), adjusted["date"].max()
    gone = (pd.Timestamp(horizon_end) - pd.Timedelta(days=45)).strftime("%Y-%m-%d")
    for sid, g in adjusted[adjusted["sid"].isin(lab.index[lab["fwd_return_20d"].isna()]) & (adjusted["date"] > a)].groupby("sid"):
        if g["date"].iloc[-1] < gone and len(g) <= 20 and (pd.Timestamp(g["date"].iloc[0]) - pd.Timestamp(a)).days <= 7:
            lab.loc[sid, "fwd_return_20d"] = round(float(g["adj_close"].iloc[-1] / g["adj_close"].iloc[0] - 1), 4)
    return lab["fwd_return_20d"]


def build_one(d, raw, adjusted, lab_px, listed_px, panel_tiers):
    df, _ = pit.reconstruct_one_date(d, raw, set(PRODUCERS))
    cols = [c for c in COLUMNS if c in df.columns]
    out = df[["sid", *cols]].set_index("sid")
    out = out[out.notna().any(axis=1)]
    if out.empty:
        return pd.DataFrame()
    a_u = adtv(raw["prices"], d)
    listed = panel_tiers.to_frame("cap_tier").join(adtv(listed_px, d))
    out["adtv_90d_cr"] = a_u.reindex(out.index).round(4)
    out["cap_tier"] = estimate_tiers(out["adtv_90d_cr"].dropna(), listed).reindex(out.index)
    out["tier_estimated"] = 1
    out["fwd_return_20d"] = labels(d, adjusted, lab_px).reindex(out.index)
    out = out.reset_index()
    out["symbol"] = out.pop("sid").str[1:]
    out["snapshot_date"] = d.isoformat()
    return out


def _ensure_columns(cols):
    with get_db() as conn:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({TABLE})")}
        for c in cols:
            if c not in have:
                conn.execute(f'ALTER TABLE {TABLE} ADD COLUMN "{c}" REAL')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", action="append", help="anchor(s); default every daily_snapshots_pit anchor")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    anchors = a.date or read_sql("SELECT DISTINCT snapshot_date FROM daily_snapshots_pit ORDER BY 1")["snapshot_date"].tolist()
    raw = unlisted_raw()
    adjusted = apply_adjustments(raw["prices"], raw["adjustments"], date.max)
    lab_px = adjusted[["sid", "date"]].assign(close=adjusted["adj_close"])
    listed_px = pit.load_raw({"prices"})["prices"]
    tiers = read_sql("SELECT sid, snapshot_date, cap_tier FROM daily_snapshots_pit WHERE cap_tier IS NOT NULL")
    print(f"{len(PRODUCERS)} price producers → {len(COLUMNS)} columns; "
          f"{raw['stocks']['sid'].nunique():,} unlisted symbols; {len(anchors)} anchors")
    if not a.dry_run:
        _ensure_columns(COLUMNS)
    total = 0
    for d_s in anchors:
        d = date.fromisoformat(d_s)
        out = build_one(d, raw, adjusted, lab_px, listed_px, tiers[tiers["snapshot_date"] == d_s].set_index("sid")["cap_tier"])
        if out.empty:
            print(f"[{d_s}] no unlisted symbol traded")
            continue
        n_tier = out["cap_tier"].value_counts().to_dict()
        if not a.dry_run:
            total += upsert_df(out.astype(object).where(out.notna(), None), TABLE, lock_retries=10)
        print(f"[{d_s}] {len(out):,} symbols · labelled {out['fwd_return_20d'].notna().sum():,} · tiers {n_tier}", flush=True)
    print(f"{'(dry run) ' if a.dry_run else ''}wrote {total:,} rows to {TABLE}")


if __name__ == "__main__":
    main()
