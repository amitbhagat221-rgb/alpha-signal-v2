"""
Alpha Signal v2 — the Code Janitor's probes (plan 0032 stage 3, ADR 0085).

Clutter never breaks anything, so no check ever reports it. These probes do, weekly, with
the evidence that would let a reader delete with confidence:

  unreferenced     a module under tools/, sources/, signals/, output/, scoring/, checks/ or
                   validators/ that no production code, run.sh case, crontab line, pipeline
                   step or command refers to (its own tests do not count as use), with the
                   date it was last touched and whether anything ran it in 90 days
  cron_orphans     a run.sh case that neither ops/crontab.txt nor the live crontab schedules
  tests_cannot_fail
                   a test function with no assert and no pytest.raises: green by construction
  flaky_steps      a pipeline step that FAILED and then SUCCEEDED on the same run date, in
                   the last 60 days: a retry hid it
  duplicates       two functions in different modules with the same body (docstrings
                   ignored), or one name defined in three or more modules
  stale_flags      a True / False constant in config.py untouched for 180 days

A finding is a plain claim plus the evidence behind it (reference counts by kind, dates,
run counts). Nothing here changes a file or writes to the database.

The sticker (ADR 0085 J6): a suspect gets `runlog.note("sticker:<module>")` at the top of its
entry point, by a work order; `sticker_hits()` counts how often it fired in 90 days. Silence
is the evidence for deletion.

`drill()` plants each kind of clutter in a scratch tree (and a scratch run log) and checks the
probe that must notice it does. A probe that cannot catch its plant is itself a finding.

Usage:
    python -m tools.code_probes               # findings, as a table
    python -m tools.code_probes --json
    python -m tools.code_probes --drill
"""
import argparse
import ast
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCAN_DIRS = ("tools", "sources", "signals", "output", "scoring", "checks", "validators")
CODE_DIRS = ("", "tools", "sources", "signals", "output", "scoring", "checks", "validators", "cockpit", "cockpit_ops",
             "alpha_mcp", "datamodel", "eligibility", "mf", "scripts")
SKIP_PARTS = {"tests", "docs", "_archive", ".archify", ".claude", "output", "data", ".devlib", "graphify-out", "backups",
              "node_modules", "__pycache__", ".git"}
STICKER_DAYS = 90
FLAKY_DAYS = 60
FLAG_DAYS = 180
DUP_MIN_LINES = 8


# ─────────────────────────── the tree ───────────────────────────

def _py_files(root, dirs=CODE_DIRS):
    out = []
    for d in dirs:
        base = root / d if d else root
        if not base.is_dir():
            continue
        for p in (base.glob("*.py") if d else base.glob("*.py")):
            if p.name.startswith(".") or any(part in SKIP_PARTS for part in p.relative_to(root).parts[:-1]):
                continue
            out.append(p)
    return sorted(set(out))


def _text_files(root):
    """Everything that can refer to a module: production .py, run.sh, the crontab file, commands,
    routines, agent files, service units kept in ops/."""
    files = list(_py_files(root))
    for extra in ("run.sh", "ops/crontab.txt"):
        if (root / extra).exists():
            files.append(root / extra)
    for d in (".claude/commands", ".claude/routines", ".claude/agents", "ops"):
        if (root / d).is_dir():
            files += [p for p in (root / d).rglob("*") if p.is_file() and p.suffix in (".md", ".txt", ".sh", ".service")]
    return files


def _test_files(root):
    return sorted((root / "tests").glob("test_*.py")) if (root / "tests").is_dir() else []


def _git_last_touch(root, path):
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", str(path)], cwd=root, capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _ran_recently(conn, stem, days=STICKER_DAYS):
    """Steps named after the module that ran in the window: pipeline_log step names and run.sh jobs."""
    if conn is None:
        return 0
    try:
        return conn.execute("SELECT COUNT(*) FROM pipeline_log WHERE run_date >= date('now', ?) AND "
                            "(step_name = ? OR step_name = ? OR step_name LIKE ?)",
                            (f"-{days} day", stem, f"cron_{stem}", f"%{stem}%")).fetchone()[0]
    except sqlite3.Error:
        return 0


# ─────────────────────────── probes ───────────────────────────

