"""
The org (plan 0019, ADR 0057): Alpha Signal run as a fund with one human, the CEO,
and every other seat an agent.

ROLES is the one registry (like FACTORS / FEEDS / HOSTS). A role is a seat with a
mission, a deliverable, measures, a gate and a grader. Two kinds of agent seat:

  desk     runs unattended from cron. Its work is a task kind on the llm_tasks queue
           (alpha_mcp/org_kinds.py): the deterministic side builds a facts brief, a
           local `claude -p` worker running AS that role reads it (plus the read-only
           alpha-research / alpha-ops MCP tools), and alpha-work.submit validates the
           memo server-side and stores it. No shell, no file access, no other write.
  builder  changes code. Spawned by a human-led Claude Code session as a subagent
           (.claude/agents/<role>.md) in a worktree; its gate is the tests and the
           CEO's merge.

    python -m org roster                     # the org chart
    python -m org run                        # cron: every desk role due today, in order
    python -m org run --role cio --adhoc     # run one role now (keeps its scheduled period free)
    python -m org inbox                      # what is waiting for the CEO
    python -m org decide 123 approve --note "go"
    python -m org board --send               # (re)send the latest board pack

Storage: memos are rows of the v3 `documents` table (source='org', doc types
org.*). A memo's asks and hypotheses are child documents; a CEO decision is a
child `org.decision`. Nothing here can change weights, config, cron or code.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import db
from db import get_db

ROOT = Path(__file__).resolve().parent
CHARTERS = ROOT / ".claude" / "routines" / "roles"
WORKER_PROMPT = ROOT / ".claude" / "routines" / "org-worker.md"
LOG = ROOT / "output" / "org_worker.log"
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "/home/ubuntu/.local/bin/claude")
# Where the Boardroom is served over HTTPS (nginx site ops/nginx/alpha-ops.conf): links in the
# board-pack email and the page a push notification opens. One place to change the address.
BOARDROOM_URL = os.environ.get("ALPHA_BOARDROOM_URL", "https://alpha.rendezvous-app.duckdns.org/org")
PYTHON = "/home/ubuntu/alpha-signal/venv/bin/python"

# ═══════════════════════════ the registry ═══════════════════════════
# type: human | desk | builder.   cadence (desk): daily | weekly:<mon..sun>.
# graded_by: who scores this role's output. Never the role itself, never its own
# reporting line (the doer and the grader are separate seats).
# A desk role's charter is .claude/routines/roles/<id>.md; a builder's (and the
# data engineer's fix mode) is .claude/agents/<id>.md.

ROLES = {
    "ceo": {
        "title": "CEO", "type": "human", "reports_to": None, "who": "Amit",
        "mission": "Capital, strategy and every gate: weights, production defaults, paid data, merges, orders.",
        "deliverable": "Decisions on the inbox (approve / reject / park).",
        "measures": ["hours per week spent on the fund", "net-of-cost return vs the honest expected return"],
        "gate": "none",
    },
    "chief-of-staff": {
        "title": "Chief of Staff", "type": "desk", "reports_to": "ceo",
        "cadence": "weekly:sun", "model": "sonnet", "kinds": ["org_board_pack"],
        "mission": "Turn a week of desk memos into one page the CEO can act on.",
        "deliverable": "Weekly board pack: state of the fund, the decisions that need the CEO, wins, worries.",
        "measures": ["CEO decisions taken per pack", "nothing material missing from the pack"],
        "gate": "Reports only. Recommends on existing asks; raises none of its own.",
        "graded_by": "ceo",
    },
    "cio": {
        "title": "Chief Investment Officer", "type": "desk", "reports_to": "ceo",
        "cadence": "weekly:sun", "model": "opus", "effort": "high", "web": True,
        "kinds": ["org_cio_review", "org_cio_outlook"],
        "mission": "Own the model's honesty and the house view: which factors earn their weight, where the market is "
                   "going, which sectors to pursue, which of the desk's ideas deserve conviction.",
        "deliverable": "Weekly: (1) investment review: a call on every wired factor, triage of hypothesis cards, asks; "
                       "(2) market outlook: macro, market stance, what to be careful about, sectors to pursue, and a "
                       "second-pass review of the sector desk's ideas into a short conviction list.",
        "measures": ["wired factors surviving BY-FDR", "promotion hit rate at 6 months", "replicated t-stat disagreements = 0"],
        "gate": "Proposes only. A weight or production default changes only by CEO decision + a builder's merged PR.",
        "graded_by": "compliance",
    },
    "sector-desk": {
        "title": "Sector Desk", "type": "desk", "reports_to": "cio",
        "cadence": "weekly:sun", "model": "sonnet", "web": True, "kinds": ["org_sector_view"],
        "mission": "One specialist view per sector from policy, macro and model breadth, and the sector's best ideas.",
        "deliverable": "Weekly view per sector, up to three investment ideas with reasons (to the CIO), flags on "
                       "picks in the sector, hypothesis cards.",
        "measures": ["hypothesis cards that reach KEEP", "flag precision", "nothing feeds ranking"],
        "gate": "Narrative, ideas and hypotheses only. Ideas go to the CIO, then to the CEO as advice. Nothing here is a "
                "ranking input until a factor built from it passes the bar.",
        "graded_by": "compliance",
    },
    "quant-researcher": {
        "title": "Quant Researcher", "type": "builder", "reports_to": "cio",
        "mission": "Turn an approved hypothesis card into a factor, its PIT twin, a backtest and a verdict.",
        "deliverable": "One PR per card: compute function, FACTORS entry, backtest study, verdict (KEEP / WEAK / DROP).",
        "measures": ["cost per verdict", "verdicts compliance reproduces", "look-ahead findings = 0"],
        "gate": "Library only. Never adds `weights`; promotion is a CIO proposal + CEO decision.",
        "graded_by": "compliance",
    },
    "risk-officer": {
        "title": "Risk Officer", "type": "desk", "reports_to": "ceo",
        "cadence": "daily", "model": "sonnet", "kinds": ["org_risk_note"],
        "mission": "Independent daily read of the book: concentration, churn, regime, data trust.",
        "deliverable": "Daily book note: verdict (within-limits / watch / breach) and flags.",
        "measures": ["cap breaches flagged the day they occur", "turnover per day vs baseline", "false-alarm rate"],
        "gate": "Reports to the CEO, not the CIO. Flags only; cannot resize or halt anything.",
        "graded_by": "compliance",
    },
    "compliance": {
        "title": "Compliance", "type": "desk", "reports_to": "ceo",
        "cadence": "daily", "model": "opus", "kinds": ["org_grade"],
        "mission": "The independent grader: score every desk memo against the facts it was given.",
        "deliverable": "A grade per memo (grounded, actionable, in-charter, calibrated) with the issues found.",
        "measures": ["grades the CEO overturns", "memos graded within a day"],
        "gate": "Grades only. Cannot edit or suppress a memo.",
        "graded_by": "ceo",
    },
    "cto": {
        "title": "Chief Technology Officer", "type": "desk", "reports_to": "ceo",
        "cadence": "weekly:sun", "model": "sonnet", "kinds": ["org_cto_review"],
        "mission": "Keep the platform boring: rank the engineering backlog from a week of incidents.",
        "deliverable": "Weekly platform review: state, a ranked backlog with an owner per item, asks for the CEO.",
        "measures": ["CRITICAL days per month", "time from CRITICAL to fixed", "backlog items that recur"],
        "gate": "Ranks and assigns. Builders do the work in a worktree; the CEO merges.",
        "graded_by": "compliance",
    },
    "data-engineer": {
        "title": "Data Engineer", "type": "desk", "reports_to": "cto",
        "cadence": "daily", "model": "sonnet", "kinds": ["org_data_triage"], "agent": True,
        "mission": "On call for the data supply: diagnose every health issue each morning, fix on request.",
        "deliverable": "Daily triage: per issue a diagnosis, a proposed fix and an owner. Fix PRs when spawned as a builder.",
        "measures": ["issues diagnosed the day they appear", "diagnoses confirmed by the fix", "repeat incidents"],
        "gate": "Triage cannot rerun, fix or send anything. Fixes are builder work behind tests and a CEO merge.",
        "graded_by": "compliance",
    },
    "dq-auditor": {
        "title": "Data Quality Auditor", "type": "desk", "reports_to": "cto",
        "cadence": "weekly:sun", "model": "opus", "effort": "high", "kinds": ["org_dq_audit"],
        "mission": "Find data that is wrong while looking right: a column that holds something else, a value that "
                   "cannot be real, a weight whose proof is gone. Every week, before anyone else notices.",
        "deliverable": "Weekly audit: a call on every probe finding (real, does not reproduce, known), its own "
                       "findings each with the query that shows it, and the one fix that matters most.",
        "measures": ["calls that match a re-run of the finding's query", "findings it reported as real that did not reproduce = 0",
                     "new real findings per month", "planted faults the probes caught"],
        "gate": "Read-only. Every finding carries a query the server re-runs; a claim that does not reproduce is "
                "refused or scored against the seat. Fixes are builder work behind tests and a CEO merge.",
        "graded_by": "compliance",
    },
    "backend-engineer": {
        "title": "Backend Engineer", "type": "builder", "reports_to": "cto",
        "mission": "Pipeline, schema, registries, tests.",
        "deliverable": "A PR per backlog item with tests and a zero-behaviour-change note where it applies.",
        "measures": ["tests green on first review", "regressions traced to the change = 0"],
        "gate": "Worktree + tests + CEO merge. Never touches weights, cron or credentials.",
        "graded_by": "cto",
    },
    "frontend-engineer": {
        "title": "Frontend Engineer", "type": "builder", "reports_to": "cto",
        "mission": "Cockpit pages that show the data without re-querying it.",
        "deliverable": "A PR per page change that passes the design-review agent.",
        "measures": ["design-review findings per PR", "page error rate"],
        "gate": "Worktree + design-review pass + CEO merge.",
        "graded_by": "cto",
    },
    "system-architect": {
        "title": "System Architect", "type": "builder", "reports_to": "cto",
        "mission": "Guard the seven building blocks and five invariants; write the ADR before the code.",
        "deliverable": "An ADR + change-locality table for any structural change; a quarterly architecture review.",
        "measures": ["change scenarios touching ≤2 places", "invariant ratchets never loosened"],
        "gate": "Proposes. Production code changes only after the CEO approves the ADR.",
        "graded_by": "ceo",
    },
    "ai-scout": {
        "title": "AI & Tools Scout", "type": "desk", "reports_to": "ceo",
        "cadence": "weekly:sun", "model": "sonnet", "kinds": ["org_ai_scout"], "web": True,
        "mission": "Watch what is new in models, tools and data sources; own the LLM budget.",
        "deliverable": "Weekly brief: at most three recommendations, each with the gate that would prove it. Default: no change.",
        "measures": ["adopted recommendations with measured gain", "LLM usage trend", "ungated adoptions = 0"],
        "gate": "Recommends only. Every adoption needs a measured gate and a CEO decision.",
        "graded_by": "compliance",
    },
}

# Doers first, then the grader, then the pack that summarises both.
RUN_ORDER = ["data-engineer", "dq-auditor", "risk-officer", "sector-desk", "cio", "cto", "ai-scout", "compliance", "chief-of-staff"]
DOW = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
VERDICTS = ("approve", "reject", "park")


def desk_roles():
    return [r for r in RUN_ORDER if ROLES[r]["type"] == "desk"]


def builder_roles():
    return [r for r, s in ROLES.items() if s["type"] == "builder" or s.get("agent")]


def charter(role):
    return (CHARTERS / f"{role}.md").read_text()


HOUSE_STYLE = CHARTERS.parent / "house-style.md"


def house_style():
    """The writing style every seat follows (memos and chat). One file, editable from the Boardroom."""
    return HOUSE_STYLE.read_text()


def save_house_style(text, note=None):
    """The CEO's edit to the house style. The file is the truth; each save keeps the text as history."""
    if not isinstance(text, str) or not text.strip() or len(text) > 8000:
        raise ValueError("the house style must be non-empty text of at most 8000 characters")
    factory = (_all_settings().get("_house") or {}).get("factory") or house_style()
    _write(HOUSE_STYLE, text.strip() + "\n")
    with get_db() as conn:
        save_doc(conn, "settings", "_house", "house style",
                 {"role": "_house", "text": house_style(), "factory": factory, "note": (note or "")[:300],
                  "changed": ["house_style"], "saved_at": _now()})
    _settings_cache["v"] = None
    return house_style_view()


