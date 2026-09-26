"""output/_llm.py with a mocked Anthropic client — no network, no credits."""
import sys
import types

import pytest

import output._llm as llm


class _FakeClient:
    def __init__(self, text):
        self.text = text
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(text=self.text)],
            usage=types.SimpleNamespace(input_tokens=11, output_tokens=7),
        )


@pytest.fixture
def usage_log(monkeypatch):
    logged = []
    monkeypatch.setattr(llm, "log_llm_usage", lambda *a, **k: logged.append((a, k)))
    return logged


@pytest.mark.parametrize("reply, expected", [
    ('{"thesis": "x", "conviction": "HIGH"}', {"thesis": "x", "conviction": "HIGH"}),
    ('Sure:\n```json\n{"thesis": "y"}\n```\nDone', {"thesis": "y"}),
    ('```{"a": 1}```', {"a": 1}),
    ("no json here", {"raw_response": "no json here"}),
])
def test_llm_json_parses_and_logs(usage_log, reply, expected):
    client = _FakeClient(reply)
    out = llm.llm_json("prompt!", "claude-sonnet-4-6", "dossier", max_tokens=1024, client=client)
    assert out == expected
    assert client.calls == [{"model": "claude-sonnet-4-6", "max_tokens": 1024,
                             "messages": [{"role": "user", "content": "prompt!"}]}]
    (args, kwargs), = usage_log
    assert args[:2] == ("dossier", "claude-sonnet-4-6") and kwargs == {}
    assert args[2].input_tokens == 11


def test_llm_json_bad_fenced_block_raises(usage_log):
    with pytest.raises(ValueError):
        llm.llm_json("p", "m", "s", client=_FakeClient("```json\n{not json\n```"))


def test_llm_text_builds_default_client(usage_log, monkeypatch):
    fake = _FakeClient("hello")
    monkeypatch.setitem(sys.modules, "anthropic",
                        types.SimpleNamespace(Anthropic=lambda **kw: fake))
    assert llm.llm_text("p", "claude-haiku-4-5-20251001", "step_x", max_tokens=512) == "hello"
    assert fake.calls[0]["max_tokens"] == 512
    assert usage_log[0][0][:2] == ("step_x", "claude-haiku-4-5-20251001")


def test_sector_dossier_call_claude_uses_llm_json(usage_log, monkeypatch):
    from output import sector_dossier
    fake = _FakeClient('{"thesis": "sector"}')
    monkeypatch.setitem(sys.modules, "anthropic",
                        types.SimpleNamespace(Anthropic=lambda **kw: fake))
    assert sector_dossier._call_claude("p") == {"thesis": "sector"}
    assert usage_log[0][0][:2] == ("compute_sector_dossiers", sector_dossier.MODEL)


def test_compare_reg_models_keeps_production_parser(usage_log):
    from tools import compare_reg_models as crm
    ev = {"title": "t", "summary": "s", "source": "BSE", "published_at": "2026-09-01"}
    client = _FakeClient('```json\n{"sectors_affected": [{"sector": "IT", "direction": 1}]}\n```')
    cls = crm._classify_with(client, "claude-haiku-4-5-20251001", ev)
    assert crm._sector_dirs(cls) == {"IT": 1}
    assert usage_log[0][0][0] == "compare_reg_models[haiku]"
    # embedded (non-leading) fence: production parser rejects it, and so does the gate
    assert crm._classify_with(_FakeClient('x ```{"a":1}```'), "claude-haiku-4-5-20251001", ev) is None
