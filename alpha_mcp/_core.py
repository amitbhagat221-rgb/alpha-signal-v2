"""
Shared plumbing for the alpha_mcp servers (plan 0016): read-only DB wiring, the
JSON output contract, the size cap, pagination, stock resolution and the
`mcp_calls` audit.

Read-only by construction: `install_readonly()` swaps `db.get_db` (and every
module-level copy of it) for a `mode=ro` + `query_only` connection, and points
runlog and the cockpit's disk cache away from shared state. The research and ops
servers call it before importing views/cockpit; nothing they run can write.
The one exception is `audit()`: its own connection, whose authorizer permits
INSERT INTO mcp_calls and nothing else.
"""
import contextlib
import datetime as dt
import functools
import hashlib
import json
import math
import os
import sqlite3
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAX_TOKENS = 20_000          # per-result budget (Claude Code's hard cap is 25K)
CHARS_PER_TOKEN = 3          # conservative for JSON full of short keys and digits
MAX_CHARS = MAX_TOKENS * CHARS_PER_TOKEN

_READONLY = False


# ═══════════════════════════ read-only wiring ═══════════════════════════

@contextmanager
def _ro_get_db():
    """db.get_db's read-only twin: same context-manager shape, cannot write."""
    import db
    conn = sqlite3.connect(f"file:{db.DB_PATH}?mode=ro", uri=True, timeout=30)
    conn.execute("PRAGMA query_only = ON")
    try:
        yield conn
    finally:
        conn.close()


def _ro_runlog_conn():
    import runlog
    return sqlite3.connect(f"file:{runlog.DB_PATH}?mode=ro", uri=True, timeout=1)


def install_readonly():
    """Make this process unable to write the DB. Idempotent. Call before importing
    views / cockpit where possible; module-level `from db import get_db` copies that
    already exist are replaced too."""
    global _READONLY
    os.environ.setdefault("COCKPIT_CACHE_DIR", tempfile.mkdtemp(prefix="alpha_mcp_cache_"))
    import db
    import runlog
    original = db.get_db
    if original is not _ro_get_db:
        for mod in list(sys.modules.values()):
            if getattr(mod, "get_db", None) is original:
                mod.get_db = _ro_get_db
    runlog._conn = _ro_runlog_conn
    _READONLY = True


def assert_readonly():
    if not _READONLY:
        raise RuntimeError("alpha_mcp: install_readonly() was not called")


# ═══════════════════════════ output contract ═══════════════════════════

def _num(x):
    if x is None or isinstance(x, bool):
        return x
    if isinstance(x, int):
        return x
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        return None
    if x == int(x) and abs(x) < 1e15:
        return int(x)
    return float(f"{x:.6g}")


def jsonable(obj):
    """DataFrame → records, numpy → Python, NaN/inf → null, dates → ISO, floats → 6
    significant digits. Recurses through dicts, lists and tuples."""
    import numpy as np
    import pandas as pd
    if isinstance(obj, pd.DataFrame):
        return [jsonable(r) for r in obj.to_dict("records")]
    if isinstance(obj, pd.Series):
        return jsonable(obj.to_dict())
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return _num(obj)
    if isinstance(obj, (dt.datetime, dt.date, pd.Timestamp)):
        return None if pd.isna(obj) else obj.isoformat()
    if obj is pd.NaT:
        return None
    if isinstance(obj, bytes):
        return obj.decode("utf-8", "replace")
    return obj


def _size(obj):
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def _largest_list(obj, path=()):
    """(len, path) of the longest list anywhere in obj."""
    best = (0, None)
    if isinstance(obj, list):
        best = (len(obj), path)
        items = enumerate(obj)
    elif isinstance(obj, dict):
        items = obj.items()
    else:
        return best
    for k, v in items:
        cand = _largest_list(v, path + (k,))
        if cand[0] > best[0]:
            best = cand
    return best


