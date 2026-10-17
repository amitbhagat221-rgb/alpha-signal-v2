"""Macro mockup v5: prologue + India framework + global and geopolitical framework + synthesis, each chapter with charts,
diagrams and history; today's brief re-linked to the new chapters; the v2 deep sections on the shelf."""
import build3 as v3                     # CSS3, shelf, brief helpers (no file write on import)
from core import *                      # noqa: F401,F403
import charts as C
from chapters_v5 import CH, D2, feed, ch_link
import json
from pathlib import Path
import links as LK
from tools_industries import INDUSTRIES
SNAPS = json.loads(Path(__file__).with_name("data4.json").read_text())

TRACKS = [("Prologue", "Start here"), ("India", "The India framework"), ("Global", "The global and geopolitical framework"), ("Synthesis", "Putting it together")]
ORDER = [c["id"] for c in CH]
TITLE = {c["id"]: c["title"] for c in CH}

def kicker(c):
    same = [x["id"] for x in CH if x["track"] == c["track"]]
    i = same.index(c["id"]) + 1
    name = dict(TRACKS)[c["track"]]
    return f'{name} · chapter {i} of {len(same)} · {c["mins"]} minute read' if c["track"] != "Prologue" else f'Prologue · {c["mins"]} minute read'

def chapter_html(c):
    used = set()
    c = dict(c)
    for f in ("hook", "body", "history", "today"):
        if c.get(f): c[f] = LK.linkify(c[f], used, c["id"])
    c["sowhat_html"] = LK.linkify(E(c["sowhat"]), used, c["id"])
    k = ORDER.index(c["id"])
    prev = f'<a class="nav-prev" href="#{ORDER[k-1]}">← {E(TITLE[ORDER[k-1]])}</a>' if k > 0 else '<a class="nav-prev" href="#start">← Start here</a>'
    nxt = (f'<a class="nav-next" href="#{ORDER[k+1]}">Next: {E(TITLE[ORDER[k+1]])} →</a>' if k + 1 < len(ORDER)
           else '<a class="nav-next primary" href="#today">Open today\'s brief →</a>')
    inds = "".join(f'<tr><td>{E(a)}</td><td class="num">{b}</td></tr>' for a, b in c.get("indicators", []))
    deep_href = "#today" if c["deeper"] == "today" else f'#deeper-{c["deeper"]}'
    track_cls = {"India": "tr-in", "Global": "tr-gl", "Synthesis": "tr-sy", "Prologue": "tr-pro"}[c["track"]]
    return f'''<article class="chapter {track_cls}" data-view="{c["id"]}">
  <div class="asof-banner" hidden>Viewing as of <b class="asof-d"></b>: this chapter's earliest archived version is 2026-10-17, shown below.</div>
  <div class="ch-kicker"><span class="trk">{E(c["track"])}</span> {E(kicker(c))} · version of 2026-10-17 · refreshed monthly</div>
  <h1 class="ch-title">{E(c["title"])}</h1>
  <div class="ch-hook">{c["hook"]}</div>
  <div class="ch-body">{c["body"]}</div>
  {c.get("history", "")}
  {c.get("today", "")}
  <div class="ch-sowhat"><b>So what for positioning.</b> {c["sowhat_html"]}</div>
  {f'<div class="ch-inds"><div class="ch-words-h">Indicators to track</div><table class="ind-t"><tbody>{inds}</tbody></table></div>' if inds else ""}
  {c.get("extra", "")}
  <div class="ch-deeper">Want more? <a href="{deep_href}">{E(c["deeper_label"])} →</a></div>
  <div class="ch-nav">{prev}{nxt}</div>
</article>'''

CHAPTER_VIEWS = "".join(chapter_html(c) for c in CH)
TOC = ""
for t, name in TRACKS:
    items = [c for c in CH if c["track"] == t]
    TOC += f'<div class="toc-g toc-g-{t.lower()}">{E(name)}</div>'
    for i, c in enumerate(items):
        num = "P" if t == "Prologue" else str(i + 1)
        TOC += f'<a class="toc-i" href="#{c["id"]}" data-ch="{c["id"]}"><span class="toc-n">{num}</span><span class="toc-t">{E(c["title"])}</span><span class="toc-d">✓</span></a>'

# ── today's brief, re-linked ──
def light(color, title, reading, meaning, links, chart=None, source=None):
    used = set()
    meaning_html = LK.linkify(E(meaning), used)
    reading_html = f'<a class="rd" href="{chart}" title="Open the chart">{reading}</a>' if chart else reading
    src = f' · Source: <a class="xl" href="{source[1]}" target="_blank" rel="noopener">{E(source[0])}</a>' if source else ""
    return (f'<div class="light l-{color}"><div class="light-top"><span class="dot"></span><b>{E(title)}</b></div>'
            f'<div class="light-r">{reading_html}</div><div class="light-m">{meaning_html}</div><div class="light-c">Mechanism: {" · ".join(links)}{src}</div></div>')
