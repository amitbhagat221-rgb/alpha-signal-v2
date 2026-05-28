"""
Alpha Signal v2 — AMFI Mutual Fund scheme master ingest.

Source: https://www.amfiindia.com/spages/NAVAll.txt — single pipe-delimited
public file with every active MF scheme + today's NAV. AMFI publishes this
each business day around 6pm IST.

File layout:
    Scheme Code;ISIN Growth;ISIN Div Reinvest;Scheme Name;NAV;Date  ← header
    <blank>
    Open Ended Schemes(Debt Scheme - Banking and PSU Fund)         ← category line
    <blank>
    Aditya Birla Sun Life Mutual Fund                              ← AMC line
    <blank>
    119551;INF209KA12Z1;INF209KA13Z9;Aditya Birla...;104.5269;26-May-2026
    ... (more schemes for this AMC)
    <blank>
    Axis Mutual Fund                                                ← next AMC
    ...

This module's `parse_navall(text)` is shared by:
  - `sources/mf_amfi_master.py`  → writes `mf_scheme_master` (universe sync)
  - `sources/mf_nav_daily.py`    → writes `mf_nav_history`   (daily NAV upsert)

Usage:
    python -m sources.mf_amfi_master              # weekly: refresh universe
    python -m sources.mf_amfi_master --dry-run    # parse + report, no DB write
"""

import argparse
import re
import sys
import time
from datetime import datetime, date as _date
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import get_db, upsert_df

NAVALL_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
TIMEOUT = 60
HEADERS = {"User-Agent": "Mozilla/5.0 alpha-signal-v2/1.0"}

# Category header lines look like:  "Open Ended Schemes(Equity Scheme - Multi Cap Fund)"
_CATEGORY_RE = re.compile(r"^(Open Ended|Close Ended|Interval Fund) Schemes?\s*\((.+)\)\s*$")

# Plan / option detection from scheme name. Order matters: "Direct" before "Regular"
# (some names contain both due to fund-of-funds naming weirdness; first-match wins).
_PLAN_PATTERNS = [
    ("DIRECT",  re.compile(r"\b(direct(?:\s+plan)?)\b", re.I)),
    ("REGULAR", re.compile(r"\b(regular(?:\s+plan)?|retail)\b", re.I)),
]
_OPTION_PATTERNS = [
    ("IDCW",   re.compile(r"\b(idcw|dividend|income\s+distribution)\b", re.I)),
    ("GROWTH", re.compile(r"\bgrowth\b", re.I)),
]


def _detect(name: str, patterns) -> str:
    for label, regex in patterns:
        if regex.search(name or ""):
            return label
    return "UNKNOWN"


# ─── Category normalisation: SEBI 36-category taxonomy → our compact labels ───
#
# Pattern: "<Family> / <Sub>" so equity-vs-debt-vs-hybrid is one glance.
# Unknown strings fall through to category_raw (no map entry).
# Revisit annually when SEBI reclassifies.

