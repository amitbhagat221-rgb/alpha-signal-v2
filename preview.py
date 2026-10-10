"""
Alpha Signal v2 - preview mode for the Cockpit v2 layout, shared by both apps.

The same code runs live and as a side-by-side PREVIEW (so the new layout can be compared
with the live one before it is approved). Everything is driven by env vars, read per
request so a test can flip them:

  COCKPIT_PREVIEW=1            preview on: banner on every page, writes refused (403)
  COCKPIT_COMPARE_MAIN_URL     live main cockpit  (default http://140.245.248.166:3000)
  COCKPIT_COMPARE_OPS_URL      live ops cockpit   (default https://alpha.rendezvous-app.duckdns.org)
  COCKPIT_MAIN_URL / _OPS_URL  where main_url() / ops_url() / other_url() point (cockpit/_shared.py)
                               - on the preview each app links to the other PREVIEW host

Extending the compare link (the banner's "Open this page on the live cockpit"): edit
COMPARE below and nothing else.
"""

import json
import os

# ── where the same page lives on the live (old-layout) cockpit ──────────────────────
# New path -> old path, per app. A page not listed maps to the same path.
#   "/path"        the page, whatever tab is open
#   "/path#tab"    that tab of the page (the banner script swaps the link when the
#                  URL hash changes, since the server never sees the hash)
# The old value may itself carry a hash ("/system#pipeline"). Query strings are carried over.
COMPARE = {
    "main": {
        "/": "/",
        "/#actions": "/actions",
        "/stocks": "/explorer",
        "/markets": "/news",
        "/markets#industries": "/sectors",
        "/markets#search": "/news/all",
        "/ideas": "/playbooks",
        "/ideas#screens": "/playbooks",          # strict compounders (the toggle) = live /multibagger
        "/ideas#avoid": "/playbooks",
        "/ideas#track-record": "/playbooks",
        "/book": "/portfolio",
        "/book#track-record": "/model/outcomes",
        "/model": "/model",
        "/mutual-funds": "/mutual-funds",
    },
    "ops": {
        "/system": "/system",
        "/feeds": "/feeds",
        "/feeds#data": "/command",
        "/flow": "/flow",
        "/flow#pipeline-log": "/system#pipeline",
        "/org": "/org",
        "/options": "/options",
        "/sql": "/sql",
    },
}

# Pages with a path parameter: new prefix -> old prefix (the rest of the path is kept).
COMPARE_PREFIXES = {
    "main": [("/stocks/", "/explorer/"), ("/markets/theme/", "/news/theme/")],
    "ops": [],
}

_DEFAULT_LIVE = {"main": "http://140.245.248.166:3000", "ops": "https://alpha.rendezvous-app.duckdns.org"}
READONLY_MESSAGE = "preview is read-only — use the live cockpit"


def is_preview():
    return os.environ.get("COCKPIT_PREVIEW", "").strip().lower() in ("1", "true", "yes", "on")


def live_base(role):
    return (os.environ.get(f"COCKPIT_COMPARE_{role.upper()}_URL") or _DEFAULT_LIVE[role]).rstrip("/")


def compare_target(role, path):
    """(old path for `path`, {"#tab": old path for that tab}) on the live cockpit."""
    table = COMPARE.get(role, {})
    old = table.get(path)
    if old is None:
        old = path
        for new_prefix, old_prefix in COMPARE_PREFIXES.get(role, []):
            if path.startswith(new_prefix):
                old = old_prefix + path[len(new_prefix):]
                break
    tabs = {k[len(path):]: v for k, v in table.items() if k.startswith(path + "#")}
    return old, tabs


def compare_links(role, path, query=""):
    """What the banner needs: the live URL of this page and of each of its tabs."""
    old, tabs = compare_target(role, path)
    base, qs = live_base(role), (f"?{query}" if query else "")

    def full(target):
        p, _, h = target.partition("#")
        return f"{base}{p}{qs}" + (f"#{h}" if h else "")

    return {"url": full(old), "tabs": {h: full(t) for h, t in tabs.items()}}


def banner(role, request):
    """Template global `preview_banner()`: None when preview is off, else the link data."""
    if not is_preview():
        return None
    data = compare_links(role, request.url.path, request.url.query) if request else {"url": live_base(role), "tabs": {}}
    return {**data, "tabs_json": json.dumps(data["tabs"])}


# ── read-only guard ─────────────────────────────────────────────────────────────────

class PreviewReadOnly:
    """ASGI middleware: in preview, every request that is not GET/HEAD/OPTIONS gets a 403
    JSON error, except the login POST. A no-op when COCKPIT_PREVIEW is unset."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] == "http" and is_preview()
                and scope["method"] not in ("GET", "HEAD", "OPTIONS")
                and scope["path"] != "/login"):
            body = json.dumps({"error": READONLY_MESSAGE}).encode()
            await send({"type": "http.response.start", "status": 403, "headers": [
                (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store")]})
            return await send({"type": "http.response.body", "body": body})
        return await self.app(scope, receive, send)


# ── redirects from retired URLs ─────────────────────────────────────────────────────

def add_redirects(app, redirects):
    """Register [(old path, target)] as 302 GET redirects. `{name}` in the old path is a
    path parameter the target may reuse; the query string is kept and a `#tab` in the
    target is kept in the Location, so the new page opens on that tab."""
    from fastapi import Request
    from fastapi.responses import RedirectResponse

    def make(target):
        def go(request: Request):
            url, _, tab = target.format(**request.path_params).partition("#")
            if request.url.query:
                url += ("&" if "?" in url else "?") + request.url.query
            return RedirectResponse(url + (f"#{tab}" if tab else ""), status_code=302)
        return go

    for old, target in redirects:
        app.add_api_route(old, make(target), methods=["GET"], include_in_schema=False)
