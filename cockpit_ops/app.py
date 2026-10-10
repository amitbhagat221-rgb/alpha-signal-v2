"""
Alpha Signal v2 — Ops cockpit (port 3001).

Standalone service for the Ops surface: Health, Feeds, Flow, Boardroom, Options,
SQL console. Imports its API surface from
cockpit_ops/api.py, which depends only on cockpit/_shared.py (not cockpit/api.py).

The main trading cockpit on port 3000 continues to run independently.
You can restart this service to fix an Ops-only bug without touching
the trading cockpit.

Run: uvicorn cockpit_ops.app:app --host 0.0.0.0 --port 3001 --reload
Production: systemctl restart alpha-cockpit-ops
"""

import json
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from webauth import LoginRequired
from preview import PreviewReadOnly, add_redirects
from cockpit._shared import CachedStatic, COCKPIT_STATIC, make_templates, nav_model, prewarm
from cockpit_ops import api, pages

OPS_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Alpha Signal Ops")
# Gzip every response > 1KB. /system is 1.2MB plaintext HTML and compresses
# to ~150KB; for users on WAN (especially the Bengaluru → Oracle Cloud round
# trip) this is the difference between 3-5s and sub-second download.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(LoginRequired, app_name="Ops console")  # webauth.py — password login (review F5)
app.add_middleware(PreviewReadOnly)                        # preview.py — refuses writes when COCKPIT_PREVIEW=1
# Shared static assets from the main cockpit. No need to duplicate CSS/JS.
app.mount("/static", CachedStatic(directory=COCKPIT_STATIC), name="static")   # cache rules: _shared.CachedStatic

# Ops pages first, then cockpit/templates for the shared base.html /
# _components.html / _icons.html (single copies — the ops forks went stale).
templates = make_templates([OPS_DIR / "templates"],
                           nav=nav_model(pages.PAGES, pages.OTHER_APP, pages.BRAND), role="ops")


def _ticks(text):
    """Escape a plain-words string and render its `backticked` parts as code, so a fix like
    "run `run.sh canary`" reads as a command and not with raw backticks."""
    from markupsafe import Markup, escape
    return Markup(re.sub(r"`([^`]+)`", r'<code class="mono">\1</code>', str(escape(text if text is not None else ""))))


templates.env.filters["ticks"] = _ticks


@app.get("/api/search")
def api_search(q: str = ""):
    """The rail stock search; same lookup as the main cockpit (its results open there)."""
    from cockpit import api as cockpit_api
    return cockpit_api.search_stocks(q) if len(q) >= 2 else []


# ────────────── Startup cache warmer ──────────────
# Same parallel-prewarm pattern as cockpit/app.py, but for Ops-only
# endpoints. Cuts cold start on /system from ~19s to first-render-ready.
@app.on_event("startup")
def _prewarm_cache():
    prewarm([
        ("data_freshness",     lambda: api.get_data_freshness()),
        ("db_summary",         lambda: api.get_db_summary()),
        ("data_health_scores", lambda: api.get_data_health_scores(force=False)),
        ("flow_overview",      lambda: api.get_flow_overview()),
        ("health_overview",    lambda: api.get_health_overview()),
        ("pipeline_status",    lambda: api.get_pipeline_status()),
        ("feed_overview",      lambda: api.get_feed_overview()),
        ("org_overview",       lambda: api.get_org_overview()),
    ], label="ops cache-warm")


# ────────────── Pages ──────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Ops landing page → redirect to Health Center."""
    return await system(request)


@app.get("/system", response_class=HTMLResponse)
async def system(request: Request, refresh: int = 0):
    """Health Center page. Only the Overview ships with the page; every other tab is a partial
    (/system/tab/<name>) fetched the first time it opens. ?refresh=1 recomputes the table scores."""
    import asyncio

    if refresh:
        await asyncio.to_thread(api.get_data_health_scores, True)
    try:
        overview = await asyncio.to_thread(api.get_health_overview)
    except Exception:
        import traceback; traceback.print_exc()
        overview = None
    return templates.TemplateResponse(request, "system.html", {"page": "system", "overview": overview})


@app.get("/system/tab/{name}", response_class=HTMLResponse)
async def system_tab(request: Request, name: str):
    """One Health tab as an HTML fragment. Each reads the same cached views the full page used to."""
    import asyncio
    if name not in SYSTEM_TABS:
        return HTMLResponse("unknown tab", status_code=404)
    ctx = await asyncio.to_thread(_system_tab_context, name)
    return templates.TemplateResponse(request, f"system_tabs/{name}.html", ctx)


