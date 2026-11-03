"""A cached Kite token is a session only when Kite says so (ADR 0093, after 2026-11-03)."""
import json
from datetime import datetime, timezone

import pytest
from kiteconnect.exceptions import TokenException

from sources import kite_pull as kp


class _Stub:
    dead = set()

    def __init__(self, api_key=None):
        self.token = None

    def set_access_token(self, tok):
        self.token = tok

    def place_order(self, **kw):
        return "PLACED"

    def profile(self):
        if self.token in _Stub.dead:
            raise TokenException("Incorrect `api_key` or `access_token`.")
        return {"user_id": "FAKE"}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    f = tmp_path / "tok.json"
    monkeypatch.setattr(kp, "TOKEN_CACHE", str(f))
    monkeypatch.setenv("KITE_API_KEY", "k")
    import kiteconnect
    monkeypatch.setattr(kiteconnect, "KiteConnect", _Stub)
    return f


def _write(f, tok, at=None):
    f.write_text(json.dumps({"date": kp._ist_now().date().isoformat(), "access_token": tok,
                             "at": at or datetime.now(timezone.utc).isoformat()}))


def test_a_rejected_cached_token_is_dropped_and_reported_as_no_session(cache):
    _write(cache, "dead")
    _Stub.dead = {"dead"}
    with pytest.raises(kp.NoKiteSession) as ex:
        kp.kite(cached_only=True)
    assert "after 08:30" in str(ex.value) and not cache.exists()        # the next call cannot reuse it
    with pytest.raises(kp.NoKiteSession):
        kp.kite(cached_only=True)


def test_a_live_cached_token_is_handed_out(cache):
    _write(cache, "good")
    _Stub.dead = set()
    assert kp.kite(cached_only=True).token == "good" and cache.exists()


def test_login_info_flags_a_login_before_0830_ist(cache):
    _write(cache, "good", at="2026-11-03T00:49:07+00:00")                 # 06:19 IST: the 2026-11-03 login
    assert kp.login_info()["early"] is True
    _write(cache, "good", at="2026-11-03T03:30:00+00:00")                 # 09:00 IST
    assert kp.login_info()["early"] is False
    cache.unlink()
    assert kp.login_info() is None


def test_a_claude_session_cannot_write_to_the_broker(cache, monkeypatch):
    _write(cache, "good")
    _Stub.dead = set()
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(kp.ClaudeMayNotTrade):
        kp.kite(cached_only=True).place_order(variety="regular")
    assert kp.kite(cached_only=True).profile()["user_id"] == "FAKE"       # reads still work
    monkeypatch.delenv("CLAUDECODE")
    assert kp.kite(cached_only=True).place_order(variety="regular") == "PLACED"   # cron and the cockpit are untouched
