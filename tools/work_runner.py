"""
Alpha Signal v2 — the unattended Tier B work-order runner (plan 0032 stage 7, ADR 0091).

Every night it takes the work orders the CEO approved (or let stand 48 h, ADR 0086) that are
Tier B, runs each one as a headless Claude Code builder in its own git worktree, checks the
result, merges what passed into master, and writes a plain-words memo per order on the
Boardroom. Tier A orders are never touched: they wait for a session the CEO opens.

Guardrails, every one of which can stop a run:
  kill switch       output/work_runner.off exists → nothing runs (touch it to pause the runner)
  quiet window      no run between 02:00 and 08:00 UTC (the morning pipeline and the org)
  one at a time     a lock file; a second runner exits
  tier              the order's tier is B and no item's `where` is on a Tier A path (org_kinds.tier_for)
  attempts          an order gets MAX_ATTEMPTS tries; the runner's own faults (no Claude login, a baseline that would
                    not run, another session's edits, a refused push) are not charged, but MAX_STARTS caps them
  time              ORDER_TIMEOUT_S per order (the builder is killed), RUN_BUDGET_S per night
  tools             the builder may Read / Edit / Write / Grep / Glob and run only pytest, git diff /
                    status / log, ls and the probes (claude -p --allowedTools, --permission-mode dontAsk)
  no live data      ALPHA_DB is unset in the worktree (an empty scratch DB appears there, nothing else)
  scope             the diff touches at most MAX_FILES files / MAX_LINES lines, none on a Tier A path,
                    none under ops/, .claude/settings*, secrets; a deleted file must be named in an item
  suite             no test fails that does not already fail on an untouched copy of the same commit (ADR 0096:
                    a worktree has no database, so about 35 tests can never pass there; a new failure is re-run once
                    to rule out a flake)
  live data         an order that needs the database (dq-auditor findings, a data-engineer or quant-researcher item)
                    is refused: a session runs it. Nothing under signals/, scoring/, eligibility/, pit.py or
                    portfolio_construction.py is merged: a change to the ranking needs a pick diff on real data
  overlap           no merge while another session's uncommitted edits touch the same files
  push              master is pushed through the pre-push suite, the one run on real data; if it refuses, the merge
                    is reverted, so unverified code never stays on master
  undo              every memo carries the one command that reverts the merge

Usage:
    python -m tools.work_runner                # the nightly run (cron: run.sh work_orders)
    python -m tools.work_runner --dry          # list what it would do, change nothing
    python -m tools.work_runner --order 7      # one order, now (still every guardrail)
    python -m tools.work_runner --order 7 --verify   # everything up to the merge; the branch is left ready
    python -m tools.work_runner --reset 7      # a person says: give this order its attempts back
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import org  # noqa: E402
from alpha_mcp import org_kinds  # noqa: E402

KILL_FILE = ROOT / "output" / "work_runner.off"
LOCK_FILE = Path("/tmp/alpha_signal_work_runner.lock")
WORKTREES = ROOT / ".claude" / "worktrees"
QUIET_UTC = (2, 8)                   # [from, to): the morning pipeline (03:30) and the org (06:30)
MAX_ORDERS_PER_RUN = 2
MAX_ATTEMPTS = 2
MAX_STARTS = 5                       # charged or not, an order is not started more often than this
PICK_PATHS = ("signals/", "scoring/", "eligibility/", "pit.py", "portfolio_construction.py")
LIVE_DATA_ROLES = ("dq-auditor",)
LIVE_DATA_OWNERS = ("data-engineer", "quant-researcher")
RUNNER_FAULTS = ("Failed to authenticate", "OAuth", "usage limit", "rate limit")
ORDER_TIMEOUT_S = 45 * 60
SUITE_TIMEOUT_S = 20 * 60
PUSH_TIMEOUT_S = 20 * 60
RUN_BUDGET_S = 110 * 60
MAX_FILES = 25
MAX_LINES = 1500
FORBIDDEN_PREFIXES = ("ops/", ".claude/settings", ".claude/hooks", "data/", "backup", "run.sh", "schema.sql")
ALLOWED_TOOLS = ["Read", "Edit", "Write", "Grep", "Glob",
                 "Bash(python -m pytest:*)", "Bash(PYTHONPATH=.devlib python -m pytest:*)",
                 "Bash(PYTHONPATH=/home/ubuntu/alpha-signal-v2/.devlib python -m pytest:*)",
                 "Bash(git diff:*)", "Bash(git status:*)", "Bash(git log:*)", "Bash(ls:*)",
                 "Bash(python -m tools.code_probes:*)", "Bash(python -m tools.arch_probes:*)",
                 "Bash(python -m tools.dq_probes:*)", "Bash(python -m datamodel.gate:*)"]
RUNNER_ROLE = "work-runner"
PATCHES = ROOT / "data" / "work_runner"

SUMMARY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["headline", "story", "items", "worries"],
    "properties": {
        "headline": {"type": "string", "maxLength": 160},
        "story": {"type": "string", "maxLength": 1500,
                  "description": "4 to 7 short sentences a smart non-programmer can follow: what the job was, what you did, how you checked it, what you left alone and why."},
        "items": {"type": "array", "maxItems": 12, "items": {
            "type": "object", "additionalProperties": False, "required": ["title", "done", "what_i_did", "how_checked"],
            "properties": {"title": {"type": "string", "maxLength": 160}, "done": {"type": "boolean"},
                           "what_i_did": {"type": "string", "maxLength": 500}, "how_checked": {"type": "string", "maxLength": 300}}}},
        "worries": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 240}},
    },
}


# ─────────────────────────── guardrails ───────────────────────────

def kill_switch():
    return KILL_FILE.exists()


def in_quiet_window(now=None):
    h = (now or dt.datetime.now(dt.timezone.utc)).hour
    return QUIET_UTC[0] <= h < QUIET_UTC[1]


def _notes(order):
    """The order's progress notes since the last reset, oldest first. Each new note supersedes the last, so read every status."""
    docs = sorted(org.docs(["progress"], days=None, parent=order["doc_id"], status=None, limit=200), key=lambda d: d["doc_id"])
    notes = [d["fields"].get("note") or "" for d in docs]
    last = max((i for i, x in enumerate(notes) if x.startswith("[runner] reset")), default=-1)
    return notes[last + 1:]