CATEGORY_MAP = {
    # Equity
    "Equity Scheme - Large Cap Fund":              "Equity / Large Cap",
    "Equity Scheme - Large & Mid Cap Fund":        "Equity / Large & Mid Cap",
    "Equity Scheme - Mid Cap Fund":                "Equity / Mid Cap",
    "Equity Scheme - Small Cap Fund":              "Equity / Small Cap",
    "Equity Scheme - Multi Cap Fund":              "Equity / Multi Cap",
    "Equity Scheme - Flexi Cap Fund":              "Equity / Flexi Cap",
    "Equity Scheme - ELSS":                        "Equity / ELSS",
    "Equity Scheme - Value Fund":                  "Equity / Value",
    "Equity Scheme - Contra Fund":                 "Equity / Contra",
    "Equity Scheme - Focused Fund":                "Equity / Focused",
    "Equity Scheme - Dividend Yield Fund":         "Equity / Dividend Yield",
    "Equity Scheme - Sectoral/ Thematic":          "Equity / Sectoral-Thematic",
    "Equity Scheme - Sectoral / Thematic":         "Equity / Sectoral-Thematic",
    "ELSS":                                        "Equity / ELSS",
    # Income Scheme (legacy SEBI category — pre-2017 funds still labeled this way)
    "Income":                                      "Debt / Income (legacy)",
    "Income Scheme":                               "Debt / Income (legacy)",
    "Gilt":                                        "Debt / Gilt",
    "Money Market":                                "Debt / Money Market",
    # Debt
    "Debt Scheme - Liquid Fund":                   "Debt / Liquid",
    "Debt Scheme - Overnight Fund":                "Debt / Overnight",
    "Debt Scheme - Ultra Short Duration Fund":     "Debt / Ultra Short",
    "Debt Scheme - Low Duration Fund":             "Debt / Low Duration",
    "Debt Scheme - Money Market Fund":             "Debt / Money Market",
    "Debt Scheme - Short Duration Fund":           "Debt / Short Duration",
    "Debt Scheme - Medium Duration Fund":          "Debt / Medium Duration",
    "Debt Scheme - Medium to Long Duration Fund":  "Debt / Medium-Long",
    "Debt Scheme - Long Duration Fund":            "Debt / Long Duration",
    "Debt Scheme - Dynamic Bond Fund":             "Debt / Dynamic Bond",
    "Debt Scheme - Dynamic Bond":                  "Debt / Dynamic Bond",
    "Debt Scheme - Corporate Bond Fund":           "Debt / Corporate Bond",
    "Debt Scheme - Credit Risk Fund":              "Debt / Credit Risk",
    "Debt Scheme - Banking and PSU Fund":          "Debt / Banking & PSU",
    "Debt Scheme - Gilt Fund":                     "Debt / Gilt",
    "Debt Scheme - Gilt Fund with 10 year constant duration": "Debt / Gilt 10Y",
    "Debt Scheme - Floater Fund":                  "Debt / Floater",
    # Hybrid
    "Hybrid Scheme - Conservative Hybrid Fund":    "Hybrid / Conservative",
    "Hybrid Scheme - Balanced Hybrid Fund":        "Hybrid / Balanced",
    "Hybrid Scheme - Aggressive Hybrid Fund":      "Hybrid / Aggressive",
    "Hybrid Scheme - Dynamic Asset Allocation or Balanced Advantage": "Hybrid / BAF",
    "Hybrid Scheme - Multi Asset Allocation":      "Hybrid / Multi-Asset",
    "Hybrid Scheme - Arbitrage Fund":              "Hybrid / Arbitrage",
    "Hybrid Scheme - Equity Savings":              "Hybrid / Equity Savings",
    # Index / ETF
    "Other Scheme - Index Funds":                  "Index / Equity",
    "Other Scheme - Gold ETF":                     "ETF / Gold",
    "Other Scheme - Other ETFs":                   "ETF / Other",
    "Other Scheme - Other  ETFs":                  "ETF / Other",   # AMFI source has double space
    "Other Scheme - Index Fund":                   "Index / Equity",
    "Growth":                                      "Equity / Growth (legacy)",
    "Other Scheme - FoF Domestic":                 "FoF / Domestic",
    "Other Scheme - FoF Overseas":                 "FoF / Overseas",
    # Solution oriented
    "Solution Oriented Scheme - Retirement Fund":  "Solution / Retirement",
    "Solution Oriented Scheme - Childrens Fund":   "Solution / Children",
    "Solution Oriented Scheme - Children's Fund":  "Solution / Children",
}


def _normalise_category(raw: str) -> str:
    if not raw:
        return None
    raw = raw.strip()
    if raw in CATEGORY_MAP:
        return CATEGORY_MAP[raw]
    # Fall through — keep raw, lowercased family prefix for sortability
    return raw


