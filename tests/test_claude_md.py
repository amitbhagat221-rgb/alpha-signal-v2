"""CLAUDE.md stays small: the always-loaded file has a word budget, and area rules live in
path-scoped `.claude/rules/*.md` files that load only when a matching file is touched.

2026-10-14: CLAUDE.md had grown 555 -> 2,183 words since the 2026-05-22 trim. Every
/handoff added to it and nothing ever took a rule out; new lessons were appended onto
old bullets (one reached 148 words) and incident stories crowded out the rules."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLAUDE_MD = ROOT / "CLAUDE.md"
RULES = ROOT / ".claude" / "rules"

ROOT_WORDS = 1800
BULLET_WORDS = 60
RULE_FILE_WORDS = 800


def _words(text):
    return len(text.split())


def _paths(rule_file):
    """The `paths:` globs from a rule file's frontmatter (a list of quoted strings)."""
    text = rule_file.read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m or "paths:" not in m.group(1):
        return []
    return re.findall(r'^\s*-\s*"([^"]+)"\s*$', m.group(1), re.M)


def test_root_claude_md_within_word_budget():
    n = _words(CLAUDE_MD.read_text())
    assert n <= ROOT_WORDS, (
        f"CLAUDE.md is {n} words (budget {ROOT_WORDS}). Move an area rule to .claude/rules/, "
        "or move its story to the ADR and keep one clause + the ADR number.")


def test_root_bullets_are_one_rule_not_a_story():
    long = [(l.strip()[:70], _words(l)) for l in CLAUDE_MD.read_text().splitlines()
            if l.lstrip().startswith("- ") and _words(l) > BULLET_WORDS]
    assert not long, f"bullets over {BULLET_WORDS} words: {long}"


def test_every_rule_file_is_path_scoped_and_small():
    files = sorted(RULES.glob("*.md"))
    assert files, "no .claude/rules/*.md files"
    for f in files:
        # A rule file without paths loads in EVERY session, silently growing the budget.
        assert _paths(f), f"{f.name}: needs a `paths:` frontmatter list"
        n = _words(f.read_text())
        assert n <= RULE_FILE_WORDS, f"{f.name}: {n} words (budget {RULE_FILE_WORDS})"


def test_every_rule_glob_matches_a_real_file():
    # A glob that matches nothing means the rule never loads (a file was renamed or moved).
    dead = []
    for f in sorted(RULES.glob("*.md")):
        for g in _paths(f):
            pattern = g + "/*" if g.endswith("**") else g
            if not any(p.is_file() for p in ROOT.glob(pattern)):
                dead.append(f"{f.name}: {g}")
    assert not dead, f"globs matching no file: {dead}"


def test_every_rule_file_is_listed_in_claude_md():
    text = CLAUDE_MD.read_text()
    missing = [f.name for f in RULES.glob("*.md") if f"`{f.name}`" not in text]
    assert not missing, f"add a row to CLAUDE.md's 'Area rules' table for: {missing}"
