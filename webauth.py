"""
Alpha Signal v2 — password login for the cockpits (:3000 main, :3001 ops).

Both apps were reachable from the internet with no auth (architecture review F5):
:3001/sql read the whole DB and POST /api/pipeline/rerun started harvests.

  * One password for both apps, stored as a scrypt hash — never the password —
    in AUTH_FILE (chmod 600, outside the repo; the secrets backup bundles it).
  * A signed session cookie (HMAC-SHA256, 30 days, HttpOnly, SameSite=Lax, Secure
    when served over HTTPS). SameSite=Lax also stops cross-site POSTs (CSRF).
  * 5 failed logins from one IP → that IP is locked out for 15 minutes.
  * Fails CLOSED: no AUTH_FILE → every page says "login not configured".
  * Unauthenticated page request → 303 to /login?next=<path>; /api/* → 401 JSON.

Plain functions + one ASGI middleware class (ADR 0004). No new dependencies.

Usage:
    python -m webauth set-password        # prompt for a password (and create the file)
    python -m webauth generate            # set a random password and print it once
    python -m webauth status              # is it configured?
"""

import base64
import getpass
import hashlib
import hmac
import html
import json
import os
import pathlib
import secrets
import sys
import time
from urllib.parse import parse_qs, quote

AUTH_FILE = pathlib.Path(os.environ.get(
    "ALPHA_AUTH_FILE", pathlib.Path.home() / ".config/alpha-signal/cockpit_auth.json"))
COOKIE = "alpha_session"
SESSION_DAYS = 30
MAX_FAILS, LOCK_SECONDS = 5, 15 * 60
PUBLIC_PATHS = ("/login", "/logout", "/static/", "/favicon.ico")
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
_fails = {}                        # ip → [fail_count, first_fail_ts]


# ─────────────────────────── credentials ───────────────────────────

def _load():
    try:
        return json.loads(AUTH_FILE.read_text())
    except (OSError, ValueError):
        return None


def _hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT).hex()


def set_password(password):
    """Write a new hash; keeps the session secret (rotate it to log everyone out)."""
    if len(password) < 10:
        raise ValueError("use at least 10 characters")
    cfg = _load() or {"session_secret": secrets.token_hex(32)}
    salt = secrets.token_bytes(16)
    cfg.update(salt=salt.hex(), password_hash=_hash(password, salt))
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = AUTH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg))
    os.chmod(tmp, 0o600)
    tmp.replace(AUTH_FILE)


def check_password(password):
    cfg = _load()
    if not cfg:
        return False
    return hmac.compare_digest(_hash(password, bytes.fromhex(cfg["salt"])), cfg["password_hash"])


# ─────────────────────────── session cookie ───────────────────────────

def _sign(payload, secret):
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(now=None):
    cfg = _load()
    exp = int((now or time.time()) + SESSION_DAYS * 86400)
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode()
    return f"{payload}.{_sign(payload, cfg['session_secret'])}"


def valid_token(token, now=None):
    cfg = _load()
    if not cfg or not token or "." not in token:
        return False
    payload, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(payload, cfg["session_secret"])):
        return False
    try:
        exp = json.loads(base64.urlsafe_b64decode(payload.encode()))["exp"]
    except (ValueError, KeyError):
        return False
    return (now or time.time()) < exp


# ─────────────────────────── rate limit ───────────────────────────

def _locked(ip, now):
    n, first = _fails.get(ip, (0, now))
    if now - first > LOCK_SECONDS:
        _fails.pop(ip, None)
        return False
    return n >= MAX_FAILS


def _record_fail(ip, now):
    n, first = _fails.get(ip, (0, now))
    _fails[ip] = [n + 1, first if now - first <= LOCK_SECONDS else now]


# ─────────────────────────── ASGI ───────────────────────────

def _headers(scope):
    return {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}


def _client_ip(scope, h):
    ip = (scope.get("client") or ("?",))[0]
    if ip in ("127.0.0.1", "::1") and h.get("x-forwarded-for"):
        ip = h["x-forwarded-for"].split(",")[0].strip()       # behind the local nginx
    return ip


