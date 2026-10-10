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
from datetime import datetime, date as _date

import pandas as pd
import requests


from db import get_db, upsert_df
from sources._http import polite_get

NAVALL_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
TIMEOUT = 60

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


# AMFI has relabelled its categories more than once and old funds keep the label they were
# filed under, so one family shows up as "Equity Scheme - X", "Equity Schemes - X",
# "Hybrid Schemes - X", "Income/Debt Oriented Schemes - X" ... All spellings merge into one
# compact label so peers, ranks and presets see one group.
CATEGORY_MAP.update({
    "Equity Schemes - Large Cap Fund":              "Equity / Large Cap",
    "Equity Schemes - Large & Mid Cap Fund":        "Equity / Large & Mid Cap",
    "Equity Schemes - Mid Cap Fund":                "Equity / Mid Cap",
    "Equity Schemes - Small Cap Fund":              "Equity / Small Cap",
    "Equity Schemes - Multi Cap Fund":              "Equity / Multi Cap",
    "Equity Schemes - Flexi Cap Fund":              "Equity / Flexi Cap",
    "Equity Schemes - ELSS- Tax Saver Fund":        "Equity / ELSS",
    "Equity Schemes - Value Fund":                  "Equity / Value",
    "Equity Schemes - Contra Fund":                 "Equity / Contra",
    "Equity Schemes - Focused Fund":                "Equity / Focused",
    "Equity Schemes - Dividend Yield Fund":         "Equity / Dividend Yield",
    "Equity Schemes - Sectoral Fund":               "Equity / Sectoral-Thematic",
    "Equity Schemes - Thematic Fund":               "Equity / Sectoral-Thematic",
    "Hybrid Schemes - Aggressive Hybrid Fund":      "Hybrid / Aggressive",
    "Hybrid Schemes - Arbitrage Fund":              "Hybrid / Arbitrage",
    "Hybrid Schemes - Balanced Advantage Fund/ Dynamic Asset Allocation": "Hybrid / BAF",
    "Hybrid Schemes - Balanced Hybrid Fund":        "Hybrid / Balanced",
    "Hybrid Schemes - Conservative Hybrid Fund":    "Hybrid / Conservative",
    "Hybrid Schemes - Equity Savings Fund":         "Hybrid / Equity Savings",
    "Hybrid Schemes - Multi Asset Allocation Fund": "Hybrid / Multi-Asset",
    "Income/Debt Oriented Schemes - 10-year Constant Maturity Gilt Fund": "Debt / Gilt 10Y",
    "Income/Debt Oriented Schemes - Banking and PSU Debt Fund": "Debt / Banking & PSU",
    "Income/Debt Oriented Schemes - Corporate Bond Fund":       "Debt / Corporate Bond",
    "Income/Debt Oriented Schemes - Credit Risk Fund":          "Debt / Credit Risk",
    "Income/Debt Oriented Schemes - Dynamic Term Fund":         "Debt / Dynamic Bond",
    "Income/Debt Oriented Schemes - Fixed Term Plan":           "Debt / Other",
    "Income/Debt Oriented Schemes - Floating Interest Rates Fund": "Debt / Floater",
    "Income/Debt Oriented Schemes - Gilt Fund":                 "Debt / Gilt",
    "Income/Debt Oriented Schemes - Liquid Fund":               "Debt / Liquid",
    "Income/Debt Oriented Schemes - Long Term Fund":            "Debt / Long Duration",
    "Income/Debt Oriented Schemes - Medium Term Fund":          "Debt / Medium Duration",
    "Income/Debt Oriented Schemes - Medium to Long Term Fund":  "Debt / Medium-Long",
    "Income/Debt Oriented Schemes - Money Market Fund":         "Debt / Money Market",
    "Income/Debt Oriented Schemes - Other Debt Scheme":         "Debt / Other",
    "Income/Debt Oriented Schemes - Sectoral Fund":             "Debt / Other",
    "Income/Debt Oriented Schemes - Overnight Fund":            "Debt / Overnight",
    "Income/Debt Oriented Schemes - Short Term Fund":           "Debt / Short Duration",
    "Income/Debt Oriented Schemes - Ultra Short Term Fund":     "Debt / Ultra Short",
    "Income/Debt Oriented Schemes - Ultra Short to Short Term Fund": "Debt / Ultra Short",
    "Index Funds - Equity Funds":                   "Index / Equity",
    "Index Funds - Debt Funds":                     "Index / Debt",
    "Index Funds - Hybrid Fund":                    "Index / Hybrid",
    "Exchange Traded Funds (ETFs) - Equity ETF":    "ETF / Equity",
    "Exchange Traded Funds (ETFs) - Debt ETF":      "ETF / Debt",
    "Exchange Traded Funds (ETFs) - Gold ETF":      "ETF / Gold",
    "Exchange Traded Funds (ETFs) - Silver ETF":    "ETF / Silver",
    "Exchange Traded Funds (ETFs) - Hybrid ETF":    "ETF / Hybrid",
    "Exchange Traded Funds (ETFs) - ETFs investing overseas": "ETF / Overseas",
    "Exchange Traded Funds (ETFs) - Other ETF":     "ETF / Other",
    "Fund of Funds Scheme (Domestic) - Fund of Funds Scheme (Domestic)": "FoF / Domestic",
    "Overseas Fund of Funds - Fund of Funds investing overseas":         "FoF / Overseas",
    "Solution Oriented Scheme - Children’s Fund":  "Solution / Children",
    "Children’s Fund - Childrens' Fund":           "Solution / Children",
    "Solution Oriented Schemes ** - Retirement Fund": "Solution / Retirement",
    "Life Cycle Funds - Life Cycle Fund with Maturity of 5 Years":  "Solution / Life Cycle",
    "Life Cycle Funds - Life Cycle Fund with Maturity of 10 Years": "Solution / Life Cycle",
    "Life Cycle Funds - Life Cycle Fund with Maturity of 15 Years": "Solution / Life Cycle",
})