LIGHTS = (
    light(SNAPS[-1]["oil"], "Oil", f'Brent {feed(fmt(B["value"]))}, {feed(sign(B["chg_63"]))} in three months',
          "A supply-led war premium from the closed Gulf route: a pure tax on India.", [ch_link("in-5", "India: oil and the rupee"), ch_link("gl-3", "Global: oil and the Gulf")], chart="#in-5", source=("FRED, Brent", LK.EXT["fred_brent"]))
  + light(SNAPS[-1]["us"], "US rates and the dollar", f'US 10-year {feed(f"{T["value"]:.2f}%")}, near the high of our sample',
          "Keeps foreign money flowing out and the India premium under pressure.", [ch_link("gl-2", "Global: the dollar and US rates")], chart="#gl-2", source=("FRED, US ten-year", LK.EXT["fred_10y"]))
  + light(SNAPS[-1]["flows"], "Flows and positioning", f'FIIs {feed(rupee(F20["FII"]))}, DIIs {feed(rupee(F20["DII"]))} in 20 sessions; FII futures {feed(str(FII["value"]) + "% long")}',
          "Foreigners selling hard, domestic funds absorbing almost all. Bearish positioning is a stress sign, not a rally signal on our data.", [ch_link("in-6", "India: flows and positioning")], chart="#in-6", source=("NSE, FII and DII activity", LK.EXT["nse_fii"]))
  + light(SNAPS[-1]["rbi"], "The RBI", "Raised rates in October; another rise likely",
          "Tightening through rates and liquidity at once to defend the rupee.", [ch_link("in-4", "India: the RBI's three levers")], chart="#in-4", source=("RBI", LK.EXT["rbi"])))

TODAY = f'''<article class="brief" data-view="today">
  <div class="ch-kicker">Today's brief · data to {B["date"]} · about five minutes</div>
  <h1 class="ch-title">The squeeze continues</h1>
  <div class="verdict">The Iran war's tanker attacks have pushed oil back near its spring high, and record US yields add pressure from outside; the RBI has turned
  to tightening to hold the rupee. Foreign investors are selling and domestic funds are absorbing it. The drawdown so far is in the 2018 range. The signpost for a turn is shipping through Hormuz.</div>
  <div class="snapnote">Since the last snapshot ({SNAPS[-2]["date"]}): {", ".join(f"{n} {SNAPS[-2][k]} → {SNAPS[-1][k]}" for n, k in (("oil", "oil"), ("US rates", "us"), ("flows", "flows"), ("RBI", "rbi")) if SNAPS[-2][k] != SNAPS[-1][k]) or "no light changed colour"}. <a href="#archive">All past briefs →</a></div>
  <h2 class="b-h">1 · The regime <span class="b-sub">Mechanism: {ch_link("sy-1", "Regimes")}</span></h2>
  <div class="season-now"><span class="pill-season">{india_quad}</span> Growth and inflation both accelerating, supply-led. The risk is the turn to stagflation.</div>
  <h2 class="b-h">2 · The four lights</h2>
  <div class="lights">{LIGHTS}</div>
  <h2 class="b-h">Hot spots this week <span class="b-sub">Mechanism: {ch_link("gl-9", "Hot spots")}</span></h2>
  <div class="hotstrip"><span class="hs esc">Iran war · escalating</span><span class="hs elv">Russia–Ukraine · elevated</span><span class="hs elv">Taiwan · elevated</span><span class="hs elv">South China Sea · elevated</span><span class="hs elv">Korea · elevated</span><span class="hs calm">India's borders · calm</span></div>
  <h2 class="b-h">3 · What changed yesterday</h2>
  <p class="b-p">IT had the most unusual day, up {feed(sign(D["movers"][0]["chg"]))}, as fears eased that AI will eat IT services work. The rupee firmed to
  {feed(fmt(U["value"]))} on the RBI's new defences. Brent rose another {feed(sign(B["chg_1"]))}. Foreigners were net buyers for one day, {feed(rupee(FL["FII"]))}; one day is not a trend.</p>
  <table class="b-table"><thead><tr><th>Biggest unusual moves</th><th class="num">Move</th><th>How unusual</th><th>Who it helps or hurts</th></tr></thead><tbody>{v3.mv_rows}</tbody></table>
  <div class="tiny">σ compares the move with each series' normal daily move. <a href="#deeper-data">All moves and the latest data →</a></div>
  <h2 class="b-h">4 · Who wins and who loses right now</h2>
  <div class="winlose"><div><div class="wl-h win">Doing better in this setup</div>
    <div class="sec-i win"><b>IT and pharma exporters</b><span>earn in dollars; gain if the rupee weakens · {ch_link("in-5", "why")}</span></div>
    <div class="sec-i win"><b>Upstream oil producers</b><span>sell at the higher price, unless taxed · {ch_link("in-5", "why")}</span></div>
    <div class="sec-i win"><b>Defence</b><span>policy priority; border events lift it on a multi-year view · {ch_link("gl-7", "why")}</span></div>
    <div class="sec-i win"><b>Banks with cheap deposits</b><span>externally linked loans reprice first · {ch_link("in-4", "why")}</span></div></div>
  <div><div class="wl-h lose">Under pressure</div>
    <div class="sec-i lose"><b>FMCG</b><span>lagged in every kind of oil shock in our data · {ch_link("in-5", "why")}</span></div>
    <div class="sec-i lose"><b>Airlines, paints, OMCs</b><span>crude is their biggest cost · {ch_link("gl-3", "why")}</span></div>
    <div class="sec-i lose"><b>Wholesale-funded lenders</b><span>funding costs rise first · {ch_link("in-4", "why")}</span></div>
    <div class="sec-i lose"><b>Richly valued large caps</b><span>the India premium compresses with US yields · {ch_link("gl-2", "why")}</span></div></div></div>
  <h2 class="b-h">5 · What's coming</h2>
  <div class="coming">
    <div><b>End of October</b><span>IIP for September: did factories slow as rates rose?</span></div>
    <div><b>Mid-November</b><span>CPI for October: the first full month of the oil shock in prices.</span></div>
    <div><b>Next RBI meeting</b><span>Insurance move or the start of a cycle?</span></div>
    <div><b>November</b><span>US midterms: tariffs and fiscal policy for two years.</span></div>
  </div>
  <h2 class="b-h">6 · Risk radar</h2>
  <div class="radar-c">{v3.radar_compact}</div>
  <div class="ch-nav"><a class="nav-prev" href="#sy-3">← The daily routine</a><a class="nav-next" href="#deeper">Go deeper →</a></div>
</article>'''

