"""Macro mockup v3: a reader flow instead of a data layout.

Start here  →  Learn the basics (12 chapters, in order)  →  Today's brief (links back to chapters)  →  Go deeper (reference shelf).
Data and helpers come from core.py; the deep-dive sections are reused from build.py (v2).
Written prose carries no figures except years; every figure is inserted from the database.
"""
import build as v2                      # reuses the v2 deep-dive sections (no file write on import)
from core import *                      # noqa: F401,F403

T10 = f'{T["value"]:.2f}%'
def feed(v): return f'<span class="mono feedv">{v}</span>'
def ch_link(n, label=None):
    return f'<a class="chlink" href="#learn-{n}">{E(label or f"Chapter {n}")}</a>'

# ═══════════════════════════ the twelve chapters ═══════════════════════════
# Each: (title, minutes, hook html, body html, today html, so-what, words, deeper-id, deeper-label)

from chapters_pro import CHAPTERS   # practitioner-level chapters (v4)

def chapter_html(i, c):
    n = i + 1
    prev = f'<a class="nav-prev" href="#learn-{n-1}">← {E(CHAPTERS[i-1]["title"])}</a>' if i > 0 else '<a class="nav-prev" href="#start">← Start here</a>'
    nxt = (f'<a class="nav-next" href="#learn-{n+1}">Next: {E(CHAPTERS[i+1]["title"])} →</a>' if n < len(CHAPTERS)
           else '<a class="nav-next primary" href="#today">Open today\'s brief →</a>')
    inds = "".join(f'<tr><td>{E(a)}</td><td class="num">{b}</td></tr>' for a, b in c.get("indicators", []))
    deep_href = "#today" if c["deeper"] == "today" else f'#deeper-{c["deeper"]}'
    return f'''<article class="chapter" data-view="learn-{n}">
  <div class="ch-kicker">Chapter {n} of {len(CHAPTERS)} · {c["mins"]} minute read</div>
  <h1 class="ch-title">{E(c["title"])}</h1>
  <div class="ch-hook">{c["hook"]}</div>
  <div class="ch-body">{c["body"]}</div>
  {c["today"]}
  <div class="ch-sowhat"><b>So what for positioning.</b> {E(c["sowhat"])}</div>
  {f'<div class="ch-inds"><div class="ch-words-h">Indicators to track</div><table class="ind-t"><tbody>{inds}</tbody></table></div>' if inds else ""}
  <div class="ch-deeper">Want more? <a href="{deep_href}">{E(c["deeper_label"])} →</a></div>
  <div class="ch-nav">{prev}{nxt}</div>
</article>'''

CHAPTER_VIEWS = "".join(chapter_html(i, c) for i, c in enumerate(CHAPTERS))
TOC = "".join(f'<a class="toc-i" href="#learn-{i+1}" data-ch="{i+1}"><span class="toc-n">{i+1}</span><span class="toc-t">{E(c["title"])}</span><span class="toc-d">✓</span></a>' for i, c in enumerate(CHAPTERS))

# ═══════════════════════════ today's brief ═══════════════════════════

def light(color, title, reading, meaning, chap):
    return (f'<div class="light l-{color}"><div class="light-top"><span class="dot"></span><b>{E(title)}</b></div>'
            f'<div class="light-r">{reading}</div><div class="light-m">{E(meaning)}</div><div class="light-c">Mechanism: {ch_link(chap)}</div></div>')

LIGHTS = (
    light("red", "Oil", f'Brent {feed(fmt(B["value"]))}, {feed(sign(B["chg_63"]))} in three months',
          "A war premium from the closed Gulf route. Costly for India on every front.", 6)
  + light("red", "US rates and the dollar", f'US 10-year {feed(T10)}, near its record',
          "High US rates keep pulling foreign money out and pressing on the rupee.", 8)
  + light("amber", "Flows and positioning", f'FIIs {feed(rupee(F20["FII"]))}, DIIs {feed(rupee(F20["DII"]))} in 20 sessions',
          "Foreigners are selling hard; Indian funds are catching almost all of it.", 7)
  + light("red", "The RBI", "Raised rates in October; more likely",
          "The thermostat is turning down to defend the rupee and fight imported inflation.", 5))

