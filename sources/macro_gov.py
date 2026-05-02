"""
Alpha Signal v2 — Government Macro Data Fetcher

Two sources:
  1. data.gov.in: IIP (9 sub-indices), CPI (12 components), Core Sector (8), GST, WPI
  2. FRED: India CPI, money market rate, exports, imports, Brent, USD/INR

All stored in macro_history + macro_indicator_meta tables.

Requires: DATAGOV_API_KEY env var (for data.gov.in)
FRED: no key needed.

Usage:
    python -m sources.macro_gov                  # fetch all
    python -m sources.macro_gov --source datagov # data.gov.in only
    python -m sources.macro_gov --source fred    # FRED only
    python -m sources.macro_gov --dry-run
"""

import argparse
import os
import re
import time
from datetime import datetime

import pandas as pd
import requests

from db import get_db, upsert_df

# ═══════════════════════════════════════════════════
# DATA.GOV.IN
# ═══════════════════════════════════════════════════

DATAGOV_KEY = os.environ.get(
    "DATAGOV_API_KEY",
    "579b464db66ec23bdd000001dfe3167758b141d37d2f164d3f05d793",
)

# Month name → number
MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _datagov_fetch(resource_id, limit=500, retries=3):
    """Fetch from data.gov.in API with retries."""
    url = f"https://api.data.gov.in/resource/{resource_id}?api-key={DATAGOV_KEY}&format=json&limit={limit}"
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            return resp.json().get("records", [])
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 10
                print(f"\n    Timeout, retrying in {wait}s...", end=" ", flush=True)
                time.sleep(wait)
            else:
                print(f"\n    Failed after {retries} attempts: {e}")
                return []


def _wide_to_long(records, id_field, value_fields_prefix, indicator_prefix, name_field=None):
    """Convert wide-format data.gov.in records (months as columns) to long-format rows."""
    rows = []
    for rec in records:
        item_id = rec.get(id_field, "unknown")
        item_name = rec.get(name_field, item_id) if name_field else item_id

        for key, val in rec.items():
            # Match column pattern: _YYYY_mmm or VALUEYYMM
            match = re.match(r"_(\d{4})_(\w{3})", key)
            if not match:
                match2 = re.match(r"VALUE(\d{4})(\d{2})", key)
                if match2:
                    year = int(match2.group(1))
                    month = int(match2.group(2))
                else:
                    continue
            else:
                year = int(match.group(1))
                month_str = match.group(2).lower()
                month = MONTH_MAP.get(month_str)
                if not month:
                    continue

            if year < 2022:  # only need last 3-4 years
                continue

            try:
                value = float(val) if val not in (None, "", "-", "NA") else None
            except (ValueError, TypeError):
                continue

            if value is not None:
                date_str = f"{year}-{month:02d}-01"
                rows.append({
                    "indicator_id": f"{indicator_prefix}_{item_id}".lower().replace(" ", "_"),
                    "date": date_str,
                    "value": value,
                    "source": "data.gov.in",
                    "unit": "index",
                    "_name": f"{indicator_prefix}: {item_name}",
                })

    return rows


def fetch_iip():
    """Fetch IIP (Index of Industrial Production) — 9 key sub-indices."""
    print("  IIP...", end=" ", flush=True)
    records = _datagov_fetch("31d53713-46c6-48bd-951a-4d986272fd96")

    # Filter to key sub-indices by NIC code
    KEY_IIP = {
        "General": "iip_general",
        "Mining": "iip_mining",
        "Manufacturing": "iip_manufacturing",
        "Electricity": "iip_electricity",
    }

    rows = []
    for rec in records:
        desc = rec.get("description", "")
        if desc not in KEY_IIP:
            continue

        ind_id = KEY_IIP[desc]
        for key, val in rec.items():
            match = re.match(r"_(\d{4})_(\w{3})", key)
            if not match:
                continue
            year = int(match.group(1))
            month = MONTH_MAP.get(match.group(2).lower())
            if not month or year < 2022:
                continue
            try:
                value = float(val) if val not in (None, "", "-") else None
            except (ValueError, TypeError):
                continue
            if value is not None:
                rows.append({
                    "indicator_id": ind_id,
                    "date": f"{year}-{month:02d}-01",
                    "value": value,
                    "source": "data.gov.in",
                    "category": "coincident",
                    "unit": "index",
                })

    print(f"{len(rows)} rows")
    return rows


def fetch_core_sector():
    """Fetch Eight Core Industries index."""
    print("  Core Sector...", end=" ", flush=True)
    records = _datagov_fetch("cc473f03-4db1-4c34-949e-481bdb3da490")

    # Use ITEM_CODE (not ITEM_NAME which has "Growth of..." or "Index of..." prefixes)
    CORE_MAP = {
        "INDEX_COAL": "core_coal",
        "INDEX_CRUDE_OIL": "core_crude",
        "INDEX_NATURAL_GAS": "core_gas",
        "INDEX_REFINERY": "core_refinery",
        "INDEX_FERTILIZER": "core_fertilizer",
        "INDEX_STEEL": "core_steel",
        "INDEX_CEMENT": "core_cement",
        "INDEX_ELECTRICITY": "core_electricity",
        "INDEX_OVERALL": "core_combined",
    }

    rows = []
    for rec in records:
        code = rec.get("ITEM_CODE", "").strip()
        ind_id = CORE_MAP.get(code)
        if not ind_id:
            continue

        for key, val in rec.items():
            match = re.match(r"VALUE(\d{4})(\d{2})", key)
            if not match:
                continue
            year = int(match.group(1))
            month = int(match.group(2))
            if year < 2022:
                continue
            try:
                value = float(val) if val not in (None, "", "-") else None
            except (ValueError, TypeError):
                continue
            if value is not None:
                rows.append({
                    "indicator_id": ind_id,
                    "date": f"{year}-{month:02d}-01",
                    "value": value,
                    "source": "data.gov.in",
                    "category": "coincident",
                    "unit": "index",
                })

    print(f"{len(rows)} rows")
    return rows


