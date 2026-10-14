#!/usr/bin/env python3
"""SessionStart hook: the automatic /catchup.

Prints the health report, HANDOFF.md and git state; Claude Code adds stdout to the new
session's context, and the instruction at the top makes the first reply the catchup report.
Output is capped under Claude Code's 10,000-character hook limit (over it, the text is
replaced by a file path and a short preview that Claude is not told to read).

The health report takes ~17 s, so it is cached for 15 minutes across sessions."""
import os
import pathlib
import subprocess
import time

ROOT = pathlib.Path(os.environ.get("CLAUDE_PROJECT_DIR") or pathlib.Path(__file__).resolve().parents[2])
VENV_PY = pathlib.Path.home() / "alpha-signal" / "venv" / "bin" / "python"
CACHE = pathlib.Path.home() / ".cache" / "alpha-signal" / "session_health.txt"
CACHE_SECONDS = 15 * 60
LIMIT = 9500                      # stay under the 10,000-char hook cap
HEALTH_MAX, GIT_LINES = 4600, 15   # HANDOFF gets whatever room is left

INSTRUCTION = """AUTO-CATCHUP (SessionStart hook, .claude/hooks/session_start.py)
Open your FIRST reply in this session with the /catchup situation report, built from the
context below, before answering anything else:
- Put the health report verbatim at the top; name every CRITICAL under Watch out.
- Then read docs/plans/0000-checklist.md ("Next 3") and the active plan HANDOFF names.
- Four short sentences: Left off / Pick up / Watch out / This session (quote the checklist
  bullet the user's request belongs to; if none fits, say so so it can be added first).
- Flag a HANDOFF older than 48 h or an unexpectedly dirty tree. Don't propose work yet.
If the user's first message is a quick question, keep the report to those four sentences
and then answer it."""


def _run(cmd, timeout):
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or r.stderr).rstrip()   # keep the leading column of `git status --short`
    except Exception as e:  # a broken hook must never block the session
        return f"(failed: {type(e).__name__}: {e})"


def _clip(text, n, what):
    return text if len(text) <= n else text[:n].rstrip() + f"\n… (truncated — read {what} for the rest)"


def health():
    try:
        age = time.time() - CACHE.stat().st_mtime
        if age < CACHE_SECONDS:
            return CACHE.read_text() + f"\n(cached {int(age // 60)} min ago)"
    except OSError:
        pass
    out = _run([str(VENV_PY), "-m", "tools.health_report"], timeout=90)
    if not out.startswith("(failed"):
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(out)
    return out


def handoff(room):
    f = ROOT / "HANDOFF.md"
    if not f.exists():
        return "(no HANDOFF.md)"
    hours = (time.time() - f.stat().st_mtime) / 3600
    stale = f"  ⚠ STALE: {hours / 24:.1f} days old" if hours > 48 else ""
    return f"(file age {hours:.0f} h){stale}\n" + _clip(f.read_text().strip(), room, "HANDOFF.md")


def git():
    branch = _run(["git", "branch", "--show-current"], 10)
    status = _run(["git", "status", "--short"], 20).splitlines()
    shown = "\n".join(status[:GIT_LINES])
    more = f"\n… and {len(status) - GIT_LINES} more (git status)" if len(status) > GIT_LINES else ""
    log = _run(["git", "log", "--oneline", "-5"], 10)
    return f"branch: {branch} · {len(status)} changed/untracked paths\n{shown}{more}\n\nlast commits:\n{log}"


def main():
    head = [INSTRUCTION, "=== HEALTH REPORT ===\n" + _clip(health(), HEALTH_MAX, "`python -m tools.health_report`")]
    tail = "=== GIT ===\n" + git()
    room = LIMIT - sum(len(x) + 2 for x in head) - len(tail) - 200
    print("\n\n".join(head + ["=== HANDOFF.md ===\n" + handoff(room), tail]))


if __name__ == "__main__":
    main()