# ── dated snapshots: the date filter ──
LATEST = SNAPS[-1]["date"]
PREV = {SNAPS[i]["date"]: SNAPS[i - 1] for i in range(1, len(SNAPS))}
COLOR_WORD = {"red": "red", "amber": "amber", "green": "green"}
def snap_lights(sn):
    rows = [("Oil", sn["oil"], f'Brent {feed(fmt(sn["brent"]))}, {feed(sign(sn["brent_3m"], "%", 1))} over 63 sessions', "#in-5", ("FRED, Brent", LK.EXT["fred_brent"])),
            ("US rates and the dollar", sn["us"], f'US 10-year {feed(f"{sn['us10y']:.2f}%")}', "#gl-2", ("FRED, US ten-year", LK.EXT["fred_10y"])),
            ("Flows and positioning", sn["flows"], f'FIIs {feed(rupee(sn["fii20"]))}, DIIs {feed(rupee(sn["dii20"]))} over 20 sessions; FII futures {feed(str(sn["fii_long"]) + "% long")}', "#in-6", ("NSE", LK.EXT["nse_fii"])),
            ("The RBI", sn["rbi"], E(sn["rbi_text"]), "#in-4", ("RBI", LK.EXT["rbi"]))]
    prev = PREV.get(sn["date"])
    keymap = {"Oil": "oil", "US rates and the dollar": "us", "Flows and positioning": "flows", "The RBI": "rbi"}
    out = ""
    for name, col, reading, chart, src in rows:
        chg = ""
        if prev and prev[keymap[name]] != col:
            chg = f'<span class="chg">changed from {prev[keymap[name]]} on {prev["date"]}</span>'
        out += (f'<div class="light l-{col}"><div class="light-top"><span class="dot"></span><b>{E(name)}</b>{chg}</div>'
                f'<div class="light-r"><a class="rd" href="{chart}">{reading}</a></div>'
                f'<div class="light-c">Source: <a class="xl" href="{src[1]}" target="_blank" rel="noopener">{E(src[0])}</a></div></div>')
    return out

def snap_view(sn):
    notes = "".join(f'<div class="theme"><div class="th-h">{E(n["theme"])}</div><div class="th-now">{E(n["now"])}</div><div class="th-chg"><b>What changed.</b> {E(n["changed"] or "")}</div></div>' for n in sn["notes"])
    return f'''<article class="brief" data-view="today@{sn['date']}">
  <div class="snapbar">Viewing the archived brief for <b>{sn['date']}</b>. <a href="#today">Back to today →</a></div>
  <div class="ch-kicker">Brief as of {sn['date']} · point-in-time</div>
  <h1 class="ch-title">The four lights on {sn['date']}</h1>
  <div class="fig-cap">Recomputed from data dated on or before {sn['date']}; the regime uses only releases published by then. Live snapshots are stored as they run; this archive was rebuilt retrospectively for the mockup. The verdict line and hot spots were not written for this date.</div>
  <h2 class="b-h">The regime</h2><div class="season-now"><span class="pill-season">{sn['regime'] or "n/a"}</span> from data to {sn['regime_month']}.</div>
  <h2 class="b-h">The four lights</h2><div class="lights">{snap_lights(sn)}</div>
  <h2 class="b-h">Market context</h2><div class="season-now">Nifty {feed(fmt(sn['nifty']))} · USD/INR {feed(fmt(sn['usdinr']))} · India VIX {feed(fmt(sn['vix']))} · FII long share percentile since 2022: {feed(sn['fii_long_pct'])}</div>
  <h2 class="b-h">The news desk on {sn['note_date']}</h2><div class="themes">{notes or '<div class="tiny">No news-desk note for this date.</div>'}</div>
  <div class="ch-nav"><a class="nav-prev" href="#archive">← All archived briefs</a><a class="nav-next" href="#today">Today's brief →</a></div>
</article>'''
SNAP_VIEWS = "".join(snap_view(sn) for sn in SNAPS if sn["date"] != LATEST)

