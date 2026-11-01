"""
Alpha Signal v2 — the architect's probes (plan 0032 stage 6; the system-architect seat on a cadence).

The architect guards seven building blocks (Node, Dataset, Host, Feature, Model, Check, View) and
five invariants (as-of, segment, kind-decides-write, post-checks decide success, politeness; ADR 0052,
ADR 0054, docs/reference/architecture.md). Three of them have ratchet tests on every push
(tests/test_invariant_ratchets.py); the rest were a rule someone had to remember. These probes
make the mechanical part of the review run every week, with the file and line behind each finding:

  layer_map          an import that crosses the block layering the wrong way (a source importing a
                     signal, a signal importing the cockpit, a check importing a page …)
  single_caller      a function of 15+ lines that exactly one place in another module calls, or a
                     pass-through wrapper (its body is one return of one call): inline candidates
  base_classes       a class with a non-exception base or an abstractmethod (ADR 0004: no frameworks,
                     no base classes), and any YAML file in the tree
  tier_literals      a hard-coded tier list outside config.py (CLAUDE.md: tiers are data)
  twice_stated       the same ALL_CAPS constant bound to a literal in two or more modules
  sleep_outside_door time.sleep in a module other than sources/_http.py (politeness is the door's job)
  undeclared_io      a pipeline step whose module reads or writes a registered table its
                     PIPELINE_STEPS entry does not declare (post-checks decide success only if
                     the graph knows the write)
  hotspots           a module over 1,500 lines or a function over 120 lines

Nothing here changes a file or writes to the database. `drill()` plants each kind in a scratch tree
and checks the probe that must notice it does.

Usage:
    python -m tools.arch_probes               # findings, as a table
    python -m tools.arch_probes --json
    python -m tools.arch_probes --drill
"""
import argparse
import ast
import json
import re
import sys
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SKIP_PARTS = {"tests", "docs", "_archive", ".archify", ".claude", "output", "data", ".devlib", "graphify-out", "backups",
              "node_modules", "__pycache__", ".git", ".playwright-mcp", "notebooks"}
CODE_DIRS = ("", "tools", "sources", "signals", "output", "scoring", "checks", "validators", "cockpit", "cockpit_ops",
             "alpha_mcp", "datamodel", "eligibility", "mf", "scripts")

# ── the layering: which block a module belongs to, and which imports are the wrong way ──
# Lower blocks must not reach up. A source gathers data; a feature computes from as-of frames; a
# model ranks; a check judges; a view shows. Core (db, config, hosts, runlog, tables, feeds) is
# below everything.
BLOCKS = [
    # validators/ are the write contracts db.py applies (ADR 0055) and views.py is the read model every
    # block reads through (plan 0017): both are core, not a check or a page
    ("core", ("db.py", "config.py", "hosts.py", "runlog.py", "tables.py", "feeds.py", "formatting.py", "lineage.py",
              "validators/", "views.py")),
    ("source", ("sources/",)),
    ("feature", ("signals/", "pit.py", "factors.py", "eligibility/")),
    ("model", ("scoring/", "portfolio_construction.py")),
    ("check", ("checks/",)),
    ("view", ("cockpit/", "cockpit_ops/", "output/", "alpha_mcp/", "org.py", "org_chat.py", "ask.py")),
]
VIEW_DIRS = ("cockpit/", "cockpit_ops/", "alpha_mcp/", "output/", "org", "ask.py")      # thin wrappers are the pattern here
FORBIDDEN = {                      # from-block → blocks it must not import
    "core": {"source", "feature", "model", "check", "view"},
    "source": {"feature", "model", "check", "view"},
    "feature": {"model", "check", "view", "source"},
    "model": {"check", "view", "source"},
    "check": {"view"},
}
SINGLE_CALLER_MIN_LINES = 40
HOTSPOT_MODULE_LINES = 1500
HOTSPOT_FUNC_LINES = 120
TIER_WORDS = ("LARGE", "MID", "SMALL", "MICRO")


