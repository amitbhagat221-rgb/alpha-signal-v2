"""The macro page (/macro, plan 0028), assembled from desk_snapshots for any "as of" date.

Nothing here computes markets: output/macro_desk.py writes the daily brief, chapters / hot spots / the shelf are
written monthly or weekly, and every one is a dated, versioned row. page(as_of) picks the newest version of each
part on or before the date; a part with nothing that early shows its earliest version under a banner that says so.
"""
import datetime as dt
import html
import re

from output import desk_archive as A

E = html.escape
TRACKS = [("Prologue", "Start here"), ("India", "The India framework"), ("Global", "The global and geopolitical framework"),
          ("Synthesis", "Putting it together")]
CH_ORDER = ["pro"] + [f"in-{i}" for i in range(1, 9)] + [f"gl-{i}" for i in range(1, 10)] + [f"sy-{i}" for i in range(1, 4)]
NOTE_STALE_DAYS = 7

EXT = {"fred_brent": "https://fred.stlouisfed.org/series/DCOILBRENTEU", "fred_10y": "https://fred.stlouisfed.org/series/DGS10",
       "nse_fii": "https://www.nseindia.com/reports/fii-dii", "rbi": "https://www.rbi.org.in/"}
# (key, title, chapters it is explained in, source, meaning by colour). The meanings carry no figures.
LIGHTS = [
    ("oil", "Oil", [("in-5", "India: oil and the rupee"), ("gl-3", "Global: oil and the Gulf")], ("FRED, Brent", EXT["fred_brent"]), {
        "red": "Expensive enough to act as a tax on India: it widens the trade gap, weakens the rupee and lifts inflation.",
        "amber": "High enough to watch: fuel users' margins and the trade gap start to feel it.",
        "green": "Not a constraint on India right now."}),
    ("us", "US rates and the dollar", [("gl-2", "Global: the dollar and US rates")], ("FRED, US ten-year", EXT["fred_10y"]), {
        "red": "High enough to pull foreign money out of emerging markets and squeeze the India premium.",
        "amber": "A headwind: foreign money is choosier and valuations have less room.",
        "green": "Not a constraint on Indian valuations right now."}),
    ("flows", "Flows and positioning", [("in-6", "India: flows and positioning")], ("NSE, FII and DII activity", EXT["nse_fii"]), {
        "red": "Foreigners are selling hard; how much domestic funds absorb decides the market's direction.",
        "amber": "Foreigners are net sellers, at a pace domestic funds can absorb.",
        "green": "Foreign selling is not a pressure point."}),
    ("rbi", "The RBI", [("in-4", "India: the RBI's three levers")], ("RBI", EXT["rbi"]), {
        "red": "Tightening: money is getting dearer and scarcer.",
        "amber": "On hold: neither easing nor tightening.",
        "green": "Easing: money is getting cheaper."}),
]
REGIME_LINE = {"Goldilocks": "growth picking up while inflation eases", "Reflation": "growth and inflation both picking up",
               "Stagflation": "growth slowing while inflation picks up", "Deflation": "growth and inflation both slowing"}
HOT_CLASS = {"escalating": "esc", "elevated": "elv", "easing": "eas", "calm": "calm"}
# what each part is, how often it changes and how it is made: the Start page's cadence table and the archive
CADENCE = [
    ("brief", "Today's brief: lights, regime, unusual moves, risk radar", "Daily, about 11:15 IST", "computed from our database after the morning data run"),
    ("brief_note", "The verdict, winners and losers, what's coming", "When written; flagged after a week", "written by hand, no figures in the prose"),
    ("rbi", "The RBI's stance", "When the RBI acts", "set by hand from the decision"),
    ("hotspots", "Hot spots and the heat matrix", "Weekly", "written and web-checked, sources linked"),
    ("regime", "Regime clock", "Daily, moving with each IIP and CPI release", "computed, point-in-time"),
    ("chapter", "Framework chapters, charts and history blocks", "Monthly", "written and web-checked; charts rebuilt with the version"),
    ("deeper", "The Deeper shelf", "Monthly", "rebuilt with the chapters"),
    ("house_view", "House view", "Monthly", "written; scored a quarter later"),
    ("playbook", "Event studies and playbooks", "Monthly", "computed from our price history"),
    ("external", "External readings", "Monthly", "web, with source and date"),
    ("industry_explainer", "Industry explainers on Sectors", "Monthly", "written per industry"),
]