def _parse_date(s: str) -> str | None:
    """'26-May-2026' → '2026-05-26'."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


# ─── Core parser — shared by master + daily ──────────────────────────────────


def parse_navall(text: str) -> list[dict]:
    """Parse NAVAll.txt body. Returns one dict per scheme with keys:
      scheme_code, isin_growth, isin_div, scheme_name, amc, category_raw,
      category_norm, plan_type, option_type, nav, nav_date.
    """
    rows: list[dict] = []
    current_category_raw = None
    current_amc = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Skip the file header
        if line.startswith("Scheme Code"):
            continue

        # Category header line?
        m = _CATEGORY_RE.match(line)
        if m:
            current_category_raw = m.group(2).strip()
            continue

        # Pipe-delimited scheme data?
        if ";" in line:
            parts = line.split(";")
            if len(parts) < 6:
                continue
            code = parts[0].strip()
            if not code.isdigit():
                continue
            isin_growth = parts[1].strip() or None
            isin_div = parts[2].strip() or None
            if isin_growth == "-":
                isin_growth = None
            if isin_div == "-":
                isin_div = None
            scheme_name = parts[3].strip()
            try:
                nav = float(parts[4].strip()) if parts[4].strip() not in ("", "N.A.", "-") else None
            except ValueError:
                nav = None
            nav_date = _parse_date(parts[5])

            rows.append({
                "scheme_code":   code,
                "isin_growth":   isin_growth,
                "isin_div":      isin_div,
                "scheme_name":   scheme_name,
                "amc":           current_amc,
                "category_raw":  current_category_raw,
                "category_norm": _normalise_category(current_category_raw),
                "plan_type":     _detect(scheme_name, _PLAN_PATTERNS),
                "option_type":   _detect(scheme_name, _OPTION_PATTERNS),
                "nav":           nav,
                "nav_date":      nav_date,
            })
            continue

        # Otherwise it's an AMC name line (e.g. "Axis Mutual Fund")
        current_amc = line

    return rows


def fetch_navall_text() -> str:
    """Single HTTP fetch of NAVAll.txt with retry. Returns the text body."""
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(NAVALL_URL, timeout=TIMEOUT, headers=HEADERS)
            if r.status_code == 200 and r.text:
                return r.text
            last_err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last_err = str(e)
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to fetch NAVAll.txt after 3 attempts: {last_err}")


# ─── Master ingest (this module's primary entry point) ───────────────────────


def compute(dry_run: bool = False) -> int:
    """Refresh mf_scheme_master from NAVAll.txt.

    Strategy:
      - Fetch NAVAll.txt (~2 MB, <2s)
      - Parse all scheme rows
      - Upsert into mf_scheme_master (PK scheme_code)
      - Mark schemes that DIDN'T appear today as `active=0` if last_seen >7d old
        (keeps history of wound-down funds visible but flagged)
    """
    print(f"Fetching {NAVALL_URL}…")
    text = fetch_navall_text()
    print(f"  {len(text):,} bytes received")

    rows = parse_navall(text)
    print(f"Parsed {len(rows)} scheme rows")
    if not rows:
        raise RuntimeError("Parsed 0 schemes — file format may have changed")

    today_iso = _date.today().isoformat()
    df = pd.DataFrame(rows)
    df["last_seen"] = today_iso
    df["active"]    = 1
    df["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Quick category breakdown
    print("\nCategory family breakdown:")
    fams = df["category_norm"].fillna("UNMAPPED").str.split(" / ").str[0].value_counts().head(10)
    for k, v in fams.items():
        print(f"  {k:25s} {v}")

    n_unmapped = df["category_norm"].isna().sum()
    if n_unmapped:
        print(f"\n{n_unmapped} schemes have unmapped categories — sample:")
        for raw in df.loc[df["category_norm"].isna(), "category_raw"].dropna().unique()[:5]:
            print(f"  '{raw}'")

    if dry_run:
        print("\n--dry-run: not saving.")
        return len(df)

    # Master columns the table accepts (drop nav/nav_date — those belong to mf_nav_history)
    master_cols = [
        "scheme_code", "isin_growth", "isin_div", "scheme_name", "amc",
        "category_raw", "category_norm", "plan_type", "option_type",
        "last_seen", "active", "fetched_at",
    ]
    n = upsert_df(df[master_cols], "mf_scheme_master")
    print(f"\nWrote {n} rows to mf_scheme_master")

    # Flag stale schemes (last_seen > 7d ago and not seen today). Soft-delete via active=0.
    with get_db() as conn:
        conn.execute("""
            UPDATE mf_scheme_master
            SET active = 0
            WHERE last_seen IS NOT NULL
              AND last_seen < date('now', '-7 day')
              AND active = 1
        """)
        n_inactive = conn.execute("SELECT COUNT(*) FROM mf_scheme_master WHERE active=0").fetchone()[0]
    print(f"Inactive flagged: {n_inactive}")

    return n


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Parse + report; don't write DB")
    args = p.parse_args()
    compute(dry_run=args.dry_run)
