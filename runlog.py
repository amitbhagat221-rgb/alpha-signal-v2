"""
Alpha Signal v2 — Run log: structured, queryable events for every ingestor run
(plan 0018 "logs an agent can act on").

Every step / cron job / manual source run gets a run_id. Events land in ONE table,
`run_events`, so a human, the ops page, or an outside agent over MCP can ask
"what exactly failed, where, and what did the upstream say?" with plain SQL:

    run_start     step, feed, module, argv, pid, git sha
    request       a failed / retried HTTP call: host, redacted URL, status, attempt,
                  latency, bytes, and a redacted snippet of the response body
    item_error    one harvest item failed: item key, error, exact file:line, frames
    exception     the run raised: error, symptom class A-H, file:line of the failure
                  point, the innermost frame in the feed's own module, traceback frames
    summary       a harvest loop finished: items, ok, errors, rows written
    note          anything a module wants to say (level INFO/WARN/ERROR)
    run_end       status, duration, per-host request/status counters, retries,
                  rows written per table, and the tail of what the run printed
    run_exit      the shell's exit code for a cron job (run.sh `logged`)

Nothing here can break a harvest: every write is best-effort, capped per run
(no log floods), and secrets are redacted (query params, auth headers, cookies,
and the literal values of secret environment variables).

Hooks (no per-module code needed): sources/_http.polite_request + pace +
run_harvester, db.insert_df / upsert_df, pipeline.run_step, tools/canary, and
run.sh `logged` (exports ALPHA_STEP / ALPHA_RUN_ID to the child process).

CLI:
    python -m runlog runs   [--feed F | --step S] [--limit N]
    python -m runlog events [--run ID | --feed F] [--level ERROR] [--since 24h]
    python -m runlog bundle F [--json]    # incident bundle for an agent / human
Plain functions (ADR 0004).
"""

import atexit
import collections
import json
import os
import re
import sqlite3
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
try:
    from config import DB_PATH as _CONFIG_DB
except Exception:                                         # pragma: no cover
    _CONFIG_DB = ROOT / "data" / "alpha_signal.db"
DB_PATH = Path(os.environ.get("ALPHA_RUNLOG_DB") or _CONFIG_DB)

CAPS = {"request": 50, "item_error": 200, "note": 100}   # events per run, then counted only
TAIL_LINES = 120
SNIPPET_BYTES = 600
RETENTION_DAYS = 90
LOUD_STATUS = {401, 403, 407, 429}                          # + every 5xx and network error

_lock = threading.RLock()
_ctx = {}                     # run_id, step, feed, module, t0, ended
_counts = None
_tail = collections.deque(maxlen=TAIL_LINES)
_warned = False


# ─────────────────────────────── redaction ───────────────────────────────

_SECRET_PARAM = re.compile(
    r"(?i)\b((?:[a-z_]*token|api_?key|key|secret|password|passwd|pwd|session(?:id)?|csrf(?:token)?|"
    r"auth|signature|sig|cookie|enctoken|checksum)=)[^&\s\"'<>]+")
_SECRET_HEADER = re.compile(r"(?i)\b(authorization|cookie|set-cookie|x-api-key|x-kite-apikey)(\s*[:=]\s*)[^\n\r]+")
_BEARER = re.compile(r"(?i)\b(bearer|token)\s+[a-z0-9._\-]{12,}")
_SECRET_ENV = re.compile(r"(?i)(key|token|secret|password|passwd|pwd|cookie|session)")


def _secret_values():
    return sorted({v for k, v in os.environ.items() if _SECRET_ENV.search(k) and v and len(v) >= 6},
                  key=len, reverse=True)


def redact(text):
    """Strip secrets from any text that is about to be logged."""
    if text is None:
        return None
    s = str(text)
    for v in _secret_values():
        s = s.replace(v, "***")
    s = _SECRET_PARAM.sub(r"\1***", s)
    s = _SECRET_HEADER.sub(r"\1\2***", s)
    return _BEARER.sub(r"\1 ***", s)


# ─────────────────────────────── failure location ───────────────────────────────

def _rel(path):
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return None


_LIB_ROOTS = tuple(str(Path(p).resolve()) for p in {sys.base_prefix, sys.prefix, sys.exec_prefix})


def _is_lib(path):
    p = str(path)
    return "site-packages" in p or "dist-packages" in p or p.startswith(_LIB_ROOTS) or p.startswith("<")


