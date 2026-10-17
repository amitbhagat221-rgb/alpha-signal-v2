"""The "Ask" page assistant (ask.py): page context, stored conversations, read-only tool scope."""
import json
import re
from pathlib import Path

import pytest

import ask
import db
import org

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """A temp DB and a fake CLI turn that records each prompt and replies "answer N"."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ask.db")
    db.init_db()
    calls = []

    def turn(prompt, session_id, model):
        calls.append({"prompt": prompt, "session_id": session_id, "model": model})
        yield "tool", "research.stock"
        yield "delta", f"answer {len(calls)}"
        yield "end", {"session_id": "sess-1", "text": f"answer {len(calls)}", "tools": ["research.stock"],
                      "error": None, "usage": None, "model": "claude-sonnet"}
    monkeypatch.setattr(ask, "_turn", turn)
    return calls


def _events(gen):
    return [json.loads(chunk[6:]) for chunk in gen]


PAGE = {"url": "/stocks/REDY", "title": "Dr Reddy's", "text": "Rank 23 of 100\n\n\nScore 0.61", "selection": ""}


def test_page_block_sends_the_page_once_and_the_selection_first():
    block, h = ask.page_block(dict(PAGE, selection="Rank  23\nof 100"))
    assert block.startswith('<page url="/stocks/REDY" title="Dr Reddy\'s">')
    assert block.index("Selected text") < block.index("Visible text")
    assert "Rank 23 of 100\nScore 0.61" in block                    # blank-line runs dropped, lines kept
    again, h2 = ask.page_block(PAGE, previous_hash=h)
    assert h2 == h and "unchanged" in again and "Score 0.61" not in again
    assert ask.page_block({}) == ("", ask.page_block({})[1])
    assert ask.page_block(dict(PAGE, text="#" * 50000))[0].count("#") == ask.MAX_PAGE_TEXT


def test_a_stock_page_names_its_stock(monkeypatch):
    monkeypatch.setattr(db, "one", lambda sql, params: {"sid": params[0], "name": "Larsen and Toubro Ltd", "ticker": "LT"})
    assert ask.page_stock("/stocks/LART#financials")["name"] == "Larsen and Toubro Ltd"
    assert ask.page_stock("/multibagger/stock/LART/valuation?x=1")["sid"] == "LART"
    assert ask.page_stock("/stocks") is None and ask.page_stock("/sectors") is None
    block, _ = ask.page_block({"url": "/stocks/LART", "title": "L&T", "text": "Capex"})
    assert "sid LART (Larsen and Toubro Ltd · NSE LT)" in block and '"This business"' in block
    assert "stock" not in ask.page_block({"url": "/sectors", "text": "x"})[0]


def test_a_turn_is_stored_and_the_conversation_continues(fake):
    ev = _events(ask.stream("What is this?", PAGE, new=True))
    assert [e["t"] for e in ev] == ["start", "tool", "delta", "done"]
    h = ask.history()
    assert h["conv"] == ev[0]["conv"] and not h["pending"] and h["session_id"] == "sess-1"
    assert [(m["who"], m["text"]) for m in h["messages"]] == [("you", "What is this?"), ("assistant", "answer 1")]
    assert h["messages"][0]["page"] == {"url": "/stocks/REDY", "title": "Dr Reddy's"}

    _events(ask.stream("And the score?", PAGE))                      # same conversation, same page
    assert fake[1]["session_id"] == "sess-1"
    assert "unchanged" in fake[1]["prompt"] and "Score 0.61" not in fake[1]["prompt"]
    assert fake[1]["prompt"].endswith("And the score?")
    assert [c["n"] for c in ask.conversations()] == [4]

    _events(ask.stream("New topic", PAGE, new=True))                  # a new chat starts a new session
    assert fake[2]["session_id"] is None and "Score 0.61" in fake[2]["prompt"]
    assert len(ask.conversations()) == 2


def test_a_failed_turn_is_stored_so_the_panel_stops_waiting(fake, monkeypatch):
    def dead(prompt, session_id, model):
        yield "end", {"session_id": None, "text": "", "tools": [], "error": "rate limited", "usage": None, "model": None}
    monkeypatch.setattr(ask, "_turn", dead)
    ev = _events(ask.stream("Hello", PAGE, new=True))
    assert ev[-1] == {"t": "error", "error": "rate limited"}
    h = ask.history()
    assert not h["pending"] and "rate limited" in h["messages"][-1]["text"]


def test_bad_input_is_refused(fake):
    with pytest.raises(ValueError):
        ask.stream("   ", PAGE)
    with pytest.raises(ValueError):
        ask.stream("x" * (ask.MAX_MESSAGE + 1), PAGE)
    with pytest.raises(ValueError):
        ask.history("nope")


def test_the_assistant_is_read_only_and_files_are_scoped_to_the_repo():
    tools = set(ask.TOOLS.split(","))
    assert not tools & {"Bash", "Edit", "Write", "NotebookEdit", "Task", "Agent"}
    # a bare "Grep"/"Glob" allow would search any path; the one Read rule scopes all three (tested live 2026-10-17)
    assert not {"Read", "Grep", "Glob"} & set(ask.ALLOWED)
    reads = [a for a in ask.ALLOWED if a.startswith("Read(")]
    assert reads == [f"Read(/{ask.REPO}/**)"] and ask.REPO.startswith("/")
    assert any("*.db" in d for d in ask.DENIED) and any("env" in d for d in ask.DENIED)


def test_the_doc_type_does_not_collide_with_another_org_document():
    """org.ask is the seats' questions to the CEO: the assistant writing there put chat lines in the inbox."""
    used = set()
    for p in [*ROOT.glob("*.py"), *ROOT.glob("alpha_mcp/*.py"), *ROOT.glob("cockpit*/*.py")]:
        if p.name != "ask.py":
            used |= set(re.findall(r'save_doc\(\s*\w+,\s*["\'](\w+)["\']', p.read_text()))
            used |= set(re.findall(r'["\']org\.(\w+)["\']', p.read_text()))
    assert "assistant" not in used
    assert 'save_doc(conn, "assistant"' in (ROOT / "ask.py").read_text()