SYSTEM_TABS = ("checks", "inventory")


def _system_tab_context(name):
    """What each Health tab's fragment renders (all cached views; see api)."""
    ctx = {}
    if name == "checks":
        ctx["overview"] = api.get_health_overview()
    elif name == "inventory":
        from db import DOMAIN_ORDER
        health = api.get_data_freshness()
        by_domain = {}
        for row in health:
            by_domain.setdefault(row.get("domain") or "Other", []).append(row)
        ctx["health"] = health
        ctx["columns"] = api.get_table_columns()
        ctx["inventory_groups"] = [{"domain": d, "rows": by_domain[d]} for d in DOMAIN_ORDER if d in by_domain]
    return ctx


@app.get("/feeds/tab/data", response_class=HTMLResponse)
async def feeds_tab_data(request: Request):
    """Feeds › Data: universe coverage, the database-health card and per-table scores, fetched on first open."""
    import asyncio
    ctx = await asyncio.to_thread(_data_tab_context)
    return templates.TemplateResponse(request, "feeds_data.html", ctx)


def _data_tab_context():
    ctx = {"overview": api.get_health_overview()}
    # Cold cache: the scan takes minutes. Answer at once with what exists and let the scan finish in the background.
    scores, summary = api._data_health_scores.peek(), api.get_db_summary.peek()
    if scores is None or summary is None:
        for fn in (api._data_health_scores, api.get_db_summary):
            if fn.peek() is None:
                fn.warm()
        ctx["scan_running"] = True
    ctx["summary"], ctx["health_scores"] = summary, scores
    return ctx


@app.get("/feeds/data/{table}", response_class=HTMLResponse)
async def feeds_data_table(request: Request, table: str):
    """One table's per-factor health diagnostic, fetched when its row is expanded."""
    import asyncio
    scores = await asyncio.to_thread(api.get_data_health_scores, False)
    t = next((x for x in (scores or {}).get("tables", []) if x["table"] == table), None)
    if t is None:
        return HTMLResponse("unknown table", status_code=404)
    return templates.TemplateResponse(request, "feeds_data_table.html", {"t": t})


@app.get("/flow/tab/log", response_class=HTMLResponse)
async def flow_tab_log(request: Request):
    """Flow › Pipeline log: the broken streaks and the 7-day step log, fetched on first open."""
    import asyncio
    ctx = await asyncio.to_thread(lambda: {"overview": api.get_health_overview(), "pipeline": api.get_pipeline_status()})
    return templates.TemplateResponse(request, "flow_log.html", ctx)


@app.get("/flow", response_class=HTMLResponse)
def flow_page(request: Request):
    overview = api.get_flow_overview()
    try:
        run = api.get_run_summary()
    except Exception:                                 # noqa: BLE001 — the header degrades, the page still renders
        run = None
    return templates.TemplateResponse(request, "flow.html", {
        "page": "flow", "run": run, **overview,
    })


@app.get("/options", response_class=HTMLResponse)
def options_page(request: Request):
    """Option-premium paper book (plan 0022): the pre-registered rule, open and settled
    paper trades, live-quote slippage, Kite login status. Data from option_book.page_data."""
    import option_book
    return templates.TemplateResponse(request, "options.html", {"page": "options", **option_book.page_data()})


@app.get("/api/options")
def api_options():
    import option_book
    return option_book.page_data()


@app.get("/kite/login")
def kite_login():
    """One tap to Zerodha's login; Kite sends the browser back to /kite/callback."""
    from fastapi.responses import RedirectResponse
    from sources.kite_pull import _env
    return RedirectResponse(f"https://kite.zerodha.com/connect/login?v=3&api_key={_env('KITE_API_KEY')}")


@app.get("/kite/callback")
def kite_callback(request_token: str = "", status: str = ""):
    """Kite's redirect after login: exchange the one-time request_token for today's session
    (cached for the 15:20 IST quote job). Read-only use; the token never reaches the page."""
    from fastapi.responses import RedirectResponse
    from kiteconnect import KiteConnect
    from sources import _http
    from sources.kite_pull import _cache_token, _env
    if status != "success" or not request_token:
        return RedirectResponse("/options?kite=failed", status_code=303)
    try:                                            # the cached session is replaced only on success
        kc = KiteConnect(api_key=_env("KITE_API_KEY"))
        with _http.pace("kite"):
            data = kc.generate_session(request_token, api_secret=_env("KITE_API_SECRET"))
        _cache_token(data["access_token"])
    except Exception:                               # noqa: BLE001 — shown on the page, not raised
        return RedirectResponse("/options?kite=failed", status_code=303)
    return RedirectResponse("/options?kite=ok", status_code=303)