def frames_of(exc):
    """Traceback frames as dicts (innermost last): `repo` = inside this repo,
    `lib` = a library / stdlib frame (never the failure point)."""
    out = []
    for f in traceback.extract_tb(exc.__traceback__):
        rel = _rel(f.filename)
        out.append({"file": rel or f.filename, "line": f.lineno, "func": f.name,
                    "code": (f.line or "").strip()[:200], "repo": rel is not None,
                    "lib": rel is None and _is_lib(f.filename)})
    return out


def location(frames, module=None):
    """(failure_point, origin): the innermost repo frame, and the innermost frame in
    the feed's own module (sources/x.py, not the shared door) — 'where it broke' and
    'which line of the feed's code led there'."""
    ours = [f for f in frames if not f.get("lib") and f["file"] != "runlog.py"]
    repo = [f for f in ours if f["repo"]]
    point = ours[-1] if ours else (frames[-1] if frames else None)
    own = [f for f in repo if f["file"].startswith("sources/") and f["file"] not in ("sources/_http.py",)]
    if module:
        mod_file = module.replace(".", "/") + ".py"
        own = [f for f in repo if f["file"] == mod_file] or own
    origin = own[-1] if own else (repo[-1] if repo else point)
    fmt = (lambda f: f"{f['file']}:{f['line']} in {f['func']}" if f else None)
    return fmt(point), fmt(origin)


def classify_exception(exc):
    """(status, symptom A-H) for a raised exception. Our own bugs are ERROR (they
    must not page as an upstream outage); transport errors are A/E; anything the
    payload did to a parser (KeyError, ValueError, JSON decode…) is shape drift D."""
    name, msg = type(exc).__name__, str(exc).lower()
    if name == "ContractViolation":
        return "FAIL", "F"                      # the batch looked like data but was garbage
    if isinstance(exc, (ImportError, NameError, AttributeError, SyntaxError)):
        return "ERROR", None
    mod = type(exc).__module__ or ""
    if mod.startswith(("requests", "urllib3", "curl_cffi", "http", "socket")) or isinstance(exc, (ConnectionError, TimeoutError)):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (401,):
            return "FAIL", "C"
        if status == 404:
            return "FAIL", "B"
        if status == 429:
            return "FAIL", "G"
        if status == 403 or any(k in msg for k in ("reset", "403", "forbidden", "refused")):
            return "FAIL", "A"
        return "FAIL", "E"
    if "credit balance" in msg or "429" in msg or "rate limit" in msg:
        return "FAIL", "G"
    if isinstance(exc, PermissionError) or re.search(r"\b(login|unauthori[sz]ed|authenticat\w*|session expired)\b", msg):
        return "FAIL", "C"
    if "0 of " in msg and "items returned data" in msg:
        return "FAIL", "E"
    if name == "JSONDecodeError" or "expecting value" in msg:
        return "FAIL", "A"                    # non-JSON body: almost always a bot/HTML page
    return "FAIL", "D"


# ─────────────────────────────── writing ───────────────────────────────

def _conn():
    c = sqlite3.connect(DB_PATH, timeout=5)
    c.execute("PRAGMA busy_timeout=5000")
    return c


