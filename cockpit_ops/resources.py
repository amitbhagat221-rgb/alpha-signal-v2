"""The ops cockpit's Resources page (/resources): reference guides worth keeping one click away, each a standalone
HTML document in the repo, shown in a tab and served whitelisted at /resources/doc/<file name>.

Adding a guide = one RESOURCES entry (the file must live under docs/). Order = tab order."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RESOURCES = [
    {"key": "options-primer", "title": "Options primer", "file": "docs/research/0006-options-explainer.html",
     "subtitle": "Options setup identification",
     "blurb": "How an option is priced and what moves it, then the setups worth trading and how to tell them apart. Start here."},
    {"key": "options-bets", "title": "Options as bets", "file": "docs/research/0006-options-bets-guide.html",
     "subtitle": "Every structure as a bet on direction, speed and volatility",
     "blurb": "Calls, puts, spreads, strangles and condors read as bets: what each wins on, what it loses on, and what it costs."},
    {"key": "options-landscape", "title": "Who wins in options", "file": "docs/research/0006-options-landscape.html",
     "subtitle": "Who makes money in index options, and why",
     "blurb": "Market makers, premium sellers, tail-hedgers and retail traders: where the edge sits and where the money goes."},
]
BY_FILE = {Path(r["file"]).name: r for r in RESOURCES}

# external links open in a new tab, so a click never replaces the guide inside the frame
_LINKS = ('<script>document.querySelectorAll(\'a[href^="http"]\').forEach(a => { a.target = "_blank"; '
          'a.rel = "noopener"; });</script>')


def tabs():
    return [(r["key"], r["title"]) for r in RESOURCES]


def document(name):
    """The guide's HTML for a whitelisted file name, or None."""
    r = BY_FILE.get(name)
    if not r:
        return None
    path = (ROOT / r["file"]).resolve()
    if not path.is_file() or ROOT / "docs" not in path.parents:
        return None
    html = path.read_text(encoding="utf-8")
    # the cockpit is dark-only; the guides go dark only on a dark device, so apply their own dark palette always
    dark = re.search(r'@media \(prefers-color-scheme: ?dark\)\s*\{\s*:root:not\(\[data-theme="light"\]\)\s*\{([^}]*)\}', html)
    if dark and "</head>" in html:
        html = html.replace("</head>", f"<style>:root{{{dark.group(1)}}}</style></head>", 1)
    return html.replace("</body>", _LINKS + "</body>", 1) if "</body>" in html else html + _LINKS