def _py_files(root):
    out = []
    for d in CODE_DIRS:
        base = root / d if d else root
        if base.is_dir():
            out += [p for p in base.glob("*.py") if not any(x in SKIP_PARTS for x in p.relative_to(root).parts[:-1])]
    return sorted(set(out))


def _block(rel):
    for name, prefixes in BLOCKS:
        if any(rel == pfx or rel.startswith(pfx) for pfx in prefixes):
            return name
    return None


def _parse(p):
    try:
        return ast.parse(p.read_text(errors="ignore"))
    except (SyntaxError, OSError):
        return None


def _finding(probe, subject, claim, evidence, touches=()):
    return {"probe": probe, "subject": subject, "claim": claim, "evidence": evidence, "touches": list(touches)}


# ─────────────────────────── probes ───────────────────────────

def _imports(tree):
    """[(module name, line)] for every import in a tree (first segment resolved to a file path later)."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [(a.name, n.lineno) for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.append((n.module, n.lineno))
            out += [(f"{n.module}.{a.name}", n.lineno) for a in n.names]
    return out


def layer_map(root=ROOT):
    files = _py_files(root)
    known = {".".join(p.relative_to(root).with_suffix("").parts): str(p.relative_to(root)) for p in files}
    out = []
    for p in files:
        rel = str(p.relative_to(root))
        src = _block(rel)
        if src not in FORBIDDEN:
            continue
        tree = _parse(p)
        if tree is None:
            continue
        seen = set()
        for mod, line in _imports(tree):
            target = known.get(mod) or known.get(mod.rsplit(".", 1)[0]) if "." in mod else known.get(mod)
            if not target or target == rel or (line, target) in seen:
                continue
            seen.add((line, target))
            dst = _block(target)
            if dst in FORBIDDEN[src]:
                out.append(_finding("layer_map", f"{rel}:{line}", f"a {src} module imports a {dst} module ({target})",
                                    {"from_block": src, "to_block": dst, "imports": target, "line": line}))
    return out


def _defs_and_calls(root):
    """({(module, name): lines}, {name: {module: count}}) over production code."""
    defs, calls = {}, defaultdict(lambda: defaultdict(int))
    for p in _py_files(root):
        rel = str(p.relative_to(root))
        tree = _parse(p)
        if tree is None:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs[(rel, node.name)] = (node.end_lineno or node.lineno) - node.lineno + 1
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                f = n.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                if name:
                    calls[name][rel] += 1
            elif isinstance(n, ast.Attribute):          # a reference without a call (passed as a callback) counts too
                calls[n.attr][rel] += 0
    return defs, calls


def single_caller(root=ROOT):
    defs, calls = _defs_and_calls(root)
    out = []
    for (mod, name), lines in defs.items():
        if name.startswith("_") or name in ("main", "compute", "run", "build", "fetch", "check") or lines < SINGLE_CALLER_MIN_LINES:
            continue
        if mod.startswith(VIEW_DIRS):
            continue
        users = {m: c for m, c in calls.get(name, {}).items() if m != mod and c > 0}
        if len(users) == 1 and sum(users.values()) == 1 and sum(c for m, c in calls.get(name, {}).items() if m == mod) == 0:
            (caller, _n), = users.items()
            out.append(_finding("single_caller", f"{mod}:{name}", f"{lines} lines, called exactly once, from {caller}: inline candidate",
                                {"lines": lines, "caller": caller}))
    # pass-through wrappers: def f(...): return g(...)
    for p in _py_files(root):
        rel = str(p.relative_to(root))
        if rel.startswith(VIEW_DIRS):
            continue
        tree = _parse(p)
        if tree is None:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                body = [n for n in node.body if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant))]
                if len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Call):
                    callee = body[0].value.func
                    cname = callee.id if isinstance(callee, ast.Name) else callee.attr if isinstance(callee, ast.Attribute) else "?"
                    if cname != node.name:
                        out.append(_finding("single_caller", f"{rel}:{node.name}", f"a pass-through wrapper around {cname}()",
                                            {"wraps": cname, "line": node.lineno}))
    return out


_EXC_BASES = {"Exception", "RuntimeError", "ValueError", "KeyError", "TypeError", "OSError", "IOError", "LookupError",
              "BaseException", "Warning", "NamedTuple", "Enum", "IntEnum", "StrEnum", "TypedDict", "Protocol", "object"}


def base_classes(root=ROOT):
    out = []
    for p in _py_files(root):
        rel = str(p.relative_to(root))
        tree = _parse(p)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = [b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else "?" for b in node.bases]
                odd = [b for b in bases if b not in _EXC_BASES and not b.endswith(("Error", "Exception", "Warning"))]
                abstract = any(isinstance(d, ast.Name) and d.id == "abstractmethod" or isinstance(d, ast.Attribute) and d.attr == "abstractmethod"
                               for f in node.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) for d in f.decorator_list)
                if odd or abstract:
                    out.append(_finding("base_classes", f"{rel}:{node.name}",
                                        ("inherits from " + ", ".join(odd)) if odd else "declares an abstractmethod",
                                        {"bases": bases, "abstract": abstract, "line": node.lineno}))
    for q in root.rglob("*.y*ml"):
        if not any(x in SKIP_PARTS for x in q.relative_to(root).parts):
            out.append(_finding("base_classes", str(q.relative_to(root)), "a YAML file (ADR 0004: config is a Python dict)", {}))
    return out


_TIER_LIST = re.compile(r"[\[(]\s*(['\"])(" + "|".join(TIER_WORDS) + r")\1\s*,\s*(['\"])(" + "|".join(TIER_WORDS) + r")\3")


def tier_literals(root=ROOT):
    out = []
    for p in _py_files(root):
        rel = str(p.relative_to(root))
        if rel == "config.py":
            continue
        for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            if _TIER_LIST.search(line) and not line.lstrip().startswith("#"):
                out.append(_finding("tier_literals", f"{rel}:{i}", "a hard-coded tier list; tiers are data (config.TIERS)",
                                    {"line": i, "text": line.strip()[:120]}, touches=["the tiers"]))
    return out


def twice_stated(root=ROOT):
    where = defaultdict(dict)
    for p in _py_files(root):
        rel = str(p.relative_to(root))
        tree = _parse(p)
        if tree is None:
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                v = node.value.value if isinstance(node.value, ast.Constant) else None
                if name.isupper() and len(name) > 2 and v is not None and not isinstance(v, bool) and (not isinstance(v, str) or len(v) <= 40):
                    where[name][rel] = v
    out = []
    for name, mods in where.items():
        if len(mods) >= 2 and name not in ("ROOT", "PROJECT_ROOT", "TODAY", "NOW", "DB_PATH"):
            vals = sorted({repr(v) for v in mods.values()})
            out.append(_finding("twice_stated", f"{name} in {len(mods)} modules",
                                "the same constant bound in more than one module" + (": with DIFFERENT values" if len(vals) > 1 else ""),
                                {"modules": sorted(mods)[:8], "values": vals[:4]}))
    return out


def sleep_outside_door(root=ROOT):
    out = []
    for p in _py_files(root):
        rel = str(p.relative_to(root))
        if rel in ("sources/_http.py", "runlog.py"):
            continue
        tree = _parse(p)
        if tree is None:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                f = n.func
                if (isinstance(f, ast.Attribute) and f.attr == "sleep" and isinstance(f.value, ast.Name) and f.value.id == "time") or \
                   (isinstance(f, ast.Name) and f.id == "sleep"):
                    out.append(_finding("sleep_outside_door", f"{rel}:{n.lineno}", "time.sleep outside sources/_http: pacing belongs to the host door",
                                        {"line": n.lineno}, touches=["politeness"]))
    return out


_SQL_READ = re.compile(r"\b(?:FROM|JOIN)\s+\[?([a-z_][a-z0-9_]*)\]?", re.I)
_SQL_WRITE = re.compile(r"\b(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM)\s+\[?([a-z_][a-z0-9_]*)\]?", re.I)
_DF_WRITE = re.compile(r"\b(?:insert_df|upsert_df|replace_df)\(\s*(?:[a-z_]+\s*,\s*)?['\"]([a-z_][a-z0-9_]*)['\"]", re.I)


def undeclared_io(root=ROOT, steps=None, tables=None):
    """Pipeline steps whose module touches a registered table the step does not declare."""
    if steps is None or tables is None:
        import config
        import tables as registry
        steps, tables = config.PIPELINE_STEPS, set(registry.TABLES)
    out = []
    by_module = defaultdict(lambda: {"reads": set(), "writes": set()})
    for s in steps:
        if s.get("module"):
            by_module[s["module"]]["reads"] |= set(s.get("reads", []))
            by_module[s["module"]]["writes"] |= set(s.get("writes", [])) | ({s["table"]} if s.get("table") else set())
    for s in steps:
        mod = s.get("module")
        if not mod:
            continue
        p = root / (mod.replace(".", "/") + ".py")
        if not p.exists():
            continue
        text = p.read_text(errors="ignore")
        tree = _parse(p)
        sql = "\n".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|JOIN)\b", n.value)) if tree else ""
        reads = {t for t in _SQL_READ.findall(sql) if t in tables}
        writes = {t for t in _SQL_WRITE.findall(sql) if t in tables} | {t for t in _DF_WRITE.findall(text) if t in tables}
        decl_r, decl_w = by_module[mod]["reads"], by_module[mod]["writes"]
        und_w = sorted(writes - decl_w)
        und_r = sorted(reads - decl_r - decl_w - writes)
        if und_w:
            out.append(_finding("undeclared_io", f"{s['name']} writes {', '.join(und_w)}", "the module writes a table its PIPELINE_STEPS entry does not declare",
                                {"module": mod, "undeclared_writes": und_w, "declared_writes": sorted(decl_w)}, touches=["post-checks decide success"]))
        if und_r:
            out.append(_finding("undeclared_io", f"{s['name']} reads {', '.join(und_r[:5])}", "the module reads a table its PIPELINE_STEPS entry does not declare",
                                {"module": mod, "undeclared_reads": und_r[:10], "declared_reads": sorted(decl_r)[:10]}))
    return out


def hotspots(root=ROOT):
    out = []
    for p in _py_files(root):
        rel = str(p.relative_to(root))
        n = sum(1 for _ in p.open(errors="ignore"))
        if n > HOTSPOT_MODULE_LINES:
            out.append(_finding("hotspots", rel, f"{n:,} lines in one module", {"lines": n}))
        tree = _parse(p)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                L = (node.end_lineno or node.lineno) - node.lineno + 1
                if L > HOTSPOT_FUNC_LINES:
                    out.append(_finding("hotspots", f"{rel}:{node.name}", f"a {L}-line function", {"lines": L, "line": node.lineno}))
    return out


PRIORITY = {"undeclared_io": 0, "layer_map": 1, "sleep_outside_door": 2, "tier_literals": 3, "base_classes": 4,
            "twice_stated": 5, "single_caller": 6, "hotspots": 7}


def prioritise(findings):
    return sorted(findings, key=lambda f: (PRIORITY.get(f["probe"], 9), f["subject"]))


def run(root=ROOT):
    findings, scanned = [], {}
    for name, fn in (("layer_map", layer_map), ("single_caller", single_caller), ("base_classes", base_classes),
                     ("tier_literals", tier_literals), ("twice_stated", twice_stated), ("sleep_outside_door", sleep_outside_door),
                     ("undeclared_io", undeclared_io), ("hotspots", hotspots)):
        try:
            got = fn(root)
            findings += got
            scanned[name] = f"{len(got)} finding(s)"
        except Exception as e:                              # noqa: BLE001
            scanned[name] = f"could not run: {type(e).__name__}: {e}"[:200]
    findings = prioritise(findings)
    for i, f in enumerate(findings, 1):
        f["id"] = f"A{i}"
    return {"as_of": date.today().isoformat(), "findings": findings, "scanned": scanned, "scope": {"modules": len(_py_files(root))}}


# ─────────────────────────── the drill ───────────────────────────

def _scratch_tree(tmp):
    root = Path(tmp)
    for d in ("sources", "signals", "checks", "cockpit", "tools"):
        (root / d).mkdir()
    (root / "db.py").write_text("def get_db():\n    return None\n")
    (root / "config.py").write_text("TIERS = {}\nCRORE = 1e7\n")
    (root / "sources" / "feed.py").write_text("import db\n\ndef fetch_all():\n    return db.get_db()\n")
    (root / "signals" / "sig.py").write_text("def compute(frame):\n    return frame\n")
    (root / "cockpit" / "page.py").write_text("from signals import sig\n\ndef render():\n    return sig.compute(1)\n")
    (root / "tools" / "util.py").write_text("def helper(x):\n" + "".join(f"    x = x + {i}\n" for i in range(45)) + "    return x\n")
    (root / "tools" / "user.py").write_text("from tools import util\n\ndef go():\n    return util.helper(1)\n\ndef again():\n    return util.helper(2)\n")
    return root


# (name, what is planted, plant(root), probe, subject that must appear)
PLANTS = [
    ("layer crossing", "a source importing a signal",
     lambda r: (r / "sources" / "feed.py").write_text("import db\nfrom signals import sig\n\ndef fetch_all():\n    return sig.compute(db.get_db())\n"),
     layer_map, "sources/feed.py:2"),
    ("single caller", "a 47-line helper called from exactly one place",
     lambda r: (r / "tools" / "user.py").write_text("from tools import util\n\ndef go():\n    return util.helper(1)\n"),
     single_caller, "tools/util.py:helper"),
    ("base class", "a class inheriting from a home-made base",
     lambda r: (r / "tools" / "base.py").write_text("class Base:\n    pass\n\nclass Thing(Base):\n    pass\n"),
     base_classes, "tools/base.py:Thing"),
    ("tier literal", "a hard-coded tier list in a signal",
     lambda r: (r / "signals" / "sig.py").write_text("def compute(frame):\n    for t in ['LARGE', 'MID', 'SMALL']:\n        pass\n    return frame\n"),
     tier_literals, "signals/sig.py:2"),
    ("twice stated", "CRORE bound again in a second module",
     lambda r: (r / "tools" / "money.py").write_text("CRORE = 1e7\n\ndef cr(x):\n    return x / CRORE\n"),
     twice_stated, "CRORE in 2 modules"),
    ("sleep outside the door", "time.sleep in a source",
     lambda r: (r / "sources" / "slow.py").write_text("import time\n\ndef fetch():\n    time.sleep(2)\n"),
     sleep_outside_door, "sources/slow.py:4"),
    ("undeclared write", "a step module writing a table its entry does not declare",
     lambda r: (r / "sources" / "feed.py").write_text("import db\n\ndef fetch_all():\n    c = db.get_db()\n    c.execute('INSERT INTO prices VALUES (1)')\n"),
     lambda r: undeclared_io(r, steps=[{"name": "fetch_feed", "module": "sources.feed", "reads": [], "writes": ["feed_log"]}],
                             tables={"prices", "feed_log"}), "fetch_feed writes prices"),
]


def drill():
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        root = _scratch_tree(tmp)
        for name, what, plant, probe, subject in PLANTS:
            before = {f["subject"] for f in probe(root)}
            plant(root)
            after = {f["subject"] for f in probe(root)}
            results.append({"plant": name, "planted": what, "must_flag": subject, "caught": subject in after and subject not in before})
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
            print(f"\n{d['caught']} of {d['planted']} planted faults caught")
        sys.exit(1 if d["missed"] else 0)
    out = run()
    if a.json:
        print(json.dumps(out, default=str))
        return
    for f in out["findings"]:
        print(f"  {f['id']:5s} {f['probe']:18s} {f['subject'][:64]:64s} {f['claim'][:70]}")
    print("\nscanned: " + "; ".join(f"{k}: {v}" for k, v in out["scanned"].items()) + f" · {out['scope']}")


if __name__ == "__main__":
    main()