def dotgrid():
    keys = [("Oil", "oil"), ("US rates and the dollar", "us"), ("Flows and positioning", "flows"), ("The RBI", "rbi")]
    head = "".join(f'<th class="dg-d"><a href="#{"today" if sn["date"] == LATEST else "today@" + sn["date"]}">{sn["date"][5:]}</a></th>' for sn in SNAPS)
    body = "".join(f'<tr><td>{E(n)}</td>' + "".join(f'<td class="dg-c"><span class="gdot g-{sn[k]}" title="{n}, {sn["date"]}: {sn[k]}"></span></td>' for sn in SNAPS) + "</tr>" for n, k in keys)
    reg = "<tr><td>Regime</td>" + "".join(f'<td class="dg-c tiny reg">{sn["regime"] or ""}</td>' for sn in SNAPS) + "</tr>"
    return f'<table class="dotgrid"><thead><tr><th></th>{head}</tr></thead><tbody>{body}{reg}</tbody></table>'

arch_rows = "".join(f'<tr><td class="mono"><a href="#{"today" if sn["date"] == LATEST else "today@" + sn["date"]}">{sn["date"]}</a></td><td>{"".join(f"<span class='gdot g-{sn[k]}'></span>" for k in ("oil","us","flows","rbi"))}</td>'
                    f'<td class="num mono">{fmt(sn["brent"])}</td><td class="num mono">{sn["us10y"]:.2f}%</td><td class="num mono">{rupee(sn["fii20"])}</td><td class="num mono">{fmt(sn["nifty"])}</td><td>{E(sn["regime"] or "")}</td><td class="tiny">{len(sn["notes"])} notes</td></tr>' for sn in reversed(SNAPS))
ARCHIVE = f'''<article class="brief" data-view="archive">
  <div class="ch-kicker">Archive · every brief is kept with its date</div>
  <h1 class="ch-title">Past briefs</h1>
  <p class="b-p">Nothing is overwritten. Every refresh stores a dated snapshot, and the date filter in the top bar opens any of them as it read on the day. Below, the four lights across the archived dates, then the full list.</p>
  <div class="fig">{dotgrid()}<div class="fig-cap">Click a date to open that day's brief. Red, amber and green follow the same rules as today's lights.</div></div>
  <h2 class="b-h">Everything archived, by part</h2>
  <div class="fig"><table class="b-table"><thead><tr><th>Part</th><th>Cadence</th><th class="num">Items</th><th>Dates archived</th><th>How it was stored</th></tr></thead><tbody>
    <tr><td>Daily brief</td><td>daily</td><td class="num mono">1</td><td class="mono">2026-09-06 → {LATEST} (8 dates)</td><td>7 retrospective, latest written</td></tr>
    <tr><td>Hot spots</td><td>weekly + on escalation</td><td class="num mono">6 conflicts</td><td class="mono">2026-10-17</td><td>written, web-checked, sources kept</td></tr>
    <tr><td>Framework chapters</td><td>monthly</td><td class="num mono">{len(CH)}</td><td class="mono">2026-10-17</td><td>written; each version kept</td></tr>
    <tr><td>Industry explainers</td><td>monthly</td><td class="num mono">38</td><td class="mono">2026-10-16 → 2026-10-17</td><td>written; each version kept</td></tr>
    <tr><td>Regime clock</td><td>weekly</td><td class="num mono">1</td><td class="mono">2026-09-06 → {LATEST}</td><td>computed, point-in-time</td></tr>
    <tr><td>House view</td><td>weekly</td><td class="num mono">3 cases</td><td class="mono">2026-10-17</td><td>written; scored a quarter later</td></tr>
    <tr><td>Playbooks and event studies</td><td>monthly</td><td class="num mono">6 tables</td><td class="mono">2026-10-17</td><td>computed</td></tr>
    <tr><td>External readings</td><td>monthly</td><td class="num mono">{len(__import__("chapters_v5").EXTERNAL_ROWS)}</td><td class="mono">2026-10-17</td><td>web, with source links</td></tr>
    <tr><td>News-desk notes</td><td>weekly</td><td class="num mono">7 themes</td><td class="mono">2026-09-06 → 2026-10-12</td><td>already dated in the news tables</td></tr>
  </tbody></table><div class="fig-cap">All in the database table <code>desk_snapshots</code> (the news-desk notes stay in their own dated tables). The "As of" filter reads the newest version on or before the chosen date.</div></div>
  <h2 class="b-h">Every archived brief</h2>
  <div class="fig"><table class="b-table"><thead><tr><th>Date</th><th>Lights</th><th class="num">Brent</th><th class="num">US 10y</th><th class="num">FII, 20 sessions</th><th class="num">Nifty</th><th>Regime</th><th>News desk</th></tr></thead><tbody>{arch_rows}</tbody></table></div>
</article>'''
ASOF_OPTS = "".join(f'<option value="{sn["date"]}"{" selected" if sn["date"] == LATEST else ""}>{sn["date"]}{" · today" if sn["date"] == LATEST else ""}</option>' for sn in reversed(SNAPS))

