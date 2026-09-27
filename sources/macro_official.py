"""
Alpha Signal v2 — official Indian macro series (IIP, CPI, Eight Core) + macro labels.

Replaced data.gov.in on 2026-09-27: its gateway 502s / times out, and the IIP, CPI
and core-sector datasets it served had stopped updating (Feb-2023 … Jul-2024).

  IIP   MoSPI API  GET https://api.mospi.gov.in/api/iip/getIipData
        base 2022-23, monthly, General + Sectoral + Use-based categories
  CPI   MoSPI API  GET https://api.mospi.gov.in/api/cpi/getCPIData
        base 2024 "Current" series (2025→), All-India Combined, General + 12 divisions
  Core  Office of the Economic Adviser, Index of Eight Core Industries (base 2022-23):
        the newest eight_core_infra/Core_Industries_2022_23_<YYYYMMDD>.xlsx listed on
        https://eaindustry.nic.in/ici_download_data.asp (Index + Growth sheets)

YoY comes from the publisher's own growth/inflation columns — never recomputed from
index levels, which break at every base-year change. No API key; both hosts need a
browser TLS client (hosts.HOSTS "impersonate"). MoSPI reference: nso-india/esankhyiki-mcp.

Also rebuilds `macro_indicators` (the per-indicator STRONG / IMPROVING / STABLE /
DETERIORATING labels signals/macro.py turns into sector scores). It had no producer
after the v1 migration — frozen at 2026-04-09, incl. a hard-coded v1 "credit_growth
11.5%" fallback. Thresholds are v1's (scripts/14_macro_pulse.py). An indicator whose
latest month is older than LABEL_MAX_AGE_DAYS gets no label, so a dead feed drops
out of the sector scores instead of freezing them.

Writes: macro_history, macro_indicator_meta, macro_indicators
Usage:  python -m sources.macro_official [--dry-run]
"""

import argparse
import io
import re
from datetime import date, timedelta

import pandas as pd

from db import read_sql, upsert_df
from sources import _http

MOSPI = "https://api.mospi.gov.in"
OEA_PAGE = "https://eaindustry.nic.in/ici_download_data.asp"
OEA_BASE = "https://eaindustry.nic.in/"
IIP_FIRST_YEAR = 2023          # base 2022-23 starts Apr-2023
CPI_FIRST = (2025, 1)          # base-2024 "Current" series starts Jan-2025
LABEL_MAX_AGE_DAYS = 150       # IIP/core publish ~6-8 weeks after the month
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}

IIP_IDS = {
    "general": "iip_general", "mining": "iip_mining", "manufacturing": "iip_manufacturing",
    "electricity": "iip_electricity",
    "water supply, sewerage & waste management": "iip_water_supply",
    "primary goods": "iip_primary_goods", "capital goods": "iip_capital_goods",
    "intermediate goods": "iip_intermediate_goods",
    "infrastructure/ construction goods": "iip_infrastructure_goods",
    "consumer durables": "iip_consumer_durables", "consumer non-durables": "iip_consumer_nondurables",
}
CPI_IDS = {
    "cpi (general)": "cpi_general", "food and beverages": "cpi_food_beverages",
    "paan, tobacco and intoxicants": "cpi_paan_tobacco", "clothing and footwear": "cpi_clothing_footwear",
    "housing, water, electricity, gas and other fuels": "cpi_housing_fuel",
    "furnishings, household equipment and routine household maintenance": "cpi_household",
    "health": "cpi_health", "transport": "cpi_transport",
    "information and communication": "cpi_info_communication",
    "recreation, sport and culture": "cpi_recreation", "education services": "cpi_education",
    "restaurants and accommodation services": "cpi_restaurants",
    "personal care, social protection and miscellaneous goods and services": "cpi_personal_misc",
}
# Core-sheet column header (lower, prefix) → id. Names match the v1 labels
# signals/macro.py maps sectors to (core_fertilizers, core_crude_oil, …).
CORE_IDS = [("overall", "core_combined"), ("coal", "core_coal"), ("natural gas", "core_natural_gas"),
            ("crude oil", "core_crude_oil"), ("refinery", "core_refinery"),
            ("fertilizer", "core_fertilizers"), ("steel", "core_steel"), ("cement", "core_cement"),
            ("electricity", "core_electricity"), ("iron ore", "core_iron_ore")]


def _iip_id(cat):
    """MoSPI names sectors "Mining & Quarrying" / "Electricity, Gas, Steam …"; keep the
    short ids the sector map and the old series use."""
    c = cat.strip().lower()
    for prefix, ind in (("mining", "iip_mining"), ("electricity", "iip_electricity")):
        if c.startswith(prefix):
            return ind
    return IIP_IDS.get(c, _slug("iip_", cat))


def _slug(prefix, name):
    return prefix + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _mospi(sess, path, **params):
    r = _http.polite_get(MOSPI + path, session=sess, params={**params, "Format": "JSON"}, timeout=90)
    return r.json() if r is not None else {}