mv_rows = ""
for m in D["movers"][:5]:
    helps, hurts, mixed = who_cares(m["id"], m["chg"])
    who = ""
    if helps: who += '<span class="tag-h">helps</span>' + chips(helps[:4], "h")
    if hurts: who += ' <span class="tag-x">hurts</span>' + chips(hurts[:4], "x")
    if mixed and not (helps or hurts): who += '<span class="tag-m">watch</span>' + chips(mixed[:4], "m")
    mv_rows += (f'<tr><td><b>{E(LABEL.get(m["id"], m["id"]))}</b></td><td class="num mono {"pos" if m["chg"] > 0 else "neg"}">'
                f'{sign(m["chg"], " bps" if m["unit"] == "bps" else "%")}</td><td class="mono tiny">{m["z"]:+.1f} σ</td><td>{who}</td></tr>')

WIN = [("IT and pharma exporters", "earn in dollars; gain when the rupee weakens", 6), ("Upstream oil producers", "sell at the higher oil price", 6),
       ("Defence", "government priority, orders keep coming", 9), ("Banks with cheap deposits", "lend at higher rates without paying much more for deposits", 5)]
LOSE = [("Airlines", "fuel is their biggest cost", 6), ("Paints", "raw materials come from crude", 6), ("Autos", "dearer loans and dearer fuel", 5),
        ("Property developers", "home loans get costlier", 5), ("Shadow banks", "borrow in the market, so their costs rise first", 5)]
def sector_list(items, cls):
    return "".join(f'<div class="sec-i {cls}"><b>{E(a)}</b><span>{E(b)} · {ch_link(c, "why")}</span></div>' for a, b, c in items)

radar_compact = "".join(f'<div class="rc rc-{c}"><span class="rr-dot"></span><b>{E(n)}</b><span class="tiny">{E(r)}</span></div>' for n, r, c, rule in radar)

TODAY = f'''<article class="brief" data-view="today">
  <div class="ch-kicker">Today's brief · data to {B["date"]} · about five minutes</div>
  <h1 class="ch-title">The squeeze continues</h1>
  <div class="verdict">Oil is up, America's rates are high, and the RBI has started raising rates to protect the rupee. Foreign investors are selling; Indian
  savers are buying. The market is under pressure but not panicking. The one thing to watch: whether the Gulf sea route reopens.</div>

  <h2 class="b-h">1 · The season <span class="b-sub">Mechanism: {ch_link(10)}</span></h2>
  <div class="season-now"><span class="pill-season">{india_quad}</span> Growth and inflation are both rising. Hot summer: companies sell more, but rates are going up. The risk is a turn to stagflation.</div>

  <h2 class="b-h">2 · The four lights <span class="b-sub">the three variables from chapter one, plus the RBI</span></h2>
  <div class="lights">{LIGHTS}</div>

  <h2 class="b-h">3 · What changed yesterday</h2>
  <p class="b-p">IT stocks had the most unusual day, jumping {feed(sign(D["movers"][0]["chg"]))}, as fears eased that AI will eat IT services work. The rupee
  firmed to {feed(fmt(U["value"]))} as the RBI's new defences took hold. Oil climbed another {feed(sign(B["chg_1"]))}. Foreigners were net buyers for one day,
  {feed(rupee(FL["FII"]))}, but one day is not a trend.</p>
  <table class="b-table"><thead><tr><th>Biggest unusual moves</th><th class="num">Move</th><th>How unusual</th><th>Who it helps or hurts</th></tr></thead><tbody>{mv_rows}</tbody></table>
  <div class="tiny">"How unusual" compares the move with a normal day; two σ happens about one day in twenty. <a href="#deeper-data">All moves and the latest data →</a></div>

  <h2 class="b-h">4 · Who wins and who loses right now</h2>
  <div class="winlose"><div><div class="wl-h win">Doing better in this setup</div>{sector_list(WIN, "win")}</div>
  <div><div class="wl-h lose">Under pressure</div>{sector_list(LOSE, "lose")}</div></div>
  <div class="tiny">From the house view and the 38 industry pages. Open any industry in Sectors for the detail. <a href="#deeper-playbook">The three scenarios →</a></div>

  <h2 class="b-h">5 · What's coming</h2>
  <div class="coming">
    <div><b>End of October</b><span>Factory output for September: did factories slow as rates rose?</span></div>
    <div><b>Mid-November</b><span>Inflation for October: the first full month of the oil shock in prices.</span></div>
    <div><b>Next RBI meeting</b><span>Was October a one-off, or the start of a series?</span></div>
    <div><b>November</b><span>US midterm elections: tariffs and spending for the next two years.</span></div>
  </div>

  <h2 class="b-h">6 · Risk radar <span class="b-sub">eight tail risks, coloured by rules on live data</span></h2>
  <div class="radar-c">{radar_compact}</div>

  <div class="ch-nav"><a class="nav-prev" href="#learn-12">← The daily routine</a><a class="nav-next" href="#deeper">Go deeper →</a></div>
</article>'''

