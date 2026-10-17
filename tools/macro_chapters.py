"""The macro page's framework chapters as prose + figures (plan 0028).

A chapter is stored in desk_snapshots (part "chapter") as rendered HTML plus the parts it was built from: the written
prose (hook, sections, history stories, where it stands now, so what, the short version) and the figures (charts,
diagrams, matrices) it places with [[fig:N]] tokens. Current readings in the prose are [[val:name]] tokens filled from
the newest daily brief, so a monthly refresh can re-render the figures and readings without touching the words, and a
rewrite of the words keeps every figure.

    python -m tools.macro_chapters extract DIR            # one JSON per chapter: figures, reference blocks, old prose
    python -m tools.macro_chapters values                 # the [[val:...]] tokens and today's readings
    python -m tools.macro_chapters assemble DIR [--save]  # DIR/<id>.prose.json -> validate, render, preview, save

Prose rules (validated): no digits except years and calendar tokens; tags limited to p b strong em i ul ol li
blockquote br; every figure used exactly once; only known tokens.
"""
import argparse
import datetime as dt
import html as H
import json
import re
import sys
from pathlib import Path

from output import desk_archive as A
from output import macro_links as LK

TRACKS = {"Prologue": "Prologue", "India": "The India framework", "Global": "The global and geopolitical framework",
          "Synthesis": "Putting it together"}
KEEP_BODY = ("fig", "extbox", "hots", "flow4")          # blocks inside the old body that are figures, not prose
ALLOWED_TAGS = {"p", "b", "strong", "em", "i", "ul", "ol", "li", "blockquote", "br"}
_TOK = re.compile(r"\[\[(fig|val):([\w-]+)\]\]")
_TAG = re.compile(r"</?([a-zA-Z0-9]+)\b[^>]*>")
TEXT_VALUES = {"rbi", "regime"}                         # words, not figures: no number styling
MIN_WORDS = {"sy-3": 600}                               # the daily-routine chapter is a checklist
DEFAULT_MIN_WORDS = 1400


# ─────────────────────────── extract ───────────────────────────

def _children(html):
    """Top-level elements of an HTML fragment: [(tag, class, html)]."""
    out, depth, start, cur = [], 0, None, None
    for m in re.finditer(r"<(/?)(div|p|table|svg|section|h[1-6]|ul|ol|details|blockquote|figure)\b([^>]*)>", html, re.S):
        if not m.group(1):
            if depth == 0:
                start, cur = m.start(), (m.group(2), (re.search(r'class="([^"]*)"', m.group(3)) or [None, ""])[1])
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                out.append((*cur, html[start:m.end()]))
    return out


