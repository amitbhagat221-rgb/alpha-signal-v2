"""
Alpha Signal v2 — Return on Incremental Invested Capital (ROIIC)

Reads:  fundamentals_screener (annual rows), stocks
Writes: roiic_scores

  NOPAT_t  = (PBT_t + Interest_t) × (1 − Tax_t/PBT_t)
  IC_t     = Equity Share Capital_t + Reserves_t + Borrowings_t
  ROIIC    = (NOPAT_t − NOPAT_{t-5}) / (IC_t − IC_{t-5})

Measures how productively the marginal rupee of capital has been deployed
over the trailing five years. The sister metric of ROIC: ROIC tells you what
the existing book earns today; ROIIC tells you what *new* book earns. A
company with high ROIC but low/negative ROIIC is harvesting an old advantage;
a company with rising ROIIC is compounding.

Definitions mirror signals/roic.py for cross-comparability — same NOPAT and
IC formulas, same tax-rate clipping, same Financial Services exclusion.

Filters:
  - ΔIC ≥ MIN_DELTA_IC_CR (₹50 cr) — drop tiny denominators (rate explodes)
    and capital-returning companies (sign inverts meaning)
  - Both endpoints must have all six line items present
  - Need ≥6 distinct annual periods (year-0 and year-5)

Sign convention: ROIIC > 0 means new capital earned a positive return. The
top of the cross-sectional distribution is the desirable end.

Usage:
    python -m signals.roiic
    python -m signals.roiic --dry-run
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])

REQUIRED_ITEMS = [
    "Profit before tax",
    "Tax",
    "Interest",
    "Equity Share Capital",
    "Reserves",
    "Borrowings",
]

WINDOW_YEARS = 5
MIN_DELTA_IC_CR = 50.0
# Real-world ROIIC sits in (-2, +2). Cap to ±5 in the scorer to keep extreme
# tail names (tiny ΔIC sneaking past the floor) from dominating ranks.
ROIIC_CAP = 5.0


def _load_data():
    placeholders = ",".join("?" for _ in FINANCIAL_SECTORS)
    stocks = read_sql(
        f"SELECT sid, sector FROM stocks WHERE sector NOT IN ({placeholders})",
        params=list(FINANCIAL_SECTORS),
    )
    sids = set(stocks["sid"])

    fund = read_sql(
        "SELECT sid, period_end, line_item, value "
        "FROM fundamentals_screener "
        "WHERE period_type = 'annual' AND line_item IN "
        f"({','.join('?' for _ in REQUIRED_ITEMS)})",
        params=REQUIRED_ITEMS,
    )
    fund = fund[fund["sid"].isin(sids)].copy()
    return stocks, fund


def _compute(stocks, fund):
    if fund.empty:
        return pd.DataFrame(columns=["sid", "period_end", "delta_nopat", "delta_ic", "roiic"])

    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    if wide.empty:
        return pd.DataFrame(columns=["sid", "period_end", "delta_nopat", "delta_ic", "roiic"])

    pbt = wide["Profit before tax"]
    tax = wide["Tax"]
    interest = wide["Interest"]
    tax_rate = np.where(pbt > 0, (tax / pbt.replace(0, np.nan)).clip(0.0, 1.0), 0.0)
    wide["nopat"] = (pbt + interest) * (1 - tax_rate)
    wide["ic"] = (
        wide["Equity Share Capital"] + wide["Reserves"] + wide["Borrowings"]
    )

    wide = wide.sort_values(["sid", "period_end"])
    # Need the row from WINDOW_YEARS back AND today's row — same sid only.
    rows = []
    for sid, g in wide.groupby("sid"):
        if len(g) < WINDOW_YEARS + 1:
            continue
        endpoints = g.iloc[[-(WINDOW_YEARS + 1), -1]]
        nopat_old, nopat_new = endpoints["nopat"].iloc[0], endpoints["nopat"].iloc[1]
        ic_old, ic_new = endpoints["ic"].iloc[0], endpoints["ic"].iloc[1]
        delta_nopat = nopat_new - nopat_old
        delta_ic = ic_new - ic_old
        if delta_ic < MIN_DELTA_IC_CR:
            continue
        roiic = float(np.clip(delta_nopat / delta_ic, -ROIIC_CAP, ROIIC_CAP))
        rows.append({
            "sid": sid,
            "period_end": endpoints["period_end"].iloc[1],
            "delta_nopat": float(delta_nopat),
            "delta_ic": float(delta_ic),
            "roiic": roiic,
        })

    if not rows:
        return pd.DataFrame(columns=["sid", "period_end", "delta_nopat", "delta_ic", "roiic"])
    return pd.DataFrame(rows).reset_index(drop=True)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)

    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end", "delta_nopat", "delta_ic", "roiic"]]

    n = len(df)
    if n:
        r = df["roiic"]
        print(f"ROIIC: {n} stocks scored | "
              f"median={r.median():.3f} | "
              f"p25={r.quantile(0.25):.3f} | p75={r.quantile(0.75):.3f} | "
              f"negative={(r < 0).sum()}")
    else:
        print("ROIIC: 0 stocks scored — fundamentals_screener thin or no qualifying ΔIC.")

    if dry_run:
        print("Dry run — not saving.")
        return n

    rows = upsert_df(df, "roiic_scores")
    print(f"Saved {rows} rows to roiic_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