def _cookie(h, name):
    for part in h.get("cookie", "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return None


def _https(scope, h):
    return scope.get("scheme") == "https" or h.get("x-forwarded-proto") == "https"


def _safe_next(n):
    return n if n.startswith("/") and not n.startswith("//") and "\\" not in n else "/"


async def _send(send, status, body, ctype="text/html; charset=utf-8", extra=()):
    body = body.encode() if isinstance(body, str) else body
    hdrs = [(b"content-type", ctype.encode()), (b"content-length", str(len(body)).encode()),
            (b"cache-control", b"no-store"), (b"x-frame-options", b"DENY")] + list(extra)
    await send({"type": "http.response.start", "status": status, "headers": hdrs})
    await send({"type": "http.response.body", "body": body})


def _page(app_name, next_path, error=""):
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign in · {html.escape(app_name)}</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--fg:#1c2024;--mut:#6b7280;--acc:#2563eb;--bd:#e5e7eb;--err:#b91c1c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1115;--card:#171a21;--fg:#e6e8eb;--mut:#9aa3af;--acc:#60a5fa;--bd:#2a2f3a;--err:#f87171}}}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);
color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:16px}}
.card{{width:100%;max-width:360px;background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:28px}}
h1{{font-size:18px;margin:0 0 4px}}p.sub{{margin:0 0 20px;color:var(--mut);font-size:13px}}
label{{display:block;font-size:13px;color:var(--mut);margin-bottom:6px}}
input{{width:100%;padding:10px 12px;border:1px solid var(--bd);border-radius:8px;background:transparent;color:var(--fg);font-size:15px}}
input:focus{{outline:2px solid var(--acc);outline-offset:1px}}
button{{margin-top:16px;width:100%;padding:10px;border:0;border-radius:8px;background:var(--acc);color:#fff;font-size:15px;cursor:pointer}}
.err{{color:var(--err);font-size:13px;margin:12px 0 0}}</style></head><body>
<form class="card" method="post" action="/login">
<h1>Alpha Signal</h1><p class="sub">{html.escape(app_name)} — sign in to continue</p>
<label for="pw">Password</label>
<input id="pw" name="password" type="password" autocomplete="current-password" autofocus required>
<input type="hidden" name="next" value="{html.escape(next_path)}">
<button type="submit">Sign in</button>{err}</form></body></html>"""


class LoginRequired:
    """ASGI middleware: everything except PUBLIC_PATHS needs a valid session cookie."""

    def __init__(self, app, app_name="Cockpit"):
        self.app, self.app_name = app, app_name

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path, method = scope["path"], scope["method"]
        h = _headers(scope)
        if _load() is None:                              # fail closed
            return await _send(send, 503, "<h1>Login not configured</h1>"
                               "<p>Run <code>python -m webauth set-password</code> on the server.</p>")
        if path == "/login":
            return await self._login(scope, receive, send, h, method)
        if path == "/logout":
            return await _send(send, 303, "", extra=[(b"location", b"/login"),
                               (b"set-cookie", f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax".encode())])
        if path.startswith(PUBLIC_PATHS) or valid_token(_cookie(h, COOKIE)):
            return await self.app(scope, receive, send)
        if path.startswith("/api/"):
            return await _send(send, 401, '{"error": "login required"}', "application/json")
        nxt = path + ("?" + scope["query_string"].decode() if scope.get("query_string") else "")
        return await _send(send, 303, "", extra=[(b"location", f"/login?next={quote(nxt)}".encode())])

    async def _login(self, scope, receive, send, h, method):
        qs = parse_qs(scope.get("query_string", b"").decode())
        if method != "POST":
            return await _send(send, 200, _page(self.app_name, _safe_next(qs.get("next", ["/"])[0])))
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body") or len(body) > 8192:
                break
        form = parse_qs(body.decode(errors="replace"))
        nxt = _safe_next(form.get("next", ["/"])[0])
        ip, now = _client_ip(scope, h), time.time()
        if _locked(ip, now):
            return await _send(send, 429, _page(self.app_name, nxt, "Too many attempts — try again in 15 minutes."))
        if not check_password(form.get("password", [""])[0]):
            _record_fail(ip, now)
            return await _send(send, 401, _page(self.app_name, nxt, "Wrong password."))
        _fails.pop(ip, None)
        secure = "; Secure" if _https(scope, h) else ""
        cookie = (f"{COOKIE}={make_token(now)}; Path=/; Max-Age={SESSION_DAYS * 86400}; "
                  f"HttpOnly; SameSite=Lax{secure}")
        return await _send(send, 303, "", extra=[(b"location", nxt.encode()), (b"set-cookie", cookie.encode())])


# ─────────────────────────── CLI ───────────────────────────

if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["status"])[0]
    if cmd == "set-password":
        p1 = getpass.getpass("New cockpit password: ")
        if p1 != getpass.getpass("Repeat: "):
            sys.exit("passwords differ")
        set_password(p1)
        print(f"saved hash to {AUTH_FILE} (chmod 600)")
    elif cmd == "generate":
        pw = secrets.token_urlsafe(15)
        set_password(pw)
        print(f"cockpit password: {pw}\n(stored only as a hash in {AUTH_FILE}; change it with set-password)")
    elif cmd == "status":
        print("configured" if _load() else f"NOT configured — no {AUTH_FILE}")
    else:
        sys.exit("usage: python -m webauth [set-password|generate|status]")
