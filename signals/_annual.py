"""
Alpha Signal v2 — shared plumbing for the Screener-ratio factor modules
(signals/roic.py, capex_to_dep.py, … — the factors built off annual
fundamentals_screener rows).

Each module keeps only its math: a pure `_compute(stocks, fund)` on frames.
This module holds what every one of them repeated verbatim — the live loader,
the universe/line-item scoping the PIT backtest applies to its filing-lagged
slice (so tools/reconstruct_pit's pit_* helpers call the SAME `_compute`), and
the compute()/CLI wrapper that stamps, prints and saves the frame.
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])


def load(items, excluded=FINANCIAL_SECTORS):
    """Live inputs: (stocks[sid, sector] outside `excluded` sectors, annual
    fundamentals_screener rows [sid, period_end, line_item, value] for `items`
    and those sids). SQL NOT IN also drops NULL-sector stocks."""
    if excluded:
        placeholders = ",".join("?" for _ in excluded)
        stocks = read_sql(
            f"SELECT sid, sector FROM stocks WHERE sector NOT IN ({placeholders})",
            params=list(excluded),
        )
    else:
        stocks = read_sql("SELECT sid, sector FROM stocks")
    sids = set(stocks["sid"])
    fund = read_sql(
        "SELECT sid, period_end, line_item, value "
        "FROM fundamentals_screener WHERE period_type = 'annual' "
        f"AND line_item IN ({','.join('?' for _ in items)})",
        params=list(items),
    )
    fund = fund[fund["sid"].isin(sids)].copy()
    return stocks, fund


def scope(stocks, fund, items, excluded=FINANCIAL_SECTORS):
    """The live universe applied to caller-supplied frames (the PIT slice):
    stocks outside `excluded`, fund rows for those sids and `items`."""
    stocks = stocks[~stocks["sector"].isin(excluded)]
    fund = fund[fund["sid"].isin(set(stocks["sid"])) & fund["line_item"].isin(items)].copy()
    return stocks, fund


def pit_frame(compute_fn, stocks, fund, items, col, excluded=FINANCIAL_SECTORS):
    """[sid, col] from a module's `_compute` on a PIT fundamentals slice."""
    out = compute_fn(*scope(stocks, fund, items, excluded))
    if col not in out.columns:   # a module that built its frame from zero rows
        return pd.DataFrame(columns=["sid", col])
    return out[["sid", col]].reset_index(drop=True)


def days_of_sales_change(fund, item, col, min_sales_cr):
    """YoY change in days-of-sales of a balance-sheet `item` (DSO: Receivables,
    DIO: Inventory): item_t/(Sales_t/365) − item_{t−1}/(Sales_{t−1}/365), over each
    sid's last two annual periods with Sales ≥ min_sales_cr.
    Returns DataFrame[sid, period_end, col]."""
    cols = ["sid", "period_end", col]
    if fund.empty:
        return pd.DataFrame(columns=cols)
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for c in ("Sales", item):
        if c not in wide.columns:
            wide[c] = np.nan
    wide = wide.dropna(subset=["Sales", item])
    wide = wide[wide["Sales"] >= min_sales_cr].copy()
    wide["days"] = wide[item] / (wide["Sales"] / 365.0)
    wide = wide.sort_values(["sid", "period_end"])

    rows = []
    for sid, g in wide.groupby("sid"):
        if len(g) < 2:
            continue
        latest, prior = g.iloc[-1], g.iloc[-2]
        rows.append({"sid": sid, "period_end": latest["period_end"],
                     col: float(latest["days"] - prior["days"])})
    return pd.DataFrame(rows, columns=cols)


def save(df, table, label, value_col, dry_run=False, fmt=".3f", unit=""):
    """Stamp today's snapshot_date, print a one-line distribution, upsert to `table`.
    Returns rows written (or the row count on a dry run)."""
    df = df.copy()
    df.insert(1, "snapshot_date", date.today().isoformat())
    n = len(df)
    if n:
        v = df[value_col]
        print(f"{label}: {n} stocks scored | median={v.median():{fmt}}{unit} | "
              f"p25={v.quantile(0.25):{fmt}}{unit} | p75={v.quantile(0.75):{fmt}}{unit}")
    else:
        print(f"{label}: 0 stocks scored — fundamentals_screener has no qualifying annual rows.")
    if dry_run:
        print("Dry run — not saving.")
        return n
    rows = upsert_df(df, table)
    print(f"Saved {rows} rows to {table}")
    return rows


def cli(compute):
    """`python -m signals.<module> [--dry-run]`."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