# ── start page ──
n_in = sum(c["track"] == "India" for c in CH); n_gl = sum(c["track"] == "Global" for c in CH)
geo_tl = C.timeline([(1962, "war with China", "geo"), (1971, "war with Pakistan", "geo"), (1973, "oil embargo", "global"), (1991, "BoP crisis, reforms", "domestic"),
                     (1999, "Kargil", "geo"), (2001, "China joins WTO", "global"), (2003, "FRBM Act", "policy"), (2008, "global crisis", "global"), (2025.6, "US tariffs", "global"), (2020.2, "Covid", "global"),
                     (2013, "taper tantrum", "global"), (2016, "demonetisation", "policy"), (2018, "US–China trade war", "global"),
                     (2020, "Galwan", "geo"), (2022, "Ukraine war", "global"), (2024, "coalition govt", "domestic"), (2025, "Op Sindoor", "geo"),
                     (2026, "Iran war", "geo")], title="Sixty years of shocks that shaped Indian markets")
START = f'''<article class="start" data-view="start">
  <div class="ch-kicker">Macro for Indian equities</div>
  <h1 class="start-title">Two frameworks, then today's read.</h1>
  <p class="start-sub">What is built at home and what arrives from abroad, each with its own mechanisms, charts and history, joined by a short synthesis and a five-minute daily brief on live data.</p>
  <div class="doors doors3">
    <a class="door door-in" href="#in-1"><div class="door-tag">Framework one · {n_in} chapters</div><div class="door-t">India</div>
      <div class="door-d">The national balance sheet, growth engines, inflation, the RBI's three levers, oil and the rupee as India lives it, flows and positioning, fiscal policy and politics, a decade of drawdowns.</div>
      <div class="door-go">Start the India framework →</div></a>
    <a class="door door-gl" href="#gl-1"><div class="door-tag">Framework two · {n_gl} chapters</div><div class="door-t">Global and geopolitical</div>
      <div class="door-d">How six economies reach India, the dollar and US rates, oil and the Gulf, China, Europe and Japan, Russia and sanctions, India's borders, technology and the AI chip cycle, and this week's hot spots.</div>
      <div class="door-go">Start the global framework →</div></a>
    <a class="door door-pro" href="#today"><div class="door-tag">Already have the framework</div><div class="door-t">Today's brief</div>
      <div class="door-d">Verdict, regime, four lights, unusual moves and who they hit, winners and losers, what's coming, the risk radar.</div>
      <div class="door-go">Open the brief →</div></a>
  </div>
  <div class="pro-link">New here? Read the three-minute <a href="#pro">prologue: three variables, two frameworks →</a> <span class="door-prog" id="prog-text"></span></div>
  <div class="fig">{geo_tl}<div class="legend3"><span><i style="background:var(--accent)"></i>domestic</span><span><i style="background:#d97706"></i>global</span><span><i style="background:var(--red)"></i>geopolitical</span><span><i style="background:var(--green)"></i>policy</span></div>
  <div class="fig-cap">Each dot is covered in a chapter's history block. Hover a dot for the label.</div></div>
  <h2 class="b-h">How often each part updates</h2>
  <div class="fig"><table class="b-table freq"><thead><tr><th>Part of the page</th><th>Updates</th><th>How</th><th>Kept as a dated snapshot</th><th>Latest in this mockup</th></tr></thead><tbody>
    <tr><td>Charts and live numbers in every chapter</td><td><b>Daily</b>, after the evening data run</td><td>read straight from our database</td><td>the data history itself is kept; past views stop at the chosen date</td><td class="mono">data to {B["date"]}</td></tr>
    <tr><td>Today's brief: lights, unusual moves, risk radar</td><td><b>Daily</b></td><td>computed; the verdict line is written</td><td>yes, every run</td><td class="mono">{B["date"]}</td></tr>
    <tr><td>Storylines from the news desk</td><td><b>Weekly</b>, with smaller mid-week passes</td><td>the news-desk task over our news feed</td><td>yes, already (since 2026-09-06)</td><td class="mono">2026-10-12</td></tr>
    <tr><td>Hot spots chapter and heat matrix</td><td><b>Weekly</b>, and the same day if the news desk flags a major escalation</td><td>news desk plus a web check, sources linked</td><td>yes, from 2026-10-17</td><td class="mono">2026-10-17</td></tr>
    <tr><td>Regime clock</td><td><b>Weekly</b>; monthly data as released (CPI mid-month, IIP month-end)</td><td>computed</td><td>yes</td><td class="mono">August data</td></tr>
    <tr><td>House view and call log</td><td><b>Weekly</b>; scored a quarter later</td><td>written, then scored</td><td>yes, with its later score</td><td class="mono">2026-10-17</td></tr>
    <tr><td>Event studies and playbooks</td><td><b>Monthly</b> recompute</td><td>computed from our price history</td><td>yes, by version</td><td class="mono">2026-10-17</td></tr>
    <tr><td>External readings (Korea exports, AI capex)</td><td><b>Monthly</b> web check until each becomes a feed</td><td>web, shown separately with source and date</td><td>yes, with the source link</td><td class="mono">2026-10-17</td></tr>
    <tr><td>Chapter prose and history blocks</td><td><b>Monthly</b>, and sooner when a "would change" trigger fires</td><td>written, web-checked</td><td>yes, every version</td><td class="mono">2026-10-17</td></tr>
  </tbody></table><div class="fig-cap">Proposed cadence for the cockpit page (plan 0028). Nothing is overwritten: each refresh appends a dated snapshot to the database table <code>desk_snapshots</code>, the "As of" filter in the top bar opens any past date for every part, and charts viewed for a past date stop at that date. This mockup is a static build of 2026-10-17 with a retrospective archive of eight dates; the news desk runs weekly today.</div></div>
  <h2 class="b-h">How the two frameworks meet</h2>
  <div class="meet"><div class="m-in"><b>India framework</b><span>balance sheet · growth · inflation · RBI · flows · fiscal</span></div><div class="m-x">→ regime ←</div><div class="m-gl"><b>Global framework</b><span>US rates · oil · China · Europe · Japan · sanctions · borders</span></div></div>
  <div class="fig-cap" style="text-align:center">Both feed one question, are growth and inflation accelerating, which names the regime and organises the daily brief.</div>
</article>'''