def _text(fragment):
    t = re.sub(r"<svg.*?</svg>", " ", fragment, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", H.unescape(t)).strip()


def split_chapter(cid, row):
    html = row["payload"]["html"]
    inner = re.search(r"<article[^>]*>(.*)</article>", html, re.S).group(1)
    top = {c.split()[0] if c else t: x for t, c, x in _children(inner)}
    body = re.search(r'<div class="ch-body">(.*)</div>$', top["ch-body"], re.S).group(1)
    figures, old_body = [], []
    for t, c, x in _children(body):
        if (c or "").split()[:1] and c.split()[0] in KEEP_BODY:
            cap = re.search(r'<div class="fig-cap">(.*?)</div>', x, re.S)
            figures.append({"n": len(figures) + 1, "kind": c.split()[0], "caption": _text(cap.group(1)) if cap else "",
                            "label": (re.search(r'aria-label="([^"]*)"', x) or [None, ""])[1], "html": x})
        else:
            old_body.append(_text(x))
    kicker = _text(top.get("ch-kicker", ""))
    mins = re.search(r"(\w+) minute read", kicker)
    return {"id": cid, "track": row["payload"]["track"], "title": row["payload"]["title"], "minutes_word": mins.group(1) if mins else "",
            "figures": figures,
            "keep": {k: top[k] for k in ("ch-inds", "srcbox", "ch-deeper", "ch-nav") if k in top},
            "old": {"hook": _text(top.get("ch-hook", "")), "body": old_body, "history": _text(top.get("histblock", "")),
                    "where_it_stands": _text(top.get("seeit", "")), "so_what": _text(top.get("ch-sowhat", ""))},
            "sources": re.findall(r'<a href="(https?://[^"]+)"[^>]*>([^<]+)</a>', html)}


def extract(out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    rows = A.latest_all("chapter")
    for cid, row in rows.items():
        (out / f"{cid}.json").write_text(json.dumps(split_chapter(cid, row), ensure_ascii=False, indent=1))
    print(f"extracted {len(rows)} chapters to {out}")


# ─────────────────────────── values ───────────────────────────

def _f(v, d=2):
    return f"{v:,.{d}f}"


def values(as_of=None):
    """[[val:name]] -> (display text, what it is), from the newest brief on or before as_of."""
    b = A.latest("brief", as_of=as_of)
    if not b:
        raise RuntimeError("no brief archived: run `run.sh macro_desk` first")
    p = b["payload"]
    radar = {r["name"]: r["reading"] for r in p.get("radar", [])}
    cpi = re.search(r"CPI ([\d.]+)% in (\d{4}-\d\d), ([+-][\d.]+) pp", radar.get("Inflation turning", ""))
    ush = re.search(r"is ([\d.]+)% on (\d{4}-\d\d-\d\d)", radar.get("US yields", ""))
    rup = re.search(r"record is ([\d.]+) on (\d{4}-\d\d-\d\d)", radar.get("Rupee slide", ""))
    v = {
        "date": (p["data_date"], "the date the readings describe"),
        "brent": (f"${_f(p['brent'])}", "Brent crude, a barrel"),
        "brent_3m": (f"{p['brent_3m']:+.1f}%", "Brent change over 63 sessions"),
        "us10y": (f"{p['us10y']:.2f}%", "US ten-year Treasury yield"),
        "us10y_3m": (f"{p['us_3m_bps']:+.0f} bps", "US ten-year change over 63 sessions"),
        "us10y_high": (f"{ush.group(1)}% on {ush.group(2)}" if ush else "n/a", "highest US ten-year in our data, and when"),
        "usdinr": (_f(p["usdinr"]), "rupees per US dollar"),
        "usdinr_3m": (f"{p.get('usdinr_3m', 0):+.2f}%", "rupee change over 63 sessions (+ = weaker rupee)"),
        "usdinr_record": (f"{rup.group(1)} on {rup.group(2)}" if rup else "n/a", "weakest rupee in our data, and when"),
        "fii20": (f"{'−' if p['fii20'] < 0 else '+'}₹{abs(p['fii20']):,} cr", "FII net cash buying, 20 sessions"),
        "dii20": (f"{'−' if p['dii20'] < 0 else '+'}₹{abs(p['dii20']):,} cr", "DII net cash buying, 20 sessions"),
        "fii_long": (f"{p['fii_long']:.1f}%", "share of FII index-futures positions that are long"),
        "fii_long_pct": (f"percentile {p['fii_long_pct']}", "where that share sits since 2022"),
        "vix": (_f(p["vix"], 1), "India VIX"),
        "nifty": (_f(p["nifty"], 1), "Nifty 50"),
        "cpi": (f"{cpi.group(1)}% in {cpi.group(2)}" if cpi else "n/a", "CPI inflation, latest published month"),
        "cpi_3m": (f"{cpi.group(3)} pp" if cpi else "n/a", "change in CPI inflation over three months"),
        "regime": (p.get("regime") or "n/a", "the regime on published IIP and CPI"),
        "regime_month": (p.get("regime_month") or "n/a", "the month the regime's data runs to"),
        "rbi": (p["rbi_text"], "the RBI's stance, as set"),
    }
    return v, b["snapshot_date"]


# ─────────────────────────── assemble ───────────────────────────

def _check_prose(field, html, problems, figs_used, val_names, n_figs):
    from tools.sector_explainer import prose_digits
    for t in set(m.group(1).lower() for m in _TAG.finditer(html or "")):
        if t not in ALLOWED_TAGS:
            problems.append(f"{field}: tag <{t}> not allowed")
    for kind, name in _TOK.findall(html or ""):
        if kind == "fig":
            if not name.isdigit() or not 1 <= int(name) <= n_figs:
                problems.append(f"{field}: no figure {name}")
            figs_used.append(int(name) if name.isdigit() else name)
        elif name not in val_names:
            problems.append(f"{field}: unknown value [[val:{name}]]")
    plain = _text(_TOK.sub(" ", html or ""))
    bad = prose_digits(plain)
    if bad:
        problems.append(f"{field}: figures in prose {bad[:4]}")
    return len(plain.split())


def validate(prose, src, val_names):
    problems, used = [], []
    n = len(src["figures"])
    words = 0
    for f in ("hook", "today", "sowhat"):
        if not (prose.get(f) or "").strip() and not (f == "today" and src["id"].startswith("sy")):
            problems.append(f"{f}: missing")
        words += _check_prose(f, prose.get(f, ""), problems, used, val_names, n)
    for i, t in enumerate(prose.get("short", [])):
        _check_prose(f"short[{i}]", t, problems, used, val_names, n)
    for i, s in enumerate(prose.get("sections", [])):
        _check_prose(f"sections[{i}].heading", s.get("heading", ""), problems, used, val_names, n)
        words += _check_prose(f"sections[{i}].html", s.get("html", ""), problems, used, val_names, n)
    for i, h in enumerate(prose.get("history", [])):
        for k in ("title", "story", "lesson"):
            words += _check_prose(f"history[{i}].{k}", h.get(k, ""), problems, used, val_names, n)
        if not re.fullmatch(r"[\w\s–\-—,]+", h.get("when", "")):
            problems.append(f"history[{i}].when: a year or period, like 2013 or 2025–26")
    missing = [k for k in range(1, n + 1) if used.count(k) != 1]
    if missing:
        problems.append(f"figures {missing} must each appear exactly once")
    need = MIN_WORDS.get(src["id"], DEFAULT_MIN_WORDS)
    if words < need:
        problems.append(f"{words} words; at least {need}")
    if len(prose.get("history", [])) < (0 if src["id"] == "sy-3" else 4):
        problems.append("history: at least four stories")
    return problems, words


def _fill(html, src, vals):
    """Tokens -> figures and readings. A figure never sits inside a paragraph: a token mid-paragraph closes the
    paragraph around it."""
    html = re.sub(r"<p>\s*(\[\[fig:\d+\]\])\s*</p>", r"\1", html)
    out, pos = [], 0
    for m in _TOK.finditer(html):
        before = html[pos:m.start()]
        out.append(before)
        kind, name = m.group(1), m.group(2)
        if kind == "val":
            cls = "feedt" if name in TEXT_VALUES else "mono feedv"
            out.append(f'<span class="{cls}" title="{H.escape(vals[name][1])}">{H.escape(vals[name][0])}</span>')
        else:
            sofar = html[:m.start()]
            inside_p = sofar.count("<p>") + len(re.findall(r"<p\s[^>]*>", sofar)) > sofar.count("</p>")
            fig = src["figures"][int(name) - 1]["html"]
            out.append(f"</p>{fig}<p>" if inside_p else fig)
        pos = m.end()
    out.append(html[pos:])
    return re.sub(r"<p>\s*</p>", "", "".join(out))


def nav(cid, order, titles):
    k = order.index(cid)
    prev = (f'<a class="nav-prev" href="#{order[k - 1]}">← {H.escape(titles[order[k - 1]])}</a>' if k > 0
            else '<a class="nav-prev" href="#start">← Start here</a>')
    nxt = (f'<a class="nav-next" href="#{order[k + 1]}">Next: {H.escape(titles[order[k + 1]])} →</a>' if k + 1 < len(order)
           else '<a class="nav-next primary" href="#today">Open today\'s brief →</a>')
    return f'<div class="ch-nav">{prev}{nxt}</div>'


def render(prose, src, vals, version_date, index, total, nav_html=None):
    used = set()
    link = lambda x: LK.linkify(x, used, src["id"])                    # noqa: E731
    cid, track = src["id"], src["track"]
    kicker = (f'{TRACKS[track]} · chapter {index} of {total} · ' if track != "Prologue" else "Prologue · ") + \
             f'{prose.get("minutes", 12)} minute read · version of {version_date} · refreshed monthly'
    short = "".join(f"<li>{link(_fill(t, src, vals))}</li>" for t in prose.get("short", []))
    secs = "".join(f'<section class="ch-sec"><h2 class="ch-h2">{H.escape(s["heading"])}</h2>{link(_fill(s["html"], src, vals))}</section>'
                   for s in prose["sections"])
    hist = ""
    if prose.get("history"):
        cards = "".join(f'<div class="story-card"><div class="sc-when">{H.escape(h["when"])}</div><div class="sc-body">'
                        f'<h3 class="sc-t">{H.escape(h["title"])}</h3>{link(_fill(h["story"], src, vals))}'
                        f'<div class="sc-lesson"><b>The lesson.</b> {link(_fill(h["lesson"], src, vals))}</div></div></div>'
                        for h in prose["history"])
        hist = f'<div class="histblock stories"><div class="hb-h">History · {H.escape(prose.get("history_title", "how we got here"))}</div>{cards}</div>'
    today = (f'<div class="seeit"><div class="seeit-h">Where it stands now · readings to {vals["date"][0]}</div>'
             f'{link(_fill(prose["today"], src, vals))}</div>') if prose.get("today") else ""
    keep = src["keep"]
    title = prose.get("title") or src["title"]
    track_cls = {"India": "tr-in", "Global": "tr-gl", "Synthesis": "tr-sy", "Prologue": "tr-pro"}[track]
    return f'''<article class="chapter {track_cls}" data-view="{cid}">
  <div class="ch-kicker"><span class="trk">{H.escape(track)}</span> {H.escape(kicker)}</div>
  <h1 class="ch-title">{H.escape(title)}</h1>
  <div class="ch-hook">{link(_fill(prose["hook"], src, vals))}</div>
  {f'<div class="ch-tldr"><div class="ch-words-h">The short version</div><ul>{short}</ul></div>' if short else ""}
  <div class="ch-body">{secs}</div>
  {hist}
  {today}
  <div class="ch-sowhat"><div class="sw-h">So what for positioning</div>{link(_fill(prose["sowhat"], src, vals))}</div>
  {keep.get("ch-inds", "")}
  {keep.get("srcbox", "")}
  {keep.get("ch-deeper", "")}
  {nav_html or keep.get("ch-nav", "")}
</article>'''


def assemble(in_dir, save=False, version_date=None):
    d = Path(in_dir)
    vals, vdate = values()
    version_date = version_date or dt.date.today().isoformat()
    order = ["pro"] + [f"in-{i}" for i in range(1, 9)] + [f"gl-{i}" for i in range(1, 10)] + [f"sy-{i}" for i in range(1, 4)]
    per_track = {}
    for cid in order:
        src = json.loads((d / f"{cid}.json").read_text())
        per_track.setdefault(src["track"], []).append(cid)
    titles = {}
    for cid in order:
        pf = d / f"{cid}.prose.json"
        src = json.loads((d / f"{cid}.json").read_text())
        titles[cid] = (json.loads(pf.read_text()).get("title") if pf.exists() else None) or src["title"]
    built, bad = {}, {}
    for cid in order:
        pf = d / f"{cid}.prose.json"
        if not pf.exists():
            continue
        src = json.loads((d / f"{cid}.json").read_text())
        prose = json.loads(pf.read_text())
        problems, words = validate(prose, src, set(vals))
        if problems:
            bad[cid] = problems
            continue
        same = per_track[src["track"]]
        built[cid] = (src, prose, render(prose, src, vals, version_date, same.index(cid) + 1, len(same),
                                         nav(cid, order, titles)), words)
    for cid, p in bad.items():
        print(f"✗ {cid}: " + "; ".join(p[:8]))
    for cid, (_, _, _, w) in built.items():
        print(f"✓ {cid}: {w} words")
    if save and built:
        for cid, (src, prose, html, _) in built.items():
            v = A.save("chapter", {"title": prose.get("title") or src["title"], "track": src["track"], "html": html,
                                   "prose": prose, "figures": [f["html"] for f in src["figures"]],
                                   "keep": src["keep"], "values_as_of": vdate}, version_date, item=cid, method="manual")
            print(f"saved {cid} v{v}")
    return built, bad


def main(argv=None):
    ap = argparse.ArgumentParser(description="macro chapters: prose + figures (plan 0028)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract"); e.add_argument("dir")
    sub.add_parser("values")
    a_ = sub.add_parser("assemble"); a_.add_argument("dir"); a_.add_argument("--save", action="store_true"); a_.add_argument("--date")
    a = ap.parse_args(argv)
    if a.cmd == "extract":
        extract(a.dir)
    elif a.cmd == "values":
        v, d = values()
        print(f"readings from the brief of {d}:")
        for k, (txt, what) in v.items():
            print(f"  [[val:{k}]]  {txt:28} {what}")
    else:
        _, bad = assemble(a.dir, a.save, a.date)
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