def house_style_view():
    cur = _all_settings().get("_house") or {}
    return {"text": house_style(), "edited": bool(cur) and cur.get("factory", "").strip() != house_style().strip(),
            "default": cur.get("factory") or house_style(),
            "fixed": "Checked by the server, whatever this text says: no trade jargon, no code names and no long "
                     "sentences in the plain-words block, the headline and everything addressed to you."}


def is_due(role, day):
    s = seat(role)
    cad = s.get("cadence")
    if not cad or not s.get("enabled", True):
        return False
    if cad == "daily":
        return True
    kind, _, arg = cad.partition(":")
    return kind == "weekly" and DOW[day.weekday()] == arg


def period_key(role, day):
    """The period a scheduled run covers: the date (daily) or the ISO week (weekly)."""
    if seat(role)["cadence"] == "daily":
        return day.isoformat()
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


# ═══════════════════════════ seat settings (what the CEO may change) ═══════════════════════════
# The CEO tunes a seat from the Boardroom: its variables and its prompt. What a seat
# may NOT do stays in code: its kinds, its gate, the validator, the write path.
#   variables → a `documents` row (type org.settings, key = role), newest valid wins
#   prompts   → the files themselves (.claude/routines/roles/<id>.md for a desk seat,
#               the body of .claude/agents/<id>.md for a builder), so git shows the edit;
#               every save keeps the text in the settings row, which is the history.

