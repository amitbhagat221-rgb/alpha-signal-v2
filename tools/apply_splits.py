"""
Apply parsed split/bonus events from `split_adjustments` to `stock_prices`.

Adds `adj_close` column to stock_prices (idempotent — populated for every row).
For each stock with splits, multiplies pre-event close prices by the cumulative
factor product so that historical prices line up with post-split levels.

Run once after `tools/compute_splits.py` populates split_adjustments.
Run again whenever new corporate actions land.

Effect on v2 momentum signals: removes the "1:1 bonus = 50% drop" artifacts
that pushed v2 mom_6m/12m to 0.67-0.70 corr against v1's Adj-Close-based
calculation.
"""

import pandas as pd
from db import get_db, read_sql


def main():
    # 1. Ensure adj_close column exists
    with get_db() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(stock_prices)").fetchall()]
        if "adj_close" not in cols:
            c.execute("ALTER TABLE stock_prices ADD COLUMN adj_close REAL")
            print("Added adj_close column to stock_prices")

    # 2. Default: adj_close = close everywhere
    with get_db() as c:
        c.execute("UPDATE stock_prices SET adj_close = close")
        print("Initialized adj_close = close for all rows")

    # 3. For stocks with splits, recompute
    splits = read_sql(
        "SELECT sid, effective_date, cumulative_factor FROM split_adjustments "
        "WHERE cumulative_factor IS NOT NULL AND cumulative_factor > 0 "
        "ORDER BY sid, effective_date"
    )
    if splits.empty:
        print("No splits to apply. Done.")
        return

    sids_with_splits = splits["sid"].unique()
    print(f"Applying splits to {len(sids_with_splits)} stocks ({len(splits)} events)...")

    n_updated_total = 0
    for sid in sids_with_splits:
        stock_events = splits[splits["sid"] == sid].sort_values("effective_date")
        prices = read_sql(
            "SELECT date, close FROM stock_prices WHERE sid = ? ORDER BY date",
            params=(sid,),
        )
        if prices.empty:
            continue

        prices["adj_factor"] = 1.0
        for _, ev in stock_events.iterrows():
            ev_date = ev["effective_date"]
            prices.loc[prices["date"] < ev_date, "adj_factor"] *= ev["cumulative_factor"]

        prices["adj_close"] = (prices["close"] * prices["adj_factor"]).round(4)

        # Update only rows whose factor != 1
        affected = prices[prices["adj_factor"] != 1.0]
        if affected.empty:
            continue

        with get_db() as c:
            for _, row in affected.iterrows():
                c.execute(
                    "UPDATE stock_prices SET adj_close = ? WHERE sid = ? AND date = ?",
                    (float(row["adj_close"]), sid, row["date"]),
                )
        n_updated_total += len(affected)

    print(f"Done. Adjusted adj_close for {n_updated_total} (sid, date) rows across {len(sids_with_splits)} stocks.")


if __name__ == "__main__":
    main()