def fmt(v, d=2):
    return "—" if v is None else f"{v:,.{d}f}"


def sign(v, unit="%", d=2):
    return "—" if v is None else f"{'+' if v > 0 else ''}{v:.{d}f}{unit}"


def rupee(v):
    return "—" if v is None else f"{'−' if v < 0 else '+'}₹{abs(v):,.0f} cr"


_HREF_LOCAL = re.compile(r'<a (?![^>]*\btarget=)([^>]*\bhref="/[^"]*")')
_BANNER = re.compile(r'<div class="asof-banner"[^>]*>.*?</div>\s*', re.S)


def _top(fragment):
    """Cockpit links inside the frame open in the whole window, not inside the frame."""
    return _HREF_LOCAL.sub(r'<a target="_top" \1', fragment)


def _chapter(row, as_of):
    body = _BANNER.sub("", row["payload"]["html"], count=1)
    if row["early"]:
        banner = (f'<div class="asof-banner">Viewing as of <b>{E(as_of)}</b>: the earliest archived version of this chapter is '
                  f'{E(row["snapshot_date"])}, shown below.</div>')
        body = re.sub(r"(<article[^>]*>)", lambda m: m.group(1) + banner, body, count=1)
    return _top(body)


def _lights(b, prev):
    out = []
    readings = {
        "oil": f'Brent ${fmt(b["brent"])}, {sign(b["brent_3m"], "%", 1)} over 63 sessions',
        "us": f'US 10-year {fmt(b["us10y"])}%' + (f', {sign(b["us_3m_bps"], " bps", 0)} over 63 sessions' if b.get("us_3m_bps") is not None else ""),
        "flows": f'FIIs {rupee(b["fii20"])}, DIIs {rupee(b["dii20"])} over 20 sessions; FII index futures {fmt(b["fii_long"], 1)}% long',
        "rbi": E(b["rbi_text"]) + (f' <span class="tiny">(set {E(b["rbi_set"])})</span>' if b.get("rbi_set") else ""),
    }
    for key, title, chapters, src, meaning in LIGHTS:
        colour = b[key]
        extra = ""
        if key == "flows" and b.get("fii_long_pct") is not None and b["fii_long_pct"] < 15:
            extra = " Bearish futures positioning is a stress sign, not a rally signal on our data."
        out.append({"key": key, "title": title, "colour": colour, "reading": readings[key], "meaning": meaning[colour] + extra,
                    "chart": chapters[0][0], "chapters": chapters, "src": src,
                    "was": prev[key] if prev and prev.get(key) != colour else None, "was_date": prev["date"] if prev else None})
    return out


def _movers(b):
    rows = []
    for m in b.get("movers") or []:
        rows.append({**m, "move": sign(m["chg"], " bps" if m["unit"] == "bps" else "%"), "zs": f'{m["z"]:+.1f} σ',
                     "up": m["chg"] > 0, "zw": min(100, abs(m["z"]) / 3 * 100)})
    return rows


def _valid_date(s):
    try:
        return dt.date.fromisoformat(s).isoformat()
    except (TypeError, ValueError):
        return None