def _emit(event, level="INFO", **f):
    """Insert one event; never raises (a logging failure must not fail a harvest)."""
    global _warned
    run_id = _ctx.get("run_id") or _adhoc()
    row = {"run_id": run_id, "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
           "step": _ctx.get("step"), "feed": _ctx.get("feed"), "event": event, "level": level,
           "host": f.get("host"), "url": redact(f.get("url")), "http_status": f.get("http_status"),
           "attempt": f.get("attempt"), "duration_ms": f.get("duration_ms"),
           "item": redact(f.get("item")), "rows": f.get("rows"), "symptom": f.get("symptom"),
           "error_type": f.get("error_type"), "message": redact(f.get("message")),
           "location": f.get("location"),
           "detail": redact(json.dumps(f["detail"], default=str)) if f.get("detail") is not None else None}
    try:
        with _conn() as c:
            c.execute(f"INSERT INTO run_events ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                      list(row.values()))
    except Exception as e:                                  # noqa: BLE001
        if not _warned:
            _warned = True
            sys.__stderr__.write(f"[runlog] could not write event ({type(e).__name__}: {e}) — continuing\n")
    return row


def _adhoc():
    """An event outside any run (a library call from the cockpit, a REPL): tag it
    with an ad-hoc id — never hook exit handlers in a process we don't own."""
    global _counts
    if _counts is None:
        _counts = _new_counts()
    _ctx.setdefault("run_id", f"adhoc:{Path(sys.argv[0]).name or 'python'}:{os.getpid()}")
    _ctx.setdefault("step", _ctx["run_id"].split(":")[1])
    return _ctx["run_id"]


def _new_counts():
    return {"requests": collections.defaultdict(collections.Counter),   # host → {status: n}
            "retries": collections.Counter(), "bytes": collections.Counter(),
            "latency_ms": collections.Counter(), "lib_calls": collections.Counter(),
            "writes": collections.Counter(), "suppressed": collections.Counter(),
            "emitted": collections.Counter(), "items": collections.Counter()}


def _capped(kind):
    with _lock:
        if _counts is None:
            return False
        if _counts["emitted"][kind] >= CAPS.get(kind, 10 ** 9):
            _counts["suppressed"][kind] += 1
            return True
        _counts["emitted"][kind] += 1
        return False


# ─────────────────────────────── stdout/stderr tail ───────────────────────────────

class _Tee:
    """Writes through to the real stream; keeps the last lines for run_end."""

    def __init__(self, stream):
        self._s, self._buf = stream, ""

    def write(self, s):
        try:
            self._buf += s
            *lines, self._buf = self._buf.split("\n")
            _tail.extend(line[:400] for line in lines if line.strip())
        except Exception:                                   # noqa: BLE001
            pass
        return self._s.write(s)

    def __getattr__(self, name):
        return getattr(self._s, name)


def _install_tee():
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout)
    if not isinstance(sys.stderr, _Tee):
        sys.stderr = _Tee(sys.stderr)


# ─────────────────────────────── run lifecycle ───────────────────────────────

def _git_sha():
    try:
        head = (ROOT / ".git" / "HEAD").read_text().strip()
        if head.startswith("ref: "):
            return (ROOT / ".git" / head[5:]).read_text().strip()[:10]
        return head[:10]
    except OSError:
        return None


def feed_for(step=None, module=None):
    """The feeds.FEEDS key a step / cron log name / module belongs to."""
    try:
        import feeds
        for name in feeds.FEEDS:
            if step and step in feeds.log_steps(name):
                return name
        if module:
            for name, f in feeds.FEEDS.items():
                if module in (f.get("modules") or []):
                    return name
    except Exception:                                       # noqa: BLE001
        pass
    return None


def start(step, module=None, feed=None, run_id=None, adopt_env=False):
    """Open a run (resets counters and the output tail). Returns the run_id.
    adopt_env: a job's entry point (tools/canary) joins the run run.sh `logged`
    opened for it (ALPHA_STEP / ALPHA_RUN_ID) instead of starting a second one."""
    if adopt_env and os.environ.get("ALPHA_RUN_ID"):
        step, run_id = os.environ.get("ALPHA_STEP") or step, os.environ["ALPHA_RUN_ID"]
    global _counts
    with _lock:
        _install_tee()
        _counts = _new_counts()
        _tail.clear()
        rid = run_id or f"{step}:{datetime.now(timezone.utc):%Y%m%dT%H%M%S}:{os.getpid()}"
        _ctx.clear()
        _ctx.update(run_id=rid, step=step, module=module, t0=time.monotonic(), ended=False,
                    feed=feed or feed_for(step, module))
    _emit("run_start", detail={"module": module, "argv": sys.argv, "pid": os.getpid(), "git": _git_sha(),
                               "parent_run": os.environ.get("ALPHA_RUN_ID") if run_id is None else None})
    return rid


