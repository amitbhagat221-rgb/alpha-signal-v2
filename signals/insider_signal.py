"""
Alpha Signal v2 — Insider Trading Signal

Computes per-stock insider signal from trade disclosures:
  - Promoter net buying (strongest signal — Brochet et al. 2017)
  - KMP/Director trades (moderate signal)
  - Pledge changes (negative signal)

Window: 90 days (insider trades are sparse, need longer window than 30d)

Scoring:
  insider_score = promoter_weight × promoter_signal
               + director_weight × director_signal
               + pledge_weight × pledge_signal

  promoter_signal:  net_buy_value > 0 → bullish, net_sell > 0 → bearish (dampened)
  director_signal:  same logic, lower weight
  pledge_signal:    any new pledge → bearish

Reads: insider_trades, stocks
Writes: insider_signals

Usage:
    python -m signals.insider_signal            # compute and save
    python -m signals.insider_signal --dry-run  # compute but don't save
"""

import argparse
from datetime import date, timedelta

import numpy as np
import pandas as pd

from db import read_sql, upsert_df

# Weights by person category. Keys are matched via case-insensitive substring
# against the `person_category` column. 2026-05-24 audit: "KMP" never matched
# anything because actual data uses the full "Key Managerial Personnel" — 92
# KMP trades / 90d were silently skipped. "Employees/Designated Employees"
# (258 trades / 34 stocks / 90d) is deliberately excluded — non-promoter
# employee trading is a weaker signal per Brochet et al. 2017 and adding it
# would drown out the priority categories. Revisit if the empirical IC says
# otherwise.
CATEGORY_WEIGHTS = {
    "Promoters": 1.0,
    "Promoter Group": 0.8,
    "Director": 0.5,
    "Key Managerial Personnel": 0.4,
    "Immediate Relative": 0.3,
}

# Asymmetric: selling is less informative than buying
SELL_DAMPENING = 0.4

LOOKBACK_DAYS = 90


def _compute_scores(trades, stocks, eval_date=None):
    """Compute insider signal for all stocks as of eval_date."""
    if eval_date is None:
        eval_date = date.today()
    elif isinstance(eval_date, str):
        eval_date = date.fromisoformat(eval_date)

    cutoff = (eval_date - timedelta(days=LOOKBACK_DAYS)).isoformat()
    eval_str = eval_date.isoformat()

    recent = trades[(trades["trade_date"] >= cutoff) & (trades["trade_date"] <= eval_str)].copy()

    rows = []
    for sid in stocks["sid"]:
        row = {"sid": sid}

        stock_trades = recent[recent["sid"] == sid]
        if stock_trades.empty:
            rows.append(row)
            continue

        # Separate by category
        total_signal = 0.0
        total_weight = 0.0
        descriptions = []
        n_total_trades = len(stock_trades)
        n_tracked_trades = 0

        for cat, weight in CATEGORY_WEIGHTS.items():
            cat_trades = stock_trades[stock_trades["person_category"].str.contains(cat, case=False, na=False)]
            if cat_trades.empty:
                continue
            n_tracked_trades += len(cat_trades)

            buys = cat_trades[cat_trades["transaction_type"].str.contains("Buy", case=False, na=False)]
            sells = cat_trades[cat_trades["transaction_type"].str.contains("Sell", case=False, na=False)]
            pledges = cat_trades[cat_trades["transaction_type"].str.contains("Pledge", case=False, na=False)]

            buy_val = buys["value_lakhs"].sum() if not buys.empty else 0
            sell_val = sells["value_lakhs"].sum() if not sells.empty else 0

            # Net signal: positive = net buying
            if buy_val > 0 or sell_val > 0:
                net = buy_val - (sell_val * SELL_DAMPENING)
                # Normalize: map to -1 to +1 range using log scale
                if net > 0:
                    signal = min(1.0, np.log1p(net) / 10)
                elif net < 0:
                    signal = max(-1.0, -np.log1p(abs(net)) / 10)
                else:
                    signal = 0.0

                total_signal += weight * signal
                total_weight += weight

                if buy_val > 0:
                    descriptions.append(f"{cat} bought ₹{buy_val:.0f}L")
                if sell_val > 0:
                    descriptions.append(f"{cat} sold ₹{sell_val:.0f}L")

            # Pledge penalty
            if not pledges.empty:
                pledge_count = len(pledges)
                total_signal -= 0.3 * pledge_count  # each pledge event is bearish
                descriptions.append(f"{cat} pledge activity ({pledge_count})")

        if total_weight > 0:
            # Normalize by total weight
            score = total_signal / total_weight
            score = max(-1.0, min(1.0, score))

            # Determine signal type and strength
            if score > 0.3:
                signal_type = "STRONG_BUY"
                strength = "strong"
            elif score > 0.1:
                signal_type = "BUY"
                strength = "moderate"
            elif score < -0.3:
                signal_type = "STRONG_SELL"
                strength = "strong"
            elif score < -0.1:
                signal_type = "SELL"
                strength = "moderate"
            else:
                signal_type = "NEUTRAL"
                strength = "weak"

            row["signal_type"] = signal_type
            row["strength"] = strength
            row["score_impact"] = round(score, 4)
            row["description"] = "; ".join(descriptions)[:500]
        elif n_total_trades > 0:
            # Trades exist but all from non-tracked categories (Employees, Other, "-").
            # Don't claim "no activity" — that's misleading. WIPR 2026-05-24 had 6
            # Employee trades and the message read "No insider activity in last 90d".
            row["signal_type"] = "NEUTRAL"
            row["strength"] = "weak"
            row["score_impact"] = 0.0
            row["description"] = f"{n_total_trades} trade(s) from non-tracked categories (no Promoter/Director/KMP activity)"

        rows.append(row)

    return pd.DataFrame(rows)