AGENTS = ROOT / ".claude" / "agents"
MODELS = ("sonnet", "opus", "haiku")
EFFORTS = ("", "low", "medium", "high", "xhigh")
CADENCES = ("daily",) + tuple(f"weekly:{d}" for d in DOW)
DESK_VARS = ("enabled", "cadence", "model", "effort", "web", "max_submits", "directive")
BUILDER_VARS = ("model",)
VAR_DEFAULTS = {"enabled": True, "effort": "", "web": False, "max_submits": 30, "directive": ""}
MAX_PROMPT, MAX_DIRECTIVE = 20000, 1500
_settings_cache = {"t": 0.0, "v": None}


def _all_settings():
    """{role: newest valid settings fields}. Cached for a few seconds per process."""
    import time
    c = _settings_cache
    if c["v"] is None or time.monotonic() - c["t"] > 5:
        try:
            v = {}
            for d in docs(["settings"], days=None, limit=500):
                v.setdefault(d["key"], d["fields"])
        except Exception as e:                              # a DB without the v3 tables
            if "no such table" not in str(e):
                raise
            v = {}
        c["v"], c["t"] = v, time.monotonic()
    return c["v"]


def seat(role):
    """The seat as it runs: its ROLES entry with the CEO's variable overrides applied.
    A builder's model is the one in its agent file (Claude Code reads it there)."""
    base = ROLES[role]
    if base["type"] == "builder":
        return {**base, "model": _agent_model(role)}
    if base["type"] != "desk":
        return dict(base)
    ov = (_all_settings().get(role) or {}).get("vars") or {}
    return {**VAR_DEFAULTS, **base, **{k: v for k, v in ov.items() if k in DESK_VARS}}


def _agent_parts(role):
    """(frontmatter incl. both --- lines, body) of a builder's agent file."""
    text = (AGENTS / f"{role}.md").read_text()
    if text.startswith("---\n") and "\n---\n" in text[4:]:
        head, body = text[4:].split("\n---\n", 1)
        return f"---\n{head}\n---\n", body.lstrip("\n")
    return "", text


def _agent_model(role):
    import re
    m = re.search(r"^model: *(\S+)", _agent_parts(role)[0], re.M)
    return m.group(1) if m else None


def prompts(role):
    """The seat's editable prompts: {"prompt": desk charter, "agent_prompt": builder file body}."""
    s, out = ROLES[role], {}
    if s["type"] == "desk":
        out["prompt"] = charter(role)
    if s["type"] == "builder" or s.get("agent"):
        out["agent_prompt"] = _agent_parts(role)[1]
    return out


def prompt_version(role):
    """Short hash of what steers the seat (prompts + directive + model): stamped on every
    memo so grades can be compared across versions of a seat."""
    s = seat(role)
    blob = json.dumps([prompts(role), s.get("directive"), s.get("model"), house_style()], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:8]