def end(status, rows=None, error=None):
    """Close the run with its counters and the tail of what it printed."""
    if not _ctx.get("run_id") or _ctx.get("ended"):
        return None
    with _lock:
        c = _counts or _new_counts()
        detail = {
            "duration_s": round(time.monotonic() - _ctx["t0"], 2),
            "requests": {h: dict(v) for h, v in c["requests"].items()},
            "retries": dict(c["retries"]), "bytes": dict(c["bytes"]),
            "avg_latency_ms": {h: round(c["latency_ms"][h] / max(1, sum(c["requests"][h].values())))
                               for h in c["requests"]},
            "library_calls": dict(c["lib_calls"]), "rows_written": dict(c["writes"]),
            "items": dict(c["items"]), "suppressed_events": dict(c["suppressed"]),
            "output_tail": list(_tail)[-(60 if status != "SUCCESS" else 15):],
        }
        _ctx["ended"] = True
    lvl = "INFO" if status == "SUCCESS" else "ERROR"
    return _emit("run_end", lvl, rows=rows if rows is not None else (sum(c["writes"].values()) or None),
                 message=redact(error) if error else status, detail=detail, error_type=status)


def exception(exc, item=None, event="exception", level="ERROR"):
    """Record a raised exception with its exact failure point."""
    frames = frames_of(exc)
    point, origin = location(frames, _ctx.get("module"))
    status, symptom = classify_exception(exc)
    resp = getattr(exc, "response", None)
    detail = {"frames": frames[-12:], "origin": origin, "classified": status}
    if resp is not None:
        detail["response"] = _response_detail(resp)
    return _emit(event, level, item=item, symptom=symptom, error_type=type(exc).__name__,
                 message=f"{type(exc).__name__}: {str(exc)[:800]}", location=point,
                 http_status=getattr(resp, "status_code", None), detail=detail)


def _response_detail(resp):
    try:
        body = (resp.content or b"")[:SNIPPET_BYTES]
        return {"status": resp.status_code, "content_type": resp.headers.get("content-type"),
                "bytes": len(resp.content or b""), "snippet": redact(body.decode("utf-8", "replace"))}
    except Exception:                                       # noqa: BLE001
        return None


def _auto_start():
    """A source run by hand (python -m sources.x) or by run.sh `logged` (ALPHA_STEP)
    opens its own run and closes it at exit (maybe_auto_start decides)."""
    step = os.environ.get("ALPHA_STEP")
    main = sys.modules.get("__main__")
    spec = getattr(main, "__spec__", None)
    module = spec.name if spec else None
    if not step:
        step = f"manual:{module or Path(sys.argv[0]).stem}"
    rid = start(step, module=module, run_id=os.environ.get("ALPHA_RUN_ID"))
    _hook_exit()
    return rid


_hooked = False


def _hook_exit():
    global _hooked
    if _hooked:
        return
    _hooked = True
    prev_hook, prev_exit = sys.excepthook, sys.exit

    def _excepthook(tp, val, tb):
        try:
            exception(val)
            end("FAILED", error=f"{tp.__name__}: {val}")
        finally:
            prev_hook(tp, val, tb)

    def _exit(code=0):
        _ctx["exit_code"] = code
        prev_exit(code)

    sys.excepthook, sys.exit = _excepthook, _exit
    atexit.register(lambda: end("SUCCESS" if _ctx.get("exit_code") in (None, 0) else "FAILED",
                                error=None if _ctx.get("exit_code") in (None, 0) else f"exit {_ctx.get('exit_code')}"))


def maybe_auto_start():
    """Called at import by sources/_http: open the run eagerly for cron children and
    `python -m sources.x`, so even a clean run leaves run_start / run_end."""
    main = sys.modules.get("__main__")
    spec = getattr(main, "__spec__", None)
    if _ctx.get("run_id"):
        return
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        return
    if os.environ.get("ALPHA_STEP") or (spec and spec.name.startswith("sources.")):
        _auto_start()


# ─────────────────────────────── hooks (called by the shared door) ───────────────────────────────

def request(host, url, status=None, attempt=0, duration_ms=None, nbytes=None, error=None,
            response=None, will_retry=False):
    """One HTTP attempt through the host door. Counted always; logged when it is
    loud (401/403/407/429/5xx/network error) — capped per run."""
    if not _ctx.get("run_id"):
        maybe_auto_start()
    with _lock:
        if _counts is not None:
            _counts["requests"][host][str(status if status is not None else type(error).__name__ if error else "?")] += 1
            if will_retry:
                _counts["retries"][host] += 1
            if nbytes:
                _counts["bytes"][host] += nbytes
            if duration_ms:
                _counts["latency_ms"][host] += duration_ms
    loud = error is not None or (status is not None and (status in LOUD_STATUS or status >= 500))
    if not loud or _capped("request"):
        return
    symptom = ("C" if status in (401, 407) else "A" if status == 403 else "G" if status == 429
               else "E" if (status and status >= 500) else classify_exception(error)[1] if error else None)
    _emit("request", "WARN" if will_retry else "ERROR", host=host, url=url, http_status=status,
          attempt=attempt, duration_ms=duration_ms, symptom=symptom,
          error_type=type(error).__name__ if error else None,
          message=(f"{type(error).__name__}: {error}" if error else f"HTTP {status}")
                  + (" — will retry" if will_retry else ""),
          detail={"response": _response_detail(response)} if response is not None else None)