# ═══════════════════════════ go deeper ═══════════════════════════

SHELVES = [
    ("plumbing", "The plumbing", "How money flows from savers to borrowers and the world, and where the pipes burst.", v2.M1),
    ("twin", "The twin deficits", "Oil, the rupee and the RBI's tools, with what each one costs.", v2.M2),
    ("engines", "The five engines", "What drives each engine, how it reaches stocks, where it stands.", v2.M3),
    ("referees", "The referees", "The RBI, the Budget, the GST Council, SEBI and the states: how each behaves and what's next.", v2.M4),
    ("politics", "The political economy", "What the government wants, its record, and likely next moves.", v2.M5),
    ("history", "History that still bites", "Nine episodes from 1991 to 2024 and how closely each rhymes with today.", v2.M6),
    ("world", "The world", "The US, China, Europe, Japan, the Gulf and Russia: how each one reaches India.", v2.WORLD_HTML),
    ("us", "The US card", "Rates, the dollar, tariffs and visas.", v2.world_card(*v2.WORLD[0])),
    ("shock", "Shock walk-through", "Today's oil shock, step by step, with live numbers.", v2.W6),
    ("playbook", "The playbook", "What worked in each season, three scenarios, the risk radar, the asset lens, the call log.", v2.PLAY),
    ("data", "The data room", "Every gauge: the season chart, rates, positioning, flows, all moves, monthly prints, the reverse dial index.", v2.CLOCK + v2.P1 + v2.P2 + v2.P4),
    ("news", "Storylines", "The news desk's seven themes in full.", v2.P3),
    ("lesson3", "Worked lesson: CPI", "Read an inflation release, step by step, on our data.", v2.L3),
    ("lesson7", "Worked lesson: flows", "Read FII and DII flows without over-reading them.", v2.L7),
    ("lesson10", "Worked lesson: oil and the rupee", "The twin-deficit chain on live numbers.", v2.L10),
    ("glossary", "Glossary", "Every term in plain words.", v2.card("§", "Glossary", "every term on this page", "One line each, plain words.", v2.gloss_html)),
]
SHELF_GRID = "".join(f'<a class="shelf" href="#deeper-{k}"><b>{E(t)}</b><span>{E(d)}</span></a>' for k, t, d, _ in SHELVES if k != "us")
DEEPER_INDEX = f'''<article class="deeper-index" data-view="deeper">
  <div class="ch-kicker">Go deeper · the reference shelf</div>
  <h1 class="ch-title">Everything behind the brief</h1>
  <p class="b-p">The chapters teach the ideas and the brief applies them. This shelf holds the detail: the tools, the history, the world, the data. Dip in when a chapter or the brief makes you curious.</p>
  <div class="shelves">{SHELF_GRID}</div>
</article>'''
DEEPER_VIEWS = "".join(f'<article class="deep" data-view="deeper-{k}"><div class="deep-back"><a href="#deeper">← The shelf</a> · <a href="#today">Today\'s brief</a></div>{html_}</article>'
                       for k, t, d, html_ in SHELVES)

# ═══════════════════════════ start here ═══════════════════════════

