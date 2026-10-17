"""Build docs/research/0014-macro-explainer-mockup.html from data.json (computed) + the map prose below."""
import json, html, math
from pathlib import Path

HERE = Path(__file__).parent
D = json.load(open(HERE / "data.json"))
BASE_CSS = (HERE / "base.css").read_text()
OUT = Path("/home/ubuntu/alpha-signal-v2/docs/research/0014-macro-explainer-mockup.html")
E = html.escape

LABEL = {
    "brent_crude": "Brent crude", "usdinr": "USD/INR (rupee)", "us_10y": "US 10-year yield", "gold": "Gold", "silver": "Silver",
    "copper": "Copper", "aluminium": "Aluminium", "india_vix": "India VIX", "nifty50": "Nifty 50", "bank_nifty": "Bank Nifty",
    "nifty_auto": "Nifty Auto", "nifty_energy": "Nifty Energy", "nifty_fmcg": "Nifty FMCG", "nifty_infra": "Nifty Infra",
    "nifty_it": "Nifty IT", "nifty_media": "Nifty Media", "nifty_metal": "Nifty Metal", "nifty_pharma": "Nifty Pharma",
    "nifty_psubank": "Nifty PSU Bank", "nifty_realty": "Nifty Realty", "india_money_rate": "Money-market rate",
    "iip_general": "IIP, all industry", "iip_manufacturing": "IIP manufacturing", "iip_capital_goods": "IIP capital goods",
    "iip_consumer_durables": "IIP consumer durables", "core_combined": "Core sector, eight industries", "cpi_general": "CPI, headline",
    "cpi_food_beverages": "CPI food and beverages", "cpi_housing_fuel": "CPI housing and fuel", "india_exports": "Goods exports",
    "india_imports": "Goods imports", "gsec10_etf": "10-year G-sec (ETF price)", "cpi_health": "CPI health",
}
# a sector index move maps to the industries that read it as a dial; for indices no explainer lists, map by hand
INDEX_INDUSTRY = {"nifty_it": ["IT Services & ITeS", "Software Products & SaaS"], "nifty_media": ["Media & Entertainment"],
                  "nifty_metal": ["Iron & Steel", "Mining & Minerals"], "nifty_auto": ["Automobiles", "Auto Components"],
                  "nifty_infra": ["Construction & Engineering", "Capital Goods & Industrial Machinery"],
                  "nifty_fmcg": ["FMCG", "Food & Beverages", "Personal Care & Household Products"],
                  "nifty_pharma": ["Pharmaceuticals", "Hospitals & Diagnostics"], "nifty_energy": ["Oil & Gas", "Power Generation"],
                  "nifty_realty": ["Real Estate Developers", "REITs"], "bank_nifty": ["Banks"], "nifty_psubank": ["Banks"]}
LESSON_FOR = {"brent_crude": 10, "usdinr": 10, "us_10y": 11, "india_vix": 12, "gold": 9, "copper": 8, "nifty_it": 9,
              "cpi_general": 3, "iip_general": 4, "india_money_rate": 1, "india_exports": 5}
CARD_FOR = {"brent_crude": "Twin deficits and the rupee", "usdinr": "Twin deficits and the rupee", "us_10y": "United States",
            "nifty_it": "Engines › services exports", "india_vix": "Market gauges", "gold": "Twin deficits and the rupee",
            "copper": "China (phase 2)", "nifty_media": "Engines › consumption", "nifty_metal": "China (phase 2)",
            "nifty50": "The plumbing", "nifty_auto": "Engines › consumption", "nifty_infra": "Engines › government capex"}


def fmt(v, unit=""):
    if v is None:
        return "—"
    return f"{v:,.2f}{unit}"


def sign(v, unit="%", d=2):
    return f"{'+' if v > 0 else ''}{v:.{d}f}{unit}"


def rupee(v):
    return f"{'−' if v < 0 else '+'}₹{abs(v):,.0f} cr"


def tone(v, good_when_up=True):
    if v is None or abs(v) < 1e-9:
        return "neutral"
    return "up" if (v > 0) == good_when_up else "down"