def page(as_of=None):
    briefs = A.history("brief")
    if not briefs:
        return None
    latest = briefs[-1][0]
    want = _valid_date(as_of) or latest
    upto = [x for x in briefs if x[0] <= want] or briefs[:1]
    bdate, b = upto[-1]
    b = {**b, "date": bdate}
    prev = ({**upto[-2][1], "date": upto[-2][0]} if len(upto) > 1 else None)
    view = want if want < latest else latest
    note_row = A.latest("brief_note", as_of=bdate)
    note = None
    if note_row:
        age = (dt.date.fromisoformat(bdate) - dt.date.fromisoformat(note_row["snapshot_date"])).days
        note = {**note_row["payload"], "date": note_row["snapshot_date"], "age": age, "stale": age > NOTE_STALE_DAYS}
    hot = A.latest("hotspots", as_of=view) or A.latest("hotspots")
    chapters = A.latest_all("chapter", as_of=view)
    deeper = A.latest("deeper", as_of=view) or A.latest("deeper")
    ordered = [dict(id=i, **chapters[i]) for i in CH_ORDER if i in chapters]
    ordered += [dict(id=i, **r) for i, r in sorted(chapters.items()) if i not in CH_ORDER]
    toc = []
    for track, name in TRACKS:
        items = [c for c in ordered if c["payload"].get("track") == track]
        toc.append({"track": track, "name": name, "items": [{"id": c["id"], "title": c["payload"]["title"],
                                                             "num": "P" if track == "Prologue" else str(n + 1)} for n, c in enumerate(items)]})
    summary = {r["part"]: r for r in A.summary()}
    cadence = [{"label": lab, "cadence": cad, "how": how, "last": summary.get(part, {}).get("last"),
                "first": summary.get(part, {}).get("first"), "days": summary.get(part, {}).get("days", 0),
                "items": summary.get(part, {}).get("items", 0)} for part, lab, cad, how in CADENCE]
    arch = []
    for d, p in reversed(briefs):
        arch.append({"date": d, "colours": [p.get(k) for k in ("oil", "us", "flows", "rbi")], "brent": fmt(p.get("brent")),
                     "us10y": f'{p["us10y"]:.2f}%' if p.get("us10y") is not None else "—", "fii20": rupee(p.get("fii20")),
                     "nifty": fmt(p.get("nifty"), 1), "regime": p.get("regime") or "", "notes": len(p.get("notes") or []),
                     "computed": "movers" in p})
    return {
        "as_of": view, "latest": latest, "is_latest": bdate == latest, "brief": b, "prev": prev, "note": note,
        "lights": _lights(b, prev), "movers": _movers(b),
        "regime_line": REGIME_LINE.get(b.get("regime") or "", ""),
        "context": {"nifty": fmt(b.get("nifty"), 1), "usdinr": fmt(b.get("usdinr")), "vix": fmt(b.get("vix"), 1),
                    "fii_last": rupee(b.get("fii_last")) if b.get("fii_last") is not None else None,
                    "dii_last": rupee(b.get("dii_last")) if b.get("dii_last") is not None else None},
        "hot": ({"date": hot["snapshot_date"], "early": hot["snapshot_date"] > view,
                 "rows": [{"name": n, "state": s, "cls": HOT_CLASS.get(s, "elv")} for n, s in hot["payload"].get("rows", [])]} if hot else None),
        "chapters": [{"id": c["id"], "html": _chapter(c, view), "date": c["snapshot_date"], "early": c["early"]} for c in ordered],
        "chapter_ids": [c["id"] for c in ordered],
        "n_india": sum(c["payload"].get("track") == "India" for c in ordered),
        "n_global": sum(c["payload"].get("track") == "Global" for c in ordered),
        "n_synth": sum(c["payload"].get("track") == "Synthesis" for c in ordered),
        "toc": toc,
        "deeper": ({"html": _top(deeper["payload"]["html"]), "date": deeper["snapshot_date"], "data_to": deeper["payload"].get("data_to")}
                   if deeper else None),
        "dates": [d for d, _ in reversed(briefs)],
        "archive": arch, "dotgrid": list(reversed(arch[:30])), "cadence": cadence,
    }