def _finding(probe, subject, claim, evidence, touches=()):
    return {"probe": probe, "subject": subject, "claim": claim, "evidence": evidence, "touches": list(touches)}


def unreferenced(root=ROOT, conn=None):
    """Modules nothing refers to. A reference is the dotted name (tools.x), the path (tools/x.py)
    or `from tools import x`, in production code, run.sh, the crontab, commands, routines or
    agent files; references from the module itself and from its tests do not count."""
    texts = {}
    for p in _text_files(root):
        try:
            texts[p] = p.read_text(errors="ignore")
        except OSError:
            continue
    tests = {p: p.read_text(errors="ignore") for p in _test_files(root)}
    docs = {}
    if (root / "docs").is_dir():
        for q in (root / "docs").rglob("*"):
            if q.is_file() and q.suffix in (".md", ".html") and "_archive" not in q.parts:
                try:
                    docs[q] = q.read_text(errors="ignore")
                except OSError:
                    pass
    out = []
    for p in _py_files(root, SCAN_DIRS):
        if p.name == "__init__.py":
            continue
        rel = p.relative_to(root)
        dotted = ".".join(rel.with_suffix("").parts)
        stem = p.stem
        pats = [re.compile(r"\b" + re.escape(dotted) + r"\b"), re.compile(re.escape(str(rel))),
                re.compile(r"from\s+" + re.escape(".".join(rel.parts[:-1])) + r"\s+import\s+(?:\w+\s*,\s*)*" + re.escape(stem) + r"\b")]
        refs = {"code": [], "cron": [], "tests": []}
        for q, t in texts.items():
            if q == p:
                continue
            if any(x.search(t) for x in pats):
                kind = "cron" if q.name in ("run.sh", "crontab.txt") or q.suffix in (".service",) else "code"
                refs[kind].append(str(q.relative_to(root)))
        for q, t in tests.items():
            if any(x.search(t) for x in pats):
                refs["tests"].append(str(q.relative_to(root)))
        if refs["code"] or refs["cron"]:
            continue
        refs_docs = [str(q.relative_to(root)) for q, t in docs.items() if stem in t and (dotted in t or str(rel) in t or f"{stem}.py" in t)]
        ran = _ran_recently(conn, stem)
        touched = _git_last_touch(root, rel)
        out.append(_finding("unreferenced", str(rel),
                            "no production code, run.sh case, crontab line, command or routine refers to it"
                            + (" (only its tests do)" if refs["tests"] else ""),
                            {"refs_code": 0, "refs_cron": 0, "refs_tests": refs["tests"][:6], "refs_docs": refs_docs[:4],
                             "last_touched": touched, "ran_in_90d": ran, "lines": sum(1 for _ in p.open(errors="ignore"))}))
    return out


def cron_orphans(root=ROOT, live_crontab=None):
    """run.sh cases that no crontab line schedules (the file in ops/ or the live one)."""
    sh = root / "run.sh"
    if not sh.exists():
        return []
    cases = set()
    for m in re.finditer(r"^\s{4}([a-z_|]+)\)", sh.read_text(), re.M):
        cases.update(m.group(1).split("|"))
    scheduled = set()
    sources = {"ops/crontab.txt": (root / "ops" / "crontab.txt").read_text() if (root / "ops" / "crontab.txt").exists() else ""}
    if live_crontab is None:
        try:
            live_crontab = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.TimeoutExpired):
            live_crontab = ""
    sources["live crontab"] = live_crontab or ""
    for t in sources.values():
        scheduled.update(re.findall(r"run\.sh\s+([a-z_]+)", t))
    out = []
    for c in sorted(cases - scheduled):
        if c in ("harvest_lock",):
            continue
        comment = re.search(r"^\s{4}" + re.escape(c) + r"[a-z_|]*\)\s*#\s*(.*)$", sh.read_text(), re.M)
        out.append(_finding("cron_orphans", f"run.sh {c}", "a run.sh case that no crontab line schedules",
                            {"comment": (comment.group(1).strip()[:160] if comment else None),
                             "checked": list(sources)}))
    return out