CSS5 = C.CHART_CSS + """
  .doors3 { grid-template-columns: 1fr 1fr 1fr !important; }
  .door-in { border-color: var(--accent); background: linear-gradient(160deg, var(--accent-soft), var(--bg-card) 60%); }
  .door-gl { border-color: #d97706; background: linear-gradient(160deg, rgba(217,119,6,0.12), var(--bg-card) 60%); } .door-gl .door-tag, .door-gl .door-go { color: #d97706; }
  .pro-link { font-size: 14.5px; color: var(--text-secondary); margin: -10px 0 18px; }
  .start { max-width: 980px !important; }
  .meet { display: grid; grid-template-columns: 1fr auto 1fr; gap: 12px; align-items: center; }
  .meet > div:not(.m-x) { border-radius: 12px; padding: 12px 14px; } .meet b { display: block; font-size: 15px; margin-bottom: 4px; } .meet span { font-size: 13px; color: var(--text-secondary); }
  .m-in { border: 1px solid var(--accent); background: var(--accent-soft); } .m-gl { border: 1px solid #d97706; background: rgba(217,119,6,0.10); }
  .m-x { font-weight: 700; color: var(--amber); }
  .trk { display: inline-block; font-size: 10.5px; padding: 1px 8px; border-radius: 999px; margin-right: 6px; letter-spacing: .06em; }
  .tr-in .trk { background: var(--accent-soft); color: var(--accent); } .tr-gl .trk { background: rgba(217,119,6,0.15); color: #d97706; }
  .tr-sy .trk { background: var(--green-bg); color: var(--green); } .tr-pro .trk { background: rgba(142,144,172,0.15); color: var(--text-secondary); }
  .toc-g { font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase; margin: 14px 0 4px 8px; font-weight: 700; }
  .toc-g-prologue { color: var(--text-muted); margin-top: 4px; } .toc-g-india { color: var(--accent); } .toc-g-global { color: #d97706; } .toc-g-synthesis { color: var(--green); }
  .histblock { margin: 22px 0; border: 1px solid var(--border-accent); border-radius: 12px; padding: 12px 14px; background: var(--bg-card); }
  .hb-h { font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: var(--amber); font-weight: 700; margin-bottom: 6px; }
  .hist-t th { font-size: 10.5px; } .hist-t td { padding: 7px 8px; } .tiny-t { font-size: 12.5px; color: var(--text-secondary); margin-top: 2px; }
  .bal4 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; } .bal4 > div { border: 1px solid var(--border-accent); border-radius: 10px; padding: 10px 12px; font-size: 13.5px; }
  .bal4 b { display: block; color: var(--text-primary); margin-bottom: 4px; } .bal4 span { color: var(--text-secondary); } .bal4 em { color: var(--amber); font-style: normal; }
  .hots { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0; }
  .hot { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; background: var(--bg-card); font-size: 13px; }
  .hot-h { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; } .hot-h b { font-size: 15px; color: var(--text-primary); }
  .hot-r { display: grid; grid-template-columns: 104px 1fr; gap: 8px; padding: 4px 0; border-top: 1px dashed var(--border); color: var(--text-secondary); }
  .hot-r .rl { font-size: 10.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); padding-top: 2px; }
  .hot-src { font-size: 11.5px; color: var(--text-muted); margin-top: 6px; }
  .t-esc, .t-elv, .t-eas, .t-calm { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; }
  .t-esc { color: var(--red); background: var(--red-bg); } .t-elv { color: var(--amber); background: var(--amber-bg); } .t-eas { color: var(--green); background: var(--green-bg); } .t-calm { color: var(--text-muted); background: rgba(142,144,172,0.12); }
  .srcbox, .extbox { margin: 16px 0; border: 1px solid var(--border); border-radius: 12px; padding: 10px 14px; background: var(--bg-card); font-size: 13px; }
  .extbox { border-color: rgba(59,130,246,0.5); } .extbox .hb-h { color: var(--blue); } .srcbox .hb-h { color: var(--text-muted); }
  .hotstrip { display: flex; flex-wrap: wrap; gap: 6px; } .hs { font-size: 12.5px; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border); }
  .hs.esc { color: var(--red); border-color: rgba(239,68,68,0.5); background: var(--red-bg); } .hs.elv { color: var(--amber); border-color: rgba(245,158,11,0.4); } .hs.calm { color: var(--text-muted); }
  .freq td:first-child { color: var(--text-primary); }
  a.xl::after { content: " ↗"; font-size: .8em; opacity: .7; } a.il { border-bottom: 1px dotted var(--accent); } a.xl { border-bottom: 1px dotted var(--accent); }
  .light-r a.rd { color: var(--text-primary); border-bottom: 1px dotted var(--text-muted); } .light-r a.rd:hover { border-bottom-color: var(--accent); }
  a.ind { text-decoration: none; } a.ind:hover { filter: brightness(1.25); }
  .topnav a { white-space: nowrap; padding: 12px 13px !important; }
  .asof { margin-left: auto; white-space: nowrap; display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-muted); padding: 0 6px; }
  .asof select { background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border-accent); border-radius: 8px; padding: 5px 8px; font: inherit; font-size: 13px; }
  .snapbar { background: var(--amber-bg); border: 1px solid rgba(245,158,11,0.45); color: var(--text-primary); border-radius: 10px; padding: 8px 12px; font-size: 13.5px; margin-bottom: 14px; }
  .asof-banner { background: var(--amber-bg); border: 1px solid rgba(245,158,11,0.45); border-radius: 10px; padding: 8px 12px; font-size: 13.5px; margin: 0 0 12px; }
  .snapnote { font-size: 13px; color: var(--text-secondary); margin: 10px 0 0; } .chg { font-size: 11px; color: var(--amber); margin-left: auto; }
  .dotgrid { width: 100%; font-size: 13px; } .dotgrid td, .dotgrid th { padding: 6px 4px; text-align: center; } .dotgrid td:first-child { text-align: left; color: var(--text-primary); white-space: nowrap; }
  .dg-d a { font-family: var(--mono); font-size: 11.5px; } .dotgrid .reg { font-size: 9.5px; } .b-table td:nth-child(1), .b-table td:nth-child(2) { white-space: nowrap; } .gdot { display: inline-block; width: 14px; height: 14px; border-radius: 50%; margin: 0 2px; vertical-align: -2px; }
  .g-red { background: var(--red); } .g-amber { background: var(--amber); } .g-green { background: var(--green); }
  @media (max-width: 900px) { .hots { grid-template-columns: 1fr; } .hot-r { grid-template-columns: 1fr; gap: 2px; } }
  @media (max-width: 900px) { .doors3, .meet, .bal4 { grid-template-columns: 1fr !important; } .hist-t td:first-child { white-space: normal; } }
"""