# ── India quadrant points: x = 3-month change in IIP growth (pp), y = 3-month change in CPI inflation (pp) ──
iip = D["iip_yoy3"]; cpi = D["cpi_yoy"]
months = sorted(set(iip) & set(cpi))
def back3(m):
    y, mo = map(int, m.split("-")); mo -= 3
    if mo <= 0: y, mo = y - 1, mo + 12
    return f"{y:04d}-{mo:02d}"
pts = [(m, iip[m] - iip[back3(m)], cpi[m] - cpi[back3(m)]) for m in months if back3(m) in iip and back3(m) in cpi]
# keep only the latest unbroken run of months (the CPI base change leaves a gap in 2025)
def _mi(m): y, mo = map(int, m.split("-")); return y * 12 + mo
run = [pts[-1]]
for p_ in reversed(pts[:-1]):
    if _mi(run[0][0]) - _mi(p_[0]) == 1: run.insert(0, p_)
    else: break
trail = run[-9:]
def quad(x, y):
    return ("Reflation" if y > 0 else "Goldilocks") if x > 0 else ("Stagflation" if y > 0 else "Deflation")
now_m, now_x, now_y = trail[-1]
india_quad = quad(now_x, now_y)

def quadrant_svg(points, title):
    W, H, C, S = 300, 300, 150, 22    # 22 px per percentage point
    def px(x): return round(C + max(-6, min(6, x)) * S, 1)
    def py(y): return round(C - max(-6, min(6, y)) * S, 1)
    poly = " ".join(f"{px(x)},{py(y)}" for _, x, y in points)
    dots = "".join(f'<circle cx="{px(x)}" cy="{py(y)}" r="{3 if i < len(points) - 1 else 7}" class="{"q-trail" if i < len(points) - 1 else "q-now"}"><title>{m}: growth change {x:+.1f} pp, inflation change {y:+.1f} pp</title></circle>'
                   for i, (m, x, y) in enumerate(points))
    lbl = "".join(f'<text x="{px(x) + 8}" y="{py(y) - 6}" class="q-lbl">{m[2:]}</text>' for i, (m, x, y) in enumerate(points) if i in (0, len(points) - 1))
    return f'''<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="{E(title)}">
  <rect x="150" y="10" width="140" height="140" class="q-ref"/><rect x="10" y="10" width="140" height="140" class="q-stag"/>
  <rect x="10" y="150" width="140" height="140" class="q-def"/><rect x="150" y="150" width="140" height="140" class="q-gold"/>
  <line x1="10" x2="290" y1="150" y2="150" class="axis"/><line x1="150" x2="150" y1="10" y2="290" class="axis"/>
  <text x="282" y="28" text-anchor="end" class="q-name">Reflation</text><text x="18" y="28" class="q-name">Stagflation</text>
  <text x="18" y="282" class="q-name">Deflation</text><text x="282" y="282" text-anchor="end" class="q-name">Goldilocks</text>
  <text x="286" y="144" text-anchor="end" class="q-ax">growth ↑</text><text x="156" y="20" class="q-ax">inflation ↑</text>
  <polyline points="{poly}" class="q-path"/>{dots}{lbl}
</svg>'''


def spark(series, key, w=520, h=90, ref=None, cls="spark"):
    vals = [p[key] for p in series]
    lo, hi = min(vals + ([ref] if ref is not None else [])), max(vals + ([ref] if ref is not None else []))
    rng = hi - lo or 1
    def X(i): return round(8 + i * (w - 16) / (len(vals) - 1), 1)
    def Y(v): return round(h - 8 - (v - lo) / rng * (h - 16), 1)
    pts = " ".join(f"{X(i)},{Y(v)}" for i, v in enumerate(vals))
    refl = f'<line x1="8" x2="{w - 8}" y1="{Y(ref)}" y2="{Y(ref)}" class="ref"/>' if ref is not None else ""
    return f'<svg viewBox="0 0 {w} {h}" width="100%" class="{cls}" role="img">{refl}<polyline points="{pts}" class="line"/><circle cx="{X(len(vals) - 1)}" cy="{Y(vals[-1])}" r="4" class="dot"/></svg>'