# ─────────────────────────────── fetchers ───────────────────────────────

def fetch_iip(sess, first_year=IIP_FIRST_YEAR):
    """Category-level IIP index + official YoY growth, monthly, base 2022-23."""
    rows = []
    for year in range(first_year, date.today().year + 1):
        page, pages = 1, 1
        while page <= pages:
            j = _mospi(sess, "/api/iip/getIipData", base_year="2022-23", frequency="Monthly",
                       type="All", year=str(year), limit=200, page=str(page))
            pages = (j.get("meta_data") or {}).get("totalPages") or 0
            for x in j.get("data") or []:
                if (x.get("sub_category") or "").strip():
                    continue                            # category level only
                cat = (x.get("category") or "").strip()
                month = MONTHS.get((x.get("month") or "").strip().lower())
                if not cat or not month:
                    continue
                rows.append({"indicator_id": _iip_id(cat),
                             "date": f"{int(x['year']):04d}-{month:02d}-01",
                             "value": _num(x.get("index")), "yoy_change": _num(x.get("growth_rate")),
                             "source": "mospi", "category": "coincident", "unit": "index",
                             "_name": f"IIP {cat}", "_ref": "mospi iip base 2022-23"})
            page += 1
    return rows


def fetch_cpi(sess, start=CPI_FIRST):
    """All-India Combined CPI (General + 12 divisions) index + official YoY inflation,
    base 2024, one small request per month from `start` until a month has no data."""
    rows = []
    y, m = start
    today = date.today()
    while (y, m) <= (today.year, today.month):
        j = _mospi(sess, "/api/cpi/getCPIData", base_year="2024", series="Current", year=str(y),
                   month_code=str(m), state_code="1", sector_code="3", limit=20, page="1")
        divs = [x for x in (j.get("data") or []) if x.get("group") is None and x.get("division")]
        if not divs:
            break                                        # not released yet
        for x in divs:
            div = x["division"].strip()
            rows.append({"indicator_id": CPI_IDS.get(div.lower(), _slug("cpi_", div)),
                         "date": f"{y:04d}-{m:02d}-01",
                         "value": _num(x.get("index")), "yoy_change": _num(x.get("inflation")),
                         "source": "mospi", "category": "lagging", "unit": "index",
                         "_name": f"CPI {div}", "_ref": "mospi cpi base 2024 (All India, Combined)"})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return rows


def _core_sheet(df):
    """{indicator_id: {YYYY-MM-01: value}} from an OEA Index/Growth sheet."""
    hdr_i = next(i for i in range(len(df)) if str(df.iat[i, 0]).strip().lower() == "months/years")
    cols = {}
    for j, h in enumerate(df.iloc[hdr_i]):
        h = str(h).strip().lower()
        for key, ind in CORE_IDS:
            if h.startswith(key):
                cols[j] = ind
                break
    out = {ind: {} for ind in cols.values()}
    for i in range(hdr_i + 1, len(df)):
        c0 = df.iat[i, 0]
        if isinstance(c0, (pd.Timestamp, date)):
            d = pd.Timestamp(c0)
        elif re.fullmatch(r"[A-Za-z]{3}-\d{2}", str(c0).strip()):
            d = pd.to_datetime(str(c0).strip(), format="%b-%y")
        else:
            continue                                     # FY summary rows etc.
        for j, ind in cols.items():
            v = _num(df.iat[i, j])
            if v is not None:
                out[ind][d.strftime("%Y-%m-01")] = v
    return out


def fetch_core(sess):
    """Index of Eight Core Industries (+ iron ore), base 2022-23, from OEA's newest Excel."""
    page = _http.polite_get(OEA_PAGE, session=sess, timeout=60)
    links = re.findall(r"eight_core_infra/Core_Industries_2022_23_(\d{8})\.xlsx", page.text if page else "")
    if not links:
        raise RuntimeError("OEA: no Core_Industries_2022_23_*.xlsx link on ici_download_data.asp")
    url = f"{OEA_BASE}eight_core_infra/Core_Industries_2022_23_{max(links)}.xlsx"
    xls = pd.ExcelFile(io.BytesIO(_http.polite_get(url, session=sess, timeout=90).content))
    index = _core_sheet(xls.parse("Index", header=None))
    growth = _core_sheet(xls.parse(next(s for s in xls.sheet_names if s.lower().startswith("growth")),
                                   header=None))
    rows = []
    for ind, series in index.items():
        for d, v in series.items():
            rows.append({"indicator_id": ind, "date": d, "value": v,
                         "yoy_change": growth.get(ind, {}).get(d), "source": "oea",
                         "category": "coincident", "unit": "index",
                         "_name": f"Core {ind[5:].replace('_', ' ').title()}",
                         "_ref": f"OEA ICI base 2022-23 ({max(links)})"})
    return rows


# ─────────────────────────────── labels ───────────────────────────────

