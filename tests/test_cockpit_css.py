"""Every CSS class a cockpit template uses is defined somewhere (cockpit.css or a template <style>).

2026-10-10: a clean-up pruned 240 lines of `_sector_styles.html` it thought unused, and the
industry dossier (Sectors and the stock page's Industry tab) rendered as unstyled text. This
test fails the next time a stylesheet loses rules a template still uses."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE_DIRS = [ROOT / "cockpit" / "templates", ROOT / "cockpit_ops" / "templates"]
STYLESHEETS = [ROOT / "cockpit" / "static" / "cockpit.css"]

# Used in class="" but deliberately without a rule: JS/Alpine hooks, prefixes completed by
# Jinja (`pill-{{ tone }}`), state keys parsed out of :class objects, semantic markers.
UNSTYLED_OK = {
    "byScore", "cur", "dark", "ds-", "f", "filter", "h-", "heatmapOpen", "i", "it-note", "loading",
    "ns-heat-", "null", "o", "og-", "og-av-", "og-memo-body", "og-ref", "pill-", "score-", "st-",
    "statusFilter", "tab", "tf", "verdict",
}


def _templates():
    for d in TEMPLATE_DIRS:
        yield from sorted(d.rglob("*.html"))


def _defined_classes():
    css = "\n".join(p.read_text() for p in STYLESHEETS)
    for f in _templates():
        css += "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", f.read_text(), re.S))
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", css))


def _used_classes():
    used = {}
    for f in _templates():
        for m in re.finditer(r'\bclass="([^"]*)"', f.read_text()):
            value = re.sub(r"\{\{.*?\}\}|\{%.*?%\}", " ", m.group(1))
            for c in value.split():
                if re.fullmatch(r"[a-zA-Z][\w-]*", c):
                    used.setdefault(c, set()).add(f.relative_to(ROOT).as_posix())
    return used


def test_every_template_class_has_a_css_rule():
    defined = _defined_classes()
    missing = {c: sorted(files) for c, files in _used_classes().items()
               if c not in defined and c not in UNSTYLED_OK}
    assert not missing, f"classes used in templates but defined in no stylesheet: {missing}"


def test_industry_dossier_styles_are_present():
    styles = (ROOT / "cockpit" / "templates" / "_sector_styles.html").read_text()
    for cls in ("vc-card", "slide-row", "drv-card", "pick-row", "seg-chip", "trend-box", "ps-header"):
        assert f".{cls}" in styles, cls