def _write(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _check_var(key, v):
    if key in ("enabled", "web"):
        if not isinstance(v, bool):
            raise ValueError(f"{key} must be true or false")
    elif key == "model":
        if v not in MODELS:
            raise ValueError(f"model must be one of {MODELS}")
    elif key == "effort":
        if v not in EFFORTS:
            raise ValueError(f"effort must be one of {EFFORTS[1:]} or empty for the default")
    elif key == "cadence":
        if v not in CADENCES:
            raise ValueError(f"cadence must be one of {CADENCES}")
    elif key == "max_submits":
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 60:
            raise ValueError("max_submits must be an integer 1..60")
    elif key == "directive":
        if not isinstance(v, str) or len(v) > MAX_DIRECTIVE:
            raise ValueError(f"directive must be text of at most {MAX_DIRECTIVE} characters")
    return v


def _var_names(role):
    t = ROLES[role]["type"]
    return DESK_VARS if t == "desk" else BUILDER_VARS if t == "builder" else ()


def _state(role):
    """What a saved version records and what reset restores: variables + prompts."""
    s = seat(role)
    return {"vars": {k: s.get(k) for k in _var_names(role)}, "prompts": prompts(role)}


def save_settings(role, changes, note=None):
    """Apply the CEO's changes to one seat: variables (validated against closed lists) and
    prompts (written to the seat's files). Returns the seat's settings view. Nothing here
    can widen what a seat is allowed to do: kinds, gate, validator and write path are code."""
    import re
    if role not in ROLES or ROLES[role]["type"] == "human":
        raise ValueError(f"{role!r} is not an agent seat")
    base, names = ROLES[role], _var_names(role)
    prev = _all_settings().get(role) or {}
    factory = prev.get("factory") or _state(role)           # the seat before its first edit
    ov = dict(prev.get("vars") or {}) if base["type"] == "desk" else {}
    current, new_prompts, new_model = prompts(role), {}, None
    for k, v in (changes or {}).items():
        if k in ("prompt", "agent_prompt"):
            if k not in current:
                raise ValueError(f"{role} has no {k}")
            if not isinstance(v, str) or not v.strip() or len(v) > MAX_PROMPT:
                raise ValueError(f"{k} must be non-empty text of at most {MAX_PROMPT} characters")
            if v.strip() != current[k].strip():
                new_prompts[k] = v.strip() + "\n"
        elif k not in names:
            raise ValueError(f"{k!r} is not a setting of this seat; editable: {names + tuple(current)}")
        elif base["type"] == "builder":                     # a builder's model lives in its agent file
            new_model = _check_var(k, v)
        elif _check_var(k, v) == {**VAR_DEFAULTS, **base}.get(k):
            ov.pop(k, None)                                 # the registry value again: not an override
        else:
            ov[k] = v
    if "prompt" in new_prompts:
        _write(CHARTERS / f"{role}.md", new_prompts["prompt"])
    if "agent_prompt" in new_prompts or new_model:
        head, body = _agent_parts(role)
        if new_model:
            head = re.sub(r"^model: *\S+", f"model: {new_model}", head, flags=re.M)
        _write(AGENTS / f"{role}.md", f"{head}\n{new_prompts.get('agent_prompt', body)}")
    with get_db() as conn:
        save_doc(conn, "settings", role, f"{role} settings",
                 {"role": role, "vars": ov if base["type"] == "desk" else {"model": _agent_model(role)},
                  "prompts": prompts(role), "factory": factory, "changed": sorted(changes or {}),
                  "note": (note or "")[:300], "saved_at": _now()})
    _settings_cache["v"] = None
    return seat_settings(role)


def reset_settings(role):
    """Back to the registry's variables and the prompts as they were before the first edit."""
    factory = (_all_settings().get(role) or {}).get("factory")
    if not factory:
        return seat_settings(role)
    return save_settings(role, {**factory["vars"], **factory["prompts"]}, note="reset to default")


def restore_settings(role, doc_id):
    """Re-apply an earlier saved version (its variables and prompts) as a new save."""
    d = doc(doc_id)
    if not d or d["type"] != "settings" or d["key"] != role:
        raise ValueError(f"{doc_id} is not a saved version of {role}")
    f = d["fields"]
    if ROLES[role]["type"] == "desk":
        base = {**VAR_DEFAULTS, **ROLES[role]}
        variables = {k: (f.get("vars") or {}).get(k, base[k]) for k in DESK_VARS}
    else:
        variables = {k: v for k, v in (f.get("vars") or {}).items() if k in BUILDER_VARS and v}
    return save_settings(role, {**variables, **(f.get("prompts") or {})}, note=f"restored version {doc_id}")


def _edited(role, cur=None):
    """Which of the seat's settings differ from how it started: variable names and prompt names."""
    cur = cur if cur is not None else (_all_settings().get(role) or {})
    factory = cur.get("factory")
    if not factory:
        return []
    now = _state(role)
    return sorted([k for k, v in now["vars"].items() if v != factory["vars"].get(k)]
                  + [k for k, v in now["prompts"].items() if v.strip() != (factory["prompts"].get(k) or "").strip()])


def seat_settings(role):
    """Everything the Boardroom's seat editor shows: the effective variables, what was
    changed, the choices, the prompts, the history, and what is fixed in code."""
    base = ROLES[role]
    cur = _all_settings().get(role) or {}
    state = _state(role) if base["type"] != "human" else {"vars": {}, "prompts": {}}
    hist = [{"doc_id": d["doc_id"], "saved_at": d["fields"].get("saved_at"), "changed": d["fields"].get("changed"),
             "note": d["fields"].get("note"), "current": d["status"] == "valid"}
            for d in docs(["settings"], days=None, status=None, limit=500) if d["key"] == role][:12]
    return {"role": role, "title": base["title"], "type": base["type"], "vars": state["vars"],
            "prompts": state["prompts"], "edited": _edited(role, cur),
            "defaults": (cur.get("factory") or state)["vars"],
            "choices": {"model": MODELS, "effort": EFFORTS, "cadence": CADENCES},
            "limits": {"prompt": MAX_PROMPT, "directive": MAX_DIRECTIVE},
            "fixed": {"gate": base.get("gate"), "kinds": base.get("kinds"), "graded_by": base.get("graded_by"),
                      "note": "Fixed in code, not editable here: what the seat may write, the memo schema, the "
                              "number / id / link / evidence checks, and the rules appended to every prompt."},
            "version": prompt_version(role) if base["type"] != "human" else None, "history": hist}


# ═══════════════════════════ documents (the memo store) ═══════════════════════════

def _now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _type_id(conn, name):
    conn.execute("INSERT OR IGNORE INTO catalog (kind, name, first_seen) VALUES ('doc_type', ?, ?)",
                 (name, _now()[:10]))
    return conn.execute("SELECT catalog_id FROM catalog WHERE kind = 'doc_type' AND name = ?", (name,)).fetchone()[0]


def _org_types():
    """{catalog_id: short type name} for every org.* doc type (documents is large:
    every read filters by type_id, which its unique index leads with)."""
    return {r["catalog_id"]: r["name"][4:] for r in db.rows(
        "SELECT catalog_id, name FROM catalog WHERE kind = 'doc_type' AND name LIKE 'org.%'")}


def save_doc(conn, doc_type, key, title, fields, model=None, parent=None, doc_date=None):
    """Insert one org document and supersede the earlier valid version of the same key.
    Returns (doc_id, [superseded doc_ids])."""
    tid = _type_id(conn, f"org.{doc_type}")
    fj = json.dumps(fields, sort_keys=True, ensure_ascii=False, default=str)
    h = hashlib.sha1(fj.encode()).hexdigest()
    now = _now()
    old = [r[0] for r in conn.execute(
        "SELECT doc_id FROM documents WHERE type_id = ? AND source = 'org' AND source_key = ? AND status = 'valid'",
        (tid, key))]
    cur = conn.execute(
        "INSERT OR IGNORE INTO documents (type_id, parent_doc_id, doc_date, available_at, source, source_key, "
        "model, title, fields, content_hash, status, created_at) VALUES (?, ?, ?, ?, 'org', ?, ?, ?, ?, ?, 'valid', ?)",
        (tid, parent, doc_date or now[:10], now, key, model, (title or "")[:300], fj, h, now))
    if cur.rowcount:
        doc_id = cur.lastrowid
    else:                                   # identical content saved before: revive that row
        doc_id = conn.execute("SELECT doc_id FROM documents WHERE type_id = ? AND source = 'org' AND source_key = ? "
                              "AND content_hash = ?", (tid, key, h)).fetchone()[0]
        conn.execute("UPDATE documents SET status = 'valid' WHERE doc_id = ?", (doc_id,))
    superseded = [d for d in old if d != doc_id]
    if superseded:
        conn.execute(f"UPDATE documents SET status = 'superseded' WHERE doc_id IN ({','.join('?' * len(superseded))})",
                     superseded)
    return doc_id, superseded


def docs(types=None, days=30, role=None, parent=None, status="valid", limit=300, since=None, until=None):
    """Org documents, newest first: [{doc_id, type, parent_doc_id, doc_date, key, title, fields, ...}].
    since / until: ISO dates (inclusive); when either is given they replace `days`."""
    tmap = _org_types()
    ids = [i for i, n in tmap.items() if not types or n in types]
    if not ids:
        return []
    where, params = [f"type_id IN ({','.join('?' * len(ids))})", "source = 'org'"], list(ids)
    if status:
        where.append("status = ?")
        params.append(status)
    if since or until:
        if since:
            where.append("substr(doc_date, 1, 10) >= ?")
            params.append(str(since)[:10])
        if until:
            where.append("substr(doc_date, 1, 10) <= ?")
            params.append(str(until)[:10])
    elif days:
        where.append("doc_date >= date('now', ?)")
        params.append(f"-{int(days)} days")
    if parent is not None:
        where.append("parent_doc_id = ?")
        params.append(parent)
    out = []
    for r in db.rows("SELECT doc_id, type_id, parent_doc_id, doc_date, source_key, title, fields, model, status, "
                     f"created_at FROM documents WHERE {' AND '.join(where)} ORDER BY doc_id DESC LIMIT ?",
                     params + [int(limit)]):
        f = json.loads(r.pop("fields") or "{}")
        if role and f.get("role") != role:
            continue
        typ, key = tmap[r.pop("type_id")], r.pop("source_key")
        out.append({**r, "type": typ, "key": key, "fields": f})
    return out


def doc(doc_id):
    tmap = _org_types()
    r = db.one("SELECT doc_id, type_id, parent_doc_id, doc_date, source_key, title, fields, model, status, created_at "
               "FROM documents WHERE doc_id = ? AND source = 'org'", [int(doc_id)])
    if not r or r["type_id"] not in tmap:
        return None
    typ, key, fields = tmap[r.pop("type_id")], r.pop("source_key"), json.loads(r.pop("fields") or "{}")
    return {**r, "type": typ, "key": key, "fields": fields}


ITEM_TYPES = ("ask", "hypothesis", "work_order")
WORK_STATUSES = ("in_progress", "done", "blocked", "cancelled")


def _via_cio(d):
    """A hypothesis card from a seat that reports to the CIO goes to the CIO first."""
    return d["type"] == "hypothesis" and ROLES.get(d["fields"].get("role"), {}).get("reports_to") == "cio"


def card_queue(days=90):
    """Hypothesis cards from the CIO's reports that the CIO has not triaged yet, oldest first."""
    triaged = {t["parent_doc_id"] for t in docs(["triage"], days=days)}
    return sorted((d for d in docs(["hypothesis"], days=days) if _via_cio(d) and d["doc_id"] not in triaged),
                  key=lambda d: d["doc_id"])


def idea_queue(days=30):
    """The sector desk's investment ideas the CIO has not reviewed yet, oldest first."""
    reviewed = {t["parent_doc_id"] for t in docs(["triage"], days=days)}
    return sorted((d for d in docs(["idea"], days=days) if d["doc_id"] not in reviewed), key=lambda d: d["doc_id"])


def ideas(days=21):
    """Ideas after the CIO's second pass: {"conviction": [...], "watchlist": [...], "rejected": [...],
    "pending": [...]}. Each = the desk's idea + the CIO's call and reason + the model's own numbers
    for the stock (taken from the ranking when the idea was stored, never from the model's text)."""
    review = {t["parent_doc_id"]: t["fields"] for t in docs(["triage"], days=days + 14)}
    out = {"conviction": [], "watchlist": [], "rejected": [], "pending": []}
    for d in docs(["idea"], days=days):
        r = review.get(d["doc_id"])
        f = d["fields"]
        item = {"doc_id": d["doc_id"], "date": d["doc_date"], "ticker": f.get("ticker"), "sector": f.get("sector"),
                "stance": f.get("stance"), "reason": f.get("reason"), "catalyst": f.get("catalyst"),
                "risk": f.get("risk"), "horizon": f.get("horizon"), "desk_conviction": f.get("conviction"),
                "model": f.get("model"), "cio_call": (r or {}).get("call"), "cio_why": (r or {}).get("why")}
        bucket = {"conviction": "conviction", "watchlist": "watchlist", "reject": "rejected"}.get((r or {}).get("call"),
                                                                                              "pending")
        out[bucket].append(item)
    return out


def inbox(days=90):
    """What waits for the CEO (urgent first, then asks, then cards, oldest first): every ask, every hypothesis card from a seat
    that reports to the CEO, and cards from the CIO's reports that the CIO forwarded."""
    decided = {d["parent_doc_id"] for d in docs(["decision"], days=days)}
    forwarded = {t["parent_doc_id"] for t in docs(["triage"], days=days) if t["fields"].get("call") == "forward"}
    items = [d for d in docs(list(ITEM_TYPES), days=days)
             if d["doc_id"] not in decided and (not _via_cio(d) or d["doc_id"] in forwarded)]
    today = dt.date.today()
    for d in items:
        d["age_days"] = (today - dt.date.fromisoformat(d["doc_date"][:10])).days
    order = {"work_order": 0, "ask": 1, "hypothesis": 2}
    return sorted(items, key=lambda d: (d["fields"].get("urgency") != "now", order.get(d["type"], 3), d["doc_id"]))


# ═══════════════════════════ work orders (chat → inbox → a Claude Code session) ═══════════════════════════
# A work order is the list of fixes the CEO and a seat agreed in chat, written down by the
# seat (org_chat.make_work_order). It waits in the inbox for approval; a human-led Claude
# Code session then runs it (`/work-order N`), starting the owning builder seats in a
# worktree, and reports progress back here. Nothing runs a work order on its own.

def work_orders(days=180):
    """Every work order, newest first, with its status: awaiting approval → approved /
    rejected / parked (the CEO's decision) → in_progress / blocked / done / cancelled."""
    decided = {d["parent_doc_id"]: d["fields"] for d in docs(["decision"], days=days)}
    progress = {d["parent_doc_id"]: d["fields"] for d in docs(["progress"], days=days)}
    out = []
    for d in docs(["work_order"], days=days):
        f, dec, prog = d["fields"], decided.get(d["doc_id"]), progress.get(d["doc_id"])
        status = (prog or {}).get("status") or {"approve": "approved", "reject": "rejected", "park": "parked"}.get(
            (dec or {}).get("verdict"), "awaiting approval")
        out.append({"number": f.get("number"), "doc_id": d["doc_id"], "date": d["doc_date"], "title": d["title"],
                    "role": f.get("role"), "conv": f.get("conv"), "summary": f.get("summary"),
                    "items": f.get("items") or [], "open_questions": f.get("open_questions") or [],
                    "status": status, "note": (prog or {}).get("note"),
                    "updated": (prog or {}).get("at") or (dec or {}).get("decided_at")})
    return out


def work_order(number):
    return next((w for w in work_orders() if w["number"] == int(number)), None)


def save_work_order(role, conv, wo):
    """Store a work order written by `role` in chat conversation `conv`; returns its number."""
    with get_db() as conn:
        tid = _type_id(conn, "org.work_order")
        n = 1 + (conn.execute("SELECT COUNT(*) FROM documents WHERE source = 'org' AND type_id = ?",
                              (tid,)).fetchone()[0])
        save_doc(conn, "work_order", f"wo:{n}", wo["title"],
                 {**wo, "number": n, "role": role, "conv": conv, "created_at": _now()})
    return n


def work_status(number, status, note=None):
    """Progress on a work order, reported by the session that runs it."""
    if status not in WORK_STATUSES:
        raise ValueError(f"status must be one of {WORK_STATUSES}")
    w = work_order(number)
    if not w:
        raise ValueError(f"no work order {number}")
    if status != "cancelled" and w["status"] not in ("approved", "in_progress", "blocked"):
        raise ValueError(f"work order {number} is '{w['status']}': the CEO approves it in the Boardroom inbox first")
    with get_db() as conn:
        save_doc(conn, "progress", f"wo:{w['number']}", status,
                 {"status": status, "note": (note or "")[:1500], "at": _now()}, parent=w["doc_id"])
    return work_order(number)


def decide(item_id, verdict, note=None):
    """Record the CEO's decision on an ask or a hypothesis card (a child org.decision;
    deciding again supersedes the earlier decision)."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    item = doc(item_id)
    if not item or item["type"] not in ITEM_TYPES or item["status"] != "valid":
        raise ValueError(f"{item_id} is not an open ask or hypothesis")
    with get_db() as conn:
        did, _ = save_doc(conn, "decision", f"doc{item['doc_id']}", f"{verdict}: {item['title']}",
                          {"verdict": verdict, "note": (note or "")[:500], "decided_by": "ceo",
                           "item_type": item["type"], "item_title": item["title"],
                           "role": item["fields"].get("role"), "decided_at": _now()},
                          parent=item["doc_id"])
    return {"item_id": item["doc_id"], "verdict": verdict, "decision_doc_id": did}


# ═══════════════════════════ scorecard ═══════════════════════════

def scorecard(days=30):
    """Per desk role over `days`: tasks done / failed, first-pass rate (results accepted
    on the first claim), average compliance grade (0-8), MCP tool calls, fresh input and
    output tokens, last run. The numbers the quarterly budget review reads."""
    since = f"-{int(days)} days"
    kind_role = {k: r for r, s in ROLES.items() for k in s.get("kinds", [])}
    card = {r: {"done": 0, "failed": 0, "first_pass": None, "grade": None, "n_graded": 0, "tool_calls": 0,
                "tokens_in": 0, "tokens_out": 0, "last_done": None} for r in desk_roles()}
    try:
        for r in db.rows("SELECT kind, SUM(status = 'done') AS done, SUM(status = 'failed') AS failed, "
                         "SUM(status = 'done' AND attempts <= 1) AS clean, MAX(done_at) AS last_done "
                         "FROM llm_tasks WHERE kind LIKE 'org_%' AND created_at >= datetime('now', ?) GROUP BY kind",
                         [since]):
            c = card.get(kind_role.get(r["kind"]))
            if c is None:
                continue
            c["done"] += int(r["done"] or 0)
            c["failed"] += int(r["failed"] or 0)
            c["_clean"] = c.get("_clean", 0) + int(r["clean"] or 0)
            c["last_done"] = max(filter(None, [c["last_done"], r["last_done"]]), default=None)
        for r in db.rows("SELECT role, COUNT(*) AS n FROM mcp_calls WHERE ts >= datetime('now', ?) GROUP BY role",
                         [since]):
            if r["role"] in card:
                card[r["role"]]["tool_calls"] = int(r["n"])
        for r in db.rows("SELECT step, SUM(input_tokens) AS i, SUM(output_tokens) AS o FROM llm_usage "
                         "WHERE step LIKE 'org:%' AND called_at >= datetime('now', ?) GROUP BY step", [since]):
            c = card.get(r["step"][4:])
            if c is not None:
                c["tokens_in"], c["tokens_out"] = int(r["i"] or 0), int(r["o"] or 0)
    except Exception as e:                                  # a fresh DB without the queue tables
        if "no such table" not in str(e):
            raise
    grades = {}
    for g in docs(["grade"], days=days):
        grades.setdefault(g["fields"].get("graded_role"), []).append(g["fields"].get("total") or 0)
    audits = [d["fields"].get("score") for d in docs(["dq_audit"], days=days) if d["fields"].get("score")]
    if audits and "dq-auditor" in card:      # how often its calls matched a re-run of the query
        card["dq-auditor"]["audit"] = {
            "audits": len(audits), "checked": sum(a["checked"] for a in audits), "right": sum(a["right"] for a in audits),
            "claimed_real_but_not": sum(len(a["claimed_real_but_not"]) for a in audits),
            "dismissed_but_real": sum(len(a["dismissed_but_real"]) for a in audits),
            "new_real": sum(a["new_real"] for a in audits), "own_confirmed": sum(a["own_confirmed"] for a in audits)}
    for r, c in card.items():
        clean = c.pop("_clean", 0)
        c["first_pass"] = round(clean / c["done"], 2) if c["done"] else None
        if grades.get(r):
            c["grade"], c["n_graded"] = round(sum(grades[r]) / len(grades[r]), 1), len(grades[r])
    return card


MEMO_TYPES = sorted({k[4:] for s in ROLES.values() for k in s.get("kinds", [])} - {"grade"})


def memos(since=None, until=None, role=None, limit=150):
    """Desk memos in a date range (ISO dates, inclusive), newest first, each with its compliance grade.
    What the Boardroom's date filter shows; no dates = the last 14 days."""
    ms = docs(MEMO_TYPES, days=None if (since or until) else 14, since=since, until=until, role=role or None,
              limit=5000)[:int(limit)]
    grades = {g["parent_doc_id"]: g["fields"] for g in docs(["grade"], days=None, limit=20000)} if ms else {}
    for m in ms:
        g = grades.get(m["doc_id"])
        m["grade"] = {"total": g.get("total"), "verdict": g.get("verdict"), "issues": g.get("issues")} if g else None
    return ms


def overview(days=14):
    """Everything the Boardroom page and the alpha-ops `org` tool show."""
    card = scorecard()
    memo_types = sorted({k[4:] for s in ROLES.values() for k in s.get("kinds", [])} - {"grade"})
    memos = docs(memo_types, days=days, limit=200)
    grade_of = {g["parent_doc_id"]: g["fields"] for g in docs(["grade"], days=days + 7)}
    for m in memos:
        g = grade_of.get(m["doc_id"])
        m["grade"] = {"total": g.get("total"), "verdict": g.get("verdict"), "issues": g.get("issues")} if g else None
    latest = {}
    for m in memos:
        latest.setdefault(m["fields"].get("role"), m)
    roles = []
    settings = _all_settings()
    for rid in ROLES:
        m, s = latest.get(rid), seat(rid)
        roles.append({"id": rid, **{k: s.get(k) for k in ("title", "type", "reports_to", "cadence", "model",
                                                             "mission", "deliverable", "measures", "gate",
                                                             "graded_by", "who", "effort", "web", "directive")},
                      "enabled": s.get("enabled", True) if s["type"] == "desk" else None,
                      "edited": _edited(rid, settings.get(rid) or {}) if s["type"] != "human" else [],
                      "score": card.get(rid),
                      "latest": {"doc_id": m["doc_id"], "date": m["doc_date"], "headline": m["title"]} if m else None})
    board = next((m for m in memos if m["type"] == "board_pack"), None)
    return {"as_of": _now(), "roles": roles, "inbox": inbox(), "board_pack": board,
            "outlook": next((m for m in memos if m["type"] == "cio_outlook"), None), "ideas": ideas(),
            "work_orders": work_orders(),
            "subscription": next(iter(d["fields"] for d in docs(["subscription"], days=3, limit=1)), None),
            "cio_queue": [{"doc_id": c["doc_id"], "title": c["title"], "role": c["fields"].get("role")}
                          for c in card_queue()],
            "memos": [m for m in memos if m["type"] != "board_pack"],
            "decisions": docs(["decision"], days=days)}


# ═══════════════════════════ running a desk role ═══════════════════════════

def enqueue_role(role, day=None, adhoc=False, kinds=None):
    """Build the role's briefs for the period and queue them. A scheduled period is
    queued once; --adhoc adds a run keyed by the clock, which leaves the period free."""
    from alpha_mcp import org_kinds, tasks
    day = day or dt.date.today()
    key = f"adhoc-{dt.datetime.now():%Y%m%dT%H%M}" if adhoc else period_key(role, day)
    queued = 0
    for kind in ROLES[role]["kinds"]:
        if kinds and kind not in kinds:
            continue
        if not adhoc and kind != "org_grade" and db.scalar(
                "SELECT COUNT(*) FROM llm_tasks WHERE kind = ? AND (item_key = ? OR item_key LIKE ?) "
                "AND status != 'failed'", [kind, key, key + ":%"], default=0):
            continue                                        # this period is already queued or done
        items = org_kinds.build(kind, day, key)
        if items:
            queued += tasks.enqueue(kind, items=items)["queued"]
    return queued


def _mcp_config(role):
    env = {"PYTHONPATH": str(ROOT), "ALPHA_MCP_ROLE": role, "ALPHA_MCP_MODE": "local"}
    if os.environ.get("ALPHA_DB"):
        env["ALPHA_DB"] = os.environ["ALPHA_DB"]
    servers = {f"alpha-{p}": {"type": "stdio", "command": PYTHON, "args": ["-m", f"alpha_mcp.{p}"], "env": env}
               for p in ("research", "ops", "work")}
    return json.dumps({"mcpServers": servers})


def run_role(role, max_batches=None, timeout_min=25):
    """One `claude -p` run AS `role` on the Claude subscription: it sees only its own
    task kinds, reads through alpha-research / alpha-ops, and writes only through
    alpha-work.submit. Returns {"ran", "before", "after", "rc", "error"}."""
    from alpha_mcp import tasks
    spec = seat(role)
    max_batches = max_batches or spec.get("max_submits") or 30
    before = tasks.claimable_count(spec["kinds"])
    if not before:
        return {"role": role, "ran": False, "before": 0, "after": 0}
    prompt = (f"{WORKER_PROMPT.read_text()}\n\nYou hold the seat: {spec['title']} (role id `{role}`).\n"
              f"Mission: {spec['mission']}\nRun budget: at most {max_batches} submit calls, then stop and "
              "give the final answer.")
    tools = "WebSearch,WebFetch" if spec.get("web") else ""
    allowed = ["mcp__alpha-work__*", "mcp__alpha-research__*", "mcp__alpha-ops__*"] + (tools.split(",") if tools else [])
    with tempfile.NamedTemporaryFile("w", suffix=".json", prefix=f"org_mcp_{role}_", delete=False) as f:
        f.write(_mcp_config(role))
        cfg = f.name
    cmd = [CLAUDE_BIN, "-p", prompt, "--model", spec.get("model", "sonnet"), "--mcp-config", cfg,
           "--strict-mcp-config", "--tools", tools, "--allowedTools", *allowed,
           "--permission-mode", "dontAsk", "--no-session-persistence", "--output-format", "stream-json", "--verbose"]
    if spec.get("effort"):
        cmd += ["--effort", spec["effort"]]
    # Subscription login only: with ANTHROPIC_API_KEY set the CLI would bill the API (HANDOFF 2026-10-02).
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    out, rc, err = {}, 1, None
    try:
        p = subprocess.run(cmd, env=env, cwd=ROOT, capture_output=True, text=True, timeout=timeout_min * 60)
        rc = p.returncode
        for line in p.stdout.splitlines():                  # one JSON event per line; the last `result` is the run
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "result":
                out = ev
            elif ev.get("type") == "rate_limit_event":
                note_subscription(ev.get("rate_limit_info"))
        if not out:
            err = (p.stderr or p.stdout or "no output")[-400:]
    except subprocess.TimeoutExpired:
        err = f"timeout after {timeout_min} min"
    finally:
        os.unlink(cfg)
    if out.get("is_error"):
        err = str(out.get("result"))[:400]
    after = tasks.claimable_count(spec["kinds"])
    u = out.get("usage") or {}
    mu = out.get("modelUsage") or {}                       # the CLI also bills small helper calls: take the main model
    model = max(mu, key=lambda m: mu[m].get("outputTokens") or 0) if mu else spec.get("model", "sonnet")
    if u:
        db.log_llm_usage(f"org:{role}", f"subscription/{model}",
                         {"input_tokens": (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0),
                          "output_tokens": u.get("output_tokens") or 0}, mode="local", n_calls=0)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps({"ts": _now(), "role": role, "model": model, "rc": rc, "claimable": [before, after],
                            "ms": out.get("duration_ms"), "turns": out.get("num_turns"), "error": err,
                            "cost_equiv_usd": out.get("total_cost_usd"),
                            "result": str(out.get("result"))[:600]}) + "\n")
    return {"role": role, "ran": True, "before": before, "after": after, "rc": rc, "error": err}


