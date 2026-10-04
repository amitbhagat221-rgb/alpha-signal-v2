"""
Alpha Signal v2 — Ops cockpit (port 3001).

Standalone service for the Ops surface: Health Center, Pipeline status,
SQL console, Flow diagram, Command centre. Imports its API surface from
cockpit_ops/api.py, which depends only on cockpit/_shared.py (not cockpit/api.py).

The main trading cockpit on port 3000 continues to run independently.
You can restart this service to fix an Ops-only bug without touching
the trading cockpit.

Run: uvicorn cockpit_ops.app:app --host 0.0.0.0 --port 3001 --reload
Production: systemctl restart alpha-cockpit-ops
"""

import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from webauth import LoginRequired
from cockpit._shared import COCKPIT_STATIC, make_templates, nav_model, prewarm
from cockpit_ops import api, pages

OPS_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Alpha Signal Ops")
# Gzip every response > 1KB. /system is 1.2MB plaintext HTML and compresses
# to ~150KB; for users on WAN (especially the Bengaluru → Oracle Cloud round
# trip) this is the difference between 3-5s and sub-second download.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(LoginRequired, app_name="Ops console")  # webauth.py — password login (review F5)
# Shared static assets from the main cockpit. No need to duplicate CSS/JS.
app.mount("/static", StaticFiles(directory=COCKPIT_STATIC), name="static")

# Ops pages first, then cockpit/templates for the shared base.html /
# _components.html / _icons.html (single copies — the ops forks went stale).
templates = make_templates([OPS_DIR / "templates"],
                           nav=nav_model(pages.PAGES, pages.OTHER_APP, pages.BRAND))


# ────────────── Startup cache warmer ──────────────
# Same parallel-prewarm pattern as cockpit/app.py, but for Ops-only
# endpoints. Cuts cold start on /system from ~19s to first-render-ready.
@app.on_event("startup")
def _prewarm_cache():
    prewarm([
        ("data_freshness",     lambda: api.get_data_freshness()),
        ("db_summary",         lambda: api.get_db_summary()),
        ("data_health_scores", lambda: api.get_data_health_scores(force=False)),
        ("factor_health",      lambda: api.get_factor_health()),
        ("model_overview",     lambda: api.get_model_overview()),
        ("flow_overview",      lambda: api.get_flow_overview()),
        ("command_centre",     lambda: api.get_command_centre()),
        ("health_overview",    lambda: api.get_health_overview()),
        ("pipeline_status",    lambda: api.get_pipeline_status()),
        ("feed_overview",      lambda: api.get_feed_overview()),
    ], label="ops cache-warm")


# ────────────── Pages ──────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Ops landing page → redirect to Health Center."""
    return await system(request)


@app.get("/system", response_class=HTMLResponse)
async def system(request: Request, refresh: int = 0):
    """Health Center page. Pass ?refresh=1 to force a recompute."""
    # These calls are independent and each is individually cached, but on a cold
    # (cache-expired) load the slow ones — get_health_overview ~14s, freshness
    # ~7s, db_summary ~3s — ran serially (~24s). Fire them concurrently; the
    # data_health(cache_ttl) memo dedupes the freshness scan shared with
    # get_health_overview. Wall-clock collapses to the slowest single call.
    import asyncio

    async def _overview():
        try:
            return await asyncio.to_thread(api.get_health_overview)
        except Exception:
            import traceback; traceback.print_exc()
            return None

    pipeline, health, summary, health_scores, factor_health, overview = await asyncio.gather(
        asyncio.to_thread(api.get_pipeline_status),
        asyncio.to_thread(api.get_data_freshness),
        asyncio.to_thread(api.get_db_summary),
        asyncio.to_thread(api.get_data_health_scores, bool(refresh)),
        asyncio.to_thread(api.get_factor_health),
        _overview(),
    )

    from db import DOMAIN_ORDER
    by_domain: dict[str, list[dict]] = {}
    for row in health:
        by_domain.setdefault(row.get("domain") or "Other", []).append(row)
    inventory_groups = [
        {"domain": d, "rows": by_domain[d]}
        for d in DOMAIN_ORDER if d in by_domain
    ]

    return templates.TemplateResponse(request, "system.html", {
        "page": "system", "pipeline": pipeline, "health": health,
        "summary": summary, "health_scores": health_scores,
        "inventory_groups": inventory_groups,
        "factor_health": factor_health,
        "overview": overview,
    })


@app.get("/flow", response_class=HTMLResponse)
def flow_page(request: Request):
    overview = api.get_flow_overview()
    return templates.TemplateResponse(request, "flow.html", {
        "page": "flow", **overview,
    })


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
def org_page(request: Request, mfrom: str = None, mto: str = None, mrole: str = None):
    """Boardroom — the agent org (plan 0019): what is waiting for the CEO, the role
    tree with each seat's scorecard, the latest board pack and the desk memos.
    mfrom / mto / mrole: the Memos tab's date range and employee filter."""
    return templates.TemplateResponse(request, "org.html",
                                      {"page": "org", **api.get_org_overview(mfrom, mto, mrole)})


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
        return org.decide(int(body["item_id"]), body.get("verdict"), body.get("note"))
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


@app.get("/command", response_class=HTMLResponse)
def command_centre(request: Request):
    """Command centre — collapsible view of plans, factor library, data layer,
    pending actions. Updates whenever HANDOFF / plans / git change."""
    payload = api.get_command_centre()
    return templates.TemplateResponse(request, "command.html", {
        "page": "command", **payload,
    })


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