def library_call(host):
    with _lock:
        if _counts is not None:
            _counts["lib_calls"][host] += 1


def item_error(label, item, exc):
    with _lock:
        if _counts is not None:
            _counts["items"]["error"] += 1
    if _capped("item_error"):
        return
    exception(exc, item=f"{label}: {item!r}"[:300], event="item_error", level="WARN")


def item_failed(label, item, message, symptom=None, exc=None):
    """A harvest item that failed without (or after catching) an exception — for
    modules with their own loop (not run_harvester). Records the feed-code line
    that detected it, so the event still says WHERE."""
    if exc is not None:
        return item_error(label, item, exc)
    with _lock:
        if _counts is not None:
            _counts["items"]["error"] += 1
    if _capped("item_error"):
        return
    caller = sys._getframe(1)
    rel = _rel(caller.f_code.co_filename) or caller.f_code.co_filename
    _emit("item_error", "WARN", item=f"{label}: {item!r}"[:300], symptom=symptom, error_type="ItemFailed",
          message=str(message)[:800], location=f"{rel}:{caller.f_lineno} in {caller.f_code.co_name}")


def item_ok(n=1):
    with _lock:
        if _counts is not None:
            _counts["items"]["ok"] += n


def harvest_summary(label, total, ok, errors, written):
    lvl = "ERROR" if total and ok == 0 else ("WARN" if errors else "INFO")
    _emit("summary", lvl, rows=written, message=f"{label}: {total} items · {ok} with data · {errors} errors · {written} rows written",
          detail={"label": label, "total": total, "ok": ok, "errors": errors, "written": written})


def count_write(table, n):
    with _lock:
        if _counts is not None and n:
            _counts["writes"][table] += int(n)


def note(message, level="INFO", **detail):
    if level == "INFO" and _capped("note"):
        return
    _emit("note", level, message=message, detail=detail or None)


def exit_code(run_id, step, rc, started=None):
    """run.sh `logged`: the job's shell exit code, under the same run_id."""
    _ctx.update(run_id=run_id, step=step, feed=feed_for(step))
    _emit("run_exit", "INFO" if str(rc) == "0" else "ERROR", message=f"exit {rc}",
          detail={"rc": int(rc), "started": started})


def prune(days=RETENTION_DAYS):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        with _conn() as c:
            return c.execute("DELETE FROM run_events WHERE ts < ?", (cutoff,)).rowcount
    except sqlite3.Error:
        return 0


# ─────────────────────────────── querying ───────────────────────────────

def _rows(sql, params=()):
    with _conn() as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, params)]


def _since(s):
    if not s:
        return None
    m = re.fullmatch(r"(\d+)([hd])", s)
    if m:
        delta = timedelta(hours=int(m[1])) if m[2] == "h" else timedelta(days=int(m[1]))
        return (datetime.now(timezone.utc) - delta).isoformat()
    return s


def events(run_id=None, feed=None, step=None, level=None, since=None, limit=200):
    q, p = ["1=1"], []
    for col, v in (("run_id", run_id), ("feed", feed), ("step", step)):
        if v:
            q.append(f"{col} = ?")
            p.append(v)
    if level:
        q.append("level IN ('ERROR')" if level == "ERROR" else "level IN ('ERROR','WARN')")
    if since:
        q.append("ts >= ?")
        p.append(_since(since))
    rows = _rows(f"SELECT * FROM run_events WHERE {' AND '.join(q)} ORDER BY id DESC LIMIT ?", (*p, limit))
    for r in rows:
        if r.get("detail"):
            try:
                r["detail"] = json.loads(r["detail"])
            except ValueError:
                pass
    return rows


