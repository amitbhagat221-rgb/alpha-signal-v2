"""
Alpha Signal v2 — Validation

Shared checks for data quality. Every source calls these after fetching.
Every signal calls these before saving. Pipeline uses check_table_health()
for post-run sanity.

Usage:
    from validate import check_prices, check_fundamentals, check_no_nulls
"""

import pandas as pd
from db import read_sql, get_db


# ── Generic checks ──

def check_not_empty(df: pd.DataFrame, name: str) -> list[str]:
    """Fail if DataFrame is empty."""
    if df.empty:
        return [f"{name}: DataFrame is empty"]
    return []


def check_no_nulls(df: pd.DataFrame, columns: list[str], name: str) -> list[str]:
    """Fail if any of the specified columns have nulls."""
    errors = []
    for col in columns:
        if col not in df.columns:
            errors.append(f"{name}: missing column '{col}'")
        elif df[col].isna().any():
            n = df[col].isna().sum()
            errors.append(f"{name}: {n} nulls in '{col}'")
    return errors


def check_min_rows(df: pd.DataFrame, min_rows: int, name: str) -> list[str]:
    """Fail if fewer rows than expected."""
    if len(df) < min_rows:
        return [f"{name}: {len(df)} rows (expected >= {min_rows})"]
    return []


def check_range(df: pd.DataFrame, column: str, lo: float, hi: float, name: str) -> list[str]:
    """Fail if any values fall outside [lo, hi]."""
    if column not in df.columns:
        return [f"{name}: missing column '{column}'"]
    out = df[(df[column] < lo) | (df[column] > hi)]
    if len(out) > 0:
        return [f"{name}: {len(out)} values in '{column}' outside [{lo}, {hi}]"]
    return []


def check_unique(df: pd.DataFrame, columns: list[str], name: str) -> list[str]:
    """Fail if the given columns are not unique together."""
    dupes = df.duplicated(subset=columns, keep=False)
    if dupes.any():
        return [f"{name}: {dupes.sum()} duplicate rows on {columns}"]
    return []


# ── Domain-specific checks ──

def check_prices(df: pd.DataFrame) -> list[str]:
    """Validate a bhavcopy/price DataFrame before insert."""
    errors = []
    errors += check_not_empty(df, "prices")
    errors += check_no_nulls(df, ["sid", "date", "close"], "prices")
    errors += check_unique(df, ["sid", "date"], "prices")
    if "close" in df.columns:
        bad = df[df["close"] <= 0]
        if len(bad) > 0:
            errors.append(f"prices: {len(bad)} rows with close <= 0")
    if "delivery_pct" in df.columns:
        errors += check_range(df, "delivery_pct", 0, 100, "prices")
    return errors


def check_fundamentals(df: pd.DataFrame, table_name: str) -> list[str]:
    """Validate income/BS/CF data."""
    errors = []
    errors += check_not_empty(df, table_name)
    errors += check_no_nulls(df, ["sid", "period"], table_name)
    errors += check_unique(df, ["sid", "period"], table_name)
    return errors


def check_shareholding(df: pd.DataFrame) -> list[str]:
    """Validate shareholding data."""
    errors = []
    errors += check_not_empty(df, "shareholding")
    errors += check_no_nulls(df, ["sid", "end_date"], "shareholding")
    pct_cols = [c for c in df.columns if c.endswith("_pct")]
    for col in pct_cols:
        errors += check_range(df, col, 0, 100, "shareholding")
    return errors


def check_signal(df: pd.DataFrame, signal_name: str, score_column: str) -> list[str]:
    """Validate a computed signal DataFrame before save."""
    errors = []
    errors += check_not_empty(df, signal_name)
    errors += check_no_nulls(df, ["sid", "snapshot_date"], signal_name)
    errors += check_unique(df, ["sid", "snapshot_date"], signal_name)
    if score_column in df.columns:
        inf_count = df[score_column].apply(lambda x: pd.notna(x) and abs(x) == float("inf")).sum()
        if inf_count > 0:
            errors.append(f"{signal_name}: {inf_count} infinite values in '{score_column}'")
    return errors


# ── Table health (post-pipeline) ──

def check_table_health() -> dict[str, dict]:
    """
    Quick health report on all populated tables.
    Returns dict of table_name → {rows, nulls_in_key_cols, latest_date}.
    """
    report = {}
    # Key columns per table that should never be null
    key_cols = {
        "stocks": ["sid", "ticker", "cap_tier"],
        "stock_prices": ["sid", "date", "close"],
        "quarterly_income": ["sid", "period"],
        "annual_balance_sheet": ["sid", "period"],
        "annual_cash_flow": ["sid", "period"],
        "shareholding": ["sid", "end_date"],
        "analyst_consensus": ["sid"],
        "vix_history": ["date", "vix"],
    }

    with get_db() as conn:
        for table, cols in key_cols.items():
            row_count = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            null_counts = {}
            for col in cols:
                n = conn.execute(
                    f"SELECT COUNT(*) FROM [{table}] WHERE [{col}] IS NULL"
                ).fetchone()[0]
                if n > 0:
                    null_counts[col] = n

            # Try to get latest date
            date_col = next(
                (c for c in ["date", "snapshot_date", "end_date", "period", "fetched_at"]
                 if c in cols or True),  # just try the first available
                None,
            )
            latest = None
            for candidate in ["date", "snapshot_date", "end_date", "period", "fetched_at"]:
                try:
                    row = conn.execute(
                        f"SELECT MAX([{candidate}]) FROM [{table}]"
                    ).fetchone()
                    if row and row[0]:
                        latest = row[0]
                        break
                except Exception:
                    continue

            report[table] = {
                "rows": row_count,
                "null_keys": null_counts if null_counts else "clean",
                "latest": latest,
            }

    return report


# ── Quick self-test ──

if __name__ == "__main__":
    print("Running table health check...\n")
    report = check_table_health()
    for table, info in report.items():
        status = "OK" if info["null_keys"] == "clean" else f"NULLS: {info['null_keys']}"
        print(f"  {table:30s} {info['rows']:>10,} rows  latest={info['latest']}  {status}")
