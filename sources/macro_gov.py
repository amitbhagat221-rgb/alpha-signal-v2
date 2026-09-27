"""
Alpha Signal v2 — Government Macro Data Fetcher

Two sources:
  1. Official (sources/macro_official.py): IIP + CPI from the MoSPI API, Index of
     Eight Core Industries from the Office of the Economic Adviser; also rebuilds
     the macro_indicators labels. Replaced data.gov.in on 2026-09-27 (gateway 502s /
     timeouts; its datasets had stopped updating in 2023-24).
  2. FRED: India CPI, money market rate, exports, imports, Brent, USD/INR

All stored in macro_history + macro_indicator_meta tables. No API keys.

Usage:
    python -m sources.macro_gov                   # fetch all
    python -m sources.macro_gov --source official # MoSPI + OEA only
    python -m sources.macro_gov --source fred     # FRED only
    python -m sources.macro_gov --dry-run
"""

import argparse
import io

import pandas as pd

from db import upsert_df
from sources import macro_official
from sources._http import polite_get

# ═══════════════════════════════════════════════════
# FRED
# ═══════════════════════════════════════════════════

FRED_SERIES = {
    "india_cpi_index":      ("INDCPIALLMINMEI", "India CPI All Items",      "lagging",    "index"),
    "india_money_rate":     ("IRSTCI01INM156N", "India Money Market Rate",  "leading",    "percent"),
    "india_exports":        ("XTEXVA01INM667S", "India Exports Value",      "coincident", "usd_bn"),
    "india_imports":        ("XTIMVA01INM667S", "India Imports Value",      "coincident", "usd_bn"),
    "fred_brent":           ("DCOILBRENTEU",    "Brent Crude (FRED daily)", "leading",    "usd"),
    "fred_usdinr":          ("DEXINUS",         "USD/INR (FRED daily)",     "coincident", "inr"),
}


def fetch_fred(dry_run=False):
    """Fetch all FRED India macro series."""
    print("FRED macro data:")

    if dry_run:
        for ind_id, (series, name, _, _) in FRED_SERIES.items():
            print(f"  {ind_id:25s} {series:20s} {name}")
        return 0

    all_rows = []
    for ind_id, (series_id, name, category, unit) in FRED_SERIES.items():
        print(f"  {ind_id:25s}", end=" ", flush=True)
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

        try:
            resp = polite_get(url, timeout=60)   # paced ≥2s per host (was 0.5s)
            if resp is None:
                raise RuntimeError("HTTP 404")
            df = pd.read_csv(io.StringIO(resp.text))
            df.columns = ["date", "value"]
            df = df[df["value"] != "."]
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            df = df.dropna(subset=["value"])

            # Filter to last 4 years
            df = df[df["date"] >= "2022-01-01"]

            for _, row in df.iterrows():
                all_rows.append({
                    "indicator_id": ind_id,
                    "date": row["date"],
                    "value": row["value"],
                    "source": "fred",
                    "category": category,
                    "unit": unit,
                })

            print(f"{len(df)} rows ({df['date'].iloc[0]} → {df['date'].iloc[-1]})")
        except Exception as e:
            print(f"ERROR: {e}")

    if all_rows:
        df = pd.DataFrame(all_rows)
        df = _compute_changes_monthly(df)
        n = upsert_df(df, "macro_history")
        print(f"\nFRED total: {len(df)} rows saved to macro_history")

        # Update indicator meta
        _update_meta_fred(df)

    return len(all_rows)


# ═══════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════

def _compute_changes_monthly(df):
    """Compute YoY and MoM for monthly data."""
    if df.empty:
        return df

    df = df.copy()
    df["yoy_change"] = None
    df["mom_change"] = None

    for ind_id in df["indicator_id"].unique():
        mask = df["indicator_id"] == ind_id
        sub = df.loc[mask].sort_values("date")

        if len(sub) >= 2:
            vals = sub["value"].values
            # MoM
            mom = pd.Series(vals).pct_change() * 100
            df.loc[sub.index, "mom_change"] = mom.values

            # YoY (12 months back)
            if len(sub) >= 13:
                yoy = pd.Series(vals).pct_change(periods=12) * 100
                df.loc[sub.index, "yoy_change"] = yoy.values

    return df


def _update_meta_fred(df):
    """Update macro_indicator_meta for FRED indicators."""
    meta_rows = []
    for ind_id, (series, name, category, unit) in FRED_SERIES.items():
        meta_rows.append({
            "indicator_id": ind_id,
            "name": name,
            "source": "fred",
            "source_ref": series,
            "category": category,
            "frequency": "daily" if "daily" in name.lower() else "monthly",
            "unit": unit,
            "description": f"{name} from FRED ({series})",
        })
    if meta_rows:
        upsert_df(pd.DataFrame(meta_rows), "macro_indicator_meta")


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

def compute(dry_run=False):
    """Pipeline entry point — fetch from both sources.

    Runs both, then RAISES naming every source that produced 0 rows, so a dead
    source can't hide behind the other's rows (data.gov.in did: SUCCESS/~2,500 rows
    weekly while every data.gov.in call timed out)."""
    print("official macro (MoSPI + OEA):")
    n_gov = macro_official.fetch_all(dry_run=dry_run)
    n_fred = fetch_fred(dry_run=dry_run)
    dead = [name for name, n in (("MoSPI/OEA", n_gov), ("FRED", n_fred)) if n == 0]
    if dead and not dry_run:
        raise RuntimeError(f"macro_gov: 0 rows from {' + '.join(dead)} "
                           f"({n_gov + n_fred} rows from the rest were saved)")
    return n_gov + n_fred


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["official", "fred"], help="Fetch specific source")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.source == "official":
        macro_official.fetch_all(dry_run=args.dry_run)
    elif args.source == "fred":
        fetch_fred(dry_run=args.dry_run)
    else:
        compute(dry_run=args.dry_run)