page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Indian macro framework</title>
<meta name="description" content="Mockup v5 of the cockpit's macro page (plan 0028): an India framework, a global and geopolitical framework, a synthesis, and today's brief, with charts and history on real data to 2026-10-16.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{BASE_CSS}{EXTRA_CSS}{v3.v2.EXTRA2}{v3.CSS3}{CSS5}</style>
</head>
<body>
<div class="topbar">
  <span class="crumb">Cockpit › <b>Macro</b></span>
  <span class="tag mock">Mockup v5 · plan 0028</span>
  <span class="right">data to 2026-10-16 · every figure from our DB · written prose carries no figures</span>
</div>
<nav class="topnav" id="topnav">
  <a href="#start" data-nav="start">Start</a>
  <a href="#in-1" data-nav="india">India<small>{n_in}</small></a>
  <a href="#gl-1" data-nav="global">Global<small>{n_gl}</small></a>
  <a href="#sy-1" data-nav="synthesis">Synthesis<small>3</small></a>
  <a href="#today" data-nav="today">Today's brief</a>
  <a href="#archive" data-nav="archive">Archive</a>
  <a href="#deeper" data-nav="deeper">Deeper</a>
  <label class="asof">As of <select id="asof" aria-label="View the brief as of a past date">{ASOF_OPTS}</select></label>
</nav>
<div class="wrap" style="padding:0 24px">
  {START}
  <div class="learn-wrap" data-view="learn-shell">
    <aside class="toc"><div class="toc-h">Your progress</div><div class="toc-bar"><i id="toc-bar"></i></div><div class="toc-list">{TOC}</div></aside>
    <div>{CHAPTER_VIEWS}</div>
  </div>
  {TODAY}
  {SNAP_VIEWS}
  {ARCHIVE}
  {v3.DEEPER_INDEX}
  {v3.DEEPER_VIEWS}
