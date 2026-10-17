"""
Reviewed industry corrections (Amit 2026-10-17: "this is a textiles company not a paper wood company" →
"yes please"). The one place a human-checked industry lives; tools/classify_industries.py re-applies it
after every run, so a re-classification can never undo it.

How the list was made: tools/industry_audit.py compared every stock's industry with the category in its
Moneycontrol page slug (stocks.mc_slug, slug identity checked against the stock's name). 349 stocks
disagreed. Each was read by hand; an entry is here only where the current industry is wrong and the new one
is right. Moneycontrol's own category was wrong for many (IndiGo / SpiceJet as logistics, REITs as
construction, Dr. Lal PathLabs as pharma, the city-gas distributors as oil drilling, Ather / Ola as brake
makers, tractors as automobiles): those stocks keep their industry and are not listed.

The textiles industry did not exist before 2026-10-17: the classifier's closed list had none, so mills
went to "Paper, Wood & Forest Products", fibre makers to Chemicals and apparel makers to Retail or Consumer
Durables. Apparel brands whose business is mainly their own store chain (Vedant Fashions, ABFRL, Go Fashion,
Arvind Fashions, Credo Brands, Kewal Kiran's peers) stay in Retail.

Every move also sets stocks.sector to the new industry's parent sector (the invariant tools/classify_industries
keeps: 0 of 2,444 stocks broke it on 2026-10-17).

Usage:
    python -m tools.industry_review            # dry run: what would change
    python -m tools.industry_review --apply    # write stocks.industry + stocks.sector
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEX = "Textiles & Apparel"

# ticker → why (all to Textiles & Apparel). Keyed by NSE ticker for readability; plan() resolves sids.
_TEXTILES = {
    # spinning, weaving, processing, composite mills (were Paper, Wood & Forest Products / Chemicals / Retail)
    "AMBIKCO": "cotton yarn spinner", "BORANA": "grey fabric weaver", "GHCLTEXTIL": "yarn and fabric (GHCL demerger)",
    "GLOSTERLTD": "jute goods", "HIMATSEIDE": "home textiles (bed linen)", "LAKSHMIMIL": "cotton yarn mill",
    "NAHARSPING": "yarn and knitwear", "RAJPALAYAM": "cotton yarn and fabric", "RNBDENIMS": "denim fabric",
    "RSWM": "synthetic and blended yarn", "RUBYMILLS": "fabric mill", "SANATHAN": "polyester and cotton yarn",
    "SWARAJ": "suiting fabric and denim", "VTL": "yarn and fabric (Vardhman Textiles)",
    "TRIDENT": "yarn and home textiles are most of revenue (paper is the smaller segment)",
    "ABCOTS": "cotton yarn (slug pointed at Abbott India)", "PRECOT": "cotton yarn (slug pointed at Pricol)",
    "VISHAL": "fabric and denim (slug pointed at Vishal Mega Mart)", "DONEAR": "suiting fabric (slug pointed at Dollar)",
    "LUDLOWJUT": "jute goods", "CHEVIOT": "jute goods", "PASHUPATI": "cotton yarn (had no industry)",
    "ALOKINDS": "yarn, fabric and home textiles", "ASHIMASYN": "fabric (Ashima)", "AXITA": "cotton bales and yarn",
    "AYMSYNTEX": "polyester and nylon yarn", "BANSWRAS": "synthetic yarn and fabric", "BOMDYEING": "polyester and home textiles",
    "CENTENKA": "nylon filament yarn", "DCMSIL": "textiles (DCM Shriram International)", "FILATEX": "polyester yarn",
    "GANECOS": "recycled polyester fibre", "GARFIBRES": "technical textiles (nets, ropes)", "GINNIFILA": "yarn and non-wovens",
    "ICIL": "home textiles (Indo Count)", "INDORAMA": "polyester fibre and yarn", "JINDWORLD": "denim and fabric",
    "LEMERITE": "fabric exporter", "MAFATIND": "fabric and uniforms", "NDL": "denim fabric", "NITINSPIN": "cotton yarn",
    "PASUPTAC": "acrylic fibre", "RAJRILTD": "polyester yarn", "SANGAMIND": "yarn and fabric", "SARLAPOLY": "nylon and polyester yarn",
    "SOMATEX": "composite mill", "VARDHACRLC": "acrylic fibre", "VARDMNPOLY": "yarn",
    "SUMEETINDS": "polyester yarn", "VTMLTD": "fabric", "NAHARINDUS": "yarn and fabric (sugar is the smaller part)",
    "ORBTEXP": "fabric exporter", "SIYSIL": "suiting fabric and apparel", "SPORTKING": "yarn", "SUTLEJTEX": "yarn and home textiles",
    "VGL": "denim fabric", "SHREEKARNI": "fabric", "UNITEDPOLY": "fabric", "BELLACASA": "home textiles",
    "FAZE3Q": "home textiles (rugs, bath mats)", "ARVIND": "denim, fabric and garments",
    # garment and knitwear makers (were Retail / Consumer Durables / Personal Care / Auto Components / Capital Goods)
    "DOLLAR": "innerwear and knitwear maker", "PAGEIND": "innerwear maker (Jockey licensee)", "WELSPUNLIV": "home textiles",
    "KARNIKA": "children's garments", "TTL": "hosiery and knitwear", "RUPA": "innerwear and knitwear maker",
    "GOKEX": "garment exporter", "IRISDOREME": "children's garments", "JAIPURKURT": "women's ethnic garments (Jaipur Kurti)",
    "KITEX": "children's garments", "MONTECARLO": "woollen and knitwear maker", "PGIL": "garment exporter",
    "RAYMONDLSL": "fabric and branded apparel (Raymond Lifestyle)", "SPAL": "garment exporter", "THOMASCOTT": "garments",
    "CPS": "shapewear and garments", "PDSL": "apparel sourcing and manufacturing", "VIRAT": "knitwear",
    "KPRMILL": "yarn, fabric and garments (had no industry)", "LUXIND": "innerwear and knitwear maker (had no industry)",
}

# the other reviewed corrections: ticker → (industry, why)
_OTHER = {
    # tyres and auto parts filed as automobiles / capital goods / chemicals
    "APOLLOTYRE": ("Auto Components", "tyres"), "BALKRISIND": ("Auto Components", "tyres"), "MRF": ("Auto Components", "tyres"),
    "PTL": ("Auto Components", "tyre plant leased to Apollo"), "JBMA": ("Auto Components", "sheet-metal auto parts are most of revenue"),
    "KROSS": ("Auto Components", "axle and suspension parts"), "OMAXAUTO": ("Auto Components", "auto parts"),
    "ARE&M": ("Auto Components", "automotive batteries"), "ISTLTD": ("Auto Components", "auto parts"),
    "LGBBROSLTD": ("Auto Components", "chains and sprockets for two-wheelers"), "SEDEMAC": ("Auto Components", "engine control units"),
    "TRITONV": ("Auto Components", "tyre valves"), "OBSCP": ("Auto Components", "precision auto parts"),
    "UCAL": ("Auto Components", "carburettors and fuel systems"), "BELRISE": ("Auto Components", "sheet-metal auto parts"),
    "KINETICENG": ("Auto Components", "gearboxes and auto parts"),
    "SMLMAH": ("Automobiles", "trucks and buses"),
    "LMW": ("Capital Goods & Industrial Machinery", "textile machinery"),
    # cement
    "KCP": ("Cement", "cement is the largest segment"), "NCLIND": ("Cement", "cement"), "PRSMJOHNSN": ("Cement", "cement and tiles"),
    # chemicals and agrochemicals
    "AMAL": ("Chemicals & Specialty", "sulphuric acid and oleum"), "BLACKROSE": ("Chemicals & Specialty", "chemicals distribution"),
    "DHANUKA": ("Chemicals & Specialty", "agrochemicals"), "MBAPL": ("Chemicals & Specialty", "fertilisers"),
    "ANDHRSUGAR": ("Chemicals & Specialty", "caustic soda and chemicals are most of revenue"),
    "VIDHIING": ("Chemicals & Specialty", "synthetic food colours (dyes)"), "TGVSL": ("Chemicals & Specialty", "chlor-alkali"),
    "GOACARBON": ("Chemicals & Specialty", "calcined petroleum coke"), "HIGREEN": ("Chemicals & Specialty", "recovered carbon black"),
    # construction and EPC
    "EMSLIMITED": ("Construction & Engineering", "water and sewerage EPC"), "SEPC": ("Construction & Engineering", "EPC contractor"),
    "VIKRAN": ("Construction & Engineering", "power EPC"), "VPRPL": ("Construction & Engineering", "water EPC"),
    "TRANSRAILL": ("Construction & Engineering", "transmission-line EPC"),
    "IRBINVIT": ("REITs", "an InvIT, like the other trusts in REITs"),
    # consumer durables
    "VOEPL": ("Consumer Durables", "air-conditioner components and lighting"),
    # defence
    "SIKA": ("Defence & Aerospace", "aerospace and defence systems"), "ASTRAMICRO": ("Defence & Aerospace", "defence RF and microwave"),
    "AZAD": ("Defence & Aerospace", "aero-engine and turbine parts"), "MTARTECH": ("Defence & Aerospace", "nuclear, space and defence parts"),
    "NIBE": ("Defence & Aerospace", "defence equipment"), "ROSSTECH": ("Defence & Aerospace", "aerospace electrical harnesses"),
    "SIGMAADV": ("Defence & Aerospace", "defence electronics"), "ZENTEC": ("Defence & Aerospace", "defence simulators and anti-drone"),
    "JAYKAY": ("Defence & Aerospace", "defence and aerospace parts"), "C2C": ("Defence & Aerospace", "defence electronics"),
    # FMCG and food
    "NTCIND": ("FMCG", "cigarettes"), "VSTIND": ("FMCG", "cigarettes"),
    "FLAIR": ("FMCG", "writing instruments and stationery (had no industry)"),
    "DCMSRIND": ("Food & Beverages", "sugar and alcohol"), "GOKUL": ("Food & Beverages", "edible oils"),
    "SCPL": ("Food & Beverages", "snacks and ice cream"), "SHEETAL": ("Food & Beverages", "packaged food"),
    "BCLIND": ("Food & Beverages", "distillery and edible oil"), "REGAAL": ("Food & Beverages", "maize starch and food ingredients"),
    "SHINDL": ("Food & Beverages", "aquaculture"), "GANESHCP": ("Food & Beverages", "flour and packaged food"),
    # hotels and restaurants
    "HLVLTD": ("Hospitality & Hotels", "hotels (Hotel Leelaventure)"), "SAVERA": ("Hospitality & Hotels", "hotel"),
    "SAPPHIRE": ("Hospitality & Hotels", "quick-service restaurants"), "WESTLIFE": ("Hospitality & Hotels", "quick-service restaurants"),
    # IT
    "LTM": ("IT Services & ITeS", "IT services"), "BBOX": ("IT Services & ITeS", "IT and network services"),
    "MOLDTECH": ("IT Services & ITeS", "engineering design services"), "MOSCHIP": ("IT Services & ITeS", "semiconductor design services"),
    # steel
    "APLAPOLLO": ("Iron & Steel", "structural steel tubes"), "COSMICCRF": ("Iron & Steel", "cold-rolled steel"),
    "JTLIND": ("Iron & Steel", "steel tubes"), "MANINDS": ("Iron & Steel", "steel pipes"),
    "RATNAVEER": ("Iron & Steel", "stainless steel products"), "SURYAROSNI": ("Iron & Steel", "steel pipes are most of revenue"),
    "SURAJLTD": ("Iron & Steel", "stainless steel pipes"), "GOODLUCK": ("Iron & Steel", "steel tubes and forgings"),
    "JAIBALAJI": ("Iron & Steel", "sponge iron and steel"), "KRISHCA": ("Iron & Steel", "steel strapping"),
    "MWL": ("Iron & Steel", "stainless steel"), "WELSPLSOL": ("Iron & Steel", "alloy and stainless steel"),
    "BMWVENTLTD": ("Iron & Steel", "steel products"), "SARDAEN": ("Iron & Steel", "steel and ferro alloys"),
    "OILCOUNTUB": ("Iron & Steel", "oil-country steel tubes"), "WELCORP": ("Iron & Steel", "steel line pipes"),
    # logistics
    "GLOTTIS": ("Logistics & Transport", "freight forwarding"),
    # media
    "CINELINE": ("Media & Entertainment", "cinemas"), "DEN": ("Media & Entertainment", "cable TV distribution"),
    "DISHTV": ("Media & Entertainment", "DTH television"), "GTPL": ("Media & Entertainment", "cable TV distribution"),
    "HATHWAY": ("Media & Entertainment", "cable TV and broadband; TV is the larger part"),
    # metals and mining
    "ARFIN": ("Mining & Minerals", "aluminium alloys"), "NILE": ("Mining & Minerals", "lead recycling"),
    "MIDWESTLTD": ("Mining & Minerals", "granite and heavy mineral sands"), "SHERA": ("Mining & Minerals", "copper and aluminium products"),
    "JAINREC": ("Mining & Minerals", "metal recycling"),
    # finance
    "SBICARD": ("NBFCs / Finance", "credit-card lender"),
    # oil and gas
    "CASTROLIND": ("Oil & Gas", "lubricants"), "GULFOILLUB": ("Oil & Gas", "lubricants"), "VEEDOL": ("Oil & Gas", "lubricants"),
    "IRMENERGY": ("Gas Utilities", "city-gas distribution"),
    # paper and wood
    "NRAIL": ("Paper, Wood & Forest Products", "paper and board"), "SATIA": ("Paper, Wood & Forest Products", "writing and printing paper"),
    "RUSHIL": ("Paper, Wood & Forest Products", "laminates and MDF"), "EUROPRATIK": ("Paper, Wood & Forest Products", "decorative laminates"),
    # pharma
    "HIKAL": ("Pharmaceuticals", "pharma APIs are the larger part"), "IOLCP": ("Pharmaceuticals", "pharma APIs (ibuprofen)"),
    "NGLFINE": ("Pharmaceuticals", "veterinary APIs"), "SIGACHI": ("Pharmaceuticals", "pharma excipients"),
    "AMANTA": ("Pharmaceuticals", "IV fluids and injectables"), "BLUEJET": ("Pharmaceuticals", "contrast-media intermediates"),
    "SAKAR": ("Pharmaceuticals", "formulations"), "ZOTA": ("Pharmaceuticals", "generic medicines"),
    "ACCENTMIC": ("Pharmaceuticals", "pharma excipients"), "VIYASH": ("Pharmaceuticals", "pharma APIs"),
    # power
    "SCHNEIDER": ("Power T&D", "transformers and switchgear"), "ZODIAC": ("Power Generation", "solar EPC and power"),
    # telecom
    "SUYOG": ("Telecom", "telecom towers"),
}

REVIEWED = {**{sid: (TEX, why) for sid, why in _TEXTILES.items()}, **_OTHER}


def _sid_of_ticker():
    from db import read_sql
    s = read_sql("SELECT sid, ticker FROM stocks")
    return dict(zip(s["ticker"], s["sid"]))


def plan():
    """[(sid, ticker, old_industry, old_sector, new_industry, new_sector, why)] for every entry that changes a row.
    The lists are keyed by TICKER for readability; this resolves them to sids and refuses an unknown ticker."""
    from db import read_sql
    from tools.classify_industries import ALL_INDUSTRIES
    s = read_sql("SELECT sid, ticker, sector, industry FROM stocks").set_index("ticker")
    unknown = [t for t in REVIEWED if t not in s.index]
    if unknown:
        raise ValueError(f"industry_review: tickers not in stocks: {unknown}")
    bad = sorted({ind for ind, _ in REVIEWED.values() if ind not in ALL_INDUSTRIES})
    if bad:
        raise ValueError(f"industry_review: industries not in the taxonomy: {bad}")
    out = []
    for t, (ind, why) in REVIEWED.items():
        r = s.loc[t]
        sec = ALL_INDUSTRIES[ind]
        if r["industry"] != ind or r["sector"] != sec:
            out.append((r["sid"], t, r["industry"], r["sector"], ind, sec, why))
    return out


def apply(dry_run=False):
    rows = plan()
    if not dry_run and rows:
        from db import get_db
        with get_db() as conn:
            conn.executemany("UPDATE stocks SET industry = ?, sector = ? WHERE sid = ?",
                             [(ind, sec, sid) for sid, _, _, _, ind, sec, _ in rows])
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    rows = apply(dry_run=not a.apply)
    for sid, t, oi, os_, ni, ns, why in rows:
        print(f"{t:12} {str(oi):36} → {ni:36}{'  [sector ' + str(os_) + ' → ' + ns + ']' if os_ != ns else ''}  {why}")
    print(f"\n{len(rows)} stocks {'updated' if a.apply else 'would change (dry run; --apply writes)'}")


if __name__ == "__main__":
    main()