def fetch_cpi():
    """Fetch CPI All India — key components."""
    print("  CPI...", end=" ", flush=True)
    records = _datagov_fetch("2a6edbfb-b416-48db-9183-645be023f757", limit=1000)

    CPI_COMPONENTS = [
        "cereals_and_products", "meat_and_fish", "milk_and_products",
        "oils_and_fats", "fruits", "vegetables", "pulses_and_products",
        "sugar_and_confectionery", "spices",
    ]

    rows = []
    for rec in records:
        year = rec.get("year")
        month_str = rec.get("month", "").strip().lower()
        month = MONTH_MAP.get(month_str[:3])
        if not year or not month:
            continue
        try:
            year = int(year)
        except (ValueError, TypeError):
            continue
        if year < 2022:
            continue

        date_str = f"{year}-{month:02d}-01"
        sector = rec.get("sector", "")

        # General CPI
        for comp in CPI_COMPONENTS:
            val = rec.get(comp)
            try:
                value = float(val) if val not in (None, "", "-") else None
            except (ValueError, TypeError):
                continue
            if value is not None:
                ind_id = f"cpi_{comp}" if sector == "Rural+Urban" else f"cpi_{comp}_{sector.lower()}"
                if sector == "Rural+Urban":  # only keep combined for simplicity
                    rows.append({
                        "indicator_id": ind_id,
                        "date": date_str,
                        "value": value,
                        "source": "data.gov.in",
                        "category": "lagging",
                        "unit": "index",
                    })

    print(f"{len(rows)} rows")
    return rows


def fetch_gst():
    """Fetch GST monthly collections."""
    print("  GST...", end=" ", flush=True)
    records = _datagov_fetch("3c92ba18-8554-4967-aa8c-5c3afe0b7ba5")

    rows = []
    for rec in records:
        month_str = rec.get("month", "")  # Format: "Apr-20"
        match = re.match(r"(\w{3})-(\d{2})", month_str)
        if not match:
            continue
        month = MONTH_MAP.get(match.group(1).lower())
        year = 2000 + int(match.group(2))
        if not month or year < 2022:
            continue

        try:
            total = float(rec.get("_total", 0))
        except (ValueError, TypeError):
            continue

        if total > 0:
            rows.append({
                "indicator_id": "gst_monthly",
                "date": f"{year}-{month:02d}-01",
                "value": total,
                "source": "data.gov.in",
                "category": "coincident",
                "unit": "inr_cr",
            })

            # YoY growth if available
            yoy = rec.get("year_on_year_growth__")
            if yoy:
                try:
                    rows.append({
                        "indicator_id": "gst_yoy_growth",
                        "date": f"{year}-{month:02d}-01",
                        "value": float(yoy),
                        "source": "data.gov.in",
                        "category": "coincident",
                        "unit": "percent",
                    })
                except (ValueError, TypeError):
                    pass

    print(f"{len(rows)} rows")
    return rows


def fetch_datagov(dry_run=False):
    """Fetch all data.gov.in datasets."""
    print("data.gov.in macro data:")

    if dry_run:
        print("  IIP: 9 sub-indices × ~36 months")
        print("  Core Sector: 8 industries × ~36 months")
        print("  CPI: 9 components × ~36 months")
        print("  GST: ~36 monthly totals + YoY growth")
        return 0

    all_rows = []
    for name, func in [("IIP", fetch_iip), ("Core Sector", fetch_core_sector),
                        ("CPI", fetch_cpi), ("GST", fetch_gst)]:
        try:
            rows = func()
            all_rows.extend(rows)
        except Exception as e:
            print(f"  {name} FAILED: {e}")
        time.sleep(2)

    if all_rows:
        df = pd.DataFrame(all_rows)
        # Compute YoY and MoM changes
        df = _compute_changes_monthly(df)
        n = upsert_df(df, "macro_history")
        print(f"\ndata.gov.in total: {len(df)} rows saved to macro_history")

        # Update indicator meta
        _update_meta_datagov(df)
    else:
        print("\nNo data fetched from data.gov.in")

    return len(all_rows)


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
            df = pd.read_csv(url)
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

        time.sleep(0.5)

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


def _update_meta_datagov(df):
    """Update macro_indicator_meta for data.gov.in indicators."""
    meta_rows = []
    for ind_id in df["indicator_id"].unique():
        name = ind_id.replace("_", " ").title()
        row_sample = df[df["indicator_id"] == ind_id].iloc[0]
        meta_rows.append({
            "indicator_id": ind_id,
            "name": name,
            "source": "data.gov.in",
            "source_ref": ind_id,
            "category": row_sample.get("category", "coincident"),
            "frequency": "monthly",
            "unit": row_sample.get("unit", "index"),
            "description": f"{name} from data.gov.in",
        })
    if meta_rows:
        upsert_df(pd.DataFrame(meta_rows), "macro_indicator_meta")


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
    """Pipeline entry point — fetch from both sources."""
    total = 0
    total += fetch_datagov(dry_run=dry_run)
    total += fetch_fred(dry_run=dry_run)
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["datagov", "fred"], help="Fetch specific source")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.source == "datagov":
        fetch_datagov(dry_run=args.dry_run)
    elif args.source == "fred":
        fetch_fred(dry_run=args.dry_run)
    else:
        compute(dry_run=args.dry_run)
