"""
Alpha Signal v2 — Operating Margin Trend

Reads:  fundamentals_screener (annual rows), stocks
Writes: operating_margin_trend_scores

  EBIT_t            = PBT_t + Interest_t
  margin_t          = EBIT_t / Sales_t
  margin_slope      = OLS slope of (year_index, margin) over last 5 years (pp/year)
  margin_5y_avg    = mean of last 5 margins

Positive slope = expanding profitability. Loss years (negative EBIT)
are kept since the trend matters more than the level — a stock moving
from −5% to +3% margin is a positive signal.

Financial Services excluded — "operating margin" is ill-defined for
banks/NBFCs where Interest IS the core revenue stream.

Usage:
    python -m signals.operating_margin_trend
    python -m signals.operating_margin_trend --dry-run
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])

REQUIRED_ITEMS = ["Sales", "Profit before tax", "Interest"]
WINDOW_YEARS = 5
MIN_SALES_CR = 50.0


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
        return pd.DataFrame(columns=["sid", "period_end", "margin_latest",
                                     "margin_5y_avg", "margin_slope"])

    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in REQUIRED_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=REQUIRED_ITEMS)
    wide = wide[wide["Sales"] >= MIN_SALES_CR].copy()

    wide["ebit"] = wide["Profit before tax"] + wide["Interest"]
    wide["margin"] = wide["ebit"] / wide["Sales"]
    # Drop physically implausible margins (operating leverage breakdowns)
    wide = wide[wide["margin"].between(-2.0, 2.0)]

    wide = wide.sort_values(["sid", "period_end"])
    last_n = wide.groupby("sid", as_index=False).tail(WINDOW_YEARS)

    rows = []
    for sid, g in last_n.groupby("sid"):
        if len(g) < WINDOW_YEARS:
            continue
        x = np.arange(len(g), dtype=float)
        y = g["margin"].values
        # OLS slope in fraction/year; convert to percentage-points/year.
        slope_frac = np.polyfit(x, y, 1)[0]
        rows.append({
            "sid": sid,
            "period_end": g["period_end"].iloc[-1],
            "margin_latest": float(y[-1]),
            "margin_5y_avg": float(y.mean()),
            "margin_slope": float(slope_frac) * 100.0,
        })
    return pd.DataFrame(rows)


def compute(dry_run=False):
    stocks, fund = _load_data()
    df = _compute(stocks, fund)

    df["snapshot_date"] = date.today().isoformat()
    df = df[["sid", "snapshot_date", "period_end",
             "margin_latest", "margin_5y_avg", "margin_slope"]]

    n = len(df)
    if n:
        s = df["margin_slope"]
        print(f"OpMargin trend: {n} stocks scored | "
              f"median_slope={s.median():.2f}pp/yr | "
              f"p25={s.quantile(0.25):.2f} | p75={s.quantile(0.75):.2f} | "
              f"improving={(s > 0).sum()} deteriorating={(s < 0).sum()}")
    else:
        print("OpMargin trend: 0 stocks scored — thin fundamentals.")

    if dry_run:
        print("Dry run — not saving.")
        return n

    rows = upsert_df(df, "operating_margin_trend_scores")
    print(f"Saved {rows} rows to operating_margin_trend_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
