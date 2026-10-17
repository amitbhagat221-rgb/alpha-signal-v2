"""Macro chapters as prose + figures (plan 0028): the validator and the renderer."""
from tools import macro_chapters as M

SRC = {"id": "in-9", "track": "India", "title": "T", "figures": [{"n": 1, "kind": "fig", "caption": "c", "label": "l",
                                                                  "html": '<div class="fig"><svg></svg></div>'}],
       "keep": {"ch-inds": '<div class="ch-inds">x</div>', "ch-nav": '<div class="ch-nav">old</div>'}}
VALS = {"date": ("2026-10-16", "d"), "brent": ("$109.69", "Brent"), "rbi": ("Raised rates", "stance")}
WORDS = " ".join(["word"] * 1500)


def _prose(**kw):
    p = {"title": "New", "minutes": 9, "hook": "<p>A scene.</p>", "short": ["One."],
         "sections": [{"heading": "Why", "html": f"<p>{WORDS}</p><p>Mid [[fig:1]] para.</p>"}],
         "history": [{"when": "2013", "title": "t", "story": "<p>s</p>", "lesson": "l"}] * 4,
         "today": "<p>Brent at [[val:brent]]; stance <b>[[val:rbi]]</b>.</p>", "sowhat": "<p>Prefer banks.</p>"}
    p.update(kw)
    return p


def test_valid_chapter_renders_figures_values_and_new_nav():
    problems, words = M.validate(_prose(), SRC, set(VALS))
    assert not problems and words > 1400
    html = M.render(_prose(), SRC, VALS, "2026-10-17", 1, 1, M.nav("in-9", ["in-8", "in-9"], {"in-8": "Prev", "in-9": "New"}))
    assert '<p>Mid </p><div class="fig"><svg></svg></div><p> para.</p>' in html      # a figure never sits inside a paragraph
    assert '<span class="mono feedv" title="Brent">$109.69</span>' in html and '<span class="feedt"' in html
    assert "← Prev" in html and "old" not in html and "story-card" in html and "The short version" in html


def test_validator_catches_figures_in_prose_missing_figures_tags_and_tokens():
    bad = _prose(hook="<p>Brent rose 4% today.</p>", sections=[{"heading": "h", "html": f"<p>{WORDS}</p><h2>x</h2>"}],
                 today="<p>[[val:nope]]</p>")
    problems, _ = M.validate(bad, SRC, set(VALS))
    text = " ".join(problems)
    assert "figures in prose" in text and "tag <h2>" in text and "[[val:nope]]" in text and "figures [1]" in text
    assert any("at least four stories" in p for p in M.validate(_prose(history=[]), SRC, set(VALS))[0])
