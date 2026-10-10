"""Every script/stylesheet a template loads from /static carries ?v=<version>, and /static
answers with cache rules: versioned = immutable, unversioned = revalidate.

2026-10-10: cockpit.js was loaded without ?v=, browsers kept a days-old copy after deploys,
and the stock page's charts (which call loadChart/makeChart from it) stayed blank."""
import pathlib
import re

from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_every_static_script_and_stylesheet_is_versioned():
    bad = []
    for d in ("cockpit/templates", "cockpit_ops/templates"):
        for f in (ROOT / d).rglob("*.html"):
            for m in re.finditer(r'(?:src|href)="(/static/[^"]+\.(?:js|css)[^"]*)"', f.read_text()):
                if "?v=" not in m.group(1):
                    bad.append(f"{f.relative_to(ROOT)}: {m.group(1)}")
    assert not bad, bad


def test_static_cache_headers():
    from cockpit.app import app
    c = TestClient(app)
    assert c.get("/static/cockpit.js").headers["cache-control"] == "no-cache"
    assert "immutable" in c.get("/static/cockpit.js?v=1").headers["cache-control"]