def attempts(order):
    """Tries charged to this order: a failure that was its own, not the runner's."""
    return sum(1 for x in _notes(order) if x.startswith("[runner] attempt"))


def starts(order):
    return sum(1 for x in _notes(order) if x.startswith(("[runner] started", "[runner] attempt")) and "failed" not in x[:30])


def needs_live_data(order):
    """The runner has no database, so it cannot measure or fix what lives in the data."""
    return order.get("role") in LIVE_DATA_ROLES or any(it.get("owner") in LIVE_DATA_OWNERS for it in order.get("items") or [])


def touches_picks(path):
    return str(path).startswith(PICK_PATHS)


def pick_items(order):
    """Items whose `where` is the ranking's own code: the builder leaves these for a session."""
    return [it for it in order.get("items") or [] if touches_picks(it.get("where") or "")]


def refusal(order):
    """Why the runner must not take this order, or None."""
    note = order.get("note") or ""
    # one of its own runs ended short, or died mid-way (the lock says no other runner is alive): it may try again
    mine = order["status"] in ("blocked", "in_progress") and note.startswith("[runner]")
    if order["status"] != "approved" and not mine:
        return f"status is {order['status']}"
    if org.work_order_tier(order) != "B":
        return "Tier A: waits for the CEO and a session"
    if needs_live_data(order):
        return f"needs the live database: a session runs it with /work-order {order['number']}"
    for it in order.get("items") or []:
        if org_kinds.tier_for(it.get("where") or "") == "A":
            return f"item '{it.get('title', '')[:60]}' touches a Tier A path ({it.get('where', '')[:60]})"
    if order.get("items") and len(pick_items(order)) == len(order["items"]):
        return "every item changes the ranking's code: a session measures the pick diff first"
    n = attempts(order)
    if n >= MAX_ATTEMPTS:
        return f"already tried {n} time(s)"
    if starts(order) >= MAX_STARTS:
        return f"started {MAX_STARTS} times without finishing: the runner itself needs a look"
    return None


def eligible():
    """Approved Tier B orders the runner may take, oldest first, with refusals for the rest."""
    take, skip = [], []
    for w in sorted(org.work_orders(days=120), key=lambda w: w["number"]):
        if w["status"] not in ("approved", "blocked", "in_progress"):
            continue
        why = refusal(w)
        (skip if why else take).append((w, why))
    return take, skip