def cap(payload, max_chars=MAX_CHARS):
    """Keep a result under the token budget: halve the longest list until it fits,
    and say so in `truncated` (the caller should page or narrow the query)."""
    if _size(payload) <= max_chars:
        return payload
    cut = []
    for _ in range(40):
        n, path = _largest_list(payload)
        if path is None or n <= 1:
            break
        parent = payload
        for k in path[:-1]:
            parent = parent[k]
        lst = parent[path[-1]] if path else payload
        keep = max(1, n // 2)
        if path:
            parent[path[-1]] = lst[:keep]
        else:
            payload = lst[:keep]
        cut.append("/".join(map(str, path)) or "<root>")
        if _size(payload) <= max_chars:
            break
    if isinstance(payload, dict):
        payload["truncated"] = {"lists_cut": sorted(set(cut)),
                                "hint": "result exceeded the size budget; page (offset/limit) or narrow the query"}
    return payload


def page(items, limit, offset=0, max_limit=200):
    """Slice a list into a page: {items, total, offset, limit, next_offset}."""
    limit = max(1, min(int(limit), max_limit))
    offset = max(0, int(offset))
    total = len(items)
    chunk = items[offset:offset + limit]
    nxt = offset + limit if offset + limit < total else None
    return {"items": chunk, "total": total, "offset": offset, "limit": limit, "next_offset": nxt}


# ═══════════════════════════ stocks ═══════════════════════════

def resolve_sid(stock):
    """A Tickertape sid or an NSE ticker (case-insensitive) → sid. Raises a clear
    error for anything else, with near matches, so a typo is never an empty success."""
    import db
    s = str(stock or "").strip()
    if not s:
        raise ValueError("stock is required (a sid like 'RELI' or a ticker like 'RELIANCE')")
    r = db.one("SELECT sid FROM stocks WHERE sid = ?", [s]) or \
        db.one("SELECT sid FROM stocks WHERE UPPER(ticker) = UPPER(?)", [s]) or \
        db.one("SELECT sid FROM stocks WHERE UPPER(sid) = UPPER(?)", [s])
    if r:
        return r["sid"]
    near = db.rows("SELECT sid, ticker, name FROM stocks WHERE ticker LIKE ? OR name LIKE ? LIMIT 5",
                   [f"%{s}%", f"%{s}%"])
    hint = "; ".join(f"{n['ticker']} (sid {n['sid']}, {n['name']})" for n in near)
    raise ValueError(f"unknown stock {s!r}" + (f" — did you mean: {hint}" if hint else
                                               " — use search_stocks to find it"))


# ═══════════════════════════ audit ═══════════════════════════

_AUDIT_WARNED = False


def _audit_authorizer(action, a1, a2, dbname, source):
    if action == sqlite3.SQLITE_INSERT and a1 == "mcp_calls":
        return sqlite3.SQLITE_OK
    if action in (sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT, sqlite3.SQLITE_TRANSACTION,
                  sqlite3.SQLITE_PRAGMA, sqlite3.SQLITE_FUNCTION):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def audit(profile, tool, args, rows, ms, error=None):
    """Append one mcp_calls row. Telemetry: never raises, never waits more than 1 s
    for a lock, and the connection can insert into mcp_calls and nothing else."""
    global _AUDIT_WARNED
    try:
        import db
        h = hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16]
        conn = sqlite3.connect(db.DB_PATH, timeout=1)
        try:
            conn.set_authorizer(_audit_authorizer)
            conn.execute(
                "INSERT INTO mcp_calls (ts, profile, role, tool, args_hash, rows, ms, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
                 profile, os.environ.get("ALPHA_MCP_ROLE"), tool, h, rows, int(ms),
                 (str(error)[:500] if error else None)))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:                                   # noqa: BLE001
        if not _AUDIT_WARNED:
            _AUDIT_WARNED = True
            sys.stderr.write(f"[alpha_mcp] audit write skipped ({type(e).__name__}: {e})\n")


def _count(result):
    if isinstance(result, dict):
        for k in ("items", "rows", "picks"):
            if isinstance(result.get(k), list):
                return len(result[k])
        return 1
    return len(result) if isinstance(result, list) else 1


def tool(mcp, profile, readonly=True, name=None, **ann):
    """Register fn as an MCP tool with the shared contract: stdout kept off the stdio
    channel, output made JSON-safe and capped, every call audited. Errors propagate
    (FastMCP returns them as isError results) after being audited. The decorated
    function stays directly callable (tests call it without the MCP layer)."""
    from mcp.types import ToolAnnotations

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.monotonic()
            out = err = None
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    out = cap(jsonable(fn(*args, **kwargs)))
                return out
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                raise
            finally:
                audit(profile, name or fn.__name__, {"args": args, "kwargs": kwargs},
                      None if err else _count(out),
                      (time.monotonic() - t0) * 1000, err)

        @functools.wraps(fn)
        def as_text(*args, **kwargs):
            # compact JSON on the wire: FastMCP's own dict rendering is indented (~35% more tokens)
            return json.dumps(wrapper(*args, **kwargs), ensure_ascii=False, separators=(",", ":"))

        annotations = ToolAnnotations(readOnlyHint=readonly, destructiveHint=False,
                                      openWorldHint=False, **ann)
        mcp.tool(name=name, annotations=annotations, structured_output=False)(as_text)
        return wrapper
    return deco


def today_iso():
    return dt.date.today().isoformat()