@app.get("/feeds", response_class=HTMLResponse)
def feeds_page(request: Request):
    """Data Supply — feeds by family, canaries, resilience, discovery funnel,
    known issues (plan 0018). Same checks.feeds verdicts as the health email."""
    return templates.TemplateResponse(request, "feeds.html", {
        "page": "feeds", **api.get_feed_overview(),
    })


@app.get("/api/feeds")
def api_feeds():
    return api.get_feed_overview()


@app.get("/api/feeds/{feed}/incident")
def api_feed_incident(feed: str):
    """Incident bundle for one feed (runlog.bundle): registry facts, code paths,
    canary verdicts, recent runs, the failing run's events with exact file:line and
    redacted upstream responses, the symptom playbook and past incidents — what an
    outside agent needs to diagnose and instruct a fix."""
    import feeds
    import runlog
    if feed not in feeds.FEEDS:
        return JSONResponse({"error": f"unknown feed {feed}"}, status_code=404)
    return JSONResponse(json.loads(json.dumps(runlog.bundle(feed), default=str)))


@app.get("/api/runs")
def api_runs(feed: str = None, step: str = None, limit: int = 20):
    import runlog
    return runlog.runs(feed=feed, step=step, limit=min(limit, 200))


@app.get("/api/run-events")
def api_run_events(run: str = None, feed: str = None, step: str = None, level: str = None,
                   since: str = None, limit: int = 100):
    """Filterable run log: ?feed=bse_announcements&level=ERROR&since=24h"""
    import runlog
    return json.loads(json.dumps(runlog.events(run, feed, step, level, since, min(limit, 500)), default=str))