def flows_svg(series, w=760, h=170):
    fi = [p.get("FII", 0) for p in series]; di = [p.get("DII", 0) for p in series]
    m = max(max(map(abs, fi)), max(map(abs, di))) or 1
    bw = (w - 20) / len(series)
    mid = h / 2
    bars = []
    for i, p in enumerate(series):
        x = 10 + i * bw
        for v, cls, off in ((p.get("FII", 0), "fii", 0), (p.get("DII", 0), "dii", bw / 2)):
            hh = abs(v) / m * (mid - 10)
            y = mid - hh if v > 0 else mid
            bars.append(f'<rect x="{x + off:.1f}" y="{y:.1f}" width="{max(1, bw / 2 - 1):.1f}" height="{hh:.1f}" rx="1" class="{cls}"><title>{p["d"]}: {"FII" if cls == "fii" else "DII"} net ₹{v:,.0f} cr</title></rect>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="FII and DII net daily cash flows, last 60 sessions"><line x1="10" x2="{w - 10}" y1="{mid}" y2="{mid}" class="axis"/>{"".join(bars)}<text x="12" y="14" class="q-ax">net buying ↑</text><text x="12" y="{h - 4}" class="q-ax">net selling ↓</text><text x="{w - 10}" y="{h - 4}" text-anchor="end" class="q-ax">{series[0]["d"]} → {series[-1]["d"]}</text></svg>'


def rate_svg(hist, w=520, h=120):
    ks = sorted(hist); vals = [hist[k] for k in ks]
    lo, hi = min(vals) - 0.25, max(vals) + 0.25
    def X(i): return round(10 + i * (w - 20) / (len(vals) - 1), 1)
    def Y(v): return round(h - 18 - (v - lo) / (hi - lo) * (h - 34), 1)
    d = f"M{X(0)},{Y(vals[0])}" + "".join(f" H{X(i)} V{Y(v)}" for i, v in enumerate(vals) if i)
    ticks = "".join(f'<text x="{X(i)}" y="{h - 4}" text-anchor="middle" class="q-ax">{k[:4]}</text>' for i, k in enumerate(ks) if k.endswith("-01"))
    keep = {0, vals.index(max(vals)), len(vals) - 1}
    lv = "".join(f'<text x="{X(i) + (4 if i < len(vals) - 1 else -4)}" y="{Y(v) - 6}" text-anchor="{"start" if i < len(vals) - 1 else "end"}" class="q-lbl">{v:g}%</text>' for i, v in enumerate(vals) if i in keep)
    return f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Money-market rate, monthly"><path d="{d}" class="step"/>{ticks}{lv}<circle cx="{X(len(vals) - 1)}" cy="{Y(vals[-1])}" r="4" class="dot"/></svg>'


# ── pulse rows ──
REV = D["reverse"]
def who_cares(ind_id, chg):
    """Industries that read this dial, split by whether today's move helps or hurts them."""
    if ind_id in INDEX_INDUSTRY:
        return [], [], INDEX_INDUSTRY[ind_id]
    rows = REV.get(ind_id, [])
    up = chg > 0
    helps = [r["industry"] for r in rows if (r["direction"] == "up") == up and r["direction"] != "mixed"]
    hurts = [r["industry"] for r in rows if (r["direction"] == "down") == up and r["direction"] != "mixed"]
    mixed = [r["industry"] for r in rows if r["direction"] == "mixed"]
    return helps, hurts, mixed

def chips(names, cls):
    return " ".join(f'<span class="ind {cls}">{E(n)}</span>' for n in names[:8]) + (f' <span class="more">+{len(names) - 8} more</span>' if len(names) > 8 else "")

mover_rows = []
for m in D["movers"][:12]:
    helps, hurts, mixed = who_cares(m["id"], m["chg"])
    z = m["z"]; zw = min(100, abs(z) / 3 * 100)
    lesson = LESSON_FOR.get(m["id"]); card = CARD_FOR.get(m["id"])
    mover_rows.append(f'''<tr><td><b>{E(LABEL.get(m["id"], m["id"]))}</b><div class="tiny">{m["date"]} · {fmt(m["value"])}</div></td>
<td class="num mono {"pos" if m["chg"] > 0 else "neg"}">{sign(m["chg"], " bps" if m["unit"] == "bps" else "%")}</td>
<td><div class="zbar"><i class="{"zp" if z > 0 else "zn"}" style="width:{zw:.0f}%"></i></div><div class="tiny mono">{z:+.1f} σ</div></td>
<td>{(('<div><span class="tag-h">helps</span>' + chips(helps, "h") + "</div>") if helps else "")}{(('<div><span class="tag-x">hurts</span>' + chips(hurts, "x") + "</div>") if hurts else "")}{(('<div><span class="tag-m">' + ("reads it" if m["id"] in INDEX_INDUSTRY else "mixed") + '</span>' + chips(mixed, "m") + "</div>") if mixed else "")}{"" if (helps or hurts or mixed) else '<span class="tiny">no industry lists this dial yet</span>'}</td>
<td class="tiny">{E(card) if card else "—"}{f'<br><a href="#learn">lesson {lesson}</a>' if lesson else ""}</td></tr>''')

monthly_rows = "".join(
    f'<tr><td>{E(LABEL.get(p["id"], p["id"]))}</td><td class="mono">{p["month"]}</td><td class="num mono">{sign(p["yoy"])}</td><td class="num mono tiny">{sign(p["prev"])}</td>'
    f'<td><span class="pill {"up" if p["yoy"] > p["prev"] else "down"}">{"▲ faster" if p["yoy"] > p["prev"] else "▼ slower"}</span></td></tr>'
    for p in D["monthly_prints"])

theme_cards = "".join(
    f'''<div class="theme"><div class="th-h">{E(t["title"])}</div><div class="th-now">{E(t["stands_now"])}</div>
<div class="th-chg"><b>What changed.</b> {E(t["what_changed"])}</div>
<div class="th-gl">{"".join(f'<span class="ind h">{E(g)}</span>' for g in json.loads(t["gains"] or "[]"))}{"".join(f'<span class="ind x">{E(g)}</span>' for g in json.loads(t["loses"] or "[]"))}</div>
<div class="tiny">news desk note of {t["updated_at"]}</div></div>''' for t in D["themes"])

# ── regime table ──
RT = D["regime_table"]
SECT = [("bank_nifty", "Banks"), ("nifty_psubank", "PSU banks"), ("nifty_auto", "Auto"), ("nifty_fmcg", "FMCG"), ("nifty_it", "IT"),
        ("nifty_pharma", "Pharma"), ("nifty_metal", "Metals"), ("nifty_energy", "Energy"), ("nifty_infra", "Infra"),
        ("nifty_realty", "Realty"), ("nifty_media", "Media"), ("gold", "Gold")]
def cell(r):
    rel, t = r["rel"], r["t"]
    strength = min(1, abs(t) / 3)
    col = f"rgba(34,197,94,{0.1 + 0.5 * strength:.2f})" if rel > 0 else f"rgba(239,68,68,{0.1 + 0.5 * strength:.2f})"
    return f'<td class="num mono rcell" style="background:{col}" title="t = {t:+.2f}, beat the Nifty in {r["hit"]:.0f}% of months">{rel:+.1f}<div class="tiny">t {t:+.1f}</div></td>'
regime_rows = "".join(
    f'<tr class="{"rnow" if q == D["regime_now"]["regime"] else ""}"><td><b>{q}</b>{" ◀ now" if q == D["regime_now"]["regime"] else ""}<div class="tiny">{RT[q]["n"]} months · Nifty {RT[q]["nifty"]:+.1f}%/mo</div></td>'
    + "".join(cell(RT[q][s]) for s, _ in SECT) + "</tr>" for q in ["Goldilocks", "Reflation", "Stagflation", "Deflation"])
best_t, best_q, best_s = max((abs(RT[q][s]["t"]), q, n) for q in RT for s, n in SECT)
n_cells = len(RT) * len(SECT)
from statistics import NormalDist
bonf = NormalDist().inv_cdf(1 - 0.05 / n_cells / 2)
n_over = sum(abs(RT[q][s]["t"]) >= 2.5 for q in RT for s, _ in SECT)

# ── risk radar (thresholds are config; readings are feeds) ──
L = D
radar = [
    ("Oil shock", f'Brent {fmt(L["lvl_brent_crude"]["value"])} $, {sign(L["lvl_brent_crude"]["chg_63"])} in three months', "red" if L["lvl_brent_crude"]["chg_63"] > 25 else "amber" if L["lvl_brent_crude"]["chg_63"] > 10 else "green", "red above +25% in three months, amber above +10%"),
    ("US yields", f'US 10-year {L["lvl_us_10y"]["value"]:.2f}%, the highest in our history was 5.31% on 2026-10-05', "red" if L["lvl_us_10y"]["value"] > 5 else "amber" if L["lvl_us_10y"]["value"] > 4.5 else "green", "red above 5%, amber above 4.5%"),
    ("FII selling", f'FII net {rupee(D["flows_20d"]["FII"])} over 20 sessions; DII {rupee(D["flows_20d"]["DII"])}', "red" if D["flows_20d"]["FII"] < -50000 else "amber" if D["flows_20d"]["FII"] < -20000 else "green", "red below −₹50,000 cr, amber below −₹20,000 cr"),
    ("Crowded FII short", f'FIIs hold {D["fii_long_pct"]["value"]}% of their index futures long, the {D["fii_long_pct"]["pctile"]:.0f}th percentile since 2022', "amber" if D["fii_long_pct"]["pctile"] < 15 else "green", "amber below the 15th percentile: crowded short; since 2022 not followed by better-than-normal months"),
    ("Inflation turning", f'CPI {D["cpi_last"][1]:.2f}% in {D["cpi_last"][0]}, {sign(D["cpi_last"][2], " pp")} in three months', "red" if D["cpi_last"][2] > 1 else "amber" if D["cpi_last"][2] > 0.5 else "green", "red above +1 pp in three months, amber above +0.5 pp"),
    ("Rupee slide", f'USD/INR {L["lvl_usdinr"]["value"]:.2f}, {sign(L["lvl_usdinr"]["chg_63"])} in three months; record 96.88 on 2026-07-24', "red" if L["lvl_usdinr"]["chg_63"] > 3 else "amber" if L["lvl_usdinr"]["chg_63"] > 1.5 else "green", "red above +3% in three months, amber above +1.5%"),
    ("Fear gauge", f'India VIX {L["lvl_india_vix"]["value"]:.1f}, {D["vix_pctile_3y"]:.0f}th percentile of three years', "red" if D["vix_pctile_3y"] > 90 else "amber" if D["vix_pctile_3y"] > 75 else "green", "red above the 90th percentile, amber above the 75th"),
    ("Policy feed lag", f'Money-market rate feed last {L["lvl_india_money_rate"]["date"]} at {L["lvl_india_money_rate"]["value"]}%; the news desk reports an October rate rise', "amber", "amber whenever the feed is older than the last reported decision"),
]
radar_rows = "".join(f'<div class="rr rr-{c}"><span class="rr-dot"></span><div><b>{E(n)}</b><div>{E(r)}</div><div class="tiny">{E(rule)}</div></div></div>' for n, r, c, rule in radar)

# ── reverse index summary + feed backlog ──
rev_top = sorted(REV.items(), key=lambda kv: -len(kv[1]))[:10]
rev_rows = "".join(
    f'<tr><td>{E(LABEL.get(k, k))}</td><td class="num mono">{len(v)}</td><td>{chips([r["industry"] for r in v if r["direction"] == "up"], "h")}</td><td>{chips([r["industry"] for r in v if r["direction"] == "down"], "x")}</td></tr>'
    for k, v in rev_top)
backlog = " · ".join(f"{E(n)}" for n, c in D["unmapped_top"][:14])

# ── engines: live gauges ──
MP = {p["id"]: p for p in D["monthly_prints"]}
def gauge(k, note=""):
    p = MP.get(k)
    if not p:
        return f'<div class="gauge nofeed">no feed{(" · " + note) if note else ""}</div>'
    return f'<div class="gauge"><span class="mono">{sign(p["yoy"])}</span> year on year · {E(LABEL[k])} · {p["month"]} <span class="pill {"up" if p["yoy"] > p["prev"] else "down"}">{"▲" if p["yoy"] > p["prev"] else "▼"} from {sign(p["prev"])}</span></div>'

US_EXPOSED_H = sorted({r["industry"] for k in ("us_10y",) for r in REV.get(k, []) if r["direction"] == "down"})
US_EXPOSED_R = sorted({r["industry"] for r in REV.get("usdinr", []) if r["direction"] == "up"})

# ── learn: CPI lesson with our numbers ──
cpi_h = MP["cpi_general"]; cpi_f = MP["cpi_food_beverages"]; cpi_hf = MP["cpi_housing_fuel"]

FII = D["fii_long_pct"]; FL = D["flows_last"]; F20 = D["flows_20d"]; RN = D["regime_now"]
B = L["lvl_brent_crude"]; U = L["lvl_usdinr"]; T = L["lvl_us_10y"]; V = L["lvl_india_vix"]; MR = L["lvl_india_money_rate"]

EXTRA_CSS = """
  .wrap { grid-template-columns: 200px minmax(0, 1fr); }
  .strip { display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; margin-top: 18px; }
  .kpi .v { font-size: 20px; } .kpi .v.sm { font-size: 15px; }
  .tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin: 6px 0 18px; position: sticky; top: 49px; background: var(--bg-primary); z-index: 10; }
  .tabs button { background: transparent; border: 0; color: var(--text-secondary); font: inherit; font-size: 15px; font-weight: 600; padding: 11px 16px; cursor: pointer; border-bottom: 2px solid transparent; }
  .tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
  .tabs button small { color: var(--text-muted); font-weight: 500; margin-left: 6px; font-size: 11px; }
  .panel { display: none; } .panel.on { display: block; }
  .tiny { font-size: 11.5px; color: var(--text-muted); }
  .num { text-align: right; } .pos { color: var(--green); } .neg { color: var(--red); }
  .speed { display: inline-block; font-size: 10.5px; letter-spacing: .08em; text-transform: uppercase; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border-accent); color: var(--text-muted); margin-left: 8px; vertical-align: 3px; }
  /* plumbing */
  .pipe { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0; align-items: stretch; }
  .pipe .st { position: relative; border: 1px solid var(--border-accent); background: var(--bg-primary); border-radius: 12px; padding: 12px; margin-right: 22px; }
  .pipe .st:last-child { margin-right: 0; }
  .pipe .st::after { content: "›"; position: absolute; right: -19px; top: 40%; color: var(--accent); font-size: 28px; font-weight: 700; }
  .pipe .st:last-child::after { content: none; }
  .pipe h4 { margin: 0 0 6px; font-size: 14px; } .pipe ul { margin: 0; padding-left: 16px; font-size: 12.5px; color: var(--text-secondary); }
  .loop { margin-top: 10px; border: 1px dashed var(--accent); border-radius: 12px; padding: 10px 14px; font-size: 13px; color: var(--text-secondary); background: var(--accent-soft); }
  .loop b { color: var(--text-primary); }
  .eng-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
  .eng { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; background: var(--bg-primary); }
  .eng h4 { margin: 0; font-size: 15px; } .eng-sub { font-size: 12.5px; color: var(--text-muted); margin: 2px 0 8px; }
  .eng-row { font-size: 13px; color: var(--text-secondary); margin: 5px 0; }
  .tag-h, .tag-x, .tag-m { display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; padding: 1px 7px; border-radius: 999px; margin-right: 6px; }
  .tag-h { color: var(--green); background: var(--green-bg); } .tag-x { color: var(--red); background: var(--red-bg); } .tag-m { color: var(--amber); background: var(--amber-bg); }
  .gauge { margin-top: 8px; font-size: 12.5px; color: var(--text-primary); border-top: 1px dashed var(--border); padding-top: 8px; }
  .gauge.nofeed { color: var(--text-muted); font-style: italic; }
  .hist { display: grid; grid-template-columns: 54px 1fr; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 13.5px; }
  .hy { color: var(--accent); font-weight: 700; } .hl { color: var(--text-secondary); margin-top: 2px; }
  .chain { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 8px 0; }
  .chain span.n { border: 1px solid var(--border-accent); background: var(--bg-primary); border-radius: 10px; padding: 8px 10px; font-size: 12.5px; }
  .chain span.n.hot { border-color: var(--red); background: var(--red-bg); }
  .chain span.a { color: var(--accent); font-weight: 700; }
  .world { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
  .wc { border: 1px solid var(--border); border-radius: 12px; padding: 12px; background: var(--bg-primary); font-size: 13px; color: var(--text-secondary); }
  .wc h4 { margin: 0 0 4px; font-size: 14px; color: var(--text-primary); } .wc.stub { opacity: .75; border-style: dashed; }
  .fields { display: grid; grid-template-columns: 160px 1fr; gap: 6px 14px; font-size: 13.5px; }
  .fields dt { color: var(--text-muted); } .fields dd { margin: 0; color: var(--text-secondary); }
  .ind { display: inline-block; font-size: 11px; padding: 1px 7px; border-radius: 999px; margin: 1px 2px; border: 1px solid var(--border-accent); color: var(--text-secondary); }
  .ind.h { border-color: rgba(34,197,94,0.45); color: var(--green); } .ind.x { border-color: rgba(239,68,68,0.45); color: var(--red); } .ind.m { border-color: rgba(245,158,11,0.45); color: var(--amber); }
  .more { font-size: 11px; color: var(--text-muted); }
  /* clock */
  .clock2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .qbox { border: 1px solid var(--border); border-radius: 12px; padding: 12px; background: var(--bg-primary); }
  .qbox h4 { margin: 0 0 4px; font-size: 14px; } .qbox .qv { font-size: 18px; font-weight: 700; color: var(--amber); }
  svg .q-ref { fill: rgba(245,158,11,0.07); } svg .q-stag { fill: rgba(239,68,68,0.08); } svg .q-def { fill: rgba(59,130,246,0.07); } svg .q-gold { fill: rgba(34,197,94,0.07); }
  svg .axis { stroke: var(--border-accent); stroke-width: 1; } svg .q-name { fill: var(--text-muted); font-size: 11px; font-weight: 600; }
  svg .q-ax { fill: var(--text-muted); font-size: 10px; } svg .q-lbl { fill: var(--text-secondary); font-size: 10px; font-family: var(--mono); }
  svg .q-path { fill: none; stroke: var(--accent); stroke-width: 1.5; stroke-dasharray: 3 3; opacity: .7; }
  svg .q-trail { fill: var(--accent); opacity: .5; } svg .q-now { fill: var(--accent); stroke: var(--bg-card); stroke-width: 2; }
  svg .step { fill: none; stroke: var(--accent); stroke-width: 2; } svg .dot { fill: var(--accent); }
  svg .line { fill: none; stroke: var(--accent); stroke-width: 2; } svg .ref { stroke: var(--text-muted); stroke-dasharray: 3 3; }
  svg .fii { fill: #d97706; } svg .dii { fill: var(--accent); }
  .nofeed-box { border: 1px dashed var(--border-accent); border-radius: 12px; padding: 18px; color: var(--text-muted); font-size: 13px; min-height: 200px; display: flex; flex-direction: column; justify-content: center; gap: 6px; }
  .gauges { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px; }
  .g { border: 1px solid var(--border); border-radius: 12px; padding: 10px 12px; background: var(--bg-primary); }
  .g .l { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .06em; }
  .g .v { font-family: var(--mono); font-size: 20px; font-weight: 700; margin: 2px 0; }
  .g .s { font-size: 12px; color: var(--text-secondary); }
  .meter2 { height: 8px; border-radius: 4px; background: linear-gradient(90deg, var(--red), var(--amber) 50%, var(--green)); position: relative; margin: 8px 0 2px; }
  .meter2 i { position: absolute; top: -4px; width: 4px; height: 16px; background: #fff; border-radius: 2px; transform: translateX(-50%); }
  .cal td:first-child { white-space: nowrap; }
  /* pulse */
  .zbar { height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; width: 90px; }
  .zbar i { display: block; height: 100%; } .zbar .zp { background: var(--green); } .zbar .zn { background: var(--red); }
  .themes { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 10px; }
  .theme { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; background: var(--bg-primary); font-size: 13px; color: var(--text-secondary); }
  .th-h { font-weight: 700; color: var(--text-primary); font-size: 14px; margin-bottom: 4px; } .th-now { color: var(--text-primary); margin-bottom: 6px; }
  .th-chg { margin-bottom: 6px; } .th-gl { margin-bottom: 4px; }
  .legend2 { display: flex; gap: 14px; font-size: 12px; color: var(--text-secondary); } .legend2 i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
  /* playbook */
  .rtable td.rcell { font-size: 12.5px; } .rtable td.rcell .tiny { white-space: nowrap; } .rtable tr.rnow td { outline: 1px solid var(--accent); } .rtable th { white-space: nowrap; }
  .scen { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
  .sc { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; background: var(--bg-primary); font-size: 13px; color: var(--text-secondary); }
  .sc h4 { margin: 0 0 2px; font-size: 15px; color: var(--text-primary); } .sc .lk { font-size: 12px; font-weight: 700; margin-bottom: 8px; }
  .sc.base { border-color: var(--accent); } .sc .lk.l { color: var(--accent); } .sc .lk.p { color: var(--amber); }
  .radar { display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 8px; }
  .rr { display: flex; gap: 10px; align-items: flex-start; border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; background: var(--bg-primary); font-size: 13px; color: var(--text-secondary); }
  .rr b { color: var(--text-primary); } .rr-dot { width: 12px; height: 12px; border-radius: 50%; flex: none; margin-top: 4px; }
  .rr-red .rr-dot { background: var(--red); box-shadow: 0 0 0 4px var(--red-bg); } .rr-amber .rr-dot { background: var(--amber); box-shadow: 0 0 0 4px var(--amber-bg); } .rr-green .rr-dot { background: var(--green); box-shadow: 0 0 0 4px var(--green-bg); }
  .assets td { text-align: center; } .assets td:first-child { text-align: left; }
  /* learn */
  .lessons { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 8px; }
  .lesson { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; background: var(--bg-primary); font-size: 13px; color: var(--text-secondary); }
  .lesson b { color: var(--text-primary); } .lesson.on { border-color: var(--accent); background: var(--accent-soft); }
  .lesson .n { font-family: var(--mono); color: var(--accent); margin-right: 6px; }
  .ex { border-left: 3px solid var(--amber); background: var(--amber-bg); padding: 10px 14px; border-radius: 0 10px 10px 0; font-size: 13.5px; margin-top: 12px; }
  .ex ol { margin: 6px 0 0; padding-left: 18px; color: var(--text-secondary); }
  @media (max-width: 900px) {
    .wrap { grid-template-columns: 1fr; } .strip { grid-template-columns: repeat(2, 1fr); }
    .pipe, .clock2, .scen { grid-template-columns: 1fr; } .pipe .st { margin: 0 0 24px; } .pipe .st::after { content: "⌄"; right: auto; left: 50%; top: auto; bottom: -26px; }
    .fields { grid-template-columns: 1fr; } .tabs { overflow-x: auto; top: 41px; } .tabs button { white-space: nowrap; padding: 10px 10px; font-size: 14px; }
    table { display: block; overflow-x: auto; }
  }
"""