START = f'''<article class="start" data-view="start">
  <div class="start-hero">
    <div class="ch-kicker">Macro for Indian equities</div>
    <h1 class="start-title">The framework, then today's read.</h1>
    <p class="start-sub">Twelve short chapters on how Indian macro actually transmits to equities, and a five-minute daily brief that applies them to live data. Every brief item links to the mechanism behind it.</p>
  </div>
  <div class="doors">
    <a class="door door-new" href="#learn-1"><div class="door-tag">Build the framework</div><div class="door-t">The twelve chapters</div>
      <div class="door-d">India-specific mechanisms, not definitions: the balance sheet, the RBI's three levers, the oil chain, flows and positioning, the US transmission, fiscal and political economy, regimes, and a full case study of the current shock.</div>
      <div class="door-go">Start with chapter 1 →</div><div class="door-prog" id="prog-text"></div></a>
    <a class="door door-pro" href="#today"><div class="door-tag">Already have the framework</div><div class="door-t">Today's brief</div>
      <div class="door-d">Verdict, regime, four lights, the unusual moves and who they hit, the sector map, what's coming, the risk radar.</div>
      <div class="door-go">Open the brief →</div></a>
  </div>
  <h2 class="b-h">How this page works</h2>
  <div class="howto">
    <div><span class="howto-n">1</span><b>Learn</b><span>The mechanisms, once, in order. Each chapter ends with where it stands now and the indicators to track.</span></div>
    <div class="howto-a">→</div>
    <div><span class="howto-n">2</span><b>Today</b><span>The daily brief applies those ideas to the latest data. Five minutes with your tea.</span></div>
    <div class="howto-a">→</div>
    <div><span class="howto-n">3</span><b>Go deeper</b><span>The reference shelf: the RBI's tools, history, the world, the full data room.</span></div>
  </div>
  <h2 class="b-h">The three variables that explain most of the market</h2>
  <div class="q3">
    <div><b>Oil</b><span>The terms-of-trade shock: current account, rupee, CPI, fiscal and margins in one move.</span><a href="#learn-6">Chapter 6 →</a></div>
    <div><b>US real yields and the dollar</b><span>The price of India's valuation premium and the driver of foreign flows.</span><a href="#learn-8">Chapter 8 →</a></div>
    <div><b>Domestic flows</b><span>The structural buyer that now absorbs foreign selling, and the risk if it stalls.</span><a href="#learn-7">Chapter 7 →</a></div>
  </div>
</article>'''

# ═══════════════════════════ page ═══════════════════════════

