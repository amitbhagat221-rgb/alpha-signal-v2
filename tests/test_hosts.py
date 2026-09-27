"""hosts.HOSTS — the one declaration of every external dependency (plan 0015 Phase 2)."""
import ast
import pathlib
import re

from hosts import DEFAULT, HOSTS

ROOT = pathlib.Path(__file__).resolve().parent.parent
_KEYS = {"netlocs", "gap", "jitter", "headers", "retries", "budget_min", "models"}


def test_every_host_is_polite():
    """CLAUDE.md: ≥2 s between calls to one host — no entry may undercut it."""
    assert DEFAULT["gap"] >= 2.0
    for name, h in HOSTS.items():
        assert set(h) <= _KEYS, f"{name}: unknown keys {set(h) - _KEYS}"
        assert {**DEFAULT, **h}["gap"] >= 2.0, name
        assert {**DEFAULT, **h}["jitter"] >= 0, name


def test_netloc_belongs_to_one_host():
    seen = {}
    for name, h in HOSTS.items():
        for n in h.get("netlocs", ()):
            assert n == n.lower() and "/" not in n, f"{name}: bad netloc {n!r}"
            assert n not in seen, f"{n} declared by both {seen.get(n)} and {name}"
            seen[n] = name


def test_known_politeness_exceptions_kept():
    """The documented per-host gaps must never get faster than before the door."""
    assert HOSTS["moneycontrol"]["gap"] >= 12.0            # 2 s tripped the WAF
    assert HOSTS["moneycontrol"]["budget_min"] == 90
    assert HOSTS["etmoney"]["gap"] >= 2.5
    assert HOSTS["screener"]["gap"] >= 2.5                 # was 2.5–4 s between stocks


def test_every_url_literal_in_sources_resolves_to_a_declared_host():
    """A new external host must be declared in hosts.HOSTS before code calls it."""
    from sources import _http
    undeclared = set()
    for f in (ROOT / "sources").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for url in re.findall(r"https?://[A-Za-z0-9.-]+\.[a-z]{2,}(?=[/?\"']|$)", node.value):
                    # an XML namespace and a sign-up link in an error message — never called
                    if url.split("//")[1] in ("www.w3.org", "www.pexels.com"):
                        continue
                    if _http.host(url)[0] not in HOSTS:
                        undeclared.add(f"{f.name}: {url}")
    assert not undeclared, "declare in hosts.HOSTS:\n" + "\n".join(sorted(undeclared))


def test_llm_models_read_from_the_anthropic_host():
    models = HOSTS["anthropic"]["models"]
    assert all(v.startswith("claude-") for v in models.values())
    from output import _llm, sector_dossier
    from sources import news_brief, news_classifier, regulatory_classifier
    assert _llm.MODELS is models
    assert sector_dossier.MODEL == models["sector_dossier"]
    assert news_brief.SONNET_MODEL == models["news_brief"]
    assert news_classifier.HAIKU_MODEL == models["news_classify"]
    assert regulatory_classifier.HAIKU_MODEL == models["regulatory_prefilter"]
    assert regulatory_classifier.SONNET_MODEL == models["regulatory_deep"]
    # the hard-coded ids are gone from every LLM call site
    for rel in ("output/dossier.py", "output/sector_dossier.py", "sources/news_brief.py",
                "sources/news_classifier.py", "sources/regulatory_classifier.py"):
        assert not re.search(r"[\"']claude-[a-z0-9-]+[\"']", (ROOT / rel).read_text()), rel


def test_config_api_block_is_gone():
    import config
    assert not hasattr(config, "API")
    assert config.LLM["regulatory_deep_model"] == HOSTS["anthropic"]["models"]["regulatory_deep"]
