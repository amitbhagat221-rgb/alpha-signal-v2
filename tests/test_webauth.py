"""webauth: cockpit password login (architecture review F5)."""
import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def wa(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHA_AUTH_FILE", str(tmp_path / "auth.json"))
    import webauth
    importlib.reload(webauth)
    webauth._fails.clear()
    return webauth


def _client(wa):
    app = FastAPI()
    app.add_middleware(wa.LoginRequired, app_name="Test")

    @app.get("/")
    def home():
        return {"ok": True}

    @app.get("/api/x")
    def api():
        return {"ok": True}

    return TestClient(app, follow_redirects=False)


def test_fails_closed_without_credentials(wa):
    assert _client(wa).get("/").status_code == 503


def test_pages_redirect_and_api_gets_401(wa):
    wa.set_password("correct horse battery")
    c = _client(wa)
    r = c.get("/?tier=LARGE")
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/%3Ftier%3DLARGE"
    assert c.get("/api/x").status_code == 401
    assert c.get("/login").status_code == 200


def test_login_sets_a_cookie_that_grants_access(wa):
    wa.set_password("correct horse battery")
    c = _client(wa)
    r = c.post("/login", data={"password": "correct horse battery", "next": "/api/x"})
    assert r.status_code == 303 and r.headers["location"] == "/api/x"
    assert "HttpOnly" in r.headers["set-cookie"] and "Secure" not in r.headers["set-cookie"]
    assert c.get("/api/x").json() == {"ok": True}
    assert c.get("/logout").status_code == 303


def test_secure_cookie_behind_https_proxy(wa):
    wa.set_password("correct horse battery")
    r = _client(wa).post("/login", data={"password": "correct horse battery"},
                         headers={"x-forwarded-proto": "https"})
    assert "Secure" in r.headers["set-cookie"]


def test_wrong_password_then_lockout(wa):
    wa.set_password("correct horse battery")
    c = _client(wa)
    for _ in range(wa.MAX_FAILS):
        assert c.post("/login", data={"password": "nope"}).status_code == 401
    r = c.post("/login", data={"password": "correct horse battery"})
    assert r.status_code == 429                         # locked even with the right password


def test_tampered_or_expired_tokens_are_rejected(wa):
    wa.set_password("correct horse battery")
    t = wa.make_token(now=1_000_000)
    assert wa.valid_token(t, now=1_000_001)
    assert not wa.valid_token(t, now=1_000_000 + wa.SESSION_DAYS * 86400 + 1)
    payload, sig = t.rsplit(".", 1)
    assert not wa.valid_token(payload + "." + "0" * len(sig), now=1_000_001)
    assert not wa.valid_token("garbage", now=1_000_001)


def test_next_cannot_redirect_off_site(wa):
    assert wa._safe_next("//evil.com") == "/"
    assert wa._safe_next("https://evil.com") == "/"
    assert wa._safe_next("/\\evil.com") == "/"
    assert wa._safe_next("/picks?tier=MID") == "/picks?tier=MID"


def test_hash_file_is_private_and_holds_no_password(wa):
    import os
    import stat
    wa.set_password("correct horse battery")
    assert stat.S_IMODE(os.stat(wa.AUTH_FILE).st_mode) == 0o600
    assert "correct horse battery" not in wa.AUTH_FILE.read_text()
    with pytest.raises(ValueError):
        wa.set_password("short")