CSS3 = """
  body { font-size: 15.5px; }
  .wrap { display: block; max-width: 1180px; }
  .topnav { position: sticky; top: 49px; z-index: 15; background: var(--bg-primary); border-bottom: 1px solid var(--border); display: flex; gap: 4px; padding: 0 24px; max-width: 1180px; margin: 0 auto; }
  .topnav a { padding: 12px 16px; color: var(--text-secondary); font-weight: 600; font-size: 15px; border-bottom: 2px solid transparent; }
  .topnav a.on { color: var(--accent); border-bottom-color: var(--accent); }
  .topnav a small { color: var(--text-muted); font-weight: 500; font-size: 11px; margin-left: 6px; }
  [data-view] { display: none; } [data-view].show { display: block; }
  .ch-kicker { font-size: 12px; letter-spacing: .1em; text-transform: uppercase; color: var(--text-muted); margin-bottom: 6px; }
  .ch-title { font-size: 32px; line-height: 1.2; letter-spacing: -0.02em; margin: 0 0 18px; font-weight: 800; }
  /* reading column */
  .chapter, .brief, .deeper-index, .start { max-width: 760px; margin: 0 auto; padding: 28px 0 60px; }
  .learn-wrap { grid-template-columns: 250px minmax(0, 1fr); gap: 36px; } .learn-wrap.show { display: grid; }
  .toc { position: sticky; top: 110px; align-self: start; padding-top: 28px; }
  .toc-h { font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: var(--text-muted); margin-bottom: 8px; }
  .toc-bar { height: 4px; background: var(--border); border-radius: 2px; margin-bottom: 10px; overflow: hidden; } .toc-bar i { display: block; height: 100%; background: var(--accent); width: 0; }
  .toc-i { display: grid; grid-template-columns: 22px 1fr 14px; gap: 6px; padding: 6px 8px; border-radius: 8px; color: var(--text-secondary); font-size: 13px; line-height: 1.35; }
  .toc-i:hover, .toc-i.on { background: var(--accent-soft); color: var(--text-primary); }
  .toc-n { font-family: var(--mono); color: var(--text-muted); font-size: 12px; } .toc-d { color: var(--green); visibility: hidden; } .toc-i.read .toc-d { visibility: visible; }
  .ch-hook p { font-size: 18px; line-height: 1.7; color: var(--text-primary); }
  .ch-body p, .b-p { font-size: 16.5px; line-height: 1.75; color: var(--text-secondary); margin: 0 0 16px; }
  .ch-body b, .b-p b { color: var(--text-primary); }
  ol.big3 { margin: 0 0 18px; padding-left: 22px; font-size: 16px; line-height: 1.7; color: var(--text-secondary); } ol.big3 li { margin: 6px 0; } ol.big3 b { color: var(--text-primary); }
  .flow4 { display: grid; grid-template-columns: 1fr auto 1fr auto 1fr auto 1fr; gap: 6px; align-items: stretch; margin: 6px 0 20px; }
  .flow4 > div:not(.arr) { border: 1px solid var(--border-accent); border-radius: 12px; padding: 10px; background: var(--bg-card); font-size: 13px; }
  .flow4 b { display: block; color: var(--text-primary); margin-bottom: 4px; } .flow4 span { color: var(--text-secondary); }
  .flow4 .arr { color: var(--accent); font-size: 22px; font-weight: 700; display: grid; place-items: center; }
  .engines5 { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 4px 0 20px; }
  .engines5 > div { border: 1px solid var(--border-accent); border-radius: 12px; padding: 10px; background: var(--bg-card); font-size: 13px; }
  .engines5 b { display: block; color: var(--text-primary); margin-bottom: 4px; } .engines5 span { color: var(--text-secondary); }
  .seasons { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 4px 0 20px; }
  .seasons > div { border-radius: 12px; padding: 12px; font-size: 14px; border: 1px solid var(--border-accent); }
  .seasons b { display: block; color: var(--text-primary); margin-bottom: 4px; font-size: 15px; } .seasons span { color: var(--text-secondary); }
  .s-gold { background: rgba(34,197,94,0.08); } .s-ref { background: rgba(245,158,11,0.10); outline: 2px solid var(--amber); } .s-stag { background: rgba(239,68,68,0.08); } .s-def { background: rgba(59,130,246,0.08); }
  .seeit { margin: 22px 0; border: 1px solid var(--accent); border-radius: 14px; padding: 14px 16px; background: var(--accent-soft); }
  .seeit-h { font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: var(--accent); font-weight: 700; margin-bottom: 6px; }
  .seeit-r { font-size: 15px; line-height: 1.6; color: var(--text-primary); padding: 4px 0; }
  .seeit-two { display: grid; grid-template-columns: 220px 1fr; gap: 16px; align-items: center; }
  .feedv { color: var(--text-primary); font-weight: 600; background: rgba(255,255,255,0.05); padding: 0 4px; border-radius: 4px; }
  .ch-sowhat { margin: 18px 0; padding: 14px 16px; border-left: 4px solid var(--accent); background: var(--bg-card); border-radius: 0 12px 12px 0; font-size: 16px; line-height: 1.6; color: var(--text-primary); }
  .ch-sowhat b { color: var(--accent); }
  .ch-words { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 14px 0; }
  .ch-words-h { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--text-muted); margin-right: 4px; }
  .word { font-size: 12.5px; padding: 3px 10px; border-radius: 999px; border: 1px solid var(--border-accent); color: var(--text-secondary); }
  .ch-inds { margin: 16px 0; } .ind-t { width: 100%; } .ind-t td { padding: 6px 8px; font-size: 13.5px; border-bottom: 1px solid var(--border); color: var(--text-secondary); } .ind-t td:first-child { color: var(--text-primary); }
  ul.pts { margin: 0 0 18px; padding-left: 20px; font-size: 16px; line-height: 1.7; color: var(--text-secondary); } ul.pts li { margin: 8px 0; } ul.pts b { color: var(--text-primary); }
  .ch-deeper { font-size: 14px; color: var(--text-muted); margin: 10px 0 26px; }
  .ch-nav { display: flex; justify-content: space-between; gap: 12px; border-top: 1px solid var(--border); padding-top: 18px; margin-top: 18px; }
  .ch-nav a { font-size: 14px; color: var(--text-secondary); max-width: 48%; } .ch-nav a:hover { color: var(--text-primary); }
  .nav-next { margin-left: auto; text-align: right; color: var(--accent) !important; font-weight: 600; }
  .nav-next.primary { background: var(--accent); color: #fff !important; padding: 10px 16px; border-radius: 10px; }
  .chlink { font-size: 0.92em; white-space: nowrap; }
  ol.story { margin: 0 0 16px; padding-left: 0; list-style: none; counter-reset: st; }
  ol.story li { counter-increment: st; position: relative; padding: 10px 0 10px 42px; border-bottom: 1px solid var(--border); font-size: 15.5px; line-height: 1.6; color: var(--text-secondary); }
  ol.story li::before { content: counter(st); position: absolute; left: 0; top: 10px; width: 28px; height: 28px; border-radius: 50%; background: var(--accent-soft); color: var(--accent); font-weight: 700; display: grid; place-items: center; font-family: var(--mono); font-size: 13px; }
  ol.story b { color: var(--text-primary); }
  ol.routine { list-style: none; padding: 0; margin: 0 0 18px; counter-reset: r; }
  ol.routine li { counter-increment: r; display: grid; grid-template-columns: 36px 1fr; gap: 4px 10px; padding: 10px 0; border-bottom: 1px solid var(--border); }
  ol.routine li::before { content: counter(r); grid-row: span 2; width: 28px; height: 28px; border-radius: 50%; background: var(--accent); color: #fff; font-weight: 700; display: grid; place-items: center; }
  ol.routine b { color: var(--text-primary); font-size: 16px; } ol.routine span { color: var(--text-secondary); font-size: 15px; }
  /* start */
  .start-title { font-size: 40px; line-height: 1.15; letter-spacing: -0.02em; margin: 0 0 14px; font-weight: 800; }
  .start-sub { font-size: 18px; color: var(--text-secondary); margin: 0 0 26px; }
  .doors { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 30px; }
  .door { display: block; border-radius: 16px; padding: 20px; border: 1px solid var(--border-accent); background: var(--bg-card); color: var(--text-primary); transition: transform .15s, border-color .15s; }
  .door:hover { transform: translateY(-2px); border-color: var(--accent); }
  .door-new { border-color: var(--accent); background: linear-gradient(160deg, var(--accent-soft), var(--bg-card) 60%); }
  .door-tag { font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: var(--accent); font-weight: 700; }
  .door-t { font-size: 24px; font-weight: 800; margin: 4px 0 8px; } .door-d { font-size: 15px; color: var(--text-secondary); line-height: 1.6; }
  .door-go { margin-top: 14px; font-weight: 700; color: var(--accent); } .door-prog { font-size: 12px; color: var(--text-muted); margin-top: 6px; }
  .howto { display: grid; grid-template-columns: 1fr auto 1fr auto 1fr; gap: 8px; align-items: stretch; margin-bottom: 28px; }
  .howto > div:not(.howto-a) { border: 1px solid var(--border); border-radius: 12px; padding: 12px; background: var(--bg-card); font-size: 14px; }
  .howto b { display: block; color: var(--text-primary); font-size: 16px; margin: 4px 0; } .howto span:not(.howto-n) { color: var(--text-secondary); }
  .howto-n { display: inline-grid; place-items: center; width: 24px; height: 24px; border-radius: 50%; background: var(--accent-soft); color: var(--accent); font-weight: 700; font-family: var(--mono); font-size: 12px; }
  .howto-a { color: var(--accent); font-size: 24px; display: grid; place-items: center; }
  .q3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .q3 > div { border: 1px solid var(--border); border-radius: 12px; padding: 12px; background: var(--bg-card); font-size: 14px; display: flex; flex-direction: column; gap: 6px; }
  .q3 b { color: var(--text-primary); font-size: 15px; } .q3 span { color: var(--text-secondary); flex: 1; }
  /* brief */
  .verdict { font-size: 18px; line-height: 1.7; color: var(--text-primary); padding: 16px 18px; border-radius: 14px; background: var(--bg-card); border: 1px solid var(--border-accent); margin-bottom: 8px; }
  .b-h { font-size: 19px; margin: 30px 0 12px; display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
  .b-sub { font-size: 12.5px; color: var(--text-muted); font-weight: 500; }
  .season-now { font-size: 16px; color: var(--text-secondary); line-height: 1.6; }
  .pill-season { display: inline-block; padding: 3px 12px; border-radius: 999px; background: var(--amber-bg); color: var(--amber); font-weight: 700; margin-right: 8px; border: 1px solid rgba(245,158,11,0.4); }
  .lights { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .light { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; background: var(--bg-card); }
  .light-top { display: flex; align-items: center; gap: 8px; font-size: 16px; } .light .dot { width: 12px; height: 12px; border-radius: 50%; }
  .l-red .dot { background: var(--red); box-shadow: 0 0 0 4px var(--red-bg); } .l-amber .dot { background: var(--amber); box-shadow: 0 0 0 4px var(--amber-bg); } .l-green .dot { background: var(--green); box-shadow: 0 0 0 4px var(--green-bg); }
  .light-r { font-size: 14.5px; margin: 8px 0 4px; color: var(--text-primary); } .light-m { font-size: 14px; color: var(--text-secondary); } .light-c { font-size: 12.5px; color: var(--text-muted); margin-top: 6px; }
  .b-table td, .b-table th { font-size: 13.5px; }
  .winlose { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .wl-h { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; font-weight: 700; margin-bottom: 6px; } .wl-h.win { color: var(--green); } .wl-h.lose { color: var(--red); }
  .sec-i { border-left: 3px solid var(--border-accent); padding: 6px 10px; margin-bottom: 6px; background: var(--bg-card); border-radius: 0 8px 8px 0; }
  .sec-i.win { border-left-color: var(--green); } .sec-i.lose { border-left-color: var(--red); }
  .sec-i b { display: block; color: var(--text-primary); font-size: 14.5px; } .sec-i span { font-size: 13px; color: var(--text-secondary); }
  .coming { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .coming > div { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; background: var(--bg-card); }
  .coming b { display: block; color: var(--text-primary); } .coming span { font-size: 13.5px; color: var(--text-secondary); }
  .radar-c { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .rc { display: grid; grid-template-columns: 16px 130px 1fr; gap: 8px; align-items: start; font-size: 13px; padding: 6px 8px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-card); }
  .rc .rr-dot { width: 10px; height: 10px; border-radius: 50%; margin-top: 4px; }
  .rc-red .rr-dot { background: var(--red); } .rc-amber .rr-dot { background: var(--amber); } .rc-green .rr-dot { background: var(--green); }
  /* deeper */
  .shelves { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
  .shelf { display: block; border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; background: var(--bg-card); color: var(--text-primary); }
  .shelf:hover { border-color: var(--accent); } .shelf b { display: block; font-size: 15px; margin-bottom: 4px; } .shelf span { font-size: 13px; color: var(--text-secondary); }
  .deep { padding: 20px 0 60px; } .deep-back { font-size: 13px; margin-bottom: 12px; }
  .deep .card { margin-bottom: 18px; }
  @media (max-width: 900px) {
    .learn-wrap { grid-template-columns: 1fr; } .learn-wrap.show { display: block; } .toc { position: static; padding-top: 12px; }
    .toc-list { display: flex; overflow-x: auto; gap: 4px; } .toc-i { grid-template-columns: 18px auto; white-space: nowrap; } .toc-t { display: none; } .toc-i .toc-d { display: none; }
    .ch-title { font-size: 26px; } .start-title { font-size: 30px; }
    .doors, .howto, .q3, .lights, .winlose, .coming, .radar-c, .seasons, .seeit-two { grid-template-columns: 1fr; }
    .howto-a { transform: rotate(90deg); } .flow4 { grid-template-columns: 1fr; } .flow4 .arr { transform: rotate(90deg); } .engines5 { grid-template-columns: 1fr 1fr; }
    .topnav { padding: 0 8px; overflow-x: auto; top: 41px; } .topnav a { padding: 10px 10px; white-space: nowrap; font-size: 14px; } .topnav a small { display: none; }
    .rc { grid-template-columns: 14px 1fr; } .rc .tiny { grid-column: 2; }
    .radar, .ref-grid, .eng-grid, .themes, .gauges, .shelves, .scen, .world { grid-template-columns: 1fr !important; }
    table { display: block; overflow-x: auto; }
  }
"""

