"""
Industry audit against a second source (Amit 2026-10-17: "this is a textiles company not a paper wood
company" → "yes please").

stocks.industry was set by a closed-set LLM pick from ticker + name only (tools/classify_industries.py),
and the 38-industry list had no textiles industry, so every textile company landed in the nearest offered
bucket (mills → "Paper, Wood & Forest Products", fibre makers → Chemicals, brands → Retail / Consumer
Durables). NSE's own quote page holds the exchange's 4-level classification but its WAF answers 403 to this
server (2026-10-17), so the second source is the industry category in each stock's Moneycontrol page slug,
already stored in stocks.mc_slug (2,258 of 2,448 stocks).

Rules:
  • a slug counts only when its company token matches the stock (else the slug points at another company —
    TRIDENT's points at Trent); unverified slugs are listed, never used
  • MC_ACCEPTS maps a Moneycontrol category to the set of our industries it is compatible with; a category
    that is too vague (miscellaneous, trading, diversified, engineering…) has no entry and no vote
  • every Moneycontrol textile category → "Textiles & Apparel" (textile machinery → Capital Goods)
  • a disagreement = a verified category with an entry whose set does not contain the current industry

READ-ONLY. Output: the disagreement table (proposed industry = the set's first member).

Usage:  python -m tools.industry_audit [--csv PATH]
"""
import argparse
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import read_sql  # noqa: E402

TEX = "Textiles & Apparel"
CAP = "Capital Goods & Industrial Machinery"
CON = "Construction & Engineering"
RED = "Real Estate Developers"

MC_ACCEPTS = {
    # textiles: every Moneycontrol textile category
    **{c: (TEX,) for c in (
        "textiles", "textilesapparel", "textiles-general", "textilesgeneral", "textiles-readymade-apparels",
        "textiles-spinning-cotton-blended", "textiles-spinning-synthetic-blended", "textile-spinning",
        "textiles-cotton-blended", "textiles-composite-mills", "textiles-processing", "textiles-hosieryknitwear",
        "textiles-denim", "textiles-weaving", "textiles-manmade", "textiles-syntheticsilk")},
    "textiles-machinery": (CAP,),
    # the rest: only categories that pin the industry down
    **{c: ("Pharmaceuticals",) for c in ("pharmaceuticals", "pharmaceuticalsdrugs")},
    **{c: ("Paper, Wood & Forest Products",) for c in ("paper", "paperpaper-products", "paperforest-products",
                                                       "woodwood-products", "laminatesdecoratives")},
    **{c: ("Iron & Steel",) for c in ("ironsteel", "steel-tubespipes", "steel-sponge-iron", "steel-pig-iron",
                                      "steel-rolling", "steel-crhr-strips", "steel-gpgc-sheets", "steel-large",
                                      "steel-mediumsmall", "ferro-manganese")},
    **{c: ("Cement",) for c in ("cement-major", "cement-mini", "cement")},
    **{c: ("Banks",) for c in ("banks-private-sector", "banks-public-sector", "bank-private")},
    **{c: ("Oil & Gas",) for c in ("refineries", "oil-drillingexploration", "oil-explorationproduction", "lubricants")},
    "gas-distribution": ("Gas Utilities", "Oil & Gas"),
    **{c: ("Power Generation", "Power T&D") for c in ("power-generationdistribution", "renewables")},
    "tyres": ("Auto Components",),
    **{c: ("Auto Components",) for c in ("auto-ancillaries", "auto-ancillary", "auto-ancillaries-others",
                                         "auto-ancillaries-brakes", "auto-ancillaries-head-lampslights",
                                         "auto-ancillaries-engine-parts", "auto-ancillaries-spare-partsaccessories",
                                         "auto-ancillaries-auto-truckmotorcycle-parts", "auto-ancillaries-bus-body",
                                         "auto-ancillaries-tyresrubber-products", "auto-ancillaries-bearings",
                                         "auto-ancillaries-castingsforgings")},
    **{c: ("Automobiles",) for c in ("auto-23-wheelers", "auto-carsjeeps", "auto-lcvshcvs", "auto-tractors",
                                     "automobile-passenger-cars", "automobile-truckslcvs", "automobile-tractors",
                                     "automobile-23-wheelers")},
    **{c: ("Food & Beverages", "FMCG") for c in ("sugar", "food-processing", "consumer-food", "breweriesdistilleries",
                                                 "plantations-teacoffee", "edible-oilssolvent-extraction",
                                                 "edibleoilssolventextraction", "vegetable-oilsproducts",
                                                 "vanaspatioils", "aquaculture")},
    **{c: ("Personal Care & Household Products", "FMCG") for c in ("householdpersonal-products", "personal-care",
                                                                   "detergents")},
    "cigarettes": ("FMCG",),
    **{c: ("Hospitality & Hotels",) for c in ("hotels", "hotel-resortrestaurants")},
    **{c: ("Hospitals & Diagnostics",) for c in ("hospitalhealthcare-services", "hospitalsmedical-services",
                                                 "labslife-sciences-services")},
    "medical-equipmentsuppliesaccessories": ("Medical Devices",),
    **{c: ("NBFCs / Finance",) for c in ("finance-nbfc", "finance-housing", "finance-leasinghire-purchase",
                                         "finance-term-lending-institutions", "finance-term-lending")},
    **{c: ("Insurance",) for c in ("lifehealth-insurance", "multiline-insurancebrokers")},
    "finance-stock-broking": ("Capital Markets & Exchanges",),
    **{c: ("IT Services & ITeS", "Software Products & SaaS") for c in (
        "computers-software", "computers-software-mediumsmall", "computerssoftwaremediumsmall", "software",
        "it-servicesconsulting", "bpoites")},
    **{c: ("Telecom",) for c in ("telecommunications-service", "telecommunications-services",
                                 "telecommunication-service-provider")},
    **{c: ("Media & Entertainment",) for c in ("mediaentertainment", "media", "film-production-distributionentertainment",
                                               "tv-broadcastingsoftware-production")},
    **{c: ("Chemicals & Specialty",) for c in ("fertilisers", "fertilizers", "pesticidesagro-chemicals",
                                               "pesticidesagrochemicals", "pesticidesagrochemical", "dyespigments",
                                               "speciality-chemicals", "chemicals", "commodity-chemicals",
                                               "petrochemicals", "diversified-chemicals", "carbon-black",
                                               "paintsvarnishes", "paints")},
    **{c: ("Mining & Minerals", "Iron & Steel") for c in ("miningminerals", "metals-non-ferrous", "aluminium",
                                                          "aluminiumaluminium-products", "metalsmining", "coal",
                                                          "specialty-miningmetals")},
    **{c: ("Defence & Aerospace",) for c in ("aerospacedefence", "defence")},
    **{c: ("Logistics & Transport",) for c in ("shipping", "transportlogistics", "logistics",
                                               "ground-freightlogistics-services", "courier-services", "couriers")},
    "airlines": ("Aviation",),
    **{c: (RED, CON) for c in ("construction-real-estate", "constructioncontracting-real-estate",
                               "construction-residentialcommercial-complexes", "real-estate-rental-developmentoperations",
                               "real-estate-operations")},
    **{c: (CON, RED) for c in ("constructioncontracting-civil", "construction-infrastructure",
                               "engineering-construction", "engineeringconstruction", "constructioncontracting-housing")},
    **{c: ("Consumer Durables",) for c in ("domestic-appliances", "consumer-goods-electronic",
                                           "consumer-goods-white-goods", "air-conditioners")},
    **{c: ("Retail", "E-Commerce") for c in ("retailing", "retail", "speciality-retailers", "fooddrug-retailing")},
}