def tests_cannot_fail(root=ROOT):
    """Test functions with no assert and no pytest.raises: they pass whatever the code does."""
    out = []
    for p in _test_files(root):
        try:
            tree = ast.parse(p.read_text(errors="ignore"))
        except SyntaxError:
            continue
        helpers = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and not n.name.startswith("test_") and any(isinstance(x, ast.Assert) for x in ast.walk(n))}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                body = ast.dump(node)
                has_assert = any(isinstance(n, ast.Assert) for n in ast.walk(node))
                raises = "attr='raises'" in body or "id='raises'" in body
                fails = "attr='fail'" in body or "attr='skip'" in body or "attr='xfail'" in body
                calls_helper = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in helpers
                                   for n in ast.walk(node))          # the assert lives in a helper it calls
                if not (has_assert or raises or fails or calls_helper):
                    out.append(_finding("tests_cannot_fail", f"{p.relative_to(root)}::{node.name}",
                                        "no assert and no pytest.raises: it cannot fail",
                                        {"lines": (node.end_lineno or node.lineno) - node.lineno + 1, "line": node.lineno}))
    return out


def flaky_steps(conn, days=FLAKY_DAYS):
    """Pipeline steps that FAILED and then SUCCEEDED on the same run date."""
    if conn is None:
        return []
    try:
        rows = conn.execute("""
            SELECT f.step_name, COUNT(DISTINCT f.run_date) AS days_flaky, MAX(f.run_date) AS last_day,
                   COUNT(DISTINCT f.run_date) * 1.0 / NULLIF((SELECT COUNT(DISTINCT run_date) FROM pipeline_log
                                                               WHERE step_name = f.step_name AND run_date >= date('now', ?)), 0) AS share
            FROM pipeline_log f JOIN pipeline_log s ON s.step_name = f.step_name AND s.run_date = f.run_date
                 AND s.status = 'SUCCESS' AND s.id > f.id
            WHERE f.status = 'FAILED' AND f.run_date >= date('now', ?)
            GROUP BY f.step_name ORDER BY days_flaky DESC""", (f"-{days} day", f"-{days} day")).fetchall()
    except sqlite3.Error:
        return []
    return [_finding("flaky_steps", step, f"failed and then succeeded on the same day, {n} day(s) in {days}",
                     {"days_flaky": n, "last_day": last, "share_of_run_days": round(share or 0, 2)}) for step, n, last, share in rows]


def _func_bodies(root):
    """{(module, name): (normalized body hash, lines)} for every top-level function in production code."""
    out = {}
    for p in _py_files(root):
        try:
            tree = ast.parse(p.read_text(errors="ignore"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body = [n for n in node.body if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant)
                                                     and isinstance(n.value.value, str))]
                if not body:
                    continue
                h = hashlib.sha1("\n".join(ast.dump(n) for n in body).encode()).hexdigest()
                out[(str(p.relative_to(root)), node.name)] = (h, (node.end_lineno or node.lineno) - node.lineno + 1)
    return out


def duplicates(root=ROOT):
    """Same body in two modules, or one name in three or more modules."""
    bodies = _func_bodies(root)
    by_hash, by_name = {}, {}
    for (mod, name), (h, lines) in bodies.items():
        if lines >= DUP_MIN_LINES:
            by_hash.setdefault(h, []).append((mod, name, lines))
        if not name.startswith("_") and name not in ("main", "compute", "run", "build", "fetch", "load", "render", "refresh", "check"):
            by_name.setdefault(name, set()).add(mod)
    out = []
    for h, items in by_hash.items():
        mods = {m for m, _n, _l in items}
        if len(mods) >= 2:
            out.append(_finding("duplicates", " = ".join(f"{m}:{n}" for m, n, _l in sorted(items)[:4]),
                                "the same function body in more than one module (docstrings ignored)",
                                {"copies": len(items), "lines": items[0][2]}))
    for name, mods in by_name.items():
        if len(mods) >= 3 and sum(1 for m in mods if not m.startswith("tools/")) >= 2:
            out.append(_finding("duplicates", f"{name}() in {len(mods)} modules",
                                "one function name defined in three or more modules: are they the same thing?",
                                {"modules": sorted(mods)[:8]}))
    return out


