"""SVG charts and diagrams for mockup v5. One y-axis per chart (stacked panels instead of dual axes),
episode bands labelled directly, hover titles on marks. Colours come from the page's CSS tokens."""
from datetime import date
from html import escape as E

def _d(s): y, m, d = map(int, s[:10].split("-")); return date(y, m, d).toordinal()

def _ticks(lo, hi, n=4):
    span = hi - lo or 1
    raw = span / n
    mag = 10 ** len(str(int(raw))) / 10 if raw >= 1 else 0.1
    for step in (1, 2, 2.5, 5, 10):
        if raw <= step * mag: break
    step *= mag
    t = (int(lo / step)) * step
    out = []
    while t <= hi + 1e-9:
        if t >= lo - 1e-9: out.append(round(t, 6))
        t += step
    return out

def line_panel(series, w=720, h=170, color="var(--accent)", label="", unit="", episodes=(), x_range=None, fmt="{:,.0f}",
               ref=None, show_years=True, area=False, markers=(), gap_days=70):
    """series: [[date, value], ...]. episodes: [(start, end, text)]. markers: [(date, text)]."""
    xs = [_d(p[0]) for p in series]; ys = [p[1] for p in series]
    x0, x1 = x_range or (min(xs), max(xs))
    lo, hi = min(ys + ([ref] if ref is not None else [])), max(ys + ([ref] if ref is not None else []))
    pad = (hi - lo) * 0.08 or 1; lo -= pad; hi += pad
    if area: hi = max(hi, 0); lo = min(lo, 0)
    L, R, T, B = 48, 12, 18, 22
    def X(x): return L + (x - x0) / (x1 - x0) * (w - L - R)
    def Y(y): return T + (hi - y) / (hi - lo) * (h - T - B)
    g = []
    for a, b, txt in episodes:
        xa, xb = X(max(_d(a), x0)), X(min(_d(b), x1))
        if xb < L or xa > w - R: continue
        g.append(f'<rect x="{xa:.1f}" y="{T}" width="{max(2, xb - xa):.1f}" height="{h - T - B}" class="ep"><title>{E(txt)}</title></rect>'
                 f'<text x="{xa + 2:.1f}" y="{T + 9}" class="ep-t">{E(txt)}</text>')
    for t in _ticks(lo, hi):
        g.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="gl"/><text x="{L - 6}" y="{Y(t) + 3:.1f}" text-anchor="end" class="ax">{fmt.format(t)}</text>')
    if show_years:
        y0, y1 = date.fromordinal(int(x0)).year, date.fromordinal(int(x1)).year
        step = 1 if y1 - y0 <= 6 else 2
        for yr in range(y0 + 1, y1 + 1, step):
            xx = X(date(yr, 1, 1).toordinal())
            if L < xx < w - R: g.append(f'<text x="{xx:.1f}" y="{h - 6}" text-anchor="middle" class="ax">{yr}</text>')
    if ref is not None:
        g.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(ref):.1f}" y2="{Y(ref):.1f}" class="refl"/>')
    pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xs, ys))
    segs, cur = [], []
    for i, (x, y) in enumerate(zip(xs, ys)):
        if cur and x - xs[i - 1] > gap_days:
            segs.append(cur); cur = []
        cur.append(f"{X(x):.1f},{Y(y):.1f}")
    segs.append(cur)
    if area:
        g.append(f'<polygon points="{X(xs[0]):.1f},{Y(0):.1f} {pts} {X(xs[-1]):.1f},{Y(0):.1f}" style="fill:{color};opacity:.22"/>')
    for sg in segs:
        g.append(f'<polyline points="{" ".join(sg)}" style="fill:none;stroke:{color};stroke-width:1.8"/>')
    g.append(f'<circle cx="{X(xs[-1]):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5" style="fill:{color}"><title>{series[-1][0]}: {fmt.format(ys[-1])}{unit}</title></circle>')
    for d, txt in markers:
        xx = X(_d(d))
        g.append(f'<line x1="{xx:.1f}" x2="{xx:.1f}" y1="{T}" y2="{h - B}" class="mk"/><text x="{xx + 3:.1f}" y="{h - B - 4}" class="mk-t">{E(txt)}</text>')
    g.append(f'<text x="{L}" y="11" class="lab" style="fill:{color}">{E(label)}</text><text x="{w - R}" y="11" text-anchor="end" class="lab-v">{fmt.format(ys[-1])}{E(unit)} · {series[-1][0]}</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" class="chart" role="img" aria-label="{E(label)}">{"".join(g)}</svg>'

def stacked(*panels):
    return '<div class="stack">' + "".join(panels) + "</div>"

def event_study(events, w=720, h=260, highlight=None, title=""):
    """events: [{name, path(36 pts from -5..+30)}]. Grey lines, mean in accent, highlight one in amber."""
    allv = [v for e in events for v in e["path"]]
    lo, hi = min(allv + [100]) - 1, max(allv + [100]) + 1
    L, R, T, B = 44, 150, 18, 26
    def X(k): return L + (k + 5) / 35 * (w - L - R)
    def Y(v): return T + (hi - v) / (hi - lo) * (h - T - B)
    g = []
    for t in _ticks(lo, hi):
        g.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="gl"/><text x="{L - 6}" y="{Y(t) + 3:.1f}" text-anchor="end" class="ax">{t:g}</text>')
    for k in (-5, 0, 10, 20, 30):
        g.append(f'<text x="{X(k):.1f}" y="{h - 8}" text-anchor="middle" class="ax">{"day 0" if k == 0 else f"{k:+d}"}</text>')
    g.append(f'<line x1="{X(0):.1f}" x2="{X(0):.1f}" y1="{T}" y2="{h - B}" class="mk"/><line x1="{L}" x2="{w - R}" y1="{Y(100):.1f}" y2="{Y(100):.1f}" class="refl"/>')
    labels = []
    for e in events:
        pts = " ".join(f"{X(i - 5):.1f},{Y(v):.1f}" for i, v in enumerate(e["path"]))
        hot = highlight and e["name"] == highlight
        g.append(f'<polyline points="{pts}" class="{"ev-hot" if hot else "ev"}"><title>{E(e["name"])} ({e["date"]}): day 0 {e["day0"]:+.1f}%, worst in 10 days {e["min10"]:+.1f}%, +30 days {e["d30"]:+.1f}%</title></polyline>')
        labels.append((Y(e["path"][-1]), e["name"], e["path"][-1], hot))
    mean = [sum(e["path"][i] for e in events) / len(events) for i in range(36)]
    g.append(f'<polyline points="{" ".join(f"{X(i - 5):.1f},{Y(v):.1f}" for i, v in enumerate(mean))}" class="ev-mean"><title>Average of {len(events)} events</title></polyline>')
    labels.append((Y(mean[-1]), "average", mean[-1], "mean"))
    labels.sort()
    last = -99
    for y, nm, v, hot in labels:
        y = max(y, last + 11); last = y
        cls = "ev-l-mean" if hot == "mean" else ("ev-l-hot" if hot else "ev-l")
        g.append(f'<text x="{w - R + 6}" y="{y + 3:.1f}" class="{cls}">{E(nm)} {v - 100:+.1f}%</text>')
    g.append(f'<text x="{L}" y="11" class="lab">{E(title)}</text>')
    return f'<svg viewBox="0 0 {w} {h + max(0, last - h + 30)}" width="100%" class="chart" role="img" aria-label="{E(title)}">{"".join(g)}</svg>'

def hbars(rows, w=720, title="", unit=" pp", note_fmt="t {t:+.1f}"):
    """rows: [(label, value, t)] — diverging bars around zero, sorted as given."""
    vmax = max(abs(r[1]) for r in rows) or 1
    L, R, rowh = 130, 70, 22
    h = 24 + rowh * len(rows)
    mid = L + (w - L - R) / 2
    def X(v): return mid + v / vmax * (w - L - R) / 2
    g = [f'<text x="0" y="12" class="lab">{E(title)}</text>', f'<line x1="{mid:.1f}" x2="{mid:.1f}" y1="18" y2="{h - 4}" class="refl"/>']
    for i, (lab, v, t) in enumerate(rows):
        y = 22 + i * rowh
        x0, x1 = sorted((mid, X(v)))
        strong = t is not None and abs(t) >= 2.5
        cls = ("bp" if v > 0 else "bn") + (" strong" if strong else "")
        g.append(f'<text x="{L - 8}" y="{y + 12}" text-anchor="end" class="ax2">{E(lab)}</text>')
        g.append(f'<rect x="{x0:.1f}" y="{y + 2}" width="{max(1.5, x1 - x0):.1f}" height="{rowh - 7}" rx="3" class="{cls}"><title>{E(lab)}: {v:+.2f}{unit}{"" if t is None else f", t {t:+.2f}"}</title></rect>')
        tx = X(v) + (6 if v >= 0 else -6)
        g.append(f'<text x="{tx:.1f}" y="{y + 12}" text-anchor="{"start" if v >= 0 else "end"}" class="ax2 mono">{v:+.1f}{"" if t is None else "  " + note_fmt.format(t=t)}</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" class="chart" role="img" aria-label="{E(title)}">{"".join(g)}</svg>'

def timeline(items, w=720, title=""):
    """items: [(year_float, label, kind)] kind in domestic|global|geo|policy. Two rows alternating."""
    y0, y1 = min(i[0] for i in items) - 1, max(i[0] for i in items) + 1
    L, R = 20, 20
    def X(y): return L + (y - y0) / (y1 - y0) * (w - L - R)
    h = 300
    g = [f'<text x="{L}" y="12" class="lab">{E(title)}</text>', f'<line x1="{L}" x2="{w - R}" y1="{h / 2}" y2="{h / 2}" class="axis-l"/>']
    for yr in range(int(y0) + 1, int(y1) + 1):
        if yr % 5 == 0:
            g.append(f'<line x1="{X(yr):.1f}" x2="{X(yr):.1f}" y1="{h / 2 - 4}" y2="{h / 2 + 4}" class="axis-l"/><text x="{X(yr):.1f}" y="{h / 2 + 16}" text-anchor="middle" class="ax">{yr}</text>')
    for i, (yr, lab, kind) in enumerate(sorted(items)):
        up = i % 2 == 0
        lane = (i // 2) % 5
        ly = h / 2 - 20 - lane * 22 if up else h / 2 + 30 + lane * 22
        x = X(yr)
        g.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{h / 2}" y2="{ly + (6 if up else -10):.1f}" class="tl-stem"/>'
                 f'<circle cx="{x:.1f}" cy="{h / 2}" r="4.5" class="tl-{kind}"><title>{int(yr)}: {E(lab)}</title></circle>'
                 f'<text x="{x:.1f}" y="{ly:.1f}" text-anchor="middle" class="tl-t">{E(lab)}</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" class="chart" role="img" aria-label="{E(title)}">{"".join(g)}</svg>'

def buckets(rows, w=720, title=""):
    """rows: [(label, mean, hit, n)] — vertical bars of mean forward return."""
    vmax = max(abs(r[1]) for r in rows) or 1
    h, L, B, TOP = 215, 40, 50, 48
    bw = (w - L - 20) / len(rows)
    zero = TOP + (h - TOP - B) / 2
    def Y(v): return zero - v / vmax * (h - TOP - B) / 2
    g = [f'<text x="{L}" y="12" class="lab">{E(title)}</text>', f'<line x1="{L}" x2="{w - 20}" y1="{zero:.1f}" y2="{zero:.1f}" class="refl"/>']
    for i, (lab, m, hit, n) in enumerate(rows):
        x = L + i * bw + bw * 0.25; y = Y(m)
        g.append(f'<rect x="{x:.1f}" y="{min(y, zero):.1f}" width="{bw * 0.5:.1f}" height="{abs(zero - y):.1f}" rx="4" class="{"bp" if m > 0 else "bn"}"><title>{E(lab)}: mean {m:+.2f}%, up {hit:.0f}% of the time, {n} days</title></rect>'
                 f'<text x="{x + bw * 0.25:.1f}" y="{(y - 6) if m > 0 else (y + 14):.1f}" text-anchor="middle" class="ax2 mono">{m:+.2f}%</text>'
                 f'<text x="{x + bw * 0.25:.1f}" y="{h - 30}" text-anchor="middle" class="ax2">{E(lab)}</text>'
                 f'<text x="{x + bw * 0.25:.1f}" y="{h - 14}" text-anchor="middle" class="ax">up {hit:.0f}% · {n} days</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" class="chart" role="img" aria-label="{E(title)}">{"".join(g)}</svg>'

# ── diagrams ──

def diagram_levers():
    """RBI: three levers → channels → markets."""
    L = [("Policy rate", "repo; stance language"), ("Liquidity", "CRR, OMOs, FX sterilisation"), ("Exchange rate", "spot and forward intervention")]
    C = [("Loan and deposit pricing", "EBLR fast · MCLR slow · deposits lag"), ("Overnight and term rates", "call rate within the corridor"),
         ("Bond yields", "G-sec curve, corporate spreads"), ("The rupee", "imported inflation, FPI returns")]
    M = [("Banks and NBFCs", "margins, funding cost"), ("Rate-sensitives", "property, autos, durables"), ("Valuations", "long-duration growth"), ("Exporters vs importers", "IT, pharma vs OMCs, airlines")]
    def col(items, x, cls):
        out = []
        for i, (a, b) in enumerate(items):
            y = 20 + i * 64
            out.append(f'<rect x="{x}" y="{y}" width="190" height="52" rx="10" class="{cls}"/><text x="{x + 12}" y="{y + 21}" class="dg-h">{E(a)}</text><text x="{x + 12}" y="{y + 39}" class="dg-s">{E(b)}</text>')
        return out
    g = col(L, 10, "dg-a") + col(C, 265, "dg-b") + col(M, 520, "dg-c")
    links = [(0, 0), (0, 2), (1, 1), (1, 2), (2, 3), (1, 0)]
    for a, b in links:
        g.insert(0, f'<path d="M200,{46 + a * 64} C232,{46 + a * 64} 233,{46 + b * 64} 265,{46 + b * 64}" class="dg-link"/>')
    for a in range(4):
        g.insert(0, f'<path d="M455,{46 + a * 64} L520,{46 + a * 64}" class="dg-link"/>')
    g.append('<text x="10" y="12" class="dg-col">Three levers</text><text x="265" y="12" class="dg-col">Channels</text><text x="520" y="12" class="dg-col">Where equities feel it</text>')
    return f'<svg viewBox="0 0 720 280" width="100%" class="chart diagram" role="img" aria-label="RBI levers, channels and equity impact">{"".join(g)}</svg>'

def diagram_world():
    """Six economies → five channels → India."""
    ECON = ["United States", "China", "Europe", "Japan", "The Gulf", "Russia"]
    CH = ["Rates and the dollar", "Commodity prices", "Trade and tariffs", "Capital flows", "Energy supply"]
    IN = ["Rupee and reserves", "Inflation", "Corporate margins", "Equity flows"]
    LINKS = {0: [0, 2, 3], 1: [1, 2], 2: [2, 4], 3: [0, 3], 4: [4, 1], 5: [4, 1]}
    CL = {0: [0, 3], 1: [1, 2], 2: [2], 3: [3, 0], 4: [0, 1, 2]}
    g = []
    def ey(i): return 24 + i * 44
    def cy(i): return 34 + i * 52
    def iy(i): return 50 + i * 60
    for e, chs in LINKS.items():
        for c in chs: g.append(f'<path d="M170,{ey(e) + 16} C220,{ey(e) + 16} 220,{cy(c) + 16} 270,{cy(c) + 16}" class="dg-link"/>')
    for c, ins in CL.items():
        for i in ins: g.append(f'<path d="M450,{cy(c) + 16} C500,{cy(c) + 16} 500,{iy(i) + 16} 550,{iy(i) + 16}" class="dg-link"/>')
    for i, n in enumerate(ECON): g.append(f'<rect x="10" y="{ey(i)}" width="160" height="32" rx="8" class="dg-a"/><text x="22" y="{ey(i) + 20}" class="dg-h">{E(n)}</text>')
    for i, n in enumerate(CH): g.append(f'<rect x="270" y="{cy(i)}" width="180" height="32" rx="8" class="dg-b"/><text x="282" y="{cy(i) + 20}" class="dg-h">{E(n)}</text>')
    for i, n in enumerate(IN): g.append(f'<rect x="550" y="{iy(i)}" width="160" height="32" rx="8" class="dg-c"/><text x="562" y="{iy(i) + 20}" class="dg-h">{E(n)}</text>')
    g.append('<text x="10" y="14" class="dg-col">Where it starts</text><text x="270" y="14" class="dg-col">The channel</text><text x="550" y="14" class="dg-col">Where India feels it</text>')
    return f'<svg viewBox="0 0 720 300" width="100%" class="chart diagram" role="img" aria-label="How six economies reach India through five channels">{"".join(g)}</svg>'

def diagram_chokepoints():
    """Schematic of India's crude routes and chokepoints (not to scale)."""
    g = ['<text x="10" y="14" class="dg-col">India\'s crude routes, schematic (not to scale)</text>']
    nodes = {"Gulf producers": (90, 90), "Strait of Hormuz": (240, 110), "Arabian Sea": (400, 160), "India's west-coast refineries": (590, 170),
             "Russia (Baltic, Black Sea)": (90, 230), "Suez and the Red Sea": (240, 250), "Bab-el-Mandeb": (360, 230), "Cape of Good Hope (long way)": (240, 320),
             "US and West Africa": (90, 330), "Strait of Malacca": (590, 300)}
    hot = {"Strait of Hormuz", "Bab-el-Mandeb"}
    routes = [("Gulf producers", "Strait of Hormuz"), ("Strait of Hormuz", "Arabian Sea"), ("Arabian Sea", "India's west-coast refineries"),
              ("Russia (Baltic, Black Sea)", "Suez and the Red Sea"), ("Suez and the Red Sea", "Bab-el-Mandeb"), ("Bab-el-Mandeb", "Arabian Sea"),
              ("Russia (Baltic, Black Sea)", "Cape of Good Hope (long way)"), ("US and West Africa", "Cape of Good Hope (long way)"), ("Cape of Good Hope (long way)", "Arabian Sea"),
              ("India's west-coast refineries", "Strait of Malacca")]
    for a, b in routes:
        (x1, y1), (x2, y2) = nodes[a], nodes[b]
        cls = "route-hot" if (a in hot or b in hot) else "route"
        g.append(f'<path d="M{x1},{y1} Q{(x1 + x2) / 2},{(y1 + y2) / 2 - 18} {x2},{y2}" class="{cls}"/>')
    for n, (x, y) in nodes.items():
        cls = "cp-hot" if n in hot else ("cp-in" if "India" in n else "cp")
        g.append(f'<circle cx="{x}" cy="{y}" r="{9 if n in hot else 6}" class="{cls}"><title>{E(n)}</title></circle><text x="{x}" y="{(y + 24) if n in ("Bab-el-Mandeb", "Suez and the Red Sea", "Cape of Good Hope (long way)") else (y - 13)}" text-anchor="middle" class="dg-s2">{E(n)}</text>')
    g.append('<text x="590" y="330" text-anchor="middle" class="dg-s">exports to East Asia</text>')
    return f'<svg viewBox="0 0 720 350" width="100%" class="chart diagram" role="img" aria-label="India crude routes and chokepoints">{"".join(g)}</svg>'

def diagram_budget():
    LINES = [("Capex allocation", ["Construction and engineering", "Capital goods", "Cement and steel", "Defence"]),
             ("Borrowing programme", ["Bond yields", "Bank treasury gains or losses", "Cost of capital for everyone"]),
             ("Tax changes", ["Consumer demand (income tax)", "Single industries (GST rates)", "Capital-gains rules and flows"]),
             ("Subsidies", ["Fertiliser makers", "Oil marketing companies", "Rural consumption"])]
    g = ['<text x="10" y="14" class="dg-col">The Budget line</text><text x="300" y="14" class="dg-col">What it moves</text>']
    y = 24
    for head, items in LINES:
        top = y
        for it in items:
            g.append(f'<rect x="300" y="{y}" width="400" height="24" rx="6" class="dg-c"/><text x="312" y="{y + 16}" class="dg-s">{E(it)}</text>')
            g.append(f'<path d="M210,{top + len(items) * 14} C255,{top + len(items) * 14} 255,{y + 12} 300,{y + 12}" class="dg-link"/>')
            y += 28
        g.append(f'<rect x="10" y="{top + len(items) * 14 - 16}" width="200" height="32" rx="8" class="dg-a"/><text x="22" y="{top + len(items) * 14 + 4}" class="dg-h">{E(head)}</text>')
        y += 10
    return f'<svg viewBox="0 0 720 {y + 6}" width="100%" class="chart diagram" role="img" aria-label="Budget lines and what they move">{"".join(g)}</svg>'

CHART_CSS = """
  svg.chart { display: block; margin: 6px 0 4px; overflow: visible; }
  svg.chart text { font-family: Inter, sans-serif; }
  svg.chart .ax { fill: var(--text-muted); font-size: 10px; } svg.chart .ax2 { fill: var(--text-secondary); font-size: 11.5px; }
  svg.chart .mono { font-family: var(--mono); }
  svg.chart .gl { stroke: var(--border); stroke-width: 1; } svg.chart .refl { stroke: var(--text-muted); stroke-dasharray: 3 3; }
  svg.chart .lab { fill: var(--text-primary); font-size: 12px; font-weight: 600; } svg.chart .lab-v { fill: var(--text-muted); font-size: 11px; font-family: var(--mono); }
  svg.chart .ep { fill: rgba(239,68,68,0.10); } svg.chart .ep-t { fill: var(--red); font-size: 9.5px; font-weight: 600; }
  svg.chart .mk { stroke: var(--amber); stroke-dasharray: 2 3; } svg.chart .mk-t { fill: var(--amber); font-size: 9.5px; }
  svg.chart .ev { fill: none; stroke: var(--text-muted); stroke-width: 1.2; opacity: .55; } svg.chart .ev-hot { fill: none; stroke: #d97706; stroke-width: 2.2; }
  svg.chart .ev-mean { fill: none; stroke: var(--accent); stroke-width: 3; }
  svg.chart .ev-l { fill: var(--text-muted); font-size: 10px; } svg.chart .ev-l-hot { fill: #d97706; font-size: 10.5px; font-weight: 600; } svg.chart .ev-l-mean { fill: var(--accent); font-size: 11px; font-weight: 700; }
  svg.chart .bp { fill: var(--green); opacity: .55; } svg.chart .bn { fill: var(--red); opacity: .55; } svg.chart .bp.strong, svg.chart .bn.strong { opacity: .95; }
  svg.chart .axis-l { stroke: var(--border-accent); stroke-width: 1.5; } svg.chart .tl-stem { stroke: var(--border-accent); }
  svg.chart .tl-t { fill: var(--text-secondary); font-size: 10px; }
  svg.chart .tl-domestic { fill: var(--accent); } svg.chart .tl-global { fill: #d97706; } svg.chart .tl-geo { fill: var(--red); } svg.chart .tl-policy { fill: var(--green); }
  svg.diagram .dg-a { fill: var(--accent-soft); stroke: var(--accent); } svg.diagram .dg-b { fill: var(--bg-card); stroke: var(--border-accent); } svg.diagram .dg-c { fill: rgba(217,119,6,0.10); stroke: rgba(217,119,6,0.6); }
  svg.diagram .dg-h { fill: var(--text-primary); font-size: 12.5px; font-weight: 600; } svg.diagram .dg-s { fill: var(--text-secondary); font-size: 11px; } svg.diagram .dg-s2 { fill: var(--text-secondary); font-size: 10.5px; }
  svg.diagram .dg-col { fill: var(--text-muted); font-size: 10.5px; text-transform: uppercase; letter-spacing: .08em; }
  svg.diagram .dg-link { fill: none; stroke: var(--border-accent); stroke-width: 1.5; }
  svg.diagram .route { fill: none; stroke: var(--text-muted); stroke-width: 2; stroke-dasharray: 5 4; } svg.diagram .route-hot { fill: none; stroke: var(--red); stroke-width: 2.6; }
  svg.diagram .cp { fill: var(--text-muted); } svg.diagram .cp-hot { fill: var(--red); stroke: var(--red-bg); stroke-width: 6; } svg.diagram .cp-in { fill: var(--accent); }
  .stack svg.chart { margin: 0; } .stack { border: 1px solid var(--border); border-radius: 12px; padding: 8px 10px; background: var(--bg-card); margin: 10px 0 4px; }
  .fig { border: 1px solid var(--border); border-radius: 12px; padding: 10px 12px; background: var(--bg-card); margin: 14px 0 6px; }
  .fig-cap { font-size: 12.5px; color: var(--text-muted); margin: 2px 0 12px; line-height: 1.5; }
  .legend3 { display: flex; flex-wrap: wrap; gap: 12px; font-size: 11.5px; color: var(--text-secondary); margin: 2px 0 6px; } .legend3 i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; vertical-align: -1px; }
  .hist-t { width: 100%; font-size: 13.5px; } .hist-t td { vertical-align: top; } .hist-t td:first-child { white-space: nowrap; font-family: var(--mono); color: var(--accent); }
"""


def heat_matrix(rows, cols, cells, title=""):
    """rows: [(name, trend)], cols: [name], cells: {(r, c): level} level in high|med|low|none."""
    L, top, cw, rh = 190, 64, 88, 34
    w = L + cw * len(cols) + 10; h = top + rh * len(rows) + 30
    g = [f'<text x="0" y="12" class="lab">{E(title)}</text>']
    for j, c in enumerate(cols):
        x = L + j * cw + cw / 2
        words = c.split(" ")
        for k, wd in enumerate([" ".join(words[:2]), " ".join(words[2:])]):
            if wd: g.append(f'<text x="{x:.1f}" y="{38 + k * 12}" text-anchor="middle" class="ax2">{E(wd)}</text>')
    arrow = {"escalating": ("▲ escalating", "hm-esc"), "elevated": ("■ elevated", "hm-elv"), "easing": ("▼ easing", "hm-eas"), "calm": ("● calm", "hm-calm")}
    for i, (r, trend) in enumerate(rows):
        y = top + i * rh
        a, cls = arrow[trend]
        g.append(f'<text x="0" y="{y + 15}" class="dg-h">{E(r)}</text><text x="0" y="{y + 28}" class="{cls}">{a}</text>')
        for j, c in enumerate(cols):
            lvl = cells.get((i, j), "none")
            g.append(f'<rect x="{L + j * cw + 4}" y="{y + 3}" width="{cw - 8}" height="{rh - 6}" rx="6" class="hm-{lvl}"><title>{E(r)} → {E(c)}: {lvl}</title></rect>'
                     f'<text x="{L + j * cw + cw / 2:.1f}" y="{y + rh / 2 + 4}" text-anchor="middle" class="hm-t">{"" if lvl == "none" else lvl}</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" class="chart diagram" role="img" aria-label="{E(title)}">{"".join(g)}</svg>'

def ladder(rungs, here, title=""):
    """rungs: [(label, note)] bottom to top; here: index of the current rung."""
    rh, w = 40, 720
    h = 24 + rh * len(rungs) + 10
    g = [f'<text x="0" y="12" class="lab">{E(title)}</text>']
    for i, (lab, note) in enumerate(rungs):
        y = 24 + (len(rungs) - 1 - i) * rh
        cls = "ld-here" if i == here else ("ld-past" if i < here else "ld-next")
        g.append(f'<rect x="40" y="{y}" width="{w - 50}" height="{rh - 8}" rx="8" class="{cls}"/>'
                 f'<text x="56" y="{y + 15}" class="dg-h">{E(lab)}</text><text x="56" y="{y + 28}" class="dg-s">{E(note)}</text>'
                 f'<text x="18" y="{y + 21}" text-anchor="middle" class="ld-n">{i + 1}</text>')
        if i == here:
            g.append(f'<text x="{w - 18}" y="{y + 21}" text-anchor="end" class="ld-tag">we are here</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" class="chart diagram" role="img" aria-label="{E(title)}">{"".join(g)}</svg>'

def diagram_ai_chain():
    LAYERS = [("Models and hyperscalers", "US labs and cloud giants fund the build-out", "IT services: integration work, but AI coding tools cut billable hours; GCCs grow"),
              ("Chip design", "US designers; export controls decide who can buy", "Design centres in Bengaluru and Hyderabad"),
              ("Foundry and memory", "Taiwan for leading-edge logic, Korea for memory", "Semiconductor mission: assembly and test plants now running; first fab under construction"),
              ("Servers and equipment", "Server assembly, networking, cooling", "AI-server makers and electronics manufacturing services"),
              ("Data centres and power", "Land, grid connections, transformers, cooling", "Data-centre build-out, power transmission and electrical equipment")]
    g = ['<text x="10" y="14" class="dg-col">The AI value chain</text><text x="380" y="14" class="dg-col">Where India sits</text>']
    for i, (a, b, c) in enumerate(LAYERS):
        y = 24 + i * 58
        g.append(f'<rect x="10" y="{y}" width="340" height="48" rx="10" class="dg-b"/><text x="24" y="{y + 20}" class="dg-h">{E(a)}</text><text x="24" y="{y + 37}" class="dg-s">{E(b)}</text>')
        g.append(f'<path d="M350,{y + 24} L380,{y + 24}" class="dg-link"/>')
        g.append(f'<rect x="380" y="{y}" width="330" height="48" rx="10" class="{"dg-c" if i else "dg-a"}"/><foreignObject x="388" y="{y + 4}" width="316" height="42"><div xmlns="http://www.w3.org/1999/xhtml" class="fo">{E(c)}</div></foreignObject>')
        if i < len(LAYERS) - 1:
            g.append(f'<path d="M180,{y + 48} L180,{y + 58}" class="dg-link"/>')
    return f'<svg viewBox="0 0 720 {24 + 58 * len(LAYERS)}" width="100%" class="chart diagram" role="img" aria-label="AI value chain and India">{"".join(g)}</svg>'

CHART_CSS += """
  svg.diagram .hm-high { fill: rgba(239,68,68,0.55); } svg.diagram .hm-med { fill: rgba(245,158,11,0.40); } svg.diagram .hm-low { fill: rgba(245,158,11,0.14); } svg.diagram .hm-none { fill: var(--bg-primary); stroke: var(--border); }
  svg.diagram .hm-t { fill: var(--text-primary); font-size: 10.5px; font-weight: 600; }
  svg.diagram .hm-esc { fill: var(--red); font-size: 10.5px; font-weight: 600; } svg.diagram .hm-elv { fill: var(--amber); font-size: 10.5px; font-weight: 600; }
  svg.diagram .hm-eas { fill: var(--green); font-size: 10.5px; font-weight: 600; } svg.diagram .hm-calm { fill: var(--text-muted); font-size: 10.5px; }
  svg.diagram .ld-past { fill: var(--bg-primary); stroke: var(--border-accent); } svg.diagram .ld-here { fill: rgba(239,68,68,0.15); stroke: var(--red); stroke-width: 2; }
  svg.diagram .ld-next { fill: var(--bg-primary); stroke: var(--border); stroke-dasharray: 4 4; }
  svg.diagram .ld-n { fill: var(--text-muted); font-family: var(--mono); font-size: 12px; } svg.diagram .ld-tag { fill: var(--red); font-size: 11px; font-weight: 700; }
  svg.diagram .fo { font: 11.5px/1.35 Inter, sans-serif; color: var(--text-secondary); }
"""