@app.get("/sw.js")
def service_worker():
    """The Boardroom app's service worker, served from the root so it can control every page."""
    from fastapi.responses import FileResponse
    return FileResponse(COCKPIT_STATIC / "boardroom" / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/org", response_class=HTMLResponse)
def org_page(request: Request, mfrom: str = None, mto: str = None, mrole: str = None, mpage: int = 1):
    """Boardroom — the agent org (plan 0019): what is waiting for the CEO, the role
    tree with each seat's scorecard, the latest board pack and the desk memos.
    mfrom / mto / mrole: the memo archive's date range and employee filter; mpage: its page."""
    ov = api.get_org_overview(mfrom, mto, mrole)       # cached; the run flag is the one live bit
    return templates.TemplateResponse(request, "org.html",
                                      {"page": "org", **ov, "running": api.org_running(),
                                       "mpage": max(1, mpage), "memo_per_page": MEMO_PER_PAGE})


MEMO_PER_PAGE = 12


@app.get("/org/memo/{doc_id}", response_class=HTMLResponse)
def org_memo(request: Request, doc_id: int):
    """One memo's full text, fetched when its row in the archive is opened."""
    m = api.get_org_memo(doc_id)
    if m is None:
        return HTMLResponse("not a memo", status_code=404)
    return templates.TemplateResponse(request, "org_memo.html", {"m": m})


@app.get("/api/org")
def api_org():
    return api.get_org_overview()


@app.post("/api/org/decide")
async def api_org_decide(request: Request):
    """The CEO's decision on an inbox item (an ask or a hypothesis card):
    {"item_id": 123, "verdict": "approve" | "reject" | "park", "note": "..."}.
    Recorded as a child org.decision document; it changes nothing else."""
    import org
    body = await request.json()
    try:
        result = org.decide(int(body["item_id"]), body.get("verdict"), body.get("note"), body.get("option"))
        api.invalidate_org_overview()
        return result
    except (ValueError, KeyError, TypeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


def _org_call(fn, *args):
    try:
        return api._clean(fn(*args))
    except (ValueError, KeyError, TypeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/org/house-style")
def api_org_house_style():
    """The writing style every seat follows: the text, and what the server enforces regardless."""
    import org
    return _org_call(org.house_style_view)


@app.post("/api/org/house-style")
async def api_org_house_style_save(request: Request):
    import org
    body = await request.json()
    return _org_call(org.save_house_style, body.get("text"), body.get("note"))


@app.get("/api/org/seat/{role}")
def api_org_seat(role: str):
    """One seat's settings for the editor: variables, prompts, history, and what is fixed in code."""
    import org
    if role not in org.ROLES:
        return JSONResponse({"error": f"unknown seat {role}"}, status_code=404)
    return _org_call(org.seat_settings, role)


@app.post("/api/org/seat/{role}")
async def api_org_seat_save(role: str, request: Request):
    """Save the CEO's changes to a seat: {"changes": {"model": "opus", "directive": "...", "prompt": "..."},
    "note": "why"}. Variables are checked against closed lists; prompts are written to the seat's file."""
    import org
    body = await request.json()
    return _org_call(org.save_settings, role, body.get("changes") or {}, body.get("note"))


@app.post("/api/org/seat/{role}/reset")
def api_org_seat_reset(role: str):
    import org
    return _org_call(org.reset_settings, role)


@app.post("/api/org/seat/{role}/restore")
async def api_org_seat_restore(role: str, request: Request):
    import org
    body = await request.json()
    return _org_call(org.restore_settings, role, int(body.get("doc_id") or 0))


@app.get("/api/org/conversations")
def api_org_conversations(role: str = None):
    """Chat history: every stored conversation, with one seat (?role=) or with everyone."""
    import org_chat
    return _org_call(org_chat.conversations, role or None)


@app.get("/api/org/chat/{role}")
def api_org_chat_history(role: str, conv: str = None):
    """One conversation with a seat: the current one, or an earlier one (?conv=)."""
    import org_chat
    return _org_call(org_chat.history, role, conv or None)


@app.get("/api/org/chats")
def api_org_chats():
    """Per seat: messages in the current conversation, last message time and a preview."""
    import org_chat
    return _org_call(org_chat.chats)


@app.post("/api/org/chat/{role}/work-order")
def api_org_chat_work_order(role: str, conv: str = None):
    """Have the seat write down what was agreed in the current chat as a work order. It lands in
    the inbox; nothing runs until the CEO approves it and a Claude Code session runs `/work-order N`."""
    import org_chat
    return _org_call(org_chat.make_work_order, role, conv or None)


@app.post("/api/org/chat/{role}")
async def api_org_chat(role: str, request: Request):
    """One live chat turn with a seat: {"message": "...", "new": false}. The reply streams as
    server-sent events (delta / tool / done / error). A chat reads; it cannot change anything."""
    import org_chat
    from fastapi.responses import StreamingResponse
    body = await request.json()
    try:
        gen = org_chat.stream(role, body.get("message"), bool(body.get("new")), body.get("conv") or None)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    # text/event-stream is exempt from the gzip middleware, so chunks reach the browser as they are written
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/org/run")
async def api_org_run(request: Request):
    """Start a desk seat now ({"role": "cio"}) or every enabled desk seat ({"role": "all"})."""
    body = await request.json()
    result = api.org_run(str(body.get("role") or ""))
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.get("/api/org/running")
def api_org_running():
    return {"running": api.org_running()}


add_redirects(app, pages.REDIRECTS)


@app.get("/sql", response_class=HTMLResponse)
def sql_console(request: Request, table: str = None, q: str = None):
    """Read-only SQL query interface.

    Pre-fill via ?table=foo (SELECT * FROM foo LIMIT 20, auto-runs) or
    ?q=<verbatim query> (auto-runs — used by health drill-down links).
    """
    if q:
        initial_query = q
    elif table:
        initial_query = f"SELECT * FROM {table} LIMIT 20"
    else:
        initial_query = None
    return templates.TemplateResponse(request, "sql_console.html", {
        "page": "sql",
        "initial_query": initial_query,
    })


# ────────────── JSON API endpoints ──────────────

@app.get("/api/health/overview")
def api_health_overview():
    return api.get_health_overview()


@app.get("/api/health")
def api_health():
    return api.get_data_freshness()


@app.get("/api/pipeline")
def api_pipeline(days: int = 7):
    return api.get_pipeline_status(days=days)


@app.post("/api/pipeline/rerun/{step_name}")
def api_pipeline_rerun(step_name: str):
    """Trigger a single pipeline step in the background. Returns immediately."""
    from cockpit_ops.api import rerun_step
    result = rerun_step(step_name)
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.post("/api/sql")
async def api_sql(request: Request):
    """Execute a read-only SQL query and return JSON results."""
    import asyncio
    body = await request.json()
    query = body.get("query", "").strip()
    # async only to await the body; the query itself runs off the event loop.
    return await asyncio.to_thread(api.run_sql_query, query, max_rows=500)