# An index fund's category says "index", not what it tracks. A Nifty 50 spread and a peer rank
# among Nifty trackers mean nothing for a NASDAQ 100 fund or a gilt/SDL target-maturity fund,
# so those get their own groups, decided from the scheme name (the only place AMFI says it).
_OVERSEAS_INDEX_RE = re.compile(
    r"nasdaq|s&p\s*500|hang\s*seng|nikkei|\bfang\b|\bus\b|\bu\.s\.|world|global|overseas|"
    r"international|developed|emerging|\bchina\b|\beurope|\bjapan|\btaiwan", re.I)
_DEBT_INDEX_RE = re.compile(r"gilt|\bsdl\b|g-?sec|bond|\bibx\b|maturity|liquid|overnight|treasury", re.I)


def _normalise_category(raw: str, name: str | None = None) -> str:
    if not raw:
        return None
    raw = raw.strip()
    norm = CATEGORY_MAP.get(raw, raw)    # an unknown label keeps its raw text (test_mf_categories fails on it)
    if norm == "Index / Equity" and name:
        if _DEBT_INDEX_RE.search(name):
            return "Index / Debt"
        if _OVERSEAS_INDEX_RE.search(name):
            return "Index / Overseas"
    return norm


def renormalise_master() -> int:
    """Re-derive category_norm for every stored scheme from category_raw + name after the map
    changed. One-column UPDATE on this producer's own table; returns rows changed."""
    with get_db() as conn:
        rows = conn.execute("SELECT scheme_code, category_raw, scheme_name, category_norm "
                            "FROM mf_scheme_master").fetchall()
        ups = [(n, r[0]) for r in rows if (n := _normalise_category(r[1], r[2])) != r[3]]
        conn.executemany("UPDATE mf_scheme_master SET category_norm=? WHERE scheme_code=?", ups)
        conn.commit()
    return len(ups)


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
    # Column positions come from the header row. ~2026-08-19 AMFI inserted
    # `Plan;Option` before NAV (6 → 8 cols); fixed indexes silently parsed
    # "Direct Plan" as the NAV and every row came back NAV-less. Defaults = legacy layout.
    col = {"name": 3, "plan": None, "option": None, "nav": 4, "date": 5}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Scheme Code"):
            hdr = [h.strip().lower() for h in line.split(";")]
            col = {
                "name":   hdr.index("scheme name"),
                "plan":   hdr.index("plan") if "plan" in hdr else None,
                "option": hdr.index("option") if "option" in hdr else None,
                "nav":    hdr.index("net asset value"),
                "date":   hdr.index("date"),
            }
            continue

        # Category header line?
        m = _CATEGORY_RE.match(line)
        if m:
            current_category_raw = m.group(2).strip()
            continue

        # Pipe-delimited scheme data?
        if ";" in line:
            parts = line.split(";")
            if len(parts) <= max(col["nav"], col["date"]):
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
            scheme_name = parts[col["name"]].strip()
            # Plan/option now have their own columns; append them so _detect
            # sees "Direct Plan"/"Growth Option" even when the name omits them.
            detect_text = " ".join(
                [scheme_name] + [parts[col[k]] for k in ("plan", "option") if col[k] is not None]
            )
            nav_raw = parts[col["nav"]].strip()
            try:
                nav = float(nav_raw) if nav_raw not in ("", "N.A.", "-") else None
            except ValueError:
                nav = None
            nav_date = _parse_date(parts[col["date"]])

            rows.append({
                "scheme_code":   code,
                "isin_growth":   isin_growth,
                "isin_div":      isin_div,
                "scheme_name":   scheme_name,
                "amc":           current_amc,
                "category_raw":  current_category_raw,
                "category_norm": _normalise_category(current_category_raw, scheme_name),
                "plan_type":     _detect(detect_text, _PLAN_PATTERNS),
                "option_type":   _detect(detect_text, _OPTION_PATTERNS),
                "nav":           nav,
                "nav_date":      nav_date,
            })
            continue

        # Otherwise it's an AMC name line (e.g. "Axis Mutual Fund")
        current_amc = line

    return rows


def fetch_navall_text() -> str:
    """Single HTTP fetch of NAVAll.txt (polite_get: 3 attempts on timeout/5xx).
    Returns the text body; raises if AMFI didn't serve a non-empty file."""
    try:
        r = polite_get(NAVALL_URL, timeout=TIMEOUT, retries=2)
    except requests.RequestException as e:
        raise RuntimeError(f"Failed to fetch NAVAll.txt: {e}")
    if r is None or not r.content:
        raise RuntimeError("Failed to fetch NAVAll.txt: 404 or empty body")
    # Server sends no charset → requests guesses latin-1 → mojibake.
    return r.content.decode("utf-8", errors="replace")


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
