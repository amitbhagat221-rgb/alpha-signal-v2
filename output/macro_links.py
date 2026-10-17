# Moved from the v5.2 mockup generator (docs/research/0014-macro-mockup-src/links.py), plan 0028.
"""Inline links for the macro page: each term links once per chapter, to the chapter that explains it, an authoritative
external source, or the cockpit's industry page. Text inside tags, existing links, SVG and headings is never touched."""
import re
from urllib.parse import quote

EXT = {   # authoritative sources
    "rbi": "https://www.rbi.org.in/", "mospi": "https://www.mospi.gov.in/", "nse_fii": "https://www.nseindia.com/reports/fii-dii",
    "nse": "https://www.nseindia.com/", "fred_brent": "https://fred.stlouisfed.org/series/DCOILBRENTEU", "fred_10y": "https://fred.stlouisfed.org/series/DGS10",
    "fred_inr": "https://fred.stlouisfed.org/series/DEXINUS", "fed": "https://www.federalreserve.gov/monetarypolicy.htm", "gst": "https://gstcouncil.gov.in/",
    "sebi": "https://www.sebi.gov.in/", "dgtr": "https://www.dgtr.gov.in/", "budget": "https://www.indiabudget.gov.in/", "ism": "https://ism.gov.in/",
    "opec": "https://www.opec.org/", "cbam": "https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism_en", "boj": "https://www.boj.or.jp/en/",
    "ecb": "https://www.ecb.europa.eu/", "amfi": "https://www.amfiindia.com/", "imd": "https://mausam.imd.gov.in/",
}
# (regex, href, title). Order matters: longer phrases first.
TERMS = [
    (r"current-account (?:deficit|gap)", "#in-5", "Chapter: oil and the rupee, the twin-deficit chain"),
    (r"twin deficits?", "#in-5", "Chapter: oil and the rupee"),
    (r"cash reserve requirement", "#in-4", "Chapter: the RBI's three levers"),
    (r"external benchmark", "#in-4", "Chapter: the RBI's three levers"),
    (r"monetary policy committee|the MPC", EXT["rbi"], "Reserve Bank of India"),
    (r"repo(?: rate)?", "#in-4", "Chapter: the RBI's three levers"),
    (r"inflation targeting", "#in-3", "Chapter: inflation"),
    (r"core CPI|core inflation", "#in-3", "Chapter: inflation"),
    (r"CPI", EXT["mospi"], "Ministry of Statistics (MoSPI): CPI releases"),
    (r"IIP", EXT["mospi"], "Ministry of Statistics (MoSPI): IIP releases"),
    (r"systematic (?:investment )?plans?|monthly fund(?:-flow)? (?:data|inflows)", EXT["amfi"], "AMFI: monthly mutual-fund flows"),
    (r"(?:FII|DII) (?:and (?:FII|DII) )?(?:cash )?flows|FII and DII numbers", EXT["nse_fii"], "NSE: daily FII and DII trading activity"),
    (r"crowded (?:foreign )?short", "#in-6", "Chapter: flows and positioning"),
    (r"domestic institutions|domestic funds", "#in-6", "Chapter: flows and positioning"),
    (r"foreign investors", "#in-6", "Chapter: flows and positioning"),
    (r"(?:India(?:'s)? )?valuation premium|India premium", "#gl-2", "Chapter: the dollar and US rates"),
    (r"term premium", "#gl-2", "Chapter: the dollar and US rates"),
    (r"US real yields", "#gl-2", "Chapter: the dollar and US rates"),
    (r"the Fed\b", EXT["fed"], "US Federal Reserve: monetary policy"),
    (r"Hormuz(?: route)?|the closed Gulf route|Iran war", "#gl-9", "Chapter: hot spots"),
    (r"Taiwan Strait", "#gl-9", "Chapter: hot spots"),
    (r"Korean peninsula", "#gl-9", "Chapter: hot spots"),
    (r"South China Sea", "#gl-9", "Chapter: hot spots"),
    (r"Bab-el-Mandeb|chokepoints?", "#gl-3", "Chapter: oil and the Gulf"),
    (r"OPEC\+?", EXT["opec"], "OPEC"),
    (r"export controls", "#gl-8", "Chapter: technology, AI and the chip cycle"),
    (r"high-bandwidth memory|AI build-out|AI capex", "#gl-8", "Chapter: technology, AI and the chip cycle"),
    (r"semiconductor mission", EXT["ism"], "India Semiconductor Mission"),
    (r"rare earths?", "#gl-4", "Chapter: China"),
    (r"China\+1", "#gl-4", "Chapter: China"),
    (r"carry trade|yen carry", "#gl-5", "Chapter: Europe and Japan"),
    (r"Bank of Japan", EXT["boj"], "Bank of Japan"),
    (r"European Central Bank", EXT["ecb"], "European Central Bank"),
    (r"carbon border tax", EXT["cbam"], "EU Carbon Border Adjustment Mechanism"),
    (r"(?:penalty )?tariffs?", "#gl-6", "Chapter: Russia, sanctions and India's balancing act"),
    (r"sanctions", "#gl-6", "Chapter: Russia, sanctions and India's balancing act"),
    (r"stagflation|reflation|goldilocks|the regime", "#sy-1", "Chapter: regimes"),
    (r"fertiliser subsidies", "#in-7", "Chapter: fiscal policy and political economy"),
    (r"(?:public|government) capex", "#in-2", "Chapter: growth engines"),
    (r"GST Council", EXT["gst"], "GST Council"),
    (r"SEBI", EXT["sebi"], "Securities and Exchange Board of India"),
    (r"anti-dumping", EXT["dgtr"], "Directorate General of Trade Remedies"),
    (r"(?:the )?(?:February )?Budget", EXT["budget"], "Union Budget documents"),
    (r"monsoon", EXT["imd"], "India Meteorological Department"),
    (r"India VIX", EXT["nse"], "NSE: India VIX"),
]
_TERMS = [(re.compile(r"(?<![\w-])(" + p + r")(?![\w-])", re.I), h, t) for p, h, t in TERMS]
_SKIP = re.compile(r"(<svg\b.*?</svg>|<a\b.*?</a>|<h[1-3]\b.*?</h[1-3]>|<div class=\"ch-kicker\">.*?</div>|<span class=\"mono[^\"]*\">.*?</span>|<[^>]+>)", re.S | re.I)

