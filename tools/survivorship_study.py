"""
Alpha Signal v2 — What survivorship does to the price factors (plan 0020).

Read-only. The backtest panel holds only the stocks in today's universe. This
recomputes the price-only factors on EVERY symbol that traded at each monthly
anchor — the universe plus stock_prices_unlisted (delisted, merged, and listed names
outside the universe; a symbol that is an earlier name of a universe stock is
already in stock_prices, sources.nse.link_renames) — and compares the rank IC with
and without the extra names.

  factors   the live functions, unchanged: delivery_anomaly_z, mom_6m, low_vol_252d,
            st_reversal_21d, max_lottery_21d
  prices    adjusted for splits / bonuses / dividends: corporate_adjustments for the
            universe, corporate_actions by symbol (same parser) for the rest
  label     20 sessions from the first session after the anchor (pit.pit_fwd_return_20d);
            a stock that stops trading inside the window and never trades again
            exits at its last close (a delisting is a return, not a missing value)
  buckets   no market cap exists for a dead name, so tiers are not available: the
            cross-section is split by 90-day average traded value (≥ ₹1 Cr a day =
            tradeable; below = thin)

Usage:
    python -m tools.survivorship_study              # print
    python -m tools.survivorship_study --md FILE    # also write the table as markdown
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pit
from db import read_sql
from signals._prices import apply_adjustments
from tools.backtest_pit import _aggregate, _compute_ic
from tools.compute_corporate_adjustments import parse_bonus_factor, parse_split_factor

TRADEABLE_CR = 1.0
FACTORS = {"delivery_anomaly_z": lambda px: pit.pit_delivery_anomaly_z(px),
           "mom_6m": lambda px: pit.pit_momentum(px),
           "low_vol_252d": lambda px: pit.pit_low_vol_252d(px),
           "st_reversal_21d": lambda px: pit.pit_st_reversal_21d(px),
           "max_lottery_21d": lambda px: pit.pit_max_lottery_21d(px)}


def _unlisted_prices():
    """stock_prices_unlisted as a price frame keyed by a pseudo sid '~SYMBOL', with its
    own split / bonus adjustments parsed from corporate_actions."""
    px = read_sql("SELECT '~' || symbol AS sid, date, close, delivery_pct, volume FROM stock_prices_unlisted "
                  "WHERE close > 0 AND series IN ('EQ', 'BE', 'BZ', 'SM', 'ST') ORDER BY symbol, date")
    px = px.drop_duplicates(["sid", "date"])
    ca = read_sql("SELECT '~' || symbol AS sid, ex_date, ind, subject FROM corporate_actions "
                  "WHERE sid IS NULL AND ind IN ('SPLIT', 'BONUS') AND ex_date IS NOT NULL")
    ca["factor"] = [parse_split_factor(s) if i == "SPLIT" else parse_bonus_factor(s) for i, s in zip(ca["ind"], ca["subject"])]
    adj = ca.dropna(subset=["factor"]).groupby(["sid", "ex_date"], as_index=False)["factor"].prod()
    return px, adj


def _labels(anchor, prices):
    """fwd 20d (next-session entry, adjusted); a symbol whose series ends inside the
    window exits at its last close."""
    lab = pit.pit_fwd_return_20d(anchor, prices).set_index("sid").reindex(columns=["fwd_return_20d"])
    missing = lab.index[lab["fwd_return_20d"].isna()]
    a = anchor.isoformat()
    last_day = prices["date"].max()
    for sid, g in prices[prices["sid"].isin(missing)].groupby("sid"):
        after = g[g["date"] > a]
        if len(after) and after["date"].iloc[-1] < (pd.Timestamp(last_day) - pd.Timedelta(days=45)).strftime("%Y-%m-%d") \
                and (pd.Timestamp(after["date"].iloc[0]) - pd.Timestamp(a)).days <= 7 and len(after) <= 20:
            lab.loc[sid, "fwd_return_20d"] = float(after["adj_close"].iloc[-1] / after["adj_close"].iloc[0] - 1)
    return lab.reset_index()


def run():
    raw = pit.load_raw({"stocks", "prices", "adjustments"})
    universe = apply_adjustments(raw["prices"], raw["adjustments"], date.max)
    ux, uadj = _unlisted_prices()
    unlisted = apply_adjustments(ux, uadj, date.max)
    prices = pd.concat([universe, unlisted], ignore_index=True)
    prices["close_raw"], prices["close"] = prices["close"], prices["adj_close"]   # the label reads `close`
    anchors = [d for d in sorted(read_sql("SELECT DISTINCT snapshot_date d FROM daily_snapshots_pit")["d"])
               if "2020-06" <= d[:7] and pd.Timestamp(d).day <= 7 and pd.Timestamp(d).weekday() < 5]
    anchors = sorted({d[:7]: d for d in reversed(anchors)}.values())                # one per month
    rows = []
    for a in anchors:
        t = date.fromisoformat(a)
        px = prices[prices["date"] <= a]
        px = px[px["sid"].isin(px.loc[px["date"] >= (t - timedelta(days=10)).isoformat(), "sid"].unique())]   # trading at the anchor
        recent = px[px["date"] >= (t - timedelta(days=90)).isoformat()]
        adtv = (recent["close_raw"] * recent["volume"]).groupby(recent["sid"]).mean() / 1e7
        frame = pd.DataFrame({"sid": adtv.index, "adtv_cr": adtv.values})
        for name, fn in FACTORS.items():      # reindex: a factor nobody has enough history for yet returns no column
            frame = frame.merge(fn(px).reindex(columns=["sid", name]), on="sid", how="left")
        frame = frame.merge(_labels(t, prices), on="sid", how="left")
        frame["snapshot_date"] = a
        rows.append(frame)
        print(f"  {a}: {len(frame)} symbols, {frame['sid'].str.startswith('~').sum()} outside the universe, "
              f"{frame['fwd_return_20d'].notna().sum()} labelled", flush=True)
    df = pd.concat(rows, ignore_index=True)
    df["outside"] = df["sid"].str.startswith("~")
    out = []
    for bucket, mask in (("tradeable (≥ ₹1 Cr/day)", df["adtv_cr"] >= TRADEABLE_CR), ("thin (< ₹1 Cr/day)", df["adtv_cr"] < TRADEABLE_CR)):
        for name in FACTORS:
            for scope, sub in (("universe only", df[mask & ~df["outside"]]), ("everything that traded", df[mask])):
                r = _aggregate(_compute_ic(sub, name, "fwd_return_20d"), name, bucket, scope)
                if r:
                    out.append({"bucket": bucket, "factor": name, "scope": scope, "anchors": r["n_periods"],
                                "stocks_avg": r["n_stocks_avg"], "mean_ic": r["mean_ic"], "t": r["t_stat"]})
    res = pd.DataFrame(out)
    summary = (df.groupby("outside").agg(rows=("sid", "size"), labelled=("fwd_return_20d", "count"),
                                         mean_fwd=("fwd_return_20d", "mean"), median_fwd=("fwd_return_20d", "median"),
                                         worse_than_minus_30=("fwd_return_20d", lambda s: (s < -0.3).mean())))
    return res, summary, len(anchors)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md")
    a = ap.parse_args()
    res, summary, n = run()
    wide = res.pivot_table(index=["bucket", "factor"], columns="scope", values=["mean_ic", "t", "stocks_avg"]).round(4)
    print(f"\n{n} monthly anchors\n\n{summary.round(4).to_string()}\n\n{wide.to_string()}")
    if a.md:
        from tools.factor_audit import _md
        Path(a.md).write_text(_md(res) + "\n\n" + _md(summary.round(4).reset_index()) + "\n")


if __name__ == "__main__":
    main()