</div>
<script>
  const IDS = {ORDER!r};
  const store = {{
    get() {{ try {{ return JSON.parse(localStorage.getItem('macro-read-v5') || '[]'); }} catch (e) {{ return []; }} }},
    add(n) {{ try {{ const s = new Set(this.get()); s.add(n); localStorage.setItem('macro-read-v5', JSON.stringify([...s])); }} catch (e) {{}} }}
  }};
  function paint() {{
    const read = new Set(store.get());
    document.querySelectorAll('.toc-i').forEach(a => a.classList.toggle('read', read.has(a.dataset.ch)));
    const bar = document.getElementById('toc-bar'); if (bar) bar.style.width = (100 * read.size / IDS.length) + '%';
    const t = document.getElementById('prog-text'); if (t) t.textContent = read.size ? `· ${{read.size}} of ${{IDS.length}} chapters read` : '';
  }}
  function route() {{
    const h = (location.hash || '#start').slice(1);
    document.querySelectorAll('[data-view]').forEach(v => v.classList.remove('show'));
    let nav = 'start';
    if (IDS.includes(h)) {{
      document.querySelector('[data-view="learn-shell"]').classList.add('show');
      document.querySelector(`[data-view="${{h}}"]`).classList.add('show');
      store.add(h);
      nav = h === 'pro' ? 'start' : (h.startsWith('in-') ? 'india' : h.startsWith('gl-') ? 'global' : 'synthesis');
      document.querySelectorAll('.toc-i').forEach(a => a.classList.toggle('on', a.dataset.ch === h));
    }} else {{
      (document.querySelector(`[data-view="${{h}}"]`) || document.querySelector('[data-view="start"]')).classList.add('show');
      nav = h.startsWith('deeper') ? 'deeper' : (h === 'today' || h.startsWith('today@') ? 'today' : (h === 'archive' ? 'archive' : 'start'));
      const sel = document.getElementById('asof');
      if (sel && (h.startsWith('today') || h === 'archive')) sel.value = h.startsWith('today@') ? h.slice(6) : sel.options[0].value;
    }}
    document.querySelectorAll('#topnav a').forEach(a => a.classList.toggle('on', a.dataset.nav === nav));
    const asofSel = document.getElementById('asof'); const asofV = asofSel ? asofSel.value : null; const asofLatest = asofSel ? asofSel.options[0].value : null;
    document.querySelectorAll('.asof-banner').forEach(b => {{ const show = asofV && asofV !== asofLatest && asofV < '2026-10-17'; b.hidden = !show; const d = b.querySelector('.asof-d'); if (d) d.textContent = asofV; }});
    paint(); window.scrollTo(0, 0);
  }}
  window.addEventListener('hashchange', route);
  document.getElementById('asof').addEventListener('change', e => {{
    const latest = e.target.options[0].value;
    const cur = (location.hash || '').slice(1);
    if (IDS.includes(cur)) {{ route(); return; }}   // on a chapter: keep the chapter, show its version for that date
    location.hash = e.target.value === latest ? '#today' : '#today@' + e.target.value;
  }});
  document.querySelectorAll('a[href="#learn"]').forEach(a => a.setAttribute('href', '#deeper-lesson3'));
  document.querySelectorAll('a[href^="#learn-"]').forEach(a => {{ const m = {{'1':'pro','2':'in-1','3':'in-2','4':'in-3','5':'in-4','6':'in-5','7':'in-6','8':'gl-2','9':'in-7','10':'sy-1','11':'sy-2','12':'sy-3'}}[a.getAttribute('href').slice(7)]; if (m) a.setAttribute('href', '#' + m); }});
  route();
</script>
</body>
</html>
"""
page = LK.industry_links(page, INDUSTRIES)
OUT.write_text(page)

# ── export everything the page shows, for the desk_snapshots backfill (tools/desk_archive_backfill.py) ──
import re as _re
from chapters_v5 import EXTERNAL_ROWS, HOT_ROWS, HOT_COLS, HOT_CELLS, IRAN_RUNGS, TAIWAN_RUNGS
def _srcs(html):
    return [{"title": t, "url": u} for u, t in _re.findall(r'<a href="(https?://[^"]+)"[^>]*>([^<]+)</a>', html)]
chapters_export = []
for c in CH:
    art = _re.search(r'<article class="chapter[^"]*" data-view="' + c["id"] + r'">.*?</article>', page, _re.S).group(0)
    chapters_export.append({"id": c["id"], "track": c["track"], "title": c["title"], "html": art, "sources": _srcs(c.get("extra", ""))})
today_html = _re.search(r'<article class="brief" data-view="today">.*?</article>', page, _re.S).group(0)
export = {
    "built": "2026-10-17",
    "brief_snapshots": SNAPS,
    "brief_today": {"date": LATEST, "verdict": "The squeeze continues", "html": today_html, "lights": {k: SNAPS[-1][k] for k in ("oil", "us", "flows", "rbi")}},
    "hotspots": {"date": "2026-10-17", "rows": HOT_ROWS, "cols": HOT_COLS, "cells": [[r, c, v] for (r, c), v in HOT_CELLS.items()],
                 "ladders": {"iran": {"rungs": IRAN_RUNGS, "here": 5}, "taiwan": {"rungs": TAIWAN_RUNGS, "here": 1}},
                 "html": next(x["html"] for x in chapters_export if x["id"] == "gl-9"), "sources": next(x["sources"] for x in chapters_export if x["id"] == "gl-9")},
    "chapters": chapters_export,
    "external": EXTERNAL_ROWS,
    "house_view": [{"case": t, "likelihood": lk, "story": st, "signposts": sg, "wins": w, "loses": l, "assets": a} for _c, t, lk, st, sg, w, l, a in v3.v2.SCEN],
    "playbook": {"oil": D2["oil_playbook"], "us": D2["us_playbook"], "positioning": D2["pos_buckets"], "regime_table": RT, "events": D2["events"], "episodes": D2["episodes"]},
}
Path(__file__).with_name("desk_export.json").write_text(json.dumps(export, ensure_ascii=False))
print("export:", len(export["chapters"]), "chapters,", len(export["brief_snapshots"]), "brief snapshots,", len(export["external"]), "external readings")
print("wrote", OUT, len(page), "bytes")
