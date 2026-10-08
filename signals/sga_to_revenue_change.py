"""
Alpha Signal v2 — SG&A Intensity, YoY change

Reads:  fundamentals_screener (annual rows), stocks
Computed point in time only (pit.py); the live step that wrote its *_scores table had no reader and was removed (plan 0020, 2026-10).

  SGA_int_t = "Selling and admin"_t / Sales_t
  Δ         = SGA_int_t − SGA_int_{t-1}

Rising SGA intensity = operating discipline slipping, or sales falling faster
than overheads can be cut. Higher Δ = worse.

"Selling and admin" in Screener is the closest line to GAAP SG&A; it doesn't
include R&D or other overheads broken out separately, but it captures the
sales/marketing engine specifically.

"""

import numpy as np
import pandas as pd


REQUIRED_ITEMS = ["Sales", "Selling and admin"]
MIN_SALES_CR = 50.0


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "sga_to_revenue_change"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Sales"] >= MIN_SALES_CR].copy()
    wide["sga_int"] = wide["Selling and admin"] / wide["Sales"]
    wide = wide.sort_values(["sid", "period_end"])

    rows = []
    for sid, g in wide.groupby("sid"):
        if len(g) < 2:
            continue
        latest, prior = g.iloc[-1], g.iloc[-2]
        rows.append({
            "sid": sid,
            "period_end": latest["period_end"],
            "sga_to_revenue_change": float(latest["sga_int"] - prior["sga_int"]),
        })
    if not rows:
        return pd.DataFrame(columns=["sid", "period_end", "sga_to_revenue_change"])
    return pd.DataFrame(rows).reset_index(drop=True)
