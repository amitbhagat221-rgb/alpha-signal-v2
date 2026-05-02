"""
Alpha Signal v2 — Macro Sector Signal

Maps 22 macro indicators to sector scores using a rules table.
Signal → Score: STRONG=80, IMPROVING=65, STABLE=50, DETERIORATING=30.
Per-sector score = average of mapped indicator scores.

Reads: macro_indicators
Writes: macro_sector_signals

Usage:
    python -m signals.macro
    python -m signals.macro --dry-run
"""

import argparse
from datetime import date

import pandas as pd

from db import read_sql, upsert_df

# Signal label → numeric score
SIGNAL_SCORES = {
    "STRONG": 80,
    "IMPROVING": 65,
    "STABLE": 50,
    "DETERIORATING": 30,
}

# Sector → which indicators drive it
SECTOR_MAP = {
    "Automobiles":              ["iip_manufacturing", "credit_growth", "gst"],
    "Auto Components":          ["iip_manufacturing", "credit_growth"],
    "Capital Goods":            ["iip_capital_goods", "core_cement", "core_steel"],
    "Cement":                   ["core_cement", "iip_manufacturing"],
    "Chemicals":                ["iip_manufacturing", "core_fertilizers"],
    "Communication Services":   ["gst"],
    "Construction":             ["core_cement", "core_steel", "credit_growth"],
    "Consumer Discretionary":   ["iip_consumer_durables", "gst", "credit_growth"],
    "Consumer Staples":         ["iip_consumer_nondurables", "gst"],
    "Energy":                   ["core_crude_oil", "core_natural_gas", "core_refinery"],
    "Financials":               ["credit_growth", "gst"],
    "Financial Services":       ["credit_growth", "gst"],
    "Health Care":              ["iip_manufacturing", "gst"],
    "Industrials":              ["iip_capital_goods", "core_cement", "core_steel", "credit_growth"],
    "Information Technology":   ["gst"],
    "Materials":                ["core_steel", "core_coal", "iip_mining", "core_cement"],
    "Real Estate":              ["core_cement", "core_steel", "credit_growth"],
    "Utilities":                ["core_electricity", "core_coal"],
}

# Sector signal labels based on score
def _sector_signal(score):
    if score >= 70: return "TAILWIND"
    if score >= 55: return "FAVORABLE"
    if score >= 45: return "NEUTRAL"
    if score >= 30: return "HEADWIND"
    return "ADVERSE"


def compute(dry_run=False):
    """Compute macro sector signals from indicator data."""
    indicators = read_sql("SELECT indicator, signal, detail FROM macro_indicators")

    if indicators.empty:
        print("No macro indicators found.")
        return 0

    # Build indicator → score lookup
    ind_scores = {}
    ind_details = {}
    for _, row in indicators.iterrows():
        label = row["signal"]
        ind_scores[row["indicator"]] = SIGNAL_SCORES.get(label, 50)
        ind_details[row["indicator"]] = row.get("detail", "")

    today = date.today().isoformat()
    rows = []

    for sector, inds in SECTOR_MAP.items():
        scores = [ind_scores[i] for i in inds if i in ind_scores]
        if not scores:
            continue

        macro_score = round(sum(scores) / len(scores), 1)
        signal = _sector_signal(macro_score)
        detail = " | ".join(ind_details.get(i, i) for i in inds if i in ind_scores)

        rows.append({
            "sector": sector,
            "snapshot_date": today,
            "macro_score": macro_score,
            "macro_signal": signal,
            "macro_detail": detail[:500],
        })

    df = pd.DataFrame(rows)

    print(f"Macro Sector: {len(df)} sectors scored")
    for _, r in df.iterrows():
        print(f"  {r['sector']:30s} {r['macro_score']:5.1f}  {r['macro_signal']}")

    if dry_run:
        print("\nDry run — not saving.")
        return len(df)

    n = upsert_df(df, "macro_sector_signals")
    print(f"Saved {n} rows to macro_sector_signals")
    return n


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