def runs(feed=None, step=None, limit=20):
    """One row per run: its start, end (or INCOMPLETE — killed / still running) and
    how many WARN / ERROR events it produced."""
    q, p = [], []
    if feed:
        q.append("feed = ?")
        p.append(feed)
    if step:
        q.append("step = ?")
        p.append(step)
    where = ("WHERE " + " AND ".join(q)) if q else ""
    return _rows(f"""
        SELECT run_id, MIN(step) step, MIN(feed) feed, MIN(ts) started, MAX(ts) last_event,
               COALESCE(MAX(CASE WHEN event = 'run_end' THEN error_type END),
                        MAX(CASE WHEN event = 'run_exit' THEN message END), 'INCOMPLETE') status,
               MAX(CASE WHEN event = 'run_end' THEN rows END) rows,
               SUM(level = 'ERROR') n_error, SUM(level = 'WARN') n_warn
        FROM run_events {where} GROUP BY run_id ORDER BY MAX(id) DESC LIMIT ?""", (*p, limit))


def bundle(feed, n_runs=5):
    """Everything an outside agent needs to diagnose and instruct a fix for one feed,
    in one JSON-able dict: what the feed is, its routes and code, its canary verdicts,
    recent runs, the failing run's events (exact file:line, frames, redacted upstream
    responses, output tail), past incidents and the playbook for the symptom class."""
    import feeds
    f = feeds.FEEDS[feed]
    try:
        canaries = _rows("SELECT run_date, checked_at, status, symptom, http_status, n_rows, fingerprint, baseline, detail "
                         "FROM feed_checks WHERE feed = ? ORDER BY id DESC LIMIT 3", (feed,))
        for c in canaries:
            c["detail"] = json.loads(c["detail"]) if c.get("detail") else None
    except sqlite3.Error:
        canaries = []
    recent = runs(feed=feed, limit=n_runs)
    ok = ("SUCCESS", "exit 0")
    failing = next((r for r in recent if r["n_error"] or r["n_warn"] or r["status"] not in ok), None)
    fail_events = events(run_id=failing["run_id"], limit=300) if failing else []
    symptoms = sorted({e["symptom"] for e in fail_events if e.get("symptom")} |
                      {c["symptom"] for c in canaries if c.get("symptom")})
    locations = collections.Counter(e["location"] for e in fail_events if e.get("location"))
    raw_dir = ROOT / "data" / "raw" / (f.get("canary") or "")
    return {
        "feed": feed, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "what": f.get("what"), "family": f.get("family"), "status": f.get("status"),
        "tier": feeds.tier(feed), "schedule": f.get("schedule"), "cadence": f.get("cadence"),
        "routes": f.get("routes"), "hosts": f.get("hosts"), "writes": f.get("writes"),
        "code": {"modules": [m.replace(".", "/") + ".py" for m in f.get("modules") or []],
                 "canary": f"sources/canaries.py:{f.get('canary')}" if f.get("canary") else None,
                 "failure_points": locations.most_common(5)},
        "pit": f.get("pit"), "tos": f.get("tos"), "fallback_plan": f.get("fallback_plan"), "notes": f.get("notes"),
        "canary_recent": canaries,
        "runs_recent": recent,
        "failing_run": failing,
        "failing_run_events": [e for e in fail_events if e["level"] in ("ERROR", "WARN") or e["event"] in ("run_start", "run_end")][:120],
        "symptom_playbook": {s: dict(zip(("name", "signature", "first_response"), feeds.SYMPTOM_CLASSES[s]))
                             for s in symptoms if s in feeds.SYMPTOM_CLASSES},
        "past_incidents": [dict(zip(("date", "feed", "class", "symptom", "cause", "fix", "ref"), i))
                           for i in feeds.INCIDENTS if i[1] == feed],
        "raw_responses": sorted(str(p.relative_to(ROOT)) for p in raw_dir.glob("*")) if f.get("canary") and raw_dir.exists() else [],
        "verify_with": ([f"flock -n /tmp/alpha_signal_harvest.lock python -m tools.canary --feed {feed}"]
                        + [f"python -m {m} --help   # then a 3-item smoke (--limit 3 / --sid …)" for m in f.get("modules") or []]),
        "rules": ["never bypass captcha/auth/WAF", "never lower hosts.HOSTS politeness", "never run two harvesters at once",
                  "fix on a branch with a fixture + passing smoke; do not merge"],
    }


