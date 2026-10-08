"""
Alpha Signal v2 — Sloan Accruals (full balance-sheet formula)

Reads:  fundamentals_screener (annual rows), stocks
Computed point in time only (pit.py); the live step that wrote its *_scores table had no reader and was removed (plan 0020, 2026-10).

  NWC_t   = Receivables_t + Inventory_t − Trade Payables_t
  ΔNWC    = NWC_t − NWC_{t-1}
  TA_avg  = (Total_t + Total_{t-1}) / 2
  Sloan   = (ΔNWC − Depreciation_t) / TA_avg

The original Sloan (1996) accruals measure. Captures earnings quality:
high accruals (positive Sloan) = lots of non-cash income that hasn't shown
up in operating cash flow yet → lower-quality earnings, tend to mean-revert.

Lower is better (negative Sloan = cash-rich earnings).

Note: this complements `cf_accruals` (already in production) which uses CF
statement directly. This uses the BS-construction formula — the gap between
the two is itself a forensic signal but we're not encoding that here.

"""

import numpy as np
import pandas as pd


REQUIRED_ITEMS = ["Receivables", "Inventory", "Trade Payables", "Depreciation", "Total"]
MIN_ASSETS_CR = 50.0


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "sloan_accruals_full"])
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Total"] >= MIN_ASSETS_CR].copy()
    wide["nwc"] = wide["Receivables"] + wide["Inventory"] - wide["Trade Payables"]
    wide = wide.sort_values(["sid", "period_end"])

    rows = []
    for sid, g in wide.groupby("sid"):
        if len(g) < 2:
            continue
        latest, prior = g.iloc[-1], g.iloc[-2]
        ta_avg = (latest["Total"] + prior["Total"]) / 2.0
        if ta_avg <= 0:
            continue
        sloan = (latest["nwc"] - prior["nwc"] - latest["Depreciation"]) / ta_avg
        rows.append({
            "sid": sid,
            "period_end": latest["period_end"],
            "sloan_accruals_full": float(sloan),
        })
    if not rows:
        return pd.DataFrame(columns=["sid", "period_end", "sloan_accruals_full"])
    return pd.DataFrame(rows).reset_index(drop=True)