def note_subscription(info):
    """Remember the Claude subscription's usage windows as the CLI last reported them
    (share of the rolling 5-hour and 7-day allowance used). This is the org's real budget:
    there is no per-token bill, only these two meters, shared with every other Claude use."""
    w = (info or {}).get("unifiedWindows") or {}
    if not w:
        return
    fields = {"status": info.get("status"), "at": _now(),
              **{k: {"used_pct": round(100 * (v.get("utilization") or 0)),
                     "resets_at": dt.datetime.utcfromtimestamp(v["resetsAt"]).isoformat(timespec="minutes")
                     if v.get("resetsAt") else None} for k, v in w.items()}}
    try:
        with get_db() as conn:
            save_doc(conn, "subscription", "latest", info.get("status"), fields)
    except Exception:                                       # telemetry only
        pass


def run(day=None, roles=None, adhoc=False, deliver=True, kinds=None, drain=False):
    """Every desk role due on `day` (or the named roles), in RUN_ORDER: queue its briefs,
    run its worker, twice at most while it makes progress. A role that had work and did
    none fails the run (CLAUDE.md: a producer with zero output is a failure)."""
    day = day or dt.date.today()
    todo = [r for r in RUN_ORDER if (r in roles if roles else is_due(r, day))]
    report, failed = [], []
    for role in todo:
        try:
            queued = 0 if drain else enqueue_role(role, day, adhoc=adhoc, kinds=kinds)
        except Exception as e:                              # one role's brief must not stop the others
            report.append({"role": role, "error": f"enqueue: {type(e).__name__}: {e}"})
            failed.append(role)
            continue
        r = run_role(role)
        first, runs = r["before"], 1
        while r["ran"] and r["after"] and r["after"] < r["before"] and runs < 12:     # again while it makes progress
            r = run_role(role)
            runs += 1
        r = {**r, "before": first, "runs": runs}
        r["queued"] = queued
        report.append(r)
        if r["ran"] and r["after"] >= first:
            failed.append(role)
    delivered = deliver_all(day) if deliver else {}
    return {"day": day.isoformat(), "roles": report, "failed": failed, "delivered": delivered}