def compute(dry_run=False):
    """Main entry point."""
    stocks = read_sql("SELECT sid FROM stocks")
    trades = read_sql(
        "SELECT sid, person_category, transaction_type, shares, value_lakhs, trade_date "
        "FROM insider_trades WHERE trade_date IS NOT NULL"
    )

    print(f"Insider Signal: {len(trades)} trades, {len(stocks)} stocks")

    df = _compute_scores(trades, stocks)

    snapshot = date.today().isoformat()
    has_signal = df["signal_type"].notna().sum()

    print(f"  Stocks with insider activity: {has_signal}")

    if has_signal > 0:
        signal_dist = df["signal_type"].value_counts().to_dict()
        print(f"  Distribution: {signal_dist}")

    if dry_run:
        print("\nDry run — not saving.")
        return len(df)

    # Write a row for every stock so downstream joins don't drop coverage.
    # Stocks with no insider activity get NEUTRAL/0; the dry-run line above still
    # reports the "had activity" subset, which is the more useful number day-to-day.
    out = df.copy()
    out["signal_type"] = out["signal_type"].fillna("NEUTRAL")
    out["strength"] = out["strength"].fillna("weak")
    out["score_impact"] = out["score_impact"].fillna(0.0)
    out["description"] = out["description"].fillna("No insider activity in last 90d")
    out["snapshot_date"] = snapshot
    out_cols = ["sid", "snapshot_date", "signal_type", "strength", "score_impact", "description"]
    n = upsert_df(out[out_cols], "insider_signals")
    print(f"Saved {n} rows to insider_signals (snapshot={snapshot})")
    return n


def reconstruct_historical(start="2024-04-01", end=None, dry_run=False):
    """
    Reconstruct monthly insider signals for backtesting.
    Re-runs the scorer at the 1st of each month using only trades
    visible at that point (point-in-time, no lookahead).
    """
    import pandas as pd

    if end is None:
        end = date.today().isoformat()

    stocks = read_sql("SELECT sid FROM stocks")
    all_trades = read_sql(
        "SELECT sid, person_category, transaction_type, shares, value_lakhs, trade_date "
        "FROM insider_trades WHERE trade_date IS NOT NULL AND trade_date >= '2020-01-01'"
    )

    dates = pd.date_range(start=start, end=end, freq="MS")
    print(f"Reconstructing insider signals: {len(dates)} months ({start} → {end})")
    print(f"  Trades available: {len(all_trades)}, Stocks: {len(stocks)}")

    if dry_run:
        for d in dates:
            print(f"  {d.date()}")
        return 0

    total_saved = 0
    for d in dates:
        eval_d = d.date()
        df = _compute_scores(all_trades, stocks, eval_date=eval_d)

        if "signal_type" not in df.columns or df["signal_type"].notna().sum() == 0:
            print(f"  {eval_d}: 0 signals (no trades in window)")
            continue
        out = df[df["signal_type"].notna()].copy()

        out["snapshot_date"] = eval_d.isoformat()
        out_cols = ["sid", "snapshot_date", "signal_type", "strength", "score_impact", "description"]
        n = upsert_df(out[out_cols], "insider_signals")
        total_saved += n

        dist = out["signal_type"].value_counts().to_dict()
        print(f"  {eval_d}: {n} signals — {dist}")

    print(f"\nTotal: {total_saved} historical insider signal rows saved")
    return total_saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--historical", action="store_true", help="Reconstruct monthly signals for backtesting")
    parser.add_argument("--start", default="2024-04-01", help="Start date for historical mode")
    args = parser.parse_args()

    if args.historical:
        reconstruct_historical(start=args.start, dry_run=args.dry_run)
    else:
        compute(dry_run=args.dry_run)