def scope_problems(changed, order):
    """[reasons] the diff is out of bounds. `changed` = [(status, path)] from git status --porcelain."""
    out = []
    paths = [p for _s, p in changed]
    if len(paths) > MAX_FILES:
        out.append(f"{len(paths)} files changed, the cap is {MAX_FILES}")
    named = " ".join(str(it.get("where") or "") + " " + str(it.get("what") or "") for it in order.get("items") or [])
    for status, p in changed:
        if org_kinds.tier_for(p) == "A":
            out.append(f"{p} is a Tier A path")
        if p.startswith(FORBIDDEN_PREFIXES) or "secrets" in p:
            out.append(f"{p} is off limits")
        if touches_picks(p):
            out.append(f"{p} is the ranking's code: a session measures the pick diff first")
        if status.strip().startswith("D") and Path(p).name not in named and p not in named:
            out.append(f"{p} was deleted but no item names it")
    return out


# ─────────────────────────── git ───────────────────────────

def _git(args, cwd=ROOT, timeout=120, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def _changed(cwd):
    rows = []
    for line in _git(["status", "--porcelain"], cwd=cwd).splitlines():
        rows.append((line[:2], line[3:].strip()))
    return rows


def _diff_lines(cwd):
    out = _git(["diff", "--shortstat", "HEAD"], cwd=cwd)
    m = re.findall(r"(\d+) (?:insertion|deletion)", out)
    return sum(int(x) for x in m)


def _main_tree_overlap(paths):
    dirty = {p for _s, p in _changed(ROOT)}
    return sorted(dirty & set(paths))


# ─────────────────────────── the builder ───────────────────────────

def _agent_rules(owner):
    p = ROOT / ".claude" / "agents" / f"{owner}.md"
    text = p.read_text() if p.exists() else ""
    if text.startswith("---"):
        text = text.split("---", 2)[-1]
    return text.strip()


def prompt_for(order):
    leave = [it["title"] for it in pick_items(order)]
    items = "\n".join(f"{i + 1}. {it['title']}\n   what: {it.get('what', '')}\n   where: {it.get('where', '')}\n"
                      f"   done when: {it.get('done_when', '')}" for i, it in enumerate(order.get("items") or []))
    return f"""You are running work order #{order['number']} unattended, overnight, in a git worktree of Alpha Signal v2.
Title: {order['title']}
Why: {order.get('summary', '')}

Items, in order:
{items}

{"Leave these items alone and mark them done=false; they change the ranking and a session measures them on real data: " + "; ".join(leave) if leave else ""}

Rules that are enforced, not advisory:
- Change only what the items name. Touch nothing under ops/, run.sh, schema.sql, config.py, factors.py, options_live.py,
  option_book.py, signals/, scoring/, eligibility/, pit.py, portfolio_construction.py, the crontab, settings or secrets.
  Do not create new tables or new modules unless an item says so.
- You have no live database here (ALPHA_DB is unset). About 35 tests fail in any worktree because of that, before you
  change anything; the runner compares against a clean copy, so do not chase them. Do not try to reach data/.
- Do not commit, push, merge, or touch other branches. The runner commits your worktree after it checks it.
- Run the relevant tests after each item with
  `PYTHONPATH=/home/ubuntu/alpha-signal-v2/.devlib python -m pytest -q -p no:cacheprovider <tests>`.
- If an item is unclear, or its done_when cannot be met without touching something off limits, leave that item,
  mark it done=false and say why. A wrong change costs more than a skipped one.
- Finish well inside 40 minutes.

When you are done, answer ONLY with the JSON the schema asks for. Write `story` the way a sharp newsletter explains
things to a smart reader who does not code: short sentences, what the job was, what you changed, how you checked it,
what you left alone and why, no jargon without a plain gloss."""


def run_builder(order, worktree, timeout=ORDER_TIMEOUT_S, dry=False):
    """→ (summary dict | None, raw result text, rc). Headless Claude Code with a tool allowlist."""
    owner = next((it.get("owner") for it in order.get("items") or [] if it.get("owner")), "backend-engineer")
    system = _agent_rules(owner) + "\n\n" + org.house_style()
    cmd = [org.CLAUDE_BIN, "-p", prompt_for(order), "--system-prompt", system, "--permission-mode", "dontAsk",
           "--allowedTools", *ALLOWED_TOOLS, "--output-format", "json", "--json-schema", json.dumps(SUMMARY_SCHEMA)]
    if dry:
        return None, "dry run: builder not started", 0
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ALPHA_DB") and not k.startswith("GIT_")}
    env["COCKPIT_PREVIEW"] = "1"
    try:
        p = subprocess.run(cmd, cwd=worktree, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"killed after {timeout // 60} minutes", 124
    try:
        out = json.loads(p.stdout)
        summary = out.get("structured_output")
        if isinstance(summary, str):
            summary = json.loads(summary)
        if summary is None and out.get("result"):
            summary = json.loads(out["result"])
        return summary, p.stdout[-2000:], p.returncode
    except (ValueError, TypeError):
        return None, (p.stdout or p.stderr)[-2000:], p.returncode or 1


# ─────────────────────────── one order ───────────────────────────

def _clear_stray_data(worktree):
    """A test run in a worktree leaves an empty data/alpha_signal.db, and tests that skip when no DB exists then run against
    it and fail (14 extra failures on 2026-11-04). Only ever inside a worktree, and data/ there is git-ignored."""
    d = Path(worktree) / "data"
    if str(Path(worktree)).startswith(str(WORKTREES)) and d.exists():
        d.unlink() if d.is_symlink() else shutil.rmtree(d, ignore_errors=True)


def _pytest(worktree, targets):
    env = {k: v for k, v in os.environ.items() if k != "ALPHA_DB" and not k.startswith("GIT_")}
    env["PYTHONPATH"] = str(ROOT / ".devlib")
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no", "-rfE", *targets], cwd=worktree,
                          env=env, capture_output=True, text=True, timeout=SUITE_TIMEOUT_S)


def parse_suite(text):
    """pytest -rfE output → (set of failing test ids, last line, did it really run)."""
    failed = set()
    for line in text.splitlines():
        m = re.match(r"(?:FAILED|ERROR) (\S+)", line)
        if m:
            failed.add(m.group(1))
    lines = text.strip().splitlines()
    tail = lines[-1][:200] if lines else ""
    return failed, tail, bool(re.search(r"\d+ (passed|failed)", tail))


def run_suite(worktree, targets=("tests/",)):
    """→ {"failed": set, "tail": str, "ran": bool}. A timeout or a crash before the summary is ran=False."""
    _clear_stray_data(worktree)
    try:
        failed, tail, ran = parse_suite(_pytest(worktree, targets).stdout or "")
    except subprocess.TimeoutExpired:
        return {"failed": set(), "tail": f"timed out after {SUITE_TIMEOUT_S // 60} minutes", "ran": False}
    return {"failed": failed, "tail": tail, "ran": ran}


_baselines = {}


def baseline(sha):
    """What already fails on an untouched copy of commit `sha`, once per commit per run."""
    if sha not in _baselines:
        wt = WORKTREES / "wo-baseline"
        if wt.exists():
            shutil.rmtree(wt, ignore_errors=True)
            _git(["worktree", "prune"])
        _git(["worktree", "add", "-q", "--detach", str(wt), sha])
        try:
            _baselines[sha] = run_suite(wt)
        finally:
            shutil.rmtree(wt, ignore_errors=True)
            _git(["worktree", "prune"], check=False)
    return _baselines[sha]


def new_failures(order_suite, base):
    return sorted(order_suite["failed"] - base["failed"])


def _keep_patch(wt, n):
    """A rebuilt worktree discards the last attempt's edits: keep them as a patch first."""
    try:
        diff = _git(["diff", "HEAD"], cwd=wt)
    except (RuntimeError, OSError):
        return None
    if not diff.strip():
        return None
    PATCHES.mkdir(parents=True, exist_ok=True)
    path = PATCHES / f"wo-{n}-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M}.patch"
    path.write_text(diff)
    return path


def _revert_merge(sha):
    """Undo a merge the real-data suite refused. Returns None, or why it could not."""
    try:
        _git(["-c", "user.name=alpha-runner", "-c", "user.email=runner@alpha-signal", "revert", "-m", "1", "--no-edit", sha])
        return None
    except RuntimeError as e:
        return str(e)[:200]


def run_order(order, dry=False, verify=False):
    """Run one approved Tier B order end to end. → the facts dict the memo is written from."""
    n = order["number"]
    facts = {"order": n, "title": order["title"], "tier": org.work_order_tier(order), "started_at": org._now(),
             "items": [it["title"] for it in order.get("items") or []], "merged": False, "sha": None, "branch": f"wo-{n}",
             "changed": [], "lines": 0, "suite": None, "problems": [], "summary": None, "dry": dry, "verify": verify,
             "ready": False, "runner_fault": False, "already_failing": None, "new_failures": []}
    why = refusal(order)
    if why:
        facts["problems"].append(why)
        return facts
    if dry:
        facts["problems"].append("dry run: nothing started")
        return facts
    wt = WORKTREES / f"wo-{n}"
    if wt.exists():
        facts["kept_patch"] = str(_keep_patch(wt, n) or "") or None
        shutil.rmtree(wt, ignore_errors=True)
        _git(["worktree", "prune"])
    _git(["branch", "-D", f"wo-{n}"], check=False)
    sha = _git(["rev-parse", "master"]).strip()
    _git(["worktree", "add", "-q", str(wt), "-b", f"wo-{n}", sha])
    facts["attempt"] = attempts(order) + 1
    org.work_status(n, "in_progress", f"[runner] started attempt {facts['attempt']} at {facts['started_at']}")
    try:
        summary, raw, rc = run_builder(order, wt)
        facts["summary"], facts["builder_rc"] = summary, rc
        if rc:
            facts["problems"].append(f"the builder exited {rc}: {raw[-200:]}")
            facts["runner_fault"] = any(x in raw for x in RUNNER_FAULTS)
        changed = _changed(wt)
        facts["changed"] = [p for _s, p in changed]
        facts["lines"] = _diff_lines(wt) if changed else 0
        if not changed and not rc:
            facts["problems"].append("the builder changed nothing")
        facts["problems"] += scope_problems(changed, order)
        if facts["lines"] > MAX_LINES:
            facts["problems"].append(f"{facts['lines']} lines changed, the cap is {MAX_LINES}")
        if not facts["problems"]:
            base = baseline(sha)
            mine = run_suite(wt)
            facts["already_failing"] = len(base["failed"])
            facts["suite"] = mine["tail"]
            if not base["ran"] or not mine["ran"]:
                facts["runner_fault"] = True
                facts["problems"].append(f"the test suite did not finish: clean copy '{base['tail']}', this order '{mine['tail']}'")
            else:
                new = new_failures(mine, base)
                if new:                                      # once more, on their own: a flake is not this order's fault
                    again = run_suite(wt, new)
                    new = sorted(set(new) & again["failed"]) if again["ran"] else new
                facts["new_failures"] = new
                if new:
                    facts["problems"].append(f"{len(new)} test(s) fail that pass on a clean copy: " + ", ".join(new[:6]))
        if not facts["problems"]:
            _git(["add", "-A"], cwd=wt)                      # the worktree holds only the builder's edits
            msg = (f"wo-{n}: {order['title'][:70]}\n\nUnattended Tier B run (ADR 0091, 0096); items: "
                   + "; ".join(facts["items"])[:400] + "\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
            _git(["-c", "user.name=alpha-runner", "-c", "user.email=runner@alpha-signal", "commit", "-q", "-m", msg], cwd=wt)
            overlap = _main_tree_overlap(facts["changed"])
            if verify:
                facts["ready"] = True
            elif overlap:
                facts["runner_fault"] = True
                facts["problems"].append(f"another session has uncommitted edits in {overlap[:5]}; branch wo-{n} kept, not merged")
            else:
                try:
                    _git(["merge", "--no-ff", "-q", f"wo-{n}", "-m", f"merge: work order #{n} (unattended Tier B run, ADR 0091)\n\n"
                          "Co-Authored-By: Claude <noreply@anthropic.com>"])
                    merged_sha = _git(["rev-parse", "HEAD"]).strip()
                except RuntimeError as e:
                    facts["runner_fault"] = True
                    facts["problems"].append(f"the merge did not apply: {str(e)[:200]}")
                else:
                    try:
                        _git(["push", "origin", "master"], timeout=PUSH_TIMEOUT_S)
                        facts["sha"], facts["merged"], facts["pushed"] = merged_sha, True, True
                    except (RuntimeError, subprocess.TimeoutExpired) as e:
                        facts["pushed"], facts["runner_fault"] = False, True
                        undo = _revert_merge(merged_sha)
                        facts["problems"].append(f"the real-data suite refused the push, so the merge was reverted: {str(e)[:160]}"
                                                 if undo is None else
                                                 f"the push was refused AND the revert failed, master holds {merged_sha[:7]}: {undo}")
    except Exception as e:                                   # noqa: BLE001  one order's crash must not stop the night or strand the status
        facts["runner_fault"] = True
        facts["problems"].append(f"the runner crashed: {type(e).__name__}: {str(e)[:240]}")
    finally:
        if wt.exists() and (facts["merged"] or not facts["changed"]):
            shutil.rmtree(wt, ignore_errors=True)
            _git(["worktree", "prune"], check=False)
    left = [i["title"] for i in (facts["summary"] or {}).get("items") or [] if not i.get("done")]
    if facts["merged"]:
        org.work_status(n, "done", f"[runner] merged as {facts['sha'][:7]}" + (f"; left for a session: {'; '.join(left)}"[:400] if left else ""))
    elif facts["ready"]:
        org.work_status(n, "blocked", f"[verify] the gate passed; branch wo-{n} is ready, not merged")
    elif facts["runner_fault"]:
        org.work_status(n, "blocked", "[runner] not charged, the runner's own problem: " + "; ".join(facts["problems"])[:560])
    else:
        org.work_status(n, "blocked", f"[runner] attempt {facts['attempt']} failed: " + "; ".join(facts["problems"])[:560])
    facts["finished_at"] = org._now()
    return facts


def reset(number):
    """A person gives an order its attempts back, and it may run again."""
    w = org.work_order(int(number))
    if not w:
        raise ValueError(f"no work order {number}")
    org.work_status(int(number), "blocked", f"[runner] reset by a person at {org._now()}: attempts start again")
    return org.work_order(int(number))


# ─────────────────────────── the memo ───────────────────────────

def memo_fields(facts):
    """A Finshots-style memo: the story for a non-programmer, then the facts and the undo."""
    s = facts.get("summary") or {}
    n = facts["order"]
    if facts.get("dry"):
        headline = f"Dry run: work order #{n} would be {'refused' if facts['problems'] else 'taken'}"
    elif facts.get("ready"):
        headline = f"Work order #{n} passed the gate; branch wo-{n} is ready, not merged"
    elif facts["merged"]:
        headline = s.get("headline") or f"Work order #{n} done and merged overnight"
    else:
        headline = f"Work order #{n} stopped short: {facts['problems'][0][:90]}" if facts["problems"] else f"Work order #{n}: nothing to merge"
    story = s.get("story") or ("The runner did not get as far as the work itself. " + " ".join(facts["problems"]))
    what = (f"The runner picked up work order #{n}, \"{facts['title']}\". " + story)[:340]
    why = ("Tier B orders run on their own after the 48-hour window (ADR 0086); the runner only merges when the diff stays inside "
           "the order, touches no Tier A or ranking path, adds no test failure over a clean copy, and the real-data push suite passes.")[:340]
    if facts["merged"]:
        do = f"Nothing, unless you disagree: `git revert -m 1 {facts['sha'][:7]}` undoes it in one step."
    elif facts.get("ready"):
        do = f"Read the changes on branch wo-{n}; a session merges it."
    elif facts.get("runner_fault"):
        do = "Nothing: this was the runner's own problem, it is not charged to the order, and it tries again tomorrow night."
    elif facts.get("attempt", 1) >= MAX_ATTEMPTS or any("tried" in p for p in facts["problems"]):
        do = "Read the problems below. The order is blocked: it has had its tries and needs a person."
    else:
        do = "Read the problems below. The runner will try the order once more tomorrow night; park it on /org if you would rather it did not."
    do = do[:340]
    remember = "A reverted merge counts against the seat that proposed it (ADR 0085 J6)."
    return {
        "role": RUNNER_ROLE, "as_of": facts["started_at"][:10], "headline": headline[:160],
        "verdict": "merged" if facts["merged"] else "ready" if facts.get("ready") else "stopped",
        "eli5": {"what": what, "why": why, "do": do, "remember": remember},
        "items": [{"title": i["title"], "done": i["done"], "what_i_did": i["what_i_did"], "how_checked": i["how_checked"]}
                  for i in (s.get("items") or [])] or [{"title": t, "done": False, "what_i_did": "not reached", "how_checked": ""}
                                                        for t in facts["items"]],
        "worries": s.get("worries") or [],
        "files_changed": facts["changed"][:40], "lines_changed": facts["lines"], "suite": facts.get("suite"),
        "already_failing_on_clean_copy": facts.get("already_failing"), "new_failures": facts.get("new_failures") or [],
        "runner_fault": bool(facts.get("runner_fault")), "kept_patch": facts.get("kept_patch"),
        "merged": facts["merged"], "sha": facts.get("sha"), "pushed": facts.get("pushed"),
        "undo": f"git revert -m 1 {facts['sha']}" if facts["merged"] else None,
        "problems": facts["problems"], "branch": facts["branch"], "started_at": facts["started_at"],
        "finished_at": facts.get("finished_at"), "order": n,
    }


def write_memo(facts, push=True):
    from db import get_db
    fields = memo_fields(facts)
    with get_db() as conn:
        doc_id, _sup = org.save_doc(conn, "runner_memo", f"wo:{facts['order']}:{facts['started_at'][:16]}", fields["headline"],
                                    fields, doc_date=fields["as_of"], parent=None)
    if push and not facts.get("dry"):
        try:
            from tools.health_report import send_ntfy
            send_ntfy(f"Runner: {fields['headline']}", click=org.BOARDROOM_URL)
        except Exception:                                   # noqa: BLE001  a push is not worth a failed run
            pass
    return doc_id


# ─────────────────────────── the night ───────────────────────────

def run(dry=False, only=None, max_orders=MAX_ORDERS_PER_RUN, verify=False):
    """→ {"ran": [...facts], "skipped": [(number, why)], "stopped": reason | None}."""
    out = {"ran": [], "skipped": [], "stopped": None}
    if kill_switch():
        out["stopped"] = f"kill switch {KILL_FILE} exists"
        return out
    if in_quiet_window() and not dry and only is None:
        out["stopped"] = "quiet window (02:00–08:00 UTC)"
        return out
    take, skip = eligible()
    out["skipped"] = [(w["number"], why) for w, why in skip]
    if only is not None:
        take = [(w, why) for w, why in take if w["number"] == int(only)]
        if not take:
            w = org.work_order(int(only))
            out["stopped"] = f"order {only}: " + (refusal(w) if w else "not found")
            return out
    t0 = time.time()
    for w, _why in take[:max_orders]:
        if time.time() - t0 > RUN_BUDGET_S - ORDER_TIMEOUT_S:
            out["stopped"] = "night budget used up"
            break
        facts = run_order(w, dry=dry, verify=verify)
        if not dry:
            facts["memo_doc"] = write_memo(facts)
        out["ran"].append(facts)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--order", type=int)
    ap.add_argument("--max", type=int, default=MAX_ORDERS_PER_RUN)
    ap.add_argument("--verify", action="store_true", help="stop before the merge; needs --order")
    ap.add_argument("--reset", type=int, help="a person gives this order its attempts back")
    a = ap.parse_args()
    if a.reset:
        print(f"order #{a.reset}: {reset(a.reset)['status']}, attempts reset")
        return 0
    if a.verify and not a.order:
        ap.error("--verify needs --order")
    if not a.dry:
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR)
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("another runner holds the lock; exiting")
            return 0
    out = run(dry=a.dry, only=a.order, max_orders=a.max, verify=a.verify)
    for f in out["ran"]:
        print(f"  order #{f['order']}: {'MERGED ' + (f['sha'] or '')[:7] if f['merged'] else 'stopped'}"
              f" · {len(f['changed'])} files · {f['lines']} lines · {'; '.join(f['problems'])[:200] or 'no problems'}")
    for n, why in out["skipped"]:
        print(f"  order #{n}: skipped — {why}")
    if out["stopped"]:
        print(f"  stopped: {out['stopped']}")
    if not out["ran"] and not out["skipped"] and not out["stopped"]:
        print("  nothing approved and waiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