# ═══════════════════════════ delivery ═══════════════════════════
# Pull by default (Boardroom page, alpha-ops `org` tool), push by exception (an ask
# marked urgency=now), one email a week (the board pack).

def _sent(conn, doc_id):
    """Mark a document delivered exactly once (a child org.delivery)."""
    if conn.execute("SELECT 1 FROM documents WHERE parent_doc_id = ? AND source = 'org' AND source_key = ?",
                    (doc_id, f"sent{doc_id}")).fetchone():
        return False
    save_doc(conn, "delivery", f"sent{doc_id}", "delivered", {"doc_id": doc_id, "at": _now()}, parent=doc_id)
    return True


def board_html(pack, items):
    f = pack["fields"]
    esc = lambda s: str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")   # noqa: E731
    by_id = {str(i["doc_id"]): i for i in items}
    li = lambda xs: "".join(f"<li style='margin:4px 0'>{esc(x)}</li>" for x in xs or [])            # noqa: E731
    dec = ""
    for d in f.get("decisions") or []:
        it = by_id.get(str(d.get("item_id")))
        title = it["title"] if it else f"item {d.get('item_id')}"
        who = ROLES.get((it or {}).get("fields", {}).get("role"), {}).get("title", "")
        dec += (f"<tr><td style='padding:8px;border-top:1px solid #333;vertical-align:top;color:#93c5fd'>"
                f"#{esc(d.get('item_id'))}</td><td style='padding:8px;border-top:1px solid #333'>"
                f"<b>{esc(title)}</b><br><span style='color:#9ca3af'>{esc(who)} · {esc(d.get('why_now'))}</span></td>"
                f"<td style='padding:8px;border-top:1px solid #333;vertical-align:top;white-space:nowrap'>"
                f"{esc(d.get('recommendation'))}</td></tr>")
    e = f.get("eli5") or {}
    plain = "".join(f"<p style='margin:6px 0;line-height:1.5'><b style='color:#a78bfa'>{q}</b><br>{esc(e.get(k))}</p>"
                    for k, q in (("what", "What is happening?"), ("why", "Why does it matter?"),
                                 ("do", "What should you do?"), ("remember", "What to remember")) if e.get(k))
    if plain:
        plain = f"<div style='border-left:3px solid #8b5cf6;padding:4px 12px;margin:12px 0;background:#12121a'>{plain}</div>"
    return f"""<!doctype html><html><body style="background:#0b0f17;color:#e5e7eb;font-family:-apple-system,Segoe UI,sans-serif;padding:20px">
<div style="max-width:680px;margin:auto">
<div style="font-size:12px;color:#9ca3af">Alpha Signal · board pack · {esc(pack['doc_date'][:10])}</div>
<h2 style="margin:6px 0 12px">{esc(f.get('headline'))}</h2>
{plain}
<p style="line-height:1.55">{esc(f.get('state_of_fund'))}</p>
<h3 style="margin:20px 0 6px">Decisions for you ({len(f.get('decisions') or [])})</h3>
<table style="width:100%;border-collapse:collapse;font-size:14px">{dec or "<tr><td style='color:#9ca3af'>None this week.</td></tr>"}</table>
<p style="font-size:13px;color:#9ca3af"><a href="{BOARDROOM_URL}#inbox" style="color:#a78bfa">Open the Boardroom inbox to decide</a>, or: <code>python -m org decide &lt;id&gt; approve|reject|park</code></p>
<h3 style="margin:20px 0 6px">Wins</h3><ul style="padding-left:18px">{li(f.get('wins'))}</ul>
<h3 style="margin:20px 0 6px">Worries</h3><ul style="padding-left:18px">{li(f.get('worries'))}</ul>
<h3 style="margin:20px 0 6px">Next week</h3><ul style="padding-left:18px">{li(f.get('next_week'))}</ul>
</div></body></html>"""