page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Indian macro framework</title>
<meta name="description" content="Mockup v3 of the cockpit's macro page (plan 0028): start here, twelve chapters, today's brief, go deeper. Real data to 2026-10-16.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{BASE_CSS}{EXTRA_CSS}{v2.EXTRA2}{CSS3}</style>
</head>
<body>
<div class="topbar">
  <span class="crumb">Cockpit › <b>Macro</b></span>
  <span class="tag mock">Mockup v4 · plan 0028</span>
  <span class="right">data to 2026-10-16 · every figure from our DB · written prose carries no figures</span>
</div>
<nav class="topnav" id="topnav">
  <a href="#start" data-nav="start">Start here</a>
  <a href="#learn-1" data-nav="learn">The framework<small>12 chapters</small></a>
  <a href="#today" data-nav="today">Today's brief<small>5 minutes</small></a>
  <a href="#deeper" data-nav="deeper">Go deeper<small>reference</small></a>
</nav>
<div class="wrap" style="padding:0 24px">
  {START}
  <div class="learn-wrap" data-view="learn-shell">
    <aside class="toc"><div class="toc-h">The framework · your progress</div><div class="toc-bar"><i id="toc-bar"></i></div><div class="toc-list">{TOC}</div></aside>
    <div>{CHAPTER_VIEWS}</div>
  </div>
  {TODAY}
  {DEEPER_INDEX}
  {DEEPER_VIEWS}
