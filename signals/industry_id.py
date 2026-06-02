"""
Alpha Signal v2 — Industry identity code — Plan 0002 §3.2.6 (industry dummies).

A single categorical *control* column: a stable integer code for each stock's
industry. NOT a rankable alpha factor — it carries no directional signal, and a
Spearman IC of an arbitrary integer code against forward return is meaningless.
It exists so downstream model-fitting / scoring can one-hot or neutralise by
industry (the "industry dummies (1)" the plan calls for), and so the PIT panel
carries the as-of industry for sector-relative diagnostics. Hence it is registered
as a CONTROL in BACKTEST_SIGNALS and deliberately kept OUT of SIGNAL_COLUMN_MAP /
the IC roster.

The code mapping is FROZEN (sorted canonical names → 1..N, 0 = unknown/NULL) so
the PIT path and the live path always agree and adding a new stock never shifts
existing codes. A genuinely new industry name maps to 0 until it's added here.

Reads:  stocks (industry)
Returns: DataFrame[sid, industry_id]

Usage:
    python -m signals.industry_id            # compute live + print code table
"""

from __future__ import annotations

import pandas as pd

from db import read_sql

# Frozen canonical industry set (DISTINCT stocks.industry, 2026-06-02). Sorted →
# 1-based code. Append-only: never reorder or delete (would re-key the panel);
# add new names at the end-of-sort naturally by regenerating, only on a deliberate
# migration. 0 is reserved for unknown / NULL.
INDUSTRIES = [
    "Asset Management",
    "Auto Components",
    "Automobiles",
    "Aviation",
    "Banks",
    "Capital Goods & Industrial Machinery",
    "Capital Markets & Exchanges",
    "Cement",
    "Chemicals & Specialty",
    "Construction & Engineering",
    "Consumer Durables",
    "Defence & Aerospace",
    "E-Commerce",
    "FMCG",
    "Food & Beverages",
    "Gas Utilities",
    "Hospitality & Hotels",
    "Hospitals & Diagnostics",
    "IT Services & ITeS",
    "Industrial Services & Misc",
    "Insurance",
    "Iron & Steel",
    "Logistics & Transport",
    "Media & Entertainment",
    "Medical Devices",
    "Mining & Minerals",
    "NBFCs / Finance",
    "Oil & Gas",
    "Paper, Wood & Forest Products",
    "Personal Care & Household Products",
    "Pharmaceuticals",
    "Power Generation",
    "Power T&D",
    "REITs",
    "Real Estate Developers",
    "Retail",
    "Software Products & SaaS",
    "Telecom",
]
INDUSTRY_CODES = {name: i for i, name in enumerate(sorted(INDUSTRIES), start=1)}


def compute_industry_id(stocks: pd.DataFrame | None = None) -> pd.DataFrame:
    """Core: frozen integer code per stock's industry (0 = unknown/NULL).

    `stocks` (sid, industry) is injectable; the PIT path passes the as-of stocks
    frame. When None it's loaded live.

    Returns DataFrame[sid, industry_id].
    """
    cols = ["sid", "industry_id"]
    if stocks is None:
        stocks = read_sql("SELECT sid, industry FROM stocks")
    if stocks is None or stocks.empty:
        return pd.DataFrame(columns=cols)
    out = stocks[["sid"]].copy()
    out["industry_id"] = (
        stocks["industry"].map(INDUSTRY_CODES).fillna(0).astype(int)
        if "industry" in stocks.columns else 0
    )
    return out[cols].reset_index(drop=True)


if __name__ == "__main__":
    out = compute_industry_id()
    print(f"Computed industry_id for {len(out):,} stocks "
          f"({(out['industry_id'] == 0).sum()} unknown/NULL)")
    print(f"  {len(INDUSTRIES)} frozen industries → codes 1..{len(INDUSTRIES)}")