def deliver_all(day=None, force=False):
    """Email today's board pack (once) and push once for today's asks marked urgency=now.
    Only documents dated `day` are sent, so a pack from a run with --no-deliver is never
    emailed late. force: (re)send the newest pack whatever its date."""
    from tools.health_report import send_email, send_ntfy
    out = {}
    today = (day or dt.date.today()).isoformat()
    pack = next(iter(docs(["board_pack"], days=30 if force else 2, limit=1)), None)
    with get_db() as conn:
        send_pack = bool(pack) and (force or (pack["doc_date"][:10] == today and _sent(conn, pack["doc_id"])))
        urgent = [a for a in docs(["ask"], days=2) if a["fields"].get("urgency") == "now"
                  and a["doc_date"][:10] == today and _sent(conn, a["doc_id"])]
    if send_pack:
        out["board_email"] = send_email(board_html(pack, inbox()), f"Alpha Signal board pack · {pack['doc_date'][:10]}")
        n = len(pack["fields"].get("decisions") or [])
        if n:
            out["board_push"] = send_ntfy(f"Board pack {pack['doc_date'][:10]}: {n} decision(s) waiting. {pack['title']}",
                                          click=f"{BOARDROOM_URL}#pack")
    if urgent:
        out["urgent_push"] = send_ntfy("Needs you now:\n" + "\n".join(
            f"#{a['doc_id']} [{a['fields'].get('role')}] {a['title']}" for a in urgent[:5]), urgent=True,
            click=f"{BOARDROOM_URL}#inbox")
    return out