</div>
<script>
  const N = {len(CHAPTERS)};
  const store = {{
    get() {{ try {{ return JSON.parse(localStorage.getItem('macro-read') || '[]'); }} catch (e) {{ return []; }} }},
    add(n) {{ try {{ const s = new Set(this.get()); s.add(n); localStorage.setItem('macro-read', JSON.stringify([...s])); }} catch (e) {{}} }}
  }};
  function paintProgress() {{
    const read = new Set(store.get());
    document.querySelectorAll('.toc-i').forEach(a => a.classList.toggle('read', read.has(+a.dataset.ch)));
    const bar = document.getElementById('toc-bar'); if (bar) bar.style.width = (100 * read.size / N) + '%';
    const t = document.getElementById('prog-text');
    if (t) t.textContent = read.size ? `You have read ${{read.size}} of ${{N}} chapters` : '';
  }}
  function route() {{
    const h = (location.hash || '#start').slice(1);
    const views = document.querySelectorAll('[data-view]');
    views.forEach(v => v.classList.remove('show'));
    let nav = 'start';
    if (h.startsWith('learn-')) {{
      document.querySelector('[data-view="learn-shell"]').classList.add('show');
      const v = document.querySelector(`[data-view="${{h}}"]`); (v || document.querySelector('[data-view="learn-1"]')).classList.add('show');
      const n = +h.split('-')[1]; store.add(n); nav = 'learn';
      document.querySelectorAll('.toc-i').forEach(a => a.classList.toggle('on', +a.dataset.ch === n));
    }} else {{
      const v = document.querySelector(`[data-view="${{h}}"]`) || document.querySelector('[data-view="start"]');
      v.classList.add('show');
      nav = h.startsWith('deeper') ? 'deeper' : (h === 'today' ? 'today' : 'start');
    }}
    document.querySelectorAll('#topnav a').forEach(a => a.classList.toggle('on', a.dataset.nav === nav));
    paintProgress();
    window.scrollTo(0, 0);
  }}
  window.addEventListener('hashchange', route);
  // links inside reused deep sections that point to the old #learn anchor
  document.querySelectorAll('a[href="#learn"]').forEach(a => a.setAttribute('href', '#deeper-lesson3'));
  route();
</script>
</body>
</html>
"""
if __name__ == "__main__":
    OUT.write_text(page)
    print("wrote", OUT, len(page), "bytes")