def _print_bundle_md(b):
    p = print
    p(f"# Incident bundle — {b['feed']} ({b['tier']}, {b['status']})\n\n{b['what']}\n")
    p(f"- schedule: {', '.join(b['schedule'] or []) or 'UNSCHEDULED'} · cadence {b['cadence']} · writes {', '.join(b['writes'] or [])}")
    p(f"- code: {', '.join(b['code']['modules'])}" + (f" · canary {b['code']['canary']}" if b['code']['canary'] else ""))
    for r in b["routes"] or []:
        p(f"- route {r['kind']}: {r['id']} @{r.get('host')} — {r.get('how')}" + (f"  [DEAD: {r['dead']}]" if r.get("dead") else ""))
    p("\n## Canary (latest)")
    for c in b["canary_recent"]:
        p(f"- {c['checked_at']} {c['status']} {c.get('symptom') or ''} http={c.get('http_status')} rows={c.get('n_rows')}")
        for g in (c.get("detail") or {}).get("gates", []):
            if g[1] != "PASS":
                p(f"    gate {g[0]}: {g[1]} [{g[2]}] {g[3]}")
    p("\n## Recent runs")
    for r in b["runs_recent"]:
        p(f"- {r['started']} {r['status']:10} rows={r['rows']} errors={r['n_error']} warns={r['n_warn']}  ({r['run_id']})")
    if b["failing_run"]:
        p(f"\n## Problem run {b['failing_run']['run_id']} ({b['failing_run']['status']}, "
          f"{b['failing_run']['n_error']} errors, {b['failing_run']['n_warn']} warnings)")
        for e in reversed(b["failing_run_events"]):
            if e["event"] == "run_end":
                d = e.get("detail") or {}
                p(f"- run_end {e['error_type']}: requests={d.get('requests')} retries={d.get('retries')} rows={d.get('rows_written')}")
                for line in d.get("output_tail", [])[-15:]:
                    p(f"    | {line}")
            elif e["event"] != "run_start":
                p(f"- {e['ts']} {e['level']} {e['event']} [{e.get('symptom') or '-'}] {e.get('message')}")
                if e.get("location"):
                    p(f"    at {e['location']}" + (f"  (feed code: {e['detail'].get('origin')})" if isinstance(e.get('detail'), dict) and e['detail'].get('origin') else ""))
                resp = (e.get("detail") or {}).get("response") if isinstance(e.get("detail"), dict) else None
                if resp:
                    p(f"    upstream {resp.get('status')} {resp.get('content_type')}: {str(resp.get('snippet'))[:200]!r}")
    if b["symptom_playbook"]:
        p("\n## Playbook")
        for s, v in b["symptom_playbook"].items():
            p(f"- {s} {v['name']}: {v['first_response']}")
    if b["past_incidents"]:
        p("\n## Past incidents")
        for i in b["past_incidents"]:
            p(f"- {i['date']} [{i['class']}] {i['symptom']} → {i['fix']} ({i['ref']})")
    p("\n## Verify with\n" + "\n".join(f"- `{v}`" for v in b["verify_with"]))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Query the run log (plan 0018)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("runs")
    r.add_argument("--feed")
    r.add_argument("--step")
    r.add_argument("--limit", type=int, default=20)
    e = sub.add_parser("events")
    e.add_argument("--run")
    e.add_argument("--feed")
    e.add_argument("--step")
    e.add_argument("--level", choices=["ERROR", "WARN"])
    e.add_argument("--since", help="24h, 7d or an ISO timestamp")
    e.add_argument("--limit", type=int, default=50)
    b = sub.add_parser("bundle")
    b.add_argument("feed")
    b.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "runs":
        for x in runs(a.feed, a.step, a.limit):
            print(f"{x['started']}  {x['status']:10} err={x['n_error']:<3} warn={x['n_warn']:<3} rows={x['rows']}  {x['run_id']}")
    elif a.cmd == "events":
        for x in reversed(events(a.run, a.feed, a.step, a.level, a.since, a.limit)):
            print(f"{x['ts']} {x['level']:5} {x['event']:10} {x.get('feed') or '-':22} [{x.get('symptom') or '-'}] "
                  f"{x.get('message') or ''}" + (f"  @ {x['location']}" if x.get("location") else ""))
    else:
        bb = bundle(a.feed)
        print(json.dumps(bb, indent=1, default=str)) if a.json else _print_bundle_md(bb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
