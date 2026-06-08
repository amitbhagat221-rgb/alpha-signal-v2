"""Import total-comp CSV exports (levels.fyi / AmbitionBox / Blind / manual).

These sources are the PRECISE comp layer (base + bonus + stock by level) but block datacenter
scraping — so the workflow is: export the CSV from the site, drop it in data/imports/, and run
`import-comp`. This importer maps common column names flexibly and normalises to INR/year.
"""

import csv
import hashlib

import config
from comp_intel import store

# flexible column aliases → our canonical fields (lowercased, stripped)
ALIASES = {
    "company":   ["company", "employer", "company name", "organisation"],
    "role":      ["role", "title", "designation", "job title", "position"],
    "level":     ["level", "grade", "tag", "seniority"],
    "location":  ["location", "city", "geo"],
    "years_exp": ["yearsofexperience", "years of experience", "experience", "yoe", "exp"],
    "base":      ["basesalary", "base salary", "base", "fixed"],
    "bonus":     ["bonus", "cash bonus", "variable"],
    "stock":     ["stockgrantvalue", "stock", "equity", "rsu"],
    "total":     ["totalyearlycompensation", "total comp", "total", "ctc", "tc"],
    "currency":  ["currency", "ccy"],
    "as_of":     ["timestamp", "date", "as_of", "year"],
}


def _norm_header(h):
    return (h or "").strip().lower()


def _pick(row, field):
    for alias in ALIASES[field]:
        for k, v in row.items():
            if _norm_header(k) == alias and v not in (None, ""):
                return v
    return None


def _num(v):
    if v is None:
        return None
    s = str(v).replace(",", "").replace("₹", "").replace("$", "").strip()
    # handle "12L" / "1.2Cr" Indian shorthand
    mult = 1.0
    low = s.lower()
    if low.endswith("cr"):
        mult, s = 1e7, low[:-2]
    elif low.endswith("l") or low.endswith("lakh") or low.endswith("lakhs"):
        mult, s = 1e5, low.replace("lakhs", "").replace("lakh", "").rstrip("l")
    elif low.endswith("k"):
        mult, s = 1e3, low[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def _firm_tag(company):
    c = (company or "").lower()
    for f in config.FIRMS:
        if f.lower() in c:
            return f
    return None


def import_csv(path, source="manual"):
    """Import a comp CSV → comp_records. Returns rows written."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            company = _pick(raw, "company")
            base = _num(_pick(raw, "base"))
            bonus = _num(_pick(raw, "bonus"))
            stock = _num(_pick(raw, "stock"))
            total = _num(_pick(raw, "total"))
            if total is None and (base or bonus or stock):
                total = sum(x for x in (base, bonus, stock) if x)
            currency = (_pick(raw, "currency") or "USD").upper()
            fx = config.FX_TO_INR.get(currency, 1.0)
            basis = f"{source}|{company}|{_pick(raw,'level')}|{_pick(raw,'location')}|{total}|{_pick(raw,'as_of')}"
            rows.append({
                "rec_id":    hashlib.md5(basis.encode("utf-8", "replace")).hexdigest()[:20],
                "source":    source,
                "company":   company,
                "firm_tag":  _firm_tag(company),
                "role":      _pick(raw, "role"),
                "level":     _pick(raw, "level"),
                "location":  _pick(raw, "location"),
                "years_exp": _num(_pick(raw, "years_exp")),
                "base":      base,
                "bonus":     bonus,
                "stock":     stock,
                "total":     total,
                "currency":  currency,
                "total_inr": round(total * fx, 0) if total else None,
                "as_of":     str(_pick(raw, "as_of") or ""),
                "raw":       raw,
                "imported_at": store.now(),
            })
    return store.upsert("comp_records", rows, "rec_id")
