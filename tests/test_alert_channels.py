"""Urgent alerts ring the phone too (ALERT_CALL_URL), not only ntfy (2026-11-03: the push never reached the phone)."""
import urllib.request

from tools import health_report as hr


class _Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_an_urgent_push_also_rings_the_phone(monkeypatch):
    calls = []
    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.setenv("ALERT_CALL_URL", "https://call.example/ring?msg={text}")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: calls.append((req.full_url, req.get_method(), dict(req.header_items()))) or _Resp())
    assert hr.send_ntfy("step closeall CRASHED: x", urgent=True)
    assert len(calls) == 2
    ntfy, ring = calls
    assert ntfy[0] == "https://ntfy.sh/t" and ntfy[2]["Priority"] == "urgent" and "rotating_light" in ntfy[2]["Tags"]
    assert ring[0].startswith("https://call.example/ring?msg=step%20closeall%20CRASHED") and ring[1] == "GET"


def test_a_plain_push_does_not_ring(monkeypatch):
    calls = []
    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.setenv("ALERT_CALL_URL", "https://call.example/ring?msg={text}")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: calls.append(req.full_url) or _Resp())
    hr.send_ntfy("weekly P&L", urgent=False)
    assert calls == ["https://ntfy.sh/t"]


def test_ring_is_a_noop_without_the_url(monkeypatch, capsys):
    monkeypatch.delenv("ALERT_CALL_URL", raising=False)
    assert hr.ring_phone("x") is False and "ALERT_CALL_URL not set" in capsys.readouterr().out