def link_html(href, text, title):
    ext = href.startswith("http")
    return (f'<a href="{href}" class="{"xl" if ext else "il"}" title="{title}"'
            + (' target="_blank" rel="noopener"' if ext else "") + f">{text}</a>")

def linkify(html, used, self_id=None):
    """Link the first occurrence of each term in `html` not already in `used` (a set shared across one chapter).
    Re-splits after every insertion so a term can never match inside a link added earlier."""
    for rx, href, title in _TERMS:
        key = (rx.pattern, href)
        if key in used or (self_id and href == f"#{self_id}"):
            continue
        parts = _SKIP.split(html)
        for i, part in enumerate(parts):
            if not part or _SKIP.fullmatch(part):
                continue
            m = rx.search(part)
            if m:
                used.add(key)
                parts[i] = part[:m.start()] + link_html(href, m.group(1), title) + part[m.end():]
                html = "".join(parts)
                break
    return html

def industry_links(html, industries):
    """Turn industry chips into links to the cockpit's industry page (works when served from the cockpit)."""
    names = sorted(industries, key=len, reverse=True)
    def rep(m):
        cls, text = m.group(1), m.group(2)
        plain = text.replace("&amp;", "&")
        if plain in industries:
            return f'<a class="ind {cls}" href="/sectors?industry={quote(plain)}#per-sector" title="Open the {text} industry page in the cockpit">{text} ↗</a>'
        return m.group(0)
    return re.sub(r'<span class="ind ([a-z]+)">([^<]+)</span>', rep, html)