_STRIP = re.compile(r"\b(ltd|limited|the|co|company|corporation|corp|and)\b")


def _norm(x):
    return re.sub(r"[^a-z0-9]", "", _STRIP.sub("", str(x).lower()))


def slug_matches(name, token):
    """The slug's company token is this stock: one starts the other, or they are close (renames fail here)."""
    n = _norm(name)
    tokens = [_norm(re.sub(r"^the", "", x)) for x in str(token).split("-")]      # "thetatapowercompany", "irctc-…"
    return any(_same(n, t) for t in tokens if t)


def _same(n, t):
    if not n:
        return False
    k = min(len(n), len(t), 6)
    return n[:k] == t[:k] and (n.startswith(t) or t.startswith(n) or SequenceMatcher(None, n, t).ratio() >= 0.6) \
        or SequenceMatcher(None, n, t).ratio() >= 0.88       # TRIDENT → "trent" (0.83) must fail


def audit():
    s = read_sql("SELECT sid, ticker, name, sector, industry, cap_tier, market_cap_cr, mc_slug FROM stocks")
    parts = s["mc_slug"].fillna("").str.extract(r"^/india/stockpricequote/([^/]+)/([^/]+)/")
    s["mc_cat"], s["mc_co"] = parts[0], parts[1]
    s["slug_ok"] = [isinstance(c, str) and slug_matches(n, c) for n, c in zip(s["name"], s["mc_co"])]
    s["accepts"] = [MC_ACCEPTS.get(c) if ok else None for c, ok in zip(s["mc_cat"], s["slug_ok"])]
    s["disagree"] = [a is not None and ind not in a for a, ind in zip(s["accepts"], s["industry"])]
    s["proposed"] = [a[0] if d else None for a, d in zip(s["accepts"], s["disagree"])]
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    a = ap.parse_args()
    s = audit()
    has = s["mc_cat"].notna()
    print(f"stocks {len(s)} · with a slug {has.sum()} · slug verified {s['slug_ok'].sum()} · "
          f"category with a vote {s['accepts'].notna().sum()} · disagreements {s['disagree'].sum()}")
    d = s[s["disagree"]]
    print("\nproposed ← current (counts):")
    print(d.groupby(["proposed", "industry"], dropna=False).size().sort_values(ascending=False).to_string())
    bad = s[has & ~s["slug_ok"]]
    print(f"\nslugs that point at another company ({len(bad)}):")
    print(bad[["ticker", "name", "mc_co"]].to_string(index=False))
    if a.csv:
        d[["sid", "ticker", "name", "cap_tier", "sector", "industry", "mc_cat", "proposed"]].to_csv(a.csv, index=False)


if __name__ == "__main__":
    main()