def _label(yoy):
    """v1 macro_pulse thresholds for IIP / core-sector YoY (%)."""
    if yoy > 5:
        return "STRONG"
    if yoy > 2:
        return "IMPROVING"
    if yoy > -2:
        return "STABLE"
    return "DETERIORATING"


def build_labels(latest, today):
    """macro_indicators rows from {indicator_id: (date, yoy)} for IIP + core series
    no older than LABEL_MAX_AGE_DAYS, plus v1's macro_overall pulse."""
    cutoff = (today - timedelta(days=LABEL_MAX_AGE_DAYS)).isoformat()
    rows = []
    for ind, (d, yoy) in sorted(latest.items()):
        if not ind.startswith(("iip_", "core_")) or yoy is None or d < cutoff:
            continue
        rows.append({"indicator": ind, "signal": _label(yoy), "value": round(yoy, 2),
                     "detail": f"{ind}: {yoy:+.1f}% YoY ({pd.Timestamp(d):%b %Y})",
                     "snapshot_date": today.isoformat()})
    if rows:
        pts = {"STRONG": 2, "IMPROVING": 1, "STABLE": 0, "DETERIORATING": -1}
        avg = sum(pts[r["signal"]] for r in rows) / len(rows)
        overall = ("STRONG_EXPANSION" if avg > 1 else "EXPANDING" if avg > 0.3 else
                   "NEUTRAL" if avg > -0.3 else "SLOWING" if avg > -1 else "CONTRACTING")
        rows.append({"indicator": "macro_overall", "signal": overall, "value": round(avg, 2),
                     "detail": f"Macro Pulse: {overall} (avg score: {avg:.2f})",
                     "snapshot_date": today.isoformat()})
    return rows


# ─────────────────────────────── entry ───────────────────────────────

def fetch_all(dry_run=False):
    """Fetch IIP, CPI and core; write macro_history + meta + macro_indicators.
    Returns rows fetched. Each dataset fails on its own (printed); the caller
    raises when the total is 0."""
    mospi = _http.session(MOSPI)
    oea = _http.session(OEA_BASE)
    have = read_sql("SELECT indicator_id, MAX(date) d FROM macro_history "
                    "WHERE source IN ('mospi', 'oea') GROUP BY indicator_id")
    have = dict(zip(have["indicator_id"], have["d"]))
    # Re-pull a trailing window only (publishers revise the last 1-2 prints).
    iip_from = int(have["iip_general"][:4]) - 1 if "iip_general" in have else IIP_FIRST_YEAR
    cpi_from = CPI_FIRST
    if "cpi_general" in have:
        d = pd.Timestamp(have["cpi_general"]) - pd.DateOffset(months=2)
        cpi_from = max(CPI_FIRST, (d.year, d.month))

    rows = []
    for name, fn in (("IIP", lambda: fetch_iip(mospi, max(IIP_FIRST_YEAR, iip_from))),
                     ("CPI", lambda: fetch_cpi(mospi, cpi_from)),
                     ("Core", lambda: fetch_core(oea))):
        try:
            got = fn()
            print(f"  {name}: {len(got)} rows, latest {max((r['date'] for r in got), default='—')}")
            rows += got
        except Exception as e:
            print(f"  {name} FAILED: {type(e).__name__}: {str(e)[:160]}")
    if not rows or dry_run:
        return len(rows)

    # mom_change set to NULL explicitly: a column upsert over an old data.gov.in row
    # (core, 2023-04→2024-07) would otherwise keep MoM computed on the old base.
    df = pd.DataFrame(rows).assign(mom_change=None)
    upsert_df(df[["indicator_id", "date", "value", "yoy_change", "mom_change", "source",
                  "category", "unit"]], "macro_history")
    meta = (df.drop_duplicates("indicator_id")
              .rename(columns={"_name": "name", "_ref": "source_ref"})
              .assign(frequency="monthly",
                      description=lambda d: d["name"] + " — official, YoY from the publisher"))
    upsert_df(meta[["indicator_id", "name", "source", "source_ref", "category", "frequency",
                    "unit", "description"]], "macro_indicator_meta")

    latest = read_sql("SELECT h.indicator_id, h.date, h.yoy_change FROM macro_history h "
                      "JOIN (SELECT indicator_id, MAX(date) d FROM macro_history "
                      "      WHERE source IN ('mospi', 'oea') AND yoy_change IS NOT NULL "
                      "      GROUP BY indicator_id) m "
                      "ON h.indicator_id = m.indicator_id AND h.date = m.d")
    labels = build_labels({r.indicator_id: (r.date, r.yoy_change) for r in latest.itertuples()},
                          date.today())
    if labels:
        upsert_df(pd.DataFrame(labels), "macro_indicators")
    print(f"official macro: {len(df)} macro_history rows · {len(labels)} macro_indicators labels")
    return len(rows)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="fetch + parse, no write")
    fetch_all(dry_run=p.parse_args().dry_run)