# ═══════════════════════════ CLI ═══════════════════════════

def _roster():
    lines = []

    def walk(boss, depth):
        for rid, s in ROLES.items():
            if s["reports_to"] == boss:
                tag = s["type"] + (f" · {s['cadence']} · {s.get('model')}" if s["type"] == "desk" else "")
                lines.append(f"{'  ' * depth}{s['title']} ({rid}) [{tag}]")
                walk(rid, depth + 1)
    walk(None, 0)
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("roster")
    r = sub.add_parser("run")
    r.add_argument("--role", action="append")
    r.add_argument("--all", action="store_true", help="every desk role, whatever its cadence")
    r.add_argument("--adhoc", action="store_true", help="an extra run that leaves the scheduled period free")
    r.add_argument("--no-deliver", action="store_true")
    r.add_argument("--kind", action="append", help="only this task kind of the seat (e.g. org_cio_outlook)")
    r.add_argument("--drain", action="store_true", help="queue nothing new: only work off what is already queued")
    sub.add_parser("inbox")
    d = sub.add_parser("decide")
    d.add_argument("item_id", type=int)
    d.add_argument("verdict", choices=VERDICTS)
    d.add_argument("--note")
    b = sub.add_parser("board")
    b.add_argument("--send", action="store_true")
    sub.add_parser("scorecard")
    w = sub.add_parser("work", help="work orders: list, show one with the chat it came from, or report progress")
    w.add_argument("number", nargs="?", type=int)
    w.add_argument("--status", choices=WORK_STATUSES)
    w.add_argument("--note")
    a = p.parse_args(argv)
    if a.cmd == "work":
        if a.number is None:
            for x in work_orders():
                print(f"#{x['number']:<4} {x['status']:<18} {x['role']:<18} {len(x['items'])} item(s)  {x['title']}")
            return 0
        try:
            x = work_status(a.number, a.status, a.note) if a.status else work_order(a.number)
        except ValueError as e:
            print(f"ERROR: {e}")
            return 1
        if not x:
            print(f"no work order {a.number}")
            return 1
        import org_chat
        print(json.dumps({**x, "chat_it_came_from": org_chat.transcript(x["role"], x["conv"])}, indent=1,
                         ensure_ascii=False))
        return 0
    if a.cmd == "roster":
        print(_roster())
        return 0
    if a.cmd == "run":
        roles = [r for r in desk_roles() if seat(r).get("enabled", True)] if a.all else a.role
        for x in roles or []:
            if x not in ROLES or ROLES[x]["type"] != "desk":
                p.error(f"{x!r} is not a desk role; one of {desk_roles()}")
        out = run(roles=roles, adhoc=a.adhoc, deliver=not a.no_deliver, kinds=a.kind, drain=a.drain)
        print(json.dumps(out, indent=1, default=str))
        return 1 if out["failed"] else 0
    if a.cmd == "inbox":
        for i in inbox():
            print(f"#{i['doc_id']:<7} {i['type']:<10} {i['fields'].get('role', ''):<16} {i['age_days']}d  {i['title']}")
        return 0
    if a.cmd == "decide":
        print(json.dumps(decide(a.item_id, a.verdict, a.note)))
        return 0
    if a.cmd == "board":
        pack = next(iter(docs(["board_pack"], days=30, limit=1)), None)
        if not pack:
            print("no board pack yet")
            return 1
        print(json.dumps(pack["fields"], indent=1, ensure_ascii=False))
        if a.send:
            print(deliver_all(force=True))
        return 0
    print(json.dumps(scorecard(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