def stale_flags(root=ROOT, days=FLAG_DAYS):
    """True / False constants in config.py whose line has not changed in `days` (git blame)."""
    cfg = root / "config.py"
    if not cfg.exists():
        return []
    try:
        blame = subprocess.run(["git", "blame", "--line-porcelain", "config.py"], cwd=root, capture_output=True,
                               text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    when, out, cur = {}, [], {}
    for line in blame.splitlines():
        if line.startswith("committer-time "):
            cur["t"] = int(line.split()[1])
        elif line.startswith("\t"):
            cur["text"] = line[1:]
            m = re.match(r"^([A-Z][A-Z0-9_]{3,})\s*=\s*(True|False)\b", cur["text"])
            if m and "t" in cur:
                when[m.group(1)] = (date.fromtimestamp(cur["t"]), m.group(2))
            cur = {}
    cutoff = date.today() - timedelta(days=days)
    for name, (d, val) in sorted(when.items()):
        if d <= cutoff:
            out.append(_finding("stale_flags", f"config.{name} = {val}", f"a True/False constant unchanged since {d.isoformat()}",
                                {"since": d.isoformat(), "value": val, "days": (date.today() - d).days}))
    return out


def sticker_hits(conn, days=STICKER_DAYS):
    """{module: hits} from run_events notes 'sticker:<module>' in the window (ADR 0085 J6)."""
    if conn is None:
        return {}
    try:
        rows = conn.execute("SELECT substr(message, 9), COUNT(*) FROM run_events WHERE event = 'note' AND message LIKE 'sticker:%' "
                            "AND ts >= date('now', ?) GROUP BY 1", (f"-{days} day",)).fetchall()
    except sqlite3.Error:
        return {}
    return {m: n for m, n in rows}


PRIORITY = {"flaky_steps": 0, "cron_orphans": 1, "tests_cannot_fail": 2, "duplicates": 3, "stale_flags": 4, "unreferenced": 5}


def prioritise(findings):
    """Hidden failures first, then things a reader can settle quickly, then the pile of unreferenced
    modules oldest first; a brief shows the first 40, so the order decides what the seat sees."""
    def key(f):
        ev = f.get("evidence") or {}
        return (PRIORITY.get(f["probe"], 9), -(ev.get("days_flaky") or 0), -(ev.get("copies") or 0),
                ev.get("last_touched") or "9999", f["subject"])
    return sorted(findings, key=key)


def run(root=ROOT, db_path=None):
    """Every probe → {as_of, findings: [...], scanned: {...}}. A probe that cannot run is reported in
    `scanned`, never dropped."""
    import config
    path = db_path or config.DB_PATH
    conn = None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        pass
    findings, scanned = [], {}
    for name, fn in (("unreferenced", lambda: unreferenced(root, conn)), ("cron_orphans", lambda: cron_orphans(root)),
                     ("tests_cannot_fail", lambda: tests_cannot_fail(root)), ("flaky_steps", lambda: flaky_steps(conn)),
                     ("duplicates", lambda: duplicates(root)), ("stale_flags", lambda: stale_flags(root))):
        try:
            got = fn()
            findings += got
            scanned[name] = f"{len(got)} finding(s)"
        except Exception as e:                              # noqa: BLE001
            scanned[name] = f"could not run: {type(e).__name__}: {e}"[:200]
    stickers = sticker_hits(conn)
    for f in findings:
        f["sticker_hits_90d"] = stickers.get(f["subject"].replace("/", ".").removesuffix(".py"))
    if conn is not None:
        conn.close()
    findings = prioritise(findings)
    for i, f in enumerate(findings, 1):
        f["id"] = f"C{i}"
    return {"as_of": date.today().isoformat(), "findings": findings, "scanned": scanned,
            "scope": {"modules": len(_py_files(root, SCAN_DIRS)), "tests": len(_test_files(root))}}


# ─────────────────────────── the drill ───────────────────────────

def _scratch_tree(tmp):
    """A tiny repo-shaped tree with one real-looking tool, one caller, and a crontab."""
    root = Path(tmp)
    (root / "tools").mkdir()
    (root / "tests").mkdir()
    (root / "ops").mkdir()
    (root / "tools" / "alive.py").write_text("def main():\n    return 1\n")
    (root / "tools" / "caller.py").write_text("from tools import alive\n\ndef main():\n    return alive.main()\n")
    (root / "run.sh").write_text("case $JOB in\n    morning)  # the pipeline\n        echo 1 ;;\n    sweep)  # weekly\n        echo 2 ;;\nesac\n")
    (root / "ops" / "crontab.txt").write_text("0 3 * * * /x/run.sh morning\n0 9 * * 0 /x/run.sh sweep\n")
    (root / "tests" / "test_alive.py").write_text("def test_alive():\n    assert 1 == 1\n")
    (root / "config.py").write_text("DEBUG = False\n")
    (root / "a.py").write_text("def helper(x):\n" + "".join(f"    x = x + {i}\n" for i in range(9)) + "    return x\n")
    (root / "b.py").write_text("def other(y):\n    return y\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=d@x", "-c", "user.name=d", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=d@x", "-c", "user.name=d", "commit", "-q", "-m", "seed"], cwd=root, check=True)
    return root


# (name, what is planted, the planting function, the probe that must notice, the subject it must name)
PLANTS = [
    ("dead module", "a tool nothing refers to",
     lambda r, c: (r / "tools" / "nobody.py").write_text("def main():\n    return 0\n"),
     lambda r, c: unreferenced(r, None), "tools/nobody.py"),
    ("cron orphan", "a run.sh case with no crontab line",
     lambda r, c: (r / "run.sh").write_text((r / "run.sh").read_text().replace("esac", "    probe)  # temporary\n        echo 3 ;;\nesac")),
     lambda r, c: cron_orphans(r, live_crontab=""), "run.sh probe"),
    ("test that cannot fail", "a test with no assert",
     lambda r, c: (r / "tests" / "test_alive.py").write_text("def test_alive():\n    assert 1 == 1\n\ndef test_nothing():\n    x = 1\n    return x\n"),
     lambda r, c: tests_cannot_fail(r), "tests/test_alive.py::test_nothing"),
    ("duplicate body", "helper() copied into a second module",
     lambda r, c: (r / "b.py").write_text((r / "a.py").read_text().replace("helper", "helper2")),
     lambda r, c: duplicates(r), "a.py:helper = b.py:helper2"),
    ("flaky step", "a step that failed then succeeded on one day",
     lambda r, c: c.executemany("INSERT INTO pipeline_log (run_date, step_name, status) VALUES (?, ?, ?)",
                                [(date.today().isoformat(), "fetch_x", "FAILED"), (date.today().isoformat(), "fetch_x", "SUCCESS")]),
     lambda r, c: flaky_steps(c), "fetch_x"),
]


def drill():
    """Plant each kind of clutter in a scratch tree / run log and run the probe that must notice it.
    → {planted, caught, missed: [...], results: [...]}. Nothing outside the scratch is touched."""
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        root = _scratch_tree(tmp)
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE pipeline_log (id INTEGER PRIMARY KEY, run_date TEXT, step_name TEXT, status TEXT)")
        conn.execute("INSERT INTO pipeline_log (run_date, step_name, status) VALUES (?, 'fetch_y', 'SUCCESS')", (date.today().isoformat(),))
        for name, what, plant, probe, subject in PLANTS:
            before = {f["subject"] for f in probe(root, conn)}
            plant(root, conn)
            after = {f["subject"] for f in probe(root, conn)}
            results.append({"plant": name, "planted": what, "must_flag": subject,
                            "caught": subject in after and subject not in before})
    return {"planted": len(results), "caught": sum(r["caught"] for r in results),
            "missed": [r["plant"] for r in results if not r["caught"]], "results": results}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--drill", action="store_true")
    a = ap.parse_args()
    if a.drill:
        d = drill()
        if a.json:
            print(json.dumps(d))
        else:
            for r in d["results"]:
                print(f"  {'caught' if r['caught'] else 'MISSED':8s} {r['plant']}: {r['planted']}")
            print(f"\n{d['caught']} of {d['planted']} planted kinds of clutter caught")
        sys.exit(1 if d["missed"] else 0)
    out = run()
    if a.json:
        print(json.dumps(out, default=str))
        return
    for f in out["findings"]:
        ev = {k: v for k, v in f["evidence"].items() if v not in (None, [], 0)}
        print(f"  {f['id']:4s} {f['probe']:18s} {f['subject'][:70]:70s} {f['claim'][:60]}  {json.dumps(ev, default=str)[:120]}")
    print(f"\nscanned: " + "; ".join(f"{k}: {v}" for k, v in out["scanned"].items()) + f" · scope {out['scope']}")


if __name__ == "__main__":
    main()
